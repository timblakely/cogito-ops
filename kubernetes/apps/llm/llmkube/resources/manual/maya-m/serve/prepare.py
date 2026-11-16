#!/usr/bin/env python3
"""Seed an ephemeral runtime without overwriting retained model calibration."""
from pathlib import Path
import shutil

SOURCE_COMMIT = "d93d1499021b98a39bede20d33368907f1ea4ad8"


def prepare(seed, runtime, retained_config):
    assert (seed / ".cogito-source-commit").read_text().strip() == SOURCE_COMMIT
    assert retained_config.is_file(), "retained upstream setup config missing"
    shutil.copytree(seed, runtime, dirs_exist_ok=True, symlinks=True,
                    ignore=lambda directory, names: ["data"] if Path(directory) == seed else [])
    shutil.copy2(retained_config, runtime / "maya-maya-m.json")


if __name__ == "__main__":
    prepare(Path("/opt/maya-image/project-maya"),
            Path("/model/maya-work/project-maya"),
            Path("/etc/maya/retained-config.json"))
