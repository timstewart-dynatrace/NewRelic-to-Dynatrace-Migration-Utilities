"""Tests for Phase 17 modules: non-NRQL alerts, baseline/outlier alerts,
lookup tables, maintenance windows, change tracking, custom event ingest,
identity, log obfuscation, NRDB archive tool."""

import json
from unittest.mock import MagicMock

import pytest

from tools.nrdb_archive import NRDBArchive
from transformers import (
    BaselineAlertTransformer,
    ChangeTrackingTransformer,
    CustomEventIngestTransformer,
    IdentityTransformer,
    LogObfuscationTransformer,
    LookupTableTransformer,
    MaintenanceWindowTransformer,
    NonNRQLAlertTransformer,
)


# ---------------------------------------------------------------------------
# NonNRQLAlertTransformer
# ---------------------------------------------------------------------------


class TestNonNRQLAlert:
    def test_synthetic_condition_maps_to_detector(self):
        r = NonNRQLAlertTransformer().transform({
            "type": "synthetic", "name": "api-ping-down", "enabled": True,
            "terms": [{"priority": "critical", "threshold": 1, "thresholdDuration": 300}],
        })
        assert r.success
        det = r.anomaly_detectors[0]
        assert det["schemaId"] == "builtin:davis.anomaly-detectors"
        assert det["value"]["strategy"]["alertCondition"] == "BELOW"

    def test_browser_condition_flags_manual_review(self):
        r = NonNRQLAlertTransformer().transform({
            "type": "browser", "name": "slow-lcp",
            "terms": [{"threshold": 2500}],
        })
        assert r.success
        assert "BrowserRUMTransformer" in r.anomaly_detectors[0]["value"]["description"]

    def test_multi_location_synthetic_encodes_required_count(self):
        r = NonNRQLAlertTransformer().transform({
            "type": "multi_location_synthetic", "name": "mls",
            "locationsRequired": 2,
            "terms": [{"threshold": 1}],
        })
        assert r.anomaly_detectors[0]["value"]["strategy"]["minLocationsFailing"] == 2
        assert any("Multi-location" in w for w in r.warnings)

    def test_unknown_type_errors_gracefully(self):
        r = NonNRQLAlertTransformer().transform({"type": "unknown", "name": "x"})
        assert not r.success

    def test_workflow_trigger_targets_detector_id(self):
        r = NonNRQLAlertTransformer().transform({
            "type": "infra", "name": "cpu-hi",
            "terms": [{"threshold": 90}],
        })
        det_id = r.anomaly_detectors[0]["detectorId"]
        trigger = r.workflows[0]["trigger"]["event"]["config"]["davis_event"]
        assert trigger["detectorIds"] == [det_id]


# ---------------------------------------------------------------------------
# BaselineAlertTransformer
# ---------------------------------------------------------------------------


class TestBaselineAlert:
    def test_baseline_condition_auto_adaptive_strategy(self):
        r = BaselineAlertTransformer().transform({
            "name": "response-time-baseline",
            "conditionType": "baseline",
            "baselineDirection": "upper_only",
            "deviations": 4.0,
            "nrql": {"query": "SELECT average(duration) FROM Transaction"},
        })
        assert r.success
        strat = r.anomaly_detectors[0]["value"]["strategy"]
        assert strat["type"] == "AUTO_ADAPTIVE_BASELINE"
        assert strat["alertCondition"] == "ABOVE_UPPER_BOUND"
        assert strat["sensitivity"] == 4.0

    def test_outlier_without_facet_warns_and_defaults(self):
        r = BaselineAlertTransformer().transform({
            "name": "svc-outliers", "conditionType": "outlier",
        })
        strat = r.anomaly_detectors[0]["value"]["strategy"]
        assert strat["type"] == "AUTO_ADAPTIVE_OUTLIER"
        assert strat["byDimensions"] == ["dt.entity.service"]
        assert any("no facet" in w for w in r.warnings)

    def test_direction_both_maps_to_outside_bounds(self):
        r = BaselineAlertTransformer().transform({
            "name": "x", "baselineDirection": "both",
        })
        assert r.anomaly_detectors[0]["value"]["strategy"]["alertCondition"] == "OUTSIDE_BOUNDS"


