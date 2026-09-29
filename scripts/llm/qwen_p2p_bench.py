#!/usr/bin/env python3
"""Repeatable, direct-backend Qwen throughput probe for Iggy's TP=2 service."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def request_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def prompt_tokens(endpoint: str, model: str, content: str) -> int:
    result = request_json(
        f"{endpoint}/tokenize", {"model": model, "prompt": content}, 120
    )
    if "count" in result:
        return result["count"]
    tokens = result.get("tokens", [])
    if not tokens:
        tokens = request_json(f"{endpoint}/tokenize", {"content": content}, 120)[
            "tokens"
        ]
    return len(tokens)


def build_prompt(endpoint: str, model: str, target: int) -> tuple[str, int]:
    # One shared prefix across requests exercises the same cache path as a
    # concurrent agent round. Numbered lines keep the synthetic context varied.
    block = "".join(
        f"Record {i:03d}: Describe compute scheduling, memory pressure, network "
        "latency, failure recovery, and evidence collection in a GPU service.\n"
        for i in range(50)
    )
    suffix = (
        "\nWrite a detailed technical briefing in prose about operating a two-GPU "
        "inference service. Cover scheduling, memory, communication, and "
        "recovery in at least twelve paragraphs. Use the context above as "
        "background and continue until the output limit.\n"
    )
    per_block = prompt_tokens(endpoint, model, block)
    count = max(1, round(target / per_block))
    measured = 0
    for _ in range(6):
        content = block * count + suffix
        measured = prompt_tokens(endpoint, model, content)
        if abs(measured - target) <= max(20, target // 500):
            return content, measured
        count = max(1, round(count * target / measured))
    return content, measured


def run_request(
    endpoint: str,
    model: str,
    prompt: str,
    request_id: int,
    barrier: threading.Barrier,
    max_tokens: int,
    timeout: float,
    seed: int,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Answer directly in prose. Do not call tools."},
            {"role": "user", "content": f"{prompt}\nSession {request_id}."},
        ],
        "max_tokens": max_tokens,
        "temperature": 0,
        "seed": seed + request_id,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    request = urllib.request.Request(
        f"{endpoint}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    barrier.wait()
    started = time.monotonic()
    first_token = None
    usage: dict[str, Any] = {}
    finish_reason = None
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for raw in response:
                line = raw.decode(errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                usage = chunk.get("usage") or usage
                for choice in chunk.get("choices") or []:
                    finish_reason = choice.get("finish_reason") or finish_reason
                    delta = choice.get("delta") or {}
                    if first_token is None and any(
                        delta.get(key)
                        for key in ("content", "reasoning", "reasoning_content", "tool_calls")
                    ):
                        first_token = time.monotonic()
        ended = time.monotonic()
        generated = usage.get("completion_tokens")
        if first_token is None or not generated:
            raise RuntimeError("stream ended without generated tokens")
        return {
            "request": request_id,
            "ok": True,
            "ttft_seconds": None if first_token is None else first_token - started,
            "total_seconds": ended - started,
            "usage": usage,
            "finish_reason": finish_reason,
            "decode_tps": (
                generated / (ended - first_token)
                if generated and first_token and ended > first_token
                else None
            ),
        }
    except Exception as error:  # Keep failed requests in the artifact.
        detail = str(error)
        if isinstance(error, urllib.error.HTTPError):
            detail += ": " + error.read().decode(errors="replace")[:1000]
        return {
            "request": request_id,
            "ok": False,
            "error": detail[:1200],
            "total_seconds": time.monotonic() - started,
        }


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:18020")
    parser.add_argument("--model", default="qwen3.8-27b")
    parser.add_argument("--target-prompt-tokens", type=int, default=40890)
    parser.add_argument("--concurrency", type=int, required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--seed", type=int, default=20260923)
    parser.add_argument("--cell", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    endpoint = args.endpoint.rstrip("/")
    prompt, count = build_prompt(endpoint, args.model, args.target_prompt_tokens)
    artifact: dict[str, Any] = {
        "cell": args.cell,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "endpoint": endpoint,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "prompt_tokens_by_tokenize": count,
        "target_prompt_tokens": args.target_prompt_tokens,
        "concurrency": args.concurrency,
        "repetitions": args.repetitions,
        "max_tokens": args.max_tokens,
        "seed": args.seed,
        "rounds": [],
    }
    for repetition in range(args.repetitions):
        barrier = threading.Barrier(args.concurrency)
        results: list[dict[str, Any] | None] = [None] * args.concurrency
        threads = [
            threading.Thread(
                target=lambda i=i: results.__setitem__(
                    i,
                    run_request(
                        endpoint,
                        args.model,
                        prompt,
                        i,
                        barrier,
                        args.max_tokens,
                        args.timeout,
                        args.seed + repetition * 1000,
                    ),
                )
            )
            for i in range(args.concurrency)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        artifact["rounds"].append({"repetition": repetition + 1, "requests": results})
        print(json.dumps(artifact["rounds"][-1]), flush=True)

    requests = [request for round_ in artifact["rounds"] for request in round_["requests"]]
    good = [request for request in requests if request and request["ok"]]
    summary = {"requests": len(requests), "successful": len(good)}
    for field in ("ttft_seconds", "total_seconds", "decode_tps"):
        values = [request[field] for request in good if request.get(field) is not None]
        summary[f"{field}_p50"] = statistics.median(values) if values else None
        summary[f"{field}_p95"] = percentile(values, 0.95)
    artifact["summary"] = summary
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)
    if len(good) != len(requests):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
