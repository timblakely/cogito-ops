"""LiteLLM planner-role client with a stable provider-neutral prompt."""

from dataclasses import dataclass
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import json


SYSTEM = """You are Cogito's planning role. Produce a complete Markdown plan.
Include Context, Decisions, Deliverables, Dependencies, Risks, Acceptance
criteria, and Rollback. Under Deliverables use top-level Markdown checkboxes;
each checkbox must be independently implementable and testable. Do not claim
that work has already been performed."""


@dataclass
class PlannerClient:
    api_key: str
    base_url: str = "https://litellm.timblakely.com/v1"
    model: str = "planner"
    fallback_models: tuple[str, ...] = ("planner-gpt", "planner-gpt-pro", "planner-local")

    def plan(self, objective: str, prior: str = "", comments: list[str] | None = None) -> str:
        content = f"Objective:\n{objective.strip()}"
        if prior:
            content += f"\n\nPrior plan:\n{prior}"
        if comments:
            content += "\n\nReview comments:\n" + "\n".join(f"- {c}" for c in comments)
        last_error = None
        for model in (self.model, *self.fallback_models):
            body = json.dumps({
                "model": model,
                "messages": [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": content}],
            }).encode()
            request = Request(
                self.base_url.rstrip("/") + "/chat/completions", data=body, method="POST",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            )
            try:
                with urlopen(request, timeout=1800) as response:
                    result = json.load(response)
                return result["choices"][0]["message"]["content"]
            except HTTPError as exc:
                last_error = exc
                if exc.code not in {401, 402, 403, 429, 500, 502, 503, 504}:
                    raise
        raise last_error
