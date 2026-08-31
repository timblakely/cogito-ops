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

2. Open the noVNC viewer in a browser: `https://browser.timblakely.com/vnc.html`

3. Complete the login in the VNC desktop (handle MFA prompts, CAPTCHAs, etc.).

4. Close the session to trigger the persistence checkpoint:

    ```bash
    curl -s -X DELETE https://camofox.timblakely.com/sessions/facebook
    ```

5. Any agent session created with `userId: "facebook"` now inherits the
   authenticated cookies automatically.

Notes:

- **Black desktop.** With no session/tab the X desktop has no browser window
  and renders black, which is indistinguishable from a failed connection in
  the viewer. The `vnc-tab-seeder` container keeps a `vnc-default` tab open
  whenever `activeTabs` drops to 0, so the desktop should always show
  *something*. If it is still black, check that the seeder is running
  (`kubectl logs -n llm deploy/camofox -c vnc-tab-seeder`) and that
  `curl -s https://camofox.timblakely.com/health` reports `activeTabs >= 1`.
- `MAX_SESSIONS=11` — ten user slots plus the one permanently held by the
  seeder. Close the login session when done to free a slot.
- The noVNC WebSocket connects via `wss://` to the same 443 route; Envoy
  Gateway handles the WebSocket upgrade transparently.
- Port 5900 (raw VNC, plaintext) is intentionally **not** exposed. Only the
  noVNC HTTP/WebSocket interface on port 6080 is routed.
- **Clipboard.** noVNC clipboard works both ways (VNC→X and X→VNC). The
  `X11VNC_AVOID_WINDOWS=never` env var removes x11vnc's 45s display-manager
  grace period so the X clipboard is owned as soon as the first viewer
  connects, rather than 45s after the first connection.
- **Viewport & fullscreen.** The desktop is a fixed `1920x1080` framebuffer
  (`VNC_RESOLUTION`); the Xvfb/Firefox server resolution is **not** made
  dynamic. noVNC only *scales* that feed client-side to fit the window. For
  fit-to-viewport, open
  `https://browser.timblakely.com/vnc.html?autoconnect=true&resize=scale`; for
  full-screen use noVNC's on-screen fullscreen button (the browser Fullscreen
  API). These are client-side options and depend on the noVNC build in the
  image — recommended, not guaranteed.

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
`browser.timblakely.com` from the HTTPRoute hostnames.

## Troubleshooting: "can't connect"

A black viewer and a genuinely broken connection look the same in noVNC, so
confirm which one you have before changing anything. This proves the whole
path — Envoy → websockify → x11vnc → Xvfb — independently of the browser:

```bash
curl -sSi --http1.1 --max-time 15 \
    -H 'Connection: Upgrade' -H 'Upgrade: websocket' \
    -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Protocol: binary' \
    -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
    https://browser.timblakely.com/websockify
```

A healthy stack answers `101 Switching Protocols` followed by the RFB banner
`RFB 003.008`. If you get that, the transport is fine and a black or failed
viewer is a *desktop* problem (no tab open) — check `/health` for
`activeTabs`.

Note that `--http1.1` is required: over HTTP/2 the same request is not a
WebSocket handshake at all, and websockify answers `404`. That 404 is
expected and is **not** evidence of a broken route. Real browsers are
unaffected — Envoy advertises `SETTINGS_ENABLE_CONNECT_PROTOCOL = 0`, so they
fall back to an HTTP/1.1 connection for the WebSocket on their own.
