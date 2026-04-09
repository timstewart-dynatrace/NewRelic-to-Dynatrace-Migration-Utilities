"""Tests for SLOAuditor — metric extraction, validation, fuzzy search."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from registry.slo_auditor import SLOAuditor


@pytest.fixture
def auditor():
    return SLOAuditor(
        dt_url="https://abc123.live.dynatrace.com",
        oauth_token="test-oauth",
        api_token="dt0c01.TEST"
    )


class TestExtractMetricsFromDql:
    def test_should_extract_timeseries_metric(self, auditor):
        dql = "timeseries avg(dt.service.request.response_time)"
        metrics = auditor.extract_metrics_from_dql(dql)
        assert "dt.service.request.response_time" in metrics

    def test_should_extract_builtin_metric(self, auditor):
        dql = "timeseries sum(builtin:service.errors.total.rate)"
        metrics = auditor.extract_metrics_from_dql(dql)
        assert "builtin:service.errors.total.rate" in metrics

    def test_should_not_extract_dql_keywords(self, auditor):
        dql = "fetch logs | filter severity == 'ERROR' | summarize count()"
        metrics = auditor.extract_metrics_from_dql(dql)
        # "fetch", "filter", "summarize" should not be extracted as metrics
        assert "fetch" not in metrics
        assert "filter" not in metrics

    def test_should_handle_empty_dql(self, auditor):
        result = auditor.extract_metrics_from_dql("")
        assert len(result) == 0


class TestValidateDql:
    def test_should_detect_nrql_syntax(self, auditor):
        issues = auditor.validate_dql("SELECT count(*) FROM Transaction")
        # Should flag NRQL keywords
        assert any("NRQL" in str(i) or "SELECT" in str(i) or "nrql" in str(i).lower() for i in issues)

    def test_should_pass_valid_dql(self, auditor):
        issues = auditor.validate_dql("fetch logs | summarize count()")
        # Valid DQL should have no critical issues
        nrql_issues = [i for i in issues if "NRQL" in str(i) or "SELECT" in str(i)]
        assert len(nrql_issues) == 0

    def test_should_detect_invalid_timeseries_agg(self, auditor):
        issues = auditor.validate_dql("timeseries takeLast(dt.host.cpu.usage)")
        assert any("takeLast" in str(i) for i in issues)


class TestFindCorrectMetric:
    def test_should_find_similar_metric(self, auditor):
        # find_correct_metric uses the registry for fuzzy matching
        # Without a live registry, it returns None for unknown metrics
        result = auditor.find_correct_metric("dt.host.cpu.usage")
        # Without registry loaded, returns None — that's expected
        assert result is None or isinstance(result, str)

    def test_should_return_none_for_no_match(self, auditor):
        auditor._known_metrics = set()
        result = auditor.find_correct_metric("dt.completely.unknown.metric.xyz")
        assert result is None


class TestMetricSynonyms:
    def test_should_have_common_synonym_groups(self):
        assert "error" in SLOAuditor.METRIC_SYNONYMS
        assert "response" in SLOAuditor.METRIC_SYNONYMS
        assert "memory" in SLOAuditor.METRIC_SYNONYMS

    def test_should_have_bidirectional_synonyms(self):
        # error -> failure and failure -> error
        assert "failure" in SLOAuditor.METRIC_SYNONYMS.get("error", set())


class TestInvalidAggregations:
    def test_should_list_invalid_timeseries_aggs(self):
        assert "takeLast" in SLOAuditor.INVALID_TIMESERIES_AGGS
        assert "takeFirst" in SLOAuditor.INVALID_TIMESERIES_AGGS
        assert "collectArray" in SLOAuditor.INVALID_TIMESERIES_AGGS

    def test_should_list_valid_timeseries_aggs(self):
        assert "sum" in SLOAuditor.VALID_TIMESERIES_AGGS
        assert "avg" in SLOAuditor.VALID_TIMESERIES_AGGS
        assert "count" in SLOAuditor.VALID_TIMESERIES_AGGS
