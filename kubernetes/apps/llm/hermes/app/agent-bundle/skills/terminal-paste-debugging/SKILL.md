---
name: terminal-paste-debugging
description: Use when paste fails in tmux/screen inside a terminal TUI.
version: 1.0.0
author: hermes
license: MIT
metadata:
  hermes:
    tags: [tmux, terminal, paste, debugging]
    related_skills: [chezmoi-dotfiles]
---

# Debugging terminal paste/input issues (multiplexer layers)

## When to Use

Paste or keystrokes work in the terminal app directly but fail inside tmux/screen running a TUI (Hermes, editors, REPLs), or a pane appears to swallow all input.

Symptom class: paste or keystrokes work in terminal-app-direct but fail inside tmux/screen running a TUI (Hermes, editors, REPLs). The TUI is usually innocent — something in the layer chain swallows input. Debug layer by layer, terminal → multiplexer → app; never start by blaming the app's paste handling.

## Procedure

1. **Confirm you are actually inside the multiplexer**: the agent's own shell may run outside the user's tmux. Check `$TMUX`, and probe the live server: `tmux ls`, `tmux list-panes -a -F '#{pane_id} #{window_name} MODE=#{pane_in_mode}'`. `pane_in_mode != 0` = pane is in copy-mode = **every keystroke is consumed as copy-mode navigation**, including pastes. This single check often IS the diagnosis.
2. **Rule out clipboard plumbing** (terminal→OS): on Wayland `wl-paste`/`wl-copy` vs X11 `xclip`/`xsel` mismatches silently break copy helpers. `command -v` the helper referenced in tmux/screen copy bindings — a binding piping to a missing binary fails silently AND can leave the pane stuck.
3. **Read the configs with fresh eyes, not defaults assumptions**: `~/.tmux.conf`, terminal config (`~/.config/ghostty/config` etc.). Look specifically for: `copy-pipe-no-clear` (never exits copy-mode — a paste-swallowing trap), `set-clipboard`, `assume-paste-time` (1 disables paste-burst protection so control chars inside pastes, e.g. a remapped prefix like `C-z`, fire multiplexer commands), prefix remaps onto keys pastes may contain.
4. **Prove the app-side path end-to-end before patching anything** — inject a bracketed paste through the real chain into a live pane:
   `printf 'PASTEPROBE-42' | tmux load-buffer -; tmux paste-buffer -p -t <pane>`
   then `tmux capture-pane -p -t <pane> -S -4 | grep PASTEPROBE` (paste-buffer sends bracketed-paste sequences, so this exercises the exact path a terminal paste takes). Clear with `tmux send-keys -t <pane> C-u`. If the probe lands, the app is fine and the bug is upstream input interception.
5. **Fix + converge**: patch the config, reload live (`tmux source-file ~/.tmux.conf`), kick stuck panes out of modes (send `q`), and verify `pane_in_mode=0` everywhere. Then check dotfile management (see chezmoi-dotfiles skill) and clean up any probe sessions/windows you created.

## Pitfalls

- Check `pane_in_mode` FIRST — it is invisible to the user and explains 'keys do nothing in exactly one pane' instantly; anything else you test first is wasted time.
- Terminal-app mouse default + tmux `mouse on` means drag-select enters tmux copy-mode, not the terminal's own selection; any copy binding using `copy-pipe-no-clear` strands the pane there. Prefer `copy-pipe-and-clear <helper>` so release restores input.
- On Wayland there is no X primary selection — bindings that pipe to `xclip -selection primary` are doubly dead (no xclip, no primary). tmux's own buffer + OSC52 (`set-clipboard external`) is the working middle-click/clipboard path.
- Do not claim 'the app can't receive pastes' without running the load-buffer/paste-buffer probe against a live pane; the probe result is the fact, config reading alone is not.
