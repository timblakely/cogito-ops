"""Argo container boundary selecting one allowlisted harness without a shell."""

from pathlib import Path
import json
import os
import sys

from .harness_runtime import start
from .models import AgentRun, canonical_json


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"contract", "pi", "opencode"}:
        raise SystemExit("usage: agent_entry contract|pi|opencode")
    request = json.loads(os.environ["COGITO_AGENT_REQUEST"])
    run = AgentRun.from_dict(request)
    if sys.argv[1] == "contract":
        result = {
            "api_version": run.api_version, "run_id": run.run_id, "status": "succeeded",
            "summary": "Contract adapter completed",
            "checks": [{"name": "contract-smoke", "status": "passed"}],
            "artifacts": [], "usage": {"role": run.role, "harness": "contract"},
        }
    else:
        result = start(sys.argv[1], request)
    path = Path("/tmp/result.json")
    path.write_text(canonical_json(result))
    path.chmod(0o644)


if __name__ == "__main__":
    main()
