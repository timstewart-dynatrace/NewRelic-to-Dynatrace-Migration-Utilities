"""Authentication utilities for Dynatrace and New Relic APIs."""

from typing import Optional

import requests
import structlog

logger = structlog.get_logger()


def get_auth_header(token: str) -> str:
    """Return correct Authorization header based on token type."""
    if token.startswith("dt0c01."):
        return f"Api-Token {token}"
    return f"Bearer {token}"


def get_dt_oauth_token(
    client_id: str,
    client_secret: str,
    scopes: str,
) -> Optional[str]:
    """Fetch OAuth token from Dynatrace SSO using client credentials."""
    if not client_id or not client_secret:
        logger.debug("OAuth client credentials not configured")
        return None

    token_url = "https://sso.dynatrace.com/sso/oauth2/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": scopes,
    }

    try:
        response = requests.post(
            token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()
        return result.get("access_token")
    except requests.exceptions.HTTPError as e:
        error_body = e.response.text if e.response is not None else ""
        logger.error("OAuth error: %s - %s", e.response.status_code, error_body)
        return None
    except Exception as e:
        logger.warning("Could not fetch OAuth token: %s", e)
        return None


def nrql_comment(nrql: str) -> str:
    """Format NRQL as a safe single-line DQL comment."""
    return "// Original NRQL: " + " ".join(nrql.split())


def ms_to_dql_duration(ms: float) -> str:
    """Convert milliseconds to the most readable DQL duration literal."""
    if ms <= 0:
        return "0s"
    if ms >= 86_400_000 and ms % 86_400_000 == 0:
        return f"{int(ms // 86_400_000)}d"
    if ms >= 3_600_000 and ms % 3_600_000 == 0:
        return f"{int(ms // 3_600_000)}h"
    if ms >= 60_000 and ms % 60_000 == 0:
        return f"{int(ms // 60_000)}m"
    if ms >= 1000 and ms % 1000 == 0:
        return f"{int(ms // 1000)}s"
    if ms == int(ms):
        return f"{int(ms)}ms"
    us = ms * 1000
    if us == int(us):
        return f"{int(us)}us"
    return f"{ms}ms"
