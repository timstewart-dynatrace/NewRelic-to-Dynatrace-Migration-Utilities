"""
CloudWatch Metric Streams Transformer — Gen3 target.

Ported from nrql-engine TS sibling
(`src/transformers/cloudwatch-metric-streams.transformer.ts`). NR's
CloudWatch Metric Streams integration (Kinesis Firehose → NR ingest)
maps to Dynatrace's AWS Metric Streams ingestion via Firehose.

Complementary to `CloudIntegrationTransformer` (Phase 18) which handles
the API-poll AWS integration; this module handles the *stream* path,
which is faster and recommended for customers with > 500 resources.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class CloudWatchMetricStreamsResult:
    success: bool
    envelope: Optional[Dict[str, Any]] = None
    firehose_terraform: Optional[str] = None
    runbook: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class CloudWatchMetricStreamsTransformer:
    """NR CloudWatch Metric Streams config -> DT AWS Metric Streams ingestion."""

    def transform(
        self, nr_config: Dict[str, Any]
    ) -> CloudWatchMetricStreamsResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            name = nr_config.get("name", "unnamed-metric-stream")
            aws_account = nr_config.get("awsAccountId", "")
            region = nr_config.get("region", "us-east-1")
            namespaces = nr_config.get("includeNamespaces") or []
            output_format = str(nr_config.get("outputFormat", "opentelemetry")).lower()

            if output_format not in ("opentelemetry", "json"):
                warnings.append(
                    f"Unknown outputFormat '{output_format}' — defaulted to "
                    "opentelemetry (required by DT)."
                )
                output_format = "opentelemetry"
            if output_format != "opentelemetry":
                warnings.append(
                    "DT requires the OpenTelemetry 1.0 output format for "
                    "Metric Streams. Update the CloudWatch stream before "
                    "pointing Firehose at DT."
                )

            envelope = {
                "schemaId": "builtin:aws.metric-streams",
                "scope": "environment",
                "value": {
                    "name": f"[Migrated] {name}",
                    "enabled": True,
                    "awsAccountId": aws_account,
                    "region": region,
                    "includeNamespaces": [
                        {"namespace": ns} for ns in namespaces
                    ],
                    "outputFormat": "OPENTELEMETRY_1_0",
                    "ingestTokenReference": "<fill-after-token-rotation>",
                },
            }

            firehose_terraform = _firehose_snippet(
                name=name, region=region, aws_account=aws_account
            )

            runbook = {
                "token_scope_required": "metrics.ingest",
                "aws_steps": [
                    "In the AWS account, reconfigure the CloudWatch Metric "
                    "Stream's output format to `OpenTelemetry 1.0`.",
                    "Update the Kinesis Firehose destination to point at the "
                    "DT OTLP ingest endpoint (see the Terraform snippet below).",
                    "Rotate the ingest token; inject via AWS Secrets Manager.",
                ],
                "nr_deprovision": (
                    "Once metrics appear in DT, delete the NR Kinesis Firehose "
                    "and revoke the NR-side IAM role."
                ),
            }

            logger.info(
                "Transformed CloudWatch Metric Streams",
                name=name,
                region=region,
                namespaces=len(namespaces),
            )
            return CloudWatchMetricStreamsResult(
                success=True,
                envelope=envelope,
                firehose_terraform=firehose_terraform,
                runbook=runbook,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "CloudWatch Metric Streams transformation failed",
                error=str(exc),
            )
            return CloudWatchMetricStreamsResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, configs: List[Dict[str, Any]]
    ) -> List[CloudWatchMetricStreamsResult]:
        return [self.transform(c) for c in configs]


def _firehose_snippet(name: str, region: str, aws_account: str) -> str:
    slug = "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")
    return (
        f'resource "aws_kinesis_firehose_delivery_stream" "dt_{slug}" {{\n'
        f'  name        = "dt-metrics-{slug}"\n'
        f'  destination = "http_endpoint"\n'
        f"  http_endpoint_configuration {{\n"
        f'    url                = "https://<DT_URL_HOST>/api/v2/otlp/v1/metrics"\n'
        f'    name               = "dynatrace-otlp-metrics"\n'
        f"    access_key         = data.aws_secretsmanager_secret_version.dt_ingest.secret_string\n"
        f"    buffering_size     = 5\n"
        f"    buffering_interval = 60\n"
        f"    request_configuration {{\n"
        f'      content_encoding = "GZIP"\n'
        f"    }}\n"
        f"  }}\n"
        f"  server_side_encryption {{ enabled = true }}\n"
        f"}}\n"
    )
