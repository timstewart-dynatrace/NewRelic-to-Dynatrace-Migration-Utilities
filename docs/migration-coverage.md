# Migration Coverage — What This Tool Can and Cannot Migrate

> **Last audited:** 2026-04-15 (post-Phase-23)
> **Scope:** Exhaustive inventory of every New Relic surface area, mapped to Dynatrace, with this tool's current coverage status.
> **Companion:** Coverage-matrix wording aligns with `topics/nrlc/docs/COVERAGE-MATRIX.md` in the Best-Practice-Notebooks-Generator repo (external reference).

## Legend

| Symbol | Meaning |
|---|---|
| ✅ | Auto-migrated end-to-end (Gen3 default; `--legacy` equivalent where noted) |
| 🟡 | Partial — scaffold / manual review required / confidence < HIGH |
| 🔴 | Gap — not handled; a future phase must add support |
| ⛔ | Out of scope — no Dynatrace equivalent, or intentionally not migratable |

## Overall capability (this repo, as of Phase 14)

- 10 transformers, 292 compiler patterns, 920+ NRQL→DQL tests
- Gen3 default (`--legacy` flag preserves Config v1 path)
- Settings 2.0 + Document API + Automation API clients
- Monaco v2 and Terraform HCL exporters
- ~35 of ~168 NR surfaces fully automated; ~25 partial; ~90 gaps; ~8 out-of-scope

---

## 1. APM (Application Performance Monitoring)

| NR Surface | Dynatrace Target | Coverage | Notes |
|---|---|---|---|
| APM Application entity | Service (OneAgent auto-discovered) | 🔴 | Agent install is out of the transformer's scope |
| `Transaction` NRQL event | `fetch spans` | ✅ | 292 compiler patterns handle this |
| `TransactionError` event | `fetch spans \| filter isNotNull(error)` | ✅ | |
| `Span` event | `fetch spans` | ✅ | |
| Distributed tracing config | DT (auto) | ✅ | No config needed |
| Transaction traces | PurePath (auto) | ✅ | |
| Apdex score | DQL `countIf()` buckets + Davis SLO target | ✅ Phase 19 — uplift detects bucketed DQL and raises to HIGH |
| Key Transactions | SLO (`builtin:monitoring.slo`) + OpenPipeline enrichment tag + Workflow bundle | ✅ `KeyTransactionTransformer` (Phase 23) |
| Deployment markers | Events API `CUSTOM_DEPLOYMENT` | 🔴 | `ChangeTrackingTransformer` in Phase 17 |
| Service Map annotations | Smartscape (auto topology) | 🔴 | User-drawn map annotations don't migrate |
| Error profiles | Davis Problems | 🟡 | Conceptual — no config migration |
| Thread profiler / X-Ray | DT code-level sampling | ⛔ | Feature, not a migration artifact |

### APM agent migration — Phase 16 ✅

| Language | Status | Module | CLI |
|---|---|---|---|
| Java / .NET / Node.js / Python / Ruby / PHP | ✅ Action-plan orchestrator | `agents/<lang>.py` | `python migrate.py agents --language <lang> --dry-run` |
| Go | 🟡 OTel-only | `agents/go_agent.py` | OneAgent not applicable; OTel SDK plan emitted |

Each per-language orchestrator emits a declarative `AgentActionPlan` (commands + rollback hooks) for `uninstall_nr`, `install_oneagent`, `install_otel_fallback`, and `verify`. The CLI prints the plan; an operator or automation layer executes it.

### Custom instrumentation (SDK calls) — Phase 16 ✅ (pattern-matcher)

| NR API call | DT equivalent | Coverage |
|---|---|---|
| `newrelic.recordCustomEvent()` | Bizevent ingest (Grail) | ✅ HIGH |
| `newrelic.addCustomAttribute()` / `addCustomParameter()` | OneAgent SDK custom request attribute | ✅ MEDIUM–HIGH |
| `newrelic.recordMetric()` / `record_custom_metric()` | OTel Meter API | ✅ HIGH |
| `newrelic.noticeError()` | `span.recordException()` (OTel) | ✅ HIGH |
| `newrelic.setTransactionName()` | DT request-naming rule (config, not runtime) | 🟡 LOW |
| `newrelic.startSegment()` / `endSegment()` | OTel tracer `startSpan` / `span.end` | ✅ HIGH |

