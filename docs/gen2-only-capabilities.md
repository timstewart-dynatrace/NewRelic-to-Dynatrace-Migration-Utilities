# Gen2-only Capabilities — What `--legacy` Does That Gen3 Default Can't

> **Audited:** 2026-04-16 (post-Phase-25 — 6 of 8 items now have Gen3 workarounds)
> **Audience:** Operators choosing between Gen3 default and `--legacy`.
> **Companion:** `docs/migration-coverage.md`, `docs/out-of-scope.md`.

Most capabilities have a Gen3 equivalent that is at parity or better
(Workflows replace Alerting Profiles + Problem Notifications, Segments
replace Management Zones, OpenPipeline replaces Auto-Tag Rules, Davis
Anomaly Detectors replace Metric Events, Document API replaces Config
v1 Dashboards). This document catalogs the *exceptions* — things you
can only produce by running with `--legacy` or `MIGRATION_LEGACY_MODE=true`.

## Hard Gen2-only capabilities

### 1. Per-severity delay ladders on alerting profiles

**Gen2:** `builtin:alerting.profile` encodes five severity levels
(AVAILABILITY / ERROR / PERFORMANCE / RESOURCE_CONTENTION / CUSTOM_ALERT)
each with an independent `delayInMinutes`. Operators tune how long
each class waits before firing.

**Gen3 gap:** Workflows trigger on Davis events once, with one delay
per Workflow. A customer with five distinct delay rules must either
create five separate Workflows (the Gen3 transformer emits one bundled
Workflow) or accept collapsing the ladder.

**Why not migrated:** An automatic 5-way split would inflate Workflow
counts and obscure operator intent. Operators who rely on the ladder
should run with `--legacy` until they restructure their notification
logic.

### 2. Typed problem-notification integrations

**Gen2:** Dedicated schemas per channel:
`builtin:problem.notifications.{email,slack,pager-duty,webhook,jira,service-now,ops-genie,victor-ops}`.
Each has a fully-typed config (e.g. ServiceNow table name, Jira project
key, OpsGenie responder list) with credential fields validated by DT.

**Gen3 partial:** Workflows have first-class tasks for **email / slack /
pagerduty / webhook**. Other channels (Jira, ServiceNow, OpsGenie,
xMatters, VictorOps, Teams) are emitted as generic `http-function`
tasks — the operator wires auth + payload template manually.

**Why not fully migrated:** DT's Workflow connector ecosystem is
evolving; as new typed connectors ship, the Gen3 `NotificationTransformer`
(folded into `alert_transformer.py`) will be expanded to call them
instead of the webhook fallback.

### 3. Template-value auto-tagging with `{TAG:name}` references

**Gen2:** `builtin:tags.auto-tagging` lets a rule's `valueFormat` use
`{TAG:env}` template syntax — the value is pulled from a *different*
tag on the entity at detection time. Enables "copy tag env into a
standardized `environment` auto-tag" patterns.

**Gen3 gap:** OpenPipeline `addFields` processors accept a literal
value, not a template reference. The Gen3 `TagTransformer` emits the
literal value captured at export time; dynamic templating is dropped.

**Workaround:** Use OpenPipeline `computeFields` with a DQL expression
(e.g. `env = tags.env`). The Gen3 transformer does not yet emit this
shape; Phase 24's `MetricNormalizationTransformer` candidate may
cover it.

### 4. Entity-ID-targeted Management Zone rules

**Gen2:** MZ rules can target a specific entity by id/name:
`type("HOST"),entityName.equals("exact-host-name")`. Useful for
"critical-host-only" scopes.

**Gen3 partial:** `builtin:segment` filters *records* not *entities*.
The Gen3 `WorkloadTransformer` emits a Segment with a
`Group/Statement` tree using `entity.name contains`, which is weaker
than an exact-id match. Customers with thousands of per-host MZ
entries lose the exact-match semantics.

**Why:** Segments are designed for record-level filtering in Grail,
not for permissions scoping. Per-entity access should now be expressed
via IAM policies keyed by entity tags. Operators with large
per-entity MZ inventories should consider tag-refactoring before
migrating.

### 5. Config v1 Dashboard `preset`, `tags` on dashboardMetadata

