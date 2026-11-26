#!/usr/bin/env python3
"""Re-sync the generated parts of manual/radiance-23-preflight.yaml.

Why this exists. `radiance --check` is the only gate that runs before the push:
an unknown fleet key exits 2 at startup, so a bad ConfigMap crashloops the lane
instead of being refused by reload. That gate only proves anything if the bytes
it checks are the bytes that will land, so the Job carries its OWN copy of the
fleet (mounting the live ConfigMap would apply the new bytes early and roll the
lane onto the OLD image - see the header in that file). A hand-copied block is
where that goes wrong, so this script rewrites the copy from the lane file.

What it treats as generated, and what it leaves alone:

  * the ConfigMap's `radiance.yaml` block, replaced verbatim from
    InferenceService's sibling ConfigMap/radiance-fleet-config;
  * the weight probe's PATH / SIZE / SHA constants, replaced from the staging
    Job's own FILES table, so the preflight cannot pin a digest the stager does
    not write;
  * every comment and every other line, byte for byte: the file is edited as
    text, not round-tripped through a YAML emitter, so re-running this on a
    current file changes nothing.

scripts/validate-llm-catalogue.py (check 10) fails the repo if the embedded copy
stops matching the ConfigMap, so a forgotten run of this script is caught in CI
rather than by the preflight Job failing after a roll.

    python3 plans/llm/artifacts/2026-11-26-radiance-23-inkling-deleuze/gen_preflight.py --check
    python3 plans/llm/artifacts/2026-11-26-radiance-23-inkling-deleuze/gen_preflight.py

--check exits 1 without writing, and prints what drifted.
"""
import argparse
import hashlib
import re
import sys
import textwrap
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]

# The three constants the weight probe pins, as they appear in the Job's inlined
# python. Anchored at line start inside the block scalar's indentation.
PROBE_CONST = re.compile(r'^(\s*)(PATH|SIZE|SHA) = (?:"([^"]*)"|(\d+))$', re.M)


def one(docs, kind, name):
    for d in docs:
        if isinstance(d, dict) and d.get("kind") == kind and \
                d["metadata"]["name"] == name:
            return d
    raise SystemExit("no %s named %s" % (kind, name))


def stager_files(docs, name=None):
    """The staging Job's FILES table: url, name, sha256, size."""
    job = (one(docs, "Job", name) if name
           else next(d for d in docs if isinstance(d, dict)
                and d.get("kind") == "Job"))
    script = job["spec"]["template"]["spec"]["containers"][0]["args"][0]
    out = []
    for m in re.finditer(r'"url": \(([^)]*)\),\s*"name": "([^"]+)",\s*'
                         r'"sha256": "([0-9a-f]{64})",\s*"size": (\d+),', script):
        url = "".join(re.findall(r'"([^"]+)"', m.group(1)))
        out.append({"url": url, "name": m.group(2), "sha": m.group(3),
                    "size": int(m.group(4)), "path": "/models/radiance/" + m.group(2)})
    if not out:
        raise SystemExit("%s: no FILES entries parsed - the stager's shape changed"
                         % "staging")
    return out


def replace_block_scalar(text, key_line, new_block):
    """Swap the body of a `key: |` block scalar, keeping its indentation."""
    lines = text.split("\n")
    try:
        i = lines.index(key_line)
    except ValueError:
        raise SystemExit("no %r line in the preflight file" % key_line)
    indent = len(key_line) - len(key_line.lstrip()) + 2      # block body indent
    j = i + 1
    while j < len(lines) and (not lines[j].strip()
                              or len(lines[j]) - len(lines[j].lstrip()) >= indent):
        j += 1
    body = textwrap.indent(new_block.rstrip("\n"), " " * indent).split("\n")
    return "\n".join(lines[:i + 1] + body + lines[j:]), j - i - 1, len(body)


def replace_probe_constants(text, want):
    """Rewrite PATH/SIZE/SHA in the Job's inlined probe; return (text, before)."""
    before = {}

    def sub(m):
        pad, name, sval, ival = m.group(1), m.group(2), m.group(3), m.group(4)
        before[name] = sval if sval is not None else ival
        return '%s%s = %s' % (pad, name,
                              ('"%s"' % want[name]) if name != "SIZE" else want[name])

    out = PROBE_CONST.sub(sub, text)
    missing = set(want) - set(before)
    if missing:
        raise SystemExit("the probe no longer sets %s - its shape changed"
                         % ", ".join(sorted(missing)))
    return out, before


