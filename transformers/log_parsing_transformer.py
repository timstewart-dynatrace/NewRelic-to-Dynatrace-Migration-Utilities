"""
Log Parsing Transformer - Converts New Relic log parsing rules to Dynatrace format.
"""

from dataclasses import dataclass
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger()


@dataclass
class LogParsingTransformResult:
    """Result of log parsing rule transformation."""
    success: bool
    processing_rules: List[Dict[str, Any]] = None
    warnings: List[str] = None
    errors: List[str] = None

    def __post_init__(self):
        self.processing_rules = self.processing_rules or []
        self.warnings = self.warnings or []
        self.errors = self.errors or []


class LogParsingTransformer:
    """
    Transforms New Relic log parsing rules to Dynatrace log processing rules.

    New Relic log parsing:
    - Regex-based field extraction
    - Grok patterns
    - Attribute enrichment

    Dynatrace equivalents:
    - Log processing rules with DPL (Dynatrace Pattern Language)
    - Log attribute extraction
    """

    def __init__(self):
        pass

    def transform(self, nr_rule: Dict[str, Any]) -> LogParsingTransformResult:
        """Transform a New Relic log parsing rule to Dynatrace processing rule."""
        warnings: List[str] = []
        errors: List[str] = []

        try:
            rule_name = nr_rule.get("name", "Unnamed Rule")
            rule_type = nr_rule.get("type", "regex")
            enabled = nr_rule.get("enabled", True)

            if rule_type == "regex":
                processing_rule = self._transform_regex_rule(nr_rule, warnings)
            elif rule_type == "grok":
                processing_rule = self._transform_grok_rule(nr_rule, warnings)
            else:
                warnings.append(
                    f"Unknown log parsing type '{rule_type}' for rule '{rule_name}'."
                )
                processing_rule = self._create_placeholder(nr_rule)

            if not enabled:
                processing_rule["enabled"] = False

            processing_rules = [processing_rule] if processing_rule else []

            logger.info(
                "Transformed log parsing rule",
                name=rule_name,
                type=rule_type,
            )

            return LogParsingTransformResult(
                success=True,
                processing_rules=processing_rules,
                warnings=warnings,
            )

        except Exception as e:
            logger.error("Log parsing transformation failed", error=str(e))
            return LogParsingTransformResult(
                success=False,
                errors=[f"Transformation error: {str(e)}"],
            )

    def _transform_regex_rule(
        self, rule: Dict[str, Any], warnings: List[str]
    ) -> Dict[str, Any]:
        """Transform a regex-based parsing rule to DPL pattern."""
        name = rule.get("name", "Regex Rule")
        pattern = rule.get("pattern", "")
        attributes = rule.get("attributes", [])

        # Convert regex capture groups to DPL named groups
        dpl_pattern = self._regex_to_dpl(pattern, attributes)

        return {
            "name": f"[Migrated] {name}",
            "description": f"Migrated from NR log parsing rule: {name}",
            "type": "ATTRIBUTE_EXTRACTION",
            "enabled": rule.get("enabled", True),
            "query": "matchesValue(content, \"*\")",
            "pattern": dpl_pattern,
            "source": "content",
        }

    def _transform_grok_rule(
        self, rule: Dict[str, Any], warnings: List[str]
    ) -> Dict[str, Any]:
        """Transform a grok-based parsing rule."""
        name = rule.get("name", "Grok Rule")

        warnings.append(
            f"Grok pattern in rule '{name}' requires manual conversion to DPL. "
            "Dynatrace uses DPL (Dynatrace Pattern Language) instead of Grok."
        )

        return {
            "name": f"[Migrated] {name}",
            "description": f"Migrated from NR grok rule: {name}. Requires manual DPL conversion.",
            "type": "ATTRIBUTE_EXTRACTION",
            "enabled": False,
            "query": "matchesValue(content, \"*\")",
            "pattern": "// TODO: Convert grok pattern to DPL",
            "source": "content",
        }

    def _regex_to_dpl(self, regex_pattern: str, attributes: List[str]) -> str:
        """
        Convert a basic regex pattern to DPL notation.

        This handles simple capture group patterns. Complex regex
        requires manual conversion.
        """
        if not regex_pattern:
            return "// TODO: Add DPL pattern"

        # Simple conversion: named capture groups
        dpl = regex_pattern
        for i, attr in enumerate(attributes):
            # Replace unnamed groups (...) with named DPL groups
            dpl = dpl.replace(f"({attr})", f"'{attr}':STRING", 1)

        return dpl

    def _create_placeholder(self, rule: Dict[str, Any]) -> Dict[str, Any]:
        """Create a disabled placeholder for unknown rule types."""
        name = rule.get("name", "Unknown Rule")
        return {
            "name": f"[Migrated] {name}",
            "description": f"Migrated from NR log parsing rule (unknown type): {name}",
            "type": "ATTRIBUTE_EXTRACTION",
            "enabled": False,
            "query": "matchesValue(content, \"*\")",
            "pattern": "// TODO: Manual conversion required",
            "source": "content",
        }

    def transform_all(
        self, rules: List[Dict[str, Any]]
    ) -> List[LogParsingTransformResult]:
        """Transform multiple log parsing rules."""
        results = []

        for rule in rules:
            result = self.transform(rule)
            results.append(result)

        successful = sum(1 for r in results if r.success)
        logger.info(
            f"Transformed {successful}/{len(results)} log parsing rules"
        )

        return results
