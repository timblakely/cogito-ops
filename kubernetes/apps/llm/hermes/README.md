# Hermes

The Hermes gateway and dashboard run in one supervised container and share the
VolSync/Kopia-backed `hermes` PVC mounted at `/opt/data`.  The dashboard is
available at `https://hermes.${DOMAIN_NAME}` through the internal Envoy gateway.

## Agent bundle (skills, plugins, personality)

`agent-bundle/` holds the GitOps bootstrap of the cluster agent, mirrored
from the workstation profile at the time of writing: custom skills
(`skills/`), the litellm-caps model-provider plugin
(`plugins/model-providers/`), and seeds (`seeds/`).  `gen-bundle.py` packs it
into `bundle.yaml` (ConfigMap binaryData tarball — regenerate with
`../.venv/bin/python gen-bundle.py` after any change; the pod-template
`bundle-sha256` annotation rolls the pod).

**Seeding is one-way and one-time.** The `configure-provider` init container
copies each leaf skill/plugin dir, `SOUL.md`, and the memory files into
`/opt/data` only when absent; after that the agent on the PVC owns its whole
identity — skill edits and agent-created skills survive every deploy, are
never clobbered by a bundle change, and ride the PVC's Kopia snapshots.  To
re-seed deliberately, delete the path on the PVC (`kubectl -n llm exec
deploy/hermes -- rm -rf /opt/data/skills/<name>`) and restart the pod.  The
same script reconciles the provider/model/behavior keys of `config.yaml`
(those stay GitOps-owned; see `configure.py`, embedded via the
`hermes-provider-bootstrap` ConfigMap — `gen-bundle.py` re-embeds it).

**Mirror policy.** `agent-bundle/skills/` is a straight copy of the workstation
profile: edit `/home/tim/.hermes/skills/<name>/SKILL.md` and re-copy it
(`rsync -a --delete ~/.hermes/skills/<name>/ agent-bundle/skills/<name>/`), never
edit the bundle copy — a hand-edit there is silently reverted by the next
re-sync. Two consequences worth knowing before trusting a bundled skill: it keeps
workstation-only paths and commands (the pod has no `kubectl`, `mise`, `jj`,
`tmux`, `chezmoi` or `talosctl`, and `HERMES_HOME` is `/opt/data`, not
`~/.hermes`), and a re-sync or prune **does not change the running pod** —
seeding is one-time, so the pod keeps whatever it already has until that path is
deleted on the PVC and the pod restarts.

To reach the cluster agent from a workstation terminal:
`kubectl -n llm exec -it deploy/hermes -- hermes` (interactive CLI on the
cluster profile), or open the dashboard URL. The CLI's own agent runtime is
always local; there is no remote-agent attach flag.

Before Flux can start the pod, create a `hermes` item in 1Password.  Its fields
is synced to the `hermes` Kubernetes secret. Add model-provider credentials and
optional integrations (for example, `OPENAI_API_KEY`, `FIRECRAWL_API_URL`, and
messaging tokens) to it as they are enabled.

The dashboard authenticates through PocketID using Hermes' native OIDC + PKCE
provider. Access is limited to the `hermes` PocketID user group, which currently
contains `tim`. The former `HERMES_DASHBOARD_BASIC_AUTH_*` fields are explicitly
masked so they cannot enable a second login method if they remain in 1Password.

The gateway connects to the private Matrix homeserver as
`@hermes:matrix.${DOMAIN_NAME}`. Its password is stored as `MATRIX_PASSWORD` in
the existing `hermes` item in the 1Password `Kubernetes` vault and synced into
the `hermes-matrix` Secret. Matrix E2EE is required and uses the stable
`HERMES_BOT` device ID, with crypto state retained on the backed-up Hermes PVC.
On first connection, Hermes writes its cross-signing recovery key once to
`/opt/data/matrix-recovery-key` with mode `0600`; this file is also backed up.
Only `@tim:matrix.${DOMAIN_NAME}` may invoke the bot. Hermes automatically accepts
room invitations; set `MATRIX_ALLOWED_ROOMS` after choosing permanent rooms if
access should be narrower than the user allowlist.

Hermes' provider is reconciled automatically before every pod start. One
provider, `litellm-chat` (displayed as **LiteLLM**), uses chat completions against
LiteLLM. The provider ID is retained for existing sessions. The retired
`litellm-responses` provider is removed on reconciliation: backend transport
selection belongs in LiteLLM, not in duplicate client provider entries.

The model catalogue is discovered dynamically from the authenticated
`/v1/models` endpoint. Do not add client-side model lists or disable discovery.
Model access is enforced by the LiteLLM virtual key, not by a picker list.
The startup default (`flashnext-deleuze`) and auxiliary task selections are
preferences, not an inventory. Context windows come from endpoint metadata;
reasoning capabilities come from the central model-caps service. `/model
--refresh` refreshes the client cache after catalogue changes. `/model qwen`
and `/model muse` remain convenience shortcuts.

The key comes from `litellm-key-hermes`. Inspect its server-side scope with
`kubectl -n llm get litellmvirtualkey hermes -o jsonpath='{.spec.models}'`.

The LiteLLM operator currently reconciles an edited `LiteLLMVirtualKey` object
without updating the model list of an already-issued key in LiteLLM's database.
The v4 rollout therefore applied `/key/update` once with the existing Hermes
and master keys held only in a short-lived, no-service-account pod, then deleted
that pod. Fresh key issuance uses the scoped CR directly; future scope edits
must repeat the database update until the operator closes this gap. When
repeating it, POST `/key/update` with the key **handle** from `/key/info` — the
raw token 404s with "Key not found" on that endpoint even though `/key/info`
accepts it — and assert the new model list is non-empty before posting, because
a wrongly-nested extraction posts `models: []` and silently blanks the scope of
the key the cluster agent runs on.
