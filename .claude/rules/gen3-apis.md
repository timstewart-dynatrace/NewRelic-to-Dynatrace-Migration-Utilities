# Gen3 Dynatrace API rules

Hard-won correctness rules for producing requests that Gen3 SaaS tenants accept. Every item here came from a real `400` / `404` / `415` against a live tenant (see PRs #16–22, commits merged 2026-04-20). If you're writing new code that talks to `.apps.*` tenants, check against this list before emitting a request.

---

## 1. Auth scheme is token-prefix driven [MUST]

Use `clients._http.token_auth_header()` — do not hand-roll the header.

| Token prefix | Scheme | Notes |
|---|---|---|
| `dt0c01.*` | `Api-Token` | Classic SaaS + Managed |
| `dt0s01.*` | `Bearer`    | Platform OAuth2-issued |
| `dt0s16.*` | `Bearer`    | Platform static token |

Sending `Api-Token` with a `dt0s16.*` token against an `.apps.*` tenant returns `401 "Unsupported authorization scheme 'Api-Token'"`.

## 2. Settings 2.0 base path depends on tenant generation [MUST]

Use `clients._http.settings_v2_base(environment_url)` — do not hard-code `/api/v2`.

| Host contains | Base path |
|---|---|
| `.apps.` (Gen3 SaaS) | `/platform/classic/environment-api/v2` |
| `.live.` / Managed   | `/api/v2` |

`GET /api/v2/settings/schemas` returns `404` on Gen3 SaaS tenants.

## 3. Document API POST is multipart/form-data [MUST]

`/platform/document/v1/documents` rejects JSON bodies with `415 Unsupported Media Type`. Use `HttpTransport.post_multipart(...)` with four parts:

```
name      = <dashboard name>
type      = dashboard
isPrivate = false
content   = (filename="content.json", mime="application/json", body=<dashboard JSON>)
```

Subtle gotcha the transport already handles: `HttpTransport.request(..., files=...)` passes `Content-Type=None` in per-call headers so `requests`' auto-computed multipart boundary wins over the session-default `application/json`. Don't reintroduce the session default without re-verifying uploads.

## 4. Automation API `tasks` is a dict, not a list [MUST]

`POST /platform/automation/v1/workflows` with a list-shaped `tasks` returns `{"tasks": ["Input should be a valid dictionary"]}`. Use `transformers._workflow_utils.tasks_list_to_dict()` — it preserves order via insertion, slugs names, and handles collisions with numeric suffixes.

All five workflow emitters (`alert_transformer`, `aiops_transformer`, `infrastructure_transformer`, `non_nrql_alert_transformer`, `key_transaction_transformer`) already call it. Any new workflow emitter must too.

## 5. `analyzer.input[query].value` is DQL, server-validated [MUST]

Passing raw NRQL produces `400 "Invalid DQL query. 'FROM' isn't allowed here."` Use `transformers._detector_utils.nrql_to_analyzer_query(nrql, warnings=...)`:

- HIGH/MEDIUM conversion → converter's DQL, normalised by `ensure_timeseries()`: the analyzer only accepts timeseries results, so `fetch … | summarize …` becomes `makeTimeseries` (arithmetic over aggregations such as percentages is split into named series + `fieldsAdd`)
- Empty/LOW/failure, or DQL that cannot be made a timeseries → `// UNCONVERTED NRQL: <orig>\n` + `FALLBACK_QUERY`, an inert timeseries that matches no data so the detector creates but never fires

Verified live (`dtctl exec analyzer`, docs/live-validation-2026-09.md): `summarize` output fails with "No valid time series records found", and the old placeholder `timeseries count()` is invalid (count() needs a metric key). Metric-based detectors must use Grail keys (`transformers._detector_utils.GRAIL_METRIC_KEYS`) — `timeseries avg(builtin:…)` is a DQL syntax error.

Span fields verified on OneAgent data: service identity is `dt.service.name` (`service.name` is empty on spans; logs keep `service.name`), and failures are `request.is_failed` (`otel.status_code` is unset).

## 6. `builtin:davis.anomaly-detectors` canonical shape (v1.0.14) [MUST]

All five emitters (`alert_transformer`, `aiops_transformer`, `baseline_alert_transformer`, `non_nrql_alert_transformer`, `infrastructure_transformer`) must emit:

```
value {
  enabled: boolean
  title: text (required)
  description: text
  source: text (required)                      # NOT an object
  executionSettings: {actor, queryOffset}
  analyzer: {
    name: text (Davis analyzer id)
    input: [{key, value}, ...]                 # all strings, value minLength=1
  }
  eventTemplate: {
    properties: [{key, value}, ...]            # ONLY this field is allowed
  }
}
```

Forbidden (emission triggers validator errors): `name`, `strategy`, `eventTemplate.title`, `eventTemplate.description`, `eventTemplate.eventType`, `eventTemplate.davisMerge`.

Canonical analyzer names:

- `dt.statistics.ui.anomaly_detection.StaticThresholdAnomalyDetectionAnalyzer`
- `dt.statistics.ui.anomaly_detection.AutoAdaptiveAnomalyDetectionAnalyzer`
- `dt.statistics.ui.anomaly_detection.SeasonalBaselineAnomalyDetectionAnalyzer`

**Audit command** before any schema-shape change:

```bash
grep -rn '"schemaId": "builtin:davis.anomaly-detectors"' transformers/
```

All five sites must move in lockstep. PR #20 missed `alert_transformer.py` this way; PR #21 cleaned it up.

`dt-alerting/references/anomaly-detectors.md` also documents `RecordAnomalyDetectionAnalyzer` (rows-returned = violations); no emitter uses it yet.

## 7. Emitted DQL is Smartscape-first, not classic entity [MUST]

Source: Dynatrace-maintained `dt-dql-essentials` and `dt-migration` skills (`dynatrace-for-ai` v8.0.0). `dt.entity.*` is deprecated for new queries. Anything the compiler, converter, fixer, or a transformer writes into a DQL string must follow:

| Classic (do not emit) | Smartscape (emit) | Notes |
|---|---|---|
| `dt.entity.<type>` in `by:` / `filter` / `fieldsAdd` | `dt.smartscape.<type>` | e.g. `dt.entity.host` → `dt.smartscape.host`, `dt.entity.service` → `dt.smartscape.service`, `dt.entity.process_group_instance` → `dt.smartscape.process` |
| `fetch dt.entity.<type>` (entity list) | `smartscapeNodes <NODE_TYPE>` | e.g. `smartscapeNodes HOST`; field `entity.name` → `name` |
| `fetch dt.entity.cloud_application_instance` | `smartscapeNodes K8S_POD` | |
| `fetch dt.entity.cloud_application` | K8s workload node types | 1:N — see `dt-migration/references/entity-cloud-application.md` |
| `entityName(x)` | `getNodeName(x)` (signal/edge) or `name` (on nodes) | `getNodeName()` takes only an ID — no `type:` arg |
| `entityAttr(x, "f")` | `getNodeField(x, "f")` or direct node field | |
| `classicEntitySelector(...)` | raw-dimension filter first; `traverse` / `in [smartscapeNodes ...]` fallback | |
| `affected_entity_ids` + `affected_entity_types` | `smartscape.affected_entities` | record array of `{id, type, name}` |

No classic mapping exists for host groups, process groups, or container groups — they are fields on `HOST` / `PROCESS` / `CONTAINER`. Classic entity IDs do not carry over. Full tables: `/Users/Shared/GitHub/PROJECTS/CLAUDE/dynatrace-for-ai/skills/dt-migration/references/type-mappings.md`, `dql-function-migration.md`, `special-cases.md`.

**Status:** implemented in the compiler, converter, and fixer (`validators/smartscape_map.py`, `DQLValidator._fix_classic_entity_references`), mirrored in nrql-engine. NRQL `entityName` / `entity.name` emit a raw dimension by context: `service.name` (spans/logs), `host.name` (host samples), `dt.service.name` (Metric), `k8s.workload.name` (K8s, with warning).

**Segment filters:** live Gen3 segments include `dataObject: "_all_entities"` with `type = <NODE_TYPE>` AND (`id = …` | `name = …`) statements; `workload_transformer.py` emits that form. NR GUIDs are not Dynatrace IDs, so they fall back to `name`. The emitted wrapper is still the Settings-style `{schemaId, value.includes.items}` shape, whereas the Platform filter-segments API takes `{name, isPublic, includes: [{dataObject, filter: "<stringified tree>"}]}` — another reason segment import stays SKIPPED.

Events API v2 `entitySelector` strings (`entityId(...)` / `entityName(...)`) in change-event payloads are also not DQL and remain supported on Gen3 — not covered by this rule.

Any change here is a compiler-output change: mirror it in `/Users/Shared/GitHub/PROJECTS/NewRelic/nrql-engine` and extend `tests/unit/test_phase19b_engine_parity.py`.

Audit command:

```bash
grep -rnE 'dt\.entity\.|entityName\(|entityAttr\(|classicEntitySelector' compiler/ transformers/ validators/ --include='*.py' | grep -v '/legacy/'
```

## 8. Alerting conventions from Dynatrace guidance [SHOULD — not yet implemented]

Source: `dt-alerting` skill. Accepted by the API today in their current form, so these are improvements, not correctness fixes. Change them together and verify against a live Gen3 tenant first.

- **Workflow triggers on problems, not Davis events.** The workflow emitters use `trigger.event.config.davis_event`; Dynatrace recommends a problem trigger (one notification per grouped incident). See `/Users/Shared/GitHub/PROJECTS/CLAUDE/dynatrace-for-ai/skills/dt-alerting/references/workflow-notifications.md`.
- **Detector input key:** `query.expression` is preferred over `query` for new configs (both accepted).
- **Routing/grouping:** set `dt.alert_group` (and `dt.source_entity` where known) in `eventTemplate.properties`.
- **Dashboard content `version`:** `dashboard_transformer.py` emits `13`; current Dynatrace examples use `21`.

## 9. SLOs are Platform SLOs, not `builtin:monitoring.slo` [MUST]

`SLOTransformer`, `KeyTransactionTransformer`, and the converter's auto-create path all emit the Platform SLO API body via `transformers/_slo_utils.py` and push it through `clients/slo_client.py`:

```
POST /platform/slo/v1/slos            # platform host (.apps.), Bearer, slo:slos:write
{
  name, description, tags[], externalId?,
  criteria: [{target, warning, timeframeFrom: "now-7d", timeframeTo: "now"}],   # warning > target
  customSli: {indicator: "<DQL producing an `sli` percent series>"}
}
```

- The indicator is DQL and must follow §7 (`by: { dt.smartscape.service }`, `getNodeName()`).
- DELETE (and PUT) need the current `optimisticLockingVersion`; `SloClient.delete_slo` GETs it first. The query-param name follows this repo's Document API convention and is not yet verified on a live tenant.
- IaC: Monaco `type: slo-v2` (body is the template JSON); Terraform `dynatrace_platform_slo`.
- Classic metric-selector SLOs (`metricExpression`, `entitySelector("type(service)")`) are not emitted anywhere in the Gen3 path.

Test pattern: `tests/unit/test_dynatrace_client.py::TestPlatformSloWire`.

---

## Known-SKIPPED entity types [MUST NOT re-enable without building the right client]

`migrate.py::_import_phase` deliberately SKIPs three entity types. Each represents a real Gen3 architectural mismatch, not a bug. Envelopes are still built + written to `transformed_data.json`; only the POST step is skipped.

| Entity | Reason it's SKIPPED | Would require |
|---|---|---|
| Synthetic tests | Gen3 splits into 20+ `builtin:synthetic.{http,browser,multiprotocol}.*` per-facet settings schemas; no single `builtin:synthetic_test` exists | Multi-envelope emitter + orchestration |
| Grail segments | `builtin:segment` is not a Settings 2.0 schema; segments live under a Gen3 Platform API (`/platform/segment/v1/...`) | Platform segment client |
| IAM policies | Gen3 IAM uses Account Management API (`api.dynatrace.com/iam/v1/repo/...`), not Settings 2.0 | Account Management client |

If a future task asks to "fix" the SKIPPED behavior, the first answer is: what Gen3 client surface exists for this, and is wiring that client in-scope? If not, keep them SKIPPED.

---

## Test patterns for Gen3 API code [MUST]

**Wire-level is the default.** Transport-mock / client-mock tests let serialization bugs through (PR #20 cases in point: 415 on dashboards, `strategy` leaked into anomaly detectors). Capture at `Session.send` and inspect the `PreparedRequest`:

```python
def test_outgoing_shape(self):
    transport = HttpTransport(api_token="dt0s16.test")
    captured = {}
    def fake_send(req, **kw):
        captured["headers"] = dict(req.headers)
        captured["body"] = req.body
        r = requests.Response(); r.status_code = 200; r._content = b"{}"
        return r
    with patch.object(transport.session, "send", side_effect=fake_send):
        client.do_thing(transport)
    # Assert on captured["headers"] / captured["body"]
```

Examples in-repo: `tests/unit/test_dynatrace_client.py::TestMultipartContentTypeWire`, `::TestAnomalyDetectorWirePayload`, `::TestAnalyzerInputQueryIsDql`.

---

## Schema verification workflow

When a payload shape is in doubt, **fetch the live schema** — don't infer from error messages.

```bash
TENANT=https://xzj8412h.sprint.apps.dynatracelabs.com
T=$DYNATRACE_API_TOKEN     # dt0s16.* Platform Token
curl -sH "Authorization: Bearer $T" \
  "$TENANT/platform/classic/environment-api/v2/settings/schemas/<schemaId>" | jq
```

To find the current schemaId when the old one 404s:

```bash
curl -sH "Authorization: Bearer $T" \
  "$TENANT/platform/classic/environment-api/v2/settings/schemas?pageSize=500" \
  | jq '.items[] | select(.schemaId | test("<partial>"; "i"))'
```
