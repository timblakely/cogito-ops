# First-run checklist — ComfyUI on `amnesia`

Everything here was executed or is the exact command to run. Ordered by what
fails first if you skip it.

## 0. Image built and verified locally (done, 2026-11-01)

`podman build -t localhost/comfyui-h3:probe services/comfyui-h3` → exit 0.

Imports that were asserted inside the build (all passed):

```
torch 2.11.0+cu130  cuda 13.0  torchvision 0.26.0+cu130  torchaudio 2.11.0+cu130
nunchaku  imported from site-packages (wheel sha256 f9258376b63e…, 138633136 B)
```

And a real CPU-mode boot of the image (`--cpu --quick-test-for-ci`) printed:

```
Import times for custom nodes:
   0.0 seconds: /opt/ComfyUI/custom_nodes/websocket_image_save.py
   0.0 seconds: /opt/ComfyUI/custom_nodes/comfyui-h3-rotnvfp4
   0.2 seconds: /opt/ComfyUI/custom_nodes/comfyui-gguf
```

No `IMPORT FAILED` line, which is the only cheap proof that the nunchaku wheel
and the torch pair agree. On the pod the same table must also show no failures —
but with a driver present, the loader additionally prints what it patched:

```
[rot] chunked-swiglu adaptation skipped (ComfyUI internals differ): Found no NVIDIA driver
```

That line is expected **in the build/CPU test only**. If it appears on `amnesia`,
the loader's Blackwell fast paths were silently skipped and H3 will run far
slower than the numbers in `../../comfyui/README.md` §4.

Nodes the loader registers (verified in the built image): `H3RotNVFP4Loader`,
`H3RotNVFP4LoaderSplit`, `H3RotNVFP4Patch`, `H3NativeNVFP4Patch`,
`H3EmbedsTEFree`. The pinned workflow uses `H3RotNVFP4Loader`.

## 1. Node facts to re-confirm before the first start

Observed read-only on 2026-11-01 (`KUBECONFIG=$PWD/kubeconfig kubectl --context main`):

| check | observed | note |
|---|---|---|
| `amnesia` GPU capacity / allocatable | 2 / 2 `nvidia.com/gpu` | the two time-sliced units of one 5070 Ti |
| `amnesia` allocatable | 23950m CPU, 60632568Ki (~57.8 GiB) | ComfyUI asks 4 CPU / 24 Gi request |
| GPU-holding pods on the node | exactly one: `gemma-4-12b-5c5945bd97-jsknm`, `limits nvidia.com/gpu: 2`, 24 Gi | the lock really is one pod |
| `InferenceService/gemma-4-12b` | `suspend: false`, `replicas: 1` | left alone by this app |
| PriorityClasses | `gaming-interactive` 20000 PreemptLowerPriority, `llmkube-normal` 10000, `llmkube-low` 1000, `llmkube-batch` 100 **Never**, `llmkube-critical` 1000000 | `comfyui-interactive` 5000 slots in cleanly; `llmkube-batch` is `Never` so the staging Job can never evict a serving pod |
| server-side dry-run of `app/` + `resources/` | all 5 objects accepted | schema + admission only; nothing was persisted |

Two dead gemma pods are still parked on the node (`UnexpectedAdmissionError`
from 6 days ago, `Completed` from 12) — residue, not tenants. They hold nothing,
but they are why `kubectl get pods` on that node looks busier than the GPU is.

Re-run before the first start, because a lot of this is a snapshot:

```sh
export KUBECONFIG=$PWD/kubeconfig
kubectl --context main get node amnesia -o jsonpath='{.status.allocatable}{"\n"}'
kubectl --context main -n llm get pods --field-selector spec.nodeName=amnesia   -o custom-columns=NAME:.metadata.name,STATUS:.status.phase,GPU:.spec.containers[0].resources.limits.'nvidia\.com/gpu'
```

And inside any GPU pod on the node (`cuda-dev`, or the ComfyUI pod itself):

| check | expected | why it matters |
|---|---|---|
| `nvidia-smi --query-gpu=name,memory.total` | RTX 5070 Ti, 16303 MiB | the whole plan is sized to this |
| compute capability | 12.0 (sm_120) | NVFP4 W4A4 kernel needs it; P0 failure if not |
| driver version | CUDA 13 capable | the cu130 wheels need it |

`torch.cuda.get_arch_list()` inside the *build* returned `[]` because the build
sandbox has no driver — so capability has to be confirmed here, on the node, and
nowhere earlier.

## 2. Weights

