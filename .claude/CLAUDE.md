# New Relic to Dynatrace Migration Tool

**ALWAYS** ask clarifying questions and **ALWAYS** provide a plan **BEFORE** making changes.

## Project Summary

Universal migration tool for converting New Relic monitoring configurations to Dynatrace. Migrates dashboards (with a real NRQL-to-DQL compiler), alerts, synthetic monitors, SLOs, and workloads. Three-phase pipeline: Export (NR NerdGraph) -> Transform -> Import (DT APIs). Supports config-as-code export (Monaco, Terraform).

**Last Updated:** 2026-04-09
**Version:** 1.3.0
**Phases Completed:** 0-10 (all complete)

## Quick Reference

```bash
# Run tests (894 unit + 8 integration across 28 files)
pytest tests/ -v

# Integration tests (requires .env with real credentials)
RUN_INTEGRATION_TESTS=1 pytest tests/integration/ -v

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

# Full migration
python migrate.py migrate --dry-run          # Preview what would be created
python migrate.py migrate --full             # Execute migration
python migrate.py migrate --diff             # Compare against live DT
python migrate.py migrate --retry failed.json # Retry failed entities

# Config-as-code export
python migrate.py export-monaco --input ./output --output ./monaco-out
python migrate.py export-terraform --input ./output --output ./tf-out

# SLO audit
python migrate.py audit-slos

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
| Testing | pytest | 920 unit + 8 integration tests across 29 files |

## Architecture

```
EXPORT (NR NerdGraph)  ->  TRANSFORM  ->  IMPORT (DT APIs)
                                      ->  EXPORT (Monaco / Terraform)

Transformers (10):                     Targets:
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
| `compiler/` | NRQL-to-DQL AST compiler (292 tested patterns) |
| `clients/` | NR NerdGraph + DT API clients (Config v1 + Documents v2 + Settings v2) |
| `transformers/` | 10 entity transformers + NRQL converter + mapping tables |
| `validators/` | DQL syntax validator + 19-rule auto-fixer |
| `registry/` | DTEnvironmentRegistry (live validation) + SLOAuditor |
| `migration/` | Rollback, checkpoint, incremental, reports, retry, diff |
| `exporters/` | Monaco YAML + Terraform HCL config-as-code exporters |
| `config/` | Pydantic BaseSettings from .env |
| `utils/` | Logging, auth (OAuth), validators |
| `examples/` | Sample NRQL queries for batch testing |
| `tests/` | 920 unit + 8 integration tests across 29 files |

## Rules

### Always active
@.claude/rules/architecture.md
@.claude/rules/python.md
@.claude/rules/testing.md
@.claude/rules/development.md
@.claude/rules/deployment.md

## Skills (domain knowledge)

### Always active
@/Users/Shared/GitHub/PROJECTS/VisualCode-AI-Template/SKILLS/dynatrace-dql/SKILL.md
@/Users/Shared/GitHub/PROJECTS/VisualCode-AI-Template/SKILLS/nrql-to-dql/SKILL.md
@/Users/Shared/GitHub/PROJECTS/VisualCode-AI-Template/SKILLS/dynatrace-apis/SKILL.md
@/Users/Shared/GitHub/PROJECTS/VisualCode-AI-Template/SKILLS/dynatrace-document-api/SKILL.md
@/Users/Shared/GitHub/PROJECTS/VisualCode-AI-Template/SKILLS/dynatrace-monaco/SKILL.md
@/Users/Shared/GitHub/PROJECTS/VisualCode-AI-Template/SKILLS/dynatrace-terraform/SKILL.md

## Key Constraints

- **No hardcoded credentials** — all secrets via .env / environment variables
- **Community project** — not officially supported by Dynatrace
- **Feature branches** — never commit features directly to main
- **Compiler vs Converter** — `compiler/` handles pure NRQL->DQL translation. `transformers/nrql_converter.py` wraps it with post-processing and auto-fixes.
- **DQL validation** — structurally valid DQL doesn't guarantee data returns. Field existence requires live validation against Grail API.
- **Phase gates** — Every phase must have complete tests, documentation, and memory updates before moving to the next phase.