def replace_header_evidence(text, fleet, fsha, entries):
    """Keep the header's stated sha256 / size / entry list honest.

    The header describes the copy it carries, so those three lines are generated
    too: a reader comparing the live ConfigMap against the Job needs the number
    the Job will actually mount, not the number from the day it was written.
    """
    listing = "\n".join("#   " + l for l in
                        (", ".join(entries)).replace(", ", ",\n").split("\n"))
    text, n1 = re.subn(r"^#   sha256 [0-9a-f]{64}$", "#   sha256 " + fsha,
                       text, count=1, flags=re.M)
    text, n2 = re.subn(r"^#   \d+ bytes, \d+ entries:\n(?:#   [^\n]*\n)+",
                       lambda _: "#   %d bytes, %d entries:\n%s\n"
                       % (len(fleet), len(entries), listing), text, count=1,
                       flags=re.M)
    if n1 != 1 or n2 != 1:
        raise SystemExit("the preflight header no longer states its fleet evidence "
                         "in the generated shape (sha line %d, listing %d)" % (n1, n2))
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lane", default="kubernetes/apps/llm/llmkube/resources/"
                                      "radiance-deleuze.yaml")
    ap.add_argument("--staging", default="kubernetes/apps/llm/llmkube/resources/"
                                         "manual/radiance-deleuze-stage-inkling.yaml")
    ap.add_argument("--preflight", default="kubernetes/apps/llm/llmkube/resources/"
                                           "manual/radiance-23-preflight.yaml")
    ap.add_argument("--name", default="radiance-23-preflight")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    lane_docs = [d for d in yaml.safe_load_all((ROOT / a.lane).read_text()) if d]
    fleet = one(lane_docs, "ConfigMap", "radiance-fleet-config")["data"]["radiance.yaml"]
    image = one(lane_docs, "InferenceService", "radiance")["spec"]["image"]

    staging_docs = [d for d in yaml.safe_load_all((ROOT / a.staging).read_text()) if d]
    files = stager_files(staging_docs)
    if len(files) != 1:
        raise SystemExit("%s stages %d files; this gate probes one" % (a.staging, len(files)))
    staged = files[0]

    # The probe must describe an entry that exists in the fleet and mounts the
    # path the stager writes, or a green Job would prove nothing about the push.
    models_block = fleet[fleet.index("\nmodels:\n"):fleet.index("\ngroups:\n")]
    entry = None
    for cand in re.findall(r"^  ([a-z0-9][a-z0-9.-]*):$", models_block, re.M):
        block = models_block.split("\n  %s:\n" % cand, 1)[1]
        mounted = re.match(r"(?: *#[^\n]*\n)* *model: (\S+)", block)
        if mounted and mounted.group(1) == staged["path"]:
            entry = cand
            break
    if entry is None:
        raise SystemExit("no models.<entry> in the lane file mounts %s, so a probe "
                         "for it proves nothing" % staged["path"])
    want = {"PATH": staged["path"], "SIZE": str(staged["size"]), "SHA": staged["sha"]}

    src = (ROOT / a.preflight).read_text()
    out, old_n, new_n = replace_block_scalar(src, "  radiance.yaml: |", fleet)
    out, seen = replace_probe_constants(out, want)
    entries = re.findall(r"^  ([a-z0-9][a-z0-9.-]*):$", models_block, re.M)
    out = replace_header_evidence(out, fleet,
                                  hashlib.sha256(fleet.encode()).hexdigest(), entries)

    # Round trip: what we produced must read back as the lane's bytes exactly.
    docs = [d for d in yaml.safe_load_all(out) if d]
    got = one(docs, "ConfigMap", a.name + "-config")["data"]["radiance.yaml"]
    if got != fleet:
        raise SystemExit("GENERATION BUG: emitted fleet bytes differ from the lane's "
                         "(%d vs %d)" % (len(got), len(fleet)))
    job = one(docs, "Job", a.name)
    spec = job["spec"]["template"]["spec"]
    if spec["containers"][0]["image"] != image:
        raise SystemExit("GENERATION BUG: the Job's image is not the lane's image")
    probe = spec["initContainers"][0]["args"][0]
    compile(probe, "probe", "exec")
    for k, v in want.items():
        if v not in probe:
            raise SystemExit("GENERATION BUG: the probe lost %s = %s" % (k, v))
    if "claimName: radiance-deleuze" not in out:
        raise SystemExit("GENERATION BUG: the Job no longer mounts radiance-deleuze")

    fsha = hashlib.sha256(fleet.encode()).hexdigest()
    if out == src:
        print("%s is current: fleet %d B sha256 %s; probes models.%s -> %s "
              "%d B sha256 %s..." % (a.preflight, len(fleet), fsha[:16], entry,
                                     staged["name"], staged["size"],
                                     staged["sha"][:16]))
        return 0
    print("%s is STALE against %s and %s:\n"
          "  fleet block: %d -> %d lines\n  probe constants were %s"
          % (a.preflight, a.lane, a.staging, old_n, new_n, seen), file=sys.stderr)
    if a.check:
        return 1
    (ROOT / a.preflight).write_text(out)
    print("wrote %s (fleet %d B sha256 %s)" % (a.preflight, len(fleet), fsha))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
