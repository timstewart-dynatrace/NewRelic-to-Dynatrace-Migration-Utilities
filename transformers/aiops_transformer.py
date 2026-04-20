"""
AIOps Transformer — Gen3 target.

New Relic Applied Intelligence (NR AIOps) concepts map to Dynatrace
Davis + Workflows:

  NR AI Workflow         -> DT Automation Workflow
                            (`builtin:automation.workflows` — note name
                            collision with the Gen3 Workflow product)
  NR Destinations        -> Workflow action tasks
                            (delegates to NotificationTransformer)
  NR Enrichments         -> Workflow enrichment steps (tasks with
                            `dynatrace.automations:dql-query` or
                            `http-function` actions)
  NR Decisions (correlation rules)
                         -> Davis causal engine (auto — no direct
                            migration; documented as replaced)
  NR Anomaly detection settings
                         -> `builtin:davis.anomaly-detectors` envelopes

The transformer explicitly renames workflows with a `[NR AIOps → DT]`
prefix so operators can tell these apart from Gen3 Workflows built from
Alert Policies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger()


@dataclass
class AIOpsTransformResult:
    success: bool
    workflows: List[Dict[str, Any]] = field(default_factory=list)
    anomaly_detectors: List[Dict[str, Any]] = field(default_factory=list)
    decisions_notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class AIOpsTransformer:
    """NR AIOps config -> DT Workflows + Davis detectors + decision notes."""

    def transform(self, nr_aiops: Dict[str, Any]) -> AIOpsTransformResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            ai_workflows = nr_aiops.get("workflows") or []
            decisions = nr_aiops.get("decisions") or []
            anomaly_settings = nr_aiops.get("anomalyDetectionSettings") or []

            workflows_out: List[Dict[str, Any]] = []
            for wf in ai_workflows:
                workflows_out.append(self._workflow(wf, warnings))

            detectors_out: List[Dict[str, Any]] = []
            for setting in anomaly_settings:
                detectors_out.append(self._anomaly_detector(setting))

            decision_notes: List[str] = []
            for d in decisions:
                decision_notes.append(
                    f"Decision '{d.get('name', 'unnamed')}' "
                    "is NOT migrated. Davis's causal engine replaces manual "
                    f"correlation rules. Original logic: "
                    f"{d.get('expression', '(none)')}"
                )

            if decisions:
                warnings.append(
                    f"{len(decisions)} NR Decisions encountered — Davis "
                    "replaces manual correlation. Recorded as decisions_notes "
                    "for reference only."
                )

            logger.info(
                "Transformed NR AIOps config",
                workflows=len(workflows_out),
                detectors=len(detectors_out),
                decisions=len(decisions),
            )
            return AIOpsTransformResult(
                success=True,
                workflows=workflows_out,
                anomaly_detectors=detectors_out,
                decisions_notes=decision_notes,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("AIOps transformation failed", error=str(exc))
            return AIOpsTransformResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    # ------------------------------------------------------------------

    def _workflow(
        self, nr_wf: Dict[str, Any], warnings: List[str]
    ) -> Dict[str, Any]:
        name = nr_wf.get("name", "unnamed-ai-workflow")
        destinations = nr_wf.get("destinations") or []
        enrichments = nr_wf.get("enrichments") or []

        tasks: List[Dict[str, Any]] = []
        for idx, enr in enumerate(enrichments):
            tasks.append(
                {
                    "name": f"enrich_{idx}",
                    "action": "dynatrace.automations:dql-query",
                    "active": True,
                    "description": f"Migrated NR enrichment: {enr.get('name', '')}",
                    "input": {
                        "query": enr.get("nrql", "")
                        or "// TODO: translate NRQL enrichment",
                    },
                    "position": {"x": 0, "y": idx + 1},
                }
            )

        for i, dest in enumerate(destinations, start=len(tasks) + 1):
            tasks.append(
                {
                    "name": f"destination_{i}",
                    "action": "dynatrace.automations:http-function",
                    "active": True,
                    "description": f"Migrated NR destination: {dest.get('name', '')}",
                    "input": {
                        "method": "POST",
                        "url": dest.get("url", "<set-target-webhook>"),
                        "headers": [{"key": "Content-Type", "value": "application/json"}],
                        "body": dest.get("payloadTemplate", "{}"),
                    },
                    "position": {"x": 0, "y": i + 1},
                }
            )

        if not tasks:
            warnings.append(
                f"AI workflow '{name}' had no destinations or enrichments — "
                "emitted an empty shell."
            )

        return {
            "title": f"[NR AIOps → DT] {name}",
            "description": "Migrated from NR AI workflow.",
            "private": False,
            "trigger": {
                "event": {
                    "active": True,
                    "config": {
                        "davis_event": {
                            "eventType": "CUSTOM_ALERT",
                            "anyEventMatches": True,
                        }
                    },
                }
            },
            "tasks": tasks,
        }

    def _anomaly_detector(self, setting: Dict[str, Any]) -> Dict[str, Any]:
        """Emit a `builtin:davis.anomaly-detectors` settings envelope.

        Schema (v1.0.14, verified 2026-04-20 against sprint tenant):
          value.{enabled,title,description,source,executionSettings,
                 analyzer{name,input[{key,value}]},
                 eventTemplate{properties[{key,value}]}}

        `analyzer.name` picks an auto-adaptive analyzer since the NR AIOps
        anomaly-detection settings we migrate are always adaptive (they use
        sensitivity/stddev thresholds, not fixed values). The DQL query is
        synthesized from the NR metricKey + aggregation.
        """
        name = setting.get("name", "anomaly-setting")
        detector_id = "".join(
            c if c.isalnum() or c == "-" else "-"
            for c in f"davis-aiops-{name}".lower()
        )[:180]
        metric_key = setting.get("metricKey", "builtin:host.cpu.usage")
        agg = setting.get("aggregation", "AVG").lower()
        sensitivity = float(setting.get("sensitivity", 3.0))
        dql_query = f"timeseries {agg}({metric_key})"

        return {
            "schemaId": "builtin:davis.anomaly-detectors",
            "scope": "environment",
            "detectorId": detector_id,
            "value": {
                "enabled": bool(setting.get("enabled", True)),
                "title": f"[NR AIOps] {name}",
                "description": "Migrated anomaly-detection setting.",
                "source": "newrelic-migration",
                "executionSettings": {"actor": None, "queryOffset": None},
                "analyzer": {
                    "name": (
                        "dt.statistics.ui.anomaly_detection"
                        ".AutoAdaptiveAnomalyDetectionAnalyzer"
                    ),
                    "input": [
                        {"key": "query", "value": dql_query},
                        {"key": "numberOfSignalFluctuations",
                         "value": str(sensitivity)},
                        {"key": "alertCondition", "value": "ABOVE"},
                        {"key": "alertOnMissingData", "value": "false"},
                        {"key": "violatingSamples", "value": "3"},
                        {"key": "slidingWindow", "value": "5"},
                        {"key": "dealertingSamples", "value": "5"},
                    ],
                },
                "eventTemplate": {
                    "properties": [
                        {"key": "event.type", "value": "CUSTOM_ALERT"},
                        {"key": "event.name", "value": f"[NR AIOps] {name}"},
                        {"key": "migrated.from", "value": "newrelic-aiops"},
                    ],
                },
            },
        }

    def transform_all(
        self, configs: List[Dict[str, Any]]
    ) -> List[AIOpsTransformResult]:
        return [self.transform(c) for c in configs]
