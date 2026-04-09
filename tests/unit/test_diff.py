"""Tests for migration.diff — DiffReport and DiffEntry."""

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from migration.diff import DiffReport, DiffEntry


@pytest.fixture
def mock_registry():
    """Create a mock registry with configurable lookups."""
    registry = MagicMock()
    registry.dashboard_exists.return_value = None
    registry.find_management_zone.return_value = None
    return registry


class TestDiffReport:
    def test_should_add_entry(self):
        report = DiffReport()
        report.add("dashboard", "Web Overview", "CREATE", "Not found in DT")
        assert len(report.entries) == 1
        entry = report.entries[0]
        assert entry.entity_type == "dashboard"
        assert entry.name == "Web Overview"
        assert entry.action == "CREATE"
        assert entry.reason == "Not found in DT"
        assert entry.dt_id is None

    def test_should_compute_summary(self):
        report = DiffReport()
        report.add("dashboard", "Dash A", "CREATE", "Not found in DT")
        report.add("dashboard", "Dash B", "CREATE", "Not found in DT")
        report.add("dashboard", "Dash C", "UPDATE", "Name match found", dt_id="dt-1")
        report.add("management_zone", "MZ A", "CONFLICT", "Multiple matches")

        summary = report.summary()
        assert summary == {"creates": 2, "updates": 1, "conflicts": 1}

    def test_should_identify_creates(self, mock_registry):
        transformed = {
            "dashboards": [
                {"name": "New Dashboard"},
                {"name": "Another New"},
            ],
        }
        report = DiffReport.generate_diff(transformed, mock_registry)

        creates = report.get_creates()
        assert len(creates) == 2
        assert all(e.action == "CREATE" for e in creates)
        assert creates[0].name == "New Dashboard"

    def test_should_identify_updates(self, mock_registry):
        mock_registry.dashboard_exists.side_effect = (
            lambda name: "dt-abc" if name == "Existing Dash" else None
        )
        transformed = {
            "dashboards": [
                {"name": "Existing Dash"},
                {"name": "Brand New Dash"},
            ],
        }
        report = DiffReport.generate_diff(transformed, mock_registry)

        updates = report.get_updates()
        assert len(updates) == 1
        assert updates[0].name == "Existing Dash"
        assert updates[0].dt_id == "dt-abc"

        creates = report.get_creates()
        assert len(creates) == 1
        assert creates[0].name == "Brand New Dash"

    def test_should_handle_empty_data(self, mock_registry):
        report = DiffReport.generate_diff({}, mock_registry)
        assert len(report.entries) == 0
        assert report.summary() == {"creates": 0, "updates": 0, "conflicts": 0}
        assert report.get_creates() == []
        assert report.get_updates() == []
