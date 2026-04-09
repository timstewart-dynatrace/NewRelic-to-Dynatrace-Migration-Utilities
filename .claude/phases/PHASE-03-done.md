# Phase 03 — Environment Registry & Live Validation
Status: PENDING

## Goal
Port the DTEnvironmentRegistry from the Migrator repo to enable live DT environment validation — verify metrics exist, resolve entities, fuzzy-match field names before uploading.

## Tasks
- [ ] Port `registry/environment.py` from Dynatrace_NRQL_Dashboard_Migrator
  - `DTEnvironmentRegistry` class with lazy-loaded registries
  - Metric registry: `metric_exists()`, `find_metric()` (fuzzy search with synonyms)
  - Entity registry: `get_entity()` by name/type
  - Dashboard registry: `dashboard_exists()`
  - Synthetic location registry: `get_synthetic_location()`
  - Management zone registry: `get_management_zone()`
  - `SYNONYMS` dict for fuzzy matching (14 semantic groups)
- [ ] Port `SLOAuditor` from Migrator repo
  - `extract_metrics_from_dql()` — find metric references in DQL
  - `validate_slo()` — check if SLO metrics exist
  - `find_correct_metric()` — fuzzy search for correct metric key
  - `audit_slos()` — batch audit all SLOs
- [ ] Integrate registry into `NRQLtoDQLConverter` for optional live field validation
- [ ] Integrate registry into `DashboardTransformer` for metric existence checks
- [ ] Add `--validate` flag to CLI that runs live validation against DT environment
- [ ] Add `audit-slos` CLI subcommand
- [ ] Port OAuth authentication support (`auth.py`) — support both API token and OAuth2 client credentials
- [ ] Add confidence scoring with structured notes (from nrql-translator): `dataSourceMapping`, `fieldExtraction`, `keyDifferences`, `performanceConsiderations`, `testingRecommendations`
- [ ] Tests for registry (mocked HTTP), SLO auditor, auth helpers

## Acceptance Criteria
- Registry connects to live DT environment and caches results
- Fuzzy metric search finds correct metrics with >80% accuracy on synonym matches
- SLO auditor identifies missing metrics before upload
- OAuth flow works alongside API token auth
- Confidence scoring returns structured notes, not just warnings list
- All new code has tests

## Decisions Made This Phase
(append as you go)