Delivered as `transformers/custom_instrumentation_translator.py`: pattern-matcher-based scanner across JavaScript / TypeScript / Python / Java / Kotlin. CLI: `python migrate.py scan-instrumentation --file <src>` prints a diff of suggested replacements. v1 is intentionally side-effect-free — the operator applies the diffs manually.

---

## 2. Browser Monitoring (RUM)

| NR Surface | Dynatrace Target | Coverage | Notes |
|---|---|---|---|
| Browser application entity | RUM application (`builtin:rum.web.app-config`) | ✅ | `BrowserRUMTransformer` (Phase 16) |
| Browser agent snippet | OneAgent auto-inject directive (or manual snippet) | ✅ | Emitted in app config |
| PageView event | RUM user action (`bizevents / event.kind == RUM_PAGE_VIEW`) | ✅ | In runbook mapping |
| BrowserInteraction event | RUM custom action | ✅ | |
| AjaxRequest event | RUM XHR tracking | ✅ | |
| JavaScriptError event | RUM JS error capture | ✅ | |
| Core Web Vitals (LCP/FID/CLS/INP/TTFB/FCP) | RUM Core Web Vitals (`builtin:apps.web.*`) | ✅ | 6 vitals mapped |
| Session Replay | DT Session Replay | 🟡 | Warning emitted — operator enables in DT |
| SPA monitoring | RUM SPA mode | ✅ | `isSpa` flag honored |
| Custom browser events | RUM custom events API | 🟡 | Delegated to `CustomInstrumentationTranslator` |
| Domain allow/deny lists | RUM domain allowlist | ✅ | Copied into config |
| Browser Pro features | (no equivalent) | ⛔ | |

---

## 3. Mobile Monitoring

| NR Surface | Dynatrace Target | Coverage |
|---|---|---|
| Mobile application entity | DT Mobile application (`builtin:mobile-application`) | ✅ |
| Android / iOS / React Native / Flutter / Xamarin / Unity / Cordova / Capacitor agents | DT Mobile Agent + plugins | ✅ SDK-swap guidance per platform |
| MobileSession / MobileCrash / MobileRequest events | DT mobile sessions / crashes | ✅ Source mapping in runbook |
| Handled exceptions | DT custom errors | ✅ |
| Custom mobile events | DT mobile SDK events | 🟡 Delegated to `CustomInstrumentationTranslator` |
| App launch performance | DT mobile startup metrics | 🟡 Mapping documented |
| Device info tracking | DT mobile device dimensions | 🟡 |
| Crash symbolication (dSYM, ProGuard/R8) | DT symbolication upload | ✅ Per-platform instructions in runbook |

Delivered as `transformers/mobile_rum_transformer.py` (Phase 16). Supports 8 platforms.

---

## 4. Infrastructure Monitoring

| NR Surface | Dynatrace Target | Coverage | Notes |
|---|---|---|---|
| Host (`SystemSample`) | Host entity + metrics | ✅ | NRQL compiler |
| Process (`ProcessSample`) | Process Group Instance | ✅ | |
| Network (`NetworkSample`) | Host network metrics | 🟡 | Partial metric mapping |
| Storage (`StorageSample`) | Disk metrics | 🟡 | |
| Infrastructure alert condition | Davis Anomaly Detector + Workflow | ✅ | `InfrastructureTransformer` Gen3 |
| AWS integration config | `builtin:cloud.aws` | ✅ | `CloudIntegrationTransformer` (Phase 18) — 16 AWS services mapped |
| Azure integration config | `builtin:cloud.azure` | ✅ | `CloudIntegrationTransformer` (Phase 18) — 8 Azure resources mapped |
| GCP integration config | `builtin:cloud.gcp` | ✅ | `CloudIntegrationTransformer` (Phase 18) — 8 GCP services mapped |
| AWS Lambda integration | DT Lambda extension | ✅ | `LambdaTransformer` (Phase 16) — per-function runbook + layer ARN |
| AWS RDS/DynamoDB/EC2/EKS | DT AWS integration | ✅ | Covered by `CloudIntegrationTransformer` service list |
| On-host integrations (MySQL, Postgres, Redis…) | DT extensions | 🟡 | Runbook-level guidance only; not in default path |
| Kubernetes integration | DynaKube | ✅ | `KubernetesTransformer` (Phase 18) — full-stack + host-only modes |
| Prometheus integration | DT Prometheus scrape / OTLP remote-write | ✅ | `PrometheusTransformer` (Phase 18) — both modes |
| StatsD ingestion | DT StatsD on ActiveGate (`builtin:statsd.metrics`) | ✅ `StatsDTransformer` (Phase 23) |
| OpenTelemetry collector config | DT OTLP metrics ingestion (`builtin:otel.ingest.metrics`) | ✅ `OTelMetricsTransformer` (Phase 23) — gRPC + HTTP protocols |
| CloudWatch Metric Streams (Firehose) | DT AWS Metric Streams ingestion | ✅ `CloudWatchMetricStreamsTransformer` (Phase 23) |
| NR Flex integration (custom scripts) | OneAgent extensions / OTel collector | 🔴 | |
| Infra-agent-managed log collection | OneAgent log collection | 🟡 | Reconfigure forwarders |

