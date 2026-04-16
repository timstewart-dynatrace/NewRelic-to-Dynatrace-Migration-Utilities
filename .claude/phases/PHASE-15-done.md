# Phase 15 — Tests, Docs, v2.0.0 Release
Status: ON HOLD (user-suspended 2026-04-15)

> **Do not execute any release work** — no version bumps, no git tags, no commits
> to main, no PyPI publishes, no CHANGELOG date-stamping — until the user
> explicitly marks this phase ready. Phases 16–22 may proceed in the working
> tree only; commits and merges wait on user approval.

## Goal
Ship the Gen3-default release as v2.0.0 with complete test coverage, refreshed docs, a CHANGELOG entry calling out the breaking change, and a signed git tag.

## Tasks
- [ ] Add `tests/unit/test_gen3_*.py` coverage for each new transformer target (Workflow, Segment, Davis Anomaly Detector, OpenPipeline)
- [ ] Migrate Gen2 tests to `tests/legacy/` — must continue to pass when `--legacy` is set
- [ ] Update `CLAUDE.md` — version, architecture summary, Gen3-default wording
- [ ] Update `.claude/rules/architecture.md` — transformer/client/exporter tables reflect Gen3 targets; legacy submodules documented
- [ ] Update `.claude/rules/deployment.md` if release steps change
- [ ] Rewrite `README.md` intro to state Gen3-default + legacy flag availability
- [ ] Add `CHANGELOG.md` `[2.0.0] - YYYY-MM-DD` section:
  - **Changed (BREAKING):** All transformers emit Gen3 objects by default
  - **Added:** `--legacy` flag for Gen2 (classic tenant) compatibility
  - **Added:** Workflow, Segment, Davis Anomaly Detector, OpenPipeline transformer targets
  - **Added:** Automation API client, Document API client, Settings 2.0 consolidation
  - **Added:** `migrate.py preflight` tenant capability check
  - **Deprecated:** Alerting Profiles, Management Zones, Auto-Tag Rules, Problem Notifications, Config v1 Metric Events (available only under `--legacy`)
- [ ] Add stop-gap dma note to README + footer: "nrql-engine will relocate to dynatrace-dma; URLs repoint in a future patch release"
- [ ] Bump `_version.py` → `2.0.0`
- [ ] Bump `pyproject.toml` `[project].version` → `2.0.0`
- [ ] Run full quality gate: `ruff check . && ruff format --check . && pytest --cov=. --cov-fail-under=80 && mypy compiler/ migration/ validators/ config/`
- [ ] Commit: `chore: bump version to 2.0.0`
- [ ] Tag: `git tag -a v2.0.0 -m "Release v2.0.0: Gen3-default migration targets (Workflows, Segments, Davis Anomaly Detectors, OpenPipeline); --legacy flag preserves Gen2 path"`

## Acceptance Criteria
- All quality gates pass (ruff, ruff format, pytest ≥80% coverage, mypy)
- Both `--legacy` and default paths produce dry-run success on a fixture account
- `python migrate.py --version` prints `2.0.0`
- Git tag `v2.0.0` exists locally and is ready to push
- CHANGELOG accurately enumerates breaking changes and the legacy-flag runway

## Decisions Made This Phase
(append as you go)
