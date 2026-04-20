"""Phase 20 tests — canary mode, Gen3 rollback completeness, audit tool,
enhanced report."""

import json
from unittest.mock import MagicMock

from click.testing import CliRunner

from clients._http import DynatraceResponse
from clients.dynatrace_client import DynatraceClient
from migration.audit import (
    AuditDrift,
    AuditReport,
    diff_buckets,
    run_audit,
)
from migration.canary import (
    CanaryPlan,
    auto_approve_gate,
    default_approval_gate,
)
from migration.report import ConversionReport

# ---------------------------------------------------------------------------
# CanaryPlan
# ---------------------------------------------------------------------------


class TestCanaryPlan:
    def test_disabled_returns_full_bucket_and_empty_rest(self):
        plan = CanaryPlan()  # no canary_percent
        canary, rest = plan.split([1, 2, 3, 4, 5])
        assert canary == [1, 2, 3, 4, 5] and rest == []

    def test_50_percent_split(self):
        plan = CanaryPlan(canary_percent=50)
        canary, rest = plan.split([1, 2, 3, 4])
        assert canary == [1, 2] and rest == [3, 4]

    def test_min_canary_size_one_when_pct_too_small(self):
        plan = CanaryPlan(canary_percent=1)
        canary, rest = plan.split([1, 2, 3])
        assert canary == [1] and rest == [2, 3]

    def test_pct_above_100_clamps_disabled(self):
        plan = CanaryPlan(canary_percent=150)
        canary, rest = plan.split([1, 2])
        assert canary == [1, 2] and rest == []

    def test_pct_99_still_holds_back_one(self):
        plan = CanaryPlan(canary_percent=99)
        canary, rest = plan.split(list(range(10)))
        assert len(rest) >= 1

    def test_empty_bucket(self):
        plan = CanaryPlan(canary_percent=50)
        assert plan.split([]) == ([], [])

    def test_default_gate_blocks(self):
        assert default_approval_gate("x", 1, 5) is False

    def test_auto_approve_gate_proceeds(self):
        assert auto_approve_gate("x", 1, 5) is True


# ---------------------------------------------------------------------------
# Gen3 delete dispatch (rollback completeness)
# ---------------------------------------------------------------------------


class TestDeleteEntity:
    def _client(self):
        c = DynatraceClient(
            environment_url="https://abc.live.dynatrace.com",
            api_token="t",
        )
        c.settings.delete_object = MagicMock(
            return_value=DynatraceResponse(data=None, status_code=204)
        )
        c.documents.delete_document = MagicMock(
            return_value=DynatraceResponse(data=None, status_code=204)
        )
        c.automation.delete_workflow = MagicMock(
            return_value=DynatraceResponse(data=None, status_code=204)
        )
        return c

    def test_settings_dispatch(self):
        c = self._client()
        for entity_type in (
            "anomaly_detector", "segment", "iam_policy",
            "synthetic_test", "slo", "openpipeline_processor",
        ):
            r = c.delete_entity(entity_type, "abc-123")
            assert r.success, f"delete failed for {entity_type}: {r.error_message}"
            c.settings.delete_object.assert_called_with("abc-123")

    def test_dashboard_dispatch(self):
        c = self._client()
        r = c.delete_entity("dashboard", "doc-1")
        assert r.success
        c.documents.delete_document.assert_called_once_with("doc-1")

    def test_workflow_dispatch(self):
        c = self._client()
        r = c.delete_entity("workflow", "wf-1")
        assert r.success
        c.automation.delete_workflow.assert_called_once_with("wf-1")

    def test_unknown_type_returns_failure(self):
        c = self._client()
        r = c.delete_entity("alerting_profile", "ap-1")
        assert not r.success
        assert "No Gen3 delete handler" in r.error_message
        assert "--legacy" in r.error_message

    def test_exception_captured(self):
        c = self._client()
        c.settings.delete_object = MagicMock(side_effect=RuntimeError("boom"))
        r = c.delete_entity("segment", "seg-1")
        assert not r.success and "boom" in r.error_message


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class TestAuditDiff:
    def test_no_drift_when_baseline_and_live_match(self):
        baseline = {
            "anomaly_detectors": [
                {"value": {"name": "[Migrated] svc-cpu", "enabled": True}},
            ],
        }
        live = {
            "anomaly_detectors": [
                {"objectId": "abc",
                 "value": {"name": "[Migrated] svc-cpu", "enabled": True}},
            ],
        }
        report = diff_buckets(baseline, live)
        assert not report.has_drift()

    def test_deleted_when_baseline_present_live_empty(self):
        baseline = {
            "segments": [{"value": {"name": "[Migrated] prod"}}],
        }
        live = {"segments": []}
        report = diff_buckets(baseline, live)
        assert any(d.kind == "DELETED" for d in report.drifts)

    def test_renamed_detected_via_id_match(self):
        baseline = {
            "segments": [{"objectId": "seg-1", "value": {"name": "old-name"}}],
        }
        live = {
            "segments": [{"objectId": "seg-1", "value": {"name": "new-name"}}],
        }
        report = diff_buckets(baseline, live)
        # Both renamed AND modified (because value differs).
        kinds = [d.kind for d in report.drifts]
        assert "RENAMED" in kinds

    def test_modified_detected_for_payload_diff(self):
        baseline = {
            "anomaly_detectors": [
                {"value": {"name": "x", "enabled": True}},
            ],
        }
        live = {
            "anomaly_detectors": [
                {"objectId": "a", "value": {"name": "x", "enabled": False}},
            ],
        }
        report = diff_buckets(baseline, live)
        assert any(d.kind == "MODIFIED" for d in report.drifts)

    def test_extra_detected_for_unknown_migrated_entity(self):
        baseline = {"workflows": []}
        live = {
            "workflows": [
                {"id": "wf-x", "title": "[Migrated] rogue",
                 "description": "Migrated from NR; created out-of-band"},
            ],
        }
        report = diff_buckets(baseline, live)
        assert any(d.kind == "EXTRA" for d in report.drifts)

    def test_extra_ignored_for_non_migrated_entities(self):
        baseline = {"workflows": []}
        live = {
            "workflows": [
                {"id": "wf-x", "title": "operator-built",
                 "description": "hand-crafted, not from migration"},
            ],
        }
        report = diff_buckets(baseline, live)
        assert not any(d.kind == "EXTRA" for d in report.drifts)

    def test_run_audit_loads_baseline_from_disk(self, tmp_path):
        baseline_path = tmp_path / "baseline.json"
        baseline_path.write_text(json.dumps({
            "segments": [{"value": {"name": "[Migrated] prod"}}],
        }))
        report = run_audit(baseline_path, lambda: {"segments": []})
        assert any(d.kind == "DELETED" for d in report.drifts)

    def test_to_json_groups_by_kind(self):
        report = AuditReport(drifts=[
            AuditDrift("DELETED", "segments", "id1", "n1"),
            AuditDrift("DELETED", "segments", "id2", "n2"),
            AuditDrift("EXTRA", "workflows", "id3", "n3"),
        ])
        body = json.loads(report.to_json())
        assert body["drift_count"] == 3
        assert len(body["by_kind"]["DELETED"]) == 2
        assert len(body["by_kind"]["EXTRA"]) == 1