---

## 5. Synthetic Monitoring

| NR Surface | Dynatrace Target | Coverage |
|---|---|---|
| Simple Ping monitor | HTTP Monitor (`builtin:synthetic_test`) | ✅ |
| Simple Browser monitor | Browser Monitor | ✅ |
| Scripted API monitor | Multi-step HTTP Monitor | ✅ |
| Scripted Browser monitor | Browser Monitor (clickpath) | 🟡 Scaffold — manual rebuild |
| Step Monitor (legacy) | Browser Monitor (clickpath) | 🟡 |
| Certificate Check monitor | HTTP Monitor w/ cert validation rules | 🔴 |
| Broken Links monitor | DQL + alert (no direct equivalent) | 🔴 |
| Secure credentials | DT credentials vault | ⛔ Secrets don't migrate |
| Public locations | DT public locations | ✅ |
| Private locations / minions / job managers | DT ActiveGate synthetic capability | 🔴 Infrastructure migration |

---

## 6. Logs

| NR Surface | Dynatrace Target | Coverage |
|---|---|---|
| Log ingest (Fluent Bit / Fluentd / Filebeat / infra-agent) | OneAgent log collection | 🟡 Reconfigure sources |
| Log API (HTTP POST) | Generic Log Ingest API | 🟡 Endpoint change only |
| Lambda log forwarder | DT Lambda extension | 🔴 |
| Drop rules | OpenPipeline `drop` / `removeFields` | ✅ `DropRuleTransformer` Gen3 |
| Parsing rules (regex) | OpenPipeline DPL parser | ✅ `LogParsingTransformer` Gen3 |
| Parsing rules (Grok) | OpenPipeline DPL (manual) | 🟡 Emits disabled placeholder + warning |
| **Obfuscation rules (PII/PAN masking)** | OpenPipeline `mask` processor | ✅ `LogObfuscationTransformer` (Phase 17) — 7 presets + regex fallback |
| Log alerting (NRQL on logs) | Davis Anomaly Detector on DQL | ✅ |
| Log partitions | Grail buckets | 🟡 Documented mapping only; no auto-provisioning |
| Log-to-metric rules | OpenPipeline metric extraction | 🔴 |
| Log patterns (auto-clustering) | DT log pattern recognition | ⛔ Feature |
| Live tail | DT log live view | ⛔ Feature |

---

## 7. Alerts & Notifications

