"""
New Relic NerdGraph API Client.

Provides methods to export all configuration entities from New Relic
using the NerdGraph GraphQL API.
"""

import json
import time
from typing import Any, Dict, List, Optional, Generator
from dataclasses import dataclass
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import structlog

logger = structlog.get_logger()


@dataclass
class NerdGraphResponse:
    """Response wrapper for NerdGraph API calls."""
    data: Optional[Dict[str, Any]]
    errors: Optional[List[Dict[str, Any]]]

    @property
    def is_success(self) -> bool:
        return self.errors is None or len(self.errors) == 0


class NewRelicClient:
    """
    Client for interacting with New Relic's NerdGraph GraphQL API.

    Supports exporting:
    - Dashboards
    - Alert Policies & Conditions
    - Synthetic Monitors
    - SLOs
    - Workloads
    - Notification Channels
    - Entity metadata
    """

    def __init__(
        self,
        api_key: str,
        account_id: str,
        region: str = "US",
        rate_limit: float = 5.0
    ):
        self.api_key = api_key
        self.account_id = account_id
        self.region = region.upper()
        self.rate_limit = rate_limit
        self._last_request_time = 0.0

        # Set endpoint based on region
        if self.region == "EU":
            self.graphql_endpoint = "https://api.eu.newrelic.com/graphql"
        else:
            self.graphql_endpoint = "https://api.newrelic.com/graphql"

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
            "API-Key": self.api_key
        })

    def _rate_limit_wait(self):
        """Implement rate limiting between requests."""
        if self.rate_limit > 0:
            elapsed = time.time() - self._last_request_time
            min_interval = 1.0 / self.rate_limit
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    def execute_query(
        self,
        query: str,
        variables: Optional[Dict[str, Any]] = None
    ) -> NerdGraphResponse:
        """Execute a NerdGraph GraphQL query."""
        self._rate_limit_wait()

        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        try:
            response = self.session.post(
                self.graphql_endpoint,
                json=payload,
                timeout=60
            )
            response.raise_for_status()
            result = response.json()

            return NerdGraphResponse(
                data=result.get("data"),
                errors=result.get("errors")
            )
        except requests.exceptions.RequestException as e:
            logger.error("NerdGraph API error", error=str(e))
            return NerdGraphResponse(data=None, errors=[{"message": str(e)}])

    def _paginate_query(
        self,
        query: str,
        path_to_cursor: List[str],
        path_to_results: List[str],
        variables: Optional[Dict[str, Any]] = None
    ) -> Generator[Dict[str, Any], None, None]:
        """Handle cursor-based pagination for NerdGraph queries."""
        cursor = None
        variables = variables or {}

        while True:
            variables["cursor"] = cursor
            response = self.execute_query(query, variables)

            if not response.is_success:
                logger.error("Pagination query failed", errors=response.errors)
                break

            # Navigate to results
            data = response.data
            for key in path_to_results:
                if data is None:
                    break
                data = data.get(key)

            if data:
                for item in data:
                    yield item

            # Get next cursor
            cursor_data = response.data
            for key in path_to_cursor:
                if cursor_data is None:
                    break
                cursor_data = cursor_data.get(key)

            cursor = cursor_data
            if not cursor:
                break

    # =========================================================================
    # Dashboard Export Methods
    # =========================================================================

    def get_all_dashboards(self) -> List[Dict[str, Any]]:
        """Export all dashboards from the account."""
        query = """
        query($accountId: Int!, $cursor: String) {
            actor {
                entitySearch(
                    query: "accountId = $accountId AND type = 'DASHBOARD'"
                    options: { limit: 200 }
                ) {
                    results(cursor: $cursor) {
                        entities {
                            guid
                            name
                            ... on DashboardEntityOutline {
                                dashboardParentGuid
                            }
                        }
                        nextCursor
                    }
                }
            }
        }
        """

        dashboards = []
        cursor = None

        while True:
            response = self.execute_query(query, {
                "accountId": int(self.account_id),
                "cursor": cursor
            })

            if not response.is_success:
                logger.error("Failed to fetch dashboards", errors=response.errors)
                break

            results = response.data["actor"]["entitySearch"]["results"]
            entities = results.get("entities", [])

            for entity in entities:
                # Get full dashboard definition
                full_dashboard = self.get_dashboard_definition(entity["guid"])
                if full_dashboard:
                    dashboards.append(full_dashboard)

            cursor = results.get("nextCursor")
            if not cursor:
                break

        logger.info(f"Exported {len(dashboards)} dashboards")
        return dashboards

    def get_dashboard_definition(self, guid: str) -> Optional[Dict[str, Any]]:
        """Get full dashboard definition by GUID."""
        query = """
        query($guid: EntityGuid!) {
            actor {
                entity(guid: $guid) {
                    ... on DashboardEntity {
                        guid
                        name
                        description
                        permissions
                        pages {
                            guid
                            name
                            description
                            widgets {
                                id
                                title
                                layout {
                                    column
                                    row
                                    width
                                    height
                                }
                                visualization {
                                    id
                                }
                                rawConfiguration
                            }
                        }
                        variables {
                            name
                            type
                            defaultValues
                            isMultiSelection
                            items {
                                title
                                value
                            }
                            nrqlQuery {
                                accountIds
                                query
                            }
                            replacementStrategy
                        }
                    }
                }
            }
        }
        """

        response = self.execute_query(query, {"guid": guid})
        if response.is_success and response.data:
            return response.data["actor"]["entity"]
        return None

    # =========================================================================
    # Alert Export Methods
    # =========================================================================

    def get_all_alert_policies(self) -> List[Dict[str, Any]]:
        """Export all alert policies and their conditions."""
        query = """
        query($accountId: Int!, $cursor: String) {
            actor {
                account(id: $accountId) {
                    alerts {
                        policiesSearch(cursor: $cursor) {
                            policies {
                                id
                                name
                                incidentPreference
                            }
                            nextCursor
                        }
                    }
                }
            }
        }
        """

        policies = []
        cursor = None

        while True:
            response = self.execute_query(query, {
                "accountId": int(self.account_id),
                "cursor": cursor
            })

            if not response.is_success:
                logger.error("Failed to fetch alert policies", errors=response.errors)
                break

            search_result = response.data["actor"]["account"]["alerts"]["policiesSearch"]
            policy_list = search_result.get("policies", [])

            for policy in policy_list:
                # Get conditions for each policy
                conditions = self.get_alert_conditions(policy["id"])
                policy["conditions"] = conditions
                policies.append(policy)

            cursor = search_result.get("nextCursor")
            if not cursor:
                break

        logger.info(f"Exported {len(policies)} alert policies")
        return policies

    def get_alert_conditions(self, policy_id: str) -> List[Dict[str, Any]]:
        """Get all conditions for an alert policy."""
        # NRQL Conditions
        nrql_query = """
        query($accountId: Int!, $policyId: ID!, $cursor: String) {
            actor {
                account(id: $accountId) {
                    alerts {
                        nrqlConditionsSearch(
                            searchCriteria: { policyId: $policyId }
                            cursor: $cursor
                        ) {
                            nrqlConditions {
                                id
                                name
                                type
                                enabled
                                nrql {
                                    query
                                }
                                signal {
                                    aggregationWindow
                                    aggregationMethod
                                    aggregationDelay
                                    fillOption
                                    fillValue
                                }
                                terms {
                                    threshold
                                    thresholdDuration
                                    thresholdOccurrences
                                    operator
                                    priority
                                }
                                expiration {
                                    closeViolationsOnExpiration
                                    expirationDuration
                                    openViolationOnExpiration
                                }
                                runbookUrl
                                description
                            }
                            nextCursor
                        }
                    }
                }
            }
        }
        """

        conditions = []
        cursor = None

        while True:
            response = self.execute_query(nrql_query, {
                "accountId": int(self.account_id),
                "policyId": policy_id,
                "cursor": cursor
            })

            if not response.is_success:
                break

            search_result = response.data["actor"]["account"]["alerts"]["nrqlConditionsSearch"]
            nrql_conditions = search_result.get("nrqlConditions", [])

            for condition in nrql_conditions:
                condition["conditionType"] = "NRQL"
                conditions.append(condition)

            cursor = search_result.get("nextCursor")
            if not cursor:
                break

        return conditions

    def get_notification_channels(self) -> List[Dict[str, Any]]:
        """Export all notification channels/destinations."""
        query = """
        query($accountId: Int!, $cursor: String) {
            actor {
                account(id: $accountId) {
                    aiNotifications {
                        destinations(cursor: $cursor) {
                            entities {
                                id
                                name
                                type
                                active
                                properties {
                                    key
                                    value
                                }
                            }
                            nextCursor
                        }
                    }
                }
            }
        }
        """

        channels = []
        cursor = None

        while True:
            response = self.execute_query(query, {
                "accountId": int(self.account_id),
                "cursor": cursor
            })

            if not response.is_success:
                logger.error("Failed to fetch notification channels", errors=response.errors)
                break

            result = response.data["actor"]["account"]["aiNotifications"]["destinations"]
            entities = result.get("entities", [])
            channels.extend(entities)

            cursor = result.get("nextCursor")
            if not cursor:
                break

        logger.info(f"Exported {len(channels)} notification channels")
        return channels

    # =========================================================================
    # Synthetic Monitor Export Methods
    # =========================================================================

    def get_all_synthetic_monitors(self) -> List[Dict[str, Any]]:
        """Export all synthetic monitors."""
        query = """
        query($accountId: Int!, $cursor: String) {
            actor {
                entitySearch(
                    query: "accountId = $accountId AND type = 'SYNTHETIC_MONITOR'"
                    options: { limit: 200 }
                ) {
                    results(cursor: $cursor) {
                        entities {
                            guid
                            name
                            ... on SyntheticMonitorEntityOutline {
                                monitorType
                                monitoredUrl
                                period
                            }
                        }
                        nextCursor
                    }
                }
            }
        }
        """

        monitors = []
        cursor = None

        while True:
            response = self.execute_query(query, {
                "accountId": int(self.account_id),
                "cursor": cursor
            })

            if not response.is_success:
                break

            results = response.data["actor"]["entitySearch"]["results"]
            entities = results.get("entities", [])

            for entity in entities:
                full_monitor = self.get_synthetic_monitor_details(entity["guid"])
                if full_monitor:
                    monitors.append(full_monitor)

            cursor = results.get("nextCursor")
            if not cursor:
                break

        logger.info(f"Exported {len(monitors)} synthetic monitors")
        return monitors

    def get_synthetic_monitor_details(self, guid: str) -> Optional[Dict[str, Any]]:
        """Get full synthetic monitor configuration."""
        query = """
        query($guid: EntityGuid!) {
            actor {
                entity(guid: $guid) {
                    ... on SyntheticMonitorEntity {
                        guid
                        name
                        monitorType
                        monitoredUrl
                        period
                        status
                        monitorSummary {
                            status
                            successRate
                        }
                        tags {
                            key
                            values
                        }
                    }
                }
            }
        }
        """

        response = self.execute_query(query, {"guid": guid})
        if response.is_success and response.data:
            return response.data["actor"]["entity"]
        return None

    def get_synthetic_monitor_script(self, monitor_guid: str) -> Optional[str]:
        """Get script for scripted synthetic monitors."""
        query = """
        query($accountId: Int!, $monitorGuid: EntityGuid!) {
            actor {
                account(id: $accountId) {
                    synthetics {
                        script(monitorGuid: $monitorGuid) {
                            text
                        }
                    }
                }
            }
        }
        """

        response = self.execute_query(query, {
            "accountId": int(self.account_id),
            "monitorGuid": monitor_guid
        })

        if response.is_success and response.data:
            script_data = response.data["actor"]["account"]["synthetics"]["script"]
            if script_data:
                return script_data.get("text")
        return None

    # =========================================================================
    # SLO Export Methods
    # =========================================================================

    def get_all_slos(self) -> List[Dict[str, Any]]:
        """Export all Service Level Objectives."""
        query = """
        query($accountId: Int!, $cursor: String) {
            actor {
                account(id: $accountId) {
                    serviceLevel {
                        indicators(cursor: $cursor) {
                            entities {
                                guid
                                name
                                description
                                objectives {
                                    target
                                    timeWindow {
                                        rolling {
                                            count
                                            unit
                                        }
                                    }
                                }
                                events {
                                    validEvents {
                                        from
                                        where
                                    }
                                    goodEvents {
                                        from
                                        where
                                    }
                                    badEvents {
                                        from
                                        where
                                    }
                                }
                            }
                            nextCursor
                        }
                    }
                }
            }
        }
        """

        slos = []
        cursor = None

        while True:
            response = self.execute_query(query, {
                "accountId": int(self.account_id),
                "cursor": cursor
            })

            if not response.is_success:
                break

            result = response.data["actor"]["account"]["serviceLevel"]["indicators"]
            entities = result.get("entities", [])
            slos.extend(entities)

            cursor = result.get("nextCursor")
            if not cursor:
                break

        logger.info(f"Exported {len(slos)} SLOs")
        return slos

    # =========================================================================
    # Workload Export Methods
    # =========================================================================

    def get_all_workloads(self) -> List[Dict[str, Any]]:
        """Export all workloads."""
        query = """
        query($accountId: Int!, $cursor: String) {
            actor {
                entitySearch(
                    query: "accountId = $accountId AND type = 'WORKLOAD'"
                    options: { limit: 200 }
                ) {
                    results(cursor: $cursor) {
                        entities {
                            guid
                            name
                            ... on WorkloadEntityOutline {
                                workloadStatus {
                                    statusValue
                                }
                            }
                        }
                        nextCursor
                    }
                }
            }
        }
        """

        workloads = []
        cursor = None

        while True:
            response = self.execute_query(query, {
                "accountId": int(self.account_id),
                "cursor": cursor
            })

            if not response.is_success:
                break

            results = response.data["actor"]["entitySearch"]["results"]
            entities = results.get("entities", [])

            for entity in entities:
                full_workload = self.get_workload_details(entity["guid"])
                if full_workload:
                    workloads.append(full_workload)

            cursor = results.get("nextCursor")
            if not cursor:
                break

        logger.info(f"Exported {len(workloads)} workloads")
        return workloads

    def get_workload_details(self, guid: str) -> Optional[Dict[str, Any]]:
        """Get full workload configuration."""
        query = """
        query($guid: EntityGuid!) {
            actor {
                entity(guid: $guid) {
                    ... on WorkloadEntity {
                        guid
                        name
                        collection {
                            guid
                            name
                            type
                        }
                        entitySearchQueries {
                            query
                        }
                    }
                }
            }
        }
        """

        response = self.execute_query(query, {"guid": guid})
        if response.is_success and response.data:
            return response.data["actor"]["entity"]
        return None

    # =========================================================================
    # Full Export Method
    # =========================================================================

    def export_all(self) -> Dict[str, Any]:
        """Export all supported configurations from New Relic."""
        logger.info("Starting full New Relic export", account_id=self.account_id)

        export_data = {
            "metadata": {
                "account_id": self.account_id,
                "region": self.region,
                "export_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "tool_version": "1.0.0"
            },
            "dashboards": self.get_all_dashboards(),
            "alert_policies": self.get_all_alert_policies(),
            "notification_channels": self.get_notification_channels(),
            "synthetic_monitors": self.get_all_synthetic_monitors(),
            "slos": self.get_all_slos(),
            "workloads": self.get_all_workloads(),
        }

        logger.info(
            "Export complete",
            dashboards=len(export_data["dashboards"]),
            alert_policies=len(export_data["alert_policies"]),
            synthetic_monitors=len(export_data["synthetic_monitors"]),
            slos=len(export_data["slos"]),
            workloads=len(export_data["workloads"])
        )

        return export_data
