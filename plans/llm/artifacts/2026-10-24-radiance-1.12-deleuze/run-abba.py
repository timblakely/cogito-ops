#!/usr/bin/env python3
"""Paired A/B of the Deleuze Radiance suite: 1.11.0 control vs 1.12.0 candidate.

Order is ABBA (control, candidate, candidate, control) so thermal or drift effects
show up as within-variant spread instead of masquerading as a version effect -- the
plan doc warns that cross-run comparisons are only valid with an identical
procedure, and the 1.11 run was never paired with a same-session control.

The suite needs both R9700s, so the serving lane is suspended for the whole window
(that is also the agent's own model). Everything from `suspend` onward is undone in
`finally`, including on SIGTERM. Same flags as the 1.11 run: protocols
common,decode,pp,c2, three repetitions, --smoke, no --original.
"""
import hashlib
import json
import pathlib
import signal
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[4]
HERE = pathlib.Path(__file__).resolve().parent
KUBECTL = "/home/tim/.local/share/mise/installs/kubectl/1.37.1/kubectl"
FLUX = "/home/tim/.local/share/mise/installs/aqua-fluxcd-flux2/2.7.3/flux"
K = [KUBECTL, "--kubeconfig", str(ROOT / "kubeconfig"), "--server=https://192.168.42.13:6443",
     "--request-timeout=20s", "-n", "llm"]
KS, LANE = "llmkube-resources", "radiance"
CORPUS = pathlib.Path("/tmp/deleuze-radiance/aider-chat-history.md")
CORPUS_SHA = "a9a89dfd830af253103f86ff25dcba55364b22db779664d2fb36a3c2fd058710"
R112 = "sha256:9a90121be351ea1da9b99a944b7e92c43132a3513d1dff3a60c67f41fcfdb65f"
RUNS = [("ab-a1-r111", "1.11.0"), ("ab-b1-r112", "1.12.0"),
        ("ab-b2-r112", "1.12.0"), ("ab-a2-r111", "1.11.0")]
METRICS = ("short_warm_decode_tps", "short_warm_ttft_s", "long_median_ttft_s",
           "long_median_decode_tps", "long_median_wall_s", "pp8192_mean_tps",
           "pp32768_mean_tps", "pp65536_mean_tps", "c2_long_wall_s")
LOG = HERE / "run-abba.log"
STATE = {"started_utc": datetime.now(timezone.utc).isoformat(), "steps": [], "runs": []}


def log(message):
    line = f"[{datetime.now(timezone.utc):%H:%M:%S}] {message}"
    print(line, flush=True)
    with LOG.open("a") as handle:
        handle.write(line + "\n")


def sh(cmd, check=True, timeout=None):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode != 0:
        log(f"FAILED ({result.returncode}): {' '.join(map(str, cmd))}\n{result.stdout[-500:]}{result.stderr[-800:]}")
        raise RuntimeError("command failed: " + " ".join(map(str, cmd)))
    return result


def lane_pods(digest=None):
    out = json.loads(subprocess.check_output(K + ["get", "pods", "-o", "json"]))
    found = []
    for pod in out.get("items", []):
        name = pod["metadata"]["name"]
        if not name.startswith(LANE + "-"):
            continue
        ready = any(cs.get("ready") for cs in pod["status"].get("containerStatuses", []))
        image = pod["spec"]["containers"][0]["image"]
        found.append((name, ready, image))
    if digest:
        found = [f for f in found if digest in f[2]]
    return found


def wait_lane_gone(limit=300):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        if not lane_pods():
            return True
        time.sleep(5)
    return False


def wait_lane_ready(digest, limit=600):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        for name, ready, image in lane_pods(digest):
            if ready:
                return name
        time.sleep(5)
    return None


