# Phase 05 — Migration Infrastructure
Status: DONE

## Goal
Add production-grade migration infrastructure: rollback capability, progress checkpointing, incremental migration, entity ID mapping, and a conversion report for manual review.

## Tasks
- [ ] **Rollback manifest**
  - Track every entity created in DT during migration (type, ID, name, timestamp)
  - Save manifest as JSON after each migration run
  - Add `--rollback <manifest-file>` CLI command that deletes all created entities
  - Confirm before destructive rollback action
- [ ] **Entity ID mapping file**
  - NR GUID → DT entity ID mapping persisted as JSON
  - Updated during import phase as entities are created
  - Used to resolve cross-references between migrated entities (e.g., alert referencing dashboard)
  - Add `--id-map <file>` CLI flag to load/save mapping
- [ ] **Incremental migration**
  - Track what has been migrated (by NR GUID + hash of content)
  - On re-run, only export/transform/import changed entities
  - Add `--incremental` flag (default off for safety)
  - Store migration state in `.migration-state.json`
- [ ] **Progress checkpointing**
  - Save state after each successful entity import
  - On failure, resume from last checkpoint instead of restarting
  - Add `--resume` flag to continue from checkpoint
  - Checkpoint file: `.migration-checkpoint.json`
- [ ] **Conversion report generator**
  - Per-query confidence scores (HIGH/MEDIUM/LOW)
  - List of queries requiring manual review (MEDIUM/LOW confidence)
  - Manual review checklist with original NRQL and converted DQL side by side
  - Summary statistics: total queries, auto-converted, needs-review, failed
  - Output as HTML and JSON
  - Add `--report` flag to generate after migration
- [ ] **Version tracking**
  - Add version field to `pyproject.toml` (currently missing)
  - Add `__version__` to package `__init__.py`
  - Add `--version` flag to CLI
- [ ] Tests for rollback, checkpointing, incremental logic, report generation

## Acceptance Criteria
- Rollback deletes exactly what was created, nothing more
- Entity ID mapping correctly resolves cross-references
- Incremental migration skips unchanged entities (verified by content hash)
- Checkpoint resume continues from exact failure point
- Conversion report clearly identifies which queries need manual attention
- Version number consistent between pyproject.toml and __init__.py
- All infrastructure code has tests

## Decisions Made This Phase
(append as you go)
