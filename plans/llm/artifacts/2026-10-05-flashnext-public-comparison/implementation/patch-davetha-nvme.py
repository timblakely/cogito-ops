from pathlib import Path
import hashlib,difflib
source=Path('/tmp/flashnext-competition/davetha-base-vllm/app/vllm/vllm/models/qwen4_exp/amd/ple_layer.py');s=source.read_text()
needle='''                    embedding.weight.data = torch.empty_like(
                        embedding.weight.data, dtype=loaded_weight.dtype
                    )'''
replacement='''                    # Iggy comparison: retain the checkpoint's exact FP8 rows
                    # in a pageable local NVMe mapping instead of a full RAM copy.
                    import os
                    nvme_path = os.environ.get("FLASHNEXT_PLE_NVME_PATH")
                    if nvme_path and is_offload_process():
                        if loaded_weight.dtype != torch.float8_e4m3fn:
                            raise ValueError("NVMe PLE adapter requires FP8 E4M3")
                        total_rows = embedding.org_vocab_size
                        row_bytes = embedding.embedding_dim
                        if os.stat(nvme_path).st_size != total_rows * row_bytes:
                            raise ValueError("NVMe PLE table size differs from checkpoint")
                        mapped = torch.from_file(nvme_path, shared=False,
                            size=total_rows * row_bytes, dtype=torch.uint8)
                        mapped = mapped.view(loaded_weight.dtype).view(total_rows, row_bytes)
                        first = embedding.shard_indices.org_vocab_start_index
                        end = embedding.shard_indices.org_vocab_end_index
                        rows = mapped[first:end]
                        if rows.shape != embedding.weight.shape:
                            raise ValueError("NVMe PLE table needs unsupported TP padding")
                        embedding.weight.data = rows
                        self._nvme_ple_mapped = True
                    else:
                        embedding.weight.data = torch.empty_like(
                            embedding.weight.data, dtype=loaded_weight.dtype
                        )'''
assert s.count(needle)==1;s=s.replace(needle,replacement)
needle='''                copy_ple_embedding_shard_(
                    embedding.weight.data,
                    loaded_weight,
                    checkpoint_start=checkpoint_start,
                    tp_start=embedding.shard_indices.org_vocab_start_index,
                    tp_end=embedding.shard_indices.org_vocab_end_index,
                )'''
replacement='''                if not getattr(self, "_nvme_ple_mapped", False):
                    copy_ple_embedding_shard_(
                        embedding.weight.data,
                        loaded_weight,
                        checkpoint_start=checkpoint_start,
                        tp_start=embedding.shard_indices.org_vocab_start_index,
                        tp_end=embedding.shard_indices.org_vocab_end_index,
                    )'''
assert s.count(needle)==1;s=s.replace(needle,replacement)
out=Path('/tmp/flashnext-competition/davetha-nvme-ple.patch');out.write_text(''.join(difflib.unified_diff(source.read_text().splitlines(True),s.splitlines(True),fromfile='a/vllm/models/qwen4_exp/amd/ple_layer.py',tofile='b/vllm/models/qwen4_exp/amd/ple_layer.py')))
compile(s,str(source),'exec');print('Patch prepared',hashlib.sha256(out.read_bytes()).hexdigest())
