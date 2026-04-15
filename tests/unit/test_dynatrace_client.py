"""Tests for the Gen3 Dynatrace client façade.

Covers:
- DynatraceClient composition (Settings 2.0 + Document + Automation sub-clients)
- Settings 2.0 CRUD, pagination, Gen3 create helpers
- Document API pagination (pageKey) and dashboard create
- Automation API workflow CRUD
- OAuth2 platform-token exchange and auth header selection
"""

from unittest.mock import MagicMock, patch

import pytest

from clients._http import (
    DynatraceResponse,
    HttpTransport,
    ImportResult,
    OAuth2PlatformTokenProvider,
)
from clients.automation_client import AutomationClient
from clients.document_client import DocumentClient
from clients.dynatrace_client import DynatraceClient
from clients.settings_v2_client import SettingsV2Client


ENV = "https://abc12345.live.dynatrace.com"


# ---------------------------------------------------------------------------
# Client composition
# ---------------------------------------------------------------------------


class TestDynatraceClientComposition:
    def test_should_require_auth(self):
        with pytest.raises(ValueError):
            DynatraceClient(environment_url=ENV)

    def test_should_compose_three_sub_clients(self):
        c = DynatraceClient(environment_url=ENV, api_token="t")
        assert isinstance(c.settings, SettingsV2Client)
        assert isinstance(c.documents, DocumentClient)
        assert isinstance(c.automation, AutomationClient)

    def test_should_route_apps_subdomain_for_platform_apis(self):
        c = DynatraceClient(environment_url=ENV, api_token="t")
        assert c.documents.base.startswith("https://abc12345.apps.")
        assert c.automation.base.startswith("https://abc12345.apps.")
        assert c.settings.base.startswith("https://abc12345.live.")


# ---------------------------------------------------------------------------
# HttpTransport + auth header resolution
# ---------------------------------------------------------------------------


class TestHttpTransportAuth:
    def test_should_use_api_token_by_default(self):
        t = HttpTransport(api_token="abc")
        assert t._auth_header(prefer_oauth=False) == "Api-Token abc"

    def test_should_prefer_oauth_when_requested(self):
        oauth = MagicMock(spec=OAuth2PlatformTokenProvider)
        oauth.bearer_header.return_value = "Bearer xyz"
        t = HttpTransport(api_token="abc", oauth=oauth)
        assert t._auth_header(prefer_oauth=True) == "Bearer xyz"
        oauth.bearer_header.assert_called_once()

    def test_should_fall_back_to_oauth_when_no_api_token(self):
        oauth = MagicMock(spec=OAuth2PlatformTokenProvider)
        oauth.bearer_header.return_value = "Bearer xyz"
        t = HttpTransport(api_token=None, oauth=oauth)
        assert t._auth_header(prefer_oauth=False) == "Bearer xyz"

    def test_should_raise_when_no_credentials(self):
        t = HttpTransport()
        with pytest.raises(RuntimeError):
            t._auth_header(prefer_oauth=False)


class TestOAuth2TokenProvider:
    def test_should_exchange_client_credentials(self):
        with patch("clients._http.requests.post") as mock_post:
            mock_post.return_value.json.return_value = {
                "access_token": "tok-1",
                "expires_in": 300,
            }
            mock_post.return_value.raise_for_status.return_value = None
            p = OAuth2PlatformTokenProvider(
                client_id="cid", client_secret="sec"
            )
            assert p.bearer_header() == "Bearer tok-1"
            assert mock_post.call_args.kwargs["data"]["grant_type"] == "client_credentials"

    def test_should_reuse_token_until_expiry(self):
        with patch("clients._http.requests.post") as mock_post:
            mock_post.return_value.json.return_value = {
                "access_token": "tok-1",
                "expires_in": 3600,
            }
            mock_post.return_value.raise_for_status.return_value = None
            p = OAuth2PlatformTokenProvider(client_id="cid", client_secret="sec")
            p.bearer_header()
            p.bearer_header()
            assert mock_post.call_count == 1


# ---------------------------------------------------------------------------
# Settings 2.0
# ---------------------------------------------------------------------------


def _ok(data):
    return DynatraceResponse(data=data, status_code=200)


def _err(error, status=400):
    return DynatraceResponse(data=None, status_code=status, error=error)


