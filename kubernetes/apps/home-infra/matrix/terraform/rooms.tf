locals {
  server_name = "matrix.timblakely.com"

  users = {
    gitops = "@agent-gitops:${local.server_name}"
    hermes = "@hermes:${local.server_name}"
    tim    = "@tim:${local.server_name}"
  }

  agent_rooms = {
    alerts = {
      name  = "Agent Alerts"
      topic = "Failures, blocked work, approval requests, and important completions."
      alias = "agent-alerts"
      order = "20"
    }
    plans = {
      name  = "Agent Plans"
      topic = "Plan review threads that do not yet belong to a dedicated project room."
      alias = "agent-plans"
      order = "30"
    }
    runs = {
      name  = "Agent Runs"
      topic = "Detailed progress and results for agent and cluster automation runs."
      alias = "agent-runs"
      order = "40"
    }
    cogito = {
      name  = "Cogito"
      topic = "Design decisions, plans, and implementation work for the Cogito cluster."
      alias = "project-cogito"
      order = "50"
    }
  }

  agent_room_members = merge([
    for room_key, room in local.agent_rooms : {
      for user_key, user_id in local.users : "${room_key}:${user_key}" => {
        room_key = room_key
        user_key = user_key
        user_id  = user_id
      }
    }
  ]...)
}

# This room predates the controller. The import block adopts it into state so
# the first reconciliation cannot create a duplicate.
resource "matrix_room" "hermes_agent" {
  name               = "Agent Control"
  topic              = "Commands, questions, approvals, and concise results for interactive agents."
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

resource "matrix_room_alias" "agent_control" {
  alias   = "#agent-control:${local.server_name}"
  room_id = matrix_room.hermes_agent.id
}

resource "matrix_room_state" "hermes_agent_canonical_alias" {
  room_id    = matrix_room.hermes_agent.id
  event_type = "m.room.canonical_alias"
  state_key  = ""
  content_json = jsonencode({
    alias       = matrix_room_alias.agent_control.alias
    alt_aliases = [matrix_room_alias.hermes_agent.alias]
  })
}

resource "matrix_space" "agents" {
  name               = "Agents"
  topic              = "Agent control, plans, alerts, runs, and project work."
  preset             = "private_chat"
  room_alias_name    = "agents"
  room_version       = "12"
  history_visibility = "shared"
  visibility         = "private"

  lifecycle {
    prevent_destroy = true
  }
}

resource "matrix_room_member" "agents_space" {
  room_id    = matrix_space.agents.id
  user_id    = local.users.tim
  membership = "invite"
}

resource "matrix_room_join_rules" "agents_space" {
  room_id   = matrix_space.agents.id
  join_rule = "invite"
}

resource "matrix_room_power_levels" "agents_space" {
  room_id = matrix_space.agents.id

  # Room v12 creators retain intrinsic control and must not appear here.
  users = {
    (local.users.tim) = 100
  }
}

resource "matrix_room" "agent" {
  for_each = local.agent_rooms

  name               = each.value.name
  topic              = each.value.topic
  preset             = "private_chat"
  room_alias_name    = each.value.alias
  room_version       = "12"
  encryption_enabled = true
  history_visibility = "shared"
  visibility         = "private"

  lifecycle {
    prevent_destroy = true
  }
}

resource "matrix_room_member" "agent" {
  for_each = local.agent_room_members

  room_id    = matrix_room.agent[each.value.room_key].id
  user_id    = each.value.user_id
  membership = each.value.user_key == "gitops" ? "join" : "invite"
}

resource "matrix_room_join_rules" "agent" {
  for_each = local.agent_rooms

  room_id   = matrix_room.agent[each.key].id
  join_rule = "invite"
}

resource "matrix_room_power_levels" "agent" {
  for_each = local.agent_rooms

  room_id        = matrix_room.agent[each.key].id
  users_default  = 0
  events_default = 0
  state_default  = 50
  invite         = 0
  kick           = 50
  ban            = 50
  redact         = 50

  # agent-gitops creates these v12 rooms and therefore has intrinsic control.
  users = {
    (local.users.hermes) = 0
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

  depends_on = [matrix_room_member.agent]
}

resource "matrix_space_child" "agent_control" {
  parent_space_id = matrix_space.agents.id
  child_room_id   = matrix_room.hermes_agent.id
  suggested       = true
  order           = "10"
  via             = [local.server_name]
}

resource "matrix_space_child" "agent" {
  for_each = local.agent_rooms

  parent_space_id = matrix_space.agents.id
  child_room_id   = matrix_room.agent[each.key].id
  suggested       = true
  order           = each.value.order
  via             = [local.server_name]
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
