# Document Matrix client enrollment

## Objective

Document the one-time Matrix membership steps that a human performs after the
room GitOps controller creates a private Space and its child rooms. The result
should explain why an invitation does not immediately appear as a joined room
in Commet and what remains automated afterward.

## Context

Cogito now declares private `Agents` and `Personal` Spaces and their rooms with
the Matrix Terraform provider. The controller creates the hierarchy and sends
invitations to `@tim:matrix.timblakely.com`. Matrix requires the invited account
to accept its own membership. Joining a Space also does not automatically join
each private child room.

This behavior was confusing during the first Commet enrollment and should be
recorded beside the existing room GitOps documentation.

## Proposed change

Update `kubernetes/apps/home-infra/matrix/README.md` with a concise client
enrollment section that explains:

- the controller declaratively creates Spaces, rooms, aliases, hierarchy, and
  invitations;
- the human accepts the Space invitation and each private child-room invitation
  once in the Matrix client;
- accepted `join` membership persists while later names, topics, aliases, and
  hierarchy changes continue to reconcile through GitOps;
- a client refresh or restart may be needed if Commet does not immediately
  redraw the Space hierarchy;
- the canonical aliases can be used to confirm that the intended rooms were
  joined;
- the new section follows the existing README's heading, paragraph, list, and
  line-wrapping conventions.

Keep the wording client-neutral where the behavior comes from Matrix, while
using Commet as the concrete example already used in the Android instructions.

## Non-goals

- Do not change Synapse, room, membership, or power-level configuration.
- Do not add forced joins or server-administrator automation.
- Do not change Android push configuration.
- Do not change the Cogito name or rename any existing Matrix Space or room.
- Do not modify files other than the Matrix README.

## Acceptance evidence

- The rendered Markdown clearly distinguishes `invite` from `join`.
- It states that Space membership does not imply membership in private child
  rooms.
- It describes which configuration remains automatic after the one-time joins.
- `git diff --check` passes.
- `scripts/validate-llm-catalogue.py` still passes as the delivery workflow's
  repository-level trusted check.
