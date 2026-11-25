#!/usr/bin/env python3
"""Seed managed Paseo settings without deleting user-installed plugins."""

import json
import os
import sys
import tempfile
from pathlib import Path


def configure(template, destination):
    managed = json.loads(template.read_text())
    previous = json.loads(destination.read_text()) if destination.exists() else {}
    managed["plugins"] = {**previous.get("plugins", {}), **managed.get("plugins", {})}
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=destination.parent, prefix=".paseo-config-", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(managed, handle, indent=2)
            handle.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    configure(Path(sys.argv[1]), Path(sys.argv[2]))