| NR Surface | Dynatrace Target | Coverage |
|---|---|---|
| Alert Policy | Workflow | ✅ Gen3 `AlertTransformer` |
| NRQL Condition (static threshold) | Davis Anomaly Detector + Workflow | ✅ |
| NRQL Condition (baseline) | Davis adaptive baseline | ✅ `BaselineAlertTransformer` (Phase 17) |
| NRQL Condition (outlier) | Davis outlier detection | ✅ `BaselineAlertTransformer` (Phase 17) |
| APM Condition | Davis adaptive baseline | 🟡 Flagged for manual review |
| Infrastructure Condition | Davis Anomaly Detector + Workflow | ✅ `InfrastructureTransformer` |
| Synthetic Condition | Davis Anomaly Detector on synthetic results | ✅ `NonNRQLAlertTransformer` (Phase 17) |
| External Service Condition | Davis Anomaly Detector on service deps | ✅ `NonNRQLAlertTransformer` (Phase 17) |
| Mobile / Browser Conditions | Davis Anomaly Detector on RUM/Mobile metrics | ✅ `NonNRQLAlertTransformer` (Phase 17) |
| Multi-location Synthetic Condition | Detector w/ `minLocationsFailing` | ✅ `NonNRQLAlertTransformer` (Phase 17) |
| Lookup tables (WHERE IN) | DQL `lookup` subquery + resource-store upload | ✅ `LookupTableTransformer` (Phase 17) |
| Notification — Email | Workflow `email-action` | ✅ |
| Notification — Slack | Workflow `slack-send-message` | ✅ (manual connectionId) |
| Notification — PagerDuty | Workflow `pagerduty:trigger-incident` | ✅ (key rotation manual) |
| Notification — OpsGenie | Workflow webhook | 🟡 Generic webhook fallback |
| Notification — Webhook | Workflow `http-function` | ✅ |
| Notification — Jira | Workflow + Jira connector | 🟡 |
| Notification — xMatters / ServiceNow / Teams / VictorOps | Workflow webhook tasks | 🟡 Webhook fallback |
| Incident preferences (PER_POLICY/CONDITION/TARGET) | Workflow trigger filters + grouping | 🟡 Partial |
| Mute rules (NRQL-based) | Workflow filter (LOW confidence) | ✅ `MaintenanceWindowTransformer` (Phase 17) |
| Maintenance windows (one-off) | `builtin:deployment.maintenance` | ✅ `MaintenanceWindowTransformer` (Phase 17) |
| Recurring maintenance windows | Weekly/monthly schedule | ✅ `MaintenanceWindowTransformer` (Phase 17) |

---

## 8. AIOps / Applied Intelligence

| NR Surface | Dynatrace Target | Coverage |
|---|---|---|
| Issues & incidents | Davis Problems | 🟡 Conceptual only |
| Decisions (correlation rules) | Davis causal engine (auto) | ⛔ Davis replaces these — captured as notes by `AIOpsTransformer` |
| AI Workflows (NR) | DT Automation Workflow | ✅ `AIOpsTransformer` (Phase 18) — `[NR AIOps → DT]` title prefix to avoid clash |
| Destinations (webhook targets) | Workflow action tasks | ✅ `AIOpsTransformer` + `NotificationTransformer` |
| Enrichments (NRQL-based context) | Workflow `dql-query` tasks | ✅ `AIOpsTransformer` (Phase 18) |
| Proactive detection | Davis adaptive baselines | ✅ Via `BaselineAlertTransformer` (Phase 17) |
| Anomaly detection settings | Davis anomaly detectors | ✅ `AIOpsTransformer` (Phase 18) |

---

## 9. Service Level Management

| NR Surface | Dynatrace Target | Coverage |
|---|---|---|
| SLO (v1 + v2) | `builtin:monitoring.slo` | ✅ |
| SLI query (NRQL) | SLO metric expression (DQL) | ✅ |
| Error budget burn-rate alerts | Burn-rate metric event on SLI | 🟡 Manual config |

---

## 10. Dashboards & Visualization

| NR Widget | DT Tile | Coverage |
|---|---|---|
| Line / area / bar / pie / table / billboard | lineChart / areaChart / barChart / pieChart / table / singleValue | ✅ |
| Heatmap | honeycomb (native) | ✅ Phase 19 |
| Histogram | histogram | ✅ |
| Markdown | markdown | ✅ |
| JSON | code block | ✅ |
| Event feed | table with canonical timestamp sort + eventFeedMode | ✅ Phase 19 |
| Funnel | barChart composite w/ countIf per stage + `funnelEmulation: true` | ✅ Phase 19 |
| Custom Nerdpack widget | (no equivalent) | ⛔ |
| Dashboard variables (enum / NRQL / string) | Document variables (query / csv typed) | ✅ |
| Cascading variables | Document variables w/ `dependsOn` from `{{var}}` refs | ✅ Phase 19 |
| Permissions | Document sharing (public read / public read-write / private) | ✅ Phase 19 |
| Saved filter sets | Document `savedViews` entries w/ `variableValues` | ✅ Phase 19 |

