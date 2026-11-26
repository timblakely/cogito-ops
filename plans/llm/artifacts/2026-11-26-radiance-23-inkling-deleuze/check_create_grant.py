#!/usr/bin/env python3
"""Exact-scope check for the named-create addition to llm/radiance-23-model-validator.

Usage: check_create_grant.py <rendered-flux-ops.yaml> <published-render.yaml>
Reads the rendered flux-ops output (kustomize build, LoadRestrictionsNone) and the
render taken before this change, and fails on anything beyond one verb on one rule.
"""
import subprocess
import sys
import yaml

EXPECTED = [
    (["inference.llmkube.dev"], ["inferenceservices"], ["radiance"], ["get", "patch"]),
    (["litellm.home-operations.com"], ["litellmmodels"], ["inkling-deleuze"],
     ["get", "patch", "create"]),
    (["litellm.home-operations.com"], ["litellmvirtualkeys"], ["hermes", "opencode"],
     ["get", "patch"]),
]
FORBIDDEN_VERBS = {"delete", "deletecollection", "update", "list", "watch", "impersonate", "*"}

fails = []


def ck(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def load(path):
    return [d for d in yaml.safe_load_all(open(path)) if d]


new, old = load(sys.argv[1]), load(sys.argv[2])
ck(len(new) == len(old) == 14, "no objects added or removed: %d rendered, %d before" % (len(new), len(old)))

key = lambda d: (d["kind"], d["metadata"].get("namespace"), d["metadata"]["name"])
nmap, omap = {key(d): d for d in new}, {key(d): d for d in old}
ck(set(nmap) == set(omap), "identical object identity set")

role = nmap[("Role", "llm", "radiance-23-model-validator")]
got = [(r["apiGroups"], r["resources"], r.get("resourceNames") or [], sorted(r["verbs"])) for r in role["rules"]]
want = [(g, r, n, sorted(v)) for g, r, n, v in EXPECTED]
ck(got == want, "Role rules exactly the three intended (groups/resources/names/verbs): %s" % got)
ck(sorted({v for r in role["rules"] for v in r["verbs"]}) == ["create", "get", "patch"],
   "no verb beyond get/patch/create anywhere in the Role")
ck(not FORBIDDEN_VERBS & {v for r in role["rules"] for v in r["verbs"]},
   "no delete/update/list/watch/impersonate/wildcard verbs")
ck(all(r.get("resourceNames") for r in role["rules"]),
   "every rule is name-scoped; a bare-resource rule would match every object of the kind")
ck(all(len(r["apiGroups"]) == 1 and len(r["resources"]) == 1 for r in role["rules"]),
   "one apiGroup and one resource per rule (no grouping that could widen)")
ck(sorted({n for r in role["rules"] for n in (r.get("resourceNames") or [])}) ==
   ["hermes", "inkling-deleuze", "opencode", "radiance"], "resourceNames: only the four intended names")
ck(role["metadata"]["namespace"] == "llm", "Role lives in llm only")

rb = nmap[("RoleBinding", "llm", "radiance-23-model-validator")]
ck(rb["roleRef"] == {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role",
                     "name": "radiance-23-model-validator"}, "RoleBinding still points at this Role")
ck(rb["subjects"] == [{"kind": "ServiceAccount", "name": "opencode-flux-operator",
                       "namespace": "llm"}], "single subject: SA llm/opencode-flux-operator (no new identity)")

changed = [k for k in nmap if nmap[k] != omap.get(k)]
ck(changed == [("Role", "llm", "radiance-23-model-validator")],
   "exactly one rendered object differs from the published grant: %s" % changed)
r_old, r_new = omap[changed[0]], nmap[changed[0]]
ck({k: v for k, v in r_new.items() if k != "rules"} == {k: v for k, v in r_old.items() if k != "rules"},
   "Role metadata unchanged (same name/namespace/labels)")
ck(len(r_old["rules"]) == len(r_new["rules"]) == 3, "still three rules")
diffs = [(r_old["rules"][i]["resources"], r_old["rules"][i]["verbs"], r_new["rules"][i]["verbs"])
         for i in range(3) if r_old["rules"][i] != r_new["rules"][i]]
ck(diffs == [(["litellmmodels"], ["get", "patch"], ["get", "patch", "create"])],
   "the single delta is +create on litellmmodels/inkling-deleuze: %s" % diffs)

# no other Role/ClusterRole in the render gained anything
gained = [k for k in nmap if nmap[k] != omap.get(k) and k[0] in ("Role", "ClusterRole", "RoleBinding", "ClusterRoleBinding")]
ck(gained == [("Role", "llm", "radiance-23-model-validator")], "no other RBAC object touched: %s" % gained)

print("GRANT SCOPE CHECK FAILED" if fails else "GRANT SCOPE CHECK PASSED - one verb on one named rule, nothing else")
sys.exit(1 if fails else 0)
