"""Tests for DynatraceClient — all public methods with mocked HTTP."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from clients.legacy.config_v1_client import DynatraceResponse, ImportResult
from clients.legacy.config_v1_client import LegacyDynatraceV1Client as DynatraceClient


@pytest.fixture
def client():
    return DynatraceClient(
        api_token="dt0c01.TEST",
        environment_url="https://abc123.live.dynatrace.com",
        rate_limit=0
    )


def _mock_response(data, status_code=200):
    """Create a mock requests.Response."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.content = b'{"data": true}' if data is not None else b''
    mock.json.return_value = data
    mock.reason = "OK" if status_code < 400 else "Error"
    return mock


class TestDynatraceResponse:
    def test_should_be_success_for_2xx(self):
        assert DynatraceResponse(data={}, status_code=200).is_success is True
        assert DynatraceResponse(data={}, status_code=201).is_success is True

    def test_should_not_be_success_for_4xx(self):
        assert DynatraceResponse(data=None, status_code=400).is_success is False
        assert DynatraceResponse(data=None, status_code=401).is_success is False


class TestImportResult:
    def test_should_store_fields(self):
        r = ImportResult("dashboard", "My Dash", True, "dash-123")
        assert r.entity_type == "dashboard"
        assert r.success is True
        assert r.dynatrace_id == "dash-123"


class TestDynatraceClientInit:
    def test_should_set_api_endpoints(self):
        c = DynatraceClient("token", "https://abc.live.dynatrace.com", rate_limit=0)
        assert c.api_v2 == "https://abc.live.dynatrace.com/api/v2"
        assert c.config_api == "https://abc.live.dynatrace.com/api/config/v1"

    def test_should_strip_trailing_slash(self):
        c = DynatraceClient("token", "https://abc.live.dynatrace.com/", rate_limit=0)
        assert c.environment_url == "https://abc.live.dynatrace.com"

    def test_should_set_auth_header(self):
        c = DynatraceClient("dt0c01.TEST", "https://abc.live.dynatrace.com", rate_limit=0)
        assert "Api-Token dt0c01.TEST" in c.session.headers["Authorization"]


class TestHTTPMethods:
    def test_get_should_call_request(self, client):
        with patch.object(client.session, 'request', return_value=_mock_response({"ok": True})):
            resp = client.get("https://abc.live.dynatrace.com/api/v2/test")
            assert resp.is_success
            assert resp.data["ok"] is True

    def test_post_should_call_request(self, client):
        with patch.object(client.session, 'request', return_value=_mock_response({"id": "123"}, 201)):
            resp = client.post("https://url/api", {"name": "test"})
            assert resp.is_success

    def test_should_handle_http_error(self, client):
        with patch.object(client.session, 'request', return_value=_mock_response({"error": "bad"}, 400)):
            resp = client.get("https://url/api")
            assert resp.is_success is False
            assert resp.error is not None

    def test_should_handle_connection_error(self, client):
        import requests as req
        with patch.object(client.session, 'request', side_effect=req.exceptions.ConnectionError("timeout")):
            resp = client.get("https://url/api")
            assert resp.is_success is False
            assert resp.status_code == 0


class TestSettingsAPI:
    def test_should_get_schemas(self, client):
        with patch.object(client.session, 'request', return_value=_mock_response({"items": [{"id": "schema1"}]})):
            schemas = client.get_settings_schemas()
            assert len(schemas) == 1

    def test_should_get_settings_objects(self, client):
        with patch.object(client.session, 'request', return_value=_mock_response({"items": [{"objectId": "o1"}], "nextPageKey": None})):
            objects = client.get_settings_objects("builtin:alerting.profile")
            assert len(objects) == 1

    def test_should_create_settings_object(self, client):
        with patch.object(client.session, 'request', return_value=_mock_response([{"objectId": "new-1"}], 201)):
            resp = client.create_settings_object("builtin:test", {"name": "test"})
            assert resp.is_success

    def test_should_update_settings_object(self, client):
        with patch.object(client.session, 'request', return_value=_mock_response({"objectId": "o1"}, 200)):
            resp = client.update_settings_object("o1", {"name": "updated"})
            assert resp.is_success


class TestCreateDashboard:
    def test_should_return_success_result(self, client):
        dash = {"dashboardMetadata": {"name": "My Dash"}, "tiles": []}
        with patch.object(client.session, 'request', return_value=_mock_response({"id": "dash-abc"}, 201)):
            result = client.create_dashboard(dash)
            assert result.success is True
            assert result.entity_type == "dashboard"
            assert result.dynatrace_id == "dash-abc"

    def test_should_return_failure_on_error(self, client):
        dash = {"dashboardMetadata": {"name": "Bad"}, "tiles": []}
        with patch.object(client.session, 'request', return_value=_mock_response({"error": "invalid"}, 400)):
            result = client.create_dashboard(dash)
            assert result.success is False
            assert result.error_message is not None


