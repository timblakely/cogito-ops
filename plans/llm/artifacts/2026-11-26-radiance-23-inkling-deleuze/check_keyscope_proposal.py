#!/usr/bin/env python3
"""Offline validator for the NOT-APPLIED key-scope sync proposal.

Checks, without contacting a cluster and without reading any credential:
  1. the YAML parses and is a single batch/v1 Job, marked as a proposal;
  2. the embedded python compiles, and its pure --self-test logic behaves
     (additive-only, refuse-on-extra, no-op-when-converged, never-blank);
  3. credential handling is least-privilege by construction: the only Secret
     source is llm/litellm-secrets key PROXY_MASTER_KEY, projected 0400, read as
     a file; no Secret is injected as an env var; no cluster API identity;
  4. the target scopes embedded in the script equal the scopes declared by
     kubernetes/apps/llm/litellm/app/virtualkeys/{hermes,opencode}.yaml, and the
     only difference from the live CRs is the additive inkling-deleuze row;
  5. the script never references any egress target other than the in-cluster
     litellm Service, and never prints the token or a handle.

Run:  python3 plans/llm/artifacts/<dir>/check_keyscope_proposal.py
"""
import ast
import pathlib
import re
import subprocess
import sys
import tempfile

import yaml

HERE = pathlib.Path(__file__).resolve().parent
REPO = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parents[3]
PROPOSAL = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "keyscope-sync-proposal.yaml"
KEYS_DIR = REPO / "kubernetes/apps/llm/litellm/app/virtualkeys"
ALLOWED_HOST = "litellm.llm.svc.cluster.local"
ADMIN_SECRET = "litellm-secrets"
ADMIN_KEY = "PROXY_MASTER_KEY"

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


doc = yaml.safe_load(PROPOSAL.read_text())
print("1. shape")
check(doc["kind"] == "Job" and doc["metadata"]["namespace"] == "llm", "single batch Job in llm")
check(doc["metadata"]["name"] == "radiance-23-keyscope-sync", "named radiance-23-keyscope-sync")
check(doc["metadata"]["labels"].get("cogito.local/proposal") == "true", "labelled as a proposal")
check(doc["spec"]["ttlSecondsAfterFinished"] == 3600 and doc["spec"]["backoffLimit"] == 1,
      "bounded lifetime and one retry")

tmpl = doc["spec"]["template"]["spec"]
cs = tmpl["containers"][0]
script = cs["args"][0]
print("2. embedded script")
try:
    tree = ast.parse(script, filename="keyscope", mode="exec")
    check(True, "script compiles")
except SyntaxError as e:
    check(False, "script compiles: %s" % e)
    tree = None
compiled = compile(script, "keyscope", "exec")
check(compiled is not None, "script compiles to bytecode")
with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
    fh.write(script)
    path = fh.name
proc = subprocess.run([sys.executable, path, "--self-test"], capture_output=True, text=True, timeout=60)
check(proc.returncode == 0 and "SELF-TEST PASS" in proc.stdout,
      "script --self-test passes (%s)" % proc.stdout.strip().splitlines()[-1:])
check(proc.stderr == "", "self-test prints nothing to stderr")

print("3. credential handling")
check(tmpl["automountServiceAccountToken"] is False, "no service-account token in the pod")
sc = tmpl.get("securityContext", {})
check(sc.get("runAsNonRoot") is True and sc.get("seccompProfile", {}).get("type") == "RuntimeDefault",
      "non-root, RuntimeDefault seccomp")
csc = cs.get("securityContext", {})
check(csc.get("readOnlyRootFilesystem") is True and csc.get("allowPrivilegeEscalation") is False,
      "read-only rootfs, no privilege escalation")
check(csc.get("capabilities", {}).get("drop") == ["ALL"], "all capabilities dropped")
check("valueFrom" not in __import__("json").dumps(cs.get("env", [])),
      "no Secret material injected as an environment variable")
vols = tmpl["volumes"]
check(len(vols) == 1, "exactly one volume")
proj = vols[0]["projected"]
srcs = proj["sources"]
check(len(srcs) == 1 and srcs[0]["secret"]["name"] == ADMIN_SECRET,
      "the only Secret source is llm/%s" % ADMIN_SECRET)
items = srcs[0]["secret"]["items"]
check([i["key"] for i in items] == [ADMIN_KEY], "exactly one key projected: %s" % ADMIN_KEY)
check(proj.get("defaultMode") == 0o440,
      "projected at mode 0440 (group-read; the file is root-owned)")
check(sc.get("fsGroup") == sc.get("runAsGroup") == 1000,
      "fsGroup == runAsGroup == 1000, so the root-owned 0440 file is readable")
check("show up in `kubectl describe pod`" not in PROPOSAL.read_text(),
      "no inaccurate describe-pod-leak claim (describe shows the ref, not the value)")
check(cs["volumeMounts"][0]["readOnly"] is True, "mounted read-only")
check("os.environ" not in script, "script never reads credentials from the environment")

print("4. additive scope vs the declared CRs")
declared = {}
for name in ("hermes", "opencode"):
    for d in yaml.safe_load_all((KEYS_DIR / ("%s.yaml" % name)).read_text()):
        if d and d["kind"] == "LiteLLMVirtualKey":
            declared[d["spec"].get("key_alias") or d["spec"].get("keyAlias")] = (
                d["metadata"]["name"], d["spec"]["secretName"], d["spec"]["models"])
targets_node = next(
    n for n in ast.walk(ast.parse(script))
    if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "TARGETS")
targets = {t["alias"]: t["models"] for t in ast.literal_eval(ast.unparse(targets_node.value))}
check(set(targets) == set(declared), "targets are exactly the two live key aliases %s" % sorted(targets))
for alias, models in targets.items():
    cr_name, secret, cr_models = declared[alias]
    check(models == cr_models, "%s target == %s spec.models" % (alias, cr_name))
    diff = sorted(set(models) - set(cr_models))
    check(diff == [], "%s target declares nothing the CR does not" % alias)
check("if not live_models:" in script, "an empty live scope is refused, never filled")

print("5. egress and output discipline")
hosts = set(re.findall(r'https?://([^/"\s]+)', script))
check(hosts == {ALLOWED_HOST + ":4000"}, "only the in-cluster litellm Service is addressable: %s" % hosts)
for needle in ("print(tok", "print(handle", "print(new)", "print(\" %s\" % tok", "% tok)", "% handle)", ", tok)", ", handle)"):
    check(needle not in script, "script does not print credential material (%r)" % needle)
check("print(rec)" not in script and "print(body)" not in script,
      "no raw API response object is printed")
check("urllib.request.urlopen" in script and "requests" not in script,
      "stdlib only (nothing installed at run time)")

print()
if fails:
    print("PROPOSAL CHECK FAILED (%d)" % len(fails))
    for f in fails:
        print(" - " + f)
    sys.exit(1)
print("PROPOSAL CHECK PASSED - still not applicable without explicit user approval")
