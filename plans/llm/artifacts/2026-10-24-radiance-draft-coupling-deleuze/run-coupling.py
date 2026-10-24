#!/usr/bin/env python3
"""Paired A/B of --draft-coupling on the Deleuze Radiance lane (1.12.0 both sides).

Same image digest on both sides: the only difference between the two bench pods is
the engine flag `--draft-coupling on`, so nothing but the drafter's sampling law
moves. Order is ABBA (off, on, on, off) so drift shows as within-variant spread.

Two things make this different from the version A/B:

  * Coupling is refused, not degraded. The arch declares the coupled planes only when
    the checkpoint carries the 2-bit candidate head (arch/qwen4exp_fp8/qwen4exp_fp8.cpp
    mtp_draft_head_q2 gate), and core/engine_draft.cpp refuses a program with no
    coupled planes. So a model that cannot couple does not serve uncoupled -- it stops.
    A cheap probe therefore runs first: bring the `on` pod up, read its startup log,
    tear it down. If it refuses, the suite is skipped and that is the result.

  * Fixed-seed tokens are NOT preserved (the engine says so at startup). So outputs
    differ by construction, which means the suite's wall times are only comparable
    through per-token rates (decode tok/s, prefill tok/s) and the token counts have to
    be reported alongside them. Draft acceptance is the mechanism being tested, so the
    engine's own counters are captured from /metrics at the end of every run.

The suite needs both R9700s, so the serving lane is suspended for the window.
Everything from `suspend` onward is undone in `finally`, including on SIGTERM.
"""
import hashlib
import json
import pathlib
import re
import signal
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[4]
HERE = pathlib.Path(__file__).resolve().parent
KUBECTL = "/home/tim/.local/share/mise/installs/kubectl/1.37.1/kubectl"
FLUX = "/home/tim/.local/share/mise/installs/aqua-fluxcd-flux2/2.7.3/flux"
K = [KUBECTL, "--kubeconfig", str(ROOT / "kubeconfig"), "--server=https://192.168.42.13:6443",
     "--request-timeout=20s", "-n", "llm"]
KS, LANE, BENCH = "llmkube-resources", "radiance", "radiance-bench-current"
CORPUS = pathlib.Path("/tmp/deleuze-radiance/aider-chat-history.md")
CORPUS_SHA = "a9a89dfd830af253103f86ff25dcba55364b22db779664d2fb36a3c2fd058710"
R112 = "sha256:9a90121be351ea1da9b99a944b7e92c43132a3513d1dff3a60c67f41fcfdb65f"
RUNS = [("a1-off", "off"), ("b1-on", "on"), ("b2-on", "on"), ("a2-off", "off")]
METRICS = ("short_warm_decode_tps", "short_warm_ttft_s", "long_median_ttft_s",
           "long_median_decode_tps", "long_median_wall_s", "long_completion_tokens",
           "pp8192_mean_tps", "pp32768_mean_tps", "pp65536_mean_tps", "c2_long_wall_s")
# radiance:<name> counters pulled from the bench pod's /metrics after each suite
COUNTERS = ("draft_tokens_total", "draft_accepted_total", "draft_acceptance_ratio",
            "draft_position_accepted_total", "draft_position_reached_total",
            "draft_refills_total", "draft_refill_tokens_total", "decode_tokens_total",
            "engine_steps_decode_total", "decode_rows_unspeculated_total",
            "decode_step_seconds_recent", "decode_tokens_per_second",
            "prefill_tokens_total", "prefill_tokens_per_second")
REFUSALS = ("--draft-coupling on requires", "declared no coupled MTP planes",
            "requires the linear serial draft chain")
LOG = HERE / "run-coupling.log"
STATE = {"started_utc": datetime.now(timezone.utc).isoformat(), "runs": []}


def log(message):
    line = f"[{datetime.now(timezone.utc):%H:%M:%S}] {message}"
    print(line, flush=True)
    with LOG.open("a") as handle:
        handle.write(line + "\n")


def sh(cmd, check=True, timeout=None):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode != 0:
        log(f"FAILED ({result.returncode}): {' '.join(map(str, cmd))}\n"
            f"{result.stdout[-500:]}{result.stderr[-800:]}")
        raise RuntimeError("command failed: " + " ".join(map(str, cmd)))
    return result


def pod_json(name):
    return json.loads(subprocess.check_output(K + ["get", "pod", name, "-o", "json"], text=True))


