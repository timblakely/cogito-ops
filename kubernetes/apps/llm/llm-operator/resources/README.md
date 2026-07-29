# Reviewed LLM resources

This directory is reserved for Cogito-specific `LLMBackend`, `LLMModel`,
`LLMModelOverlay`, and (when appropriate) `LLMActiveModel` resources.

It is intentionally not reconciled by Flux yet. Before activating it:

1. Publish and reconcile the operator chart with `transitions.enabled: false`.
2. Inventory the live backend Deployments, Services, container names, ports, and
   model revisions.
3. Add only resources reviewed against that inventory. Do not translate the
   historical sample manifests or model ConfigMaps blindly.
4. Add `RESOURCES=resources` to the parent `APP-app-vars` generator and replace
   the `../../../components/ks/app` component with
   `../../../components/ks/app-resources`. This creates a separate Flux
   Kustomization that depends on the operator installation and its CRDs.
5. Render and review both Kustomizations before committing the activation.

Observation mode permits status reconciliation but must not mutate backend
Deployments. An `LLMActiveModel` should report transitions disabled until the
separate transition-safety gate is approved.
