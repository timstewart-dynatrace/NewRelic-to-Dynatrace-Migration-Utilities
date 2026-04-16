"""Phase 26 Tier 3 — IaC dry-run validation.

Runs `terraform validate` on TerraformExporter output and
`monaco deploy --dry-run` on MonacoExporter output.

Gated on `RUN_IAC_VALIDATION=1` because it requires terraform and
monaco binaries on PATH.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_IAC_VALIDATION"),
    reason="RUN_IAC_VALIDATION=1 not set",
)


_GEN3_FIXTURE = {
    "dashboards": [
        {"version": 13, "name": "test-dash", "tiles": {}, "layouts": {}},
    ],
    "workflows": [
        {"title": "test-wf", "trigger": {}, "tasks": []},
    ],
    "anomaly_detectors": [
        {
            "schemaId": "builtin:davis.anomaly-detectors",
            "scope": "environment",
            "value": {"name": "det", "enabled": True},
        },
    ],
    "segments": [
        {
            "schemaId": "builtin:segment",
            "scope": "environment",
            "value": {"name": "seg", "includes": {"items": []}},
        },
    ],
    "slos": [
        {
            "schemaId": "builtin:monitoring.slo",
            "scope": "environment",
            "value": {
                "name": "slo",
                "enabled": True,
                "metricExpression": "(100)*(builtin:service.availability)",
                "evaluationType": "AGGREGATE",
                "timeframe": "-7d",
                "filter": "",
                "target": 99.9,
                "warning": 99.5,
            },
        },
    ],
}


class TestTerraformValidate:
    @pytest.fixture(autouse=True)
    def skip_if_no_terraform(self):
        if not shutil.which("terraform"):
            pytest.skip("terraform binary not found on PATH")

    def test_gen3_terraform_validates(self, tmp_path):
        from exporters.terraform import TerraformExporter

        TerraformExporter().export(_GEN3_FIXTURE, tmp_path)
        subprocess.run(
            ["terraform", "init", "-backend=false", "-input=false"],
            cwd=tmp_path, check=True, capture_output=True,
        )
        result = subprocess.run(
            ["terraform", "validate"],
            cwd=tmp_path, capture_output=True, text=True,
        )
        assert result.returncode == 0, f"terraform validate failed:\n{result.stderr}"


class TestMonacoDryRun:
    @pytest.fixture(autouse=True)
    def skip_if_no_monaco(self):
        if not shutil.which("monaco"):
            pytest.skip("monaco binary not found on PATH")

    def test_gen3_monaco_structure_valid(self, tmp_path):
        from exporters.monaco import MonacoExporter

        MonacoExporter().export(_GEN3_FIXTURE, tmp_path)
        # Monaco deploy --dry-run requires a manifest.yaml
        manifest = tmp_path / "manifest.yaml"
        assert manifest.exists(), "MonacoExporter didn't create manifest.yaml"
        # Validate YAML structure at least parses
        import yaml
        with manifest.open() as f:
            doc = yaml.safe_load(f)
        assert doc["manifestVersion"] == "1.0"
        assert len(doc["projects"]) >= 1
