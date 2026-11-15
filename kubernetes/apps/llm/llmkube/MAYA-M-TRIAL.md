# Iggy Maya-M trial preparation

## Verified baseline (2026-11-15)

- Iggy and Deleuze are Ready, uncordoned, and retain
  `workload.cogito/dedicated=ml:NoSchedule`.
- Radiance remains on Deleuze. `/health` returned 200 and a chat request to
  its advertised `qwen3.8-flash-next` model returned `RADIANCE_OK`.
- Iggy reports 131799820Ki capacity and 129075980Ki allocatable RAM
  (~128 GiB physical / 123.1 GiB allocatable). Deleuze now reports
  65738476Ki capacity / 63014636Ki allocatable (~64 / 60.1 GiB).
  Older 64 GiB Iggy / 128 GiB Deleuze inventories are stale.
- Both `muse-glimmer-30b` and `qwen3-8-awq-iggy` are intentionally suspended.
  Their Models, PVCs, Services, LiteLLM aliases and key scopes remain registered.
  Restore either lane by clearing only its `spec.suspend` in Git and reconciling
  `llm/llmkube-resources`; do not resume it while a trial owns both GPUs.
- A bounded NVIDIA-runtime Pod successfully allocated both exclusive GPU units:
  `GPU-787b1f07-4246-5ccd-5074-4bb2120f2c14` and
  `GPU-a5982685-6ed7-6fce-8096-52d29e241396`. Both are RTX 3090 24576 MiB,
  driver 595.91.07, 280 W limits. No compute processes were present.
  Reported free VRAM was 24126 / 24115 MiB. Topology is PHB, not NVLink.
- A second bounded Pod using the cached Qwen image, `runtimeClassName: nvidia`,
  and capabilities `IPC_LOCK` / `SYS_RESOURCE` raised RLIMIT_MEMLOCK from
  8388608 bytes to unlimited and successfully allocated/freed 64 MiB through
  `cuMemHostAlloc` on each GPU. This verifies capability/runtime support,
  not a full-size 90 GiB RAM-tier allocation or Maya itself.

## Preserved NAS weights

The existing Retain PV `llm-model-archive` points to
`nuglab-storage.internal:/volume1/nuglab/Models`.
No replacement download or new copy was necessary:

- `llmkube/muse-glimmer-30b-abliterated`: all three GGUFs were fully SHA256-checked
  against the published hashes in `resources/muse-iggy-staging-job.yaml`.
  The local `muse-iggy` claim and its weights remain intact.
- `llmkube/qwen-3-8-awq-int4`: all five safetensors shards and eleven tokenizer,
  configuration, template and license files were fully SHA256-checked against
  `resources/qwen38-awq-kristeva-staging.yaml`. The suspended serving lane
  already reads this archive directly; it needs no Iggy hot copy.

## Cleanup boundary

Five abandoned Kopia cache directories had no PV, PVC or Pod references and
were removed, reclaiming ~0.99 GiB:

```text
pvc-0c4c4a6c-840c-4fb6-922d-874fa5aa034f
pvc-15180082-e1f6-46e6-a22d-2694981556f7
pvc-79a19592-5f30-4a48-987a-b70bfd554021
pvc-7f7cfd48-3377-4b08-90af-f8493f739aa8
pvc-9e072d30-02e8-43cb-8c99-a8d6e661f56d
```

The retired DeepSeek hot-cache subdirectory was evicted only after all four
GGUF sizes and full SHA256 hashes matched the retained NAS copy:
`/var/mnt/local-hostpath/pvc-d0f08fa0-b083-4d20-a271-c38bc426f74b/deepseek-v4-flash-0731`.
No live Model or InferenceService referenced it. The eviction removed
117310852864 bytes of model files (~109.25 GiB); an independent read verified
the target absent, every sibling unchanged, and **227.75 GiB available** on the
backing filesystem. The shared cache PVC and NAS files remain intact. The
local-only zero-byte `.promoted` marker was metadata, not a missing archive
file. All temporary maintenance and preflight Pods were removed afterward.

