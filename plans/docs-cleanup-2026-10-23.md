# Cogito documentation inventory — 2026-10-23

Sixty-eight tracked Markdown files (~8.4k lines), each classified against live cluster
state. Every verdict below is a doc claim checked against `kubectl`/`helm`/`flux` output or the
manifest sitting next to the doc — never against the doc's own age.

| bucket | files | lines | default action |
|---|---|---|---|
| `outright-incorrect` | 4 | 409 | fix now |
| `out-of-date-but-relevant` | 21 | 2279 | fix named claims / add superseded-by header |
| `no-longer-relevant` | 8 | 2737 | archive |
| `vestigial` | 7 | 152 | delete |
| `current` | 28 | 2856 | keep |

Method note: a doc's date is not evidence. Dated benchmark reports are the *record*, not
the guidance — being old is not a defect. The four `outright-incorrect` entries are live-facing
docs (READMEs, a runbook, a bundled skill) whose claims are false about objects that exist today.


## 1. Outright incorrect — contradicted by live state (fix first) — 4 files

| file | verdict | action |
|---|---|---|
| `kubernetes/apps/llm/hermes/README.md` (72L) | Model-routing paragraphs describe the retired v4 seats: 'Direct sessions use the coordinator alias by default' (configure.py: the seat was retired; default is flashnext-deleuze on both providers) and 'the key is limited to exactly those three model aliases' vs the live hermes LiteLLMVirtualKey carrying 8 models — an agent trimming the scope to match this doc would break the in-cluster agent itself. Bundle/seeding, Matrix, OIDC and secret sections all verify. | Rewrite the provider/key section to the live 8-alias catalogue with flashnext-deleuze default |
| `kubernetes/apps/llm/hermes/app/agent-bundle/skills/cogito-llm-change-validation/SKILL.md` (100L) | Ships a physically false hardware fact to an agent that will act on it: 'Kristeva GPUs: A380 ...; RTX 3090 = 02:00.0 (nvidia)' while `kubectl get node kristeva` reports nvidia.com/gpu=0 (the card moved to iggy). PriorityClass/cache-PVC facts verify; otherwise it is materially older than the workstation copy (missing the self-session-kill warning and 2 references). | Fix the kristeva-3090 line in BOTH copies, re-sync, regenerate |
| `kubernetes/apps/llm/litellm/app/models/README.md` (108L) | The whole 'Role seats'/'Metered frontier' taxonomy documents aliases that no longer exist — coordinator, coordinator-heavy, planner, planner-local, planner-gpt, planner-gpt-pro, reviewer, scout, worker-escalated (deleted by ab8324d; `kubectl get litellmmodels` shows 8 aliases) plus the 'vision' lane (deleted 49624bf). Context budgets are wrong too: it claims 262144/131072 while worker.yaml and qwen3-8-27b.yaml both set maxInputTokens: 65536. Live aliases it never mentions: coder, gemma-4-12b, flashnext-deleuze. | Rewrite to the live 8-alias catalogue and correct the ceilings; mechanism sections stay |
| `services/gateway/RUNBOOK.md` (129L) | On-call steps fail as written: `kubectl -n llm logs deploy/foreman-agent` -> NotFound (live deploy is foreman-execution-agent); 'two Ready FleetNodes / scouts FleetNode' vs one FleetNode with roles [worker, coder, verifier]; 'Both reviewers must return GO' enforces a deleted reviewer role. | Fix now: single execution FleetNode, correct deploy name, drop the reviewer/quorum gate until the redesign lands |

## 2. Out of date but relevant (fix or header-note) — 21 files

