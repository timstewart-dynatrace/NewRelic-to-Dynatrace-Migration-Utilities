# Architecture

## Project Structure

```
NewRelic-to-Dynatrace-Migration-Utilities/
├── migrate.py                         # Click CLI: migrate, compile, convert, reference, batch, extract-nrql,
│                                      #   export-monaco, export-terraform, preflight, audit, audit-slos,
│                                      #   agents, scan-instrumentation, archive
├── _version.py                        # Version (2.0.0) — must match pyproject.toml
├── pyproject.toml                     # Project config, pip install, pytest, ruff, mypy
├── requirements.txt                   # Python dependencies
├── .env.example                       # Environment template
├── CHANGELOG.md / DECISIONS.md / HISTORY.md / MEMORY.md
│
├── compiler/                          # NRQL-to-DQL AST compiler (309 compiler tests)
│   ├── shorthands.py                  # Pre-lex shorthand expansion (Phase 19b, nrql-engine port)
│   ├── tokens.py                      # TokenType enum, Token dataclass, KEYWORDS
│   ├── lexer.py                       # NRQLLexer (tokenization, preserves regex escapes)
│   ├── ast_nodes.py                   # AST node classes
│   ├── parser.py                      # NRQLParser (recursive descent)
│   ├── emitter.py                     # DQLEmitter (context-aware DQL generation)
│   └── compiler.py                    # NRQLCompiler (orchestrator + validation)
│
├── clients/                           # API clients (Gen3 default)
│   ├── _http.py                       # HttpTransport, token_auth_header(), settings_v2_base(), OAuth2 provider
│   ├── dynatrace_client.py            # Gen3 facade (Settings 2.0 + Document + Automation) + preflight_gen3()
│   ├── settings_v2_client.py          # Settings API v2
│   ├── document_client.py             # /platform/document/v1/documents (multipart)
│   ├── automation_client.py           # /platform/automation/v1/workflows
│   ├── slo_client.py                  # /platform/slo/v1/slos (Platform SLOs)
│   ├── newrelic_client.py             # NerdGraph GraphQL (pagination, rate limit, retry)
│   └── legacy/config_v1_client.py     # Gen2 Config v1 client (--legacy only)
│
├── transformers/                      # 40 *_transformer.py modules (Gen3 default)
│   ├── __init__.py                    # Registers every transformer
│   ├── dashboard_transformer.py       # NR Dashboard -> Document API dashboard
│   ├── alert_transformer.py           # NR Policy/Condition/Channel -> Workflow + Davis anomaly detector
│   ├── *_transformer.py               # See docs/COVERAGE.md for full inventory
│   ├── _detector_utils.py             # nrql_to_analyzer_query() for analyzer.input
│   ├── _workflow_utils.py             # tasks_list_to_dict() for Automation API
│   ├── _slo_utils.py                  # Platform SLO body + DQL SLI indicators
│   ├── nrql_converter.py              # NRQLtoDQLConverter (compiler + post-processing + auto-fix + uplift)
│   ├── converters.py                  # RegexToDPL, Aparse, Rate, CompareWith, Funnel, etc.
│   ├── metric_transform.py            # Phase 23 MetricTransform plugin protocol + registry
│   ├── mapping_rules.py               # EntityMapper, VISUALIZATION_TYPE_MAP, CHART_TYPE_MAP
│   ├── nrql_mapping_rules.py          # METRIC_MAP (235), ATTR_MAP (72), AGG_MAP (90), EVENT_TYPE_MAP (37)
│   ├── mappings/                      # Per-concern re-exports (metrics, attributes, aggregations, ...)
│   └── legacy/                        # Gen2 *_v1 transformers (--legacy only)
│
├── validators/
│   ├── dql_validator.py               # Structural DQL syntax validator
│   ├── smartscape_map.py              # classic dt.entity.* -> Smartscape table
│   └── dql_fixer.py                   # Auto-fixer (25 fix rules, parity with nrql-engine)
│
├── registry/
│   ├── environment.py                 # DTEnvironmentRegistry (metrics, entities, segments, dashboards, locations)
│   └── slo_auditor.py                 # SLOAuditor
│
├── migration/
│   ├── state.py                       # RollbackManifest, EntityIdMap, Checkpoint, IncrementalState
│   ├── report.py                      # ConversionReport (JSON + HTML)
│   ├── retry.py                       # FailedEntities (partial retry)
│   ├── diff.py                        # DiffReport (transformed vs live DT)
│   ├── canary.py                      # Phase 20 — two-wave import with approval gate
│   └── audit.py                       # Phase 20 — post-migration drift audit
│
├── exporters/
│   ├── monaco.py                      # Gen3 Monaco v2 YAML project
│   ├── terraform.py                   # Gen3 Terraform HCL (dynatrace-oss/dynatrace provider)
│   └── legacy/                        # monaco_v1.py, terraform_v1.py (--legacy only)
│
├── agents/                            # Phase 16 — per-language APM agent orchestrators
│   └── base.py, java.py, dotnet.py, nodejs.py, python_agent.py, ruby.py, php.py, go_agent.py
├── tools/nrdb_archive.py              # Phase 17 — pre-decommission NRDB JSONL snapshot
├── scripts/fetch_dt_schemas.py        # Fetch Settings 2.0 schemas for offline validation
├── config/
│   ├── settings.py                    # Pydantic BaseSettings (NR + DT + Migration + legacy mode)
│   └── project_links.py               # Single-source URL registry
├── utils/
│   ├── logger.py / auth.py / validators.py
│   └── error_taxonomy.py              # WarningCode / ErrorCode
├── examples/example_queries.nrql
│
└── tests/                             # 1380 collected: 1209 unit + 158 legacy + 13 env-gated integration
    ├── conftest.py                    # Session-scoped `compiler` fixture
    ├── unit/                          # 36 files (compiler, CLI, clients incl. wire-level, per-phase, invariants)
    ├── legacy/                        # 8 files — Gen2 *_v1 regressions
    └── integration/                   # 5 files — live NR/DT, schema validation, IaC dry-run (gated)
```

