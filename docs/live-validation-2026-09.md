# Live validation — 2026-09-17

Read-only evidence gathered against a Gen3 SaaS tenant (`*.apps.dynatrace.com`) with
`dtctl` 0.38.0. No objects were created. Tenant, host, and service names are omitted.
This document drives the fixes on branch `fix/live-validated-defects`.

## Method

| Check | dtctl command | What it proves |
|---|---|---|
| Settings schema | `get settings-schemas builtin:davis.anomaly-detectors` | Allowed value fields |
| Real object shapes | `get anomaly-detectors`, `get workflows <id>`, `get slos`, `get segments <id>`, `get dashboards <id>` | Formats tenants actually store |
| DQL syntax | `verify query` | **Syntax only** — unknown metrics/fields still report `valid` |
| Detector input | `exec analyzer <analyzer> --input …` | Runs the analyzer without persisting; catches non-timeseries and invalid DQL. `verify analyzer` accepted invalid queries, so it is **not** sufficient |
| Field existence | bounded `query` (`from:-10m`..`-2h`, `limit`) | Dimension actually carries data |

## Findings

### D1 — detector query must be a timeseries — CONFIRMED FAILURE
`exec analyzer StaticThresholdAnomalyDetectionAnalyzer` with
`fetch spans | … | summarize count()` → `resultStatus: FAILED`:
"No valid time series records found. Expected a single field of type timeframe.
Consider using the 'timeseries' or 'makeTimeseries' DQL command."

### D2 — classic `builtin:*` metric keys in DQL — CONFIRMED FAILURE
`timeseries avg(builtin:host.cpu.usage)` → DQL error "There isn't a parameter builtin."
(both `verify query` and `exec analyzer`). Control `timeseries avg(dt.host.cpu.usage)` succeeds.

### D3 — `detectorId` in the Settings envelope — CONFIRMED NOT A SCHEMA FIELD
Schema `builtin:davis.anomaly-detectors` is **v1.0.16** (repo documented v1.0.14). Value
properties: `analyzer, description, enabled, eventTemplate, executionSettings, source, title`.
`ExecutionSettings` now has `actor, delay, queryOffset`. `detectorId` is not a value or
envelope field. Live detectors use input key `query` (55) and `query.expression` (10).

### D4 — workflow trigger shape — CONFIRMED WRONG
Emitters produce `trigger.event.config.davis_event{detectorIds, eventType, anyEventMatches}`.
Every event-triggered workflow on the tenant uses:

```
trigger.eventTrigger {
  isActive, filterQuery (server-derived), uniqueExpression,
  triggerConfiguration: {
    type: "davis-event" | "davis-problem" | "event",
    value: {…}
  }
}
```

- `davis-event` value: `customFilter, entityTags, entityTagsMatch, maintenanceWindowTriggerBehavior, onProblemClose, triggerOn`
- `davis-problem` value: `analysisReady, categories, customFilter, entityTags, entityTagsMatch, onProblemClose, problemOpenDuration, severityThreshold, triggerOn, triggerOnUpdateFields`

Detector → workflow linkage is done with `customFilter` on event fields that the detector sets
via `eventTemplate.properties` — there is no `detectorIds` field. `tasks` is a dict (§4 holds).

### D8 — new Smartscape / SLO output — CONFIRMED WORKING
| Query | Result |
|---|---|
| `timeseries avg(dt.host.cpu.usage), by:{host.name}` | data |
| `timeseries sum(dt.service.request.count), by:{dt.service.name}` | data |
| `timeseries avg(dt.kubernetes.container.cpu_usage), by:{k8s.workload.name}` | data |
| Platform SLO availability indicator (`by:{dt.smartscape.service}` + `getNodeName`) | `sli` series |
| Platform SLO latency indicator | `sli` series |
| `smartscapeNodes K8S_DEPLOYMENT… \| parse k8s.object` readyReplicas / desiredReplicas | data |
| `smartscapeNodes K8S_POD \| parse k8s.object` phase | data |
| `smartscapeNodes HOST \| fields name, id` | data |

Platform SLO objects on the tenant have exactly `id, name, description, version, criteria[{timeframeFrom, timeframeTo, target, warning}], customSli{indicator, filterSegments}, tags, externalId` — matches `_slo_utils.build_platform_slo`. `version` is present for optimistic locking.

