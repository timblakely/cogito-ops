locals {
  server_name = "matrix.timblakely.com"

  users = {
    gitops = "@agent-gitops:${local.server_name}"
    hermes = "@hermes:${local.server_name}"
    tim    = "@tim:${local.server_name}"
  }
}

# This room predates the controller. The import block adopts it into state so
# the first reconciliation cannot create a duplicate.
resource "matrix_room" "hermes_agent" {
  name               = "Hermes Agent"
  topic              = "Private room for agent workflows and notification testing."
  encryption_enabled = true
  history_visibility = "shared"
  visibility         = "private"

  lifecycle {
    prevent_destroy = true
  }
}

import {
  to = matrix_room.hermes_agent
  id = "!rADbfOpOlzoprqhGdz:${local.server_name}"
}

resource "matrix_room_alias" "hermes_agent" {
  alias   = "#hermes-agent:${local.server_name}"
  room_id = matrix_room.hermes_agent.id
}

resource "matrix_room_state" "hermes_agent_canonical_alias" {
  room_id    = matrix_room.hermes_agent.id
  event_type = "m.room.canonical_alias"
  state_key  = ""
  content_json = jsonencode({
    alias       = matrix_room_alias.hermes_agent.alias
    alt_aliases = []
  })
}

resource "matrix_room_join_rules" "hermes_agent" {
  room_id   = matrix_room.hermes_agent.id
  join_rule = "invite"
}

import {
  to = matrix_room_join_rules.hermes_agent
  id = "!rADbfOpOlzoprqhGdz:${local.server_name}"
}

resource "matrix_room_member" "hermes_agent" {
  for_each = local.users

  room_id    = matrix_room.hermes_agent.id
  user_id    = each.value
  membership = each.key == "gitops" ? "join" : "invite"
}

import {
  for_each = local.users
  to       = matrix_room_member.hermes_agent[each.key]
  id       = "!rADbfOpOlzoprqhGdz:${local.server_name}|${each.value}"
}

resource "matrix_room_power_levels" "hermes_agent" {
  room_id        = matrix_room.hermes_agent.id
  users_default  = 0
  events_default = 0
  state_default  = 50
  invite         = 0
  kick           = 50
  ban            = 50
  redact         = 50

  users = {
    (local.users.gitops) = 100
    (local.users.hermes) = 100
    (local.users.tim)    = 100
  }

  events = {
    "m.room.avatar"             = 50
    "m.room.canonical_alias"    = 50
    "m.room.encryption"         = 100
    "m.room.history_visibility" = 100
    "m.room.name"               = 50
    "m.room.power_levels"       = 100
    "m.room.server_acl"         = 100
    "m.room.tombstone"          = 100
  }

  depends_on = [matrix_room_member.hermes_agent]
}

import {
  to = matrix_room_power_levels.hermes_agent
  id = "!rADbfOpOlzoprqhGdz:${local.server_name}"
}

check "controller_identity" {
  assert {
    condition     = data.matrix_whoami.controller.user_id == local.users.gitops
    error_message = "The supplied Matrix token does not belong to the GitOps service account."
  }
}