```sh
flux suspend ks comfyui-resources -n llm         # so Flux doesn't fight the re-run
kubectl -n llm delete job comfyui-stage-weights-v2 --ignore-not-found
flux resume ks comfyui-resources -n llm
kubectl -n llm logs -f job/comfyui-stage-weights-v2
```

Expected tail: one `ok`/`get` line per entry, then 12 lines of `du -sh`, and the
marker `/data/.weights-v1.promoted`. Total **48.6 GiB** across 11 files; every
pin was re-verified against the Hugging Face API on 2026-11-01 (revision
resolves, path exists at that revision, LFS sha256 matches): **11/11 OK**.

If it fails, the pod template is immutable — delete the Job and resume, don't
edit by hand.

## 2b. What the first live run broke (2026-11-02)

Three real failures, each of which looks like something else.

1. **The app Kustomization hung in `Running health checks` until timeout and the
   PVC stayed `Pending`.** Not a storage fault. `comfyui-data` is
   `WaitForFirstConsumer`, the Deployment is `replicas: 0` by design, and the
   only other consumer — this Job — sat in `comfyui-resources` behind
   `dependsOn: comfyui`. So the KS waited on the PVC, the PVC waited for a pod to
   consume it, and that pod waited on the KS. Fixed by dropping `dependsOn` from
   the `comfyui-resources` Kustomization in `../kustomization.yaml`; the PVC bound
   within seconds of that landing.
   Do **not** fix it with `spec.healthCheck`: this cluster's `Kustomization` CRD
   has no such field, server-side apply rejects the object with
   `field not declared in schema`, and it takes the whole `llm` parent
   Kustomization down with it.
