#!/usr/bin/env python3
"""Preserve an external DFlash2 draft architecture beside a GGUF target.

vLLM copies the target's config_format into an external speculative model.  A
GGUF target therefore sends the ordinary HF DFlash2 directory through the
out-of-tree GGUF config parser.  That parser intentionally maps base HF model
types to GGUF adapter architectures, but doing so here replaces the explicit
``DFlash2DraftModel`` architecture with generic ``Qwen3ForCausalLM``.  vLLM's
DFlash wrapper then turns that into the unsupported
``DFlashQwen3ForCausalLM`` architecture.

Return the untouched HF config only for an explicitly declared DFlash2 draft.
The GGUF target and every other adapter mapping keep the plugin's stock path.
The edit is anchor-checked and idempotent so a future plugin change fails
closed instead of silently applying to the wrong source.
"""

import io
import py_compile
import sys
import tempfile


TARGET = "/usr/local/lib/python3.12/dist-packages/vllm_gguf_plugin/config_parser.py"
MARKER = "# cogito: preserve an external DFlash2 architecture beside a GGUF target"
ANCHOR = '        if config.model_type == "qwen3_moe" and "norm_topk_prob" not in config_dict:\n'
INSERT = '''        # cogito: preserve an external DFlash2 architecture beside a GGUF target
        if "DFlash2DraftModel" in (getattr(config, "architectures", None) or []):
            return config_dict, config

'''


def main() -> int:
    try:
        source = io.open(TARGET, encoding="utf-8").read()
    except OSError as error:
        print(f"[gguf-dflash2] REFUSE: cannot read target: {error}")
        return 1

    if MARKER in source:
        print("[gguf-dflash2] already patched (idempotent no-op)")
        return 0
    if source.count(ANCHOR) != 1:
        print(
            "[gguf-dflash2] REFUSE: anchor drift - expected exactly one "
            f"Qwen3 MoE normalization block, found {source.count(ANCHOR)}"
        )
        return 1

    patched = source.replace(ANCHOR, INSERT + ANCHOR)
    with tempfile.NamedTemporaryFile(
        "w", suffix=".py", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(patched)
        temporary = handle.name
    try:
        py_compile.compile(temporary, doraise=True)
    except py_compile.PyCompileError as error:
        print(f"[gguf-dflash2] REFUSE: patched file does not compile: {error}")
        return 1

    io.open(TARGET, "w", encoding="utf-8").write(patched)
    print("[gguf-dflash2] applied: external DFlash2 architecture remains HF-parsed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