def pod_phase(name):
    try:
        pod = pod_json(name)
    except subprocess.CalledProcessError:
        return "absent", False
    statuses = pod["status"].get("containerStatuses", [])
    ready = any(cs.get("ready") for cs in statuses)
    phase = pod["status"].get("phase", "?")
    # a refused flag exits the process: report the container's own state, not just the pod phase
    for cs in statuses:
        state = cs.get("state", {})
        if "terminated" in state or "waiting" in state:
            why = state.get("terminated") or state.get("waiting") or {}
            if why.get("reason") in ("Error", "CrashLoopBackOff", "OOMKilled"):
                phase = f"{phase}:{why['reason']}"
    return phase, ready


def lane_pods(digest=None):
    out = json.loads(subprocess.check_output(K + ["get", "pods", "-o", "json"]))
    found = []
    for pod in out.get("items", []):
        name = pod["metadata"]["name"]
        if not name.startswith(LANE + "-") or name == BENCH:
            continue
        ready = any(cs.get("ready") for cs in pod["status"].get("containerStatuses", []))
        found.append((name, ready, pod["spec"]["containers"][0]["image"]))
    return [f for f in found if digest in f[2]] if digest else found


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
        for name, ready, _ in lane_pods(digest):
            if ready:
                return name
        time.sleep(5)
    return None


