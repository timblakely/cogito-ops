# Gemma 4 12B on Amnesia — deployment + preemptible GPU lane (2026-10-07)

## What shipped

- **Serving**: `llmkube/resources/gemma-4-12b-amnesia.yaml` — Model
  (`pvc://llm-model-archive/llmkube/gemma-4-12b-it/gemma-4-12b-it-Q8_0.gguf`)
  + InferenceService `gemma-4-12b` on Amnesia's RTX 5070 Ti
  (16303 MiB, time-sliced to 2 device-plugin units; the pod claims both).
  Runtime `llamacpp`, image pinned to the b10991 CUDA build the FlashNext
  Amnesia lane proved on this exact card/driver.
- **Staging**: `llmkube/resources/manual/cache-prime-gemma-4-12b.yaml` —
  manual-apply Job into the NFS cold tier (main Q8_0 + mmproj-F16 + MTP
  draft), pinned to HF revision `fc034cf`, per-file sha256 asserted.
  Deliberately out of the Kustomization (the 12.7 GiB download shares the
  LAN with game streaming); the InferenceService ships `suspend: true` and
  is unsuspended only after the Job completes.
- **Catalogue**: `litellm/app/models/gemma-4-12b.yaml`, passthrough alias
  `google/gemma-4-12b-it`, `maxInputTokens` mirrors `contextSize` 32768.
  Scopes: hermes + open-webui keys.
- **Retired**: FlashNext on Amnesia — dropped from both Kustomizations
  (files kept in git), its alias removed from the two key scopes. Its 140
  GiB Q4 shard set is a *different quant* than Radiance serves on Iggy
  (llama.cpp Q4_K_M+M64 vs the Radiance IQ4R `.rad`), so per the 2026-10-07
  decision it is archived to the NAS first, then the PVC/PV released and
  the NVMe space freed (see Runbook).
- **Gaming priority**: `testball.yaml` App template lacked
  `priorityClassName` (pod priority 0 — under every inference lane), so a
  Test Ball launch could never preempt a server. Now `gaming-interactive`
  (20000), matching Steam. Verified the operator propagates the App
  template's priority onto the live session pod (Steam pod carries 20000).

## Priority design (step 3)

`gaming-interactive` 20000/PreemptLowerPriority vs the lane's
`priority: low` → `llmkube-low` 1000/PreemptLowerPriority. A Fenrir
session pod preempts this lane within one scheduler cycle; the lane then
sits Pending (reclaiming both time-sliced units) until the session ends.
Steam and Test Ball both carry the class now; do not raise the lane above
`low`, and do not give any *other* inference lane `low` on Amnesia — this
card is gaming-first.

## VRAM / context ladder (the bench task)

Q8_0 weights 11.84 GiB. KV is cheap: 40/48 layers are sliding-window
(1024), only 8 full-attn layers (8 KV heads × 512 dim); SWA rings are
bounded. q8_0 KV ≈ 2.32/4.46/8.76 GB at 32k/64k/128k (single slot,
`--parallel 1`). Compute + CUDA graph buffers ≈ 1-1.5 GiB; time-slicing
reserves a slice fraction on top — b10991 has no `--gpu-split`, so the
actual budget must be measured, not computed.

Starting point: `--ctx-size 32768 --fit off` (guaranteed fit, validator
mirrors it in `maxInputTokens`).

Bench ladder on the live pod (`/v1` on `gemma-4-12b.llm.svc:8080`,
`google/gemma-4-12b-it`):

1. 32768 — ship state. Record decode tok/s (1 and 4 streams) + prompt
   tok/s at 8k.
2. 65536 — expected to fit (KV +2.1 GiB). If it loads and holds under a
   32k-prompt + 2k-decode soak, raise `contextSize` + catalogue mirror.
3. 98304/131072 — attempt with `--cache-type-k/v q8_0`; if OOM, step back
   one notch. `--fit off` keeps failures honest (explicit KV refusal).
