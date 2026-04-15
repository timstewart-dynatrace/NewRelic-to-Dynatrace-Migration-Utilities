# Phase 20 — Validation, Rollback, Operational Safety
Status: PENDING

## Goal
Every migration is reversible, previewable, and diffable. Raise operator confidence from "trust the tool" to "verify at each step".

## Tasks
- [ ] **Canary mode** — `migrate.py migrate --canary <pct>` applies the migration to a fraction of entities first, pauses for operator approval before full rollout
- [ ] **Per-entity dry-run diff** — show expected DT payload vs. current live DT payload side by side
- [ ] **Rollback completeness** — current rollback manifest covers Gen3 entities; extend to Workflows, Segments, OpenPipeline, IAM (verify delete API coverage)
- [ ] **Rollback dry-run** — `--rollback --dry-run` lists what would be deleted without calling the API
- [ ] **Integration tests against a throwaway tenant** — env-var-gated, uses a short-lived OAuth client; asserts create/read/delete round-trip for every Gen3 entity type
- [ ] **Structured conversion report** — enhance HTML/JSON report to include per-entity confidence, warning categories, and links to NRLC runbooks
- [ ] **Post-migration audit tool** — `migrate.py audit --baseline <export> --live` diffs what's actually in DT against what was transformed (detects drift, missing imports, rogue objects)

## Acceptance Criteria
- Canary mode respects the percentage and pauses cleanly (unit-tested)
- Rollback deletes 100% of Gen3 entity types (integration test on throwaway tenant)
- Audit tool catches at least these drift types: entity renamed, entity deleted, entity modified, extra entity present
- Full suite + 30 new operational-safety tests pass

## Decisions Made This Phase
(append as you go)
