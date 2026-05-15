# Architecture

## Project Structure

```
NewRelic-to-Dynatrace-Migration-Utilities/
├── migrate.py                         # CLI entry point (migrate, compile, convert, reference, batch, audit-slos)
├── _version.py                        # Version (1.3.0)
├── pyproject.toml                     # Project config, pip install, pytest
├── requirements.txt                   # Python dependencies
├── .env.example                       # Environment template
│
├── compiler/                          # NRQL-to-DQL AST compiler (292 tested patterns)
│   ├── tokens.py                      # TokenType enum, Token dataclass, KEYWORDS
│   ├── lexer.py                       # NRQLLexer (tokenization, preserves regex escapes)
│   ├── ast_nodes.py                   # 18 AST node classes
│   ├── parser.py                      # NRQLParser (recursive descent)
│   ├── emitter.py                     # DQLEmitter (context-aware DQL generation)
│   └── compiler.py                    # NRQLCompiler (orchestrator + validation)
│
├── clients/                           # API clients
│   ├── newrelic_client.py             # NerdGraph GraphQL (pagination, rate limit, retry)
│   └── dynatrace_client.py           # Settings API v2 + Config API v1 + Documents API v2
│
├── transformers/                      # 10 entity transformers
│   ├── mapping_rules.py              # EntityMapper, VISUALIZATION_TYPE_MAP, CHART_TYPE_MAP
│   ├── nrql_mapping_rules.py         # METRIC_MAP (230), ATTR_MAP (72), AGG_MAP (90+), EVENT_TYPE_MAP (34)
│   ├── nrql_converter.py             # NRQLtoDQLConverter (compiler + post-processing + auto-fix)
│   ├── converters.py                 # Specialized: RegexToDPL, Aparse, Rate, CompareWith, Funnel, etc.
│   ├── dashboard_transformer.py      # NR Dashboard -> DT Dashboard
│   ├── alert_transformer.py          # NR Alert Policy -> DT Alerting Profile + Metric Events
│   ├── synthetic_transformer.py      # NR Monitors -> DT HTTP/Browser Monitors
│   ├── slo_transformer.py            # NR SLO -> DT SLO
│   ├── workload_transformer.py       # NR Workload -> DT Management Zone
│   ├── infrastructure_transformer.py # NR Infra Conditions -> DT Metric Events
│   ├── log_parsing_transformer.py    # NR Log Rules -> DT Processing Rules (DPL)
│   ├── tag_transformer.py            # NR Tags -> DT Auto-Tag Rules
│   └── drop_rule_transformer.py      # NR Drop Rules -> DT Ingest Rules
│
├── validators/                        # DQL validation
│   ├── dql_validator.py              # Structural syntax validator (9 regex rules)
│   └── dql_fixer.py                  # Auto-fixer (19 fix rules)
│
├── registry/                          # Live environment validation
│   ├── environment.py                # DTEnvironmentRegistry (metrics, entities, dashboards, mgmt zones, locations)
│   └── slo_auditor.py               # SLOAuditor (metric extraction, validation, fuzzy search)
│
├── migration/                         # Migration infrastructure
│   ├── state.py                      # RollbackManifest, EntityIdMap, Checkpoint, IncrementalState
│   ├── report.py                     # ConversionReport (JSON + HTML)
│   ├── retry.py                      # FailedEntities (save/load/filter for partial retry)
│   └── diff.py                       # DiffReport (compare transformed vs live DT)
│
├── exporters/                         # Config-as-code exporters
│   ├── monaco.py                     # Monaco v2 YAML project structure
│   └── terraform.py                  # Terraform HCL with dynatrace provider
│
├── config/
│   └── settings.py                   # Pydantic BaseSettings (NR + DT + Migration config)
│
├── utils/
│   ├── logger.py                     # structlog configuration
│   ├── auth.py                       # OAuth flow, auth header detection, duration conversion
│   └── validators.py                 # Config validators (NR key format, DT token format)
│
├── examples/
│   └── example_queries.nrql          # Sample NRQL queries for batch testing
│
└── tests/                            # 920 unit + 8 integration tests across 29 files
    ├── conftest.py
    └── unit/
        ├── test_compiler.py          # 292 compiler tests (25+ classes)
        ├── test_cli.py               # CLI command tests (interactive, batch, reference, version)
        ├── test_transformers.py      # Dashboard, Alert, Notification, Synthetic, SLO, Workload
        ├── test_infrastructure_transformer.py
        ├── test_log_parsing_transformer.py
        ├── test_tag_transformer.py
        ├── test_drop_rule_transformer.py
        ├── test_converters.py        # RegexToDPL, Aparse, Rate, CompareWith, Funnel
        ├── test_mapping_rules.py     # EntityMapper + mapping dicts
        ├── test_nrql_mapping_rules.py
        ├── test_dql_validator.py
        ├── test_dql_fixer.py
        ├── test_utils_validators.py
        ├── test_newrelic_client.py    # 24 NR client tests (mocked HTTP)
        ├── test_dynatrace_client.py   # 29 DT client tests (mocked HTTP)
        ├── test_settings.py           # 13 config tests
        ├── test_auth.py               # 14 auth utility tests
        ├── test_registry.py           # 19 registry tests
        ├── test_slo_auditor.py        # 14 SLO auditor tests
        ├── test_migration_state.py    # 21 state management tests
        ├── test_report.py             # 8 report tests
        ├── test_retry.py              # 5 retry tests
        ├── test_diff.py               # 5 diff tests
        ├── test_monaco_exporter.py    # 8 Monaco exporter tests
        └── test_terraform_exporter.py # 7 Terraform exporter tests
```

