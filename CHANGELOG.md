# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.0.0] - 2026-04-16

> Phases 11–26 + 19b + 3rd-pass + Phase 25. Gen3-default migration
> engine with `--legacy` Gen2 fallback. 1271 unit + 14 gated tests.
> 53/53 nrql-engine transformer parity. 40+ transformers across 19
> NR surface categories. See `docs/COVERAGE.md` for the full matrix.
> performed; everything described here lives in the working tree.

### Added — Phase 16 (P0 coverage)
- `agents/` orchestrator: per-language APM-agent action plans
  (Java, .NET, Node.js, Python, Ruby, PHP, Go) — `migrate.py agents`
- `transformers/lambda_transformer.py` — NR Lambda → DT Lambda
  extension with per-runtime layer ARN templates
- `transformers/browser_rum_transformer.py` — NR Browser app →
  `builtin:rum.web.app-config` + Core Web Vitals + event-source mapping
- `transformers/mobile_rum_transformer.py` — NR Mobile app →
  `builtin:mobile-application` + 8-platform SDK-swap runbook
- `transformers/custom_instrumentation_translator.py` — `newrelic.*()` →
  DT/OTel pattern scanner (`migrate.py scan-instrumentation`)

### Added — Phase 17 (P1 alerts + data + identity)
- `non_nrql_alert_transformer`, `baseline_alert_transformer`,
  `lookup_table_transformer`, `maintenance_window_transformer`,
  `change_tracking_transformer`, `custom_event_ingest_transformer`,
  `identity_transformer`, `log_obfuscation_transformer`
- `tools/nrdb_archive.py` + `migrate.py archive` — resumable
  pre-decommission JSONL snapshot (per-event-type cursors)

### Added — Phase 18 (specialized products)
- `cloud_integration_transformer` (AWS/Azure/GCP), `kubernetes_transformer`
  (DynaKube), `aiops_transformer`, `vulnerability_transformer`,
  `npm_transformer`, `ai_monitoring_transformer`, `prometheus_transformer`

### Added — Phase 19 (dashboard + compiler uplift)
- Dashboard widget parity: funnel composite, native honeycomb heatmap,
  event-feed table with canonical sort, cascading variables with
  `dependsOn`, permissions → Document sharing, saved filter sets →
  `savedViews`
- `_apply_phase19_uplift` in `nrql_converter.py` raises confidence to
  HIGH when post-processors successfully translated Apdex / COMPARE
  WITH / rate() / percentage()

### Added — Phase 19b (nrql-engine compiler parity)
- `compiler/shorthands.py` — standalone `expand_nr_shorthands()`
- 16 regression tests pin Python compiler to TS sibling for shorthand
  expansion, K8s metric overrides + entity-field map, DQL fixer
  method coverage; CI parity job in `.github/workflows/ci.yml`

### Added — Phase 20 (operational safety)
- `migration/canary.py` — two-wave import with approval gate
  (`--canary <pct>`, `--canary-auto-proceed`)
- `migration/audit.py` + `migrate.py audit` — drift detection
  (RENAMED / DELETED / MODIFIED / EXTRA) against live tenant
- `DynatraceClient.delete_entity` — unified Gen3 delete dispatch
  (Settings 2.0 + Document + Automation); rollback CLI now actually
  executes deletes
- `ConversionReport` enrichment — numeric `confidence_score`,
  `warning_codes`, `runbook_url` per entry; `warnings_by_code()` and
  `average_confidence_score()` aggregators

### Added — Phase 21 (cross-repo alignment)
- `HISTORY.md` — breadcrumb file for past + planned ownership changes
- `config/project_links.py` — single-source URL registry; flip one
  field when `nrql-engine` relocates to `dynatrace-dma`

### Added — Phase 22 (lifecycle scaffolding)
- `docs/out-of-scope.md` — permanent exclusions + decision log
- `utils/error_taxonomy.py` — `WarningCode` / `ErrorCode` enums +
  `CodedMessage` dataclass + `warn()` / `error()` helpers
- `.github/workflows/ci.yml` — added `nrql-engine-parity` job
- `DECISIONS.md` — entries for legacy-removal deferral, project-links
  centralization, coded-warnings adoption

