"""
Custom Event Ingest Transformer — Gen3 target.

NR custom event types (registered via the Event API, used with
`FROM <CustomType>` NRQL) map to Dynatrace bizevents. Each NR custom
event record becomes a DT CloudEvent-shaped bizevent payload ingested via:
    POST /platform/classic/environment-api/v2/bizevents/ingest

The transformer also emits source-mapping guidance so NRQL like
`FROM CheckoutCompleted SELECT count(*)` translates to
`fetch bizevents | filter event.type == "CheckoutCompleted"`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class CustomEventIngestResult:
    success: bool
    bizevents: List[Dict[str, Any]] = field(default_factory=list)
    dql_source_mapping: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class CustomEventIngestTransformer:
    """NR custom event type + records -> DT bizevent payloads."""

    INGEST_ENDPOINT = "/platform/classic/environment-api/v2/bizevents/ingest"

    def transform(self, nr_event_batch: Dict[str, Any]) -> CustomEventIngestResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            event_type = nr_event_batch.get("eventType", "UnknownEvent")
            records = nr_event_batch.get("records", []) or []

            bizevents: List[Dict[str, Any]] = []
            for rec in records:
                # NR timestamp comes as epoch ms; DT bizevent accepts RFC3339
                # in its `time` field (optional; server-stamped if absent).
                bizevents.append(
                    {
                        "specversion": "1.0",
                        "type": event_type,
                        "source": "newrelic-migration",
                        "time": rec.get("timestamp"),
                        "id": rec.get("id") or rec.get("guid") or None,
                        "data": {
                            k: v
                            for k, v in rec.items()
                            if k not in ("eventType", "timestamp", "id", "guid")
                        },
                    }
                )

            dql_mapping = (
                f'# NRQL:  FROM {event_type} SELECT count(*) SINCE 1 day ago\n'
                f'# DQL:   fetch bizevents, from:now()-1d '
                f'| filter event.type == "{event_type}" '
                f'| summarize count()'
            )

            if not records:
                warnings.append(
                    f"Event type '{event_type}' has no records — emitted an "
                    "empty payload. Operator may still want to register the "
                    "event type in DT by sending one sample event."
                )

            logger.info(
                "Transformed custom event batch to bizevents",
                event_type=event_type,
                count=len(records),
            )
            return CustomEventIngestResult(
                success=True,
                bizevents=bizevents,
                dql_source_mapping=dql_mapping,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Custom event ingest transformation failed", error=str(exc))
            return CustomEventIngestResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, batches: List[Dict[str, Any]]
    ) -> List[CustomEventIngestResult]:
        return [self.transform(b) for b in batches]
