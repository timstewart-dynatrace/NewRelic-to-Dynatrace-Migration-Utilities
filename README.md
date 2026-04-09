# Dynatrace-NewRelic

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> **⚠️ DISCLAIMER:** This project is not officially supported by Dynatrace. It is provided as-is for community use. Use at your own discretion and risk. For official Dynatrace migration support, please contact your Dynatrace account team.

Utilities for migrating from New Relic to Dynatrace.

## New Relic to Dynatrace Migration Framework

A universal, comprehensive migration framework for converting New Relic monitoring configurations to Dynatrace. Includes a built-in NRQL-to-DQL compiler with 292 tested patterns and 894 tests.

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
pip install -r requirements.txt

# Configure (create .env file)
cp .env.example .env
# Edit .env with your credentials

# Run migration
python migrate.py migrate --dry-run  # Validate first
python migrate.py migrate --full     # Execute migration
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
| `python migrate.py batch --file queries.csv`       | Batch compile from CSV/Excel file                |
| `python migrate.py audit-slos`                     | Audit SLOs for metric validity                   |
| `python migrate.py export-monaco --input ./output` | Export as Monaco config-as-code (YAML)           |
| `python migrate.py export-terraform --input ./output` | Export as Terraform HCL                       |
| `python migrate.py migrate --diff`                 | Compare against live DT environment              |
| `python migrate.py migrate --retry failed.json`    | Retry previously failed entities                 |
| `python migrate.py migrate --report`               | Generate conversion quality report               |
| `python migrate.py --version`                      | Show version                                     |

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
├── migrate.py                     # CLI entry point (migrate, compile, convert, reference, batch, export)
├── pyproject.toml                 # Project config + pip install
├── requirements.txt               # Python dependencies
├── .env.example                   # Environment template
├── _version.py                    # Version (1.2.0)
│
├── compiler/                      # NRQL-to-DQL AST compiler (292 tested patterns)
├── clients/                       # NR NerdGraph + DT API clients
├── config/                        # Pydantic settings from .env
├── transformers/                  # 10 entity transformers + NRQL converter
├── validators/                    # DQL syntax validator + auto-fixer
├── registry/                      # DTEnvironmentRegistry + SLOAuditor
├── migration/                     # Rollback, checkpoint, retry, diff, reports
├── exporters/                     # Monaco YAML + Terraform HCL exporters
├── utils/                         # Logging, auth, validators
├── examples/                      # Sample NRQL queries
├── tests/                         # 894 tests across 25 files
│
├── docs/                          # SVG diagrams + migration research
├── .github/workflows/ci.yml       # CI pipeline
└── CHANGELOG.md
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
| **NRQL → DQL**          | AST compiler covers 292 tested patterns; edge cases may need review | Manual query review    |
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
