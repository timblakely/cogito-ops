#!/usr/bin/env python3
"""Seed an ephemeral runtime without overwriting retained model calibration."""
from pathlib import Path
import json
import os
import shutil

SOURCE_COMMIT = "d93d1499021b98a39bede20d33368907f1ea4ad8"


def prepare(seed, runtime, retained_config, context_size=None):
    assert (seed / ".cogito-source-commit").read_text().strip() == SOURCE_COMMIT
    assert retained_config.is_file(), "retained upstream setup config missing"
    config = None
    if context_size is not None:
        if type(context_size) is not int or context_size <= 0:
            raise ValueError("context size must be a positive integer")
        config = json.loads(retained_config.read_text())
        args = config["args"]
        if not isinstance(args, list) or args.count("--max-context") != 1:
            raise ValueError("expected one retained --max-context argument")
        index = args.index("--max-context") + 1
        if index >= len(args) or int(args[index]) <= 0:
            raise ValueError("invalid retained --max-context value")
        args[index] = str(context_size)
    def skip_existing(directory, names):
        source = Path(directory)
        ignored = ["data"] if source == seed else []
        for name in names:
            src = source / name
            dst = runtime / source.relative_to(seed) / name
            # copytree does not overwrite existing symlinks on container restart.
            if src.is_symlink() and dst.is_symlink() and os.readlink(src) == os.readlink(dst):
                ignored.append(name)
        return ignored

    shutil.copytree(seed, runtime, dirs_exist_ok=True, symlinks=True, ignore=skip_existing)
    target = runtime / "maya-maya-m.json"
    if config is None:
        shutil.copy2(retained_config, target)
    else:
        target.write_text(json.dumps(config, indent=2) + "\n")


if __name__ == "__main__":
    prepare(Path("/opt/maya-image/project-maya"),
            Path("/model/maya-work/project-maya"),
            Path("/etc/maya/retained-config.json"),
            context_size=int(os.environ["COGITO_MAYA_CONTEXT_SIZE"])
            if "COGITO_MAYA_CONTEXT_SIZE" in os.environ else None)
