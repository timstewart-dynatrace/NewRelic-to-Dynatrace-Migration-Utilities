# Dynatrace-NewRelic Coverage Matrix

> **Purpose:** Operational status dashboard — every New Relic surface, mapped to its Gen3 Dynatrace equivalent and the Python module responsible. Tracks what is convertible today, what is partial, what is a gap, and what is not convertible.
>
> **Rule:** Gen3 default output. Gen2 shapes are available as opt-in via `--legacy` (CLI) / `MIGRATION_LEGACY_MODE=true` (env) and always emit a warning. Gen2 code lives under `transformers/legacy/`, `clients/legacy/`, `exporters/legacy/`. See `.claude/phases/` for the phase-by-phase delivery history (all phases complete; v2.0.0 released 2026-04-16).
>
> **Companion docs:**
> - `migration-coverage.md` — broader migratability discussion + absolute-limits section
> - `gen2-only-capabilities.md` — the 8 capabilities `--legacy` can emit that Gen3 cannot
> - `nrql-engine-sync-audit.md` — TS sibling parity audit (1st/2nd/3rd pass)
> - `out-of-scope.md` — permanent exclusions with reasoning + decision log
> - `architecture.md` — top-level codebase map
>
> **Audit status (post-Phase-24 + third-pass parity, 2026-04-15):** zero 🔴 rows among transformer-shaped capabilities. Remaining 🟡 rows are documented with their residual manual-review reasons. `--legacy` opt-in paths always emit a `WARNING` log line at startup.

## Status Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Covered end-to-end in Python with tests, Gen3 output |
| 🟡 | Partial: scaffold only, missing fields, or manual-review required |
| 🔴 | Gap: no Python support yet |
| ⚫ | Not convertible: no Gen3 equivalent, or outside library scope (see `out-of-scope.md`) |

## Python-Side Module Status Summary

