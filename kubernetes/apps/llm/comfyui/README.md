# `comfyui` — image and video generation on the gaming GPU (experiment)

ComfyUI on `amnesia`'s single **RTX 5070 Ti (16 GiB)**, for a private-local
experiment: photoreal image generation with the Civitai LoRA ecosystem, and
MiniMax **H3** text/image-to-video with native audio.

Nothing here runs by default: the Deployment is `replicas: 0`. This directory is
the whole experiment, and it is meant to be read before it is applied.

```
kubernetes/apps/llm/comfyui/
├── kustomization.yaml          KS wrapper -> emits comfyui + comfyui-resources
├── app/                        what Flux reconciles (priority, pvc, deploy, svc)
├── resources/weights-job.yaml  pinned, sha256-verified weight staging
├── README.md                   this file
└── FIRST-RUN.md                ordered checklist for the first start, with the
                                commands that falsify each assumption
```

Image: `services/comfyui-h3/Dockerfile` →
`.github/workflows/comfyui-h3-image.yaml` → `ghcr.io/timblakely/comfyui-h3`.

---

## 1. Tenancy: who owns the card

One heavy tenant at a time. The card is shared by **priority and preemption**,
which is the contract Dreamcast already uses (`../dreamcast/README.md` §14);
this app only adds one rung to that ladder.

| rung | class | value | holds |
|---|---|---|---|
| gaming | `gaming-interactive` | 20000 | Direwolf/Fenrir session pod |
| **this app** | **`comfyui-interactive`** | **5000** | ComfyUI pod |
| LLM lane | `llmkube-low` | 1000 | `gemma-4-12b` on this node |

Behaviour that follows from those numbers:

- nothing running → `gemma-4-12b` holds the card.
- ComfyUI scaled to 1 → it asks for `nvidia.com/gpu: 2`, which is everything
  the node advertises, so the scheduler cannot fit it while gemma holds those
  units and **evicts gemma**. The GPU lock, not the memory request, is the
  preemption trigger.
- a gaming session launches → ComfyUI is evicted, mid-render, immediately.
- ComfyUI scaled to 0 → gemma's pending pod schedules again on its own. No
  manual refill, no suspend, nothing to undo.

Two consequences worth being explicit about:

**Preemption is eviction, not pause.** There is no checkpointing of a
diffusion state; a clip that was 40 seconds into a 66-second render is lost.
Start a render knowing someone can take the card.

**One tenant is arithmetic, not preference.** gemma Q8 at its configured 64 k
window measured **13584 MiB** of the 16303 MiB card. The H3 NVFP4 DiT needs
**11.68 GiB** resident plus ~1.2 GiB ComfyUI reserve. The text encoder alone is
11.78 GiB. There is no pair of these that co-resides, which is why the design
is "swap by priority" rather than "share".

`gemma-4-12b` is **not** suspended by this app and its `suspend: false` is left
alone. It loses the card only when this Deployment actually wants it, and gets
it back the moment this Deployment goes to zero. If you want it off the node
regardless, that is `spec.suspend: true` on `InferenceService/gemma-4-12b`
(never `kubectl scale` — the operator co-owns `.spec.replicas`).

## 2. Starting and stopping it

`spec.replicas` lives in Git and Flux re-applies it, so **a bare
`kubectl scale` is reverted** at the next reconcile (30 min, or immediately on
any push). Pick one:

**A. Suspend Flux for the session** (what I would use for a sitting-down
session):

```sh
flux suspend ks comfyui comfyui-resources -n llm
kubectl -n llm scale deploy/comfyui --replicas=1
kubectl -n llm get pods -l app.kubernetes.io/name=comfyui -w
# ...work...
kubectl -n llm scale deploy/comfyui --replicas=0
flux resume ks comfyui comfyui-resources -n llm
```

**B. Commit the replica count** for anything long-running or shared.

Then reach the UI — there is no Ingress, deliberately (§5):