4. MTP speculative decode (draft `MTP/mtp-gemma-4-12b-it-Q8_0.gguf`,
   already staged): `--spec-type draft-mtp --spec-draft-n-max 2` (start
   small, b10991-era flag names) — keep only if decode improves ≥15% at
   4k decode, per the Iggy MTP acceptance rule.
5. mmproj-F16 is mounted via `--mmproj --no-mmproj-offload` (CPU vision
   tower, Muse precedent). The catalogue stays text-flagged
   (`supportsVision` absent) until an image round-trip passes; if it
   fails on b10991, drop both args — the lane works fine text-only.

Sampling defaults match upstream generation_config (temp 1.0, top-p 0.95,
top-k 64).

## Runbook — execution state (2026-10-07 evening)

1. DONE — cache-prime Job staged Q8_0 + mmproj + MTP draft to the cold
   tier; all three sha256s `OK` in-job; InferenceService unsuspended.
2. DONE — `manual/flashnext-amnesia-archive.yaml` (v2; v1's rsync was
   OOMKilled at 1Gi) copied all 33 shards to
   `llm-model-archive/llmkube/flashnext-amnesia-q4-m64/`. Byte sizes
   match 1:1; md5 verification of the full 94.5 GB runs in-cluster before
   the source is released.
3. IN PROGRESS — Flux prune GCs the `flashnext-amnesia` PVC (the running
   verifier pod keeps it pvc-protection-pinned until md5s pass); then
   `kubectl delete pv pvc-97284458-…` (Retain PV) and wipe the hostpath
   dir on Amnesia.
4. IN PROGRESS — bench ladder; md5 job `flashnext-amnesia-verify-v3`
   (94.5 GB x2 reads) pins the Terminating PVC until it completes.

## Bench results (2026-10-07, RTX 5070 Ti, b10991, Q8_0, --parallel 1)

- 32768 ctx (ship state): VRAM 13140-13158/16303 MiB steady (~3.1 GiB
  headroom). Decode ~40 tok/s single-stream; TTFT ~1.1 s for a ~4k-token
  prompt; LiteLLM passthrough E2E OK, cached-token accounting works.
  Note: Gemma 4 is a thinking model — short answers burn the token budget
  on reasoning content; clients need max_tokens headroom or reasoning-off.
- Model loaded multimodal (mmproj OK, CPU-side) and served
  `google/gemma-4-12b-it` cleanly; E2E through the proxy returned READY.
- 65536 ctx: SHIPPED (fd504d7b). Post-roll VRAM 13478-13496/16303 MiB
  steady, incl. under a ~36k-token prompt (TTFT 18.7s ~= 1900 prompt
  tok/s). Decode unchanged (~40 tok/s, single slot). 131k stays out of
  reach (~8.8 GiB q8 KV vs 2.8 GiB headroom). The FlashNext Q4-M64 shard
  archive was released to trust after a size-verified 33/33 copy (md5
  spot-check passed on the first shard; full re-verify waived by the
  operator - re-downloadable from AtomicChat if ever suspect).
- Ops notes this run: litellm-operator re-issued the Hermes key during its
  22:44 retry (transient 401s while secrets/DB/PushSecret settled —
  harmless once settled); scope edits are NOT pushed to existing keys, so
  `/key/update` by key_alias was run manually for Hermes + open-webui per
  the standing note in open-webui.yaml. The rsync-based archive v1 was
  OOMKilled; v2 `cp` succeeded and the 33-file byte map matches.

## Validation actually performed (2026-10-07)

- `scripts/validate-llm-catalogue.py --self-test` → 22 modelNames,
  RESULT: catalogue valid.
- `kustomize build` on `llmkube/resources` and `litellm/app` → clean.
- `kubectl apply --dry-run=server` (admission+webhooks) on rendered
  Model/InferenceService/LiteLLMModel + patched keys + testball → all
  accepted; nothing persisted.
- cluster-wide `flux-local test` (CI image v8.4.0): 7 llm/dreamcast tests
  failed IDENTICALLY on a pristine baseline copy — environmental
  ("Invalid stdin" under podman), not introduced by this change. Reported
  honestly; the checks above cover the diff.
