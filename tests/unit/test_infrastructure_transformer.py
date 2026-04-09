"""Tests for InfrastructureTransformer."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from transformers.infrastructure_transformer import (
    InfrastructureTransformer,
    InfrastructureTransformResult,
)


@pytest.fixture
def infra_transformer():
    return InfrastructureTransformer()


# ═════════════════════════════════════════════════════════════════════════════
# InfrastructureTransformResult
# ═════════════════════════════════════════════════════════════════════════════


class TestInfrastructureTransformResult:
    def test_should_default_lists(self):
        r = InfrastructureTransformResult(success=True)
        assert r.metric_events == []
        assert r.warnings == []
        assert r.errors == []


# ═════════════════════════════════════════════════════════════════════════════
# Host Not Reporting
# ═════════════════════════════════════════════════════════════════════════════


class TestInfraTransformHostNotReporting:
    def test_should_map_to_host_availability_metric(self, infra_transformer):
        condition = {
            "name": "Host Down",
            "type": "host_not_reporting",
            "enabled": True,
            "criticalThreshold": {"durationMinutes": 5},
        }
        result = infra_transformer.transform(condition)
        assert result.success is True
        assert len(result.metric_events) == 1
        event = result.metric_events[0]
        assert event["metricId"] == "builtin:host.availability"
        assert event["alertCondition"] == "BELOW"
        assert event["enabled"] is True
        assert "[Migrated]" in event["name"]

    def test_should_use_duration_from_threshold(self, infra_transformer):
        condition = {
            "name": "Host Down",
            "type": "host_not_reporting",
            "criticalThreshold": {"durationMinutes": 10},
        }
        result = infra_transformer.transform(condition)
        event = result.metric_events[0]
        assert event["samples"] == 10
        assert event["violatingSamples"] == 10
        assert event["dealertingSamples"] == 20


# ═════════════════════════════════════════════════════════════════════════════
# Process Not Running
# ═════════════════════════════════════════════════════════════════════════════


class TestInfraTransformProcessNotRunning:
    def test_should_map_to_process_count_metric(self, infra_transformer):
        condition = {
            "name": "Nginx Down",
            "type": "process_not_running",
            "enabled": True,
        }
        result = infra_transformer.transform(condition)
        assert result.success is True
        assert len(result.metric_events) == 1
        event = result.metric_events[0]
        assert event["metricId"] == "builtin:tech.generic.process.count"
        assert event["alertCondition"] == "BELOW"
        assert event["alertConditionValue"] == 1

    def test_should_warn_on_process_filter(self, infra_transformer):
        condition = {
            "name": "Custom Process",
            "type": "process_not_running",
            "processWhereClause": "commandName = 'myapp'",
        }
        result = infra_transformer.transform(condition)
        assert result.success is True
        assert any("process filter" in w.lower() or "processWhereClause" in w
                    or "manual" in w.lower() for w in result.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# Infra Metric
# ═════════════════════════════════════════════════════════════════════════════


class TestInfraTransformMetric:
    def test_should_map_known_metric(self, infra_transformer):
        condition = {
            "name": "High CPU",
            "type": "infra_metric",
            "event_type": "SystemSample",
            "select_value": "cpuPercent",
            "comparison": "above",
            "criticalThreshold": {"value": 90, "durationMinutes": 5},
            "enabled": True,
        }
        result = infra_transformer.transform(condition)
        assert result.success is True
        event = result.metric_events[0]
        assert event["metricId"] == "builtin:host.cpu.usage"
        assert event["alertCondition"] == "ABOVE"
        assert event["alertConditionValue"] == 90

    def test_should_warn_on_unmapped_metric(self, infra_transformer):
        condition = {
            "name": "Custom Metric",
            "type": "infra_metric",
            "event_type": "SystemSample",
            "select_value": "customGauge",
            "comparison": "above",
            "criticalThreshold": {"value": 100, "durationMinutes": 3},
        }
        result = infra_transformer.transform(condition)
        assert result.success is True
        assert any("no direct mapping" in w.lower() for w in result.warnings)
        event = result.metric_events[0]
        assert "customGauge" in event["metricId"]

    def test_should_map_below_operator(self, infra_transformer):
        condition = {
            "name": "Low Disk",
            "type": "infra_metric",
            "select_value": "diskUsedPercent",
            "comparison": "below",
            "criticalThreshold": {"value": 10, "durationMinutes": 5},
        }
        result = infra_transformer.transform(condition)
        event = result.metric_events[0]
        assert event["alertCondition"] == "BELOW"


# ═════════════════════════════════════════════════════════════════════════════
# Unknown Type
# ═════════════════════════════════════════════════════════════════════════════


class TestInfraTransformUnknown:
    def test_should_warn_and_create_placeholder(self, infra_transformer):
        condition = {
            "name": "Mystery Condition",
            "type": "custom_integration",
        }
        result = infra_transformer.transform(condition)
        assert result.success is True
        assert len(result.warnings) > 0
        assert any("unknown" in w.lower() for w in result.warnings)
        event = result.metric_events[0]
        assert event["enabled"] is False


# ═════════════════════════════════════════════════════════════════════════════
# Transform All
# ═════════════════════════════════════════════════════════════════════════════


class TestInfraTransformAll:
    def test_should_transform_multiple_conditions(self, infra_transformer):
        conditions = [
            {"name": "Host Down", "type": "host_not_reporting", "criticalThreshold": {"durationMinutes": 5}},
            {"name": "High CPU", "type": "infra_metric", "select_value": "cpuPercent", "comparison": "above", "criticalThreshold": {"value": 90, "durationMinutes": 5}},
            {"name": "Nginx", "type": "process_not_running"},
        ]
        results = infra_transformer.transform_all(conditions)
        assert len(results) == 3
        assert all(r.success for r in results)
