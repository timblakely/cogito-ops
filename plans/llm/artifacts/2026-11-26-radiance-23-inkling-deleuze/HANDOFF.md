# Handoff — this change is the Inkling deployment; both RBAC grants are already live

Updated 2026-11-27 03:25Z. **Both RBAC grants are published and live** (named
get+patch on four model records, plus `create` on the one new record), and the
coordinator's owner-aware server dry run of **all nine changed objects passed** at
grant revision `0f6e28974009acf9c80a4b41cb4ebe1918a05b5f` (`final-validation-gate.json`:
9 changed objects dry-run clean, new `LiteLLMModel` create accepted, zero unexpected
changes or deletions; 58 unchanged out-of-scope objects stay dry-run-inaccessible and
need no grants). Publication of this change is therefore authorized; whatever the read
commands below show is the state after it.

## 1. Repo state (verify with these commands)

```sh
jj git fetch --remote origin              # "Nothing changed." after the push
jj log -r 'main@origin::@' --no-pager     # only the unpublished model change
jj diff --name-only -r vyulpmvo | wc -l   # 49 paths, none in toolhive/
jj bookmark list main                     # main = tzrsunnv 0f6e2897 (second grant)
kubectl -n llm get role radiance-23-model-validator -o jsonpath='{.rules[*].verbs}{"\n"}'
```

| | |
| --- | --- |
| grant 1 (get+patch) | `lytvynpo` `ad4049bfae5214d362a581b9093e02c38c3963b5` — `vibe(flux-mcp): allow named model-record server dry runs for llm validation`, one path, applied 03:06:23Z |
| grant 2 (+create, one name) | `tzrsunnv` `0f6e28974009acf9c80a4b41cb4ebe1918a05b5f` — `vibe(flux-mcp): permit named SSA creation of the inkling-deleuze model record`, same single path, applied 03:19:44Z |
| unpublished task change | `vyulpmvo` `e8afdaf6` (change ID kept across every rebase, `jj edit` and `jj describe`), 49 paths |
| stack | grants are `main`'s two tip commits (`ad4049bf` then `0f6e2897`); this change is the single child, published as `main` on the PASS |
| consequence | three independent RBAC diffs, each separately approved and reviewable, all landed before the model change, so the model diff contains no privilege change |
| title | `vibe(llm): serve Inkling 2 Mini on the Deleuze radiance lane at radiance 2.3.0` |
| no PR | this repo publishes `main` directly (`jj bookmark set main -r vyulpmvo && jj git push --remote origin --bookmark main`) |

The model change's description already carries the executed evidence (staging digest,
`--check` exit 0, key-scope sync, cleanup); it will be rewritten to the deploy outcome
at publish time rather than growing further here.

## 2. Live facts already established (do not redo)

* **Weight staged:** `/models/radiance/inkling-2-mini-iq4r-v4.rad`, 15 496 360 448 B,
  sha256 `1522e6d7e0432cd8308ba0478a969d678648d0245983d05e964caecb4b03dcc9`
  (stager Job `succeeded=1`, "digest verified"/"ALL FILES STAGED").
* **Binary gate passed:** `radiance --check` on `radiance:2.3.0@sha256:1e0fe6a2…`
  exited 0, parsing all five fleet entries, last
  `model inkling-2-mini = /models/radiance/inkling-2-mini-iq4r-v4.rad, tp 2`, after
  a weight probe on the real claim. The fleet bytes it checked are byte-identical to
  this change's ConfigMap: 25 277 B, sha256 `3cbc1313c0244363a5d1d57f084307671f35f6f5dafb079214fd054b713ba173`.
* **Key scopes already correct in LiteLLM's DB** (user-approved Job, dry-run →
  apply → dry-run): `Hermes` 8→9, `role-opencode` 4→5, adding only
  `inkling-deleuze`, each write confirmed by a read-back asserting the previous
  scope survived, third run reporting "already correct, nothing to do".
  **Therefore the client rows in this change land on scopes that already allow the
  alias — no 403 window exists after publication.**