Preserve the five orphaned `pgdata` directories (~16.0 GiB) until provenance
and disposal are separately confirmed:

```text
pvc-bc442370-bac1-487c-88ed-e1daef98f48a
pvc-6f250819-7edf-482c-8120-9a61fa54ca3a
pvc-ab064876-7df3-4dd0-9385-32826ec9d1cf
pvc-bedafd47-6709-46ff-b00f-fe74dd822de3
pvc-d5938a83-8592-4f46-8b6d-6c3dd991730b
```

Also preserve the CUDA development claim, local FlashNext requants/builds,
`d5-work`, Muse claims, and the empty former Foreman cache claim. No PVC or PV
was deleted during this preparation.

## Verified Maya-M preparation

Completed on 2026-11-15:

- `maya-m-stage-v1` completed at 20:35:45 UTC. All three source GGUFs
  (116003563168 bytes) passed full SHA256 checks on Iggy and the NAS. A
  separate read-only inspector matched both retained reports and all six
  file sizes after the staging Pod exited.
- `maya-m-upstream-setup-v1` completed at 20:46:14 UTC using the intended
  upstream installer. Both GPU hardware checks, engine compilation, normal
  compatibility pack creation and default vision-encoder setup succeeded.
  The engine's `--help` also ran successfully; no server was started.
- The retained config is
  `/model/maya-work/project-maya/maya-maya-m.json`, with GPUs `[0, 1]`,
  context 32768, parallel 1, 1024 MiB reserves, RAM tier 90 GiB, and four
  CPU-lane threads per GPU. The inspector checked the executable, config,
  source pin and completion marker directly on the PVC.
- `/model/Maya-M/pack` occupies 951660152 bytes, including a 943935232-byte
  `dense.bin`; no duplicated `experts.bin` exists. Original GGUFs remain the
  expert source. The backing filesystem still had 125257773056 free bytes
  at post-setup inspection.
- Native engine and vision encoder are present, but a full model load,
  pinned-memory peak, inference, vision ingestion, calibration and throughput
  are NOT yet tested. This is ready for a deliberate trial, not a verified
  serving deployment. The completed setup Job releases both GPU allocations.

The manual `maya-m-stage-v1` Job stages only model files; it does not allocate
GPUs or start a server. Its `maya-m-iggy` PVC is Retain, pinned to Iggy, and
registered separately in the Flux resources list. The long-running Job is
intentionally NOT a Flux health-check dependency. Its script tries verified
hot/NAS files before ISP access, resumes `.partial` transfers, drains dirty
page cache in bounded chunks, and verifies every shard on both tiers.
Progress survives the Pod in `/model/Maya-M/.staging.log`; completion requires
`.verified.json` on both tiers and a successful Job, not file presence alone.

Run the cheap stager regression tests from the repository root:

```sh
python3 -m unittest discover \
  -s kubernetes/apps/llm/llmkube/resources/manual/maya-m -p test_stage.py -v
```

The manual recipe is rendered with explicit load restrictions because it
references the separately registered PVC definition:

```sh
kustomize build --load-restrictor=LoadRestrictionsNone \
  kubernetes/apps/llm/llmkube/resources/manual/maya-m
```

## Pinned Maya-M inputs

This is ordinary Maya-M, not the experimental Maya-M-Derisked variant.

- Engine release: `v1.1.64`, commit
  `d93d1499021b98a39bede20d33368907f1ea4ad8`.
- Upstream llama.cpp dependency:
  `3cf03257f219afbe7334045ff7c6a06ac68c627d`.
- HF repository: `peasantsmith/GLM-5.3-Flash-Maya-GGUF`.
- HF revision: `5ca1df1d2436bd1ab270b169c5ea6c47aad23641`.
- All three files are below `Maya-M/`; total 116003563168 bytes
  (~108.04 GiB). Sizes and publisher LFS digests were verified through the
  immutable HF revision API. Full hot/NAS checks completed successfully;
  the retained reports agree on the exact revision and all three shard hashes.

