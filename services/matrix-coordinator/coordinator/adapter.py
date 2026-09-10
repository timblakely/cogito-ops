"""Harness adapter invocation and conformance CLI."""

from __future__ import annotations

from collections.abc import Sequence
import argparse
import json
import os
import subprocess
import sys

from .models import AgentResult, AgentRun, ValidationError, canonical_json


class AdapterError(RuntimeError):
    pass


class CommandAdapter:
    def __init__(self, name: str, command: Sequence[str]):
        if not command or any(not isinstance(v, str) or not v for v in command):
            raise ValidationError("adapter command must be a non-empty argv list")
        self.name = name
        self.command = tuple(command)

    def capabilities(self) -> dict[str, object]:
        return {
            "api_version": "cogito.dev/v1alpha1",
            "adapter": self.name,
            "operations": ["capabilities", "start", "status", "cancel", "resume", "collect-result"],
        }

    def start(self, run: AgentRun, timeout: int | None = None) -> AgentResult:
        timeout = timeout or run.limits.get("wall_seconds", 3600)
        completed = subprocess.run(
            [*self.command, "start"], input=canonical_json(run.as_dict()),
            text=True, capture_output=True, timeout=timeout, check=False,
            env={**os.environ, "COGITO_AGENT_ROLE": run.role},
        )
        if completed.returncode != 0:
            raise AdapterError(
                f"{self.name} exited {completed.returncode}: {completed.stderr[-1000:]}")
        try:
            result = AgentResult.from_dict(json.loads(completed.stdout))
        except (json.JSONDecodeError, TypeError, ValidationError) as exc:
            raise AdapterError(f"{self.name} returned an invalid result") from exc
        if result.run_id != run.run_id:
            raise AdapterError("adapter result run_id does not match request")
        return result


def configured_adapter(name: str) -> CommandAdapter:
    commands = {
        "pi": os.environ.get("COGITO_PI_ADAPTER", "adapters/pi-adapter").split(),
        "opencode": os.environ.get("COGITO_OPENCODE_ADAPTER", "adapters/opencode-adapter").split(),
        "contract": os.environ.get("COGITO_CONTRACT_ADAPTER", "adapters/contract-adapter").split(),
    }
    if name not in commands:
        raise ValidationError(f"unknown adapter {name!r}")
    return CommandAdapter(name, commands[name])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("adapter", choices=("pi", "opencode", "contract"))
    parser.add_argument("operation", choices=("capabilities", "start"))
    args = parser.parse_args()
    adapter = configured_adapter(args.adapter)
    if args.operation == "capabilities":
        print(canonical_json(adapter.capabilities()))
        return
    run = AgentRun.from_dict(json.load(sys.stdin))
    print(canonical_json(adapter.start(run).as_dict()))
