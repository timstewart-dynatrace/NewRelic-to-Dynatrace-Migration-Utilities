"""
Security Signals Transformer — Gen3 target.

NR Security Signals / IAST configuration maps to Dynatrace Security
Investigator via `builtin:appsec.security-signals` and bizevent ingest
rules. Severity mappings carry through; customer signatures become
OpenPipeline enrichment processors that tag security-relevant records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


_SEVERITY_MAP = {
    "critical": "CRITICAL",
    "high": "HIGH",
    "medium": "MEDIUM",
    "low": "LOW",
    "info": "INFO",
}


@dataclass
class SecuritySignalsResult:
    success: bool
    envelope: Optional[Dict[str, Any]] = None
    enrichment_processors: List[Dict[str, Any]] = field(default_factory=list)
    runbook: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class SecuritySignalsTransformer:
    """NR Security Signals -> DT Security Investigator."""

    def transform(self, nr_config: Dict[str, Any]) -> SecuritySignalsResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            name = nr_config.get("name", "unnamed-signals-policy")
            severity = _SEVERITY_MAP.get(
                str(nr_config.get("minSeverity", "high")).lower(), "HIGH"
            )
            signatures = nr_config.get("signatures") or []
            mute_list = nr_config.get("muteList") or []

            envelope = {
                "schemaId": "builtin:appsec.security-signals",
                "scope": "environment",
                "value": {
                    "name": f"[Migrated] {name}",
                    "enabled": True,
                    "minSeverity": severity,
                    "alertOnIastFinding": bool(nr_config.get("iastEnabled", True)),
                    "mutedSignatures": [
                        {"signatureId": s, "reason": "Migrated from NR mute list"}
                        for s in mute_list
                    ],
                },
            }

            enrichment_processors: List[Dict[str, Any]] = []
            for sig in signatures:
                enrichment_processors.append(
                    {
                        "schemaId": "builtin:openpipeline.events.pipelines",
                        "scope": "environment",
                        "value": {
                            "name": f"[Migrated sec-sig] {sig.get('name', 'unnamed')}",
                            "enabled": True,
                            "processor": {
                                "type": "addFields",
                                "id": f"secsig-{sig.get('id', 'unknown')}",
                                "matcher": sig.get("matcher", "true"),
                                "fields": [
                                    {"name": "security.signature", "value": sig.get("id", "")},
                                    {"name": "security.severity", "value": sig.get("severity", "MEDIUM")},
                                ],
                            },
                        },
                    }
                )

            runbook = {
                "activation_steps": [
                    "Enable DT Application Security (AppSec) on target services.",
                    "Confirm IAST is active on the target OneAgent.",
                    "Review migrated signatures; DT maintains its own signature catalog — operator-authored signatures may not have DT equivalents.",
                ],
                "mute_list_count": len(mute_list),
            }

            if signatures:
                warnings.append(
                    f"{len(signatures)} customer-authored signatures captured as OpenPipeline enrichment. "
                    "Review against DT's built-in signature catalog to avoid duplicates."
                )

            logger.info(
                "Transformed security signals config",
                name=name,
                signatures=len(signatures),
                mute_count=len(mute_list),
            )
            return SecuritySignalsResult(
                success=True,
                envelope=envelope,
                enrichment_processors=enrichment_processors,
                runbook=runbook,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Security signals transformation failed", error=str(exc))
            return SecuritySignalsResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, configs: List[Dict[str, Any]]
    ) -> List[SecuritySignalsResult]:
        return [self.transform(c) for c in configs]
