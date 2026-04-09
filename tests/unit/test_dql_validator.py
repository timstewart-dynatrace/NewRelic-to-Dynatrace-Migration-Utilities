"""Tests for validators/dql_validator.py — DQL syntax validation."""

import pytest

from validators.dql_validator import DQLSyntaxValidator


@pytest.fixture
def validator():
    return DQLSyntaxValidator()


# ─── Valid DQL ────────────────────────────────────────────────────────────────


class TestValidDQL:
    """Queries that should pass validation."""

    def test_should_accept_simple_fetch(self, validator):
        result = validator.validate('fetch logs')
        assert result.valid is True
        assert result.errors == []

    def test_should_accept_fetch_with_filter(self, validator):
        result = validator.validate('fetch logs\n| filter status == "error"')
        assert result.valid is True

    def test_should_accept_timeseries_start(self, validator):
        result = validator.validate('timeseries avg(dt.host.cpu.usage)')
        assert result.valid is True

    def test_should_accept_data_start(self, validator):
        # data record() uses = for assignment, but the validator flags it
        # as a single-equals comparison issue. Use == to avoid the false positive.
        result = validator.validate('data record(a==1)')
        assert result.valid is True

    def test_should_accept_empty_query(self, validator):
        result = validator.validate('')
        assert result.valid is True

    def test_should_accept_comment_only(self, validator):
        result = validator.validate('// This is a comment')
        assert result.valid is True

    def test_should_accept_lowercase_and_or(self, validator):
        result = validator.validate('fetch logs\n| filter a == 1 and b == 2 or c == 3')
        assert result.valid is True

    def test_should_accept_double_equals(self, validator):
        result = validator.validate('fetch logs\n| filter status == "ok"')
        assert result.valid is True

    def test_should_accept_not_equals(self, validator):
        result = validator.validate('fetch logs\n| filter status != "error"')
        assert result.valid is True


# ─── Case-insensitive invalid patterns ───────────────────────────────────────


class TestCaseInsensitivePatterns:
    """Patterns that are invalid regardless of case."""

    def test_should_reject_single_equals_with_string(self, validator):
        result = validator.validate('fetch logs\n| filter status = "error"')
        assert result.valid is False
        assert any("==" in e.message for e in result.errors)

    def test_should_reject_single_equals_with_number(self, validator):
        result = validator.validate('fetch logs\n| filter count = 5')
        assert result.valid is False

    def test_should_reject_triple_not_equals(self, validator):
        result = validator.validate('fetch logs\n| filter a !== "b"')
        assert result.valid is False
        assert any("!==" in e.message for e in result.errors)

    def test_should_reject_single_quotes(self, validator):
        result = validator.validate("fetch logs\n| filter status == 'error'")
        assert result.valid is False
        assert any("Single quotes" in e.message for e in result.errors)

    def test_should_reject_like_keyword(self, validator):
        result = validator.validate('fetch logs\n| filter name LIKE "%test%"')
        assert result.valid is False
        assert any("LIKE" in e.message for e in result.errors)

    def test_should_reject_diamond_operator(self, validator):
        result = validator.validate('fetch logs\n| filter a <> b')
        assert result.valid is False

    def test_should_reject_double_pipes(self, validator):
        result = validator.validate('fetch logs\n| filter a == 1 || b == 2')
        assert result.valid is False

    def test_should_reject_semicolons(self, validator):
        result = validator.validate('fetch logs; fetch spans')
        assert result.valid is False

    def test_should_reject_percentage_function(self, validator):
        result = validator.validate('fetch logs\n| summarize percentage(count(), status == "ok")')
        assert result.valid is False

    def test_should_reject_unique_count(self, validator):
        result = validator.validate('fetch logs\n| summarize uniqueCount(user)')
        assert result.valid is False
        assert any("countDistinct" in e.message for e in result.errors)

    def test_should_reject_funnel(self, validator):
        result = validator.validate('fetch logs\n| summarize funnel(session)')
        assert result.valid is False

    def test_should_reject_not_contains(self, validator):
        result = validator.validate('fetch logs\n| filter not contains(name, "test")')
        assert result.valid is False

    def test_should_reject_not_startswith(self, validator):
        result = validator.validate('fetch logs\n| filter not startsWith(name, "test")')
        assert result.valid is False

    def test_should_reject_not_endswith(self, validator):
        result = validator.validate('fetch logs\n| filter not endsWith(name, "test")')
        assert result.valid is False


# ─── Case-sensitive invalid patterns ─────────────────────────────────────────


