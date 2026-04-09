# Dynatrace-NewRelic

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> **⚠️ DISCLAIMER:** This project is not officially supported by Dynatrace. It is provided as-is for community use. Use at your own discretion and risk. For official Dynatrace migration support, please contact your Dynatrace account team.

Utilities for migrating from New Relic to Dynatrace.

## New Relic to Dynatrace Migration Framework

A universal, comprehensive migration framework for converting New Relic monitoring configurations to Dynatrace. Includes a built-in NRQL-to-DQL compiler with 282+ tested patterns.

**Location:** [`newrelic-to-dynatrace-migration/`](newrelic-to-dynatrace-migration/)

### Architecture

![Architecture Overview](docs/images/architecture-overview.svg)

### Supported Components

| Component         | New Relic                      | →   | Dynatrace                        | Status  |
| ----------------- | ------------------------------ | --- | -------------------------------- | ------- |
| **Dashboards**    | Dashboard (multi-page)         | →   | Dashboard                        | ✅ Full |
| **Alerts**        | Alert Policy + NRQL Conditions | →   | Alerting Profile + Metric Events | ✅ Full |
| **Synthetics**    | Ping/Browser/API Monitors      | →   | HTTP/Browser Monitors            | ✅ Full |
| **SLOs**          | Service Level Objectives       | →   | SLOs                             | ✅ Full |
| **Workloads**     | Entity Groupings               | →   | Management Zones                 | ✅ Full |
| **Notifications** | Channels (Email, Slack, etc.)  | →   | Problem Notifications            | ✅ Full |

### Pipeline

![Pipeline Architecture](docs/images/pipeline.svg)

### Quick Start

```bash
# Install
cd newrelic-to-dynatrace-migration
pip install -r requirements.txt

# Configure (create .env file)
NEW_RELIC_API_KEY=NRAK-XXXXXXXXXXXXXXXXXXXXXXXXXXXX
NEW_RELIC_ACCOUNT_ID=1234567
DYNATRACE_API_TOKEN=dt0c01.XXXXXXXXXXXXXXXXXXXXXXXX
DYNATRACE_ENVIRONMENT_URL=https://abc12345.live.dynatrace.com

# Run migration
python migrate.py --dry-run --full  # Validate first
python migrate.py --full            # Execute migration
```

### CLI Reference

| Command                                            | Description                                      |
| -------------------------------------------------- | ------------------------------------------------ |
| `python migrate.py migrate --full`                 | Complete migration (export → transform → import) |
| `python migrate.py migrate --export-only`          | Export from New Relic only                       |
| `python migrate.py migrate --import-only --input ./path` | Import to Dynatrace from previous export   |
| `python migrate.py migrate --components dashboards,alerts` | Migrate specific components              |
| `python migrate.py migrate --dry-run`              | Validate without making changes                  |
| `python migrate.py migrate --list-components`      | List available components                        |
| `python migrate.py compile "SELECT ..."`           | Compile a single NRQL query to DQL               |
| `python migrate.py compile --interactive`          | Interactive REPL for ad-hoc query conversion     |
| `python migrate.py compile --file queries.nrql`    | Batch compile queries from file                  |
| `python migrate.py compile --file q.nrql --output r.dql` | Batch compile with output file             |
| `python migrate.py convert "SELECT ..."`           | Compile with post-processing and auto-fixes      |
| `python migrate.py reference`                      | Show NRQL→DQL quick reference table              |
| `python migrate.py reference --mappings`           | Show full mapping tables                         |

### Entity Mapping

![Entity Mapping](docs/images/entity-mapping.svg)

| New Relic           | Dynatrace                 | Notes                                  |
| ------------------- | ------------------------- | -------------------------------------- |
| Dashboard           | Dashboard                 | Each page becomes a separate dashboard |
| Alert Policy        | Alerting Profile          | 1:1 mapping                            |
| NRQL Condition      | Metric Event              | Query conversion (limited automation)  |
| APM Condition       | Auto-Adaptive Baseline    | Manual review recommended              |
| Synthetic (Ping)    | HTTP Monitor              | Direct mapping                         |
| Synthetic (Browser) | Browser Monitor           | Script adaptation needed               |
| Synthetic (API)     | HTTP Monitor (Multi-step) | Script adaptation needed               |
| SLO                 | SLO                       | Metric expression mapping              |
| Workload            | Management Zone           | Entity selector rules                  |
| Email Channel       | Email Notification        | Direct mapping                         |
| Slack Channel       | Slack Notification        | Webhook URL update needed              |
| PagerDuty           | PagerDuty Integration     | Service key recreation                 |
| Webhook             | Webhook Notification      | Payload format adjustment              |

---

## Project Structure

