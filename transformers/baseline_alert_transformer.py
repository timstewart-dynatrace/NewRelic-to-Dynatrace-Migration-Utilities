"""
Baseline & Outlier Alert Transformer — Gen3 target.

New Relic supports:
  * Baseline NRQL conditions — adaptive thresholds over historical data
  * Outlier NRQL conditions — per-facet deviation detection

Dynatrace's equivalents are encoded as Davis Anomaly Detectors with
`AUTO_ADAPTIVE_BASELINE` / `AUTO_ADAPTIVE_OUTLIER` strategies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger()


# NR baseline direction -> DT alert condition.
_BASELINE_DIRECTION_MAP = {
    "upper_only": "ABOVE_UPPER_BOUND",
    "lower_only": "BELOW_LOWER_BOUND",
    "both": "OUTSIDE_BOUNDS",
    "upper_and_lower": "OUTSIDE_BOUNDS",
}


@dataclass
class BaselineAlertTransformResult:
    success: bool
    anomaly_detectors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class BaselineAlertTransformer:
    """Translate NR baseline/outlier conditions to Davis adaptive detectors."""

    def transform(self, nr_condition: Dict[str, Any]) -> BaselineAlertTransformResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            name = nr_condition.get("name", "Unnamed Baseline")
            kind = str(nr_condition.get("conditionType", "baseline")).lower()
            direction = str(
                nr_condition.get("baselineDirection", "upper_only")
            ).lower()
            sensitivity = float(nr_condition.get("deviations", 3.0))

            if kind == "outlier":
                strategy_type = "AUTO_ADAPTIVE_OUTLIER"
                facet = nr_condition.get("facet", "")
                if not facet:
                    warnings.append(
                        f"Outlier condition '{name}' has no facet — DT outlier "
                        "detection requires a `by:` dimension. Default set to "
                        "'dt.entity.service'."
                    )
                    facet = "dt.entity.service"
            else:
                strategy_type = "AUTO_ADAPTIVE_BASELINE"
                facet = nr_condition.get("facet", "")

            alert_condition = _BASELINE_DIRECTION_MAP.get(direction, "ABOVE_UPPER_BOUND")

            nrql = nr_condition.get("nrql", {}).get("query", "")
            if not nrql:
                warnings.append(
                    f"Baseline condition '{name}' has no NRQL source — "
                    "the detector will reference a placeholder DQL."
                )

            detector_id = f"davis-baseline-{name}".lower()
            detector_id = "".join(
                c if c.isalnum() or c == "-" else "-" for c in detector_id
            )[:180]
            detector = {
                "schemaId": "builtin:davis.anomaly-detectors",
                "scope": "environment",
                "detectorId": detector_id,
                "value": {
                    "name": f"[Migrated baseline] {name}",
                    "description": (
                        f"Migrated from NR {kind} condition. "
                        f"Direction: {direction}, sensitivity: {sensitivity}σ."
                    ),
                    "enabled": bool(nr_condition.get("enabled", True)),
                    "source": {
                        "type": "DQL",
                        "query": "",  # populated by NRQLtoDQLConverter downstream
                        "originalNRQL": nrql,
                    },
                    "strategy": {
                        "type": strategy_type,
                        "alertCondition": alert_condition,
                        "sensitivity": sensitivity,
                        "byDimensions": [facet] if facet else [],
                        "learningPeriodDays": int(
                            nr_condition.get("learningPeriodDays", 7)
                        ),
                    },
                    "eventTemplate": {
                        "title": f"[Migrated baseline] {name}",
                        "description": name,
                        "eventType": "CUSTOM_ALERT",
                        "davisMerge": True,
                        "properties": [
                            {"key": "migrated.from", "value": "newrelic"},
                            {"key": "source.kind", "value": kind},
                        ],
                    },
                },
            }

            logger.info(
                "Transformed baseline/outlier condition to Gen3",
                name=name,
                kind=kind,
                direction=direction,
            )
            return BaselineAlertTransformResult(
                success=True, anomaly_detectors=[detector], warnings=warnings
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Baseline alert transformation failed", error=str(exc))
            return BaselineAlertTransformResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, conditions: List[Dict[str, Any]]
    ) -> List[BaselineAlertTransformResult]:
        return [self.transform(c) for c in conditions]