```sh
kubectl -n llm port-forward svc/comfyui 8188:8188
```

Weights land in `/data/output` on the volume, i.e. under the hostpath PV on
`amnesia`; `kubectl cp` them out, or grab them from the browser UI.

## 3. The model set (what the staging Job pins)

Video — **MiniMax H3, rotated-NVFP4 line** (`pottokao`), which is the only
H3 variant that is *fully resident* on this card instead of streaming a 19.5 GiB
DiT through host RAM:

| file | size | why |
|---|---|---|
| `diffusion_models/h3_base_T1.safetensors` | 11.68 GiB | the DiT, all-NVFP4 + runtime Hadamard rotation, native W4A4 kernel |
| `text_encoders/…Q3_K_S_vis.gguf` | 11.78 GiB | Qwen3-VL 32B encoder, vision tower merged in, loaded by `CLIPLoaderGGUF` |
| `vae/minimax_h3_video_vae_fp16.safetensors` | 4.85 GiB | |
| `vae/minimax_h3_audio_vae_fp32.safetensors` | 0.56 GiB | H3 generates audio in the same pass |
| `loras/…turbo_4step…bf16.safetensors` | 1.82 GiB | optional 4-step distillation |
| `embeddings/minimaxh3_kiss_camera.safetensors` | 1 MiB | "Camera" control |

Image — two lines, because they answer different questions:

| file | size | why |
|---|---|---|
| `checkpoints/RealVisXL_V5.0_fp16.safetensors` + `vae/sdxl_vae.safetensors` | 6.8 GiB | SDXL: realistic humans **and** the Civitai LoRA depth that only SDXL/Pony has |
| `diffusion_models/flux-2-klein-4b.safetensors` + `text_encoders/qwen_3_4b_fp4_flux2.safetensors` + `vae/flux2-vae.safetensors` | 11.1 GiB | FLUX.2 Klein 4B: current-generation architecture, prompt adherence, text rendering, ~11 GiB resident |

FLUX.2 Klein does **not** accept FLUX.1 LoRAs — FLUX.2 retrained the latent
space, the VAE and the text encoder. That is exactly why SDXL stays in the set
rather than being replaced by it.

Every weight is pinned by repo revision *and* sha256 in
`resources/weights-job.yaml`. The encoder and quant repos are moving targets.

**Civitai LoRAs are not in the Job**: they need an account token and manual
terms acceptance. Put them on the volume's `models/loras/` (upload through the
UI, or `kubectl cp` into the pod).

## 4. Runtime flags, and why they are not the defaults

The container runs:

```
--listen 0.0.0.0 --port 8188 --use-ck-attention
--models-directory /data/models  --input-directory /data/input
--output-directory /data/output  --user-directory /data/user
--temp-directory /data/temp
```

`--use-ck-attention` is measured, not taste: on Blackwell it roughly halved H3
step time, while **SageAttention made low-VRAM cards 2.5–3× slower** because
its workspace pushed more of the model into host RAM.

Deliberately absent:

- `--disable-smart-memory` — would force the 11.78 GiB encoder and the 11.68
  GiB DiT resident together. The default swap is precisely what makes 16 GiB
  feasible.
- `--lowvram` — the escape hatch if the measured peak exceeds the authored
  13.6 GiB. It costs speed, so it stays a decision, not a default.
- `--fast` — trades output quality, and judging output quality is the point.
- `--enable-manager` — would let a browser tab change this environment.

For H3 runs: `euler`/`simple`, CFG 1.0, sigma shift **video 12 / audio 3**
(the pinned workflow already encodes this); frame counts must satisfy
`17k + 5` (124 is the default 480p clip); 480p preview then upscale is ~2.8×
faster than rendering 768p directly; and do **not** stack EasyCache/TeaCache on
top of the 4-step Turbo LoRA — the cache skips steps the LoRA already removed.

## 5. Deliberate limits of this experiment

