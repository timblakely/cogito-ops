---
name: chezmoi-dotfiles
description: Use when editing dotfiles on a chezmoi-managed machine.
version: 1.0.0
author: hermes
license: MIT
metadata:
  hermes:
    tags: [chezmoi, dotfiles, git]
    related_skills: [terminal-paste-debugging]
---

# Chezmoi-managed dotfiles workflow

## When to Use

Any edit to a file under `$HOME` (shell/tmux/git/terminal configs, scripts) on a machine where chezmoi manages dotfiles.

Standing user rule: **any dotfile edit must land in chezmoi** (the user asks for it, and expects it unprompted). An edit that lives only in `~/` is an incomplete task.

## Procedure

1. **Before editing any file under `$HOME`, check management**: `chezmoi managed | grep -i <name>`. If managed, edit the *destination* file and converge, or edit the source directly — but never leave destination and source diverged.
2. **Edit the working file** with patch/write tools as normal, then converge source from it: `chezmoi add --force ~/.<file>`.
3. **Verify convergence**: `chezmoi diff ~/.<file>` must print nothing. The diff is source→dest: if it lists your new text with `-` lines, the source still has the old content (add didn't happen or hit the wrong path).
4. **Commit scoped to the touched file(s) only**: `git -C <source-path> commit -q -F <msgfile> -- <source-file>`. These repos commonly carry the user's long-running unrelated WIP (dirty `git status`); a bare `git commit -a` or broad add would sweep it in. The pathspec form of `git commit` works even with other staged/unstaged changes.

## Pitfalls

- Source files use chezmoi prefix conventions (`dot_tmux.conf`, `dot_bashrc.tmpl`) and may live in subdirs or be templates/scripts (`run_once_*.sh.tmpl`) — locate with `chezmoi source-path` + `git ls-files | grep -i <name>` or `find <src> -name '*<name>*'`, don't assume `<src>/<file>`.
- Multi-line commit messages: write the message to a scratch file and use `git commit -F <file>` — embedding newlines in inline `-m` strings inside Python-wrapped shell calls breaks quoting.
- Do NOT push unless asked; commit is the deliverable. Remind the user other machines need `chezmoi apply`/`chezmoi update` to pick it up.
- This user's repo: source-path `/home/tim/git/blakely-dotfiles`; commit style `vibe(<area>): <summary>` per `git log` — match existing history style.
