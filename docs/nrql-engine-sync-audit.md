# nrql-engine ↔ Dynatrace-NewRelic Sync Audit

> **Audited:** 2026-04-15
> **Sibling repo:** `/Users/Shared/GitHub/PROJECTS/nrql-engine/` (TypeScript)
> **This repo:** `/Users/Shared/GitHub/PROJECTS/Dynatrace-NewRelic/` (Python)

The two projects are meant to stay feature-synced. This doc catalogs
where they diverge and identifies concrete opportunities to port work
back into Python.

## Shared features (both projects)

- NRQL→DQL compiler pipeline: Lexer → Parser → AST → DQL Emitter
- 292-pattern compiler test corpus
- Post-processors: COMPARE WITH → shift, EXTRAPOLATE, apdex buckets, funnel
- DQL validator + auto-fixer
- HIGH/MEDIUM/LOW confidence scoring
- Alert / Dashboard / Synthetic / SLO / Workload / Infra / Log / Tag / Drop-Rule / Notification transformers

## Where nrql-engine is ahead of Python

| # | Feature | TS module | Current Python status |
|---|---|---|---|
| 1 | **Key Transaction transformer** — NR Key Transactions → DT entity tag + SLO + Workflow bundle | `src/transformers/key-transaction.transformer.ts` | 🔴 No equivalent. Alerts map 1:1 but Key Transactions as a first-class entity are dropped. |
| 2 | ~~Phase 0 shorthand expansion~~ | `NRQLCompiler.expandNrShorthands()` | ✅ **At parity (Phase 19b, 2026-04-15).** `compiler/shorthands.py` ports the exact 9-pattern list; `compiler.compiler._expand_nr_shorthands` delegates. 10 regression tests in `TestShorthandExpansion`. |
| 3 | ~~K8s metric overrides + K8s entity-field map~~ | `DQLEmitter.K8S_METRIC_OVERRIDES` + `K8S_ENTITY_FIELDS` | ✅ **At parity (Phase 19b).** `compiler/emitter.py:207,222` already carries the exact same dicts. `TestK8sOverridesParity` pins 10 metric keys + 3 entity-field keys to the TS values. |
| 4 | ~~Richer DQL fixer rules~~ | `dql-fixer.ts` (22 private `fix*` methods) | ✅ **Python is at or above parity (Phase 19b).** `validators/dql_fixer.py` exposes 24 `_fix_*` methods, one-to-one with every TS fixer via snake-case mapping. `TestDQLFixerParity` pins the mapping. |
| 5 | **OTel metrics transformer** — OTLP ingestion path for metrics (separate from Prometheus) | `src/transformers/otel-metrics.transformer.ts` | 🔴 Not present; Phase 18 Prometheus transformer covers remote-write only |
| 6 | **StatsD + CloudWatch Metric Streams transformers** | `src/transformers/statsd.transformer.ts`, `cloudwatch-metric-streams.transformer.ts` | 🔴 StatsD is a known gap in coverage matrix §4; CloudWatch Metric Streams not individually addressed |
| 7 | **`MetricTransform` callback framework** — plugin-style metric resolution for customer-specific mappings | `src/transformers/metric-transform.interface.ts` | 🔴 No equivalent; Python hard-codes mappings |
| 8 | **Default metric map file** — `default-metric-map.ts` as an isolated overridable file | `src/transformers/default-metric-map.ts` | 🟡 Python has `transformers/nrql_mapping_rules.py` but it's 9-in-1; operators can't override single entries cleanly |
| 9 | **Subpath exports for tree-shaking** — `@nrql-engine/compiler`, `@nrql-engine/validators` etc. | `package.json` exports map | N/A — less relevant for Python; no port needed |

## Where Python is ahead of nrql-engine

| Feature | Python module |
|---|---|
| Explicit Phase 19 `_apply_phase19_uplift()` — post-processor loop-back confidence raising | `transformers/nrql_converter.py` end-of-file |
| `--legacy` flag + Gen2 fallback (clients/transformers/exporters) | Phase 14 deliverables |
| NRDB pre-decommission archive tool (resumable JSONL) | `tools/nrdb_archive.py` (Phase 17) |
| Agent migration orchestrator (7 languages, action plans) | `agents/` (Phase 16) |
| Custom instrumentation translator (JS/TS/Python/Java patterns) | `transformers/custom_instrumentation_translator.py` (Phase 16) |
| Identity transformer with SAML + SCIM runbooks | `transformers/identity_transformer.py` (Phase 17) |
| Cloud (AWS/Azure/GCP) + Kubernetes + AIOps + Vulnerability + NPM + AI Monitoring + Prometheus | Phase 18 deliverables |
| Preflight tenant capability check | `migrate.py preflight` (Phase 14) |
| Full NR Lambda layer ARN resolver (runtime × arch) | `transformers/lambda_transformer.py` (Phase 16) |

