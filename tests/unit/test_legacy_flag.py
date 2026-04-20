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
    """Exercise the structured-diagnostic preflight command.

    The command accepts either the new ``List[PreflightCheck]`` return type
    or the legacy ``Dict[str, bool]`` shape (normalized internally). Both
    paths are covered here.
    """

    ENV = {
        "NEW_RELIC_API_KEY": "NRAK-XX",
        "NEW_RELIC_ACCOUNT_ID": "1",
        "DYNATRACE_API_TOKEN": "dt0s16.X.Y",
        "DYNATRACE_ENVIRONMENT_URL": "https://abc.live.dynatrace.com",
    }

    @staticmethod
    def _ok_check(api, scopes_min, scopes_rec):
        from clients.dynatrace_client import PreflightCheck
        return PreflightCheck(
            api=api,
            endpoint=f"https://abc.live.dynatrace.com/{api}",
            reachable=True,
            status_code=200,
            error=None,
            scopes_min=scopes_min,
            scopes_recommended=scopes_rec,
            diagnosis="OK",
            remediation=[],
        )

    @staticmethod
    def _fail_check(api, status, scopes_min, scopes_rec):
        from clients.dynatrace_client import PreflightCheck
        return PreflightCheck(
            api=api,
            endpoint=f"https://abc.live.dynatrace.com/{api}",
            reachable=False,
            status_code=status,
            error="Forbidden",
            scopes_min=scopes_min,
            scopes_recommended=scopes_rec,
            diagnosis=f"HTTP {status} — missing scope(s): {', '.join(scopes_min)}",
            remediation=[
                "Add scopes in Dynatrace Access Tokens UI.",
                "Re-run: python3 migrate.py preflight",
            ],
        )

    def test_reports_all_green_exit_zero(self):
        runner = CliRunner()
        from clients.dynatrace_client import (
            _AUTOMATION_SCOPES_MIN,
            _AUTOMATION_SCOPES_RECOMMENDED,
            _DOCUMENT_SCOPES_MIN,
            _DOCUMENT_SCOPES_RECOMMENDED,
            _SETTINGS_SCOPES_MIN,
            _SETTINGS_SCOPES_RECOMMENDED,
        )
        checks = [
            self._ok_check("settings_v2", _SETTINGS_SCOPES_MIN, _SETTINGS_SCOPES_RECOMMENDED),
            self._ok_check("document_api", _DOCUMENT_SCOPES_MIN, _DOCUMENT_SCOPES_RECOMMENDED),
            self._ok_check("automation_api", _AUTOMATION_SCOPES_MIN, _AUTOMATION_SCOPES_RECOMMENDED),
        ]
        with patch.object(DynatraceClient, "preflight_gen3", return_value=checks):
            result = runner.invoke(migrate_mod.preflight, [], env=self.ENV)
        assert result.exit_code == 0, result.output
        assert "Gen3 APIs reachable" in result.output
        # Recommended-scope summary always appears.
        assert "Recommended token scopes for a full migrate run" in result.output
        assert "storage:logs:read" in result.output

    def test_reports_missing_api_exit_nonzero_with_diagnostic(self):
        """When an API is not reachable the output must contain:
        the missing scope names, a remediation step, and the legacy-mode tip.
        """
        runner = CliRunner()
        from clients.dynatrace_client import (
            _AUTOMATION_SCOPES_MIN,
            _AUTOMATION_SCOPES_RECOMMENDED,
            _DOCUMENT_SCOPES_MIN,
            _DOCUMENT_SCOPES_RECOMMENDED,
            _SETTINGS_SCOPES_MIN,
            _SETTINGS_SCOPES_RECOMMENDED,
        )
        checks = [
            self._ok_check("settings_v2", _SETTINGS_SCOPES_MIN, _SETTINGS_SCOPES_RECOMMENDED),
            self._fail_check("document_api", 403, _DOCUMENT_SCOPES_MIN, _DOCUMENT_SCOPES_RECOMMENDED),
            self._fail_check("automation_api", 403, _AUTOMATION_SCOPES_MIN, _AUTOMATION_SCOPES_RECOMMENDED),
        ]
        with patch.object(DynatraceClient, "preflight_gen3", return_value=checks):
            result = runner.invoke(migrate_mod.preflight, [], env=self.ENV)
        assert result.exit_code == 1
        assert "--legacy" in result.output
        # Scope names must appear so the operator knows what to add.
        assert "document:documents:read" in result.output
        assert "automation:workflows:read" in result.output
        # Remediation block must appear.
        assert "Remediation" in result.output
        # The 403 diagnosis wording must make clear WHY it failed.
        assert "HTTP 403" in result.output

    def test_accepts_legacy_bool_dict_report_shape(self):
        """Pre-existing callers that patched `preflight_gen3` with a
        `{name: bool}` dict still work — the CLI normalizes that shape.
        """
        runner = CliRunner()
        with patch.object(
            DynatraceClient,
            "preflight_gen3",
            return_value={"settings_v2": True, "document_api": False, "automation_api": False},
        ):
            result = runner.invoke(migrate_mod.preflight, [], env=self.ENV)
        assert result.exit_code == 1
        assert "--legacy" in result.output
        # Normalized entries still surface the scope names.
        assert "document:documents:read" in result.output


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
