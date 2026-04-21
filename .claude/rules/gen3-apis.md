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

- HIGH/MEDIUM conversion → converter's DQL
- Empty/LOW/failure → `// UNCONVERTED NRQL: <orig>\ntimeseries count()` (preserves the NRQL as a comment; trailing placeholder keeps the payload server-validatable so the detector still creates)

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
