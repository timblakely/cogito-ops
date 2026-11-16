#!/usr/bin/env python3
"""Build upstream GLM and vision helpers without detecting GPUs or preparing weights."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path("/model/maya-work/project-maya")
LLAMA_COMMIT = "3cf03257f219afbe7334045ff7c6a06ac68c627d"


def cmake_commands(conf, build):
    conf = [*conf, "-DSTRATA_PORTABLE=ON"]
    build = list(build)
    build[build.index("-j") + 1] = "4"
    return conf, build


def main():
    sys.path.insert(0, str(ROOT))
    import maya as maya

    assert maya.S.ROOT == ROOT
    assert maya.S.LLAMA_CPP_COMMIT == LLAMA_COMMIT
    original = maya.cmake_steps

    def bounded(conf, build, *args, **kwargs):
        conf, build = cmake_commands(conf, build)
        return original(conf, build, *args, **kwargs)

    maya.cmake_steps = bounded
    # tools_step owns the upstream pip stamp. PIP_CONSTRAINT holds observed versions.
    llama = maya.tools_step(SimpleNamespace(yes=True, llama_dir=None))
    meta = maya.compile_engine(
        [86], [0, 1], "/usr/local/cuda/bin/nvcc", None, llama,
        maya.S.source_hash(maya.S.ENGINE_SOURCES),
    )
    assert meta and maya.EXE.is_file(), "native GLM engine missing"
    assert maya.compile_vision(
        {"backend": "cuda", "archs": [86], "nvcc": "/usr/local/cuda/bin/nvcc"},
        meta, llama, maya.S.source_hash(("tools/vision",)),
    ), "native vision encoder build failed"
    assert maya.VEXE.is_file()
    (ROOT / "image-build.json").write_text(json.dumps({
        "maya_commit": (ROOT / ".cogito-source-commit").read_text().strip(),
        "llama_commit": LLAMA_COMMIT,
        "architectures": [86], "portable": True, "jobs": 4,
        "model_weights_included": False,
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
