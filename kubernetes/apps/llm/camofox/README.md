# Camofox

Camoufox (anti-detect Firefox) browser automation server with per-user session
persistence. The image bundles a VNC plugin that provides a live desktop view
for one-time interactive logins (MFA, CAPTCHA).

## State persistence

Each session's cookies and storage state are checkpointed on close to
`/root/.camofox/profiles/<sha256(userId) first 32 hex>/storage-state.json`
on the `camofox` PVC (RWO ceph-block). Any new session created with the same
`userId` auto-restores that state. Live Firefox profiles are ephemeral
(`/tmp/playwright_firefoxdev_profile-*`).

## Manual VNC login (one-time)

Use this to log into a site that requires visual interaction (e.g. Facebook
with MFA or CAPTCHA). After one successful login, all subsequent sessions with
the same `userId` inherit the authenticated state automatically.

1. Create a session pointing at the target site:

    ```bash
    curl -s -X POST https://camofox.timblakely.com/tabs \
        -H 'content-type: application/json' \
        -d '{"userId":"facebook","sessionKey":"default","url":"https://www.facebook.com"}'
    ```

2. Open the noVNC viewer in a browser: `https://camofox-vnc.timblakely.com/vnc.html`

3. Complete the login in the VNC desktop (handle MFA prompts, CAPTCHAs, etc.).

4. Close the session to trigger the persistence checkpoint:

    ```bash
    curl -s -X DELETE https://camofox.timblakely.com/sessions/facebook
    ```

5. Any agent session created with `userId: "facebook"` now inherits the
   authenticated cookies automatically.

Notes:

- `MAX_SESSIONS=10` — close the login session when done to free a slot.
- The noVNC WebSocket connects via `wss://` to the same 443 route; Envoy
  Gateway handles the WebSocket upgrade transparently.
- Port 5900 (raw VNC, plaintext) is intentionally **not** exposed. Only the
  noVNC HTTP/WebSocket interface on port 6080 is routed.
- **Clipboard.** noVNC clipboard works both ways (VNC→X and X→VNC). The
  `X11VNC_AVOID_WINDOWS=never` env var removes x11vnc's 45s display-manager
  grace period so the X clipboard is owned as soon as the first viewer
  connects, rather than 45s after the first connection.

## Security hardening (future)

This run ships without a VNC password: the camofox API is already
unauthenticated on the internal-only gateway (`POST /tabs` grants full browser
control), so noVNC adds no new threat surface.

To add a VNC password later:

1. Create a 1Password item (e.g. `camofox-vnc`) with a `VNC_PASSWORD` field.
2. Add an ExternalSecret (pattern: `kubernetes/apps/llm/litellm/app/externalsecret.yaml`)
   to project the secret into the `llm` namespace.
3. Add `VNC_PASSWORD` to `containers.app.env` sourced from the secret.

## DNS

`unifi-dns` (external-dns unifi-webhook, `sources: [gateway-httproute]`)
automatically creates CNAME records for both `camofox.timblakely.com` and
`camofox-vnc.timblakely.com` from the HTTPRoute hostnames.
