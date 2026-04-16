"""
Legacy Dynatrace API Client (Config v1 + classic Settings 2.0 schemas).

Preserved for the `--legacy` CLI flag on tenants without Gen3 features.
Emits Alerting Profiles, Metric Events, Management Zones, Problem
Notifications, Config v1 dashboards, Config v1 synthetic monitors, and
Config v1 SLOs. Do NOT import from default (Gen3) code paths — use
`clients.dynatrace_client.DynatraceClient` instead.
"""

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
import structlog
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = structlog.get_logger()


@dataclass
class DynatraceResponse:
    """Response wrapper for Dynatrace API calls."""
    data: Optional[Any]
    status_code: int
    error: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300


@dataclass
class ImportResult:
    """Result of an import operation."""
    entity_type: str
    entity_name: str
    success: bool
    dynatrace_id: Optional[str] = None
    error_message: Optional[str] = None


class LegacyDynatraceV1Client:
    """
    Legacy Dynatrace client — Config v1 + classic Settings 2.0 schemas.

    Retained for `--legacy` mode only. Emits:
    - Config v1 dashboards (fallback) and Config v1 synthetics/SLOs
    - Alerting Profiles, Metric Events, Management Zones (classic schemas)
    - Problem Notification integrations (classic schemas)
    """

    def __init__(
        self,
        api_token: str,
        environment_url: str,
        rate_limit: float = 5.0
    ):
        self.api_token = api_token
        self.environment_url = environment_url.rstrip("/")
        self.rate_limit = rate_limit
        self._last_request_time = 0.0

        # API endpoints
        self.api_v2 = f"{self.environment_url}/api/v2"
        self.config_api = f"{self.environment_url}/api/config/v1"

        # Configure session with retries
        self.session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)
        self.session.headers.update({
            "Content-Type": "application/json",
            "Authorization": f"Api-Token {self.api_token}"
        })

    def _rate_limit_wait(self):
        """Implement rate limiting between requests."""
        if self.rate_limit > 0:
            elapsed = time.time() - self._last_request_time
            min_interval = 1.0 / self.rate_limit
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    def _request(
        self,
        method: str,
        url: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> DynatraceResponse:
        """Make an API request to Dynatrace."""
        self._rate_limit_wait()

        try:
            response = self.session.request(
                method=method,
                url=url,
                json=data,
                params=params,
                timeout=60
            )

            response_data = None
            if response.content:
                try:
                    response_data = response.json()
                except json.JSONDecodeError:
                    response_data = response.text

            if response.status_code >= 400:
                error_msg = str(response_data) if response_data else response.reason
                return DynatraceResponse(
                    data=response_data,
                    status_code=response.status_code,
                    error=error_msg
                )

            return DynatraceResponse(
                data=response_data,
                status_code=response.status_code
            )

        except requests.exceptions.RequestException as e:
            logger.error("Dynatrace API error", error=str(e))
            return DynatraceResponse(
                data=None,
                status_code=0,
                error=str(e)
            )

    def get(self, url: str, params: Optional[Dict] = None) -> DynatraceResponse:
        """HTTP GET request."""
        return self._request("GET", url, params=params)

    def post(self, url: str, data: Dict) -> DynatraceResponse:
        """HTTP POST request."""
        return self._request("POST", url, data=data)

    def put(self, url: str, data: Dict) -> DynatraceResponse:
        """HTTP PUT request."""
        return self._request("PUT", url, data=data)

    def delete(self, url: str) -> DynatraceResponse:
        """HTTP DELETE request."""
        return self._request("DELETE", url)

    # =========================================================================
    # Settings API v2 Methods
    # =========================================================================

    def get_settings_schemas(self) -> List[Dict[str, Any]]:
        """Get all available settings schemas."""
        url = f"{self.api_v2}/settings/schemas"
        response = self.get(url)

        if response.is_success:
            return response.data.get("items", [])
        return []

    def get_settings_objects(
        self,
        schema_id: str,
        scope: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get settings objects for a schema."""
        url = f"{self.api_v2}/settings/objects"
        params = {"schemaIds": schema_id}
        if scope:
            params["scopes"] = scope

        all_objects = []
        next_page_key = None

        while True:
            if next_page_key:
                params["nextPageKey"] = next_page_key

            response = self.get(url, params=params)

            if not response.is_success:
                break

            items = response.data.get("items", [])
            all_objects.extend(items)

            next_page_key = response.data.get("nextPageKey")
            if not next_page_key:
                break

        return all_objects

    def create_settings_object(
        self,
        schema_id: str,
        value: Dict[str, Any],
        scope: str = "environment"
    ) -> DynatraceResponse:
        """Create a settings object."""
        url = f"{self.api_v2}/settings/objects"
        payload = [{
            "schemaId": schema_id,
            "scope": scope,
            "value": value
        }]

        return self.post(url, payload)

    def update_settings_object(
        self,
        object_id: str,
        value: Dict[str, Any]
    ) -> DynatraceResponse:
        """Update a settings object."""
        url = f"{self.api_v2}/settings/objects/{object_id}"
        return self.put(url, {"value": value})

    # =========================================================================
    # Dashboard Methods
    # =========================================================================

    def create_dashboard(self, dashboard: Dict[str, Any]) -> ImportResult:
        """Create a dashboard in Dynatrace.

        Tries Documents API v1 first (Platform), falls back to Config API v1.
        """
        name = dashboard.get("dashboardMetadata", {}).get("name", "Unknown")

        # Try Documents API first (newer, supports Grail dashboards)
        result = self.create_dashboard_v2(dashboard)
        if result.success:
            return result

        # Fallback to Config API v1
        url = f"{self.config_api}/dashboards"
        response = self.post(url, dashboard)

        if response.is_success:
            dashboard_id = response.data.get("id")
            return ImportResult(
                entity_type="dashboard",
                entity_name=name,
                success=True,
                dynatrace_id=dashboard_id
            )
        else:
            return ImportResult(
                entity_type="dashboard",
                entity_name=name,
                success=False,
                error_message=response.error
            )

    def create_dashboard_v2(self, dashboard: Dict[str, Any]) -> ImportResult:
        """Create a dashboard via Documents API v1 (Platform).

        Uses /platform/document/v1/documents for Grail-compatible dashboards.
        Requires OAuth token (Bearer auth).
        """
        name = dashboard.get("dashboardMetadata", {}).get("name", "Unknown")
        platform_url = self.environment_url.replace('.live.', '.apps.')
        url = f"{platform_url}/platform/document/v1/documents"

        doc_payload = {
            "name": name,
            "type": "dashboard",
            "content": json.dumps(dashboard),
            "isPrivate": not dashboard.get("dashboardMetadata", {}).get("shared", False),
        }

        response = self.post(url, doc_payload)

        if response.is_success:
            doc_id = response.data.get("id") if response.data else None
            return ImportResult(
                entity_type="dashboard",
                entity_name=name,
                success=True,
                dynatrace_id=doc_id
            )
        else:
            return ImportResult(
                entity_type="dashboard",
                entity_name=name,
                success=False,
                error_message=response.error
            )

    def update_dashboard_v2(self, doc_id: str, dashboard: Dict[str, Any]) -> ImportResult:
        """Update a dashboard via Documents API v1."""
        name = dashboard.get("dashboardMetadata", {}).get("name", "Unknown")
        platform_url = self.environment_url.replace('.live.', '.apps.')
        url = f"{platform_url}/platform/document/v1/documents/{doc_id}"

        doc_payload = {
            "name": name,
            "content": json.dumps(dashboard),
            "isPrivate": not dashboard.get("dashboardMetadata", {}).get("shared", False),
        }

        response = self.put(url, doc_payload)

        if response.is_success:
            return ImportResult(
                entity_type="dashboard",
                entity_name=name,
                success=True,
                dynatrace_id=doc_id
            )
        else:
            return ImportResult(
                entity_type="dashboard",
                entity_name=name,
                success=False,
                error_message=response.error
            )

    def get_all_dashboards(self) -> List[Dict[str, Any]]:
        """Get all dashboards for backup purposes."""
        url = f"{self.config_api}/dashboards"
        response = self.get(url)

        if response.is_success:
            dashboards = []
            for item in response.data.get("dashboards", []):
                # Get full dashboard definition
                full_url = f"{self.config_api}/dashboards/{item['id']}"
                full_response = self.get(full_url)
                if full_response.is_success:
                    dashboards.append(full_response.data)
            return dashboards
        return []

    # =========================================================================
    # Alerting / Metric Events Methods
    # =========================================================================

    def create_metric_event(self, metric_event: Dict[str, Any]) -> ImportResult:
        """Create a metric event (alert) in Dynatrace."""
        # Use Settings API v2 for metric events
        schema_id = "builtin:anomaly-detection.metric-events"

        response = self.create_settings_object(
            schema_id=schema_id,
            value=metric_event
        )

        if response.is_success:
            created_items = response.data
            if created_items and len(created_items) > 0:
                return ImportResult(
                    entity_type="metric_event",
                    entity_name=metric_event.get("summary", "Unknown"),
                    success=True,
                    dynatrace_id=created_items[0].get("objectId")
                )

        return ImportResult(
            entity_type="metric_event",
            entity_name=metric_event.get("summary", "Unknown"),
            success=False,
            error_message=response.error
        )

    def create_alerting_profile(self, profile: Dict[str, Any]) -> ImportResult:
        """Create an alerting profile in Dynatrace."""
        schema_id = "builtin:alerting.profile"

        response = self.create_settings_object(
            schema_id=schema_id,
            value=profile
        )

        if response.is_success:
            created_items = response.data
            if created_items and len(created_items) > 0:
                return ImportResult(
                    entity_type="alerting_profile",
                    entity_name=profile.get("name", "Unknown"),
                    success=True,
                    dynatrace_id=created_items[0].get("objectId")
                )

        return ImportResult(
            entity_type="alerting_profile",
            entity_name=profile.get("name", "Unknown"),
            success=False,
            error_message=response.error
        )

    # =========================================================================
    # Synthetic Monitor Methods
    # =========================================================================

    def create_http_monitor(self, monitor: Dict[str, Any]) -> ImportResult:
        """Create an HTTP synthetic monitor."""
        url = f"{self.environment_url}/api/v1/synthetic/monitors"
        response = self.post(url, monitor)

        if response.is_success:
            return ImportResult(
                entity_type="http_monitor",
                entity_name=monitor.get("name", "Unknown"),
                success=True,
                dynatrace_id=response.data.get("entityId")
            )
        else:
            return ImportResult(
                entity_type="http_monitor",
                entity_name=monitor.get("name", "Unknown"),
                success=False,
                error_message=response.error
            )

    def create_browser_monitor(self, monitor: Dict[str, Any]) -> ImportResult:
        """Create a browser synthetic monitor."""
        url = f"{self.environment_url}/api/v1/synthetic/monitors"
        response = self.post(url, monitor)

        if response.is_success:
            return ImportResult(
                entity_type="browser_monitor",
                entity_name=monitor.get("name", "Unknown"),
                success=True,
                dynatrace_id=response.data.get("entityId")
            )
        else:
            return ImportResult(
                entity_type="browser_monitor",
                entity_name=monitor.get("name", "Unknown"),
                success=False,
                error_message=response.error
            )

    def get_synthetic_locations(self) -> List[Dict[str, Any]]:
        """Get available synthetic monitoring locations."""
        url = f"{self.environment_url}/api/v1/synthetic/locations"
        response = self.get(url)

        if response.is_success:
            return response.data.get("locations", [])
        return []

    # =========================================================================
    # SLO Methods
    # =========================================================================

    def create_slo(self, slo: Dict[str, Any]) -> ImportResult:
        """Create an SLO in Dynatrace."""
        url = f"{self.api_v2}/slo"
        response = self.post(url, slo)

        if response.is_success:
            return ImportResult(
                entity_type="slo",
                entity_name=slo.get("name", "Unknown"),
                success=True,
                dynatrace_id=response.data.get("id")
            )
        else:
            return ImportResult(
                entity_type="slo",
                entity_name=slo.get("name", "Unknown"),
                success=False,
                error_message=response.error
            )

    def get_all_slos(self) -> List[Dict[str, Any]]:
        """Get all SLOs for backup purposes."""
        url = f"{self.api_v2}/slo"
        all_slos = []
        next_page_key = None

        while True:
            params = {}
            if next_page_key:
                params["nextPageKey"] = next_page_key

            response = self.get(url, params=params)

            if not response.is_success:
                break

            slos = response.data.get("slo", [])
            all_slos.extend(slos)

            next_page_key = response.data.get("nextPageKey")
            if not next_page_key:
                break

        return all_slos

    # =========================================================================
    # Management Zone Methods
    # =========================================================================

    def create_management_zone(self, mz: Dict[str, Any]) -> ImportResult:
        """Create a management zone in Dynatrace."""
        schema_id = "builtin:management-zones"

        response = self.create_settings_object(
            schema_id=schema_id,
            value=mz
        )

        if response.is_success:
            created_items = response.data
            if created_items and len(created_items) > 0:
                return ImportResult(
                    entity_type="management_zone",
                    entity_name=mz.get("name", "Unknown"),
                    success=True,
                    dynatrace_id=created_items[0].get("objectId")
                )

        return ImportResult(
            entity_type="management_zone",
            entity_name=mz.get("name", "Unknown"),
            success=False,
            error_message=response.error
        )

    # =========================================================================
    # Notification / Integration Methods
    # =========================================================================

    def create_notification_integration(
        self,
        integration_type: str,
        config: Dict[str, Any]
    ) -> ImportResult:
        """Create a notification integration."""
        # Map integration types to schema IDs
        schema_map = {
            "email": "builtin:problem.notifications.email",
            "slack": "builtin:problem.notifications.slack",
            "pagerduty": "builtin:problem.notifications.pager-duty",
            "webhook": "builtin:problem.notifications.webhook",
            "jira": "builtin:problem.notifications.jira",
            "servicenow": "builtin:problem.notifications.service-now",
            "opsgenie": "builtin:problem.notifications.ops-genie",
            "victorops": "builtin:problem.notifications.victor-ops",
        }

        schema_id = schema_map.get(integration_type.lower())
        if not schema_id:
            return ImportResult(
                entity_type="notification",
                entity_name=config.get("name", "Unknown"),
                success=False,
                error_message=f"Unknown integration type: {integration_type}"
            )

        response = self.create_settings_object(
            schema_id=schema_id,
            value=config
        )

        if response.is_success:
            created_items = response.data
            if created_items and len(created_items) > 0:
                return ImportResult(
                    entity_type="notification",
                    entity_name=config.get("name", "Unknown"),
                    success=True,
                    dynatrace_id=created_items[0].get("objectId")
                )

        return ImportResult(
            entity_type="notification",
            entity_name=config.get("name", "Unknown"),
            success=False,
            error_message=response.error
        )

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def validate_connection(self) -> bool:
        """Validate API token and connectivity."""
        url = f"{self.api_v2}/settings/schemas"
        response = self.get(url, params={"pageSize": 1})
        return response.is_success

    def backup_all(self) -> Dict[str, Any]:
        """Backup all supported configurations from Dynatrace."""
        logger.info("Starting Dynatrace backup")

        backup_data = {
            "metadata": {
                "environment_url": self.environment_url,
                "backup_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "tool_version": "1.0.0"
            },
            "dashboards": self.get_all_dashboards(),
            "slos": self.get_all_slos(),
            "alerting_profiles": self.get_settings_objects("builtin:alerting.profile"),
            "metric_events": self.get_settings_objects("builtin:anomaly-detection.metric-events"),
            "management_zones": self.get_settings_objects("builtin:management-zones"),
        }

        logger.info(
            "Backup complete",
            dashboards=len(backup_data["dashboards"]),
            slos=len(backup_data["slos"])
        )

        return backup_data
