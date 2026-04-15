"""
Prometheus Transformer — Gen3 target.

NR Prometheus Agent (aka nri-prometheus) configuration maps to Dynatrace
Prometheus ingestion via remote-write or OneAgent's Prometheus endpoint
scraper:

  NR Prometheus scrape config  -> DT OneAgent Prometheus endpoint scrape
                                  (`builtin:prometheus.exporter`) or
                                  remote-write config
                                  (`builtin:otel.ingest.prometheus`)

Scrape configs with relabeling rules are preserved as DT sample-filter
rules; histogram buckets transfer unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class PrometheusTransformResult:
    success: bool
    scrape_envelopes: List[Dict[str, Any]] = field(default_factory=list)
    remote_write_envelope: Optional[Dict[str, Any]] = None
    runbook: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class PrometheusTransformer:
    """NR Prometheus Agent config -> DT Prometheus ingestion."""

    def transform(self, nr_config: Dict[str, Any]) -> PrometheusTransformResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            mode = str(nr_config.get("mode", "scrape")).lower()
            targets = nr_config.get("targets") or []
            relabel_configs = nr_config.get("relabelConfigs") or []

            scrape_envelopes: List[Dict[str, Any]] = []
            for t in targets:
                scrape_envelopes.append(
                    {
                        "schemaId": "builtin:prometheus.exporter",
                        "scope": "environment",
                        "value": {
                            "name": f"[Migrated] {t.get('job', 'unnamed')}",
                            "url": t.get("url", ""),
                            "scrapeIntervalSeconds": int(
                                t.get("scrapeIntervalSeconds", 60)
                            ),
                            "honorLabels": bool(t.get("honorLabels", True)),
                            "metricFilters": [
                                {
                                    "action": rc.get("action", "keep"),
                                    "regex": rc.get("regex", ""),
                                    "sourceLabels": rc.get("sourceLabels") or [],
                                }
                                for rc in relabel_configs
                            ],
                            "enabled": bool(t.get("enabled", True)),
                        },
                    }
                )

            remote_write_envelope: Optional[Dict[str, Any]] = None
            if mode == "remote_write":
                remote_write_envelope = {
                    "schemaId": "builtin:otel.ingest.prometheus",
                    "scope": "environment",
                    "value": {
                        "enabled": True,
                        "endpoint": "<DT_URL>/api/v2/otlp/v1/metrics",
                        "authHeader": "Authorization: Api-Token <DT_API_TOKEN>",
                    },
                }
                warnings.append(
                    "Remote-write mode points at DT OTLP — ensure an ingest "
                    "token exists with metrics.ingest scope and rotate the "
                    "existing NR token out of any Prometheus config."
                )

            runbook = {
                "mode": mode,
                "nri_prometheus_uninstall": [
                    "Stop / remove the nri-prometheus pod in Kubernetes "
                    "(`helm uninstall newrelic-prometheus-agent -n newrelic`).",
                    "Remove the nri-prometheus binary if running on a VM.",
                ],
                "verify": (
                    "After applying the DT scrape config, verify metrics appear "
                    "in `fetch metrics | filter dt.metric.source == \"prometheus\"` "
                    "within 2 minutes."
                ),
            }

            logger.info(
                "Transformed Prometheus config",
                mode=mode,
                targets=len(scrape_envelopes),
            )
            return PrometheusTransformResult(
                success=True,
                scrape_envelopes=scrape_envelopes,
                remote_write_envelope=remote_write_envelope,
                runbook=runbook,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Prometheus transformation failed", error=str(exc))
            return PrometheusTransformResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, configs: List[Dict[str, Any]]
    ) -> List[PrometheusTransformResult]:
        return [self.transform(c) for c in configs]
