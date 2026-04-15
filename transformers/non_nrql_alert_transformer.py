"""
Non-NRQL Alert Condition Transformer — Gen3 target.

New Relic alert conditions come in multiple flavors; only NRQL conditions
are already handled by `AlertTransformer`. This module covers the rest:

  * Infrastructure Condition  (already partially handled — upgraded here)
  * Synthetic Condition
  * External Service Condition
  * Browser Condition
  * Mobile Condition
  * Multi-location Synthetic Condition

All produce `builtin:davis.anomaly-detectors` envelopes + a paired
Workflow (Davis-event trigger) following the same shape as
`AlertTransformer`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


# NR condition type -> (default metric key, default alert condition, note)
_CONDITION_METRIC_MAP = {
    "synthetic": (
        "builtin:synthetic.http.availability.location.total",
        "BELOW",
        "Synthetic availability condition.",
    ),
    "external_service": (
        "builtin:service.response.time",
        "ABOVE",
        "External service response-time condition.",
    ),
    "browser": (
        "builtin:apps.web.actionCount.osAndGeo",
        "ABOVE",
        "Browser RUM condition. Verify metric key with BrowserRUMTransformer mapping.",
    ),
    "mobile": (
        "builtin:apps.mobile.crashCount",
        "ABOVE",
        "Mobile RUM condition. Verify metric key with MobileRUMTransformer mapping.",
    ),
    "infra": (
        "builtin:host.cpu.usage",
        "ABOVE",
        "Generic infra fallback (CPU). Prefer InfrastructureTransformer for infra_metric type.",
    ),
    "multi_location_synthetic": (
        "builtin:synthetic.http.availability.location.total",
        "BELOW",
        "Multi-location synthetic condition — DT needs location-count logic in the detector strategy.",
    ),
}


@dataclass
class NonNRQLAlertTransformResult:
    success: bool
    anomaly_detectors: List[Dict[str, Any]] = field(default_factory=list)
    workflows: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class NonNRQLAlertTransformer:
    """Dispatch-by-condition-type translator for NR non-NRQL conditions."""

    def transform(self, nr_condition: Dict[str, Any]) -> NonNRQLAlertTransformResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            ctype = str(nr_condition.get("type", "")).lower()
            name = nr_condition.get("name", "Unnamed Condition")
            if ctype not in _CONDITION_METRIC_MAP:
                warnings.append(
                    f"Condition type '{ctype}' for '{name}' is not a recognized "
                    "non-NRQL condition. Skipped."
                )
                return NonNRQLAlertTransformResult(
                    success=False,
                    errors=[f"Unsupported condition type: {ctype}"],
                )
            metric_key, alert_cond, note = _CONDITION_METRIC_MAP[ctype]

            terms = nr_condition.get("terms", []) or []
            threshold = 0.0
            samples = 3
            if terms:
                critical = next(
                    (t for t in terms if str(t.get("priority", "")).lower() == "critical"),
                    terms[0],
                )
                threshold = float(critical.get("threshold", 0))
                duration_seconds = int(critical.get("thresholdDuration", 300))
                samples = max(1, duration_seconds // 60)

            strategy = {
                "type": "STATIC_THRESHOLD",
                "threshold": threshold,
                "alertCondition": alert_cond,
                "samples": samples,
                "violatingSamples": samples,
                "dealingWithGapsStrategy": "DROP_DATA",
            }
            if ctype == "multi_location_synthetic":
                required = int(nr_condition.get("locationsRequired", 3))
                strategy["minLocationsFailing"] = required
                warnings.append(
                    f"Multi-location synthetic '{name}' requires "
                    f"{required} locations failing — verify DT detector "
                    "supports minLocationsFailing in the target tenant."
                )

            detector_id = f"davis-{ctype}-{name}".lower()
            detector_id = "".join(
                c if c.isalnum() or c == "-" else "-" for c in detector_id
            )[:180]
            detector = {
                "schemaId": "builtin:davis.anomaly-detectors",
                "scope": "environment",
                "detectorId": detector_id,
                "value": {
                    "name": f"[Migrated] {name}",
                    "description": f"{note} Migrated from NR '{ctype}' condition.",
                    "enabled": bool(nr_condition.get("enabled", True)),
                    "source": {
                        "type": "METRIC_KEY",
                        "metricKey": metric_key,
                        "aggregation": "AVG",
                    },
                    "strategy": strategy,
                    "eventTemplate": {
                        "title": f"[Migrated] {name}",
                        "description": name,
                        "eventType": "CUSTOM_ALERT",
                        "davisMerge": True,
                        "properties": [
                            {"key": "source.condition", "value": name},
                            {"key": "source.type", "value": ctype},
                            {"key": "migrated.from", "value": "newrelic"},
                        ],
                    },
                },
            }

            workflow = {
                "title": f"[Migrated {ctype}] {name}",
                "description": note,
                "private": False,
                "trigger": {
                    "event": {
                        "active": True,
                        "config": {
                            "davis_event": {
                                "eventType": "CUSTOM_ALERT",
                                "detectorIds": [detector_id],
                                "anyEventMatches": True,
                            }
                        },
                    }
                },
                "tasks": [
                    {
                        "name": "placeholder_action",
                        "action": "dynatrace.automations:run-javascript",
                        "active": False,
                        "description": "Attach notifications/actions in Phase 17 NotificationTransformer integration.",
                        "input": {"script": "export default () => ({ ok: true });"},
                        "position": {"x": 0, "y": 1},
                    }
                ],
            }

            logger.info(
                "Transformed non-NRQL alert condition",
                name=name,
                type=ctype,
            )
            return NonNRQLAlertTransformResult(
                success=True,
                anomaly_detectors=[detector],
                workflows=[workflow],
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Non-NRQL alert transformation failed", error=str(exc))
            return NonNRQLAlertTransformResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, conditions: List[Dict[str, Any]]
    ) -> List[NonNRQLAlertTransformResult]:
        return [self.transform(c) for c in conditions]
