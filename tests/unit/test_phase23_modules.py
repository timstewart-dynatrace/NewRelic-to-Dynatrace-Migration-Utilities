"""Phase 23 tests — remaining nrql-engine parity items.

Covers:
  * KeyTransactionTransformer (SLO + OpenPipeline enrichment + Workflow)
  * OTelMetricsTransformer (Settings 2.0 OTLP ingest + collector snippet)
  * StatsDTransformer (ActiveGate StatsD config)
  * CloudWatchMetricStreamsTransformer (Firehose path)
  * MetricTransform plugin hook (register_metric_transform)
  * Numeric confidence-score sync
  * Per-concern mapping submodule imports
"""

from transformers import (
    CloudWatchMetricStreamsTransformer,
    KeyTransactionTransformer,
    NRQLtoDQLConverter,
    OTelMetricsTransformer,
    StatsDTransformer,
)
from transformers.metric_transform import MetricTransformRegistry
from transformers.nrql_converter import _sync_confidence_score, ConversionResult


# ---------------------------------------------------------------------------
# KeyTransactionTransformer
# ---------------------------------------------------------------------------


class TestKeyTransaction:
    def test_emits_slo_enrichment_and_workflow_bundle(self):
        r = KeyTransactionTransformer().transform({
            "name": "Checkout Flow",
            "applicationName": "checkout-svc",
            "apdexTarget": 0.5,
        })
        assert r.success
        assert r.slo_envelope["schemaId"] == "builtin:monitoring.slo"
        assert r.enrichment_processor["schemaId"] == (
            "builtin:openpipeline.logs.pipelines"
        )
        assert r.workflow["trigger"]["event"]["config"]["davis_event"][
            "entityTags"
        ] == {"key_transaction": "checkout-flow"}

    def test_slo_metric_expression_uses_duration_threshold(self):
        r = KeyTransactionTransformer().transform({
            "name": "Fast Path",
            "applicationName": "svc",
            "apdexTarget": 0.25,  # 250ms
        })
        # countIf(duration < 250ms)
        assert "countIf(duration < 250ms)" in r.slo_envelope["value"]["metricExpression"]

    def test_missing_service_warns(self):
        r = KeyTransactionTransformer().transform({
            "name": "Orphan", "apdexTarget": 0.5,
        })
        assert any("no applicationName" in w for w in r.warnings)

    def test_migrated_from_metadata_preserved(self):
        r = KeyTransactionTransformer().transform({
            "name": "X", "applicationName": "svc",
        })
        assert r.workflow["migratedFrom"]["type"] == "newrelic.key_transaction"


# ---------------------------------------------------------------------------
# OTelMetricsTransformer
# ---------------------------------------------------------------------------


class TestOTelMetrics:
    def test_grpc_envelope(self):
        r = OTelMetricsTransformer().transform({
            "name": "prod-otel",
            "protocol": "grpc",
            "temporality": "delta",
        })
        assert r.success
        val = r.ingest_envelope["value"]
        assert val["protocol"] == "GRPC"
        assert val["temporality"] == "DELTA"

    def test_unknown_protocol_defaults_to_grpc_with_warning(self):
        r = OTelMetricsTransformer().transform({
            "name": "x", "protocol": "mystery",
        })
        assert r.ingest_envelope["value"]["protocol"] == "GRPC"
        assert any("Unknown OTLP protocol" in w for w in r.warnings)

    def test_collector_snippet_has_otlp_exporter(self):
        r = OTelMetricsTransformer().transform({"name": "x", "protocol": "http"})
        assert "otlp/dynatrace" in r.collector_config_snippet
        assert "DT_API_TOKEN_METRICS_INGEST" in r.collector_config_snippet

    def test_resource_attribute_filtering_enabled_when_given(self):
        r = OTelMetricsTransformer().transform({
            "name": "x", "resourceAttributes": {"service.name": "myapp"},
        })
        filtering = r.ingest_envelope["value"]["resourceAttributeFiltering"]
        assert filtering["enabled"] is True
        assert filtering["requiredAttributes"] == ["service.name"]


# ---------------------------------------------------------------------------
# StatsDTransformer
# ---------------------------------------------------------------------------


class TestStatsD:
    def test_envelope_basics(self):
        r = StatsDTransformer().transform({
            "name": "prod-statsd",
            "listenPort": 8125,
            "metricPrefix": "app.",
            "aggregationIntervalSeconds": 10,
        })
        assert r.success
        val = r.envelope["value"]
        assert val["listenPort"] == 8125
        assert val["metricPrefix"] == "app."
        assert val["activeGateReference"] == "<pick-ActiveGate-after-import>"

    def test_nonstandard_interval_warns(self):
        r = StatsDTransformer().transform({
            "name": "x", "aggregationIntervalSeconds": 7,
        })
        assert any("non-standard" in w for w in r.warnings)

    def test_tag_mapping_list_format(self):
        r = StatsDTransformer().transform({
            "name": "x",
            "tagMappings": {"env": "environment", "svc": "service.name"},
        })
        mappings = r.envelope["value"]["tagMappings"]
        assert {"source": "env", "target": "environment"} in mappings


# ---------------------------------------------------------------------------
# CloudWatchMetricStreamsTransformer
# ---------------------------------------------------------------------------


