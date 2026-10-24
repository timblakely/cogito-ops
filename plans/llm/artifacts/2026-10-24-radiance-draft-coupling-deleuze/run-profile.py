#!/usr/bin/env python3
"""Run the existing Iggy harnesses against a temporary, pinned Deleuze pod."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
KUBECTL = os.environ.get("KUBECTL", "/home/tim/.local/share/mise/installs/kubectl/1.37.1/kubectl")
K = [KUBECTL, "--kubeconfig", str(ROOT / "kubeconfig"),
     "--server=https://192.168.42.13:6443", "--request-timeout=20s", "-n", "llm"]


def capture(pod, output, phase):
    output.joinpath(f"{phase}-pod.json").write_bytes(subprocess.check_output(K + ["get", "pod", pod, "-o", "json"]))
    output.joinpath(f"{phase}-runtime.log").write_bytes(subprocess.check_output(K + ["logs", pod, "-c", "runtime"]))
    command = """b=/usr/bin/busybox
$b cat /proc/self/mountinfo /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.events
for d in /sys/class/drm/card[0-9]/device; do
  $b readlink -f "$d"
  for f in mem_info_vram_total mem_info_vram_used current_link_speed current_link_width; do
    $b cat "$d/$f"
  done
done
$b cat /sys/module/amdgpu/parameters/cwsr_enable
"""
    result = subprocess.run(K + ["exec", pod, "-c", "runtime", "--", "/bin/sh", "-c", command], capture_output=True)
    output.joinpath(f"{phase}-memory.txt").write_bytes(result.stdout + result.stderr)


def smoke(endpoint, output):
    common = {"model": "qwen3.8-flash-next", "temperature": 0, "max_tokens": 256,
              "reasoning_effort": "none", "chat_template_kwargs": {"enable_thinking": False}}
    arithmetic = [{"role": "user", "content": "Compute 17 * 23 + 19. Return a JSON object with the integer answer under key answer."}]
    tools = [{"type": "function", "function": {"name": "get_weather", "description": "Get the current weather for a city",
              "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}]
    cases = {
        "json_object": {"messages": arithmetic, "response_format": {"type": "json_object"}},
        "json_schema": {"messages": arithmetic, "response_format": {"type": "json_schema", "json_schema": {
            "name": "answer", "strict": True, "schema": {"type": "object", "properties": {"answer": {"type": "integer"}},
            "required": ["answer"], "additionalProperties": False}}}},
        "tool_auto": {"messages": [{"role": "user", "content": "Use get_weather to check the current weather in Denver."}],
                      "tools": tools, "tool_choice": "auto"},
    }
    results = {}
    for name, fields in cases.items():
        request = urllib.request.Request(endpoint + "/v1/chat/completions", data=json.dumps(common | fields).encode(),
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.load(response)
        message = result["choices"][0]["message"]
        if name.startswith("json"):
            passed = json.loads(message["content"]).get("answer") == 410
        else:
            passed = any(c.get("function", {}).get("name") == "get_weather" for c in message.get("tool_calls", []))
        results[name] = {"passed": passed, "response": result}
    output.joinpath("api-smoke.json").write_text(json.dumps(results, indent=2) + "\n")
    if not all(result["passed"] for result in results.values()):
        raise RuntimeError("API qualification failed; see api-smoke.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pod", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--protocols", default="common,decode,pp,c2")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--corpus", type=Path, default=Path("/tmp/deleuze-radiance/aider-chat-history.md"))
    parser.add_argument("--original", action="store_true", help="also repeat the October 5 single-sample cells")
    parser.add_argument("--smoke", action="store_true", help="check arithmetic JSON, strict schema and automatic tools")
    args = parser.parse_args()
    output = HERE / args.profile
    output.mkdir(exist_ok=True)
    with output.joinpath("port-forward.log").open("w") as log:
        forward = subprocess.Popen(K + ["port-forward", f"pod/{args.pod}", "18081:8080"], stdout=log, stderr=log)
        try:
            endpoint = "http://127.0.0.1:18081"
            deadline = time.monotonic() + 1800
            while True:
                try:
                    with urllib.request.urlopen(endpoint + "/health", timeout=3) as response:
                        if response.status == 200:
                            break
                except OSError:
                    pass
                if forward.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("runtime or port-forward did not become healthy")
                time.sleep(5)
            if not output.joinpath("startup-pod.json").exists():
                capture(args.pod, output, "startup")
            for route in ("/v1/models", "/server_info", "/stats"):
                if output.joinpath(route.rsplit("/", 1)[-1] + ".json").exists():
                    continue
                with urllib.request.urlopen(endpoint + route, timeout=30) as response:
                    output.joinpath(route.rsplit("/", 1)[-1] + ".json").write_bytes(response.read())
            try:
                with urllib.request.urlopen(endpoint + "/diagnostics", timeout=30) as response:
                    output.joinpath("diagnostics.json").write_bytes(response.read())
            except OSError:
                pass  # Older Radiance has no diagnostics route.
            if args.original:
                for concurrency in (1, 2):
                    for size, name in ((1512, "short"), (40890, "40k")):
                        cell = f"{args.profile}-original-c{concurrency}-{name}"
                        subprocess.run([sys.executable, str(ROOT / "scripts/llm/qwen_p2p_bench.py"),
                                        "--endpoint", endpoint, "--model", "qwen3.8-flash-next",
                                        "--concurrency", str(concurrency), "--repetitions", "1",
                                        "--target-prompt-tokens", str(size), "--max-tokens", "256",
                                        "--cell", cell,
                                        "--output", str(output / (cell + ".json"))], check=True)
            for protocol in args.protocols.split(","):
                if not protocol:
                    continue
                command = [sys.executable, str(ROOT / "scripts/llm/flashnext_public_bench.py"),
                           "--endpoint", endpoint, "--profile", args.profile,
                           "--protocol", protocol, "--thinking", "default",
                           "--repetitions", str(1 if protocol == "c2" else args.repetitions),
                           "--output", str(output / (protocol + ".json"))]
                if protocol == "pp":
                    command += ["--corpus", str(args.corpus)]
                with output.joinpath(protocol + ".log").open("w") as protocol_log:
                    subprocess.run(command, stdout=protocol_log, stderr=subprocess.STDOUT, check=True)
                print(json.dumps({"profile": args.profile, "completed": protocol}), flush=True)
            if args.smoke:
                smoke(endpoint, output)
            capture(args.pod, output, "final")
        finally:
            forward.terminate()
            forward.wait(timeout=10)


if __name__ == "__main__":
    main()