# ---------------------------------------------------------------------------
# LookupTableTransformer
# ---------------------------------------------------------------------------


class TestLookupTable:
    def test_empty_table_warns(self):
        r = LookupTableTransformer().transform({"name": "empty", "rows": []})
        assert r.success
        assert r.resource_store_jsonl == ""
        assert any("empty" in w for w in r.warnings)

    def test_rows_become_jsonl(self):
        r = LookupTableTransformer().transform({
            "name": "vip-users",
            "lookupField": "user_id",
            "rows": [{"user_id": "u1", "tier": "gold"}, {"user_id": "u2", "tier": "silver"}],
            "returnFields": ["tier"],
        })
        lines = r.resource_store_jsonl.splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["user_id"] == "u1"

    def test_dql_fragment_uses_lookup(self):
        r = LookupTableTransformer().transform({
            "name": "vip-users",
            "lookupField": "user_id",
            "sourceField": "user.id",
            "rows": [{"user_id": "u1"}],
            "returnFields": ["tier"],
        })
        assert "| lookup" in r.dql_fragment
        assert "sourceField:user.id" in r.dql_fragment
        assert "lookupField:user_id" in r.dql_fragment

    def test_upload_metadata_filepath_is_slug_safe(self):
        r = LookupTableTransformer().transform({"name": "My Crazy Name!", "rows": []})
        assert "/lookups/migrated-" in r.resource_store_upload_metadata["filePath"]
        assert "!" not in r.resource_store_upload_metadata["filePath"]


# ---------------------------------------------------------------------------
# MaintenanceWindowTransformer
# ---------------------------------------------------------------------------


class TestMaintenanceWindow:
    def test_one_off_window(self):
        r = MaintenanceWindowTransformer().transform({
            "name": "db-upgrade", "kind": "maintenance", "recurrence": "once",
            "startTime": "2026-05-01T02:00:00Z",
            "endTime": "2026-05-01T04:00:00Z",
            "timeZone": "America/New_York",
        })
        assert r.success
        assert r.envelope["schemaId"] == "builtin:deployment.maintenance"
        assert r.envelope["value"]["schedule"]["scheduleType"] == "ONCE"

    def test_weekly_recurrence(self):
        r = MaintenanceWindowTransformer().transform({
            "name": "weekly", "recurrence": "weekly",
            "weeklyPattern": {"daysOfWeek": ["SUNDAY"], "startTime": "02:00"},
        })
        assert r.envelope["value"]["schedule"]["scheduleType"] == "WEEKLY"

    def test_mute_rule_emits_filter_comment(self):
        r = MaintenanceWindowTransformer().transform({
            "name": "mute-prod-deploys",
            "kind": "mute_rule",
            "filterNRQL": "WHERE deployment == 'rolling'",
        })
        assert r.success
        assert r.workflow_filter_expression is not None
        assert "deployment" in r.workflow_filter_expression


# ---------------------------------------------------------------------------
# ChangeTrackingTransformer
# ---------------------------------------------------------------------------


class TestChangeTracking:
    def test_deployment_maps_to_custom_deployment(self):
        r = ChangeTrackingTransformer().transform({
            "category": "deployment",
            "entityGuid": "MXxBUE18QVBQTA",
            "version": "v1.2.3",
            "user": "alice",
            "timestamp": 1700000000000,
        })
        assert r.success
        ev = r.events[0]
        assert ev["eventType"] == "CUSTOM_DEPLOYMENT"
        assert ev["properties"]["nr.version"] == "v1.2.3"
        assert 'tag("nr.entity.guid:MXxBUE18QVBQTA")' == ev["entitySelector"]

    def test_feature_flag_maps_to_custom_configuration(self):
        r = ChangeTrackingTransformer().transform({
            "category": "feature_flag", "version": "flag-X on",
        })
        assert r.events[0]["eventType"] == "CUSTOM_CONFIGURATION"

    def test_unknown_category_warns_defaults_to_info(self):
        r = ChangeTrackingTransformer().transform({"category": "weird"})
        assert r.events[0]["eventType"] == "CUSTOM_INFO"
        assert any("Unknown" in w for w in r.warnings)

    def test_historical_marker_set(self):
        r = ChangeTrackingTransformer().transform({"category": "deployment"})
        assert r.events[0]["properties"]["historical"] == "true"


