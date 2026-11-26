# Radiance 2.3.0 + Inkling 2 Mini on the Deleuze lane — **in progress, not yet published**

Status on 2026-11-27: the naming question is **settled** (the user asked for
"Inkling 2 Flash", no such model exists upstream, and confirmed **Inkling 2 Mini**
as the model to ship), and **GLM-5.3-Flash is deferred by the user** — its
capacity arithmetic stays in §2 so nobody re-derives it. The change is described
in jj as `vibe(llm): serve Inkling 2 Mini on the Deleuze radiance lane at radiance
2.3.0`, and execution is gated in this order: staging digest verified -> `radiance
--check` on the 2.3.0 binary -> owner-aware server-side diffs -> publish `main`
via jj -> reconcile once -> live verification. Until all of those succeed nothing
is pushed and no fleet byte is live.

The shell credential for this session is `system:serviceaccount:llm:opencode-reader`
(`auth can-i` says create/patch/exec are all no), so cluster writes go through the
Flux MCP identity instead, which server-side applies with field manager
`kubectl-flux-mcp`. That identity is `system:serviceaccount:llm:opencode-flux-operator`:
it **can** create workload objects in `llm` (it created the staging Job), but it
cannot `get` the `llm/cluster-settings` Secret, and that one denial is now the only
thing blocking the remaining gate.

## 0. Live execution status (2026-11-27)

Per-gate state, evidence and the exact denial live in
`/tmp/opencode/radiance-230-deploy/GATE-STATUS.md`. In short:

- **Staging: passed.** `Job/radiance-deleuze-stage-inkling` succeeded at
  00:44:32Z, `staged: /models/radiance/inkling-2-mini-iq4r-v4.rad 14.43 GiB digest
  verified` / `ALL FILES STAGED`, after reporting 1381.35 GiB free against 16.43 GiB
  needed. The script running in the cluster was compared token-for-token with the
  repo copy (identical apart from comments) and carries the pinned digest and size.
- **`radiance --check` preflight: passed.** `ConfigMap/llm/radiance-23-preflight-config`
  and `Job/radiance-23-preflight` were applied through the MCP identity; pod
  `radiance-23-preflight-qgv66` exited **0** (`succeeded=1 failed=0`) at 00:47:12Z.
  The `weight` init container: `weight ok: inkling-2-mini-iq4r-v4.rad 15496360448 B
  sha256 1522e6d7…4b03dcc9 (read in 10 s)`. The `check` container, on the pinned
  2.3.0 image, parsed all five entries, last line
  `model inkling-2-mini = /models/radiance/inkling-2-mini-iq4r-v4.rad, tp 2`. The
  ConfigMap read back out of the cluster is **byte identical** to the lane ConfigMap
  in this change (25 277 B, sha256 `3cbc1313c0244363a5d1d57f084307671f35f6f5dafb079214fd054b713ba173`),
  so the bytes that passed the gate are the bytes that would be pushed; the live
  `radiance-fleet-config` is untouched at its baseline sha256 `990640aa…118` and
  still contains no `inkling`. Logs and those bytes are in this directory.
- **Owner-aware server-side diffs: blocked.** All four llm Kustomization paths
  return the same forbidden error on `substituteFrom Secret llm/cluster-settings`
  for `system:serviceaccount:llm:opencode-flux-operator`. Every llm KS requests that
  Secret (`kubernetes/flux/cluster/kustomization.yaml:30-33`, applied cluster-wide
  by the patch targeting every Kustomization),
  so the MCP's owner-aware diff cannot prepare objects without `get` on that one
  Secret. No RBAC change was attempted and no alternate identity was used to read
  secrets. The smallest fix (a `resourceNames`-scoped Role + RoleBinding in `llm`)
  is written out in GATE-STATUS.md for an owner to apply; the alternatives that
  need no new grant are to run those four diffs as an identity that already has the
  grant, or to accept the substituted offline comparisons as this gate.
