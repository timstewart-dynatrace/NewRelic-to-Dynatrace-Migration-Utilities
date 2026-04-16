"""
OTel Metrics Transformer — Gen3 target.

Ported from nrql-engine TS sibling
(`src/transformers/otel-metrics.transformer.ts`). Converts NR OTel
metric ingestion config (OTLP endpoint + headers for OpenTelemetry
collectors pointing at NR) into Dynatrace OTLP metrics ingestion
config (`builtin:otel.ingest.metrics`).

Distinct from `PrometheusTransformer`:
  * Prometheus transformer handles `nri-prometheus` scrape configs and
    Prometheus remote-write endpoints.
  * This transformer handles OTel metrics (OTLP protocol, gRPC or HTTP)
    where the customer has already standardized on OpenTelemetry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class OTelMetricsResult:
    success: bool
    ingest_envelope: Optional[Dict[str, Any]] = None
    collector_config_snippet: Optional[str] = None
    runbook: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class OTelMetricsTransformer:
    """NR OTel metrics ingestion config -> DT OTLP metrics ingestion."""

    def transform(self, nr_config: Dict[str, Any]) -> OTelMetricsResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            name = nr_config.get("name", "unnamed-otel-metrics")
            protocol = str(nr_config.get("protocol", "grpc")).lower()
            resource_attributes = nr_config.get("resourceAttributes") or {}
            temporality = str(nr_config.get("temporality", "cumulative")).lower()

            if protocol not in ("grpc", "http"):
                warnings.append(
                    f"Unknown OTLP protocol '{protocol}' — defaulted to grpc."
                )
                protocol = "grpc"

            ingest_envelope = {
                "schemaId": "builtin:otel.ingest.metrics",
                "scope": "environment",
                "value": {
                    "name": f"[Migrated] {name}",
                    "enabled": True,
                    "protocol": protocol.upper(),
                    "temporality": temporality.upper(),
                    "resourceAttributeFiltering": {
                        "enabled": bool(resource_attributes),
                        "requiredAttributes": list(resource_attributes.keys()),
                    },
                },
            }

            dt_endpoint = (
                "<DT_URL>/api/v2/otlp"
                if protocol == "http"
                else "<DT_URL_HOST>:443"
            )
            collector_config_snippet = (
                "# Replace the NR OTLP exporter in your OpenTelemetry collector\n"
                "# config with this DT-pointing exporter. Secrets live outside\n"
                "# this file — set via env vars at runtime.\n"
                f"exporters:\n"
                f"  otlp/dynatrace:\n"
                f"    endpoint: {dt_endpoint}\n"
                f"    headers:\n"
                f"      Authorization: ${{DT_API_TOKEN_METRICS_INGEST}}\n"
                f"    compression: gzip\n"
                f"    tls:\n"
                f"      insecure: false\n"
                f"service:\n"
                f"  pipelines:\n"
                f"    metrics:\n"
                f"      receivers: [otlp]\n"
                f"      processors: [batch]\n"
                f"      exporters: [otlp/dynatrace]\n"
            )

            runbook = {
                "token_scope_required": "metrics.ingest",
                "pre_deploy_steps": [
                    "Mint a DT API token with `metrics.ingest` scope.",
                    "Update the OTel collector's exporter config per the "
                    "snippet above; do NOT delete the NR exporter until "
                    "metrics are visible in DT.",
                    "Run the collector in dual-export mode for 24h, then "
                    "remove the NR exporter.",
                ],
                "verify": (
                    "In DT, run `timeseries count() by: {metric.name} "
                    "| filter dt.metric.source == \"otlp\" | limit 20` "
                    "to confirm ingestion."
                ),
            }

            logger.info(
                "Transformed OTel metrics config",
                name=name,
                protocol=protocol,
                temporality=temporality,
            )
            return OTelMetricsResult(
                success=True,
                ingest_envelope=ingest_envelope,
                collector_config_snippet=collector_config_snippet,
                runbook=runbook,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("OTel metrics transformation failed", error=str(exc))
            return OTelMetricsResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, configs: List[Dict[str, Any]]
    ) -> List[OTelMetricsResult]:
        return [self.transform(c) for c in configs]
