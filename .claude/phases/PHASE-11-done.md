# Phase 11 — Gen3 Transformer Target Swap
Status: ACTIVE

## Goal
Rewrite all entity transformers to emit Gen3 Dynatrace objects by default (Workflows, Segments, Davis Anomaly Detectors, OpenPipeline enrichment, Document API). Gen2 paths remain available behind a `--legacy` flag (implemented in Phase 14).

## Scope — Gen2 → Gen3 Substitution Map
| Transformer | Gen2 target (old) | Gen3 target (new default) |
|---|---|---|
| AlertTransformer | Alerting Profile + Metric Event | Workflow (Davis event trigger) + `builtin:davis.anomaly-detectors` |
| NotificationTransformer | Problem Notification | Workflow action task (email/slack/webhook) |
| InfrastructureTransformer | Metric Event (Config v1) | `builtin:davis.anomaly-detectors` + Workflow |
| WorkloadTransformer | Management Zone (Config v1) | `builtin:segment` + bucket-scoped IAM policy |
| TagTransformer | Auto-Tag Rule (`builtin:tags.auto-tagging`) | OpenPipeline enrichment (`builtin:openpipeline.logs.pipelines`, events/bizevents/metrics) |
| DashboardTransformer | Config v1 Dashboard fallback | Document API only (`type=='dashboard'`, Grail DQL tiles) |
| SyntheticTransformer | Config v1 `/synthetic/monitors` | `builtin:synthetic_test` (Settings 2.0) |
| SLOTransformer | Config v1 `/slo` | `builtin:monitoring.slo` (Settings 2.0) |
| LogParsingTransformer | Config v1 log processing rule | OpenPipeline processor (`builtin:openpipeline.logs.pipelines`) |
| DropRuleTransformer | Config v1 ingest rule | OpenPipeline drop processor |

## Tasks
- [ ] Update `transformers/alert_transformer.py` — emit Workflow JSON (`dynatrace_automation_workflow` shape) with Davis event trigger + Anomaly Detector payload
- [ ] Update `transformers/notification_transformer.py` — emit Workflow task definitions (email/slack/webhook) instead of Problem Notification configs
- [ ] Update `transformers/infrastructure_transformer.py` — emit Davis Anomaly Detector payloads + paired Workflow
- [ ] Update `transformers/workload_transformer.py` — emit `builtin:segment` payload + IAM policy skeleton
- [ ] Update `transformers/tag_transformer.py` — emit OpenPipeline enrichment processor payloads
- [ ] Update `transformers/dashboard_transformer.py` — remove Config v1 fallback from default path (keep for `--legacy`)
- [ ] Update `transformers/synthetic_transformer.py` — target `builtin:synthetic_test`
- [ ] Update `transformers/slo_transformer.py` — target `builtin:monitoring.slo`
- [ ] Update `transformers/log_parsing_transformer.py` — emit OpenPipeline processor
- [ ] Update `transformers/drop_rule_transformer.py` — emit OpenPipeline drop processor
- [ ] Update each `{Entity}TransformResult` docstring to note Gen3 target schema
- [ ] Move existing Gen2 logic into `transformers/legacy/` submodule for Phase 14 reuse (do NOT delete)

## Acceptance Criteria
- All 10 transformers emit Gen3 payloads by default
- Legacy Gen2 code preserved under `transformers/legacy/`
- All transformer unit tests either updated to assert Gen3 shape OR moved to `tests/legacy/`
- No test file is deleted — tests for Gen2 targets migrate to legacy suite
- `pytest tests/ -v` passes
- Zero references to Alerting Profile / Management Zone / Auto-Tag Rule / Problem Notification / Metric Event in default code paths (grep clean outside `transformers/legacy/`)

## Decisions Made This Phase
(append as you go)
