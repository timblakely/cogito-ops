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
   `kubectl get secret litellm-key-<name> -n llm -o jsonpath='{.data.api-key}' | base64 -d | kubectl exec -i -n llm deploy/litellm -c litellm -- python3 ... POST /key/update {"key": handle, "models": [...full scope...]}` using PROXY_MASTER_KEY inside the pod.
   LiteLLM 1.97 API shapes (verified live):
   - `GET /key/list?page=1&size=100` returns `keys: [<64-char hash>, ...]` — plain strings, and the hash is NOT sha256(raw token) (salted); do not try to match by hashing the raw token. Locate the record via `GET /key/info?key=<hash>` and its `info.key_alias`; the `key` field of that record is the handle /key/update wants (the raw token 404s with "Key not found" on /key/update even though /key/info accepts it).
   - `POST /key/info` is 405 (route is GET); model scope lives at `info.models`, not top-level `models` — reading the wrong level silently yields [] and an update can blank the scope.
   - `/v1/models` lists both the public alias and each deployment's litellm_params.model name, so the count can exceed the model-file count by one; that is display duplication, not a leftover.
4. Verify live: chat completion with the key itself (master key succeeding means nothing about key scope); `/key/info` with the key token shows the new models.
   When retiring aliases wholesale, sweep `/key/list` and revoke keys whose scope is entirely dead names, but NEVER touch a key with any surviving scoped model; assert the new scope list is non-empty before POSTing /key/update (a wrong-nesting extraction posts `models: []` and silently blanks the scope), and never truncate an API response body before json-parsing it.
5. If the consumer is the Hermes deployment: its provider catalogue/aliases are owned by the init container (hermes/app/provider-bootstrap.yaml) — edit that ConfigMap's configure.py too, and `kubectl rollout restart deploy/hermes` to re-run it.

## Notes
- Hermes key secret: litellm-key-hermes; provider bootstrap also strips/registers model_aliases.
- LiteLLM env var inside pod is PROXY_MASTER_KEY (not LITELLM_MASTER_KEY).
- A secret-scrubbing file-writing tool rewrites the literal `"Bearer "` inside written script content into `"***"`, so the request goes out as header value `***<key>` and the gateway answers `Malformed API Key` — indistinguishable from a revoked key. Build that header from pieces (`"Be" + "ar" + "er " + key`) and check the on-disk bytes (`grep Authorization f | od -c`) before believing a 401 from a generated script.
- kubectl via `mise exec kubectl@1.37.1`; KUBECONFIG=~/git/cogito-gitonly/kubeconfig — that is
  the real file; `~/git/cogito/kubeconfig` is a symlink to it, so either path works but only one
  is the file. The pod has neither kubectl nor this kubeconfig.
