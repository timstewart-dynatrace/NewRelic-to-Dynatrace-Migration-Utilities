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
from transformers._detector_utils import FALLBACK_QUERY, ensure_timeseries

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
            "/platform/slo/v1/slos": DynatraceResponse(data={}, status_code=200),
        })
        checks = c.preflight_gen3()
        assert [ch.api for ch in checks] == [
            "settings_v2", "document_api", "automation_api", "slo_api"
        ]
        slo = checks[-1]
        assert slo.scopes_min == ["slo:slos:read"]
        assert "slo:slos:write" in slo.scopes_recommended
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


class TestAnalyzerInputQueryIsDql:
    """Regression — analyzer.input[{key:"query"}].value must be DQL, not NRQL.

    The live Gen3 tenant server-validates the query value as DQL syntax. PR
    #21 fixed the surrounding schema shape but passed RAW NRQL through into
    analyzer.input, so the tenant rejected 7/7 `[Migrated]` detectors with
    400 "Error parsing parameter 'query'. Invalid DQL query. `FROM` isn't
    allowed here." — NRQL is not DQL.

    These wire-level tests catch any future regression that passes NRQL
    through unchanged.
    """

    _ALLOWED_PREFIXES = ("fetch", "timeseries", "//")
    _FORBIDDEN_TOKENS = ("SELECT", "FROM ")  # NRQL-only keywords

    def _query_value(self, detector):
        value = detector["value"]["analyzer"]["input"]
        return next(item["value"] for item in value if item["key"] == "query")

    def _first_token(self, s):
        return s.lstrip().split()[0] if s and s.strip() else ""

    def test_alert_transformer_emits_dql_for_nrql_source(self):
        from transformers.alert_transformer import AlertTransformer

        nrql = (
            "SELECT average(`newrelic.goldenmetrics.apm.application.throughput`)"
            " FROM Metric FACET entity.guid, appName"
        )
        r = AlertTransformer().transform({
            "name": "Golden Signals",
            "id": "pol-1",
            "conditions": [{
                "conditionType": "NRQL",
                "name": "throughput",
                "nrql": {"query": nrql},
                "terms": [{"threshold": 100, "priority": "critical",
                           "operator": "ABOVE"}],
            }],
            "notifications": [],
        })
        assert r.success
        query = self._query_value(r.anomaly_detectors[0])
        first = self._first_token(query)
        assert first in self._ALLOWED_PREFIXES, (
            f"analyzer.input[query].value must start with one of "
            f"{self._ALLOWED_PREFIXES}; got first token {first!r} in "
            f"{query!r}"
        )
        # The NR-only tokens must not appear as code (they can appear
        # inside a `//` comment — so slice off any leading comment line
        # before asserting).
        code_only = "\n".join(
            line for line in query.splitlines()
            if not line.lstrip().startswith("//")
        )
        for tok in self._FORBIDDEN_TOKENS:
            assert tok not in code_only, (
                f"Forbidden NRQL token {tok!r} leaked into DQL code portion "
                f"of analyzer.input[query].value: {code_only!r}"
            )

    def test_baseline_transformer_emits_dql_for_nrql_source(self):
        from transformers.baseline_alert_transformer import BaselineAlertTransformer

        r = BaselineAlertTransformer().transform({
            "name": "response-time-baseline",
            "conditionType": "baseline",
            "baselineDirection": "upper_only",
            "deviations": 3.0,
            "nrql": {"query": "SELECT average(duration) FROM Transaction"},
        })
        assert r.success
        query = self._query_value(r.anomaly_detectors[0])
        first = self._first_token(query)
        assert first in self._ALLOWED_PREFIXES, (
            f"Baseline detector analyzer.input[query] must start with one of "
            f"{self._ALLOWED_PREFIXES}; got {first!r}"
        )

    def test_empty_nrql_gets_valid_placeholder(self):
        # `analyzer.input[].value` minLength=1 — an empty query breaks
        # server validation. The fallback must always produce something
        # valid.
        from transformers.baseline_alert_transformer import BaselineAlertTransformer

        r = BaselineAlertTransformer().transform({
            "name": "no-nrql", "conditionType": "baseline",
            # no `nrql` key
        })
        assert r.success
        query = self._query_value(r.anomaly_detectors[0])
        assert query.strip(), "Fallback query must be non-empty"
        assert self._first_token(query) in self._ALLOWED_PREFIXES

    def test_unconverted_fallback_preserves_original_nrql_in_comment(self):
        """When the NRQL→DQL conversion can't be done with confidence, the
        operator still needs the original NRQL to fix it by hand. Pin that
        the fallback format carries it through.
        """
        from transformers._detector_utils import _fallback
        out = _fallback(
            "SELECT gibberish(not real nrql) FROM NoSuchEvent SINCE forever"
        )
        assert out.startswith("// UNCONVERTED NRQL:")
        assert "gibberish" in out and "NoSuchEvent" in out
        # Must still end with a valid DQL placeholder so the payload
        # server-validates.
        assert out.endswith(FALLBACK_QUERY)
        assert "timeseries count()" not in out  # D11: count() without metric is invalid


