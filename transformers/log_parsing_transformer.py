"""
Log Parsing Transformer — Gen3 target.

Converts New Relic log parsing rules into OpenPipeline `parse` / `dpl`
processors emitted against schema `builtin:openpipeline.logs.pipelines`.

Legacy (Config v1 log processing rule) behavior is preserved in
`transformers/legacy/log_parsing_transformer_v1.py`.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger()


@dataclass
class LogParsingTransformResult:
    """Result of NR log rule -> OpenPipeline processor translation (Gen3)."""

    success: bool
    processors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class LogParsingTransformer:
    """NR log parsing rule -> OpenPipeline DPL `parse` processor (Gen3)."""

    SCHEMA = "builtin:openpipeline.logs.pipelines"

    def transform(self, nr_rule: Dict[str, Any]) -> LogParsingTransformResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            name = nr_rule.get("name", "Unnamed Rule")
            rule_type = nr_rule.get("type", "regex")
            enabled = bool(nr_rule.get("enabled", True))

            if rule_type == "regex":
                proc = self._regex_processor(nr_rule)
            elif rule_type == "grok":
                warnings.append(
                    f"Grok pattern in rule '{name}' requires manual DPL conversion."
                )
                proc = self._placeholder_processor(nr_rule, note="grok → DPL (manual)")
                proc["value"]["enabled"] = False
            else:
                warnings.append(
                    f"Unknown log parsing type '{rule_type}' for rule '{name}'."
                )
                proc = self._placeholder_processor(nr_rule, note="unknown type")
                proc["value"]["enabled"] = False

            if not enabled:
                proc["value"]["enabled"] = False

            logger.info(
                "Transformed log parsing rule to OpenPipeline processor",
                name=name,
                type=rule_type,
            )
            return LogParsingTransformResult(
                success=True, processors=[proc], warnings=warnings
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Log parsing transformation failed", error=str(exc))
            return LogParsingTransformResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def _regex_processor(self, rule: Dict[str, Any]) -> Dict[str, Any]:
        name = rule.get("name", "Regex Rule")
        pattern = rule.get("pattern", "")
        attributes = rule.get("attributes", []) or []
        dpl_pattern = self._regex_to_dpl(pattern, attributes)

        return {
            "schemaId": self.SCHEMA,
            "scope": "environment",
            "value": {
                "name": f"[Migrated] {name}",
                "description": f"Migrated from NR log parsing rule: {name}",
                "enabled": True,
                "processor": {
                    "type": "dql",
                    "id": self._slug(name),
                    "matcher": 'true',
                    "dql": f'parse content, "{dpl_pattern}"',
                },
            },
        }

    def _placeholder_processor(
        self, rule: Dict[str, Any], note: str
    ) -> Dict[str, Any]:
        name = rule.get("name", "Unknown Rule")
        return {
            "schemaId": self.SCHEMA,
            "scope": "environment",
            "value": {
                "name": f"[Migrated] {name}",
                "description": f"Migrated from NR log parsing rule ({note}): {name}",
                "enabled": False,
                "processor": {
                    "type": "dql",
                    "id": self._slug(name),
                    "matcher": "true",
                    "dql": "// TODO: add DPL parse expression",
                },
            },
        }

    @staticmethod
    def _regex_to_dpl(regex_pattern: str, attributes: List[str]) -> str:
        if not regex_pattern:
            return "// TODO: add DPL pattern"
        dpl = regex_pattern
        for attr in attributes:
            dpl = dpl.replace(f"({attr})", f"'{attr}':STRING", 1)
        return dpl

    @staticmethod
    def _slug(text: str) -> str:
        return "".join(c if c.isalnum() or c == "-" else "-" for c in text.lower())[:180]

    def transform_all(
        self, rules: List[Dict[str, Any]]
    ) -> List[LogParsingTransformResult]:
        results = [self.transform(r) for r in rules]
        successful = sum(1 for r in results if r.success)
        logger.info(
            f"Transformed {successful}/{len(results)} log rules to OpenPipeline processors"
        )
        return results
