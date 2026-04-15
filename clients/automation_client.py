"""Dynatrace Automation API v1 client (`/platform/automation/v1/workflows`).

Workflows are the Gen3 replacement for Alerting Profiles and Problem
Notifications. Requires a platform (OAuth2) bearer token.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog

from ._http import DynatraceResponse, HttpTransport, ImportResult, platform_url

logger = structlog.get_logger()


class AutomationClient:
    def __init__(self, environment_url: str, transport: HttpTransport) -> None:
        self.base = f"{platform_url(environment_url)}/platform/automation/v1/workflows"
        self.http = transport

    def list_workflows(self, page_size: int = 200) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"pageSize": page_size}
        results: List[Dict[str, Any]] = []
        next_key: Optional[str] = None
        while True:
            call_params = dict(params)
            if next_key:
                call_params["nextPageKey"] = next_key
            response = self.http.get(
                self.base, params=call_params, prefer_oauth=True
            )
            if not response.is_success or not isinstance(response.data, dict):
                break
            results.extend(response.data.get("workflows", []) or [])
            next_key = response.data.get("nextPageKey")
            if not next_key:
                break
        return results

    def get_workflow(self, workflow_id: str) -> DynatraceResponse:
        return self.http.get(f"{self.base}/{workflow_id}", prefer_oauth=True)

    def create_workflow(self, workflow: Dict[str, Any]) -> ImportResult:
        name = workflow.get("title", "Untitled Workflow")
        response = self.http.post(self.base, workflow, prefer_oauth=True)
        if response.is_success and isinstance(response.data, dict):
            return ImportResult(
                entity_type="workflow",
                entity_name=name,
                success=True,
                dynatrace_id=response.data.get("id"),
            )
        return ImportResult(
            entity_type="workflow",
            entity_name=name,
            success=False,
            error_message=response.error,
        )

    def update_workflow(
        self, workflow_id: str, workflow: Dict[str, Any]
    ) -> ImportResult:
        name = workflow.get("title", "Untitled Workflow")
        response = self.http.put(
            f"{self.base}/{workflow_id}", workflow, prefer_oauth=True
        )
        if response.is_success:
            return ImportResult(
                entity_type="workflow",
                entity_name=name,
                success=True,
                dynatrace_id=workflow_id,
            )
        return ImportResult(
            entity_type="workflow",
            entity_name=name,
            success=False,
            error_message=response.error,
        )

    def delete_workflow(self, workflow_id: str) -> DynatraceResponse:
        return self.http.delete(
            f"{self.base}/{workflow_id}", prefer_oauth=True
        )
