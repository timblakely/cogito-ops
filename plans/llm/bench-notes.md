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
