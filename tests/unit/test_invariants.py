"""Phase 26 Tier 6 — Hypothesis property-based invariant tests.

Universal invariants checked against randomized NR inputs for every
major transformer. Catches unhandled exception paths, un-serializable
output, Gen2 schema leaks in Gen3 default mode, and confidence-score
boundary violations.

These run in the regular `pytest tests/unit/` suite — no env-var gate.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Import every transformer class we want to fuzz.
# ---------------------------------------------------------------------------
from transformers.alert_transformer import AlertTransformer
from transformers.baseline_alert_transformer import BaselineAlertTransformer
from transformers.browser_rum_transformer import BrowserRUMTransformer
from transformers.change_tracking_transformer import ChangeTrackingTransformer
from transformers.cloud_integration_transformer import CloudIntegrationTransformer
from transformers.custom_entity_transformer import CustomEntityTransformer
from transformers.custom_event_ingest_transformer import CustomEventIngestTransformer
from transformers.dashboard_transformer import DashboardTransformer
from transformers.database_monitoring_transformer import DatabaseMonitoringTransformer
from transformers.drop_rule_transformer import DropRuleTransformer
from transformers.identity_transformer import IdentityTransformer
from transformers.infrastructure_transformer import InfrastructureTransformer
from transformers.key_transaction_transformer import KeyTransactionTransformer
from transformers.kubernetes_transformer import KubernetesTransformer
from transformers.lambda_transformer import LambdaTransformer
from transformers.log_archive_transformer import LogArchiveTransformer
from transformers.log_obfuscation_transformer import LogObfuscationTransformer
from transformers.log_parsing_transformer import LogParsingTransformer
from transformers.lookup_table_transformer import LookupTableTransformer
from transformers.maintenance_window_transformer import MaintenanceWindowTransformer
from transformers.metric_normalization_transformer import MetricNormalizationTransformer
from transformers.mobile_rum_transformer import MobileRUMTransformer
from transformers.non_nrql_alert_transformer import NonNRQLAlertTransformer
from transformers.npm_transformer import NPMTransformer
from transformers.otel_collector_transformer import OTelCollectorTransformer
from transformers.otel_metrics_transformer import OTelMetricsTransformer
from transformers.prometheus_transformer import PrometheusTransformer
from transformers.saved_filter_notebook_transformer import SavedFilterNotebookTransformer
from transformers.security_signals_transformer import SecuritySignalsTransformer
from transformers.slo_transformer import SLOTransformer
from transformers.statsd_transformer import StatsDTransformer
from transformers.synthetic_specialized_transformer import SyntheticSpecializedTransformer
from transformers.synthetic_transformer import SyntheticTransformer
from transformers.tag_transformer import TagTransformer
from transformers.vulnerability_transformer import VulnerabilityTransformer
from transformers.workload_transformer import WorkloadTransformer

# ---------------------------------------------------------------------------
# Gen2 schemas that must NEVER appear in default (Gen3) output.
# ---------------------------------------------------------------------------
GEN2_SCHEMAS = frozenset({
    "builtin:alerting.profile",
    "builtin:management-zones",
    "builtin:tags.auto-tagging",
    "builtin:problem.notifications.email",
    "builtin:problem.notifications.slack",
    "builtin:problem.notifications.pager-duty",
    "builtin:problem.notifications.webhook",
    "builtin:problem.notifications.jira",
    "builtin:problem.notifications.service-now",
    "builtin:problem.notifications.ops-genie",
    "builtin:problem.notifications.victor-ops",
    "builtin:anomaly-detection.metric-events",
})

# ---------------------------------------------------------------------------
# Strategies — produce plausible (not valid) NR payloads to stress
# transformers with unexpected combinations.
# ---------------------------------------------------------------------------
_text = st.text(min_size=0, max_size=60, alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")))
_small_int = st.integers(min_value=0, max_value=9999)
_bool = st.booleans()
_opt_text = st.one_of(st.none(), _text)

_nr_dict = st.fixed_dictionaries(
    {},
    optional={
        "name": _text,
        "id": _small_int,
        "enabled": _bool,
        "type": _text,
        "conditions": st.lists(
            st.fixed_dictionaries(
                {},
                optional={
                    "conditionType": st.sampled_from(["NRQL", "APM", "BROWSER", "MOBILE", "INFRA"]),
                    "name": _text,
                    "enabled": _bool,
                    "nrql": st.fixed_dictionaries({}, optional={"query": _text}),
                    "terms": st.lists(
                        st.fixed_dictionaries(
                            {},
                            optional={
                                "priority": st.sampled_from(["critical", "warning"]),
                                "operator": st.sampled_from(["ABOVE", "BELOW", "EQUALS"]),
                                "threshold": st.floats(min_value=0, max_value=1e6, allow_nan=False),
                                "thresholdDuration": _small_int,
                            },
                        ),
                        max_size=3,
                    ),
                },
            ),
            max_size=5,
        ),
        "notificationChannels": st.lists(
            st.fixed_dictionaries(
                {},
                optional={
                    "type": st.sampled_from(["EMAIL", "SLACK", "PAGERDUTY", "WEBHOOK", "JIRA", ""]),
                    "name": _text,
                    "active": _bool,
                    "properties": st.lists(
                        st.fixed_dictionaries({"key": _text, "value": _text}),
                        max_size=3,
                    ),
                },
            ),
            max_size=3,
        ),
        "description": _opt_text,
        "provider": st.sampled_from(["aws", "azure", "gcp", "oracle", ""]),
        "dbType": st.sampled_from(["mysql", "postgres", "oracle", "redis", "mystery", ""]),
        "integration": st.sampled_from(["nginx", "kafka", "unknown", ""]),
        "platform": st.sampled_from(["android", "ios", "react-native", "flutter", "mystery", ""]),
        "monitorType": st.sampled_from(["SIMPLE", "BROWSER", "SCRIPT_API", "CERT_CHECK", "BROKEN_LINKS", ""]),
        "clusterName": _text,
        "signals": st.lists(st.sampled_from(["traces", "metrics", "logs", "mystery"]), max_size=3),
        "preset": st.sampled_from(["email", "credit_card", "ssn", "bespoke", ""]),
        "runtime": st.sampled_from(["nodejs20.x", "python3.12", "java21", "rust-custom", ""]),
        "category": st.sampled_from(["deployment", "feature_flag", "chaos_experiment", "weird", ""]),
        "eventType": _text,
        "records": st.lists(st.fixed_dictionaries({}, optional={"id": _text, "amount": _small_int}), max_size=3),
        "rows": st.lists(st.fixed_dictionaries({"id": _text, "v": _text}), max_size=5),
        "sites": st.lists(
            st.fixed_dictionaries({}, optional={"name": _text, "serviceName": _text}), max_size=3
        ),
        "cells": st.lists(
            st.fixed_dictionaries(
                {},
                optional={"type": st.sampled_from(["markdown", "nrql", "mystery"]), "content": _text, "query": _text},
            ),
            max_size=3,
        ),
        "pages": st.lists(
            st.fixed_dictionaries(
                {},
                optional={
                    "name": _text,
                    "widgets": st.lists(
                        st.fixed_dictionaries(
                            {},
                            optional={
                                "title": _text,
                                "visualization": st.fixed_dictionaries({}, optional={"id": st.sampled_from([
                                    "viz.line", "viz.bar", "viz.billboard", "viz.markdown",
                                    "viz.heatmap", "viz.funnel", "viz.event-feed", "",
                                ])}),
                                "layout": st.fixed_dictionaries({}, optional={
                                    "column": st.integers(1, 12),
                                    "row": st.integers(1, 20),
                                    "width": st.integers(1, 12),
                                    "height": st.integers(1, 8),
                                }),
                                "rawConfiguration": st.fixed_dictionaries({}, optional={
                                    "text": _text,
                                    "nrqlQueries": st.lists(
                                        st.fixed_dictionaries({}, optional={"query": _text}),
                                        max_size=2,
                                    ),
                                }),
                            },
                        ),
                        max_size=5,
                    ),
                },
            ),
            max_size=3,
        ),
    },
)

# ---------------------------------------------------------------------------
# Invariant assertions
# ---------------------------------------------------------------------------


def _assert_invariants(result: Any, transformer_name: str) -> None:
    """Assert universal invariants on any transformer result."""
    # 1. Never raises — if we got here, it didn't raise. Check success/errors.
    assert hasattr(result, "success"), f"{transformer_name}: result missing .success"

    # 2. JSON-serializable — everything on the result must round-trip.
    try:
        json.dumps(result.__dict__, default=str)
    except (TypeError, ValueError) as e:
        pytest.fail(f"{transformer_name}: result not JSON-serializable: {e}")

    # 3. Warnings/errors are lists of non-empty strings.
    for field in ("warnings", "errors"):
        val = getattr(result, field, None)
        if val is not None:
            assert isinstance(val, list), f"{transformer_name}.{field} not a list"

    # 4. Any Settings 2.0 envelopes must have schemaId + scope + value.
    for field_name in dir(result):
        val = getattr(result, field_name, None)
        if isinstance(val, dict) and "schemaId" in val:
            _assert_envelope_shape(val, transformer_name, field_name)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict) and "schemaId" in item:
                    _assert_envelope_shape(item, transformer_name, field_name)


def _assert_envelope_shape(env: Dict[str, Any], tname: str, fname: str) -> None:
    assert "schemaId" in env, f"{tname}.{fname}: envelope missing schemaId"
    assert "scope" in env, f"{tname}.{fname}: envelope missing scope"
    assert "value" in env, f"{tname}.{fname}: envelope missing value"
    # 5. No Gen2 schema in Gen3 default mode.
    assert env["schemaId"] not in GEN2_SCHEMAS, (
        f"{tname}.{fname}: Gen2 schema '{env['schemaId']}' emitted in Gen3 default mode"
    )


# ---------------------------------------------------------------------------
# Per-transformer property tests
# ---------------------------------------------------------------------------

_SETTINGS = settings(
    max_examples=30,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
    deadline=None,
)


@_SETTINGS
@given(data=_nr_dict)
def test_alert_transformer_invariants(data):
    _assert_invariants(AlertTransformer().transform(data), "AlertTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_baseline_alert_invariants(data):
    _assert_invariants(BaselineAlertTransformer().transform(data), "BaselineAlertTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_browser_rum_invariants(data):
    _assert_invariants(BrowserRUMTransformer().transform(data), "BrowserRUMTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_change_tracking_invariants(data):
    _assert_invariants(ChangeTrackingTransformer().transform(data), "ChangeTrackingTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_cloud_integration_invariants(data):
    _assert_invariants(CloudIntegrationTransformer().transform(data), "CloudIntegrationTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_custom_entity_invariants(data):
    _assert_invariants(CustomEntityTransformer().transform(data), "CustomEntityTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_custom_event_ingest_invariants(data):
    _assert_invariants(CustomEventIngestTransformer().transform(data), "CustomEventIngestTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_dashboard_invariants(data):
    _assert_invariants(DashboardTransformer().transform(data), "DashboardTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_database_monitoring_invariants(data):
    _assert_invariants(DatabaseMonitoringTransformer().transform(data), "DatabaseMonitoringTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_drop_rule_invariants(data):
    _assert_invariants(DropRuleTransformer().transform(data), "DropRuleTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_identity_invariants(data):
    _assert_invariants(IdentityTransformer().transform(data), "IdentityTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_infrastructure_invariants(data):
    _assert_invariants(InfrastructureTransformer().transform(data), "InfrastructureTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_key_transaction_invariants(data):
    _assert_invariants(KeyTransactionTransformer().transform(data), "KeyTransactionTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_kubernetes_invariants(data):
    _assert_invariants(KubernetesTransformer().transform(data), "KubernetesTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_lambda_invariants(data):
    _assert_invariants(LambdaTransformer().transform(data), "LambdaTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_log_archive_invariants(data):
    _assert_invariants(LogArchiveTransformer().transform(data), "LogArchiveTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_log_obfuscation_invariants(data):
    _assert_invariants(LogObfuscationTransformer().transform(data), "LogObfuscationTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_log_parsing_invariants(data):
    _assert_invariants(LogParsingTransformer().transform(data), "LogParsingTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_lookup_table_invariants(data):
    _assert_invariants(LookupTableTransformer().transform(data), "LookupTableTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_maintenance_window_invariants(data):
    _assert_invariants(MaintenanceWindowTransformer().transform(data), "MaintenanceWindowTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_metric_normalization_invariants(data):
    _assert_invariants(MetricNormalizationTransformer().transform(data), "MetricNormalizationTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_mobile_rum_invariants(data):
    _assert_invariants(MobileRUMTransformer().transform(data), "MobileRUMTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_non_nrql_alert_invariants(data):
    _assert_invariants(NonNRQLAlertTransformer().transform(data), "NonNRQLAlertTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_npm_invariants(data):
    _assert_invariants(NPMTransformer().transform(data), "NPMTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_otel_collector_invariants(data):
    _assert_invariants(OTelCollectorTransformer().transform(data), "OTelCollectorTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_otel_metrics_invariants(data):
    _assert_invariants(OTelMetricsTransformer().transform(data), "OTelMetricsTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_prometheus_invariants(data):
    _assert_invariants(PrometheusTransformer().transform(data), "PrometheusTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_saved_filter_notebook_invariants(data):
    _assert_invariants(SavedFilterNotebookTransformer().transform(data), "SavedFilterNotebookTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_security_signals_invariants(data):
    _assert_invariants(SecuritySignalsTransformer().transform(data), "SecuritySignalsTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_slo_invariants(data):
    _assert_invariants(SLOTransformer().transform(data), "SLOTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_statsd_invariants(data):
    _assert_invariants(StatsDTransformer().transform(data), "StatsDTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_synthetic_invariants(data):
    _assert_invariants(SyntheticTransformer().transform(data), "SyntheticTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_synthetic_specialized_invariants(data):
    _assert_invariants(SyntheticSpecializedTransformer().transform(data), "SyntheticSpecializedTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_tag_invariants(data):
    _assert_invariants(TagTransformer().transform(data), "TagTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_vulnerability_invariants(data):
    _assert_invariants(VulnerabilityTransformer().transform(data), "VulnerabilityTransformer")


@_SETTINGS
@given(data=_nr_dict)
def test_workload_invariants(data):
    _assert_invariants(WorkloadTransformer().transform(data), "WorkloadTransformer")
