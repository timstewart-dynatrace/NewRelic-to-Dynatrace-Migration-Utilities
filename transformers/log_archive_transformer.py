"""
Log Archive Transformer — Gen3 target.

NR Log Live Archive + Streaming Export configs map to Dynatrace Grail
buckets plus OpenPipeline egress processors. Compliance tags carry
through; retention is expressed as Grail bucket retention days.

Emits:
  - `builtin:logmonitoring.log-storage-settings` envelope per bucket
  - `builtin:openpipeline.logs.pipelines` egress processor for
    streaming-export destinations (S3, GCS, Azure Blob)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


_EGRESS_DESTINATION_MAP = {
    "s3": "s3",
    "aws_s3": "s3",
    "gcs": "gcs",
    "google_cloud_storage": "gcs",
    "azure_blob": "azure_blob",
    "azure_storage": "azure_blob",
}


@dataclass
class LogArchiveResult:
    success: bool
    bucket_envelope: Optional[Dict[str, Any]] = None
    egress_processor: Optional[Dict[str, Any]] = None
    runbook: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class LogArchiveTransformer:
    """NR Log Live Archive / Streaming Export -> DT Grail bucket + egress."""

    def transform(self, nr_config: Dict[str, Any]) -> LogArchiveResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            name = nr_config.get("name", "unnamed-archive")
            filter_nrql = nr_config.get("filterNRQL", "") or ""
            retention_days = int(nr_config.get("retentionDays", 35))
            compliance_tags = nr_config.get("complianceTags") or []
            destination = str(nr_config.get("destination", "")).lower()

            safe_bucket = "".join(
                c if c.isalnum() else "_" for c in name.lower()
            )[:80]
            bucket_envelope = {
                "schemaId": "builtin:logmonitoring.log-storage-settings",
                "scope": "environment",
                "value": {
                    "name": f"migrated_{safe_bucket}",
                    "displayName": f"[Migrated] {name}",
                    "retentionDays": retention_days,
                    "bucketName": f"migrated_{safe_bucket}",
                    "enabled": True,
                    "tags": list(compliance_tags),
                },
            }

            egress_processor: Optional[Dict[str, Any]] = None
            if destination:
                dt_dest = _EGRESS_DESTINATION_MAP.get(destination)
                if dt_dest is None:
                    warnings.append(
                        f"Unknown streaming-export destination '{destination}' — "
                        "egress processor not emitted."
                    )
                else:
                    egress_processor = {
                        "schemaId": "builtin:openpipeline.logs.pipelines",
                        "scope": "environment",
                        "value": {
                            "name": f"[Migrated log egress] {name}",
                            "enabled": True,
                            "processor": {
                                "type": "export",
                                "id": f"egress-{safe_bucket}",
                                "matcher": (
                                    f"/* TODO: translate NRQL filter: {filter_nrql[:80]} */"
                                    if filter_nrql
                                    else "true"
                                ),
                                "destination": dt_dest,
                                "bucketReference": nr_config.get(
                                    "destinationBucket", "<set-after-import>"
                                ),
                                "format": "jsonl",
                                "compression": "gzip",
                            },
                        },
                    }
                    if filter_nrql:
                        warnings.append(
                            "Log-archive filter NRQL carried through as a TODO "
                            "comment — verify the DPL matcher after import."
                        )

            runbook = {
                "bucket_name": f"migrated_{safe_bucket}",
                "retention_days": retention_days,
                "compliance_tags": list(compliance_tags),
                "non_migratable": (
                    "Historical NR-archived logs cannot be re-ingested into Grail "
                    "(see docs/out-of-scope.md §1). Run the legacy and Gen3 "
                    "pipelines in parallel during the migration window, or use "
                    "tools/nrdb_archive.py for local JSONL snapshots."
                ),
                "credentials_note": (
                    "Egress destination credentials (IAM role ARN for S3, "
                    "service-account key for GCS, SAS token for Azure Blob) "
                    "must be configured on the DT side after import — they "
                    "never migrate."
                ),
            }

            logger.info(
                "Transformed log archive",
                name=name,
                destination=destination,
                retention=retention_days,
            )
            return LogArchiveResult(
                success=True,
                bucket_envelope=bucket_envelope,
                egress_processor=egress_processor,
                runbook=runbook,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Log archive transformation failed", error=str(exc))
            return LogArchiveResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, configs: List[Dict[str, Any]]
    ) -> List[LogArchiveResult]:
        return [self.transform(c) for c in configs]
