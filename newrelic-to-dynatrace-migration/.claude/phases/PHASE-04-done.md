# Phase 04 — New Entity Transformers
Status: DONE

## Goal
Add transformers for New Relic entity types that are currently missing, expanding migration coverage beyond dashboards/alerts/synthetics/SLOs/workloads.

## Tasks
- [ ] **Infrastructure Conditions transformer**
  - NR host-not-reporting conditions → DT metric events with `builtin:host.availability`
  - NR process-not-running conditions → DT metric events with `builtin:tech.generic.process.count`
  - Map infrastructure thresholds to DT static threshold strategy
- [ ] **Log Parsing Rules transformer**
  - NR Grok/regex ingest rules → DT Log Processing Rules with DPL patterns
  - Leverage existing `RegexToDPLConverter` for pattern conversion
  - Map NR log attribute extraction to DT log processing pipeline
- [ ] **Tags/Labels migration**
  - NR entity tags → DT auto-tags (rule-based) or manual tags
  - Build tag rules from NR tag key/value pairs
  - Support tag-based management zone creation
- [ ] **Key Transactions transformer**
  - NR key transaction settings → DT service-level request naming rules
  - Map transaction name patterns to DT request attribute rules
- [ ] **NRQL Drop Rules transformer**
  - NR data drop filter rules → DT Log/Metric ingest rules
  - Map NR drop rule conditions to DT processing rule conditions
- [ ] **Notification Destinations v2 transformer**
  - NR newer notification system (replacing channels) → DT problem notifications
  - Support email, Slack, PagerDuty, webhook, Jira, ServiceNow destinations
  - Map NR workflow triggers to DT alerting profile event filters
- [ ] Register all new transformers in `transformers/__init__.py`
- [ ] Add to `MigrationOrchestrator` in `migrate.py`
- [ ] Update `AVAILABLE_COMPONENTS` with new entries
- [ ] Tests for each new transformer

## Acceptance Criteria
- Each new transformer follows existing pattern (dataclass result, transform/transform_all)
- Infrastructure conditions produce valid DT metric events
- Log parsing rules produce valid DT processing rules with DPL patterns
- Tags produce valid DT auto-tag rules
- All new transformers registered and accessible via CLI `--components` flag
- Tests cover happy path + error cases for each transformer

## Decisions Made This Phase
(append as you go)