| file | verdict | action |
|---|---|---|
| `README.md` (140L) | Hardware table omits the live node `amnesia`; Talos badge says 1.12|1.13 vs live v1.14.4/v1.14.2/v1.12.5; only nuc-1 credited with Rook-Ceph though all three NUCs carry rook-ceph-core. | Fix Talos badge, add amnesia row, fix NUC roles; rest verifies (K8s 1.34, Flux 2.7, all-CP-and-worker, Thunderbolt Ceph backplane, whole component list) |
| `kubernetes/acceptance/async-agentic-v4.md` (184L) | Checklist is COMPLETED (accepted 2026-09-14, all six operator items ticked) and every required component is live and Ready — so it is a closed evidence record, not live guidance. Its fleet facts are now stale: 'two Ready FleetNodes / separate scout FleetNode' vs one, the 403-reviewer probe references a deleted alias, and the 3-alias hermes key scope is now 8. | Keep as evidence; extend the supersession note to the 2026-10-21 tier retirement |
| `kubernetes/apps/cilium/cilium/README.md` (22L) | 22-line hand-written stub that duplicates bgp.conf and shows only 3 of 7 live BGP neighbors (nuc-1/2/3 vs .10-.16). Copying it into UniFi would leave iggy/kristeva/amnesia/deleuze unpeered. The actual deployment (chart 1.19.2, kubeProxyReplacement, DSR/maglev, ${BGP_CIDR} pool, ${UNIFI_ROUTER_IP}) is entirely undocumented. | Rewrite or delete; point BGP at bgp.conf as the single source of truth |
| `kubernetes/apps/llm/hermes/app/agent-bundle/skills/cogito-litellm-key-scope-edit/SKILL.md` (32L) | DRIFTED (bundle strictly older): step 3 POSTs /key/update with the raw token — the workstation copy documents that this 404s and the handle must be used — and the bundle also lacks the 'assert the new scope list is non-empty before POSTing' guard, which is the one failure mode that blanks a live key scope. | Re-sync from the workstation copy, then regenerate the bundle |
| `kubernetes/apps/llm/hermes/app/agent-bundle/skills/cogito-llm-change-validation/references/llmkube-tooling.md` (73L) | Architecture and script paths verify, but it tells the agent to hand-make a bogus expr to test the gate when scripts/validate-grafana-dashboard.py has a built-in --self-test, and it lacks three workstation-learned pitfalls (per-app KS lives in llm ns, port-forward self-kill, stale-Ready litellm). | Re-sync from the workstation copy |
| `kubernetes/apps/llm/hermes/app/agent-bundle/skills/devops/gpu-llm-serving/SKILL.md` (95L) | Key safety fact verifies ('a time-sliced device plugin inflates nvidia.com/gpu by replicas' — amnesia reports 2 x RTX-5070-Ti-SHARED), but Prerequisites export KUBECONFIG=~/git/cogito-gitonly/kubeconfig (stale path; the repo is cogito) and ~15 workstation-verified pitfalls are missing. | Re-sync from workstation and fix the cogito-gitonly path |
| `kubernetes/apps/llm/hermes/app/agent-bundle/skills/devops/gpu-llm-serving/references/model-and-scheduling.md` (58L) | Generic checklist still sound, but missing the workstation's whole 'Bulk model staging Jobs' section (added after real failures) and the p2p-verification.md reference. | Re-sync from workstation |
| `kubernetes/apps/llm/hermes/app/agent-bundle/skills/devops/llm-provider-reasoning-config/SKILL.md` (111L) | Shipped architecture verifies (model-caps.yaml present), but 'Consuming: ~/.hermes/plugins/...' resolves to nothing in the pod (HERMES_HOME=/opt/data) and its 'Live verdicts' name flashnext-iggy, a retired alias — only flashnext-deleuze exists. | Re-sync from workstation, rewrite ~/.hermes paths as /opt/data or mark the section workstation-scoped, drop flashnext-iggy |
| `kubernetes/apps/llm/hermes/app/agent-bundle/skills/llm-engine-metrics-dashboard/SKILL.md` (74L) | Facts verify (llmkube-inference PodMonitor, grafanadashboard.yaml, build script), but the bundle lacks the workstation's refId-collision pitfall that makes a whole panel render 'No data'. | Re-sync from workstation |
| `kubernetes/apps/llm/hermes/app/agent-bundle/skills/research/software-release-research/SKILL.md` (48L) | No wrong cogito facts, but three workstation procedure revisions are missing (thematic summary, dual-boundary-tag option diff, anti-poisoning fallback). | Re-sync from workstation |
| `kubernetes/apps/llm/hermes/app/agent-bundle/skills/research/software-release-research/references/release-source-fallbacks.md` (44L) | Bundle still carries the old 'Compatibility checklist' where the workstation replaced it with ~55 lines of anti-scraper-poisoning guidance (git transport first). | Re-sync from workstation |
| `plans/llm/bench-notes.md` (252L) | Frozen 2026-09-25 scratch pad, not a live one: labels '**current** INT8/MTP qwen3-8-27b' (deploy is scaled to 0), 'G6 restored 2x131k' (live Muse is --ctx-size 131072 --parallel 1) and '250 W per card' (live 280 W). Its unique 2026-09-16 Qwen capacity study is the only record of that work. | Add frozen-ledger header + superseded-by pointers; keep the unique Qwen tables |
| `plans/llm/flashnext-amnesia-benchmark-2026-09-28.md` (59L) | Lane retired 2026-10-07, PV deleted 2026-10-23; no flashnext deploy on amnesia and only flashnext-deleuze.yaml remains. Hardware (5070 Ti, 16303 MiB) still matches, artifacts/2026-09-28-flashnext-amnesia/ complete. | Add 2-line retired header; keep as the 5070 Ti llama.cpp record |
| `plans/llm/flashnext-iggy-benchmark-2026-10-05.md` (88L) | Opens in present tense — 'Flash Next now serves through flashnext-iggy across Iggy's two R9700s' and calls radiance 'the production runtime ... one pod on iggy'. Live: iggy amd.com/gpu=0, ~31 GiB RAM, 2x3090; that config now runs on deleuze. BORDERLINE: per the dated-report convention it stays out-of-date-but-relevant; read literally it asserts a retired lane is live. | Add a prominent superseded-by header pointing at radiance-deleuze-2026-10-21.md; keep as the origin baseline |
| `plans/llm/flashnext-public-comparison-2026-10-05.md` (313L) | Runtime survey measured on iggy's R9700 pair (0000:2f:00.0), now on deleuze; its conclusions (Native Radiance wins, Q6 CPU-expert placements too slow) still inform the live deleuze lane. Also has the repo's only 2 broken markdown links -> ../../kubernetes/apps/llm/llmkube/resources/manual/flashnext-iggy-q6-*.yaml, both deleted. | Add node-move header; fix or delete the two dead preset links |
| `plans/llm/glimmer-benchmark-2026-09-14.md` (115L) | Same physical card (iggy GPU-787b) so the capacity frontier still means something, but 'production baseline remains 2x131k' is not what runs (now Abliterated Q4_K_M, 1x131k), its pinned digest 404s at GHCR, and 250 W is now 280 W. | Add header: card still valid, lane now abliterated/1x131k/new digest/280 W |
| `plans/llm/idle-hardware-options-2026-09-24.md` (166L) | Brainstorm whose inventory premises are gone: 'iggy 128 GB / ~111 GB free, both 3090s stay on the 27B lane' (live: ~28.6 GiB allocatable, 27B lane at 0 replicas) and 'workstation (not in cluster) ... 5070 Ti' (now the in-cluster amnesia node). Its two big recommendations were subsequently built; its kristeva-batch-only and NUC-not-worth-it conclusions still hold. | Add dated-inventory header; keep as methodology/derating reference |
| `plans/llm/qwen-p2p-benchmark-2026-09-23.md` (73L) | P2P result valid on the same two cards (GPU-787b/GPU-a598 still on iggy), but the qwen3-8-27b target is scaled to zero, driver/Talos premises moved (595.71.05/v1.13.5 -> 595.91.07/v1.14.4) and the 250 W cap it warns about was restored to 280 W. | Add dated header; keep as the record behind plans/talos/2026-09-iggy-gpu-p2p.md |
| `plans/talos/2026-08-talos-review.md` (280L) | 2026-08-28 audit: NUC/containerd-2.1.6 roll, Renovate talos/** blind spot and .taskfiles/talos/Taskfile.yaml deletion are still open, but its node table (iggy 1.13.5, kristeva 1.12.5) and 'four of five nodes untouched' are now wrong, and its 'upgrade-node refuses iggy' banner no longer matches talos/mod.just (only the shutdown guard remains). | Refresh node table + point Iggy at 2026-10-iggy-stock-nvidia.md; keep §2.1/§2.3/§5 as the open checklist |
| `services/gateway/README.md` (33L) | Live, reconciled-today gateway, but it still describes the Matrix image-description path deleted in e117d35 via the `image` alias retired in e54742a, plus 4 'planning scouts', two-profile review, and planner/coordinator role seats removed in 52d949f. | Refresh to post-52d949f/e117d35 reality (highest-priority gateway doc) |
| `vllm/README.md` (19L) | Core claim (nothing references these images) verifies, but it forward-references plans/llm/plan.md G7 (deleted in 9d5bb9e), omits the radiance image lane, and misses the build-laguna/push-laguna targets. | Fix the dangling plan reference; document laguna targets |

## 3. No longer relevant (archive) — 8 files

| file | verdict | action |
|---|---|---|
| `foreman_migration_pathway.md` (372L) | Self-labelled migration history; Foreman live (foreman-0.9.27), the Argo/coordinator platform it replaced is fully removed, and its pinned 'LLMKube core 0.9.18' is now 0.9.27. | Keep as history; cite v4 plan + services/gateway for the live model |
| `kubernetes/apps/llm/llmkube/modes/README.md` (103L) | Honest archive of modes retired 2026-09-12: modes/ is excluded from every Kustomization and `just kube llm-mode` really is read-only kubectl-get; but it speaks in present tense about the qwen-3-8-fp8 lane (now resources/disabled/) and repeats the 262144/131072 + reviewer claims, and its 'fixed GPU UUIDs' line contradicts qwen38-awq-iggy.yaml (device plugin, no UUID override). | Move under the archive convention or append a dated retirement note |
| `matrix_development_coordination.md` (588L) | Historical record of the finished coordinator/Argo project; Decision 5 says 'Argo Workflows owns run execution' — no Argo release or manifest exists; cites services/matrix-coordinator/RUNBOOK.md, a deleted path. | Keep as history behind its v4 banner; fix the dead citation to services/gateway/RUNBOOK.md |
| `plans/iggy_surgery.md` (396L) | Executed AMD cutover later reversed: body's 'Kubernetes advertises amd.com/gpu: 2' (iggy) and 'AMD device plugin scoped to Iggy' are now deleuze facts; its own banner defers to 2026-10-iggy-stock-nvidia.md. Its 2026-09-29 hostcall/RCCL diagnosis is the sole record of what fed the Deleuze bring-up. | Archive (do not delete — RCCL/hostcall findings); stock-nvidia doc wins on current claims |
| `plans/llm/async-agentic-homelab-v4.md` (583L) | Implemented and therefore history: §13 milestones map onto live deployments. Its §3.3 alias table is exactly the set ab8324d deleted, §9's 'three aliases' key is contradicted by the live 8-model key, and §1.2-1.3 ('5 nodes', 'iggy 128 GB', 'No 5070 Ti node', 'Muse suspended') is inverted by live state. | Add a superseded banner + archive; do not update the body |
| `plans/review/README.md` (62L) | PR-label plan queue (`workflow/plan-approved`/`implementation-queued`) was never wired: zero label automation, and .github/labels.yaml (synced with delete-other-labels:true) replaced it with the issue-based `workflow/approved` scheme implemented in services/gateway/coordinator. No plan ever used the queue. | Delete/archive; rewrite against the issue-based scheme only if a queue contract is still wanted |
| `plans/talos/2026-09-iggy-gpu-p2p.md` (220L) | Executed 2026-09-22/23 then reversed 2026-10-20: live iggy labels show stock nonfree-kmod-nvidia-production 595.91.07-v1.14.4, no P2P extension; talos/schematics/iggy.yaml.j2 itself says 'The historical patched P2P image is documented in plans/talos/2026-09-iggy-gpu-p2p.md'. | Archive as the P2P-era record; the surviving rules (restart-only, no powercycle) live in the stock-nvidia doc |
| `plans/workstation_talos.md` (413L) | Executed, not stalled: amnesia is a live control plane + gaming host (Talos v1.14.2, custom nvidia-open 615.78.08), which disproves its §2 pin of 'Talos 1.13.5 + official 595.71.05'; 'Gaming setup remains' is superseded by fenrir being Released. The doc itself cedes authority to the Dreamcast README. | Archive as the amnesia build record; annotate the §10 checklist so nobody re-runs it as a live plan |

## 4. Vestigial (delete / prune) — 7 files

| file | verdict | action |
|---|---|---|
| `GEMINI.md` (13L) | Standalone older copy of AGENTS.md's jj/vibe rules under a bogus '## SVN Settings' heading; omits the 1Password policy. Gemini CLI loads this stale subset instead of AGENTS.md. | Replace body with `@AGENTS.md` (CLAUDE.md pattern) |
| `bootstrap/GEMINI.md` (5L) | Self-declared 'leftover/cruft' notice for bootstrap/; the notice is itself the leftover. bootstrap/ survives only via `.justfile mod bootstrap`. | Delete; fold the caveat into a comment next to `mod bootstrap` |
| `kubernetes/acceptance/matrix-android-approval.md` (1L) | Whole file is one line: `android-approval-ok` — a one-shot test artifact committed to the repo. | Delete |
| `kubernetes/apps/llm/hermes/app/agent-bundle/skills/blank-window-dmabuf-fix/SKILL.md` (25L) | Byte-identical to the workstation copy and accurate for a Fedora/Wayland desktop, but inert in-cluster: the pod has no display server, no AppImage .desktop entries. It consumes the cluster agent's context for zero in-cluster use. | Prune from the cluster bundle (keep on workstation) |
| `kubernetes/apps/llm/hermes/app/agent-bundle/skills/chezmoi-dotfiles/SKILL.md` (33L) | Accurate workstation chezmoi flow (blakely-dotfiles exists) shipped to a pod with no chezmoi and no dotfiles repo. | Prune from the cluster bundle |
| `kubernetes/apps/llm/hermes/app/agent-bundle/skills/jj-managed-dotfiles-push/SKILL.md` (39L) | Targets ~/git/blakely-dotfiles from a pod with no jj and no credentials by design, and it is also stale — the workstation copy adds the empty-ancestor abandon fix and the '::main' per-file-history rule. | Prune, or re-sync and explicitly scope it as workstation-handoff guidance |
| `kubernetes/apps/llm/hermes/app/agent-bundle/skills/terminal-paste-debugging/SKILL.md` (36L) | Correct tmux debugging, identical to the workstation copy — and the pod has no tmux and no user terminal to debug. | Prune from the cluster bundle |

## 5. Current (keep) — 28 files

| file | verdict | action |
|---|---|---|
| `.claude/skills/jj-workflow/SKILL.md` (110L) | Mandated by AGENTS.md + CLAUDE.md; its flux-local workflow pin and title convention match live practice. | Keep |
| `AGENTS.md` (44L) | Authoritative agent-instructions doc; jj/vibe convention and the op-headless helper it mandates both exist. | Keep; single source of truth |
| `CLAUDE.md` (6L) | 6-line `@AGENTS.md` include-pointer; adds nothing that can drift. | Keep as-is |
| `kubernetes/apps/dreamcast/README.md` (690L) | 690 lines and it holds: every image digest (operator 7a73d323, proxy 9c8576cc, WOLF 4e5d97f7, steam 4f88a5e3, chart d097c154), the priority contract (gaming-interactive 20000 PreemptLowerPriority vs llmkube-low 1000), app ids 1/2, 3 pairings / 0 sessions, tim-steam 600Gi PV affinity, and the full amnesia Talos extension list verify. Only 'nuc-2 today'/'nuc-3 today' placement hedges are wrong (operator is on nuc-1, proxy on nuc-2). | Fix the two placement hedges; disambiguate the §6 NVIDIA_DRIVER_CAPABILITIES ban (user.yaml does set it for the wolf sidecar) |
| `kubernetes/apps/home-infra/knowledge/README.md` (64L) | Matches the live release (knowledge.v6, deployed 2026-10-08, /healthz 200, OAuth-gated /mcp), correctly admits the retired CPU embedding lane and that EMBEDDING_URL still points at the deleted knowledge-embeddings service; Pocket-ID/OIDC/WebDAV/firecrawl/cron claims all verify. | Keep; reword line 3 (Open WebUI RAG wiring does not exist), document knowledge-tika, keep the dangling EMBEDDING_URL as a tracked TODO |
| `kubernetes/apps/home-infra/matrix/README.md` (158L) | Verifies end to end: auth/exposure, CNPG matrix-db INST=3 + UTF8/C bootstrap + ScheduledBackup + kopiur, matrix-room-ids keys, the three-bot identity split (Gateway/Astra/Luna + @hermes), hookshot's single manageConnections entry, and even 'Alertmanager has no receiver' (receivers: [{name: null}]); pinned Sable file is byte-identical to the latest release. | No content changes; optionally note KS 'matrix-coordinator' renders HelmRelease 'gateway' |
| `kubernetes/apps/llm/camofox/README.md` (413L) | Structurally exact: MAX_SESSIONS 11 + seeder slot, VNC 2560x1440, three containers, cookies POST body, SecurityPolicy->camofox-vnc HTTPRoute, novnc bridge hash c0d19e44 (= sha256('tim')[:32]), hourly kopiur cron. | Keep; fix 'first SecurityPolicy in the cluster' (radiance-oidc now exists) and re-point the op instructions at op-headless |
| `kubernetes/apps/llm/hermes/app/agent-bundle/seeds/MEMORY.md` (5L) | 4-line cluster memory seed; amnesia Talos v1.14.2 + custom driver claims match live, and the pod's /opt/data/memories/MEMORY.md carries the same text (seeding works). | No change |
| `kubernetes/apps/llm/hermes/app/agent-bundle/seeds/SOUL.md` (1L) | NOT empty: 667 bytes on one line with no trailing newline, so wc -l reports 0 — a wc artifact. configure.py copies it whole-file to /opt/data/SOUL.md and the live pod matches. | Optional trailing newline to stop the confusion |
| `kubernetes/apps/llm/hermes/app/agent-bundle/seeds/USER.md` (1L) | NOT empty: 219 bytes, single line, no trailing newline; carries the gaming-protection preference and is seeded to /opt/data/memories/USER.md. | Optional trailing newline |
| `kubernetes/apps/llm/hermes/app/agent-bundle/skills/devops/kubernetes-cluster-health-audit/SKILL.md` (69L) | Identical to workstation; generic read-only methodology, and its gaming-protection rule matches live priority classes. | Keep |
| `kubernetes/apps/llm/hermes/app/agent-bundle/skills/devops/kubernetes-cluster-health-audit/references/cluster-health-checks.md` (73L) | Identical to workstation; CRD command forms and the GitRepository->KS->HelmRelease chain match the live flux layout. | Keep |
| `kubernetes/apps/llm/hermes/app/agent-bundle/skills/devops/oidc-integration-debugging/SKILL.md` (66L) | Identical to workstation; provider-agnostic boundary-isolation procedure, nothing to falsify. | Keep |
| `kubernetes/apps/llm/hermes/app/agent-bundle/skills/devops/talos-custom-extensions/SKILL.md` (71L) | Identical to workstation; 'v1.14 uses --reboot-mode' matches all control-plane nodes, and the amnesia cutover artifacts it references exist. | Keep (talosctl/podman stay workstation-side) |
| `kubernetes/apps/llm/hermes/app/agent-bundle/skills/internet-availability-address-lookup/SKILL.md` (25L) | Identical to workstation; machine-independent public-endpoint research, runnable from the pod. | Keep |
| `kubernetes/apps/llm/hermes/app/agent-bundle/skills/pocket-id-oidc-login-debug/SKILL.md` (109L) | Identical to workstation; pocket-id-db-2 Running, operator v0.5.0 and cluster-infra Reloader all match the doc. | Keep |
| `kubernetes/apps/llm/hermes/app/agent-bundle/skills/talos-custom-nvidia-driver/SKILL.md` (77L) | Identical to workstation; the amnesia 615.78.08-v1.14.2 facts it encodes are the live state and match the MEMORY seed and repo pins. | Keep |
| `kubernetes/apps/llm/hermes/app/agent-bundle/skills/xfinity-availability-check/SKILL.md` (101L) | Identical to workstation; browser-driven public flow, machine-independent. | Keep |
| `kubernetes/apps/observability/ntfy/README.md` (53L) | ntfy deployed (rev 3); live secret keys and NTFY_AUTH_ACCESS string implement exactly the documented anonymous-up*-write / tim-read / agent-write model. | Keep as-is |
| `kubernetes/apps/tools/firecrawl/NUQ-SOURCE.md` (18L) | Provenance exact: doc's image digest == the digest pinned in helmrelease.yaml; derived SQL + CNPG instance both deployed. | Keep; edit only when image and NuQ SQL bump together |
| `kubernetes/apps/tools/firecrawl/README.md` (55L) | Components, in-cluster URL, Dragonfly db 5, USE_DB_AUTHENTICATION=false, HTTPRoute all match manifests + live pods. | Keep; optionally replace <internal-domain> placeholder |
| `plans/fenrir-upstream-findings.md` (50L) | Live evidence log: fenrir HelmRelease pins and WOLF_IMAGE digest match the digests its PRs published; patches/, the two build workflows and steam.yaml all exist; only direwolf-operator + moonlight-proxy run, as described. | Keep as the living log; file or close its 5 open rows |
| `plans/hermes-incluster-ops.md` (100L) | Genuinely-open proposal, and still accurate: no hermes-runner-image workflow, no hermes-ops SA/RBAC, no /work PVC, no scripts/agent-prepush.sh, 'pending-deploy' greps only this file; its verified baseline (hermes-agent:v2026.9.24, 2Gi PVC, automountServiceAccountToken: false) matches live exactly. | Keep as actionable; date-stamp 'Verified current state' if implemented, archive if abandoned |
| `plans/llm/gemma-4-12b-amnesia-2026-10-07.md` (131L) | Live lane, right node/hardware, shipped config: pod on amnesia, server-cuda-b10991 pin matches, contextSize 65536 + supportsVision true in both manifests, retirement claims match the repo. | Optional: tick Runbook items 3-4 (Released-PV deletion finished 2026-10-23) |
| `plans/llm/radiance-deleuze-benchmark-2026-10-21.md` (106L) | Live lane, live runtime: deploy pins radiance:1.11.0@sha256:7595a642 on node deleuze 1/1; deleuze hardware matches its artifacts; its deferred '--api-key not passed' item is genuinely still open in radiance-deleuze.yaml. | Keep; track the admin-endpoint --api-key gap |
| `plans/talos/2026-10-deleuze.md` (103L) | Executed install record; every final-state claim verifies: Talos v1.14.4/6.18.57, schematic == node labels (amdgpu 20260916-v1.14.4), amd.com/gpu=2, BGP 'AS 64514/64513, 4 received / 2 advertised' matches `cilium bgp peers`. | Keep as the authoritative Deleuze reference |
| `plans/talos/2026-10-iggy-stock-nvidia.md` (107L) | Authoritative Iggy record: Talos v1.14.4, nonfree-kmod-nvidia 595.91.07-v1.14.4, ~31,990 MiB RAM, 2 allocatable GPUs sharing-strategy none, shutdown guard only. One stale sentence: 'the old flashnext-iggy ... remain available' — no such manifest exists anywhere in kubernetes/. | Fix the flashnext-iggy 'remain available' sentence (retained PVCs only) |
| `scripts/agent-notify.md` (50L) | Matches scripts/agent-notify.sh verbatim (outbox path, topic regex, --flush/STRICT); ntfy backend live with the documented agent write-only topic ACL. | Keep; optionally document optional NTFY_TOKEN |
## Cross-cutting findings

### A. The repo root has non-markdown droppings (all tracked)

| file | content | action |
|---|---|---|
| `health.txt` | `ok` | delete |
| `opencode-health.txt` | `ok` | delete |
| `matrix-e2e.txt` | `matrix-ok-v2` | delete |
| `failure-review-repair-smoke.txt` | `repair-ok` | delete |
| `wlog.txt` | 7 lines of `DEP 128 1` rollout log | delete |
| `tmp_move.sh` | one-shot `mv` script for a completed flux tree move | delete |
| `format_releases.py` | reads `/home/tim/git/cogito/content.json`, which does not exist | delete |

`.pytest_cache/` exists on disk, is untracked, and is absent from `.gitignore` — add the ignore rule.

### B. The Hermes agent bundle is the highest-risk doc surface

The bundle is instructions the in-cluster agent follows, so drift there is operational, not
cosmetic. `gen-bundle.py --check` passes (exit 0) — it only proves `bundle.yaml` matches the
bundle *source*, so CI is blind to every one of these:

- **Wrong fact an agent will act on:** `cogito-llm-change-validation` states `kristeva ... RTX 3090 =
  02:00.0`; `kubectl get node kristeva` reports `nvidia.com/gpu=0` (the card moved to iggy).
- **Retired alias:** `llm-provider-reasoning-config` lists `flashnext-iggy` in its live verdicts;
  only `flashnext-deleuze` exists.
- **Paths that resolve to nothing in the pod:** `~/.hermes/...` (HERMES_HOME is `/opt/data`),
  `~/git/cogito-gitonly/kubeconfig`, and `mise`/`kubectl`/`jj`/`tmux`/`chezmoi`, none of which are
  in the image.
- **A step that fails as written:** `cogito-litellm-key-scope-edit` POSTs `/key/update` with the raw
  token (404s; the handle is required) and omits the non-empty-scope assertion that prevents blanking
  a live key's model list.
- **Drifted behind the workstation copy (re-sync):** `cogito-litellm-key-scope-edit`,
  `cogito-llm-change-validation` (+ `references/llmkube-tooling.md`, and 2 workstation references
  never bundled), `devops/gpu-llm-serving` (+ `model-and-scheduling.md`, `p2p-verification.md`
  missing), `devops/llm-provider-reasoning-config`, `llm-engine-metrics-dashboard`,
  `jj-managed-dotfiles-push`, `research/software-release-research` (+ `release-source-fallbacks.md`).
- **Identical, no action:** `kubernetes-cluster-health-audit` (+ref), `oidc-integration-debugging`,
  `talos-custom-extensions`, `talos-custom-nvidia-driver`, `pocket-id-oidc-login-debug`,
  `internet-availability-address-lookup`, `xfinity-availability-check`, and the three seeds.
- **Inert in-cluster (accurate workstation skills with no pod capability to run them):**
  `blank-window-dmabuf-fix`, `chezmoi-dotfiles`, `jj-managed-dotfiles-push`,
  `terminal-paste-debugging`.
- `seeds/SOUL.md` and `seeds/USER.md` are *not* empty — 667 and 219 bytes on one line with no
  trailing newline, so `wc -l` reports 0. Seeding is a whole-file byte copy; harmless. Add trailing
  newlines only to stop the confusion.

### C. Supersession chains — pick one winner per subject

- **Iggy (4 docs, one winner):** `plans/talos/2026-08-talos-review.md` →
  `plans/talos/2026-09-iggy-gpu-p2p.md` (P2P image, reversed) → `plans/iggy_surgery.md` (AMD cutover,
  reversed) → **`plans/talos/2026-10-iggy-stock-nvidia.md` wins**. The repo already agrees:
  `talos/schematics/iggy.yaml.j2` names the P2P doc as history.
- **FlashNext/Radiance (4 reports, one winner):** `flashnext-amnesia-2026-09-28` →
  `flashnext-iggy-2026-10-05` → `flashnext-public-comparison-2026-10-05` →
  **`radiance-deleuze-2026-10-21` wins** (and is current).
- **Plan-queue contract:** `plans/review/README.md` (PR-label queue, never wired) is superseded by
  the issue-based `workflow/approved` scheme in `.github/labels.yaml` +
  `services/gateway/coordinator/`.
- **Cilium BGP:** `kubernetes/apps/cilium/cilium/bgp.conf` (7 neighbours) is the source of truth;
  the README duplicates 3 of them.
- **Gaming stack:** `kubernetes/apps/dreamcast/README.md` wins on pins (workstation_talos.md cedes
  authority to it in its own text); `plans/fenrir-upstream-findings.md` is the live why-log.
- **v4 coordination:** `services/gateway/{README,RUNBOOK}.md` are the live docs;
  `matrix_development_coordination.md` and `foreman_migration_pathway.md` are their history.

### D. Broken links (2, both in one file)

`plans/llm/flashnext-public-comparison-2026-10-05.md` links
`../../kubernetes/apps/llm/llmkube/resources/manual/flashnext-iggy-q6-cache-c1.yaml` and
`.../flashnext-iggy-q6-stew-c2.yaml` — both presets were deleted with the iggy lane.

### E. Live-state problems the audit surfaced (not doc defects)

- `kubernetes/apps/home-infra/knowledge`: `EMBEDDING_URL=http://knowledge-embeddings:8000/v1` points
  at a service that no longer exists (the README already admits the retirement).
- `services/gateway/coordinator/luna.py:89` and `service.py:46` still default to model
  `coordinator`/`planner` — aliases deleted in the catalogue. `virtualkeys/pi.yaml` comments still
  mention `planner-gpt-pro`.
- `radiance-deleuze.yaml` passes no `--api-key` on the admin endpoint (tracked in the benchmark doc
  as deferred).
- `talos/schematics/amnesia.yaml.j2` does not match amnesia's running custom 615.78.08-v1.14.2
  extensions — the same committed-schematic-vs-running-machine gap the 2026-08 review called its
  highest-risk item.
- A stale not-ready `gemma-4-12b` ReplicaSet pod (`77d9574d47`) sits on amnesia beside the Ready one.

### F. Suggested execution order

1. Delete the 7 root droppings + `kubernetes/acceptance/matrix-android-approval.md`; gitignore `.pytest_cache/`.
2. Fix the 4 `outright-incorrect` docs (gateway RUNBOOK, LiteLLM models README, hermes README,
   bundled `cogito-llm-change-validation` — fix the kristeva-3090 line in **both** the bundle and the
   workstation copy so the re-sync doesn't reintroduce it).
3. Re-sync the 7 drifted bundle skills, prune the 4 inert ones, regenerate + `--check`.
4. Add superseded-by headers to the 9 dated records in bucket 2 that need only a header.
5. Create `plans/archive/`, move the 8 `no-longer-relevant` docs, leave a pointer line behind.
6. Fix `README.md` (amnesia row, Talos badge, NUC roles).


## Executed 2026-10-23

Six changes, one per step, all local (`jj`, not pushed):

| Step | Change | What landed |
| --- | --- | --- |
| 1 | `0f49ddb8` | Deleted `health.txt`, `opencode-health.txt`, `matrix-e2e.txt`, `failure-review-repair-smoke.txt`, `wlog.txt`, `tmp_move.sh`, `format_releases.py`, `kubernetes/acceptance/matrix-android-approval.md`; `.pytest_cache/` ignored. |
| 2 | `4cd09dc7` | Rewrote `services/gateway/RUNBOOK.md`; corrected the LiteLLM models README, the hermes README, and the kristeva GPU facts in **both** the bundled and workstation `cogito-llm-change-validation`. |
| 3 | `144a5000` | Re-synced the 6 drifted bundle skills from `~/.hermes/skills`, pruned the 4 the pod cannot execute, documented the mirror policy in `kubernetes/apps/llm/hermes/README.md`, regenerated `bundle.yaml`. |
| 4 | `6930d515` | Superseded/frozen-record banners on 7 benchmark docs + 9 targeted factual corrections (dead links, deleted lanes, retired SecurityPolicy-first claim, embedding dependency, `knowledge-tika`, dreamcast placements, op-headless path, cilium BGP). |
| 5 | `dd5b31d6` | `plans/archive/` created with its own rule-set; 6 finished docs moved in with dated banners; `plans/review/` deleted; `llmkube/modes/README.md` corrected in place. |
| 6 | `1d6d4eca` | Root README (badge, amnesia row, NUC OSD roles, custom-driver explanation); `GEMINI.md` → `@AGENTS.md`; `bootstrap/GEMINI.md` deleted with its caveat folded into `.justfile`. |

Deviations from the plan above, both deliberate:

- **6 archived, not 8.** `kubernetes/apps/llm/llmkube/modes/README.md` is an
  archive of serving modes that belongs next to `modes/`, so it got a dated
  correction instead of a move. `plans/review/` held exactly one file — a
  convention nobody wired up or used — so it was deleted rather than archived;
  archiving it would have preserved the fiction that a queue contract exists.
- **7 re-synced, not 7.** One of the eight originally-flagged bundle skills
  (`cogito-llm-benchmark-recall`) is not in the bundle at all, so the drift count
  was 6.

Verified, not assumed: every relative link in all 67 tracked markdown files
resolves (0 broken); `gen-bundle.py --check` exits 0; `just -l` still parses after
the `.justfile` comment; the two `kubectl` facts used in banners (amnesia PV gone,
BGP `established` with non-zero counts) were read off the live cluster.

Still open, deliberately untouched (cluster changes, not doc changes):

- Everything in §E above — the dangling `EMBEDDING_URL`, the gateway's
  `coordinator`/`planner` model defaults, the unauthenticated Radiance admin
  endpoint, `talos/schematics/amnesia.yaml.j2` vs the running custom extensions,
  and the stale not-ready `gemma-4-12b` ReplicaSet pod.
- Three retired-lane service directories survive: `services/flashnext-iggy-llama/`,
  `services/foreman-planning-scout/`, `services/iggy-radiance-rccl/`. They hold
  build scripts and an entrypoint for lanes that no longer exist; deleting them is
  a code decision, not a doc one.
- Several workstation skills that would be *useful* in the cluster bundle
  (`cogito-llm-benchmark-recall`, `cogito-backup-audit`,
  `hybrid-gpu-state-verification`, `qwen38-megakernel-3090`,
  `muse-glimmer-abliterated-3090`) are not in `bundle.yaml`; adding them is a
  scope decision for the next bundle sync.
