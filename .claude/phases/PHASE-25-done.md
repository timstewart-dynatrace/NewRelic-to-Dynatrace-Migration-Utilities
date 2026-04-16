# Phase 25 — Gen3 Workarounds for Gen2-Only Capabilities
Status: PENDING (release-hold also applies)

## Goal
Close 6 of the 8 Gen2-only capabilities listed in
`docs/gen2-only-capabilities.md` by emitting more sophisticated Gen3
shapes. Items 2 (typed problem-notification connectors) and 6
(synthetic KPMs — already at parity) are excluded because they
require upstream DT Platform work or no action.

After this phase, operators on Gen3 tenants should only need `--legacy`
for the two residual items.

## In-scope items

### 1. Per-severity delay ladder → multiple Workflows per policy

**Current Gen2:** `builtin:alerting.profile` carries 5 severity rules
(AVAILABILITY / ERROR / PERFORMANCE / RESOURCE_CONTENTION /
CUSTOM_ALERT) with distinct `delayInMinutes` each.

**Phase 25 Gen3 solution:** `AlertTransformer` emits **one Workflow
per severity level** (up to 5) when the source policy specifies
non-zero delays. Each Workflow's trigger filters Davis events by
`event.severity` matching one severity, and its tasks replay the
notification destinations with the correct delay on a pre-step sleep
node. Shared artifacts (anomaly detectors, segments) stay as a single
envelope each.

**Implementation notes:**
- New emitter helper `_workflows_for_severity_ladder(policy) -> List[workflow]`
  in `transformers/alert_transformer.py`.
- Workflows keyed by severity in `migratedFrom.severity` metadata so
  the audit tool can group them.
- Default to single-workflow emission if all severities share the same
  delay (avoids fanout for the common case).

### 3. Template-value auto-tagging → OpenPipeline computeFields

**Current Gen2:** `valueFormat: "{TAG:env}"` on an Auto-Tag Rule pulls
the `env` tag value off the entity at detection time.

**Phase 25 Gen3 solution:** `TagTransformer` emits an OpenPipeline
`computeFields` processor (not `addFields`) when the source
`valueFormat` contains a `{TAG:name}` reference. The computed value
is a DQL expression reading `tags.<name>` from the record, which
produces the same dynamic-substitution semantics at ingest time.

**Implementation notes:**
- Parser for `{TAG:name}` placeholders in `tag_transformer.py`.
- Emit `computeFields` with `expression = "tags.<name>"`; fall back
  to `addFields` with literal when no placeholders detected.
- Warning emitted if the referenced tag is not in the NR export
  (operator must ensure the source tag is also migrated).

### 4. Entity-ID Segment filters

**Current Gen2:** MZ rule
`type("HOST"),entityName.equals("web-prod-01")` targets a specific
entity by exact name.

**Phase 25 Gen3 solution:** `WorkloadTransformer` emits a Segment
`Statement` with `key: dt.entity.id` and operator `==` when the NR
collection references a specific entity GUID. Falls back to the
`entity.name contains` filter only when the GUID is unavailable.
Also synthesizes `dt.entity.name` equality statements via `==` (not
`contains`) when the NR `entityName.equals` pattern is detected.

**Implementation notes:**
- Requires NR export to carry entity GUIDs (usually present in NR
  Workload collections).
- Emit an OR-group so a single Segment covers (id-match OR name-match)
  for robustness.

### 5. Config v1 dashboard `.preset` + `.tags` → Document attributes

**Current Gen2:** `dashboardMetadata.preset` (bool) and `.tags`
(string list) live on the v1 dashboard payload.

**Phase 25 Gen3 solution:** `DashboardTransformer` emits a parallel
Document-API **attributes** POST after the dashboard creation:
- `tags` → `{"attributes": {"tags": [...]}}` via Document API tag endpoints.
- `preset` → dropped with a warning (no Gen3 equivalent; DT doesn't
  expose preset distinctions to operators).

**Implementation notes:**
- Extend `DocumentClient` with `put_tags(doc_id, tags)` method.
- Orchestrator calls it after `create_dashboard` succeeds.
- `preset=true` produces a runbook note, not an error.

### 7. Private synthetic location inventory on Gen3 client

**Current Gen2:** `LegacyDynatraceV1Client.get_synthetic_locations()`
returns PUBLIC + PRIVATE in one call.

**Phase 25 Gen3 solution:** Add
`DynatraceClient.list_synthetic_locations(scope: Optional[Literal["PUBLIC","PRIVATE","ALL"]])`
that queries `/api/v2/synthetic/locations` directly (not a Settings
2.0 schema). Handles pagination; returns full location objects.

**Implementation notes:**
- The `/api/v2/synthetic/locations` endpoint is a classic API even on
  Gen3 tenants, but it lives outside the Settings 2.0 / Document /
  Automation trio. Add a small client method in `DynatraceClient`
  itself (not a new sub-client) to avoid expanding the composition.

### 8. Dashboard Document-then-Config-v1 fallback

**Current Gen2:** `LegacyDynatraceV1Client.create_dashboard` tries
Documents first, falls back to Config v1 on failure.

**Phase 25 Gen3 solution:** Add an opt-in fallback flag on the Gen3
`DynatraceClient.create_dashboard`:

```python
dt_client.create_dashboard(content, fallback_to_config_v1=True)
```

When True, failed Document creation dispatches to the legacy Config v1
endpoint. Off by default; only the orchestrator's `--dashboard-fallback`
CLI flag would enable it (to be added).

**Implementation notes:**
- Requires composing `LegacyDynatraceV1Client` lazily inside the
  `create_dashboard` method when the flag is set.
- Tenants running Phase 25 code should almost never need the fallback
  on Gen3 — this is a belt-and-suspenders feature for mixed-mode tenants.

## Out-of-scope items (explicitly deferred)

### 2. Typed problem-notification integrations (Jira, ServiceNow, OpsGenie, xMatters, VictorOps, Teams)

**Why excluded:** DT's Automation API ships first-class tasks for
email / slack / pagerduty / webhook only. Jira/ServiceNow/etc. are
emitted as `http-function` generic tasks. The underlying blocker is
the DT Workflow connector catalog — when DT ships typed connectors
for those products, add them as tasks in `NotificationTransformer`.
No transformer-side work can close this today.

### 6. Synthetic KPMs

**Why excluded:** Already at parity. Python's `SyntheticTransformer`
wraps the Config-v1-shaped body (including `keyPerformanceMetrics`)
in a `builtin:synthetic_test` Settings 2.0 envelope. Listed in the
Gen2-only doc only because the original audit flagged it as a
concern; direct inspection confirmed parity.

## Acceptance Criteria

- All 6 in-scope items land as code changes with ≥ 4 tests each.
- `docs/gen2-only-capabilities.md` updated — items 1, 3, 4, 5, 7, 8
  cross-referenced to their Phase 25 Gen3 workarounds (status flips
  from "use --legacy" to "Gen3 default w/ workaround").
- Full pytest suite stays green.
- Coverage matrix gains one row: "Gen2-only feature coverage" → ~75%
  (6 of 8 items closed; 2 remain permanently deferred upstream).

## Execution order recommendation

1. Item 5 (preset/tags → Document attributes) — smallest
2. Item 7 (private-location listing) — standalone client method
3. Item 8 (dashboard fallback) — defensive addition
4. Item 3 (template auto-tagging) — OpenPipeline expertise needed
5. Item 4 (entity-ID Segment filter) — Segment schema deep-dive
6. Item 1 (severity ladder fanout) — largest, touches AlertTransformer + NotificationTransformer
