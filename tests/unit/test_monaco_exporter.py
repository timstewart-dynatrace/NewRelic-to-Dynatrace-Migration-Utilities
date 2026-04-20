"""Tests for the Gen3 Monaco exporter."""


import pytest
import yaml

from exporters.monaco import MonacoExporter


@pytest.fixture
def exporter():
    return MonacoExporter()


@pytest.fixture
def gen3_data():
    return {
        "dashboards": [
            {"version": 13, "name": "Service Overview", "tiles": {}, "layouts": {}}
        ],
        "workflows": [
            {
                "title": "Alert Routing",
                "trigger": {"event": {"config": {"davis_event": {"detectorIds": ["d1"]}}}},
                "tasks": [{"name": "email", "action": "dynatrace.email:email-action"}],
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
                "value": {"name": "Production"},
            }
        ],
        "iam_policies": [
            {
                "schemaId": "builtin:iam.policy",
                "scope": "environment",
                "value": {
                    "name": "prod-read",
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
                "value": {"name": "checkout-slo", "target": 99.9},
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


class TestMonacoGen3Structure:
    def test_should_emit_manifest_yaml_not_project_yaml(self, exporter, gen3_data, tmp_path):
        exporter.export(gen3_data, tmp_path)
        assert (tmp_path / "manifest.yaml").is_file()
        assert not (tmp_path / "project.yaml").is_file()

    def test_manifest_should_declare_oauth_and_token_auth(self, exporter, gen3_data, tmp_path):
        exporter.export(gen3_data, tmp_path)
        manifest = yaml.safe_load((tmp_path / "manifest.yaml").read_text())
        auth = manifest["environmentGroups"][0]["environments"][0]["auth"]
        assert "token" in auth
        assert "oAuth" in auth

    def test_should_place_settings_under_schema_dir(self, exporter, gen3_data, tmp_path):
        exporter.export(gen3_data, tmp_path)
        project = tmp_path / "migrated"
        # builtin:davis.anomaly-detectors slugified
        schema_dir = project / "settings" / "builtin-davis-anomaly-detectors"
        assert schema_dir.is_dir()
        assert (schema_dir / "svc-latency.yaml").is_file()
        assert (schema_dir / "svc-latency.json").is_file()

    def test_should_place_dashboards_under_documents_dir(self, exporter, gen3_data, tmp_path):
        exporter.export(gen3_data, tmp_path)
        docs = tmp_path / "migrated" / "documents"
        assert (docs / "service-overview.json").is_file()
        yaml_config = yaml.safe_load((docs / "service-overview.yaml").read_text())
        assert yaml_config["configs"][0]["type"]["document"]["kind"] == "dashboard"

    def test_should_place_workflows_under_workflows_dir(self, exporter, gen3_data, tmp_path):
        exporter.export(gen3_data, tmp_path)
        wf_dir = tmp_path / "migrated" / "workflows"
        assert (wf_dir / "alert-routing.json").is_file()
        yaml_config = yaml.safe_load((wf_dir / "alert-routing.yaml").read_text())
        assert yaml_config["configs"][0]["type"]["automation"]["resource"] == "workflow"

    def test_summary_counts_all_gen3_entity_types(self, exporter, gen3_data, tmp_path):
        summary = exporter.export(gen3_data, tmp_path)
        for key in (
            "dashboards",
            "workflows",
            "anomaly_detectors",
            "segments",
            "iam_policies",
            "synthetic_tests",
            "slos",
            "openpipeline_processors",
        ):
            assert summary.get(key) == 1

    def test_should_not_emit_gen2_dirs(self, exporter, gen3_data, tmp_path):
        exporter.export(gen3_data, tmp_path)
        project = tmp_path / "migrated"
        for forbidden in (
            "alerting_profiles",
            "metric_events",
            "management_zones",
            "auto_tags",
            "synthetic-monitors",
        ):
            assert not (project / forbidden).exists()
            assert not (project / "settings" / f"builtin-{forbidden}").exists()

    def test_should_handle_empty_input(self, exporter, tmp_path):
        summary = exporter.export({}, tmp_path)
        assert summary == {}
        assert (tmp_path / "manifest.yaml").is_file()