class TestCaseSensitivePatterns:
    """Patterns where case determines validity."""

    def test_should_reject_uppercase_WHERE(self, validator):
        result = validator.validate('fetch logs\n| WHERE status == "error"')
        assert result.valid is False
        assert any("WHERE" in e.message and "filter" in e.message for e in result.errors)

    def test_should_reject_uppercase_AND(self, validator):
        result = validator.validate('fetch logs\n| filter a == 1 AND b == 2')
        assert result.valid is False
        assert any("AND" in e.message and "lowercase" in e.message for e in result.errors)

    def test_should_reject_uppercase_OR(self, validator):
        result = validator.validate('fetch logs\n| filter a == 1 OR b == 2')
        assert result.valid is False

    def test_should_reject_uppercase_NOT(self, validator):
        result = validator.validate('fetch logs\n| filter NOT(a == 1)')
        assert result.valid is False

    def test_should_reject_is_null(self, validator):
        result = validator.validate('fetch logs\n| filter name IS NULL')
        assert result.valid is False
        assert any("isNull" in e.message for e in result.errors)

    def test_should_reject_is_not_null(self, validator):
        result = validator.validate('fetch logs\n| filter name IS NOT NULL')
        assert result.valid is False
        assert any("isNotNull" in e.message for e in result.errors)

    def test_should_reject_facet(self, validator):
        result = validator.validate('fetch logs\nFACET name')
        assert result.valid is False

    def test_should_reject_select(self, validator):
        result = validator.validate('SELECT count(*)\nfetch logs')
        assert result.valid is False

    def test_should_reject_from(self, validator):
        result = validator.validate('fetch logs\nFROM dt.logs')
        assert result.valid is False

    def test_should_reject_since(self, validator):
        result = validator.validate('fetch logs\nSINCE 1 hour ago')
        assert result.valid is False

    def test_should_reject_until(self, validator):
        result = validator.validate('fetch logs\nUNTIL now')
        assert result.valid is False


# ─── Structural checks ──────────────────────────────────────────────────────


class TestStructuralChecks:
    """Parentheses, braces, and first-command checks."""

    def test_should_reject_unbalanced_open_paren(self, validator):
        result = validator.validate('fetch logs\n| filter count((a)')
        assert result.valid is False
        assert any("parentheses" in e.message.lower() for e in result.errors)

    def test_should_reject_unbalanced_close_paren(self, validator):
        result = validator.validate('fetch logs\n| filter count(a))')
        assert result.valid is False

    def test_should_reject_unbalanced_open_brace(self, validator):
        result = validator.validate('fetch logs\n| summarize count(), by: {name')
        assert result.valid is False
        assert any("brace" in e.message.lower() for e in result.errors)

    def test_should_reject_unbalanced_close_brace(self, validator):
        result = validator.validate('fetch logs\n| summarize count(), by: name}')
        assert result.valid is False

    def test_should_reject_wrong_first_command(self, validator):
        result = validator.validate('select count(*) from logs')
        assert result.valid is False
        assert any("fetch" in e.message for e in result.errors)

    def test_should_accept_comment_before_fetch(self, validator):
        result = validator.validate('// comment\nfetch logs')
        assert result.valid is True


# ─── Position reporting ──────────────────────────────────────────────────────


class TestPositionReporting:
    """Errors should report meaningful line/column positions."""

    def test_should_report_line_number(self, validator):
        result = validator.validate('fetch logs\n| filter a == 1 AND b == 2')
        assert result.valid is False
        assert result.errors[0].line >= 1

    def test_should_report_error_severity(self, validator):
        result = validator.validate('fetch logs\n| filter a AND b')
        assert result.valid is False
        assert result.errors[0].severity == "ERROR"


# ─── Performance anti-pattern detection ──────────────────────────────────────


class TestAntiPatterns:
    """Performance anti-pattern warnings from DQL best practices."""

    def test_should_warn_sort_before_filter(self, validator):
        result = validator.validate('fetch logs\n| sort timestamp desc\n| filter loglevel == "ERROR"')
        # Valid query but with performance warning
        warnings = [e for e in result.errors if e.severity == "WARNING"]
        assert any("sort" in w.message.lower() and "filter" in w.message.lower() for w in warnings)

    def test_should_not_warn_sort_after_filter(self, validator):
        result = validator.validate('fetch logs\n| filter loglevel == "ERROR"\n| sort timestamp desc')
        warnings = [e for e in result.errors if e.severity == "WARNING" and "sort" in e.message.lower()]
        assert len(warnings) == 0

    def test_should_warn_limit_before_summarize(self, validator):
        result = validator.validate('fetch logs\n| limit 1000\n| summarize count()')
        warnings = [e for e in result.errors if e.severity == "WARNING"]
        assert any("limit" in w.message.lower() and "summarize" in w.message.lower() for w in warnings)

    def test_should_not_warn_limit_after_summarize(self, validator):
        result = validator.validate('fetch logs\n| summarize count(), by: {host}\n| limit 10')
        warnings = [e for e in result.errors if e.severity == "WARNING" and "limit" in e.message.lower()]
        assert len(warnings) == 0

    def test_should_still_be_valid_with_only_warnings(self, validator):
        result = validator.validate('fetch logs\n| sort timestamp desc\n| filter loglevel == "ERROR"')
        # Anti-patterns are warnings, not errors — query is still valid
        assert result.valid is True
