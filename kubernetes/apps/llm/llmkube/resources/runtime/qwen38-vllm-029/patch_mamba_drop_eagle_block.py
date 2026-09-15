#!/usr/bin/env python3
"""Vendored vllm#48375: honor drop_eagle_block in MambaManager cache hits."""
import io
import sys

TARGET = "/usr/local/lib/python3.12/dist-packages/vllm/v1/core/single_type_kv_cache_manager.py"
MARKER = "drop_eagle_block and max_num_blocks > 0"
ANCHOR = "        max_num_blocks = max_length // block_size\n"
INSERT = """        if drop_eagle_block and max_num_blocks > 0:
            # club-3090 vendored vllm#48375. Drop the final matched page: its
            # recurrent-state snapshot may reflect rejected draft tokens.
            max_num_blocks -= 1
"""


def main() -> int:
    try:
        src = io.open(TARGET, encoding="utf-8").read()
    except OSError as exc:
        print(f"[pr48375] REFUSE: cannot read target: {exc}")
        return 1
    if MARKER in src:
        print("[pr48375] already patched (idempotent no-op)")
        return 0
    class_offset = src.find("class MambaManager")
    if class_offset < 0:
        print("[pr48375] REFUSE: anchor drift - class MambaManager not found")
        return 1
    anchor_offset = src.find(ANCHOR, class_offset)
    if anchor_offset < 0:
        print("[pr48375] REFUSE: anchor drift - max_num_blocks line not found in MambaManager")
        return 1
    insertion_offset = anchor_offset + len(ANCHOR)
    io.open(TARGET, "w", encoding="utf-8").write(
        src[:insertion_offset] + INSERT + src[insertion_offset:])
    print("[pr48375] applied: MambaManager now honors drop_eagle_block")
    return 0


if __name__ == "__main__":
    sys.exit(main())
