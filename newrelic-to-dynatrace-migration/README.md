# New Relic to Dynatrace Migration Tool

A comprehensive migration framework for converting New Relic monitoring configurations to Dynatrace.

## Features

- **Full Migration Pipeline** — Export → Transform → Import
- **AST-Based NRQL Compiler** — 292 tested patterns with formal lexer/parser/emitter
- **Interactive REPL** — Ad-hoc query conversion with `compile --interactive`
- **Batch Processing** — Convert query files with `compile --file`
- **Selective Migration** — Choose specific components to migrate
- **Dry Run Mode** — Validate without making changes
- **DQL Auto-Fixer** — 19 fix rules for common DQL issues
- **Rich CLI Output** — Progress indicators and detailed reports

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
# New Relic
NEW_RELIC_API_KEY=NRAK-XXXXXXXXXXXXXXXXXXXXXXXXXXXX
NEW_RELIC_ACCOUNT_ID=1234567
NEW_RELIC_REGION=US  # or EU

# Dynatrace
DYNATRACE_API_TOKEN=dt0c01.XXXXXXXXXXXXXXXXXXXXXXXX
DYNATRACE_ENVIRONMENT_URL=https://abc12345.live.dynatrace.com
```

## CLI Commands

### Migration

```bash
python migrate.py migrate --full                         # Full migration
python migrate.py migrate --dry-run                      # Validate without changes
python migrate.py migrate --export-only --output ./out   # Export only
python migrate.py migrate --import-only --input ./out    # Import only
python migrate.py migrate --components dashboards,alerts # Specific components
python migrate.py migrate --list-components              # List available components
```

### NRQL Compilation

```bash
# Single query (raw AST compilation)
python migrate.py compile "SELECT count(*) FROM Transaction FACET appName"

# Interactive REPL (type 'quit' to exit, 'ref' for reference)
python migrate.py compile --interactive

# Batch compile from file
python migrate.py compile --file queries.nrql

# Batch compile with output file
python migrate.py compile --file queries.nrql --output results.dql
```

### NRQL Conversion (with post-processing)

```bash
# Compile + auto-fix + validation
python migrate.py convert "SELECT avg(duration) FROM Transaction WHERE appName = 'api'"
```

### Reference Tables

```bash
# Quick reference (NRQL→DQL syntax mapping)
python migrate.py reference

# Full mapping tables (aggregations, event types, attributes)
python migrate.py reference --mappings
```

### Testing

```bash
pytest tests/ -v                    # All 747 tests
pytest tests/unit/test_compiler.py  # 292 compiler tests only
pytest tests/unit/test_cli.py       # 14 CLI tests only
pytest -x --tb=short               # Stop on first failure
pytest --cov=. --cov-report=html   # Coverage report
```

## Architecture

```
EXPORT (NR NerdGraph)  →  TRANSFORM  →  IMPORT (DT APIs)

NRQL Compiler Pipeline:
  NRQL string → Lexer → Token[] → Parser → AST → DQLEmitter → DQL string

Transformers:                              Targets:
  DashboardTransformer (AST compiler)        Dashboards (Documents API)
  AlertTransformer                           Alerting Profiles + Metric Events
  SyntheticTransformer                       HTTP/Browser Monitors
  SLOTransformer                             SLOs
  WorkloadTransformer                        Management Zones
  NotificationTransformer                    Problem Notifications
```

### Transformer Interface Standard

All transformers follow a consistent interface:

- **Result class**: `{Entity}TransformResult` dataclass with `success`, `warnings`, `errors`
- **Method**: `transform(nr_entity) → {Entity}TransformResult`
- **Batch**: `transform_all(items) → List[{Entity}TransformResult]`

## Supported Components

| Component | New Relic | Dynatrace |
|-----------|-----------|-----------|
| Dashboards | Dashboard (multi-page) | Dashboard (per page) |
| Alerts | Alert Policy + Conditions | Alerting Profile + Metric Events |
| Synthetics | Ping/Browser/API Monitors | HTTP/Browser Monitors |
| SLOs | Service Level Objectives | SLOs |
| Workloads | Entity Groupings | Management Zones |
| Notifications | Channels (Email, Slack, etc.) | Problem Notifications |

## Project Structure

```
newrelic-to-dynatrace-migration/
├── migrate.py              # CLI entry point (migrate, compile, convert, reference)
├── pyproject.toml          # Project config + pytest settings
├── requirements.txt        # Dependencies
├── .env.example            # Environment template
│
├── compiler/               # NRQL-to-DQL AST compiler (292 tested patterns)
│   ├── tokens.py           # TokenType enum, Token dataclass
│   ├── lexer.py            # NRQLLexer (tokenization)
│   ├── ast_nodes.py        # 18 AST node classes
│   ├── parser.py           # NRQLParser (recursive descent)
│   ├── emitter.py          # DQLEmitter (context-aware DQL generation)
│   └── compiler.py         # NRQLCompiler (orchestrator + validation)
│
├── config/
│   └── settings.py         # Pydantic BaseSettings from .env
│
├── clients/
│   ├── newrelic_client.py  # NerdGraph GraphQL (pagination, rate limit, retry)
│   └── dynatrace_client.py # Settings API v2 + Config API v1
│
├── transformers/
│   ├── mapping_rules.py    # Entity/visualization/chart mappings
│   ├── nrql_mapping_rules.py # NRQL field/metric/aggregation maps (230+72+90)
│   ├── nrql_converter.py   # NRQLtoDQLConverter (compiler + post-processing)
│   ├── converters.py       # Specialized: RegexToDPL, Aparse, Rate, CompareWith, etc.
│   ├── dashboard_transformer.py
│   ├── alert_transformer.py  # + NotificationTransformer
│   ├── synthetic_transformer.py
│   ├── slo_transformer.py
│   └── workload_transformer.py
│
├── validators/
│   ├── dql_validator.py    # DQL syntax validator (9 regex rules)
│   └── dql_fixer.py        # DQL auto-fixer (19 fix rules)
│
├── examples/
│   └── example_queries.nrql # Sample NRQL queries for testing
│
├── utils/
│   ├── logger.py           # structlog configuration
│   └── validators.py       # Config & structure validators
│
└── tests/                  # 747 tests across 9 files
    ├── conftest.py
    └── unit/
        ├── test_compiler.py           # 292 compiler tests
        ├── test_cli.py                # 14 CLI tests
        ├── test_transformers.py       # 77 transformer tests
        ├── test_converters.py         # Specialized converter tests
        ├── test_mapping_rules.py      # EntityMapper tests
        ├── test_nrql_mapping_rules.py # Mapping table tests
        ├── test_dql_validator.py      # DQL validator tests
        ├── test_dql_fixer.py          # DQL fixer tests
        └── test_utils_validators.py   # Config validator tests
```

## API Permissions Required

### New Relic
- NerdGraph access
- Dashboards (read)
- Alerts (read)
- Synthetics (read)
- Service Levels (read)
- Workloads (read)

### Dynatrace
- `settings.read` / `settings.write`
- `WriteConfig` / `ReadConfig`
- `ExternalSyntheticIntegration`
- `slo.read` / `slo.write`

## Known Limitations

1. **NRQL to DQL** — AST compiler covers 292 tested patterns; complex or custom queries may require manual review
2. **Scripted Synthetics** — Complex scripts need manual recreation
3. **Entity References** — NR GUIDs don't map to Dynatrace entity IDs
4. **Dashboard Variables** — Limited filter conversion
5. **Dynamic Baselines** — Require manual configuration

## License

MIT License
