# Phase 09 — Harden
Status: DONE

## Goal
Enforce code quality gates in CI: coverage threshold, type checking, and integration test scaffolding.

## Tasks
- [ ] Verify current coverage meets 80%; enforce threshold in CI
- [ ] Add mypy to CI for compiler/, migration/, validators/, config/
- [ ] Create env-var-gated integration test scaffold
- [ ] Phase gate: v1.2.1, docs, memories, PR, merge

## Acceptance Criteria
- `pytest --cov=. --cov-fail-under=80` passes locally and in CI
- `mypy compiler/ migration/ validators/ config/` passes with zero errors
- Integration tests skip cleanly in CI, pass with real credentials
- All existing tests unaffected

## Decisions Made This Phase
(append as you go)
