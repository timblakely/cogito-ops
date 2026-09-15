#!/usr/bin/env python3
"""Vendored fix for vllm#51581: materialize dense DFlash K/V rows.

Supports the stock dense path, compressed-tensors W4/W8, and the out-of-tree
vLLM GGUF plugin's independently quantized/padded Q, K, and V shards.
"""
import io
import os
import py_compile
import sys
import tempfile

TARGET = os.environ.get(
    "VLLM_QWEN3_DFLASH_PATH",
    "/usr/local/lib/python3.12/dist-packages/vllm/model_executor/models/"
    "qwen3_dflash.py",
)
MARKER = "_dense_kv_rows"
BUG = "        kv_weights = [a.qkv_proj.weight[a.q_size :] for a in layers_attn]\n"
FIX = "        kv_weights = [_dense_kv_rows(a) for a in layers_attn]\n"
CLASS_ANCHOR = "@support_torch_compile\nclass DFlashQwen3Model"

HELPER = '''def _dense_kv_rows(attn: nn.Module) -> torch.Tensor:
    """Rows [q_size:] of the qkv projection as a dense bf16 matrix.

    club-3090 vendored fix for vllm#51581. GGUF merged QKV projections keep
    independently quantized shards in a padded tensor; dequantize K and V
    separately so dynamic Unsloth quants and TP=2 retain their real widths.
    For compressed-tensors W4A16/W8A16 this runs before the Marlin repack, so
    weight_packed/weight_scale remain in plain checkpoint layout.
    """
    qkv = attn.qkv_proj
    w = getattr(qkv, "weight", None)
    weight_type = getattr(qkv, "weight_type", None)
    if w is not None and weight_type is not None:
        import gguf
        from vllm_gguf_plugin import ops as gguf_ops

        def dequantize(shard: torch.Tensor, quant_type: int) -> torch.Tensor:
            if shard.dtype.is_floating_point:
                return shard.to(torch.bfloat16)
            block_size, type_size = gguf.GGML_QUANT_SIZES[int(quant_type)]
            logical_cols = int(shard.shape[1]) // type_size * block_size
            return gguf_ops.ggml_dequantize(
                shard.contiguous(), int(quant_type), int(shard.shape[0]),
                logical_cols, torch.bfloat16)

        offsets = getattr(w, "shard_offset_map", None)
        if offsets and "k" in offsets and "v" in offsets:
            dense = []
            fallback_type = int(weight_type.weight_type)
            for shard_id in ("k", "v"):
                start, end, packed_cols = offsets[shard_id]
                shard_type = int(weight_type.shard_weight_type.get(
                    shard_id, fallback_type))
                dense.append(dequantize(w[start:end, :packed_cols], shard_type))
            return torch.cat(dense, dim=0)
        return dequantize(w, int(weight_type.weight_type))[attn.q_size:]
    if w is not None and w.dim() == 2:
        return w[attn.q_size:]
    packed, scale = qkv.weight_packed, qkv.weight_scale
    out_f, in_f = int(packed.shape[0]), int(qkv.input_size)
    bits = 32 * packed.shape[1] // in_f
    from compressed_tensors.compressors.pack_quantized.base import unpack_from_int32
    q = unpack_from_int32(packed.data, bits, torch.Size([out_f, in_f]), packed_dim=1)
    group = in_f // scale.shape[1]
    dense = (q.to(torch.float32).reshape(out_f, in_f // group, group)
             * scale.to(torch.float32)[..., None]).reshape(out_f, in_f)
    out_dtype = scale.dtype if scale.dtype.is_floating_point else torch.bfloat16
    return dense.to(out_dtype)[attn.q_size:]


'''


def main() -> int:
    try:
        src = io.open(TARGET, encoding="utf-8").read()
    except OSError as exc:
        print(f"[51581] REFUSE: cannot read target: {exc}")
        return 1
    if MARKER in src:
        print("[51581] already patched (idempotent no-op)")
        return 0
    if src.count(BUG) != 1:
        print(f"[51581] REFUSE: anchor drift - expected exactly 1 fused-KV slice line, found {src.count(BUG)}")
        return 1
    if src.count(CLASS_ANCHOR) != 1:
        print(f"[51581] REFUSE: anchor drift - expected exactly 1 DFlashQwen3Model class anchor, found {src.count(CLASS_ANCHOR)}")
        return 1
    out = src.replace(CLASS_ANCHOR, HELPER + CLASS_ANCHOR).replace(BUG, FIX)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as handle:
        handle.write(out)
        temporary = handle.name
    try:
        py_compile.compile(temporary, doraise=True)
    except py_compile.PyCompileError as exc:
        print(f"[51581] REFUSE: patched file does not compile: {exc}")
        return 1
    io.open(TARGET, "w", encoding="utf-8").write(out)
    print("[51581] applied: DFlash fused-KV slice now handles dense, compressed-tensors, and GGUF qkv_proj")
    return 0


if __name__ == "__main__":
    sys.exit(main())