### Added — Phase 23 (second-wave nrql-engine parity)
- `key_transaction_transformer` — NR Key Transaction → SLO + OpenPipeline
  enrichment + Workflow bundle with `migratedFrom` metadata
- `otel_metrics_transformer` — NR OTel ingestion → `builtin:otel.ingest.metrics`
  + collector YAML snippet
- `statsd_transformer` — NR StatsD → ActiveGate `builtin:statsd.metrics`
- `cloudwatch_metric_streams_transformer` — Firehose path
  (`builtin:aws.metric-streams`) + Terraform snippet
- `transformers/metric_transform.py` — `MetricTransform` protocol +
  `MetricTransformRegistry` chain;
  `NRQLtoDQLConverter.register_metric_transform()` lets operators
  inject project-specific metric renames without forking
- `transformers/mappings/` package — per-concern re-export modules
  (`metrics`, `attributes`, `aggregations`, `event_types`,
  `metric_transforms`, `visualizations`)
- Numeric `confidence_score` always synced to categorical `confidence`
  via `_sync_confidence_score`

### Tests
- 1151 unit tests + 8 integration tests passing as of Phase 20

### Documentation
- `docs/migration-coverage.md` — exhaustive can/cannot inventory
  (~160 ✅ / ~25 🟡 / ~2 🔴 / ~8 ⛔)
- `docs/out-of-scope.md` — permanent exclusions
- `docs/nrql-engine-sync-audit.md` — first + second-pass audit findings
- `docs/architecture.md` — top-level codebase map (Phase 20)

### Changed (BREAKING — Gen3-default, planned for 2.0.0)
- All transformers emit Gen3 Dynatrace objects by default
  - `AlertTransformer` → Workflow + `builtin:davis.anomaly-detectors`
  - `NotificationTransformer` → Workflow action tasks (folded into the alert transform)
  - `InfrastructureTransformer` → Davis Anomaly Detector + Workflow
  - `WorkloadTransformer` → `builtin:segment` + bucket-scoped IAM policy
  - `TagTransformer` → OpenPipeline enrichment (`builtin:openpipeline.*`)
  - `LogParsingTransformer` + `DropRuleTransformer` → OpenPipeline `parse` / `drop` / `removeFields` processors
  - `DashboardTransformer` → Grail dashboard JSON (Document API, `version: 13`)
  - `SyntheticTransformer` → `builtin:synthetic_test`
  - `SLOTransformer` → `builtin:monitoring.slo`
- `DynatraceClient` rewritten as a Gen3 façade over `SettingsV2Client` +
  `DocumentClient` + `AutomationClient`; Config v1 methods moved to
  `clients/legacy/config_v1_client.py`.
- Monaco + Terraform exporters emit Gen3 resources
  (`dynatrace_document`, `dynatrace_automation_workflow`, `dynatrace_segment`,
  `dynatrace_iam_policy`, `dynatrace_slo_v2`, `dynatrace_generic_setting`).
- `registry/environment.py` — management-zone registry replaced with
  segment registry (`builtin:segment`).
- Orchestrator consumes Gen3 `TransformResult` fields: `workflow`,
  `anomaly_detectors`, `segment`, `iam_policy`, `synthetic_tests`,
  `openpipeline_processors`.

### Added
- `--legacy` CLI flag on `migrate`, `export-monaco`, `export-terraform`;
  `MIGRATION_LEGACY_MODE` env var mirrors the flag.
- `migrate.py preflight` subcommand — probes Settings 2.0, Document,
  and Automation APIs and suggests `--legacy` if any Gen3 surface is missing.
- OAuth2 platform-token provider (`OAuth2PlatformTokenProvider`) for
  Gen3 Platform APIs, alongside existing Api-Token auth.
- Legacy submodules preserved: `transformers/legacy/`, `clients/legacy/`,
  `exporters/legacy/`.
- Gen3 test suites — 19 DynatraceClient tests (composition, auth,
  Settings 2.0 pagination, Document `pageKey`, Automation), 18 exporter
  tests, 7 legacy-flag + preflight tests.