# ---------------------------------------------------------------------------
# Enhanced ConversionReport
# ---------------------------------------------------------------------------


class TestEnhancedReport:
    def test_warning_codes_aggregated(self):
        r = ConversionReport()
        r.add_query("a", "b", "HIGH", warning_codes=["SECRET_MANUAL"])
        r.add_query("c", "d", "MEDIUM", warning_codes=["SECRET_MANUAL", "CONFIDENCE_MEDIUM"])
        counts = r.warnings_by_code()
        assert counts["SECRET_MANUAL"] == 2
        assert counts["CONFIDENCE_MEDIUM"] == 1

    def test_average_confidence_score(self):
        r = ConversionReport()
        r.add_query("a", "b", "HIGH", confidence_score=90)
        r.add_query("c", "d", "MEDIUM", confidence_score=60)
        assert r.average_confidence_score() == 75.0

    def test_average_confidence_handles_no_scores(self):
        r = ConversionReport()
        r.add_query("a", "b", "HIGH")
        assert r.average_confidence_score() is None

    def test_runbook_url_round_trip(self):
        r = ConversionReport()
        r.add_query("a", "b", "LOW", runbook_url="https://runbooks/x")
        assert r.entries[0]["runbook_url"] == "https://runbooks/x"


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


class TestPhase20CLI:
    def test_audit_cli_no_drift(self, tmp_path, monkeypatch):
        import migrate as migrate_mod
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"segments": []}))

        # Stub get_settings + DynatraceClient so the CLI doesn't require creds.
        class _FakeSettings:
            class dynatrace:
                api_token = "t"
                environment_url = "https://abc.live.dynatrace.com"
        monkeypatch.setattr(migrate_mod, "get_settings", lambda: _FakeSettings())

        class _FakeDT:
            def __init__(self, **_): pass
            def backup_all(self):
                return {"metadata": {}, "segments": []}
        monkeypatch.setattr(migrate_mod, "DynatraceClient", _FakeDT)

        runner = CliRunner()
        result = runner.invoke(
            migrate_mod.audit_cmd, ["--baseline", str(baseline)]
        )
        assert result.exit_code == 0, result.output
        assert "No drift" in result.output

    def test_canary_flags_present_in_help(self):
        import migrate as migrate_mod
        runner = CliRunner()
        result = runner.invoke(migrate_mod.main, ["--help"])
        assert "--canary" in result.output
        assert "--canary-auto-proceed" in result.output
