# Publication gate status (copy of GATE-STATUS.md) — radiance 2.3.0 + Inkling 2 Mini (llm)

As of 2026-11-27T00:52Z. Publication of `main` is **held**: gate 3 below is
blocked on one named RBAC denial. No cluster write has been made except the two
out-of-band one-shot Jobs named in gates 1 and 2.

| # | Gate | Status | Evidence |
|---|---|---|---|
| 1 | Weight staged, digest verified on the real claim | **PASSED** | `radiance-deleuze-stage-inkling` Job `succeeded=1`, `completionTime 2026-11-27T00:44:32Z`; log `staged: /models/radiance/inkling-2-mini-iq4r-v4.rad 14.43 GiB digest verified` / `ALL FILES STAGED`; pre-flight `space: 1381.35 GiB free; 16.43 GiB needed`. Staged script vs repo script: token-normalised **identical** (`live-stager-script.py`, 6711 B vs repo 8442 B — difference is comments/blank lines only); the staged digest pin `1522e6d7…4b03dcc9` and size `15496360448` are present in the live object. |
| 2 | `radiance --check` on the actual 2.3.0 binary + weight probe | **PASSED** | `ConfigMap/llm/radiance-23-preflight-config` + `Job/llm/radiance-23-preflight` created through the MCP identity; pod `radiance-23-preflight-qgv66` `Succeeded` **exit 0** at 00:47:12Z, Job `succeeded=1 failed=0`. Init `weight`: `weight ok: inkling-2-mini-iq4r-v4.rad 15496360448 B sha256 1522e6d7…4b03dcc9 (read in 10 s)` + `the weight this entry names is on the claim, byte-exact`; `check` logged all five entries parsed by the pinned 2.3.0 binary, ending `model inkling-2-mini = /models/radiance/inkling-2-mini-iq4r-v4.rad, tp 2`. Logs: `preflight-weight-init-log.txt`, `preflight-pod-log.txt`. |
| 3 | Owner-aware server-side diff of every fully rendered llm path | **BLOCKED — RBAC** | Four identical denials, `serverdiff-ks-{llmkube-resources,litellm,opencode,hermes}.txt`. |
| 4 | Full rendered manifests saved | **DONE** | `ks-llmkube-resources.yaml` 56 477 B/32 docs, `ks-litellm.yaml` 118 682 B/57 docs, `ks-opencode.yaml` 59 370 B/29 docs, `ks-hermes.yaml` 126 539 B/14 docs (`flux-local build kustomization … --skip-secrets`). |
| 5 | Substituted comparison for the Hermes HelmRelease | **DONE, offline** | `offline-diff-hr-hermes.patch`: exactly one changed line, the `hermes.home-operations.com/bundle-sha256` pod-template annotation. This render is substituted — `flux-local diff hr` templates against the **live** HelmRelease, and the live `spec.values` was checked to contain no `${`. |
| 6 | Existing model settings unchanged | **DONE, offline** | `offline-diff-ks-llm.patch`: 9 objects, 0 `${` placeholders, no Secret objects; the four pre-existing fleet entries and every other model are untouched (only additive inkling rows in the fleet ConfigMap, the two key scopes, the pickers, plus the new `LiteLLMModel/llm/inkling-deleuze`). |

## Gate 2 proof that the checked bytes are the pushed bytes

The live preflight ConfigMap was pulled back out of the cluster and hashed against
the repo lane ConfigMap: **byte identical**, 25 277 B,
sha256 `3cbc1313c0244363a5d1d57f084307671f35f6f5dafb079214fd054b713ba173`
(`live-preflight-fleet-bytes.yaml`). So `--check` ran against exactly the fleet bytes
this change would push, on `radiance:2.3.0@sha256:1e0fe6a2…`, without touching the
lane. The live `radiance-fleet-config` is unchanged at its baseline sha256
`990640aa9027a3a7…118` with no `inkling` string in it — nothing has been rolled.
(The byte-count note: reading the ConfigMap through `.data` as JSON vs raw value
differs by the trailing newline; the sha256 is the earlier baseline's, so the live
bytes are the bytes captured at baseline.)