| Module | Tests | Gen3 Verdict |
|--------|-------|--------------|
| compiler | 292 patterns | ✅ Gen3 — emits DQL only; Phase 19b parity-pinned to nrql-engine |
| validators | 24 DQL fixer rules | ✅ Gen3 — DQL syntax + auto-fix; parity with nrql-engine fixer set |
| transformers/alert | Phase 11, 16 tests | ✅ Gen3 Workflow + `builtin:davis.anomaly-detectors` default; `LegacyAlertTransformer` preserves Alerting Profile + Metric Event (opt-in via `--legacy`, warns) |
| transformers/notification (folded into alert) | Phase 11 | ✅ Gen3 Workflow task (email/slack/pagerduty/webhook first-class; Jira/ServiceNow/OpsGenie/xMatters/VictorOps/Teams via generic `http-function` fallback); `LegacyNotificationTransformer` preserves classic Problem Notification (opt-in, warns) |
| transformers/dashboard | Phase 11 + 19 parity | ✅ Gen3 Grail dashboard JSON (Document API, `version: 13`) default; `LegacyDashboardTransformer` preserves Config v1 dashboard (opt-in, warns) |
| transformers/drop-rule | Phase 11 | ✅ Gen3 OpenPipeline `drop` / `removeFields` processors |
| transformers/infrastructure | Phase 11 | ✅ Gen3 `builtin:davis.anomaly-detectors` + Workflow pair |
| transformers/log-parsing | Phase 11 | ✅ Gen3 OpenPipeline DPL `parse` processors |
| transformers/slo | Phase 11 | ✅ Gen3 `builtin:monitoring.slo` Settings 2.0 envelope |
| transformers/synthetic | Phase 11 | ✅ Gen3 `builtin:synthetic_test` Settings 2.0 envelope |
| transformers/tag | Phase 11 | ✅ Gen3 OpenPipeline enrichment default; `LegacyTagTransformer` preserves Auto-Tag Rule (opt-in, warns) |
| transformers/workload | Phase 11 | ✅ Gen3 `builtin:segment` + bucket-scoped IAM policy default; `LegacyWorkloadTransformer` preserves Management Zone (opt-in, warns) |
| transformers/browser-rum | Phase 16, 5 tests | ✅ `builtin:rum.web.app-config` + Core Web Vitals + event source mapping |
| transformers/mobile-rum | Phase 16, 5 tests | ✅ `builtin:mobile-application` + 8-platform SDK-swap runbook |
| transformers/lambda | Phase 16, 5 tests | ✅ DT Lambda extension + per-runtime/arch layer ARN templates |
| transformers/custom-instrumentation | Phase 16, 9 tests | ✅ JS/TS/Python/Java/Kotlin pattern matcher; emits suggestion diffs (no file rewrite) |
| agents/ | Phase 16, 10 tests | ✅ 7-language action plans (Java/.NET/Node/Python/Ruby/PHP/Go); `migrate.py agents` subcommand |
| transformers/non-nrql-alert | Phase 17 | ✅ Infrastructure / Synthetic / Browser / Mobile / External Service / Multi-location Synthetic conditions |
| transformers/baseline-alert | Phase 17 | ✅ NR baseline + outlier → Davis adaptive detectors |
| transformers/lookup-table | Phase 17 | ✅ Resource Store JSONL + DQL `lookup` subquery fragment |
| transformers/maintenance-window | Phase 17 | ✅ one-off + recurring windows + mute-rule filter expression |
| transformers/change-tracking | Phase 17 | ✅ NR deployment/change events → DT events API `CUSTOM_*` types |
| transformers/custom-event-ingest (alias: CustomEventTransformer) | Phase 17 + Phase 24 alias | ✅ NR custom events → bizevent CloudEvent payloads + DQL source mapping |
| transformers/identity | Phase 17 | ✅ Users / Teams / Roles / SAML → IAM Settings 2.0; API-key/SCIM runbook |
| transformers/log-obfuscation | Phase 17 | ✅ 7 PII/PAN presets + regex fallback → OpenPipeline mask |
| tools/nrdb_archive | Phase 17 | ✅ resumable per-event-type JSONL archive (`migrate.py archive`) |
| transformers/cloud-integration | Phase 18 | ✅ AWS (16 services) / Azure (8 resources) / GCP (8 services) |
| transformers/kubernetes | Phase 18 | ✅ NR → DynaKube CR + Helm values; full-stack / host-only modes |
| transformers/aiops | Phase 18 | ✅ NR AI Workflows (`[NR AIOps → DT]` prefix) + enrichments + Davis detectors |
| transformers/vulnerability | Phase 18 | ✅ RVA alerting + per-CVE muting |
| transformers/npm | Phase 18 | ✅ SNMP devices + NetFlow collector (secrets redacted) |
| transformers/ai-monitoring | Phase 18 | ✅ Model registry + inference NRQL→DQL mapping |
| transformers/prometheus | Phase 18 | ✅ scrape + OTLP remote-write + relabel filters |
| transformers/key-transaction | Phase 23 | ✅ SLO + OpenPipeline enrichment + Workflow bundle |
| transformers/otel-metrics | Phase 23 | ✅ NR OTLP ingestion → `builtin:otel.ingest.metrics` + collector YAML snippet |
| transformers/otel-collector | 3rd-pass, 8 tests | ✅ 3 signals (traces + metrics + logs) + 5 processor kinds (attributes/filter/batch/memory_limiter/resource) + pass-through for unknowns |
| transformers/statsd | Phase 23 | ✅ ActiveGate `builtin:statsd.metrics` + tag-mapping translation |
| transformers/cloudwatch-metric-streams | Phase 23 | ✅ `builtin:aws.metric-streams` + Firehose Terraform snippet |
| transformers/metric-transform | Phase 23 | ✅ `MetricTransform` protocol + `MetricTransformRegistry` plugin hook |
| transformers/mappings/ | Phase 23 | ✅ per-concern re-export submodules (metrics/attributes/aggregations/event_types/metric_transforms/visualizations) |
| transformers/database-monitoring | Phase 24, 5 tests | ✅ 10 DB engines (MySQL/Postgres/MSSQL/Oracle/MongoDB/Redis/Cassandra/MariaDB/DB2/HANA) |
| transformers/on-host-integration | Phase 24, 4 tests | ✅ 12 integrations (NGINX/HAProxy/Kafka/RabbitMQ/Elasticsearch/Memcached/Couchbase/Consul/Apache/etcd/Varnish/Zookeeper) |
| transformers/security-signals | Phase 24, 3 tests | ✅ AppSec envelope + per-signature OpenPipeline enrichment |
| transformers/custom-entity | Phase 24, 3 tests | ✅ custom-device POST payload + enrichment matcher |
| transformers/log-archive | Phase 24, 4 tests | ✅ Grail bucket + OpenPipeline egress (S3/GCS/Azure Blob) |
| transformers/metric-normalization | Phase 24, 4 tests | ✅ rename / aggregate / drop → OpenPipeline metric processors |
| transformers/synthetic-specialized | Phase 24, 4 tests | ✅ CERT_CHECK (certificateExpiryDate rule) + BROKEN_LINKS (multi-step HTTP, capped at 50) |
| transformers/saved-filter-notebook | Phase 24, 4 tests | ✅ NR Data Apps → Document API `type=='notebook'` with markdown + DQL cells |
| transformers/legacy/error_inbox_v1 | 3rd-pass, 5 tests | ✅ `--legacy` only — NR Errors Inbox → DT Problems API actions (comments / close / acknowledge) |
| transformers/legacy/request_naming_v1 | 3rd-pass, 4 tests | ✅ `--legacy` only — `newrelic.setTransactionName()` sites → `builtin:request-naming.request-naming-rules` |
| migration/canary | Phase 20, 7 tests | ✅ two-wave import with approval gate |
| migration/audit | Phase 20, 8 tests | ✅ drift detection (RENAMED / DELETED / MODIFIED / EXTRA); `migrate.py audit` |
| migration/state | Existing | ✅ RollbackManifest / EntityIdMap / IncrementalState / MigrationCheckpoint |
| migration/report | Phase 20 enrichment | ✅ ConversionReport + numeric `confidence_score` + `warning_codes` + `warnings_by_code()` |
| utils/error_taxonomy | Phase 22 | ✅ `WarningCode` / `ErrorCode` enums + `CodedMessage` |

