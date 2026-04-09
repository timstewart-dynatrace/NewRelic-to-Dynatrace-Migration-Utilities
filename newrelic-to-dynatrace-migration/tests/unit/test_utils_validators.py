"""Tests for utils/validators.py — config and structure validation functions."""

import pytest

from utils.validators import (
    validate_newrelic_config,
    validate_dynatrace_config,
    validate_dashboard,
    validate_metric_event,
    validate_synthetic_monitor,
)


# ─── validate_newrelic_config ─────────────────────────────────────────────────


class TestValidateNewRelicConfig:
    """Tests for validate_newrelic_config."""

    def test_should_pass_valid_config(self):
        config = {"api_key": "NRAK-ABC123", "account_id": "1234567", "region": "US"}
        valid, errors = validate_newrelic_config(config)
        assert valid is True
        assert errors == []

    def test_should_pass_eu_region(self):
        config = {"api_key": "NRAK-ABC123", "account_id": "1234567", "region": "EU"}
        valid, errors = validate_newrelic_config(config)
        assert valid is True

    def test_should_fail_when_api_key_missing(self):
        config = {"account_id": "1234567", "region": "US"}
        valid, errors = validate_newrelic_config(config)
        assert valid is False
        assert any("API_KEY" in e for e in errors)

    def test_should_fail_when_api_key_empty(self):
        config = {"api_key": "", "account_id": "1234567"}
        valid, errors = validate_newrelic_config(config)
        assert valid is False

    def test_should_fail_when_api_key_wrong_prefix(self):
        config = {"api_key": "WRONG-ABC123", "account_id": "1234567"}
        valid, errors = validate_newrelic_config(config)
        assert valid is False
        assert any("NRAK-" in e for e in errors)

    def test_should_fail_when_account_id_missing(self):
        config = {"api_key": "NRAK-ABC123", "region": "US"}
        valid, errors = validate_newrelic_config(config)
        assert valid is False
        assert any("ACCOUNT_ID" in e for e in errors)

    def test_should_fail_when_account_id_empty(self):
        config = {"api_key": "NRAK-ABC123", "account_id": ""}
        valid, errors = validate_newrelic_config(config)
        assert valid is False

    def test_should_fail_when_account_id_non_numeric(self):
        config = {"api_key": "NRAK-ABC123", "account_id": "abc"}
        valid, errors = validate_newrelic_config(config)
        assert valid is False
        assert any("numeric" in e for e in errors)

    def test_should_fail_when_region_invalid(self):
        config = {"api_key": "NRAK-ABC123", "account_id": "123", "region": "APAC"}
        valid, errors = validate_newrelic_config(config)
        assert valid is False
        assert any("US" in e and "EU" in e for e in errors)

    def test_should_default_region_to_us(self):
        config = {"api_key": "NRAK-ABC123", "account_id": "123"}
        valid, errors = validate_newrelic_config(config)
        assert valid is True

    def test_should_collect_multiple_errors(self):
        config = {"api_key": "", "account_id": "abc", "region": "APAC"}
        valid, errors = validate_newrelic_config(config)
        assert valid is False
        assert len(errors) >= 2


# ─── validate_dynatrace_config ───────────────────────────────────────────────


class TestValidateDynatraceConfig:
    """Tests for validate_dynatrace_config."""

    def test_should_pass_valid_config(self):
        config = {
            "api_token": "dt0c01.ABCDEF",
            "environment_url": "https://abc12345.live.dynatrace.com",
        }
        valid, errors = validate_dynatrace_config(config)
        assert valid is True
        assert errors == []

    def test_should_pass_apps_domain(self):
        config = {
            "api_token": "dt0c01.TOKEN",
            "environment_url": "https://abc12345.apps.dynatrace.com",
        }
        valid, errors = validate_dynatrace_config(config)
        assert valid is True

    def test_should_fail_when_api_token_missing(self):
        config = {"environment_url": "https://abc.live.dynatrace.com"}
        valid, errors = validate_dynatrace_config(config)
        assert valid is False
        assert any("API_TOKEN" in e for e in errors)

    def test_should_fail_when_api_token_empty(self):
        config = {"api_token": "", "environment_url": "https://abc.live.dynatrace.com"}
        valid, errors = validate_dynatrace_config(config)
        assert valid is False

    def test_should_fail_when_api_token_wrong_prefix(self):
        config = {
            "api_token": "wrong.prefix",
            "environment_url": "https://abc.live.dynatrace.com",
        }
        valid, errors = validate_dynatrace_config(config)
        assert valid is False
        assert any("dt0c01." in e for e in errors)

    def test_should_fail_when_environment_url_missing(self):
        config = {"api_token": "dt0c01.TOKEN"}
        valid, errors = validate_dynatrace_config(config)
        assert valid is False
        assert any("ENVIRONMENT_URL" in e for e in errors)

    def test_should_fail_when_environment_url_empty(self):
        config = {"api_token": "dt0c01.TOKEN", "environment_url": ""}
        valid, errors = validate_dynatrace_config(config)
        assert valid is False

    def test_should_fail_when_environment_url_wrong_format(self):
        config = {
            "api_token": "dt0c01.TOKEN",
            "environment_url": "http://abc.live.dynatrace.com",
        }
        valid, errors = validate_dynatrace_config(config)
        assert valid is False

    def test_should_fail_when_environment_url_has_wrong_domain(self):
        config = {
            "api_token": "dt0c01.TOKEN",
            "environment_url": "https://abc.example.com",
        }
        valid, errors = validate_dynatrace_config(config)
        assert valid is False


