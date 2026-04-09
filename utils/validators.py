"""Validation utilities for migration configurations."""

from typing import Dict, Any, List, Tuple
import re


def validate_newrelic_config(config: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate New Relic configuration.

    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []

    # Check API key format
    api_key = config.get("api_key", "")
    if not api_key:
        errors.append("NEW_RELIC_API_KEY is required")
    elif not api_key.startswith("NRAK-"):
        errors.append("NEW_RELIC_API_KEY should start with 'NRAK-'")

    # Check account ID
    account_id = config.get("account_id", "")
    if not account_id:
        errors.append("NEW_RELIC_ACCOUNT_ID is required")
    elif not account_id.isdigit():
        errors.append("NEW_RELIC_ACCOUNT_ID should be numeric")

    # Check region
    region = config.get("region", "US").upper()
    if region not in ["US", "EU"]:
        errors.append("NEW_RELIC_REGION should be 'US' or 'EU'")

    return len(errors) == 0, errors


def validate_dynatrace_config(config: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate Dynatrace configuration.

    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []

    # Check API token
    api_token = config.get("api_token", "")
    if not api_token:
        errors.append("DYNATRACE_API_TOKEN is required")
    elif not api_token.startswith("dt0c01."):
        errors.append("DYNATRACE_API_TOKEN should start with 'dt0c01.'")

    # Check environment URL
    env_url = config.get("environment_url", "")
    if not env_url:
        errors.append("DYNATRACE_ENVIRONMENT_URL is required")
    else:
        # Validate URL format
        url_pattern = r"^https://[a-zA-Z0-9-]+\.(live|apps)\.dynatrace\.com$"
        if not re.match(url_pattern, env_url):
            errors.append(
                "DYNATRACE_ENVIRONMENT_URL should be in format: "
                "https://<environment-id>.live.dynatrace.com"
            )

    return len(errors) == 0, errors


def validate_dashboard(dashboard: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate a Dynatrace dashboard structure."""
    errors = []

    # Check required fields
    if "dashboardMetadata" not in dashboard:
        errors.append("Dashboard missing 'dashboardMetadata'")
    else:
        metadata = dashboard["dashboardMetadata"]
        if "name" not in metadata:
            errors.append("Dashboard metadata missing 'name'")

    if "tiles" not in dashboard:
        errors.append("Dashboard missing 'tiles'")

    return len(errors) == 0, errors


def validate_metric_event(event: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate a Dynatrace metric event structure."""
    errors = []

    if "summary" not in event:
        errors.append("Metric event missing 'summary'")

    if "monitoringStrategy" not in event:
        errors.append("Metric event missing 'monitoringStrategy'")

    return len(errors) == 0, errors


def validate_synthetic_monitor(monitor: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate a Dynatrace synthetic monitor structure."""
    errors = []

    if "name" not in monitor:
        errors.append("Synthetic monitor missing 'name'")

    if "type" not in monitor:
        errors.append("Synthetic monitor missing 'type'")
    elif monitor["type"] not in ["HTTP", "BROWSER"]:
        errors.append(f"Invalid monitor type: {monitor['type']}")

    if "frequencyMin" not in monitor:
        errors.append("Synthetic monitor missing 'frequencyMin'")

    if "locations" not in monitor or not monitor["locations"]:
        errors.append("Synthetic monitor missing 'locations'")

    return len(errors) == 0, errors
