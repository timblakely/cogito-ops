#!/usr/bin/env python3
"""GPU-free image gate; deliberately not an inference or vision ingestion test."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path("/model/maya-work/project-maya")


def missing_dependencies(output):
    return [name for name in re.findall(r"^\s*(\S+)\s+=> not found", output, re.M)
            if name != "libcuda.so.1"]


def cmake_cache_matches(cache):
    return bool(re.search(r"^STRATA_PORTABLE:BOOL=ON$", cache, re.M)
                and re.search(r"^CMAKE_CUDA_ARCHITECTURES:[A-Z]+=86$", cache, re.M))


def main():
    assert sys.version_info[:2] == (3, 12)
    assert (ROOT / ".cogito-source-commit").read_text().strip() == "d93d1499021b98a39bede20d33368907f1ea4ad8"
    sys.path.insert(0, str(ROOT))
    import maya as maya

    engine = json.loads((ROOT / "build/MAYA-BUILD.json").read_text())
    vision = json.loads((ROOT / "build-vision/MAYA-BUILD.json").read_text())
    assert engine["src"] == maya.S.source_hash(maya.S.ENGINE_SOURCES)
    assert vision["src"] == maya.S.source_hash(("tools/vision",))
    assert engine["archs"] == vision["archs"] == [86]
    assert engine["gpu_ids"] == [0, 1] and "maya" in engine["targets"]
    assert vision["backend"] == "cuda"
    assert engine["llama"] == vision["llama"] == str(ROOT / "third_party/llama.cpp")
    installed = json.loads((ROOT / ".venv/.strata-pip.json").read_text())
    assert set(maya.PY_PACKAGES) <= set(installed)
    for folder in ("build", "build-vision"):
        cache = (ROOT / folder / "CMakeCache.txt").read_text()
        assert cmake_cache_matches(cache), f"nonportable or unexpected CUDA architecture: {folder}"
    for binary in (ROOT / "build/maya", ROOT / "build-vision/bin/maya-vision"):
        assert binary.is_file() and os.access(binary, os.X_OK)
        result = subprocess.run(["ldd", str(binary)], text=True, capture_output=True, check=True)
        print(result.stdout)
        assert not missing_dependencies(result.stdout), result.stdout
    subprocess.run([sys.executable, "-m", "pip", "check"], check=True)
    # Launcher help parses arguments before any GPU check or model preparation.
    subprocess.run([str(ROOT / "setup.sh"), "--help"], cwd=ROOT, check=True,
                   stdout=subprocess.DEVNULL)
    print("MAYA_IMAGE_GPU_FREE_VERIFY_PASS", flush=True)


if __name__ == "__main__":
    main()
