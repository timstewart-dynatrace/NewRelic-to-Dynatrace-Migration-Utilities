import os
import sys
import json
import tempfile
import shutil
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from exporters.monaco import MonacoExporter


@pytest.fixture
def transformed_data():
    return {
        "dashboards": [{"dashboardMetadata": {"name": "Test Dash"}, "tiles": []}],
        "alerting_profiles": [{"name": "Critical"}],
        "metric_events": [{"summary": "High Latency"}],
        "management_zones": [{"name": "Production"}],
        "http_monitors": [{"name": "Health Check"}],
        "slos": [{"name": "Availability"}],
    }


@pytest.fixture
def output_dir():
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d)


class TestMonacoExporter:
    def test_should_create_project_yaml(self, transformed_data, output_dir):
        exporter = MonacoExporter()
        exporter.export(transformed_data, output_dir)

        project_yaml = output_dir / "project.yaml"
        assert project_yaml.exists()
        content = project_yaml.read_text()
        assert "project" in content
        assert "migrated-project" in content

    def test_should_export_dashboards_as_json(self, transformed_data, output_dir):
        exporter = MonacoExporter()
        exporter.export(transformed_data, output_dir)

        dash_dir = output_dir / "dashboards"
        assert dash_dir.exists()
        json_files = list(dash_dir.glob("*.json"))
        assert len(json_files) == 1
        dashboard = json.loads(json_files[0].read_text())
        assert dashboard["dashboardMetadata"]["name"] == "Test Dash"

    def test_should_export_alerting_profiles_as_yaml(self, transformed_data, output_dir):
        exporter = MonacoExporter()
        exporter.export(transformed_data, output_dir)

        profile_dir = output_dir / "alerting_profiles"
        assert profile_dir.exists()
        yaml_files = list(profile_dir.glob("*.yaml"))
        assert len(yaml_files) == 1
        json_files = list(profile_dir.glob("*.json"))
        assert len(json_files) == 1
        entity = json.loads(json_files[0].read_text())
        assert entity["name"] == "Critical"

    def test_should_export_management_zones(self, transformed_data, output_dir):
        exporter = MonacoExporter()
        exporter.export(transformed_data, output_dir)

        mz_dir = output_dir / "management_zones"
        assert mz_dir.exists()
        json_files = list(mz_dir.glob("*.json"))
        assert len(json_files) == 1
        entity = json.loads(json_files[0].read_text())
        assert entity["name"] == "Production"

    def test_should_export_monitors(self, transformed_data, output_dir):
        exporter = MonacoExporter()
        exporter.export(transformed_data, output_dir)

        synth_dir = output_dir / "synthetic-monitors"
        assert synth_dir.exists()
        json_files = list(synth_dir.glob("*.json"))
        assert len(json_files) == 1
        monitor = json.loads(json_files[0].read_text())
        assert monitor["name"] == "Health Check"

    def test_should_handle_empty_data(self, output_dir):
        exporter = MonacoExporter()
        summary = exporter.export({}, output_dir)

        assert summary == {}
        # project.yaml should still be created
        assert (output_dir / "project.yaml").exists()

    def test_should_sanitize_names(self, output_dir):
        data = {
            "management_zones": [{"name": "My Zone!!! @#$"}],
        }
        exporter = MonacoExporter()
        exporter.export(data, output_dir)

        mz_dir = output_dir / "management_zones"
        json_files = list(mz_dir.glob("*.json"))
        assert len(json_files) == 1
        # Name should be sanitized: lowercase, special chars replaced with hyphens
        filename = json_files[0].stem
        assert filename == "my-zone"

    def test_should_return_summary(self, transformed_data, output_dir):
        exporter = MonacoExporter()
        summary = exporter.export(transformed_data, output_dir)

        assert summary["dashboards"] == 1
        assert summary["alerting_profiles"] == 1
        assert summary["management_zones"] == 1
        assert summary["http_monitors"] == 1
        assert summary["slos"] == 1
