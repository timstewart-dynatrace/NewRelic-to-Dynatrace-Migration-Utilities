"""
Infrastructure Transformer — Gen3 target.

Converts New Relic Infrastructure conditions into Dynatrace Gen3 objects:

  NR host_not_reporting / process_not_running / infra_metric  ->
      Davis Anomaly Detector (builtin:davis.anomaly-detectors)
      + Workflow with Davis-event trigger

The Workflow is an empty-shell trigger so downstream action tasks (assigned
by AlertTransformer when the infra condition lives inside a policy) or
operator hand-editing can be attached. When invoked standalone, the
transformer emits one detector + one workflow per condition.

Legacy (Config v1 Metric Event) behavior is preserved in
`transformers/legacy/infrastructure_transformer_v1.py`.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

import structlog

from ._workflow_utils import tasks_list_to_dict

logger = structlog.get_logger()


INFRA_METRIC_MAP: Dict[str, Any] = {
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

OPERATOR_MAP = {"above": "ABOVE", "below": "BELOW", "equal": "EQUALS"}


@dataclass
class InfrastructureTransformResult:
    """Result of infra condition -> Gen3 translation."""

    success: bool
    anomaly_detectors: List[Dict[str, Any]] = field(default_factory=list)
    workflows: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class InfrastructureTransformer:
    """NR Infra condition -> Davis Anomaly Detector + Workflow (Gen3)."""

    def transform(self, nr_condition: Dict[str, Any]) -> InfrastructureTransformResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            condition_type = nr_condition.get("type", "unknown")
            name = nr_condition.get("name", "Unnamed Condition")

            if condition_type == "host_not_reporting":
                det = self._detector_host_not_reporting(nr_condition)
            elif condition_type == "process_not_running":
                det = self._detector_process_not_running(nr_condition, warnings)
            elif condition_type == "infra_metric":
                det = self._detector_infra_metric(nr_condition, warnings)
            else:
                warnings.append(
                    f"Unknown infrastructure condition type '{condition_type}' "
                    f"for '{name}'. Emitted disabled placeholder detector."
                )
                det = self._detector_placeholder(nr_condition)

            workflow = self._workflow_for_detector(det, name)

            logger.info(
                "Transformed infra condition to Gen3",
                name=name,
                type=condition_type,
            )
            return InfrastructureTransformResult(
                success=True,
                anomaly_detectors=[det],
                workflows=[workflow],
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Infrastructure transformation failed", error=str(exc))
            return InfrastructureTransformResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    # ------------------------------------------------------------------
    # Detector builders
    # ------------------------------------------------------------------

    def _base_detector(
        self,
        name: str,
        metric_key: str,
        alert_condition: str,
        threshold: float,
        samples: int,
        enabled: bool = True,
    ) -> Dict[str, Any]:
        detector_id = f"davis-infra-{name}".lower()
        detector_id = "".join(c if c.isalnum() or c == "-" else "-" for c in detector_id)[:180]
        # New builtin:davis.anomaly-detectors schema (v1.0.14, 2026-04-20):
        # top level is {enabled,title,description,source,executionSettings,
        # analyzer{name,input[{key,value}]},eventTemplate{properties}}.
        alert_on_missing = "true" if (
            alert_condition == "BELOW" and threshold <= 1
        ) else "false"
        return {
            "schemaId": "builtin:davis.anomaly-detectors",
            "scope": "environment",
            "detectorId": detector_id,
            "value": {
                "enabled": enabled,
                "title": f"[Migrated] {name}",
                "description": f"Migrated from New Relic infrastructure condition: {name}",
                "source": "newrelic-migration",
                "executionSettings": {"actor": None, "queryOffset": None},
                "analyzer": {
                    "name": (
                        "dt.statistics.ui.anomaly_detection"
                        ".StaticThresholdAnomalyDetectionAnalyzer"
                    ),
                    "input": [
                        {"key": "query", "value": f"timeseries avg({metric_key})"},
                        {"key": "threshold", "value": str(threshold)},
                        {"key": "alertCondition", "value": alert_condition},
                        {"key": "alertOnMissingData", "value": alert_on_missing},
                        {"key": "violatingSamples", "value": str(samples)},
                        {"key": "slidingWindow", "value": str(samples)},
                        {"key": "dealertingSamples", "value": "5"},
                    ],
                },
                "eventTemplate": {
                    "properties": [
                        {"key": "event.type", "value": "RESOURCE_CONTENTION"},
                        {"key": "event.name", "value": f"[Migrated] {name}"},
                        {"key": "source.condition", "value": name},
                        {"key": "migrated.from", "value": "newrelic"},
                    ],
                },
            },
        }

    def _detector_host_not_reporting(self, condition: Dict[str, Any]) -> Dict[str, Any]:
        name = condition.get("name", "Host Not Reporting")
        duration = int(condition.get("criticalThreshold", {}).get("durationMinutes", 5))
        return self._base_detector(
            name=name,
            metric_key=INFRA_METRIC_MAP["host_not_reporting"],
            alert_condition="BELOW",
            threshold=1,
            samples=max(1, duration),
            enabled=bool(condition.get("enabled", True)),
        )

    def _detector_process_not_running(
        self, condition: Dict[str, Any], warnings: List[str]
    ) -> Dict[str, Any]:
        name = condition.get("name", "Process Not Running")
        process_filter = condition.get("processWhereClause", "")
        if process_filter:
            warnings.append(
                f"Process filter '{process_filter}' requires manual configuration "
                "in Dynatrace process group detection."
            )
        return self._base_detector(
            name=name,
            metric_key=INFRA_METRIC_MAP["process_not_running"],
            alert_condition="BELOW",
            threshold=1,
            samples=3,
            enabled=bool(condition.get("enabled", True)),
        )

    def _detector_infra_metric(
        self, condition: Dict[str, Any], warnings: List[str]
    ) -> Dict[str, Any]:
        name = condition.get("name", "Infra Metric")
        event_type = condition.get("event_type", "SystemSample")
        select_value = condition.get("select_value", "")
        comparison = condition.get("comparison", "above")

        metric_id = INFRA_METRIC_MAP["infra_metric"].get(select_value)
        if not metric_id:
            warnings.append(
                f"Metric '{select_value}' from '{event_type}' has no direct mapping. "
                "Using placeholder metric key."
            )
            metric_id = f"builtin:host.{select_value}"

        critical = condition.get("criticalThreshold", {}) or {}
        return self._base_detector(
            name=name,
            metric_key=metric_id,
            alert_condition=OPERATOR_MAP.get(comparison, "ABOVE"),
            threshold=float(critical.get("value", 0)),
            samples=max(1, int(critical.get("durationMinutes", 5))),
            enabled=bool(condition.get("enabled", True)),
        )

    def _detector_placeholder(self, condition: Dict[str, Any]) -> Dict[str, Any]:
        name = condition.get("name", "Unknown Condition")
        return self._base_detector(
            name=name,
            metric_key="builtin:host.cpu.usage",
            alert_condition="ABOVE",
            threshold=0,
            samples=5,
            enabled=False,
        )

    # ------------------------------------------------------------------
    # Workflow builder (bare shell)
    # ------------------------------------------------------------------

    @staticmethod
    def _workflow_for_detector(detector: Dict[str, Any], name: str) -> Dict[str, Any]:
        return {
            "title": f"[Migrated infra] {name}",
            "description": f"Workflow shell for Davis anomaly detector '{detector['detectorId']}'.",
            "private": False,
            "isPrivate": False,
            "trigger": {
                "event": {
                    "active": True,
                    "config": {
                        "davis_event": {
                            "eventType": "RESOURCE_CONTENTION",
                            "detectorIds": [detector["detectorId"]],
                            "anyEventMatches": True,
                        }
                    },
                }
            },
            # Gen3 Automation API requires `tasks` as a dict keyed by task id.
            "tasks": tasks_list_to_dict([
                {
                    "name": "placeholder_action",
                    "action": "dynatrace.automations:run-javascript",
                    "active": False,
                    "description": "Attach notification/action tasks as needed.",
                    "input": {"script": "export default () => ({ ok: true });"},
                    "position": {"x": 0, "y": 1},
                }
            ]),
        }

    def transform_all(
        self, conditions: List[Dict[str, Any]]
    ) -> List[InfrastructureTransformResult]:
        results = [self.transform(c) for c in conditions]
        successful = sum(1 for r in results if r.success)
        logger.info(
            f"Transformed {successful}/{len(results)} infra conditions to Gen3"
        )
        return results