def server_info(pod):
    forward = subprocess.Popen(K + ["port-forward", f"pod/{pod}", "18099:8080"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(5)
        with urllib.request.urlopen("http://127.0.0.1:18099/server_info", timeout=20) as response:
            return json.load(response)
    finally:
        forward.terminate()
        forward.wait(timeout=10)


def preflight():
    if hashlib.sha256(CORPUS.read_bytes()).hexdigest() != CORPUS_SHA:
        raise RuntimeError("pp corpus digest drifted; refusing to bench against a different prompt")
    for name, _ in RUNS:
        path = HERE / "profiles" / f"{name}.json"
        if not path.exists():
            raise RuntimeError(f"missing bench pod spec {path.name}")
    args = {tuple(json.loads((HERE / "profiles" / f"{n}.json").read_text())
                      ["spec"]["containers"][0]["args"]) for n, _ in RUNS}
    if len(args) != 1:
        raise RuntimeError("the four bench pod specs do not carry identical engine args")
    pods = lane_pods()
    log(f"preflight ok: corpus digest matches, 4 pod specs identical except image, lane pods {pods}")
    if not any(p[1] and R112 in p[2] for p in pods):
        raise RuntimeError("the serving lane is not Ready on 1.12.0 -- nothing to compare against")


def restore():
    log("=== restoring the serving lane ===")
    sh(K + ["delete", "pod", "radiance-bench-current", "--ignore-not-found=true", "--wait=true"], check=False)
    sh(K + ["patch", "inferenceservice", LANE, "--type=merge", "-p", '{"spec":{"suspend":false}}'], check=False)
    sh([FLUX, "-n", "llm", "resume", "kustomization", KS], check=False)
    sh([FLUX, "-n", "llm", "reconcile", "kustomization", KS, "--with-source", "--timeout", "8m"], check=False)
    pod = wait_lane_ready(R112, limit=600)
    STATE["restore"] = {"pod": pod}
    if pod:
        info = server_info(pod)
        STATE["restore"]["server_info"] = {"version": info["server"]["version"],
                                           "max_model_len": info["server"]["max_model_len"],
                                           "max_num_seqs": info["server"]["max_num_seqs"]}
        (HERE / "restored-lane-pod.json").write_text(json.dumps(
            json.loads(subprocess.check_output(K + ["get", "pod", pod, "-o", "json"])), indent=2) + "\n")
        log(f"lane back: {pod} version {info['server']['version']}")
    else:
        log("LANE NOT BACK -- check kubectl -n llm get pods,inferenceservice and 'flux resume kustomization "
            f"{KS} -n llm' by hand")
    health = subprocess.check_output(
        K + ["get", "kustomization", KS, "-o",
             "jsonpath={range .status.conditions[*]}{.type}={.status} {.reason};{end}"], text=True)
    log(f"KS {KS}: {health}")


def main():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit("SIGTERM"))
    signal.signal(signal.SIGINT, lambda *_: sys.exit("SIGINT"))
    preflight()
    try:
        log(f"suspending KS {KS} and the {LANE} lane (both R9700s are needed by the bench pod)")
        sh([FLUX, "-n", "llm", "suspend", "kustomization", KS, "--timeout", "5m"])
        sh(K + ["patch", "inferenceservice", LANE, "--type=merge", "-p", '{"spec":{"suspend":true}}'])
        if not wait_lane_gone():
            raise RuntimeError("the serving lane pod did not go away")
        log("lane down; GPUs free")
        for name, version in RUNS:
            started = time.monotonic()
            log(f"=== {name} ({version}) : bringing up the bench pod ===")
            sh(K + ["delete", "pod", "radiance-bench-current", "--ignore-not-found=true", "--wait=true"])
            sh(K + ["apply", "-f", str(HERE / "profiles" / f"{name}.json")])
            sh(K + ["wait", "--for=condition=Ready", "pod/radiance-bench-current", "--timeout", "10m"])
            image = subprocess.check_output(
                K + ["get", "pod", "radiance-bench-current", "-o",
                     "jsonpath={.status.containerStatuses[0].imageID}"], text=True).strip()
            log(f"bench pod Ready on {image[-24:]}")
            sh([sys.executable, str(HERE / "run-profile.py"), "--pod", "radiance-bench-current",
                "--profile", name, "--protocols", "common,decode,pp,c2", "--repetitions", "3",
                "--corpus", str(CORPUS), "--smoke"], timeout=2400)
            elapsed = round(time.monotonic() - started, 1)
            STATE["runs"].append({"profile": name, "version": version, "image": image,
                                  "wall_s": elapsed, "utc": datetime.now(timezone.utc).isoformat()})
            log(f"{name} done in {elapsed}s")
    finally:
        restore()
        (HERE / "run-abba-state.json").write_text(json.dumps(STATE, indent=2) + "\n")

    log("=== summarising ===")
    table = subprocess.run([sys.executable, str(HERE / "summarize.py")], cwd=str(HERE),
                           capture_output=True, text=True)
    print(table.stdout, flush=True)
    rows = {r["profile"]: r for r in json.loads((HERE / "summary.json").read_text())}
    comparison = {"order": [n for n, _ in RUNS], "metrics": {}}
    for metric in METRICS:
        a = [rows[p].get(metric) for p, v in RUNS if v == "1.11.0" and rows.get(p, {}).get(metric) is not None]
        b = [rows[p].get(metric) for p, v in RUNS if v == "1.12.0" and rows.get(p, {}).get(metric) is not None]
        if not a or not b:
            continue
        ma, mb = statistics.mean(a), statistics.mean(b)
        comparison["metrics"][metric] = {
            "r111_runs": a, "r112_runs": b, "mean_1.11.0": round(ma, 3), "mean_1.12.0": round(mb, 3),
            "delta_pct": round((mb - ma) / ma * 100, 2),
            "within_1.11_spread_pct": (round((max(a) - min(a)) / ma * 100, 2) if len(a) > 1 else None),
            "within_1.12_spread_pct": (round((max(b) - min(b)) / mb * 100, 2) if len(b) > 1 else None)}
    comparison["noise_floor_note"] = ("within-variant spread between the two runs of each version is the "
                                      "paired noise floor; a delta smaller than that spread is not a result")
    (HERE / "comparison.json").write_text(json.dumps(comparison, indent=2) + "\n")
    print(json.dumps(comparison, indent=2), flush=True)
    log("DONE")


if __name__ == "__main__":
    main()
