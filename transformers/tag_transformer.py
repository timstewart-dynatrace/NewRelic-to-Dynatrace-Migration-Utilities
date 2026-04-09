"""
Tag Transformer - Converts New Relic entity tags to Dynatrace auto-tag rules.
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class TagTransformResult:
    """Result of tag transformation."""
    success: bool
    auto_tag_rules: List[Dict[str, Any]] = None
    warnings: List[str] = None
    errors: List[str] = None

    def __post_init__(self):
        self.auto_tag_rules = self.auto_tag_rules or []
        self.warnings = self.warnings or []
        self.errors = self.errors or []


class TagTransformer:
    """
    Transforms New Relic entity tags to Dynatrace auto-tag rules.

    New Relic tags:
    - Key-value pairs attached to entities
    - Used for filtering, grouping, alerting

    Dynatrace auto-tags:
    - Automatically applied based on rules
    - Support entity selectors and conditions
    """

    # Entity type mapping for tag rule scopes
    ENTITY_TYPE_MAP = {
        "APPLICATION": "SERVICE",
        "APM_APPLICATION": "SERVICE",
        "HOST": "HOST",
        "BROWSER_APPLICATION": "APPLICATION",
        "MOBILE_APPLICATION": "MOBILE_APPLICATION",
        "SYNTHETIC_MONITOR": "SYNTHETIC_TEST",
    }

    def __init__(self):
        pass

    def transform(self, nr_entity: Dict[str, Any]) -> TagTransformResult:
        """Transform tags from a New Relic entity to Dynatrace auto-tag rules."""
        warnings: List[str] = []
        errors: List[str] = []

        try:
            entity_name = nr_entity.get("name", "Unknown Entity")
            entity_type = nr_entity.get("type", "APPLICATION")
            tags = nr_entity.get("tags", [])

            auto_tag_rules = []

            for tag in tags:
                tag_key = tag.get("key", "")
                tag_values = tag.get("values", [])

                if not tag_key:
                    warnings.append(
                        f"Empty tag key found on entity '{entity_name}', skipping."
                    )
                    continue

                for tag_value in tag_values:
                    rule = self._create_auto_tag_rule(
                        tag_key=tag_key,
                        tag_value=tag_value,
                        entity_type=entity_type,
                        entity_name=entity_name,
                    )
                    auto_tag_rules.append(rule)

            logger.info(
                "Transformed entity tags to auto-tag rules",
                entity=entity_name,
                rules_count=len(auto_tag_rules),
            )

            return TagTransformResult(
                success=True,
                auto_tag_rules=auto_tag_rules,
                warnings=warnings,
            )

        except Exception as e:
            logger.error("Tag transformation failed", error=str(e))
            return TagTransformResult(
                success=False,
                errors=[f"Transformation error: {str(e)}"],
            )

    def _create_auto_tag_rule(
        self,
        tag_key: str,
        tag_value: str,
        entity_type: str,
        entity_name: str,
    ) -> Dict[str, Any]:
        """Create a Dynatrace auto-tag rule from a NR tag."""
        dt_type = self.ENTITY_TYPE_MAP.get(entity_type, "SERVICE")

        return {
            "name": f"[Migrated] {tag_key}",
            "description": f"Migrated from NR tag: {tag_key}={tag_value}",
            "rules": [
                {
                    "type": dt_type,
                    "enabled": True,
                    "valueFormat": tag_value,
                    "conditions": [
                        {
                            "key": {
                                "attribute": "ENTITY_NAME",
                            },
                            "comparisonInfo": {
                                "type": "STRING",
                                "operator": "CONTAINS",
                                "value": entity_name,
                            },
                        }
                    ],
                }
            ],
        }

    def transform_all(
        self, entities: List[Dict[str, Any]]
    ) -> List[TagTransformResult]:
        """Transform tags from multiple entities."""
        results = []

        for entity in entities:
            result = self.transform(entity)
            results.append(result)

        successful = sum(1 for r in results if r.success)
        logger.info(
            f"Transformed tags for {successful}/{len(results)} entities"
        )

        return results