```
Dynatrace-NewRelic/
├── README.md                              # This file
├── .gitignore
├── docs/
│   └── images/                            # SVG diagrams
│
└── newrelic-to-dynatrace-migration/       # Migration framework
    ├── migrate.py                         # CLI entry point (migrate, compile, convert, reference)
    ├── pyproject.toml                     # pytest configuration
    ├── requirements.txt                   # Python dependencies
    ├── .env.example                       # Environment template
    │
    ├── compiler/                          # NRQL-to-DQL AST compiler
    │   ├── tokens.py                      # TokenType enum, Token dataclass
    │   ├── lexer.py                       # NRQLLexer (tokenization)
    │   ├── ast_nodes.py                   # 18 AST node classes
    │   ├── parser.py                      # NRQLParser (recursive descent)
    │   ├── emitter.py                     # DQLEmitter (context-aware DQL generation)
    │   └── compiler.py                    # NRQLCompiler (orchestrator + validation)
    │
    ├── config/
    │   └── settings.py                    # Configuration (pydantic)
    │
    ├── clients/
    │   ├── newrelic_client.py             # NerdGraph GraphQL client
    │   └── dynatrace_client.py            # Settings API v2 + Config API v1 client
    │
    ├── transformers/
    │   ├── mapping_rules.py               # Entity/visualization/chart mappings
    │   ├── nrql_mapping_rules.py          # NRQL field/metric/aggregation maps (230+72+43)
    │   ├── nrql_converter.py              # NRQLtoDQLConverter (AST + post-processing)
    │   ├── converters.py                  # Specialized converters (regex→DPL, rate, etc.)
    │   ├── dashboard_transformer.py       # Dashboard page→dashboard conversion
    │   ├── alert_transformer.py           # Alert policy→alerting profile + metric events
    │   ├── synthetic_transformer.py       # Monitor→HTTP/Browser monitor
    │   ├── slo_transformer.py             # SLO→SLO with type detection
    │   └── workload_transformer.py        # Workload→management zone
    │
    ├── validators/
    │   ├── dql_validator.py               # DQL syntax validator (9 regex rules)
    │   └── dql_fixer.py                   # DQL auto-fixer (19 fix rules)
    │
    ├── examples/
    │   └── example_queries.nrql           # Sample NRQL queries for testing
    │
    ├── utils/
    │   ├── logger.py                      # Structured logging (structlog)
    │   └── validators.py                  # Config & structure validators
    │
    └── tests/
        ├── conftest.py                    # Shared fixtures
        └── unit/
            ├── test_compiler.py           # 282 compiler tests (25 classes)
            ├── test_cli.py                # CLI command tests (interactive, batch, reference)
            ├── test_transformers.py       # All 5 transformer tests
            ├── test_converters.py         # Specialized converter tests
            ├── test_mapping_rules.py      # EntityMapper + mapping dict tests
            ├── test_dql_validator.py       # DQL syntax validator tests
            ├── test_dql_fixer.py          # DQL auto-fixer tests
            └── test_utils_validators.py   # Config validator tests
```

## Required API Permissions

### New Relic API Key

| Permission            | Required For                  |
| --------------------- | ----------------------------- |
| NerdGraph access      | All exports                   |
| Dashboards (read)     | Dashboard export              |
| Alerts (read)         | Alert policy/condition export |
| Synthetics (read)     | Monitor export                |
| Service Levels (read) | SLO export                    |
| Workloads (read)      | Workload export               |

### Dynatrace API Token

| Scope                          | Required For                                 |
| ------------------------------ | -------------------------------------------- |
| `settings.read`                | Reading existing configs                     |
| `settings.write`               | Creating alerting profiles, management zones |
| `WriteConfig`                  | Creating dashboards                          |
| `ReadConfig`                   | Reading existing configs                     |
| `ExternalSyntheticIntegration` | Creating synthetic monitors                  |
| `slo.read` / `slo.write`       | SLO operations                               |

## Known Limitations

| Area                    | Limitation                                            | Workaround             |
| ----------------------- | ----------------------------------------------------- | ---------------------- |
| **NRQL → DQL**          | AST compiler covers 282 tested patterns; edge cases may need review | Manual query review    |
| **Scripted Synthetics** | Complex scripts not converted                         | Manual recreation      |
| **Entity References**   | GUIDs don't map to DT IDs                             | Manual linking         |
| **Dashboard Variables** | Limited filter conversion                             | Manual configuration   |
| **Dynamic Baselines**   | Not automatically converted                           | Manual threshold setup |
| **Historical Data**     | Not transferable                                      | N/A                    |

## Related Resources

- [New Relic NerdGraph API](https://docs.newrelic.com/docs/apis/nerdgraph/)
- [Dynatrace Settings API v2](https://docs.dynatrace.com/docs/dynatrace-api/environment-api/settings)
- [Dynatrace Monaco CLI](https://docs.dynatrace.com/docs/deliver/configuration-as-code/monaco)
- [Dynatrace Terraform Provider](https://github.com/dynatrace-oss/terraform-provider-dynatrace)

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## License

MIT License - See LICENSE file for details.
