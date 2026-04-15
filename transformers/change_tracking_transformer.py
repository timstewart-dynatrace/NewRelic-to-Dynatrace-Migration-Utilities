"""
Change Tracking Transformer — Gen3 target.

NR change-tracking / deployment markers are ingested via:
  * APM deployment API  (`POST /v2/applications/:id/deployments.json`)
  * Change Tracking API (`POST /v1/changes`)

Dynatrace exposes deployment + configuration events via the Classic Events
API (`POST /api/v2/events/ingest`) with `eventType` in:
  * `CUSTOM_DEPLOYMENT`
  * `CUSTOM_CONFIGURATION`
  * `CUSTOM_INFO`

This transformer emits a per-change payload ready for POSTing to the DT
events endpoint. Historical NR change events are importable as a
replayable archive (marked "historical" via a property) but are not
authoritative — DT maintains its own causal timeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


_NR_TO_DT_EVENT_TYPE = {
    "deployment": "CUSTOM_DEPLOYMENT",
    "feature_flag": "CUSTOM_CONFIGURATION",
    "infrastructure": "CUSTOM_CONFIGURATION",
    "chaos_experiment": "CUSTOM_INFO",
    "business": "CUSTOM_INFO",
    "config": "CUSTOM_CONFIGURATION",
    "operational": "CUSTOM_INFO",
}


@dataclass
class ChangeTrackingResult:
    success: bool
    events: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class ChangeTrackingTransformer:
    """NR change markers -> DT events API payloads."""

    def transform(self, nr_change: Dict[str, Any]) -> ChangeTrackingResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            category = str(nr_change.get("category", "deployment")).lower()
            dt_event_type = _NR_TO_DT_EVENT_TYPE.get(
                category, "CUSTOM_INFO"
            )
            if category not in _NR_TO_DT_EVENT_TYPE:
                warnings.append(
                    f"Unknown NR change category '{category}' — defaulted to "
                    "CUSTOM_INFO. Verify the target event type."
                )

            entity_guid = nr_change.get("entityGuid", "")
            version = nr_change.get("version") or nr_change.get("deploymentVersion", "")
            user = nr_change.get("user", "")
            description = nr_change.get("description", "")
            timestamp = nr_change.get("timestamp")  # epoch ms
            commit = nr_change.get("commit", "")
            changelog = nr_change.get("changelog", "")

            event_payload = {
                "eventType": dt_event_type,
                "title": f"[Migrated] {category}: {version or 'change'}",
                "startTime": timestamp,
                "endTime": timestamp,
                "entitySelector": (
                    f'tag("nr.entity.guid:{entity_guid}")' if entity_guid else ""
                ),
                "properties": {
                    "migrated.from": "newrelic",
                    "nr.category": category,
                    "nr.version": version,
                    "nr.user": user,
                    "nr.commit": commit,
                    "nr.changelog": changelog,
                    "nr.description": description,
                    "historical": "true",  # marker so DT users know this is replayed
                },
            }

            logger.info(
                "Transformed change/deployment marker",
                category=category,
                dt_event_type=dt_event_type,
            )
            return ChangeTrackingResult(
                success=True, events=[event_payload], warnings=warnings
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Change tracking transformation failed", error=str(exc))
            return ChangeTrackingResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, changes: List[Dict[str, Any]]
    ) -> List[ChangeTrackingResult]:
        return [self.transform(c) for c in changes]
