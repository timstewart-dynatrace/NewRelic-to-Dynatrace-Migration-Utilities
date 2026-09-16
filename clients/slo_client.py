"""Dynatrace Platform SLO API client (`/platform/slo/v1/slos`).

Gen3 replacement for classic `builtin:monitoring.slo` Settings objects.
Requires a platform bearer token with `slo:slos:read` / `slo:slos:write`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog

from ._http import DynatraceResponse, HttpTransport, ImportResult, platform_url

logger = structlog.get_logger()


class SloClient:
    def __init__(self, environment_url: str, transport: HttpTransport) -> None:
        self.base = f"{platform_url(environment_url)}/platform/slo/v1/slos"
        self.http = transport

    def list_slos(self, page_size: int = 500) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        next_key: Optional[str] = None
        while True:
            # nextPageKey carries the original query; send it alone.
            params: Dict[str, Any] = {"nextPageKey": next_key} if next_key else {"pageSize": page_size}
            response = self.http.get(self.base, params=params, prefer_oauth=True)
            if not response.is_success or not isinstance(response.data, dict):
                break
            results.extend(response.data.get("slos", response.data.get("items", [])) or [])
            next_key = response.data.get("nextPageKey")
            if not next_key:
                break
        return results

    def create_slo(self, slo: Dict[str, Any]) -> ImportResult:
        name = slo.get("name", "Untitled SLO")
        response = self.http.post(self.base, slo, prefer_oauth=True)
        if response.is_success and isinstance(response.data, dict):
            return ImportResult(
                entity_type="slo",
                entity_name=name,
                success=True,
                dynatrace_id=response.data.get("id"),
            )
        return ImportResult(
            entity_type="slo",
            entity_name=name,
            success=False,
            error_message=response.error,
        )

    def get_slo(self, slo_id: str) -> DynatraceResponse:
        return self.http.get(f"{self.base}/{slo_id}", prefer_oauth=True)

    def delete_slo(
        self, slo_id: str, optimistic_version: Optional[str] = None
    ) -> DynatraceResponse:
        """Delete an SLO. The API requires the current optimistic-locking
        version; it is looked up when not supplied."""
        if not optimistic_version:
            current = self.get_slo(slo_id)
            if not current.is_success:
                return current
            if isinstance(current.data, dict):
                optimistic_version = current.data.get("version")
        params: Dict[str, Any] = {}
        if optimistic_version:
            params["optimisticLockingVersion"] = optimistic_version
        return self.http.delete(
            f"{self.base}/{slo_id}", params=params, prefer_oauth=True
        )
