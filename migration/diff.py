"""Diff/preview — compare transformed entities against live DT environment."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class DiffEntry:
    """A single diff result for one entity."""

    entity_type: str
    name: str
    action: str  # "CREATE", "UPDATE", "CONFLICT"
    reason: str  # e.g., "Not found in DT", "Name match found", "Multiple matches"
    dt_id: Optional[str] = None


class DiffReport:
    """Compares transformed entities against a live Dynatrace environment."""

    def __init__(self) -> None:
        self.entries: List[DiffEntry] = []

    def add(
        self,
        entity_type: str,
        name: str,
        action: str,
        reason: str,
        dt_id: Optional[str] = None,
    ) -> None:
        """Add a diff entry."""
        entry = DiffEntry(
            entity_type=entity_type,
            name=name,
            action=action,
            reason=reason,
            dt_id=dt_id,
        )
        self.entries.append(entry)
        logger.info(
            "diff_entry",
            entity_type=entity_type,
            name=name,
            action=action,
            reason=reason,
        )

    @classmethod
    def generate_diff(cls, transformed_data: Dict, registry: Any) -> "DiffReport":
        """Generate a diff report by comparing transformed data against a registry.

        For dashboards and management_zones, checks for existing entities via the
        registry. For other entity types (alerting_profiles, metric_events, slos,
        monitors), defaults to CREATE since no registry lookup is available yet.

        Args:
            transformed_data: Dict with entity type keys mapping to lists of entities.
            registry: Object with dashboard_exists(name) and find_management_zone(name).

        Returns:
            A populated DiffReport.
        """
        report = cls()

        # Dashboards — check registry
        for dashboard in transformed_data.get("dashboards", []):
            name = dashboard.get("name", "")
            dt_id = registry.dashboard_exists(name)
            if dt_id is None:
                report.add("dashboard", name, "CREATE", "Not found in DT")
            else:
                report.add(
                    "dashboard", name, "UPDATE", "Name match found", dt_id=dt_id
                )

        # Management zones — check registry
        for mz in transformed_data.get("management_zones", []):
            name = mz.get("name", "")
            dt_id = registry.find_management_zone(name)
            if dt_id is None:
                report.add("management_zone", name, "CREATE", "Not found in DT")
            else:
                report.add(
                    "management_zone",
                    name,
                    "UPDATE",
                    "Name match found",
                    dt_id=dt_id,
                )

        # Entity types without registry lookup — always CREATE
        for entity_type in ("alerting_profiles", "metric_events", "slos", "monitors"):
            for entity in transformed_data.get(entity_type, []):
                name = entity.get("name", "")
                report.add(entity_type, name, "CREATE", "No registry lookup available")

        return report

    def summary(self) -> Dict[str, int]:
        """Return counts by action type."""
        creates = sum(1 for e in self.entries if e.action == "CREATE")
        updates = sum(1 for e in self.entries if e.action == "UPDATE")
        conflicts = sum(1 for e in self.entries if e.action == "CONFLICT")
        return {"creates": creates, "updates": updates, "conflicts": conflicts}

    def get_creates(self) -> List[DiffEntry]:
        """Return all entries with CREATE action."""
        return [e for e in self.entries if e.action == "CREATE"]

    def get_updates(self) -> List[DiffEntry]:
        """Return all entries with UPDATE action."""
        return [e for e in self.entries if e.action == "UPDATE"]
