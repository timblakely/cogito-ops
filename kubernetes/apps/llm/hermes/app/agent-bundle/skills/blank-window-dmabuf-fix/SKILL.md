---
name: blank-window-dmabuf-fix
description: "Use when app windows render blank on Wayland/XWayland."
---
# Diagnosing blank/white app windows under Wayland/XWayland

Use when a GUI app (Electron, GTK, Qt, AppImage slicers like BambuStudio) launches, spams console errors, and its windows render blank/white/black.

## Signature errors
- `Failed to create GBM buffer of size WxH: Invalid argument` — WebKitGTK/GTK dmabuf renderer failing over XWayland (typical on NVIDIA or hybrid iGPU+dGPU laptops).
- `Invalid MIT-MAGIC-COOKIE-1 key` / `Authorization required, but no authorization protocol specified` — shell lacks `DISPLAY`+`XAUTHORITY` of the desktop session; grab them from a GUI process environ: `tr '\0' '\n' < /proc/$(pgrep -x plasmashell | head -1)/environ | grep -E '^(DISPLAY|XAUTHORITY|WAYLAND_DISPLAY)='`.
- `qt.qpa.plugin: Could not find the Qt platform plugin "wayland"` — app bundles Qt without wayland plugin; it falls back to X11/XWayland, where the GBM failure then bites.
- `Gtk-CRITICAL gtk_window_resize: assertion ... failed` — harmless BambuStudio/GTK noise; not the cause.

## Fix
`WEBKIT_DISABLE_DMABUF_RENDERER=1` (optionally plus `WEBKIT_DISABLE_COMPOSITING_MODE=1`) before the binary. Persist by prefixing `env WEBKIT_DISABLE_DMABUF_RENDERER=1` in the app's `.desktop` Exec= line (AppImageLauncher entries live in ~/.local/share/applications/appimagekit_*-App.desktop; they get regenerated if the AppImage is re-registered).

## Verify without vision (vision backend may be down)
1. Run app in background with env fix; wait ~15s.
2. List mapped windows: `xprop -root _NET_CLIENT_LIST`, then `xprop -id 0xWIN WM_CLASS WM_NAME`.
3. Capture each window: `magick import -window 0xWIN out.png`, then color histogram: `magick out.png -depth 8 txt:- | tail -n +2 | awk '{print $3}' | sort | uniq -c | sort -rn | head`. A uniform single color = blank; many distinct colors + brand accent colors = rendering fine.

## Gotchas
- Root-window screenshot under KWin Wayland: `spectacle -b -n -o file.png` (`import -window root` may fail via the IMv7 `import` shim).
- An unknown-option usage dump + exit 0 means binary + FUSE mount are fine — problem is rendering, not packaging.
