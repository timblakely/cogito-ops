# Matrix coordinator

This service owns deterministic plan and delivery state between Matrix, GitHub,
and Argo Workflows. Matrix decryption is delegated to the maubot plugin; the
coordinator receives authenticated normalized events. Harnesses implement the
versioned JSON contract in `schema/` and never own workflow state.

The package intentionally uses the Python standard library. This keeps its
runtime image small and makes replay, policy, and adapter tests independent of
network services.

Run the local checks from this directory:

```sh
python -m unittest discover -s tests -v
python tests/conformance.py adapters/contract-adapter
python tests/conformance.py adapters/pi-adapter
python tests/conformance.py adapters/opencode-adapter
```

The Pi and OpenCode conformance tests substitute a fixture executable for the
real harness. Production provides `PI_COMMAND` or `OPENCODE_COMMAND` and a
role-scoped LiteLLM credential. Adapter input is JSON on stdin and output is one
JSON result on stdout; prompt content is never evaluated as shell code.