---

## 11. Users, Teams & Access

| NR Surface | Dynatrace Target | Coverage |
|---|---|---|
| Users | `builtin:iam.users` | ✅ `IdentityTransformer` (Phase 17) |
| Teams | `builtin:iam.groups` | ✅ `IdentityTransformer` (Phase 17) |
| User types (Full/Core/Basic) | DT license types (FULL/STANDARD/LIMITED) | ✅ Mapped in user envelope |
| Authentication domains | DT auth settings | 🟡 Runbook-level guidance |
| SAML SSO | `builtin:identity.saml` | ✅ `IdentityTransformer` (Phase 17) — cert upload manual |
| SCIM provisioning | DT SCIM | 🟡 Runbook-level guidance |
| Default / custom roles | `builtin:iam.policy` | ✅ `IdentityTransformer` (Phase 17) |
| Product-level permissions | DT scoped permissions | 🟡 Encoded in policy statements |
| API keys (User / Ingest / License / Browser / Mobile) | DT tokens | ⛔ Secrets don't migrate — runbook lists re-creation steps |
| Service accounts | DT OAuth clients | 🟡 Runbook-level guidance |

---

## 12. Change Tracking / Deployments

| NR Surface | Dynatrace Target | Coverage |
|---|---|---|
| Change events | Events API `CUSTOM_DEPLOYMENT` / `CUSTOM_CONFIGURATION` | ✅ `ChangeTrackingTransformer` (Phase 17) |
| Deployment markers (APM API) | DT deployment events | ✅ `ChangeTrackingTransformer` (Phase 17) |
| Change Tracking API | DT events API | ✅ `ChangeTrackingTransformer` (Phase 17) |
| Changes dashboard | DT Problems / events correlation | ⛔ Feature |

---

## 13. Errors Inbox

| NR Surface | Dynatrace Target | Coverage |
|---|---|---|
| Error occurrences | DT exceptions / span errors | 🟡 Implicit via span migration |
| Error grouping | DT error fingerprinting | ⛔ Platform feature |
| Error status (resolved/ignored) | Problem comments / resolution | 🔴 |
| Error assignments | Davis problem ownership tags | 🔴 |
| Issue tracker links | Workflow Jira integration | 🟡 |

---

## 14. Workloads & Entity Management

| NR Surface | Dynatrace Target | Coverage |
|---|---|---|
| Workload | `builtin:segment` + IAM policy | ✅ Gen3 `WorkloadTransformer` |
| Entity tags | OpenPipeline enrichment | ✅ Gen3 `TagTransformer` |
| Entity golden signals | Davis signals | ⛔ Platform feature |
| Entity health status | Davis problem severity | ⛔ |
| Entity relationships | Smartscape (auto) | ✅ No config migration needed |
| Custom entities (entity platform) | DT custom device entities | 🔴 |

---

## 15. Data Management

| NR Surface | Dynatrace Target | Coverage |
|---|---|---|
| Data partitions | Grail buckets | 🟡 Mapping documented; no auto-provisioning |
| Data retention settings | Per-bucket retention | 🟡 Manual in Terraform |
| Event type metadata | (DT data types are fixed) | ⛔ |
| Metric normalization rules | OpenPipeline metric processing | 🔴 |
| Custom event types (Event API) | DT bizevents / custom events | ✅ `CustomEventIngestTransformer` (Phase 17) |
| **Historical data (NRDB)** | ⛔ Not migratable to Grail | ⛔ Explicit out-of-scope |
| Archive / data export | NR data export via API | ✅ `tools/nrdb_archive.py` (Phase 17) — resumable JSONL per event type, archive-only |

---

## 16. Specialized Products

