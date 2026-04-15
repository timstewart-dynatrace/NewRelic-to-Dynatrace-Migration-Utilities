"""
Infrastructure Transformer - Converts New Relic Infrastructure conditions to Dynatrace format.
"""

from dataclasses import dataclass
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger()


# Mapping of NR infra condition types to Dynatrace metric keys
INFRA_METRIC_MAP = {
    "host_not_reporting": "builtin:host.availability",
    "process_not_running": "builtin:tech.generic.process.count",
    "infra_metric": {
        "cpuPercent": "builtin:host.cpu.usage",
        "memoryUsedPercent": "builtin:host.mem.usage",
        "diskUsedPercent": "builtin:host.disk.usedPct",
        "loadAverageOneMinute": "builtin:host.cpu.load",
        "networkReceiveRate": "builtin:host.net.bytesRx",
        "networkTransmitRate": "builtin:host.net.bytesTx",
    },
}

OPERATOR_MAP = {
    "above": "ABOVE",
    "below": "BELOW",
    "equal": "EQUALS",
}


@dataclass
class InfrastructureTransformResult:
    """Result of infrastructure condition transformation."""
    success: bool
    metric_events: List[Dict[str, Any]] = None
    warnings: List[str] = None
    errors: List[str] = None

    def __post_init__(self):
        self.metric_events = self.metric_events or []
        self.warnings = self.warnings or []
        self.errors = self.errors or []


class InfrastructureTransformer:
    """
    Transforms New Relic Infrastructure alert conditions to Dynatrace metric events.

    New Relic Infrastructure conditions:
    - host_not_reporting: Host availability check
    - process_not_running: Process monitoring
    - infra_metric: Generic metric threshold (CPU, memory, disk, etc.)

    Dynatrace equivalents:
    - Metric events with builtin metric keys
    - Custom thresholds and monitoring strategies
    """

    def __init__(self):
        pass

    def transform(self, nr_condition: Dict[str, Any]) -> InfrastructureTransformResult:
        """Transform a New Relic infrastructure condition to Dynatrace metric event(s)."""
        warnings: List[str] = []
        errors: List[str] = []

        try:
            condition_type = nr_condition.get("type", "unknown")
            condition_name = nr_condition.get("name", "Unnamed Condition")

            if condition_type == "host_not_reporting":
                metric_event = self._transform_host_not_reporting(nr_condition, warnings)
            elif condition_type == "process_not_running":
                metric_event = self._transform_process_not_running(nr_condition, warnings)
            elif condition_type == "infra_metric":
                metric_event = self._transform_infra_metric(nr_condition, warnings)
            else:
                warnings.append(
                    f"Unknown infrastructure condition type '{condition_type}' "
                    f"for '{condition_name}'. Creating placeholder."
                )
                metric_event = self._create_placeholder(nr_condition)

            metric_events = [metric_event] if metric_event else []

            logger.info(
                "Transformed infrastructure condition",
                name=condition_name,
                type=condition_type,
            )

            return InfrastructureTransformResult(
                success=True,
                metric_events=metric_events,
                warnings=warnings,
            )

        except Exception as e:
            logger.error("Infrastructure transformation failed", error=str(e))
            return InfrastructureTransformResult(
                success=False,
                errors=[f"Transformation error: {str(e)}"],
            )

    def _transform_host_not_reporting(
        self, condition: Dict[str, Any], warnings: List[str]
    ) -> Dict[str, Any]:
        """Transform host-not-reporting condition."""
        name = condition.get("name", "Host Not Reporting")
        duration = condition.get("criticalThreshold", {}).get("durationMinutes", 5)

        return {
            "name": f"[Migrated] {name}",
            "description": f"Migrated from NR infra condition: {name}",
            "metricId": INFRA_METRIC_MAP["host_not_reporting"],
            "enabled": condition.get("enabled", True),
            "alertCondition": "BELOW",
            "alertConditionValue": 1,
            "samples": duration,
            "violatingSamples": duration,
            "dealertingSamples": duration * 2,
        }

    def _transform_process_not_running(
        self, condition: Dict[str, Any], warnings: List[str]
    ) -> Dict[str, Any]:
        """Transform process-not-running condition."""
        name = condition.get("name", "Process Not Running")
        process_filter = condition.get("processWhereClause", "")

        if process_filter:
            warnings.append(
                f"Process filter '{process_filter}' requires manual configuration "
                "in Dynatrace process group detection."
            )

        return {
            "name": f"[Migrated] {name}",
            "description": f"Migrated from NR infra condition: {name}",
            "metricId": INFRA_METRIC_MAP["process_not_running"],
            "enabled": condition.get("enabled", True),
            "alertCondition": "BELOW",
            "alertConditionValue": 1,
            "samples": 3,
            "violatingSamples": 3,
            "dealertingSamples": 6,
        }

    def _transform_infra_metric(
        self, condition: Dict[str, Any], warnings: List[str]
    ) -> Dict[str, Any]:
        """Transform generic infra metric condition."""
        name = condition.get("name", "Infra Metric")
        event_type = condition.get("event_type", "SystemSample")
        select_value = condition.get("select_value", "")
        comparison = condition.get("comparison", "above")

        # Map metric
        metric_map = INFRA_METRIC_MAP.get("infra_metric", {})
        metric_id = metric_map.get(select_value)

        if not metric_id:
            warnings.append(
                f"Metric '{select_value}' from '{event_type}' has no direct mapping. "
                "Using placeholder metric key."
            )
            metric_id = f"builtin:host.{select_value}"

        # Get threshold
        critical = condition.get("criticalThreshold", {})
        threshold_value = critical.get("value", 0)
        duration = critical.get("durationMinutes", 5)

        return {
            "name": f"[Migrated] {name}",
            "description": f"Migrated from NR infra condition: {name}",
            "metricId": metric_id,
            "enabled": condition.get("enabled", True),
            "alertCondition": OPERATOR_MAP.get(comparison, "ABOVE"),
            "alertConditionValue": threshold_value,
            "samples": duration,
            "violatingSamples": duration,
            "dealertingSamples": duration * 2,
        }

    def _create_placeholder(self, condition: Dict[str, Any]) -> Dict[str, Any]:
        """Create a disabled placeholder metric event for unknown types."""
        name = condition.get("name", "Unknown Condition")
        return {
            "name": f"[Migrated] {name}",
            "description": f"Migrated from NR infra condition (unknown type): {name}",
            "metricId": "builtin:host.cpu.usage",
            "enabled": False,
            "alertCondition": "ABOVE",
            "alertConditionValue": 0,
            "samples": 5,
            "violatingSamples": 5,
            "dealertingSamples": 10,
        }

    def transform_all(
        self, conditions: List[Dict[str, Any]]
    ) -> List[InfrastructureTransformResult]:
        """Transform multiple infrastructure conditions."""
        results = []

        for condition in conditions:
            result = self.transform(condition)
            results.append(result)

        successful = sum(1 for r in results if r.success)
        logger.info(
            f"Transformed {successful}/{len(results)} infrastructure conditions"
        )

        return results
