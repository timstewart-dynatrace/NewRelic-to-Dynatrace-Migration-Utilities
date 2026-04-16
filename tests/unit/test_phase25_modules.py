"""Phase 25 — Gen3 workarounds for Gen2-only capabilities."""

from unittest.mock import MagicMock

from clients._http import DynatraceResponse, HttpTransport
from clients.document_client import DocumentClient
from clients.dynatrace_client import DynatraceClient
from transformers.alert_transformer import AlertTransformer
from transformers.tag_transformer import TagTransformer
from transformers.workload_transformer import WorkloadTransformer

ENV = "https://abc12345.live.dynatrace.com"


# ---------------------------------------------------------------------------
# Item 5+7: Document tags + private-location lister
# ---------------------------------------------------------------------------


class TestDocumentPutTags:
    def test_put_tags_calls_correct_endpoint(self):
        transport = MagicMock(spec=HttpTransport)
        transport.put.return_value = DynatraceResponse(data={}, status_code=200)
        dc = DocumentClient(ENV, transport)
        dc.put_tags("doc-1", ["migrated", "env:prod"])
        args = transport.put.call_args
        assert "/doc-1/tags" in args.args[0]
        assert args.args[1] == {"tags": ["migrated", "env:prod"]}
        assert args.kwargs["prefer_oauth"] is True


class TestListSyntheticLocations:
    def test_returns_public_and_private(self):
        c = DynatraceClient(environment_url=ENV, api_token="t")
        c.transport.get = MagicMock(side_effect=[
            DynatraceResponse(data={"locations": [{"entityId": "pub1"}]}, status_code=200),
            DynatraceResponse(data={"locations": [{"entityId": "priv1"}]}, status_code=200),
        ])
        locs = c.list_synthetic_locations("ALL")
        assert len(locs) == 2
        assert {l["entityId"] for l in locs} == {"pub1", "priv1"}

    def test_public_only(self):
        c = DynatraceClient(environment_url=ENV, api_token="t")
        c.transport.get = MagicMock(return_value=DynatraceResponse(
            data={"locations": [{"entityId": "pub1"}]}, status_code=200))
        locs = c.list_synthetic_locations("PUBLIC")
        assert len(locs) == 1
        assert c.transport.get.call_count == 1


# ---------------------------------------------------------------------------
# Item 8: Dashboard Document-then-Config-v1 fallback
# ---------------------------------------------------------------------------


class TestDashboardFallback:
    def test_fallback_invoked_on_document_failure(self):
        from unittest.mock import patch
        c = DynatraceClient(environment_url=ENV, api_token="t")
        c.documents.create_dashboard = MagicMock(return_value=MagicMock(
            success=False, error_message="403 Documents disabled"))
        # Patch the lazy import inside the method
        with patch("clients.legacy.LegacyDynatraceV1Client") as MockLegacy:
            mock_legacy = MockLegacy.return_value
            mock_legacy.create_dashboard.return_value = MagicMock(
                success=True, entity_name="dash", dynatrace_id="d-1")
            result = c.create_dashboard({"name": "test"}, fallback_to_config_v1=True)
        assert result.success

    def test_no_fallback_by_default(self):
        c = DynatraceClient(environment_url=ENV, api_token="t")
        c.documents.create_dashboard = MagicMock(return_value=MagicMock(
            success=False, error_message="403", dynatrace_id=None))
        result = c.create_dashboard({"name": "test"})
        assert not result.success

    def test_tags_applied_after_success(self):
        c = DynatraceClient(environment_url=ENV, api_token="t")
        c.documents.create_dashboard = MagicMock(return_value=MagicMock(
            success=True, dynatrace_id="doc-1", entity_name="x"))
        c.documents.put_tags = MagicMock(return_value=DynatraceResponse(data={}, status_code=200))
        c.create_dashboard({"name": "test"}, tags=["migrated", "env:prod"])
        c.documents.put_tags.assert_called_once_with("doc-1", ["migrated", "env:prod"])


# ---------------------------------------------------------------------------
# Item 3: Template-value auto-tagging -> computeFields
# ---------------------------------------------------------------------------


class TestTemplateValueAutoTag:
    def test_literal_value_uses_addfields(self):
        r = TagTransformer().transform({
            "name": "svc", "type": "APM_APPLICATION",
            "tags": [{"key": "env", "values": ["production"]}],
        })
        proc = r.enrichment_processors[0]["value"]["processor"]
        assert proc["type"] == "addFields"
        assert proc["fields"][0]["value"] == "production"

    def test_single_tag_ref_uses_computefields(self):
        r = TagTransformer().transform({
            "name": "svc", "type": "APM_APPLICATION",
            "tags": [{"key": "environment", "values": ["{TAG:env}"]}],
        })
        proc = r.enrichment_processors[0]["value"]["processor"]
        assert proc["type"] == "computeFields"
        assert proc["fields"][0]["expression"] == "tags.env"

    def test_multi_tag_ref_emits_concat_expression(self):
        r = TagTransformer().transform({
            "name": "svc", "type": "APM_APPLICATION",
            "tags": [{"key": "full_env", "values": ["{TAG:env}-{TAG:region}"]}],
        })
        proc = r.enrichment_processors[0]["value"]["processor"]
        assert proc["type"] == "computeFields"
        expr = proc["fields"][0]["expression"]
        assert "concat(" in expr
        assert "tags.env" in expr
        assert "tags.region" in expr

    def test_mixed_literal_and_ref(self):
        r = TagTransformer().transform({
            "name": "svc", "type": "APM_APPLICATION",
            "tags": [{"key": "label", "values": ["prefix-{TAG:env}-suffix"]}],
        })
        proc = r.enrichment_processors[0]["value"]["processor"]
        assert proc["type"] == "computeFields"
        expr = proc["fields"][0]["expression"]
        assert '"prefix-"' in expr
        assert "tags.env" in expr
        assert '"-suffix"' in expr


