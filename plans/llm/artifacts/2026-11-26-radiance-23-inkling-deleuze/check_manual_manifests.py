#!/usr/bin/env python3
"""Validate the two out-of-band radiance manifests under manual/.

Checks, all machine-readable:
  1. every YAML doc parses;
  2. the embedded python of the staging Job COMPILES (the house stager body lives
     in a YAML block scalar, so a stray indent is a runtime surprise otherwise);
  3. the staged artifact's url / size / sha256 agree with what the Hugging Face
     API publishes for the LFS object (network; skipped with --offline);
  4. the preflight Job's embedded copy of radiance.yaml is BYTE-IDENTICAL to the
     ConfigMap the lane will actually mount (otherwise the --check gate proves
     nothing about the bytes being pushed), and it pins the same image digest as
     the InferenceService;
  5. the preflight Job's digest check matches the staging Job's digest.

Usage: python3 check_manual_manifests.py [repo_root] [--offline]
"""
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--")
            else "/workspace/cogito")
MAN = ROOT / "kubernetes/apps/llm/llmkube/resources/manual"
LANE = ROOT / "kubernetes/apps/llm/llmkube/resources/radiance-deleuze.yaml"
STAGE = MAN / "radiance-deleuze-stage-inkling.yaml"
PREFLIGHT = MAN / "radiance-23-preflight.yaml"
fails = []


def ok(msg):
    print("PASS:", msg)


def bad(msg):
    fails.append(msg)
    print("FAIL:", msg)


def docs(path):
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


# ---- 1/2: parse + compile the stager's embedded python -----------------------
stagedocs = docs(STAGE)
job = next(d for d in stagedocs if d.get("kind") == "Job")
cont = job["spec"]["template"]["spec"]["containers"][0]
script = cont["args"][0]
try:
    compile(script, "stager.py", "exec")
    ok("staging Job embedded python compiles (%d bytes)" % len(script))
except SyntaxError as e:
    bad("staging Job python does not compile: %s" % e)
if "statvfs" not in script or "REFUSING" not in script:
    bad("staging Job lost its space gate")
else:
    ok("staging Job carries the statvfs space gate")
vmounts = [m["mountPath"] for m in cont["volumeMounts"]]
if "/models" not in vmounts:
    bad("staging Job does not mount the claim at /models")

# ---- 3: artifact facts against the Hugging Face API --------------------------
m = re.search(r'"url": \("([^"]+)"\s*\n\s*"([^"]+)"\)', script)
url = "".join(m.groups())
size = int(re.search(r'"size": (\d+)', script).group(1))
sha = re.search(r'"sha256": "([0-9a-f]{64})"', script).group(1)
repo = re.search(r"huggingface\.co/([^/]+/[^/]+)/resolve", url).group(1)
name = re.search(r'"name": "([^"]+)"', script).group(1)
if "--offline" in sys.argv:
    print("SKIP: Hugging Face cross-check (--offline)")
else:
    api = "https://huggingface.co/api/models/%s/tree/main?blobs=true" % repo
    with urllib.request.urlopen(api, timeout=60) as r:
        tree = json.load(r)
    ent = next((f for f in tree if f["path"] == name), None)
    if ent is None:
        bad("%s not found in %s" % (name, repo))
    else:
        got_size, got_oid = ent.get("size"), (ent.get("lfs") or {}).get("oid")
        (ok if got_size == size else bad)(
            "HF size for %s/%s = %s (manifest says %s)" % (repo, name, got_size, size))
        (ok if got_oid == sha else bad)(
            "HF LFS OID = %s (manifest says %s)" % (got_oid, sha))
    meta = json.load(urllib.request.urlopen(
        "https://huggingface.co/api/models/%s" % repo, timeout=60))
    (ok if meta.get("gated") is False and meta.get("private") is False else bad)(
        "repo %s gated=%s private=%s (header claims ungated)"
        % (repo, meta.get("gated"), meta.get("private")))

# ---- 4/5: the preflight gate proves the bytes that will land -----------------
lanedocs = docs(LANE)
cm = next(d for d in lanedocs
          if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "radiance-fleet-config")
fleet = cm["data"]["radiance.yaml"]
isvc = next(d for d in lanedocs if d.get("kind") == "InferenceService")
lane_image = isvc["spec"]["image"]
fleet_sha = hashlib.sha256(fleet.encode()).hexdigest()
print("fleet ConfigMap bytes: %d, sha256 %s" % (len(fleet), fleet_sha))

pfdocs = docs(PREFLIGHT)
pfcm = next(d for d in pfdocs
            if d.get("kind") == "ConfigMap" and "radiance.yaml" in (d.get("data") or {}))
pfjob = next(d for d in pfdocs if d.get("kind") == "Job")
copy = pfcm["data"]["radiance.yaml"]
if copy == fleet:
    ok("preflight ConfigMap is byte-identical to radiance-fleet-config (%d B)" % len(copy))
else:
    bad("preflight ConfigMap DIFFERS from radiance-fleet-config: %d B vs %d B"
        % (len(copy), len(fleet)))
pf_img = pfjob["spec"]["template"]["spec"]["containers"][0]["image"]
if pf_img == lane_image:
    ok("preflight image == InferenceService image: %s" % pf_img)
else:
    bad("preflight image %s != InferenceService image %s" % (pf_img, lane_image))
init = pfjob["spec"]["template"]["spec"].get("initContainers", [])
if init:
    isc = init[0]["args"][0] if "args" in init[0] else ""
    if sha in isc and str(size) in isc:
        ok("preflight weight probe pins the same digest+size as the stager")
    else:
        bad("preflight weight probe does not pin %s / %s" % (sha, size))
else:
    bad("preflight Job has no initContainer weight probe")

# fleet-config sanity: the entry this change adds, and the group that must name it
models_block = fleet[fleet.index("\nmodels:\n"):fleet.index("\ngroups:\n")]
if "\n  inkling-2-mini:\n" not in models_block:
    bad("fleet config has no inkling-2-mini entry under models:")
else:
    ok("fleet config declares models.inkling-2-mini")
entry_keys = re.findall(r"^  ([a-z0-9][a-z0-9.-]*):", models_block, re.M)
if entry_keys == ["qwen3.8-flash-next", "muse-glimmer", "flux-3-klein",
                  "gemma4-heretic", "inkling-2-mini"]:
    ok("model order keeps qwen3.8-flash-next FIRST and inkling LAST "
       "(warm-up loads later-in-file first, so the agent lane stays resident): %s"
       % entry_keys)
else:
    bad("model entry order changed: %s" % entry_keys)
grp = re.search(r"exclusive: \[([^\]]*)\]", fleet, re.S)
names = [n.strip() for n in grp.group(1).replace("\n", " ").split(",")]
if "inkling-2-mini" in names:
    ok("inkling-2-mini is in the one-at-a-time exclusive group: %s" % names)
else:
    bad("inkling-2-mini missing from exclusive group: %s" % names)

print("RESULT:", "FAILURES: %d" % len(fails) if fails else "all manual-manifest checks pass")
sys.exit(1 if fails else 0)