| File | Bytes | Published SHA256 |
| --- | ---: | --- |
| GLM-5.3-Flash-Maya-M-IQ2_S-00001-of-00003.gguf | 47678327584 | 3f740d1b1022b4a0ddad50cd861bb071dd415bde94afa1292d0476641186c638 |
| GLM-5.3-Flash-Maya-M-IQ2_S-00002-of-00003.gguf | 47820244896 | 285951d2afa0cd98285b03d0dc4aa68d83daf1a6f4a2594fe40b0cdd27ade485 |
| GLM-5.3-Flash-Maya-M-IQ2_S-00003-of-00003.gguf | 20504990688 | ebf1ce713f71207747e10eeebed87597969d8b5e1d9dd817420d2c2f7ca51e0e |

Use the intended upstream installer, not a custom Maya image pipeline. The
manual `resources/manual/maya-m/setup` recipe runs pinned upstream `./setup.sh`
inside an NVIDIA CUDA 13 development container on Iggy. No packages are
installed on Talos or the workstation. The abandoned CI/Dockerfile scaffolding
was removed without publishing or dispatching a build.

The development image is pinned to its linux/amd64 digest:
`docker.io/nvidia/cuda:13.0.0-devel-ubuntu24.04@sha256:435220c0fef35cbf712e11999f8670a83835ef3cdd18564e5e8122f83078c88c`.
The source archive is SHA256-checked before extraction. Source, `.venv`,
builds, configs, logs and auxiliary models persist below `/model/maya-work`
on `maya-m-iggy`; upstream owns dependency installation, compilation and pack
creation. Both GPU units are reserved by the Job, with an 8 CPU / 108Gi
request and limit, a 2Gi shared-memory cap, and an eight-hour deadline.

The bootstrap checks upstream `./setup.sh --help` and `--check`, then waits for
the existing stager's exact revision/report and all three full-size files. It
never starts another model downloader. The actual installer invocation uses
`--setup --yes --plain --no-start --backend cuda --gguf-dir /model/Maya-M`,
`--gpus 0,1`, context 32768, parallel 1, native MTP, 1024 MiB VRAM reserves,
and explicit RAM/CPU-lane settings. Vision retains upstream's default rather
than being silently omitted by a text-only runtime image. No server or Service
is started; a full inference/vision test remains a separate trial.

Apply this separately from the staging recipe, after its PVC is Bound:

```sh
kustomize build --load-restrictor=LoadRestrictionsNone \
  kubernetes/apps/llm/llmkube/resources/manual/maya-m/setup |
  kubectl -n llm apply -f -
```

Setup logs persist at `/model/maya-work/setup.log`. A successful Job and
`/model/maya-work/.setup-complete` indicate installer/engine-help completion,
not inference readiness. No serving lane or LiteLLM alias is registered.

## Trial gates and initial bounds

This preparation does not deploy or benchmark Maya. Before the first trial:

1. Stage the pinned model resumably and SHA256-check every complete shard;
   retain a verified NAS copy to avoid repeat ISP transfers. Serve from the
   Iggy NVMe, never treat NFS as its intended overflow tier.
2. Let upstream setup create the pack from the existing shards. The normal
   GLM `iq_pack.py --compat-bf16` layout indexes experts in the source shards;
   do NOT opt into `--experts-bin`, which duplicates ~97.6 GiB of trunk
   experts. Header/packer analysis predicts ~0.88 GiB of dense overhead for
   that layout, ~108.92 GiB including shards; verify actual generated sizes.
   The 227.75 GiB post-cleanup space budget covers source GGUFs plus the
   derived pack and workspace. Recheck current remaining free space before
   additions; do not require another full model's free bytes after staging.
3. Start at context 32768, parallel 1, both GPUs (`gpu: [0, 1]` in server
   config, auto layer splitting), 1024 MiB initial/later VRAM reserves,
   and `--expert-cache auto`. This is not DeepSeek's tensor-parallel flag.
