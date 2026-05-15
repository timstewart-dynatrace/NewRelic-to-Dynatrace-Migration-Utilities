# Architecture (Gen3, post-Phase-23)

> **Last updated:** 2026-04-15
> **Companion docs:** `migration-coverage.md`, `out-of-scope.md`, `nrql-engine-sync-audit.md`, `quickstart.md`, `migration-guide.md`.

This is the high-level map of the codebase after Phases 11–23. For
per-surface migration status, read `docs/migration-coverage.md`. For
permanent exclusions, read `docs/out-of-scope.md`.

## Top-level layout

```
NewRelic-to-Dynatrace-Migration-Utilities/
├── migrate.py                       # Click CLI entry point
├── compiler/                        # NRQL → DQL pipeline (lexer → parser → emitter)
│   ├── compiler.py                  # NRQLCompiler orchestrator
│   ├── lexer.py / parser.py / ast_nodes.py / emitter.py
│   ├── shorthands.py                # Phase 19b — pre-lex shorthand expansion
│   └── tokens.py
├── transformers/                    # 30+ entity transformers (one per NR surface)
│   ├── alert_transformer.py         # Gen3: Workflow + Davis Anomaly Detector
│   ├── dashboard_transformer.py     # Gen3: Document API dashboard JSON
│   ├── *_transformer.py             # see "Transformer inventory" below
│   ├── nrql_converter.py            # Wrapper around compiler with post-processors
│   ├── metric_transform.py          # Phase 23 plugin protocol + registry
│   ├── mappings/                    # Phase 23 per-concern re-export modules
│   └── legacy/                      # Gen2 (Config v1) implementations
├── clients/
│   ├── dynatrace_client.py          # Gen3 façade (Settings 2.0 + Document + Automation)
│   ├── settings_v2_client.py
│   ├── document_client.py
│   ├── automation_client.py
│   ├── _http.py                     # HttpTransport + OAuth2PlatformTokenProvider
│   ├── newrelic_client.py           # NerdGraph
│   └── legacy/
│       └── config_v1_client.py      # LegacyDynatraceV1Client (--legacy mode)
├── exporters/
│   ├── monaco.py                    # Gen3 Monaco v2 project emitter
│   ├── terraform.py                 # Gen3 Terraform HCL emitter
│   └── legacy/                      # Gen2 emitters (--legacy mode)
├── validators/
│   ├── dql_validator.py             # 24 DQL fixers (Phase 19b at parity with TS)
│   └── dql_fixer.py
├── registry/
│   ├── environment.py               # DT environment lookups (entities, metrics, segments)
│   └── slo_auditor.py
├── migration/
│   ├── state.py                     # RollbackManifest, EntityIdMap, IncrementalState, MigrationCheckpoint
│   ├── canary.py                    # Phase 20 — two-wave import w/ approval gate
│   ├── audit.py                     # Phase 20 — drift detection (RENAMED/DELETED/MODIFIED/EXTRA)
│   ├── diff.py                      # Pre-import diff against live DT
│   ├── retry.py                     # FailedEntities for partial re-runs
│   └── report.py                    # ConversionReport (JSON + HTML, Phase 20 enrichment)
├── agents/                          # Phase 16 — per-language APM agent orchestrators
│   ├── base.py                      # AgentOrchestrator + AgentActionPlan
│   ├── java.py / dotnet.py / nodejs.py / python_agent.py
│   └── ruby.py / php.py / go_agent.py
├── tools/
│   └── nrdb_archive.py              # Phase 17 — pre-decommission NRDB snapshot
├── config/
│   ├── settings.py                  # Pydantic settings (env + .env)
│   └── project_links.py             # Phase 21 — single-source URL registry
├── utils/
│   ├── error_taxonomy.py            # Phase 22 — WarningCode/ErrorCode enums
│   ├── auth.py / logger.py / validators.py
└── tests/
    ├── unit/                        # 1100+ unit tests
    ├── integration/                 # env-var-gated tests against real tenants
    └── legacy/                      # tests for transformers/legacy/* under --legacy
```

## Pipeline