class TestPlatformSloWire:
    """Platform SLO requests as the tenant sees them (`/platform/slo/v1/slos`)."""

    def _run(self, transport, caller, responses):
        import requests

        sent = []

        def fake_send(req, **kwargs):
            sent.append({"method": req.method, "url": req.url,
                         "headers": dict(req.headers), "body": req.body})
            status, content = responses[len(sent) - 1]
            r = requests.Response()
            r.status_code = status
            r._content = content
            return r

        with patch.object(transport.session, "send", side_effect=fake_send):
            result = caller()
        return sent, result

    def _slo(self):
        from transformers.slo_transformer import SLOTransformer

        return SLOTransformer().transform({
            "name": "checkout availability",
            "guid": "MXxTRVJWSUNFX0xFVkVMfDE",
            "objectives": [{"target": 99.5, "timeWindow": {"rolling": {"count": 7, "unit": "DAY"}}}],
            "events": {"validEvents": {"from": "Transaction", "where": "appName = 'checkout'"},
                       "goodEvents": {"from": "Transaction", "where": "appName = 'checkout' AND error IS FALSE"}},
        }).slo

    def test_create_posts_platform_slo_json_with_bearer(self):
        import json

        from clients.slo_client import SloClient

        transport = HttpTransport(api_token="dt0s16.test")
        client = SloClient("https://abc12345.apps.dynatrace.com", transport)
        sent, result = self._run(
            transport, lambda: client.create_slo(self._slo()),
            [(201, b'{"id": "slo-1", "version": "v1"}')],
        )
        req = sent[0]
        assert req["method"] == "POST"
        assert req["url"] == "https://abc12345.apps.dynatrace.com/platform/slo/v1/slos"
        assert req["headers"]["Authorization"] == "Bearer dt0s16.test"
        assert req["headers"]["Content-Type"] == "application/json"
        body = json.loads(req["body"])
        assert "schemaId" not in body and "value" not in body
        assert body["name"] == "[Migrated] checkout availability"
        assert body["criteria"] == [{"target": 99.5, "warning": 99.75,
                                     "timeframeFrom": "now-7d", "timeframeTo": "now"}]
        indicator = body["customSli"]["indicator"]
        assert "by: { dt.smartscape.service }" in indicator
        assert 'contains(entityName, "checkout")' in indicator
        assert "sli=" in indicator and "dt.entity" not in indicator
        assert body["externalId"] == "nr-slo-MXxTRVJWSUNFX0xFVkVMfDE"
        assert result.success and result.dynatrace_id == "slo-1"

    def test_live_host_is_mapped_to_apps_platform_host(self):
        from clients.slo_client import SloClient

        client = SloClient(ENV, HttpTransport(api_token="dt0s16.test"))
        assert client.base.endswith("/platform/slo/v1/slos")
        assert ".live." not in client.base

    def test_delete_looks_up_optimistic_locking_version(self):
        from clients.slo_client import SloClient

        transport = HttpTransport(api_token="dt0s16.test")
        client = SloClient("https://abc12345.apps.dynatrace.com", transport)
        sent, result = self._run(
            transport, lambda: client.delete_slo("slo-1"),
            [(200, b'{"id": "slo-1", "version": "v7"}'), (204, b"")],
        )
        assert [s["method"] for s in sent] == ["GET", "DELETE"]
        assert sent[1]["url"] == (
            "https://abc12345.apps.dynatrace.com/platform/slo/v1/slos/slo-1"
            "?optimistic-locking-version=v7"  # D22: verified against dtctl's live request
        )
        assert result.is_success


