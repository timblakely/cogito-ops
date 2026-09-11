"""Shared secure workspace and result lifecycle for command-line harnesses."""

from __future__ import annotations

from fnmatch import fnmatch
from hashlib import sha256
from pathlib import Path
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

from .models import AgentRun, canonical_json


def _run(argv: list[str], cwd: Path | None = None, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, text=True, check=True, **kwargs)


class Workspace:
    def __init__(self, run: AgentRun):
        self.run = run
        root = Path(os.environ.get("COGITO_WORK_ROOT", "/workspace"))
        self.root = root / run.run_id
        self.repo = self.root / "repo"
        self.artifacts = self.root / "artifacts"
        self.base_sha = ""

    def prepare(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)
        self.artifacts.mkdir(parents=True, mode=0o700)
        _run(["git", "clone", "--no-checkout", "--filter=blob:none", "--", self.run.repository,
              str(self.repo)], capture_output=True)
        _run(["git", "fetch", "--depth=1", "origin", self.run.base_ref], self.repo,
             capture_output=True)
        self.base_sha = _run(["git", "rev-parse", "FETCH_HEAD"], self.repo,
                             capture_output=True).stdout.strip()
        _run(["git", "checkout", "--detach", self.base_sha], self.repo, capture_output=True)
        _run(["git", "config", "user.name", "Cogito Agent"], self.repo)
        _run(["git", "config", "user.email", "agent@cogito.invalid"], self.repo)
        if shutil.which("jj"):
            _run(["jj", "git", "init", "--colocate"], self.repo, capture_output=True)
            _run(["jj", "config", "set", "--repo", "user.name", "Cogito Agent"], self.repo)
            _run(["jj", "config", "set", "--repo", "user.email", "agent@cogito.invalid"], self.repo)

    def changed_paths(self) -> list[str]:
        output = _run(["git", "status", "--porcelain=v1", "-z"], self.repo,
                      capture_output=True).stdout
        paths = []
        for record in output.split("\0"):
            if record:
                paths.append(record[3:].split(" -> ")[-1])
        return paths

    def verify_paths(self) -> list[str]:
        paths = self.changed_paths()
        if self.run.allowed_paths:
            denied = [path for path in paths if not any(fnmatch(path, rule) for rule in self.run.allowed_paths)]
            if denied:
                raise RuntimeError(f"harness changed paths outside allowlist: {denied}")
        return paths

    def publish(self) -> tuple[str, str | None]:
        paths = self.verify_paths()
        if not paths:
            return self.base_sha, None
        _run(["git", "add", "--all"], self.repo)
        _run(["git", "commit", "-m", f"agent: complete {self.run.run_id}"], self.repo,
             capture_output=True)
        head = _run(["git", "rev-parse", "HEAD"], self.repo, capture_output=True).stdout.strip()
        branch = "agent/" + re.sub(r"[^A-Za-z0-9._-]", "-", self.run.run_id)
        if os.environ.get("COGITO_PUBLISH", "1") == "1":
            ref = f"refs/heads/{branch}"
            existing = subprocess.run(["git", "ls-remote", "--heads", "origin", ref], cwd=self.repo,
                                      text=True, capture_output=True, check=True).stdout.strip()
            if existing and not existing.startswith(head + "\t"):
                raise RuntimeError(f"ref {ref} already exists at another revision")
            if not existing:
                _run(["git", "push", "origin", f"HEAD:{ref}"], self.repo, capture_output=True)
        return head, branch


def prompt(run: AgentRun) -> str:
    sections = [
        run.objective,
        "Work only in the current repository. Complete the task, run relevant checks, and leave changes in the working tree.",
    ]
    if run.constraints:
        sections.append("Constraints:\n" + "\n".join(f"- {v}" for v in run.constraints))
    if run.allowed_paths:
        sections.append("Allowed paths:\n" + "\n".join(f"- {v}" for v in run.allowed_paths))
    if run.acceptance_checks:
        sections.append("Acceptance criteria:\n" + "\n".join(f"- {v}" for v in run.acceptance_checks))
    return "\n\n".join(sections)


def configure_pi(role_model: str, env: dict[str, str]) -> None:
    """Configure Pi's documented OpenAI-compatible custom provider."""
    home = Path(env.get("HOME", "/tmp/agent-home"))
    agent_dir = home / ".pi" / "agent"
    agent_dir.mkdir(parents=True, mode=0o700)
    config = {
        "providers": {
            "litellm": {
                "baseUrl": env.get("OPENAI_BASE_URL", "https://litellm.timblakely.com/v1"),
                "api": "openai-completions",
                # Pi resolves this value from the environment at request time.
                "apiKey": "OPENAI_API_KEY",
                "authHeader": True,
                "compat": {
                    "supportsDeveloperRole": False,
                    "supportsReasoningEffort": False,
                },
                "models": [{"id": role_model, "name": role_model}],
            }
        }
    }
    path = agent_dir / "models.json"
    path.write_text(canonical_json(config))
    path.chmod(0o600)


