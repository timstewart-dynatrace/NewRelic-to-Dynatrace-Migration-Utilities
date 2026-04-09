"""Partial retry — save and reload failed entities for re-import."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


class FailedEntities:
    """Tracks entities that failed during import for later retry."""

    def __init__(self) -> None:
        self.entries: List[Dict] = []

    def add(self, entity_type: str, name: str, error: str) -> None:
        """Record a failed entity."""
        self.entries.append(
            {"entity_type": entity_type, "name": name, "error": error}
        )
        logger.warning(
            "entity_failed", entity_type=entity_type, name=name, error=error
        )

    def save(self, path: Path) -> None:
        """Write failed entities to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.entries, indent=2))
        logger.info("failed_entities_saved", path=str(path), count=len(self.entries))

    @classmethod
    def load(cls, path: Path) -> "FailedEntities":
        """Load failed entities from a previously saved JSON file."""
        instance = cls()
        data = json.loads(path.read_text())
        instance.entries = data
        logger.info("failed_entities_loaded", path=str(path), count=len(data))
        return instance

    def get_failed_names(self, entity_type: str) -> List[str]:
        """Return names of failed entities filtered by type."""
        return [
            entry["name"]
            for entry in self.entries
            if entry["entity_type"] == entity_type
        ]

    def filter_transformed_data(
        self,
        transformed_data: Dict,
        entity_type_key: str,
        name_key: str,
    ) -> List[Dict]:
        """Return only items from transformed_data that match failed names.

        Args:
            transformed_data: Dict containing a list of entities under entity_type_key.
            entity_type_key: Key in transformed_data whose value is a list of entities.
            name_key: Key within each entity dict that holds the entity name.

        Returns:
            List of entity dicts whose name matches a failed entry for that type.
        """
        failed_names = set(self.get_failed_names(entity_type_key))
        items = transformed_data.get(entity_type_key, [])
        return [item for item in items if item.get(name_key) in failed_names]

    def is_empty(self) -> bool:
        """Return True if no failures have been recorded."""
        return len(self.entries) == 0
