"""Tests for the Gen3 Terraform exporter."""

import pytest

from exporters.terraform import TerraformExporter


@pytest.fixture
def exporter():
    return TerraformExporter()


@pytest.fixture
def gen3_data():
    return {
        "dashboards": [
            {"version": 13, "name": "Svc Overview", "tiles": {}, "layouts": {}}
        ],
        "workflows": [
            {
                "title": "Alert Routing",
                "description": "policy migration",
                "trigger": {"event": {"config": {"davis_event": {"detectorIds": ["d1"]}}}},
                "tasks": [{"name": "email"}],
            }
        ],
        "anomaly_detectors": [
            {
                "schemaId": "builtin:davis.anomaly-detectors",
                "scope": "environment",
                "detectorId": "d1",
                "value": {"name": "svc-latency", "enabled": True},
            }
        ],
        "segments": [
            {
                "schemaId": "builtin:segment",
                "scope": "environment",
                "value": {
                    "name": "Production",
                    "description": "prod workloads",
                    "includes": {
                        "items": [{"dataObject": "_all_data_object", "filter": {"type": "Group"}}]
                    },
                },
            }
        ],
        "iam_policies": [
            {
                "schemaId": "builtin:iam.policy",
                "scope": "environment",
                "value": {
                    "name": "prod-read",
                    "description": "bucket-scoped",
                    "statementQuery": 'ALLOW storage:logs:read WHERE segment:"Production"',
                },
            }
        ],
        "synthetic_tests": [
            {
                "schemaId": "builtin:synthetic_test",
                "scope": "environment",
                "value": {"name": "api-ping", "type": "HTTP"},
            }
        ],
        "slos": [
            {
                "schemaId": "builtin:monitoring.slo",
                "scope": "environment",
                "value": {
                    "name": "checkout-slo",
                    "enabled": True,
                    "metricExpression": "(100)*(builtin:service.availability)",
                    "evaluationType": "AGGREGATE",
                    "timeframe": "-7d",
                    "filter": "",
                    "target": 99.9,
                    "warning": 99.5,
                },
            }
        ],
        "openpipeline_processors": [
            {
                "schemaId": "builtin:openpipeline.logs.pipelines",
                "scope": "environment",
                "value": {"name": "enrich-env", "enabled": True},
            }
        ],
    }


class TestTerraformGen3Output:
    def test_provider_declares_oauth_and_token_inputs(self, exporter, gen3_data, tmp_path):
        exporter.export(gen3_data, tmp_path)
        provider = (tmp_path / "provider.tf").read_text()
        assert "dynatrace-oss/dynatrace" in provider
        assert "dt_api_token" in provider
        assert "automation_client_id" in provider
        assert "automation_client_secret" in provider

    def test_dashboards_emit_dynatrace_document(self, exporter, gen3_data, tmp_path):
        exporter.export(gen3_data, tmp_path)
        hcl = (tmp_path / "dashboards.tf").read_text()
        assert 'resource "dynatrace_document"' in hcl
        assert 'type    = "dashboard"' in hcl

    def test_workflows_emit_dynatrace_automation_workflow(self, exporter, gen3_data, tmp_path):
        exporter.export(gen3_data, tmp_path)
        hcl = (tmp_path / "workflows.tf").read_text()
        assert 'resource "dynatrace_automation_workflow"' in hcl
        assert "definition" in hcl

    def test_anomaly_detectors_use_generic_setting(self, exporter, gen3_data, tmp_path):
        exporter.export(gen3_data, tmp_path)
        hcl = (tmp_path / "anomaly_detectors.tf").read_text()
        assert 'resource "dynatrace_generic_setting"' in hcl
        assert "builtin:davis.anomaly-detectors" in hcl

    def test_segments_emit_dynatrace_segment(self, exporter, gen3_data, tmp_path):
        exporter.export(gen3_data, tmp_path)
        hcl = (tmp_path / "segments.tf").read_text()
        assert 'resource "dynatrace_segment"' in hcl
        assert 'data_object = "_all_data_object"' in hcl

    def test_iam_policy_emits_statement_query(self, exporter, gen3_data, tmp_path):
        exporter.export(gen3_data, tmp_path)
        hcl = (tmp_path / "iam_policies.tf").read_text()
        assert 'resource "dynatrace_iam_policy"' in hcl
        assert "statement_query" in hcl

    def test_slos_emit_dynatrace_slo_v2(self, exporter, gen3_data, tmp_path):
        exporter.export(gen3_data, tmp_path)
        hcl = (tmp_path / "slos.tf").read_text()
        assert 'resource "dynatrace_slo_v2"' in hcl
        assert "target_success    = 99.9" in hcl

    def test_synthetic_tests_use_generic_setting(self, exporter, gen3_data, tmp_path):
        exporter.export(gen3_data, tmp_path)
        hcl = (tmp_path / "synthetic_tests.tf").read_text()
        assert 'resource "dynatrace_generic_setting"' in hcl
        assert "builtin:synthetic_test" in hcl

    def test_openpipeline_uses_generic_setting(self, exporter, gen3_data, tmp_path):
        exporter.export(gen3_data, tmp_path)
        hcl = (tmp_path / "openpipeline_processors.tf").read_text()
        assert "builtin:openpipeline.logs.pipelines" in hcl

    def test_should_not_emit_gen2_resource_types(self, exporter, gen3_data, tmp_path):
        exporter.export(gen3_data, tmp_path)
        files = list(tmp_path.glob("*.tf"))
        combined = "\n".join(f.read_text() for f in files)
        for forbidden in (
            "dynatrace_alerting",
            "dynatrace_management_zone",
            "dynatrace_autotag",
            "dynatrace_problem_notification",
            "dynatrace_metric_events",
            "dynatrace_http_monitor",
            "dynatrace_browser_monitor",
            "dynatrace_json_dashboard",
        ):
            assert forbidden not in combined

    def test_summary_counts_entities(self, exporter, gen3_data, tmp_path):
        summary = exporter.export(gen3_data, tmp_path)
        for key in gen3_data:
            assert summary.get(key) == len(gen3_data[key])
