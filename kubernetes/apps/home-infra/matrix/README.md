# Matrix homeserver

Synapse implements Cogito's private Matrix homeserver at
`https://matrix.${DOMAIN_NAME}`. The permanent Matrix server name is
`matrix.${DOMAIN_NAME}`, so Tim's account becomes `@tim:matrix.${DOMAIN_NAME}`.
Changing that name later is a migration, not a normal hostname edit.

Human login uses Synapse's native OIDC support and the generated Pocket ID
client. Only members of the `matrix` Pocket ID group may authenticate; it starts
with `tim`. Open registration is disabled. Password login remains available for
explicitly provisioned service accounts such as the non-admin Hermes bot. The
service is only exposed through the internal Envoy gateway, which also prevents
public federation even though Synapse implements the Matrix protocol.

The single-node Synapse process uses a three-instance CNPG cluster. CNPG is
explicitly bootstrapped with UTF-8 encoding and `C` collation/ctype, which
Synapse requires. Database backups use Cogito's CNPG component. Media, server
signing keys, and other stable Synapse secrets live on the backed-up `matrix`
PVC.

The ntfy hostname resolves through Cogito's internal Envoy address. That one
address is in Synapse's outbound IP whitelist so it can call ntfy's Matrix push
gateway without allowing arbitrary private-network URL fetches.

## Room configuration

Matrix rooms and spaces are durable Synapse state and are no longer reconciled
by Terraform. `app/room-ids.yaml` publishes the stable room IDs the gateway
needs as the `matrix-room-ids` ConfigMap. Update that ConfigMap only when one of
those rooms is deliberately replaced.

Names, topics, aliases, membership, join rules, power levels, and space
hierarchy are administered directly in Matrix. The retired
`@agent-gitops:matrix.${DOMAIN_NAME}` account remains the creator of some rooms
and of the existing Hookshot repository connection, but Kubernetes no longer
needs its access token.

The private `Agents` space is ordered for a phone, most-touched first, with one
notification decision per room. `m.space.child` carries an explicit `order`, so
the list does not re-sort alphabetically as rooms are renamed.

| Order | Room | Alias | Notifications | Contents |
| --- | --- | --- | --- | --- |
| 10 | `Cogito` | `#project-cogito` | all messages | Planning conversation with Astra; a bare message starts or continues a plan |
| 20 | `Implementation` | `#implementation` | all messages | Luna's execution updates and Tim's instructions |
| 30 | `Alerts` | `#alerts` | all messages, high priority | Only things that are broken |
| 40 | `GitHub` | `#github` | muted | The Hookshot repository firehose |
| 50 | `Runs` | `#agent-runs` | muted | Foreman Workload and scout transcripts |

Muting is only safe because `Alerts` stays audible; without it a failure would
land in a muted room and go unseen. Nothing else is wired to `Alerts` yet —
Alertmanager has no receiver configured on this cluster.

Conversations are flat. A plan is correlated to a message by explicit plan id,
then by the message a rich reply points at, then by the room's one open plan.
Threads remain only in `Runs`, where they group a scout's transcript in a room
that never notifies; a thread in a room that does notify behaves differently
across clients, which is exactly the ambiguity a phone surface cannot afford.

The gateway pins the plan card for every open plan and unpins it when the plan
reaches a terminal state, so an open plan stays reachable from the room header
instead of scrolling away.

The separate private `Personal` space contains `Watches` and `Money Making`.
These rooms hold durable topic context that may span many agent runs; operational
progress and failures still belong in the `Agents` space. Their canonical
aliases are `#personal-watches` and `#personal-money-making`.

## Bot identities

Three Matrix accounts serve the workflow, one per role. The MXID is the role so
the agent backing it can be swapped without Tim losing the sender he recognises
in his client; the display name carries the current agent.

| MXID | Display name | Device | Role |
| --- | --- | --- | --- |
| `@gateway` | `Gateway` | `COGITO_GATEWAY` | Receives every event, owns room state and pins, posts deterministic status |
| `@planner` | `Astra` | `COGITO_PLANNER` | Posts plan drafts, questions and revisions |
| `@coordinator` | `Luna` | existing | Posts execution updates |