- **No Ingress.** ComfyUI has no authentication and its queue endpoint takes
  arbitrary workflow JSON, which is code execution on the gaming GPU as root on
  a hostpath volume. ClusterIP + `port-forward` only. Putting it behind the
  cluster's OIDC gateway is a separate decision.
- **`runAsUser: 0`.** The hostpath volume and everything the staging Job wrote
  into it is root-owned. Fixing that means an ownership Job for a prototype;
  not worth it until this is a service.
- **Pin the digest, never the tag.** CI publishes both `comfyui-v0.34.2` and a
  revision tag, and both move on rebuild; the Deployment pins
  `@sha256:28bf210e8c98…` (run 41384580988) so a rebuild cannot move a running
  pod's VRAM profile. The package is public - anonymous pull-by-digest returns
  200 - so there is no `imagePullSecrets`, matching `cuda-dev`.
- **60 GiB volume, Retain.** `openebs-hostpath-retain` on the NVMe, expansion
  allowed. Everything on it except `output/` and `user/` is re-creatable by the
  Job.

## 6. Status and what is left

| piece | state |
|---|---|
| weight pins | **verified 2026-11-02**: 11/11 resolve at their pinned revision, the *repo-internal* path exists at that revision, and the LFS sha256 matches. 48.6 GiB total. Installed on amnesia: 48.5 GiB, sha-verified by the Job |
| staging Job script | `dash -n` clean; `cp -fL` + post-copy verify so a symlink or a short write cannot be installed as a weight. **Ran live 2026-11-02.** `-v1` failed in 30 s on a `srcpath()` bug (`case` patterns treat `\|` as alternation, so every repo took the Comfy-Org branch); fixed and shipped as `-v2`, since a Job pod template is immutable. All 11 source paths are now verified against the live HF trees at the pinned revisions, not just the destination layout |
| image | **builds and is published**: CI run 41384580988 exit 0 → `ghcr.io/timblakely/comfyui-h3@sha256:28bf210e8c98…` (tags `comfyui-v0.34.2` + `5d4c7756…`), digest pull verified anonymously. Locally `podman build` exit 0, 7.58 GB. Torch trio imports as `2.11.0+cu130 / 0.26.0+cu130 / 2.11.0+cu130`; nunchaku wheel installs by verified sha256 |
| custom nodes | CPU-mode boot imports all three with no `IMPORT FAILED`: `comfyui-gguf`, `comfyui-h3-rotnvfp4` (registers `H3RotNVFP4Loader` + 4 siblings), core `nodes_minimax_h3.py` present |
| **live GPU run** | **works on the 5070 Ti** (2026-11-02): sm_120 in torch's arch list, nunchaku wrapped 200 linears, SDXL 1024²/25 steps in 25 s, H3 NVFP4 832x480x124f 8 steps in 75 s producing h264 + synchronised 32 kHz stereo aac. Full numbers and the log markers to grep for are in `FIRST-RUN.md` §3b |
| cluster manifests | `kustomize build` clean for both trees; **server-side dry-run accepted all 5 objects** against the live API (schema + admission, nothing persisted). `flux-local test`: **177 passed, 4 failed** here vs **175 passed, the same 4 failed** on an identical copy with `comfyui/` deleted — the +2 are `comfyui` and `comfyui-resources`, both passing; the 4 are ghcr.io 403s pulling `home-operations/charts-mirror` for intel-device-plugins/fluent-bit/openebs in this sandbox |

So: the build-time unknowns are closed **and the card has been exercised** — see
`FIRST-RUN.md` §3b for what actually ran and what it produced. What is still
unproven is the *preemption* path (the GPU swap was driven by hand, per the
contract) and behaviour under a co-resident gaming session.

Known open risks, in the order they will bite:

