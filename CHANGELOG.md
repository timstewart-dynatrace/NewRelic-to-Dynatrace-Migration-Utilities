# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [Unreleased]

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
- Updated newrelic-to-dynatrace-migration/README.md project structure to match actual directory layout
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
