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
by Terraform. `app/room-ids.yaml` publishes the two stable room IDs needed by
the gateway as the `matrix-room-ids` ConfigMap. Update that ConfigMap only when
one of those rooms is deliberately replaced.

Names, topics, aliases, membership, join rules, power levels, and space
hierarchy are administered directly in Matrix. The retired
`@agent-gitops:matrix.${DOMAIN_NAME}` account remains the creator of some rooms
and of the existing Hookshot repository connection, but Kubernetes no longer
needs its access token.

The private `Agents` space contains `Agent Control`, `Agent Runs`,
`Implementation`, `GitHub`, and `Cogito`. The adopted Hermes room is now
`Agent Control`; `#agent-control` is canonical and `#hermes-agent` remains a
working alternate alias. Plans use one Matrix thread per plan in the applicable
project room.

For Cogito automation, `Cogito` is the control room: planner conversation,
approval, blockers, and overall completion remain in the originating plan
thread. A top-level owner message starts plan intake without a command prefix;
`!cogito plan` remains an explicit alias. `Agent Runs` is the muteable activity room for Foreman progress,
review/merge updates, and the Hookshot repository connection. Matrix room
notification settings are the reliable client-wide boundary; activity is not
hidden in a thread that may notify differently across clients.

The separate private `Personal` space contains `Watches` and `Money Making`.
These rooms hold durable topic context that may span many agent runs; operational
progress and failures still belong in the `Agents` space. Tim and Hermes are
invited to each personal room. Their canonical aliases are `#personal-watches`
and `#personal-money-making` on this homeserver.

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
on their own. In Commet an unaccepted invitation does not appear as a joined
room in the space hierarchy, which made the first enrollment confusing; if
the hierarchy still does not redraw after accepting, refresh or restart the
client.

After the one-time joins, membership persists. The canonical aliases
(`#agent-control`, `#personal-watches`, `#personal-money-making`) confirm that
the intended rooms were joined.

Service accounts may accept invitations automatically when their own runtime
supports it. Human accounts still accept their own invitations in a Matrix
client. Hookshot retains the narrowly scoped `@agent-gitops` permission needed
by the existing repository connection; it does not grant that account cluster
credentials.

## Android setup and acceptance

1. Install the ntfy Android distributor and set its default server to
   `https://ntfy.${DOMAIN_NAME}` before registering a Matrix client.
2. Sign in to `https://matrix.${DOMAIN_NAME}` from Commet and FluffyChat using
   Pocket ID.
3. Enable UnifiedPush in each client and select the ntfy distributor/custom
   gateway. Confirm Synapse records a pusher whose URL is the self-hosted ntfy
   gateway.
4. Use a private E2EE room and enable cross-signing/key backup in the selected
   client before adding an agent bot.
5. Test locked-screen delivery, Wi-Fi/cellular and WireGuard transitions,
   overnight idle, phone restart, server restart, and offline replay.

Commet remains provisional because its current upstream tracker has open Android
UnifiedPush failures. Keep FluffyChat installed during acceptance so client and
server failures can be distinguished.
