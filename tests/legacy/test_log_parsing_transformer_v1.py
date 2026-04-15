"""Tests for LogParsingTransformer."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from transformers.legacy.log_parsing_transformer_v1 import (
    LogParsingTransformer,
    LogParsingTransformResult,
)


@pytest.fixture
def log_parsing_transformer():
    return LogParsingTransformer()


# ═════════════════════════════════════════════════════════════════════════════
# LogParsingTransformResult
# ═════════════════════════════════════════════════════════════════════════════


class TestLogParsingTransformResult:
    def test_should_default_lists(self):
        r = LogParsingTransformResult(success=True)
        assert r.processing_rules == []
        assert r.warnings == []
        assert r.errors == []


# ═════════════════════════════════════════════════════════════════════════════
# Regex Rule
# ═════════════════════════════════════════════════════════════════════════════


class TestLogParsingTransformRegex:
    def test_should_create_processing_rule_with_dpl_pattern(self, log_parsing_transformer):
        rule = {
            "name": "Extract IP",
            "type": "regex",
            "pattern": r"(\d+\.\d+\.\d+\.\d+) - (\w+)",
            "attributes": ["ip_address", "user"],
            "enabled": True,
        }
        result = log_parsing_transformer.transform(rule)
        assert result.success is True
        assert len(result.processing_rules) == 1
        pr = result.processing_rules[0]
        assert pr["type"] == "ATTRIBUTE_EXTRACTION"
        assert "[Migrated]" in pr["name"]
        assert pr["enabled"] is True
        assert pr["source"] == "content"

    def test_should_handle_empty_pattern(self, log_parsing_transformer):
        rule = {
            "name": "Empty Pattern",
            "type": "regex",
            "pattern": "",
            "attributes": [],
        }
        result = log_parsing_transformer.transform(rule)
        assert result.success is True
        pr = result.processing_rules[0]
        assert "TODO" in pr["pattern"]


# ═════════════════════════════════════════════════════════════════════════════
# Grok Rule
# ═════════════════════════════════════════════════════════════════════════════


class TestLogParsingTransformGrok:
    def test_should_warn_about_manual_conversion(self, log_parsing_transformer):
        rule = {
            "name": "Apache Log",
            "type": "grok",
            "pattern": "%{COMMONAPACHELOG}",
            "enabled": True,
        }
        result = log_parsing_transformer.transform(rule)
        assert result.success is True
        assert len(result.warnings) > 0
        assert any("manual" in w.lower() or "grok" in w.lower() for w in result.warnings)
        pr = result.processing_rules[0]
        assert pr["enabled"] is False  # Grok rules disabled by default

    def test_should_include_todo_in_pattern(self, log_parsing_transformer):
        rule = {
            "name": "Syslog",
            "type": "grok",
            "pattern": "%{SYSLOGLINE}",
        }
        result = log_parsing_transformer.transform(rule)
        pr = result.processing_rules[0]
        assert "TODO" in pr["pattern"]


# ═════════════════════════════════════════════════════════════════════════════
# Disabled Rule
# ═════════════════════════════════════════════════════════════════════════════


class TestLogParsingTransformDisabled:
    def test_should_keep_disabled_state(self, log_parsing_transformer):
        rule = {
            "name": "Old Rule",
            "type": "regex",
            "pattern": r"error: (.+)",
            "attributes": ["message"],
            "enabled": False,
        }
        result = log_parsing_transformer.transform(rule)
        assert result.success is True
        pr = result.processing_rules[0]
        assert pr["enabled"] is False


# ═════════════════════════════════════════════════════════════════════════════
# Transform All
# ═════════════════════════════════════════════════════════════════════════════


class TestLogParsingTransformAll:
    def test_should_transform_multiple_rules(self, log_parsing_transformer):
        rules = [
            {"name": "Rule 1", "type": "regex", "pattern": r"(\w+)", "attributes": ["word"]},
            {"name": "Rule 2", "type": "grok", "pattern": "%{IP}"},
            {"name": "Rule 3", "type": "regex", "pattern": r"status=(\d+)", "attributes": ["status"], "enabled": False},
        ]
        results = log_parsing_transformer.transform_all(rules)
        assert len(results) == 3
        assert all(r.success for r in results)