class TestDetectorQueryIsTimeseries:
    """D1/D11 (docs/live-validation-2026-09.md): analyzers require timeseries results.
    Each expected output below was accepted by the live StaticThreshold analyzer."""

    def test_summarize_becomes_make_timeseries(self):
        dql = 'fetch spans\n| filter dt.service.name == "x"\n| summarize avg(duration), by: {span.name}'
        assert ensure_timeseries(dql) == (
            'fetch spans\n| filter dt.service.name == "x"\n| makeTimeseries avg(duration), by: {span.name}'
        )

    def test_percentage_arithmetic_is_split_into_series(self):
        dql = "fetch spans\n| summarize (100.0 * countIf(request.is_failed == true) / count())"
        assert ensure_timeseries(dql) == (
            "fetch spans\n| makeTimeseries { nr_agg0 = countIf(request.is_failed == true), nr_agg1 = count() }"
            "\n| fieldsAdd value0 = (100.0 * nr_agg0[] / nr_agg1[])\n| fieldsRemove nr_agg0, nr_agg1"
        )

    def test_comments_and_timeseries_pass_through(self):
        dql = "// Original NRQL: x\ntimeseries avg(dt.host.cpu.usage), by: {host.name}"
        assert ensure_timeseries(dql) == dql

    def test_non_timeseries_shapes_are_rejected(self):
        assert ensure_timeseries("smartscapeNodes K8S_POD | fields name") is None
        assert ensure_timeseries("fetch spans\n| summarize count()\n| fieldsAdd x = 1") is None
        assert ensure_timeseries("fetch spans\n| fields span.name") is None

    def test_detector_query_never_summarize(self):
        from transformers._detector_utils import nrql_to_analyzer_query

        for nrql in ("SELECT count(*) FROM Transaction WHERE appName = 'a'",
                     "SELECT latest(isReady) FROM K8sDeploymentSample", ""):
            code = "\n".join(l for l in nrql_to_analyzer_query(nrql).splitlines() if not l.startswith("//"))
            assert code.startswith(("timeseries", "fetch")) and "summarize" not in code
            assert "makeTimeseries" in code or code.startswith("timeseries")


