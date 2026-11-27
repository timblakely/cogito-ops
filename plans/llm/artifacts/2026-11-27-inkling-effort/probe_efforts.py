"""Bounded consumer-key probe; never print credentials or raw API responses."""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://litellm.llm.svc.cluster.local:4000"
EFFORTS = {
    "default": "0.9",
    "none": "0",
    "minimal": "0.1",
    "low": "0.2",
    "medium": "0.7",
    "high": "0.9",
    "xhigh": "0.99",
    "max": "0.99",
}


def numeric_answer(content):
    text = (content or "").strip()
    return text if re.fullmatch(r"0(?:\.\d+)?", text) else None


def request(key, effort, max_tokens):
    body = {
        "model": "inkling-deleuze",
        "messages": [{
            "role": "user",
            "content": 'Read the "Thinking effort level:" system message. '
                       "Reply with its numeric value only, without explanation.",
        }],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    if effort != "default":
        body["reasoning_effort"] = effort
    req = urllib.request.Request(
        BASE + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=240) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        return {"status": error.code, "error_bytes": len(error.read())}
    except Exception as error:
        return {"status": "transport_error", "error_type": type(error).__name__}
    choice = (result.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    usage = result.get("usage") or {}
    return {
        "status": 200,
        "model": result.get("model"),
        "reported_effort": numeric_answer(message.get("content")),
        "reasoning_characters": len(message.get("reasoning_content") or ""),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "finish_reason": choice.get("finish_reason"),
    }


def main():
    if "--self-test" in sys.argv:
        assert numeric_answer("0.99\n") == "0.99"
        assert numeric_answer("token-or-unexpected-output") is None
        assert numeric_answer("0.9 followed by anything") is None
        assert numeric_answer(None) is None
        assert EFFORTS["high"] == EFFORTS["default"]
        assert EFFORTS["max"] == EFFORTS["xhigh"]
        print("Probe self-test passed")
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--consumer", choices=("hermes", "opencode"), action="append")
    parser.add_argument("--effort", choices=tuple(EFFORTS), action="append")
    parser.add_argument("--max-tokens", type=int, default=1024)
    args = parser.parse_args()
    if not 1 <= args.max_tokens <= 2048:
        parser.error("--max-tokens must be between 1 and 2048")
    failed = False
    for consumer in args.consumer or ("hermes", "opencode"):
        key = Path("/etc/litellm/keys", consumer).read_text().strip()
        if not key:
            raise SystemExit("Empty key file for " + consumer)
        for effort in args.effort or EFFORTS:
            expected = EFFORTS[effort]
            result = request(key, effort, args.max_tokens)
            result.update(consumer=consumer, effort=effort, expected=expected)
            # Self-report is corroborating evidence, not proof of runtime rendering.
            result["matches_conditioning"] = (
                result.get("reported_effort") is not None
                and float(result["reported_effort"]) == float(expected)
            )
            print(json.dumps(result, sort_keys=True), flush=True)
            failed |= result["status"] != 200 or not result["matches_conditioning"]
            if result["status"] == 429:
                break
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