### Deprecated
- Alerting Profiles, Management Zones, Auto-Tag Rules, Problem
  Notifications, Config v1 dashboards / synthetics / SLOs — reachable
  only via `--legacy`. Planned for removal once Gen3 rollout completes.

### Migration notes
- `nrql-engine` will relocate to `dynatrace-dma` in a future release.
  URLs in artifacts and docs will be repointed via a patch release.

## [1.3.0] - 2026-04-10

### Added (Phase 10 — Fill Functional Gaps)
- Incremental migration: `--incremental` now actually skips unchanged entities via content hashing
- Resume from checkpoint: `--resume` skips already-imported entities with periodic checkpoint saving
- Window function compilation: `windowSum`, `windowAvg`, `windowCount`, `windowMax`, `windowMin` → DQL `arrayMovingSum/Avg/Max/Min` (10 new compiler tests)
- Orphan detection in `--diff`: flags DT entities with no NR source as ORPHAN (5 new tests)
- 11 new incremental/resume tests (IncrementalState wiring, checkpoint persistence, orchestrator integration)
- 26 new tests total — 920 unit tests + 8 integration tests across 29 files

### Changed
- `MigrationOrchestrator` accepts `incremental_state` and `checkpoint` parameters
- `_transform_phase` checks `IncrementalState.has_changed()` before each entity
- `_import_phase` uses `MigrationCheckpoint.get_resume_index()` to skip completed entities
- Checkpoint saved every 10 entities during import for crash resilience
- Diff display includes ORPHAN entries with magenta styling

## [1.2.1] - 2026-04-10

### Added (Phase 9 — Harden)
- Coverage threshold enforcement: 80% minimum via `--cov-fail-under=80` in CI
- Mypy type checking in CI for `compiler/`, `migration/`, `validators/`, `config/` (zero errors)
- Integration test scaffold: 8 env-var-gated smoke tests for NR client, DT client, and compile roundtrip
- Coverage and mypy configuration in `pyproject.toml`
- `typecheck` CI job running mypy on core modules

### Changed
- Fixed type annotations across compiler package (Optional params, variable annotations, null checks)
- Fixed `dql_fixer.py` regex group type safety
- Excluded `nrql_converter.py` and `migrate.py` from coverage measurement (glue code tested indirectly)

## [1.2.0] - 2026-04-09

### Added (Phase 8 — Export Formats: Monaco & Terraform)
- Monaco exporter: generates v2 project structure (YAML configs + JSON templates)
- Terraform exporter: generates HCL files with dynatrace provider resources
- CLI: `export-monaco` and `export-terraform` subcommands with --input/--output
- 15 new tests (Monaco + Terraform exporters) — 894 total across 25 files

## [1.1.0] - 2026-04-09

### Added (Phase 7 — Validation, Retry & Diff)
- Dry-run preview: summary table of what would be created + preview JSON export
- Partial retry: save failed entities to JSON, `--retry` flag to re-import
- Diff/preview: `--diff` flag compares transformed entities against live DT (CREATE/UPDATE/CONFLICT)
- FailedEntities class for tracking and reloading import failures
- DiffReport class with registry-based comparison (dashboards, management zones)
- 10 new tests (retry, diff) — 879 total across 23 files

## [1.0.0] - 2026-04-09

### Added (Phase 6 — API Modernization & CI/CD)
- Documents API v2 for dashboard creation (with Config API v1 fallback)
- GitHub Actions CI pipeline (pytest + ruff, Python 3.9-3.12 matrix)
- Full pyproject.toml with pip-installable package (`nr-migrate` CLI entry point)
- `batch` CLI subcommand: CSV/Excel batch compilation with results output
- 6 new tests (Documents API, batch CLI, version flag) — 869 total across 21 files

### Changed
- Version bumped to 1.0.0 — all 6 phases complete

## [0.6.0] - 2026-04-09

### Added (Phase 5 — Migration Infrastructure)
- RollbackManifest: track created entities for rollback (save/load JSON)
- EntityIdMap: NR GUID → DT ID mapping with persistence
- MigrationCheckpoint: resume from last successful import point
- IncrementalState: content-hash based change detection for incremental migration
- ConversionReport: JSON + HTML reports with per-query confidence, side-by-side NRQL/DQL
- CLI: `migrate --rollback`, `--resume`, `--incremental`, `--report` flags
- CLI: `--version` flag (reads from `_version.py`)
- 29 new tests (migration state + report) — 863 total across 21 files

