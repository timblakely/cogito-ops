# Async Agentic Homelab v4 — Acceptance Evidence

**Purpose.** This document records acceptance evidence for the v4 async agentic
homelab flow, in the order **Astra → GitHub → Luna → Foreman**. It is an
evidence record only: it does **not** change runtime behavior, and it does not
assert that acceptance has passed. Every checkbox below is intentionally left
unchecked; the operator fills in the run record and evidence references after a
real run.

**Scope anchor.** Each checklist item is grounded in
`plans/llm/async-agentic-homelab-v4.md` (the v4 plan). No transport, approval,
or success semantics are invented here beyond what that plan documents.

## Operator checklist

- [ ] **Entry action.** A top-level owner request in a Matrix project room
      starts a session (routing by state, no prefix); Astra begins planning.
      (v4 §2, §5.3)
- [ ] **Astra → GitHub.** Astra drafts the plan as a GitHub issue (body = plan,
      `workflow/plan` label); the owner reviews via edits/comments; approval is
      the `workflow/approved` label (or a `/approve` comment the gateway turns
      into the label). (v4 §7.1–7.3)
- [ ] **GitHub → Luna.** The repository webhook delivers GitHub events to the
      gateway; Luna triages them and, on approval, opens the implementation
      thread. (v4 §6.5, §8.1)
- [ ] **Luna → Foreman.** Luna creates one Workload per deliverable; Foreman
      runs coder → gate → reviewers → PR; the gate passes; the PR is merged in
      order and the plan issue closes on the last merge. (v4 §8.1, R9)

## Run record

- Run identifier: `____________________`
- Timestamp (UTC): `____________________`

## Sanitized evidence references

- **Astra → GitHub:** plan issue `#____`; approval label event `____`
- **GitHub → Luna:** webhook delivery id `____`; Luna turn `____`
- **Luna → Foreman:** Workload name `____`; gate result `____`; PR `#____`

## Implementation handoff — gate

- **Gate selected:** `flux-local` — the `.github/workflows/flux-local.yaml`
  workflow (summary check `flux-local-status`).
- **Selection rationale:** the only file changed by this deliverable lives under
  `kubernetes/`; per v4 R9 the gate runs flux-local for `kubernetes/` changes.
- **Required to pass:** the `flux-local` gate **and** `git diff --check`.
