# New Relic to Dynatrace Migration Tool

**ALWAYS** ask clarifying questions and **ALWAYS** provide a plan **BEFORE** making changes.

## Project Summary

Universal migration tool for converting New Relic monitoring configurations to Dynatrace. Migrates dashboards (with a real NRQL-to-DQL compiler), alerts, synthetic monitors, SLOs, and workloads. Three-phase pipeline: Export (NR NerdGraph) -> Transform -> Import (DT APIs).

**Last Updated:** 2026-04-08

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Runtime | Python 3.9+ | Broad compatibility |
| Config | Pydantic + python-dotenv | Typed settings from .env |
| CLI | Click + Rich | Subcommands with progress display |
| Logging | structlog | Structured logging |
| HTTP | requests | API clients |
| Testing | pytest | 649 tests (282 compiler + 367 transformer/validator/converter/mapping) |

## Architecture

```
EXPORT (NR NerdGraph)  ->  TRANSFORM  ->  IMPORT (DT APIs)

Transformers:                          Targets:
  DashboardTransformer (AST compiler)    Dashboards (Documents API)
  AlertTransformer                       Alerting Profiles + Metric Events
  SyntheticTransformer                   HTTP/Browser Monitors
  SLOTransformer                         SLOs
  WorkloadTransformer                    Management Zones

NRQL Compiler Pipeline:
  NRQL string -> Lexer -> Token[] -> Parser -> AST -> DQLEmitter -> DQL string
```

See `.claude/rules/architecture.md` for the full component map.

## Essential Commands

```bash
# Setup
pip install -r requirements.txt
cp .env.example .env  # then edit with your credentials

# CLI commands
python migrate.py compile "SELECT count(*) FROM Transaction"  # Single query
python migrate.py convert "SELECT avg(duration) FROM Transaction"  # With post-processing
python migrate.py migrate --list-components  # Show available components
python migrate.py migrate --dry-run  # Validate without applying
python migrate.py migrate --full  # Full migration
python migrate.py migrate --export-only  # Just pull from NR
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
| `tests/` | 649 pytest tests (compiler, transformers, validators, converters, mapping rules) |

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
