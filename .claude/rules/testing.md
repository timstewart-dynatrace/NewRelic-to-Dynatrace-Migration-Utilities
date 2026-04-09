# Testing

## Running Tests
```bash
pytest tests/ -v                    # All tests
pytest tests/unit/test_compiler.py  # Compiler only
pytest -x --tb=short               # Stop on first failure
pytest --cov=. --cov-report=html    # Coverage
```

## Test Structure
- 649 total tests across 8 test files in `tests/unit/`
- 282 compiler tests in `test_compiler.py` (25 test classes by feature)
- 367 additional tests covering transformers, validators, converters, and mapping rules:
  - `test_transformers.py` — Dashboard, Alert, Notification, Synthetic, SLO, Workload
  - `test_converters.py` — RegexToDPL, Aparse, Rate, CompareWith, Funnel, Extrapolate, BucketPercentile
  - `test_dql_validator.py` — DQL syntax validation (case-sensitive/insensitive patterns, structural checks)
  - `test_dql_fixer.py` — DQL auto-fixer (19 fix rules) + ms_to_dql_duration
  - `test_mapping_rules.py` — EntityMapper, mapping dictionaries, nested value get/set
  - `test_utils_validators.py` — Config and structure validators
  - `test_nrql_mapping_rules.py` — EVENT_TYPE_MAP, AGG_MAP, ATTR_MAP
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
- Use `assert result.success` + `assert "expected" in result.dql`
- Mock external APIs (NR, DT) in integration tests
