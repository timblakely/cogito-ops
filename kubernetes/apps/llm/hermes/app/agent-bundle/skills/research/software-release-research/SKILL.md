---
name: software-release-research
description: "Use when researching software releases."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Research, Releases, Changelogs, Provenance, Software]
    category: research
---

# Software Release Research

Research release changes from primary sources, connect them to the user's deployed artifact, and separate publisher-reported gains from locally verified results.

## Procedure

1. Identify the exact deployed component, version, image digest, model or package artifact, and configuration flags before researching updates. Read the local deployment manifest and nearby provenance records; do not infer the active profile from an old benchmark report.
2. Check the canonical release surface first: repository releases, tags, changelog, commit history, package registry, and container registry. If a releases page is missing or blocked, use the forge's public tag and commit APIs or raw files rather than treating the failure as evidence that no releases exist.
3. Establish the comparison range using immutable tags or revisions. Enumerate every release after the deployed version through the requested target, then inspect both tag commit messages and intervening feature commits; release tags often contain only a terse title while the useful notes are in preceding commits.
4. Group findings by user impact: breaking configuration changes, correctness and reliability fixes, new compatibility, performance or memory changes, observability, and tooling. Remove duplicate lower-level commits when a release note already summarizes the feature.
5. Validate runtime compatibility against the deployment manifest. Search every removed, renamed, or behavior-changing flag and check image architecture, model format, serving API, context limits, and quantization assumptions. Call out required edits separately from optional improvements.
6. Define a smoke-test matrix before rollout, including health/readiness, a deterministic arithmetic or short-generation request, structured output if used, and the exact tool-calling mode that previously mattered (for example, forced tool choice). Run it through the production alias as well as any direct runtime endpoint, and preserve HTTP status plus response-shape evidence rather than testing only pod readiness.
7. Verify registry facts independently from source facts: use the container registry for tag existence and digest, the source repository for code and release notes, and the model registry for model revisions and checksums. Never substitute an image release for a model release.
8. After rollout, query the runtime's metrics or stats endpoint and record per-device memory, cache utilization, in-flight state, evictions, and relevant throughput counters. Treat a full accelerator as intentional only when the configured headroom and allocator behavior explain the remaining capacity; distinguish idle-state observations from controlled benchmarks.
9. Report gains with provenance labels. Distinguish publisher benchmarks, repository tests, and measurements from the user's hardware; preserve workload, concurrency, precision, and configuration qualifiers, and do not project a gain onto an older artifact when the release notes used a different model or quantization recipe.
10. Update the durable benchmark or operations record after a successful upgrade: append a dated runtime-upgrade section, preserve historical measurements unchanged, state whether the model artifact changed, and mark superseded compatibility limitations with the verification evidence. Keep observational post-rollout numbers separate from the controlled baseline tables.
11. Deliver a **thematic** summary — the handful of things the project has actually been working on — followed by upgrade implications, blockers, and verification gaps. Group commits into effort areas and state the capability each one changes; keep SHAs, commit timestamps, and per-file attribution out of the body, offering them as an appendix only if the user asks for commit-level detail. Include exact versions, immutable revisions or digests where available, and source links for claims that may change.

## Pitfalls

- Read the active manifest before an old report: benchmark prose can describe a suspended profile while production has a different image, model, or flag set.
- Treat a tag API or commit history as a valid release-note source when the releases UI is unavailable: Forgejo/Gitea repositories commonly expose tags and commits even when the releases route returns 404.
- Inspect all commits between boundary tags, not only tag objects: maintainers may put the actual release notes in feature commits immediately before a small version-bump commit.
- Check every option the live deployment passes against the option definitions at BOTH boundary tags, and grep the range's new hard-error strings for option names: a renamed value or a newly added startup refusal fails at bring-up even when the model artifact is unchanged.
- Distinguish which version constant moved before declaring a deployed artifact incompatible: a plug-in/ABI bump is internal to the released binary and needs no reconversion, while a container/file-format version move does. Guessing either way costs the user either a pointless multi-GB reconversion or a boot failure.
- Prove a new feature cannot alter the deployed lane rather than assuming it is opt-in: read the config default, and for anything documented as auto-enabled when it pays, check whether the deployed model family's plug-in declares the gating probe — the same release can be a no-op for one lane and a behavior change for another.
- Exercise the compatibility behavior through the same production routing path clients use, not only a direct pod check: proxies can reject or transform tool-choice and structured-output requests.
- Read runtime stats after rollout before interpreting VRAM: allocator reservations, cache lending, host-pinned state, and workload state can make a nearly full card healthy rather than exhausted.
- Keep post-rollout observations out of historical benchmark tables unless the workload and configuration are controlled: a warm single-stream rate is useful evidence but not a comparable benchmark.
- Update the durable report after verification and preserve the old baseline: replacing historical prose erases the comparison needed to evaluate later upgrades.
- Keep runtime and model provenance separate: changing the container does not imply a new model or quantization, so do not apply a benchmark for a new artifact to an existing one.
- Label speed and memory figures as publisher claims unless reproduced on the target hardware: benchmark gains depend on model recipe, quantization, concurrency, and flags.
- Prefer immutable identifiers over floating tags: a tag can move, while a digest or commit revision makes the upgrade reproducible.
- Answer "what have the maintainers been working on since X" with themes, not commits: a per-commit or per-file list carrying timestamps is the shape the user rejects and re-asks about. Collapse the range into a few named workstreams, each with what it changes for a user.
- When a forge serves scrambled prose instead of commit history (anti-LLM poisoning — see `web/blocked-page-recovery`), do not summarize the garbage and do not report that no commits exist: the search-engine result description for the repo's own front page usually carries its rendered "latest commit per path" table, which yields commit subjects and dates without fetching the poisoned page.

## References

- See `references/release-source-fallbacks.md` for registry and forge API patterns, boundary-tag diffs, evidence classification, reading a forge that poisons scraper requests (git transport first), and the command-level compatibility audit for an image bump.
