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
    def test_should_use_api_token_for_classic_dt0c01_prefix(self):
        # Classic Api-Token prefix — must use the legacy scheme.
        t = HttpTransport(api_token="dt0c01.CLASSIC")
        assert t._auth_header(prefer_oauth=False) == "Api-Token dt0c01.CLASSIC"

    def test_should_use_bearer_for_platform_token_dt0s16_prefix(self):
        # Regression for #17 lab repro — Platform Tokens stored in
        # DYNATRACE_API_TOKEN were being sent as `Api-Token`, which the
        # tenant rejects with 401 "Unsupported authorization scheme".
        t = HttpTransport(api_token="dt0s16.PLATFORM")
        assert t._auth_header(prefer_oauth=False) == "Bearer dt0s16.PLATFORM"

    def test_should_use_bearer_for_platform_oauth_dt0s01_prefix(self):
        t = HttpTransport(api_token="dt0s01.PLATFORM_OAUTH")
        assert t._auth_header(prefer_oauth=False) == "Bearer dt0s01.PLATFORM_OAUTH"

    def test_should_prefer_oauth_when_requested(self):
        oauth = MagicMock(spec=OAuth2PlatformTokenProvider)
        oauth.bearer_header.return_value = "Bearer xyz"
        t = HttpTransport(api_token="dt0c01.abc", oauth=oauth)
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

    def test_create_dashboard_posts_multipart_form_data(self):
        # Gen3 Document API rejects application/json with 415. Must send
        # multipart/form-data with separate `name`, `type`, `isPrivate`, and
        # `content` parts — mirrors the `@dynatrace-sdk/client-document` wire
        # format.
        transport = MagicMock(spec=HttpTransport)
        transport.post_multipart.return_value = _ok({"id": "doc-1"})
        client = DocumentClient(ENV, transport)
        result = client.create_dashboard({"name": "svc", "tiles": {}})
        assert result.success
        assert result.dynatrace_id == "doc-1"

        # The old .post(json=body) path must NOT be used anymore.
        assert not transport.post.called, (
            "create_dashboard must not fall back to application/json POST — "
            "Gen3 Document API returns 415 for that."
        )
        # Verify multipart shape.
        files = transport.post_multipart.call_args.kwargs.get(
            "files"
        ) or transport.post_multipart.call_args.args[1]
        assert files["name"] == (None, "svc")
        assert files["type"] == (None, "dashboard")
        assert files["isPrivate"] == (None, "false")
        content_part = files["content"]
        assert content_part[0] == "content.json"
        assert '"tiles"' in content_part[1]
        assert content_part[2] == "application/json"

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


# ---------------------------------------------------------------------------
# Preflight diagnostics
# ---------------------------------------------------------------------------


