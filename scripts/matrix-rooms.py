#!/usr/bin/env python3
"""Reconcile the Agents space to the layout documented in the Matrix README.

Rooms are durable Synapse state rather than GitOps resources, so this script is
the repeatable way to apply the intended arrangement: names, aliases, phone
ordering, membership, and the power levels `@gateway` needs to pin plan cards.

Every step is idempotent. Run it from a shell with access to the Synapse pod:

    kubectl exec -i -n home-infra deploy/matrix -c main -- \
        python3 - <token> < scripts/matrix-rooms.py

The token must belong to an account holding power level 100 in the rooms.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8008"
SERVER = "matrix.timblakely.com"
OWNER = f"@tim:{SERVER}"
GATEWAY = f"@gateway:{SERVER}"
PLANNER = f"@planner:{SERVER}"
COORDINATOR = f"@coordinator:{SERVER}"
HERMES = f"@hermes:{SERVER}"
HOOKSHOT = f"@hookshot:{SERVER}"
AGENT_GITOPS = f"@agent-gitops:{SERVER}"

AGENTS_SPACE = "!Atn3nkk5S9gjknNX4N8A-vXtM10TjSZYxl3gr96NLaw"
PERSONAL_SPACE = "!DTi5jw56c-Io5_pYfIiaXnIbRXaCDPABRCaRRt_Lweo"

# Ordered for a phone, most-touched first. `order` is a string sort key, so
# renaming a room never re-sorts the space.
ROOMS = [
    {"id": "!Z5AkE1biq0CAYjxBPct92Fc2LgBxUVcuZFZY9-Nm3O4", "order": "10",
     "name": "Cogito", "alias": "project-cogito",
     "topic": "Planning with Astra. Just say what you want; no prefix needed.",
     "bots": [GATEWAY, PLANNER, COORDINATOR]},
    {"id": "!i1huZbgWwv2HH6t70PbUdrGUkKa4Rnh8evm1Fzw5PuY", "order": "20",
     "name": "Implementation", "alias": "implementation",
     "topic": "Luna running approved plans. Reply here to steer a deliverable.",
     "bots": [GATEWAY, COORDINATOR]},
    {"id": "!YOrEKVNSGUcZjppjqG:matrix.timblakely.com", "order": "30",
     "name": "Alerts", "alias": "alerts",
     "topic": "Things that are broken. The one room that is never muted.",
     "bots": [GATEWAY]},
    {"id": "!WJHrtohCcXHk_Ry5Q3mIU9exrDm58sIuqERo534E1GU", "order": "40",
     "name": "GitHub", "alias": "github",
     "topic": "Hookshot repository firehose. Muted; this is a debugging stream.",
     "bots": [GATEWAY, HOOKSHOT]},
    {"id": "!5wS6Ha0iIA8OL4oWd1lYAqGubN1eXqN34ZDqmWIgbPU", "order": "50",
     "name": "Runs", "alias": "agent-runs",
     "topic": "Foreman Workload and scout transcripts. Muted; one thread per run.",
     "bots": [GATEWAY]},
]

# Adopted from the first Hermes experiment and wired to nothing since: direct
# sessions are DMs and the gateway listens to the project room.
RETIRED = {"id": "!rADbfOpOlzoprqhGdz:matrix.timblakely.com", "name": "Agent Control"}

PERSONAL = [
    {"id": "!eUaIObggPEfhJU2MbOA-qUdUSl5-xk5JywZMuJgDOuc", "order": "10", "bots": []},
    {"id": "!evswr8DPTgDVHrQ1SG6tCdU0j4420gXWuyaWGP1Oux8", "order": "20", "bots": []},
]

token = sys.argv[1]
apply = "--dry-run" not in sys.argv


def call(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        return {"_error": exc.code, "_body": exc.read().decode()[:300]}


def state(room: str, kind: str, key: str = ""):
    path = f"/_matrix/client/v3/rooms/{urllib.parse.quote(room)}/state/{kind}"
    if key:
        path += "/" + urllib.parse.quote(key)
    return call("GET", path)


def put_state(room: str, kind: str, body: dict, key: str = "") -> str:
    path = f"/_matrix/client/v3/rooms/{urllib.parse.quote(room)}/state/{kind}"
    if key:
        path += "/" + urllib.parse.quote(key)
    if not apply:
        return "dry-run"
    result = call("PUT", path, body)
    return "ok" if "event_id" in result else f"FAILED {result.get('_body', result)}"


def say(label: str, outcome: str) -> None:
    print(f"  {label}: {outcome}")


def reconcile_room(room: dict) -> None:
    print(f"{room['name']} ({room['id']})")
    current = state(room["id"], "m.room.name")
    if current.get("name") != room["name"]:
        say("name", put_state(room["id"], "m.room.name", {"name": room["name"]}))
    current = state(room["id"], "m.room.topic")
    if current.get("topic") != room["topic"]:
        say("topic", put_state(room["id"], "m.room.topic", {"topic": room["topic"]}))

    alias = f"#{room['alias']}:{SERVER}"
    directory = call("GET", "/_matrix/client/v3/directory/room/"
                     + urllib.parse.quote(alias))
    if directory.get("room_id") != room["id"] and apply:
        say("alias", str(call(
            "PUT", "/_matrix/client/v3/directory/room/" + urllib.parse.quote(alias),
            {"room_id": room["id"]}).get("_body", "ok")))
    canonical = state(room["id"], "m.room.canonical_alias")
    if canonical.get("alias") != alias:
        say("canonical alias", put_state(
            room["id"], "m.room.canonical_alias", {"alias": alias}))

    # The gateway pins plan cards, which is a state event: it needs 100.
    levels = state(room["id"], "m.room.power_levels")
    users = dict(levels.get("users") or {})
    desired = dict(users)
    desired[OWNER] = 100
    desired[GATEWAY] = 100
    for bot in room["bots"]:
        desired.setdefault(bot, 0)
    if HOOKSHOT in desired and HOOKSHOT not in room["bots"]:
        desired.pop(HOOKSHOT)
    desired.pop(HERMES, None)
    desired.pop(AGENT_GITOPS, None)
    if desired != users:
        levels["users"] = desired
        say("power levels", put_state(room["id"], "m.room.power_levels", levels))

    # Membership: the room's own bots, plus Tim. Everything else is removed so
    # a room's member list says what actually operates in it.
    allowed = {OWNER, *room["bots"]}
    members = call("GET", f"/_matrix/client/v3/rooms/{urllib.parse.quote(room['id'])}"
                          "/joined_members").get("joined", {})
    for member in members:
        if member not in allowed:
            say(f"remove {member}", "dry-run" if not apply else str(call(
                "POST", f"/_matrix/client/v3/rooms/{urllib.parse.quote(room['id'])}/kick",
                {"user_id": member, "reason": "not an operator of this room"},
            ).get("_body", "ok")))
    for bot in room["bots"]:
        if bot not in members:
            say(f"invite {bot}", "dry-run" if not apply else str(call(
                "POST", f"/_matrix/client/v3/rooms/{urllib.parse.quote(room['id'])}/invite",
                {"user_id": bot}).get("_body", "ok")))


def reconcile_space(space: str, children: list[dict]) -> None:
    print(f"space {space}")
    for child in children:
        current = state(space, "m.space.child", child["id"])
        if (current.get("order") != child["order"]
                or not current.get("via")):
            say(f"child {child['id']} order {child['order']}", put_state(
                space, "m.space.child",
                {"via": [SERVER], "order": child["order"], "suggested": True},
                child["id"]))


if __name__ == "__main__":
    if not apply:
        print("dry run; no state will be written\n")
    for room in ROOMS:
        reconcile_room(room)
    reconcile_space(AGENTS_SPACE, ROOMS)
    reconcile_space(PERSONAL_SPACE, PERSONAL)
    print(f"\n{RETIRED['name']} ({RETIRED['id']}) is retired: detach it from the "
          "space and purge it through the Synapse admin API when you are ready.")