* **Offline gates:** `validate-llm-catalogue.py --self-test`, the three artifacts
  validators, `gen_preflight.py --check`, `stamp_hermes_bundle.py --check`, both
  `kustomize build`s — 8/8 PASS on the rebased tree; `flux-local test` 187 passed /
  2 deselected (CI's own deselections) with pip `flux-local 8.4.0`, **not** the
  CI-pinned image `sha256:c0be852e…`; `check_keyscope_proposal.py` catches 9/9
  injected mutations.
* **Lane untouched:** `ConfigMap/llm/radiance-fleet-config` is still baseline
  `990640aa9027a3a744892735db3a3e852e737b5326d5bed2c2d1d7afa4f49118` and contains no
  `inkling`; the Deployment still pins 2.2.0.
* **One-shot resources cleaned:** stager Job, preflight Job + fleet-copy ConfigMap,
  keyscope Job + script ConfigMap — all deleted after their logs were saved.

## 3. What was blocking validation, and the grants that remove it (03:06Z get+patch, 03:19Z +create)

A server-side apply dry run needs **`get` AND `patch`** on every object it rewrites —
it resolves field ownership through the same code path as a real apply, and
kubernetes has no dry-run-only authorization. Read-only verbs cannot satisfy it, and
the named-Secret grant (`c86a5e`, correct as far as it goes) is unrelated to it. The
four objects that need it here, all in `llm`:

| object | apiGroup |
| --- | --- |
| `InferenceService/llm/radiance` | `inference.llmkube.dev` |
| `LiteLLMModel/llm/inkling-deleuze` | `litellm.home-operations.com` |
| `LiteLLMVirtualKey/llm/hermes` | `litellm.home-operations.com` |
| `LiteLLMVirtualKey/llm/opencode` | `litellm.home-operations.com` |

This is a **dry-run permission restriction, not a validation failure.** The
coordinator's complete substituted renders (`coordinator-render-ks-*.yaml`,
`coordinator-complete-serverdiff-*.json`, and the targeted
`coordinator-complete-serverdiff-target-{radiance,litellm}.json`) report the intended
5 changed `ConfigMap`/`HelmRelease` objects with no phantom values; every error in
them is either a `get`+`patch` refusal or an unchanged out-of-scope object (persistent
volumes, RBAC, the database), which needs no grant. **No changed-config manifest has
failed validation.** Nothing here is a cluster/context mismatch and nothing needs a
workstation: the missing validator Role simply was never in git or in the cluster.

**Durable grant, published and live as of 03:06Z:** jj change `lytvynpo`
`ad4049bfae5214d362a581b9093e02c38c3963b5`, `vibe(flux-mcp): allow named model-record
server dry runs for llm validation`, exactly one path —
`kubernetes/apps/llm/toolhive/flux-ops/rbac.yaml` (added to the existing file rather
than a new one, so Flux's `Kustomization/llm/toolhive-flux-ops` reconciles it and a
manual `kubectl apply` cannot silently drift away — and it did land through Flux:
owner labels present, inventory 14 objects, `Applied revision:
refs/heads/main@sha1:ad4049bfae52…`). It adds `Role`/`RoleBinding llm/radiance-23-model-validator`
bound to the existing `llm/opencode-flux-operator` ServiceAccount: `get`+`patch`, with
`resourceNames` limited to `inferenceservices/radiance`,
`litellmmodels/inkling-deleuze`, `litellmvirtualkeys/{hermes,opencode}`. No `create`,
no `list`/`watch`, no other apiGroup, no other namespace, no secrets, serviceaccounts
or `impersonate`. Three precise limits on what this does and does not achieve, all
stated in the manifest's own comment too:

* `patch`/`create` are **real write capabilities** on those named objects, not
  dry-run-only rights — the dry run and the mutation authorize through the same verb.
* A **missing** object needs a second, *named* create authorization: v1.34.2 `patch.go`
  builds the attributes for that case as `Verb: "create"` with `Name` set and runs them
  through `createValidation` when apply creates the object, so `get`+`patch` alone could
  not dry-run the new `LiteLLMModel/inkling-deleuze`. `create` was therefore added for
  that one name in a second approved change (`tzrsunnv`, published
  `0f6e28974009acf9c80a4b41cb4ebe1918a05b5f`), and it stays narrow for a mechanical
  reason: a POST to a collection has no name at authorization time, so a rule carrying
  `resourceNames` cannot match it. (Earlier text here claimed `resourceNames` could not
  help with CREATE at all — that was incomplete, corrected in both the manifest comment
  and the gate ledger.)
* This Role does **not** limit enumeration. The pre-existing `opencode-investigator`
  ClusterRole already grants `get/list/watch` on both API groups to this same identity;
  this Role adds no list/watch verbs. And it grants no direct pods rights
  directly, but patching an `InferenceService` does steer the pods its controller
  creates — indirect workload authority is part of what `patch` on that object means.

The Inkling deployment change `vyulpmvo` (`f82d9576`) sits **on top of the published
grant** (`main@origin → vyulpmvo`, ahead by 1, unpublished), and the two diffs stayed
disjoint by construction: 1 path vs 49, `toolhive/` in the grant only.

**Chicken-and-egg, now closed by publication.** Before the grant existed, a server dry
run of *the RBAC manifest itself* was refused — `Role/llm/radiance-23-model-validator
error: dry-run requires get and patch permission on Role/llm/radiance-23-model-validator`,
same for the RoleBinding, `Summary: 2 error` — because the operations ClusterRole holds
no `rbac.authorization.k8s.io` verbs at all. Adding those would let the identity widen
its own grant, so it was deliberately excluded: the grant was validated by the
`kustomize` render (rules byte-equal before and after the comment amendments), the
rendered-object comparison, review, and then by applying it through GitOps and reading
the effective Role/RoleBinding back. That is the only honest way to validate an
authorization change; a human with admin access could also have run
`kubectl apply --dry-run=server` on it.