## 1. APM

| NR Surface | Gen3 Target | Python Module | Status |
|-----------|-------------|---------------|--------|
| `FROM Transaction` / `Span` / `TransactionError` | `fetch spans` | compiler | ✅ |
| Service Map (user annotations) | Smartscape (auto-inferred) | — | ⚫ platform feature, no config to migrate |
| Distributed tracing / PurePath | DT distributed tracing | compiler (query) | ✅ |
| Key Transactions | SLO + OpenPipeline enrichment + Workflow bundle | transformers/key-transaction | ✅ |
| Apdex score | `countIf()` buckets in DQL + Phase 19 uplift to HIGH | compiler + `_apply_phase19_uplift` | ✅ |
| Deployment markers (APM deployment API) | DT deployment events API | transformers/change-tracking | ✅ |
| Error profiles | Davis Problems | — | ⚫ platform feature |
| Thread profiler / X-Ray | DT code profiling | — | ⚫ platform feature |
| APM agent uninstall + OneAgent install (per language) | OneAgent deployment | agents/ (7 languages) | ✅ action-plan orchestrator (not executor); `migrate.py agents` |
| Custom instrumentation (`newrelic.*()`) | OneAgent SDK / OTel SDK | transformers/custom-instrumentation | ✅ JS/TS/Python/Java/Kotlin pattern matcher; emits `TranslationSuggestion[]` (no file rewrite) |
| `newrelic.recordCustomEvent()` | `bizevent.ingest` | transformers/custom-event-ingest (alias `CustomEventTransformer`) | ✅ |
| `newrelic.addCustomAttribute()` | OneAgent SDK custom request attribute | transformers/custom-instrumentation | ✅ MEDIUM confidence |
| `newrelic.recordMetric()` | OTel Meter API | transformers/custom-instrumentation | ✅ HIGH confidence |
| `newrelic.noticeError()` | OneAgent SDK error / OTel span.recordException | transformers/custom-instrumentation | ✅ HIGH confidence |
| `newrelic.setTransactionName()` | DT request-naming rule (config-time) | transformers/custom-instrumentation → LOW; `LegacyRequestNamingTransformer` → concrete rule | 🟡 Gen3 (LOW confidence) / ✅ under `--legacy` |
| `newrelic.startSegment()/endSegment()` | OTel tracer `startSpan` / `span.end` | transformers/custom-instrumentation | ✅ HIGH confidence |

## 2. Browser RUM

| NR Surface | Gen3 Target | Python Module | Status |
|-----------|-------------|---------------|--------|
| Browser application (entity) | DT RUM application | transformers/browser-rum | ✅ `builtin:rum.web.app-config` envelope |
| PageView / BrowserInteraction / AjaxRequest / JavaScriptError | `fetch bizevents` (RUM) | compiler + transformers/browser-rum | ✅ |
| Core Web Vitals (LCP/FID/CLS/INP/TTFB/FCP) | DT RUM Core Web Vitals metrics | transformers/browser-rum | ✅ 6 vitals mapped in runbook |
| Session Replay | DT Session Replay | — | ⚫ feature activation, not config migration |
| SPA monitoring | DT SPA support | transformers/browser-rum | ✅ `isSpa` flag honored |
| Custom browser events | DT RUM custom events API | transformers/browser-rum | 🟡 delegated to `CustomInstrumentationTranslator` |
| Browser allow/deny lists | DT RUM domain allowlist | transformers/browser-rum | ✅ |
| Domain aliasing | DT application naming rules | transformers/browser-rum | ✅ |

## 3. Mobile RUM

| NR Surface | Gen3 Target | Python Module | Status |
|-----------|-------------|---------------|--------|
| Mobile application (entity) | DT Mobile application | transformers/mobile-rum | ✅ `builtin:mobile-application` envelope |
| Android / iOS / React Native / Flutter / Xamarin / Unity / Cordova / Capacitor agents | DT Mobile SDK per platform | transformers/mobile-rum | ✅ per-platform SDK-swap runbook (8 platforms) |
| MobileSession / MobileCrash / MobileRequest / handled exceptions | DT mobile session data via `fetch bizevents` | transformers/mobile-rum | ✅ source-mapping table in runbook |
| Custom mobile events | DT mobile SDK events | transformers/mobile-rum | 🟡 delegated to `CustomInstrumentationTranslator` |
| App launch / device info | DT mobile dimensions | transformers/mobile-rum | 🟡 mapping documented |
| Crash symbolication (dSYM, ProGuard/R8) | DT symbolication upload | transformers/mobile-rum | ✅ per-platform instructions in runbook |

## 4. Infrastructure