Independence of the gate-2 claim: the Job's `managedFields` show
`manager: kubectl-flux-mcp, operation: Apply, time: 2026-11-27T00:46:56Z`, the pod
terminated 00:47:12Z and the Job completed 00:47:15Z, and the byte comparison above
was computed from bytes read back with the read-only credential — the verdict does
not rest on the worker's report. (An earlier line here said the Job "had not been
created"; that was a false negative from `kubectl get job,cm a b`, which resolves
names positionally across the two types. Querying each object by itself finds them.)

Both one-shot Jobs are **still in the cluster** (`radiance-deleuze-stage-inkling`,
`radiance-23-preflight` + its ConfigMap). Nothing one-shot belongs in the Flux
Kustomization, so they are inert and prunable with
`kubectl -n llm delete job/radiance-deleuze-stage-inkling job/radiance-23-preflight configmap/radiance-23-preflight-config`
— not deleted here because further live writes were stopped after this gate.

## Gate 3: exact denial and the smallest admin action

```
Failed to diff manifest: unable to prepare objects: failed to read substituteFrom
Secret llm/cluster-settings: secrets "cluster-settings" is forbidden: User
"system:serviceaccount:llm:opencode-flux-operator" cannot get resource "secrets"
in API group "" in the namespace "llm"
```

Why it happens: every llm Kustomization carries
`spec.postBuild.substituteFrom: [{ConfigMap <app>-app-vars-*}, {Secret cluster-settings}]`
(read from the live KS objects; the repo applies it cluster-wide at
`kubernetes/flux/cluster/kustomization.yaml:30-33`, inside the cluster-wide patch
whose target block ends at `:36`). `diff_kubernetes_manifest`
resolves that substitution before diffing, so an owner-aware diff of any
KS-owned path needs `get` on `Secret llm/cluster-settings`.