class TestCloudWatchMetricStreams:
    def test_envelope_forces_otel_output(self):
        r = CloudWatchMetricStreamsTransformer().transform({
            "name": "prod-cwms",
            "awsAccountId": "123",
            "region": "us-east-1",
            "includeNamespaces": ["AWS/EC2", "AWS/Lambda"],
            "outputFormat": "opentelemetry",
        })
        assert r.success
        assert r.envelope["value"]["outputFormat"] == "OPENTELEMETRY_1_0"

    def test_wrong_output_format_warns(self):
        r = CloudWatchMetricStreamsTransformer().transform({
            "name": "x", "outputFormat": "json",
        })
        assert any("opentelemetry" in w.lower() or "OpenTelemetry" in w for w in r.warnings)

    def test_firehose_terraform_snippet_included(self):
        r = CloudWatchMetricStreamsTransformer().transform({
            "name": "my stream", "region": "eu-west-1",
        })
        assert "aws_kinesis_firehose_delivery_stream" in r.firehose_terraform
        assert "dt-metrics-my_stream" in r.firehose_terraform

    def test_runbook_includes_token_rotation(self):
        r = CloudWatchMetricStreamsTransformer().transform({"name": "x"})
        assert r.runbook["token_scope_required"] == "metrics.ingest"


# ---------------------------------------------------------------------------
# MetricTransform plugin hook
# ---------------------------------------------------------------------------


class TestMetricTransformHook:
    def test_registry_chains_resolvers(self):
        reg = MetricTransformRegistry()
        calls = []

        def never(field_key, raw, static):
            calls.append("never")
            return None

        def hit(field_key, raw, static):
            calls.append("hit")
            if raw == "customLatency":
                return ("dt.apps.custom.latency", None)
            return None

        reg.register(never)
        reg.register(hit)
        assert reg.resolve("f", "customLatency", None) == (
            "dt.apps.custom.latency", None,
        )
        assert calls == ["never", "hit"]

    def test_registry_returns_none_when_no_match(self):
        reg = MetricTransformRegistry()
        reg.register(lambda *_: None)
        assert reg.resolve("f", "anything", None) is None

    def test_converter_register_metric_transform(self):
        conv = NRQLtoDQLConverter()
        seen = []
        conv.register_metric_transform(lambda fk, rf, sm: seen.append(rf) or None)
        conv.convert("SELECT count(*) FROM Transaction", title="x")
        # Resolver is invoked for each metric reference; for a pure count(*)
        # query the exact count can be zero, but registration itself must
        # not raise.
        assert len(conv._metric_transforms) == 1


# ---------------------------------------------------------------------------
# Numeric confidence score sync
# ---------------------------------------------------------------------------


def _mkresult(conf, score):
    return ConversionResult(
        original_nrql="", dql="fetch x", confidence=conf,
        confidence_score=score, success=True, warnings=[], fixes=[],
    )


class TestConfidenceScoreSync:
    def test_low_category_floors_at_35(self):
        r = _mkresult("LOW", 10)
        _sync_confidence_score(r)
        assert r.confidence_score == 35

    def test_medium_category_floors_at_60(self):
        r = _mkresult("MEDIUM", 30)
        _sync_confidence_score(r)
        assert r.confidence_score == 60

    def test_high_category_floors_at_85(self):
        r = _mkresult("HIGH", 40)
        _sync_confidence_score(r)
        assert r.confidence_score == 85

    def test_drift_above_category_pulled_back(self):
        # Score higher than the category band suggests — clamp it down.
        r = _mkresult("LOW", 95)
        _sync_confidence_score(r)
        assert r.confidence_score <= 50

    def test_high_confidence_preserved(self):
        r = _mkresult("HIGH", 100)
        _sync_confidence_score(r)
        assert r.confidence_score == 100


# ---------------------------------------------------------------------------
# Split mapping package
# ---------------------------------------------------------------------------


class TestMappingSubmodules:
    def test_per_concern_imports(self):
        # Each submodule must expose exactly the one table it promises.
        from transformers.mappings.metrics import METRIC_MAP
        from transformers.mappings.attributes import ATTR_MAP
        from transformers.mappings.aggregations import AGG_MAP
        from transformers.mappings.event_types import EVENT_TYPE_MAP
        from transformers.mappings.metric_transforms import METRIC_TRANSFORMS
        from transformers.mappings.visualizations import VIZ_MAP
        assert isinstance(METRIC_MAP, dict)
        assert isinstance(ATTR_MAP, dict)
        assert isinstance(AGG_MAP, dict)
        assert isinstance(EVENT_TYPE_MAP, dict)
        assert isinstance(METRIC_TRANSFORMS, dict)
        assert isinstance(VIZ_MAP, dict)

    def test_package_level_reexports(self):
        import transformers.mappings as m
        for name in (
            "METRIC_MAP", "ATTR_MAP", "AGG_MAP",
            "EVENT_TYPE_MAP", "METRIC_TRANSFORMS", "VIZ_MAP",
        ):
            assert hasattr(m, name), f"transformers.mappings missing {name}"

    def test_values_identical_to_monolith(self):
        from transformers.mappings import METRIC_MAP as scoped
        from transformers.nrql_mapping_rules import METRIC_MAP as monolith
        # Same dict instance — re-export, not copy.
        assert scoped is monolith
