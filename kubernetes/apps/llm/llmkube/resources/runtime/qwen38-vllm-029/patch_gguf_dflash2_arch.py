#!/usr/bin/env python3
"""Keep an external HF DFlash2 draft independent of a GGUF target.

vLLM copies the target's config_format into an external speculative model.  A
GGUF target therefore sends the ordinary HF DFlash2 directory through the
out-of-tree GGUF config parser.  That parser intentionally maps base HF model
types to GGUF adapter architectures, but doing so here replaces the explicit
``DFlash2DraftModel`` architecture with generic ``Qwen3ForCausalLM``.  vLLM's
DFlash wrapper then turns that into the unsupported
``DFlashQwen3ForCausalLM`` architecture.

Return the untouched HF config only for an explicitly declared DFlash2 draft,
then make DFlash honor vLLM's existing ``draft_load_config`` field instead of
always reusing the target loader.  The active profile sets that loader to
``auto``.  The GGUF target and every other adapter mapping keep the plugin's
stock path.  Both edits are anchor-checked and idempotent so a future source
change fails closed instead of silently applying to the wrong code.
"""

import io
import py_compile
import sys
import tempfile


CONFIG_TARGET = "/usr/local/lib/python3.12/dist-packages/vllm_gguf_plugin/config_parser.py"
CONFIG_MARKER = "# cogito: preserve an external DFlash2 architecture beside a GGUF target"
CONFIG_ANCHOR = '        if config.model_type == "qwen3_moe" and "norm_topk_prob" not in config_dict:\n'
CONFIG_INSERT = '''        # cogito: preserve an external DFlash2 architecture beside a GGUF target
        if "DFlash2DraftModel" in (getattr(config, "architectures", None) or []):
            return config_dict, config

'''

DFLASH_TARGET = (
    "/usr/local/lib/python3.12/dist-packages/vllm/v1/worker/gpu/"
    "spec_decode/dflash/utils.py"
)
DFLASH_MARKER = "# cogito: honor the explicit loader for an external DFlash draft"
DFLASH_ANCHOR = '''    draft_vllm_config = replace(
        vllm_config,
        attention_config=replace(
'''
DFLASH_REPLACEMENT = '''    draft_vllm_config = replace(
        vllm_config,
        # cogito: honor the explicit loader for an external DFlash draft
        load_config=(
            speculative_config.draft_load_config or vllm_config.load_config
        ),
        attention_config=replace(
'''


def prepare_patch(
    target: str, marker: str, anchor: str, replacement: str
) -> tuple[str, bool]:
    try:
        source = io.open(target, encoding="utf-8").read()
    except OSError as error:
        raise RuntimeError(f"cannot read {target}: {error}") from error
    if marker in source:
        return source, False
    if source.count(anchor) != 1:
        raise RuntimeError(
            f"anchor drift in {target}: expected exactly one anchor, "
            f"found {source.count(anchor)}"
        )
    return source.replace(anchor, replacement), True


def verify_compile(source: str) -> None:
    with tempfile.NamedTemporaryFile(
        "w", suffix=".py", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(source)
        temporary = handle.name
    py_compile.compile(temporary, doraise=True)


def main() -> int:
    try:
        config_source, config_changed = prepare_patch(
            CONFIG_TARGET,
            CONFIG_MARKER,
            CONFIG_ANCHOR,
            CONFIG_INSERT + CONFIG_ANCHOR,
        )
        dflash_source, dflash_changed = prepare_patch(
            DFLASH_TARGET,
            DFLASH_MARKER,
            DFLASH_ANCHOR,
            DFLASH_REPLACEMENT,
        )
        verify_compile(config_source)
        verify_compile(dflash_source)
    except (RuntimeError, py_compile.PyCompileError) as error:
        print(f"[gguf-dflash2] REFUSE: {error}")
        return 1

    if config_changed:
        io.open(CONFIG_TARGET, "w", encoding="utf-8").write(config_source)
    if dflash_changed:
        io.open(DFLASH_TARGET, "w", encoding="utf-8").write(dflash_source)
    if not config_changed and not dflash_changed:
        print("[gguf-dflash2] already patched (idempotent no-op)")
    else:
        print(
            "[gguf-dflash2] applied: external DFlash2 config and loader remain HF"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