class TestPreflightGen3:
    """preflight_gen3 must capture per-API status + scope metadata so the CLI
    can tell the operator exactly which scope is missing and how to fix it.
    """

    def _client_with_responses(self, responses_by_url):
        """Build a DynatraceClient whose transport.get returns canned
        DynatraceResponse objects keyed by endpoint URL substring.
        """
        c = DynatraceClient(environment_url=ENV, api_token="t")

        def fake_get(url, **kwargs):
            for key, resp in responses_by_url.items():
                if key in url:
                    return resp
            return DynatraceResponse(data=None, status_code=0, error="no stub")

        c.transport.get = MagicMock(side_effect=fake_get)
        return c

    def test_all_reachable_returns_ok_checks(self):
        c = self._client_with_responses({
            "/api/v2/settings/schemas": DynatraceResponse(data={}, status_code=200),
            "/platform/document/v1/documents": DynatraceResponse(data={}, status_code=200),
            "/platform/automation/v1/workflows": DynatraceResponse(data={}, status_code=200),
        })
        checks = c.preflight_gen3()
        assert [ch.api for ch in checks] == [
            "settings_v2", "document_api", "automation_api"
        ]
        assert all(ch.reachable for ch in checks)
        assert all(ch.status_code == 200 for ch in checks)
        assert all(ch.remediation == [] for ch in checks)

    def test_403_produces_scope_specific_remediation(self):
        """A 403 on document_api must surface the document:documents:read
        scope name and include remediation steps pointing at the UI.
        """
        c = self._client_with_responses({
            "/api/v2/settings/schemas": DynatraceResponse(data={}, status_code=200),
            "/platform/document/v1/documents": DynatraceResponse(
                data=None, status_code=403, error="Forbidden"
            ),
            "/platform/automation/v1/workflows": DynatraceResponse(data={}, status_code=200),
        })
        checks = {ch.api: ch for ch in c.preflight_gen3()}
        doc = checks["document_api"]
        assert doc.reachable is False
        assert doc.status_code == 403
        assert "document:documents:read" in doc.scopes_min
        assert "HTTP 403" in doc.diagnosis
        # Remediation mentions the UI path and a re-run command.
        assert any("Access Tokens" in s for s in doc.remediation)
        assert any("preflight" in s for s in doc.remediation)

    def test_404_suggests_legacy_mode(self):
        """A 404 on an automation endpoint indicates a Classic tenant and
        must nudge the operator toward --legacy."""
        c = self._client_with_responses({
            "/api/v2/settings/schemas": DynatraceResponse(data={}, status_code=200),
            "/platform/document/v1/documents": DynatraceResponse(data={}, status_code=200),
            "/platform/automation/v1/workflows": DynatraceResponse(
                data=None, status_code=404, error="Not Found"
            ),
        })
        checks = {ch.api: ch for ch in c.preflight_gen3()}
        auto = checks["automation_api"]
        assert auto.reachable is False
        assert auto.status_code == 404
        assert "--legacy" in " ".join(auto.remediation)

    def test_network_failure_status_code_zero(self):
        """Status 0 (DNS/TLS/network) produces a distinct diagnosis."""
        c = self._client_with_responses({
            "/api/v2/settings/schemas": DynatraceResponse(
                data=None, status_code=0, error="Connection refused"
            ),
            "/platform/document/v1/documents": DynatraceResponse(data={}, status_code=200),
            "/platform/automation/v1/workflows": DynatraceResponse(data={}, status_code=200),
        })
        checks = {ch.api: ch for ch in c.preflight_gen3()}
        sv = checks["settings_v2"]
        assert sv.reachable is False
        assert sv.status_code == 0
        assert "network" in sv.diagnosis.lower() or "DNS" in sv.diagnosis
        # Remediation should point at DYNATRACE_ENVIRONMENT_URL.
        assert any("DYNATRACE_ENVIRONMENT_URL" in s for s in sv.remediation)

    def test_recommended_scopes_include_write(self):
        """Recommended scopes must include the write variants even when the
        minimum (read-only) probe succeeds."""
        c = self._client_with_responses({
            "/api/v2/settings/schemas": DynatraceResponse(data={}, status_code=200),
            "/platform/document/v1/documents": DynatraceResponse(data={}, status_code=200),
            "/platform/automation/v1/workflows": DynatraceResponse(data={}, status_code=200),
        })
        checks = {ch.api: ch for ch in c.preflight_gen3()}
        assert "settings:objects:write" in checks["settings_v2"].scopes_recommended
        assert "document:documents:write" in checks["document_api"].scopes_recommended
        assert "automation:workflows:write" in checks["automation_api"].scopes_recommended
        assert "automation:workflows:run" in checks["automation_api"].scopes_recommended


# ---------------------------------------------------------------------------
# Gen3 Platform Token + settings path regressions (lab repro against
# apps.dynatracelabs.com sprint tenant, 2026-04-20)
# ---------------------------------------------------------------------------


GEN3_APPS_ENV = "https://sprint.apps.dynatracelabs.com"


