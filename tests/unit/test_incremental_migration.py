"""Tests for incremental migration and resume from checkpoint."""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from migration.state import IncrementalState, MigrationCheckpoint


class TestIncrementalMigration:
    """Tests for the --incremental flag wiring in MigrationOrchestrator."""

    def _make_orchestrator(self, inc_state=None, checkpoint=None):
        """Create a MigrationOrchestrator with mocked clients."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from migrate import MigrationOrchestrator
            orch = MigrationOrchestrator(
                newrelic_client=MagicMock(),
                dynatrace_client=MagicMock(),
                output_dir=tmpdir,
                dry_run=False,
                incremental_state=inc_state,
                checkpoint=checkpoint,
            )
            yield orch

    def test_should_skip_unchanged_entity(self):
        """Second incremental run on same data should skip all entities."""
        inc_state = IncrementalState()
        dashboard = {"guid": "dash-1", "name": "Test Dashboard", "pages": []}

        # First run: entity is new, should be changed
        assert inc_state.has_changed("dash-1", dashboard) is True
        inc_state.update("dash-1", dashboard)

        # Second run: entity unchanged, should not be changed
        assert inc_state.has_changed("dash-1", dashboard) is False

    def test_should_process_changed_entity(self):
        """Modified entity between runs should be re-processed."""
        inc_state = IncrementalState()
        dashboard_v1 = {"guid": "dash-1", "name": "Dashboard v1", "pages": []}
        dashboard_v2 = {"guid": "dash-1", "name": "Dashboard v2", "pages": [{"widgets": []}]}

        inc_state.update("dash-1", dashboard_v1)
        assert inc_state.has_changed("dash-1", dashboard_v2) is True

    def test_should_process_all_without_incremental(self):
        """Without --incremental, orchestrator should not skip any entities."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from migrate import MigrationOrchestrator
            orch = MigrationOrchestrator(
                output_dir=tmpdir,
                incremental_state=None,
            )
            # _is_entity_changed should always return True without inc_state
            assert orch._is_entity_changed({"guid": "x"}, "dashboard", 0) is True

    def test_should_use_fallback_id_without_guid(self):
        """Entity without guid should use type-index as fallback ID."""
        inc_state = IncrementalState()
        entity = {"name": "No GUID Entity"}  # no guid or id field

        with tempfile.TemporaryDirectory() as tmpdir:
            from migrate import MigrationOrchestrator
            orch = MigrationOrchestrator(
                output_dir=tmpdir,
                incremental_state=inc_state,
            )
            # Should not raise, should use fallback "dashboard-0"
            assert orch._is_entity_changed(entity, "dashboard", 0) is True
            orch._update_entity_hash(entity, "dashboard", 0)
            assert orch._is_entity_changed(entity, "dashboard", 0) is False

    def test_incremental_state_persists_across_runs(self):
        """State saved to file should correctly skip on reload."""
        inc_state = IncrementalState()
        entity = {"guid": "persist-1", "name": "Persistent"}
        inc_state.update("persist-1", entity)

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            inc_state.save(state_file)

            loaded = IncrementalState.load(state_file)
            assert loaded.has_changed("persist-1", entity) is False
            assert loaded.has_changed("persist-1", {"guid": "persist-1", "name": "Modified"}) is True

    def test_transform_phase_skips_unchanged_dashboards(self):
        """_transform_phase should skip unchanged dashboards and track skips."""
        inc_state = IncrementalState()
        dashboard = {"guid": "d1", "name": "Dashboard 1", "pages": [{"widgets": []}]}

        # Pre-populate state so dashboard appears unchanged
        inc_state.update("d1", dashboard)

        with tempfile.TemporaryDirectory() as tmpdir:
            from migrate import MigrationOrchestrator
            orch = MigrationOrchestrator(
                output_dir=tmpdir,
                incremental_state=inc_state,
            )
            export_data = {"dashboards": [dashboard]}
            result = orch._transform_phase(export_data, ["dashboards"])
            assert len(result["dashboards"]) == 0
            assert len(result["skipped"]) == 1
            assert result["skipped"][0]["type"] == "dashboard"
            assert result["skipped"][0]["reason"] == "unchanged"


class TestResumeMigration:
    """Tests for the --resume flag wiring in MigrationOrchestrator."""

    def test_should_skip_completed_component_index(self):
        """Checkpoint marking index 2 should cause resume from index 3."""
        checkpoint = MigrationCheckpoint()
        checkpoint.mark_complete("dashboards", 2)
        assert checkpoint.get_resume_index("dashboards") == 3

    def test_should_resume_from_zero_if_not_started(self):
        """Component not in checkpoint should resume from index 0."""
        checkpoint = MigrationCheckpoint()
        assert checkpoint.get_resume_index("dashboards") == 0

    def test_should_detect_complete_component(self):
        """Component with all items processed should be complete."""
        checkpoint = MigrationCheckpoint()
        checkpoint.mark_complete("dashboards", 4)  # 0-indexed, so 5 items total
        assert checkpoint.is_complete("dashboards", 5) is True
        assert checkpoint.is_complete("dashboards", 6) is False

    def test_checkpoint_saved_and_loaded(self):
        """Checkpoint should persist to file and reload correctly."""
        checkpoint = MigrationCheckpoint()
        checkpoint.mark_complete("dashboards", 3)
        checkpoint.mark_complete("alerts", 1)

        with tempfile.TemporaryDirectory() as tmpdir:
            cp_file = Path(tmpdir) / "checkpoint.json"
            checkpoint.save(cp_file)

            loaded = MigrationCheckpoint.load(cp_file)
            assert loaded.get_resume_index("dashboards") == 4
            assert loaded.get_resume_index("alerts") == 2
            assert loaded.get_resume_index("slos") == 0

    def test_orchestrator_accepts_checkpoint(self):
        """MigrationOrchestrator should accept checkpoint parameter."""
        checkpoint = MigrationCheckpoint()
        with tempfile.TemporaryDirectory() as tmpdir:
            from migrate import MigrationOrchestrator
            orch = MigrationOrchestrator(
                output_dir=tmpdir,
                checkpoint=checkpoint,
            )
            assert orch.checkpoint is checkpoint