# ---------------------------------------------------------------------------
# Item 4: Entity-ID Segment filters
# ---------------------------------------------------------------------------


class TestEntityIDSegment:
    def test_guid_produces_dt_entity_id_statement(self):
        r = WorkloadTransformer().transform({
            "name": "prod",
            "collection": [
                {"type": "HOST", "name": "h1", "guid": "HOST-ABC123"},
            ],
        })
        seg_filter = r.segment["value"]["includes"]["items"][0]["filter"]
        # Flatten the tree to check for dt.entity.id
        flat = str(seg_filter)
        assert "dt.entity.id" in flat
        assert "HOST-ABC123" in flat

    def test_no_guid_produces_entity_name_equality(self):
        r = WorkloadTransformer().transform({
            "name": "prod",
            "collection": [{"type": "HOST", "name": "h1"}],
        })
        flat = str(r.segment["value"]["includes"]["items"][0]["filter"])
        assert "entity.name" in flat
        assert "h1" in flat
        # Should use equality, not contains
        children = r.segment["value"]["includes"]["items"][0]["filter"]["children"]
        name_group = [c for c in children if str(c).count("entity.name") > 0]
        assert name_group  # at least one group referencing entity.name

    def test_mixed_guid_and_name_collection(self):
        r = WorkloadTransformer().transform({
            "name": "mixed",
            "collection": [
                {"type": "HOST", "name": "h1", "guid": "HOST-1"},
                {"type": "HOST", "name": "h2"},  # no guid
            ],
        })
        flat = str(r.segment["value"]["includes"]["items"][0]["filter"])
        assert "dt.entity.id" in flat
        assert "entity.name" in flat


# ---------------------------------------------------------------------------
# Item 1: Per-severity Workflow fanout
# ---------------------------------------------------------------------------


class TestSeverityLadderFanout:
    def test_uniform_delays_emit_single_workflow(self):
        r = AlertTransformer().transform({
            "name": "policy-1", "id": 1,
            "conditions": [],
            "notificationChannels": [],
            "severityRules": [
                {"severityLevel": "AVAILABILITY", "delayInMinutes": 0},
                {"severityLevel": "ERROR", "delayInMinutes": 0},
            ],
        })
        assert r.workflow is not None
        # Single workflow = no fanout warning
        assert not any("severity-ladder fanout" in w for w in r.warnings)

    def test_nonuniform_delays_emit_multiple_workflows(self):
        r = AlertTransformer().transform({
            "name": "multi-sev", "id": 2,
            "conditions": [
                {"conditionType": "NRQL", "name": "c1", "enabled": True,
                 "nrql": {"query": "SELECT count(*) FROM Transaction"},
                 "terms": [{"priority": "critical", "operator": "ABOVE", "threshold": 1}]},
            ],
            "notificationChannels": [],
            "severityRules": [
                {"severityLevel": "AVAILABILITY", "delayInMinutes": 0},
                {"severityLevel": "ERROR", "delayInMinutes": 5},
                {"severityLevel": "PERFORMANCE", "delayInMinutes": 10},
            ],
        })
        assert r.success
        assert any("severity-ladder fanout" in w for w in r.warnings)
        # The primary .workflow is the first severity
        assert "[AVAILABILITY]" in r.workflow["title"]

    def test_fanout_workflow_has_delay_sleep_task(self):
        r = AlertTransformer().transform({
            "name": "delays", "id": 3,
            "conditions": [], "notificationChannels": [],
            "severityRules": [
                {"severityLevel": "AVAILABILITY", "delayInMinutes": 0},
                {"severityLevel": "ERROR", "delayInMinutes": 5},
            ],
        })
        # The ERROR workflow (second in list) should have a delay task
        assert any("severity-ladder fanout" in w for w in r.warnings)

    def test_no_severity_rules_emits_single_workflow(self):
        r = AlertTransformer().transform({
            "name": "simple", "id": 4,
            "conditions": [], "notificationChannels": [],
        })
        assert r.workflow is not None
        assert not any("fanout" in w for w in r.warnings)

    def test_fanout_workflow_severity_filter_in_trigger(self):
        r = AlertTransformer().transform({
            "name": "filter-test", "id": 5,
            "conditions": [], "notificationChannels": [],
            "severityRules": [
                {"severityLevel": "AVAILABILITY", "delayInMinutes": 0},
                {"severityLevel": "ERROR", "delayInMinutes": 3},
            ],
        })
        # The .workflow is the first from the fanout list.
        # It should have an eventProperties severity filter.
        trigger = r.workflow["trigger"]["event"]["config"]["davis_event"]
        assert trigger.get("eventProperties", {}).get("event.severity") == "AVAILABILITY"
