"""
Mobile RUM Transformer — Gen3 target.

Converts New Relic Mobile application entities into Dynatrace Mobile
configurations and per-platform SDK-swap runbooks.

  NR Mobile App        -> DT Mobile Application (builtin:mobile-application)
  NR agent (Android,
   iOS, RN, Flutter,
   Xamarin, Unity)     -> DT Mobile SDK (platform-specific swap guidance)
  NR mobile events     -> DT mobile user sessions / crashes / requests
                          (source mapping table in runbook)
  dSYM / ProGuard      -> DT symbolication upload (helper notes)

Customer code changes are called out in the runbook; the transformer does
not rewrite SDK call sites (see `CustomInstrumentationTranslator` for that).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


# NR mobile platform -> DT SDK artifact + integration guidance.
PLATFORM_MAP = {
    "android": {
        "dt_sdk": "com.dynatrace.agent:agent-android",
        "nr_uninstall": "Remove `com.newrelic.agent.android:agent-ndk` + NewRelicConfig application init",
        "symbolication": "Upload ProGuard/R8 mapping via DT Mobile app settings",
    },
    "ios": {
        "dt_sdk": "Dynatrace pod (Dynatrace iOS agent)",
        "nr_uninstall": "Remove `NewRelicAgent` pod + `NewRelic.start(withApplicationToken:)` call",
        "symbolication": "Upload dSYM via DT mobile-symbolication API",
    },
    "react-native": {
        "dt_sdk": "@dynatrace/react-native-plugin",
        "nr_uninstall": "Remove `newrelic-react-native-agent`",
        "symbolication": "Source maps upload per platform (dSYM + ProGuard)",
    },
    "flutter": {
        "dt_sdk": "dynatrace_flutter_plugin",
        "nr_uninstall": "Remove `newrelic_mobile` plugin",
        "symbolication": "Flutter obfuscation artifacts + platform mapping",
    },
    "xamarin": {
        "dt_sdk": "Dynatrace.Xamarin.Android / Dynatrace.Xamarin.iOS",
        "nr_uninstall": "Remove NewRelic.Xamarin.* packages",
        "symbolication": "Platform-native (dSYM / ProGuard)",
    },
    "unity": {
        "dt_sdk": "Dynatrace Unity plugin",
        "nr_uninstall": "Remove NewRelic Unity package",
        "symbolication": "Unity IL2CPP symbols + platform-native",
    },
    "cordova": {
        "dt_sdk": "cordova-plugin-dynatrace",
        "nr_uninstall": "Remove cordova-plugin-newrelic",
        "symbolication": "Platform-native",
    },
    "capacitor": {
        "dt_sdk": "@dynatrace/capacitor-plugin",
        "nr_uninstall": "Remove @newrelic/capacitor-plugin",
        "symbolication": "Platform-native",
    },
}


# NR mobile event -> DT Grail mapping.
NR_MOBILE_EVENT_MAP = {
    "MobileSession": {"fetch": "bizevents", "filter": 'event.kind == "MOBILE_SESSION"'},
    "MobileCrash": {"fetch": "bizevents", "filter": 'event.kind == "MOBILE_CRASH"'},
    "MobileHandledException": {
        "fetch": "bizevents",
        "filter": 'event.kind == "MOBILE_ERROR"',
    },
    "MobileRequest": {
        "fetch": "bizevents",
        "filter": 'event.kind == "MOBILE_WEB_REQUEST"',
    },
    "MobileRequestError": {
        "fetch": "bizevents",
        "filter": 'event.kind == "MOBILE_WEB_REQUEST_ERROR"',
    },
}


@dataclass
class MobileRUMTransformResult:
    """Result of NR Mobile app -> DT Mobile app translation."""

    success: bool
    app_config: Optional[Dict[str, Any]] = None
    runbook: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class MobileRUMTransformer:
    """NR Mobile app -> DT Mobile (Gen3) app config + SDK-swap runbook."""

    def transform(self, nr_app: Dict[str, Any]) -> MobileRUMTransformResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            name = nr_app.get("name", "unnamed-mobile-app")
            platform = str(nr_app.get("platform", "android")).lower()
            bundle_id = nr_app.get("bundleId") or nr_app.get("packageName", "")
            crash_reporting = bool(nr_app.get("crashReportingEnabled", True))
            handled_exceptions = bool(
                nr_app.get("handledExceptionsEnabled", True)
            )

            platform_info = PLATFORM_MAP.get(platform)
            if platform_info is None:
                warnings.append(
                    f"Unknown mobile platform '{platform}' for app '{name}'. "
                    "Dynatrace supports Android, iOS, React Native, Flutter, "
                    "Xamarin, Unity, Cordova, Capacitor — operator must pick the "
                    "closest match manually."
                )
                platform_info = {
                    "dt_sdk": "(manual)",
                    "nr_uninstall": "(manual)",
                    "symbolication": "(manual)",
                }

            app_config = {
                "schemaId": "builtin:mobile-application",
                "scope": "environment",
                "value": {
                    "name": f"[Migrated] {name}",
                    "applicationId": bundle_id,
                    "platform": platform.upper(),
                    "crashReporting": crash_reporting,
                    "userOptIn": False,
                    "apdexSettings": {
                        "frustratingThreshold": 12000,
                        "toleratedThreshold": 3000,
                    },
                },
            }

            runbook = {
                "app_name": name,
                "platform": platform,
                "bundle_id": bundle_id,
                "sdk_swap": platform_info,
                "nr_event_to_dql": NR_MOBILE_EVENT_MAP,
                "features_to_verify": [
                    "Crash reporting parity",
                    "Handled exceptions parity" if handled_exceptions else None,
                    "Network request timing",
                    "User action tracking",
                    "Device info dimensions (OS, model, carrier)",
                ],
                "symbolication_steps": platform_info.get("symbolication"),
                "post_deploy_check": (
                    "Build a debug build with DT SDK, launch, navigate a few "
                    "screens, force a handled exception. Verify session + "
                    "errors appear in the DT Mobile app within 2 minutes."
                ),
            }

            logger.info(
                "Transformed Mobile RUM to Gen3",
                name=name,
                platform=platform,
            )
            return MobileRUMTransformResult(
                success=True,
                app_config=app_config,
                runbook=runbook,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Mobile RUM transformation failed", error=str(exc))
            return MobileRUMTransformResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, apps: List[Dict[str, Any]]
    ) -> List[MobileRUMTransformResult]:
        results = [self.transform(a) for a in apps]
        successful = sum(1 for r in results if r.success)
        logger.info(
            f"Transformed {successful}/{len(results)} Mobile apps to Gen3 RUM"
        )
        return results
