"""Dynatrace Settings API v2 client.

Covers CRUD over `/api/v2/settings/objects` with nextPageKey pagination.
All Gen3 schemas (`builtin:davis.anomaly-detectors`, `builtin:segment`,
`builtin:openpipeline.*`, `builtin:synthetic_test`, `builtin:monitoring.slo`,
`builtin:iam.policy`) are addressed through this client.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog

from ._http import DynatraceResponse, HttpTransport, ImportResult

logger = structlog.get_logger()


class SettingsV2Client:
    def __init__(self, environment_url: str, transport: HttpTransport) -> None:
        self.base = f"{environment_url.rstrip('/')}/api/v2"
        self.http = transport

    # ------------------------------------------------------------------
    # Raw helpers
    # ------------------------------------------------------------------

    def list_objects(
        self,
        schema_id: str,
        scope: Optional[str] = None,
        filter_expr: Optional[str] = None,
        page_size: int = 500,
    ) -> List[Dict[str, Any]]:
        url = f"{self.base}/settings/objects"
        params: Dict[str, Any] = {"schemaIds": schema_id, "pageSize": page_size}
        if scope:
            params["scopes"] = scope
        if filter_expr:
            params["filter"] = filter_expr

        results: List[Dict[str, Any]] = []
        next_key: Optional[str] = None
        while True:
            call_params = {"nextPageKey": next_key} if next_key else params
            response = self.http.get(url, params=call_params)
            if not response.is_success or not isinstance(response.data, dict):
                break
            results.extend(response.data.get("items", []) or [])
            next_key = response.data.get("nextPageKey")
            if not next_key:
                break
        return results

    def create_object(
        self,
        schema_id: str,
        value: Dict[str, Any],
        scope: str = "environment",
    ) -> DynatraceResponse:
        url = f"{self.base}/settings/objects"
        payload = [{"schemaId": schema_id, "scope": scope, "value": value}]
        return self.http.post(url, payload)

    def create_envelope(self, envelope: Dict[str, Any]) -> DynatraceResponse:
        """Create from a pre-built `{schemaId, scope, value}` envelope.

        Transformers emit exactly this shape.
        """
        url = f"{self.base}/settings/objects"
        return self.http.post(url, [envelope])

    def update_object(
        self, object_id: str, value: Dict[str, Any]
    ) -> DynatraceResponse:
        url = f"{self.base}/settings/objects/{object_id}"
        return self.http.put(url, {"value": value})

    def delete_object(self, object_id: str) -> DynatraceResponse:
        url = f"{self.base}/settings/objects/{object_id}"
        return self.http.delete(url)

    # ------------------------------------------------------------------
    # Transformer-facing create helpers (Gen3 targets)
    # ------------------------------------------------------------------

    def create_anomaly_detector(
        self, envelope: Dict[str, Any]
    ) -> ImportResult:
        return self._import(envelope, entity_type="anomaly_detector")

    def create_segment(self, envelope: Dict[str, Any]) -> ImportResult:
        return self._import(envelope, entity_type="segment")

    def create_iam_policy(self, envelope: Dict[str, Any]) -> ImportResult:
        return self._import(envelope, entity_type="iam_policy")

    def create_openpipeline_processor(
        self, envelope: Dict[str, Any]
    ) -> ImportResult:
        return self._import(envelope, entity_type="openpipeline_processor")

    def create_synthetic_test(self, envelope: Dict[str, Any]) -> ImportResult:
        return self._import(envelope, entity_type="synthetic_test")

    def create_slo(self, envelope: Dict[str, Any]) -> ImportResult:
        return self._import(envelope, entity_type="slo")

    # ------------------------------------------------------------------

    def _import(self, envelope: Dict[str, Any], entity_type: str) -> ImportResult:
        name = envelope.get("value", {}).get("name", envelope.get("detectorId", "Unknown"))
        response = self.create_envelope(envelope)
        if response.is_success and isinstance(response.data, list) and response.data:
            return ImportResult(
                entity_type=entity_type,
                entity_name=name,
                success=True,
                dynatrace_id=response.data[0].get("objectId"),
            )
        return ImportResult(
            entity_type=entity_type,
            entity_name=name,
            success=False,
            error_message=response.error,
        )
