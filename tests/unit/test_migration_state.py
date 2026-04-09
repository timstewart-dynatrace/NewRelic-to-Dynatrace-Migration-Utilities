"""Tests for migration.state — RollbackManifest, EntityIdMap, MigrationCheckpoint, IncrementalState."""

import os
import sys
import json
import tempfile
import shutil
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from migration.state import RollbackManifest, EntityIdMap, MigrationCheckpoint, IncrementalState


class TestRollbackManifest:
    def test_should_add_entry(self):
        manifest = RollbackManifest()
        manifest.add("dashboard", "dt-123", "My Dashboard")
        assert len(manifest.entries) == 1
        assert manifest.entries[0]["entity_type"] == "dashboard"
        assert manifest.entries[0]["dynatrace_id"] == "dt-123"
        assert manifest.entries[0]["name"] == "My Dashboard"

    def test_should_save_and_load(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            manifest = RollbackManifest()
            manifest.add("dashboard", "dt-001", "Dash A")
            manifest.add("alert", "dt-002", "Alert B")
            path = Path(tmp_dir) / "rollback.json"
            manifest.save(path)

            loaded = RollbackManifest.load(path)
            assert len(loaded.entries) == 2
            assert loaded.entries[0]["dynatrace_id"] == "dt-001"
            assert loaded.entries[1]["entity_type"] == "alert"
        finally:
            shutil.rmtree(tmp_dir)

    def test_should_track_timestamp(self):
        manifest = RollbackManifest()
        manifest.add("slo", "dt-999", "SLO Test")
        entry = manifest.entries[0]
        assert "timestamp" in entry
        assert isinstance(entry["timestamp"], str)
        assert len(entry["timestamp"]) > 0

    def test_should_start_empty(self):
        manifest = RollbackManifest()
        assert manifest.entries == []
        assert manifest.get_entries() == []

    def test_should_load_nonexistent_returns_empty(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            bad_path = Path(tmp_dir) / "does_not_exist.json"
            with pytest.raises((FileNotFoundError, OSError)):
                RollbackManifest.load(bad_path)
        finally:
            shutil.rmtree(tmp_dir)

    def test_should_add_multiple_entries(self):
        manifest = RollbackManifest()
        manifest.add("dashboard", "dt-1", "D1")
        manifest.add("alert", "dt-2", "A1")
        manifest.add("slo", "dt-3", "S1")
        entries = manifest.get_entries()
        assert len(entries) == 3
        types = [e["entity_type"] for e in entries]
        assert types == ["dashboard", "alert", "slo"]


class TestEntityIdMap:
    def test_should_register_and_resolve(self):
        id_map = EntityIdMap()
        id_map.register("nr-guid-1", "dt-id-1", "dashboard")
        assert id_map.resolve("nr-guid-1") == "dt-id-1"

    def test_should_return_none_for_unknown(self):
        id_map = EntityIdMap()
        assert id_map.resolve("nonexistent-guid") is None

    def test_should_save_and_load(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            id_map = EntityIdMap()
            id_map.register("nr-1", "dt-1", "dashboard")
            id_map.register("nr-2", "dt-2", "alert")
            path = Path(tmp_dir) / "id_map.json"
            id_map.save(path)

            loaded = EntityIdMap.load(path)
            assert loaded.resolve("nr-1") == "dt-1"
            assert loaded.resolve("nr-2") == "dt-2"
        finally:
            shutil.rmtree(tmp_dir)

    def test_should_overwrite_existing(self):
        id_map = EntityIdMap()
        id_map.register("nr-1", "dt-old", "dashboard")
        id_map.register("nr-1", "dt-new", "dashboard")
        assert id_map.resolve("nr-1") == "dt-new"

    def test_should_start_empty(self):
        id_map = EntityIdMap()
        assert id_map.resolve("anything") is None


class TestMigrationCheckpoint:
    def test_should_mark_complete(self):
        cp = MigrationCheckpoint()
        cp.mark_complete("dashboards", 4)
        assert cp.get_resume_index("dashboards") == 5

    def test_should_return_resume_index(self):
        cp = MigrationCheckpoint()
        cp.mark_complete("alerts", 2)
        assert cp.get_resume_index("alerts") == 3

    def test_should_report_complete_when_all_done(self):
        cp = MigrationCheckpoint()
        cp.mark_complete("dashboards", 9)
        assert cp.is_complete("dashboards", 10) is True
        assert cp.is_complete("dashboards", 11) is False

    def test_should_save_and_load(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            cp = MigrationCheckpoint()
            cp.mark_complete("dashboards", 5)
            cp.mark_complete("alerts", 3)
            path = Path(tmp_dir) / "checkpoint.json"
            cp.save(path)

            loaded = MigrationCheckpoint.load(path)
            assert loaded.get_resume_index("dashboards") == 6
            assert loaded.get_resume_index("alerts") == 4
        finally:
            shutil.rmtree(tmp_dir)

    def test_should_return_zero_for_unknown_component(self):
        cp = MigrationCheckpoint()
        assert cp.get_resume_index("unknown_component") == 0


class TestIncrementalState:
    def test_should_detect_changed_entity(self):
        state = IncrementalState()
        data_v1 = {"name": "Dashboard A", "widgets": [1, 2]}
        data_v2 = {"name": "Dashboard A", "widgets": [1, 2, 3]}
        state.update("nr-1", data_v1)
        assert state.has_changed("nr-1", data_v2) is True

    def test_should_detect_unchanged_entity(self):
        state = IncrementalState()
        data = {"name": "Dashboard A", "widgets": [1, 2]}
        state.update("nr-1", data)
        assert state.has_changed("nr-1", data) is False

    def test_should_update_hash(self):
        state = IncrementalState()
        data_v1 = {"name": "v1"}
        data_v2 = {"name": "v2"}
        state.update("nr-1", data_v1)
        assert state.has_changed("nr-1", data_v2) is True
        state.update("nr-1", data_v2)
        assert state.has_changed("nr-1", data_v2) is False

    def test_should_save_and_load(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            state = IncrementalState()
            data = {"key": "value"}
            state.update("nr-1", data)
            path = Path(tmp_dir) / "incremental.json"
            state.save(path)

            loaded = IncrementalState.load(path)
            assert loaded.has_changed("nr-1", data) is False
            assert loaded.has_changed("nr-1", {"key": "different"}) is True
        finally:
            shutil.rmtree(tmp_dir)

    def test_should_handle_new_entity(self):
        state = IncrementalState()
        data = {"name": "brand new"}
        assert state.has_changed("nr-new", data) is True