Smallest fix (owner action, **not** taken here — no RBAC change is authorised in
this task):

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata: {name: flux-mcp-substitution-reader, namespace: llm}
rules:
  - apiGroups: [""]
    resources: ["secrets"]
    resourceNames: ["cluster-settings"]
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata: {name: flux-mcp-substitution-reader, namespace: llm}
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: Role, name: flux-mcp-substitution-reader}
subjects: [{kind: ServiceAccount, name: opencode-flux-operator, namespace: llm}]
```

Alternatives that need no new grant: run the same four owner-aware diffs as an
identity that already has the grant (kustomize-controller's own SA, or an admin
kubeconfig), or accept gates 5–6 as the substituted comparison and treat gate 3
as waived.

Side observation for the owners, no action taken: that same MCP identity
successfully **created** `Job/llm/radiance-deleuze-stage-inkling` with
field-manager `kubectl-flux-mcp`, so it can write `llm` workload objects while
the shell credential (`system:serviceaccount:llm:opencode-reader`) is
get/list/watch only. It does not read secret *values* (its own substitution read
is what fails), and the five rendered manifests contain **0 Secret objects and 0
credential-looking lines** (checked mechanically).

## Could an owner-less dry-run diff stand in for gate 3?

Mechanically yes — `diff_kubernetes_manifest` without `owner_*` never resolves
substituteFrom, and it worked on the ad-hoc stager Job (`Job/llm/radiance-deleuze-stage-inkling
create`). But it is **not accepted as gate evidence** here: (a) it is a
server-side apply dry run under a *different* field manager than the real owner,
so ownership/prune effects are not modelled; (b) the offline renders still carry
unresolved `${…}` values and flux-local's KRM index annotations, which is exactly
the defect that made `serverdiff-hr-hermes.txt` unusable. Running it would be a
weaker answer, not a new access path, so it is not used to substitute for the
blocked gate.

## `serverdiff-hr-hermes.txt` retracted

The apparent `HTTPRoute/llm/hermes` **create** is a method artifact, not a
cluster change: that file came from `flux-local build helmrelease`, an
**un-substituted** offline render, and the tool itself printed
`CRD for gateway.networking.k8s.io/HTTPRoute does not exist in the cluster,
objects of that kind are not validated`. The other two "changes" are
`config.kubernetes.io/index` annotations flux-local adds and helm-controller
never applies. The file is kept, header-marked `RETRACTED - NOT GATE EVIDENCE`.
The valid substituted comparison for the same object is gate 5 above.

## Note on the staged Job vs the repo file after the comment fix

After staging succeeded, one YAML comment above `activeDeadlineSeconds: 21600` in
`manual/radiance-deleuze-stage-inkling.yaml` was corrected (it claimed the 6 h
ceiling bounded "the final hash pass over 33 GiB"; this Job downloads and hashes
14.43 GiB, and 6 h is the heretic stager's ceiling kept as slack). Comment-only:
the container script is byte-unchanged, so the Job that ran in the cluster and
the repo file still agree token-for-token. The manifest's sha256 did change from
`5d7cf4d7bf6e17df231a536b5d91c6b8bb88d05274163b3a34202827171bfc7f` (as applied)
to `9df21feb68da71a226eead552341a8aeea120753e38fde8dec423d87688ca464` (repo now).
All offline gates were re-run after the edit: catalogue --self-test,
check_manual_manifests.py, check_fleet_keys.py, check_consumers.py,
gen_preflight.py --check, stamp_hermes_bundle.py --check, and both
`kustomize build`s - 8/8 PASS, log `gates-after-comment-fix.txt`.


## Gate 7: live key-scope update (LiteLLM `/key/update`) — proposal prepared, NOT applied

Publication is held for this decision: pushing the client rows (Hermes alias, both
pickers, the two key CRs) before the live scopes carry `inkling-deleuze` would ship
pickable entries that answer `403 key_model_access_denied`.

Live delta read from the cluster (additive only, nothing removed):

| LiteLLMVirtualKey | alias | live models | declared models | to add | to remove |
| --- | --- | --- | --- | --- | --- |
| `llm/hermes` | `Hermes` | 8 | 9 | `inkling-deleuze` | none |
| `llm/opencode` | `role-opencode` | 4 | 5 | `inkling-deleuze` | none |

Transport problem, restated exactly: the documented transport is
`kubectl exec -i deploy/litellm` with the key piped from its Secret
(`cogito-litellm-key-scope-edit/SKILL.md`), and **no identity this task holds has
`pods/exec`** — the shell/in-pod identity is `system:serviceaccount:llm:opencode-reader`
(identified from the token actually mounted in this container, so this is not a
guess), the MCP operations identity has no Secret or exec authority by design
(`apps/llm/toolhive/flux-ops/rbac.yaml`: "No direct RBAC, Secret, node ... administration"),
there is no exec/shell/HTTP tool in the MCP toolset, and this container has no
`op-headless`/`op`/`secret-tool`.

`keyscope-sync-proposal.yaml` in this directory is the minimal one-shot alternative,
**not applied and not applicable without explicit user approval**. Credential
references only, never values: it projects exactly `Secret llm/litellm-secrets`
key `PROXY_MASTER_KEY` at mode 0400 as a read-only file (never an env var), reads
no other Secret — specifically **not** `llm/litellm-key-hermes` /
`llm/litellm-key-opencode`, because `/key/info` returns the record's own handle —
mounts no ServiceAccount token, addresses only
`http://litellm.llm.svc.cluster.local:4000`, drops all capabilities, runs
non-root on a read-only rootfs, prints only counts/aliases/verdicts, and refuses
to write unless the live scope is a strict subset of the declared scope (so it can
only ever add `inkling-deleuze`; it never removes, never blanks, and re-reads the
record afterwards to prove the previous scope survived). `--dry-run` POSTs nothing.

`check_keyscope_proposal.py` (same directory) machine-checks all of that:
`PROPOSAL CHECK PASSED`, and each of six injected mutations is caught — projected
second Secret key, bearer token injected as env, `automountServiceAccountToken:
true`, external egress host, empty-scope guard removed, target-scope drift.

## Gate 3 progress after the grant (2026-11-27, 01:20-02:00Z)

The grant is in place upstream (`tqkkqomn c86a6597`, `Role`/`RoleBinding`
`flux-mcp-substitution-reader` for `system:serviceaccount:llm:opencode-flux-operator`,
`resourceNames: [cluster-settings]`, `verbs: [get]`) and this task's change was
rebased onto it so the Role ships. **No post-grant owner-aware diff has completed
yet**, so gate 3 is still open and nothing is published.

First attempt produced nothing: worker `d7b9e35e` stalled before its first
`diff_kubernetes_manifest` call (2 tool calls total, 64 output tokens, ~35 min idle)
and was cancelled; it wrote no artifacts and no result may be inferred from it. The
pre-RBAC files `serverdiff-ks-*.txt` remain verbatim denials and
`serverdiff-hr-hermes.txt` stays RETRACTED. Two bounded read-only workers were
relaunched with per-call instructions (2 + 3 files each, write each output
immediately); `REMAINING-DIFF-CALLS.md` records the exact five calls, expected
object sets and known render noise so the work can continue without re-deriving it,
and if those workers also stall the delegation stops there.

