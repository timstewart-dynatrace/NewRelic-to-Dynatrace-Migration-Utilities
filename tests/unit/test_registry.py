"""Tests for DTEnvironmentRegistry — all public methods with mocked HTTP."""

import os
import sys
import json
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from registry.environment import DTEnvironmentRegistry


@pytest.fixture
def registry():
    return DTEnvironmentRegistry(
        dt_url="https://abc123.live.dynatrace.com",
        api_token="dt0c01.TEST"
    )


def _mock_urlopen(response_data, status=200):
    """Create a mock for urllib.request.urlopen context manager."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(response_data).encode('utf-8')
    mock_resp.status = status
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


class TestRegistryInit:
    def test_should_set_live_and_platform_urls(self):
        r = DTEnvironmentRegistry("https://abc123.live.dynatrace.com", api_token="test")
        assert "live" in r.live_url
        assert "apps" in r.platform_url

    def test_should_strip_trailing_slash(self):
        r = DTEnvironmentRegistry("https://abc123.live.dynatrace.com/", api_token="test")
        assert not r.dt_url.endswith("/")

    def test_should_accept_apps_url(self):
        r = DTEnvironmentRegistry("https://abc123.apps.dynatrace.com", api_token="test")
        assert "live" in r.live_url
        assert "apps" in r.platform_url


class TestSynonyms:
    def test_should_have_semantic_groups(self):
        assert "error" in DTEnvironmentRegistry.SYNONYMS
        assert "memory" in DTEnvironmentRegistry.SYNONYMS
        assert "cpu" in DTEnvironmentRegistry.SYNONYMS

    def test_error_synonyms_should_include_failure(self):
        assert "failure" in DTEnvironmentRegistry.SYNONYMS["error"]


class TestTokenSimilarity:
    def test_should_return_1_for_identical(self, registry):
        tokens = {"host", "cpu", "usage"}
        assert registry._token_similarity(tokens, tokens) == 1.0

    def test_should_return_0_for_disjoint(self, registry):
        assert registry._token_similarity({"a", "b"}, {"c", "d"}) == 0.0

    def test_should_score_synonym_matches(self, registry):
        # "error" and "failure" are synonyms
        score = registry._token_similarity({"error", "count"}, {"failure", "count"})
        assert score > 0.5

    def test_should_handle_empty_sets(self, registry):
        assert registry._token_similarity(set(), {"a"}) == 0.0


class TestTokenize:
    def test_should_split_on_dots_and_underscores(self):
        tokens = DTEnvironmentRegistry._tokenize("dt.host.cpu.usage")
        assert tokens == {"dt", "host", "cpu", "usage"}

    def test_should_lowercase(self):
        tokens = DTEnvironmentRegistry._tokenize("Host.CPU")
        assert "host" in tokens
        assert "cpu" in tokens


class TestMetricRegistry:
    def test_should_check_metric_exists(self, registry):
        with patch("urllib.request.urlopen", return_value=_mock_urlopen({
            "metrics": [{"metricId": "dt.host.cpu.usage", "displayName": "CPU Usage", "unit": "Percent"}],
            "nextPageKey": None
        })):
            assert registry.metric_exists("dt.host.cpu.usage") is True
            assert registry.metric_exists("dt.nonexistent") is False

    def test_should_get_metric_info(self, registry):
        with patch("urllib.request.urlopen", return_value=_mock_urlopen({
            "metrics": [{"metricId": "dt.host.cpu.usage", "displayName": "CPU", "unit": "%"}],
            "nextPageKey": None
        })):
            info = registry.get_metric_info("dt.host.cpu.usage")
            assert info is not None
            assert info["displayName"] == "CPU"

    def test_should_return_none_for_unknown_metric(self, registry):
        with patch("urllib.request.urlopen", return_value=_mock_urlopen({
            "metrics": [], "nextPageKey": None
        })):
            assert registry.get_metric_info("dt.nonexistent") is None


class TestFindMetric:
    def test_should_fuzzy_find_similar_metric(self, registry):
        with patch("urllib.request.urlopen", return_value=_mock_urlopen({
            "metrics": [
                {"metricId": "dt.host.cpu.usage"},
                {"metricId": "dt.host.cpu.system"},
                {"metricId": "dt.host.memory.usage"},
            ],
            "nextPageKey": None
        })):
            result = registry.find_metric("dt.host.cpu.utilization")
            # Should find a cpu-related metric via synonym/token matching
            assert result is not None
            assert "cpu" in result


class TestEntityRegistry:
    def test_should_find_entity_by_name(self, registry):
        with patch("urllib.request.urlopen", return_value=_mock_urlopen({
            "entities": [
                {"entityId": "SERVICE-123", "displayName": "my-api-service", "tags": []},
            ],
            "nextPageKey": None
        })):
            entity = registry.find_entity("my-api-service", "SERVICE")
            assert entity is not None
            assert entity["name"] == "my-api-service"

    def test_should_return_none_for_unknown_entity(self, registry):
        with patch("urllib.request.urlopen", return_value=_mock_urlopen({
            "entities": [], "nextPageKey": None
        })):
            assert registry.find_entity("nonexistent", "SERVICE") is None


class TestDashboardRegistry:
    def test_should_check_dashboard_exists(self, registry):
        # Dashboard registry uses platform URL (OAuth needed)
        registry.oauth_token = "test-oauth"
        with patch("urllib.request.urlopen", return_value=_mock_urlopen({
            "documents": [{"id": "doc1", "name": "My Dashboard"}]
        })):
            result = registry.dashboard_exists("My Dashboard")
            assert result == "doc1"

    def test_should_return_none_for_nonexistent(self, registry):
        registry.oauth_token = "test-oauth"
        with patch("urllib.request.urlopen", return_value=_mock_urlopen({
            "documents": []
        })):
            assert registry.dashboard_exists("Nonexistent") is None


class TestManagementZoneRegistry:
    def test_should_find_management_zone(self, registry):
        with patch("urllib.request.urlopen", return_value=_mock_urlopen({
            "items": [{"objectId": "mz-1", "value": {"name": "Production", "rules": []}}],
            "nextPageKey": None
        })):
            mz = registry.find_management_zone("Production")
            assert mz is not None
            assert mz["name"] == "Production"


class TestSyntheticLocationRegistry:
    def test_should_find_location_by_city(self, registry):
        mock = _mock_urlopen({
            "locations": [
                {"entityId": "loc1", "name": "N. Virginia", "city": "N. Virginia",
                 "type": "PUBLIC", "countryCode": "US", "regionCode": "", "cloudPlatform": "AWS", "status": "ENABLED"}
            ]
        })
        with patch("urllib.request.urlopen", return_value=mock):
            loc = registry.find_synthetic_location("N. Virginia")
            assert loc is not None

    def test_should_map_aws_region(self, registry):
        mock = _mock_urlopen({
            "locations": [
                {"entityId": "loc1", "name": "N. Virginia", "city": "N. Virginia",
                 "type": "PUBLIC", "countryCode": "US", "regionCode": "", "cloudPlatform": "AWS", "status": "ENABLED"}
            ]
        })
        with patch("urllib.request.urlopen", return_value=mock):
            loc = registry.find_synthetic_location("AWS_US_EAST_1")
            assert loc is not None


class TestValidateDqlSyntax:
    def test_should_return_none_without_oauth(self, registry):
        # No oauth_token set
        result = registry.validate_dql_syntax("fetch logs")
        assert result[0] is None

    def test_should_return_valid_on_200(self, registry):
        registry.oauth_token = "test-oauth"
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"records": []}).encode('utf-8')
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            is_valid, msg, _ = registry.validate_dql_syntax("fetch logs | limit 1")
            assert is_valid is True


class TestRegistrySummary:
    def test_should_return_empty_when_nothing_loaded(self, registry):
        s = registry.summary()
        assert s == {}

    def test_should_count_metrics_after_load(self, registry):
        with patch("urllib.request.urlopen", return_value=_mock_urlopen({
            "metrics": [{"metricId": "dt.host.cpu.usage"}, {"metricId": "builtin:host.cpu"}],
            "nextPageKey": None
        })):
            registry.metric_exists("dt.host.cpu.usage")  # triggers load
            s = registry.summary()
            assert s["metrics"] >= 1
