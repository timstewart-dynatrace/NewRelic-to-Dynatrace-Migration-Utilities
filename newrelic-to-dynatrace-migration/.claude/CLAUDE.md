# New Relic to Dynatrace Migration Tool

**ALWAYS** ask clarifying questions and **ALWAYS** provide a plan **BEFORE** making changes.

## Project Summary

Universal migration tool for converting New Relic monitoring configurations to Dynatrace. Migrates dashboards (with a real NRQL-to-DQL compiler), alerts, synthetic monitors, SLOs, and workloads. Three-phase pipeline: Export (NR NerdGraph) -> Transform -> Import (DT APIs).

**Last Updated:** 2026-04-09
**Version:** 0.2.0
**Phases Completed:** 0 (Consolidation), 1 (Compiler Enhancements)

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Runtime | Python 3.9+ | Broad compatibility |
| Config | Pydantic + python-dotenv | Typed settings from .env |
| CLI | Click + Rich | Subcommands with progress display |
| Logging | structlog | Structured logging |
| HTTP | requests | API clients |
| Testing | pytest | 673 tests (292 compiler + 14 CLI + 367 transformer/validator/converter/mapping) |

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

NRQL Compiler Pipeline:
  NRQL string -> Lexer -> Token[] -> Parser -> AST -> DQLEmitter -> DQL string
```

### Transformer Interface Standard

All transformers follow a consistent pattern (standardized in Phase 0):
- **Result class**: `{Entity}TransformResult` dataclass with `success`, `warnings`, `errors`
- **Method**: `transform(nr_entity) -> {Entity}TransformResult` (single item)
- **Batch**: `transform_all(items) -> List[{Entity}TransformResult]`
- **NRQL results**: `ConversionResult` with `dql`, `fixes`, `warnings`, `confidence`

See `.claude/rules/architecture.md` for the full component map.

## Essential Commands

```bash
# Setup
pip install -r requirements.txt
cp .env.example .env  # then edit with your credentials

# CLI commands
python migrate.py compile "SELECT count(*) FROM Transaction"      # Single query
python migrate.py compile --interactive                            # REPL mode
python migrate.py compile --file queries.nrql --output results.dql # Batch
python migrate.py convert "SELECT avg(duration) FROM Transaction"  # With post-processing
python migrate.py reference                                        # Quick reference table
python migrate.py reference --mappings                             # Full mapping tables
python migrate.py migrate --list-components  # Show available components
python migrate.py migrate --dry-run          # Validate without applying
python migrate.py migrate --full             # Full migration
python migrate.py migrate --export-only      # Just pull from NR
python migrate.py migrate --components dashboards,alerts  # Specific components

# Testing
pytest tests/ -v
pytest tests/ --cov=. --cov-report=html
```

## Key Directories

| Path | Purpose |
|------|---------|
| `compiler/` | NRQL-to-DQL AST compiler (6 files: tokens, lexer, ast_nodes, parser, emitter, compiler) |
| `clients/` | NR NerdGraph + DT API clients with retry/backoff |
| `transformers/` | Entity transformers + NRQL converter + mapping tables |
| `validators/` | DQL syntax validator + 19-rule auto-fixer |
| `config/` | Pydantic BaseSettings from .env |
| `utils/` | Logging, validators |
| `examples/` | Sample NRQL queries for batch testing |
| `tests/` | 673 pytest tests (compiler, CLI, transformers, validators, converters, mapping rules) |

## Rules

### Always active
@.claude/rules/architecture.md
@.claude/rules/python.md
@.claude/rules/testing.md
@.claude/rules/dql-reference.md

## Key Constraints

- **No hardcoded credentials** — all secrets via .env / environment variables
- **Compiler vs Converter** — `compiler/` handles pure NRQL->DQL translation. `transformers/nrql_converter.py` wraps it with post-processing and auto-fixes. `transformers/dashboard_transformer.py` orchestrates widget/layout conversion.
- **DQL validation** — structurally valid DQL doesn't guarantee data returns. Field existence requires live validation against Grail API.
- **Mapping tables** — `transformers/nrql_mapping_rules.py` has the enhanced tables (230 metrics, 72 attrs). `transformers/mapping_rules.py` has entity/viz mappings used by all transformers.
- **Phase gates** — Every phase must have complete tests, documentation, and memory updates before moving to the next phase.