## Data Flow

```
NR NerdGraph API
  -> Dashboard JSON (pages, widgets, NRQL queries)
  -> Alert Policies (conditions, thresholds, channels)
  -> Synthetic Monitors (type, URL, script, frequency)
  -> SLOs (objectives, events, time windows)
  -> Workloads (entity collections, search queries)
  -> Infrastructure Conditions, Log Rules, Tags, Drop Rules

                    |
                    v

Transformers (per entity type)
  DashboardTransformer:
    NRQL -> NRQLCompiler -> AST -> DQLEmitter -> DQL
    -> DQLValidator auto-fix (quotes, operators, fields)
    -> Widget type mapping (viz.line -> DATA_EXPLORER, etc.)
    -> Layout conversion (NR 12-col grid -> DT pixel bounds)
  AlertTransformer + NotificationTransformer
  SyntheticTransformer, SLOTransformer, WorkloadTransformer
  InfrastructureTransformer, LogParsingTransformer, TagTransformer, DropRuleTransformer

                    |
                    v

DT APIs
  -> Documents API v2 (dashboards, fallback to Config API v1)
  -> Settings API v2 (alerting profiles, management zones, auto-tags)
  -> Config API v1 (metric events, monitors, SLOs)
```

## Entity Mapping

| New Relic | Dynatrace | Transformer |
|-----------|-----------|-------------|
| Dashboard (multi-page) | Dashboard (per page) | DashboardTransformer |
| NRQL Query | DQL Query | NRQLCompiler (292 tested patterns) |
| Alert Policy | Alerting Profile | AlertTransformer |
| NRQL Condition | Metric Event | AlertTransformer |
| Notification Channel | Problem Notification | NotificationTransformer |
| Ping Monitor | HTTP Monitor | SyntheticTransformer |
| Browser Monitor | Browser Monitor | SyntheticTransformer |
| SLO | SLO | SLOTransformer |
| Workload | Management Zone | WorkloadTransformer |
| Infra Condition | Metric Event | InfrastructureTransformer |
| Log Parsing Rule | Processing Rule | LogParsingTransformer |
| Entity Tags | Auto-Tag Rules | TagTransformer |
| Drop Rules | Ingest Rules | DropRuleTransformer |