**Gen2:** Dashboards carry `dashboardMetadata.preset` (boolean
flagging DT-shipped presets) and `dashboardMetadata.tags` (free-form
strings for filtering).

**Gen3 partial:** Gen3 Grail dashboards (Document API) use `version:
13`, `tiles{}`, `layouts{}`. Document-level tags are applied via
the Document API's attribute system, not inline metadata. The Gen3
`DashboardTransformer` drops the preset flag and converts tags to a
runbook note.

### 6. Classic synthetic `keyPerformanceMetrics` + per-step thresholds

**Gen2:** `/api/v1/synthetic/monitors` accepts
`keyPerformanceMetrics.loadActionKpm` / `.xhrActionKpm`
(`VISUALLY_COMPLETE` vs `SPEED_INDEX` vs `USER_ACTION_DURATION`) and
`anomalyDetection.loadingTimeThresholds[].thresholds[]` with per-step
granularity.

**Gen3 status:** Python's Phase 11 `SyntheticTransformer` wraps the
same inner body in a `builtin:synthetic_test` Settings 2.0 envelope,
so KPMs and thresholds carry through. **This one is actually at
parity** — listed here for completeness because it was flagged during
audit.

### 7. `PRIVATE_SYNTHETIC_LOCATION` inventory lookup

**Gen2:** `get_synthetic_locations()` on `LegacyDynatraceV1Client`
returns both PUBLIC and PRIVATE locations in one call
(`/api/v1/synthetic/locations`).

**Gen3 gap:** The Gen3 `DynatraceClient` has no `get_synthetic_locations`
method. Private-location lookups require either the legacy client or
a custom Settings 2.0 query against `builtin:synthetic.private-location`.

**Workaround:** Operators who need a private-location inventory today
run the `registry/environment.py` `DTEnvironmentRegistry` (which
queries `/api/v2/synthetic/locations` directly, bypassing the Gen3
client) or use `--legacy` to reach `get_synthetic_locations`.

### 8. Config v1 dashboard fallback on Documents API 404

**Gen2:** `LegacyDynatraceV1Client.create_dashboard()` tries Documents
v1 first, falls back to `/api/config/v1/dashboards` on failure. This
tolerates tenants where Documents API is disabled.

**Gen3 gap:** Gen3 `DynatraceClient.create_dashboard()` goes straight
to Document API with no fallback. If Documents is unreachable, the
migration fails for that entity. Operators on tenants without
Documents must run `--legacy`.

## Summary — when to use `--legacy`

Use `--legacy` if **any** of these apply:

- Your Dynatrace tenant is **classic** (no Gen3 Platform APIs:
  Workflows / Document API / OpenPipeline / Segments)
- You rely on **per-severity delay ladders** in alerting profiles
- You rely on **template-value auto-tagging** (`{TAG:name}`)
- You need **typed problem-notification integrations** for Jira,
  ServiceNow, OpsGenie, xMatters, VictorOps, or Teams (Gen3 emits
  generic webhook fallback that requires hand-wiring)
- Your MZ inventory includes **per-entity-ID / per-entity-name
  targeted rules** and you cannot refactor to tag-based scoping

Use Gen3 default for **everything else** — it is the supported path
going forward and has features (Davis causal engine, Grail DQL,
OpenPipeline flexibility) Gen2 lacks.

## Gen3-only capabilities (reverse direction)

Some things Gen3 does that Gen2 cannot:

- **Davis causal engine** — automatic correlation replaces manual
  Decisions rules
- **Grail DQL** — `fetch` + `timeseries` queries across arbitrary
  time windows and all bucket types; Gen2 Metric Events use a
  restricted query language
- **Segments + IAM policies** — Grail-scoped access control that
  didn't exist pre-Gen3
- **OpenPipeline processor chains** — ingest-time data-plane
  transformations (mask / drop / parse / addFields / computeFields /
  removeFields)
- **Automation Workflows** with rich task library (DQL queries,
  JavaScript, HTTP functions, typed connectors)
- **Document API** dashboards with live Grail tiles, saved views,
  cascading variables with `dependsOn`
- **builtin:davis.anomaly-detectors** with auto-adaptive baseline /
  outlier detection strategies beyond static-threshold

Operators on Gen3 tenants are strongly encouraged to migrate via the
default path and fix the edge cases enumerated above manually, rather
than lean on `--legacy` indefinitely.
