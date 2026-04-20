"""Tests for the Phase-14 `--legacy` flag + `preflight` subcommand."""

from unittest.mock import patch

from click.testing import CliRunner

import migrate as migrate_mod
from clients.dynatrace_client import DynatraceClient
from transformers.legacy import LegacyAlertTransformer


class TestLegacyModeOrchestrator:
    def test_legacy_mode_picks_legacy_transformers(self):
        orch = migrate_mod.MigrationOrchestrator(legacy_mode=True)
        assert isinstance(orch.alert_transformer, LegacyAlertTransformer)

    def test_default_mode_picks_gen3_transformers(self):
        orch = migrate_mod.MigrationOrchestrator(legacy_mode=False)
        # Gen3 AlertTransformer exposes `workflow` in its result; legacy does not.
        from transformers.alert_transformer import AlertTransformer
        assert isinstance(orch.alert_transformer, AlertTransformer)

    def test_legacy_transform_emits_legacy_field_names(self):
        orch = migrate_mod.MigrationOrchestrator(
            legacy_mode=True, output_dir="/tmp/_legacy-test-out"
        )
        export = {
            "alert_policies": [
                {
                    "name": "svc",
                    "id": 1,
                    "conditions": [
                        {
                            "conditionType": "NRQL",
                            "name": "p95",
                            "enabled": True,
                            "nrql": {"query": "SELECT count(*) FROM Transaction"},
                            "terms": [
                                {"priority": "critical", "operator": "ABOVE",
                                 "threshold": 1.0, "thresholdDuration": 300}
                            ],
                        }
                    ],
                }
            ]
        }
        transformed = orch._transform_phase(export, ["alerts"])
        # Legacy result shape — Alerting Profile + Metric Event (not Workflow).
        assert "alerting_profiles" in transformed
        assert "metric_events" in transformed
        assert "workflows" not in transformed


class TestPreflightCommand:
    def test_reports_all_green_exit_zero(self):
        runner = CliRunner()
        env = {
            "NEW_RELIC_API_KEY": "NRAK-XX",
            "NEW_RELIC_ACCOUNT_ID": "1",
            "DYNATRACE_API_TOKEN": "dt0c01.X",
            "DYNATRACE_ENVIRONMENT_URL": "https://abc.live.dynatrace.com",
        }
        with patch.object(
            DynatraceClient, "preflight_gen3",
            return_value={"settings_v2": True, "document_api": True, "automation_api": True},
        ):
            result = runner.invoke(migrate_mod.preflight, [], env=env)
        assert result.exit_code == 0, result.output
        assert "Gen3 APIs reachable" in result.output

    def test_reports_missing_api_exit_nonzero(self):
        runner = CliRunner()
        env = {
            "NEW_RELIC_API_KEY": "NRAK-XX",
            "NEW_RELIC_ACCOUNT_ID": "1",
            "DYNATRACE_API_TOKEN": "dt0c01.X",
            "DYNATRACE_ENVIRONMENT_URL": "https://abc.live.dynatrace.com",
        }
        with patch.object(
            DynatraceClient, "preflight_gen3",
            return_value={"settings_v2": True, "document_api": False, "automation_api": False},
        ):
            result = runner.invoke(migrate_mod.preflight, [], env=env)
        assert result.exit_code == 1
        assert "--legacy" in result.output


class TestLegacyExporterRouting:
    def test_export_monaco_legacy_uses_legacy_exporter(self, tmp_path):
        runner = CliRunner()
        # Write a Gen2-shaped transformed payload.
        transformed = tmp_path / "transformed"
        transformed.mkdir()
        (transformed / "dynatrace_config_legacy.json").write_text(
            '{"dashboards": [], "alerting_profiles": [], "metric_events": []}'
        )
        result = runner.invoke(
            migrate_mod.export_monaco,
            ["--input", str(tmp_path), "--output", str(tmp_path / "monaco"), "--legacy"],
        )
        assert result.exit_code == 0, result.output
        # Legacy Monaco emits `project.yaml` (Gen2) not `manifest.yaml` (Gen3).
        assert (tmp_path / "monaco" / "project.yaml").exists()
        assert not (tmp_path / "monaco" / "manifest.yaml").exists()

    def test_export_terraform_legacy_emits_gen2_resources(self, tmp_path):
        runner = CliRunner()
        transformed = tmp_path / "transformed"
        transformed.mkdir()
        (transformed / "dynatrace_config_legacy.json").write_text(
            '{"alerting_profiles": [{"name": "p"}]}'
        )
        result = runner.invoke(
            migrate_mod.export_terraform,
            ["--input", str(tmp_path), "--output", str(tmp_path / "tf"), "--legacy"],
        )
        assert result.exit_code == 0, result.output
        tf = (tmp_path / "tf" / "alerting_profiles.tf").read_text()
        assert "dynatrace_alerting_profile" in tf
