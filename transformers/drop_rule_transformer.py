"""
Drop Rule Transformer — Gen3 target.

Converts New Relic drop rules into OpenPipeline drop processors (schema
`builtin:openpipeline.logs.pipelines`). Attribute-drop rules are mapped
to OpenPipeline `removeFields` processors.

Legacy (Config v1 ingest rule) behavior is preserved in
`transformers/legacy/drop_rule_transformer_v1.py`.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger()


@dataclass
class DropRuleTransformResult:
    """Result of NR drop rule -> OpenPipeline drop processor (Gen3)."""

    success: bool
    processors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class DropRuleTransformer:
    """NR drop rule -> OpenPipeline `drop` / `removeFields` processor (Gen3)."""

    SCHEMA = "builtin:openpipeline.logs.pipelines"

    def transform(self, nr_rule: Dict[str, Any]) -> DropRuleTransformResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            name = nr_rule.get("name", "Unnamed Drop Rule")
            nrql_condition = nr_rule.get("nrqlCondition", "") or ""
            action = nr_rule.get("action", "drop_data")
            enabled = bool(nr_rule.get("enabled", True))
            matcher = self._convert_condition(nrql_condition, warnings)

            if action == "drop_attributes":
                attributes = nr_rule.get("attributes", []) or []
                proc = {
                    "schemaId": self.SCHEMA,
                    "scope": "environment",
                    "value": {
                        "name": f"[Migrated] {name}",
                        "description": f"Migrated from NR attribute-drop rule: {name}",
                        "enabled": enabled,
                        "processor": {
                            "type": "removeFields",
                            "id": self._slug(name),
                            "matcher": matcher,
                            "fields": list(attributes),
                        },
                    },
                }
                warnings.append(
                    f"Drop rule '{name}' strips attributes — verify field names "
                    "match DT attribute keys."
                )
            else:
                proc = {
                    "schemaId": self.SCHEMA,
                    "scope": "environment",
                    "value": {
                        "name": f"[Migrated] {name}",
                        "description": f"Migrated from NR drop rule: {name}",
                        "enabled": enabled,
                        "processor": {
                            "type": "drop",
                            "id": self._slug(name),
                            "matcher": matcher,
                        },
                    },
                }

            logger.info(
                "Transformed drop rule to OpenPipeline processor",
                name=name,
                action=action,
            )
            return DropRuleTransformResult(
                success=True, processors=[proc], warnings=warnings
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Drop rule transformation failed", error=str(exc))
            return DropRuleTransformResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    @staticmethod
    def _convert_condition(nrql_condition: str, warnings: List[str]) -> str:
        if not nrql_condition:
            return "true"
        converted = (
            nrql_condition.replace(" = ", " == ")
            .replace(" AND ", " and ")
            .replace(" OR ", " or ")
        )
        warnings.append(
            f"NRQL condition '{nrql_condition}' was auto-converted; verify the DQL matcher."
        )
        return converted

    @staticmethod
    def _slug(text: str) -> str:
        return "".join(c if c.isalnum() or c == "-" else "-" for c in text.lower())[:180]

    def transform_all(
        self, rules: List[Dict[str, Any]]
    ) -> List[DropRuleTransformResult]:
        results = [self.transform(r) for r in rules]
        successful = sum(1 for r in results if r.success)
        logger.info(
            f"Transformed {successful}/{len(results)} drop rules to OpenPipeline processors"
        )
        return results
