# Phase 26 — Validation Layer (Tiers 1, 3, 6 + mypy --strict)
Status: PENDING (release-hold also applies)

## Goal
Move from "structural correctness via 1201 unit tests" to "schema-,
IaC-, and invariant-validated output". Implements the minimum-for-2.0.0
subset of `docs/validation.md` (tiers 1, 3, 6 + mypy --strict).

Tiers 2 (TS compiler differential), 4 (live DQL), and 5
(throwaway-tenant round-trip) are deferred — they require external
toolchains / tenants that may not be available in CI and can ship as
opt-in extras under their own phase.

## Tasks

### T1 — Static schema validation against published DT schemas
- [ ] `tests/fixtures/dt-schemas/` directory + `index.json` mapping
      schema_id → cached JSON-schema file
- [ ] One-time fetcher script `scripts/fetch_dt_schemas.py` that pulls
      every `builtin:*` schema this project emits via
      `/api/v2/settings/schemas/<id>` and writes them to fixtures
- [ ] `tests/integration/test_schema_validation.py` — gated on
      `RUN_SCHEMA_VALIDATION=1`; iterates every transformer's output
      envelope and validates `value` against the cached schema with
      `jsonschema`
- [ ] Document the schema-version provenance (which DT tenant + when)
      in `tests/fixtures/dt-schemas/README.md`

### T3 — Terraform `validate` + Monaco `--dry-run` on emitted output
- [ ] `tests/integration/test_iac_validates.py` — gated on
      `RUN_IAC_VALIDATION=1`; runs every fixture through
      `TerraformExporter` + `terraform validate`, and through
      `MonacoExporter` + `monaco deploy --dry-run`
- [ ] `requirements-dev.txt` (or a separate `requirements-validation.txt`)
      adds the toolchain pointers; CI installs Terraform + Monaco
      versions in a setup step
- [ ] CI job `iac-validate` running on PR + nightly

### T6 — Property-based / fuzz testing
- [ ] `requirements.txt` add `hypothesis>=6.0`
- [ ] `tests/unit/test_invariants.py` — Hypothesis strategies per
      major transformer (alert, dashboard, infrastructure, workload,
      cloud_integration, kubernetes, identity)
- [ ] Universal invariants checked for every transformer output:
  - never raises an unhandled exception
  - result is JSON-serializable
  - every emitted Settings 2.0 envelope has `schemaId` + `scope` + `value`
  - in default mode, no envelope's `schemaId` matches a Gen2 schema
    (`builtin:alerting.profile` / `builtin:management-zones` /
    `builtin:tags.auto-tagging` / `builtin:problem.notifications.*` /
    `builtin:anomaly-detection.metric-events`)
  - `confidence_score` always in [0, 100]
  - all warning strings are non-empty

### mypy --strict
- [ ] `pyproject.toml` flip `disallow_untyped_defs = true` for `compiler/`,
      `migration/`, `validators/`, `config/` (already covered) and
      add `transformers/`, `agents/`, `tools/`, `clients/`,
      `exporters/`, `utils/`
- [ ] Resolve resulting errors module by module; commit per module
- [ ] CI mypy job already exists — drift will fail PRs

### Coverage uplift
- [ ] `pyproject.toml` raise `--cov-fail-under` from 80 to 85
- [ ] Generate HTML report locally; audit largest uncovered branches
      and add targeted tests

### Snapshot testing (optional within Phase 26)
- [ ] Add `syrupy` for snapshot assertions
- [ ] One snapshot fixture per transformer under `tests/snapshots/`
      built from a hand-curated real NR export

## Acceptance Criteria
- All three new test files exist and pass (T1 + T3 + T6) when their
  env-var gates are set
- `pytest tests/ -q` (without env-var gates) stays green
- `mypy` runs strict on the listed modules with zero errors
- `--cov-fail-under=85` passes
- `docs/validation.md` updated — each tier table-row gets a "shipped
  in Phase 26" / "deferred to Phase 27" status column

## Out of scope (deferred to later phases)
- T2 — TS compiler differential (needs a `compile-one.ts` script in
  `nrql-engine` + node toolchain in CI)
- T4 — Live DQL execution (needs a sandbox DT tenant + token)
- T5 — Throwaway-tenant round-trip (same)
- Real-customer pilot (organizational, not technical)

## Decisions Made This Phase
(append as you go)
