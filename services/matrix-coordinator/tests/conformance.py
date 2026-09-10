#!/usr/bin/python3
"""Run an adapter against a fixture harness and validate its result contract."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from coordinator.models import AgentResult, AgentRun

if len(sys.argv) != 2:
    raise SystemExit("usage: conformance.py ADAPTER")
adapter = str(Path(sys.argv[1]).resolve())
request = AgentRun.from_dict({
    "run_id": "conformance-0001",
    "work_item": "https://github.com/timblakely/cogito/issues/1",
    "role": "worker",
    "repository": "https://github.com/timblakely/cogito.git",
    "base_ref": "main",
    "objective": "Return a fixture result safely",
    "acceptance_checks": ["fixture exits zero"],
    "limits": {"wall_seconds": 30},
})
with tempfile.TemporaryDirectory() as directory:
    fake = Path(directory) / "harness"
    fake.write_text("#!/bin/sh\nprintf 'fixture harness completed\\n'\n")
    fake.chmod(0o700)
    env = dict(os.environ, PI_COMMAND=str(fake), OPENCODE_COMMAND=str(fake))
    completed = subprocess.run([adapter, "start"], input=json.dumps(request.as_dict()),
                               text=True, capture_output=True, env=env, timeout=30)
    if completed.returncode:
        raise SystemExit(completed.stderr)
    result = AgentResult.from_dict(json.loads(completed.stdout))
    assert result.run_id == request.run_id and result.status == "succeeded"
print(f"{Path(adapter).name}: conformant")
