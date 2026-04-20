"""
Metric Normalization Transformer — Gen3 target.

NR metric normalization rules (rename, aggregate, drop) map to DT
OpenPipeline metric processor rules (`builtin:openpipeline.metrics.pipelines`).
Supported rule types:

  * rename    -> `renameFields` processor
  * aggregate -> `computeFields` processor with aggregation DQL
  * drop      -> `drop` processor
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger()


@dataclass
class MetricNormalizationResult:
    success: bool
    processors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class MetricNormalizationTransformer:
    """NR metric normalization rule -> OpenPipeline metrics processor."""

    SCHEMA = "builtin:openpipeline.metrics.pipelines"

    def transform(self, nr_rule: Dict[str, Any]) -> MetricNormalizationResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            name = nr_rule.get("name", "unnamed-rule")
            rule_type = str(nr_rule.get("type", "rename")).lower()
            matcher = nr_rule.get("matcher", "true")

            if rule_type == "rename":
                source = nr_rule.get("sourceMetric", "")
                target = nr_rule.get("targetMetric", "")
                proc = {
                    "type": "renameFields",
                    "id": _slug(name),
                    "matcher": matcher,
                    "renames": [{"from": source, "to": target}],
                }
            elif rule_type == "aggregate":
                target = nr_rule.get("targetMetric", "")
                expression = nr_rule.get("expression", "sum(value)")
                proc = {
                    "type": "computeFields",
                    "id": _slug(name),
                    "matcher": matcher,
                    "fields": [{"name": target, "expression": expression}],
                }
            elif rule_type == "drop":
                proc = {
                    "type": "drop",
                    "id": _slug(name),
                    "matcher": matcher,
                }
            else:
                warnings.append(
                    f"Rule type '{rule_type}' has no direct OpenPipeline mapping — skipped."
                )
                return MetricNormalizationResult(
                    success=False,
                    errors=[f"Unsupported rule type: {rule_type}"],
                    warnings=warnings,
                )

            envelope = {
                "schemaId": self.SCHEMA,
                "scope": "environment",
                "value": {
                    "name": f"[Migrated] {name}",
                    "description": f"Migrated from NR metric normalization rule ({rule_type}).",
                    "enabled": bool(nr_rule.get("enabled", True)),
                    "processor": proc,
                },
            }

            logger.info(
                "Transformed metric normalization rule",
                name=name,
                rule_type=rule_type,
            )
            return MetricNormalizationResult(
                success=True, processors=[envelope], warnings=warnings
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Metric normalization transformation failed", error=str(exc))
            return MetricNormalizationResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, rules: List[Dict[str, Any]]
    ) -> List[MetricNormalizationResult]:
        return [self.transform(r) for r in rules]


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() or c == "-" else "-" for c in text.lower())[:180] or "rule"