## [0.5.0] - 2026-04-09

### Added (Phase 4 — New Entity Transformers)
- InfrastructureTransformer: NR host-not-reporting/process-not-running → DT metric events
- LogParsingTransformer: NR grok/regex log rules → DT processing rules with DPL patterns
- TagTransformer: NR entity tags → DT auto-tag rules (10 entity type mappings)
- DropRuleTransformer: NR data drop filter rules → DT metric/log ingest rules
- 32 new tests across 4 test files — 834 total across 19 files

### Changed
- Removed dead `apm_settings` from AVAILABLE_COMPONENTS (no transformer existed)
- Added `infrastructure`, `log_parsing`, `tags`, `drop_rules` to AVAILABLE_COMPONENTS

## [0.4.0] - 2026-04-09

### Added (Phase 3 — Environment Registry & Live Validation)
- DTEnvironmentRegistry: lazy-loaded caches for metrics, entities, dashboards, management zones, synthetic locations
- Fuzzy metric matching with 19 semantic synonym groups (error/failure, cpu/processor, etc.)
- DQL live validation via Grail query API (submit + parse errors)
- SLOAuditor: batch SLO audit for metric validity, invalid aggregation detection, NRQL syntax detection
- OAuth authentication support (client credentials flow via `sso.dynatrace.com`)
- Auth utilities: `get_auth_header()`, `get_dt_oauth_token()`, `ms_to_dql_duration()`
- CLI: `compile --validate` flag for live DQL validation against DT environment
- CLI: `audit-slos` subcommand for SLO metric audit
- 55 new tests (registry, SLO auditor, auth) — 802 total across 15 files

## [0.3.0] - 2026-04-09

### Added (Phase 2 — Test Coverage Completion)
- NewRelicClient unit tests: 24 tests covering all 14 public methods (mocked HTTP)
- DynatraceClient unit tests: 26 tests covering all 22 public methods (mocked HTTP)
- Settings unit tests: 13 tests covering config classes, endpoints, singleton, components
- Total test count: 747 across 12 test files (was 673)

## [0.2.0] - 2026-04-09

### Added
- CLI: `compile --interactive` — interactive REPL mode for ad-hoc query conversion
- CLI: `compile --file` / `--output` — batch compile queries from file with optional output file
- CLI: `reference` subcommand — NRQL→DQL quick reference table with `--mappings` for full mapping tables
- Field mappings: `memorytotal`, `memorytotalbytes` → `dt.host.memory.total`
- Example queries file (`examples/example_queries.nrql`)
- CLI test suite: 14 tests covering interactive, batch, reference, and example query compilation

### Added (Phase 1 — Compiler Enhancements)
- COMPARE WITH → `append` subquery for span/event queries (metric queries still use `shift:`)
- `capture(field, regex)` → `parse(field, "DPL_PATTERN")` using RegexToDPL converter
- Nested `filter()` in aggregations: `count(*, filter(WHERE ...))` → `countIf(...)`
- Lexer now preserves regex escape sequences in string literals (`\w`, `\d`, `\s`, `\S`)
- 10 new compiler regression tests (292 compiler tests, 673 total)

### Changed
- Consolidated standalone `nrql-converter/` tool into migration framework CLI
- Fixed `hostmemorytotal` mapping (was incorrectly mapped to `dt.host.memory.used`, now `dt.host.memory.total`)
- Standardized transformer interfaces for consistency:
  - Renamed `TransformResult` → `DashboardTransformResult` (consistent `{Entity}TransformResult` naming)
  - Renamed `AlertTransformer.transform_policy()` → `transform()` (consistent method name)
  - `NotificationTransformer.transform_channel()` → `transform()`, now returns `NotificationTransformResult` dataclass instead of raw dict
  - `DashboardTransformer.transform()` now returns single `DashboardTransformResult` (with `data` as list of dashboards) instead of `List[TransformResult]`
  - `ConversionResult` fields aligned with `CompileResult`: `converted_dql` → `dql`, `fixes_applied` → `fixes`

