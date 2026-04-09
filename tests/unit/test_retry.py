"""Tests for migration.retry — FailedEntities."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from migration.retry import FailedEntities


@pytest.fixture
def failed_entities():
    """Create a FailedEntities instance with sample data."""
    fe = FailedEntities()
    fe.add("dashboard", "Web Overview", "API timeout")
    fe.add("dashboard", "Mobile Stats", "403 Forbidden")
    fe.add("management_zone", "Production", "Validation error")
    return fe


class TestFailedEntities:
    def test_should_add_and_retrieve(self, failed_entities):
        assert len(failed_entities.entries) == 3
        assert failed_entities.entries[0]["entity_type"] == "dashboard"
        assert failed_entities.entries[0]["name"] == "Web Overview"
        assert failed_entities.entries[0]["error"] == "API timeout"

    def test_should_save_and_load(self, failed_entities):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "failures.json"
            failed_entities.save(path)

            assert path.exists()
            loaded = FailedEntities.load(path)
            assert len(loaded.entries) == 3
            assert loaded.entries[0]["name"] == "Web Overview"
            assert loaded.entries[2]["entity_type"] == "management_zone"

    def test_should_filter_by_type(self, failed_entities):
        dashboard_names = failed_entities.get_failed_names("dashboard")
        assert dashboard_names == ["Web Overview", "Mobile Stats"]

        mz_names = failed_entities.get_failed_names("management_zone")
        assert mz_names == ["Production"]

        assert failed_entities.get_failed_names("nonexistent") == []

    def test_should_filter_transformed_data(self, failed_entities):
        transformed_data = {
            "dashboard": [
                {"name": "Web Overview", "tiles": []},
                {"name": "Backend Perf", "tiles": []},
                {"name": "Mobile Stats", "tiles": []},
            ]
        }
        result = failed_entities.filter_transformed_data(
            transformed_data, "dashboard", "name"
        )
        assert len(result) == 2
        names = [r["name"] for r in result]
        assert "Web Overview" in names
        assert "Mobile Stats" in names
        assert "Backend Perf" not in names

    def test_should_report_empty(self):
        fe = FailedEntities()
        assert fe.is_empty() is True

        fe.add("dashboard", "Test", "error")
        assert fe.is_empty() is False
