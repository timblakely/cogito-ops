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
  with a single fixed `-screen 0 <VNC_RESOLUTION>x24` mode, and x11vnc 0.9.16
  does not implement client-initiated `SetDesktopSize`. Both halves would have
  to change to get it, so client-side scaling is the fix. Scaling preserves the
  aspect ratio, which is why the desktop is 16:9 - see *Window size* below.

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

### Checking whether the bridge is actually live

In the viewer, open devtools and select the `vnc.html` frame:

```js
window.__cogitoBridge
// {loaded: true, rfbSeen: true, caps: 0, ctrlV: 0, pasteEvents: 0, ...}
```

That object is the *only* trustworthy signal. The presence of the injected
`<script id="clipboard-bridge">` tag proves nothing, and this is not a
hypothetical: the first version of the injector appended the script while the
iframe still held its initial `about:blank` document, so the fetch was aborted
(`net::ERR_ABORTED`) the moment `vnc.html` committed — leaving a script tag that
looked perfectly correct in the final document but had never executed, and no
console error. The symptom was stock noVNC behaviour: CapsLock did nothing and
Ctrl+V pasted the *remote* clipboard.

The injector therefore retries on a 250 ms timer until `__cogitoBridge` appears,
waits for the iframe document to actually be `vnc.html`, discards any stale tag,
and cache-busts the script URL so a module-map entry poisoned by an aborted
fetch is not handed back. It logs `[cogito] clipboard bridge never started` if
it gives up after ~20 s.

The counters are useful on their own: `caps` incrementing means CapsLock is
being intercepted; `ctrlV` with `pasteEvents` also incrementing means the native
paste path is working; `readTextFallbacks` climbing instead means the browser
did not fire a paste event and the async clipboard API is doing the work.

## Window size

The desktop is `2560x1440` (`VNC_RESOLUTION`) and the browser window is pinned
to fill it exactly. That pinning is not optional decoration: without it the
window occupies an arbitrary fraction of the desktop and the rest shows as
black bands, with no window manager in the image to maximise anything.

**Camoufox randomises the window size on purpose.** It is an anti-detect
browser: camoufox-js generates a fingerprint whose window dimensions are a
random draw bounded by the real screen. Observed on this display across
launches: 1237x1108, 1536x796, 1989x1294. So there is no fixed number to
match - the size has to be pinned at launch.

Two other approaches were measured and rejected before landing on that:

- **Resizing the X window** (`XConfigureWindow` on the `Navigator` toplevel)
  works at the X level - the toplevel and its child window both resize - but
  Firefox keeps rendering at its original size even after a full page
  navigation, so the visible desktop does not change.
- **Widening Playwright's context viewport** (server.js hardcodes
  `{width: 1280, height: 720}`) does change the page size that
  `page.screenshot()` reports, but the visible window follows Camoufox's
  fingerprint rather than the viewport: with the viewport set to 2491x1226 the
  window still rendered at 1237x1108.

What actually controls it is `window.outerWidth`/`outerHeight` in the Camoufox
config, which camoufox-js passes to the Firefox process as `CAMOU_CONFIG_<n>`
environment chunks. camofox does not expose camoufox-js's `window` launch
option, so the `camofox-window` ConfigMap mounts a Node preload
(`NODE_OPTIONS=--require`) that rewrites those chunks at playwright-core's
`BrowserType.prototype.launch` - a CommonJS module, unlike camoufox-js's frozen
ESM exports, and the last point at which the environment can still be changed.
It sets the window to `VNC_RESOLUTION` at 0,0 and raises `screen.*` to match,
so the fingerprint stays self-consistent: a window exactly filling its screen
is an ordinary maximised browser, whereas a window larger than its screen is
not.

To change the desktop size, change `VNC_RESOLUTION` alone - the preload reads
it back and the window follows. Keep it 16:9 unless you want the viewer to
letterbox, and note x11vnc costs only ~8m CPU even at 2560x1440, so a larger
framebuffer is close to free. Confirm a change with:

```bash
kubectl -n llm logs deploy/camofox -c app | grep window-patch
# [window-patch] browser window 1536x796 -> 2560x1440 at 0,0
kubectl -n llm exec deploy/camofox -c app -- \
    sh -c 'DISPLAY=:99 xwininfo -root -tree | grep -i navigator'
```

## Shared identity: the VNC desktop and the agent are one browser

camofox keys sessions by `userId` **alone** - `sessionKey` is not part of the
map key (`sessions.get(normalizeUserId(userId))`). Everything that passes the
same `userId` therefore shares one *live* browser context: the same cookies, in
memory, right now. No export/import round trip is involved.

That is what makes the VNC desktop useful: log into a site by hand in the
window, and the agent is already in that session. It only works if both sides
use the same `userId`, which here is **`tim`**, set in two places that must not
drift apart:

| Side | Where |
| --- | --- |
| Interactive VNC window | `vnc-tab-seeder` in `app/helmrelease.yaml` |
| pi.dev agent | `camofox.userId` in `~/.pi/agent/settings.json` |

**The failure this fixes.** The pi.dev `camofox-browser` extension resolves its
identity as:

```ts
return envId || configId || "pi_" + randomUUID().replace(/-/g, "").slice(0, 10);
```

With `camofox.userId` unset, every agent run invented a *new random* userId, so
it got a brand-new empty profile and saw the login screen no matter how many
times a human had logged in at the VNC desktop. It also explains the ~86
accumulated `profiles/` directories, most of them 36-byte empty states. Setting
`camofox.userId` is what makes the identity stable; `CAMOFOX_USER_ID` still
overrides it per run if a throwaway identity is ever wanted.

