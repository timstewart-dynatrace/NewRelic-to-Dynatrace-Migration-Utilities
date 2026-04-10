"""Live smoke tests for the New Relic NerdGraph client."""
import os

from clients.newrelic_client import NewRelicClient
from tests.integration.conftest import requires_nr


def _make_client() -> NewRelicClient:
    return NewRelicClient(
        api_key=os.environ["NEW_RELIC_API_KEY"],
        account_id=os.environ.get("NEW_RELIC_ACCOUNT_ID", "0"),
    )


@requires_nr()
class TestNewRelicClientLive:
    def test_should_connect_and_fetch_dashboards(self):
        """Verify the client can authenticate and execute a query against NerdGraph."""
        client = _make_client()
        dashboards = client.get_all_dashboards()
        # We only care that the call succeeds and returns a list (may be empty)
        assert isinstance(dashboards, list)

    def test_should_list_dashboards(self):
        """Verify get_all_dashboards returns a list."""
        client = _make_client()
        result = client.get_all_dashboards()
        assert isinstance(result, list)

    def test_should_list_alert_policies(self):
        """Verify get_all_alert_policies returns a list."""
        client = _make_client()
        policies = client.get_all_alert_policies()
        assert isinstance(policies, list)
