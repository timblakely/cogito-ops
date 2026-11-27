"""Reconcile only the existing role-opencode concurrency limit; log no keys."""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "http://litellm.llm.svc.cluster.local:4000"
PRESERVE = ("models", "max_budget", "budget_duration", "rpm_limit", "tpm_limit")


def call(token, path, payload=None, allow_not_found=False):
    request = urllib.request.Request(
        BASE + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404 and allow_not_found:
            return None
        raise SystemExit("API request failed: HTTP " + str(error.code)) from None
    except Exception as error:
        raise SystemExit("API request failed: " + type(error).__name__) from None


def validate(record):
    info = record.get("info") or {}
    if info.get("key_alias") != "role-opencode":
        raise ValueError("Unexpected key alias; refusing update")
    if info.get("max_parallel_requests") not in (4, 8):
        raise ValueError("Unexpected concurrency limit; refusing update")
    if not record.get("key") or not info.get("models"):
        raise ValueError("Missing key handle or scope; refusing update")
    return info


def find_record(admin):
    """Fallback for proxy versions without /key/info/self; handles stay in-pod."""
    found = []
    for page in range(1, 11):
        listing = call(admin, "/key/list?page=%d&size=100" % page)
        entries = listing.get("keys")
        if not isinstance(entries, list):
            raise SystemExit("Unreadable key listing; refusing update")
        for entry in entries:
            handle = entry if isinstance(entry, str) else entry.get("token")
            if not handle:
                raise SystemExit("Unreadable key handle; refusing update")
            record = call(admin, "/key/info?key=" + urllib.parse.quote(handle, safe=""))
            if (record.get("info") or {}).get("key_alias") == "role-opencode":
                found.append(record)
        if len(entries) < 100:
            break
    else:
        raise SystemExit("Key listing exceeds bounded lookup; refusing update")
    if len(found) != 1:
        raise SystemExit("Expected exactly one role-opencode key; refusing update")
    return found[0]


def main():
    if "--self-test" in sys.argv:
        good = {"key": "test-handle", "info": {
            "key_alias": "role-opencode", "max_parallel_requests": 4,
            "models": ["inkling-deleuze"],
        }}
        assert validate(good)["max_parallel_requests"] == 4
        for alias, limit in (("other", 4), ("role-opencode", 100)):
            try:
                validate({"key": "test", "info": {
                    "key_alias": alias, "max_parallel_requests": limit,
                    "models": ["inkling-deleuze"],
                }})
            except ValueError:
                pass
            else:
                raise AssertionError("Unsafe update accepted")
        print("Concurrency sync self-test passed")
        return
    consumer = Path("/credentials/opencode").read_text().strip()
    admin = Path("/credentials/admin").read_text().strip()
    if not consumer or not admin:
        raise SystemExit("Empty credential file; refusing update")
    record = call(consumer, "/key/info/self", allow_not_found=True)
    if record is None:
        record = find_record(admin)
    before = validate(record)
    handle = record["key"]
    if before["max_parallel_requests"] == 4:
        call(admin, "/key/update", {"key": handle, "max_parallel_requests": 8})
    after_record = call(admin, "/key/info?key=" + urllib.parse.quote(handle, safe=""))
    after = validate(after_record)
    unchanged = all(before.get(field) == after.get(field) for field in PRESERVE)
    passed = after["max_parallel_requests"] == 8 and unchanged
    print(json.dumps({
        "alias": "role-opencode",
        "before": before["max_parallel_requests"],
        "after": after["max_parallel_requests"],
        "scope_budget_rate_limits_unchanged": unchanged,
        "passed": passed,
    }), flush=True)
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        raise SystemExit(str(error)) from None
