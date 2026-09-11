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

## Room GitOps

Tofu Controller reconciles room and space state declared under `terraform/`
through `raspbeguy/matrix`. The provider runs as the non-admin Matrix account
`@agent-gitops:matrix.${DOMAIN_NAME}`. Its password and long-lived access token
live in the `matrix-gitops` item in the 1Password `Kubernetes` vault; External
Secrets exposes only the access token to the short-lived runner pod.

The existing encrypted `Hermes Agent` room is imported by room ID, then managed
for its name, topic, alias, membership, join rule, and power levels. New agent
rooms and spaces belong in the same module. Agent harnesses remain ordinary
Matrix members and need no Terraform awareness.

The private `Agents` space contains `Agent Control`, `Agent Alerts`, `Agent
Plans`, `Agent Runs`, and `Cogito`. The adopted Hermes room is now `Agent
Control`; `#agent-control` is canonical and `#hermes-agent` remains a working
alternate alias. Plans should use one Matrix thread per plan in the applicable
project room, falling back to `Agent Plans` when no project room exists.

The separate private `Personal` space contains `Watches` and `Money Making`.
These rooms hold durable topic context that may span many agent runs; operational
progress and failures still belong in the `Agents` space. Tim and Hermes are
invited to each personal room. Their canonical aliases are `#personal-watches`
and `#personal-money-making` on this homeserver.

`prevent_destroy` blocks destructive replacement while an adopted room remains
declared, and the Terraform custom resource sets
`destroyResourcesOnDeletion: false` so deleting the controller object does not
tear down Matrix resources. Matrix cannot delete rooms through the client API;
removing a room resource from HCL can still make the service account leave it,
so review those diffs with the same care as any other stateful GitOps change.
Provider and controller versions, chart, and controller images are pinned. The
Matrix provider is young, so its scope is deliberately limited to durable room
state rather than messages or agent runtime behavior.

## Client enrollment

Matrix distinguishes `invite` from `join`: the controller sends the
invitations, but only the invited account can accept them. The private
`Agents` and `Personal` spaces, their child rooms, aliases, hierarchy, and
invitations are all declared and reconciled through GitOps; none of that
accepts a membership on an account's behalf. Tim accepts each outstanding
invitation once in a Matrix client: the space invitation and, separately,
every private child-room invitation.

Space membership does not imply membership in its private child rooms. Each
room holds its own membership, so the child-room invitations must be accepted
on their own. In Commet an unaccepted invitation does not appear as a joined
room in the space hierarchy, which made the first enrollment confusing; if
the hierarchy still does not redraw after accepting, refresh or restart the
client.

After the one-time joins, membership persists: later changes to room names,
topics, aliases, and space hierarchy continue to reconcile through GitOps
without further client action. The canonical aliases (`#agent-control`,
`#personal-watches`, `#personal-money-making`) confirm that the intended
rooms were joined.

Service accounts may accept invitations automatically when their own runtime
supports it. Hookshot does so only when the inviter has at least `login`
permission. Cogito grants `@agent-gitops` the additive
`generic: manageConnections` level, which includes invite permission while
remaining confined to generic webhooks. Human accounts still accept their own
invitations in a Matrix client.

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
