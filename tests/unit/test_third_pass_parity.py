"""Third-pass nrql-engine parity tests.

After Phase 24 landed, a third sweep of the TS sibling found 3 real
gaps + 1 naming alias:

- OTelCollectorTransformer (broader than OTelMetricsTransformer —
  all 3 signals + processor translation)
- LegacyErrorInboxTransformer (Gen2-only Errors Inbox -> Problems API)
- LegacyRequestNamingTransformer (Gen2-only setTransactionName ->
  builtin:request-naming.request-naming-rules)
- CustomEventTransformer alias for CustomEventIngestTransformer

These tests pin the new modules and ensure the parity alias works.
"""

from transformers import (
    CustomEventIngestTransformer,
    CustomEventTransformer,
    OTelCollectorTransformer,
)
from transformers.legacy import (
    LegacyErrorInboxTransformer,
    LegacyRequestNamingTransformer,
)

# ---------------------------------------------------------------------------
# OTelCollectorTransformer
# ---------------------------------------------------------------------------


class TestOTelCollector:
    def test_all_three_signals_emitted(self):
        r = OTelCollectorTransformer().transform({
            "name": "prod-collector",
            "signals": ["traces", "metrics", "logs"],
            "protocol": "grpc",
        })
        assert r.success
        assert set(r.exporter_blocks) == {"traces", "metrics", "logs"}

    def test_http_protocol_produces_signal_specific_urls(self):
        r = OTelCollectorTransformer().transform({
            "name": "x",
            "signals": ["metrics"],
            "protocol": "http",
        })
        assert "/api/v2/otlp/v1/metrics" in r.exporter_blocks["metrics"]["endpoint"]

    def test_unknown_signal_skipped_with_warning(self):
        r = OTelCollectorTransformer().transform({
            "name": "x",
            "signals": ["traces", "mystery"],
        })
        assert "traces" in r.exporter_blocks
        assert "mystery" not in r.exporter_blocks
        assert any("Unknown OTel signal" in w for w in r.warnings)

    def test_resource_attributes_emit_ingest_mappings(self):
        r = OTelCollectorTransformer().transform({
            "name": "x",
            "signals": ["metrics"],
            "resourceAttributes": {"service.name": "myapp", "deployment.environment": "prod"},
        })
        assert r.ingest_mappings_envelope["schemaId"] == "builtin:otel.ingest-mappings"
        assert set(r.ingest_mappings_envelope["value"]["requiredAttributes"]) == {
            "service.name", "deployment.environment",
        }

    def test_processor_translation_for_known_kinds(self):
        r = OTelCollectorTransformer().transform({
            "name": "x",
            "signals": ["metrics"],
            "processors": [
                {"kind": "batch", "timeoutSeconds": 20, "sendBatchSize": 4096},
                {"kind": "memory_limiter", "limitMiB": 1024},
                {"kind": "attributes",
                 "actions": [{"key": "team", "action": "insert", "value": "sre"}]},
                {"kind": "filter", "match": "exclude", "expression": "status == 'DEBUG'"},
                {"kind": "resource", "attributes": {"env": "prod"}},
            ],
        })
        kinds = [p["kind"] for p in r.translated_processors]
        assert kinds == ["batch", "memory_limiter", "attributes", "filter", "resource"]
        assert r.translated_processors[0]["timeoutSeconds"] == 20

    def test_unknown_processor_warns_but_passes_through(self):
        r = OTelCollectorTransformer().transform({
            "name": "x",
            "signals": ["metrics"],
            "processors": [{"kind": "cumulative_to_delta", "name": "ctod"}],
        })
        assert len(r.translated_processors) == 1
        assert any("Unknown collector processor" in w for w in r.warnings)

    def test_api_key_present_triggers_secret_warning(self):
        r = OTelCollectorTransformer().transform({
            "name": "x",
            "signals": ["metrics"],
            "apiKey": "NRAK-XYZ",
        })
        assert any("secrets never migrate" in w for w in r.warnings)

    def test_collector_yaml_includes_exporters_and_pipelines(self):
        r = OTelCollectorTransformer().transform({
            "name": "x",
            "signals": ["traces", "metrics"],
        })
        assert "otlp/dynatrace_traces" in r.collector_yaml
        assert "otlp/dynatrace_metrics" in r.collector_yaml
        assert "service:" in r.collector_yaml


# ---------------------------------------------------------------------------
# LegacyErrorInboxTransformer
# ---------------------------------------------------------------------------


