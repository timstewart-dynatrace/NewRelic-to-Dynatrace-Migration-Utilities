# Testing

## Running Tests
```bash
pytest tests/ -v                    # All 894 unit + 8 integration tests
pytest tests/unit/test_compiler.py  # 292 compiler tests
pytest tests/unit/test_cli.py       # CLI tests
pytest -x --tb=short               # Stop on first failure
pytest --cov=. --cov-fail-under=80  # Coverage with threshold
mypy compiler/ migration/ validators/ config/  # Type checking

# Integration tests (requires .env with real credentials)
RUN_INTEGRATION_TESTS=1 pytest tests/integration/ -v
```

## Test Structure
- 894 unit tests across 25 test files in `tests/unit/`
- 8 integration tests across 3 files in `tests/integration/` (env-var gated)
- 292 compiler tests in `test_compiler.py` (25+ test classes by feature)
- 17 CLI tests in `test_cli.py` (interactive, batch, reference, version, CSV batch)
- 77 transformer tests in `test_transformers.py` + 32 across 4 new transformer test files
- 29 DT client + 24 NR client tests (mocked HTTP)
- 13 settings + 14 auth + 19 registry + 14 SLO auditor tests
- 21 migration state + 8 report + 5 retry + 5 diff tests
- 8 Monaco exporter + 7 Terraform exporter tests
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