def http_through_forward(pod, port_local, paths):
    """GET each path from the pod via a throwaway port-forward; returns {path: text}."""
    forward = subprocess.Popen(K + ["port-forward", f"pod/{pod}", f"{port_local}:8080"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    got = {}
    try:
        time.sleep(5)
        for path in paths:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port_local}{path}", timeout=25) as r:
                    got[path] = r.read().decode()
            except Exception as exc:                                # noqa: BLE001
                got[path] = f"__error__ {exc}"
    finally:
        forward.terminate()
        forward.wait(timeout=10)
    return got


def parse_counters(text):
    """radiance:<name>{...} <value> -> {name: float} for the counters we care about."""
    found = {}
    for line in text.splitlines():
        match = re.match(r"^radiance:([a-z_]+)(?:\{[^}]*\})?\s+([-+0-9.eE]+)$", line.strip())
        if match and match.group(1) in COUNTERS:
            found[match.group(1)] = float(match.group(2))
    return found


def preflight():
    if hashlib.sha256(CORPUS.read_bytes()).hexdigest() != CORPUS_SHA:
        raise RuntimeError("pp corpus digest drifted; refusing to bench a different prompt")
    specs = {}
    for name, _ in RUNS:
        path = HERE / "profiles" / f"{name}.json"
        if not path.exists():
            raise RuntimeError(f"missing bench pod spec {path.name}")
        specs[name] = json.loads(path.read_text())
    args_off = list(specs["a1-off"]["spec"]["containers"][0]["args"])
    args_on = list(specs["b1-on"]["spec"]["containers"][0]["args"])
    at = args_on.index("--draft-coupling")
    if args_on[at + 1] != "on" or args_on[:at] + args_on[at + 2:] != args_off:
        raise RuntimeError("the two pod specs differ by more than the --draft-coupling flag")
    for other in ("a2-off", "b2-on"):
        if specs[other]["spec"]["containers"][0]["args"] != (args_off if other.endswith("off") else args_on):
            raise RuntimeError(f"{other} does not carry its arm's args exactly")
    images = {specs[n]["spec"]["containers"][0]["image"] for n in specs}
    if len(images) != 1 or R112 not in next(iter(images)):
        raise RuntimeError(f"pod images are not the single pinned 1.12.0 digest: {images}")
    pods = lane_pods()
    log("preflight ok: corpus digest matches, specs differ only by --draft-coupling, "
        f"single image, lane pods {pods}")
    if not any(p[1] and R112 in p[2] for p in pods):
        raise RuntimeError("the serving lane is not Ready on 1.12.0 -- nothing to compare against")


def probe_coupling():
    """Bring the `on` pod up and read its startup log. Returns (engaged, evidence)."""
    log("=== probe: does this checkpoint couple at all? ===")
    sh(K + ["delete", "pod", BENCH, "--ignore-not-found=true", "--wait=true"])
    sh(K + ["apply", "-f", str(HERE / "profiles" / "b1-on.json")])
    deadline, engaged, refusal = time.monotonic() + 420, False, None
    while time.monotonic() < deadline:
        phase, ready = pod_phase(BENCH)
        logs = sh(K + ["logs", BENCH, "--tail=600"], check=False).stdout
        if "MTP coupled LIVE" in logs:
            engaged = True
        for marker in REFUSALS:
            hits = [ln.strip() for ln in logs.splitlines()
                    if marker in ln and "[default]" not in ln and "[flag]" not in ln]
            if hits:
                refusal = hits[:2]
        if engaged and ready:
            break
        if refusal or phase in ("Failed", "Succeeded") or ":" in phase:
            break
        time.sleep(10)
    logs = sh(K + ["logs", BENCH, "--tail=1200"], check=False).stdout
    (HERE / "probe-on.log").write_text(logs)
    coupled_notes = [ln.strip() for ln in logs.splitlines()
                     if "MTP coupled" in ln or "draft" in ln.lower() and "head" in ln.lower()]
    sh(K + ["delete", "pod", BENCH, "--ignore-not-found=true", "--wait=true"], check=False)
    evidence = {"engaged": engaged, "refusal": refusal, "notes": coupled_notes[:8],
                "phase_at_exit": pod_phase(BENCH)[0]}
    log(f"probe: engaged={engaged} refusal={refusal} notes={coupled_notes[:3]}")
    return engaged, evidence


def restore():
    log("=== restoring the serving lane ===")
    sh(K + ["delete", "pod", BENCH, "--ignore-not-found=true", "--wait=true"], check=False)
    sh(K + ["patch", "inferenceservice", LANE, "--type=merge", "-p", '{"spec":{"suspend":false}}'],
       check=False)
    sh([FLUX, "-n", "llm", "resume", "kustomization", KS], check=False)
    sh([FLUX, "-n", "llm", "reconcile", "kustomization", KS, "--with-source", "--timeout", "8m"],
       check=False)
    pod = wait_lane_ready(R112, limit=600)
    STATE["restore"] = {"pod": pod}
    if pod:
        info = json.loads(http_through_forward(pod, 18099, ["/server_info"])["/server_info"])
        STATE["restore"]["server_info"] = {
            "version": info["server"]["version"], "max_model_len": info["server"]["max_model_len"],
            "max_num_seqs": info["server"]["max_num_seqs"]}
        log(f"lane back: {pod} version {info['server']['version']}")
    else:
        log(f"LANE NOT BACK -- check kubectl -n llm get pods,inferenceservice and 'flux resume "
            f"kustomization {KS} -n llm' by hand")
    health = subprocess.check_output(
        K + ["get", "kustomization", KS, "-o",
             "jsonpath={range .status.conditions[*]}{.type}={.status} {.reason};{end}"], text=True)
    log(f"KS {KS}: {health}")


def main():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit("SIGTERM"))
    signal.signal(signal.SIGINT, lambda *_: sys.exit("SIGINT"))
    preflight()
    outcome = "ran"
    try:
        log(f"suspending KS {KS} and the {LANE} lane (the bench pod needs both R9700s)")
        sh([FLUX, "-n", "llm", "suspend", "kustomization", KS, "--timeout", "5m"])
        sh(K + ["patch", "inferenceservice", LANE, "--type=merge", "-p", '{"spec":{"suspend":true}}'])
        if not wait_lane_gone():
            raise RuntimeError("the serving lane pod did not go away")
        log("lane down; GPUs free")
        engaged, evidence = probe_coupling()
        STATE["probe"] = evidence
        if not engaged:
            outcome = "unsupported"
            log(f"coupling refused on this checkpoint: {evidence['refusal'] or evidence['notes']} "
                f"-- skipping the suite")
            return
        for name, variant in RUNS:
            started = time.monotonic()
            log(f"=== {name} (coupling {variant}) : bringing up the bench pod ===")
            sh(K + ["delete", "pod", BENCH, "--ignore-not-found=true", "--wait=true"])
            sh(K + ["apply", "-f", str(HERE / "profiles" / f"{name}.json")])
            sh(K + ["wait", "--for=condition=Ready", f"pod/{BENCH}", "--timeout", "10m"])
            image = subprocess.check_output(
                K + ["get", "pod", BENCH, "-o",
                     "jsonpath={.status.containerStatuses[0].imageID}"], text=True)
            startup = sh(K + ["logs", BENCH, "--tail=1200"], check=False).stdout
            (HERE / f"{name}-startup-pre.log").write_text(startup)
            log(f"bench pod Ready; coupled lines: "
                f"{[ln.strip()[:90] for ln in startup.splitlines() if 'MTP coupled' in ln][:2]}")
            suite = subprocess.Popen(
                [sys.executable, str(HERE / "run-profile.py"), "--pod", BENCH, "--profile", name,
                 "--protocols", "common,decode,pp,c2", "--repetitions", "3",
                 "--corpus", str(CORPUS), "--smoke"])
            stop = threading.Event()

            def heartbeat():                       # counters mid-suite, in case the pod dies
                while not stop.wait(120):
                    got = http_through_forward(BENCH, 18098, ["/metrics"])
                    body = got.get("/metrics", "")
                    if body and not body.startswith("__error__"):
                        (HERE / f"{name}-metrics-mid.txt").write_text(body)

            beat = threading.Thread(target=heartbeat, daemon=True)
            beat.start()
            if suite.wait(timeout=2400) != 0:
                raise RuntimeError(f"run-profile.py failed for {name}")
            stop.set()
            got = http_through_forward(BENCH, 18099, ["/metrics", "/stats"])
            (HERE / f"{name}-metrics-post.txt").write_text(got.get("/metrics", ""))
            (HERE / f"{name}-stats-post.json").write_text(got.get("/stats", ""))
            counters = parse_counters(got.get("/metrics", ""))
            elapsed = round(time.monotonic() - started, 1)
            STATE["runs"].append({"profile": name, "variant": variant, "image": image.strip()[-24:],
                                  "wall_s": elapsed, "counters": counters,
                                  "utc": datetime.now(timezone.utc).isoformat()})
            log(f"{name} done in {elapsed}s; draft {counters.get('draft_accepted_total')}/"
                f"{counters.get('draft_tokens_total')} accepted "
                f"(ratio {counters.get('draft_acceptance_ratio')})")
    finally:
        restore()
        (HERE / "run-coupling-state.json").write_text(json.dumps(STATE, indent=2) + "\n")

    if outcome != "ran":
        log(f"DONE ({outcome})")
        return
    log("=== summarising ===")
    subprocess.run([sys.executable, str(HERE / "summarize.py")], cwd=str(HERE))
    rows = {r["profile"]: r for r in json.loads((HERE / "summary.json").read_text())}
    counters = {r["profile"]: r["counters"] for r in STATE["runs"]}
    comparison = {"order": [n for n, _ in RUNS], "flag": "--draft-coupling", "suite": {}, "counters": {}}
    for metric in METRICS:
        off = [rows[p][metric] for p, v in RUNS if v == "off" and rows.get(p, {}).get(metric) is not None]
        on = [rows[p][metric] for p, v in RUNS if v == "on" and rows.get(p, {}).get(metric) is not None]
        if not off or not on:
            continue
        mo, mn = statistics.mean(off), statistics.mean(on)
        comparison["suite"][metric] = {
            "off_runs": [round(x, 4) for x in off], "on_runs": [round(x, 4) for x in on],
            "mean_off": round(mo, 3), "mean_on": round(mn, 3),
            "delta_pct": round((mn - mo) / mo * 100, 2) if mo else None,
            "spread_off_pct": round((max(off) - min(off)) / mo * 100, 2) if len(off) > 1 else None,
            "spread_on_pct": round((max(on) - min(on)) / mn * 100, 2) if len(on) > 1 else None}
    for counter in COUNTERS:
        off = [counters[p][counter] for p, v in RUNS if v == "off" and counter in counters.get(p, {})]
        on = [counters[p][counter] for p, v in RUNS if v == "on" and counter in counters.get(p, {})]
        if not off or not on:
            continue
        mo, mn = statistics.mean(off), statistics.mean(on)
        comparison["counters"][counter] = {"off_runs": off, "on_runs": on, "mean_off": round(mo, 4),
                                           "mean_on": round(mn, 4),
                                           "delta_pct": round((mn - mo) / mo * 100, 2) if mo else None}
    # derived: what one accepted draft is worth, and the effective per-step token gain
    for side in ("off", "on"):
        steps = comparison["counters"].get("engine_steps_decode_total", {}).get(f"mean_{side}")
        tokens = comparison["counters"].get("decode_tokens_total", {}).get(f"mean_{side}")
        if steps and tokens:
            comparison["counters"].setdefault("derived_tokens_per_decode_step", {})[f"mean_{side}"] = round(
                tokens / steps, 4)
    comparison["noise_floor_note"] = ("within-variant spread between the two runs of each side is the "
                                      "paired noise floor; a delta smaller than that spread is not a "
                                      "result. Coupling changes the token stream itself, so wall times "
                                      "move with output length -- read tok/s, not wall.")
    (HERE / "comparison.json").write_text(json.dumps(comparison, indent=2) + "\n")
    print(json.dumps(comparison, indent=2), flush=True)
    log("DONE")


if __name__ == "__main__":
    main()