class TestSettingsV2Client:
    def test_should_paginate_list_objects(self):
        transport = MagicMock(spec=HttpTransport)
        transport.get.side_effect = [
            _ok({"items": [{"objectId": "a"}], "nextPageKey": "k"}),
            _ok({"items": [{"objectId": "b"}]}),
        ]
        client = SettingsV2Client(ENV, transport)
        items = client.list_objects("builtin:segment")
        assert [i["objectId"] for i in items] == ["a", "b"]
        assert transport.get.call_count == 2

    def test_should_post_envelope_as_list(self):
        transport = MagicMock(spec=HttpTransport)
        transport.post.return_value = _ok([{"objectId": "seg-1"}])
        client = SettingsV2Client(ENV, transport)
        env = {
            "schemaId": "builtin:segment",
            "scope": "environment",
            "value": {"name": "x"},
        }
        response = client.create_envelope(env)
        assert response.is_success
        posted = transport.post.call_args.args[1]
        assert posted == [env]

    def test_create_anomaly_detector_returns_import_result(self):
        transport = MagicMock(spec=HttpTransport)
        transport.post.return_value = _ok([{"objectId": "det-1"}])
        client = SettingsV2Client(ENV, transport)
        env = {
            "schemaId": "builtin:davis.anomaly-detectors",
            "scope": "environment",
            "value": {"name": "cpu"},
        }
        result = client.create_anomaly_detector(env)
        assert isinstance(result, ImportResult)
        assert result.success
        assert result.dynatrace_id == "det-1"
        assert result.entity_type == "anomaly_detector"

    def test_create_returns_failure_on_error(self):
        transport = MagicMock(spec=HttpTransport)
        transport.post.return_value = _err("bad schema")
        client = SettingsV2Client(ENV, transport)
        env = {
            "schemaId": "builtin:segment",
            "scope": "environment",
            "value": {"name": "x"},
        }
        result = client.create_segment(env)
        assert not result.success
        assert result.error_message == "bad schema"


# ---------------------------------------------------------------------------
# Document API
# ---------------------------------------------------------------------------


class TestDocumentClient:
    def test_should_paginate_with_pagekey_not_nextpagekey(self):
        transport = MagicMock(spec=HttpTransport)
        transport.get.side_effect = [
            _ok({"documents": [{"id": "d1"}], "nextPageKey": "pk-2"}),
            _ok({"documents": [{"id": "d2"}]}),
        ]
        client = DocumentClient(ENV, transport)
        docs = client.list_documents()
        assert [d["id"] for d in docs] == ["d1", "d2"]
        second_params = transport.get.call_args_list[1].kwargs["params"]
        assert second_params["pageKey"] == "pk-2"
        assert "nextPageKey" not in second_params

    def test_create_dashboard_posts_document_payload(self):
        transport = MagicMock(spec=HttpTransport)
        transport.post.return_value = _ok({"id": "doc-1"})
        client = DocumentClient(ENV, transport)
        result = client.create_dashboard({"name": "svc", "tiles": {}})
        assert result.success
        assert result.dynatrace_id == "doc-1"
        posted = transport.post.call_args.args[1]
        assert posted["type"] == "dashboard"
        assert "content" in posted

    def test_should_target_apps_subdomain(self):
        transport = MagicMock(spec=HttpTransport)
        client = DocumentClient(ENV, transport)
        assert "apps.dynatrace.com" in client.base


# ---------------------------------------------------------------------------
# Automation API
# ---------------------------------------------------------------------------


class TestAutomationClient:
    def test_create_workflow_success(self):
        transport = MagicMock(spec=HttpTransport)
        transport.post.return_value = _ok({"id": "wf-1"})
        client = AutomationClient(ENV, transport)
        result = client.create_workflow({"title": "alert-routing"})
        assert result.success
        assert result.entity_type == "workflow"
        assert result.dynatrace_id == "wf-1"
        assert transport.post.call_args.kwargs["prefer_oauth"] is True

    def test_list_workflows_paginates(self):
        transport = MagicMock(spec=HttpTransport)
        transport.get.side_effect = [
            _ok({"workflows": [{"id": "a"}], "nextPageKey": "nx"}),
            _ok({"workflows": [{"id": "b"}]}),
        ]
        client = AutomationClient(ENV, transport)
        workflows = client.list_workflows()
        assert [w["id"] for w in workflows] == ["a", "b"]


# ---------------------------------------------------------------------------
# Backup surface
# ---------------------------------------------------------------------------


class TestBackupAll:
    def test_should_only_include_gen3_tiers(self):
        c = DynatraceClient(environment_url=ENV, api_token="t")
        with patch.object(c.documents, "list_documents", return_value=[]), \
             patch.object(c.automation, "list_workflows", return_value=[]), \
             patch.object(c.settings, "list_objects", return_value=[]):
            backup = c.backup_all()
        assert backup["metadata"]["tier"] == "gen3"
        assert "alerting_profiles" not in backup
        assert "metric_events" not in backup
        assert "management_zones" not in backup
        for key in ("dashboards", "workflows", "anomaly_detectors", "segments"):
            assert key in backup
