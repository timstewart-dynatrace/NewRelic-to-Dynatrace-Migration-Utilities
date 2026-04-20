"""Phase 24 — second-wave nrql-engine parity transformer tests."""

from transformers import (
    CustomEntityTransformer,
    DatabaseMonitoringTransformer,
    LogArchiveTransformer,
    MetricNormalizationTransformer,
    OnHostIntegrationTransformer,
    SavedFilterNotebookTransformer,
    SecuritySignalsTransformer,
    SyntheticSpecializedTransformer,
)

# ---------------------------------------------------------------------------
# DatabaseMonitoringTransformer
# ---------------------------------------------------------------------------


class TestDatabaseMonitoring:
    def test_mysql_maps_to_mysql_extension(self):
        r = DatabaseMonitoringTransformer().transform({
            "name": "prod-mysql", "dbType": "mysql",
            "host": "db-1", "port": 3306, "username": "monitor",
            "databases": ["app", "billing"],
        })
        assert r.success
        assert r.envelope["schemaId"] == "builtin:dynatrace.extension.db.mysql"
        assert r.envelope["value"]["password"] == "<rotate-after-import>"

    def test_postgres_aliases_map(self):
        for alias in ("postgresql", "postgres"):
            r = DatabaseMonitoringTransformer().transform({
                "name": "pg", "dbType": alias,
            })
            assert r.success
            assert r.envelope["schemaId"] == "builtin:dynatrace.extension.db.postgres"

    def test_mssql_alias(self):
        r = DatabaseMonitoringTransformer().transform({
            "name": "x", "dbType": "sqlserver",
        })
        assert r.envelope["schemaId"] == "builtin:dynatrace.extension.db.mssql"

    def test_unsupported_dbtype_fails(self):
        r = DatabaseMonitoringTransformer().transform({
            "name": "x", "dbType": "mysterydb",
        })
        assert not r.success

    def test_runbook_covers_oneagent_overlap(self):
        r = DatabaseMonitoringTransformer().transform({"name": "x", "dbType": "oracle"})
        assert r.runbook["technology"] == "ORACLE"
        assert "OneAgent automatically captures" in r.runbook["oneagent_note"]


# ---------------------------------------------------------------------------
# OnHostIntegrationTransformer
# ---------------------------------------------------------------------------


class TestOnHostIntegration:
    def test_nginx_maps(self):
        r = OnHostIntegrationTransformer().transform({
            "name": "web-nginx", "integration": "nginx",
            "endpoints": ["http://localhost/status"],
        })
        assert r.success
        assert r.envelope["schemaId"] == "builtin:dynatrace.extension.nginx"

    def test_kafka_maps(self):
        r = OnHostIntegrationTransformer().transform({
            "name": "k", "integration": "kafka",
        })
        assert r.envelope["schemaId"] == "builtin:dynatrace.extension.kafka"

    def test_unknown_integration_fails(self):
        r = OnHostIntegrationTransformer().transform({
            "name": "x", "integration": "homebrew",
        })
        assert not r.success

    def test_runbook_includes_nri_cleanup(self):
        r = OnHostIntegrationTransformer().transform({
            "name": "x", "integration": "apache",
        })
        assert any("nri-apache" in step for step in r.runbook["nr_cleanup"])


# ---------------------------------------------------------------------------
# SecuritySignalsTransformer
# ---------------------------------------------------------------------------


class TestSecuritySignals:
    def test_envelope_severity_mapped(self):
        r = SecuritySignalsTransformer().transform({
            "name": "prod-signals", "minSeverity": "critical",
        })
        assert r.success
        assert r.envelope["value"]["minSeverity"] == "CRITICAL"

    def test_signatures_become_enrichment_processors(self):
        r = SecuritySignalsTransformer().transform({
            "name": "x",
            "signatures": [
                {"id": "SQLI-001", "name": "sqli", "severity": "HIGH",
                 "matcher": 'content contains "select *"'},
            ],
        })
        assert len(r.enrichment_processors) == 1
        assert r.enrichment_processors[0]["schemaId"].startswith("builtin:openpipeline")

    def test_mute_list_carried_through(self):
        r = SecuritySignalsTransformer().transform({
            "name": "x", "muteList": ["SIG-1", "SIG-2"],
        })
        muted = r.envelope["value"]["mutedSignatures"]
        assert {m["signatureId"] for m in muted} == {"SIG-1", "SIG-2"}


# ---------------------------------------------------------------------------
# CustomEntityTransformer
# ---------------------------------------------------------------------------


class TestCustomEntity:
    def test_custom_device_payload(self):
        r = CustomEntityTransformer().transform({
            "guid": "custom-123", "name": "widget-service",
            "type": "WIDGET", "properties": {"vendor": "acme"},
            "tags": [{"key": "env", "value": "prod"}],
        })
        assert r.success
        assert r.custom_device_payload["endpoint"] == "/api/v2/entities/custom"
        assert r.custom_device_payload["body"]["type"] == "WIDGET"
        assert r.custom_device_payload["body"]["customDeviceId"] == "migrated-custom-123"

    def test_missing_guid_warns(self):
        r = CustomEntityTransformer().transform({"name": "no-guid"})
        assert r.success
        assert any("no GUID" in w for w in r.warnings)

    def test_enrichment_matcher_uses_guid_when_present(self):
        r = CustomEntityTransformer().transform({"guid": "g1", "name": "x"})
        assert 'entity.guid == "g1"' in r.enrichment_processor["value"]["processor"]["matcher"]


# ---------------------------------------------------------------------------
# LogArchiveTransformer
# ---------------------------------------------------------------------------