# ─── validate_dashboard ──────────────────────────────────────────────────────


class TestValidateDashboard:
    """Tests for validate_dashboard."""

    def test_should_pass_valid_dashboard(self):
        dashboard = {
            "dashboardMetadata": {"name": "Test"},
            "tiles": [],
        }
        valid, errors = validate_dashboard(dashboard)
        assert valid is True
        assert errors == []

    def test_should_fail_missing_metadata(self):
        dashboard = {"tiles": []}
        valid, errors = validate_dashboard(dashboard)
        assert valid is False
        assert any("dashboardMetadata" in e for e in errors)

    def test_should_fail_missing_name_in_metadata(self):
        dashboard = {"dashboardMetadata": {}, "tiles": []}
        valid, errors = validate_dashboard(dashboard)
        assert valid is False
        assert any("name" in e for e in errors)

    def test_should_fail_missing_tiles(self):
        dashboard = {"dashboardMetadata": {"name": "Test"}}
        valid, errors = validate_dashboard(dashboard)
        assert valid is False
        assert any("tiles" in e for e in errors)


# ─── validate_metric_event ───────────────────────────────────────────────────


class TestValidateMetricEvent:
    """Tests for validate_metric_event."""

    def test_should_pass_valid_event(self):
        event = {"summary": "Alert", "monitoringStrategy": {"type": "STATIC"}}
        valid, errors = validate_metric_event(event)
        assert valid is True

    def test_should_fail_missing_summary(self):
        event = {"monitoringStrategy": {"type": "STATIC"}}
        valid, errors = validate_metric_event(event)
        assert valid is False
        assert any("summary" in e for e in errors)

    def test_should_fail_missing_monitoring_strategy(self):
        event = {"summary": "Alert"}
        valid, errors = validate_metric_event(event)
        assert valid is False
        assert any("monitoringStrategy" in e for e in errors)


# ─── validate_synthetic_monitor ──────────────────────────────────────────────


class TestValidateSyntheticMonitor:
    """Tests for validate_synthetic_monitor."""

    def test_should_pass_valid_http_monitor(self):
        monitor = {
            "name": "Test",
            "type": "HTTP",
            "frequencyMin": 15,
            "locations": ["LOC1"],
        }
        valid, errors = validate_synthetic_monitor(monitor)
        assert valid is True

    def test_should_pass_valid_browser_monitor(self):
        monitor = {
            "name": "Test",
            "type": "BROWSER",
            "frequencyMin": 15,
            "locations": ["LOC1"],
        }
        valid, errors = validate_synthetic_monitor(monitor)
        assert valid is True

    def test_should_fail_missing_name(self):
        monitor = {"type": "HTTP", "frequencyMin": 15, "locations": ["LOC1"]}
        valid, errors = validate_synthetic_monitor(monitor)
        assert valid is False

    def test_should_fail_missing_type(self):
        monitor = {"name": "Test", "frequencyMin": 15, "locations": ["LOC1"]}
        valid, errors = validate_synthetic_monitor(monitor)
        assert valid is False

    def test_should_fail_invalid_type(self):
        monitor = {
            "name": "Test",
            "type": "INVALID",
            "frequencyMin": 15,
            "locations": ["LOC1"],
        }
        valid, errors = validate_synthetic_monitor(monitor)
        assert valid is False

    def test_should_fail_missing_frequency(self):
        monitor = {"name": "Test", "type": "HTTP", "locations": ["LOC1"]}
        valid, errors = validate_synthetic_monitor(monitor)
        assert valid is False

    def test_should_fail_missing_locations(self):
        monitor = {"name": "Test", "type": "HTTP", "frequencyMin": 15}
        valid, errors = validate_synthetic_monitor(monitor)
        assert valid is False

    def test_should_fail_empty_locations(self):
        monitor = {
            "name": "Test",
            "type": "HTTP",
            "frequencyMin": 15,
            "locations": [],
        }
        valid, errors = validate_synthetic_monitor(monitor)
        assert valid is False