class TestLegacyErrorInbox:
    def test_resolved_status_emits_close_action(self):
        r = LegacyErrorInboxTransformer().transform({
            "errorGroupId": "err-1",
            "status": "RESOLVED",
            "comments": [],
        })
        assert r.success
        endpoints = [a["endpoint"] for a in r.api_actions]
        assert "/api/v2/problems/{problemId}/close" in endpoints

    def test_wip_status_emits_acknowledge_action(self):
        r = LegacyErrorInboxTransformer().transform({
            "errorGroupId": "err-1",
            "status": "WORK_IN_PROGRESS",
        })
        endpoints = [a["endpoint"] for a in r.api_actions]
        assert "/api/v2/problems/{problemId}/acknowledge" in endpoints

    def test_unresolved_status_emits_no_lifecycle_action(self):
        r = LegacyErrorInboxTransformer().transform({
            "errorGroupId": "err-1", "status": "UNRESOLVED",
        })
        endpoints = [a["endpoint"] for a in r.api_actions]
        assert all("close" not in e and "acknowledge" not in e for e in endpoints)

    def test_comments_become_problem_comment_posts(self):
        r = LegacyErrorInboxTransformer().transform({
            "errorGroupId": "err-1",
            "comments": [
                {"author": "alice", "body": "fixed in v1.2"},
                {"author": "bob", "body": "verified"},
            ],
        })
        comment_actions = [a for a in r.api_actions if "comments" in a["endpoint"]]
        assert len(comment_actions) == 2
        assert "alice" in comment_actions[0]["body"]["message"]

    def test_assignee_warns_no_dt_equivalent(self):
        r = LegacyErrorInboxTransformer().transform({
            "errorGroupId": "err-1", "assignee": "alice",
        })
        assert any("no assignee field" in w for w in r.warnings)


# ---------------------------------------------------------------------------
# LegacyRequestNamingTransformer
# ---------------------------------------------------------------------------


class TestLegacyRequestNaming:
    def test_single_site_emits_one_rule(self):
        r = LegacyRequestNamingTransformer().transform({
            "sites": [
                {"category": "Custom", "name": "/api/checkout",
                 "serviceName": "checkout-svc", "httpMethod": "POST"},
            ],
        })
        assert r.success
        assert len(r.rule_envelopes) == 1
        rule = r.rule_envelopes[0]["value"]
        assert rule["namePattern"] == "/api/checkout"
        assert rule["category"] == "Custom"
        attrs = {c["attribute"] for c in rule["conditions"]}
        assert {"SERVICE_NAME", "HTTP_REQUEST_METHOD"} <= attrs

    def test_url_pattern_adds_regex_condition(self):
        r = LegacyRequestNamingTransformer().transform({
            "sites": [
                {"name": "/api/v2/users", "serviceName": "svc",
                 "urlPathPattern": "^/api/v[0-9]+/users$"},
            ],
        })
        rule = r.rule_envelopes[0]["value"]
        url_cond = next(c for c in rule["conditions"] if c["attribute"] == "URL_PATH")
        assert url_cond["comparisonInfo"]["operator"] == "REGEX_MATCHES"
        assert url_cond["comparisonInfo"]["value"] == "^/api/v[0-9]+/users$"

    def test_missing_name_or_service_skips_and_warns(self):
        r = LegacyRequestNamingTransformer().transform({
            "sites": [
                {"name": "/x", "serviceName": ""},  # missing service
                {"name": "", "serviceName": "svc"},  # missing name
                {"name": "/y", "serviceName": "svc"},  # valid
            ],
        })
        assert len(r.rule_envelopes) == 1
        assert sum(1 for w in r.warnings if "Skipping call site" in w) == 2

    def test_empty_sites_warns_without_error(self):
        r = LegacyRequestNamingTransformer().transform({"sites": []})
        assert r.success
        assert r.rule_envelopes == []
        assert any("No call sites" in w for w in r.warnings)


# ---------------------------------------------------------------------------
# CustomEventTransformer alias
# ---------------------------------------------------------------------------


class TestCustomEventAlias:
    def test_alias_is_same_class(self):
        assert CustomEventTransformer is CustomEventIngestTransformer

    def test_alias_callable_and_produces_bizevents(self):
        r = CustomEventTransformer().transform({
            "eventType": "CheckoutCompleted",
            "records": [{"id": "c1", "amount": 42}],
        })
        assert r.success
        assert r.bizevents[0]["type"] == "CheckoutCompleted"
