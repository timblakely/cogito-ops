# Inkling effort integration

## Upstream contract

Inkling 2 Mini supports effort conditioning independently of whether our clients
advertise it. The upstream chat template maps `none`, `minimal`, `low`, `medium`,
`high`, `xhigh`, and `max` to `0`, `0.1`, `0.2`, `0.7`, `0.9`, `0.99`, and `0.99`.
The omitted default is `high`. `none` is minimum effort, not a hard guarantee of
no reasoning. `max` is an alias of `xhigh`, not additional compute.

Sources checked on 2026-11-27:

- https://huggingface.co/blog/inkling2mini#reasoning-effort
- https://huggingface.co/thinkingmachines/Inkling-2-Mini/raw/main/chat_template.jinja
- https://tinker-docs.thinkingmachines.ai/cookbook/inkling/thinking-effort/

The Mini template specifically accepts numeric values in `[0, 0.99]`. Tinker's
renderer documents `[0, 1)`; do not assume the broader renderer range applies to
every deployment.

## Bounded live probe

`probe_efforts.py --self-test` is offline and reads no credentials. Render the
one-time Job with:

```sh
kustomize build plans/llm/artifacts/2026-11-27-inkling-effort \
  --load-restrictor=LoadRestrictionsNone
```

Preview the complete output before applying. This directory is not part of the
GitOps resource tree. The Job projects only the existing Hermes and OpenCode
consumer keys, disables the ServiceAccount token, and makes eight sequential
bounded requests with each key. No runtime/admin key is mounted. Keys, raw API
responses, error bodies, and arbitrary generated content are never logged.

The probe records status, returned model, token counts, reasoning length, and a
strictly numeric model self-report of the effort-conditioning system message.
Different matching self-reports across the ladder corroborate parameter
handling; they are not a substitute for runtime-code or rendered-prompt
inspection. Response length by itself is not proof of effort handling.

Logs and validation reports are held under `/tmp/opencode/inkling-effort` while
the task is active. Record the final findings and deployed revision here before
handing off a rollout that might interrupt the agent service.

## Runtime observations

`probe-results.json` records the initial 256-token attempt, a targeted
1024-token confirmation of the three initially truncated Hermes responses,
and the complete OpenCode-key confirmation after its concurrency repair.
Through the Hermes key, all seven named efforts and the omitted default returned
HTTP 200 and the expected numeric conditioning value. The omitted default
reported `0.9`; `none` reported `0` while still producing reasoning content;
`xhigh` and `max` both reported `0.99`.

The initial OpenCode-key requests were rate-limited (HTTP 429), not rejected for
unsupported levels. The user subsequently authorized matching the key's
concurrency ceiling to Radiance's eight active-sequence slots. The declaration
and existing database key were both repaired; see `concurrency-sync/`. All eight
OpenCode-key checks then returned HTTP 200 with the expected numeric effort.
Final coverage is sixteen successful conditioning checks across both consumers.

Offline catalogue and Hermes provider-configuration tests passed. The pinned
legacy flux-local 8.4.0 command cannot collect tests in a non-colocated jj
workspace because its GitPython discovery requires `.git`. Preserve workspace
isolation rather than altering version-control metadata to bypass that limit.