4. Explicitly set `MAYA_GLM_RAM_GB=90` (implementation units are GiB and it is
   one shared budget, not per GPU), `MAYA_GLM_CPU_LANE0=4` and
   `MAYA_GLM_CPU_LANE1=4`. Fixed RAM sizing bypasses the automatic headroom
   subtraction; do not subtract `MAYA_GLM_RAM_HEADROOM_GB` a second time.
5. Initial Pod scheduling target: 20 CPU request/limit, 112Gi memory
   request/limit, two exclusive GPU request/limit, hostname `iggy`, NVIDIA
   RuntimeClass and ML dedication toleration. Recheck current requests first.
   During preparation, Iggy requested only 1065m CPU and 3590Mi RAM including
   maintenance Pods; the target fit its 23950m / ~123.1 GiB allocatable.
   Set memlock explicitly at startup and include the tested capabilities.
6. Keep the initial endpoint ClusterIP-only and authenticated. Allow a long
   startup budget; prove `/health`, `/v1/models`, and a completion using its
   returned exact model ID. Record cold load, prefill, decode and memory peak.
   No local throughput claim is established by hardware fit or another
   machine's benchmark.

## Live Maya-M trial (2026-11-15)

The user-authorized first start uses the separate manual `resources/manual/maya-m/run`
recipe and existing upstream config; it does not repeat setup, repack or model
downloads. `llm/maya-m-trial` requests both Iggy GPUs, 20 CPUs and 112Gi RAM,
uses the same pinned CUDA development image and persistent workspace, and has
`restartPolicy: Never` plus a four-hour active deadline. Its batch priority and
`preemptionPolicy: Never` cannot evict other workloads. It is not registered
as an always-on Flux workload or a LiteLLM route.

Verified on the live Pod:

- Upstream started the engine at 21:57:26 UTC and reached Ready at 21:58:20 UTC.
- `/health` is OK and `/v1/models` reports loaded model `glm-5.3-flash`,
  context 32768. A non-streaming completion with thinking disabled returned
  exactly `MAYA_OK` (5 output tokens) in 1.954 seconds. This tiny smoke test
  is not a throughput benchmark.
- Both expected RTX 3090 UUIDs are allocated. Post-request VRAM usage was
  23344 / 23318 MiB, with both 280 W caps intact.
- Post-request cgroup memory was 84753416192 bytes; peak was 85234454528 bytes
  (~79.38 GiB), below the 112Gi limit, with zero OOM/max events.
- Startup measured the native vision encoder's reserve, but actual image
  ingestion/answer correctness and sustained load remain untested.
- Radiance health remains OK; Muse and Qwen stay suspended and their weights
  remain intact.

The server binds only to Pod loopback at `127.0.0.1:8080`, without an API key.
There is no Kubernetes Service or ingress. A workstation-only port forward
was started and verified at `http://127.0.0.1:18081/` (UI 200, health OK and
model list correct). Recreate it when needed with:

```sh
KUBECONFIG=./kubeconfig kubectl -n llm port-forward \
  --address 127.0.0.1 pod/maya-m-trial 18081:8080
```

The trial stops automatically at its four-hour deadline. To stop sooner,
delete only `llm/maya-m-trial`; do not delete its retained PVC. Add proper
authentication before any later non-loopback serving deployment.

## Sources

- [Upstream memory table](https://github.com/mw00/project-maya/blob/d93d1499021b98a39bede20d33368907f1ea4ad8/docs/MEMORY.md)
- [Pinned Docker recipe](https://github.com/mw00/project-maya/blob/d93d1499021b98a39bede20d33368907f1ea4ad8/docker/Dockerfile)
- [Pinned packer](https://github.com/mw00/project-maya/blob/d93d1499021b98a39bede20d33368907f1ea4ad8/tools/iq_pack.py)
- [Immutable model metadata](https://huggingface.co/api/models/peasantsmith/GLM-5.3-Flash-Maya-GGUF/revision/5ca1df1d2436bd1ab270b169c5ea6c47aad23641?blobs=true)
