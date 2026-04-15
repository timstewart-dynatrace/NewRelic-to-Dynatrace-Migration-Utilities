"""Tests for DropRuleTransformer."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from transformers.legacy.drop_rule_transformer_v1 import (
    DropRuleTransformer,
    DropRuleTransformResult,
)


@pytest.fixture
def drop_rule_transformer():
    return DropRuleTransformer()


# ═════════════════════════════════════════════════════════════════════════════
# DropRuleTransformResult
# ═════════════════════════════════════════════════════════════════════════════


class TestDropRuleTransformResult:
    def test_should_default_lists(self):
        r = DropRuleTransformResult(success=True)
        assert r.ingest_rules == []
        assert r.warnings == []
        assert r.errors == []


# ═════════════════════════════════════════════════════════════════════════════
# Basic Drop Rule
# ═════════════════════════════════════════════════════════════════════════════


class TestDropRuleTransform:
    def test_should_create_ingest_rule(self, drop_rule_transformer):
        rule = {
            "name": "Drop Debug Logs",
            "nrqlCondition": "level = 'DEBUG'",
            "action": "drop_data",
            "enabled": True,
        }
        result = drop_rule_transformer.transform(rule)
        assert result.success is True
        assert len(result.ingest_rules) == 1
        ir = result.ingest_rules[0]
        assert ir["type"] == "DROP"
        assert "[Migrated]" in ir["name"]
        assert ir["enabled"] is True

    def test_should_convert_nrql_operators(self, drop_rule_transformer):
        rule = {
            "name": "Complex Filter",
            "nrqlCondition": "status = 200 AND path = '/health'",
            "action": "drop_data",
        }
        result = drop_rule_transformer.transform(rule)
        ir = result.ingest_rules[0]
        assert " == " in ir["condition"]
        assert " and " in ir["condition"]

    def test_should_handle_empty_condition(self, drop_rule_transformer):
        rule = {
            "name": "Drop All",
            "nrqlCondition": "",
            "action": "drop_data",
        }
        result = drop_rule_transformer.transform(rule)
        ir = result.ingest_rules[0]
        assert "matchesValue" in ir["condition"]

    def test_should_handle_drop_attributes_action(self, drop_rule_transformer):
        rule = {
            "name": "Mask PII",
            "nrqlCondition": "service = 'payments'",
            "action": "drop_attributes",
            "attributes": ["creditCard", "ssn"],
        }
        result = drop_rule_transformer.transform(rule)
        ir = result.ingest_rules[0]
        assert ir["type"] == "MASK"
        assert ir["attributes"] == ["creditCard", "ssn"]
        assert len(result.warnings) > 0


# ═════════════════════════════════════════════════════════════════════════════
# Disabled Rule
# ═════════════════════════════════════════════════════════════════════════════


class TestDropRuleTransformDisabled:
    def test_should_preserve_disabled_state(self, drop_rule_transformer):
        rule = {
            "name": "Old Rule",
            "nrqlCondition": "env = 'test'",
            "action": "drop_data",
            "enabled": False,
        }
        result = drop_rule_transformer.transform(rule)
        assert result.success is True
        ir = result.ingest_rules[0]
        assert ir["enabled"] is False


# ═════════════════════════════════════════════════════════════════════════════
# Transform All
# ═════════════════════════════════════════════════════════════════════════════


class TestDropRuleTransformAll:
    def test_should_transform_multiple_rules(self, drop_rule_transformer):
        rules = [
            {"name": "R1", "nrqlCondition": "level = 'DEBUG'", "action": "drop_data"},
            {"name": "R2", "nrqlCondition": "status = 200", "action": "drop_data", "enabled": False},
            {"name": "R3", "nrqlCondition": "", "action": "drop_data"},
        ]
        results = drop_rule_transformer.transform_all(rules)
        assert len(results) == 3
        assert all(r.success for r in results)