class TestGen3SettingsPathAndBearerAuth:
    """Pin the fix for:

    1. Platform Tokens (dt0s16.* / dt0s01.*) were being sent with
       ``Api-Token`` scheme → tenant returns 401
       "Unsupported authorization scheme 'Api-Token'".
    2. ``/api/v2/settings/schemas`` returns 404 on ``.apps.*`` Gen3
       tenants; the working path is
       ``/platform/classic/environment-api/v2/settings/schemas``.
    """

    def test_settings_v2_base_returns_platform_classic_path_on_apps(self):
        from clients._http import settings_v2_base
        assert settings_v2_base("https://foo.apps.dynatrace.com") == (
            "https://foo.apps.dynatrace.com/platform/classic/environment-api/v2"
        )
        assert settings_v2_base("https://bar.apps.dynatracelabs.com") == (
            "https://bar.apps.dynatracelabs.com/platform/classic/environment-api/v2"
        )

    def test_settings_v2_base_returns_api_v2_on_classic_saas(self):
        from clients._http import settings_v2_base
        assert settings_v2_base("https://foo.live.dynatrace.com") == (
            "https://foo.live.dynatrace.com/api/v2"
        )

    def test_settings_v2_base_returns_api_v2_on_managed(self):
        from clients._http import settings_v2_base
        # Managed tenants don't carry `.apps.` in the hostname.
        assert settings_v2_base("https://dynatrace.customer-managed.example") == (
            "https://dynatrace.customer-managed.example/api/v2"
        )

    def test_settings_v2_base_strips_trailing_slash(self):
        from clients._http import settings_v2_base
        assert settings_v2_base("https://foo.apps.dynatrace.com/").endswith(
            "/platform/classic/environment-api/v2"
        )

    def test_token_auth_header_routes_by_prefix(self):
        from clients._http import token_auth_header
        assert token_auth_header("dt0c01.CLASSIC") == "Api-Token dt0c01.CLASSIC"
        assert token_auth_header("dt0s01.OAUTH_ISSUED") == "Bearer dt0s01.OAUTH_ISSUED"
        assert token_auth_header("dt0s16.PLATFORM_STATIC") == "Bearer dt0s16.PLATFORM_STATIC"

    def test_preflight_hits_platform_classic_path_on_gen3_tenant(self):
        """Preflight against a .apps. tenant must probe
        /platform/classic/environment-api/v2/settings/schemas — NOT the
        Classic /api/v2/settings/schemas path (which 404s there).
        """
        c = DynatraceClient(environment_url=GEN3_APPS_ENV, api_token="dt0s16.PLAT")
        calls: list[str] = []

        def record_get(url, **kwargs):
            calls.append(url)
            return DynatraceResponse(data={}, status_code=200)

        c.transport.get = MagicMock(side_effect=record_get)
        checks = {ch.api: ch for ch in c.preflight_gen3()}

        # settings_v2 endpoint was probed via the Gen3-native path.
        settings_url = next(u for u in calls if "settings/schemas" in u)
        assert "/platform/classic/environment-api/v2/settings/schemas" in settings_url
        assert "/api/v2/settings/schemas" not in settings_url
        assert checks["settings_v2"].reachable is True

    def test_preflight_uses_api_v2_path_on_classic_tenant(self):
        """Classic .live. tenants must continue to probe /api/v2/settings/schemas."""
        c = DynatraceClient(environment_url=ENV, api_token="dt0c01.CLASSIC")
        calls: list[str] = []

        def record_get(url, **kwargs):
            calls.append(url)
            return DynatraceResponse(data={}, status_code=200)

        c.transport.get = MagicMock(side_effect=record_get)
        c.preflight_gen3()

        settings_url = next(u for u in calls if "settings/schemas" in u)
        assert "/api/v2/settings/schemas" in settings_url
        assert "/platform/classic/" not in settings_url

    def test_platform_token_is_sent_as_bearer_on_real_request(self):
        """End-to-end through request(): dt0s16.* api_token must produce a
        Bearer Authorization header, not Api-Token.
        """
        from clients._http import HttpTransport
        t = HttpTransport(api_token="dt0s16.PLAT")
        captured: dict[str, str] = {}

        def fake_request(**kwargs):
            captured.update(kwargs["headers"])
            class R:
                status_code = 200
                content = b"{}"
                def json(self): return {}
            return R()

        t.session.request = fake_request  # type: ignore[assignment]
        t.get("https://foo.apps.dynatrace.com/platform/classic/environment-api/v2/settings/schemas")
        assert captured["Authorization"] == "Bearer dt0s16.PLAT"

    def test_settings_v2_client_base_is_gen3_aware(self):
        """SettingsV2Client.base must reflect the tenant generation so
        list_objects/create_envelope hit the right URL."""
        from clients._http import HttpTransport
        from clients.settings_v2_client import SettingsV2Client

        gen3 = SettingsV2Client(GEN3_APPS_ENV, transport=HttpTransport(api_token="dt0s16.x"))
        classic = SettingsV2Client(ENV, transport=HttpTransport(api_token="dt0c01.x"))

        assert gen3.base.endswith("/platform/classic/environment-api/v2")
        assert classic.base.endswith("/api/v2")


# ---------------------------------------------------------------------------
# Wire-level regressions — inspect what actually goes out on the network.
# PR #20 landed multipart code, but a live Gen3 tenant still returned 415
# because `HttpTransport.__init__` sets `Content-Type: application/json` as a
# session default, and that default wins over `requests`' auto-computed
# multipart boundary. These tests capture outgoing request headers + body
# at the Session.send layer so future regressions show up at unit-test time
# instead of only against a real tenant.
# ---------------------------------------------------------------------------


