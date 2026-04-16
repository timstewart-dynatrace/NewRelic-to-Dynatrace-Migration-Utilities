"""
OpenTelemetry Collector Transformer — Gen3 target.

Broader than `OTelMetricsTransformer`: handles the full collector
configuration (traces + metrics + logs signals) and translates the
OTel Collector processor pipeline, not just the OTLP exporter block.

Ported from nrql-engine `src/transformers/otel-collector.transformer.ts`.

Emits:
  - Per-signal DT OTLP exporter blocks (endpoint + Api-Token auth)
  - `builtin:otel.ingest-mappings` settings override when resource
    attributes need tenant-side filtering
  - Processor-by-processor translation: attributes / filter / batch /
    memory_limiter / resource, plus a warning for unknown processors
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


# Which OTel collector processors we translate; unknown kinds emit a
# warning and are passed through unchanged in the output collector YAML.
_KNOWN_PROCESSORS = {"attributes", "filter", "batch", "memory_limiter", "resource"}

_SIGNAL_PATHS = {
    "traces": "/api/v2/otlp/v1/traces",
    "metrics": "/api/v2/otlp/v1/metrics",
    "logs": "/api/v2/otlp/v1/logs",
}


@dataclass
class OTelCollectorResult:
    success: bool
    exporter_blocks: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    ingest_mappings_envelope: Optional[Dict[str, Any]] = None
    translated_processors: List[Dict[str, Any]] = field(default_factory=list)
    collector_yaml: Optional[str] = None
    runbook: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class OTelCollectorTransformer:
    """NR OTel Collector config -> DT OTLP ingest across all signals."""

    def transform(self, nr_config: Dict[str, Any]) -> OTelCollectorResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            name = nr_config.get("name", "unnamed-collector")
            signals: List[str] = list(nr_config.get("signals") or ["traces", "metrics", "logs"])
            protocol = str(nr_config.get("protocol", "grpc")).lower()
            resource_attrs = nr_config.get("resourceAttributes") or {}
            processors = nr_config.get("processors") or []

            if protocol not in ("grpc", "http"):
                warnings.append(
                    f"Unknown OTLP protocol '{protocol}' — defaulted to grpc."
                )
                protocol = "grpc"

            if nr_config.get("apiKey"):
                warnings.append(
                    "NR license key present in input — secrets never migrate. "
                    "Provision a DT API token with metrics.ingest / events.ingest "
                    "scopes and reference via AWS Secrets Manager / equivalent."
                )

            # Per-signal exporter blocks.
            exporter_blocks: Dict[str, Dict[str, Any]] = {}
            for sig in signals:
                if sig not in _SIGNAL_PATHS:
                    warnings.append(
                        f"Unknown OTel signal '{sig}' — skipped. "
                        "Supported: traces, metrics, logs."
                    )
                    continue
                endpoint_host = "<DT_URL_HOST>:443" if protocol == "grpc" else (
                    f"<DT_URL>{_SIGNAL_PATHS[sig]}"
                )
                exporter_blocks[sig] = {
                    "endpoint": endpoint_host,
                    "headers": {
                        "Authorization": "${DT_API_TOKEN_" + sig.upper() + "_INGEST}",
                    },
                    "compression": "gzip",
                    "tls": {"insecure": False},
                }

            # Resource-attribute filtering envelope (optional).
            ingest_mappings_envelope: Optional[Dict[str, Any]] = None
            if resource_attrs:
                ingest_mappings_envelope = {
                    "schemaId": "builtin:otel.ingest-mappings",
                    "scope": "environment",
                    "value": {
                        "name": f"[Migrated] {name} resource filter",
                        "enabled": True,
                        "requiredAttributes": list(resource_attrs.keys()),
                        "attributeDefaults": dict(resource_attrs),
                    },
                }

            # Processor-by-processor translation.
            translated: List[Dict[str, Any]] = []
            for proc in processors:
                kind = proc.get("kind", "unknown")
                if kind == "attributes":
                    # attribute insert/update/upsert/delete/hash/extract — keep.
                    translated.append({"kind": "attributes", "actions": proc.get("actions", [])})
                elif kind == "filter":
                    # include/exclude filters — DT accepts the same OTTL expressions.
                    translated.append({
                        "kind": "filter",
                        "match": proc.get("match", "include"),
                        "expression": proc.get("expression", ""),
                    })
                elif kind == "batch":
                    translated.append({
                        "kind": "batch",
                        "timeoutSeconds": int(proc.get("timeoutSeconds", 10)),
                        "sendBatchSize": int(proc.get("sendBatchSize", 8192)),
                    })
                elif kind == "memory_limiter":
                    translated.append({
                        "kind": "memory_limiter",
                        "limitMiB": int(proc.get("limitMiB", 512)),
                        "checkIntervalSeconds": int(
                            proc.get("checkIntervalSeconds", 5)
                        ),
                    })
                elif kind == "resource":
                    translated.append({
                        "kind": "resource",
                        "attributes": dict(proc.get("attributes", {})),
                    })
                else:
                    warnings.append(
                        f"Unknown collector processor kind '{kind}' for '{proc.get('name', 'unnamed')}' "
                        "— passed through unchanged; review before deploying."
                    )
                    translated.append(proc)

            collector_yaml = _render_collector_yaml(signals, exporter_blocks, translated)

            runbook = {
                "signals": signals,
                "protocol": protocol,
                "manual_steps": [
                    "Mint DT API tokens with appropriate ingest scopes "
                    "(metrics.ingest, events.ingest, logs.ingest).",
                    "Inject tokens via AWS Secrets Manager, Vault, or "
                    "your collector's secrets plugin — never inline.",
                    "Run the collector in dual-export mode (NR + DT) for 24h, "
                    "then remove the NR exporter.",
                ],
                "verify_queries": {
                    sig: f'// DT: fetch {sig} | filter dt.metric.source == "otlp"'
                    for sig in signals
                },
            }

            logger.info(
                "Transformed OTel collector config",
                name=name,
                signals=signals,
                processors=len(translated),
            )
            return OTelCollectorResult(
                success=True,
                exporter_blocks=exporter_blocks,
                ingest_mappings_envelope=ingest_mappings_envelope,
                translated_processors=translated,
                collector_yaml=collector_yaml,
                runbook=runbook,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("OTel collector transformation failed", error=str(exc))
            return OTelCollectorResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, configs: List[Dict[str, Any]]
    ) -> List[OTelCollectorResult]:
        return [self.transform(c) for c in configs]


def _render_collector_yaml(
    signals: List[str],
    exporter_blocks: Dict[str, Dict[str, Any]],
    translated: List[Dict[str, Any]],
) -> str:
    """Render a minimal collector config YAML snippet the operator can drop in."""
    lines: List[str] = ["# Migrated OpenTelemetry Collector config"]
    lines.append("exporters:")
    for sig in signals:
        if sig not in exporter_blocks:
            continue
        ep = exporter_blocks[sig]
        lines.append(f"  otlp/dynatrace_{sig}:")
        lines.append(f"    endpoint: {ep['endpoint']}")
        lines.append("    headers:")
        for k, v in ep["headers"].items():
            lines.append(f"      {k}: {v}")
        lines.append(f"    compression: {ep['compression']}")

    if translated:
        lines.append("processors:")
        for i, proc in enumerate(translated):
            lines.append(f"  migrated_{i}_{proc.get('kind', 'unknown')}:")
            for k, v in proc.items():
                if k == "kind":
                    continue
                lines.append(f"    {k}: {v!r}")

    lines.append("service:")
    lines.append("  pipelines:")
    for sig in signals:
        if sig not in exporter_blocks:
            continue
        lines.append(f"    {sig}:")
        lines.append("      receivers: [otlp]")
        proc_names = [
            f"migrated_{i}_{p.get('kind', 'unknown')}"
            for i, p in enumerate(translated)
        ]
        lines.append(f"      processors: [{', '.join(proc_names) or 'batch'}]")
        lines.append(f"      exporters: [otlp/dynatrace_{sig}]")
    return "\n".join(lines) + "\n"
