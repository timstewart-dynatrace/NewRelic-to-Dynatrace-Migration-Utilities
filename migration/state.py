"""Migration state management — rollback, ID mapping, checkpointing, incremental."""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class RollbackManifest:
    """Tracks created Dynatrace entities for rollback support."""

    entries: List[Dict] = field(default_factory=list)

    def add(self, entity_type: str, dynatrace_id: str, name: str) -> None:
        """Append an entry with current UTC timestamp."""
        self.entries.append(
            {
                "entity_type": entity_type,
                "dynatrace_id": dynatrace_id,
                "name": name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        logger.info(
            "rollback_entry_added",
            entity_type=entity_type,
            dynatrace_id=dynatrace_id,
            name=name,
        )

    def save(self, path: Path) -> None:
        """Write manifest to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"entries": self.entries}, indent=2))
        logger.info("rollback_manifest_saved", path=str(path), count=len(self.entries))

    @classmethod
    def load(cls, path: Path) -> "RollbackManifest":
        """Read manifest from JSON file."""
        data = json.loads(path.read_text())
        manifest = cls(entries=data.get("entries", []))
        logger.info("rollback_manifest_loaded", path=str(path), count=len(manifest.entries))
        return manifest

    def get_entries(self) -> List[Dict]:
        """Return all rollback entries."""
        return list(self.entries)


@dataclass
class EntityIdMap:
    """Maps New Relic entity GUIDs to Dynatrace entity IDs."""

    _map: Dict[str, Dict] = field(default_factory=dict)

    def register(self, nr_id: str, dt_id: str, entity_type: str) -> None:
        """Register a mapping from New Relic ID to Dynatrace ID."""
        self._map[nr_id] = {"dt_id": dt_id, "entity_type": entity_type}
        logger.info(
            "entity_id_registered",
            nr_id=nr_id,
            dt_id=dt_id,
            entity_type=entity_type,
        )

    def resolve(self, nr_id: str) -> Optional[str]:
        """Return the Dynatrace ID for a given New Relic ID, or None."""
        entry = self._map.get(nr_id)
        return entry["dt_id"] if entry else None

    def save(self, path: Path) -> None:
        """Write ID map to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._map, indent=2))
        logger.info("entity_id_map_saved", path=str(path), count=len(self._map))

    @classmethod
    def load(cls, path: Path) -> "EntityIdMap":
        """Read ID map from JSON file."""
        data = json.loads(path.read_text())
        id_map = cls(_map=data)
        logger.info("entity_id_map_loaded", path=str(path), count=len(id_map._map))
        return id_map


@dataclass
class MigrationCheckpoint:
    """Tracks per-component migration progress for resumable runs."""

    _completed: Dict[str, int] = field(default_factory=dict)

    def mark_complete(self, component: str, index: int) -> None:
        """Mark a component as having completed through the given index."""
        self._completed[component] = index
        logger.debug("checkpoint_marked", component=component, index=index)

    def is_complete(self, component: str, total: int) -> bool:
        """Check if all items for a component have been processed."""
        return self._completed.get(component, -1) >= total - 1

    def get_resume_index(self, component: str) -> int:
        """Return the next index to process (0 if not started)."""
        if component not in self._completed:
            return 0
        return self._completed[component] + 1

    def save(self, path: Path) -> None:
        """Write checkpoint to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._completed, indent=2))
        logger.info("checkpoint_saved", path=str(path))

    @classmethod
    def load(cls, path: Path) -> "MigrationCheckpoint":
        """Read checkpoint from JSON file."""
        data = json.loads(path.read_text())
        checkpoint = cls(_completed=data)
        logger.info("checkpoint_loaded", path=str(path))
        return checkpoint


@dataclass
class IncrementalState:
    """Tracks content hashes for incremental migration (skip unchanged entities)."""

    _hashes: Dict[str, str] = field(default_factory=dict)

    @staticmethod
    def _compute_hash(data: Dict) -> str:
        """Compute a stable hash of entity data using sorted JSON."""
        serialized = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def has_changed(self, nr_guid: str, entity_data: Dict) -> bool:
        """Check if entity data has changed since the last recorded hash."""
        current_hash = self._compute_hash(entity_data)
        stored_hash = self._hashes.get(nr_guid)
        return stored_hash != current_hash

    def update(self, nr_guid: str, entity_data: Dict) -> None:
        """Store the current hash for an entity."""
        self._hashes[nr_guid] = self._compute_hash(entity_data)

    def save(self, path: Path) -> None:
        """Write hashes to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._hashes, indent=2))
        logger.info("incremental_state_saved", path=str(path), count=len(self._hashes))

    @classmethod
    def load(cls, path: Path) -> "IncrementalState":
        """Read hashes from JSON file."""
        data = json.loads(path.read_text())
        state = cls(_hashes=data)
        logger.info("incremental_state_loaded", path=str(path), count=len(state._hashes))
        return state