| NR Surface | Gen3 Target | Python Module | Status |
|-----------|-------------|---------------|--------|
| `SystemSample` / `ProcessSample` / `NetworkSample` / `StorageSample` | `timeseries` on `dt.host.*` / `dt.process.*` | compiler (DEFAULT_METRIC_MAP) | ✅ metric names auto-rewritten |
| AWS integration config | DT AWS cloud integration (settings) | transformers/cloud-integration | ✅ 16 AWS services; IAM role scaffold |
| Azure integration config | DT Azure integration | transformers/cloud-integration | ✅ 8 Azure resources; app registration scaffold |
| GCP integration config | DT GCP integration | transformers/cloud-integration | ✅ 8 GCP services; service-account key scaffold |
| AWS Lambda integration | DT Lambda extension config | transformers/lambda | ✅ per-runtime/arch layer ARN templates |
| On-host integrations (MySQL, Postgres, Redis, …) | DT extensions / OneAgent plugins | transformers/on-host-integration | ✅ 12 integrations (NGINX/HAProxy/Kafka/RabbitMQ/Elasticsearch/Memcached/Couchbase/Consul/Apache/etcd/Varnish/Zookeeper) |
| Database monitoring (NRDM) | DT DB extensions | transformers/database-monitoring | ✅ 10 engines (MySQL/Postgres/MSSQL/Oracle/MongoDB/Redis/Cassandra/MariaDB/DB2/HANA) |
| CloudWatch Metric Streams (Kinesis) | DT AWS Metric Streams ingest | transformers/cloudwatch-metric-streams | ✅ settings envelope + Firehose Terraform snippet |
| Kubernetes integration | DT DynaKube | transformers/kubernetes | ✅ full-stack + host-only modes, namespace selector |
| Prometheus integration | DT Prometheus ingestion | transformers/prometheus | ✅ scrape + remote-write + relabel filters |
| StatsD ingestion | DT StatsD on ActiveGate | transformers/statsd | ✅ `builtin:statsd.metrics` + tag mapping |
| OpenTelemetry collector config | DT OTLP ingestion (all 3 signals) | transformers/otel-collector | ✅ endpoint + processor pipeline (attributes / filter / batch / memory_limiter / resource / unknown-passthrough) |
| OpenTelemetry metrics pipeline (direct OTLP, non-collector) | DT OTLP metrics ingest | transformers/otel-metrics | ✅ gRPC + HTTP protocols; resource-attribute filtering |
| NR Flex (custom scripts) | OneAgent extensions / OTel collector | — | ⚫ script rewrite, not automatable |
| Infra-agent log collection | OneAgent log collection | — | 🟡 reconfigure at forwarder level (doc-only) |

## 5. Synthetic Monitoring

