"""
Browser RUM Transformer — Gen3 target.

Converts New Relic Browser application entities into Dynatrace RUM
configurations:

  NR Browser App (entity) -> DT RUM Application (builtin:rum.web.app-config)
  NR snippet install      -> OneAgent auto-injection directive or manual
                              JS agent snippet payload
  Core Web Vitals         -> DT RUM Core Web Vitals metrics (mapped keys)
  NR events               -> DT RUM user actions / XHR / JS errors (source
                              mapping table emitted as runbook)

Only the configuration migrates. Customer code that calls `newrelic.*()`
browser SDKs is translated by `CustomInstrumentationTranslator`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


# NR Browser event -> DT Grail mapping. Used by NRQL compiler enrichment
# and surfaced in the runbook so operators can translate NRQL → DQL.
NR_BROWSER_EVENT_MAP = {
    "PageView": {"fetch": "bizevents", "filter": 'event.kind == "RUM_PAGE_VIEW"'},
    "BrowserInteraction": {
        "fetch": "bizevents",
        "filter": 'event.kind == "RUM_USER_ACTION"',
    },
    "AjaxRequest": {"fetch": "bizevents", "filter": 'event.kind == "RUM_XHR"'},
    "JavaScriptError": {
        "fetch": "bizevents",
        "filter": 'event.kind == "RUM_ERROR"',
    },
    "PageAction": {"fetch": "bizevents", "filter": 'event.kind == "RUM_USER_ACTION"'},
}

# Core Web Vital NR attribute -> DT metric key.
CORE_WEB_VITALS_MAP = {
    "largestContentfulPaint": "builtin:apps.web.largestContentfulPaint",
    "firstInputDelay": "builtin:apps.web.firstInputDelay",
    "cumulativeLayoutShift": "builtin:apps.web.cumulativeLayoutShift",
    "interactionToNextPaint": "builtin:apps.web.interactionToNextPaint",
    "timeToFirstByte": "builtin:apps.web.timeToFirstByte",
    "firstContentfulPaint": "builtin:apps.web.firstContentfulPaint",
}


@dataclass
class BrowserRUMTransformResult:
    """Result of NR Browser app -> DT RUM app translation."""

    success: bool
    app_config: Optional[Dict[str, Any]] = None
    runbook: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class BrowserRUMTransformer:
    """NR Browser app -> DT RUM (Gen3) app config + source-mapping runbook."""

    def transform(self, nr_app: Dict[str, Any]) -> BrowserRUMTransformResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            name = nr_app.get("name", "unnamed-browser-app")
            domain = nr_app.get("domain") or nr_app.get("url") or ""
            spa = bool(nr_app.get("isSpa", False))
            session_replay = bool(nr_app.get("sessionReplayEnabled", False))
            allow_domains = nr_app.get("allowedDomains") or []
            deny_domains = nr_app.get("blockedDomains") or []

            if session_replay:
                warnings.append(
                    f"Session Replay for '{name}' must be enabled in Dynatrace "
                    "Session Replay settings separately — it is a licensed feature, "
                    "not a config migration."
                )

            app_config = {
                "schemaId": "builtin:rum.web.app-config",
                "scope": "environment",
                "value": {
                    "name": f"[Migrated] {name}",
                    "description": f"Migrated from New Relic Browser app '{name}'.",
                    "enabled": True,
                    "domain": domain,
                    "type": "SPA" if spa else "MPA",
                    "injection": {
                        "mode": "AUTO",
                        "autoInjectScript": True,
                        "note": (
                            "Prefer OneAgent auto-injection. If the app is not "
                            "served by a OneAgent-monitored web server, emit the "
                            "manual RUM JS snippet via the DT UI."
                        ),
                    },
                    "monitoring": {
                        "userActions": True,
                        "xhrTracking": True,
                        "jsErrors": True,
                        "coreWebVitals": True,
                    },
                    "domainAllowlist": list(allow_domains),
                    "domainDenylist": list(deny_domains),
                },
            }

            runbook = {
                "app_name": name,
                "spa_mode": spa,
                "nr_event_to_dql": NR_BROWSER_EVENT_MAP,
                "core_web_vitals": CORE_WEB_VITALS_MAP,
                "custom_api_migration": (
                    "Calls to newrelic.interaction(), newrelic.addPageAction(), "
                    "newrelic.noticeError() in customer JS must be translated by "
                    "CustomInstrumentationTranslator (Phase 16)."
                ),
                "manual_steps": [
                    "Verify the OneAgent-injected RUM script appears in the "
                    "page's HTML after deployment.",
                    "Enable Session Replay in DT if the NR app had it enabled.",
                    "Re-map any NR segment allow/deny list entries.",
                ],
            }

            logger.info(
                "Transformed Browser RUM to Gen3",
                name=name,
                spa=spa,
                allow_domains=len(allow_domains),
            )
            return BrowserRUMTransformResult(
                success=True,
                app_config=app_config,
                runbook=runbook,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Browser RUM transformation failed", error=str(exc))
            return BrowserRUMTransformResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, apps: List[Dict[str, Any]]
    ) -> List[BrowserRUMTransformResult]:
        results = [self.transform(a) for a in apps]
        successful = sum(1 for r in results if r.success)
        logger.info(
            f"Transformed {successful}/{len(results)} Browser apps to Gen3 RUM"
        )
        return results
