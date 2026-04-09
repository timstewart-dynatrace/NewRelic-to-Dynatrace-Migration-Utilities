# New Relic to Dynatrace Migration Tool

A comprehensive migration framework for converting New Relic monitoring configurations to Dynatrace.

## Features

- **Full Migration Pipeline** - Export → Transform → Import
- **NRQL to DQL Converter** - Standalone query conversion utility
- **Selective Migration** - Choose specific components to migrate
- **Dry Run Mode** - Validate without making changes
- **Rich CLI Output** - Progress indicators and detailed reports

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

## Usage

### Migration Tool

```bash
# Full migration
python migrate.py --full

# Dry run (validate without changes)
python migrate.py --dry-run --full

# Export only
python migrate.py --export-only --output ./exports

# Import only
python migrate.py --import-only --input ./exports

# Specific components
python migrate.py --components dashboards,alerts,synthetics

# List available components
python migrate.py --list-components
```

### NRQL to DQL Converter

```bash
# Convert a single query
python nrql_to_dql.py "SELECT average(duration) FROM Transaction WHERE appName = 'MyApp'"

# Interactive mode
python nrql_to_dql.py --interactive

# Show reference table
python nrql_to_dql.py --reference

# Convert from file
python nrql_to_dql.py --file queries.txt --output converted.dql
```

## Supported Components

| Component | New Relic | Dynatrace |
|-----------|-----------|-----------|
| Dashboards | Dashboard (multi-page) | Dashboard (per page) |
| Alerts | Alert Policy + Conditions | Alerting Profile + Metric Events |
| Synthetics | Ping/Browser/API Monitors | HTTP/Browser Monitors |
| SLOs | Service Level Objectives | SLOs |
| Workloads | Entity Groupings | Management Zones |
| Notifications | Channels | Problem Notifications |

## NRQL to DQL Quick Reference

| NRQL | DQL |
|------|-----|
| `SELECT * FROM Log` | `fetch logs` |
| `SELECT count(*) FROM Transaction` | `fetch ... \| summarize count()` |
| `WHERE field = 'value'` | `\| filter field == "value"` |
| `WHERE field LIKE '%pattern%'` | `\| filter matchesPhrase(field, "...")` |
| `FACET fieldName` | `\| summarize by: {fieldName}` |
| `SINCE 1 hour ago` | `from:now()-1h` |
| `LIMIT 100` | `\| limit 100` |
| `average(field)` | `avg(field)` |
| `uniqueCount(field)` | `countDistinct(field)` |
| `percentile(field, 95)` | `percentile(field, 95)` |

## Project Structure

```
newrelic-to-dynatrace-migration/
├── migrate.py              # Main migration CLI (click + rich)
├── pyproject.toml          # pytest configuration
├── requirements.txt        # Dependencies
├── .env.example            # Environment template
│
├── compiler/               # NRQL-to-DQL AST compiler
│   ├── tokens.py           # TokenType enum, Token dataclass
│   ├── lexer.py            # NRQLLexer (tokenization)
│   ├── ast_nodes.py        # 18 AST node classes
│   ├── parser.py           # NRQLParser (recursive descent)
│   ├── emitter.py          # DQLEmitter (context-aware DQL generation)
│   └── compiler.py         # NRQLCompiler (orchestrator + validation)
│
├── config/
│   └── settings.py         # Configuration management (pydantic)
│
├── clients/
│   ├── newrelic_client.py  # New Relic NerdGraph client
│   └── dynatrace_client.py # Dynatrace API client
│
├── transformers/
│   ├── mapping_rules.py    # Entity/visualization/chart mappings
│   ├── nrql_mapping_rules.py # NRQL field/metric/aggregation maps
│   ├── nrql_converter.py   # NRQLtoDQLConverter (compiler + post-processing)
│   ├── converters.py       # Specialized converters (regex→DPL, rate, etc.)
│   ├── dashboard_transformer.py
│   ├── alert_transformer.py
│   ├── synthetic_transformer.py
│   ├── slo_transformer.py
│   └── workload_transformer.py
│
├── validators/
│   ├── dql_validator.py    # DQL syntax validator (9 regex rules)
│   └── dql_fixer.py        # DQL auto-fixer (19 fix rules)
│
├── utils/
│   ├── logger.py           # Structured logging (structlog)
│   └── validators.py       # Configuration validators
│
└── tests/
    ├── conftest.py          # Shared fixtures
    └── unit/
        ├── test_compiler.py          # 282 compiler tests
        ├── test_transformers.py      # Transformer tests
        ├── test_converters.py        # Specialized converter tests
        ├── test_mapping_rules.py     # EntityMapper tests
        ├── test_dql_validator.py     # DQL validator tests
        ├── test_dql_fixer.py         # DQL fixer tests
        └── test_utils_validators.py  # Config validator tests
```

## Output

After running migration:

```
output/
├── exports/
│   └── newrelic_export.json       # Raw New Relic data
├── transformed/
│   └── dynatrace_config.json      # Transformed configs
└── reports/
    └── migration_report_*.json    # Detailed results
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

1. **NRQL to DQL** - AST compiler covers 282 tested patterns; complex or custom queries may require manual review
2. **Scripted Synthetics** - Complex scripts need manual recreation
3. **Entity References** - GUIDs don't map to Dynatrace entity IDs
4. **Dashboard Variables** - Limited filter conversion
5. **Dynamic Baselines** - Require manual configuration

## License

MIT License
