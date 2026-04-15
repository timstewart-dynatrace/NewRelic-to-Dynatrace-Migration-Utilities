"""
Tag Transformer — Gen3 target.

Converts New Relic entity tags into OpenPipeline enrichment processors. In
Gen3, tagging is no longer a separate "auto-tag rule" system; instead, tags
are attributes added to records at ingest time by OpenPipeline processors,
and segments (see WorkloadTransformer) query them downstream.

Emitted payloads target schema `builtin:openpipeline.logs.pipelines` with
an `addFields` processor matching on `entity.name` and writing the
`tags.<key>` attribute. The same processor shape is reused for events,
bizevents, and metrics pipelines by the orchestrator.

Legacy (Auto-Tag Rule) behavior is preserved in
`transformers/legacy/tag_transformer_v1.py` and reached via `--legacy`.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger()


@dataclass
class TagTransformResult:
    """Result of tag -> OpenPipeline enrichment translation (Gen3)."""

    success: bool
    enrichment_processors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class TagTransformer:
    """NR entity tags -> OpenPipeline `addFields` enrichment processors (Gen3)."""

    ENTITY_TYPE_TO_PIPELINE = {
        "APPLICATION": "logs",
        "APM_APPLICATION": "logs",
        "HOST": "logs",
        "BROWSER_APPLICATION": "bizevents",
        "MOBILE_APPLICATION": "bizevents",
        "SYNTHETIC_MONITOR": "events",
    }

    def transform(self, nr_entity: Dict[str, Any]) -> TagTransformResult:
        warnings: List[str] = []
        errors: List[str] = []

        try:
            entity_name = nr_entity.get("name", "Unknown Entity")
            entity_type = nr_entity.get("type", "APPLICATION")
            tags = nr_entity.get("tags", []) or []

            pipeline = self.ENTITY_TYPE_TO_PIPELINE.get(entity_type, "logs")
            processors: List[Dict[str, Any]] = []

            for tag in tags:
                key = tag.get("key", "")
                values = tag.get("values", []) or []
                if not key:
                    warnings.append(
                        f"Empty tag key found on entity '{entity_name}', skipping."
                    )
                    continue
                for value in values:
                    processors.append(
                        self._enrichment_processor(
                            pipeline=pipeline,
                            entity_name=entity_name,
                            tag_key=key,
                            tag_value=value,
                        )
                    )

            logger.info(
                "Transformed entity tags to OpenPipeline enrichment",
                entity=entity_name,
                pipeline=pipeline,
                processors=len(processors),
            )
            return TagTransformResult(
                success=True,
                enrichment_processors=processors,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Tag transformation failed", error=str(exc))
            return TagTransformResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    @staticmethod
    def _enrichment_processor(
        pipeline: str, entity_name: str, tag_key: str, tag_value: str
    ) -> Dict[str, Any]:
        schema = f"builtin:openpipeline.{pipeline}.pipelines"
        processor_id = f"enrich-{tag_key}-{tag_value}-{entity_name}".lower()
        processor_id = "".join(
            c if c.isalnum() or c == "-" else "-" for c in processor_id
        )[:180]
        return {
            "schemaId": schema,
            "scope": "environment",
            "value": {
                "name": f"[Migrated] {tag_key}={tag_value} for {entity_name}",
                "description": f"Migrated from NR tag: {tag_key}={tag_value}",
                "enabled": True,
                "processor": {
                    "type": "addFields",
                    "id": processor_id,
                    "matcher": f'contains(entity.name, "{entity_name}")',
                    "fields": [
                        {
                            "name": f"tags.{tag_key}",
                            "value": tag_value,
                        }
                    ],
                },
            },
        }

    def transform_all(
        self, entities: List[Dict[str, Any]]
    ) -> List[TagTransformResult]:
        results = [self.transform(e) for e in entities]
        successful = sum(1 for r in results if r.success)
        logger.info(
            f"Transformed tags for {successful}/{len(results)} entities to Gen3 enrichment"
        )
        return results
