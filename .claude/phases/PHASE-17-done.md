# Phase 17 — Close P1 Alerting/Data/Identity Gaps
Status: PENDING

## Goal
Add the transformers required for advanced alert conditions, identity migration, change tracking, data archival, and log obfuscation. These are the high-value P1 gaps from `docs/migration-coverage.md`.

## Tasks
- [ ] **`transformers/non_nrql_alert_transformer.py`** — NR Infrastructure / Synthetic / Browser / Mobile / External Service conditions → Metric Event + Workflow
  - Leverages existing `InfrastructureTransformer` pattern
  - New condition-type dispatchers per NR category
- [ ] **`transformers/baseline_alert_transformer.py`** — NR baseline / outlier conditions → Davis adaptive baseline / Davis outlier detection
  - Maps NR `baseline` direction → DT baseline `ABOVE_UPPER_BOUND` / `BELOW_LOWER_BOUND`
  - Outlier → Davis outlier detector payload
- [ ] **`transformers/lookup_table_transformer.py`** — NR lookup tables → DQL `lookup` subquery
  - Emits a subquery-producing DQL fragment usable inside anomaly-detector source DQL
  - Wires into `NRQLtoDQLConverter` via a new post-processor
- [ ] **`transformers/maintenance_window_transformer.py`** — NR maintenance windows + mute rules → DT Maintenance Window (`builtin:deployment.maintenance`)
  - One-off and recurring schedules
  - Mute-rule NRQL filter → Workflow filter or detector embedded filter
- [ ] **`transformers/change_tracking_transformer.py`** — NR Change Tracking / Deployment Markers → DT Events API `CUSTOM_DEPLOYMENT` / `CUSTOM_CONFIGURATION`
  - Import historical NR change events as replayable DT events (documented as non-canonical)
- [ ] **`transformers/identity_transformer.py`** — NR Users / Teams / Roles / SSO → DT Users / Groups / Policies / SAML
  - Users → `builtin:iam.users` (or OAuth client provisioning)
  - Teams → `builtin:iam.groups`
  - Roles → `builtin:iam.policy`
  - SAML config → `builtin:identity.saml`
  - SCIM mapping helper (no direct write, produces config doc)
- [ ] **`transformers/log_obfuscation_transformer.py`** — NR obfuscation rules → OpenPipeline `mask` processors
  - Regex → DPL mask pattern
  - PII/PAN preset detection → DT built-in redactors
- [ ] **`tools/nrdb_archive.py`** — NRDB export tool for pre-decommission snapshot
  - `python migrate.py archive --account <id> --since <date> --output <dir>`
  - Per-event-type JSONL files; resumable; documented as archive-only (not replayable)
- [ ] **`transformers/custom_event_ingest_transformer.py`** — NR custom event types (Event API) → DT bizevents or custom events
  - Ingest-path migration guidance emitted as a runbook artifact

## Acceptance Criteria
- Each new transformer has ≥ 15 unit tests with Gen3 assertions
- Lookup-table post-processor gets its own 30-pattern regression suite
- NRDB archive tool validated against a fixture NerdGraph response
- Coverage doc updated: the ~15 P1 rows flip to ✅ or 🟡 scaffold
- Full suite stays green

## Decisions Made This Phase
(append as you go)
