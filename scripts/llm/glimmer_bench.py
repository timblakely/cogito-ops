#!/usr/bin/env python3
"""Drive repeatable concurrent llama.cpp chat-completion benchmarks."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def post_json(url: str, payload: dict[str, Any], timeout: float) -> Any:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def token_count(endpoint: str, content: str, timeout: float) -> int:
    result = post_json(
        f"{endpoint}/tokenize",
        {"content": content, "add_special": False},
        timeout,
    )
    return len(result["tokens"])


def build_prompt(endpoint: str, target_tokens: int, timeout: float) -> tuple[str, int]:
    if target_tokens < 64:
        prompt = "Summarize why reproducible benchmarks need controlled variables."
        return prompt, token_count(endpoint, prompt, timeout)

    unit = "Capacity measurement must preserve context, concurrency, and evidence. "
    per_unit = token_count(endpoint, unit, timeout)
    count = max(1, target_tokens // per_unit)
    prompt = unit * count
    measured = token_count(endpoint, prompt, timeout)

    # Tokenizers merge at boundaries, so converge using proportional corrections.
    for _ in range(5):
        if abs(measured - target_tokens) <= max(8, target_tokens // 1000):
            break
        count = max(1, round(count * target_tokens / measured))
        prompt = unit * count
        measured = token_count(endpoint, prompt, timeout)

    prompt += (
        "\nReturn exactly one sentence explaining which benchmark variables were "
        "held constant."
    )
    return prompt, token_count(endpoint, prompt, timeout)


def stream_request(
    endpoint: str,
    prompt: str,
    request_id: int,
    barrier: threading.Barrier,
    max_tokens: int,
    timeout: float,
    seed: int,
) -> dict[str, Any]:
    payload = {
        "model": "muse-glimmer-30b",
        "messages": [
            {
                "role": "system",
                "content": "Answer directly. Do not use tools. Reasoning strength: low.",
            },
            {"role": "user", "content": f"{prompt}\nRequest id: {request_id}."},
        ],
        "max_tokens": max_tokens,
        "seed": seed + request_id,
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    request = urllib.request.Request(
        f"{endpoint}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    barrier.wait()
    started = time.monotonic()
    first_token: float | None = None
    completion_tokens: int | None = None
    chunks = 0
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for raw_line in response:
                line = raw_line.decode(errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                usage = chunk.get("usage")
                if usage:
                    completion_tokens = usage.get("completion_tokens")
                choices = chunk.get("choices") or []
                delta = choices[0].get("delta", {}) if choices else {}
                if first_token is None and any(
                    delta.get(key) for key in ("content", "reasoning_content", "tool_calls")
                ):
                    first_token = time.monotonic()
                chunks += 1
        ended = time.monotonic()
        return {
            "request": request_id,
            "ok": True,
            "ttft_seconds": None if first_token is None else first_token - started,
            "total_seconds": ended - started,
            "completion_tokens": completion_tokens,
            "decode_tokens_per_second": (
                None
                if completion_tokens is None or first_token is None or ended <= first_token
                else completion_tokens / (ended - first_token)
            ),
            "chunks": chunks,
        }
    except urllib.error.HTTPError as error:
        return {
            "request": request_id,
            "ok": False,
            "status": error.code,
            "error": error.read().decode(errors="replace")[:2000],
            "total_seconds": time.monotonic() - started,
        }
    except Exception as error:  # noqa: BLE001 - the artifact must capture failures
        return {
            "request": request_id,
            "ok": False,
            "error": f"{type(error).__name__}: {error}",
            "total_seconds": time.monotonic() - started,
        }


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * fraction))
    return ordered[index]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:18080")
    parser.add_argument("--concurrency", type=int, required=True)
    parser.add_argument("--target-prompt-tokens", type=int, required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--seed", type=int, default=20260914)
    parser.add_argument("--cell", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    prompt, prompt_tokens = build_prompt(
        args.endpoint.rstrip("/"), args.target_prompt_tokens, args.timeout
    )
    rounds: list[dict[str, Any]] = []
    for repetition in range(args.repetitions):
        barrier = threading.Barrier(args.concurrency)
        results: list[dict[str, Any] | None] = [None] * args.concurrency
        threads = []
        for request_id in range(args.concurrency):
            thread = threading.Thread(
                target=lambda index=request_id: results.__setitem__(
                    index,
                    stream_request(
                        args.endpoint.rstrip("/"),
                        prompt,
                        index,
                        barrier,
                        args.max_tokens,
                        args.timeout,
                        args.seed + repetition * 1000,
                    ),
                )
            )
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()
        rounds.append({"repetition": repetition + 1, "requests": results})
        print(json.dumps(rounds[-1]), flush=True)

    flat = [request for round_ in rounds for request in round_["requests"]]
    successful = [request for request in flat if request and request["ok"]]
    ttft = [request["ttft_seconds"] for request in successful if request["ttft_seconds"]]
    total = [request["total_seconds"] for request in successful]
    decode = [
        request["decode_tokens_per_second"]
        for request in successful
        if request["decode_tokens_per_second"]
    ]
    artifact = {
        "cell": args.cell,
        "endpoint": args.endpoint,
        "concurrency": args.concurrency,
        "target_prompt_tokens": args.target_prompt_tokens,
        "actual_prompt_tokens": prompt_tokens,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "repetitions": args.repetitions,
        "max_tokens": args.max_tokens,
        "seed": args.seed,
        "summary": {
            "requests": len(flat),
            "successful": len(successful),
            "ttft_p50_seconds": statistics.median(ttft) if ttft else None,
            "ttft_p95_seconds": percentile(ttft, 0.95),
            "total_p50_seconds": statistics.median(total) if total else None,
            "total_p95_seconds": percentile(total, 0.95),
            "decode_tps_p50": statistics.median(decode) if decode else None,
            "decode_tps_p95": percentile(decode, 0.95),
        },
        "rounds": rounds,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2) + "\n")
    print(json.dumps(artifact["summary"], indent=2), flush=True)
    if len(successful) != len(flat):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