class TestMultipartContentTypeWire:
    """Capture what HttpTransport actually sends over the wire."""

    def _capture(self, transport, caller):
        """Run `caller(transport)` against a session.send stub; return the
        PreparedRequest captured during the call.
        """
        captured = {}

        def fake_send(req, **kwargs):
            captured["headers"] = dict(req.headers)
            captured["body"] = req.body
            captured["url"] = req.url
            import requests
            r = requests.Response()
            r.status_code = 200
            r._content = b'{"id": "new-doc-id"}'
            return r

        with patch.object(transport.session, "send", side_effect=fake_send):
            caller(transport)
        return captured

    def test_multipart_dashboard_send_uses_multipart_content_type(self):
        """Regression: previously the session-default
        `Content-Type: application/json` leaked onto multipart requests,
        producing a multipart body with a JSON content-type header →
        Gen3 tenants returned 415 Unsupported Media Type.
        """
        transport = HttpTransport(api_token="dt0s16.test")
        client = DocumentClient(ENV, transport)

        captured = self._capture(
            transport, lambda t: client.create_dashboard({"name": "wire-test"})
        )

        content_type = captured["headers"].get("Content-Type", "")
        assert content_type.startswith("multipart/form-data"), (
            f"Outgoing Content-Type must be multipart/form-data; got: "
            f"{content_type!r}. This regressed in PR #20 — session default "
            f"`application/json` was winning over auto-multipart."
        )
        assert "application/json" not in content_type
        # Body must be multipart wire-format (not a bare JSON object).
        body_bytes = captured["body"]
        if isinstance(body_bytes, str):
            body_bytes = body_bytes.encode()
        assert body_bytes.startswith(b"--"), (
            "Body must begin with a multipart boundary marker."
        )
        assert b'name="content"' in body_bytes
        assert b'name="type"' in body_bytes

    def test_json_post_still_sends_application_json(self):
        """Make sure the multipart fix didn't accidentally break regular
        JSON POSTs (Settings 2.0, Automation API, etc.).
        """
        transport = HttpTransport(api_token="dt0s16.test")
        captured = self._capture(
            transport, lambda t: t.post("https://x/api/v2/settings/objects",
                                        {"schemaId": "x", "value": {}})
        )
        assert captured["headers"].get("Content-Type") == "application/json"


class TestAnomalyDetectorWirePayload:
    """Capture outgoing Settings 2.0 POST body and verify it matches the
    current builtin:davis.anomaly-detectors schema shape.

    Would have caught the PR #20 miss on transformers/alert_transformer.py —
    the transformer was still emitting {name, strategy, eventTemplate.title,
    ...} that the tenant rejected with 400.
    """

    def _capture_post(self, transport, url, body):
        import requests
        captured = {}
        def fake_send(req, **kwargs):
            captured["body"] = req.body
            r = requests.Response(); r.status_code = 200
            r._content = b'[{"objectId": "obj-1"}]'
            return r
        with patch.object(transport.session, "send", side_effect=fake_send):
            transport.post(url, body)
        return captured

    def test_alert_transformer_detector_matches_current_schema(self):
        """Round-trip: AlertTransformer → SettingsV2Client.create_envelope →
        captured Session.send body should NOT contain the old
        `strategy`/`eventTemplate.title` keys and SHOULD contain the new
        `analyzer`/`executionSettings` keys.
        """
        import json

        from transformers.alert_transformer import AlertTransformer

        r = AlertTransformer().transform({
            "name": "Golden Signals",
            "id": "pol-1",
            "conditions": [{
                "conditionType": "NRQL",
                "name": "latency",
                "nrql": {"query": "SELECT average(duration) FROM Transaction"},
                "terms": [{"threshold": 500, "priority": "critical",
                           "operator": "ABOVE"}],
            }],
            "notifications": [],
        })
        assert r.success
        # The transformer result carries a list of envelope dicts under
        # `anomaly_detectors`; pick the first.
        envelope = r.anomaly_detectors[0]
        # Ship it through the real SettingsV2Client POST path.
        transport = HttpTransport(api_token="dt0s16.test")
        client = SettingsV2Client(ENV, transport)
        captured = self._capture_post(
            transport, client.base + "/settings/objects", [envelope]
        )
        body = json.loads(captured["body"])
        assert isinstance(body, list) and len(body) == 1
        value = body[0]["value"]
        # Required by current schema.
        for req_field in ("title", "source", "analyzer", "executionSettings"):
            assert req_field in value, (
                f"Required field `{req_field}` missing from outgoing payload: "
                f"{sorted(value)}"
            )
        # Forbidden by current schema.
        for forbidden in ("name", "strategy"):
            assert forbidden not in value, (
                f"Outgoing payload still contains `{forbidden}` — the "
                "v1.0.14 schema validators reject it with 400. This is the "
                "regression that PR #20 missed on alert_transformer.py."
            )
        # source is text, not an object.
        assert isinstance(value["source"], str)
        # eventTemplate has only `properties`.
        assert set(value["eventTemplate"]) == {"properties"}, (
            f"eventTemplate keys must be only {{'properties'}}; got: "
            f"{sorted(value['eventTemplate'])}"
        )
        # analyzer is well-formed.
        assert value["analyzer"]["name"].startswith(
            "dt.statistics.ui.anomaly_detection."
        )
        assert all(
            set(item) == {"key", "value"}
            and isinstance(item["key"], str)
            and isinstance(item["value"], str)
            for item in value["analyzer"]["input"]
        )