class TestNonNrqlDetectorQueries:
    """D2/D6 (docs/live-validation-2026-09.md): Grail metric keys, operator + occurrences."""

    @staticmethod
    def _inputs(detector):
        return {i["key"]: i["value"] for i in detector["value"]["analyzer"]["input"]}

    def test_no_classic_builtin_keys_in_any_detector_query(self):
        from transformers.infrastructure_transformer import InfrastructureTransformer
        from transformers.non_nrql_alert_transformer import _CONDITION_METRIC_MAP, NonNRQLAlertTransformer

        detectors = []
        for ctype in _CONDITION_METRIC_MAP:
            detectors += NonNRQLAlertTransformer().transform({"type": ctype, "name": ctype}).anomaly_detectors
        for cond in (
            {"type": "host_not_reporting", "name": "h"},
            {"type": "process_not_running", "name": "p"},
            {"type": "infra_metric", "name": "m", "select_value": "diskUsedPercent"},
            {"type": "infra_metric", "name": "u", "select_value": "someUnknownMetric"},
        ):
            detectors += InfrastructureTransformer().transform(cond).anomaly_detectors
        assert detectors
        for det in detectors:
            code = "\n".join(
                l for l in self._inputs(det)["query"].splitlines() if not l.startswith("//")
            )
            assert "builtin:" not in code, code
            assert code.startswith("timeseries ")

    def test_operator_and_at_least_once_are_honoured(self):
        from transformers.non_nrql_alert_transformer import NonNRQLAlertTransformer

        det = NonNRQLAlertTransformer().transform({
            "type": "synthetic", "name": "ping",
            "terms": [{"priority": "critical", "threshold": 95, "operator": "ABOVE",
                       "thresholdDuration": 600, "thresholdOccurrences": "AT_LEAST_ONCE"}],
        }).anomaly_detectors[0]
        inputs = self._inputs(det)
        assert inputs["alertCondition"] == "ABOVE"  # overrides the synthetic default BELOW
        assert (inputs["violatingSamples"], inputs["slidingWindow"]) == ("1", "10")
        assert inputs["query"] == "timeseries avg(dt.synthetic.http.availability)"

    def test_unsupported_operator_warns(self):
        from transformers.infrastructure_transformer import InfrastructureTransformer

        r = InfrastructureTransformer().transform({
            "type": "infra_metric", "name": "m", "select_value": "cpuPercent", "comparison": "equal",
            "criticalThreshold": {"value": 90, "durationMinutes": 5},
        })
        assert self._inputs(r.anomaly_detectors[0])["alertCondition"] == "ABOVE"
        assert any("not supported" in w for w in r.warnings)


class TestSeverityFanoutWorkflowsKept:
    """D5: per-severity workflows were built but only the first was returned."""

    def test_all_fanout_workflows_returned(self):
        from transformers.alert_transformer import AlertTransformer

        r = AlertTransformer().transform({
            "name": "tiered", "conditions": [],
            "severityRules": [{"severity": "ERROR", "delayMinutes": 0},
                              {"severity": "AVAILABILITY", "delayMinutes": 10}],
        })
        assert r.success
        assert len(r.workflows) == 2
        assert r.workflow is r.workflows[0]

    def test_single_workflow_still_listed(self):
        from transformers.alert_transformer import AlertTransformer

        r = AlertTransformer().transform({"name": "flat", "conditions": []})
        assert len(r.workflows) == 1 and r.workflow is r.workflows[0]