# ---------------------------------------------------------------------------
# CustomEventIngestTransformer
# ---------------------------------------------------------------------------


class TestCustomEventIngest:
    def test_records_become_bizevents(self):
        r = CustomEventIngestTransformer().transform({
            "eventType": "CheckoutCompleted",
            "records": [
                {"id": "c1", "timestamp": "2026-04-15T00:00:00Z", "amount": 42},
                {"id": "c2", "timestamp": "2026-04-15T00:00:01Z", "amount": 50},
            ],
        })
        assert r.success and len(r.bizevents) == 2
        assert r.bizevents[0]["type"] == "CheckoutCompleted"
        assert r.bizevents[0]["data"]["amount"] == 42
        assert r.bizevents[0]["specversion"] == "1.0"

    def test_dql_source_mapping_present(self):
        r = CustomEventIngestTransformer().transform({
            "eventType": "Foo", "records": [{"x": 1}],
        })
        assert "fetch bizevents" in r.dql_source_mapping
        assert 'event.type == "Foo"' in r.dql_source_mapping

    def test_empty_batch_warns(self):
        r = CustomEventIngestTransformer().transform({"eventType": "Empty", "records": []})
        assert r.success and r.bizevents == []
        assert any("no records" in w.lower() for w in r.warnings)


# ---------------------------------------------------------------------------
# IdentityTransformer
# ---------------------------------------------------------------------------


class TestIdentity:
    def test_user_maps_type(self):
        r = IdentityTransformer().transform({
            "users": [{"email": "alice@ex.com", "name": "Alice", "type": "FULL_USER"}],
        })
        assert r.success and len(r.user_envelopes) == 1
        assert r.user_envelopes[0]["value"]["userType"] == "FULL"

    def test_team_maps_to_group(self):
        r = IdentityTransformer().transform({
            "teams": [{"name": "platform", "memberEmails": ["a@x", "b@x"]}],
        })
        assert r.group_envelopes[0]["schemaId"] == "builtin:iam.groups"
        assert r.group_envelopes[0]["value"]["members"] == ["a@x", "b@x"]

    def test_known_role_maps_to_policy(self):
        r = IdentityTransformer().transform({"roles": [{"name": "read_only"}]})
        assert "storage:logs:read" in r.policy_envelopes[0]["value"]["statementQuery"]

    def test_unknown_role_warns_and_uses_placeholder(self):
        r = IdentityTransformer().transform({"roles": [{"name": "bespoke-weirdness"}]})
        assert any("no direct DT policy" in w for w in r.warnings)

    def test_saml_uses_certificate_reference_not_inline(self):
        r = IdentityTransformer().transform({
            "saml": {"enabled": True, "issuer": "https://idp", "ssoUrl": "https://idp/sso",
                     "signingCertificate": "MIIBIjANBg..."},
        })
        assert r.saml_envelope["value"]["signingCertificateReference"] == "(upload via DT UI)"
        assert any("signing certificate" in w.lower() for w in r.warnings)

    def test_api_keys_show_up_in_runbook_not_envelope(self):
        r = IdentityTransformer().transform({
            "apiKeys": [{"name": "ingest-1", "type": "Ingest"}],
        })
        assert r.user_envelopes == []
        assert r.runbook["api_keys"][0]["name"] == "ingest-1"
        assert any("do not migrate" in w for w in r.warnings)


# ---------------------------------------------------------------------------
# LogObfuscationTransformer
# ---------------------------------------------------------------------------


