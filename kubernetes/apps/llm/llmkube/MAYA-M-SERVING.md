# Maya-M serving integration

Verified 2026-11-16. Historical preparation is recorded in [MAYA-M-TRIAL.md](MAYA-M-TRIAL.md).

## Runtime

- InferenceService/Service: `llm/maya-m`, internal OpenAI API at
  `http://maya-m.llm.svc.cluster.local:8080/v1`.
- Public LiteLLM alias: `Maya-M`; upstream served ID: `glm-5.3-flash`.
- Image: `registry.timblakely.com/timblakely/maya-m@sha256:5e82c10d8b7e042f40eac275fcf9ced54f583faacbc63c0ed352b764ab06763c`.
- Maya 1.1.64, source `d93d1499021b98a39bede20d33368907f1ea4ad8`.
- Placement: Iggy, both RTX 3090s, NVIDIA RuntimeClass, low priority.
  CPU request 20; RAM request/limit 112Gi; retained config uses a 90Gi RAM tier.
- Context: 262144 tokens, one parallel slot, verified by the
  [long-context pilot](MAYA-M-262K-BENCHMARK.md). Prompt, generation and the
  native 8-token admission margin share this window. LiteLLM advertises an
  8192-token output ceiling, not an additional context window.
- `COGITO_MAYA_CONTEXT_SIZE` changes only the writable runtime config copy;
  the original retained setup config remains untouched. Normal prefix caching
  is enabled; `MAYA_GLM_NO_REUSE=1` was used only for cold benchmarks.
- Weights, pack, vision assets and upstream config remain on `maya-m-iggy`.
  The image seed populates a nested ephemeral workspace at its original absolute
  path; a separate retained `data` mount preserves expert calibration profiles.
  `prepare.py` never overwrites that mount or the original setup config.
- Startup installs/downloads nothing. It verifies the seeded runtime and invokes
  upstream `setup.sh` with a writable config copy, update checks disabled and
  `--host 0.0.0.0 --port 8080`.
- Health probes require JSON `status=ok` and `unloaded=false`. HTTP 200 alone
  is not a loaded-model guarantee on this server.
- `maya-m-ingress` allows native-server traffic only from LiteLLM Pods in the
  same namespace. The unauthenticated dashboard/model-management surface is not
  exposed through an HTTPRoute. A non-proxy Pod's request timed out while the
  LiteLLM path remained reachable.

## LiteLLM and Paseo

The explicit Hermes virtual-key scope includes `Maya-M`; the already-issued
key's database scope was updated and read back through LiteLLM's admin API.
All pre-existing aliases and scopes were preserved. Other Iggy model lanes
remain suspended; do not resume one while Maya holds both GPUs.

Paseo's supported catalogue synchronizer was applied without restarting its
running daemon. Both persisted configuration and the live provider catalogue
contain `custom:litellm-chat:Maya-M` with `none`, `low`, `high`, `max` choices.
The synchronization timer remains enabled and its service completed successfully.

These are GLM's canonical template controls. Upstream maps `medium` to `high`
and `xhigh` to `max`; they are not additional distinct choices. The alias does
not pin an effort and overwrite the client's selection. No quantitative
reasoning-budget/quality difference between levels is claimed.

## Verification

Using the actual Hermes virtual key through LiteLLM, not the admin key:

- Nonstreaming chat returned `MAYA_OK` with thinking disabled.
- SSE completed with `[DONE]`, visible content, separate reasoning and usage.
- Forced function calls parsed as valid JSON; a tool-result round trip completed.
- Streamed function-call fragments reconstructed a valid indexed `echo` call.
- `low` and `max` were separately accepted; `none` and `high` exercised the main
  chat/SSE probes.
- A 640x480 red image was identified as red and added 393 prompt tokens compared
  with an identical text-only baseline, proving ingestion rather than guessing.
- Native API checks passed before registration as well. The deployed Pod runs
  the exact registry digest with zero restarts at verification.
- Catalogue self-test: 17 public model names, 6 virtual keys, 9 backends.
  Targeted Flux parity: 6 tests passed. Runtime seed regression test passed.

The integration checks do not benchmark sustained concurrency. The separate
[262144-token pilot](MAYA-M-262K-BENCHMARK.md) records long-context throughput
and a three-depth retrieval test, not a general accuracy guarantee.
The old manual trial Pod remains historical; no four-hour deadline applies to
this persistent InferenceService. Image-build cache/backup details are in
[the image recipe](resources/manual/maya-m/image/README.md).
