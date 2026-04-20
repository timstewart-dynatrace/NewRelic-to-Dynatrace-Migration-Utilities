"""
Dynatrace API Client — Gen3 default.

Composes the three Gen3 API surfaces used by the migrator:

  * Settings 2.0   (/api/v2/settings/objects)       → Gen3 schemas
  * Document API   (/platform/document/v1/...)      → Grail dashboards
  * Automation API (/platform/automation/v1/...)    → Workflows

Config v1 methods (alerting profiles, metric events, management zones,
problem notifications, classic dashboards/synthetics/SLOs) live in
`clients/legacy/config_v1_client.py` and are only reachable through the
`--legacy` CLI flag.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

from ._http import (
    DynatraceResponse,
    HttpTransport,
    ImportResult,
    OAuth2PlatformTokenProvider,
    platform_url,
    settings_v2_base,
)
from .automation_client import AutomationClient
from .document_client import DocumentClient
from .settings_v2_client import SettingsV2Client

logger = structlog.get_logger()


# Re-exports so callers can `from clients.dynatrace_client import DynatraceResponse`.
__all__ = [
    "DynatraceClient",
    "DynatraceResponse",
    "ImportResult",
    "OAuth2PlatformTokenProvider",
    "PreflightCheck",
]


@dataclass
class PreflightCheck:
    """Result of probing one Gen3 API surface.

    `scopes_min` — scopes the token must have for THIS preflight probe to succeed.
    `scopes_recommended` — scopes migrate also needs to actually write via this
    surface (preflight only reads; the full migrate path reads + writes).
    `diagnosis` — human-readable interpretation of `status_code` (e.g. "403 —
    token reached tenant but lacks required scope").
    `remediation` — ordered steps the operator should take when reachable is False.
    """

    api: str
    endpoint: str
    reachable: bool
    status_code: int
    error: Optional[str]
    scopes_min: List[str]
    scopes_recommended: List[str]
    diagnosis: str = ""
    remediation: List[str] = field(default_factory=list)


# Scope requirements per Gen3 surface. The `_min` set is what's needed for the
# preflight probe itself (a read). The `_recommended` set is what migrate needs
# end-to-end (read + write + anything downstream phases trigger through the
# surface, e.g. Grail reads from inside a workflow task).
_SETTINGS_SCOPES_MIN = ["settings:schemas:read", "settings:objects:read"]
_SETTINGS_SCOPES_RECOMMENDED = _SETTINGS_SCOPES_MIN + ["settings:objects:write"]

_DOCUMENT_SCOPES_MIN = ["document:documents:read"]
_DOCUMENT_SCOPES_RECOMMENDED = _DOCUMENT_SCOPES_MIN + ["document:documents:write"]

_AUTOMATION_SCOPES_MIN = ["automation:workflows:read"]
_AUTOMATION_SCOPES_RECOMMENDED = _AUTOMATION_SCOPES_MIN + [
    "automation:workflows:write",
    "automation:workflows:run",
]

# Grail storage scopes migrate uses during transform/import (log obfuscation
# lookups, entity lookups, SLO burn-rate queries). Not probed by preflight but
# surfaced in the end-of-run summary so operators provision them up front.
GRAIL_SCOPES_FULL_RUN = [
    "storage:logs:read",
    "storage:events:read",
    "storage:metrics:read",
    "storage:spans:read",
    "storage:entities:read",
    "storage:buckets:read",
]


def _diagnose(
    api: str,
    status_code: int,
    error: Optional[str],
    reachable: bool,
    scopes_min: List[str],
    endpoint: str,
    ui_path: str,
) -> "tuple[str, list[str]]":
    """Map an HTTP status + error to a one-line diagnosis and remediation steps."""
    if reachable:
        return ("OK — tenant responded 2xx with the minimum read scopes.", [])

    scope_list = ", ".join(scopes_min)
    if status_code == 0:
        diag = (
            "Could not reach the endpoint at all (DNS, TLS, or network error). "
            "The tenant URL may be wrong, or the environment may not expose "
            "this Gen3 surface."
        )
        steps = [
            f"Verify DYNATRACE_ENVIRONMENT_URL points to a SaaS/apps host: {endpoint}",
            f"Confirm the error message: {error or 'no detail'}",
            "If the tenant is a Managed tenant without Gen3, rerun migrate with --legacy.",
        ]
        return diag, steps

    if status_code in (401, 403):
        diag = (
            f"HTTP {status_code} — token reached the tenant but was refused. "
            f"Missing scope(s) required for {api}: {scope_list}."
        )
        steps = [
            f"In the Dynatrace tenant UI: {ui_path}",
            f"Required minimum scopes for this probe: {scope_list}",
            "Re-run: python3 migrate.py preflight",
        ]
        return diag, steps

    if status_code == 404:
        diag = (
            f"HTTP 404 — the {api} endpoint is not present on this tenant. "
            "Likely a Managed/Classic tenant that has not been upgraded to Gen3."
        )
        steps = [
            "Confirm with your Dynatrace account team whether this tenant runs Gen3 Platform APIs.",
            "Until upgrade, run migrate with --legacy so it targets Config v1 instead.",
        ]
        return diag, steps

    if 500 <= status_code < 600:
        diag = (
            f"HTTP {status_code} — tenant-side error. Scopes are likely correct "
            "but the service is degraded."
        )
        steps = [
            "Retry in a few minutes.",
            "Check Dynatrace status page and tenant health.",
        ]
        return diag, steps

    diag = (
        f"HTTP {status_code} — unexpected response. Inspect the raw error and "
        "compare against the scope list below."
    )
    steps = [
        f"Raw error: {error or 'none'}",
        f"Minimum scopes expected: {scope_list}",
    ]
    return diag, steps


class DynatraceClient:
    """Gen3 Dynatrace client — Settings 2.0 + Document + Automation."""

    def __init__(
        self,
        environment_url: str,
        api_token: Optional[str] = None,
        oauth: Optional[OAuth2PlatformTokenProvider] = None,
        rate_limit: float = 5.0,
    ) -> None:
        if not api_token and oauth is None:
            raise ValueError(
                "DynatraceClient requires either api_token or oauth credentials."
            )
        self.environment_url = environment_url.rstrip("/")
        self.transport = HttpTransport(
            rate_limit=rate_limit, api_token=api_token, oauth=oauth
        )

        self.settings = SettingsV2Client(self.environment_url, self.transport)
        self.documents = DocumentClient(self.environment_url, self.transport)
        self.automation = AutomationClient(self.environment_url, self.transport)

    # ------------------------------------------------------------------
    # Transformer-facing create helpers (Gen3 targets)
    # ------------------------------------------------------------------

    def create_anomaly_detector(self, envelope: Dict[str, Any]) -> ImportResult:
        return self.settings.create_anomaly_detector(envelope)

    def create_segment(self, envelope: Dict[str, Any]) -> ImportResult:
        return self.settings.create_segment(envelope)

    def create_iam_policy(self, envelope: Dict[str, Any]) -> ImportResult:
        return self.settings.create_iam_policy(envelope)

    def create_openpipeline_processor(
        self, envelope: Dict[str, Any]
    ) -> ImportResult:
        return self.settings.create_openpipeline_processor(envelope)

    def create_synthetic_test(self, envelope: Dict[str, Any]) -> ImportResult:
        return self.settings.create_synthetic_test(envelope)

    def create_slo(self, envelope: Dict[str, Any]) -> ImportResult:
        return self.settings.create_slo(envelope)

    def create_workflow(self, workflow: Dict[str, Any]) -> ImportResult:
        return self.automation.create_workflow(workflow)

    # ------------------------------------------------------------------
    # Phase 20 — unified delete dispatch (rollback completeness)
    # ------------------------------------------------------------------

    # Map of entity_type strings (as recorded in RollbackManifest entries
    # by the Phase 12 orchestrator) -> deletion behavior. New Gen3 entity
    # types added in later phases must register here so rollback covers
    # every type that the import path can create.
    _DELETE_KIND = {
        # Settings 2.0 objects (`builtin:*` schemas) — delete by objectId.
        "anomaly_detector": "settings",
        "segment": "settings",
        "iam_policy": "settings",
        "synthetic_test": "settings",
        "slo": "settings",
        "openpipeline_processor": "settings",
        # Document API.
        "dashboard": "document",
        # Automation API.
        "workflow": "automation",
    }

    def delete_entity(self, entity_type: str, entity_id: str) -> ImportResult:
        """Delete a previously-imported Gen3 entity by type + id.

        Used by the rollback engine. Unknown entity types return an
        `ImportResult` with `success=False` so the rollback log can record
        which manifest entries were skipped (and why).
        """
        kind = self._DELETE_KIND.get(entity_type)
        if kind is None:
            return ImportResult(
                entity_type=entity_type,
                entity_name=entity_id,
                success=False,
                error_message=(
                    f"No Gen3 delete handler for entity type '{entity_type}'. "
                    "Was this entity created by a legacy (--legacy) run? Use "
                    "`--legacy` on rollback to dispatch via LegacyDynatraceV1Client."
                ),
            )
        try:
            if kind == "settings":
                response = self.settings.delete_object(entity_id)
            elif kind == "document":
                response = self.documents.delete_document(entity_id)
            elif kind == "automation":
                response = self.automation.delete_workflow(entity_id)
            else:  # unreachable
                response = DynatraceResponse(data=None, status_code=0,
                                             error=f"Unknown delete kind: {kind}")

            return ImportResult(
                entity_type=entity_type,
                entity_name=entity_id,
                success=response.is_success,
                dynatrace_id=entity_id,
                error_message=None if response.is_success else response.error,
            )
        except Exception as exc:  # noqa: BLE001
            return ImportResult(
                entity_type=entity_type,
                entity_name=entity_id,
                success=False,
                error_message=f"Delete raised: {exc}",
            )

    def create_dashboard(
        self,
        dashboard_content: Dict[str, Any],
        tags: Optional[List[str]] = None,
        fallback_to_config_v1: bool = False,
    ) -> ImportResult:
        """Create a Gen3 Grail dashboard via Document API.

        Phase 25 additions:
        - `tags`: if non-empty, PUT to Document tags sub-resource after creation.
        - `fallback_to_config_v1`: if True and Document API fails, dispatch
          through LegacyDynatraceV1Client.create_dashboard (belt-and-suspenders
          for mixed-mode tenants).
        """
        result = self.documents.create_dashboard(dashboard_content)
        if result.success and tags:
            self.documents.put_tags(result.dynatrace_id, tags)
        if not result.success and fallback_to_config_v1:
            from clients.legacy import LegacyDynatraceV1Client
            legacy = LegacyDynatraceV1Client(
                api_token=self.transport._api_token or "",
                environment_url=self.environment_url,
            )
            return legacy.create_dashboard(dashboard_content)
        return result

    def list_synthetic_locations(
        self, scope: str = "ALL"
    ) -> List[Dict[str, Any]]:
        """List synthetic monitoring locations (PUBLIC, PRIVATE, or ALL).

        Phase 25 — closes Gen2-only capability #7 by querying the
        `/api/v2/synthetic/locations` endpoint (a classic API that
        exists on Gen3 tenants too).
        """
        results: List[Dict[str, Any]] = []
        if scope in ("ALL", "PUBLIC"):
            resp = self.transport.get(
                f"{self.environment_url}/api/v2/synthetic/locations",
                params={"type": "PUBLIC"},
            )
            if resp.is_success and isinstance(resp.data, dict):
                results.extend(resp.data.get("locations", []) or [])
        if scope in ("ALL", "PRIVATE"):
            resp = self.transport.get(
                f"{self.environment_url}/api/v2/synthetic/locations",
                params={"type": "PRIVATE"},
            )
            if resp.is_success and isinstance(resp.data, dict):
                results.extend(resp.data.get("locations", []) or [])
        return results

    # ------------------------------------------------------------------
    # Connectivity + backup
    # ------------------------------------------------------------------

    def validate_connection(self) -> bool:
        """Lightweight health check — hits Settings 2.0 schemas endpoint."""
        response = self.transport.get(
            f"{settings_v2_base(self.environment_url)}/settings/schemas",
            params={"pageSize": 1},
        )
        return response.is_success

    def preflight_gen3(self) -> List[PreflightCheck]:
        """Probe whether the target tenant exposes Gen3 Platform APIs.

        Returns one :class:`PreflightCheck` per API probed, with the scopes
        required (minimum + recommended) and a remediation block the CLI can
        render. The `--legacy` preflight check in Phase 14 consumes this.
        """
        platform = platform_url(self.environment_url)
        checks: List[PreflightCheck] = [
            self._probe(
                api="settings_v2",
                endpoint=f"{settings_v2_base(self.environment_url)}/settings/schemas",
                params={"pageSize": 1},
                prefer_oauth=False,
                scopes_min=_SETTINGS_SCOPES_MIN,
                scopes_recommended=_SETTINGS_SCOPES_RECOMMENDED,
                ui_path=(
                    "Access Tokens → your token → Scopes → add "
                    "'settings:schemas:read' and 'settings:objects:read' "
                    "(add 'settings:objects:write' for migrate runs)."
                ),
            ),
            self._probe(
                api="document_api",
                endpoint=f"{platform}/platform/document/v1/documents",
                params={"pageSize": 1},
                prefer_oauth=True,
                scopes_min=_DOCUMENT_SCOPES_MIN,
                scopes_recommended=_DOCUMENT_SCOPES_RECOMMENDED,
                ui_path=(
                    "Access Tokens → your token → Scopes → add "
                    "'document:documents:read' "
                    "(add 'document:documents:write' for migrate runs)."
                ),
            ),
            self._probe(
                api="automation_api",
                endpoint=f"{platform}/platform/automation/v1/workflows",
                params={"pageSize": 1},
                prefer_oauth=True,
                scopes_min=_AUTOMATION_SCOPES_MIN,
                scopes_recommended=_AUTOMATION_SCOPES_RECOMMENDED,
                ui_path=(
                    "Access Tokens → your token → Scopes → add "
                    "'automation:workflows:read' "
                    "(add ':write' and ':run' for migrate runs)."
                ),
            ),
        ]
        return checks

    def _probe(
        self,
        api: str,
        endpoint: str,
        params: Dict[str, Any],
        prefer_oauth: bool,
        scopes_min: List[str],
        scopes_recommended: List[str],
        ui_path: str,
    ) -> PreflightCheck:
        """Hit one Gen3 endpoint and wrap the response with scope + remediation."""
        try:
            response = self.transport.get(
                endpoint, params=params, prefer_oauth=prefer_oauth
            )
            status = response.status_code
            error = response.error
            reachable = response.is_success
        except Exception as exc:  # noqa: BLE001
            status = 0
            error = str(exc)
            reachable = False

        diagnosis, remediation = _diagnose(
            api=api,
            status_code=status,
            error=error,
            reachable=reachable,
            scopes_min=scopes_min,
            endpoint=endpoint,
            ui_path=ui_path,
        )
        return PreflightCheck(
            api=api,
            endpoint=endpoint,
            reachable=reachable,
            status_code=status,
            error=error,
            scopes_min=scopes_min,
            scopes_recommended=scopes_recommended,
            diagnosis=diagnosis,
            remediation=remediation,
        )

    def backup_all(self) -> Dict[str, Any]:
        """Backup Gen3 configuration only.

        Legacy (Config v1) entities are not included — use
        `clients.legacy.config_v1_client.LegacyDynatraceV1Client.backup_all`
        when running with `--legacy`.
        """
        logger.info("Starting Dynatrace Gen3 backup")
        backup = {
            "metadata": {
                "environment_url": self.environment_url,
                "backup_timestamp": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                ),
                "tool_version": "2.0.0",
                "tier": "gen3",
            },
            "dashboards": self.documents.list_documents(
                filter_expr="type=='dashboard'"
            ),
            "notebooks": self.documents.list_documents(
                filter_expr="type=='notebook'"
            ),
            "workflows": self.automation.list_workflows(),
            "anomaly_detectors": self.settings.list_objects(
                "builtin:davis.anomaly-detectors"
            ),
            "segments": self.settings.list_objects("builtin:segment"),
            "slos": self.settings.list_objects("builtin:monitoring.slo"),
            "synthetic_tests": self.settings.list_objects(
                "builtin:synthetic_test"
            ),
            "openpipeline_logs": self.settings.list_objects(
                "builtin:openpipeline.logs.pipelines"
            ),
        }
        logger.info(
            "Gen3 backup complete",
            dashboards=len(backup["dashboards"]),
            workflows=len(backup["workflows"]),
            anomaly_detectors=len(backup["anomaly_detectors"]),
        )
        return backup

    # ------------------------------------------------------------------
    # Generic HTTP proxies for callers that still want raw access
    # ------------------------------------------------------------------

    def get(self, url: str, params: Optional[Dict[str, Any]] = None) -> DynatraceResponse:
        return self.transport.get(url, params=params)

    def post(self, url: str, data: Dict[str, Any]) -> DynatraceResponse:
        return self.transport.post(url, data)

    def put(self, url: str, data: Dict[str, Any]) -> DynatraceResponse:
        return self.transport.put(url, data)

    def delete(self, url: str) -> DynatraceResponse:
        return self.transport.delete(url)