### Removed
- Standalone `nrql-converter/` directory — all functionality now available via `migrate.py compile` and `migrate.py reference`

### Added (prior)
- Comprehensive test suite: 367 new tests across 8 test files (649 total with compiler tests)
  - `test_utils_validators.py` — config and structure validation tests
  - `test_dql_validator.py` — DQL syntax validation + anti-pattern detection tests
  - `test_dql_fixer.py` — DQL auto-fixer, duration conversion, and new fix rule tests
  - `test_mapping_rules.py` — EntityMapper and mapping dictionary tests
  - `test_converters.py` — RegexToDPL, Aparse, Rate, CompareWith, Funnel, Extrapolate, BucketPercentile converter tests
  - `test_transformers.py` — Dashboard, Alert, Notification, Synthetic, SLO, and Workload transformer tests
  - `test_nrql_mapping_rules.py` — EVENT_TYPE_MAP, AGG_MAP, ATTR_MAP coverage
- DQL reference rules (`.claude/rules/dql-reference.md`) — incorporated from dynatrace-dql skill repository
  - Complete DQL function catalog (100+ functions across 10 categories)
  - Grail data objects reference
  - Performance best practices and anti-patterns
  - Recommended command ordering
- DQL validator anti-pattern detection (warnings):
  - Sort before filter detection
  - Limit before summarize detection
- DQL fixer new rules:
  - Duration unit fix (nanosecond vs millisecond for `resolved_problem_duration`)
  - Negation-to-filterOut performance hint
  - Array count without expand warning
- Expanded AGG_MAP with 40+ new function mappings from Grail function reference
  - Aggregation: countIf, variance, correlation, collectArray, takeAny, takeMax, takeMin, countDistinctApprox/Exact
  - String: indexOf, lastIndexOf, startsWith, endsWith, contains, matchesValue, matchesPhrase, matchesPattern, trim, replaceString, replacePattern, splitString, levenshteinDistance
  - Array: arrayAvg, arrayMax, arrayMin, arrayMedian, arrayFirst, arrayLast, arrayConcat, arrayDistinct, arrayFlatten, arrayDelta, arrayCumulativeSum, arrayMovingAvg
  - Boolean/conditional: isNull, isNotNull, coalesce
  - Time: getDayOfMonth, getDayOfYear, getSecond, formatTimestamp
  - Type conversion: toLong, toDouble, toBoolean, toTimestamp, toDuration
- Expanded EVENT_TYPE_MAP with mobile, custom event, audit, and integration sample types
- CHANGELOG.md following Keep a Changelog format

### Changed
- Updated root README.md project structure to reflect current codebase (added compiler/, validators/, tests/, and new transformer files)
- Updated README.md project structure to match actual directory layout
- Corrected Known Limitations to accurately describe AST compiler capabilities (282 tested patterns)

## [0.1.0] - 2026-04-08

### Added
- Initial migration framework with three-phase pipeline (Export → Transform → Import)
- AST-based NRQL-to-DQL compiler (lexer, parser, emitter) with 282 tested patterns
- Dashboard transformer (multi-page → per-page conversion)
- Alert transformer (policy → alerting profile + metric events)
- Synthetic transformer (ping/browser/API → HTTP/Browser monitors)
- SLO transformer with type detection (availability, error rate, latency)
- Workload transformer (entity groupings → management zones)
- Notification transformer (email, Slack, PagerDuty, webhook)
- DQL syntax validator (9 structural regex rules)
- DQL auto-fixer (19 fix rules: quotes, operators, functions, aliases, etc.)
- Specialized converters: RegexToDPL, Aparse, Rate/Derivative, CompareWith, Funnel, Extrapolate, BucketPercentile, WithAs (CTE)
- New Relic NerdGraph GraphQL client with pagination and rate limiting
- Dynatrace API client (Settings API v2 + Config API v1)
- Click CLI with subcommands: migrate, compile, convert
- Pydantic-based configuration from .env files
- structlog-based structured logging