class TestGetAllDashboards:
    def test_should_return_dashboards(self, client):
        list_resp = _mock_response({"dashboards": [{"id": "d1"}, {"id": "d2"}]})
        detail_resp = _mock_response({"id": "d1", "dashboardMetadata": {"name": "Test"}})
        with patch.object(client.session, 'request') as mock:
            mock.side_effect = [list_resp, detail_resp, detail_resp]
            dashboards = client.get_all_dashboards()
            assert len(dashboards) == 2


class TestCreateMetricEvent:
    def test_should_return_success(self, client):
        with patch.object(client.session, 'request', return_value=_mock_response([{"objectId": "me-1"}], 201)):
            result = client.create_metric_event({"summary": "High Latency"})
            assert result.success is True
            assert result.entity_type == "metric_event"

    def test_should_return_failure(self, client):
        with patch.object(client.session, 'request', return_value=_mock_response({"error": "bad"}, 400)):
            result = client.create_metric_event({"summary": "Bad"})
            assert result.success is False


class TestCreateAlertingProfile:
    def test_should_return_success(self, client):
        with patch.object(client.session, 'request', return_value=_mock_response([{"objectId": "ap-1"}], 201)):
            result = client.create_alerting_profile({"name": "Critical"})
            assert result.success is True
            assert result.entity_type == "alerting_profile"


class TestSyntheticMonitors:
    def test_should_create_http_monitor(self, client):
        with patch.object(client.session, 'request', return_value=_mock_response({"entityId": "HTTP-1"}, 200)):
            result = client.create_http_monitor({"name": "Health"})
            assert result.success is True
            assert result.entity_type == "http_monitor"

    def test_should_create_browser_monitor(self, client):
        with patch.object(client.session, 'request', return_value=_mock_response({"entityId": "BROWSER-1"}, 200)):
            result = client.create_browser_monitor({"name": "Login Flow"})
            assert result.success is True
            assert result.entity_type == "browser_monitor"

    def test_should_get_locations(self, client):
        with patch.object(client.session, 'request', return_value=_mock_response({"locations": [{"id": "loc1"}]})):
            locations = client.get_synthetic_locations()
            assert len(locations) == 1


class TestSLO:
    def test_should_create_slo(self, client):
        with patch.object(client.session, 'request', return_value=_mock_response({"id": "slo-1"}, 201)):
            result = client.create_slo({"name": "Availability"})
            assert result.success is True

    def test_should_get_all_slos(self, client):
        with patch.object(client.session, 'request', return_value=_mock_response({"slo": [{"id": "s1"}], "nextPageKey": None})):
            slos = client.get_all_slos()
            assert len(slos) == 1


class TestManagementZone:
    def test_should_create_management_zone(self, client):
        with patch.object(client.session, 'request', return_value=_mock_response([{"objectId": "mz-1"}], 201)):
            result = client.create_management_zone({"name": "Production"})
            assert result.success is True
            assert result.entity_type == "management_zone"


class TestNotificationIntegration:
    def test_should_create_email_notification(self, client):
        with patch.object(client.session, 'request', return_value=_mock_response([{"objectId": "n-1"}], 201)):
            result = client.create_notification_integration("email", {"name": "Team Email"})
            assert result.success is True

    def test_should_fail_for_unknown_type(self, client):
        result = client.create_notification_integration("carrier_pigeon", {"name": "Bird"})
        assert result.success is False
        assert "Unknown integration type" in result.error_message


class TestCreateDashboardV2:
    def test_should_create_via_documents_api(self, client):
        dash = {"dashboardMetadata": {"name": "My Dash", "shared": True}, "tiles": []}
        with patch.object(client.session, 'request', return_value=_mock_response({"id": "doc-123"}, 201)):
            result = client.create_dashboard_v2(dash)
            assert result.success is True
            assert result.dynatrace_id == "doc-123"

    def test_should_return_failure_on_error(self, client):
        dash = {"dashboardMetadata": {"name": "Bad"}, "tiles": []}
        with patch.object(client.session, 'request', return_value=_mock_response({"error": "auth"}, 403)):
            result = client.create_dashboard_v2(dash)
            assert result.success is False

    def test_should_update_dashboard_v2(self, client):
        dash = {"dashboardMetadata": {"name": "Updated"}, "tiles": []}
        with patch.object(client.session, 'request', return_value=_mock_response({"id": "doc-123"}, 200)):
            result = client.update_dashboard_v2("doc-123", dash)
            assert result.success is True


class TestValidateConnection:
    def test_should_return_true_on_success(self, client):
        with patch.object(client.session, 'request', return_value=_mock_response({"items": []})):
            assert client.validate_connection() is True

    def test_should_return_false_on_failure(self, client):
        with patch.object(client.session, 'request', return_value=_mock_response(None, 401)):
            assert client.validate_connection() is False


class TestBackupAll:
    def test_should_backup_all_entity_types(self, client):
        empty = _mock_response({"dashboards": [], "items": [], "slo": [], "nextPageKey": None})
        with patch.object(client.session, 'request', return_value=empty):
            result = client.backup_all()
            assert "metadata" in result
            assert "dashboards" in result
            assert "slos" in result
            assert "alerting_profiles" in result
            assert "management_zones" in result
