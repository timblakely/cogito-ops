#!/usr/bin/env python3
"""Vendored fix for vllm#51581: dequantize qkv_proj before DFlash fused-KV slicing."""
import io
import py_compile
import sys
import tempfile

TARGET = ("/usr/local/lib/python3.12/dist-packages/vllm/model_executor/models/"
          "qwen3_dflash.py")
MARKER = "_dense_kv_rows"
BUG = "        kv_weights = [a.qkv_proj.weight[a.q_size :] for a in layers_attn]\n"
FIX = "        kv_weights = [_dense_kv_rows(a) for a in layers_attn]\n"
CLASS_ANCHOR = "@support_torch_compile\nclass DFlashQwen3Model"

HELPER = '''def _dense_kv_rows(attn: nn.Module) -> torch.Tensor:
    """Rows [q_size:] of the qkv projection as a dense bf16 matrix.

    club-3090 vendored fix for vllm#51581. For a compressed-tensors
    W4A16/W8A16 qkv_proj this runs before the Marlin repack, so
    weight_packed/weight_scale remain in plain checkpoint layout.
    """
    qkv = attn.qkv_proj
    w = getattr(qkv, "weight", None)
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
    print("[51581] applied: DFlash fused-KV slice now dequantizes qkv_proj")
    return 0


if __name__ == "__main__":
    sys.exit(main())
