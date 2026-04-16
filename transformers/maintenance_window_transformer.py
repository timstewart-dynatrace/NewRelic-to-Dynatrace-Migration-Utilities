"""
Maintenance Window + Mute Rule Transformer — Gen3 target.

NR maintenance windows (one-off and recurring) and NRQL-based mute rules
both map to Dynatrace maintenance windows (Settings 2.0 schema
`builtin:deployment.maintenance`). Mute rules that filter on condition
predicates are translated into Workflow filter conditions on the paired
Davis detectors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


_RECURRENCE_MAP = {
    "once": "ONCE",
    "daily": "DAILY",
    "weekly": "WEEKLY",
    "monthly": "MONTHLY",
}


@dataclass
class MaintenanceWindowResult:
    success: bool
    envelope: Optional[Dict[str, Any]] = None
    workflow_filter_expression: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class MaintenanceWindowTransformer:
    """NR maintenance windows + mute rules -> DT maintenance window / workflow filter."""

    def transform(self, nr_window: Dict[str, Any]) -> MaintenanceWindowResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            name = nr_window.get("name", "Unnamed Window")
            kind = str(nr_window.get("kind", "maintenance")).lower()
            recurrence = str(nr_window.get("recurrence", "once")).lower()
            start = nr_window.get("startTime")
            end = nr_window.get("endTime")
            tz = nr_window.get("timeZone", "UTC")
            filter_nrql = nr_window.get("filterNRQL") or ""
            recurring = _RECURRENCE_MAP.get(recurrence, "ONCE")

            workflow_filter: Optional[str] = None
            if kind == "mute_rule":
                # Mute rules map to a Workflow filter that swallows matching events.
                # We emit both a maintenance-window envelope AND a DQL-style filter
                # that Phase 17 `AlertTransformer` integration can OR into a Workflow
                # trigger's condition block.
                if filter_nrql:
                    # Light NRQL → DQL sketch. Full translation is delegated to
                    # NRQLtoDQLConverter; here we emit the raw expression with a
                    # LOW-confidence annotation.
                    workflow_filter = (
                        f'/* migrated mute rule — verify: {filter_nrql} */'
                    )
                    warnings.append(
                        f"Mute rule '{name}' has NRQL filter — emitted as a "
                        "low-confidence DQL comment. Run scan-instrumentation on "
                        "the predicates before enabling."
                    )

            envelope = {
                "schemaId": "builtin:deployment.maintenance",
                "scope": "environment",
                "value": {
                    "generalProperties": {
                        "name": f"[Migrated] {name}",
                        "description": f"Migrated from NR {kind}.",
                        "type": "PLANNED",
                        "suppression": "DETECT_PROBLEMS_DONT_ALERT",
                    },
                    "schedule": {
                        "scheduleType": recurring,
                        "timeZone": tz,
                        "oneTime": {
                            "startTime": start,
                            "endTime": end,
                        }
                        if recurring == "ONCE"
                        else None,
                        "weeklyRecurrence": nr_window.get("weeklyPattern"),
                        "monthlyRecurrence": nr_window.get("monthlyPattern"),
                    },
                },
            }

            logger.info(
                "Transformed maintenance / mute rule",
                name=name,
                kind=kind,
                recurrence=recurrence,
            )
            return MaintenanceWindowResult(
                success=True,
                envelope=envelope,
                workflow_filter_expression=workflow_filter,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Maintenance window transformation failed", error=str(exc))
            return MaintenanceWindowResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, windows: List[Dict[str, Any]]
    ) -> List[MaintenanceWindowResult]:
        return [self.transform(w) for w in windows]
