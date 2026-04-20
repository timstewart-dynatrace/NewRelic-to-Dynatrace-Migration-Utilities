"""Tests for config/settings.py — config classes, endpoints, components."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from config.settings import (
    AVAILABLE_COMPONENTS,
    COMPONENT_DEPENDENCIES,
    DynatraceConfig,
    MigrationConfig,
    NewRelicConfig,
    Settings,
    get_settings,
)


class TestNewRelicConfig:
    def test_should_set_us_graphql_endpoint(self):
        c = NewRelicConfig(
            NEW_RELIC_API_KEY="NRAK-TEST",
            NEW_RELIC_ACCOUNT_ID="123",
            NEW_RELIC_REGION="US",
        )
        assert c.graphql_endpoint == "https://api.newrelic.com/graphql"

    def test_should_set_eu_graphql_endpoint(self):
        c = NewRelicConfig(
            NEW_RELIC_API_KEY="NRAK-TEST",
            NEW_RELIC_ACCOUNT_ID="123",
            NEW_RELIC_REGION="EU",
        )
        assert c.graphql_endpoint == "https://api.eu.newrelic.com/graphql"

    def test_should_set_us_rest_api_base(self):
        c = NewRelicConfig(
            NEW_RELIC_API_KEY="NRAK-TEST",
            NEW_RELIC_ACCOUNT_ID="123",
        )
        assert c.rest_api_base == "https://api.newrelic.com/v2"

    def test_should_set_eu_rest_api_base(self):
        c = NewRelicConfig(
            NEW_RELIC_API_KEY="NRAK-TEST",
            NEW_RELIC_ACCOUNT_ID="123",
            NEW_RELIC_REGION="EU",
        )
        assert c.rest_api_base == "https://api.eu.newrelic.com/v2"

    def test_should_default_region_to_us(self):
        c = NewRelicConfig(
            NEW_RELIC_API_KEY="NRAK-TEST",
            NEW_RELIC_ACCOUNT_ID="123",
        )
        assert c.region == "US"


class TestDynatraceConfig:
    def test_should_set_api_v2_base(self):
        c = DynatraceConfig(
            DYNATRACE_API_TOKEN="dt0c01.TEST",
            DYNATRACE_ENVIRONMENT_URL="https://abc.live.dynatrace.com",
        )
        assert c.api_v2_base == "https://abc.live.dynatrace.com/api/v2"

    def test_should_set_config_api_base(self):
        c = DynatraceConfig(
            DYNATRACE_API_TOKEN="dt0c01.TEST",
            DYNATRACE_ENVIRONMENT_URL="https://abc.live.dynatrace.com",
        )
        assert c.config_api_base == "https://abc.live.dynatrace.com/api/config/v1"

    def test_should_set_settings_api(self):
        c = DynatraceConfig(
            DYNATRACE_API_TOKEN="dt0c01.TEST",
            DYNATRACE_ENVIRONMENT_URL="https://abc.live.dynatrace.com",
        )
        assert c.settings_api == "https://abc.live.dynatrace.com/api/v2/settings"

    def test_should_set_gen3_settings_api_on_apps_host(self):
        # Gen3 SaaS tenants expose Settings 2.0 under
        # /platform/classic/environment-api/v2, NOT /api/v2.
        c = DynatraceConfig(
            DYNATRACE_API_TOKEN="dt0s16.PLATFORM",
            DYNATRACE_ENVIRONMENT_URL="https://abc.apps.dynatrace.com",
        )
        assert c.settings_api == (
            "https://abc.apps.dynatrace.com/platform/classic/environment-api/v2/settings"
        )

    def test_should_strip_trailing_slash(self):
        c = DynatraceConfig(
            DYNATRACE_API_TOKEN="dt0c01.TEST",
            DYNATRACE_ENVIRONMENT_URL="https://abc.live.dynatrace.com/",
        )
        assert c.environment_url == "https://abc.live.dynatrace.com"


class TestMigrationConfig:
    def test_should_have_default_components(self):
        c = MigrationConfig()
        assert "dashboards" in c.components
        assert "alerts" in c.components

    def test_should_default_dry_run_to_false(self):
        c = MigrationConfig()
        assert c.dry_run is False

    def test_should_default_batch_size_to_50(self):
        c = MigrationConfig()
        assert c.batch_size == 50

    def test_should_default_rate_limit(self):
        c = MigrationConfig()
        assert c.rate_limit == 5.0

    def test_should_default_continue_on_error(self):
        c = MigrationConfig()
        assert c.continue_on_error is True


class TestSettings:
    def setup_method(self):
        Settings.reset()

    def test_should_be_singleton(self):
        os.environ["NEW_RELIC_API_KEY"] = "NRAK-TEST"
        os.environ["NEW_RELIC_ACCOUNT_ID"] = "123"
        os.environ["DYNATRACE_API_TOKEN"] = "dt0c01.TEST"
        os.environ["DYNATRACE_ENVIRONMENT_URL"] = "https://abc.live.dynatrace.com"
        try:
            s1 = Settings()
            s2 = Settings()
            assert s1 is s2
        finally:
            Settings.reset()

    def test_reset_should_clear_instance(self):
        Settings.reset()
        assert Settings._instance is None


class TestGetSettings:
    def setup_method(self):
        Settings.reset()

    def test_should_return_settings_instance(self):
        os.environ["NEW_RELIC_API_KEY"] = "NRAK-TEST"
        os.environ["NEW_RELIC_ACCOUNT_ID"] = "123"
        os.environ["DYNATRACE_API_TOKEN"] = "dt0c01.TEST"
        os.environ["DYNATRACE_ENVIRONMENT_URL"] = "https://abc.live.dynatrace.com"
        try:
            s = get_settings()
            assert hasattr(s, 'newrelic')
            assert hasattr(s, 'dynatrace')
            assert hasattr(s, 'migration')
        finally:
            Settings.reset()


class TestAvailableComponents:
    def test_should_include_core_components(self):
        assert "dashboards" in AVAILABLE_COMPONENTS
        assert "alerts" in AVAILABLE_COMPONENTS
        assert "synthetics" in AVAILABLE_COMPONENTS
        assert "slos" in AVAILABLE_COMPONENTS
        assert "workloads" in AVAILABLE_COMPONENTS
        assert "notification_channels" in AVAILABLE_COMPONENTS

    def test_should_have_dependencies(self):
        assert "notification_channels" in COMPONENT_DEPENDENCIES.get("alerts", [])
        assert "alerts" in COMPONENT_DEPENDENCIES.get("slos", [])