class TestLogObfuscation:
    def test_email_preset_maps_to_dt_redactor(self):
        r = LogObfuscationTransformer().transform({
            "name": "mask-emails", "preset": "email",
        })
        assert r.success
        proc = r.processors[0]["value"]["processor"]
        assert proc["type"] == "mask"
        assert "EMAIL" in proc["pattern"]

    def test_credit_card_preset(self):
        r = LogObfuscationTransformer().transform({
            "name": "mask-cc", "preset": "credit_card",
        })
        assert "CREDIT_CARD" in r.processors[0]["value"]["processor"]["pattern"]

    def test_unknown_preset_falls_back_to_regex(self):
        r = LogObfuscationTransformer().transform({
            "name": "bespoke", "preset": "bespoke",
            "regex": r"SECRET-\d+", "replacement": "SECRET-***",
        })
        assert r.processors[0]["value"]["processor"]["pattern"] == r"SECRET-\d+"
        assert any("bespoke" in w for w in r.warnings)

    def test_disabled_rule_preserved(self):
        r = LogObfuscationTransformer().transform({
            "name": "x", "preset": "email", "enabled": False,
        })
        assert r.processors[0]["value"]["enabled"] is False


# ---------------------------------------------------------------------------
# NRDBArchive tool
# ---------------------------------------------------------------------------


class TestNRDBArchive:
    def test_archive_writes_one_jsonl_per_type(self, tmp_path):
        calls = {"count": 0}
        def fake_run_query(nrql, cursor):
            calls["count"] += 1
            # first call per type returns 2 records + no cursor
            return {"results": [{"n": 1}, {"n": 2}], "nextCursor": None}
        arch = NRDBArchive(run_query=fake_run_query, account_id="acct-1")
        manifest = arch.archive(
            since="1 hour ago",
            output_dir=str(tmp_path),
            event_types=["Transaction", "PageView"],
        )
        assert set(manifest.per_type_counts) == {"Transaction", "PageView"}
        assert manifest.per_type_counts["Transaction"] == 2
        assert (tmp_path / "Transaction.jsonl").exists()
        assert (tmp_path / "PageView.jsonl").exists()
        assert (tmp_path / "manifest.json").exists()

    def test_archive_paginates(self, tmp_path):
        state = {"calls": 0}
        def fake_run_query(nrql, cursor):
            state["calls"] += 1
            if state["calls"] == 1:
                return {"results": [{"n": 1}], "nextCursor": "c1"}
            return {"results": [{"n": 2}], "nextCursor": None}
        arch = NRDBArchive(run_query=fake_run_query, account_id="acct-1")
        manifest = arch.archive(
            since="1 hour ago",
            output_dir=str(tmp_path),
            event_types=["Transaction"],
        )
        assert state["calls"] == 2
        assert manifest.per_type_counts["Transaction"] == 2

    def test_archive_captures_errors_per_type(self, tmp_path):
        def fake_run_query(nrql, cursor):
            if "Broken" in nrql:
                raise RuntimeError("nerdgraph 500")
            return {"results": [], "nextCursor": None}
        arch = NRDBArchive(run_query=fake_run_query, account_id="acct-1")
        manifest = arch.archive(
            since="1 hour ago",
            output_dir=str(tmp_path),
            event_types=["OK", "Broken"],
        )
        assert "Broken" in manifest.errors
        assert "OK" in manifest.per_type_counts

    def test_archive_resumes_from_cursor(self, tmp_path):
        # Pre-seed a cursor file
        (tmp_path / "Transaction.cursor.json").write_text(json.dumps({"cursor": "resume-xyz"}))
        seen_cursors = []
        def fake_run_query(nrql, cursor):
            seen_cursors.append(cursor)
            return {"results": [], "nextCursor": None}
        arch = NRDBArchive(run_query=fake_run_query, account_id="acct-1")
        arch.archive(since="1h ago", output_dir=str(tmp_path), event_types=["Transaction"])
        assert "resume-xyz" in seen_cursors