## Data Flow

```
NR NerdGraph API
  -> Dashboards, alert policies/conditions/channels, synthetics, SLOs, workloads,
     infra conditions, log rules, tags, drop rules, RUM, cloud/K8s, AIOps, ...

                    |
                    v

Transformers (Gen3 default; transformers/legacy/ under --legacy)
  NRQL -> shorthands -> NRQLCompiler -> AST -> DQLEmitter -> DQL
       -> DQLFixer auto-fix -> Phase 19 confidence uplift -> MetricTransform plugins
  Detector emitters -> _detector_utils.nrql_to_analyzer_query()
  Workflow emitters -> _workflow_utils.tasks_list_to_dict()

                    |
                    v

transformed_data.json buckets -> clients/dynatrace_client.py (Gen3 facade)
  -> Document API        (dashboards, notebooks — multipart POST)
  -> Automation API      (workflows)
  -> Platform SLO API    (SLOs)
  -> Settings 2.0        (davis anomaly detectors, OpenPipeline, RUM, cloud, ...)
  -> SKIPPED on import   (synthetic tests, Grail segments, IAM policies — see gen3-apis.md)
  -> OR export-monaco / export-terraform
```

## Entity Mapping (Gen3 default)

| New Relic | Dynatrace Gen3 | Transformer |
|-----------|----------------|-------------|
| Dashboard (multi-page) | Document API dashboard | DashboardTransformer |
| NRQL Query | DQL Query | NRQLCompiler / NRQLtoDQLConverter |
| Alert Policy + NRQL Condition | Workflow + `builtin:davis.anomaly-detectors` | AlertTransformer |
| Notification Channel | Workflow task | NotificationTransformer (in alert_transformer.py) |
| Synthetic Monitor | `builtin:synthetic_test` envelope (import SKIPPED) | SyntheticTransformer |
| SLO | Platform SLO API (`/platform/slo/v1/slos`, DQL SLI) | SLOTransformer |
| Workload | `builtin:segment` + `builtin:iam.policy` (import SKIPPED) | WorkloadTransformer |
| Infra Condition | Davis anomaly detector + Workflow | InfrastructureTransformer |
| Log Parsing Rule | `builtin:openpipeline.logs.pipelines` (DPL processor) | LogParsingTransformer |
| Drop Rule | `builtin:openpipeline.logs.pipelines` (drop/removeFields) | DropRuleTransformer |
| Entity Tags | OpenPipeline enrichment | TagTransformer |
| Browser / Mobile app | `builtin:rum.web.app-config` / `builtin:mobile-application` | BrowserRUMTransformer / MobileRUMTransformer |
| 30 more surfaces | see `docs/COVERAGE.md` | — |

Gen2 targets (Alerting Profiles, Metric Events, Management Zones, Auto-Tag Rules, Problem Notifications, Config v1) are only reachable via `--legacy`; see `docs/gen2-only-capabilities.md`.
