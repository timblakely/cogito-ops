# Radiance image upgrade on a cogito lane

Reference: `kubernetes/apps/llm/llmkube/resources/radiance-deleuze.yaml`
(`InferenceService/radiance`, runtime `generic`, TP2 on deleuze's two R9700s).

## Pinning convention
The lane pins the **amd64 image digest**, NOT the manifest-list digest, with the
tag kept for readability: `...radiance:1.10.0@sha256:bb65a0a9...` (its list
digest was `cdf6cc7a...`). Read both from Docker Hub — the tag object's `.digest`
is the list, `.images[].digest` is per-arch:

```sh
curl -s https://hub.docker.com/v2/repositories/stilldeadcode/radiance/tags/1.11.0 \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['digest']);[print(i['architecture'],i['digest']) for i in d['images']]"
```

## This jj working copy is shared with other agent sessions
Another session commits and pushes `main` while you work. Uncommitted files
sitting in `@` get swept into THEIR commit (observed 2026-10-23: my new
benchmark artifacts directory was committed and pushed inside an unrelated
`vibe(llm)` gemma-4-12b commit). So: commit your own paths promptly, and before
assuming a change still needs publishing check `jj file show -r main -- <path>`
rather than `jj status`. Never rewrite the shared history to unmix it — add a
focused follow-up instead.

## Gate set for a version bump
1. `~/.local/share/mise/shims/kustomize build .../llmkube/resources` must render;
   grep the rendered output for the new digest.
2. Per-lane duplicate-flag check (argparse keeps the LAST occurrence and only
   logs "Found duplicate keys"): slice the single rendered document with
   `awk '/^# Source: .*radiance-deleuze.yaml/{f=1} f&&/^---/{f=0} f'`, then
   `grep -oE -- '--[a-z0-9-]+' | sort | uniq -d` must be empty.
3. `kubectl apply --dry-run=server -f <file>` — CRD schema + llmkube admission.
4. `.venv/bin/python scripts/validate-llm-catalogue.py --self-test` (cheap).
5. The owning Flux KS for `resources/` is `llmkube-resources` in ns `llm` (the
   app dir has its own separate `llmkube` KS).

## Radiance release facts that matter when bumping
- Codeberg serves `/tags` fine but poisons `/compare`, `/src/tag` and `/raw`
  with anti-AI junk — clone the repo and diff the tag range (`git log vA..vB`).
  Tags carry no release notes; derive "what's new" from commits + README diff.
- 1.11.0: plugin ABI 25 -> 26 (`rad_kernel_chain`, `RAD_LAYOUT_ANY`). Plugin ABI
  only — there is NO container-format version bump, so existing `.rad` weights
  load unchanged; two new server flags (`--control-vector`, `--attn-prefill-fp8`),
  none removed.
- `--control-vector` defaults to `disabled` (safe), but the image can ship a
  per-family vector file plus a `POST /admin/control-vector` admin endpoint that
  is keyless from LOOPBACK. A lane with no `--api-key` relies on its OIDC
  HTTPRoute, so any in-cluster pod hitting the pod IP could flip it.
- Kernel chaining auto-enables only when `--num-speculative-tokens > 0` AND the
  arch plugin sets `RadArchProbe::chain_pays` (in 1.11: only the Gemma 4 DFlash
  drafter) AND the `aql` device backend. MTP-drafted lanes are unaffected.
- Only `glm5next` declares `rad_kv_group_replicated` KV groups, so other archs
  never hit the new KV-tier startup refusals.

## Freeing a retired lane's host data (Talos)

A static local `PV` with `Retain` leaves its directory behind when Flux deletes the
`PV`/`PVC`; deleting manifests never frees disk. Procedure that worked on Iggy
(2026-10-23, freed 164 GiB):

1. Prove orphanhood from the API: `kubectl get pv|pvc -A -o json | grep -c <name>`
   and the same over `kubectl get pods -A -o json` must all be 0.
2. Prove it from the node with a privileged `alpine` pod (image already cached on the
   node, so no pull) that mounts `hostPath: /` and sets `hostPID: true`. Guard before
   `rm -rf`: exact basename, not a symlink, and `grep -qF " <path> " /proc/1/mounts`
   empty (that is the HOST mount namespace; `/proc/mounts` in the container is not).
3. Print `du -sh`, per-subdir `du`, `df -h` before and after, and re-list the paths you
   meant to KEEP in the same pod so one manifest does both verification halves.

Pitfalls:
- Mount `hostPath: /`, NOT `hostPath: /var/lib/kubelet`. On Talos mounting the kubelet
  dir directly yields an apparently empty tree (the probe reported the live directory
  as "absent"), which can talk you into concluding there is nothing to clean.
  `talosctl -n <node> ls /var/lib/kubelet` is a cheap second opinion.
- Never `grep -r <name> /var/lib/kubelet/pods` on a node: pod dirs bind-mount real
  volume data, so the scan runs into hundreds of GiB and never finishes (a 400 s
  timeout was pure scan, no deletion). Grep `allocated_pods_state` /
  `actuated_pods_state` and `find /host/var/lib/kubelet/pods -maxdepth 4 -name` instead.
- Expect more than one orphan: an earlier PV revision's path can linger as an empty
  stub next to the real one (Iggy had `/var/lib/flashnext-iggy-ngram` alongside the
  live-path directory). Sweep with `find /host -maxdepth 4 -name '<pattern>'`.
- Retain-policy leftovers that must survive: `local-hostpath/flashnext` (the retained
  requantised weights) and anything a live claim still binds. `kubectl get pv -o
  custom-columns=NAME:.metadata.name,PATH:.spec.local.path,STATUS:.status.phase`
  tells you which host paths are still owned.

## Deferred on the Deleuze lane
`--api-key` is absent, so 1.11's `POST /admin/control-vector` is reachable
unauthenticated from the pod network (the lane relies on the OIDC `HTTPRoute`). The fix
is `--api-key` in engine args + matching key in `litellm/app/models/flashnext-deleuze.yaml`
+ a Secret, as one dedicated change; user deferred it on 2026-10-23. A `Released` PV's `capacity.storage` is a claim, NOT evidence that bytes exist — the
`flashnext-amnesia` PV advertised 140 GiB while its host directory had already been
wiped by an earlier runbook, so the only orphan was the object itself. Always stat the
host path (`du -sh`, plus `df` before/after) before telling the user how much disk a
PV is holding, and check what else lives in the same base directory: on Amnesia the
only large `local-hostpath` occupant is `dreamcast/tim-steam`, the gaming library.

Still open on the cluster: several `Released` PVs for `home-infra`/`tools` StatefulSets
(kopiur caches, immich-db-1, atuin-db-1, knowledge-db-1) — unrelated to LLM lanes and
untouched.

## Re-running the Deleuze perf suite on a new version
Harness lives in `plans/llm/artifacts/2026-10-21-radiance-deleuze/`
(`run-profile.py` + `summarize.py`; copy both into a new dated dir at the SAME
depth — `run-profile.py` derives the repo root from `parents[4]`). Stdlib-only,
so any python works.

- The suite needs its OWN pod (`radiance-bench-current`, profile JSON in
  `profiles/`, nodeSelector deleuze, `amd.com/gpu: 2`, `--no-prefix-cache`) on
  both R9700s, so the serving lane MUST be suspended. There are only two cards.
- Outage is ~4 minutes per case, not tens: pod Ready in ~25 s (weights are
  mmapped), full common+decode+pp+c2+smoke in ~3 min. Sequence that worked:
  `flux suspend kustomization llmkube-resources -n llm` → `kubectl patch
  inferenceservice radiance -p '{"spec":{"suspend":true}}'` → apply bench pod →
  harness → all of it reverted inside a `trap ... EXIT` (delete pod,
  `suspend:false`, `flux resume`, reconcile, wait Ready, re-read `/server_info`).
  Run it as `terminal(background=true, notify=true)`: the agent's own model IS
  that lane, so nothing may depend on a live turn during the window.
- Pin the corpus digest before benching:
  `/tmp/deleuze-radiance/aider-chat-history.md` must be
  `a9a89dfd830af253103f86ff25dcba55364b22db779664d2fb36a3c2fd058710`
  (recorded in `pp-corpus-provenance.json`).
- `summarize.py` yields `short_warm_decode_tps`, `short_warm_ttft_s`,
  `long_median_ttft_s`, `long_median_decode_tps`, `long_median_wall_s`,
  `pp8192_mean_tps`, `pp32768_mean_tps`, `pp65536_mean_tps`, `c2_long_wall_s`.
  It has NO `__main__` guard — importing it runs it and rewrites `summary.json`
  in its own directory.
- **Cross-run comparisons need an identical procedure.** The October baselines
  were run with `--original` (four warm cells replayed before the scored suite)
  and the plan doc warns that startup history "matters most to the short
  trials"; a run without it is not paired with them. Same-flag spread across the
  October repeats was ~0.6% on short warm TG, so treat <2% as noise unless the
  two runs were back-to-back with the same flags and the same order.