class TestWorkflowTriggerAndEnvelopeShape:
    """D3/D4 (docs/live-validation-2026-09.md): no detectorId in Settings envelopes;
    workflows use the eventTrigger.triggerConfiguration davis-problem shape and
    link to detectors by event-name prefix."""

    @staticmethod
    def _all_outputs():
        from transformers.aiops_transformer import AIOpsTransformer
        from transformers.alert_transformer import AlertTransformer
        from transformers.baseline_alert_transformer import BaselineAlertTransformer
        from transformers.infrastructure_transformer import InfrastructureTransformer
        from transformers.key_transaction_transformer import KeyTransactionTransformer
        from transformers.non_nrql_alert_transformer import NonNRQLAlertTransformer

        detectors, workflows = [], []
        r = AlertTransformer().transform({"name": "Checkout", "conditions": [
            {"name": "High errors", "nrql": {"query": "SELECT count(*) FROM TransactionError"},
             "terms": [{"threshold": 5, "priority": "critical"}]}]})
        detectors += r.anomaly_detectors
        workflows += r.workflows
        r = NonNRQLAlertTransformer().transform({"type": "synthetic", "name": "ping"})
        detectors += r.anomaly_detectors
        workflows += r.workflows
        r = InfrastructureTransformer().transform({"type": "infra_metric", "name": "cpu", "select_value": "cpuPercent"})
        detectors += r.anomaly_detectors
        workflows += r.workflows
        detectors += BaselineAlertTransformer().transform(
            {"name": "b", "conditionType": "baseline", "nrql": {"query": "SELECT count(*) FROM Transaction"}}
        ).anomaly_detectors
        workflows.append(KeyTransactionTransformer().transform({"name": "kt", "applicationName": "svc"}).workflow)
        r = AIOpsTransformer().transform({"workflows": [{"name": "w"}], "anomalySettings": [{"name": "a"}]})
        detectors += getattr(r, "anomaly_detectors", []) or []
        workflows += getattr(r, "workflows", []) or []
        return detectors, workflows

    def test_detector_envelopes_have_only_settings_fields(self):
        detectors, _ = self._all_outputs()
        assert len(detectors) >= 4
        for det in detectors:
            assert set(det) == {"schemaId", "scope", "value"}, set(det)
            name = {p["key"]: p["value"] for p in det["value"]["eventTemplate"]["properties"]}["event.name"]
            assert name.startswith("[Migrated] ") and " | " in name

    def test_workflows_use_davis_problem_event_trigger(self):
        _, workflows = self._all_outputs()
        assert len(workflows) >= 4
        for wf in workflows:
            assert not {"private", "migratedFrom", "detectorIds"} & set(wf)
            config = wf["trigger"]["eventTrigger"]["triggerConfiguration"]
            assert config["type"] == "davis-problem"
            assert set(config["value"]) >= {"categories", "customFilter", "entityTags", "entityTagsMatch"}
            assert isinstance(wf["tasks"], dict)

    def test_alert_workflow_filter_matches_its_detector_event_names(self):
        import re as _re

        from transformers.alert_transformer import AlertTransformer

        r = AlertTransformer().transform({"name": "Prod \"EU\" alerts", "conditions": [
            {"name": "c1", "nrql": {"query": "SELECT count(*) FROM Transaction"}}]})
        custom = r.workflow["trigger"]["eventTrigger"]["triggerConfiguration"]["value"]["customFilter"]
        pattern = _re.match(r'matchesValue\(event\.name, "(.*)"\)$', custom).group(1)
        assert pattern.endswith("*")
        prefix = pattern[:-1].replace('\\"', '"').replace("\\\\", "\\")
        event_name = {p["key"]: p["value"] for p in
                      r.anomaly_detectors[0]["value"]["eventTemplate"]["properties"]}["event.name"]
        assert event_name.startswith(prefix)


