# GLM-5.3-Flash retirement

Retired from Deleuze on 2026-11-28 at the operator's request. The Radiance
fleet entry, GLM-specific serving allocation and kernel override, staging Jobs,
LiteLLM route and key allowlists, OpenCode/Paseo catalogue entries, and managed
Hermes shortcut are removed. Existing non-GLM models and client defaults remain.

## Cold-storage artifact

- NAS: `nuglab-storage.internal:/volume1/nuglab/Models`
- File: `llmkube/glm-5.3-flash-deleuze/glm53-flash-iqr-v4.rad`
- Verification record: `llmkube/glm-5.3-flash-deleuze/retirement-20261128-verified.json`
- Size: `170662334464` bytes.
- SHA-256: `1e20c4bc2f7ea7022f7bae9dd1ffa9873c2031b242d41e85d1ac0a5016342687`.
- Original source: `/models/radiance/glm53-flash-iqr-v4.rad` on
  `llm/radiance-deleuze`. Deleted only after the full NAS copy passed size and
  SHA-256 verification at `2026-11-28T07:29:34Z`.

The archive uses the existing `llm/llm-model-archive` NFS claim. It is cold
storage, not a serving source or an automatic restore/download instruction.
Reintroducing this model requires a new, explicitly validated serving decision.

## Retained local cache

The original PVC remains bound to
`pvc-64dd51b2-5880-48fb-a1b6-1e4b64c08edd` on Deleuze with
`openebs-hostpath-retain`, the same local path and `Retain` policy. PV capacity,
PVC request and PVC status now agree on `800Gi`. This is local-hostpath capacity
metadata, not a disk migration or new filesystem allocation. Backup policies
are unchanged.

The Flux MCP has `patch` permission on that PV name only; no PV deletion or
general PV write permission was added. RBAC does not restrict patch fields, so
the authorized storage operation remains capacity-only.
