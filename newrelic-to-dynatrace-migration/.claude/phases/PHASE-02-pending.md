# Phase 02 — Test Coverage Completion
Status: PENDING

## Goal
Achieve test coverage for every public function in the codebase. Currently untested: clients (mocked HTTP), migrate.py (CLI + orchestrator), and nrql_converter.py (main conversion engine).

## Tasks
- [ ] `clients/newrelic_client.py` tests — mock HTTP, test all 12 public methods: `execute_query`, `get_all_dashboards`, `get_dashboard_definition`, `get_all_alert_policies`, `get_alert_conditions`, `get_notification_channels`, `get_all_synthetic_monitors`, `get_synthetic_monitor_details`, `get_synthetic_monitor_script`, `get_all_slos`, `get_all_workloads`, `export_all`
- [ ] `clients/dynatrace_client.py` tests — mock HTTP, test all 16 public methods: `create_dashboard`, `get_all_dashboards`, `create_metric_event`, `create_alerting_profile`, `create_http_monitor`, `create_browser_monitor`, `get_synthetic_locations`, `create_slo`, `get_all_slos`, `create_management_zone`, `create_notification_integration`, `validate_connection`, `backup_all`, settings objects CRUD
- [ ] `transformers/nrql_converter.py` tests — test `NRQLtoDQLConverter.convert()` with various NRQL inputs, verify it orchestrates compiler + fixer + validator correctly
- [ ] `migrate.py` tests — test `MigrationOrchestrator` methods: `run_full_migration`, `_resolve_dependencies`, `_export_phase`, `_transform_phase`, `_import_phase`, `_generate_report`; test CLI commands with Click test runner
- [ ] `config/settings.py` tests — test Settings singleton, reset, region-based endpoints
- [ ] Remove `apm_settings` and `infrastructure` from `AVAILABLE_COMPONENTS` (no transformer code exists — dead config is misleading) OR implement stub transformers that emit clear warnings

## Acceptance Criteria
- Every public function in every module has at least one test
- Client tests use `responses` library to mock HTTP (no live API calls)
- CLI tests use Click's `CliRunner`
- 750+ total tests pass
- No dead/misleading entries in AVAILABLE_COMPONENTS

## Decisions Made This Phase
(append as you go)