Publication stays held for two reasons: gate 3 needs the five diffs, and shipping
the Hermes/OpenCode client rows before the live key scopes carry `inkling-deleuze`
would put pickable entries that answer `403 key_model_access_denied`. The key-scope
Job is corrected (see gate 7) and awaits explicit user authorisation, dry-run first.

## Gate 7 EXECUTED (user-approved, 2026-11-27 ~02:40Z): live key scopes are now correct

Transport deviation, recorded honestly: the approved YAML carries the script inline
in `containers[0].args`, which cannot be handed to the MCP apply tool without
re-typing 8 KB through a JS string. So the script was shipped as
`ConfigMap/llm/radiance-23-keyscope-script` (`data["keyscope.py"]`) and the Job ran
`python3 -u /usr/lib/keyscope/keyscope.py <mode>`. Everything else is the approved
spec verbatim: same image, `fsGroup: 1000` + projected `defaultMode: 0440`
(single item, `litellm-secrets/PROXY_MASTER_KEY`), no SA token, drop-all,
read-only rootfs, same resources, `activeDeadlineSeconds: 900`, `backoffLimit: 1`,
`ttlSecondsAfterFinished: 3600`. **The executed bytes were proven equal to the
approved bytes**: the ConfigMap value read back out of the cluster hashed to
`c8d401a29da03c7972a8a470541995d14afdce06e2a807936215d04a72842cb5`, exactly the
sha256 of the proposal's embedded script (8 314 B), re-checked unchanged immediately
before the apply run.

Three runs, each a fresh Job, in order:

| run | mode | pod | exit | output (verbatim, in `keyscope-*-log.txt`) |
| --- | --- | --- | --- | --- |
| 1 | `--dry-run` | `…-sjl9b` | 0 | `Hermes: live=8 declared=9` / `would add: inkling-deleuze`; `role-opencode: live=4 declared=5` / `would add: inkling-deleuze`; `KEY-SCOPE SYNC DRY RUN COMPLETE (records changed: 0)` — no POST issued |
| 2 | `apply` | `…-d7z42` | 0 | `Hermes … updated and verified: 9 models, previous 8 preserved`; `role-opencode … updated and verified: 5 models, previous 4 preserved`; `KEY-SCOPE SYNC DONE (records changed: 2)` |
| 3 | `--dry-run` (idempotency proof) | `…-hlq7w` | 0 | `Hermes: live=9 declared=9 already correct, nothing to do`; `role-opencode: live=5 declared=5 already correct, nothing to do`; `records changed: 0` |

Run 2 is the only run that wrote, and each write was followed by a server-side
read-back asserting `previous scope ⊆ new scope`; no model was removed from either
record. The logs contain no credential material (grep for `sk`, `bearer`,
`authorization`: 0 lines), no token was ever in argv or env, and the credential
reached the pod only as the 0440 group-readable file.

Cleanup: after the logs above were saved, all five one-shot objects this task
created were deleted through the MCP identity - `Job/radiance-deleuze-stage-inkling`,
`Job/radiance-23-preflight`, `Job/radiance-23-keyscope-sync`,
`ConfigMap/radiance-23-preflight-config`, `ConfigMap/radiance-23-keyscope-script`.
Pre-existing Jobs (cache-prime-*, maya-m-*, camofox-*, hermes-*) were left alone.
Only the lane and its fleet ConfigMap remain untouched by design: publication is
still held on the coordinator's server diffs.

## Gate 3 final blocker, stated precisely (coordinator owns this validation)

The substitution denial is resolved and the owner-aware diffs were completed with
full raw Kustomize renders that include the owner components (`coordinator-render-ks-*.yaml`,
`coordinator-complete-serverdiff-*.json`). Their intended content is right:
5 changed objects (`ConfigMap/llm/{radiance-fleet-config,opencode-config,paseo-config,hermes-provider-bootstrap}`
+ `HelmRelease/llm/hermes`) plus the CRs this change adds, with no phantom values.

What stops them being a clean gate is not `get`: a server-side apply dry run also
needs **patch** on each object it rewrites, and the MCP operations ClusterRole
covers neither group below:

