"""Argo Workflows API adapter using the pod's Kubernetes identity."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
import json
import ssl

from .models import AgentRun, ValidationError


@dataclass
class ArgoClient:
    namespace: str = "tools"
    api_server: str = "https://kubernetes.default.svc"
    token_path: str = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    ca_path: str = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        token = Path(self.token_path).read_text().strip()
        request = Request(
            self.api_server + path, method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        context = ssl.create_default_context(cafile=self.ca_path)
        with urlopen(request, timeout=30, context=context) as response:
            return json.load(response)

    def submit(self, run: AgentRun, harness: str) -> str:
        if harness not in {"contract", "pi", "opencode"}:
            raise ValidationError("unsupported harness")
        workflow = {
            "apiVersion": "argoproj.io/v1alpha1", "kind": "Workflow",
            "metadata": {
                "generateName": "agent-run-", "namespace": self.namespace,
                "labels": {"cogito.dev/run-id": run.run_id, "cogito.dev/harness": harness},
            },
            "spec": {
                "workflowTemplateRef": {"name": "agent-run-v1alpha6"},
                "arguments": {"parameters": [
                    {"name": "run-id", "value": run.run_id},
                    {"name": "harness", "value": harness},
                    {"name": "request", "value": json.dumps(run.as_dict(), sort_keys=True)},
                ]},
            },
        }
        result = self._call(
            "POST", f"/apis/argoproj.io/v1alpha1/namespaces/{self.namespace}/workflows", workflow)
        return result["metadata"]["name"]

    def find_run(self, run_id: str) -> str | None:
        selector = quote(f"cogito.dev/run-id={run_id}")
        result = self._call(
            "GET", f"/apis/argoproj.io/v1alpha1/namespaces/{self.namespace}/workflows"
            f"?labelSelector={selector}")
        names = sorted(item["metadata"]["name"] for item in result.get("items", []))
        if len(names) > 1:
            raise RuntimeError(f"multiple workflows found for run_id {run_id}")
        return names[0] if names else None

    def status(self, name: str) -> dict:
        return self._call(
            "GET", f"/apis/argoproj.io/v1alpha1/namespaces/{self.namespace}/workflows/{quote(name)}")

    def patch(self, name: str, patch: dict) -> dict:
        token = Path(self.token_path).read_text().strip()
        request = Request(
            self.api_server + f"/apis/argoproj.io/v1alpha1/namespaces/{self.namespace}/workflows/{quote(name)}",
            method="PATCH", data=json.dumps(patch).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/merge-patch+json"},
        )
        with urlopen(request, timeout=30, context=ssl.create_default_context(cafile=self.ca_path)) as response:
            return json.load(response)

    def cancel(self, name: str) -> dict:
        return self.patch(name, {"spec": {"shutdown": "Terminate"}})

    def resume(self, name: str) -> dict:
        return self.patch(name, {"spec": {"suspend": False}})

    def pause(self, name: str) -> dict:
        return self.patch(name, {"spec": {"suspend": True}})
