"""
Drop Rule Transformer - Converts New Relic drop rules to Dynatrace ingest rules.
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class DropRuleTransformResult:
    """Result of drop rule transformation."""
    success: bool
    ingest_rules: List[Dict[str, Any]] = None
    warnings: List[str] = None
    errors: List[str] = None

    def __post_init__(self):
        self.ingest_rules = self.ingest_rules or []
        self.warnings = self.warnings or []
        self.errors = self.errors or []


class DropRuleTransformer:
    """
    Transforms New Relic drop rules to Dynatrace ingest/drop rules.

    New Relic drop rules:
    - Drop data at ingest to reduce costs
    - Based on NRQL WHERE conditions
    - Can target specific event types

    Dynatrace equivalents:
    - Log/metric ingest rules
    - Data filtering at ingest pipeline
    """

    def __init__(self):
        pass

    def transform(self, nr_rule: Dict[str, Any]) -> DropRuleTransformResult:
        """Transform a New Relic drop rule to Dynatrace ingest rule."""
        warnings: List[str] = []
        errors: List[str] = []

        try:
            rule_name = nr_rule.get("name", "Unnamed Drop Rule")
            nrql_condition = nr_rule.get("nrqlCondition", "")
            action = nr_rule.get("action", "drop_data")
            enabled = nr_rule.get("enabled", True)

            # Build Dynatrace ingest rule
            ingest_rule = {
                "name": f"[Migrated] {rule_name}",
                "description": f"Migrated from NR drop rule: {rule_name}",
                "type": "DROP",
                "enabled": enabled,
                "condition": self._convert_condition(nrql_condition, warnings),
            }

            if action == "drop_attributes":
                attributes = nr_rule.get("attributes", [])
                ingest_rule["type"] = "MASK"
                ingest_rule["attributes"] = attributes
                warnings.append(
                    f"Drop rule '{rule_name}' uses attribute dropping. "
                    "Mapped to MASK rule; verify attribute names in Dynatrace."
                )

            logger.info(
                "Transformed drop rule to ingest rule",
                name=rule_name,
                action=action,
            )

            return DropRuleTransformResult(
                success=True,
                ingest_rules=[ingest_rule],
                warnings=warnings,
            )

        except Exception as e:
            logger.error("Drop rule transformation failed", error=str(e))
            return DropRuleTransformResult(
                success=False,
                errors=[f"Transformation error: {str(e)}"],
            )

    def _convert_condition(
        self, nrql_condition: str, warnings: List[str]
    ) -> str:
        """
        Convert an NRQL WHERE condition to a Dynatrace filter expression.

        Simple mapping for common patterns. Complex conditions require
        manual conversion.
        """
        if not nrql_condition:
            return "matchesValue(content, \"*\")"

        # Basic conversion of common patterns
        condition = nrql_condition
        condition = condition.replace(" = ", " == ")
        condition = condition.replace(" AND ", " and ")
        condition = condition.replace(" OR ", " or ")

        warnings.append(
            f"NRQL condition '{nrql_condition}' was auto-converted. "
            "Verify the resulting filter expression."
        )

        return condition

    def transform_all(
        self, rules: List[Dict[str, Any]]
    ) -> List[DropRuleTransformResult]:
        """Transform multiple drop rules."""
        results = []

        for rule in rules:
            result = self.transform(rule)
            results.append(result)

        successful = sum(1 for r in results if r.success)
        logger.info(
            f"Transformed {successful}/{len(results)} drop rules"
        )

        return results
