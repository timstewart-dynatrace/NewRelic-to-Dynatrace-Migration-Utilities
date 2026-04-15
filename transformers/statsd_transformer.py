"""
StatsD Transformer — Gen3 target.

Ported from nrql-engine TS sibling
(`src/transformers/statsd.transformer.ts`). NR StatsD ingestion via the
infra agent's StatsD listener maps to Dynatrace StatsD ingestion on an
ActiveGate (`builtin:statsd.metrics`). Metric prefix rules + tag
mappings carry over.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class StatsDResult:
    success: bool
    envelope: Optional[Dict[str, Any]] = None
    runbook: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class StatsDTransformer:
    """NR StatsD ingestion config -> DT StatsD metrics (ActiveGate)."""

    def transform(self, nr_config: Dict[str, Any]) -> StatsDResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            name = nr_config.get("name", "unnamed-statsd")
            listen_port = int(nr_config.get("listenPort", 8125))
            metric_prefix = nr_config.get("metricPrefix", "")
            tag_mappings = nr_config.get("tagMappings") or {}
            aggregation_interval = int(
                nr_config.get("aggregationIntervalSeconds", 10)
            )

            if aggregation_interval not in (5, 10, 30, 60):
                warnings.append(
                    f"StatsD aggregation interval {aggregation_interval}s is "
                    "non-standard for DT; verify ActiveGate config after import."
                )

            envelope = {
                "schemaId": "builtin:statsd.metrics",
                "scope": "environment",
                "value": {
                    "name": f"[Migrated] {name}",
                    "enabled": True,
                    "listenPort": listen_port,
                    "aggregationIntervalSeconds": aggregation_interval,
                    "metricPrefix": metric_prefix,
                    "tagMappings": [
                        {"source": src, "target": tgt}
                        for src, tgt in tag_mappings.items()
                    ],
                    "activeGateReference": "<pick-ActiveGate-after-import>",
                },
            }

            runbook = {
                "activegate_requirement": (
                    "DT StatsD ingestion runs on an ActiveGate with the StatsD "
                    "module enabled. Install or designate an existing "
                    "ActiveGate before applying this envelope."
                ),
                "nr_infra_cleanup": [
                    "Disable the StatsD listener in the NR infrastructure-agent "
                    "config: `statsd.enabled: false`",
                    "Redirect clients to the ActiveGate host:port.",
                ],
                "verify": (
                    "Send a test metric: "
                    "`echo 'migration.test:1|c' | nc -u -w1 <activegate-host> "
                    f"{listen_port}`. Confirm in DT: "
                    "`timeseries count() by: {metric.name} | "
                    "filter metric.name startsWith \"migration.\"`"
                ),
            }

            logger.info(
                "Transformed StatsD config",
                name=name,
                port=listen_port,
                prefix=metric_prefix,
            )
            return StatsDResult(
                success=True, envelope=envelope, runbook=runbook, warnings=warnings
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("StatsD transformation failed", error=str(exc))
            return StatsDResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, configs: List[Dict[str, Any]]
    ) -> List[StatsDResult]:
        return [self.transform(c) for c in configs]
