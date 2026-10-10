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

## Compatibility checklist

Before recommending an upgrade, compare:

- image tag and digest;
- model format, model revision, and model checksum;
- accelerator architecture and peer-to-peer assumptions;
- removed or renamed CLI flags;
- serving API behavior and tool-calling modes;
- context, KV-cache, speculative-decoding, and memory settings;
- whether the benchmarked model recipe matches the deployed artifact.
