# Phase 12 — Client Layer Consolidation (Gen3 APIs)
Status: PENDING

## Goal
`clients/dynatrace_client.py` uses Settings 2.0, Document API v2, and Automation (Workflows) API as the default paths. Config API v1 methods are retained but isolated, only reachable via Phase 14's `--legacy` flag.

## Tasks
- [ ] Split `DynatraceClient` into three mixins/classes:
  - `SettingsV2Client` — `/api/v2/settings/objects` (schema-based CRUD, pagination via `nextPageKey`)
  - `DocumentClient` — `/platform/document/v1/documents` (pagination via `pageKey`, binary content)
  - `AutomationClient` — `/platform/automation/v1/workflows` (Workflows CRUD)
- [ ] Quarantine Config API v1 methods into `clients/legacy/config_v1_client.py`
- [ ] Default `DynatraceClient` constructor wires Settings 2.0 + Document + Automation only
- [ ] Add OAuth2 platform-token auth flow (required for Automation API) alongside existing Api-Token auth
- [ ] Retry/backoff policy applies uniformly (reuse `withRetry` pattern)
- [ ] Update `registry/environment.py` — entity/metric/dashboard lookups switch to Settings 2.0 + Document API
- [ ] Update all transformer import sites to use new client shape

## Acceptance Criteria
- `DynatraceClient` default path imports nothing from `clients/legacy/`
- All 29 existing DT client tests pass OR are explicitly migrated to `tests/legacy/test_dynatrace_client_v1.py`
- New tests cover Settings 2.0 CRUD, Document pagination (`pageKey`), and Automation workflow CRUD
- OAuth2 auth path unit-tested with mocked token exchange
- `python migrate.py migrate --dry-run` completes without touching Config v1 endpoints (verify via mock HTTP log)

## Decisions Made This Phase
(append as you go)
