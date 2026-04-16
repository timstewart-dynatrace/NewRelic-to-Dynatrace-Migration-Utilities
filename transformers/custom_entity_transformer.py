"""
Custom Entity Transformer — Gen3 target.

NR custom entities (registered via the entity platform) map to DT
custom device entities via the `/api/v2/entities/custom` POST endpoint.

Emits:
  - One JSON payload per entity ready for POSTing
  - Entity tag envelope as an OpenPipeline enrichment so the custom
    entity's attributes carry through at ingest
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class CustomEntityResult:
    success: bool
    custom_device_payload: Optional[Dict[str, Any]] = None
    enrichment_processor: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class CustomEntityTransformer:
    """NR custom entity -> DT custom device + enrichment."""

    API_PATH = "/api/v2/entities/custom"

    def transform(self, nr_entity: Dict[str, Any]) -> CustomEntityResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            guid = nr_entity.get("guid", "")
            name = nr_entity.get("name", "unnamed-custom-entity")
            entity_type = nr_entity.get("type", "CUSTOM")
            properties = nr_entity.get("properties") or {}
            tags = nr_entity.get("tags") or []

            custom_device_payload = {
                "endpoint": self.API_PATH,
                "method": "POST",
                "body": {
                    "customDeviceId": f"migrated-{guid or name}",
                    "displayName": name,
                    "type": entity_type,
                    "properties": properties,
                    "tags": [
                        {"key": t.get("key", ""), "value": t.get("value", "")}
                        for t in tags if isinstance(t, dict)
                    ],
                },
            }

            enrichment_processor = {
                "schemaId": "builtin:openpipeline.events.pipelines",
                "scope": "environment",
                "value": {
                    "name": f"[Migrated custom entity] {name}",
                    "enabled": True,
                    "processor": {
                        "type": "addFields",
                        "id": f"custom-entity-{guid or name}".lower(),
                        "matcher": (
                            f'entity.guid == "{guid}"'
                            if guid
                            else f'entity.name == "{name}"'
                        ),
                        "fields": [
                            {"name": "custom.entity.type", "value": entity_type},
                            {"name": "custom.entity.migrated", "value": "true"},
                        ],
                    },
                },
            }

            if not guid:
                warnings.append(
                    f"Custom entity '{name}' has no GUID — matcher will fall "
                    "back to entity.name equality which can collide with other entities."
                )

            logger.info(
                "Transformed custom entity",
                name=name,
                type=entity_type,
                properties=len(properties),
            )
            return CustomEntityResult(
                success=True,
                custom_device_payload=custom_device_payload,
                enrichment_processor=enrichment_processor,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Custom entity transformation failed", error=str(exc))
            return CustomEntityResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, entities: List[Dict[str, Any]]
    ) -> List[CustomEntityResult]:
        return [self.transform(e) for e in entities]
