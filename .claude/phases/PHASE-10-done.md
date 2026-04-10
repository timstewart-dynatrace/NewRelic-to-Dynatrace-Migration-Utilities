# Phase 10 — Fill Functional Gaps
Status: DONE

## Goal
Wire up dead incremental/resume code paths, improve window function compilation, and add orphan detection to diff.

## Tasks
- [ ] Wire --incremental (skip unchanged entities via IncrementalState.has_changed)
- [ ] Wire --resume (skip completed components via MigrationCheckpoint.is_complete)
- [ ] Window function compilation (replace TODO placeholders with arrayMoving* DQL)
- [ ] Orphan detection in --diff (flag DT entities with no NR source)
- [ ] Phase gate: v1.3.0, docs, memories, PR, merge

## Acceptance Criteria
- Second --incremental run on same data skips all entities
- --resume after partial run skips completed components
- All 5 window* functions produce valid DQL (no /* TODO */)
- --diff shows ORPHAN entries for DT entities without NR source
- All existing tests pass, new tests added

## Decisions Made This Phase
(append as you go)
