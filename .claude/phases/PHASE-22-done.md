# Phase 22 — Long-Tail + Lifecycle (Deprecate Gen2, Productize, Polish)
Status: PENDING

## Goal
After Phases 16–21 land, decide when to retire the `--legacy` flag, polish the CLI UX, and harden the codebase for broader adoption.

## Tasks
- [ ] **Legacy removal plan** — survey real-world tenant adoption of Gen3 features; when > 95% of target tenants have Gen3, schedule removal of `transformers/legacy/`, `clients/legacy/`, `exporters/legacy/` in a 3.0.0 release
- [ ] **Out-of-scope documentation** — formalize `docs/out-of-scope.md` listing everything in the "⛔" column of `migration-coverage.md` with the reasoning
- [ ] **Error taxonomy** — rationalize warnings/errors into a small enum (CONFIDENCE_LOW, SCHEMA_MISMATCH, SECRET_MANUAL, UNSUPPORTED_WIDGET, …) used consistently across all transformers
- [ ] **Telemetry opt-in** — optional anonymous usage reporting (feature toggles, success rates) to prioritize future work; never transmits customer data
- [ ] **PyPI publish** — package as `newrelic-to-dynatrace-migration` on PyPI, signed releases
- [ ] **CI/CD** — GitHub Actions: `pytest`, `ruff`, `mypy`, coverage badge, release automation
- [ ] **Performance** — profile the compiler on 1000-query fixtures; target < 50ms/query
- [ ] **Web UI (stretch)** — lightweight Flask/FastAPI wrapper around the CLI for non-engineer operators; no API changes required

## Acceptance Criteria
- `docs/out-of-scope.md` exists and is linked from README + `migration-coverage.md`
- CI runs on every PR, fails on coverage regression or mypy errors
- A signed release v2.1.0 (or later) is published to PyPI
- Compiler benchmark: ≥ 20 queries/second sustained on a laptop
- Legacy-removal decision is documented in DECISIONS.md (not acted on yet)

## Decisions Made This Phase
(append as you go)
