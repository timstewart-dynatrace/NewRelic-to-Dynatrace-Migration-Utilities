# New Relic to Dynatrace Migration Tool

**ALWAYS** ask clarifying questions and **ALWAYS** provide a plan **BEFORE** making changes.

## Project Summary

Universal migration tool for converting New Relic monitoring configurations to Dynatrace. Migrates dashboards (with a real NRQL-to-DQL compiler), alerts, synthetic monitors, SLOs, and workloads. Three-phase pipeline: Export (NR NerdGraph) -> Transform -> Import (DT APIs).

**Last Updated:** 2026-04-09
**Version:** 1.0.0
**Phases Completed:** 0-6 (all complete) — v1.0.0

## Quick Reference

```bash
# Run tests (869 total)
pytest tests/ -v

# Compile single query
python migrate.py compile "SELECT count(*) FROM Transaction"

# Interactive REPL
python migrate.py compile --interactive

# Batch compile from file
python migrate.py compile --file examples/example_queries.nrql

# Batch CSV/Excel
python migrate.py batch --file queries.csv --output results.csv

# Reference table
python migrate.py reference

# Full migration (dry run)
python migrate.py migrate --dry-run

# Version
python migrate.py --version
```

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Runtime | Python 3.9+ | Broad compatibility |
| Config | Pydantic + python-dotenv | Typed settings from .env |
| CLI | Click + Rich | Subcommands with progress display |
| Logging | structlog | Structured logging |
| HTTP | requests | API clients |
| Testing | pytest | 894 tests across 21 files |

## Architecture

```
EXPORT (NR NerdGraph)  ->  TRANSFORM  ->  IMPORT (DT APIs)

Transformers:                          Targets:
  DashboardTransformer (AST compiler)    Dashboards (Documents API)
  AlertTransformer                       Alerting Profiles + Metric Events
  NotificationTransformer                Problem Notifications
  SyntheticTransformer                   HTTP/Browser Monitors
  SLOTransformer                         SLOs
  WorkloadTransformer                    Management Zones
  InfrastructureTransformer              Metric Events (host/process)
  LogParsingTransformer                  Log Processing Rules
  TagTransformer                         Auto-Tag Rules
  DropRuleTransformer                    Ingest Rules

NRQL Compiler Pipeline:
  NRQL string -> Lexer -> Token[] -> Parser -> AST -> DQLEmitter -> DQL string
```

### Transformer Interface Standard

All transformers follow a consistent pattern:
- **Result class**: `{Entity}TransformResult` dataclass with `success`, `warnings`, `errors`
- **Method**: `transform(nr_entity) -> {Entity}TransformResult` (single item)
- **Batch**: `transform_all(items) -> List[{Entity}TransformResult]`

## Key Directories

| Path | Purpose |
|------|---------|
| `compiler/` | NRQL-to-DQL AST compiler (6 files: tokens, lexer, ast_nodes, parser, emitter, compiler) |
| `clients/` | NR NerdGraph + DT API clients with retry/backoff |
| `transformers/` | 10 entity transformers + NRQL converter + mapping tables |
| `validators/` | DQL syntax validator + 19-rule auto-fixer |
| `registry/` | DTEnvironmentRegistry (live validation) + SLOAuditor |
| `migration/` | Rollback, checkpointing, incremental state, conversion reports, retry, diff |
| `exporters/` | Monaco YAML + Terraform HCL config-as-code exporters |
| `config/` | Pydantic BaseSettings from .env |
| `utils/` | Logging, validators, auth utilities |
| `examples/` | Sample NRQL queries for batch testing |
| `tests/` | 869 pytest tests across 21 files |

## Rules

### Always active
@.claude/rules/architecture.md
@.claude/rules/python.md
@.claude/rules/testing.md
@.claude/rules/dql-reference.md

## Key Constraints

- **No hardcoded credentials** — all secrets via .env / environment variables
- **Community project** — not officially supported by Dynatrace
- **Feature branches** — never commit features directly to main
- **Compiler vs Converter** — `compiler/` handles pure NRQL->DQL translation. `transformers/nrql_converter.py` wraps it with post-processing and auto-fixes.
- **DQL validation** — structurally valid DQL doesn't guarantee data returns. Field existence requires live validation against Grail API.
- **Phase gates** — Every phase must have complete tests, documentation, and memory updates before moving to the next phase.