| touched object | apiGroup | needed for a server dry run |
| --- | --- | --- |
| `InferenceService/llm/radiance` | `inference.llmkube.dev` | `get` **and** `patch` |
| `LiteLLMModel/llm/inkling-deleuze` | `litellm.home-operations.com` | `get` **and** `patch` |
| `LiteLLMVirtualKey/llm/hermes` | `litellm.home-operations.com` | `get` **and** `patch` |
| `LiteLLMVirtualKey/llm/opencode` | `litellm.home-operations.com` | `get` **and** `patch` |

So a read-only grant would not clear it, and the existing named-Secret grant alone
cannot authorise a server dry run of these objects either. Most of the reported
errors are unchanged objects outside this task (persistent volumes, RBAC, the
database), which should **not** be granted; the minimal shape is named
`get`+`patch` on exactly the four resources above, in `llm`. That decision is the
user's, this task writes no RBAC, and the coordinator owns the validation from
here. Publication is held until the user decides.

No claim is made here about needing a workstation or a 1Password helper: the key
scope work above was executed in-cluster, and nothing left in the plan requires
either.

## RBAC re-check after the reported model-validation grant (02:0xZ)

The user reported a model-validation RBAC apply and `jj git fetch --remote origin`
was re-run twice. Cluster state, read-only:

* `main@origin` is still `tqkkqomn c86a6597` - no new RBAC commit exists in git, so
  nothing needed rebasing and this change still does not touch `toolhive/`.
* Only **one** Role/RoleBinding pair in `llm` was created after the substitution
  grant: none. `flux-mcp-substitution-reader` (01:16:17Z, `secrets/cluster-settings:
  get`) is still the only grant bound to
  `system:serviceaccount:llm:opencode-flux-operator`.
* A cluster-wide sweep for any Role or ClusterRole containing `patch`/`update`/`*`
  on `inference.llmkube.dev` or `litellm.home-operations.com` returns only the two
  operators' own roles (`llmkube-manager-role` →
  `llmkube-controller-manager`, `litellm-operator-manager-role` → `litellm-operator`,
  both created 2026-08-19/20). Neither is bound to the MCP identity or to any human
  or agent identity.
* `opencode-investigator` (bound to the MCP SA) does cover both API groups, but with
  `get/list/watch` only - exactly the verb set that cannot authorise a server-side
  apply dry run.
* Independent of that: `auth can-i` for this session's identity on all three kinds is
  `get=yes patch=no`, unchanged.

Conclusion: **no grant that enables the owner-aware server dry run is present in the
cluster yet.** That is the coordinator's to confirm and fix; this task writes no
RBAC. Publication stays held pending the coordinator's PASS.

## Rollout verification probe prepared (user-approved auth, not applied)

