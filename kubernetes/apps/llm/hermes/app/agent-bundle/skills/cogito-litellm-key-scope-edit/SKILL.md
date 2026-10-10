---
name: cogito-litellm-key-scope-edit
description: "Use when editing LiteLLM virtual key scopes in cogito."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [litellm, kubernetes, flux, cogito]
    related_skills: [jj-managed-dotfiles-push]
---

# Editing a LiteLLMVirtualKey model scope (cogito-ops)

## When to Use
Any change to a `LiteLLMVirtualKey` model list / key scope in the cogito-ops repo, or when a key 403s with `key_model_access_denied` despite the CR looking correct.

## Pitfall: CR edit alone does NOT take effect
The litellm-operator reconciles an edited `LiteLLMVirtualKey` but does NOT update the model list of an already-issued key in LiteLLM's DB. The CR looks right; live calls still 403 with `key_model_access_denied` listing the old scope.

## Flow
1. Edit `kubernetes/apps/llm/litellm/app/virtualkeys/<key>.yaml`, jj commit + bookmark main + `jj git push` (jj repo; see jj-managed-dotfiles-push).
2. `flux reconcile source git flux-system` then `flux reconcile kustomization <app> -n llm --with-source` (don't wait for the 1h sync).
3. Manual DB fix with the existing key (README documents this as required until the operator closes the gap) — pipe the key via stdin, never as argv/env:
   `kubectl get secret litellm-key-<name> -n llm -o jsonpath='{.data.api-key}' | base64 -d | kubectl exec -i -n llm deploy/litellm -- python3 ... POST /key/update {"key": token, "models": [...full scope...]}` using PROXY_MASTER_KEY inside the pod.
4. Verify live: chat completion with the key itself (master key succeeding means nothing about key scope); `/key/info` with the key token shows the new models.
5. If the consumer is the Hermes deployment: its provider catalogue/aliases are owned by the init container (hermes/app/provider-bootstrap.yaml) — edit that ConfigMap's configure.py too, and `kubectl rollout restart deploy/hermes` to re-run it.

## Notes
- Hermes key secret: litellm-key-hermes; provider bootstrap also strips/registers model_aliases.
- LiteLLM env var inside pod is PROXY_MASTER_KEY (not LITELLM_MASTER_KEY).
- kubectl via `mise exec kubectl@1.37.1`; KUBECONFIG=~/git/cogito-gitonly/kubeconfig.
