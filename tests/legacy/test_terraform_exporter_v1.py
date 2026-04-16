import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from exporters.legacy.terraform_v1 import TerraformExporter


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


class TestTerraformExporter:
    def test_should_create_provider_tf(self, transformed_data, output_dir):
        exporter = TerraformExporter()
        exporter.export(transformed_data, output_dir)

        provider_tf = output_dir / "provider.tf"
        assert provider_tf.exists()
        content = provider_tf.read_text()
        assert "dynatrace-oss/dynatrace" in content
        assert "provider" in content
        assert "dt_env_url" in content
        assert "dt_api_token" in content

    def test_should_export_dashboards(self, transformed_data, output_dir):
        exporter = TerraformExporter()
        exporter.export(transformed_data, output_dir)

        dashboards_tf = output_dir / "dashboards.tf"
        assert dashboards_tf.exists()
        content = dashboards_tf.read_text()
        assert "dynatrace_json_dashboard" in content
        assert "migrated_" in content

    def test_should_export_alerting_profiles(self, transformed_data, output_dir):
        exporter = TerraformExporter()
        exporter.export(transformed_data, output_dir)

        alerting_tf = output_dir / "alerting_profiles.tf"
        assert alerting_tf.exists()
        content = alerting_tf.read_text()
        assert "dynatrace_alerting_profile" in content
        assert "Critical" in content

    def test_should_export_monitors(self, transformed_data, output_dir):
        exporter = TerraformExporter()
        exporter.export(transformed_data, output_dir)

        monitors_tf = output_dir / "http_monitors.tf"
        assert monitors_tf.exists()
        content = monitors_tf.read_text()
        assert "dynatrace_http_monitor" in content
        assert "Health Check" in content

    def test_should_handle_empty_data(self, output_dir):
        exporter = TerraformExporter()
        summary = exporter.export({}, output_dir)

        assert summary == {}
        # provider.tf should still be created
        assert (output_dir / "provider.tf").exists()

    def test_should_sanitize_resource_names(self, output_dir):
        data = {
            "management_zones": [{"name": "My Zone!!! @#$"}],
        }
        exporter = TerraformExporter()
        exporter.export(data, output_dir)

        mz_tf = output_dir / "management_zones.tf"
        content = mz_tf.read_text()
        # Terraform resource names use underscores, not hyphens
        assert "migrated_my_zone" in content

    def test_should_return_summary(self, transformed_data, output_dir):
        exporter = TerraformExporter()
        summary = exporter.export(transformed_data, output_dir)

        assert summary["dashboards"] == 1
        assert summary["alerting_profiles"] == 1
        assert summary["management_zones"] == 1
        assert summary["http_monitors"] == 1
        assert summary["slos"] == 1
