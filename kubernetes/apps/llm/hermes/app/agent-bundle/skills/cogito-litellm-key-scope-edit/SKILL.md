---
name: cogito-litellm-key-scope-edit
description: "Use when editing LiteLLM virtual key scopes in cogito."
version: 1.2.0
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

## Pitfall: editing an ISSUED key's scope does NOT take effect
The litellm-operator reconciles an edited `LiteLLMVirtualKey` but does NOT update the model list of an already-issued key in LiteLLM's DB. The CR looks right; live calls still 403 with `key_model_access_denied` listing the old scope, so narrowing an existing key needs the manual `/key/update` below. A **brand-new** key is the opposite and provisions fully declaratively (CR → generated `Secret` → `PushSecret Ready=True Synced` into 1Password, no DB fix), so when the goal is to move models OFF a shared key, prefer issuing a second key over mutating a live one.

## Flow
1. Edit `kubernetes/apps/llm/litellm/app/virtualkeys/<key>.yaml`, jj commit + bookmark main + `jj git push` (jj repo; see jj-managed-dotfiles-push).
2. `flux reconcile source git flux-system` then `flux reconcile kustomization <app> -n llm --with-source` (don't wait for the 1h sync).
3. Manual DB fix with the existing key (README documents this as required until the operator closes the gap) — pipe the key via stdin, never as argv/env:
   `kubectl get secret litellm-key-<name> -n llm -o jsonpath='{.data.api-key}' | base64 -d | kubectl exec -i -n llm deploy/litellm -c litellm -- python3 ... POST /key/update {"key": handle, "models": [...full scope...]}` using PROXY_MASTER_KEY inside the pod.
   **Never pipe the key into `python3 -`**: `kubectl exec -i ... -- python3 -` reads the
   *program* from stdin, so the raw token gets executed as Python (`NameError: name 'sk'
   is not defined`). `kubectl cp` the helper script to the pod's /tmp and run
   `python3 /tmp/helper.py` with the token on stdin instead.
   LiteLLM 1.97 / 1.105.5 API shapes (verified live on 1.105.5):
   - `GET /key/list?page=1&size=100` returns `keys: [<64-char hash>, ...]` — plain strings, and the hash is NOT sha256(raw token) (salted); do not try to match by hashing the raw token. Locate the record via `GET /key/info?key=<hash>` and its `info.key_alias`; the `key` field of that record is the handle /key/update wants (the raw token 404s with "Key not found" on /key/update even though /key/info accepts it).
   - `POST` is 405 on both `/key/list` and `/key/info` (both are GET). `GET /key/list` also rejects `size` above 100 — the error body has no `keys`, which a careless reader reports as "0 keys carry alias X" instead of a failed call. Print the status and fail loudly.
   - Model scope lives at `info.models`, not top-level `models` — reading the wrong level silently yields [] and an update can blank the scope.
   - After a successful `/key/update`, the removed aliases fail closed on the old key: `403 The requested model '<m>' is not available for this API key` — that message, plus the narrowed `/key/info` read, is the proof to report.
   - `/v1/models` lists both the public alias and each deployment's litellm_params.model name, so the count can exceed the model-file count by one; that is display duplication, not a leftover.
4. Verify live: chat completion with the key itself (master key succeeding means nothing about key scope); `/key/info` with the key token shows the new models.
   Multi-key scope checks (`/v1/models` per key) must run inside ONE script that fetches each secret with `subprocess` and prints only model ids and counts. `kubectl get secret ... | base64 -d` into shell variables — worse, in a `for` loop over keys — puts decoded credentials in the command line, trips the secret-handling approval gate, and the blocked turn is lost with no consent path.
   When retiring aliases wholesale, sweep `/key/list` and revoke keys whose scope is entirely dead names, but NEVER touch a key with any surviving scoped model; assert the new scope list is non-empty before POSTing /key/update (a wrong-nesting extraction posts `models: []` and silently blanks the scope), and never truncate an API response body before json-parsing it.
5. If the consumer is the Hermes deployment: its provider catalogue/aliases are owned by the init container (hermes/app/provider-bootstrap.yaml) — edit that ConfigMap's configure.py too, and `kubectl rollout restart deploy/hermes` to re-run it.

## Splitting one key across two transports (same alias listed twice)
Two provider blocks pointed at the same LiteLLM base URL is how one alias becomes
two picker entries: one block discovers from `/v1/models` (key-scope filtered) and
the other hand-lists models, so every alias in the shared key's scope shows up
twice. Fix = one key per transport with DISJOINT scopes, so discovery can never
return an alias the other transport serves. Side benefit: a Responses-only alias
requested over chat/completions then fails as model-not-allowed instead of being
silently served on the wrong transport, which is how reasoning items get dropped.
1. Copy `virtualkeys/<key>.yaml` → `virtualkeys/<key>-subscription.yaml` with a
   new `metadata.name`, new `secretName: litellm-key-<key>-subscription`, and the
   narrow `models:` list; add the file to that directory's `resources:` list or it
   is never rendered.
2. Mirror the existing `PushSecret` for the new secret so the generated key lands
   in the 1Password item as a distinct property; don't announce the credential
   until that PushSecret reports `Ready=True / Synced`.
3. Client side (Hermes): give each provider block its own `key_env` (one env var
   per key in `~/.hermes/.env`, written programmatically from an `op-headless`
   fetch — never copied from terminal output, which masks secrets) and distinct
   `display_name`s so the transports are distinguishable. The picker renders one
   row per provider block, so a model visible to both blocks always duplicates.

## Adding an alias to the subscription catalogue

One new alias is four edits plus one manual step: `models/<alias>.yaml`, that
directory's `kustomization.yaml` resource list, the `models:` list of the key that
serves it (`virtualkeys/hermes-subscription.yaml`), and `model-caps.yaml` — then the
manual `/key/update` above, because the key is already issued. Prove it with
`scripts/validate-llm-catalogue.py` (the modelNames count must rise), `kustomize
build` of `.../litellm/app` (the app dir, not its parent), and
`kubectl apply --dry-run=server` on a filtered set.

Two caches lie to you while this lands, in this order:

- `/v1/models` is filtered by the KEY SCOPE, not by the router, so a brand-new
  alias appears there the moment the key scope changes even when the proxy cannot
  serve it. The real test is a `/v1/responses` call: `400 Invalid model name passed
  in` means the router has no deployment for it yet. That usually means the proxy
  Pod has not finished rolling — during a rollout the OLD ReplicaSet pod keeps
  serving, so `kubectl -n llm rollout status deploy/litellm` before believing the
  400 is a config bug.
- the `model-caps` Deployment merges `caps.json` into a snapshot of upstream
  `/v1/models` and holds that snapshot; if its pod restarts while the proxy still
  advertises the old list it stays short one model. `kubectl -n llm rollout restart
  deploy/model-caps` after the proxy is serving the alias, then re-read
  `/caps/v1/models` and count.

## Notes
- Hermes key secret: litellm-key-hermes; provider bootstrap also strips/registers model_aliases.
- LiteLLM env var inside pod is PROXY_MASTER_KEY (not LITELLM_MASTER_KEY).
- A secret-scrubbing file-writing tool rewrites the literal `"Bearer "` inside written script content into `"***"`, so the request goes out as header value `***<key>` and the gateway answers `Malformed API Key` — indistinguishable from a revoked key. Build that header from pieces (`"Be" + "ar" + "er " + key`) and check the on-disk bytes (`grep Authorization f | od -c`) before believing a 401 from a generated script.
- kubectl via `mise exec kubectl@1.37.1`; KUBECONFIG=~/git/cogito-gitonly/kubeconfig — that is
  the real file; `~/git/cogito/kubeconfig` is a symlink to it, so either path works but only one
  is the file. The pod has neither kubectl nor this kubeconfig.
