"""Integration test fixtures. All tests skip unless RUN_INTEGRATION_TESTS=1 and relevant API credentials are set."""
import os

import pytest

INTEGRATION = os.getenv("RUN_INTEGRATION_TESTS", "").lower() in ("1", "true", "yes")


def requires_integration():
    return pytest.mark.skipif(not INTEGRATION, reason="RUN_INTEGRATION_TESTS not set")


def requires_nr():
    return pytest.mark.skipif(
        not INTEGRATION or not os.getenv("NEW_RELIC_API_KEY"),
        reason="RUN_INTEGRATION_TESTS and NEW_RELIC_API_KEY required",
    )


def requires_dt():
    return pytest.mark.skipif(
        not INTEGRATION or not os.getenv("DYNATRACE_API_TOKEN"),
        reason="RUN_INTEGRATION_TESTS and DYNATRACE_API_TOKEN required",
    )