class TestLogArchive:
    def test_bucket_envelope_retention(self):
        r = LogArchiveTransformer().transform({
            "name": "compliance-logs", "retentionDays": 365,
            "complianceTags": ["gdpr", "hipaa"],
        })
        assert r.success
        assert r.bucket_envelope["value"]["retentionDays"] == 365
        assert r.bucket_envelope["value"]["tags"] == ["gdpr", "hipaa"]

    def test_s3_destination_maps(self):
        r = LogArchiveTransformer().transform({
            "name": "x", "destination": "aws_s3",
        })
        assert r.egress_processor["value"]["processor"]["destination"] == "s3"

    def test_unknown_destination_warns(self):
        r = LogArchiveTransformer().transform({
            "name": "x", "destination": "filesystem",
        })
        assert r.egress_processor is None
        assert any("Unknown" in w for w in r.warnings)

    def test_runbook_notes_historical_data_gap(self):
        r = LogArchiveTransformer().transform({"name": "x"})
        assert "cannot be re-ingested into Grail" in r.runbook["non_migratable"]


# ---------------------------------------------------------------------------
# MetricNormalizationTransformer
# ---------------------------------------------------------------------------


class TestMetricNormalization:
    def test_rename_rule(self):
        r = MetricNormalizationTransformer().transform({
            "name": "rename-cpu", "type": "rename",
            "sourceMetric": "oldCpu", "targetMetric": "newCpu",
        })
        assert r.success
        proc = r.processors[0]["value"]["processor"]
        assert proc["type"] == "renameFields"
        assert proc["renames"][0] == {"from": "oldCpu", "to": "newCpu"}

    def test_aggregate_rule(self):
        r = MetricNormalizationTransformer().transform({
            "name": "agg", "type": "aggregate",
            "targetMetric": "svcLatency",
            "expression": "avg(duration)",
        })
        proc = r.processors[0]["value"]["processor"]
        assert proc["type"] == "computeFields"
        assert proc["fields"][0]["expression"] == "avg(duration)"

    def test_drop_rule(self):
        r = MetricNormalizationTransformer().transform({
            "name": "drop-noisy", "type": "drop",
            "matcher": 'metric.name startsWith "debug."',
        })
        assert r.processors[0]["value"]["processor"]["type"] == "drop"

    def test_unknown_rule_type_fails(self):
        r = MetricNormalizationTransformer().transform({
            "name": "x", "type": "merge",
        })
        assert not r.success


# ---------------------------------------------------------------------------
# SyntheticSpecializedTransformer
# ---------------------------------------------------------------------------


class TestSyntheticSpecialized:
    def test_cert_check_emits_expiry_rule(self):
        r = SyntheticSpecializedTransformer().transform({
            "name": "cert-check-prod",
            "monitorType": "CERT_CHECK",
            "monitoredUrl": "https://api.example.com",
            "daysUntilExpiration": 14,
        })
        assert r.success
        rules = r.envelope["value"]["script"]["requests"][0]["validation"]["rules"]
        cert_rule = next(x for x in rules if x["type"] == "certificateExpiryDate")
        assert cert_rule["value"] == "14"

    def test_broken_links_multi_step_http(self):
        r = SyntheticSpecializedTransformer().transform({
            "name": "broken-links",
            "monitorType": "BROKEN_LINKS",
            "discoveredUrls": ["https://a/", "https://b/", "https://c/"],
        })
        assert r.success
        requests = r.envelope["value"]["script"]["requests"]
        assert len(requests) == 3
        assert any("no native broken-links crawler" in w for w in r.warnings)

    def test_broken_links_truncates_over_50(self):
        r = SyntheticSpecializedTransformer().transform({
            "name": "too-many",
            "monitorType": "BROKEN_LINKS",
            "discoveredUrls": [f"https://x/{i}" for i in range(75)],
        })
        assert len(r.envelope["value"]["script"]["requests"]) == 50
        assert any("Truncating" in w for w in r.warnings)

    def test_non_specialized_type_errors(self):
        r = SyntheticSpecializedTransformer().transform({
            "name": "x", "monitorType": "SIMPLE",
        })
        assert not r.success


# ---------------------------------------------------------------------------
# SavedFilterNotebookTransformer
# ---------------------------------------------------------------------------


class TestSavedFilterNotebook:
    def test_markdown_cell_round_trip(self):
        r = SavedFilterNotebookTransformer().transform({
            "name": "runbook",
            "cells": [
                {"type": "markdown", "content": "# Checkout runbook"},
            ],
        })
        assert r.success
        assert r.notebook_content["cells"][0]["type"] == "markdown"

    def test_nrql_cell_becomes_dql_cell(self):
        r = SavedFilterNotebookTransformer().transform({
            "name": "x",
            "cells": [
                {"type": "nrql", "title": "count",
                 "query": "SELECT count(*) FROM Transaction"},
            ],
        })
        cell = r.notebook_content["cells"][0]
        assert cell["type"] == "dql"
        assert cell["query"]  # non-empty — compiler produced something

    def test_default_filters_carried(self):
        r = SavedFilterNotebookTransformer().transform({
            "name": "x",
            "defaultFilters": {"env": "prod", "region": "us-east-1"},
            "cells": [],
        })
        assert r.notebook_content["defaultVariableValues"]["env"] == "prod"

    def test_unknown_cell_type_warns(self):
        r = SavedFilterNotebookTransformer().transform({
            "name": "x",
            "cells": [{"type": "mystery", "content": "foo"}],
        })
        assert any("Unknown cell type" in w for w in r.warnings)
