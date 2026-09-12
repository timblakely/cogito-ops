"""LiteLLM planner-role client with conversational intake and plan drafting."""

from dataclasses import dataclass
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import json


SYSTEM = """You are Cogito's planning role. Produce a complete Markdown plan.
Include Context, Decisions, Deliverables, Dependencies, Risks, Acceptance
criteria, and Rollback. Under Deliverables use top-level Markdown checkboxes;
each checkbox must be independently implementable and testable. Do not claim
that work has already been performed."""

INTAKE_SYSTEM = """You are Cogito's planning partner. Decide whether the user's
objective is ready to become an implementation plan. Ask only questions whose
answers would materially change the implementation. You may push back on unsafe,
contradictory, or needlessly complex requirements. Be direct and conversational.

Return exactly one JSON object with no code fence:
- {"status":"clarify","message":"one concise response with at most three questions"}
- {"status":"pushback","message":"a concrete concern and a proposed alternative"}
- {"status":"ready","message":"a short transition","plan_markdown":"the complete plan"}

For a ready plan, include Context, Decisions, Deliverables, Dependencies, Risks,
Acceptance criteria, and Rollback. Under Deliverables use top-level Markdown
checkboxes; each checkbox must be independently implementable and testable. Do
not claim work has already been performed. When told to draft now, resolve any
remaining uncertainty with explicit assumptions instead of asking again."""


@dataclass
class PlannerClient:
    api_key: str
    base_url: str = "https://litellm.timblakely.com/v1"
    model: str = "planner"
    fallback_models: tuple[str, ...] = ("planner-gpt", "planner-gpt-pro", "planner-local")

    def _complete(self, system: str, content: str) -> str:
        last_error = None
        for model in (self.model, *self.fallback_models):
            body = json.dumps({
                "model": model,
                "messages": [{"role": "system", "content": system},
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

    def intake(self, messages: list[dict[str, str]], force: bool = False) -> dict[str, str]:
        transcript = "\n\n".join(
            f"{item['role'].title()} ({item['kind']}):\n{item['body']}" for item in messages
        )
        if force:
            transcript += "\n\nInstruction: Draft now. State reasonable assumptions in the plan."
        raw = self._complete(INTAKE_SYSTEM, transcript).strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            start, end = raw.find("{"), raw.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("planner intake returned invalid JSON")
            value = json.loads(raw[start:end + 1])
        status = value.get("status")
        if status not in {"ready", "clarify", "pushback"}:
            raise ValueError("planner intake returned an invalid status")
        if not isinstance(value.get("message"), str) or not value["message"].strip():
            raise ValueError("planner intake returned no message")
        if status == "ready" and (not isinstance(value.get("plan_markdown"), str)
                                  or not value["plan_markdown"].strip()):
            raise ValueError("planner intake returned no plan")
        if force and status != "ready":
            raise ValueError("planner did not draft when explicitly requested")
        return value

    def plan(self, objective: str, prior: str = "", comments: list[str] | None = None) -> str:
        content = f"Objective:\n{objective.strip()}"
        if prior:
            content += f"\n\nPrior plan:\n{prior}"
        if comments:
            content += "\n\nReview comments:\n" + "\n".join(f"- {c}" for c in comments)
        return self._complete(SYSTEM, content)
