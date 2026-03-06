## SVN Settings

- Ensure that all SVN commands are done with jujutsu (`jj`) and not git directly. 
- Again, DO NOT USE GIT COMMANDS; use only `jj`
- Whenever you commit something to jj, instead of the prefix`fix(talos):` or `chore:`, use `vibe($THING):` instead
  - As in if you're fixing Immich, use `vibe(immich):`
    - If you're fixing Talos use `vibe(talos):`
    - If you're fixing justfiles use `vibe(justfiles):`
  - This way I'll know which changes are agent-generated

## Testing 

- Test k8s/flux changes with flux-local before committing