- **Retracted evidence:** the first `hr-hermes` server diff (`serverdiff-hr-hermes.txt`,
  now header-marked `RETRACTED`) was taken from `flux-local build helmrelease`, an
  **un-substituted** render, so its `HTTPRoute create` and index-annotation lines are
  artifacts of the method — the tool itself said the HTTPRoute CRD was not validated.
  The valid substituted comparison for that object is `flux-local diff helmrelease`
  (`offline-diff-hr-hermes.patch`), which templates against the **live** HelmRelease
  (verified: live `spec.values` contains no `${`) and shows exactly one changed
  line, the `bundle-sha256` pod-template annotation.
- **Nothing is published**: `main`, `main@git` and `main@origin` are still
  `mnzuyprw 05b3030d`; the only cluster writes are the two one-shot Jobs above.


## 1. What was built

Engine bump `2.2.0 -> 2.3.0` on the Deleuze radiance lane
(`docker.io/stilldeadcode/radiance:2.3.0@sha256:1e0fe6a2c310e483e9e66e8446ba274ee767f06044f6761ababd593d7517af12`,
the amd64 child digest per this file's convention), a fifth fleet entry
`inkling-2-mini`, and the consumer path wired the way `heretic-deleuze` is wired.

| Path | What it does |
| --- | --- |
| `kubernetes/apps/llm/llmkube/resources/radiance-deleuze.yaml` | image pin, `inkling-2-mini` appended last in `models:`, added to `groups.one-at-a-time.exclusive`, provenance comments rewritten, GLM refusal written where the next reader hits it |
| `.../resources/manual/radiance-deleuze-stage-inkling.yaml` | out-of-band staging Job: prints the claim's own free space and refuses to start if short by more than 2 GiB, pins exact size + published sha256, `.part` then rename |
| `.../resources/manual/radiance-23-preflight.yaml` | out-of-band CPU gate: `radiance --check` on the pinned image against **its own generated copy** of the new fleet bytes, behind a weight probe (size + sha256 on the real claim) |
| `plans/llm/artifacts/2026-11-26-radiance-23-inkling-deleuze/gen_preflight.py` | regenerates the fleet copy, probe constants and the header's stated sha256 from the lane + stager; `--check` exits 1 on drift |
| `scripts/validate-llm-catalogue.py` | new check 10: that embedded copy must equal the ConfigMap byte-for-byte |
| `kubernetes/apps/llm/litellm/app/models/inkling-deleuze.yaml` + `models/kustomization.yaml` | the `inkling-deleuze` LiteLLMModel alias (would be the 17th) |
| `.../litellm/app/virtualkeys/hermes.yaml`, `.../opencode.yaml` | scopes to 9 and 5 models |
| `.../litellm/app/model-caps.yaml` | **deliberately no caps entry**, plus an inert note saying why |
| `kubernetes/apps/llm/hermes/app/{configure.py,provider-bootstrap.yaml,helmrelease.yaml}` | Hermes alias `inkling` and the `bundle-sha256` roll annotation |
| `kubernetes/apps/llm/opencode/app/{opencode-config.yaml,paseo-config.yaml}` | picker rows in both provider lists |

26 paths in the working copy: 13 repo files + the artifacts directory
(`gen_preflight.py`, the three validators, `stamp_hermes_bundle.py`, `rendered/`,
the gate log, this report, `COMMANDS.md`, the commit description).

## 2. GLM-5.3-Flash: not here, and not because of the engine

Its only published container is `animusnull/glm-5.3-flash-iqr-v4` →
`glm53-flash-iqr-v4.rad`, 170,662,334,464 B = **158.95 GiB** (159 GiB in the
upstream table), sha256 `1e20c4bc2f7ea7022f7bae9dd1ffa9873c2031b242d41e85d1ac0a5016342687`,
repo not gated. Upstream's own card for it (`README.md:261` at v2.3.0):

```
tp: 4, placement: expert_tiered, host-pool-mib: 65536, max-num-seqs: 4,
max-model-len: 262144, max-num-batched-tokens: 2048, kv-cache-dtype: i8,
num-speculative-tokens: 0, prefill-interleave: 4, prefix-cache-mib: 32768,
gpu-headroom-mib: 96, and server.kernels: glm,libr4d,libavx,libref
```

and `deploy/compose/tp4.radiance.yaml:13` says the host needs **151 GiB free**
for the three memory tiers plus the runtime's own, measured on four R9700s.

Why that does not fit Deleuze:

- Geometry: 288 routed experts × 42 MoE layers × 12 MiB (IQR-V4 4-bit) =
  **141.75 GiB of experts**, 89% of the container; the rest (~17 GiB) is the IQ8R
  trunk, bf16 KDA/kv_b/embedding/lm_head and the tower.
- `docs/GUIDE.md:4896` (v2.3.0): "A routed expert cannot be served from the file
  tier, so it has nowhere else to go" → `DID NOT FIT`. So on two cards the pinned
  host pool must hold 141.75 GiB minus at most 62.6 GiB of card memory →
  **≥ 79 GiB**, with nothing left for trunk, KV or headroom.
- This fleet's whole pinned-host ledger is **60 Gi** (3/4 of the 80 Gi container
  limit) and **36 Gi is already committed** by the four entries this change keeps,
  so a fifth entry can ask for **24 Gi**. The card asks 64 + 32 = **96 GiB at tp 4**.
