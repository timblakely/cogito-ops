# Matrix homeserver

Synapse implements Cogito's private Matrix homeserver at
`https://matrix.${DOMAIN_NAME}`. The permanent Matrix server name is
`matrix.${DOMAIN_NAME}`, so Tim's account becomes `@tim:matrix.${DOMAIN_NAME}`.
Changing that name later is a migration, not a normal hostname edit.

Human login uses Synapse's native OIDC support and the generated Pocket ID
client. Only members of the `matrix` Pocket ID group may authenticate; it starts
with `tim`. Password login and open registration are disabled. The service is
only exposed through the internal Envoy gateway, which also prevents public
federation even though Synapse implements the Matrix protocol.

The single-node Synapse process uses a single-instance CNPG cluster. CNPG is
explicitly bootstrapped with UTF-8 encoding and `C` collation/ctype, which
Synapse requires. Database backups use Cogito's CNPG component. Media, server
signing keys, and other stable Synapse secrets live on the backed-up `matrix`
PVC.

The ntfy hostname resolves through Cogito's internal Envoy address. That one
address is in Synapse's outbound IP whitelist so it can call ntfy's Matrix push
gateway without allowing arbitrary private-network URL fetches.

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