**What has been verified despite the blocked gate** (coordinator-owned evidence, cited
not duplicated here — the JSON lives in `/tmp/opencode/radiance-230-deploy/`, kept out
of the repo on purpose): `validation-classification.json` classifies **all 62** errors
in the complete owner-aware renders as server dry-run `get`+`patch` authorization,
**zero** manifest-validation errors, with the five `ConfigMap`/`HelmRelease` updates
exactly as intended. `check-live-crd-schemas.py` validated **all four** changed custom
resources against the CRD schemas read live from the cluster (`live-crd-schema-tests.*`,
`schema-*.json`). That is **offline structural validation only** — no admission, no CEL
`x-kubernetes-validations`, no server-side apply — so it narrows the risk but does not
clear the gate. `HTTPRoute/llm/hermes` was confirmed to exist through the MCP read path
(`gateway.networking.k8s.io/v1`); an earlier tool message about an "unvalidated create"
was not evidence of a missing resource.

## 4. Runbook for this deployment (PASS recorded; steps 2-6 are the rollout itself)

1. Re-check nothing moved: `jj git fetch --remote origin`, confirm `main@origin` is
   still `tzrsunnv 0f6e2897` (the second grant; `lytvynpo ad4049bf` is its parent). If the coordinator has since built on it,
   fetch, inspect the new commits and rebase `vyulpmvo` onto the new tip rather than
   pushing past their work. Then `jj bookmark set main -r vyulpmvo` and
   `jj git push --remote origin --bookmark main` — a fast forward by exactly 1 commit,
   49 paths, verified with `--dry-run` first. Rewrite `jj describe` to the deploy
   outcome at this point, not before.
2. Reconcile in dependency order and **verify revision, not just Ready**:
   `flux reconcile source git flux-system -n flux-system`, then
   `flux reconcile kustomization llmkube-resources -n llm --with-source`,
   `litellm`, `opencode`, `hermes`. Read
   `.status.artifact.revision` on the GitRepository and each Kustomization and
   compare with the pushed SHA.
3. Confirm the rollout actually landed, all read-only:
   `kubectl -n llm get cm radiance-fleet-config -o jsonpath='{.data.radiance\.yaml}' | sha256sum`
   → must equal `3cbc1313c024…3ba173`;
   `kubectl -n llm get pod -l <radiance lane selector> -o jsonpath='{…imageID}'`
   → must end in `@sha256:1e0fe6a2c310e483e9e66e8446ba274ee767f06044f6761ababd593d7517af12`;
   lane startup log must list five models with no fleet-key error;
   `LiteLLMModel/llm/inkling-deleuze` Ready and the alias present in `/v1/models`
   for the affected keys; `Deployment/hermes` rolled once on the new
   `bundle-sha256` annotation and Ready.
4. Expect and accept: the fleet ConfigMap write deletes the lane pod ~1 s later
   (`waitForIdle: false`), the first `inkling-deleuze` request displaces
   `qwen3.8-flash-next` and re-prefills live conversations, and `inkling` reports
   `supportsVision: false` with no model-caps entry on purpose until an image is
   probed on gfx1201.
5. Live proof, then restore, with `model-probe-proposal.yaml` (user-approved auth:
   it projects only `litellm-key-hermes`/`litellm-key-opencode` `api-key`, no admin
   credential, no SA token, 0440 + fsGroup 1000, in-cluster egress only;
   `check_model_probe.py` passes with 8/8 injected mutations caught; embedded script
   4 834 B, sha256 `825385b85c7a6b742ea10ae642064a2a8cfb17d55fbd116ab1dfdd6da33f8770`).
   It runs four completions - `hermes→inkling-deleuze`, `hermes→flashnext-deleuze`,
   `opencode→inkling-deleuze`, `opencode→flashnext-deleuze` - plus each key's own
   scope read, and prints names/ids/counts only. The restore requests are mandatory
   evidence, not courtesy: the exclusive group means probe 1 evicts
   `qwen3.8-flash-next`, so probe 2 is what proves the agent lane answers again.
   Confirm afterwards from the lane pod: `restartCount: 0`, the reload/evict lines,
   flashnext resident, and the Deployment still on
   `@sha256:1e0fe6a2c310e483e9e66e8446ba274ee767f06044f6761ababd593d7517af12`.
   Delete the probe Job once its log is saved.
6. Report published SHA + deployed image digest + the completion evidence. No PR.

## 5. Evidence index

`plans/llm/artifacts/2026-11-26-radiance-23-inkling-deleuze/`
(`gate-status-2026-11-27.md` is the running per-gate ledger, mirrored at
`GATE-STATUS.md`): `keyscope-{dryrun,apply,verify-dryrun}-log.txt`,
`keyscope-script.py`, `keyscope-sync-proposal.yaml`, `check_keyscope_proposal.py`,
`preflight-{pod,weight-init}-log.txt`, `live-preflight-fleet-bytes.yaml`,
`live-stager-script.py`, `live-diff-ks-llm.patch`, `live-diff-hr-hermes.patch`,
`gates-*.txt`, `serverdiff/` (pre-RBAC denials, kept as history),
`REMAINING-DIFF-CALLS.md` (superseded by the coordinator's own renders),
`REPORT.md`, `COMMANDS.md`.
