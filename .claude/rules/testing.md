# Testing

## Running Tests
```bash
pytest tests/ -v                    # All 1237 unit + 8 integration tests
pytest tests/unit/test_compiler.py  # 292 compiler tests
pytest tests/unit/test_invariants.py  # 36 Hypothesis property-based fuzz tests
pytest tests/unit/test_cli.py       # CLI tests
pytest -x --tb=short               # Stop on first failure
pytest --cov=. --cov-fail-under=80  # Coverage with threshold (82% as of Phase 26)
mypy compiler/ migration/ validators/ config/  # Type checking

# Integration tests (requires .env with real credentials)
RUN_INTEGRATION_TESTS=1 pytest tests/integration/ -v

# Schema validation (requires populated fixtures via scripts/fetch_dt_schemas.py)
RUN_SCHEMA_VALIDATION=1 pytest tests/integration/test_schema_validation.py -v

# IaC dry-run (requires terraform + monaco on PATH)
RUN_IAC_VALIDATION=1 pytest tests/integration/test_iac_validates.py -v
```

## Test Structure
- 1237 unit tests across 40+ test files in `tests/unit/`
- 36 Hypothesis property-based invariant tests in `test_invariants.py` (1080 randomized inputs per run)
- 16 nrql-engine parity regression tests in `test_phase19b_engine_parity.py`
- 8 integration tests across 5 files in `tests/integration/` (env-var gated)
- Gen2 regression tests preserved in `tests/legacy/` (run against `transformers/legacy/`)
- 292 compiler tests in `test_compiler.py` (25+ test classes by feature)
- Per-phase test files: `test_phase16_modules.py` through `test_phase24_modules.py` + `test_phase19b_engine_parity.py` + `test_phase20_modules.py` + `test_phase23_modules.py` + `test_third_pass_parity.py`
- 19 Gen3 DT client tests in `test_dynatrace_client.py` (composition, auth, Settings 2.0, Document, Automation, OAuth2)
- 7 legacy-flag + preflight tests in `test_legacy_flag.py`
- Session-scoped `compiler` fixture in `tests/conftest.py`
- Structural validators: balanced parens, no NRQL keyword leaks, reserved alias quoting

## Test Naming
```python
class TestMetricQueries:
    def test_should_emit_timeseries_for_system_sample(self, compiler):
        ...
```

## Adding Tests
- Every new NRQL pattern needs a test
- Every bug fix needs a regression test
- Every new module needs a corresponding test file
- Use `assert result.success` + `assert "expected" in result.dql`
- Mock external APIs (NR, DT) with `unittest.mock.patch`
- Use `click.testing.CliRunner` for CLI tests
- Use `tempfile` for file I/O tests
