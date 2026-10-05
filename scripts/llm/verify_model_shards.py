#!/usr/bin/env python3
"""Verify pinned Hugging Face GGUF files with bounded parallel reads.

Reads in parallel but updates SHA-256 in file order. A completed range download
is renamed only after its whole-file digest matches the upstream LFS digest.
An optional local copy receives the same bytes during verification.
"""
import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import fnmatch
import hashlib
import json
import math
import os
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include", default="*.gguf")
    parser.add_argument("--copy-root", type=Path)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--read-chunk-mib", type=int, default=128)
    args = parser.parse_args()
    if args.workers < 1 or args.read_chunk_mib < 1:
        parser.error("workers and read chunk must be positive")
    chunk = args.read_chunk_mib * 2**20
    args.output.parent.mkdir(parents=True, exist_ok=True)
    records = []
    for item in json.loads(args.metadata.read_text()):
        name = item["path"]
        assert not Path(name).is_absolute() and ".." not in Path(name).parts
        if not name.endswith(".gguf") or not fnmatch.fnmatch(name, args.include):
            continue
        target = args.root / name
        source = target if target.exists() else target.with_suffix(".range-part")
        assert source.stat().st_size == item["size"], (source, "incomplete size")
        if source != target:
            state = json.loads(target.with_suffix(".range-state.json").read_text())
            download_chunk = state.get("chunk_bytes", 512 * 2**20)
            expected_offsets = set(range(0, item["size"], download_chunk))
            assert set(state["completed"]) == expected_offsets, (source, "unfinished ranges")
            assert state["sha256"] == item["lfs"]["oid"]
        copied = args.copy_root / name if args.copy_root else None
        out = None
        prefix = 0
        local_partial = None
        if copied:
            copied.parent.mkdir(parents=True, exist_ok=True)
            local_partial = copied.with_suffix(".gguf.partial")
            if local_partial.exists():
                prefix = min(item["size"], local_partial.stat().st_size) // chunk * chunk
            space = os.statvfs(copied.parent)
            assert space.f_bavail * space.f_frsize > item["size"] - prefix + 8 * 2**30, "Insufficient local staging space"
            out = local_partial.open("r+b" if local_partial.exists() else "w+b")
            out.truncate(prefix)
            out.seek(prefix)
            if prefix:
                print("RESUME", name, round(prefix / 2**30, 2), "GiB; digest includes the local prefix", flush=True)
        started = time.monotonic()
        digest = hashlib.sha256()
        def read(n):
            read_source = local_partial if n * chunk < prefix else source
            with read_source.open("rb") as f:
                f.seek(n * chunk)
                data = f.read(min(chunk, item["size"] - n * chunk))
                assert len(data) == min(chunk, item["size"] - n * chunk), "Short model read"
                return data
        count = math.ceil(item["size"] / chunk)
        pending = deque()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            next_chunk = 0
            for _ in range(min(args.workers, count)):
                pending.append(pool.submit(read, next_chunk))
                next_chunk += 1
            done = 0
            while pending:
                data = pending.popleft().result()
                digest.update(data)
                if out and done >= prefix:
                    out.write(data)
                done += len(data)
                if next_chunk < count:
                    pending.append(pool.submit(read, next_chunk))
                    next_chunk += 1
                if done % (4 * 2**30) == 0:
                    print("READ", name, round(done / 2**30, 2), "GiB", round(time.monotonic() - started, 1), "seconds", flush=True)
        actual = digest.hexdigest()
        assert actual == item["lfs"]["oid"], (source, "checksum mismatch", actual)
        if out:
            out.flush()
            os.fsync(out.fileno())
            out.close()
            with copied.with_suffix(".gguf.partial").open("rb") as f:
                assert hashlib.file_digest(f, "sha256").hexdigest() == actual, "Local copy checksum mismatch"
            copied.with_suffix(".gguf.partial").replace(copied)
        if source != target:
            source.replace(target)
        records.append({"path": name, "bytes": item["size"], "sha256": actual, "matches_upstream": True, "local_copy": str(copied) if copied else None})
        args.output.write_text(json.dumps(records, indent=2) + "\n")
        print("VERIFIED", name, actual, flush=True)
    assert records, "No matching model files"


if __name__ == "__main__":
    main()
