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
11. Deliver a concise chronological summary followed by upgrade implications, blockers, and verification gaps. Include exact versions, immutable revisions or digests where available, and source links for claims that may change.

## Pitfalls

- Read the active manifest before an old report: benchmark prose can describe a suspended profile while production has a different image, model, or flag set.
- Treat a tag API or commit history as a valid release-note source when the releases UI is unavailable: Forgejo/Gitea repositories commonly expose tags and commits even when the releases route returns 404.
- Inspect all commits between boundary tags, not only tag objects: maintainers may put the actual release notes in feature commits immediately before a small version-bump commit.
- Check removed options against the live command line before recommending an image bump: a runtime can fail at startup even when its model artifact is unchanged.
- Exercise the compatibility behavior through the same production routing path clients use, not only a direct pod check: proxies can reject or transform tool-choice and structured-output requests.
- Read runtime stats after rollout before interpreting VRAM: allocator reservations, cache lending, host-pinned state, and workload state can make a nearly full card healthy rather than exhausted.
- Keep post-rollout observations out of historical benchmark tables unless the workload and configuration are controlled: a warm single-stream rate is useful evidence but not a comparable benchmark.
- Update the durable report after verification and preserve the old baseline: replacing historical prose erases the comparison needed to evaluate later upgrades.
- Keep runtime and model provenance separate: changing the container does not imply a new model or quantization, so do not apply a benchmark for a new artifact to an existing one.
- Label speed and memory figures as publisher claims unless reproduced on the target hardware: benchmark gains depend on model recipe, quantization, concurrency, and flags.
- Prefer immutable identifiers over floating tags: a tag can move, while a digest or commit revision makes the upgrade reproducible.

## References

- See `references/release-source-fallbacks.md` for registry and forge API patterns, boundary-tag diffs, and evidence classification.