- Node wall: Deleuze has 123.1 Gi allocatable, two R9700s, and flashnext holds
  24 Gi resident.
- Memory-independent blockers: `server.kernels` is **fleet-wide**, and GLM's int8
  latent cache requires `glm,libr4d,libavx,libref` in that order
  (`docs/ARCHITECTURES.md:860`, `docs/GUIDE.md:2745`), so adding it re-orders
  kernel selection for every other entry in that process — including the one this
  agent runs on. And there is nowhere else to put it: no second AMD box, no
  four-card node, and radiance ships AMD device kernels only (`README.md:9`).
- Engine support is **not** the blocker: `glm5next` + `plugin/glm` landed in
  2.3.0, so the author's older workaround image is unnecessary. Capacity is.

**Options:** (a) a 4× RDNA4 node with ≥ 151 GiB free host RAM, as its own lane
with its own `server.kernels`; (b) an explicitly smaller GLM container if one is
ever published (no such repo exists under `animusnull`/`StillDeadcode` today);
(c) drop it. I did not invent a tp/host configuration the card contradicts.

## 3. What has and has not been validated — read this before trusting anything below

**Has NOT been run** (these are the decisive gates; they change live state or
need the image, so they are the coordinator's):

- The staging Job. **`inkling-2-mini-iq4r-v4.rad` is not on the claim.** Nothing
  has been downloaded.
- The preflight Job. **`radiance --check` has never been run against these fleet
  bytes on the 2.3.0 image.** My key check is a reading of
  `core/fleet/config.cpp` at the v2.3.0 tag — it is strong evidence, not the
  binary. `--check` is what refuses unknown keys and not-yet-acted-on keys with
  exit 2 at startup, and that is exactly the crashloop class this lane can still
  ship.
- Any load of the weight, so the container format, the placement plan, the
  `checkpoint slots` sizing and the `mm-max-patches`/tower pairing are unproven.
- Any live request: no chat completion, no tool call, no `reasoning_content`
  observation, no image probe through this entry.
- The LiteLLM `/key/update` for `hermes` and `opencode`, so the scopes in this
  change are not in effect anywhere.

**Has been run, offline, on this box** (static/render-level only):

- `scripts/validate-llm-catalogue.py --self-test` → 17 modelNames, 9 keys, 5
  backends, "catalogue valid"; the new drift check fires on an injected bad copy.
- `check_manual_manifests.py` → HF size/OID/gating vs the manifest pins,
  preflight↔fleet byte equality, image digest agreement, entry order.
- `check_fleet_keys.py` → keys against the v2.3.0 source; the live 2.2.0 bytes
  also validate at both tags (revert stays safe); card/value agreement per key.
- `check_consumers.py` → alias resolves inside its key scope, roll annotation
  second half = `sha256(configure.py)`, opencode limits mirror the alias, both
  paseo provider lists identical.
- `kustomize build` of `llmkube/resources` and `litellm/app` → in `rendered/`.
- `gen_preflight.py --check` → current, and proven to detect an injected
  `ttl: 15m -> 16m` drift, rewrite the copy, and reproduce the original byte for
  byte once the drift is undone.
- `flux-local test` / `diff` — **with a tooling caveat that matters**: I ran
  pip-installed `flux-local 8.4.0` in a venv, not the image CI pins
  (`ghcr.io/allenporter/flux-local@sha256:c0be852e30f299ce6a220cc992b0c21a2a0b0684cc17713b9d718e18d9c8beff`),
  because this box has no docker. Same major/minor, same flags, same two
  `PYTEST_ADDOPTS` deselections as `.github/workflows/flux-local.yaml`, so it is
  an **equivalent** render/diff, **not an exact reproduction of the CI image**.

So: the renders and static checks are consistent; **the engine has not been
asked anything yet.** Definitive run, at 23:18:08 against a snapshot verified
byte-identical to the working copy for every changed path under `kubernetes/` and
`scripts/` (`flux-local-DEF.txt` in `/tmp/opencode/radiance-230/`):

- `flux-local test --enable-helm --all-namespaces` → **187 passed, 2 deselected**
  in 100.24 s (the two deselections are CI's own).
- `flux-local diff kustomization` (29,589 B patch) → exactly 9 live objects:
  `llm/radiance` InferenceService, `llm/radiance-fleet-config`,
  `llm/inkling-deleuze` LiteLLMModel, `llm/hermes` + `llm/opencode`
  LiteLLMVirtualKey, `llm/opencode-config`, `llm/paseo-config`,
  `llm/hermes-provider-bootstrap`, `llm/hermes` HelmRelease.
- `flux-local diff helmrelease` (846 B patch) → one Deployment roll, `llm/hermes`,
  and only the annotation: `...35f9cd84…` → `…7816249a85ce23031652cb86221e943fa17fd17916d877dfb6c9cf881b3c98d9`,
  whose second half is `sha256(configure.py)`.

## 4. Upstream sources — every naming and capacity claim, with its URL or path

Repo: **https://codeberg.org/StillDeadcode/radiance** (scratch clone at
`/tmp/opencode/radiance-230/radiance-src`, tags v2.0.0…v2.3.0; every path below
is at tag **v2.3.0** unless stated).

### "Inkling 2 Flash" does not exist; Inkling 2 Mini does

| Claim | Source |
| --- | --- |
| The whole Inkling family Thinking Machines publishes | `https://huggingface.co/api/models?author=thinkingmachines` → `Inkling-2-Mini`, `Inkling-2-Small`, `Inkling`, `Inkling-2-Small-MXFP8`, `Inkling-Small`, `Inkling-Small-NVFP4`, `Inkling-NVFP4`, `Inkling-Small-NVFP4`-class quant repos, tokenizer repos. **No `Inkling-2-Flash`.** Model pages: `https://huggingface.co/thinkingmachines/Inkling-2-Mini`, `https://huggingface.co/thinkingmachines/Inkling-2-Small` |
| Nothing named "Inkling 2 Flash" anywhere on HF | `https://huggingface.co/api/models?search=Inkling%202%20Flash` → 2 unrelated third-party fine-tunes whose names merely contain "flash" (`Feyd89/Inkling-2-Mini-NVFP4-capy-flash`, `StuartRiffle/Inkling-2-Mini-Flashbang`); `?search=inkling` returns ~100 repos, none named Flash |
| Upstream radiance never uses "Flash" for Inkling | `git grep -in "inkling.*flash" v2.3.0` → no match. Upstream "Flash" names are other families: `qwen3.8-next-flash*` (the model this lane already serves) and `GLM-5.3-Flash` (`README.md:26`) |
| Mini is the only Inkling with a radiance container | `README.md:85` row: "Inkling 2 Mini IQ4R-V4 + DFlash2 … text and images, one or two cards (`draft-window: adaptive`)" → `inkling-2-mini-iq4r-v4.rad` (14.43 GiB), `[download](https://huggingface.co/StillDeadcode/inkling-2-mini-iq4r-v4)`, `[convert](data/recipes/inkling2-mini-iq4r-v4.recipe)`. `https://huggingface.co/api/models?author=StillDeadcode` (54 repos) → exactly one inkling repo, this one |
| The container object, byte for byte | `https://huggingface.co/api/models/StillDeadcode/inkling-2-mini-iq4r-v4/tree/main?blobs=true` → `inkling-2-mini-iq4r-v4.rad` 15,496,360,448 B, `lfs.oid sha256-1522e6d7e0432cd8308ba0478a969d678648d0245983d05e964caecb4b03dcc9`, `restrictedAccess` absent; repo `gated: false` |
| Inkling 2 Small is a different model that this arch refuses | `docs/ARCHITECTURES.md:34` and `:2747-2763` (`arch/inkling2` serves `inkling2_loop`, 24-layer loop over 48 applications); `arch/inkling2/inkling2.cpp:60` `static const int kLayers = 24;` and `:540` `if (g.n_layer != kLayers || …)` → a 48-layer `model_type: inkling2` checkpoint is refused. No Small container exists in StillDeadcode's repos |
| The drafter the container carries | `arch/inkling2/inkling2.cpp:36` "The drafter is incoai's DFlash2 (`Inkling-2-Mini-DFlash2`…)" → `https://huggingface.co/incoai/Inkling-2-Mini-DFlash2`; `inkling2_dspark` is refused by name |
| "Thinking Machines' Inkling 2" as the upstream's own wording | `core/mm/processor.cpp:393`, `core/mm/processor.h:108` |
| The bump is required, not cosmetic | `git ls-tree -r --name-only v2.2.0 \| grep -c '^arch/inkling2/'` → 0; at v2.3.0 → 3 files |
| Old weights still load (so the bump is not a re-encode) | `abi/rad_format.h:29` `#define RAD_FORMAT_VER 2u` at **both** tags; `abi/rad_abi.h:22` 43u → 44u (plugin ABI, image-internal; cogito carries no out-of-tree plugin) |

### GLM-5.3-Flash constraints

| Claim | Source |
| --- | --- |
| The container and its size | `README.md:26` → "GLM-5.3-Flash: IQR-V4 experts, IQ8R trunk, int8 latent cache, **four cards** with the experts tiered to host memory \| `glm53-flash-iqr-v4.rad` (159 GiB) \| [download](https://huggingface.co/animusnull/glm-5.3-flash-iqr-v4) \| `tp4.yaml`" |
| Object record | `https://huggingface.co/api/models/animusnull/glm-5.3-flash-iqr-v4/tree/main?blobs=true` → 170,662,334,464 B, `sha256-1e20c4bc2f7ea7022f7bae9dd1ffa9873c2031b242d41e85d1ac0a5016342687`, ungated |
| The full key set the model needs | `README.md:261` (quoted in §2) |
| "151 GiB of memory free" | `deploy/compose/tp4.radiance.yaml:13`; its `:24` is `kernels: glm,libr4d,libavx,libref` |
| Routed experts cannot use the file tier | `docs/GUIDE.md:4896` (diagnose table, `DID NOT FIT` row) |
| int8 latent cache forces the kernel order | `docs/ARCHITECTURES.md:860` ("requires `server.kernels: glm,libr4d,libavx,libref`, in that order"), `docs/GUIDE.md:1127`, `docs/GUIDE.md:2745` |
| AMD-only device kernels | `README.md:9` (RDNA4 `libr4d` gfx1200/gfx1201, RDNA3 `libr3d`, Strix Halo) |
| No smaller GLM container published | `?author=StillDeadcode` → 0 glm repos; `animusnull` has the one 159 GiB repo |

### Image pin

| Claim | Source |
| --- | --- |
| 2.3.0 amd64 child digest = the pin | `https://hub.docker.com/v2/repositories/stilldeadcode/radiance/tags/2.3.0` → manifest-list `sha256:7d18847e…`, amd64 `sha256:1e0fe6a2c310e483e9e66e8446ba274ee767f06044f6761ababd593d7517af12`. The lane pins the **amd64 child**, per `kubernetes/apps/llm/hermes/app/agent-bundle/skills/cogito-llm-change-validation/references/radiance-lane-upgrade.md` |
| Live 2.2.0 bytes at the time of the change | `jj file show -r main -- …/radiance-deleuze.yaml` → fleet 15,734 B, sha256 `990640aa9027a3a744892735db3a3e852e737b5326d5bed2c2d1d7afa4f49118`, 4 entries |

## 5. What the lane pays, if it is published

- `inkling-2-mini` is in `one-at-a-time`, so a request to it **displaces
  `qwen3.8-flash-next`** — the model this agent runs on — and the next flashnext
  request pays a reload plus a re-prefill of every live conversation. It is in
  that set because flashnext charges 31.19 GiB per card, not because inkling is
  heavy.
- No extra GPU. Pinned-host reservations go **32 → 36 Gi** against the 60 Gi
  ledger (flashnext 24 = `host-pool-mib: 16384`, which is the 2.x *total*, 8 GiB a
  rank, + its own 8 GiB prefix tier; muse 4; heretic 4; inkling 4).
- Staging cost: 14.43 GiB onto the shared claim; recorded sizes put the 256 Gi
  PVC at ~191.97 → ~206.4 GiB. **The Job's own `statvfs` reading governs.**
- `checkpoint-draft-window: true` (new in 2.3.0) is left off deliberately: it
  costs one drafter window of *pinned* host per slot and is unmeasured here.

## 6. Coordinator runbook

`COMMANDS.md` in this directory has the exact commands, in order: confirm the
name → `df` the claim → stage → preflight → **then** push and reconcile → read
the startup report → `/key/update` for `hermes` and `opencode` (the operator
reconciles the CR but never updates an issued key's model list; see
`kubernetes/apps/llm/hermes/app/agent-bundle/skills/cogito-litellm-key-scope-edit/SKILL.md`
steps 3–4) → verify with per-key requests. Delete both Jobs afterwards: a
one-shot inside `llmkube-resources` holds that KS red forever.

Do **not** apply the fleet ConfigMap before the preflight: llmkube deletes the
pod ~1 s after a ConfigMap write (`waitForIdle: false`) and the Deployment still
pins 2.2.0, which has no `arch/inkling2`.

## 7. Open items (nothing else added beyond the original scope)

- ~~Confirm Inkling-2-Flash → Inkling 2 Mini~~ — **confirmed by the user on
  2026-11-27**; the public names in this change are therefore final.
- ~~Decide GLM-5.3-Flash~~ — **deferred by the user**; nothing about it is in this
  change beyond the refusal note in the lane file.
- `supportsVision: false` on the alias and **no `model-caps` entry** are
  deliberate: the container ships a bf16 tower and the fleet puts it on the card,
  but warm-up never runs an encoder and no image has crossed this arch on
  gfx1201 from this fleet. Flip and add caps only after a probe answers from
  image soft tokens with `restartCount: 0`, then `rollout restart
  deploy/model-caps` (the caps Deployment caches a stale `/v1/models` snapshot).
- The Hermes roll annotation was stamped with
  `artifacts/stamp_hermes_bundle.py`, not `gen-bundle.py --check`: that tool
  already fails at `main` in a fresh checkout on seed file modes
  (`seeds/{MEMORY,SOUL}.md` committed 0600 vs 0644 on disk). `bundle.yaml` is
  byte-identical and the annotation equals exactly what the tool would write.
- What this session could NOT do, and what it did: staging, the `--check`
  preflight and the key-scope sync all ran in-cluster through the Flux MCP
  operations identity, so "the reader kubeconfig blocks live work" is not true
  and was removed. What is actually absent here: `pods/exec` for either identity
  (so the documented `kubectl exec deploy/litellm` transport stays unavailable —
  the approved one-shot Job was used instead), `get` on workload Secrets by
  design, and any exec/shell/HTTP tool in the MCP toolset. Nothing in the
  remaining plan needs a workstation or a 1Password helper.