def harness_argv(kind: str, run: AgentRun) -> tuple[list[str], dict[str, str]]:
    role_model = os.environ.get(f"COGITO_MODEL_FOR_{run.role.upper().replace('-', '_')}", run.role)
    env = dict(os.environ)
    if kind == "pi":
        configure_pi(role_model, env)
        command = shlex.split(os.environ.get("PI_COMMAND", "pi"))
        return [*command, "--print", "--no-session", "--provider", "litellm",
                "--model", role_model, prompt(run)], env
    if kind == "opencode":
        command = shlex.split(os.environ.get("OPENCODE_COMMAND", "opencode"))
        base_url = os.environ.get("OPENAI_BASE_URL", "https://litellm.timblakely.com/v1")
        config = {
            "provider": {"litellm": {"npm": "@ai-sdk/openai-compatible", "name": "LiteLLM",
                "options": {"baseURL": base_url, "apiKey": os.environ.get("OPENAI_API_KEY", "")},
                "models": {role_model: {"name": role_model}}}},
        }
        env["OPENCODE_CONFIG_CONTENT"] = canonical_json(config)
        return [*command, "--pure", "run", "--auto", "--format", "json",
                "--model", f"litellm/{role_model}", prompt(run)], env
    raise ValueError(f"unknown harness {kind}")


def normalized_output(kind: str, output: str) -> tuple[str, dict]:
    """Extract a concise summary and usage from supported harness output."""
    if kind != "opencode":
        return output[-4000:], {}
    texts, usage = [], {}
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        part = event.get("part", {})
        if event.get("type") == "text" and isinstance(part.get("text"), str):
            texts.append(part["text"].strip())
        tokens = part.get("tokens")
        if event.get("type") == "step_finish" and isinstance(tokens, dict):
            usage = {f"{key}_tokens": value for key, value in tokens.items()
                     if key in {"input", "output", "reasoning"} and isinstance(value, int)}
    return (texts[-1] if texts else output[-4000:]), usage


def start(kind: str, request: dict) -> dict:
    run = AgentRun.from_dict(request)
    skip_workspace = os.environ.get("COGITO_SKIP_WORKSPACE") == "1"
    workspace = Workspace(run)
    if not skip_workspace:
        workspace.prepare()
    argv, env = harness_argv(kind, run)
    completed = subprocess.run(argv, cwd=None if skip_workspace else workspace.repo,
                               text=True, capture_output=True, env=env,
                               timeout=run.limits.get("wall_seconds", 3600), check=False)
    log = completed.stdout + ("\n[stderr]\n" + completed.stderr if completed.stderr else "")
    digest = "sha256:" + sha256(log.encode()).hexdigest()
    head, branch = (None, None)
    changed_paths: list[str] = []
    error = None
    if completed.returncode == 0 and not skip_workspace:
        try:
            changed_paths = workspace.verify_paths()
            if run.role.startswith("reviewer"):
                if changed_paths:
                    raise RuntimeError("reviewer modified the workspace")
                head = workspace.base_sha
            else:
                head, branch = workspace.publish()
        except Exception as exc:
            error = str(exc)
    status = "succeeded" if completed.returncode == 0 and error is None else "failed"
    summary, harness_usage = normalized_output(kind, completed.stdout)
    review_verdict = None
    if run.role.startswith("reviewer") and status == "succeeded":
        match = re.search(r"COGITO_REVIEW:\s*(APPROVE|REQUEST_CHANGES)\b", summary, re.IGNORECASE)
        if not match:
            status, error = "failed", "reviewer did not emit a COGITO_REVIEW verdict"
        else:
            review_verdict = match.group(1).lower()
            if review_verdict == "request_changes":
                status = "failed"
    if not skip_workspace:
        (workspace.artifacts / "harness.log").write_text(log)
        if head:
            patch = _run(["git", "diff", "--binary", workspace.base_sha, head], workspace.repo,
                         capture_output=True).stdout
            (workspace.artifacts / "changes.patch").write_text(patch)
        result_path = workspace.artifacts / "result.json"
    summary = error or summary or completed.stderr[-4000:] or f"{kind} exited {completed.returncode}"
    artifacts = [{"name": "harness.log", "digest": digest}]
    if not skip_workspace and head:
        artifacts.append({"name": "changes.patch", "digest": "sha256:" + sha256(patch.encode()).hexdigest()})
    usage = {"role": run.role, "harness": kind, "changed_paths": changed_paths, **harness_usage}
    if review_verdict:
        usage["review_verdict"] = review_verdict
    result = {
        "api_version": run.api_version, "run_id": run.run_id, "status": status,
        "summary": summary, "head_sha": head,
        "checks": [{"name": "harness exit", "status": "passed" if completed.returncode == 0 else "failed"},
                   {"name": "allowed paths", "status": "passed" if error is None else "failed"}],
        "artifacts": artifacts,
        "usage": usage,
    }
    if branch:
        result["usage"]["published_ref"] = f"refs/heads/{branch}"
    if not skip_workspace:
        result_path.write_text(canonical_json(result))
    return result


def main(kind: str) -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"capabilities", "start"}:
        raise SystemExit(f"usage: {kind}-adapter capabilities|start")
    if sys.argv[1] == "capabilities":
        print(canonical_json({"api_version": "cogito.dev/v1alpha1", "adapter": kind,
              "operations": ["capabilities", "start"],
              "lifecycle_owner": "argo", "workspace": "git+jj"}))
        return
    print(canonical_json(start(kind, json.load(sys.stdin))))
