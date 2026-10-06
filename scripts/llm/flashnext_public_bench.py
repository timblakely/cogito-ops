#!/usr/bin/env python3
"""Comparable cold-prefix PP and generation trials, retaining outputs and counters.

The public decode protocol is davetha/r9700-lru-expert-cache's ab3.py:
raw completions, greedy, three trials, 256/800/600 output caps. Its headline
rate includes prefill; we also retain streamed TTFT and decode-only throughput.
The PP protocol follows Dyluhn/R9V's pinned Aider corpus and 1K warmup,
10 x 8K/1 output, 3 x 32K/16, and 2 x 64K/16 procedure. PP is input/TTFT,
not a measurement of pure device prefill. Every trial has a leading nonce.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


CASES = [
    ("prose", "Write a detailed technical explanation of how a B-tree index works in a database.", 256),
    ("JSON", "Output a JSON array of 200 objects with fields id,name,category,price,in_stock. Only JSON.", 800),
    ("code", "Write a complete Python module implementing an LRU cache with TTL expiry, type hints and docstrings.", 600),
]


def post(endpoint, path, payload, timeout=1800):
    req = urllib.request.Request(endpoint + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def tokens(endpoint, model, prompt):
    with post(endpoint, "/tokenize", {"model": model, "prompt": prompt, "content": prompt}) as r:
        d = json.load(r)
    return int(d["count"]) if "count" in d else len(d["tokens"])


def fit(endpoint, model, prefix, corpus, target):
    low, high = 1, len(corpus)
    best, best_count = prefix, 0
    while low <= high:
        mid = (low + high) // 2
        candidate = prefix + corpus[:mid]
        count = tokens(endpoint, model, candidate)
        if abs(count-target) < abs(best_count-target):
            best, best_count = candidate, count
        if count == target:
            break
        if count < target:
            low = mid + 1
        else:
            high = mid - 1
    return best, best_count


def counters(endpoint):
    result = {}
    for path in ("/stats", "/metrics"):
        try:
            with urllib.request.urlopen(endpoint + path, timeout=10) as r:
                raw = r.read().decode()
            if path == "/stats":
                d = json.loads(raw)
                result["stats"] = {k: v for k, v in d.items() if k not in ("experts", "requests")}
            else:
                result["metrics"] = [line for line in raw.splitlines() if not line.startswith("#")
                                     and any(s in line for s in ("spec_decode", "prefix_cache", "prompt_tokens", "generation_tokens"))]
        except (OSError, ValueError):
            pass
    return result


def trial(endpoint, payload, label, barrier=None):
    before = counters(endpoint) if barrier is None else {}
    if barrier:
        barrier.wait()
    start = time.perf_counter()
    first = last = None
    text, reasoning, usage, finish = [], [], {}, None
    record = {"label": label, "prompt_sha256": hashlib.sha256(payload.get("prompt", json.dumps(payload.get("messages"))).encode()).hexdigest(),
              "payload_settings": {k: v for k, v in payload.items() if k not in ("prompt", "messages")}, "before": before}
    if barrier and "messages" in payload:
        # Retain the variable part so a concurrent request can be replayed alone.
        record["concurrency_nonce"] = payload["messages"][-1]["content"].splitlines()[0]
    try:
        route = "/v1/chat/completions" if "messages" in payload else "/v1/completions"
        with post(endpoint, route, {**payload, "stream": True, "stream_options": {"include_usage": True}}) as r:
            for raw in r:
                line = raw.decode().strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                usage = chunk.get("usage") or usage
                for c in chunk.get("choices") or []:
                    finish = c.get("finish_reason") or finish
                    delta = c.get("delta") or {}
                    part = c.get("text", delta.get("content", ""))
                    thought = delta.get("reasoning_content") or delta.get("reasoning") or ""
                    # For raw PP, an empty decoded token is still an output event.
                    if part or thought or "text" in c:
                        now = time.perf_counter()
                        if first is None:
                            first = now
                        last = now
                    text.append(part or "")
                    reasoning.append(thought)
        end = time.perf_counter()
        n = int(usage.get("completion_tokens", 0))
        if first is None or not n:
            raise RuntimeError("missing first output event or usage")
        record.update(ok=True, usage=usage, finish_reason=finish, ttft_s=first-start, wall_s=end-start,
                      pp_effective_tok_s=usage["prompt_tokens"]/(first-start),
                      generation_e2e_tok_s=n/(end-start),
                      decode_tok_s=(n-1)/(last-first) if n>1 and last>first else None,
                      legacy_decode_tok_s=n/(end-first) if n>1 and end>first else None,
                      text="".join(text), reasoning_text="".join(reasoning))
    except Exception as e:
        detail = str(e)
        if isinstance(e, urllib.error.HTTPError):
            detail += ": " + e.read().decode(errors="replace")[:2000]
        record.update(ok=False, error=detail, wall_s=time.perf_counter()-start)
    record["after"] = counters(endpoint) if barrier is None else {}
    return record


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--endpoint", required=True)
    p.add_argument("--model", default="qwen3.8-flash-next")
    p.add_argument("--profile", required=True)
    p.add_argument("--protocol", choices=("decode", "pp", "publisher-pp", "common", "c2"), required=True)
    p.add_argument("--corpus", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--repetitions", type=int, default=3)
    p.add_argument("--case", choices=("prose", "JSON", "code"), help="one public raw decode case")
    p.add_argument("--context-case", choices=("short", "long", "all"), default="all")
    p.add_argument("--thinking", choices=("default", "off"), default="off")
    p.add_argument("--llama-cache-off", action="store_true", help="llama.cpp's per-request cache control; other engines use server flags")
    p.add_argument("--ignore-eos", action="store_true", help="force the requested raw output cap; omit on runtimes without this extension")
    p.add_argument("--reset-prefix-cache", action="store_true", help="vLLM: clear and verify prefix cache before each matching chat repetition")
    args = p.parse_args()
    endpoint = args.endpoint.rstrip("/")
    artifact = {"profile": args.profile, "protocol": args.protocol, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "thinking": args.thinking if args.protocol in ("common", "c2") else "raw completion; no chat template", "trials": []}
    if args.reset_prefix_cache:
        artifact["cache_control"] = "verified reset_prefix_cache before each matching chat repetition"
    settings = {"model": args.model, "temperature": 0, "seed": 7}
    if args.llama_cache_off:
        settings["cache_prompt"] = False
    if args.thinking == "off" and args.protocol in ("common", "c2"):
        settings.update(reasoning_effort="none", chat_template_kwargs={"enable_thinking": False})

    def save(records):
        artifact["trials"].extend(records)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temp = args.output.with_suffix(".tmp")
        temp.write_text(json.dumps(artifact, indent=2) + "\n")
        temp.replace(args.output)
        for r in records:
            print(json.dumps({k:v for k,v in r.items() if k not in ("before", "after", "text", "reasoning_text", "payload_settings")}), flush=True)

    if args.protocol == "decode":
        for label, prompt, cap in CASES:
            if args.case and label != args.case:
                continue
            for i in range(args.repetitions):
                payload = {**settings, "prompt": prompt, "max_tokens": cap}
                if args.ignore_eos:
                    payload["ignore_eos"] = True
                result = trial(endpoint, payload, f"{label}-{i+1}")
                result["requested_output_tokens"] = cap
                result["output_cap_reached"] = result.get("usage", {}).get("completion_tokens") == cap
                save([result])
    elif args.protocol == "publisher-pp":
        if args.corpus is None:
            p.error("--corpus is required for publisher-pp")
        corpus = args.corpus.read_text()
        artifact["corpus_sha256"] = hashlib.sha256(args.corpus.read_bytes()).hexdigest()
        # Radiance's fnpf.sh uses four bytes per target token, a warmup and
        # three measured repetitions. Its published rate includes the response.
        for size in (8192, 32768, 65536):
            repeated = corpus * (size * 4 // len(corpus) + 1)
            for i in range(args.repetitions + 1):
                prompt = f"request {i} {time.time_ns()}\n\n" + repeated[:size*4]
                result = trial(endpoint, {**settings, "prompt": prompt, "max_tokens": 1}, f"publisher-pp{size}-{'warm' if i == 0 else i}")
                if result["ok"]:
                    result["publisher_pp_tok_s"] = result["usage"]["prompt_tokens"] / result["wall_s"]
                save([result])
    elif args.protocol == "pp":
        if args.corpus is None:
            p.error("--corpus is required for pp")
        corpus = args.corpus.read_text()
        digest = hashlib.sha256(args.corpus.read_bytes()).hexdigest()
        if digest != "a9a89dfd830af253103f86ff25dcba55364b22db779664d2fb36a3c2fd058710":
            raise ValueError("PP corpus differs from the pinned public Aider corpus")
        artifact["corpus_sha256"] = digest
        for size, runs, cap, pause in ((1024,1,1,0),(8192,10,1,1),(32768,3,16,2),(65536,2,16,2)):
            for i in range(runs):
                prefix = f"benchmark {args.profile} {size} {i} {time.time_ns()}\n"
                offset = i*len(corpus)//runs
                rotated = corpus[offset:]+corpus[:offset]
                prompt, count = fit(endpoint, args.model, prefix, rotated, size)
                payload = {**settings, "prompt": prompt, "max_tokens": cap}
                if args.ignore_eos:
                    payload["ignore_eos"] = True
                result = trial(endpoint, payload, f"pp{size}-{i+1}")
                result["tokens_by_tokenize"] = count
                save([result])
                time.sleep(pause)
    else:
        from qwen_p2p_bench import build_prompt
        sizes = {"short": (1500,), "long": (40890,), "all": (1500, 40890)}[args.context_case]
        for size in sizes:
            prompt, count = build_prompt(endpoint, args.model, size)
            n = 2 if args.protocol == "c2" else 1
            for repetition in range(args.repetitions):
                if args.reset_prefix_cache:
                    for attempt in range(5):
                        with post(endpoint, "/reset_prefix_cache", {}) as r:
                            cleared = json.load(r).get("success") is True
                        if cleared:
                            break
                        time.sleep(0.1)
                    if not cleared:
                        raise RuntimeError("prefix-cache reset failed; excluding cached comparison")
                barrier = threading.Barrier(n) if n>1 else None
                results = [None]*n
                workers = []
                for i in range(n):
                    # Leading nonce prevents sharing cached context across C2 requests.
                    user = prompt+f"\nSession {i}."
                    if args.protocol == "c2":
                        user = f"independent {i} {repetition} {time.time_ns()}\n"+user
                    payload = {**settings, "messages": [{"role":"system","content":"Answer directly in prose. Do not call tools."},
                                                            {"role":"user","content":user}], "max_tokens":256}
                    worker = threading.Thread(target=lambda i=i,payload=payload: results.__setitem__(i,trial(endpoint,payload,f"common{size}-{repetition+1}-{i}",barrier)))
                    workers.append(worker)
                for w in workers:
                    w.start()
                for w in workers:
                    w.join()
                for result in results:
                    result["base_prompt_sha256"] = hashlib.sha256(prompt.encode()).hexdigest()
                    result["base_prompt_tokens"] = count
                save(results)
    failed = [r for r in artifact["trials"] if not r["ok"]]
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
