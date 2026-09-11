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
    if run.role.startswith("reviewer") and os.environ.get("REVIEWER_API_KEY"):
        os.environ["OPENAI_API_KEY"] = os.environ["REVIEWER_API_KEY"]
    if sys.argv[1] == "contract":
        result = {
            "api_version": run.api_version, "run_id": run.run_id, "status": "succeeded",
            "summary": "Contract adapter completed",
            "checks": [{"name": "contract-smoke", "status": "passed"}],
            "artifacts": [], "usage": {"role": run.role, "harness": "contract"},
        }
    else:
        try:
            result = start(sys.argv[1], request)
        except Exception as exc:
            result = {
                "api_version": run.api_version, "run_id": run.run_id, "status": "failed",
                "summary": f"{type(exc).__name__}: {str(exc)[:3000]}",
                "checks": [{"name": "adapter runtime", "status": "failed"}],
                "artifacts": [], "usage": {"role": run.role, "harness": sys.argv[1]},
            }
    path = Path("/tmp/result.json")
    path.write_text(canonical_json(result))
    path.chmod(0o644)


if __name__ == "__main__":
    main()
