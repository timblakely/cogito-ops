# Harness-neutral agent notifications

`agent-notify.sh` publishes direct alerts to ntfy while keeping a local outbox
for publisher-side outages. It is deliberately independent of the model,
LiteLLM, and the agent harness. A harness hook maps its lifecycle event to one
of `completed`, `failed`, `needs_input`, or quiet `progress`.

The script does not decide when approval is required and does not pause a
workflow. The runner remains responsible for durable workflow state, pending
decisions, and safe resumption. The outbox only protects notification delivery.
By default, a newly queued event does not fail the calling workflow. Set
`COGITO_NOTIFY_STRICT=true` when the caller deliberately wants that behavior;
the explicit `--flush` command always returns failure while delivery is blocked.

Configure the environment from a secret manager rather than placing credentials
in a command line or repository:

```shell
export NTFY_URL=https://ntfy.example.net
export NTFY_TOPIC=tim-agent-events
export NTFY_USER=agent
export NTFY_PASSWORD=REDACTED
export AGENT_HARNESS=hermes
```

Publish an event:

```shell
AGENT_WORKFLOW_ID=research-42 \
AGENT_RESUME_URL=https://hermes.example.net \
./scripts/agent-notify.sh needs_input 'Choose between the two migration paths.'
```

Retry queued events periodically:

```shell
./scripts/agent-notify.sh --flush
```

The default outbox is
`${XDG_STATE_HOME:-$HOME/.local/state}/cogito-agent-notify/outbox`. Set
`COGITO_NOTIFY_STATE_DIR` when the harness already has a durable state volume.
Use a stable `AGENT_EVENT_ID` when a harness may invoke the same hook more than
once. ntfy delivery is at least once from this adapter, so recipients should use
the displayed event ID to recognize a duplicate.
