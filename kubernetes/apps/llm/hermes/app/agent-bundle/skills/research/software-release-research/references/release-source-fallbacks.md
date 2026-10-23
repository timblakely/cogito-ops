# Release Source Fallbacks

## Source order

1. Repository release page or official changelog.
2. Repository tag list and tag metadata.
3. Commit API/history between the deployed and target tags.
4. Raw files at the target tag (`CHANGELOG`, `RELEASES`, `README`, or docs).
5. Container or package registry for published versions and digests.

A 404 from a releases page is a retrieval-path failure, not proof that the project has no releases. Record which fallback supplied each fact.

## Boundary comparison

Use immutable boundary tags and enumerate commits newest-first until the deployed tag is reached. Capture:

- version-bump commit messages;
- feature commits between version bumps;
- explicit benchmark numbers and their workload qualifiers;
- breaking flags, migration requirements, and compatibility notes.

Do not claim that every commit is a separate user-visible release. Collapse implementation commits into the feature they implement and retain the release's stated scope.

## Evidence classes

- `source`: release note, tag, commit, or project documentation;
- `registry`: published image/package tag and digest;
- `deployment`: local manifest, runtime arguments, or recorded verification artifact;
- `publisher benchmark`: numbers stated by the upstream project;
- `local measurement`: numbers reproduced on the user's hardware and configuration.

Only `local measurement` supports a claim about the user's deployment performance. A `publisher benchmark` can explain expected direction and prerequisites, but must keep its model, quantization, hardware, concurrency, and flags attached.

## Reading a forge that poisons scrapers

Some forges answer a detected AI agent with HTTP 200 and a body of deliberately
scrambled prose instead of the real page. Treat that as a retrieval-path failure
like a 404, never as the repository's content and never as proof the history is
empty.

Working substitute, in order:

1. **Git transport** — never poisoned for a forge repo (Codeberg/Gitea/Forgejo/
   GitHub), because the poisoning lives in the HTML rendering path. Clone into
   scratch and read the range locally: `git log --oneline vA..vB`,
   `git diff --stat vA..vB`, `git diff --name-status --diff-filter=A vA..vB`,
   `git show vB:<file>`, `git tag`. This yields the complete range and per-file
   diffs that no scraped page can, and is the only route that supports a
   compatibility audit. Prefer it the moment a tags/compare/raw page looks wrong.
2. **Search-engine description of the front page** — only when cloning is
   impossible. It typically includes the "Repository files (latest commit first)"
   table: one row per path with that path's latest commit subject and date. Search
   the repo URL or a known commit SHA and read the result `description` field;
   repeating with different anchors accumulates coverage of the post-tag range.

When route 2 supplies the answer, state that the commit set came from the forge's
indexed file list rather than a full commit-log read, so the user knows the range
may be partial.

## Compatibility audit before an image bump

Run against the live deployment's arguments, not the release notes.

1. **Option surface.** Diff the file that defines CLI options between the boundary
   tags (`git diff vA..vB -- <config/options file>`), then grep the removed and
   changed lines. For every option the running lane passes, confirm at the target
   tag that its name, default, and accepted values are unchanged
   (`git grep -n <option-name> vB`). Also confirm no *default value* changed under
   a flag the lane passes silently.
2. **Artifact format vs. plug-in ABI.** `git diff vA..vB -- <abi dir> <format dir>
   | grep -E '^[+-].*(VERSION|MAGIC)'`. A plug-in/ABI constant moving is internal
   to the shipped binary; only a container/serialized-format version move means
   the user must reconvert a multi-GB artifact. Check which one moved.
3. **New startup refusals.** Grep the added error strings for option names and
   resource conditions (`grep -oE` on added lines matching the project's
   error/log macro). Each is a configuration that used to boot and now exits during
   bring-up — say which deployed lanes match the condition.
4. **New-feature defaults and auto-enable gates.** Read the config struct's
   default for each new feature (a documented `off`/`disabled` default means no
   behavior change), then, for features that switch themselves on when they pay,
   grep the arch/model plug-ins for the probe that gates them to see whether the
   deployed model family is affected at all.
5. **Served HTTP surface.** Grep the range for new route registrations and read
   their auth gating; a new admin/mutation endpoint gated only on loopback is
   reachable from every pod on a flat cluster network when the lane has no API key.
6. **Registry facts, independently of source facts.** Tag existence, per-architecture
   digest, and pullability from the registry API — never inferred from the repo.

Still compare: model revision/checksum, accelerator architecture and peer-to-peer
assumptions, serving API behavior and tool-calling modes, context/KV/speculative
decoding settings, and whether the benchmarked recipe matches the deployed artifact.
