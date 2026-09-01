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

## Viewer

Open `https://browser.timblakely.com/`. That page is `index.html` from the
`camofox-novnc` ConfigMap; it is mounted into `/usr/share/novnc/`, which
otherwise ships **no** index at all, so `/` used to serve websockify's raw
directory listing. It loads the stock `vnc.html` in a same-origin iframe with
`?autoconnect=true&resize=scale&reconnect=true&show_dot=true`, and injects
`app/clipboard-bridge.js` into that document.

Both files are *additions*, never replacements: nothing shipped in the image is
shadowed, so bumping the camofox image tag cannot silently revert the viewer to
a stale copy of a file we overwrote. `/vnc.html` remains the untouched stock
viewer if you need to rule the bridge out.

The three things the landing page fixes, and why each needs fixing:

- **It scales to the window.** noVNC's default `resize=off` pins the canvas at
  the native framebuffer size, so resizing the browser window did nothing.
  `resize=scale` scales client-side and follows window resizes.

  True *remote* resize (`resize=remote`, where the desktop actually changes
  resolution) is not available here and is not a config away: Xvfb is started
  with a single fixed `-screen 0 1920x1080x24` mode, and x11vnc 0.9.16 does not
  implement client-initiated `SetDesktopSize`. Both halves would have to change
  to get it, so client-side scaling is the fix. A widescreen window therefore
  letterboxes the 16:9 feed rather than filling it.

- **Ctrl+V pastes the *local* clipboard.** noVNC calls `preventDefault()` on
  every key it forwards, which suppresses the browser's native paste event.
  The local clipboard therefore never reached the remote X CLIPBOARD selection,
  and Ctrl+V in the remote Firefox pasted whatever that session last copied.
  The bridge intercepts Ctrl+V in the capture phase before noVNC's canvas
  listener sees it, lets the real paste event fire, sends the text over RFB as
  `ClientCutText`, then replays the keystroke. `ClientCutText` and `KeyEvent`
  travel the same stream and x11vnc handles messages in order, so the selection
  is owned before the keystroke is processed — no delay needed. If no paste
  event arrives within 150 ms the bridge falls back to
  `navigator.clipboard.readText()` (Chrome prompts once for the permission,
  then is silent) and synthesizes the modifiers too, since the physical Ctrl
  may have been released by then.

  The reverse direction is wired up as well: copying in the remote Firefox
  fires noVNC's `clipboard` event, and the bridge mirrors it into the local
  clipboard with `navigator.clipboard.writeText()`. The stock noVNC clipboard
  side-panel keeps working unchanged.

- **CapsLock acts as Ctrl.** This desktop's X config uses the
  `caps:ctrl_modifier` option, which makes CapsLock a Control *modifier*
  locally while deliberately leaving the emitted keysym as `Caps_Lock`. noVNC
  forwards keysyms, so the remote session received a bare `Caps_Lock` press and
  nothing else. The bridge swallows the key and sends `Control_L` in its place,
  and releases it on window blur (noVNC only auto-releases keys it believes it
  sent). Doing this in the client rather than with x11vnc's `-remap` keeps the
  change scoped to this page and avoids patching the image's
  `vnc-watcher.sh`, which builds its x11vnc argument list with no env hook.

Because the ConfigMap is mounted by `subPath`, updates never appear in place —
`reloader.stakater.com/auto` on the controller rolls the Deployment when the
ConfigMap changes.

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

2. Open the noVNC viewer in a browser: `https://browser.timblakely.com/`

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
- **Clipboard.** The `X11VNC_AVOID_WINDOWS=never` env var removes x11vnc's
  45s display-manager grace period so the X clipboard is owned as soon as the
  first viewer connects, rather than 45s after the first connection. Ctrl+C /
  Ctrl+V work through the landing page — see *Viewer* above.
- **Viewport & fullscreen.** Use `https://browser.timblakely.com/` (see
  *Viewer* above) — it opens the viewer with `resize=scale` so the desktop
  tracks the window. Bare `/vnc.html` is the stock noVNC viewer with stock
  defaults and does *not* scale.

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