Verified end to end: typing a URL in the VNC window that set a cookie, then
reading it back through the agent's own API path
(`POST /tabs` + `GET /tabs/<id>/snapshot` as `userId=tim`), returned
`{"cookies": {"vncProof": "shared"}}`.

### Logging into a site

1. Open `https://browser.timblakely.com/` and log in in the desktop, handling
   MFA and CAPTCHAs as usual. The window you see belongs to session `tim`.
2. That is already enough for the agent while the session lives. To make it
   survive a pod restart, close the session once so the state is checkpointed:

    ```bash
    curl -s -X DELETE https://camofox.timblakely.com/sessions/tim
    ```

   The seeder recreates the window within ~15s and the new session restores the
   persisted state.

**Persistence is checkpoint-based, and the checkpoints are on a timer.** The
storage state has always lived on Ceph - `/root/.camofox` is `/dev/rbd0`, the
`camofox` PVC (5Gi RWO `ceph-block`, hourly kopiur snapshots). What was missing
was *when* it got written: the persistence plugin checkpoints only on session
close, cookie import, and server shutdown, so a login left open survived a
graceful termination but not an OOM kill or node crash.

The `state-checkpointer` sidecar closes that window by POSTing an empty cookie
array to `/sessions/tim/cookies` every 5 minutes. `addCookies([])` adds nothing
but still emits `session:cookies:import`, one of the plugin's checkpoint
triggers - a no-op write whose only effect is flushing the live cookie jar to
Ceph. Confirm it with:

```bash
kubectl -n llm logs deploy/camofox -c app | grep "storage state persisted"
# ... "reason":"cookie_import" ... every ~5 minutes
```

Note this cannot be solved by moving a mount. Firefox does write cookies
continuously, but to `/tmp/playwright_firefoxdev_profile-<random>/cookies.sqlite`
on the container overlay, and Playwright creates a fresh randomly-named profile
per launch and deletes it on close - so putting the PVC there would gain
nothing. Making the *live* profile persistent means `launchPersistentContext`,
which is one profile per browser process; camofox is one browser with N
contexts keyed by userId, so that would be one Firefox per identity.

Profiles live at `profiles/<first 32 hex of sha256(userId)>/storage-state.json`
on the `camofox` PVC. For `tim` that is
`c0d19e4483571ff07cb01a4d3f548410`. There is no index mapping hashes back to
names; recover one with
`python3 -c 'import hashlib;print(hashlib.sha256(b"tim").hexdigest()[:32])'`.

**Only one window should normally be open.** Without a window manager, and with
every window pinned to fill the screen (see *Window size*), two sessions
produce two identical full-screen windows stacked on top of each other with no
way to tell which one has focus - so a login can silently land in the wrong
session. `curl -s https://camofox.timblakely.com/health` reporting
`activeSessions: 1` is the check.

Notes:

- **Black desktop.** With no session/tab the X desktop has no browser window
  and renders black, which is indistinguishable from a failed connection in
  the viewer. The `vnc-tab-seeder` container keeps a `tim` tab open
  whenever `activeTabs` drops to 0, so the desktop should always show
  *something*. If it is still black, check that the seeder is running
  (`kubectl logs -n llm deploy/camofox -c vnc-tab-seeder`) and that
  `curl -s https://camofox.timblakely.com/health` reports `activeTabs >= 1`.
- `MAX_SESSIONS=11` — ten slots plus the one permanently held by the seeder's
  `tim` session.
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
  defaults and does *not* scale. The browser window fills the desktop; see
  *Window size* above if black bands ever reappear.

## API authentication

The API is gated by a bearer token. camofox has two independent gates and they
are not interchangeable:

| Env var | Covers | Accepts |
| --- | --- | --- |
| `CAMOFOX_ACCESS_KEY` | every route except `/health` and cookie import | only the access key |
| `CAMOFOX_API_KEY` | cookie import, `/sessions/:userId/storage_state` | access key **or** API key |

Both are projected from a single value in the 1Password item `camofox`
(Kubernetes vault, field `CAMOFOX_ACCESS_KEY`) via `app/externalsecret.yaml`,
so one bearer token satisfies every endpoint. `CAMOFOX_API_KEY` alone is not
enough to secure the service - it leaves `POST /tabs` open, which is full
browser control.

Clients that must carry the token:

- the pi.dev extension — `camofox.apiKey` in `~/.pi/agent/settings.json`
- `vnc-tab-seeder` and `state-checkpointer` — from the same Secret

In manifests the header is written `$${CAMOFOX_ACCESS_KEY}`. The `$$` is the
Flux escape: this Kustomization runs `postBuild.substituteFrom`, and a bare
`$VAR` would be substituted away to an empty string before the container ever
sees it.

This matters more than it did when the browser was disposable: a persistent
logged-in session now lives behind this API, so an unauthenticated
`GET /sessions/tim/storage_state` would hand over live session cookies.

### Still open: the VNC desktop itself

`browser.timblakely.com` is **not** covered by any of the above. It is
websockify on port 6080, a separate process from the Express API, so the bearer
token does not apply to it — anyone on the LAN who can resolve that name can
drive the logged-in browser. Two ways to close it, neither done yet:

- **OIDC at the gateway** (preferred, and the pattern already used by eight
  apps here). The stock `components/kustomize/pocket-id` component cannot be
  dropped in as-is: its SecurityPolicy targets the HTTPRoute named `${APP}`,
  which is the *API* route, and the API must stay bearer-token because the
  agent cannot complete an interactive OIDC flow. It needs a SecurityPolicy
  targeting the `vnc` route specifically, plus its own pocket-id client and
  redirect URL.
- **`VNC_PASSWORD`** (supported by the VNC plugin, wired to `x11vnc -rfbauth`).
  Much weaker: the VNC auth scheme truncates passwords to 8 characters.

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
