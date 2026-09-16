#!/usr/bin/env python3
"""Bound accepted-token state lookups in GDN speculative decode (vllm#50021).

Speculative decoding hands per-request accepted-token counts to several Triton
kernels, which turn them into array indices without bounds checks. A stale,
zero, or too-large count produces an out-of-range read whose garbage value is
then multiplied by a page stride and dereferenced, faulting the SM with
Xid 13/31 within a handful of concurrent requests. That is the crash that
pins this lane to --max-num-seqs 1.

Upstream PR vllm-project/vllm#50021 is still open, so the fix is vendored here
in the same anchor-checked form as the other club-3090 overlays. Only the
sites Qwen 3.8's GDN path reaches are patched; the PR's Kimi KDA and Mamba2
hunks are left alone because this model never enters them.
"""
import io
import sys

MARKER = "club-3090 GDN spec-decode state bounds (vllm#50021)"
PKG = "/usr/local/lib/python3.12/dist-packages/vllm"
TAG = "[50021]"

FLA_OLD = """            # Load state index and check for invalid entries
            state_idx = tl.load(ssm_state_indices + i_n * stride_indices_seq + i_t).to(
                tl.int64
            )
            # Skip if state index is invalid (NULL_BLOCK_ID=0)
            if state_idx <= 0:
                return
"""

FLA_NEW = """            # club-3090 GDN spec-decode state bounds (vllm#50021). ``i_t`` is
            # ``num_accepted_tokens - 1`` and is otherwise unbounded against a
            # ``stride_indices_seq``-column tensor: a zero accepted count gives
            # ``i_t == -1`` (a read before this request's row, and before the
            # tensor for ``i_n == 0``); a stale or too-large count reads past
            # the row. The ``state_idx <= 0`` guard below only rejects
            # non-positive values, so an out-of-range read that returns a
            # garbage positive int flows into
            # ``h0 + state_idx * stride_init_state_token`` and is dereferenced,
            # faulting the SM. Mask the load to the row and let ``other=0``
            # fall into the existing invalid-state path.
            idx_in_row = (i_t >= 0) & (i_t < stride_indices_seq)
            state_idx = tl.load(
                ssm_state_indices + i_n * stride_indices_seq + i_t,
                mask=idx_in_row,
                other=0,
            ).to(tl.int64)
            # Skip invalid state indices without exposing uninitialized output.
            if state_idx <= 0:
                zero = tl.zeros([BV], dtype=tl.float32).to(p_o.dtype.element_ty)
                for _ in range(0, T):
                    tl.store(p_o, zero, mask=mask_v)
                    p_o += HV * V
                return
"""

MAMBA_DEST_OLD = """    dest_block_id = tl.load(block_table_base + dst_col).to(tl.int64)
"""

MAMBA_DEST_NEW = """    # club-3090 GDN spec-decode state bounds (vllm#50021). The block-table
    # columns below are derived from per-request accepted-token counts. A wrong
    # count walks the read past this request's row; the loaded int32 is then
    # multiplied by state_block_stride and dereferenced, so an out-of-range
    # column becomes a wild (and possibly misaligned) address rather than
    # merely a wrong copy. Bound the columns to the row: an out-of-range column
    # loads the ``other=-1`` sentinel, and the ``<= 0`` guards below reject both
    # that sentinel and ``NULL_BLOCK_ID`` (0, the unallocated-slot marker), so
    # neither reaches the address math.
    dst_col_ok = (dst_col >= 0) & (dst_col < block_table_stride_req)
    dest_block_id = tl.load(block_table_base + dst_col, mask=dst_col_ok, other=-1).to(
        tl.int64
    )
    if dest_block_id <= 0:
        return
"""

MAMBA_SRC_OLD = """        src_block_id = tl.load(block_table_base + src_col).to(tl.int64)
"""

MAMBA_SRC_NEW = """        src_col_ok = (src_col >= 0) & (src_col < block_table_stride_req)
        src_block_id = tl.load(
            block_table_base + src_col, mask=src_col_ok, other=-1
        ).to(tl.int64)
        if src_block_id <= 0:
            return
"""

MAMBA_TEMPORAL_OLD = """    actual_src_block_id = tl.load(block_table_base + src_col + token_bias).to(tl.int64)
"""

MAMBA_TEMPORAL_NEW = """    tmp_col = src_col + token_bias
    tmp_col_ok = (tmp_col >= 0) & (tmp_col < block_table_stride_req)
    actual_src_block_id = tl.load(
        block_table_base + tmp_col, mask=tmp_col_ok, other=-1
    ).to(tl.int64)
    if actual_src_block_id <= 0:
        return
"""

# (relative path, [(old, new, expected_occurrences), ...])
EDITS = (
    (
        "third_party/flash_linear_attention/ops/fused_recurrent.py",
        ((FLA_OLD, FLA_NEW, 1),),
    ),
    (
        "third_party/flash_linear_attention/ops/fused_sigmoid_gating.py",
        ((FLA_OLD, FLA_NEW, 1),),
    ),
    (
        "v1/worker/mamba_utils.py",
        (
            (MAMBA_DEST_OLD, MAMBA_DEST_NEW, 1),
            (MAMBA_SRC_OLD, MAMBA_SRC_NEW, 2),
            (MAMBA_TEMPORAL_OLD, MAMBA_TEMPORAL_NEW, 1),
        ),
    ),
)


def main() -> int:
    planned = []
    for relpath, edits in EDITS:
        target = f"{PKG}/{relpath}"
        try:
            src = io.open(target, encoding="utf-8").read()
        except OSError as exc:
            print(f"{TAG} REFUSE: cannot read {relpath}: {exc}")
            return 1
        if MARKER in src:
            print(f"{TAG} {relpath} already patched (idempotent no-op)")
            continue
        for old, new, expected in edits:
            found = src.count(old)
            if found != expected:
                anchor = old.strip().splitlines()[0]
                print(
                    f"{TAG} REFUSE: {relpath} has {found} of an expected "
                    f"{expected} occurrences of: {anchor}"
                )
                return 1
            src = src.replace(old, new)
        planned.append((target, relpath, src))

    # Write only after every file has verified, so a drifted vLLM leaves the
    # tree untouched rather than half-patched.
    for target, relpath, src in planned:
        try:
            io.open(target, "w", encoding="utf-8").write(src)
        except OSError as exc:
            print(f"{TAG} FAILED writing {relpath}: {exc}")
            return 1
        print(f"{TAG} applied: {relpath}")
    if planned:
        print(f"{TAG} applied: accepted-token state lookups are bounds-masked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
