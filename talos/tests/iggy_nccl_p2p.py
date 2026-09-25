"""Verify a two-rank NCCL collective on Iggy's two RTX 3090s."""

from datetime import timedelta
import os

import torch
import torch.distributed as dist


rank = int(os.environ["LOCAL_RANK"])
torch.cuda.set_device(rank)
dist.init_process_group("nccl", timeout=timedelta(seconds=90))

try:
    # 16 MiB per rank is large enough to exercise the data path while leaving
    # room for the inference workload that shares these GPUs.
    values = torch.full((4 * 1024 * 1024,), rank + 1, device=f"cuda:{rank}")
    dist.all_reduce(values)
    if not torch.all(values == 3).item():
        raise RuntimeError(f"NCCL all-reduce corrupted data on rank {rank}")
    torch.cuda.synchronize()
    dist.barrier()
    print(f"rank {rank}: NCCL all-reduce verified 16 MiB", flush=True)
finally:
    dist.destroy_process_group()
