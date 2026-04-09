"""Tests for TagTransformer."""

import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from transformers.tag_transformer import (
    TagTransformer,
    TagTransformResult,
)


@pytest.fixture
def tag_transformer():
    return TagTransformer()


# ═════════════════════════════════════════════════════════════════════════════
# TagTransformResult
# ═════════════════════════════════════════════════════════════════════════════


class TestTagTransformResult:
    def test_should_default_lists(self):
        r = TagTransformResult(success=True)
        assert r.auto_tag_rules == []
        assert r.warnings == []
        assert r.errors == []


# ═════════════════════════════════════════════════════════════════════════════
# Single Tag
# ═════════════════════════════════════════════════════════════════════════════


class TestTagTransformSingleTag:
    def test_should_create_auto_tag_rule(self, tag_transformer):
        entity = {
            "name": "my-service",
            "type": "APPLICATION",
            "tags": [
                {"key": "environment", "values": ["production"]},
            ],
        }
        result = tag_transformer.transform(entity)
        assert result.success is True
        assert len(result.auto_tag_rules) == 1
        rule = result.auto_tag_rules[0]
        assert "[Migrated]" in rule["name"]
        assert "environment" in rule["name"]
        assert rule["rules"][0]["valueFormat"] == "production"
        assert rule["rules"][0]["type"] == "SERVICE"

    def test_should_map_host_entity_type(self, tag_transformer):
        entity = {
            "name": "web-host-01",
            "type": "HOST",
            "tags": [
                {"key": "team", "values": ["platform"]},
            ],
        }
        result = tag_transformer.transform(entity)
        rule = result.auto_tag_rules[0]
        assert rule["rules"][0]["type"] == "HOST"


# ═════════════════════════════════════════════════════════════════════════════
# Multiple Tags
# ═════════════════════════════════════════════════════════════════════════════


class TestTagTransformMultipleTags:
    def test_should_create_rule_per_tag_value(self, tag_transformer):
        entity = {
            "name": "api-gateway",
            "type": "APPLICATION",
            "tags": [
                {"key": "env", "values": ["staging", "production"]},
                {"key": "team", "values": ["backend"]},
            ],
        }
        result = tag_transformer.transform(entity)
        assert result.success is True
        assert len(result.auto_tag_rules) == 3  # 2 env values + 1 team value

    def test_should_include_entity_name_in_conditions(self, tag_transformer):
        entity = {
            "name": "checkout-service",
            "type": "APM_APPLICATION",
            "tags": [
                {"key": "tier", "values": ["frontend"]},
            ],
        }
        result = tag_transformer.transform(entity)
        rule = result.auto_tag_rules[0]
        condition = rule["rules"][0]["conditions"][0]
        assert condition["comparisonInfo"]["value"] == "checkout-service"


# ═════════════════════════════════════════════════════════════════════════════
# Empty Tags
# ═════════════════════════════════════════════════════════════════════════════


class TestTagTransformEmptyTags:
    def test_should_succeed_with_no_rules(self, tag_transformer):
        entity = {
            "name": "bare-service",
            "type": "APPLICATION",
            "tags": [],
        }
        result = tag_transformer.transform(entity)
        assert result.success is True
        assert result.auto_tag_rules == []

    def test_should_succeed_with_missing_tags_key(self, tag_transformer):
        entity = {
            "name": "no-tags-entity",
            "type": "HOST",
        }
        result = tag_transformer.transform(entity)
        assert result.success is True
        assert result.auto_tag_rules == []


# ═════════════════════════════════════════════════════════════════════════════
# Transform All
# ═════════════════════════════════════════════════════════════════════════════


class TestTagTransformAll:
    def test_should_transform_multiple_entities(self, tag_transformer):
        entities = [
            {"name": "svc-1", "type": "APPLICATION", "tags": [{"key": "env", "values": ["prod"]}]},
            {"name": "host-1", "type": "HOST", "tags": [{"key": "region", "values": ["us-east-1"]}]},
            {"name": "svc-2", "type": "APPLICATION", "tags": []},
        ]
        results = tag_transformer.transform_all(entities)
        assert len(results) == 3
        assert all(r.success for r in results)
        assert len(results[0].auto_tag_rules) == 1
        assert len(results[1].auto_tag_rules) == 1
        assert len(results[2].auto_tag_rules) == 0