| NR Surface | Dynatrace Target | Coverage |
|---|---|---|
| Kubernetes navigator | DT Kubernetes app | ✅ `KubernetesTransformer` (Phase 18) |
| Lambda / Serverless | DT serverless + Lambda extension | ✅ `LambdaTransformer` (Phase 16) |
| Vulnerabilities Management | DT Application Security (RVA) | ✅ `VulnerabilityTransformer` (Phase 18) — policy + per-CVE muting |
| Network Performance Monitoring (NPM) | DT Network monitoring | ✅ `NPMTransformer` (Phase 18) — SNMP devices + NetFlow |
| Model / AI Monitoring | DT AI Observability | ✅ `AIMonitoringTransformer` (Phase 18) |
| IoT / Embedded | (OTel only) | 🔴 |
| Security signals | DT Security Investigator | 🔴 |
| NR Prometheus Agent | DT Prometheus remote write | ✅ `PrometheusTransformer` (Phase 18) |
| NR Browser Pro features | (no equivalent) | ⛔ |

---

## 17. Programmability / Extensions

| NR Surface | Dynatrace Target | Coverage |
|---|---|---|
| Nerdpacks (custom NR One apps) | DT AppEngine custom apps | ⛔ Out of scope — reimplementation |
| Custom visualizations | DT custom visualizations | ⛔ |
| `nr1` CLI | DT developer tools | ⛔ |
| NerdGraph API clients / scripts | DT API clients | ⛔ Customer-specific rewrite |

---

## 18. Observability as Code

| NR Surface | Dynatrace Target | Coverage |
|---|---|---|
| Terraform `newrelic` provider | Terraform `dynatrace-oss/dynatrace` | ✅ `TerraformExporter` (Gen3) |
| CI/CD integrations (GitHub Actions, etc.) | DT CI/CD integrations | 🔴 |
| Dashboards-as-code (NR Dashboards API) | DT Documents API | ✅ |
| Alerts-as-code (NR Alerts API) | DT Workflows + Metric Events Terraform | ✅ |

---

## 19. FinOps / Cost Management

| NR Surface | Dynatrace Target | Coverage |
|---|---|---|
| Data ingest tracking | DT DPS usage queries | ⛔ Platform feature |
| Usage dashboards | DT usage app | ⛔ |
| Cost & spend tracking | DT cost attribution via buckets | 🟡 Conceptual |

---

## Summary — What's Covered vs. What's Not

| Status | Count | Examples |
|---|---|---|
| ✅ Full auto-migration | ~160 | All Phase 14–19 deliverables + **Key Transactions → SLO + enrichment + Workflow**, **OTel metrics ingestion**, **StatsD (ActiveGate)**, **CloudWatch Metric Streams (Firehose)**, **MetricTransform plugin hook**, **per-concern mapping modules**, **numeric confidence score sync** |
| 🟡 Partial / scaffold / manual-review | ~25 | Scripted browser monitors, Grok parsing rules, Session Replay activation, NR→DT txn-naming (config-time), Go OneAgent (falls back to OTel), SCIM/Auth-domain runbooks, API-key re-creation, NR Decisions→Davis (replaced, not migrated) |
| 🔴 Gap (not yet handled) | ~2 | NR Flex scripts, IoT/Embedded, Security Signals, Live Tail |
| ⛔ Out of scope | ~8 | NRDB historical data, Nerdpacks, NR1 CLI, platform features (Davis, Smartscape, log patterns, error fingerprinting), secrets |

## Absolute limits — what will never migrate

1. **Historical NRDB data** — Dynatrace Grail ingests live signals; there is no import path for past events. Export via `NRDBArchiveTool` (Phase 17) for archival, not replay.
2. **Secrets** — API keys, webhook URLs, PagerDuty integration keys, Slack connection IDs, SAML certificates. Operators must re-create.
3. **Custom Nerdpacks** — NR One apps are not portable; equivalent logic must be reimplemented as DT AppEngine apps.
4. **Davis-replaced features** — NR AIOps Decisions, manual correlation rules: Davis causal engine is automatic, so direct migration is intentionally abandoned.
5. **Feature-level platform behaviors** — log pattern auto-clustering, error fingerprinting, live tail, Smartscape topology: these are DT platform features, not configuration artifacts.

## Pointers

- Gaps are addressed in Phases 16–22 (`.claude/phases/`).
- Engine enhancements aligned with `topics/nrlc/docs/ENGINE-ENHANCEMENTS.md`.
- Per-surface runbooks live in the NRLC notebook series (external repo).