2. **`hf download` 404'd on the first weight** — `File not found in model
   'pottokao/MiniMax-H3-NVFP4-rotated'` — which reads like a bad pin. The pins
   were fine; `srcpath()` was wrong. Its case subject was `"$2|$4"` with patterns
   like `Comfy-Org/MiniMax-H3|*`, and in shell case syntax `|` is *alternation*,
   so the first branch matched every repo and asked HF for
   `diffusion_models/h3_base_T1.safetensors` when the file is
   `h3_base_T1.safetensors` at the repo root. The branch is now on `$2` alone.
3. **The failed pod left no logs.** `backoffLimit` was reached and the Job
   controller deleted the pod within seconds (`SuccessfulDelete`), so
   `kubectl logs` had nothing. To diagnose one, run the script in a standing pod
   (`python:3.13-slim`, same nodeSelector, same priorityClass, PVC mounted) under
   `sh -x` — that located bug 2 in under a minute.

## 3. Start it

Decide the tenancy question first (README §2 — suspend Flux or commit replicas),
then:

```sh
flux suspend ks comfyui -n llm                  # REQUIRED, see below
kubectl -n llm scale deploy/comfyui --replicas=1
kubectl -n llm -w get pods -l app.kubernetes.io/name=comfyui
```

`flux suspend` is not optional. `spec.replicas: 0` is the committed state, so the
next reconcile of the `comfyui` Kustomization scales you straight back to zero and
**deletes the pod mid-generation** - measured at ~4 minutes after `scale`, with a
video render already running. It looks like a crash: the pod is simply gone, with
no OOM and no eviction event. Resume with `flux resume ks comfyui -n llm` when
done, or commit a non-zero replica count instead (README §2).

Watch for the eviction you are *supposing* to cause:

```sh
kubectl -n llm get events --field-selector reason=Preempting -w
kubectl -n llm get pods -l llmkube.io/inferenceservice=gemma-4-12b
```

If ComfyUI sits `Pending` with `0/N nodes are available: 2 Insufficient
nvidia.com/gpu` and gemma was **not** evicted, the preemption assumption is
wrong on this cluster (KubeRay/operator holding the units, or a PDB). Stop and
read `kubectl -n llm describe pod` rather than raising the LLM lane's priority.

## 3b. What the first full run measured (2026-11-02)

Everything below was measured on the real card with the CI image
(`sha256:28bf210e8c98…`), not carried over from upstream's numbers.

| check | measured |
|---|---|
| GPU / driver / capability | RTX 5070 Ti, driver 615.78.08, `compute_cap 12.0` |
| torch | `2.11.0+cu130`, `torch.cuda.get_arch_list()` includes `sm_120` |
| nunchaku | imports; `[rot] single-file wrapped 200 linears … 8s` |
| loader 16 GB path | `[rot] 16G VRAM adaptation active (chunked swiglu)` + `(chunked H3 MLP)` |
| SDXL image | RealVisXL V5.0, 1024x1024, 25 steps, dpmpp_2m/karras -> **25 s**, cold |
| H3 video | `h3_base_T1.safetensors`, 832x480, 124 frames, 8 steps euler, shift 12/3 -> **denoise 26 s at 3.43 s/it, 75 s end to end** |
| H3 output | `/data/output/h3_rotnvfp4_00001_.mp4`: h264 832x480 124 frames 5.17 s **plus aac 32 kHz stereo 5.17 s** |
| peak VRAM | 15012 MiB used during the run; loader reports `single-file load peak: cuda0=10.44GiB maxrss=24.5GiB` |
| weights | staging Job `-v2` completed in 8m19s, 48.5 GiB sha-verified on the NVMe |

Two notes on reading those numbers. `nvidia-smi` shows ~15.0 GiB while the loader's
own peak is 10.44 GiB: the difference is the video + audio VAE decode, which runs
after the denoise loop, so headroom is thinner than the loader's line suggests -
do not add a cache accelerator on top. And `maxrss=24.5 GiB` is the loader's
resident set, well inside the 60 GiB this node has, so the CPU text-encoder path
is not the constraint here.

`WARNING unet missing: [blocks.N.attn.qkv_proj.weight …]` printed while loading the
DiT is **expected** for this loader: those modules are replaced by nunchaku's
rotated-NVFP4 wrappers, so they are deliberately absent from the checkpoint's
plain-weight view. The success marker to look for is the `wrapped 200 linears`
line, not the absence of that warning.

## 4. First generation

```sh
kubectl -n llm port-forward svc/comfyui 8188:8188
```

Load `pottokao/MiniMax-H3-NVFP4-rotated` `workflow.json` (revision
`2dd1a4e33f5a…`) and check the three loaders resolve before sampling:

- `H3RotNVFP4Loader.ckpt_name` = `h3_base_T1.safetensors`
- `CLIPLoaderGGUF.clip_name` = `MiniMax-H3-TextEncoder-Qwen3VL-32B-abliterated-Q3_K_S_vis.gguf`, `type` = `minimax`
- `VAELoader` × 2 = `minimax_h3_video_vae_fp16.safetensors`, `minimax_h3_audio_vae_fp32.safetensors`

If a dropdown is empty, the file is not under `/data/models/<type>/` — the
container reads `--models-directory /data/models`, not the image's built-in
`models/` tree.

Then watch the card during a 480p / 8-step run:

```sh
kubectl -n llm exec deploy/comfyui -- nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv -l 2
```

Expect ≈13.6 GiB peak and a warm 480p×124-frame clip in ≈66 s. If `memory.used`
climbs past ~15.5 GiB or you see a CUDA OOM, add `--lowvram` to the Deployment
args (README §4). If the pod dies with a message about the GPU being lost, that
is the RAM-ceiling failure mode: check `kubectl -n llm top pod` against the
node's 57.8 GiB allocatable before touching anything else.

## 5. Image status (done - CI published it)

`services/comfyui-h3/Dockerfile` is on main and workflow run **41384580988**
published:

```
ghcr.io/timblakely/comfyui-h3@sha256:28bf210e8c9858c80ef8815c222e6b4819feb01c00b0193874bb0cd7b94fd056
  tags: comfyui-v0.34.2, 5d4c77569e2d88224534b721ffb4045eca3f4c39
```

`app/deployment.yaml` pins that digest, so a rebuild cannot move the pod. Pull
by digest was verified anonymously (HTTP 200), so the package is public and no
`imagePullSecrets` is needed - same as `cuda-dev`. Note when re-checking a
digest by hand: GHCR answers **404, not 406**, when your `Accept` header doesn't
name the stored media type, so probe with exactly
`application/vnd.oci.image.index.v1+json` before concluding an image is
unpullable.

The first pod start pulls the ~7.6 GB image (measured layer total) from GHCR,
which is why the Flux Kustomization timeout is 20m instead of the 3m default.
To rebuild:

```sh
gh workflow run comfyui-h3-image.yaml
gh run view --log | grep -A3 'digest'      # then update the digest pin
```

## 6. Benchmarking rules (so the numbers mean something)

- pin the seed per measurement; an unchanged seed + filename can reuse output
  and print a bogus 0.07 s
- warm = second run; the first includes mmap and loader patching
- record `memory.used` peak, not just time — that is the number that decides
  whether `--lowvram` is required
- do not stack EasyCache/TeaCache with the 4-step Turbo LoRA (measured 0/8 steps
  skipped), and do not use SageAttention on this card (measured 2.5–3× slower at
  low VRAM because it increases offload)
- frames must satisfy `17k + 5` (124 = 7·17+5)