```
NR NerdGraph (export)
        │
        ▼
   transformers/* (Gen3 default)         ← 30+ transformers, one per surface
        │
        ├── compile NRQL → DQL via compiler/* + nrql_converter (Phase 19 uplift)
        │     └── post-processors: shift, extrapolate, apdex, funnel, percentage
        │     └── Phase 23 MetricTransform plugins (operator hooks)
        │
        ▼
   transformed_data buckets (Gen3-shaped):
     - workflows                  (Automation API)
     - anomaly_detectors          (Settings 2.0 builtin:davis.anomaly-detectors)
     - segments                   (Settings 2.0 builtin:segment)
     - iam_policies               (Settings 2.0 builtin:iam.policy)
     - synthetic_tests            (Settings 2.0 builtin:synthetic_test)
     - slos                       (Settings 2.0 builtin:monitoring.slo)
     - openpipeline_processors    (Settings 2.0 builtin:openpipeline.*)
     - dashboards                 (Document API dashboard content)
        │
        ▼
   clients/dynatrace_client.py (Gen3 façade)
        │  ┌──────────────────┬──────────────────┬──────────────────┐
        ▼  ▼                  ▼                  ▼                  ▼
   SettingsV2Client    DocumentClient    AutomationClient    [legacy/* under --legacy]
                                                                    │
                                                       Gen2 paths (Alerting Profiles,
                                                       Management Zones, Auto-Tag Rules,
                                                       Problem Notifications, Config v1
                                                       dashboards/synthetics/SLOs)

Phase 20 wraps each push with CanaryPlan (two-wave + approval gate).
Phase 20 audit subcommand diffs a saved baseline against the live tenant.
```

## Transformer inventory (by phase)

| Phase | Transformers added |
|---|---|
| 11 | `alert_transformer` (incl. NotificationTransformer), `dashboard_transformer`, `synthetic_transformer`, `slo_transformer`, `workload_transformer`, `infrastructure_transformer`, `log_parsing_transformer`, `tag_transformer`, `drop_rule_transformer` |
| 16 | `lambda_transformer`, `browser_rum_transformer`, `mobile_rum_transformer`, `custom_instrumentation_translator`, plus `agents/*` orchestrator (7 languages) |
| 17 | `non_nrql_alert_transformer`, `baseline_alert_transformer`, `lookup_table_transformer`, `maintenance_window_transformer`, `change_tracking_transformer`, `custom_event_ingest_transformer`, `identity_transformer`, `log_obfuscation_transformer`, `tools/nrdb_archive` |
| 18 | `cloud_integration_transformer`, `kubernetes_transformer`, `aiops_transformer`, `vulnerability_transformer`, `npm_transformer`, `ai_monitoring_transformer`, `prometheus_transformer` |
| 19 | Dashboard widget parity (funnel, heatmap, event-feed, cascading vars, permissions, savedViews) + compiler confidence uplift (`_apply_phase19_uplift`) |
| 19b | Compiler parity with `nrql-engine` — verified shorthands, K8s overrides, fixer-method coverage |
| 20 | `migration/canary`, `migration/audit`, `delete_entity` dispatch on `DynatraceClient`, ConversionReport enrichment |
| 21 | `HISTORY.md`, `config/project_links.py` (single-source URL registry) |
| 22 | `docs/out-of-scope.md`, `utils/error_taxonomy.py` (WarningCode/ErrorCode), CI workflow parity job |
| 23 | `key_transaction_transformer`, `otel_metrics_transformer`, `statsd_transformer`, `cloudwatch_metric_streams_transformer`, `metric_transform` plugin hook, `mappings/` per-concern modules, numeric confidence-score sync |
| 24 (pending) | DB monitoring, on-host integrations, security signals, custom entities, log archive, metric normalization, synthetic specialized (cert-check / broken-links), saved-filter notebooks |

## Configuration & runtime

| File | Purpose |
|---|---|
| `.env` | NR + DT credentials (see `.env.example`) |
| `config/settings.py` | Pydantic settings model. New: `MIGRATION_LEGACY_MODE`, `DT_CLIENT_ID`, `DT_CLIENT_SECRET` |
| `config/project_links.py` | Phase 21 — change here when nrql-engine relocates to dynatrace-dma |
| `.claude/phases/PHASE-*.md` | Phase progress (active / done / pending / hold) |

## Testing

- **Unit:** `tests/unit/` — 1100+ tests (compiler 292, transformers + clients + exporters + migration + per-phase)
- **Integration:** `tests/integration/` — env-var-gated (`RUN_INTEGRATION_TESTS=1`)
- **Legacy:** `tests/legacy/` — Gen2-path regressions
- **Phase parity:** `tests/unit/test_phase19b_engine_parity.py` pins the Python compiler to TS `nrql-engine` and trips on either-side drift
- **CI:** `.github/workflows/ci.yml` runs ruff, mypy, pytest, and the parity job on every PR

## Where to look for…

| If you want… | Read |
|---|---|
| What does + doesn't migrate | `docs/migration-coverage.md` |
| What will never migrate | `docs/out-of-scope.md` |
| Sibling project sync state | `docs/nrql-engine-sync-audit.md` |
| Setup + first migration | `docs/quickstart.md` |
| Step-by-step migration | `docs/migration-guide.md` |
| Past + planned URL changes | `HISTORY.md` |
| Why a design choice was made | `DECISIONS.md` |
| Roadmap | `.claude/phases/PHASE-*.md` |
