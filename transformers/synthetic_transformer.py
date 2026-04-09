"""
Synthetic Monitor Transformer - Converts New Relic synthetics to Dynatrace format.
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass
import structlog

from .mapping_rules import (
    SYNTHETIC_MONITOR_TYPE_MAP,
    MONITOR_PERIOD_MAP,
)

logger = structlog.get_logger()


@dataclass
class SyntheticTransformResult:
    """Result of synthetic monitor transformation."""
    success: bool
    monitor: Optional[Dict[str, Any]] = None
    monitor_type: str = ""  # HTTP or BROWSER
    warnings: List[str] = None
    errors: List[str] = None

    def __post_init__(self):
        self.warnings = self.warnings or []
        self.errors = self.errors or []


class SyntheticTransformer:
    """
    Transforms New Relic synthetic monitors to Dynatrace format.

    Mapping:
    - New Relic Ping Monitor -> Dynatrace HTTP Monitor
    - New Relic Simple Browser -> Dynatrace Browser Monitor (single URL)
    - New Relic Scripted Browser -> Dynatrace Browser Monitor (scripted)
    - New Relic Scripted API -> Dynatrace HTTP Monitor (multi-step)
    """

    # Default Dynatrace synthetic locations (public)
    DEFAULT_LOCATIONS = [
        "GEOLOCATION-9999453BE4BDB3CD",  # AWS US East (N. Virginia)
    ]

    def __init__(self, available_locations: Optional[List[str]] = None):
        self.available_locations = available_locations or self.DEFAULT_LOCATIONS

    def transform(self, nr_monitor: Dict[str, Any]) -> SyntheticTransformResult:
        """Transform a New Relic synthetic monitor to Dynatrace format."""
        warnings = []
        errors = []

        try:
            monitor_type = nr_monitor.get("monitorType", "SIMPLE")
            monitor_name = nr_monitor.get("name", "Unnamed Monitor")

            # Determine target Dynatrace monitor type
            dt_monitor_type = SYNTHETIC_MONITOR_TYPE_MAP.get(monitor_type, "HTTP")

            if dt_monitor_type == "HTTP":
                result = self._transform_to_http_monitor(nr_monitor, warnings)
            elif dt_monitor_type == "BROWSER":
                result = self._transform_to_browser_monitor(nr_monitor, warnings)
            else:
                errors.append(f"Unknown monitor type: {monitor_type}")
                return SyntheticTransformResult(
                    success=False,
                    errors=errors
                )

            logger.info(
                "Transformed synthetic monitor",
                name=monitor_name,
                type=dt_monitor_type
            )

            return SyntheticTransformResult(
                success=True,
                monitor=result,
                monitor_type=dt_monitor_type,
                warnings=warnings
            )

        except Exception as e:
            logger.error("Synthetic monitor transformation failed", error=str(e))
            return SyntheticTransformResult(
                success=False,
                errors=[f"Transformation error: {str(e)}"]
            )

    def _transform_to_http_monitor(
        self,
        nr_monitor: Dict[str, Any],
        warnings: List[str]
    ) -> Dict[str, Any]:
        """Transform to Dynatrace HTTP monitor."""
        monitor_name = nr_monitor.get("name", "Unnamed Monitor")
        monitored_url = nr_monitor.get("monitoredUrl", "")
        period = nr_monitor.get("period", "EVERY_15_MINUTES")
        status = nr_monitor.get("status", "ENABLED")

        # Map frequency
        frequency_min = MONITOR_PERIOD_MAP.get(period, 15)

        # Build HTTP monitor configuration
        dt_monitor = {
            "name": f"[Migrated] {monitor_name}",
            "frequencyMin": frequency_min,
            "enabled": status == "ENABLED",
            "type": "HTTP",
            "createdFrom": "API",
            "script": {
                "version": "1.0",
                "requests": [
                    {
                        "description": "Migrated from New Relic",
                        "url": monitored_url,
                        "method": "GET",
                        "requestBody": "",
                        "validation": {
                            "rules": [
                                {
                                    "type": "httpStatusesList",
                                    "passIfFound": True,
                                    "value": ">=200, <400"
                                }
                            ],
                            "rulesChaining": "or"
                        },
                        "configuration": {
                            "acceptAnyCertificate": False,
                            "followRedirects": True
                        }
                    }
                ]
            },
            "locations": self.available_locations,
            "anomalyDetection": {
                "outageHandling": {
                    "globalOutage": True,
                    "globalOutagePolicy": {
                        "consecutiveRuns": 1
                    },
                    "localOutage": True,
                    "localOutagePolicy": {
                        "affectedLocations": 1,
                        "consecutiveRuns": 1
                    }
                },
                "loadingTimeThresholds": {
                    "enabled": True,
                    "thresholds": [
                        {
                            "type": "TOTAL",
                            "valueMs": 10000
                        }
                    ]
                }
            },
            "tags": [
                {
                    "key": "migrated-from",
                    "value": "newrelic"
                }
            ]
        }

        # Handle scripted API monitors
        if nr_monitor.get("monitorType") == "SCRIPT_API":
            warnings.append(
                f"Monitor '{monitor_name}' was a scripted API monitor. "
                "The script logic needs manual recreation in Dynatrace."
            )

        # Add validation rules from New Relic if present
        # (New Relic stores these differently based on monitor type)

        return dt_monitor

    def _transform_to_browser_monitor(
        self,
        nr_monitor: Dict[str, Any],
        warnings: List[str]
    ) -> Dict[str, Any]:
        """Transform to Dynatrace browser monitor."""
        monitor_name = nr_monitor.get("name", "Unnamed Monitor")
        monitored_url = nr_monitor.get("monitoredUrl", "")
        period = nr_monitor.get("period", "EVERY_15_MINUTES")
        status = nr_monitor.get("status", "ENABLED")
        monitor_type = nr_monitor.get("monitorType", "BROWSER")

        # Map frequency
        frequency_min = MONITOR_PERIOD_MAP.get(period, 15)

        # Build browser monitor configuration
        dt_monitor = {
            "name": f"[Migrated] {monitor_name}",
            "frequencyMin": frequency_min,
            "enabled": status == "ENABLED",
            "type": "BROWSER",
            "createdFrom": "API",
            "script": self._build_browser_script(monitored_url, monitor_type, warnings),
            "locations": self.available_locations,
            "anomalyDetection": {
                "outageHandling": {
                    "globalOutage": True,
                    "globalOutagePolicy": {
                        "consecutiveRuns": 1
                    },
                    "localOutage": True,
                    "localOutagePolicy": {
                        "affectedLocations": 1,
                        "consecutiveRuns": 1
                    }
                },
                "loadingTimeThresholds": {
                    "enabled": True,
                    "thresholds": [
                        {
                            "type": "TOTAL",
                            "valueMs": 30000
                        }
                    ]
                }
            },
            "keyPerformanceMetrics": {
                "loadActionKpm": "VISUALLY_COMPLETE",
                "xhrActionKpm": "VISUALLY_COMPLETE"
            },
            "tags": [
                {
                    "key": "migrated-from",
                    "value": "newrelic"
                }
            ]
        }

        return dt_monitor

    def _build_browser_script(
        self,
        url: str,
        monitor_type: str,
        warnings: List[str]
    ) -> Dict[str, Any]:
        """Build a Dynatrace browser clickpath script."""
        # For simple browser monitors, create a single navigation event
        if monitor_type in ["BROWSER", "SIMPLE"]:
            return {
                "type": "clickpath",
                "version": "1.0",
                "configuration": {
                    "device": {
                        "orientation": "landscape",
                        "deviceName": "Desktop"
                    }
                },
                "events": [
                    {
                        "type": "navigate",
                        "wait": {
                            "waitFor": "page_complete"
                        },
                        "url": url,
                        "description": f"Navigate to {url}"
                    }
                ]
            }

        # For scripted browser monitors
        warnings.append(
            f"Browser script for URL '{url}' was a scripted monitor. "
            "Complex interactions (clicks, form fills, etc.) need manual recreation. "
            "A basic navigation script has been created."
        )

        return {
            "type": "clickpath",
            "version": "1.0",
            "configuration": {
                "device": {
                    "orientation": "landscape",
                    "deviceName": "Desktop"
                }
            },
            "events": [
                {
                    "type": "navigate",
                    "wait": {
                        "waitFor": "page_complete"
                    },
                    "url": url,
                    "description": f"Navigate to {url}"
                },
                {
                    "type": "javascript",
                    "wait": {
                        "waitFor": "validation"
                    },
                    "javaScript": "// TODO: Add custom validation from New Relic script\nreturn true;",
                    "description": "Custom validation (migrated)"
                }
            ]
        }

    def transform_all(
        self,
        monitors: List[Dict[str, Any]]
    ) -> List[SyntheticTransformResult]:
        """Transform multiple synthetic monitors."""
        results = []

        for monitor in monitors:
            result = self.transform(monitor)
            results.append(result)

        successful = sum(1 for r in results if r.success)
        http_count = sum(1 for r in results if r.success and r.monitor_type == "HTTP")
        browser_count = sum(1 for r in results if r.success and r.monitor_type == "BROWSER")

        logger.info(
            f"Transformed {successful}/{len(results)} synthetic monitors "
            f"({http_count} HTTP, {browser_count} Browser)"
        )

        return results


class SyntheticScriptConverter:
    """
    Utility class for converting New Relic synthetic scripts to Dynatrace format.

    Note: Full script conversion is complex and often requires manual intervention.
    This class provides helpers for common patterns.
    """

    # New Relic to Dynatrace API mapping for common Selenium commands
    SELENIUM_COMMAND_MAP = {
        "$browser.get": "navigate",
        "$browser.findElement": "click",  # Simplified
        "$browser.wait": "javascript",
        ".click()": "click",
        ".sendKeys()": "keystrokes",
    }

    @staticmethod
    def analyze_script(script: str) -> Dict[str, Any]:
        """
        Analyze a New Relic synthetic script and provide conversion guidance.
        """
        analysis = {
            "complexity": "simple",
            "has_navigation": False,
            "has_clicks": False,
            "has_form_input": False,
            "has_assertions": False,
            "has_custom_logic": False,
            "estimated_effort": "low",
            "recommendations": []
        }

        if not script:
            return analysis

        script_lower = script.lower()

        # Check for navigation
        if "$browser.get" in script or "navigate" in script_lower:
            analysis["has_navigation"] = True

        # Check for clicks
        if ".click()" in script or "click" in script_lower:
            analysis["has_clicks"] = True

        # Check for form input
        if ".sendkeys" in script_lower or "input" in script_lower:
            analysis["has_form_input"] = True

        # Check for assertions
        if "assert" in script_lower or "expect" in script_lower:
            analysis["has_assertions"] = True

        # Check for custom logic
        if "function" in script_lower or "async" in script_lower:
            analysis["has_custom_logic"] = True

        # Determine complexity
        complexity_factors = sum([
            analysis["has_clicks"],
            analysis["has_form_input"],
            analysis["has_assertions"],
            analysis["has_custom_logic"]
        ])

        if complexity_factors == 0:
            analysis["complexity"] = "simple"
            analysis["estimated_effort"] = "low"
        elif complexity_factors <= 2:
            analysis["complexity"] = "moderate"
            analysis["estimated_effort"] = "medium"
        else:
            analysis["complexity"] = "complex"
            analysis["estimated_effort"] = "high"

        # Add recommendations
        if analysis["has_navigation"]:
            analysis["recommendations"].append(
                "Navigation can be directly converted to Dynatrace 'navigate' events"
            )

        if analysis["has_clicks"]:
            analysis["recommendations"].append(
                "Click actions need element selectors updated for Dynatrace clickpath format"
            )

        if analysis["has_form_input"]:
            analysis["recommendations"].append(
                "Form inputs should be converted to 'keystrokes' events in Dynatrace"
            )

        if analysis["has_assertions"]:
            analysis["recommendations"].append(
                "Assertions should be converted to Dynatrace validation rules or JavaScript events"
            )

        if analysis["has_custom_logic"]:
            analysis["recommendations"].append(
                "Custom JavaScript logic may need significant refactoring for Dynatrace"
            )

        return analysis
