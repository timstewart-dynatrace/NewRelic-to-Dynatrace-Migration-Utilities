"""Live smoke tests for the Dynatrace API client."""
import os

from clients.dynatrace_client import DynatraceClient
from tests.integration.conftest import requires_dt


def _make_client() -> DynatraceClient:
    return DynatraceClient(
        api_token=os.environ["DYNATRACE_API_TOKEN"],
        environment_url=os.environ.get("DYNATRACE_ENVIRONMENT_URL", "https://localhost"),
    )


@requires_dt()
class TestDynatraceClientLive:
    def test_should_connect_to_environment(self):
        """Verify validate_connection succeeds against a real environment."""
        client = _make_client()
        assert client.validate_connection() is True

    def test_should_list_management_zones(self):
        """Verify listing management zones returns a list."""
        client = _make_client()
        zones = client.get_settings_objects("builtin:management-zones")
        assert isinstance(zones, list)

    def test_should_create_and_delete_test_dashboard(self):
        """Create a minimal dashboard with a known prefix, then delete it."""
        client = _make_client()
        dashboard_payload = {
            "dashboardMetadata": {
                "name": "[INTEGRATION-TEST] Smoke Test Dashboard",
                "owner": "integration-test",
                "shared": False,
            },
            "tiles": [],
        }

        result = client.create_dashboard(dashboard_payload)
        try:
            assert result.success, f"Dashboard creation failed: {result.error_message}"
            assert result.dynatrace_id is not None
        finally:
            # Always attempt cleanup
            if result.dynatrace_id:
                url = f"{client.config_api}/dashboards/{result.dynatrace_id}"
                client.delete(url)