Each runs as its own maubot container with its own credentials, device and Olm
store; a shared maubot database would give three accounts one crypto identity.
Only `@gateway` receives, so an inbound event is handled exactly once.

`@gateway` needs power level 100 in every room it administers — pinning is a
state event, and the default `state_default` is 50. `@hermes` keeps its own
account for direct sessions and does not belong in these rooms.

Removing a room from `app/room-ids.yaml` does not remove it from Synapse.
Obsolete rooms must be detached from their spaces and purged deliberately
through the Synapse admin API. Treat room ID changes as stateful migrations:
update memberships and aliases, then update the ConfigMap and verify the
gateway before purging the old room.

## Client enrollment

Matrix distinguishes `invite` from `join`: only the invited account can accept
an invitation. Tim accepts each outstanding invitation once in a Matrix
client: the space invitation and, separately, every private child-room
invitation.

Space membership does not imply membership in its private child rooms. Each
room holds its own membership, so the child-room invitations must be accepted
on their own. A pending invitation may not appear among joined rooms in a
client's space hierarchy. If the hierarchy does not redraw after accepting all
invitations, refresh or restart the client.

After the one-time joins, membership persists. The canonical aliases
(`#project-cogito`, `#implementation`, `#alerts`, `#github`, `#agent-runs`,
`#personal-watches`, `#personal-money-making`) confirm that the intended rooms
were joined.

Service accounts may accept invitations automatically when their own runtime
supports it. Human accounts still accept their own invitations in a Matrix
client. Hookshot retains the narrowly scoped `@agent-gitops` permission needed
by the existing repository connection; it does not grant that account cluster
credentials.

## Android push setup and acceptance

Cogito runs ntfy as both the UnifiedPush server and a Matrix push gateway.
Synapse is allowed to reach the private ntfy hostname, but each Matrix client
registers its own pusher with Synapse. The ntfy Android app supplies that client
with a push endpoint and receives notifications on the phone. The client may
discover ntfy's Matrix gateway from the endpoint; configuring the ntfy server
does not require a gateway URL override in every client.

1. In the ntfy Android app, set the default server to
   `https://ntfy.${DOMAIN_NAME}` and sign in to that server as `tim`. The app
   needs LAN or WireGuard access. Its UnifiedPush topics are registered
   automatically; do not subscribe to one manually.
2. Sign in to `https://matrix.${DOMAIN_NAME}` in the Matrix client using Pocket
   ID. For encrypted rooms, verify this device can decrypt messages and set up
   cross-signing and key backup.
3. In Sable for Android, enable **Background Push Notifications**, set
   **Transport Mode** to **UnifiedPush**, and select the installed **ntfy** app
   under **UnifiedPush Distributor**. Leave **UnifiedPush Gateway URL** empty.
   Sable v1.22.6 probes the ntfy endpoint for its Matrix gateway and registers
   the discovered URL with Synapse. **Built-in** is a separate distributor
   choice, configured by **Built-in distributor server**. Its unauthenticated
   subscription cannot read Cogito's `up*` topics under the current ntfy
   access rules.
4. Check Sable's **Delivery Route** after registration. It should use Cogito's
   ntfy host, rather than `matrix.gateway.unifiedpush.org` or another public
   gateway. If discovery falls back to a public gateway, set **UnifiedPush
   Gateway URL** to
   `https://ntfy.${DOMAIN_NAME}/_matrix/push/v1/notify`, then re-enable
   background push and check the route again. This URL is the Matrix gateway
   endpoint; the ntfy Android app's default server remains the base URL above.
5. Test locked-screen delivery, Wi-Fi/cellular and WireGuard transitions,
   overnight idle, phone restart, server restart, and offline replay. If a push
   fails, compare Sable's delivery route and ntfy distributor registration
   before changing server configuration.

The Sable behavior above is based on its [v1.22.6 gateway discovery and pusher
registration](https://github.com/SableClient/Sable/blob/v1.22.6/src/app/features/settings/notifications/UnifiedPushNotifications.ts)
and the [Android distributor implementation pinned by that
release](https://github.com/SableClient/tauri-plugin-notifications/blob/92c96b300517c49024a48aaff863338e3bd63616/android/src/main/java/app/tauri/notification/EmbeddedPushService.kt).
