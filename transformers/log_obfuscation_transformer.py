"""
Log Obfuscation / Masking Transformer — Gen3 target.

NR log obfuscation rules (PII / PAN / bespoke regex masks) map to
OpenPipeline mask processors. The schema is
`builtin:openpipeline.logs.pipelines` with processor `type: mask` and a
DPL pattern + replacement.

Known NR obfuscation presets (email, CC, SSN, etc.) map to DT built-in
redactors where possible; unrecognized presets fall back to regex
translation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger()


SCHEMA = "builtin:openpipeline.logs.pipelines"


# NR preset id -> (DT built-in mask pattern, replacement)
_PRESET_MAP = {
    "email": (r"'email':EMAIL", "****@****"),
    "credit_card": (r"'cc':CREDIT_CARD", "****-****-****-****"),
    "ssn": (r"'ssn':SSN_US", "***-**-****"),
    "phone": (r"'phone':PHONE", "(***) ***-****"),
    "ip_address": (r"'ip':IPADDR", "***.***.***.***"),
    "ipv4": (r"'ip':IPADDR", "***.***.***.***"),
    "aws_access_key": (r"'key':/AKIA[0-9A-Z]{16}/", "AKIA***"),
}


@dataclass
class LogObfuscationResult:
    success: bool
    processors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class LogObfuscationTransformer:
    """NR obfuscation rule -> OpenPipeline mask processor (Gen3)."""

    def transform(self, nr_rule: Dict[str, Any]) -> LogObfuscationResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            name = nr_rule.get("name", "Unnamed Mask")
            enabled = bool(nr_rule.get("enabled", True))
            preset = str(nr_rule.get("preset", "")).lower()
            regex = nr_rule.get("regex", "")
            replacement = nr_rule.get("replacement", "****")
            matcher = nr_rule.get("matcher", "true")

            if preset and preset in _PRESET_MAP:
                dpl_pattern, default_repl = _PRESET_MAP[preset]
                replacement = nr_rule.get("replacement", default_repl)
                note = f"mapped from NR preset '{preset}'"
            elif preset:
                warnings.append(
                    f"NR preset '{preset}' has no direct DT redactor — "
                    "falling back to regex translation."
                )
                dpl_pattern = regex or ".+"
                note = f"preset '{preset}' fell back to regex"
            else:
                dpl_pattern = regex or ".+"
                note = "user-supplied regex"

            processor = {
                "schemaId": SCHEMA,
                "scope": "environment",
                "value": {
                    "name": f"[Migrated mask] {name}",
                    "description": f"Migrated from NR obfuscation rule ({note}).",
                    "enabled": enabled,
                    "processor": {
                        "type": "mask",
                        "id": _slug(name),
                        "matcher": matcher,
                        "pattern": dpl_pattern,
                        "replacement": replacement,
                    },
                },
            }

            logger.info(
                "Transformed log obfuscation rule",
                name=name,
                preset=preset or "(regex)",
            )
            return LogObfuscationResult(
                success=True, processors=[processor], warnings=warnings
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Log obfuscation transformation failed", error=str(exc))
            return LogObfuscationResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, rules: List[Dict[str, Any]]
    ) -> List[LogObfuscationResult]:
        return [self.transform(r) for r in rules]


def _slug(text: str) -> str:
    safe = text.lower()
    safe = "".join(c if c.isalnum() or c in ("-", "_") else "-" for c in safe)
    return safe.strip("-") or "mask"