| NR Surface | Gen3 Target | Python Module | Status |
|-----------|-------------|---------------|--------|
| Simple Ping / Browser / Scripted API | `builtin:synthetic_test` (HTTP / Browser / Multi-step) | transformers/synthetic | ✅ |
| Scripted Browser | DT Browser Monitor (clickpath) | transformers/synthetic | 🟡 scaffold only — manual rebuild |
| Step Monitor (legacy) | DT Browser Monitor | transformers/synthetic | 🟡 scaffold |
| Certificate Check | DT HTTP Monitor w/ cert validation | transformers/synthetic-specialized | ✅ `certificateExpiryDate` rule |
| Broken Links | Multi-step HTTP Monitor (capped at 50 URLs) | transformers/synthetic-specialized | ✅ probes NR-crawler-discovered URL list |
| Secure credentials | DT credentials vault | — | ⚫ secrets don't migrate |
| Public locations | DT public locations (region map) | transformers/synthetic | ✅ |
| Private locations / minions | DT ActiveGate synthetic capability | — | ⚫ infrastructure deployment |
| Private-location inventory lookup | `/api/v2/synthetic/locations` | clients/legacy only | 🟡 Gen2-only (see `gen2-only-capabilities.md` #7) |

## 6. Logs

| NR Surface | Gen3 Target | Python Module | Status |
|-----------|-------------|---------------|--------|
| Log ingest (Fluent Bit / Fluentd / Filebeat) | DT log ingest / OneAgent | — | 🟡 reconfigure forwarders (doc-level) |
| Log API (HTTP POST) | DT Generic Log Ingest API | — | 🟡 endpoint change |
| Drop rules | OpenPipeline `drop` / `removeFields` processors | transformers/drop-rule | ✅ |
| Log Live Archive (tiered long-term) | Grail cold bucket + retention | transformers/log-archive | ✅ `builtin:logmonitoring.log-storage-settings` + compliance tags |
| Streaming Exports (AWS S3 / GCS / Azure Blob) | Grail → OpenPipeline HTTP egress | transformers/log-archive | ✅ OpenPipeline egress processor |
| Parsing rules (regex → DPL) | OpenPipeline DPL parsers | transformers/log-parsing | ✅ |
| Parsing rules (Grok → DPL) | OpenPipeline DPL parsers | transformers/log-parsing | 🟡 emits disabled placeholder + warning (manual DPL conversion) |
| Obfuscation rules (PII / PAN masking) | OpenPipeline masking processors | transformers/log-obfuscation | ✅ 7 presets (email/CC/SSN/phone/IP/IPv4/AWS keys) + regex fallback |
| Log patterns (auto-clustering) | DT log pattern recognition | — | ⚫ platform feature |
| Log alerting (NRQL on logs) | Davis Anomaly Detector on DQL over `fetch logs` | compiler + alert | ✅ |
| Log partitions (data partitions) | Grail buckets | transformers/log-archive | ✅ per-bucket envelope emitted |
| Live tail | DT log live view | — | ⚫ platform feature |
| Log-to-metric rules | OpenPipeline metric extraction | — | 🟡 partial via OpenPipeline `computeFields` |
| NRDB pre-decommission archive | JSONL resumable snapshot | tools/nrdb_archive | ✅ `migrate.py archive` |

## 7. Alerts & Notifications

| NR Surface | Gen3 Target | Python Module | Status |
|-----------|-------------|---------------|--------|
| Alert Policy | Gen3 Workflow (Davis-event trigger) | transformers/alert | ✅ Gen3 default (legacy opt-in) |
| NRQL Condition (static threshold) | Davis Anomaly Detector (`builtin:davis.anomaly-detectors`) | transformers/alert | ✅ paired with Workflow via detector IDs |
| NRQL Condition (baseline) | Davis adaptive baseline | transformers/baseline-alert | ✅ |
| NRQL Condition (outlier) | Davis outlier detection | transformers/baseline-alert | ✅ |
| APM Condition | Davis adaptive baseline | transformers/non-nrql-alert | ✅ |
| Infrastructure Condition | Davis Anomaly Detector + Workflow | transformers/infrastructure / non-nrql-alert | ✅ |
| Synthetic Condition | Davis Anomaly Detector on synthetic results | transformers/non-nrql-alert | ✅ |
| External Service Condition | Davis Anomaly Detector on service deps | transformers/non-nrql-alert | ✅ |
| Mobile / Browser Condition | Davis Anomaly Detector on RUM metrics | transformers/non-nrql-alert | ✅ |
| Multi-location Synthetic Condition | Detector w/ `minLocationsFailing` | transformers/non-nrql-alert | ✅ |
| Lookup tables (WHERE IN) | DQL `lookup` subquery | transformers/lookup-table | ✅ Resource Store JSONL + DQL fragment |
| Notification Channel — Email | Workflow task `dynatrace.email:email-action` | transformers/alert (NotificationTransformer) | ✅ |
| Notification Channel — Slack | Workflow task `dynatrace.slack:slack-send-message` | transformers/alert | ✅ (manual connectionId) |
| Notification Channel — PagerDuty | Workflow task `dynatrace.pagerduty:trigger-incident` | transformers/alert | ✅ (key rotation manual) |
| Notification Channel — Webhook | Workflow task `dynatrace.automations:http-function` | transformers/alert | ✅ |
| Notification Channel — OpsGenie | Workflow HTTP task (`GenieKey` header) | transformers/alert | 🟡 generic webhook fallback (see `gen2-only-capabilities.md` #2) |
| Notification Channel — xMatters | Workflow HTTP task | transformers/alert | 🟡 generic webhook fallback |
| Notification Channel — Jira | Workflow HTTP task | transformers/alert | 🟡 generic webhook fallback |
| Notification Channel — ServiceNow | Workflow HTTP task | transformers/alert | 🟡 generic webhook fallback |
| Notification Channel — Teams | Workflow HTTP task | transformers/alert | 🟡 generic webhook fallback |
| Notification Channel — VictorOps | Workflow HTTP task | transformers/alert | 🟡 generic webhook fallback |
| Incident preferences (PER_POLICY / CONDITION / TARGET) | Workflow trigger filters + grouping | transformers/alert | 🟡 partial — grouping semantics require manual Workflow step |
| Mute rules (NRQL-based) | Workflow filter / detector embedded filter | transformers/maintenance-window | ✅ LOW-confidence DQL-comment translation |
| Maintenance windows (scheduled, recurring) | `builtin:deployment.maintenance` | transformers/maintenance-window | ✅ one-off + weekly/monthly recurrence |
| Per-severity delay ladder | multiple Workflows (one per severity) | — | 🟡 Gen2-only today (see `gen2-only-capabilities.md` #1); closed in Phase 25 |

## 8. AIOps / Applied Intelligence

| NR Surface | Gen3 Target | Python Module | Status |
|-----------|-------------|---------------|--------|
| Issues & incidents | Davis Problems | — | ⚫ auto-detected; concept mapping only |
| Decisions (correlation rules) | Davis causal engine | transformers/aiops (captured as decision_notes) | ⚫ Davis replaces manual decisions |
| NR AI Workflows | DT Gen3 Workflow (renamed `[NR AIOps → DT]`) | transformers/aiops | ✅ |
| Destinations (webhook targets) | Workflow action tasks | transformers/aiops + transformers/alert | ✅ |
| Enrichments (NRQL-based context injection) | Workflow `dql-query` tasks | transformers/aiops | ✅ |
| Proactive detection (APM auto-baselines) | Davis adaptive baselines | transformers/baseline-alert | ✅ |
| Anomaly detection settings | Davis anomaly detection | transformers/aiops + transformers/baseline-alert | ✅ |

## 9. Service Level Management

| NR Surface | Gen3 Target | Python Module | Status |
|-----------|-------------|---------------|--------|
| SLO (v1 / v2) | `builtin:monitoring.slo` | transformers/slo | ✅ |
| SLI query (NRQL) | DT SLO metric expression (DQL) | transformers/slo + compiler | ✅ |
| Error budget burn-rate alerts | Burn-rate Metric Event on SLI | — | 🟡 manual configuration |

## 10. Dashboards

| NR Surface | Gen3 Target | Python Module | Status |
|-----------|-------------|---------------|--------|
| Dashboard (multi-page) | DT Documents (one per page) | transformers/dashboard | ✅ `version: 13` Grail format |
| Widgets: line / area / bar / pie / table / billboard / histogram / markdown / JSON | DT Grail tile variants | transformers/dashboard | ✅ |
| Widget: heatmap | DT honeycomb (native) | transformers/dashboard (Phase 19) | ✅ |
| Widget: event feed | DT table (canonical timestamp sort + `eventFeedMode`) | transformers/dashboard (Phase 19) | ✅ |
| Widget: funnel | Composite `barChart` with `countIf` per stage + `funnelEmulation: true` | transformers/dashboard (Phase 19) | ✅ |
| Nerdpack widget | no DT equivalent | — | ⚫ customer rewrite |
| Dashboard variables (enum / NRQL / string) | DT Document variables (query / csv typed) | transformers/dashboard | ✅ |
| Cascading variables | DT cascading variables w/ `dependsOn` from `{{var}}` refs | transformers/dashboard (Phase 19) | ✅ |
| Dashboard permissions | Document sharing (public read / read-write / private) | transformers/dashboard (Phase 19) | ✅ |
| Saved filter sets | Document `savedViews` with `variableValues` | transformers/dashboard (Phase 19) | ✅ |
| Saved query / Data Apps (notebooks) | DT Notebooks (Document API `type=='notebook'`) | transformers/saved-filter-notebook | ✅ markdown + DQL cells |
| Config v1 dashboard `.preset` / `.tags` metadata | Document API attributes | — | 🟡 Gen2-only today (see `gen2-only-capabilities.md` #5); closed in Phase 25 |

## 11. Users, Teams, Access

| NR Surface | Gen3 Target | Python Module | Status |
|-----------|-------------|---------------|--------|
| Users | `builtin:iam.users` | transformers/identity | ✅ |
| Teams | `builtin:iam.groups` | transformers/identity | ✅ |
| User types (Full / Core / Basic) | DT license types (FULL/STANDARD/LIMITED) | transformers/identity | ✅ mapped in user envelope |
| Authentication domains | DT auth settings | transformers/identity | 🟡 runbook-level guidance |
| SAML SSO | DT SAML IdP config (`builtin:identity.saml`) | transformers/identity | ✅ cert upload manual |
| SCIM provisioning | DT SCIM | transformers/identity | 🟡 runbook-level guidance |
| Default roles | DT built-in policies | transformers/identity | ✅ |
| Custom roles | DT custom IAM policies | transformers/identity | ✅ common permissions mapped; unmapped emit TODO placeholders |
| Product-level permissions | DT scoped policies | transformers/identity | 🟡 encoded in policy statements |
| API keys (User / Ingest / License / Browser / Mobile) | DT tokens / OAuth clients | — | ⚫ secrets don't migrate — runbook lists re-creation steps |
| Service accounts | DT service users / OAuth clients | transformers/identity | 🟡 runbook-level guidance |

## 12. Change Tracking / Deployments

| NR Surface | Gen3 Target | Python Module | Status |
|-----------|-------------|---------------|--------|
| Change events | DT events API (`CUSTOM_DEPLOYMENT` / `CUSTOM_CONFIGURATION` / `CUSTOM_INFO`) | transformers/change-tracking | ✅ |
| Deployment markers (APM deployment API) | DT deployment events | transformers/change-tracking | ✅ |
| Change Tracking API | DT events API | transformers/change-tracking | ✅ |
| Changes dashboard | DT Problems / events correlation | — | ⚫ platform feature |
| Change intelligence | Davis causal engine | — | ⚫ platform feature |

## 13. Errors Inbox

| NR Surface | Gen3 Target | Python Module | Status |
|-----------|-------------|---------------|--------|
| Error occurrences | DT exceptions / span errors | compiler | ✅ via span query |
| Error grouping | DT error fingerprinting | — | ⚫ platform feature |
| Error status (resolved, ignored, work_in_progress) | Problems API `/close`, `/acknowledge` | transformers/legacy/error_inbox_v1 | ✅ `--legacy` only — Gen3 default treats as out-of-scope (see `out-of-scope.md`) |
| Comments on errors | Problems API `/comments` | transformers/legacy/error_inbox_v1 | ✅ `--legacy` only |
| Error assignments | — | — | ⚫ no DT assignee field |
| Issue tracker integration (Jira, …) | Workflow → Jira | transformers/alert (NotificationTransformer) | 🟡 generic webhook fallback |

## 14. Workloads & Entity Management

| NR Surface | Gen3 Target | Python Module | Status |
|-----------|-------------|---------------|--------|
| Workload | `builtin:segment` + bucket-scoped IAM | transformers/workload | ✅ Gen3 default (best-effort; manual IAM tuning flagged in warnings) |
| Entity tags | OpenPipeline enrichment (`addFields`) | transformers/tag | ✅ Gen3 default (legacy opt-in) |
| Entity golden signals | Davis signals | — | ⚫ platform feature |
| Entity health status | Problem severity / Davis | — | ⚫ platform feature |
| Entity relationships | Smartscape | — | ⚫ auto-discovered |
| Custom entities | DT custom device entities | transformers/custom-entity | ✅ `/api/v2/entities/custom` payload + enrichment matcher |
| Template-value auto-tagging (`{TAG:name}`) | OpenPipeline `computeFields` | — | 🟡 Gen2-only today (see `gen2-only-capabilities.md` #3); closed in Phase 25 |
| Entity-ID-targeted MZ rules | Segment `dt.entity.id == "..."` statement | — | 🟡 Gen2-only today (see `gen2-only-capabilities.md` #4); closed in Phase 25 |

## 15. Data Management

| NR Surface | Gen3 Target | Python Module | Status |
|-----------|-------------|---------------|--------|
| Data partitions (default + custom) | Grail buckets | transformers/log-archive | ✅ bucket envelope emission |
| Data Plus tier features (retention, PCI / HIPAA / FedRAMP) | Grail retention + bucket compliance tags | transformers/log-archive | ✅ compliance-tags field |
| Data retention settings | Per-bucket retention | transformers/log-archive | ✅ `retentionDays` in envelope |
| Event type metadata | — | — | ⚫ DT event types fixed |
| Metric normalization rules | OpenPipeline metric processing | transformers/metric-normalization | ✅ rename / aggregate / drop |
| Custom event types (via Event API) | `bizevent.ingest` | transformers/custom-event-ingest | ✅ |
| Historical data (NRDB) | — | — | ⚫ not migratable to Grail — see `out-of-scope.md` §1 |
| Archive / export (pre-decommission) | NR export via API (JSONL) | tools/nrdb_archive | ✅ resumable; archive-only (not replayable) |

## 16. Specialized Products

| NR Surface | Gen3 Target | Python Module | Status |
|-----------|-------------|---------------|--------|
| Kubernetes navigator / Cluster explorer | DT Kubernetes app | transformers/kubernetes | ✅ emits DynaKube CR + Helm values |
| Lambda / serverless monitoring | DT serverless / Lambda extension | transformers/lambda | ✅ per-runtime layer guidance |
| Vulnerability Management | DT Application Security (RVA) | transformers/vulnerability | ✅ RVA settings + muting rules + license-policy runbook |
| Network Performance Monitoring / NPM | DT Network monitoring | transformers/npm | ✅ SNMP extension + NetFlow collector |
| AI Monitoring / MLM | DT AI Observability | transformers/ai-monitoring | ✅ model registry + bizevent mapping |
| Database Monitoring (NRDM) | DT DB extensions | transformers/database-monitoring | ✅ 10 engines |
| IoT / Embedded | OTel | — | ⚫ no direct equivalent |
| Security signals | DT Security Investigator | transformers/security-signals | ✅ AppSec envelope + per-signature enrichment |
| APM 360 (service-level overview UI) | DT Services app (auto) | — | ⚫ platform feature |
| NR-Grafana plugin | Grafana DT datasource | — | ⚫ no migratable artifact |
| NR Prometheus Agent | DT Prometheus remote write | transformers/prometheus | ✅ |
| NR Browser Pro features | — | — | ⚫ no equivalent |

## 17. Programmability / Extensions

| NR Surface | Gen3 Target | Python Module | Status |
|-----------|-------------|---------------|--------|
| Nerdpacks (custom NR One apps) | DT AppEngine apps | — | ⚫ customer rewrite |
| Custom visualizations | DT custom visualizations | — | ⚫ customer rewrite |
| nr1 CLI | DT developer tools | — | ⚫ tooling, not config |
| NerdGraph scripts | DT API clients | — | ⚫ customer rewrite |

## 18. Observability as Code

| NR Surface | Gen3 Target | Python Module | Status |
|-----------|-------------|---------------|--------|
| Terraform `newrelic` provider | Terraform `dynatrace-oss/dynatrace` | exporters/terraform | ✅ Gen3-default HCL (resources: `dynatrace_document`, `dynatrace_automation_workflow`, `dynatrace_segment`, `dynatrace_iam_policy`, `dynatrace_slo_v2`, `dynatrace_generic_setting`); legacy HCL via `--legacy` |
| Monaco config-as-code | Monaco v2 project | exporters/monaco | ✅ Gen3 default with `manifest.yaml`; `oAuth` + token auth; settings/documents/workflows layout |
| Dashboards-as-code | DT Documents API | transformers/dashboard | ✅ |
| Alerts-as-code | DT Workflows + Davis Anomaly Detectors | transformers/alert | ✅ |
| CI/CD pipeline migration | — | — | ⚫ customer rewrite |

## 19. FinOps / Cost

| NR Surface | Gen3 Target | Python Module | Status |
|-----------|-------------|---------------|--------|
| Data ingest tracking | DPS usage queries | — | ⚫ platform feature |
| Usage dashboards | DT usage app | — | ⚫ platform feature |
| Cost & spend tracking | Bucket attribution | — | ⚫ platform feature |

## Gen2-Only Capabilities (reachable via `--legacy` only)

Eight specific capabilities have no Gen3 equivalent today. Each is
catalogued in `gen2-only-capabilities.md`:

| # | Capability | Gen3 status | Phase 25 plan |
|---|---|---|---|
| 1 | Per-severity delay ladder on alerting profiles | 🟡 ladder collapsed today | Fan out to one Workflow per severity |
| 2 | Typed problem-notification integrations (Jira/ServiceNow/OpsGenie/xMatters/VictorOps/Teams) | 🟡 generic webhook fallback | ⚫ blocked on upstream DT Workflow connector catalog |
| 3 | Template-value auto-tagging (`{TAG:name}`) | 🟡 literal-value only | OpenPipeline `computeFields` with `tags.<name>` DQL |
| 4 | Entity-ID-targeted MZ rules | 🟡 falls back to `entity.name contains` | Segment `dt.entity.id` equality statement |
| 5 | Config v1 dashboard `.preset` / `.tags` metadata | 🟡 dropped | Document API attribute emission |
| 6 | Classic synthetic KPMs | ✅ at parity — not a real gap | — |
| 7 | Private synthetic location inventory lookup | 🟡 no Gen3 client method | Add `DynatraceClient.list_synthetic_locations()` |
| 8 | Config v1 dashboard fallback when Documents API is disabled | 🟡 Gen3 has no fallback | Opt-in `create_dashboard(fallback_to_config_v1=True)` |

## nrql-engine Parity

**Third-pass audit (2026-04-15) confirmed 53 / 53 TS transformer files
covered** (38 direct 1:1 ports, 15 at parity via different file
organization — see `nrql-engine-sync-audit.md`). Python also has
**exclusive capabilities** not in the TS sibling:

- `agents/` orchestrator (7 languages)
- `tools/nrdb_archive.py` (pre-decommission JSONL snapshot)
- `migration/canary.py` + `migration/audit.py` (Phase 20)
- `utils/error_taxonomy.py` (Phase 22)
- `compiler/shorthands.py` standalone module (Phase 19b)
- `_apply_phase19_uplift` confidence uplift (Phase 19)
- `config/project_links.py` single-source URL registry (Phase 21)
- Phase 24 `CustomEventTransformer` alias (3rd-pass parity)

Parity is pinned in `tests/unit/test_phase19b_engine_parity.py` and the
CI `nrql-engine-parity` job.

## Exit Criteria

- 0 🔴 rows — every remaining gap is ⚫ with a reason here or in `out-of-scope.md` / `gen2-only-capabilities.md`
- 0 🟡 rows with Gen2 leak in Gen3 default path — all 🟡 rows are either (a) Gen2-only features (documented in `gen2-only-capabilities.md`) or (b) delegate to other transformers for partial coverage
- Every ✅ row has ≥ 1 test in `tests/unit/` or `tests/legacy/`
- `grep -rn 'Alerting Profile\|Management Zone\|Auto-Tag\|Problem Notification\|Metric Event' transformers/` returns 0 matches outside `transformers/legacy/` and docstring descriptions of what Gen3 replaces
- 1201 unit + 8 integration tests passing as of post-Phase-24 + third-pass

## Phase Status

| Phase | Status |
|---|---|
| 11–14 | ✅ Done — Gen3 refactor + `--legacy` flag + clients + exporters |
| 15 | ✅ Done — v2.0.0 released (version bump + tag + merge to main, 2026-04-16) |
| 16 | ✅ Done — P0 coverage (agents, RUM, Mobile, Lambda, custom instrumentation) |
| 17 | ✅ Done — P1 alerts + identity + data + log obfuscation + NRDB archive |
| 18 | ✅ Done — cloud / K8s / AIOps / vulnerability / NPM / AI / Prometheus |
| 19 | ✅ Done — dashboard parity + compiler confidence uplift |
| 19b | ✅ Done — nrql-engine compiler parity verified (shorthands, K8s overrides, fixer methods) |
| 20 | ✅ Done — canary + Gen3 rollback + drift audit + enriched report |
| 21 | ✅ Done — HISTORY.md + `config/project_links.py` (dma relocation prep) |
| 22 | ✅ Done — out-of-scope + error taxonomy + CI parity job (release items deferred per hold) |
| 23 | ✅ Done — Key Transaction + OTel Metrics + StatsD + CWMS + plugin hook + per-concern mappings + numeric score |
| 24 | ✅ Done — 8 second-wave transformers (DB monitoring, on-host integrations, security signals, custom entities, log archive, metric normalization, specialized synthetic, saved-filter notebooks) |
| 3rd-pass | ✅ Done — OTelCollectorTransformer + Legacy ErrorInbox + Legacy RequestNaming + CustomEventTransformer alias |
| 25 | ✅ Done — Gen3 workarounds for 6 of 8 Gen2-only capabilities (severity fanout, computeFields tags, entity-ID segments, Document tags, location lister, dashboard fallback) |
| 26 | ✅ Done — Validation layer (Hypothesis property-based T6 + schema harness T1 + IaC harness T3) |
