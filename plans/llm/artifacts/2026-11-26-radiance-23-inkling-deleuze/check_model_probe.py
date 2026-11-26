#!/usr/bin/env python3
"""Offline checks for the post-deploy model-probe Job (NOT applied by this script)."""
import ast, json, pathlib, subprocess, sys, tempfile, yaml
p = pathlib.Path(sys.argv[1]); fails = []
def ck(c, m):
    print(("  ok   " if c else "  FAIL ") + m)
    if not c: fails.append(m)
d = yaml.safe_load(p.read_text())
ck(d["kind"] == "Job" and d["metadata"]["namespace"] == "llm", "single Job in llm")
t = d["spec"]["template"]["spec"]; c = t["containers"][0]; s = c["args"][0]
compile(s, "probe", "exec"); ck(True, "embedded script compiles")
f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False); f.write(s); f.close()
r = subprocess.run([sys.executable, f.name, "--self-test"], capture_output=True, text=True)
ck(r.returncode == 0 and "SELF-TEST PASS" in r.stdout, "script --self-test passes")
ck(t["automountServiceAccountToken"] is False, "no service-account token")
sc = t["securityContext"]
ck(sc["runAsNonRoot"] and sc["fsGroup"] == sc["runAsGroup"] == 1000, "non-root, fsGroup==runAsGroup==1000")
ck(c["securityContext"]["readOnlyRootFilesystem"] and c["securityContext"]["capabilities"]["drop"] == ["ALL"], "read-only rootfs, drop ALL")
ck("valueFrom" not in json.dumps(c.get("env", [])), "no Secret injected as env var")
v = t["volumes"]; ck(len(v) == 1 and v[0]["projected"]["defaultMode"] == 0o440, "one projected volume at 0440")
srcs = v[0]["projected"]["sources"]
names = [(x["secret"]["name"], [i["key"] for i in x["secret"]["items"]]) for x in srcs]
ck(sorted(n for n, _ in names) == ["litellm-key-hermes", "litellm-key-opencode"], "exactly the two consumer key Secrets: %s" % names)
ck(all(k == ["api-key"] for _, k in names), "exactly one key each: api-key")
ck(not any(x["secret"]["name"] in ("litellm-secrets",) for x in srcs), "admin credential NOT projected")
ck(sorted(set(__import__("re").findall(r'https?://([^/"\s]+)', s))) == ["litellm.llm.svc.cluster.local:4000"], "in-cluster egress only")
ck(all(x in s for x in ("inkling-deleuze", "flashnext-deleuze")), "both aliases probed (new + restore)")
ck(s.count("post_chat") >= 2 and "for model in (NEW, OLD)" in s, "restore request follows each new-alias request")
ck("os.environ" not in s, "credentials read from files only")
for n in ("print(tok", "print(\" %s\" % tok", "% tok)", "print(d)", "print(body"):
    ck(n not in s, "no credential/raw-body printing (%r)" % n)
print("PROBE CHECK FAILED" if fails else "PROBE CHECK PASSED - apply only after reconcile + Ready")
sys.exit(1 if fails else 0)
