#!/usr/bin/env python3
"""Offline gate for the Deleuze fleet file: every key this build must accept.

`radiance --check` is the gate that runs in the cluster; this is the gate that
runs HERE, where no image can be pulled and no weight staged. It mirrors the
engine's own acceptance rules, read from core/fleet/config.cpp at a tag, against
the ConfigMap bytes in kubernetes/apps/llm/llmkube/resources/radiance-deleuze.yaml:

    top level        kTopKeys
    server:          kServerKeys + "log"
    memory:          kMemoryFlagKeys + host-mib, disk-tier, card-headroom-mib,
                     and at 2.3.0 also pinned-numa-node (#580) and queue-reserve (#589)
    scheduler:       load-timeout, drain-timeout, keepalive, stuck-exit, warm-up
    cards:           "all" or a list of distinct 0..63
    defaults /
    models.<name>:   every flag in core/config.cpp's table EXCEPT the kServerKeys
                     ones (Reader::misplaced refuses those at model level), plus the
                     three kMemoryFlagKeys (allowed at model level on purpose: that
                     is how models sharing a card divide it), plus kModelFleetKeys
                     {aliases, priority, pin, ttl, flex, park, cards} minus the two
                     refused under defaults.
    groups.<name>:   exactly one of together:/exclusive:, >= 2 distinct model names

and it re-checks the claims this change rests on:

  * every key of the NEW five-entry file is accepted at v2.3.0;
  * every key of the OLD four-entry file (the bytes live on the cluster today,
    sha256 recorded in the change note) was accepted at v2.2.0 and is STILL
    accepted at v2.3.0 - the "no fleet key was removed" claim, checked key by
    key rather than asserted;
  * the only keys 2.3.0 adds at the memory level are the two named above, and
    neither is set in this file, so the lane's memory arithmetic is untouched;
  * inkling-2-mini's own keys are all model-level keys at 2.3.0, and
    `arch/inkling2` does not exist at v2.2.0 (which is why the engine bump is
    required, not cosmetic);
  * the groups' member names all resolve to a declared entry, no duplicates, and
    the exclusive group contains every text entry that wants both cards.

Usage: python3 check_fleet_keys.py [tag_under_test]   (default v2.3.0)
Exits non-zero if any key would be refused.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]
# The upstream radiance checkout at the tags named in TAGS: this check reads
# key acceptance out of core/fleet/config.cpp, so it needs the source, not a
# summary of it. Point RADIANCE_SRC at any clone that has those tags.
SRC = Path(os.environ.get("RADIANCE_SRC")
           or "/tmp/opencode/radiance-230/radiance-src")
LANE = ROOT / "kubernetes/apps/llm/llmkube/resources/radiance-deleuze.yaml"
TAGS = ("v2.2.0", "v2.3.0")
TESTED = sys.argv[1] if len(sys.argv) > 1 else "v2.3.0"

fails = []


def ok(msg):
    print("PASS:", msg)


def bad(msg):
    fails.append(msg)
    print("FAIL:", msg)


def git(*args):
    r = subprocess.run(["git", *args], cwd=SRC, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("git %s failed: %s" % (" ".join(args), r.stderr.strip()))
    return r.stdout


def jj_show(rev, path):
    """Read a file from a cogito revision, with jj (this repo's VCS)."""
    r = subprocess.run(["jj", "file", "show", "-r", rev, "--", path],
                       cwd="/workspace/cogito", capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("jj file show %s %s failed: %s" % (rev, path, r.stderr.strip()))
    return r.stdout


def tables(tag):
    """The literal key tables from core/fleet/config.cpp at `tag`."""
    src = git("show", "%s:core/fleet/config.cpp" % tag)

    def table(name):
        m = re.search(r"const char\* const %s\[\]\s*=\s*\{(.*?)\};" % name, src, re.S)
        return set(re.findall(r'"([^"]+)"', m.group(1))) if m else set()

    m = re.search(r'is not a scheduler key"?\s*\+?\s*suggest\(k,\s*\{([^}]*)\}\)', src, re.S)
    sched = {s.strip().strip('"') for s in m.group(1).replace("\n", " ").split(",")} if m else set()
    mem_extra = set(re.findall(r'valid\.push_back\("([^"]+)"\)',
                               src[src.index("int Reader::read_memory"):
                                   src.index("int Reader::read_scheduler")]))
    return {
        "top": table("kTopKeys"),
        "server": table("kServerKeys") | {"log"},
        "memory": table("kMemoryFlagKeys") | mem_extra,
        "scheduler": sched or {"load-timeout", "drain-timeout", "keepalive",
                               "stuck-exit", "warm-up"},
        "model_fleet": table("kModelFleetKeys"),
        # Options with no YAML key: refused with their own message.
        "replaced": set(re.findall(r'\{\s*"([a-z-]+)",\s*"', src[src.index("kReplaced[]"):
                                                               src.index("kRepeatable")])),
    }


def flag_names(tag):
    """Model option names from core/config.cpp's flag table: the `--flag` strings."""
    src = git("show", "%s:core/config.cpp" % tag)
    # The table rows look like { "--max-model-len", "INT", ... }
    names = set(re.findall(r'\{\s*"--([a-z0-9-]+)"\s*,', src))
    names |= set(re.findall(r'\{\s*"--([a-z0-9-]+)"\s*,\s*nullptr', src))
    return names


def model_keys(tag, t, flags):
    """Reader::model_key_names() at model level; defaults drop aliases + cards."""
    return ({f for f in flags if f not in t["server"]}
            | t["model_fleet"])


def load_fleet(path, label):
    docs = [d for d in yaml.safe_load_all(path.read_text()) if d]
    cm = next(d for d in docs if d.get("kind") == "ConfigMap"
              and d["metadata"]["name"] == "radiance-fleet-config")
    text = cm["data"]["radiance.yaml"]
    doc = yaml.safe_load(text)
    print("%s: %d B, sha256 %s" % (label, len(text),
                                   __import__("hashlib").sha256(text.encode()).hexdigest()))
    return doc


def check_keys(doc, tag, t, flags, where="file under test"):
    """Every key path in the file, accepted or refused at `tag`."""
    mk = model_keys(tag, t, flags)
    bad_keys = []
    for top, val in doc.items():
        if top not in t["top"]:
            bad_keys.append("<top>.%s" % top)
            continue
        if top in ("server", "memory", "scheduler"):
            allowed = t[top]
            for k in (val or {}):
                if k not in allowed:
                    bad_keys.append("%s.%s" % (top, k))
        elif top == "models":
            for name, entry in (val or {}).items():
                for k in (entry or {}):
                    if k not in mk:
                        bad_keys.append("models.%s.%s" % (name, k))
        elif top == "defaults":
            for k in (val or {}):
                if k not in mk or k in ("aliases", "cards"):
                    bad_keys.append("defaults.%s" % k)
        elif top == "groups":
            for name, g in (val or {}).items():
                for kind in (g or {}):
                    if kind not in ("together", "exclusive"):
                        bad_keys.append("groups.%s.%s" % (name, kind))
    if bad_keys:
        bad("%s: %s would be REFUSED by %s: %s" % (where, ", ".join(bad_keys), tag,
                                                   "keys not in that build's tables"))
    else:
        ok("%s: every key is one %s accepts (%s)"
           % (where, tag, ", ".join(sorted({k for k in doc}))))
    return bad_keys


new = load_fleet(LANE, "new lane file")

# ---- the old bytes, exactly as committed at main, for the subset check --------
old_text = None
for d in yaml.safe_load_all(jj_show("main", "kubernetes/apps/llm/llmkube/resources/radiance-deleuze.yaml")):
    if d and d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "radiance-fleet-config":
        old_text = d["data"]["radiance.yaml"]
old = yaml.safe_load(old_text)
print("old (main) fleet bytes: %d B, sha256 %s"
      % (len(old_text), __import__("hashlib").sha256(old_text.encode()).hexdigest()))


def keyset(doc):
    ks = set()
    for top, val in doc.items():
        if top in ("server", "memory", "scheduler", "defaults"):
            ks |= {"%s.%s" % (top, k) for k in (val or {})}
        elif top == "models":
            for name, entry in (val or {}).items():
                ks |= {"models.*.%s" % k for k in (entry or {})}
        elif top == "groups":
            for name, g in (val or {}).items():
                ks |= {"groups.*.%s" % k for k in (g or {})}
    return ks


T = {tag: tables(tag) for tag in TAGS}
F = {tag: flag_names(tag) for tag in TAGS}
for tag in TAGS:
    print("\n== %s: %d flag names, %d memory keys (%s), %d server keys, %d model-fleet keys =="
          % (tag, len(F[tag]), len(T[tag]["memory"]), ", ".join(sorted(T[tag]["memory"])),
             len(T[tag]["server"]), len(T[tag]["model_fleet"])))

# 1. the new file against the image being pushed
check_keys(new, TESTED, T[TESTED], F[TESTED], "new five-entry file")
# 2. the live bytes against the OLD image (proves the baseline was valid) and the new
for tag in TAGS:
    check_keys(old, tag, T[tag], F[tag], "live four-entry bytes")
# 3. the superset claims
for tag in TAGS:
    if T["v2.2.0"]["server"] - T[tag]["server"]:
        bad("server keys removed in %s: %s" % (tag, sorted(T["v2.2.0"]["server"] - T[tag]["server"])))
    if T["v2.2.0"]["memory"] - T[tag]["memory"]:
        bad("memory keys removed in %s: %s" % (tag, sorted(T["v2.2.0"]["memory"] - T[tag]["memory"])))
    if T["v2.2.0"]["scheduler"] - T[tag]["scheduler"]:
        bad("scheduler keys removed in %s" % tag)
    lost = model_keys("v2.2.0", T["v2.2.0"], F["v2.2.0"]) - model_keys(tag, T[tag], F[tag])
    if lost:
        bad("model-level keys removed in %s: %s" % (tag, sorted(lost)))
ok("no fleet-schema key present at 2.2.0 is absent at 2.3.0 (server/memory/scheduler/model all supersets)")

added_mem = T["v2.3.0"]["memory"] - T["v2.2.0"]["memory"]
if added_mem == {"pinned-numa-node", "queue-reserve"}:
    ok("2.3.0 adds exactly memory.pinned-numa-node and memory.queue-reserve")
else:
    bad("unexpected memory-key delta: %s" % sorted(added_mem))
unset = added_mem & set((new.get("memory") or {}))
if not unset:
    ok("neither new memory knob is set in this file, so the lane's pinned-host arithmetic is unchanged")
else:
    bad("new memory knobs set here: %s" % sorted(unset))

added_flags = model_keys("v2.3.0", T["v2.3.0"], F["v2.3.0"]) - model_keys("v2.2.0", T["v2.2.0"], F["v2.2.0"])
print("INFO: model-level keys added by 2.3.0 (%d): %s"
      % (len(added_flags), ", ".join(sorted(added_flags))))

# 4. the entry this change adds, and the arch that serves it
entry = (new.get("models") or {}).get("inkling-2-mini")
if not entry:
    sys.exit("no inkling-2-mini entry in the new file")
mk23 = model_keys(TESTED, T[TESTED], F[TESTED])
unknown = sorted(set(entry) - mk23)
(ok("inkling-2-mini keys all accepted at %s: %s" % (TESTED, sorted(entry)))
 if not unknown else bad("inkling-2-mini keys refused at %s: %s" % (TESTED, unknown)))
for k, want in (("tp", 2), ("max-model-len", 200000), ("max-num-seqs", 8),
                ("num-speculative-tokens", 7), ("draft-window", "adaptive"),
                ("kv-cache-dtype", "i8"), ("ttl", "15m"), ("prefix-cache-mib", 4096),
                ("vision-tower-placement", "vram")):
    got = entry.get(k)
    (ok if got == want else bad)("inkling-2-mini.%s = %r (container card says %r)" % (k, got, want))
if "mm-max-patches" in entry:
    bad("inkling-2-mini sets mm-max-patches, which must stay auto with a placement key present")
else:
    ok("inkling-2-mini leaves mm-max-patches unset (auto), so the placement/pairing refusal cannot fire")
if entry.get("model", "").endswith(".rad"):
    ok("inkling-2-mini.model names a .rad container: %s" % entry["model"])
else:
    bad("inkling-2-mini.model is not a .rad path: %r" % entry.get("model"))

arch23 = git("ls-tree", "--name-only", "v2.3.0:arch")
arch22 = git("ls-tree", "--name-only", "v2.2.0:arch")
if "inkling2" in arch23.split() and "inkling2" not in arch22.split():
    ok("arch/inkling2 exists at v2.3.0 and not at v2.2.0 -> the engine bump is required, not cosmetic")
else:
    bad("arch/inkling2 presence unexpected: 2.3.0=%s 2.2.0=%s"
        % ("inkling2" in arch23.split(), "inkling2" in arch22.split()))
ink23 = git("show", "v2.3.0:arch/inkling2/inkling2.cpp")
if "inkling2_loop" in ink23 and "n_layer" in ink23:
    ok("arch/inkling2 declares model_type inkling2_loop and gates on n_layer")
n_layer = re.findall(r'n_layer\s*[!=]=\s*(\d+)', ink23)
print("INFO: arch/inkling2 n_layer comparisons at v2.3.0:", sorted(set(n_layer)))

# 5. group structure
declared = new.get("models") or {}
models = set(declared)
for name, g in (new.get("groups") or {}).items():
    for kind, members in (g or {}).items():
        dupes = [m for m in members if members.count(m) > 1]
        missing = [m for m in members if m not in models]
        if kind not in ("together", "exclusive"):
            bad("groups.%s.%s is neither together nor exclusive" % (name, kind))
        if len(members) < 2:
            bad("groups.%s takes at least two models" % name)
        if dupes:
            bad("groups.%s lists twice: %s" % (name, dupes))
        if missing:
            bad("groups.%s names undeclared models: %s" % (name, missing))
        if kind == "exclusive":
            ok("groups.%s exclusive over %d declared entries: %s" % (name, len(members), members))
            text = {n for n, e in declared.items()
                    if str(e.get("model", "")).endswith(".rad")
                    and (e.get("tp") or 1) > 1 and "flux" not in n}
            if not text - set(members):
                ok("every multi-card text entry is in the exclusive group (%s)" % sorted(text))
            else:
                bad("multi-card text entries outside the exclusive group: %s" % sorted(text - set(members)))

# 6. warm-up order consequence: first entry stays resident, new one loads first
order = list(declared)
if order[0] == "qwen3.8-flash-next" and order[-1] == "inkling-2-mini":
    ok("entry order keeps %s FIRST (the entry warm-up leaves resident) and the new one LAST"
       % order[0])
else:
    bad("models: order is %s; the agent entry must stay first" % order)
pins = {n: e.get("pin") for n, e in declared.items() if e.get("pin")}
if not pins:
    ok("no entry sets pin:, so nothing loads before the listener opens")
else:
    bad("entries with pin: %s would load before the listener is open" % pins)

print("\nRESULT:", "FAILURES: %d" % len(fails) if fails else "fleet file is accepted by %s" % TESTED)
sys.exit(1 if fails else 0)
