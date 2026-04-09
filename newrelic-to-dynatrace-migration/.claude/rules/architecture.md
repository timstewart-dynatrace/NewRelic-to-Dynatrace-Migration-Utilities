# Architecture

## Project Structure

```
newrelic-to-dynatrace-migration/
├── migrate.py                         # CLI entry point (click group: migrate, compile, convert)
├── requirements.txt
├── .env.example
│
├── compiler/                          # NRQL-to-DQL AST compiler
│   ├── tokens.py                      # TokenType enum, Token dataclass, KEYWORDS
│   ├── lexer.py                       # NRQLLexer (tokenization)
│   ├── ast_nodes.py                   # 18 AST node classes
│   ├── parser.py                      # NRQLParser (recursive descent)
│   ├── emitter.py                     # DQLEmitter (context-aware DQL generation)
│   └── compiler.py                    # NRQLCompiler (orchestrator + validation)
│
├── clients/                           # API clients
│   ├── newrelic_client.py             # NerdGraph GraphQL (pagination, rate limit, retry)
│   └── dynatrace_client.py           # Settings API v2 + Config API v1
│
├── transformers/                      # Entity transformers
│   ├── mapping_rules.py              # EntityMapper, VISUALIZATION_TYPE_MAP, CHART_TYPE_MAP, etc.
│   ├── nrql_mapping_rules.py         # METRIC_MAP (230), ATTR_MAP (72), AGG_MAP (90+), EVENT_TYPE_MAP (34)
│   ├── nrql_converter.py             # NRQLtoDQLConverter (compiler + post-processing + auto-fix)
│   ├── converters.py                 # Specialized: RegexToDPL, Aparse, Rate, CompareWith, Funnel, etc.
│   ├── dashboard_transformer.py      # NR Dashboard -> DT Dashboard (uses AST compiler)
│   ├── alert_transformer.py          # NR Alert Policy -> DT Alerting Profile + Metric Events
│   ├── synthetic_transformer.py      # NR Monitors -> DT HTTP/Browser Monitors
│   ├── slo_transformer.py            # NR SLO -> DT SLO (type detection + metric expressions)
│   └── workload_transformer.py       # NR Workload -> DT Management Zone
│
├── validators/                        # DQL validation
│   ├── dql_validator.py              # Structural syntax validator (9 regex rules)
│   └── dql_fixer.py                  # Auto-fixer (19 fix rules: quotes, operators, fields, etc.)
│
├── config/
│   └── settings.py                   # Pydantic BaseSettings (NR + DT + Migration config)
│
├── utils/
│   ├── logger.py                     # structlog configuration
│   └── validators.py                 # Config validators (NR key format, DT token format)
│
└── tests/
    ├── conftest.py                   # Shared fixtures (compiler instance, structural validators)
    └── unit/
        ├── test_compiler.py          # 282 compiler tests across 25 test classes
        ├── test_transformers.py      # Dashboard, Alert, Notification, Synthetic, SLO, Workload tests
        ├── test_converters.py        # RegexToDPL, Aparse, Rate, CompareWith, Funnel tests
        ├── test_mapping_rules.py     # EntityMapper + mapping dictionary tests
        ├── test_nrql_mapping_rules.py # EVENT_TYPE_MAP, AGG_MAP, ATTR_MAP tests
        ├── test_dql_validator.py     # DQL syntax validator + anti-pattern tests
        ├── test_dql_fixer.py         # DQL auto-fixer + duration conversion tests
        └── test_utils_validators.py  # Config and structure validator tests
```

## Data Flow

```
NR NerdGraph API
  -> Dashboard JSON (pages, widgets, NRQL queries)
  -> Alert Policies (conditions, thresholds, channels)
  -> Synthetic Monitors (type, URL, script, frequency)
  -> SLOs (objectives, events, time windows)
  -> Workloads (entity collections, search queries)

                    |
                    v

Transformers (per entity type)
  DashboardTransformer:
    NRQL -> NRQLCompiler -> AST -> DQLEmitter -> DQL
    -> DQLValidator auto-fix (quotes, operators, fields)
    -> Widget type mapping (viz.line -> DATA_EXPLORER, etc.)
    -> Layout conversion (NR 12-col grid -> DT pixel bounds)
  AlertTransformer:
    Policy -> Alerting Profile
    NRQL Condition -> Metric Event (threshold + operator mapping)
  SyntheticTransformer:
    Ping -> HTTP Monitor, Browser -> Browser Monitor
  SLOTransformer:
    Detect type (availability/error/latency) -> metric expression
  WorkloadTransformer:
    Entity collection -> Management Zone rules

                    |
                    v

DT APIs
  -> Documents API (dashboards)
  -> Settings API v2 (alerting profiles, management zones)
  -> Config API v1 (metric events, monitors, SLOs)
```

## Entity Mapping

| New Relic | Dynatrace | Transformer |
|-----------|-----------|-------------|
| Dashboard (multi-page) | Dashboard (per page) | DashboardTransformer |
| NRQL Query | DQL Query | NRQLCompiler (282 tested patterns) |
| Alert Policy | Alerting Profile | AlertTransformer |
| NRQL Condition | Metric Event | AlertTransformer |
| Ping Monitor | HTTP Monitor | SyntheticTransformer |
| Browser Monitor | Browser Monitor | SyntheticTransformer |
| Scripted API | HTTP Monitor (multi-step) | SyntheticTransformer |
| SLO | SLO | SLOTransformer |
| Workload | Management Zone | WorkloadTransformer |
| Notification Channel | Problem Notification | AlertTransformer |