class TestDetectorActorWire:
    """D16: builtin:davis.anomaly-detectors rejects a null/missing executionSettings.actor."""

    ACTOR = "12345678-1234-1234-1234-123456789abc"

    @staticmethod
    def _detector():
        from transformers.alert_transformer import AlertTransformer

        return AlertTransformer().transform({"name": "p", "conditions": [
            {"name": "c", "nrql": {"query": "SELECT count(*) FROM Transaction"}}]}).anomaly_detectors[0]

    def test_transformers_emit_no_null_execution_settings(self):
        assert self._detector()["value"]["executionSettings"] == {}

    def test_actor_injected_into_request_body(self):
        import json

        import requests

        client = DynatraceClient(environment_url="https://abc12345.apps.dynatrace.com",
                                 api_token="dt0s16.test", detector_actor=self.ACTOR)
        captured = {}

        def fake_send(req, **kw):
            captured["body"] = json.loads(req.body)
            r = requests.Response()
            r.status_code = 200
            r._content = b'[{"objectId": "obj-1"}]'
            return r

        with patch.object(client.transport.session, "send", side_effect=fake_send):
            result = client.create_anomaly_detector(self._detector())
        assert result.success
        body = captured["body"][0] if isinstance(captured["body"], list) else captured["body"]
        assert body["value"]["executionSettings"] == {"actor": self.ACTOR}

    def test_missing_actor_fails_without_http_call(self):
        client = DynatraceClient(environment_url="https://abc12345.apps.dynatrace.com", api_token="dt0s16.test")
        with patch.object(client.transport.session, "send") as send:
            result = client.create_anomaly_detector(self._detector())
        send.assert_not_called()
        assert not result.success and "DYNATRACE_DETECTOR_ACTOR" in result.error_message

    def test_exporters_parameterise_actor(self, tmp_path):
        from exporters.monaco import MonacoExporter
        from exporters.terraform import TerraformExporter

        data = {"anomaly_detectors": [self._detector()]}
        TerraformExporter().export(data, tmp_path / "tf")
        hcl = (tmp_path / "tf" / "anomaly_detectors.tf").read_text()
        assert '"actor":var.detector_actor' in hcl.replace(" ", "")
        assert 'variable "detector_actor"' in (tmp_path / "tf" / "provider.tf").read_text()

        MonacoExporter().export(data, tmp_path / "mn")
        jsons = list((tmp_path / "mn").rglob("*.json"))
        yamls = list((tmp_path / "mn").rglob("*.yaml"))
        assert any('"{{ .detectorActor }}"' in p.read_text() for p in jsons)
        assert any("DYNATRACE_DETECTOR_ACTOR" in p.read_text() for p in yamls if p.name != "manifest.yaml")


def test_detector_actor_setting_must_be_uuid(monkeypatch):
    from config.settings import DynatraceConfig

    monkeypatch.setenv("DYNATRACE_API_TOKEN", "dt0s16.x")
    monkeypatch.setenv("DYNATRACE_ENVIRONMENT_URL", "https://abc.apps.dynatrace.com")
    monkeypatch.setenv("DYNATRACE_DETECTOR_ACTOR", "not-a-uuid")
    with pytest.raises(Exception):
        DynatraceConfig()
    monkeypatch.setenv("DYNATRACE_DETECTOR_ACTOR", TestDetectorActorWire.ACTOR)
    assert DynatraceConfig().detector_actor == TestDetectorActorWire.ACTOR


class TestDetectorInputsAcceptedBySettingsValidator:
    """D17-D21: inputs rejected by live `dtctl create settings --validate-only`."""

    @staticmethod
    def _inputs(det):
        return {i["key"]: i["value"] for i in det["value"]["analyzer"]["input"]}

    def test_dealerting_never_exceeds_sliding_window(self):
        from transformers.alert_transformer import AlertTransformer
        from transformers.infrastructure_transformer import InfrastructureTransformer
        from transformers.non_nrql_alert_transformer import NonNRQLAlertTransformer

        dets = AlertTransformer().transform({"name": "p", "conditions": [
            {"name": "c", "nrql": {"query": "SELECT count(*) FROM Transaction"},
             "terms": [{"threshold": 1, "thresholdDuration": 120}]}]}).anomaly_detectors
        dets += NonNRQLAlertTransformer().transform({"type": "synthetic", "name": "s"}).anomaly_detectors
        dets += InfrastructureTransformer().transform({"type": "infra_metric", "name": "m", "select_value": "cpuPercent",
                                                       "criticalThreshold": {"value": 1, "durationMinutes": 2}}).anomaly_detectors
        for det in dets:
            inputs = self._inputs(det)
            assert int(inputs["dealertingSamples"]) <= int(inputs["slidingWindow"])

    def test_event_types_are_valid_davis_event_types(self):
        from transformers.infrastructure_transformer import InfrastructureTransformer

        valid = {"AVAILABILITY_EVENT", "CUSTOM_ALERT", "CUSTOM_INFO", "ERROR_EVENT",
                 "PERFORMANCE_EVENT", "RESOURCE_CONTENTION_EVENT"}
        for cond in ({"type": "host_not_reporting", "name": "h"}, {"type": "process_not_running", "name": "p"},
                     {"type": "infra_metric", "name": "m", "select_value": "cpuPercent"}):
            det = InfrastructureTransformer().transform(cond).anomaly_detectors[0]
            props = {p["key"]: p["value"] for p in det["value"]["eventTemplate"]["properties"]}
            assert props["event.type"] in valid

    def test_no_nonexistent_analyzer_parameters(self):
        from transformers.baseline_alert_transformer import BaselineAlertTransformer
        from transformers.non_nrql_alert_transformer import NonNRQLAlertTransformer

        dets = NonNRQLAlertTransformer().transform(
            {"type": "multi_location_synthetic", "name": "m", "locationsRequired": 2}).anomaly_detectors
        dets += BaselineAlertTransformer().transform(
            {"name": "o", "conditionType": "outlier", "learningPeriodDays": 14, "facet": "dt.service.name",
             "nrql": {"query": "SELECT average(duration) FROM Transaction"}}).anomaly_detectors
        for det in dets:
            assert not {"minLocationsFailing", "learningPeriodDays", "dimensions"} & set(self._inputs(det))


