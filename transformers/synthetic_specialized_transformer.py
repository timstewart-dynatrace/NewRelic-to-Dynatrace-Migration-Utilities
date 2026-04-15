"""
Specialized Synthetic Monitor Transformer — Gen3 target.

Two NR synthetic monitor types aren't handled by the baseline
`SyntheticTransformer`:

  * CERT_CHECK   — TLS certificate expiry check
  * BROKEN_LINKS — page-crawl link validation

DT equivalents:

  * CERT_CHECK   -> HTTP Monitor (`builtin:synthetic_test`) with a
                    `validation.rules[].type = "certificateExpiryDate"`
                    rule; DT auto-extracts expiry from the TLS handshake.
  * BROKEN_LINKS -> No direct equivalent; emit as a multi-step HTTP
                    monitor that probes each URL the NR crawler
                    discovered (requires NR to have enumerated them).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class SpecializedSyntheticResult:
    success: bool
    envelope: Optional[Dict[str, Any]] = None
    runbook: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class SyntheticSpecializedTransformer:
    """NR cert-check / broken-links monitors -> DT HTTP monitors."""

    def transform(self, nr_monitor: Dict[str, Any]) -> SpecializedSyntheticResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            name = nr_monitor.get("name", "unnamed-monitor")
            monitor_type = str(nr_monitor.get("monitorType", "")).upper()
            url = nr_monitor.get("monitoredUrl", "")
            days_before = int(nr_monitor.get("daysUntilExpiration", 30))

            if monitor_type == "CERT_CHECK":
                envelope = {
                    "schemaId": "builtin:synthetic_test",
                    "scope": "environment",
                    "value": {
                        "name": f"[Migrated cert-check] {name}",
                        "type": "HTTP",
                        "frequencyMin": int(nr_monitor.get("frequencyMin", 60)),
                        "enabled": bool(nr_monitor.get("enabled", True)),
                        "script": {
                            "version": "1.0",
                            "requests": [
                                {
                                    "description": "TLS cert validation",
                                    "url": url,
                                    "method": "GET",
                                    "validation": {
                                        "rules": [
                                            {
                                                "type": "certificateExpiryDate",
                                                "value": str(days_before),
                                                "passIfFound": True,
                                            },
                                            {
                                                "type": "httpStatusesList",
                                                "value": ">=200, <400",
                                                "passIfFound": True,
                                            },
                                        ],
                                    },
                                    "configuration": {
                                        "acceptAnyCertificate": False,
                                        "followRedirects": True,
                                    },
                                }
                            ],
                        },
                    },
                }
                runbook = {
                    "monitor_type": "CERT_CHECK",
                    "days_before_expiry_alert": days_before,
                    "validation_rule": "certificateExpiryDate",
                }
                return SpecializedSyntheticResult(
                    success=True, envelope=envelope, runbook=runbook, warnings=warnings
                )

            if monitor_type == "BROKEN_LINKS":
                discovered_urls = nr_monitor.get("discoveredUrls") or [url]
                if len(discovered_urls) > 50:
                    warnings.append(
                        f"Broken-links monitor '{name}' had {len(discovered_urls)} "
                        "URLs — DT HTTP monitors cap at 50 steps. Truncating; "
                        "consider splitting into multiple monitors."
                    )
                    discovered_urls = discovered_urls[:50]
                envelope = {
                    "schemaId": "builtin:synthetic_test",
                    "scope": "environment",
                    "value": {
                        "name": f"[Migrated broken-links] {name}",
                        "type": "HTTP",
                        "frequencyMin": int(nr_monitor.get("frequencyMin", 60)),
                        "enabled": bool(nr_monitor.get("enabled", True)),
                        "script": {
                            "version": "1.0",
                            "requests": [
                                {
                                    "description": f"Link probe {i+1}",
                                    "url": link_url,
                                    "method": "GET",
                                    "validation": {
                                        "rules": [
                                            {
                                                "type": "httpStatusesList",
                                                "value": ">=200, <400",
                                                "passIfFound": True,
                                            }
                                        ],
                                    },
                                }
                                for i, link_url in enumerate(discovered_urls)
                            ],
                        },
                    },
                }
                warnings.append(
                    "DT has no native broken-links crawler. The monitor probes "
                    "only URLs the NR crawler previously discovered; it will "
                    "not re-crawl for new links."
                )
                runbook = {
                    "monitor_type": "BROKEN_LINKS",
                    "probed_urls": len(discovered_urls),
                    "limitation": (
                        "Static URL list — re-run NR crawler before migration "
                        "to capture the latest link set, or implement a custom "
                        "crawler in a DT Workflow."
                    ),
                }
                return SpecializedSyntheticResult(
                    success=True, envelope=envelope, runbook=runbook, warnings=warnings
                )

            return SpecializedSyntheticResult(
                success=False,
                errors=[
                    f"Monitor type '{monitor_type}' is not a specialized type. "
                    "Use SyntheticTransformer for SIMPLE / BROWSER / SCRIPT_API / "
                    "SCRIPT_BROWSER."
                ],
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Specialized synthetic transformation failed", error=str(exc))
            return SpecializedSyntheticResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, monitors: List[Dict[str, Any]]
    ) -> List[SpecializedSyntheticResult]:
        return [self.transform(m) for m in monitors]
