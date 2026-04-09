"""
Alert Transformer - Converts New Relic alerts to Dynatrace format.
"""

import re
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
import structlog

from .mapping_rules import (
    EntityMapper,
    ALERT_PRIORITY_MAP,
    OPERATOR_MAP,
    THRESHOLD_OCCURRENCES_MAP,
    AGGREGATION_MAP,
    FILL_OPTION_MAP,
)

logger = structlog.get_logger()


@dataclass
class AlertTransformResult:
    """Result of alert transformation."""
    success: bool
    alerting_profile: Optional[Dict[str, Any]] = None
    metric_events: List[Dict[str, Any]] = None
    warnings: List[str] = None
    errors: List[str] = None

    def __post_init__(self):
        self.metric_events = self.metric_events or []
        self.warnings = self.warnings or []
        self.errors = self.errors or []


class AlertTransformer:
    """
    Transforms New Relic alert policies and conditions to Dynatrace format.

    Mapping:
    - New Relic Alert Policy -> Dynatrace Alerting Profile
    - New Relic NRQL Condition -> Dynatrace Metric Event (Custom Alert)
    - New Relic APM Condition -> Dynatrace Auto-Adaptive Baseline Alert
    """

    def __init__(self):
        self.mapper = EntityMapper()

    def transform(self, nr_policy: Dict[str, Any]) -> AlertTransformResult:
        """
        Transform a New Relic alert policy to Dynatrace alerting profile
        and metric events.
        """
        warnings = []
        errors = []

        try:
            policy_name = nr_policy.get("name", "Unnamed Policy")
            policy_id = nr_policy.get("id", "")

            # Create Dynatrace alerting profile
            alerting_profile = self._create_alerting_profile(nr_policy)

            # Transform conditions to metric events
            conditions = nr_policy.get("conditions", [])
            metric_events = []

            for condition in conditions:
                event_result = self._transform_condition(
                    condition=condition,
                    policy_name=policy_name
                )

                if event_result["metric_event"]:
                    metric_events.append(event_result["metric_event"])

                if event_result["warnings"]:
                    warnings.extend(event_result["warnings"])

                if event_result["errors"]:
                    errors.extend(event_result["errors"])

            logger.info(
                "Transformed alert policy",
                policy=policy_name,
                conditions_count=len(conditions),
                events_created=len(metric_events)
            )

            return AlertTransformResult(
                success=True,
                alerting_profile=alerting_profile,
                metric_events=metric_events,
                warnings=warnings,
                errors=errors
            )

        except Exception as e:
            logger.error("Alert policy transformation failed", error=str(e))
            return AlertTransformResult(
                success=False,
                errors=[f"Transformation error: {str(e)}"]
            )

    def _create_alerting_profile(self, nr_policy: Dict[str, Any]) -> Dict[str, Any]:
        """Create a Dynatrace alerting profile from New Relic policy."""
        policy_name = nr_policy.get("name", "Unnamed Policy")
        incident_preference = nr_policy.get("incidentPreference", "PER_POLICY")

        # Build alerting profile
        profile = {
            "name": f"[Migrated] {policy_name}",
            "managementZone": None,
            "severityRules": [
                {
                    "severityLevel": "AVAILABILITY",
                    "tagFilter": {"includeMode": "NONE"},
                    "delayInMinutes": 0
                },
                {
                    "severityLevel": "ERROR",
                    "tagFilter": {"includeMode": "NONE"},
                    "delayInMinutes": 0
                },
                {
                    "severityLevel": "PERFORMANCE",
                    "tagFilter": {"includeMode": "NONE"},
                    "delayInMinutes": 0
                },
                {
                    "severityLevel": "RESOURCE_CONTENTION",
                    "tagFilter": {"includeMode": "NONE"},
                    "delayInMinutes": 0
                },
                {
                    "severityLevel": "CUSTOM_ALERT",
                    "tagFilter": {"includeMode": "NONE"},
                    "delayInMinutes": 0
                }
            ],
            "eventTypeFilters": []
        }

        return profile

    def _transform_condition(
        self,
        condition: Dict[str, Any],
        policy_name: str
    ) -> Dict[str, Any]:
        """Transform a New Relic alert condition to Dynatrace metric event."""
        warnings = []
        errors = []
        metric_event = None

        condition_type = condition.get("conditionType", "NRQL")
        condition_name = condition.get("name", "Unnamed Condition")

        if condition_type == "NRQL":
            metric_event = self._transform_nrql_condition(condition, warnings)
        else:
            warnings.append(
                f"Condition type '{condition_type}' for '{condition_name}' "
                "may require manual configuration"
            )
            metric_event = self._create_placeholder_event(condition)

        return {
            "metric_event": metric_event,
            "warnings": warnings,
            "errors": errors
        }

    def _transform_nrql_condition(
        self,
        condition: Dict[str, Any],
        warnings: List[str]
    ) -> Dict[str, Any]:
        """Transform NRQL condition to metric event."""
        condition_name = condition.get("name", "Unnamed Condition")
        description = condition.get("description", "")
        enabled = condition.get("enabled", True)

        # Get NRQL query
        nrql = condition.get("nrql", {})
        query = nrql.get("query", "")

        # Get signal configuration
        signal = condition.get("signal", {})
        aggregation_window = signal.get("aggregationWindow", 60)
        aggregation_method = signal.get("aggregationMethod", "EVENT_FLOW")

        # Get terms (thresholds)
        terms = condition.get("terms", [])

        # Build metric event
        metric_event = {
            "summary": f"[Migrated] {condition_name}",
            "description": description or f"Migrated from New Relic. Original NRQL: {query[:200]}",
            "enabled": enabled,
            "alertingScope": [
                {
                    "filterType": "ENTITY_ID",
                    "entityId": None  # Will be set based on context
                }
            ],
            "monitoringStrategy": self._build_monitoring_strategy(
                terms=terms,
                aggregation_window=aggregation_window,
                query=query,
                warnings=warnings
            ),
            "primaryDimensionKey": None,
            "queryDefinition": self._build_query_definition(query, warnings)
        }

        # Add runbook URL if present
        runbook_url = condition.get("runbookUrl")
        if runbook_url:
            metric_event["description"] += f"\n\nRunbook: {runbook_url}"

        return metric_event

    def _build_monitoring_strategy(
        self,
        terms: List[Dict[str, Any]],
        aggregation_window: int,
        query: str,
        warnings: List[str]
    ) -> Dict[str, Any]:
        """Build Dynatrace monitoring strategy from New Relic terms."""
        # Default to static threshold strategy
        strategy = {
            "type": "STATIC_THRESHOLD",
            "alertCondition": "ABOVE",
            "alertingOnMissingData": False,
            "dealingWithGapsStrategy": "DROP_DATA",
            "samples": 3,
            "violatingSamples": 3,
            "threshold": 0,
            "unit": "UNSPECIFIED"
        }

        if terms:
            # Use the first critical term if available
            critical_term = None
            warning_term = None

            for term in terms:
                priority = term.get("priority", "critical").lower()
                if priority == "critical":
                    critical_term = term
                elif priority == "warning":
                    warning_term = term

            # Use critical term, fall back to warning
            active_term = critical_term or warning_term

            if active_term:
                # Map operator
                operator = active_term.get("operator", "ABOVE")
                strategy["alertCondition"] = OPERATOR_MAP.get(operator, "ABOVE")

                # Set threshold
                threshold = active_term.get("threshold", 0)
                strategy["threshold"] = threshold

                # Set duration
                duration_seconds = active_term.get("thresholdDuration", 300)
                # Dynatrace uses samples, assuming 1 sample per minute
                samples = max(1, duration_seconds // 60)
                strategy["samples"] = samples
                strategy["violatingSamples"] = samples

                # Set threshold occurrences behavior
                occurrences = active_term.get("thresholdOccurrences", "ALL")
                if occurrences == "AT_LEAST_ONCE":
                    strategy["violatingSamples"] = 1

        return strategy

    def _build_query_definition(
        self,
        nrql_query: str,
        warnings: List[str]
    ) -> Dict[str, Any]:
        """Build Dynatrace query definition from NRQL."""
        # Attempt to parse metric from NRQL
        metric_key = self._extract_metric_from_nrql(nrql_query)

        if not metric_key:
            warnings.append(
                f"Could not extract metric from NRQL: {nrql_query[:100]}... "
                "Manual configuration required."
            )
            metric_key = "builtin:tech.generic.placeholder"

        return {
            "type": "METRIC_KEY",
            "metricKey": metric_key,
            "aggregation": "AVG",
            "entityFilter": {
                "dimensionKey": "dt.entity.service",
                "conditions": []
            },
            "dimensionFilter": []
        }

    def _extract_metric_from_nrql(self, query: str) -> Optional[str]:
        """
        Attempt to extract a metric identifier from NRQL query.
        Returns a Dynatrace metric key if possible.
        """
        query_lower = query.lower()

        # Common NRQL metric patterns and their Dynatrace equivalents
        metric_mappings = {
            "transactionduration": "builtin:service.response.time",
            "duration": "builtin:service.response.time",
            "apdex": "builtin:service.response.time",
            "error": "builtin:service.errors.total.rate",
            "errorrate": "builtin:service.errors.total.rate",
            "throughput": "builtin:service.requestCount.total",
            "requestcount": "builtin:service.requestCount.total",
            "cpupercent": "builtin:host.cpu.usage",
            "cpu": "builtin:host.cpu.usage",
            "memorypercent": "builtin:host.mem.usage",
            "memory": "builtin:host.mem.usage",
            "diskpercent": "builtin:host.disk.usedPct",
            "disk": "builtin:host.disk.usedPct",
        }

        for nrql_metric, dt_metric in metric_mappings.items():
            if nrql_metric in query_lower:
                return dt_metric

        return None

    def _create_placeholder_event(self, condition: Dict[str, Any]) -> Dict[str, Any]:
        """Create a placeholder metric event for unsupported condition types."""
        return {
            "summary": f"[Migrated - Manual Config Required] {condition.get('name', 'Unknown')}",
            "description": (
                f"This alert was migrated from New Relic but requires manual configuration.\n"
                f"Original condition type: {condition.get('conditionType', 'Unknown')}"
            ),
            "enabled": False,  # Disabled by default
            "alertingScope": [],
            "monitoringStrategy": {
                "type": "STATIC_THRESHOLD",
                "alertCondition": "ABOVE",
                "threshold": 0,
                "samples": 3,
                "violatingSamples": 3
            }
        }

    def transform_all(
        self,
        policies: List[Dict[str, Any]]
    ) -> List[AlertTransformResult]:
        """Transform multiple alert policies."""
        results = []

        for policy in policies:
            result = self.transform(policy)
            results.append(result)

        successful = sum(1 for r in results if r.success)
        total_events = sum(len(r.metric_events) for r in results)

        logger.info(
            f"Transformed {successful}/{len(results)} alert policies, "
            f"{total_events} metric events created"
        )

        return results


@dataclass
class NotificationTransformResult:
    """Result of notification channel transformation."""
    success: bool
    integration_type: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    warnings: List[str] = None
    errors: List[str] = None

    def __post_init__(self):
        self.warnings = self.warnings or []
        self.errors = self.errors or []


class NotificationTransformer:
    """
    Transforms New Relic notification channels to Dynatrace integrations.
    """

    def transform(self, nr_channel: Dict[str, Any]) -> NotificationTransformResult:
        """Transform a notification channel."""
        channel_type = nr_channel.get("type", "").upper()
        channel_name = nr_channel.get("name", "Unknown Channel")
        properties = {p["key"]: p["value"] for p in nr_channel.get("properties", [])}

        if channel_type == "EMAIL":
            return self._transform_email(nr_channel, properties)
        elif channel_type == "SLACK":
            return self._transform_slack(nr_channel, properties)
        elif channel_type == "PAGERDUTY":
            return self._transform_pagerduty(nr_channel, properties)
        elif channel_type == "WEBHOOK":
            return self._transform_webhook(nr_channel, properties)
        else:
            return NotificationTransformResult(
                success=False,
                errors=[
                    f"Notification type '{channel_type}' for '{channel_name}' "
                    "is not yet supported for automatic migration"
                ]
            )

    def _transform_email(
        self,
        channel: Dict[str, Any],
        properties: Dict[str, str]
    ) -> NotificationTransformResult:
        """Transform email notification channel."""
        return NotificationTransformResult(
            success=True,
            integration_type="email",
            config={
                "name": f"[Migrated] {channel.get('name', 'Email')}",
                "recipients": properties.get("recipients", "").split(","),
                "subject": "[Dynatrace] {ProblemTitle}",
                "body": "{ProblemDetailsText}",
                "active": channel.get("active", True)
            },
        )

    def _transform_slack(
        self,
        channel: Dict[str, Any],
        properties: Dict[str, str]
    ) -> NotificationTransformResult:
        """Transform Slack notification channel."""
        return NotificationTransformResult(
            success=True,
            integration_type="slack",
            config={
                "name": f"[Migrated] {channel.get('name', 'Slack')}",
                "url": properties.get("url", ""),  # Webhook URL
                "channel": properties.get("channel", ""),
                "active": channel.get("active", True)
            },
            warnings=["Slack webhook URL may need to be updated for Dynatrace"],
        )

    def _transform_pagerduty(
        self,
        channel: Dict[str, Any],
        properties: Dict[str, str]
    ) -> NotificationTransformResult:
        """Transform PagerDuty notification channel."""
        return NotificationTransformResult(
            success=True,
            integration_type="pagerduty",
            config={
                "name": f"[Migrated] {channel.get('name', 'PagerDuty')}",
                "serviceKey": properties.get("service_key", ""),
                "active": channel.get("active", True)
            },
            warnings=[
                "PagerDuty integration key may need to be regenerated for Dynatrace"
            ],
        )

    def _transform_webhook(
        self,
        channel: Dict[str, Any],
        properties: Dict[str, str]
    ) -> NotificationTransformResult:
        """Transform generic webhook notification channel."""
        return NotificationTransformResult(
            success=True,
            integration_type="webhook",
            config={
                "name": f"[Migrated] {channel.get('name', 'Webhook')}",
                "url": properties.get("base_url", ""),
                "acceptAnyCertificate": False,
                "active": channel.get("active", True),
                "headers": [],
                "payload": "{ProblemDetailsJSON}"
            },
            warnings=[
                "Webhook payload format will need adjustment for Dynatrace problem format"
            ],
        )
