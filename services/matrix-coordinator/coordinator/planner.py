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

You have no repository, shell, or web tools. Use delegate_research whenever a
material decision depends on repository exploration, current implementation
facts, upstream documentation, or command output not already established by the
research briefing. Give each scout one focused, independently answerable task.
Do not ask the user for facts a scout can discover. Scout summaries are evidence,
not certainty: surface consequential gaps or conflicts rather than inventing facts.

When you do not call delegate_research, return exactly one JSON object with no code fence:
- {"status":"clarify","message":"one concise response with at most three questions"}
- {"status":"pushback","message":"a concrete concern and a proposed alternative"}
- {"status":"ready","message":"a short transition","plan_markdown":"the complete plan"}

For a ready plan, include Context, Decisions, Deliverables, Dependencies, Risks,
Acceptance criteria, and Rollback. Under Deliverables use top-level Markdown
checkboxes; each checkbox must be independently implementable and testable. Do
not claim work has already been performed. When told to draft now, resolve any
remaining uncertainty with explicit assumptions instead of asking again."""

DELEGATE_RESEARCH = {
    "type": "function",
    "name": "delegate_research",
    "description": (
        "Delegate repository exploration, research, and command execution to cheap "
        "read-only local planning scouts."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "Brief user-facing progress note."},
            "tasks": {
                "type": "array", "minItems": 1, "maxItems": 4,
                "items": {"type": "string"},
            },
        },
        "required": ["message", "tasks"],
        "additionalProperties": False,
    },
    "strict": True,
}


@dataclass
class PlannerClient:
    api_key: str
    base_url: str = "https://litellm.timblakely.com/v1"
    model: str = "planner"
    fallback_models: tuple[str, ...] = ()

    def _response(self, system: str, content: str, tools: list[dict] | None = None,
                  tool_choice: str | None = None) -> dict:
        last_error = None
        for model in (self.model, *self.fallback_models):
            value = {
                "model": model,
                "input": [{"role": "developer", "content": system},
                          {"role": "user", "content": content}],
                "max_output_tokens": 16_000,
            }
            if tools is not None:
                value["tools"] = tools
                value["parallel_tool_calls"] = False
            if tool_choice is not None:
                value["tool_choice"] = tool_choice
            body = json.dumps(value).encode()
            request = Request(
                self.base_url.rstrip("/") + "/responses", data=body, method="POST",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            )
            try:
                with urlopen(request, timeout=1800) as response:
                    return json.load(response)
            except HTTPError as exc:
                last_error = exc
                if exc.code not in {401, 402, 403, 429, 500, 502, 503, 504}:
                    raise
        raise last_error

    @staticmethod
    def _output_text(response: dict) -> str:
        if isinstance(response.get("output_text"), str):
            return response["output_text"]
        parts = []
        for item in response.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    parts.append(content["text"])
        return "\n".join(parts)

    def _complete(self, system: str, content: str) -> str:
        return self._output_text(self._response(system, content)).strip()

    def intake(self, messages: list[dict[str, str]], force: bool = False,
               research: list[dict] | None = None) -> dict:
        transcript = "\n\n".join(
            f"{item['role'].title()} ({item['kind']}):\n{item['body']}" for item in messages
        )
        if research:
            transcript += "\n\nResearch briefing (compact scout results):\n" + "\n\n".join(
                f"Scout round {item['round']}.{item['position']} [{item['state']}]\n"
                f"Question: {item['prompt']}\nSummary: {item['summary']}" for item in research
            )
        if force:
            transcript += "\n\nInstruction: Draft now. State reasonable assumptions in the plan."
        response = self._response(
            INTAKE_SYSTEM, transcript, [] if force else [DELEGATE_RESEARCH],
            "none" if force else "auto",
        )
        for item in response.get("output", []):
            if item.get("type") != "function_call" or item.get("name") != "delegate_research":
                continue
            arguments = item.get("arguments", {})
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            tasks = arguments.get("tasks") if isinstance(arguments, dict) else None
            message = arguments.get("message") if isinstance(arguments, dict) else None
            if (not isinstance(tasks, list) or not 1 <= len(tasks) <= 4
                    or not all(isinstance(task, str) and task.strip() for task in tasks)):
                raise ValueError("planner returned invalid research tasks")
            if not isinstance(message, str) or not message.strip():
                raise ValueError("planner returned no delegation message")
            return {"status": "delegate", "message": message.strip(),
                    "tasks": [task.strip()[:4000] for task in tasks]}
        raw = self._output_text(response).strip()
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
