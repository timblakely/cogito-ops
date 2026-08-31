# LLM bench notes

Running log of measurements and verification evidence. Manifest comments hold
the numbers next to their tunables; this file holds the raw context.

## 2026-08-21 · T0.1 GPU allocation check (pre-change)

`qwen-3-8-fp8-7ddd577cf8-5g7l8` on iggy, device plugin still time-slicing ×4:

```
GPU 0: NVIDIA GeForce RTX 3090 (UUID: GPU-787b1f07-4246-5ccd-5074-4bb2120f2c14)
GPU 1: NVIDIA GeForce RTX 3090 (UUID: GPU-a5982685-6ed7-6fce-8096-52d29e241396)
CUDA_VISIBLE_DEVICES=(unset)
0: 23114 MiB / 24576 MiB used
1: 23220 MiB / 24576 MiB used
```

Two distinct physical UUIDs → the TP=2 allocation does span both cards today.
The `replicas: 1` change makes that true by construction rather than by luck.

## 2026-08-21 · T0.1 outcome

- Gotcha: the device plugin **rejects `timeSlicing.replicas: 1`** ("number of
  replicas must be >= 2"). Removing the sharing block entirely is how
  advertised = physical. First attempt crash-looped the plugin for ~2 min;
  running workloads were unaffected.
- After fix: `iggy` capacity `nvidia.com/gpu: 2`, plugin 2/2 Running, qwen pod
  untouched (41h uptime preserved), backend smoke completion OK.

## 2026-08-21 · T1.1 retune results

New config: maxModelLen 131072, max-num-seqs 6, --language-model-only added.
vLLM startup (recorded per the manifest-comment convention):

- **GPU KV cache size: 277,007 tokens** → "Maximum concurrency for 131,072
  tokens per request: 2.11x". At the old 262,144 ceiling the same pool held
  ~1.05 full sequences — the ceiling halving doubled full-length seats, and
  typical worker turns (≤16k) pack ~17 deep in the same pool.
- Text-only mode confirmed: "All limits of multimodal modalities supported by
  the model are set to 0" — the vision tower is no longer resident.
- Engine init 119s (43.7s compilation) — the cost of a config rollout.
- vLLM hint: with CUDA-graph profiling, effective gpu-memory-utilization is
  0.8912; raising to 0.9088 would restore the pre-0.21 effective pool.
  Candidate micro-tune for the A1 sweep session.

## 2026-08-21 · T1.2/T1.3 verification

- worker/reviewer aliases live; worker-key smoke returned "OK" with short
  low-effort reasoning. Scope enforcement verified: worker key → reviewer and
  planner-gpt both 403.
- ModelPool + ModelRouter deleted; qwen pod uptime unbroken through the prune;
  InferenceService Ready with explicit replicas: 1.
- Validator: 8 modelNames, 1 backend, 0 warnings (mirror assertion now active).

## 2026-08-21 · A3 kristeva identity + bandwidth

- CPU: **dual Intel Xeon E5-2680 v2** (Ivy Bridge-EP, 2×10C/40T, DDR3-1866
  quad-channel per socket).
- sysbench memory (1M blocks): **70.9 GB/s @ 8 threads, 52.7 GB/s @ 32
  threads** (NUMA contention past one socket).
- **AVX only — no AVX2, no FMA** (Ivy Bridge). Consequences:
  - D2 MoE lane: ~6-8GB expert reads/token at ~50-70GB/s → 3-6 tok/s ceiling
    BEFORE the AVX-only compute penalty. The ≥5 tok/s bar is unlikely to
    clear; run the trial anyway when convenient, expect to delete it.
  - D1 CPU VLM: vision encode on AVX-only will run slower than the "seconds
    per image" estimate; still fine for rare screenshots, but benchmark
    before promising latency.
  - The A380 floor (Track B) is unaffected - the GPU does that work.

## 2026-08-22 · Wave 1 verification battery

- **Six parallel worker calls: 11.5s wall** for six ~11s completions — the
  seats are real (serial would be ~66s). Reviewer seat OK. Scope enforcement
  OK (worker key 403s on anything but `worker`).
- **litellm-operator gap:** LiteLLMVirtualKey scope changes are NOT pushed to
  existing keys — the DB kept the old 12-model allowlist through a spec
  change, an annotation nudge, and an operator restart (create-only
  reconciliation). Fixed via admin `/key/update`. Consequence: any future
  scope edit needs the same manual push (or an operator fix upstream); the
  validator keeps git honest but git-to-DB is not automatic for scopes.
- **coordinator / worker-escalated / reviewer-escalated: wired correctly but
  OpenAI returns "exceeded your current quota"** — the OPENAI_API_KEY account
  is out of credit, which also means planner-gpt/-pro are currently dead.
  User action required (T1.4): fund the account or land the real seats
  (Luna OAuth, GLM 5.3, K3).

## 2026-08-22 · Track B / B1-B2 probe

- **A380 confirmed by PCI id**: `0x8086:0x56a5` (DG2/Arc A380) — the NFD
  label was honest.
- **SYCL path proven before deploy**: `sycl-ls` inside the official
  `ghcr.io/ggml-org/llama.cpp:server-intel` image, unprivileged, with only
  `gpu.intel.com/i915: 1`, enumerates "Intel(R) Arc(TM) A380 Graphics" via
  Level Zero. /dev/dri injected by the plugin (card0 + renderD128).
- **No Resizable BAR** (Ivy Bridge platform cannot): notorious for Arc gaming
  performance, mild for compute; A4's throughput bench is the arbiter.

## 2026-08-22 · Track B live + A4

- Cache-prime Job staged both GGUFs into the NFS archive in 61s (the serving
  pods raced it and crash-looped until the files appeared - expected, backoff
  absorbed it; a Job-before-InferenceService ordering would remove the noise).
- bge-m3 + bge-reranker-v2-m3 Ready on the A380 (llama.cpp SYCL, ~600MB each
  on the 6GB card, shared via the i915 plugin).
- **Embeddings end-to-end**: open-webui key -> LiteLLM /v1/embeddings ->
  embedder -> A380 -> 1024-dim vectors (bge-m3's dimension).
- **Rerank both paths identical**: LiteLLM /v1/rerank (infinity provider) and
  direct service - same scores. Jory's "openai/ rejects rerank" lesson held;
  infinity/ + no-/v1 apiBase is the working shape.
- **A4 throughput: 869 chunks/min** (~90-token chunks, batch 32, sequential
  requests, parallelSlots 1, no ReBAR). A 10k-chunk reindex is ~12 min ->
  the A380 floor covers bulk indexing; no 5070 Ti reranker slot needed.
- Gotchas: node-role label values here are "true", not "" (qdrant selector);
  flux reconcile of the namespace-wide `llm` Kustomization blocks on
  wait:true - reconcile per-app Kustomizations instead.

## 2026-08-22 · Track C (pi harness lift)

- New dotfiles repo at ~/git/dotfiles: jj-colocated clone of
  joryirving/dotfiles (remote `upstream`, no origin yet - add one to push).
  Old blakely-dotfiles untouched; live ~/.pi/agent backed up to
  ~/.pi/agent.bak-20260822 before apply.
- Adaptation: role agents (worker/reviewer/escalated x2), inverted-economy
  coordinator prompt, trusted checks + validate-llm-catalogue +
  kustomize-build-llm, workflows re-agented (review-pr = council across
  families; new implement-and-validate gates manifest work on the validator).
- Provider naming unified on `llm-proxy` (his llm-proxy-refresh extension's
  established id) rather than inventing a new one.
- npm:pi-subagents dropped: the workflow layer hard-imports the vendored
  subagent extension (../subagent/index.ts), so the vendored copy is
  authoritative.
- Live models.json: 11 retired aliases dropped, Qwen ctx fixed 262144->131072,
  role aliases added. verify-llm-proxy.sh had the pre-migration
  llm-switch.timblakely.com host - fixed; smoke passes (8 models).
- pi -p on llm-proxy/worker: end-to-end OK from the workstation.
- Deviation from plan C4: the pi key stays deliberately UNSCOPED (its
  manifest documents budget-as-the-bound); role aliases are reachable
  without a scope change.

## 2026-08-22 · Context-vs-parallelism measurement (mini-A1)

Load through the proxy (worker alias/key), unique random prompts (defeats
prefix cache = worst case), max_tokens 16, 6-way concurrent:

- SMALL 6 x ~8k tok: wall 53s, per-req [39.7, 51.0-52.5], 0 preemptions,
  peak waiting 4 (brief prefill queueing). All six genuinely concurrent.
- LARGE 6 x ~55k tok: peak running 2; completions at 121/172/240s; three
  requests hit the worker's 300s timeout. 0 preemptions - the scheduler
  never over-admitted; the constraint was PREFILL BANDWIDTH (~1k tok/s
  aggregate on unique text; 6x55k = 330k tokens = ~5 min of prefill).

Capacity model (KV pool 277,007 tok, ~6% padding waste, cap 6):
  <=16k/agent -> cap-bound: 6 concurrent (KV would hold ~17)
   32k/agent  -> cap-bound: 6
  ~46k/agent  -> crossover (277k/6)
   64k/agent  -> KV-bound ~4, prefill ~70s each
  131k/agent  -> KV-bound 2 (vLLM's own 2.11x)

Practical answer: 6 agents whenever briefs stay <=~32k held tokens (the
designed coordinator workload); large-context fan-out is bounded by prefill
time + the 300s worker timeout before KV. Prefix caching (shared system
prompts) improves the real-world large case. gpu_cache_usage_perc metric
scrape returned 0 both runs - regex/label issue, not trusted; the
running/waiting gauges and preemption counter were the evidence.

## 2026-08-22 · Club 3090 number reconciled

Their "2x concurrency at 262k with ~600k KV" is the W4A16 build at TP=2:
derived KV cost ~48.7KB/token means their pool implies ~13.5GB weights =
the 4-bit build. Same ratio as our FP8 measurement (2.11x) at double the
ceiling. Not a contradiction - the FP8/W4A16 weight-precision-for-KV trade,
quantified: each GB of weights ~ 20k KV tokens. FP8 decision stands
(user-confirmed); W4A16-TP2 remains the recorded fallback if
context-parallelism ever outranks weight quality.

## 2026-08-22 · T1.4 coordinator seat: subscription OAuth, live

The chatgpt/ provider (docs.litellm.ai/docs/providers/chatgpt), landed the
hard way; the record for whoever debugs this next:

1. **Token seeding**: the codex CLI's 9-day-old auth.json was rejected
   (refresh tokens rotate single-use); the DOCUMENTED path is LiteLLM's own
   device flow. Running it LOCALLY (litellm SDK, CHATGPT_TOKEN_DIR set)
   surfaces the device code without racing the pod's ~6.5min liveness window;
   the minted auth.json then ships to the litellm-chatgpt-token PVC via
   kubectl cp. In-pod boots are headless thereafter (refresh in place).
2. **Cloudflare red herring**: the local SDK test hit a CF managed challenge
   on chatgpt.com (workstation egress); the cluster passed. Separate issue
   from:
3. **The real bug — non-streaming is broken upstream**: the Codex backend
   forces SSE even for stream:false; LiteLLM 1.97.0 parses that as "Unknown
   items in responses API response: []" (BerriAI/litellm #37039, #34094; fix
   PRs #35062, #34095 open). **Streaming works.** Every real consumer here
   streams (pi, opencode, subagent children) - only curl-style smokes hit
   the broken path. Re-test non-streaming after the next litellm bump.
4. Model shape matched to Jory's proven entries: typed info.mode: responses,
   additional_drop_params: [temperature], reasoning_effort left to clients.

Verified live: coordinator -> LUNA-OK, worker-escalated + reviewer-escalated
-> ESC-OK (interim on the same subscription seat), and the full harness path
pi --model llm-proxy/coordinator -> COORD-VIA-PI-OK. The OpenAI API account
remains unfunded, as decided; metered planner-gpt stays the dormant hedge.

## 2026-08-22 · Verification: pi access + vision reality check

- pi -> Qwen/Qwen3.8-27B-FP8: QWEN-INTERACTIVE-OK (pi key sees all 10 names).
- Worker text-only re-confirmed in the running pod ("text-only mode" x4).
- Image routing today: coordinator (Luna) ACCEPTS images and answers
  (vision path proven through the chatgpt translation, streaming); the
  local Qwen alias rejects them LOUDLY - vLLM 400 "At most 0 image(s)" -
  the clean failure mode --language-model-only buys (no silent ignoring).
- Honest status: vision is NOT on CPU yet - the worker's tower was REMOVED
  (VRAM -> KV), and the CPU lane is Track D1, still pending. Until D1 lands,
  vision = coordinator only.

## 2026-08-22 · Track D1: CPU vision lane live

- Huihui-Qwen3.5-9B (Jory's proven VLM) + f16 mmproj, llama.cpp CPU on
  kristeva, 16 threads (one socket - avoids the NUMA cliff), 16k ctx.
- **Verified: a red test image answers "Red" - 24.9s cold, 14.8s warm**
  through the full path (pi key -> litellm `vision` alias -> CPU server).
  Thinking is ON for this model; max_tokens must leave room for it (a
  100-token cap returned empty content, all budget spent reasoning).
- pi usage: `/model vision` for the image turn, back to Qwen after
  (pi history is client-side; switching models mid-session is free).
  pi catalogues updated live + in the dotfiles template; coordinator
  entry now declares image input too (Luna vision).
- Gotchas hit and fixed:
  - cache-prime v1 failed fast x3 - almost certainly unauthenticated HF
    rate limiting (debug rerun succeeded in 71s). Consider HF_TOKEN in
    the job for future primes.
  - **RWO chatgpt-token PVC vs rolling updates**: the surge pod landed on
    another node and sat ContainerCreating on the multi-attach; released
    by deleting the old pod. Follow-up chore: move the token PVC to
    cephfs RWX (Phor's documented evolution) or set Recreate strategy.

## 2026-08-22 · ChatGPT sub limits: credit-weighted, with hard multipliers

learn.chatgpt.com/docs/pricing (via developers.openai.com/codex/pricing):
"Usage is calculated in credits per million input tokens, cached input
tokens, and output tokens" and "credit cost varies by model, context,
reasoning, and tools." NOT request-count-shaped (an earlier in-chat claim
of mine, corrected by Tim's challenge).

Credits per 1M tokens:      input   output
  gpt-5.6-sol                100     500
  gpt-5.6-terra               50     300
  gpt-5.6-luna                 5      30

So thinking tokens (output-class) are NOT free - they are ~16.7x cheaper
on Luna than Sol and 10x cheaper than Terra. "Abuse Luna + xhigh" works
by ARBITRAGING the multiplier: a million thinking tokens on Luna costs
the window what ~60k costs on Sol. Plus-tier translation from the docs:
roughly 10-100 messages/5h on Sol vs 250-2000 on Luna.

Decision consequence: Terra-as-default-coordinator is a ~10x window burn
on the token-hungriest role, not a free upgrade. Luna@xhigh as the
default coordinator diet is the credit-optimal shape (and is Jory's
revealed preference - reasoning-pool rung 1); Terra/Sol belong behind an
explicit-choice alias for deliberately-spent hard sessions.

## 2026-08-22 · Seating finalized: Luna@max, coordinator-heavy, K3-via-Kimi-Code

- `max` accepted by the chatgpt backend (verified; xhigh also valid - Phor's
  choice; max is Jory's). Pinned on coordinator + both escalated seats.
- coordinator-heavy -> Terra: explicit-choice, 10x window burn, never a
  fallback. Added to the coordinator key's scope (manual /key/update pushed).
- Jory's Luna usage, for the record: reasoning-pool rung 1 at effort max IS
  Saffron-the-coordinator's primary diet; Luna is absent from frontier-pool
  (hard escalation = Sol/K3). Our shape now matches his exactly.
- GLM 5.3 SKIPPED (volume-lane alternative on record); reviewer-escalated's
  target = K3 via the Kimi Code subscription (api.kimi.com/coding/v1,
  KIMI_API_KEY, effort high never none). Awaiting the key.
- ctx metadata settled at 272000 for the 5.6 family (Phor + Jory's pi agree;
  Jory's litellm yaml said 1050000 - outvoted 2:1; understating is the safe
  direction). Fixed in aliases + both pi catalogues.

## 2026-08-23 · Seating live + token store on RWX

- coordinator@max -> COORDINATOR-OK; coordinator-heavy (Terra) ->
  COORDINATOR-HEAVY-OK; scope pushed past the operator gap.
- RWX migration done the clean way: exported auth.json at its freshest
  rotation, PRE-SEEDED the CephFS RWX claim via a throwaway seeder pod,
  then swapped the mount - the new proxy pod booted headless in 33s with
  no device flow and no attach deadlock. RWO claim pruned.
- The stuck rollout this fixed: deleting the RWO-holding pod mid-roll just
  made its ReplicaSet recreate it (still holding the attach on its node) -
  circular. Pre-seed-then-swap breaks the cycle; the pattern to reuse.
- Wart on the record: one empty commit ("complete the token-store RWX
  migration", c24ab880) pushed after an exec race short-circuited the edit
  chain but not the jj tail; the like-named real commit follows it.
- Remaining in the seating: ONLY the K3 flip, waiting on KIMI_API_KEY.

## 2026-08-23 · K3 seat wired via Moonshot metered (awaiting funds)

- Kimi Code sub is waitlisted, so rung 1 for now = Moonshot metered
  (`api.moonshot.ai/v1`, `openai/kimi-k3`, MOONSHOT_API_KEY). Sub endpoint
  (`api.kimi.com/coding/v1`) promotes to rung 1 when the waitlist clears.
- First ES sync failed with `map has no entry for key MOONSHOT_API_KEY` -
  the 1P field existed but hadn't been SAVED. After the save: forced sync
  via `force-sync` annotation, key present in the secret.
- Smoke verdict: HTTP 429 `account org-729e6b3b... <ak-fc7a7...> is
  suspended due to insufficient balance`. That is the GOOD failure: Moonshot
  authenticated the key (echoes our org + key ids) and LiteLLM routed
  reviewer-escalated to it correctly. Only money is missing; re-smoke for
  `K3-OK` once funded.
- Operational gotcha, will recur: `kubectl rollout restart deploy/litellm`
  does NOT stick - the litellm-operator reconciles the pod template right
  back (strips `restartedAt`, scales the fresh ReplicaSet to 0). The
  reliable env refresh is deleting the pod: `envFrom` re-resolves the
  Secret at container start. (Reloader's annotation is present but the
  operator won the fight; don't count on it.)
- Effort note: K3 on Moonshot's OpenAI-compat endpoint always reasons;
  `thinking` sits in additional_drop_params. Phor's "high, never none"
  rule is about the Kimi Code endpoint and applies when the sub takes over.

## 2026-08-23 · Coordinator key: dollar budget out, rate caps in

- Realization (user question exposed it): every alias in the coordinator
  key's scope is subscription-backed and meters at $0, so maxBudget could
  never trip. Dollar budgets only do real work on the escalation key
  (Moonshot metered) - the sole real-money path.
- Swap: maxBudget/budgetDuration removed; rpmLimit 30 +
  maxParallelRequests 4 added. Rationale: the scarce resource is the 5h
  credit window, which is rate-shaped; caps turn a runaway loop into 429s
  at the proxy instead of a drained subscription.
- Operator gap hit again as expected: CR updated on reconcile but the live
  key kept its old row; manual POST /key/update (rpm_limit,
  max_parallel_requests, max_budget:null) applied it. NOTE: litellm image
  has no curl - exec python3 + urllib is the in-pod pattern.
- Post-update smoke through the coordinator key -> CAP-OK (streamed).
- Worker/reviewer $1 budgets left as-is: local models, also $0, harmless.

## 2026-08-23 · K3 host research: NeuralWatt yes-at-parity, Nous no

- **NeuralWatt** (portal.neuralwatt.com): DOES serve `kimi-k3`, at exactly
  Moonshot's $3/$15 - a same-model rung, not a discount. Also carries
  kimi-k2.7-code $0.95/$4, kimi-k2.6 $0.69/$3.22, glm-5.2 $1.45/$4.50, and
  the deepseek-v4-flash $0.14/$0.28 rung Jory backstops with. Verdict:
  viable as a SAME-MODEL fallback for reviewer-escalated (Phor's rule
  allows it), zero reason to prefer it as primary over the already-wired
  Moonshot seat. Adds an account for redundancy only.
- **Nous Research** (portal.nousresearch.com): catalog is Hermes-family
  only (Hermes 4 405B $1/$3, 70B $0.13/$0.40, DeepHermes 3) plus an
  image-gen tool gateway; subscriptions unlock Hermes access, NOT
  third-party frontier models. No Kimi/Moonshot models at all. Verdict:
  NOT viable for the K3 seat under the same-model rule. (Hermes 4 405B as
  a council seat would be a new decision, and it is not frontier-class -
  the council's diversity slot stays K3.)
- Cross-check: OpenRouter lists 13 K3 providers (Sail $2.60/$13 cheapest,
  Moonshot/Together/Fireworks/Baseten at $3/$15); neither NeuralWatt nor
  Nous among them. Ladder unchanged: Moonshot metered now -> Kimi Code sub
  at rung 1 when the waitlist clears; NeuralWatt on record as rung 3.

## 2026-08-23 · Caps-compose walkthrough (Track E, on paper)

Scenario: a workflow bug makes the implement loop repair forever, fanning
out worker calls each iteration, escalating one review per iteration.

1. **Workflow `maxAttempts` (C1)** - repair loops declare maxAttempts
   (implement-and-review ships 1; registry rule in workflows/README) ->
   the loop terminates in the harness before any flood forms. First line.
2. **Worker/reviewer keys: maxParallelRequests 8 (T1.2)** - even a
   harness that ignores its own limits gets at most 8 concurrent local
   calls per key; excess 429s at the proxy, not at vLLM.
3. **vLLM maxNumSeqs (T1.1)** - whatever gets through shares the fixed
   seat count; overflow queues (peak_waiting visible in /metrics),
   nothing OOMs - KV is block-managed, preemptions counted.
4. **Coordinator key rpmLimit 30 / maxParallelRequests 4 (2026-08-23)** -
   a coordinator-side loop 429s within the minute; the 5h credit window
   cannot be drained mechanically.
5. **Escalation key maxBudget $30/30d (T1.4)** - the only real-money path
   (K3 metered) hard-stops at the budget; interactive local lanes are
   untouched because the block is per-key.
6. **Visibility** - the new Escalations dashboard row (requests, spend,
   tokens by seat, budget-left stat) makes the event legible after the
   fact; the why lives in the workflow's saved review/repair artifacts.

Every layer catches a different failure shape; no single bug bypasses
more than one layer. Composition confirmed on paper - Track E closes.

## 2026-08-23 · A1 seat sweep at maxNumSeqs 8 - VERDICT: pin 8

Method: worst-case prefix (random 8-hex tag + shuffled words per request),
prompt/completion shape cycle (4k/512, 8k/1024, 16k/2048), ignore_eos,
streaming, 3 requests per worker, direct to vLLM via port-forward.
KV pool at 8 seats: 275,656 tokens (2.10x @ 131k - unchanged from 6).

| conc | n  | agg out tok/s | seat tok/s med | TTFT p50/max | ITL p50/max | preempt | peak wait |
|------|----|---------------|----------------|--------------|-------------|---------|-----------|
| 2    | 6  | 76.3          | 55.1           | 11.3/12.8s   | 19/26ms     | 0       | 0         |
| 4    | 12 | 103.5         | 34.9           | 11.5/22.5s   | 29/64ms     | 0       | 0         |
| 6    | 18 | 115.3         | 24.9           | 11.7/40.0s   | 44/95ms     | 0       | 3         |
| 8    | 24 | 121.8         | 21.4           | 11.8/48.3s   | 50/96ms     | 0       | 4         |

- Aggregate saturates at ~122 tok/s; 6 -> 8 is +5.6% agg for -14% per-seat.
- ZERO preemptions at every level: at worker shapes (<=18k KV/seat) even
  8 full seats use ~144k of the 275k pool. The ceiling is free.
- TTFT p50 ~11.5s is the known prefill bandwidth bound (~1k tok/s on the
  8k median prompt), constant across levels; the tail (48s at conc 8) is
  prefill queueing, matching peak_waiting 4.
- Verdict: PIN 8. Seats-over-ceiling holds; table lives in the manifest.

## 2026-08-23 · A2 MTP three arms at the pinned 8 seats - VERDICT: keep 3

Same harness, conc 1 (interactive regime) + conc 8 (saturated regime):

| arm   | conc1 seat tok/s | conc1 ITL | conc8 agg | conc8 seat med | conc8 ITL p50 |
|-------|------------------|-----------|-----------|----------------|---------------|
| MTP=3 | 89.2             | 11.2ms    | 121.8     | 21.4           | 50.1ms        |
| MTP=2 | 61.7             | 16.2ms    | 114.8     | 20.5           | 50.2ms        |
| off   | 44.4             | 22.6ms    | 105.6     | 16.7           | 63.3ms        |

- MTP=3 wins BOTH regimes: 2x single-seat decode over no-MTP, and still
  +15% aggregate at full saturation - on dual 3090s the batch-8 decode is
  bandwidth-bound, so accepted speculative tokens are nearly free.
- Phor's citations (model card recommends 2; vLLM warns >1 lowers
  acceptance on one MTP layer) both LOSE to 3 on this build, measured.
  His middle arm did not win; cogito's original 3 stands.
- Ops wart: the A2-off arm hit a dead local SSH agent mid-flight (push
  impossible), so the arm was applied by suspending the llmkube-resources
  ks and patching the InferenceService directly - repo and cluster were
  reconverged at the final pinned config afterward.

## 2026-08-23 · D2 MoE lane trial - VERDICT: deleted, 0.6 tok/s

DeepSeek V4 Flash UD-IQ3_S (~110GB, NFS archive) via llama.cpp CPU on
kristeva, --numa distribute, 32 threads, ctx 8192, request 80Gi/limit
115Gi. Cold load off NFS: ~33 min to ready.

- Decode: 0.47 / 0.76 / 0.89 / 0.61 tok/s across four runs (100-150 tok
  each). ~8% of the 5 tok/s bar - not close, no tuning rescues 8x.
- Why: the A3 prediction held and compounded - AVX-only decode ceiling,
  plus the model (~110GB) never fit resident beside the floor pods
  (~53GiB RSS peak; the rest re-faulted from NFS per expert activation).
- Per plan: manifests deleted the same hour, number recorded here.
  kristeva's lanes stay D1 vision + camofox + the A380 floor.

## 2026-08-23 · Addendum: flux resume applies the STALE revision first

`flux resume kustomization` immediately re-applies the last-FETCHED
revision before any source refresh - resuming llmkube-resources after the
SSH outage applied the mid-experiment MTP=2 commit and rolled the backend
once more before the follow-up reconcile restored the pinned config
(cost: one extra ~3.5min model load). Next time: reconcile the SOURCE
(`flux reconcile source git ...` or ks --with-source WHILE SUSPENDED is
not possible - so push first, refresh the GitRepository, THEN resume).
Converged state verified after: RS hash matches the pinned config,
CONVERGED-OK through the proxy, dashboard synchronized.

## 2026-08-24 · K3 seat LIVE

- User funded Moonshot with $30 (one-time, manual recharge, same key).
- Re-smoke: `K3-OK` streamed through reviewer-escalated on the escalation
  key. The council's second family is live; ladder unchanged (Kimi Code
  sub still promotes to rung 1 when the waitlist clears).

## 2026-08-28 · D4 prep: qwen4exp (Qwen3.8-Flash-Next) on kristeva

Target: `Qwen/Qwen3.8-Flash-Next` (released 2026-08-24), experimental
`qwen4exp` arch — core LM 125B total / **6B active** MoE (512 experts,
top-10 + 1 shared, 48 layers, hidden 2560) + a **51B-param n-gram table**
(20M × 2560, bigram/trigram, layer 2, pure lookup) + 4B MTP head. First
candidate where the RAM math plausibly clears the 5 tok/s bar (6B active
at 4-bit ≈ 2.5–3.5 GB streamed/token vs the A3 ceiling).

Verified facts (all 2026-08-28):

- **Runtime in a release.** llama.cpp PR #27742 (qwen4exp + QSA graph)
  merged 2026-08-27; ancestor of **b10666** (`4e97ac86e`, built 2026-08-28)
  — no master build needed. The n-gram table is a plain tensor
  (`per_layer_token_embd`, ~97.7 GiB full-precision) pulled via
  `ggml_get_rows`; per-token cost is 1–3 rows ≈ 2.5–7.5 KB, so a
  page-cache miss is a few ms, not a re-fault pathology. **No MTP
  support in the PR** — watch item (A2: MTP=3 ≈ 2× decode).
- **Image.** `ghcr.io/ggml-org/llama.cpp:server-intel-b10666` (pin amd64
  `sha256:394b0fd7a15f527480c6c9e6ed0a75d5bc5861cfc89b4b8cc6628cd14fc52d3f`).
  Ships `libggml-cpu-ivybridge.so` — the exact ISA match for kristeva
  (SSE4.2+AVX+F16C; live cpuinfo: `avx`+`f16c` only). No custom build.
- **Gotcha (reproduced on kristeva via scratch pod):** the image
  auto-loads `libggml-sycl.so`; its oneAPI runtime throws `can not find
  preferred GPU platform` on GPU-less hosts, crashing even `--version`
  (newer oneAPI behavior — D2's older image didn't throw). Fix verified:
  command preamble `mv /app/libggml-sycl.so{,.disabled}`.
- **Storage.** kristeva's 2 TB NVMe (`nvme0n1p1` →
  `/var/mnt/local-hostpath`, XFS, `openebs-hostpath`, ~1.8 TB free) → new
  ~120 GiB hostpath PVC pinned to kristeva for the
  `unsloth/Qwen3.8-Flash-Next-GGUF` **UD-Q4_K_XL (103.6 GiB)**. D2's
  NFS-re-fault failure mode does not apply: only ~5 KB/token of table rows
  can miss, against NVMe.
- **RAM / storage split.** Core + table are ONE 103.6 GiB GGUF on the NVMe
  hostpath, mmap'd; stock llama.cpp has no per-tensor pin/stream flag, so the
  page cache is the streaming layer: core (~60 GiB, touched across every
  sequence) stays resident; the table (~40 GiB at this quant; 97.7 GiB
  full-precision) is looked up ~2–3 rows (~2.5–7.5 KB)/token — hot rows
  cached, the rest **streams from NVMe** (<1 ms/token, negligible). Best
  case: ~115 GiB free ≥ file, so the whole thing also warms into cache
  (bonus, not the assumption). Risk: LRU doesn't protect core pages under
  pressure — re-fault would be from NVMe (~1–3 GB/s, ms), not D2's NFS
  stall. Pod req ~100 Gi / limit ~118 Gi.
- **NUMA verdict: two-arm bench, single socket favored.** llama.cpp has
  NO CPU TP / layer-parallelism (one global thread pool reads every
  tensor; `-ngl`/`--tensor-split` are GPU-only). `--numa distribute` is
  round-robin thread affinity only — confirmed in source, and no
  `set_mempolicy`/`mbind` symbols in the b10666 binaries → each thread
  reads ~50% of its bytes over QPI. True per-node sharding = stalled
  PR #14232 (`GGML_NUMA_MIGRATE`, open since Apr); `--numa mirror`
  (#16000, draft, +41% TG on Xeon 6238R) needs 2× RAM — fatal at 128 GiB.
  Measured prior (A3): 70.9 GB/s @ 8 threads vs 52.7 @ 32. Arms: (A)
  numactl socket-0 bind, 8–10 physical threads; (B) `--numa distribute`,
  20 threads. Expect A ≈ 1.25× B; B surprises only via MoE scatter.
- Cross-checked the "no CPU TP" claim with a claude second opinion:
  agreed, and supplied the PR numbers above (all verified real/open).
- Second claude cross-check (optimization plan) surfaced 5 fixes, all
  adopted: (1) strict `--membind=0` is broken for a 103.7 GiB mmap on a
  64 GiB node → `--membind=0,1`; (2) `--numa` flips the mmap policy to
  MADV_RANDOM (verified at b10666 `src/llama-mmap.cpp:472,507`) → arms A/C
  share a no-`--numa` mmap policy, B = as shipped; (3) bandwidth- vs
  compute-bound is OPEN (no AVX2 → Q4_K dot at a few GB/s/core could make
  20 cores across both sockets win) → decision rule: effective GB/s =
  bytes/token × tok/s, <30 ⇒ compute-bound ⇒ favor arm C; (4) my
  250–1400× table/core per-token ratio was off 1000× (true:
  2×10⁵–1.4×10⁶ — conclusion unchanged, stronger); (5) KV → f16 (q8_0
  saves ~1 GiB only), `-tb 20 -t <arm>`, budget corrected to core
  ~63.6 GiB / ~81 GiB needed / ~47 GiB headroom, pod req 85 / limit 110
  (file page cache is cgroup-charged, reclaimable), SLO
  pgmajfault/token ≤ 10. New Q arm: UD-Q3_K_XL (83.8 GiB, verified in the
  HF repo) for ~25% fewer bytes/token + smaller footprint.

Plan of record: `plans/llm/d4-qwen4exp.md`. Steps: PVC → copy GGUF →
manifest (SYCL rename + arm-A args) → load check → bench A × 3, B × 3 →
D4 entry here with the bar verdict. Kill: < 2 tok/s warm both arms →
delete same hour per D2 precedent.

## 2026-08-28 · D4 results: qwen4exp on kristeva — FAIL (close), 4.0–4.6 t/s warm

Ran ~20:30–21:10 MDT. Image `server-intel-b10666` (digest-pinned), SYCL lib
renamed (required — see prep entry), 8k ctx, f16 KV (default), `-tb 20`,
393-token fixed prompt + 128-token gen × 4 rounds/arm (rounds 2–4 reuse
server prompt cache: only 4 new prompt tokens — decode numbers unaffected,
warm prompt-eval not measured).

| arm | config | warm gen t/s (r2–r4) | cold gen r1 | notes |
| --- | --- | --- | --- | --- |
| A | `taskset 0-9` (socket-0 10 phys), `-t 10` | 3.97 / 4.03 / 3.95 | 3.91 | cold: 47 s load + 70 s r1 (drop_caches) |
| B | `--numa distribute`, `-t 20`, no taskset | 4.62 / 4.58 / 4.67 | 4.62 | MADV_RANDOM mmap (verified confound) |
| C | `taskset 0-9,10-19` (20 phys both sockets), `-t 20` | 4.50 / 4.43 / 4.52 | 4.60 | same mmap policy as A |
| Q | Q3_K_XL (83.8 GiB), C config | 4.47 / 4.25 / 4.42 | 4.22 | 25% fewer bytes/token |

Cold prompt eval (r1): A 10.4 t/s, B 18.3, C 19.0, Q 13.0.
Memory: RSS(anon) ~3.7→7.4 GB; model pages in page cache
(75–97 GB buff/cache); pgmajfault warm arms ≈ 0–480. No OOM, no faults
at the 110 Gi limit. Q4 output quality is good (crontab parser: correct
semantics + type hints; 17-sheep trap: correct).

**Verdict: FAIL — best warm 4.67 t/s (B) < 5 t/s bar; well above the
2 t/s kill line.** Config space is exhausted: 20 physical cores over both
sockets bought only ~15% over 10 local; the mmap-policy confound (arm B)
mattered not at all; and Q3 — 25% fewer bytes per token — was no faster
(4.4 vs 4.6). That last point is the tell: decode is **compute-bound in
the AVX1/F16C Q4_K dot paths** (~15 GB/s effective = compute ceiling,
not DRAM ceiling), confirming the cross-check's hypothesis. NUMA design
(arms A/C, membind caution, no-CPU-TP analysis) all validated as planned.

**Why it still matters / what would move it:**
- MTP is the big lever: A2 showed MTP=3 ≈ 2× decode upstream. Once
  llama.cpp merges MTP for qwen4exp, expect ~9–10 t/s on this exact
  hardware → passes with 2× margin. Watch ggml-org/llama.cpp.
- The Q4_K_XL weights stay on kristeva NVMe
  (`/var/mnt/local-hostpath/d4-qwen4exp/`, 103.7 GiB + Q3 83.8 GiB) for
  quality play and the MTP re-run. Delete with
  `rm -rf /var/mnt/local-hostpath/d4-qwen4exp` (talos exec or helper pod)
  if not wanted — 187 GiB of 1.7 TB free.
- All d4 pods deleted (d4-bench, d4-download, d4-download-q3).

## 2026-08-29 · D4 v2: qwen4exp on iggy — PASS, 6.65 t/s decode / 52.95 t/s prefill

Re-ran D4 from scratch on iggy. The 2026-08-28 entry's numbers hold but its
**bottleneck model was wrong**, and fixing it produced a large speedup.
Full writeup: `plans/llm/d4-qwen4exp-results-v2.md` (v1 kept, banner added).

**What v1 got wrong.** It assumed 3.3 GB/token, computed 16.5 GB/s effective,
and concluded "per-core random-block DRAM streaming wall" with 1.5–2× of
efficiency unaccounted for. Two measurements kill that:

- A purpose-written microbenchmark (`bench/membw.c`, random 6.4 MB blocks =
  the MoE access shape) sustains **45–46 GB/s** at 4+ threads on iggy and
  **26.8 GB/s from one thread**. THP makes no difference. No per-core wall.
- The Zen2 DF counters (`amd_df/dram_channel_data_controller_{0,1}/`, 64 B
  each, calibrated against the microbenchmark) show decode pulling
  **34.0 GB/s at ~4.7 t/s = 7.2 GB/token**, i.e. **73% of the real ceiling**.
  llama.cpp was already near the wall; there was never 2× to recover.

**Why 7.2 and not 3.3 GB/token: the quant mix.** `UD-Q4_K_XL` keeps every
*dense* tensor at **Q8_0** — `attn_qkv` (36 SSM layers), `attn_gate`,
`ssm_out`, `attn_q/o/k/v` (12 full-attn layers), the four `hc_*`
hyper-connection projections, the shared expert and the LM head: 4.2 B active
params, **4.4 GB/token, 72% of all traffic**. They are only 8.6 GiB of the
103.7 GiB file (the 512-expert FFNs dominate the file but are read 10/512 at a
time), so they are invisible if you size by file. This also explains v1's
"Q3_K_XL was no faster" tell, which v1 read as evidence of a compute bound:
the whole UD ladder shrinks only the routed experts.

**Fix: requantize locally, no download.** `llama-quantize --allow-requantize
--pure` copies tensors already at the target type, so only the ~9 GiB of Q8_0
is re-encoded (from Q8_0, so ≈ quantizing from BF16). Two builds on iggy's
second NVMe (`/var/mnt/local-hostpath/d4-work/`):

- **D4S** (dense→Q4_K, LM head Q6_K): 100.31 GiB, 4.87 BPW, 2.3 min.
- **D4X** (+ `ffn_down_exps`→IQ4_NL, LM head→Q4_K, i.e. every hot tensor on a
  *repacked* kernel): **93.13 GiB, 4.52 BPW**, 16.8 min.

Row length decides what is legal: k-quants need `ne[0] % 256 == 0`, and
`ffn_down_exps` is `[640,…]` / `hc_*_up` is `[320,…]` — which is why unsloth
used Q5_1 there. IQ4_NL is the fast legal choice. `ffn_gate_inp` cannot be
quantized (llama.cpp forces F32 routers) — 252 MB/token floor.

**Result** (paired, same session, back-to-back, `OMP_PROC_BIND=spread`):

| model | pp2048 t8 | tg64 t8 | pp2048 t12 | tg64 t12 |
| --- | --- | --- | --- | --- |
| UD-Q4_K_XL | 21.41 | 4.61 | 29.51 | 4.86 |
| **D4X** | 37.20 | **6.65** | **52.95** | 6.51 |

**+44% decode, +79% prefill.** Best observed 6.88 / 53.14. Quality smoke
passes (17-sheep → 9; 17×23 → 391; Canberra; valid cron parser).

**RAM — the design is right, the mechanism isn't what the plan assumed.**
llama.cpp's CPU **repack** buffer type copies every `mul_mat` tensor out of
the mmap into **anonymous** memory: `CPU_REPACK model buffer size =
67060 MiB`, `RssAnon 66.3 GiB`. That is pinned and unreclaimable — dropping
the cgroup limit to 62 GiB **OOM-killed the pod**; ~68 GiB is a hard floor.
The PLE/n-gram table is never repacked (only `ggml_get_rows` touches it), so
it stays file-backed and streams from NVMe. Measured: **~12.5 major faults and
~63 KB of NVMe per token**, and a repeated prompt (`cache_prompt:false`) goes
from 11,761 major faults to **exactly zero** — the page cache already *is* the
hot-n-gram cache. But it cannot be usefully pre-warmed (320 M rows): sweeping
the limit 72/80/88 GiB moved resident file cache 3.8→18.9 GiB and changed the
fault count by <0.2% and throughput not at all. **Size the pod ~72 Gi request
/ 80 Gi limit and stop.**

**Negative results worth not repeating:** THP (no effect on raw bandwidth, and
forcing `enabled=always` converts 43–59 GiB of the repack buffer to 2 MiB
pages with no throughput change); SMT; `-ub` tuning (default 512 is best);
b10679 built from source with `GGML_OPENMP=OFF` (decode identical, prefill 11%
*worse* than the IntelLLVM/libiomp5 image — PR #27880's graph-split reduction
is not a decode lever here); two models in one `llama-bench` process (OOMs).

**Thread placement reverses with the bottleneck.** On the stock model binding
hurt (4.11 bound vs 4.93 unbound). On D4X, off the bandwidth wall, it helps and
cuts variance: pp2048 42.62 ± 3.51 unbound → 49.11 ± 1.91 with
`OMP_PROC_BIND=close`; `spread` gives the best decode (6.75). Re-test tuning
knobs after changing the bottleneck.

**Cluster findings.**

- **v1 §8's unattributed 27B restart is Talos's userspace OOM controller.**
  `dmesg` shows `runtime.OOMController` SIGKILLing whole cgroups under the
  bench's memory pressure; the four victim UIDs are `llm/qwen-3-8-fp8`,
  `cluster-infra/dcgm-exporter`, `home-infra/immich-db-3` and
  `llm/open-webui-db-2` — **all BestEffort**. `qwen-3-8-fp8` has no requests at
  all, so the most important GPU workload is the first OOM victim. Give it
  requests/limits. After capping the bench pod at 86 Gi, zero further node OOM
  events.
- **v1 §9.4 is wrong**: iggy's `/var/mnt/local-hostpath` exists and is mounted
  (`/dev/nvme1n1p1`, 931 GB, **475 GB free**); its openebs PVs are live. Put D4
  artifacts there, not on nvme0n1p4 (the Talos EPHEMERAL partition, 116 GB
  free — a ~95 GiB write would cross kubelet's `nodefs.available<10%`).
- `kubectl patch pod … --subresource resize` (k8s 1.34) changes a running
  pod's memory limit with no restart — the right tool for page-cache sweeps.
- Do **not** set `LD_LIBRARY_PATH=/app` (clobbers oneAPI → `libsvml.so` not
  found); prepend instead.
- 27B co-tenancy at `-t 8`: 27B ran 72–76 t/s before, 65–66 during, **62–63
  after** — the downward drift is its own, so t8 has no distinguishable cost,
  while the CPU lane still did 6.42 t/s decode / 51.7 t/s prefill alongside it.
  v1's t16 ban stands.

**Concurrency reversal.** v1 §E3's "4-way batching → zero aggregate gain" was
measured at the bandwidth wall and does not survive. `llama-batched-bench` on
D4X (`-npp 512 -ntg 128 -t 8 -tb 12`): B=1 → 6.78 t/s decode / 54.25 prefill;
B=2 → 8.99 (+33%); **B=4 → 11.75 t/s aggregate (+73%) / 57.79 prefill**. The
dense tensors are read once per batch, so they amortise across sequences. Run
the lane with `-np 4`. This also withdraws v1 §6's MTP retraction, which was
derived from the E3 result.

## 2026-08-31 · D4 v3: engine sweep on iggy — MTP lands, 10.9 t/s, vLLM ruled out

Full writeup: `d4-qwen4exp-results-v3.md`. Same box, same D4X model, same
RAM/NVMe design as v2 — this pass sweeps engines and versions rather than
quantization. Bench pod `d5-bench` (hostPath `/var/mnt/local-hostpath`, 8 CPU /
72 Gi req, 80 Gi limit); the 27B GPU lane stayed up with zero restarts and no
Talos OOM events.

**Mainline moved nothing; the compiler did.** `b10666` is still the newest
published `server-intel` tag (b10679/b10690/b10700/b10720 all 404 on GHCR).
`llama-bench` on D4X, `-p 2048 -n 64 -r 3`, `OMP_PROC_BIND=spread`:

| build | pp2048 t8 | tg64 t8 | pp2048 t12 | tg64 t12 |
| --- | ---: | ---: | ---: | ---: |
| b10666 image (IntelLLVM) | 41.02 | 7.00 | 53.32 | 6.76 |
| b10720 release tarball (GCC) | 35.74 | 6.93 | 47.60 | 6.82 |
| PR #27836+#28097 source, GCC | 36.01 | 6.90 | 47.65 | 6.86 |
| **same source, `icx`/`icpx`** | **40.94** | 6.88 | **53.14** | 6.71 |

So v2 §4's "stay on the b10666 image" was really "stay on oneAPI" — rebuilding
any branch with `-DCMAKE_C_COMPILER=icx -DCMAKE_CXX_COMPILER=icpx` recovers the
whole prefill gap. Decode is pinned at 6.7–7.0 t/s regardless of build.

**MTP works on CPU — the v2 §12 lever, collected.** PRs #27836 (draft head,
`--spec-type draft-mtp`) + #28097 (draft-head-only GGUFs, and a fix where `-md`
loaded the 93 GiB *target* again). Draft pack:
`dzannotti/Qwen3.8-Flash-Next-MTP-Q4_K_M.gguf` (2.44 GiB), pairs with the
unmodified D4X. **One patch was needed** — that pack ships the head mixer under
the trunk names `output_hc_{norm,down,up}` (→ `model.hc_head_*`), which #28097's
fallback chain does not know, so the server aborted at
`qwen4exp.cpp:497 GGML_ASSERT(head_norm && head_down && head_up)`. Fix kept as
`bench/qwen4exp-mtp-trunk-mixer-fallback.patch`; send upstream.
`LLAMA_ATTN_ROT_DISABLE=1` is mandatory.

Single stream, 256-token completions, oneAPI build, `-t 8 -tb 12 -np 1`:
no-spec 6.88 → **MTP `n-max 3 p-min 0.75` 10.64–10.75 t/s on code, 9.45–9.48 on
prose** (+56% / +38%), acceptance 0.89, mean draft length 2.8–3.2. The
confidence gate is the knob: `p-min 0` drops acceptance to 0.60 and costs 13%;
`n-max` 2/3/4 are all within noise of each other.

**MTP and batching compete — they do not compose.** Aggregate t/s, 4 fixed
prompts × 192 tokens with `ignore_eos`:

| slots | no spec | MTP n3 p0.75 |
| --- | ---: | ---: |
| `-np 1` | 6.70 | **10.47** (10.90/stream) |
| `-np 2` | 8.51 | 9.00 |
| `-np 4` | **10.52** (2.70/stream) | 9.21 |

One MTP stream equals four plain streams in aggregate at 4× the per-stream rate;
stacking them is 12% *worse* than plain batching at `-np 4`. Acceptance stays
0.82–0.94 there, so it is bandwidth contention, not draft quality. v2 §14's
"run with `-np 4`, it's free" is now conditional on genuinely having four
concurrent agents. **Lane default: `-np 1` + MTP.**

Memory with the draft head: `RssAnon` 68.9 GiB (v2: 66.3), `VmHWM` 89.5 GiB at
`-c 32768`. Pod sizing moves to **76 Gi request / 84 Gi limit**.

**MTP output is not byte-identical to non-MTP on CPU** (unlike #27836's Metal
report). Two greedy smoke prompts diverge at a single near-tie token each
(`riddle:` vs `riddle.`; `(Monday through Friday).**` vs `)**.`) while staying
correct. Verifying a 3-token draft uses different GEMM shapes than a 1-token
step, so argmax coin-flips resolve differently. Do not use MTP on/off as a
regression oracle.

**vLLM: ruled out on iggy, both paths.** Support merged today
(vllm-project/vllm#53896) but lives only in `vllm/models/qwen4_exp/{nvidia,amd}/`
— no `cpu/` tree, the package raises `NotImplementedError("Qwen4Exp currently
supports CUDA and ROCm only")`, the PR ships
`csrc/libtorch_stable/gdn/fused_gdn_decode_kernel.cu`, and integration is via
`vllm/v1/worker/gpu/*`. So the all-RAM configuration is not expressible at any
version or nightly. The GPU fallback fails on size: FP8 172.8 GiB / int4 W4A16
167.5 GiB on disk, and the int4 card (which explicitly targets 4–8× RTX 3090)
needs **~66 GB GPU-resident** after `VLLM_PLE_CPU_OFFLOAD=1` moves the 51B PLE
table to host RAM — against iggy's 48 GiB of VRAM. Reopens only on a CPU backend
for qwen4_exp or ≥96 GB of VRAM.

Untested and now the largest lever: a GPU-hybrid llama.cpp arm (`--n-cpu-moe`,
dense/attention on a 3090, experts in RAM). Out of scope here — the brief was
all-RAM and both 3090s are held by the 27B lane.

## 2026-09-01 · flashnext shipped: the D4 lane as a real deployment

`flashnext` is live in the `llm` namespace and published through LiteLLM.
Manifests: `kubernetes/apps/llm/llmkube/resources/flashnext{,-stage}.yaml`,
`kubernetes/apps/llm/litellm/app/models/flashnext.yaml`.

**llmkube already models this.** `speculativeDecoding: {type: draft-mtp,
draftModelRef, nDraftMax, pMin}` renders exactly the flags v3 benchmarked:
`--spec-type draft-mtp -md <draft> --spec-draft-n-max 3 --spec-draft-p-min 0.75`.
No extraArgs needed for speculation.

**Gotchas found while deploying (all confirmed live):**

- **`pvc://` sources reject a file set.** `source: <prefix>` + `files: [a, b]`
  fails the Model with `InvalidFileSet`: "multi-file staging requires a
  HuggingFace repo or s3:// source". Fix: the draft head is its own `Model` CR
  on the same PV, joined by `speculativeDecoding.draftModelRef`. The operator
  mounts the claim once at `/model-source` and both files resolve inside it -
  and pvc:// is mounted READ-ONLY with no copy, which is the only reason a
  93 GiB model can be served without a second copy in the hot-tier cache.
- **A static `local:` PV with node affinity is the right shape** for weights
  that must stay on one node's NVMe. Same pattern as `llm-model-archive`, but
  `local:` + `nodeAffinity` instead of `nfs:`.
- **`resources:` on an InferenceService takes requests only** (cpu/memory, no
  limits knob). That is what we want here: a memory limit turns the reclaimable
  page-cache half of a 99 GiB RSS into an OOM kill.
- **The binary comes from a hostPath**, not the image: MTP for qwen4exp is still
  two open draft PRs. `command:` is wrapped in `bash -c ... "$@"` purely to
  PREPEND to the image's `LD_LIBRARY_PATH` - replacing it breaks oneAPI and
  llama-server dies on `libsvml.so`.
- The staging Job builds in **2m21s** at `-j 12` and is idempotent, so Flux
  re-applying it is a no-op.

**As-deployed throughput** (single request, warm, `-np 1`):

| path | code | prose |
| --- | ---: | ---: |
| `/completion` | 10.69 / 10.71 | — |
| `/v1/chat/completions`, thinking on | 9.82 / 9.93 / 9.98 | 7.76 / 7.93 / 7.97 |
| `/v1/chat/completions`, thinking off | 10.54 | — |

Draft acceptance 0.90-0.93, mean draft length 2.4-3.0. Cold start 82 s. The raw
path reproduces v3's bench exactly, so the deployment is not leaving anything on
the table; the chat gap is the `<think>` token mix, which drafts worse than code.
Clients that do not need the reasoning trace should send
`chat_template_kwargs: {"enable_thinking": false}`.

**Collateral fix.** `qwen-3-8-fp8` was still BestEffort with only `gpu: 2`
requested, which made the cluster's most important GPU workload the Talos OOM
controller's FIRST victim (v2 S7 recorded four such kills). With flashnext now
holding ~69 GiB of anonymous memory on the same node permanently, that pressure
is no longer transient, so the lane got `cpu: 2 / memory: 10Gi` - enough to buy
Burstable, honest against its ~5.3 GiB of worker RSS. iggy now sits at 87% of
memory requests.

## 2026-09-01 · flashnext: 8192 was the wrong ceiling, and what depth costs

The lane shipped with `contextSize: 8192` because that is what the v3 throughput
arms used. The first real agentic turn against it - "look over my cogito
repository and give me an overview" - died on its opening tool result:

```
litellm.ContextWindowExceededError: request (8907 tokens) exceeds the
available context size (8192 tokens) ... model=flashnext
```

One `ls -la` plus a `jj log` was already over. **Bench parameters are not
serving defaults**; re-derive each one against the real workload.

Now `contextSize: 131072` on the backend, mirrored as `maxInputTokens: 131072`
on the alias, `contextWindow` in `~/.pi/agent/models.json` and its
`models-store.json` snapshot. KV cost is minor - `RssAnon` went 68.9 -> 71.5 GiB
(~2.6 GiB), which the existing 76Gi request still covers.

**Depth is what actually costs, and it costs on both axes.** Synthetic prompts,
`cache_prompt: false`, 128-token generations, single slot:

| prompt depth | prefill t/s | decode t/s | cold prefill wall |
| ---: | ---: | ---: | ---: |
| 971 | 51.98 | 9.19 | 18.7 s |
| 4,043 | 50.47 | 8.88 | 80.1 s |
| 16,139 | 42.07 | 7.41 | 383.6 s |

Draft acceptance holds across the range (0.80-0.86, mean length 2.9-3.2), so the
decay is NOT the draft head giving up - it is attention and the QSA indexer
getting more expensive with depth, the CPU face of ggml-org/llama.cpp#28012.

**So the >10 t/s headline is a short-context number.** At the ~9k depth of the
failing request, expect ~8.5 t/s and ~3 min of cold prefill. Quote 7-9 t/s for
real agentic turns and keep 10.7 for what it is: a near-empty context.

Consequence for the alias: the timeout went 900 -> 3600 s. At 42 t/s a 16k cold
prompt is already 384 s, and 900 s could not serve the 131072 window the alias
advertises. Prompt-prefix caching is what makes long sessions viable in practice
- an incrementally-growing conversation only prefills the delta - so the long
timeout covers the cold-miss case, not the common one.

**End-to-end proof at the depth that failed.** Through LiteLLM, cold prefix:
streaming ~10.4k prompt -> 141 s to first token, 146 s total, correct answer;
non-streaming 11,784-token prompt -> 268 s, correct answer. One earlier
non-streaming attempt returned a gateway 503 ("connection termination"), but
that was self-inflicted - the litellm pod was being rolled by the operator
mid-request as my own timeout change reconciled. Envoy is not implicated: its
BackendTrafficPolicy already sets `requestTimeout: 0s`.

**Rollout papercut.** llmkube's Deployment uses the default RollingUpdate
(25% surge). With a 76Gi request on a 127.6 GiB node, two copies do not fit, so
a pod-template change leaves the new pod `Pending` forever. Delete the old pod
by hand to let the rollout proceed; `rolloutPolicy` controls idle-waiting, not
surge.