1. **The loader has now met this torch - it works.** `torch 2.11.0 + cu130` is the
   newest trio where PyTorch still ships a matching `torchvision`/`torchaudio`
   pair, and the H3 core nodes `import torchaudio`, so dropping it costs H3 audio.
   The author's wheel is built against `torch 2.12.1`; the risk was that
   nunchaku's C extension would not load against 2.11. It does: on the live card
   it wrapped 200 rotated-NVFP4 linears in 8 s and denoised at 3.43 s/it, and the
   audio VAE decoded (the output MP4 carries a 32 kHz stereo track). This stays
   on the list because it is a version-coupled risk, not a settled one: bumping
   torch or the nunchaku wheel means re-running the H3 sample, not just the
   import check.
2. **Peak VRAM is measured, and it is tighter than the authored figure suggests.**
   The loader logs `single-file load peak: cuda0=10.44GiB`, but `nvidia-smi` read
   **15.0 GiB of 16.3 GiB** during the run, because the video VAE and audio VAE
   decode after the denoise loop and both are force-preloaded. That leaves ~1.3
   GiB, so nothing else may share the card and no cache accelerator belongs on
   this workflow.
3. **`amnesia` has 60.4 GiB RAM**, under the 64 GB the community treats as
   comfortable for H3 streaming paths; the NVFP4 line measured ~31 GB to load,
   which fits, but a `GPU is lost` style failure on a memory-starved box is a
   known H3 report. `--disable-pinned-memory` is the first lever if that shows.
4. **The image is 7.58 GB** (measured) and the volume is 60 Gi, holding 48.6 GiB
   of weights plus renders; the first pull is why the KS timeout is 20m.
5. **Preemption is still assumed, not proven.** ComfyUI asks for both time-sliced
   units, which should make gemma's pod the only thing in the way and therefore
   the eviction target. The first run never exercised that direction: the card was
   freed by hand (`spec.suspend: true` on `InferenceService/gemma-4-12b`, per the
   contract) before ComfyUI was scaled up, so ComfyUI was scheduled onto an empty
   node rather than onto a victim. The reverse direction *was* observed, on gemma
   itself: its replacement pod sat unschedulable for hours while the gaming
   session held the card and started the moment it was released - which is the
   same priority maths working for `gaming-interactive` (20000) over
   `llmkube-normal` (10000). `FIRST-RUN.md` §3 has the command that confirms the
   forward direction, because if the operator holds those units differently the
   pod just sits `Pending` and the wrong fix (raising the LLM lane) is very
   tempting.

## 7. Validating a change here

```sh
export KUBECONFIG=$PWD/kubeconfig            # the repo's .mise.toml sets this too
kustomize build kubernetes/apps/llm/comfyui/app
kustomize build kubernetes/apps/llm/comfyui/resources
kustomize build kubernetes/apps/llm/comfyui/app | kubectl apply --dry-run=server -f -
```

CI's gate is `flux-local test --enable-helm` over `kubernetes/flux`
(`.github/workflows/flux-local.yaml`, image pinned by digest). The two
Kustomizations emitted here are generated by the `llm` parent build, which
flux-local discovers as test nodes — so this directory is covered by CI and can
be run on its own:

```sh
PYTEST_ADDOPTS='-k comfyui' flux-local test --enable-helm --all-namespaces \
  --path kubernetes/flux --skip-secrets          # 2 passed, 181 deselected
```

After a push: `kubectl -n llm get ks comfyui comfyui-resources`, then
`kubectl -n llm get jobs,pods,pvc -l app.kubernetes.io/name=comfyui`.

There is deliberately **no wiring file** for this app. The `llm` Flux
Kustomization points at `./kubernetes/apps/llm`, which has no
`kustomization.yaml`, so every subdirectory containing one is built as a base —
that is how `camofox`, `cuda-dev` and `foreman` got there, and it is why adding
a directory is the entire registration step. The literal `NS` left in the
rendered `spec.path` is not a bug: `kubernetes/components/namespace`, a
component on the parent, rewrites index 3 of `spec.path` to the Namespace name
and sets `targetNamespace` from it.
