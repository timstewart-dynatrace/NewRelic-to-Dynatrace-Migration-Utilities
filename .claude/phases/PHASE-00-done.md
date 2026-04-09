# Phase 00 — Consolidate nrql-converter into Migration Tool
Status: DONE

## Goal
Absorb all unique features from the standalone `nrql-converter/` tool into the migration framework, then remove the standalone tool to eliminate duplication.

## Context
The repo has two NRQL-to-DQL converters:
- `nrql-converter/nrql_to_dql.py` — standalone regex-based tool (32KB, 21 tests)
- `newrelic-to-dynatrace-migration/` — AST-based compiler + full pipeline (649 tests)

The migration tool already covers most functionality. This phase absorbs what's missing and removes the standalone tool.

## Tasks

### 1. Absorb unique CLI features into migrate.py
- [ ] Add `--interactive` mode to `migrate.py compile` (REPL loop for ad-hoc query conversion)
- [ ] Add `--file` / `--output` batch mode to `migrate.py compile` (read queries from file, write results to file)
- [ ] Add `--reference` subcommand or flag to display NRQL→DQL mapping reference table (Rich table output)

### 2. Absorb unique conversion logic
- [ ] LIKE operator → DQL pattern conversion (`%x%` → `contains()`, `x%` → `startsWith()`, `%x` → `endsWith()`) — verify AST compiler handles these; if not, add to emitter or post-processing
- [ ] OPERATOR_MAPPINGS coverage — verify `=` → `==`, `LIKE` → pattern match, `IN` → `in`, `IS NULL` → `isNull()`, `IS NOT NULL` → `isNotNull()`, `NOT LIKE`, `NOT IN` are all handled
- [ ] Percentile with parameter extraction (`percentile(field, 95)`) — verify compiler handles this correctly
- [ ] QueryType classification (metrics/logs/traces/events) — add to ConversionResult if not present

### 3. Absorb unique field mappings
- [ ] Compare `nrql-converter` FIELD_MAPPINGS (50 entries) against migration tool's METRIC_MAP (230 entries) and ATTR_MAP (72 entries)
- [ ] Add any missing mappings (likely infrastructure fields like `memoryUsedBytes`, `diskFreeBytes`, network fields)

### 4. Absorb unique test patterns
- [ ] Port LIKE operator edge case tests (startsWith/endsWith/contains) if not covered
- [ ] Port time range unit tests (minutes, hours, days) if not covered
- [ ] Port per-function mapping tests if not covered
- [ ] Port batch file processing tests
- [ ] Port interactive mode tests

### 5. Absorb examples file
- [ ] Move `nrql-converter/examples.nrql` to `newrelic-to-dynatrace-migration/examples/` as reference queries
- [ ] Ensure all example queries produce valid DQL through the compiler

### 6. Remove standalone tool
- [ ] Delete `nrql-converter/` directory
- [ ] Update root `README.md` — remove references to standalone converter, update project structure
- [ ] Update `CHANGELOG.md`

## Acceptance Criteria
- `migrate.py compile --interactive` works as a REPL
- `migrate.py compile --file queries.txt --output results.dql` processes batch files
- `migrate.py reference` (or `compile --reference`) displays mapping table
- All LIKE operator patterns produce correct DQL
- All field mappings from nrql-converter exist in migration tool's mapping tables
- All 21 legacy tests have equivalent coverage in migration tool test suite
- `nrql-converter/` directory is deleted
- Root README.md no longer references standalone converter
- All existing 649 tests still pass

## Decisions Made This Phase

- **Compiler handles all NRQL conversion logic**: LIKE operators, all operators, percentile — verified no gaps, no code to port from standalone tool
- **Only 1 missing field mapping**: `memorytotalbytes` was the only mapping in the standalone tool not already in METRIC_MAP. Also fixed `hostmemorytotal` bug (was mapped to `dt.host.memory.used` instead of `dt.host.memory.total`)
- **Standardized transformer interfaces**: All transformers now follow `{Entity}TransformResult` naming, use `transform()` method, return dataclasses (not raw dicts). `ConversionResult` fields aligned with `CompileResult` (`dql`/`fixes` instead of `converted_dql`/`fixes_applied`)
- **DashboardTransformer.transform() returns single result**: Changed from `List[TransformResult]` to single `DashboardTransformResult` with `data` as list of dashboards. Multi-page handling moved inside the result, consistent with all other transformers
- **663 tests pass**: 649 original + 14 new CLI tests, all green after refactoring
