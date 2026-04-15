# Phase 23 — nrql-engine Parity Port
Status: PENDING

## Goal
Port the capabilities where the TypeScript sibling (`/Users/Shared/GitHub/PROJECTS/nrql-engine/`) is ahead of this Python project. Details in `docs/nrql-engine-sync-audit.md`.

## Tasks
- [x] ~~P0-shorthand~~ moved to Phase 19b (active)
- [x] ~~K8s overrides~~ moved to Phase 19b (active)
- [ ] **KeyTransactionTransformer:** New `transformers/key_transaction_transformer.py`. Input: NR KeyTransaction entity. Output: SLO envelope + entity tag (OpenPipeline enrichment) + Workflow trigger. Register in `transformers/__init__.py` + migrate orchestrator.
- [x] ~~DQL fixer rules 7–20~~ moved to Phase 19b (active)
- [ ] **OTelMetricsTransformer:** New `transformers/otel_metrics_transformer.py`. NR OTel metrics config → DT OTLP metrics ingestion settings (`builtin:otel.ingest.metrics`). Distinct from PrometheusTransformer.
- [ ] **StatsDTransformer:** New `transformers/statsd_transformer.py`. NR StatsD ingestion config → DT StatsD metrics extension.
- [ ] **CloudWatchMetricStreamsTransformer:** New `transformers/cloudwatch_metric_streams_transformer.py`. Supplement CloudIntegrationTransformer with the Kinesis-firehose CloudWatch metric-streams path.
- [ ] **MetricTransform plugin hook:** Add `MetricTransform` protocol + `NRQLtoDQLConverter.add_metric_transform()` so operators can inject custom metric renames without forking.
- [ ] **Split metric-map files:** Break `transformers/nrql_mapping_rules.py` into per-concern modules (`mappings/metrics.py`, `mappings/attributes.py`, `mappings/aggregations.py`, `mappings/event_types.py`) — keep `nrql_mapping_rules.py` as a re-export shim for backward compat.
- [ ] **Numeric confidence score:** Ensure `ConversionResult.confidence_score` (0–100) is always populated alongside HIGH/MEDIUM/LOW to match TS output and downstream reporting.

## Acceptance Criteria
- Coverage matrix rows currently ahead in nrql-engine (K8s entity fields, Key Transactions, OTel metrics, StatsD, CloudWatch metric streams) flip to ✅.
- `pytest tests/ -q` stays green.
- No regressions in the 292 compiler patterns.
- ≥ 30 new tests across the ported modules.
- `docs/nrql-engine-sync-audit.md` updated with "status: synced" for each ported item.

## Decisions Made This Phase
(append as you go)
