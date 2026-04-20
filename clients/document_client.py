"""Dynatrace Document API v1 client (`/platform/document/v1/documents`).

Gen3-native dashboards and notebooks live here. Uses `pageKey` (not
`nextPageKey`) for pagination, per the Document API convention.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import structlog

from ._http import DynatraceResponse, HttpTransport, ImportResult, platform_url

logger = structlog.get_logger()


class DocumentClient:
    def __init__(self, environment_url: str, transport: HttpTransport) -> None:
        self.base = f"{platform_url(environment_url)}/platform/document/v1/documents"
        self.http = transport

    def list_documents(
        self,
        filter_expr: str = "type=='dashboard'",
        page_size: int = 1000,
        sort: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"filter": filter_expr, "pageSize": page_size}
        if sort:
            params["sort"] = sort

        results: List[Dict[str, Any]] = []
        page_key: Optional[str] = None
        while True:
            call_params = dict(params)
            if page_key:
                call_params["pageKey"] = page_key
            response = self.http.get(self.base, params=call_params, prefer_oauth=True)
            if not response.is_success or not isinstance(response.data, dict):
                break
            results.extend(response.data.get("documents", []) or [])
            page_key = response.data.get("nextPageKey")
            if not page_key:
                break
        return results

    def get_document(self, doc_id: str) -> DynatraceResponse:
        return self.http.get(f"{self.base}/{doc_id}", prefer_oauth=True)

    def create_dashboard(self, dashboard_content: Dict[str, Any]) -> ImportResult:
        """Create a Gen3 Grail dashboard (type='dashboard').

        The Gen3 Document API (``/platform/document/v1/documents``) rejects
        ``application/json`` bodies with **415 Unsupported Media Type** and
        expects ``multipart/form-data`` with separate parts for the metadata
        (``name``, ``type``, ``isPrivate``) and the dashboard payload
        (``content``). Mirrors the shape the official
        ``@dynatrace-sdk/client-document`` SDK sends on the wire.
        """
        name = dashboard_content.get("name", "Untitled Dashboard")
        content_json = json.dumps(dashboard_content)
        files = {
            "name": (None, name),
            "type": (None, "dashboard"),
            "isPrivate": (None, "false"),
            "content": ("content.json", content_json, "application/json"),
        }
        response = self.http.post_multipart(self.base, files, prefer_oauth=True)
        if response.is_success and isinstance(response.data, dict):
            return ImportResult(
                entity_type="dashboard",
                entity_name=name,
                success=True,
                dynatrace_id=response.data.get("id"),
            )
        return ImportResult(
            entity_type="dashboard",
            entity_name=name,
            success=False,
            error_message=response.error,
        )

    def update_dashboard(
        self, doc_id: str, dashboard_content: Dict[str, Any]
    ) -> ImportResult:
        name = dashboard_content.get("name", "Untitled Dashboard")
        body = {
            "name": name,
            "content": json.dumps(dashboard_content),
            "isPrivate": False,
        }
        response = self.http.put(
            f"{self.base}/{doc_id}", body, prefer_oauth=True
        )
        if response.is_success:
            return ImportResult(
                entity_type="dashboard",
                entity_name=name,
                success=True,
                dynatrace_id=doc_id,
            )
        return ImportResult(
            entity_type="dashboard",
            entity_name=name,
            success=False,
            error_message=response.error,
        )

    def delete_document(
        self, doc_id: str, optimistic_version: Optional[str] = None
    ) -> DynatraceResponse:
        params: Dict[str, Any] = {}
        if optimistic_version:
            params["optimisticLockingVersion"] = optimistic_version
        return self.http.delete(
            f"{self.base}/{doc_id}", params=params, prefer_oauth=True
        )

    # Phase 25 — Document-level tag/attribute management.

    def put_tags(
        self, doc_id: str, tags: List[str]
    ) -> DynatraceResponse:
        """Apply tags to a Document (dashboard or notebook).

        Uses the Document API's tag sub-resource. Tags replace the
        existing set (PUT semantics).
        """
        return self.http.put(
            f"{self.base}/{doc_id}/tags",
            {"tags": tags},
            prefer_oauth=True,
        )
