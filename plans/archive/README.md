# Archive

Plans and investigation records that were **carried out, reversed, or replaced**.
Nothing in here has live authority: if a document in this directory contradicts
the cluster or a doc elsewhere in the repo, the other thing is right.

Two rules, so the directory stays useful instead of turning into a second source
of truth:

1. **Archive, don't delete.** These files hold the evidence a decision was made
   on — measurements, failed approaches, the reasoning behind a pin. Deleting
   them leaves a gap that gets re-investigated at GPU-node cost.
2. **Every file carries a dated banner** at the top naming what superseded it and
   which document to read instead. Add that banner when you move a file in; the
   move without the banner is what makes a stale doc dangerous.

A doc belongs here when its *subject* is finished, not merely when it is out of
date. A runbook with a wrong version number gets fixed in place; a build plan
that has been fully executed comes here.

| File | Subject | Read instead |
| --- | --- | --- |
| `async-agentic-homelab-v4.md` | The v4 design for gateway + Foreman + LiteLLM tiers (implemented) | `services/gateway/RUNBOOK.md`, `kubernetes/acceptance/async-agentic-v4.md` |
| `matrix_development_coordination.md` | Design narrative of the pre-Foreman coordinator/Argo project | `services/gateway/RUNBOOK.md` |
| `foreman_migration_pathway.md` | The Argo → Foreman migration itself | `kubernetes/apps/llm/foreman/`, `services/gateway/RUNBOOK.md` |
| `iggy_surgery.md` | Iggy's 2026-09 AMD R9700 cutover (later reversed) | `plans/talos/2026-10-iggy-stock-nvidia.md` |
| `2026-09-iggy-gpu-p2p.md` | The patched-P2P-driver era on Iggy | `plans/talos/2026-10-iggy-stock-nvidia.md`, `plans/llm/qwen-p2p-benchmark-2026-09-23.md` |
| `workstation_talos.md` | Building the workstation into the `amnesia` node | `kubernetes/apps/dreamcast/README.md`, `talos/schematics/amnesia.yaml.j2` |
