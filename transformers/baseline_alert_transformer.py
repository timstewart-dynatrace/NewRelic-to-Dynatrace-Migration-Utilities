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

from ._detector_utils import nrql_to_analyzer_query

logger = structlog.get_logger()


# NR baseline direction -> DT `alertCondition` value inside
# `analyzer.input`. The current builtin:davis.anomaly-detectors schema
# documents `ABOVE`, `BELOW`, and `OUTSIDE_BOUNDS` for the input field.
_BASELINE_DIRECTION_MAP = {
    "upper_only": "ABOVE",
    "lower_only": "BELOW",
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
                facet = nr_condition.get("facet", "")
                if not facet:
                    warnings.append(
                        f"Outlier condition '{name}' has no facet — DT outlier "
                        "detection requires a `by:` dimension. Default set to "
                        "'dt.entity.service'."
                    )
                    facet = "dt.entity.service"
            else:
                facet = nr_condition.get("facet", "")

            alert_condition = _BASELINE_DIRECTION_MAP.get(direction, "ABOVE")

            nrql = nr_condition.get("nrql", {}).get("query", "")
            if not nrql:
                warnings.append(
                    f"Baseline condition '{name}' has no NRQL source — "
                    "the detector will reference a placeholder DQL."
                )
            # `analyzer.input[].value` is server-validated as DQL syntax;
            # passing raw NRQL produces "Invalid DQL query. `FROM` isn't
            # allowed here." Route through NRQLtoDQLConverter; fall back to
            # a `// UNCONVERTED NRQL` comment + placeholder when the query
            # can't be confidently translated. minLength=1 is satisfied
            # either way.
            dql_query = nrql_to_analyzer_query(nrql, warnings=warnings)

            detector_id = f"davis-baseline-{name}".lower()
            detector_id = "".join(
                c if c.isalnum() or c == "-" else "-" for c in detector_id
            )[:180]
            # New builtin:davis.anomaly-detectors schema (v1.0.14, 2026-04-20):
            # top level has {enabled,title,description,source,executionSettings,
            # analyzer{name,input[{key,value}]},eventTemplate{properties[{...}]}}
            # — old shape with `name`, `strategy`, `source.{type,query}`,
            # `eventTemplate.{title,description,eventType,davisMerge}` was
            # rejected with 10 validator errors against sprint tenants.
            analyzer_input = [
                {"key": "query", "value": dql_query},
                {"key": "numberOfSignalFluctuations", "value": str(sensitivity)},
                {"key": "alertCondition", "value": alert_condition},
                {"key": "alertOnMissingData", "value": "false"},
                {"key": "violatingSamples", "value": "3"},
                {"key": "slidingWindow", "value": "5"},
                {"key": "dealertingSamples", "value": "5"},
            ]
            if facet:
                analyzer_input.append(
                    {"key": "dimensions", "value": facet}
                )
            analyzer_input.append(
                {"key": "learningPeriodDays", "value": str(
                    int(nr_condition.get("learningPeriodDays", 7))
                )}
            )

            detector = {
                "schemaId": "builtin:davis.anomaly-detectors",
                "scope": "environment",
                "detectorId": detector_id,
                "value": {
                    "enabled": bool(nr_condition.get("enabled", True)),
                    "title": f"[Migrated baseline] {name}",
                    "description": (
                        f"Migrated from NR {kind} condition. "
                        f"Direction: {direction}, sensitivity: {sensitivity}σ."
                    ),
                    "source": "newrelic-migration",
                    "executionSettings": {"actor": None, "queryOffset": None},
                    "analyzer": {
                        "name": (
                            "dt.statistics.ui.anomaly_detection"
                            ".AutoAdaptiveAnomalyDetectionAnalyzer"
                        ),
                        "input": analyzer_input,
                    },
                    "eventTemplate": {
                        "properties": [
                            {"key": "event.type", "value": "CUSTOM_ALERT"},
                            {"key": "event.name", "value": f"[Migrated baseline] {name}"},
                            {"key": "migrated.from", "value": "newrelic"},
                            {"key": "source.kind", "value": kind},
                            {"key": "original.nrql", "value": nrql or "(none provided)"},
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
