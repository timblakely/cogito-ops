#!/usr/bin/env bash
set -Eeuo pipefail

# Durable, harness-neutral ntfy adapter. Events are written to a local outbox
# before delivery and are removed only after ntfy accepts them. Invoke --flush
# from a timer/cron job to retry after publisher-side network outages.

usage() {
  cat <<'EOF'
Usage:
  agent-notify.sh <completed|failed|needs_input|progress> <summary>
  agent-notify.sh --flush

Required environment:
  NTFY_URL       Base URL, for example https://ntfy.example.net
  NTFY_TOPIC     Authorized topic, for example tim-agent-events

Authentication (choose one):
  NTFY_TOKEN
  NTFY_USER and NTFY_PASSWORD

Optional event metadata:
  AGENT_HARNESS, AGENT_WORKFLOW_ID, AGENT_SESSION_ID, AGENT_DECISION_ID,
  AGENT_RESUME_URL, AGENT_EVENT_ID, COGITO_NOTIFY_STATE_DIR,
  COGITO_NOTIFY_STRICT (true makes a newly queued event return failure)
EOF
}

require_env() {
  local name=$1
  if [[ -z ${!name:-} ]]; then
    printf 'agent-notify: %s is required\n' "$name" >&2
    exit 2
  fi
}

require_env NTFY_URL
require_env NTFY_TOPIC

state_root=${COGITO_NOTIFY_STATE_DIR:-${XDG_STATE_HOME:-${HOME}/.local/state}/cogito-agent-notify}
outbox=${state_root}/outbox
mkdir -p -m 700 "$outbox"

auth_args=()
if [[ -n ${NTFY_TOKEN:-} ]]; then
  auth_args+=(--header "Authorization: Bearer ${NTFY_TOKEN}")
elif [[ -n ${NTFY_USER:-} && -n ${NTFY_PASSWORD:-} ]]; then
  auth_args+=(--user "${NTFY_USER}:${NTFY_PASSWORD}")
else
  printf 'agent-notify: set NTFY_TOKEN or NTFY_USER and NTFY_PASSWORD\n' >&2
  exit 2
fi

send_file() {
  local event_file=$1
  curl --fail-with-body --silent --show-error \
    --retry 2 --retry-all-errors --connect-timeout 5 --max-time 20 \
    "${auth_args[@]}" \
    --header 'Content-Type: application/json' \
    --data-binary "@${event_file}" \
    "${NTFY_URL%/}"
}

flush_outbox() {
  local event_file
  local failed=0
  shopt -s nullglob
  for event_file in "$outbox"/*.json; do
    if send_file "$event_file" >/dev/null; then
      rm -- "$event_file"
    else
      failed=1
      break
    fi
  done
  return "$failed"
}

if [[ ${1:-} == --flush ]]; then
  [[ $# -eq 1 ]] || { usage >&2; exit 2; }
  flush_outbox
  exit
fi

[[ $# -eq 2 ]] || { usage >&2; exit 2; }
event=$1
summary=$2
case "$event" in
  completed|failed|needs_input|progress) ;;
  *)
    printf 'agent-notify: unsupported event %q\n' "$event" >&2
    exit 2
    ;;
esac

command -v jq >/dev/null || {
  printf 'agent-notify: jq is required\n' >&2
  exit 2
}

event_id=${AGENT_EVENT_ID:-$(date -u +%Y%m%dT%H%M%S)-$$-${RANDOM}}
if [[ ! $event_id =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  printf 'agent-notify: AGENT_EVENT_ID contains unsafe characters\n' >&2
  exit 2
fi
event_file=${outbox}/${event_id}.json
harness=${AGENT_HARNESS:-agent}

case "$event" in
  failed)
    priority=high
    tags='["x"]'
    ;;
  needs_input)
    priority=high
    tags='["question"]'
    ;;
  completed)
    priority=default
    tags='["white_check_mark"]'
    ;;
  progress)
    priority=low
    tags='["hourglass_flowing_sand"]'
    ;;
esac

jq -n \
  --arg topic "$NTFY_TOPIC" \
  --arg title "${harness}: ${event}" \
  --arg message "$summary" \
  --arg priority "$priority" \
  --argjson tags "$tags" \
  --arg click "${AGENT_RESUME_URL:-}" \
  --arg event_id "$event_id" \
  --arg workflow_id "${AGENT_WORKFLOW_ID:-}" \
  --arg session_id "${AGENT_SESSION_ID:-}" \
  --arg decision_id "${AGENT_DECISION_ID:-}" \
  '{
    topic: $topic,
    title: $title,
    message: ($message + "\n\nevent=" + $event_id
      + (if $workflow_id == "" then "" else "\nworkflow=" + $workflow_id end)
      + (if $session_id == "" then "" else "\nsession=" + $session_id end)
      + (if $decision_id == "" then "" else "\ndecision=" + $decision_id end)),
    priority: $priority,
    tags: $tags
  }
  + (if $click == "" then {} else {click: $click} end)' \
  >"$event_file"
chmod 600 "$event_file"

if ! flush_outbox; then
  printf 'agent-notify: event queued for retry: %s\n' "$event_file" >&2
  [[ ${COGITO_NOTIFY_STRICT:-false} == true ]] && exit 1
  exit 0
fi