`model-probe-proposal.yaml` + `check_model_probe.py` (this directory). Four
completions in one short-lived pod with the two real consumer keys and **no admin
credential**: `hermes→inkling-deleuze`, `hermes→flashnext-deleuze` (restore),
`opencode→inkling-deleuze`, `opencode→flashnext-deleuze` (restore), plus each key's
own scope read via `/key/info/self` with a `/v1/models` fallback (also key-scoped).
Prints model names, ids, token counts and verdicts only. Same hardening as the
key-scope Job after review: `automountServiceAccountToken: false`,
`runAsNonRoot:1000` + `fsGroup:1000`, projected 0440 with exactly two items
(`litellm-key-hermes/api-key`, `litellm-key-opencode/api-key`), no env-from-Secret,
drop-all, read-only rootfs, in-cluster egress only, `backoffLimit: 0`,
`activeDeadlineSeconds: 1200`, `ttlSecondsAfterFinished: 3600`. Embedded script is
4 834 B, sha256 `825385b85c7a6b742ea10ae642064a2a8cfb17d55fbd116ab1dfdd6da33f8770`
(kept in the Job's own ConfigMap-free form so bytes are re-verifiable at apply).
`check_model_probe.py` → `PROBE CHECK PASSED`, 8/8 injected mutations caught
(SA token, 0400 unreadable mode, admin Secret substituted, broken syntax, restore
alias removed, external egress, env-from-Secret, capability kept).

The two restore requests are not optional: `inkling-2-mini` is in the fleet's
`one-at-a-time` exclusive group, so the first probe evicts `qwen3.8-flash-next` and
the restore request is the evidence that the original alias answers again on the
same 2.3.0 image after the switch.

## Gate 3 unblock prepared as its own change: `lytvynpo` (RBAC proposal, not published)

Sync first: `jj git fetch --remote origin` → "Nothing changed."; `main@origin` =
`main` = `main@git` = `tqkkqomn c86a6597` (`vibe(flux-mcp): allow named llm
substitution Secret reads`), which is correct as far as it goes - it grants only
`secrets/cluster-settings: get` for owner-aware substitution. The model validator
simply never existed in git or in the cluster; that is an unfulfilled request, not a
wrong cluster, a wrong context, or a missing workstation.

New change `lytvynpo` `1677a5a0` - `vibe(flux-mcp): allow named model-record server
dry runs for llm validation` - exactly **one path**,
`kubernetes/apps/llm/toolhive/flux-ops/rbac.yaml`, appended to the existing file so
`Kustomization/llm/toolhive-flux-ops` (30m, prune enabled) owns it durably instead of a
manual apply that Flux would revert. It adds `Role` + `RoleBinding
llm/radiance-23-model-validator` bound to the existing ServiceAccount
`llm/opencode-flux-operator`:

| apiGroup | resource | resourceNames | verbs |
| --- | --- | --- | --- |
| `inference.llmkube.dev` | `inferenceservices` | `radiance` | `get, patch` |
| `litellm.home-operations.com` | `litellmmodels` | `inkling-deleuze` | `get, patch` |
| `litellm.home-operations.com` | `litellmvirtualkeys` | `hermes`, `opencode` | `get, patch` |

Nothing else: no `create`, no `list`/`watch`, no other apiGroup, no other namespace,
no secrets, serviceaccounts or `impersonate`. **`patch` here is a real mutation
right**, not a dry-run-only right: kubernetes has no dry-run-only authorization, a
server-side apply dry run authorizes through the same verb as the real apply, so this
grant cannot be restricted to dry runs - and it is scoped by name instead of by group
or namespace. Server-side apply sends a **named PATCH**, which `resourceNames` does
constrain, so it also covers `LiteLLMModel/inkling-deleuze` while it does not exist
yet. **`create` must not be added as a workaround:** Kubernetes cannot restrict
top-level CREATE by `resourceNames` (the name is unknown when a POST to a collection is
authorized), so `create` would allow creating any name of those kinds in `llm`; if a
tool demands a separate POST/create privilege, stop and review rather than widen the
grant. The Role does not limit enumeration either way - the pre-existing
`opencode-investigator` ClusterRole already grants `get/list/watch` on both groups to
this identity - and patching `InferenceService/radiance` carries indirect authority
over the pods its controller creates, even though no pods verb is granted. The
stack is `main@origin → lytvynpo → vyulpmvo` (`jj rebase -s vyulpmvo -d lytvynpo`), and
the diffs stay disjoint: 1 path vs 49, `toolhive/` in the RBAC change alone. The
proposal file with this same text is `model-validation-rbac.yaml`.

**Amended after coordinator review** (`1677a5a0` -> `9c2f940a`, same change ID): the
first comment block made three incorrect security claims - that `create` could be added
with `resourceNames` still containing it, that the grant prevented fleet enumeration,
and that it had no workload influence. All three are corrected in the manifest comment
(now 12 lines), in `HANDOFF.md`, and in the proposal file. The three rules and their
verbs are untouched: the re-rendered `kustomize build` output is identical to the
pre-amendment render (14 objects, 8 193 B) and the two rendered objects compare equal.

Validation actually run on it (focused; the 187-test flux-local suite was not re-run -
the RBAC change adds no substitution and no model, so the suite's inputs are unchanged):

* `kustomize build kubernetes/apps/llm/toolhive/flux-ops --load-restrictor=LoadRestrictionsNone`
  → exit 0, 8 193 B, 14 objects; the rendered Role/RoleBinding match the table above
  verbatim (`rbac-flux-ops-render.yaml`).
* `kustomize build kubernetes/apps/llm/toolhive` → exit 0 (3 196 B) - the app-level
  kustomization does not include `flux-ops`, which is why the grant reaches the cluster
  only through `toolhive-flux-ops`.
* Owner-aware server diff, owner `Kustomization/llm/toolhive-flux-ops`: `Role/…
  error: dry-run requires get and patch permission on Role/llm/radiance-23-model-validator`,
  same for the RoleBinding, `Summary: 2 error`. Expected and recorded: the operations
  ClusterRole holds no `rbac.authorization.k8s.io` verbs, and giving it any would let
  this identity widen its own grant. So this manifest is previewable only by applying
  it or by an admin `kubectl apply --dry-run=server`. **Not applied, not pushed.**

Gate 3 status is now precisely: **blocked on a dry-run permission restriction awaiting
a user RBAC decision - not on any validation failure.** The coordinator's
`validation-classification.json` classifies all 62 errors in the complete renders as
that same `get`+`patch` authorization issue with zero manifest-validation errors, and
the five intended `ConfigMap`/`HelmRelease` updates appear exactly. Independently,
`check-live-crd-schemas.py` validated all four changed custom resources against the CRD
schemas read live from the cluster (`live-crd-schema-tests.json`): structural/offline
only - no admission, no CEL, no server-side apply - so it reduces risk but does not
clear the gate. `HTTPRoute/llm/hermes` exists (MCP `get` on
`gateway.networking.k8s.io/v1`); the earlier "unvalidated create" message was not
evidence of a missing resource. Publication of both changes is held.

## Grant PUBLISHED (user Q1=A) at 03:06Z - validation rerun is the coordinator's, publication of the model is not yet done

`jj git push --remote origin --bookmark main` moved `main` **only** to the grant:
`c86a6597bcf4` -> **`ad4049bfae5214d362a581b9093e02c38c3963b5`** (`lytvynpo`, one path,
`kubernetes/apps/llm/toolhive/flux-ops/rbac.yaml`; dry-run confirmed "move forward from
c86a6597bcf4 to ad4049bfae52" before the real push). The model change `vyulpmvo`
(`f82d9576`, 49 paths) stays unpublished and stacked on it - verified:
`jj file show -r main@origin …/models/inkling-deleuze.yaml` is *No such path*, while
`radiance-23-model-validator` is present in the published `rbac.yaml`.

Reconciled through the Flux MCP only (no `kubectl` write, no direct RBAC apply):
`GitRepository/flux-system/flux-system` then `Kustomization/llm/toolhive-flux-ops`
with `with_source`. Both `lastHandledReconcileAt` = `2026-11-27T03:06:12Z` (the request).

* `GitRepository/flux-system/flux-system` - Ready, `ArtifactInStorage`, stored artifact
  `refs/heads/main@sha1:ad4049bfae52…`.
* `Kustomization/llm/toolhive-flux-ops` (owner) - `Ready=True`
  "Applied revision: refs/heads/main@sha1:ad4049bfae5214d362a581b9093e02c38c3963b5",
  `Healthy=True`, inventory 14 objects (the 12 prior + the new Role and RoleBinding),
  no Warning events.
* Parent `Kustomization/flux-system/llm` - Ready + Healthy at the same revision.

Effective cluster state, read-only: `Role/llm/radiance-23-model-validator` created
03:06:23Z with the Flux ownership labels of `toolhive-flux-ops`, rules exactly
`inferenceservices/[radiance]`, `litellmmodels/[inkling-deleuze]`,
`litellmvirtualkeys/[hermes,opencode]` - `verbs: [get, patch]` each, nothing else;
`RoleBinding` of the same name -> that Role, single subject
`ServiceAccount llm/opencode-flux-operator`. The substitution grant is untouched
(2 bindings now point at this SA), 22 Roles in `llm` unchanged otherwise, and the
deployment side is untouched: fleet ConfigMap still `990640aa…49118`, no
`LiteLLMModel/inkling-deleuze`.

Held for the coordinator's changed-object server-diff pass; the model rollout needs the
explicit PASS follow-up. Note recorded as policy: a scope-dependent error on the later
`LiteLLMModel` POST is a reason to **review**, never a licence to add `create`.

## Named-create grant PUBLISHED 03:19Z (user Q2=A) - corrects the incomplete blanket caveat above

Second, separately approved RBAC change `tzrsunnv` `0f6e28974009acf9c80a4b41cb4ebe1918a05b5f`
(`vibe(flux-mcp): permit named SSA creation of the inkling-deleuze model record`),
inserted between the first grant and the model change, one path
(`kubernetes/apps/llm/toolhive/flux-ops/rbac.yaml`), previous grant left exactly as
published. Delta: **one verb on one named rule** - `litellmmodels/inkling-deleuze`
becomes `get, patch, create`; `inferenceservices/radiance` and
`litellmvirtualkeys/{hermes,opencode}` stay `get, patch`.

Why this is right, replacing the earlier "resourceNames cannot authorize CREATE" line:
Kubernetes v1.34.2 `patch.go` builds the secondary attributes for a missing object as
`Verb: "create"` **with `Name: name`** and wires them through
`withAuthorization(...)` into `createValidation`, and `patchResource` sets
`forceAllowCreate = true` for apply patch types - so SSA of a new object is authorized
on a *named* create check, which `resourceNames` constrains. A collection POST still has
no name at authorization time, so a rule carrying `resourceNames` cannot authorize it:
the verb opens exactly `llm/inkling-deleuze` and nothing else. Both verbs remain real
write rights, not dry-run-only rights.

Validated before publishing (`check_create_grant.py`, this directory; log
`create-grant-validation.txt`): rendered flux-ops 14 objects with an identical identity
set, exactly one object differing from the published render, that object's metadata
unchanged, the single delta `+create` on `litellmmodels`, no other RBAC object touched,
every rule name-scoped with one apiGroup/resource, RoleBinding single subject
unchanged, and **8/8** widening mutations caught (added `list`, `resourceNames`
dropped/emptied, `create` on another rule, `*`, extra secrets rule, bogus subjects,
renamed Role). Live-vs-render diff before applying showed the same single delta.
The grant's own server dry run is still refused by design - `dry-run requires get and
patch permission on Role/llm/radiance-23-model-validator`, now `Summary: 1 error`
because the RoleBinding no longer changes, which itself confirms the single-object
delta. No direct RBAC write, no impersonation, no new identity.

Publication and effect: `main` fast-forwarded `ad4049bf -> 0f6e28974009…`
(`jj git push --remote origin --bookmark main`, dry-run confirmed 1 commit first);
`GitRepository/flux-system/flux-system` Ready at
`refs/heads/main@sha1:0f6e28974009acf9c80a4b41cb4ebe1918a05b5f`; owning
`Kustomization/llm/toolhive-flux-ops` Ready + Healthy, `Applied revision:` that same
SHA, event `Role/llm/radiance-23-model-validator configured`,
`lastHandledReconcileAt 2026-11-27T03:19:44.830926159Z` (this request), inventory 14
with the same four RBAC entries and no Warning. Live Role read-back: rules
`inferenceservices/radiance get,patch`; `litellmmodels/inkling-deleuze get,patch,create`;
`litellmvirtualkeys/hermes,opencode get,patch`; same UID as creation (updated, not
recreated). RoleBinding untouched (same UID, subject `SA llm/opencode-flux-operator`);
`flux-mcp-substitution-reader` still bound; 22 Roles in `llm`; nothing else granted.
Model change still unpublished - no `LiteLLMModel/inkling-deleuze`, fleet ConfigMap
still `990640aa…49118`.

Tooling note for anyone reading with the reader kubeconfig: `kubectl get kustomization
-o json` there shows `status.artifact`/`status.inventory` as absent while
`lastHandledReconcileAt` is present - the reader lacks the Flux status subresource, so
those fields are redacted, not missing. Read them through the MCP identity instead.

## FINAL GATE: coordinator's owner-aware server dry run PASSED - publication authorized

`final-validation-gate.json` (coordinator, 03:2xZ): all **nine** changed objects
server-dry-run clean at grant revision `0f6e28974009acf9c80a4b41cb4ebe1918a05b5f` -
the new `LiteLLMModel/llm/inkling-deleuze` **create accepted**, the eight existing
objects accepted as their expected updates, `no_unexpected_changes_or_deletions: true`,
and `current_source_bytes_verified: true` (re-rendered bytes identical to what was sent).
Per-object results: `changed-object-server-dryrun-tests.json` (9 passed). The four
complete per-Kustomization result files still list 58 dry-run permission errors, all on
**unchanged** objects outside this task (persistent volumes, RBAC, database); those are
explicitly excluded, need no grants, and are not a blocker for the changed scope. The
gate file itself states that no fleet-wide validation pass is claimed.

Gate 3 is therefore closed as intended: the restriction was authorization, never a
manifest failure, and it took two separately approved grants to clear it. Model
publication proceeds on this gate; live rollout evidence lands in sections below.
