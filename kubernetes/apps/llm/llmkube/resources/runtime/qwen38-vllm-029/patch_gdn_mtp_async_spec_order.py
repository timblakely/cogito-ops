#!/usr/bin/env python3
"""Order async input preparation after prior speculative-decode postprocessing."""
import io
import sys

TARGET = "/usr/local/lib/python3.12/dist-packages/vllm/v1/worker/gpu_model_runner.py"
MARKER = "club-3090 GDN+MTP async spec-order fix"
DEFINITION = "    def synchronize_input_prep(self):"
ANCHOR = "        self.prepare_inputs_event.synchronize()\n"
INSERT = """        # club-3090 GDN+MTP async spec-order fix. Wait for the
        # previous speculative postprocess before reused input buffers mutate.
        if self.num_accepted_tokens_event is not None:
            self.num_accepted_tokens_event.synchronize()
"""


def main() -> int:
    try:
        src = io.open(TARGET, encoding="utf-8").read()
    except OSError as exc:
        print(f"[gdn-async-order] REFUSE: cannot read target: {exc}")
        return 1
    if MARKER in src:
        print("[gdn-async-order] already patched (idempotent no-op)")
        return 0
    definition_offset = src.find(DEFINITION)
    if definition_offset < 0:
        print("[gdn-async-order] REFUSE: synchronize_input_prep not found")
        return 1
    anchor_offset = src.find(ANCHOR, definition_offset)
    if anchor_offset < 0:
        print("[gdn-async-order] REFUSE: prepare_inputs_event synchronize anchor not found")
        return 1
    insertion_offset = anchor_offset + len(ANCHOR)
    io.open(TARGET, "w", encoding="utf-8").write(
        src[:insertion_offset] + INSERT + src[insertion_offset:])
    print("[gdn-async-order] applied: input prep waits for speculative postprocess")
    return 0


if __name__ == "__main__":
    sys.exit(main())