### D10 (new) — `service.name` is empty on OneAgent spans — CONFIRMED
10-minute window: `countIf(isNotNull(service.name))` = 0 of 38,304 spans;
`dt.service.name` and `dt.smartscape.service` populated on all. Logs: `service.name` on some
records, `dt.service.name` on none. Span-context mapping of `appName` / `entityName` to
`service.name` returns no data on OneAgent-instrumented services.

### Segments — Smartscape form now observable
Live segment includes use `dataObject: "_all_entities"` with filter statements
`type = SERVICE` and `id in (…)`, plus `_all_data_object` / `logs`. A few legacy segments still
use `dataObject: "dt.entity.service"`. This gives a verified Gen3 form for
`workload_transformer.py` (currently `dt.entity.type` / `dt.entity.id`).

### Dashboards
Live Document API dashboards use content `version` 20–21; `dashboard_transformer.py` emits 13.

### Additional defects found while fixing (all fixed on this branch)
| # | Finding | Evidence |
|---|---|---|
| D11 | Fallback placeholder `timeseries count()` is invalid DQL | analyzer: "mandatory parameter is missing: metricKey" |
| D12 | `otel.status_code` unset on OneAgent spans; failures are `request.is_failed` | 0 of 39,051 spans had `otel.status_code`; 789 had `request.is_failed == true` |
| D13 | Mixed AND/OR conditions emitted without parentheses | code review; `(a OR b) AND c` became `a or b and c` |
| D14 | Segment groups used `type = X OR id = …`, matching every node of the type | code review |
| D15 | AIOps enrichment `dql-query` tasks contained raw NRQL | code review |

### Settings validation (`dtctl create settings --validate-only`, no objects created)
Every detector emitter was submitted to the tenant's Settings validator. Rejections found and fixed:

| # | Rejection | Fix |
|---|---|---|
| D16 | `executionSettings/actor: Must not be null`; random UUID → "Provided actor is not a valid service user" | Transformers emit `executionSettings: {}`; import injects `DYNATRACE_DETECTOR_ACTOR` (service-user UUID); Monaco/Terraform parameterise it |
| D17 | "Dealerting samples must be less than or equal to sliding window" | `dealertingSamples = min(5, slidingWindow)` |
| D18 | `event.type` `RESOURCE_CONTENTION` not in the allowed set | `RESOURCE_CONTENTION_EVENT` / `AVAILABILITY_EVENT` |
| D19 | "Parameter 'minLocationsFailing' does not exist" | removed; warning |
| D20 | "Parameter 'learningPeriodDays' does not exist" | removed; warning |
| D21 | "Parameter 'dimensions' does not exist" | facet moved into the query's `by:` |

After the fixes all 14 emitter variants validate (`scripts/validate_detectors_live.py`).

### Workflow linkage evidence
Problem records carry only standard fields (`event.name`, `event.category`, `tags`,
`labels.alerting_profile`, …) — not detector `eventTemplate.properties`. Over 7 days a
problem's `event.name` equalled its contributing `CUSTOM_ALERT` event's name 466/466.
`matchesValue(event.name, "<prefix>*")` validates as a workflow matcher; `startsWith()` is
not enabled, and `\*` is rejected. No events on the tenant use `dt.alert_group`.

## Phase 2 — write tests (2026-09-17)
Created on the tenant with `dtctl create`, read back, and deleted immediately. All names used
the `[nr-migration-test]` prefix; a follow-up `get` found none remaining.

| Object | Result |
|---|---|
| Workflow (`davis-problem` trigger, §4a shape, inactive) | **Accepted.** Server-derived `filterQuery` contains `matchesValue(event.name, "[Migrated] … \| *")`; categories map to `MONITORING_UNAVAILABLE, AVAILABILITY, ERROR, SLOWDOWN, RESOURCE_CONTENTION, CUSTOM_ALERT` |
| Platform SLO (`_slo_utils` body, Smartscape indicator) | **Accepted.** Deleted via `DELETE …/slos/<id>?optimistic-locking-version=<version>` → 204 |
| Document API dashboard (content version 13, converted DQL tile) | **Accepted**; stored as version 13. Deleted via `DELETE …/documents/<id>?optimistic-locking-version=1` → 204 (moved to trash) |
| Davis anomaly detectors (all emitters) | Not created — fully validated with `--validate-only` instead (see above) |

### D22 — optimistic-locking query parameter name — FIXED
Both Platform SLO and Document API deletes use `optimistic-locking-version` (kebab-case). The
repo sent `optimisticLockingVersion` from `SloClient.delete_slo` and
`DocumentClient.delete_document`, and `SLOAuditor.update_slo` sent no version at all — rollback
deletes and SLO auto-fix updates would have failed.