class TestDocumentDeleteLockingParamWire:
    """D22: Document API DELETE uses the kebab-case optimistic-locking-version param."""

    def test_document_delete_query_param(self):
        import requests

        transport = HttpTransport(api_token="dt0s16.test")
        client = DocumentClient("https://abc12345.apps.dynatrace.com", transport)
        captured = {}

        def fake_send(req, **kw):
            captured["url"] = req.url
            r = requests.Response()
            r.status_code = 204
            r._content = b""
            return r

        with patch.object(transport.session, "send", side_effect=fake_send):
            client.delete_document("doc-1", optimistic_version="3")
        assert captured["url"].endswith("/platform/document/v1/documents/doc-1?optimistic-locking-version=3")


def test_slo_auditor_update_sends_locking_version():
    from unittest.mock import patch as _patch

    from registry.slo_auditor import SLOAuditor

    auditor = SLOAuditor.__new__(SLOAuditor)
    auditor.platform_url = "https://abc12345.apps.dynatrace.com"
    calls = []

    def fake_request(url, method="GET", data=None):
        calls.append((method, url))
        return {"version": "v9"} if method == "GET" else {}

    with _patch.object(auditor, "_platform_request", side_effect=fake_request):
        assert auditor.update_slo("slo-1", {"name": "x"})
    assert calls[-1] == ("PUT", "https://abc12345.apps.dynatrace.com/platform/slo/v1/slos/slo-1?optimistic-locking-version=v9")


class TestLiveRejectedEnumsAndActions:
    """D23/D24: values rejected by / absent from a live tenant."""

    def test_nrql_alert_condition_is_above_or_below(self):
        from transformers.alert_transformer import AlertTransformer

        for op, expected in (("ABOVE_OR_EQUALS", "ABOVE"), ("BELOW_OR_EQUALS", "BELOW"), ("EQUALS", "ABOVE")):
            r = AlertTransformer().transform({"name": "p", "conditions": [
                {"name": "c", "nrql": {"query": "SELECT count(*) FROM Transaction"},
                 "terms": [{"threshold": 1, "operator": op, "priority": "critical"}]}]})
            inputs = {i["key"]: i["value"] for i in r.anomaly_detectors[0]["value"]["analyzer"]["input"]}
            assert inputs["alertCondition"] == expected
            assert r.warnings

    def test_dql_task_uses_execute_dql_query_action(self):
        from transformers.aiops_transformer import AIOpsTransformer

        r = AIOpsTransformer().transform({"workflows": [
            {"name": "w", "enrichments": [{"name": "e", "nrql": "SELECT count(*) FROM Transaction"}]}]})
        actions = [t["action"] for wf in r.workflows for t in wf["tasks"].values()]
        assert "dynatrace.automations:execute-dql-query" in actions
        assert "dynatrace.automations:dql-query" not in actions