## Top porting opportunities — remaining after Phase 19b

> Items 1, 2, 4 from the original audit turned out to be **already at parity**
> after direct source inspection. Phase 19b landed regression tests that
> guard against future drift. The remaining real gaps are:

1. **Key Transaction transformer (⭐ coverage gap)** — new `transformers/key_transaction_transformer.py` — bundles: apdex T-value → SLO envelope + entity tag + Workflow. Matrix §1 row currently 🔴.
2. **OTel metrics + StatsD + CloudWatch Metric Streams transformers (⭐ closes §4 gaps)** — three new transformers under `transformers/`, wired into migrate orchestrator. Eliminates three of the remaining §4 Infra gaps.
3. **`MetricTransform` plugin hook** — callable hook in `NRQLtoDQLConverter.add_metric_transform()` so customers can inject project-specific metric renames without forking the code.
4. **Split metric-map files** — break `transformers/nrql_mapping_rules.py` into per-concern modules so operators can pin just one override.

All remaining items are tracked in `.claude/phases/PHASE-23-pending.md`.

## Minor additions (nice-to-haves)

- **`MetricTransform` plugin framework** — a callable hook in `NRQLtoDQLConverter` so customers can inject project-specific metric renaming without forking the code.
- **Overridable default-metric map** — split `transformers/nrql_mapping_rules.py` into per-concern files (metrics / attrs / aggregations / event types) so operators can pin just one override.
- **TypeScript parity for ConversionResult** — ensure `confidence_score` numeric (0–100) is always set, not just categorical HIGH/MEDIUM/LOW, to match TS output and allow richer reporting.

## Recommendation

Create a new **Phase 23 — nrql-engine parity** immediately after Phase 22,
or inject the top 5 items into the existing Phase 19 (compiler uplift) and
Phase 18 (specialized products). Items 1, 2, 4 are compiler-level and fit
Phase 19 extensions; items 3, 5 are new transformers and fit a parity-focused
Phase 23.


## Second-pass audit (2026-04-15, post-Phase-23)

After landing Phases 16–23 + 19b, a second sweep of `nrql-engine`
identified ~8 transformer-shaped capabilities the Python project may
still lack. Each must be verified against actual TS source before
porting (the first-pass audit was overstated).

| Candidate | Python status |
|---|---|
| `DatabaseMonitoringTransformer` | 🔴 No equivalent — covers MySQL/Postgres/Mongo/Redis → DT DB extensions |
| `OnHostIntegrationTransformer` | 🔴 No equivalent — NGINX/HAProxy/Kafka/Elasticsearch/etc. config |
| `SecuritySignalsTransformer` | 🔴 NR Security Signals/IAST → DT Security Investigator |
| `CustomEntityTransformer` | 🔴 NR custom entities → DT custom-device API |
| `LogArchiveTransformer` | 🔴 NR Log Live Archive → Grail bucket + OpenPipeline egress |
| `MetricNormalizationTransformer` | 🔴 Rename / aggregate / drop metric processor rules |
| `SyntheticSpecializedTransformer` | 🔴 Cert-check + broken-links monitor specialization |
| `SavedFilterNotebookTransformer` | 🟡 Phase 19 covers dashboard saved filters; notebooks not handled |

**Already at parity (verified during second pass):**
- `NotificationTransformer` (folded into `alert_transformer.py` Phase 11)
- `OpenTelemetryCollectorTransformer` (Phase 23 `OTelMetricsTransformer`)
- `DashboardWidgetUpgradeTransformer` (Phase 19 dashboard parity)
- `MultiLocationSyntheticTransformer` (Phase 17 `NonNRQLAlertTransformer`)
- `DavisTuningTransformer` (Phase 17/18 `BaselineAlertTransformer` + `AIOpsTransformer`)
- `CustomInstrumentationTransformer` (Phase 16)
- `CustomEventTransformer` (Phase 17 `CustomEventIngestTransformer`)

**Test count delta:** TS has 220 test files; Python has 66 (lower count
because Python tests cover more per-file with parametrization). Both
project test counts approximate the same number of assertions
(Python: 1151 + 8; TS: ~838 across 6 modules).

**Tracked in Phase 24 — second-wave parity port** (new, pending —
release-hold also applies).
