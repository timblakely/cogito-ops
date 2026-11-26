# One-shot LiteLLM key-scope sync: additive only, refuses on any
# unexpected live state, prints no credential material.
#
# Modes: --self-test  pure-python checks, no network, no credential
#        --dry-run    reads /key/list + /key/info, POSTs nothing
#        (default)   read, verify, then POST /key/update per record
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://litellm.llm.svc.cluster.local:4000"
TOKEN_FILE = "/etc/litellm/admin/PROXY_MASTER_KEY"
MODE = sys.argv[1] if len(sys.argv) > 1 else "apply"

# Target scopes = what kubernetes/apps/llm/litellm/app/virtualkeys/
# {hermes,opencode}.yaml declare after this change ships. Kept as
# literals because a Job cannot read the git tree; artifacts/
# check_keyscope_proposal.py fails if these drift from the CRs.
TARGETS = [
    {
        "alias": "Hermes",
        "cr": "litellmvirtualkey/llm/hermes",
        "models": [
            "flashnext-deleuze", "glimmer-deleuze", "heretic-deleuze",
            "inkling-deleuze", "google/gemma-4-12b-it", "coder",
            "embedder", "reranker", "worker",
        ],
    },
    {
        "alias": "role-opencode",
        "cr": "litellmvirtualkey/llm/opencode",
        "models": [
            "flashnext-deleuze", "glimmer-deleuze", "heretic-deleuze",
            "inkling-deleuze", "google/gemma-4-12b-it",
        ],
    },
]

def read_token():
    with open(TOKEN_FILE) as f:
        tok = f.read().strip()
    if not tok:
        print("FATAL: admin credential file is empty", flush=True)
        sys.exit(1)
    return tok

def call(tok, path, payload=None):
    """GET when payload is None, else POST. Never logs headers,
    bodies, or anything from the response except parsed fields the
    caller prints by name."""
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        BASE + path, data=data, method="GET" if data is None else "POST",
        headers={"Authorization": "Bearer " + tok,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        # Only the literal model name is safe to echo; any body
        # could carry key material.
        return e.code, {"detail_len": len(body)}
    except Exception as e:
        return -1, {"error": type(e).__name__}

def page_count(status, body):
    """A 400/422 from /key/list returns no `keys`; reporting that as
    '0 keys' is the classic wrong verdict (SKILL.md pitfall)."""
    if status != 200 or "keys" not in body:
        print("FATAL: /key/list failed status=%s detail_len=%s"
              % (status, body.get("detail_len", body.get("error"))),
            flush=True)
        sys.exit(1)
    return body["keys"]

def find_records(tok, alias):
    """Return [(handle, live_models)] for records whose info.key_alias
    == alias. Matching is by alias only; the list entries are salted
    hashes, not sha256(token) (SKILL.md), so they are passed through
    untouched and never printed."""
    found = []
    page = 1
    while True:
        st, body = call(tok, "/key/list?page=%d&size=100" % page)
        entries = page_count(st, body)
        for ent in entries:
            h = ent if isinstance(ent, str) else (ent or {}).get("token")
            if not h:
                continue
            st2, rec = call(tok, "/key/info?key=" + urllib.parse.quote(str(h), safe=""))
            if st2 != 200:
                continue
            info = rec.get("info") or {}
            if (info.get("key_alias") or rec.get("key_alias")) != alias:
                continue
            models = info.get("models")
            if models is None:
                models = rec.get("models")
            if models is None:
                # Reading the wrong nesting yields [] and an update
                # would blank the scope. Refuse instead.
                print("FATAL: %s record has no readable info.models;"
                      " refusing to write" % alias, flush=True)
                sys.exit(1)
            handle = rec.get("key")
            if not handle:
                print("FATAL: %s record has no update handle" % alias,
                      flush=True)
                sys.exit(1)
            found.append((handle, sorted(models)))
        if len(entries) < 100:
            break
        page += 1
    return found

def plan(live_models, target):
    """(new_scope, add, extra) or None when the write must not run."""
    extra = sorted(set(live_models) - set(target))
    if extra:
        return None, [], extra
    if not live_models:
        # An empty live scope is an unexpected state, not a blank
        # canvas: filling it would grant nine models on a record
        # whose scope we cannot see. Refuse and report instead.
        return None, [], []
    add = sorted(set(target) - set(live_models))
    if not add:
        return None, [], []
    return list(target), add, []

def self_test():
    ok = True
    t = TARGETS[0]["models"]
    live8 = [m for m in t if m != "inkling-deleuze"]
    new, add, extra = plan(live8, t)
    ok &= new == t and add == ["inkling-deleuze"] and not extra
    # live scope carrying an undeclared grant -> refuse entirely
    new, add, extra = plan(live8 + ["someone-else-model"], t)
    ok &= new is None and extra == ["someone-else-model"]
    # already converged -> no write
    new, add, extra = plan(list(t), t)
    ok &= new is None and add == [] and not extra
    # an empty live scope is never auto-completed
    new, add, extra = plan([], t)
    ok &= new is None
    # a blanked target is never sent
    ok &= all(len(x["models"]) > 0 for x in TARGETS)
    # no model list is ever empty in a planned payload
    planned = plan(live8, t)[0]
    ok &= bool(planned) and set(live8) <= set(planned)
    print("SELF-TEST", "PASS" if ok else "FAIL", flush=True)
    sys.exit(0 if ok else 1)

def run():
    if MODE == "--self-test":
        self_test()
    if MODE not in ("--dry-run", "apply"):
        print("FATAL: unknown mode", MODE, flush=True)
        sys.exit(2)
    tok = read_token()
    changed = 0
    for tgt in TARGETS:
        recs = find_records(tok, tgt["alias"])
        if len(recs) != 1:
            print("SKIP %s: expected exactly 1 record, found %d"
                  % (tgt["alias"], len(recs)), flush=True)
            continue
        handle, live = recs[0]
        new, add, extra = plan(live, tgt["models"])
        print("%s: live=%d declared=%d" % (tgt["alias"], len(live),
                                              len(tgt["models"])),
              flush=True)
        if extra:
            print("  REFUSE: live scope carries %d model(s) the CR does"
                  " not declare: %s - resolve by hand, nothing written"
                  % (len(extra), ", ".join(extra)), flush=True)
            sys.exit(1)
        if new is None:
            print("  already correct, nothing to do", flush=True)
            continue
        print("  would add: %s" % ", ".join(add), flush=True)
        if MODE == "--dry-run":
            continue
        st, body = call(tok, "/key/update", {"key": handle, "models": new})
        if st != 200:
            print("  FAILED /key/update status=%s detail_len=%s"
                  % (st, body.get("detail_len", body.get("error"))),
                flush=True)
            sys.exit(1)
        # Read back and assert the union survived; the payload is
        # never trusted over the server's own answer.
        after = find_records(tok, tgt["alias"])
        if len(after) != 1 or not set(live) <= set(after[0][1]) \
                or not set(add) <= set(after[0][1]):
            print("  VERIFY FAILED: read-back scope does not contain the"
                  " previous scope plus the addition", flush=True)
            sys.exit(1)
        print("  updated and verified: %d models, previous %d preserved"
              % (len(after[0][1]), len(live)), flush=True)
        changed += 1
    print("KEY-SCOPE SYNC %s (records changed: %d)"
          % ("DRY RUN COMPLETE" if MODE == "--dry-run" else "DONE",
             changed), flush=True)

run()
