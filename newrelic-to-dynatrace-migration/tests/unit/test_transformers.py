"""Tests for all transformer classes:
- DashboardTransformer
- AlertTransformer + NotificationTransformer
- SyntheticTransformer + SyntheticScriptConverter
- SLOTransformer
- WorkloadTransformer
"""

import pytest

from transformers.dashboard_transformer import DashboardTransformer, TransformResult
from transformers.alert_transformer import (
    AlertTransformer,
    AlertTransformResult,
    NotificationTransformer,
)
from transformers.synthetic_transformer import (
    SyntheticTransformer,
    SyntheticTransformResult,
    SyntheticScriptConverter,
)
from transformers.slo_transformer import SLOTransformer, SLOTransformResult
from transformers.workload_transformer import WorkloadTransformer, WorkloadTransformResult


# ═════════════════════════════════════════════════════════════════════════════
# DashboardTransformer
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def dashboard_transformer():
    return DashboardTransformer()


class TestDashboardTransformResult:
    def test_should_default_warnings_and_errors(self):
        r = TransformResult(success=True)
        assert r.warnings == []
        assert r.errors == []


class TestDashboardTransformEmpty:
    def test_should_fail_with_no_pages(self, dashboard_transformer):
        nr = {"name": "Test", "pages": []}
        results = dashboard_transformer.transform(nr)
        assert len(results) == 1
        assert results[0].success is False
        assert any("no pages" in e for e in results[0].errors)

    def test_should_fail_with_missing_pages(self, dashboard_transformer):
        nr = {"name": "Test"}
        results = dashboard_transformer.transform(nr)
        assert len(results) == 1
        assert results[0].success is False


class TestDashboardTransformSinglePage:
    def test_should_transform_single_page_dashboard(self, dashboard_transformer):
        nr = {
            "name": "My Dashboard",
            "permissions": "PUBLIC_READ_ONLY",
            "pages": [
                {
                    "name": "Page 1",
                    "widgets": [],
                }
            ],
        }
        results = dashboard_transformer.transform(nr)
        assert len(results) == 1
        assert results[0].success is True
        dt = results[0].data
        assert dt["dashboardMetadata"]["name"] == "My Dashboard"
        assert dt["dashboardMetadata"]["shared"] is True
        assert "tiles" in dt


class TestDashboardTransformMultiPage:
    def test_should_create_separate_dashboards_per_page(self, dashboard_transformer):
        nr = {
            "name": "Multi",
            "pages": [
                {"name": "Overview", "widgets": []},
                {"name": "Details", "widgets": []},
            ],
        }
        results = dashboard_transformer.transform(nr)
        assert len(results) == 2
        assert "Overview" in results[0].data["dashboardMetadata"]["name"]
        assert "Details" in results[1].data["dashboardMetadata"]["name"]


class TestDashboardTransformWidgets:
    def test_should_transform_markdown_widget(self, dashboard_transformer):
        nr = {
            "name": "Test",
            "pages": [
                {
                    "name": "Page",
                    "widgets": [
                        {
                            "title": "Notes",
                            "visualization": {"id": "viz.markdown"},
                            "rawConfiguration": {"text": "# Hello"},
                            "layout": {"column": 1, "row": 1, "width": 4, "height": 3},
                        }
                    ],
                }
            ],
        }
        results = dashboard_transformer.transform(nr)
        assert results[0].success is True
        tiles = results[0].data["tiles"]
        assert len(tiles) == 1
        assert tiles[0]["tileType"] == "MARKDOWN"
        assert tiles[0]["markdown"] == "# Hello"

    def test_should_transform_chart_widget_with_nrql(self, dashboard_transformer):
        nr = {
            "name": "Test",
            "pages": [
                {
                    "name": "Page",
                    "widgets": [
                        {
                            "title": "Requests",
                            "visualization": {"id": "viz.line"},
                            "rawConfiguration": {
                                "nrqlQueries": [
                                    {"query": "SELECT count(*) FROM Transaction"}
                                ]
                            },
                            "layout": {"column": 1, "row": 1, "width": 6, "height": 4},
                        }
                    ],
                }
            ],
        }
        results = dashboard_transformer.transform(nr)
        assert results[0].success is True
        tiles = results[0].data["tiles"]
        assert len(tiles) == 1
        assert tiles[0]["tileType"] == "DATA_EXPLORER"
        assert tiles[0]["queries"][0]["freeText"]  # Has DQL

    def test_should_transform_billboard_widget(self, dashboard_transformer):
        nr = {
            "name": "Test",
            "pages": [
                {
                    "name": "Page",
                    "widgets": [
                        {
                            "title": "Total",
                            "visualization": {"id": "viz.billboard"},
                            "rawConfiguration": {
                                "nrqlQueries": [
                                    {"query": "SELECT count(*) FROM Transaction"}
                                ]
                            },
                            "layout": {"column": 1, "row": 1, "width": 3, "height": 3},
                        }
                    ],
                }
            ],
        }
        results = dashboard_transformer.transform(nr)
        tiles = results[0].data["tiles"]
        assert tiles[0]["tileType"] == "DATA_EXPLORER"


class TestDashboardTransformLayout:
    def test_should_convert_layout_to_pixel_bounds(self, dashboard_transformer):
        layout = {"column": 1, "row": 1, "width": 6, "height": 4}
        bounds = dashboard_transformer._transform_layout(layout)
        assert bounds["top"] == 0
        assert bounds["left"] == 0
        assert bounds["width"] == 6 * 38 * 2
        assert bounds["height"] == 4 * 38 * 2

    def test_should_handle_offset_position(self, dashboard_transformer):
        layout = {"column": 7, "row": 3, "width": 6, "height": 4}
        bounds = dashboard_transformer._transform_layout(layout)
        assert bounds["left"] == 6 * 38 * 2  # column 7 is index 6
        assert bounds["top"] == 2 * 38 * 2   # row 3 is index 2


class TestDashboardTransformPermissions:
    def test_should_map_public_read_only(self, dashboard_transformer):
        assert dashboard_transformer._map_permissions("PUBLIC_READ_ONLY") is True

    def test_should_map_public_read_write(self, dashboard_transformer):
        assert dashboard_transformer._map_permissions("PUBLIC_READ_WRITE") is True

    def test_should_map_private(self, dashboard_transformer):
        assert dashboard_transformer._map_permissions("PRIVATE") is False

    def test_should_default_none_to_false(self, dashboard_transformer):
        assert dashboard_transformer._map_permissions(None) is False


class TestDashboardTransformVariables:
    def test_should_transform_variables_to_filters(self, dashboard_transformer):
        variables = [{"name": "env", "type": "string"}, {"name": "app", "type": "nrql"}]
        result = dashboard_transformer._transform_variables(variables)
        assert len(result["genericTagFilters"]) == 2
        assert result["genericTagFilters"][0]["name"] == "env"


class TestDashboardTransformAll:
    def test_should_transform_multiple_dashboards(self, dashboard_transformer):
        dashboards = [
            {"name": "D1", "pages": [{"name": "P1", "widgets": []}]},
            {"name": "D2", "pages": [{"name": "P1", "widgets": []}]},
        ]
        results = dashboard_transformer.transform_all(dashboards)
        assert len(results) == 2
        assert all(r.success for r in results)


# ═════════════════════════════════════════════════════════════════════════════
# AlertTransformer
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def alert_transformer():
    return AlertTransformer()


class TestAlertTransformResult:
    def test_should_default_lists(self):
        r = AlertTransformResult(success=True)
        assert r.metric_events == []
        assert r.warnings == []
        assert r.errors == []


class TestAlertTransformPolicy:
    def test_should_transform_empty_policy(self, alert_transformer):
        policy = {"name": "Test Policy", "id": "123", "conditions": []}
        result = alert_transformer.transform_policy(policy)
        assert result.success is True
        assert result.alerting_profile is not None
        assert "[Migrated]" in result.alerting_profile["name"]
        assert result.metric_events == []

    def test_should_transform_policy_with_nrql_condition(self, alert_transformer):
        policy = {
            "name": "Test Policy",
            "id": "123",
            "conditions": [
                {
                    "name": "High Error Rate",
                    "conditionType": "NRQL",
                    "nrql": {"query": "SELECT count(*) FROM TransactionError"},
                    "signal": {"aggregationWindow": 60},
                    "terms": [
                        {
                            "priority": "critical",
                            "operator": "ABOVE",
                            "threshold": 10,
                            "thresholdDuration": 300,
                        }
                    ],
                    "enabled": True,
                }
            ],
        }
        result = alert_transformer.transform_policy(policy)
        assert result.success is True
        assert len(result.metric_events) == 1
        event = result.metric_events[0]
        assert event["summary"].startswith("[Migrated]")
        assert event["enabled"] is True
        assert event["monitoringStrategy"]["threshold"] == 10
        assert event["monitoringStrategy"]["alertCondition"] == "ABOVE"

    def test_should_create_placeholder_for_non_nrql_condition(self, alert_transformer):
        policy = {
            "name": "Test",
            "conditions": [
                {"name": "APM Cond", "conditionType": "APM"}
            ],
        }
        result = alert_transformer.transform_policy(policy)
        assert result.success is True
        assert len(result.metric_events) == 1
        assert result.metric_events[0]["enabled"] is False  # Placeholder disabled


class TestAlertTransformMonitoringStrategy:
    def test_should_build_default_strategy(self, alert_transformer):
        strategy = alert_transformer._build_monitoring_strategy([], 60, "", [])
        assert strategy["type"] == "STATIC_THRESHOLD"
        assert strategy["alertCondition"] == "ABOVE"

    def test_should_use_critical_term(self, alert_transformer):
        terms = [
            {"priority": "warning", "operator": "ABOVE", "threshold": 5},
            {"priority": "critical", "operator": "BELOW", "threshold": 100},
        ]
        strategy = alert_transformer._build_monitoring_strategy(terms, 60, "", [])
        assert strategy["alertCondition"] == "BELOW"
        assert strategy["threshold"] == 100

    def test_should_handle_at_least_once_occurrences(self, alert_transformer):
        terms = [
            {
                "priority": "critical",
                "operator": "ABOVE",
                "threshold": 10,
                "thresholdDuration": 300,
                "thresholdOccurrences": "AT_LEAST_ONCE",
            }
        ]
        strategy = alert_transformer._build_monitoring_strategy(terms, 60, "", [])
        assert strategy["violatingSamples"] == 1


class TestAlertExtractMetric:
    def test_should_extract_duration_metric(self, alert_transformer):
        metric = alert_transformer._extract_metric_from_nrql(
            "SELECT average(duration) FROM Transaction"
        )
        assert metric == "builtin:service.response.time"

    def test_should_extract_error_metric(self, alert_transformer):
        metric = alert_transformer._extract_metric_from_nrql(
            "SELECT count(*) FROM TransactionError"
        )
        assert metric == "builtin:service.errors.total.rate"

    def test_should_extract_cpu_metric(self, alert_transformer):
        metric = alert_transformer._extract_metric_from_nrql(
            "SELECT average(cpuPercent) FROM SystemSample"
        )
        assert metric == "builtin:host.cpu.usage"

    def test_should_return_none_for_unknown(self, alert_transformer):
        metric = alert_transformer._extract_metric_from_nrql(
            "SELECT count(*) FROM CustomEvent"
        )
        assert metric is None


class TestAlertTransformAll:
    def test_should_transform_multiple_policies(self, alert_transformer):
        policies = [
            {"name": "P1", "conditions": []},
            {"name": "P2", "conditions": []},
        ]
        results = alert_transformer.transform_all(policies)
        assert len(results) == 2
        assert all(r.success for r in results)


# ─── NotificationTransformer ────────────────────────────────────────────────


class TestNotificationTransformer:
    @pytest.fixture
    def notif_transformer(self):
        return NotificationTransformer()

    def test_should_transform_email_channel(self, notif_transformer):
        channel = {
            "name": "Team Email",
            "type": "EMAIL",
            "active": True,
            "properties": [{"key": "recipients", "value": "a@b.com,c@d.com"}],
        }
        result = notif_transformer.transform_channel(channel)
        assert result["success"] is True
        assert result["integration_type"] == "email"
        assert "a@b.com" in result["config"]["recipients"]

    def test_should_transform_slack_channel(self, notif_transformer):
        channel = {
            "name": "Slack Alert",
            "type": "SLACK",
            "properties": [
                {"key": "url", "value": "https://hooks.slack.com/xxx"},
                {"key": "channel", "value": "#alerts"},
            ],
        }
        result = notif_transformer.transform_channel(channel)
        assert result["success"] is True
        assert result["integration_type"] == "slack"
        assert result["config"]["channel"] == "#alerts"

    def test_should_transform_pagerduty_channel(self, notif_transformer):
        channel = {
            "name": "PD",
            "type": "PAGERDUTY",
            "properties": [{"key": "service_key", "value": "abc123"}],
        }
        result = notif_transformer.transform_channel(channel)
        assert result["success"] is True
        assert result["integration_type"] == "pagerduty"

    def test_should_transform_webhook_channel(self, notif_transformer):
        channel = {
            "name": "Hook",
            "type": "WEBHOOK",
            "properties": [{"key": "base_url", "value": "https://example.com/hook"}],
        }
        result = notif_transformer.transform_channel(channel)
        assert result["success"] is True
        assert result["integration_type"] == "webhook"

    def test_should_fail_unsupported_type(self, notif_transformer):
        channel = {"name": "Unknown", "type": "UNKNOWN_TYPE", "properties": []}
        result = notif_transformer.transform_channel(channel)
        assert result["success"] is False
        assert len(result["errors"]) > 0


# ═════════════════════════════════════════════════════════════════════════════
# SyntheticTransformer
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def synthetic_transformer():
    return SyntheticTransformer()


class TestSyntheticTransformResult:
    def test_should_default_lists(self):
        r = SyntheticTransformResult(success=True)
        assert r.warnings == []
        assert r.errors == []


class TestSyntheticTransformHTTP:
    def test_should_transform_simple_ping_monitor(self, synthetic_transformer):
        nr = {
            "name": "Health Check",
            "monitorType": "SIMPLE",
            "monitoredUrl": "https://example.com",
            "period": "EVERY_5_MINUTES",
            "status": "ENABLED",
        }
        result = synthetic_transformer.transform(nr)
        assert result.success is True
        assert result.monitor_type == "HTTP"
        monitor = result.monitor
        assert monitor["name"] == "[Migrated] Health Check"
        assert monitor["frequencyMin"] == 5
        assert monitor["enabled"] is True
        assert monitor["type"] == "HTTP"
        assert monitor["script"]["requests"][0]["url"] == "https://example.com"

    def test_should_transform_script_api_with_warning(self, synthetic_transformer):
        nr = {
            "name": "API Test",
            "monitorType": "SCRIPT_API",
            "monitoredUrl": "https://api.example.com",
            "period": "EVERY_15_MINUTES",
            "status": "ENABLED",
        }
        result = synthetic_transformer.transform(nr)
        assert result.success is True
        assert result.monitor_type == "HTTP"
        assert any("scripted API" in w for w in result.warnings)

    def test_should_disable_when_status_not_enabled(self, synthetic_transformer):
        nr = {
            "name": "Disabled",
            "monitorType": "SIMPLE",
            "monitoredUrl": "https://example.com",
            "period": "EVERY_HOUR",
            "status": "DISABLED",
        }
        result = synthetic_transformer.transform(nr)
        assert result.monitor["enabled"] is False


class TestSyntheticTransformBrowser:
    def test_should_transform_browser_monitor(self, synthetic_transformer):
        nr = {
            "name": "Browser Test",
            "monitorType": "BROWSER",
            "monitoredUrl": "https://example.com",
            "period": "EVERY_10_MINUTES",
            "status": "ENABLED",
        }
        result = synthetic_transformer.transform(nr)
        assert result.success is True
        assert result.monitor_type == "BROWSER"
        assert result.monitor["type"] == "BROWSER"
        assert result.monitor["frequencyMin"] == 10
        script = result.monitor["script"]
        assert script["type"] == "clickpath"
        assert script["events"][0]["url"] == "https://example.com"

    def test_should_add_warning_for_scripted_browser(self, synthetic_transformer):
        nr = {
            "name": "Scripted",
            "monitorType": "SCRIPT_BROWSER",
            "monitoredUrl": "https://example.com",
            "period": "EVERY_15_MINUTES",
            "status": "ENABLED",
        }
        result = synthetic_transformer.transform(nr)
        assert result.success is True
        assert result.monitor_type == "BROWSER"
        assert any("scripted" in w.lower() for w in result.warnings)


class TestSyntheticTransformAll:
    def test_should_transform_multiple_monitors(self, synthetic_transformer):
        monitors = [
            {"name": "M1", "monitorType": "SIMPLE", "monitoredUrl": "https://a.com", "period": "EVERY_MINUTE", "status": "ENABLED"},
            {"name": "M2", "monitorType": "BROWSER", "monitoredUrl": "https://b.com", "period": "EVERY_HOUR", "status": "ENABLED"},
        ]
        results = synthetic_transformer.transform_all(monitors)
        assert len(results) == 2
        types = {r.monitor_type for r in results}
        assert "HTTP" in types
        assert "BROWSER" in types


class TestSyntheticTransformCustomLocations:
    def test_should_use_provided_locations(self):
        locations = ["LOC-1", "LOC-2"]
        transformer = SyntheticTransformer(available_locations=locations)
        nr = {
            "name": "Test",
            "monitorType": "SIMPLE",
            "monitoredUrl": "https://example.com",
            "period": "EVERY_15_MINUTES",
            "status": "ENABLED",
        }
        result = transformer.transform(nr)
        assert result.monitor["locations"] == locations


# ─── SyntheticScriptConverter ────────────────────────────────────────────────


class TestSyntheticScriptConverter:
    def test_should_analyze_simple_script(self):
        analysis = SyntheticScriptConverter.analyze_script('$browser.get("https://example.com")')
        assert analysis["has_navigation"] is True
        assert analysis["complexity"] == "simple"

    def test_should_detect_clicks(self):
        analysis = SyntheticScriptConverter.analyze_script('element.click()')
        assert analysis["has_clicks"] is True

    def test_should_detect_form_input(self):
        analysis = SyntheticScriptConverter.analyze_script('element.sendKeys("hello")')
        assert analysis["has_form_input"] is True

    def test_should_detect_assertions(self):
        analysis = SyntheticScriptConverter.analyze_script('assert(title === "Home")')
        assert analysis["has_assertions"] is True

    def test_should_detect_custom_logic(self):
        analysis = SyntheticScriptConverter.analyze_script('async function test() {}')
        assert analysis["has_custom_logic"] is True

    def test_should_rate_complex_script_as_high_effort(self):
        script = """
        $browser.get("https://example.com")
        element.click()
        input.sendKeys("test")
        assert(result === true)
        async function validate() {}
        """
        analysis = SyntheticScriptConverter.analyze_script(script)
        assert analysis["complexity"] == "complex"
        assert analysis["estimated_effort"] == "high"

    def test_should_handle_empty_script(self):
        analysis = SyntheticScriptConverter.analyze_script("")
        assert analysis["complexity"] == "simple"
        assert analysis["estimated_effort"] == "low"

    def test_should_provide_recommendations(self):
        analysis = SyntheticScriptConverter.analyze_script(
            '$browser.get("url")\nelement.click()'
        )
        assert len(analysis["recommendations"]) >= 2


# ═════════════════════════════════════════════════════════════════════════════
# SLOTransformer
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def slo_transformer():
    return SLOTransformer()


class TestSLOTransformResult:
    def test_should_default_lists(self):
        r = SLOTransformResult(success=True)
        assert r.warnings == []
        assert r.errors == []


class TestSLOTransform:
    def test_should_transform_basic_slo(self, slo_transformer):
        nr_slo = {
            "name": "Availability SLO",
            "description": "99.9% uptime",
            "objectives": [
                {
                    "target": 99.9,
                    "timeWindow": {"rolling": {"count": 7, "unit": "DAY"}},
                }
            ],
            "events": {
                "validEvents": {"where": "status = 200"},
                "goodEvents": {"where": "status = 200"},
            },
        }
        result = slo_transformer.transform(nr_slo)
        assert result.success is True
        slo = result.slo
        assert slo["name"] == "[Migrated] Availability SLO"
        assert slo["target"] == 99.9
        assert slo["warning"] == 98.9  # target - 1.0
        assert slo["enabled"] is True
        assert slo["timeframe"] == "-7d"

    def test_should_fail_when_no_objectives(self, slo_transformer):
        nr_slo = {"name": "Bad SLO", "objectives": []}
        result = slo_transformer.transform(nr_slo)
        assert result.success is False

    def test_should_detect_error_rate_type(self, slo_transformer):
        slo_type = slo_transformer._detect_slo_type("", "error count > 0")
        assert slo_type == "error_rate"

    def test_should_detect_latency_type(self, slo_transformer):
        slo_type = slo_transformer._detect_slo_type("", "duration < 500")
        assert slo_type == "latency"

    def test_should_detect_availability_type(self, slo_transformer):
        slo_type = slo_transformer._detect_slo_type("status = 200", "")
        assert slo_type == "availability"

    def test_should_default_to_unknown(self, slo_transformer):
        slo_type = slo_transformer._detect_slo_type("", "")
        assert slo_type == "unknown"


class TestSLOSanitizeMetricName:
    def test_should_sanitize_name(self, slo_transformer):
        result = slo_transformer._sanitize_metric_name("My SLO Test!")
        assert result == "slo.migrated.my_slo_test"

    def test_should_handle_special_chars(self, slo_transformer):
        result = slo_transformer._sanitize_metric_name("SLO (prod) - v2")
        assert result == "slo.migrated.slo_prod__v2"


class TestSLOBuildTimeframe:
    def test_should_build_day_timeframe(self, slo_transformer):
        assert slo_transformer._build_timeframe(7, "DAY") == "-7d"

    def test_should_build_week_timeframe(self, slo_transformer):
        assert slo_transformer._build_timeframe(4, "WEEK") == "-4w"

    def test_should_build_month_timeframe(self, slo_transformer):
        assert slo_transformer._build_timeframe(1, "MONTH") == "-1M"


class TestSLOTransformAll:
    def test_should_transform_multiple_slos(self, slo_transformer):
        slos = [
            {
                "name": "SLO1",
                "objectives": [{"target": 99.0, "timeWindow": {"rolling": {"count": 7, "unit": "DAY"}}}],
                "events": {"validEvents": {"where": ""}, "goodEvents": {"where": ""}},
            },
            {
                "name": "SLO2",
                "objectives": [{"target": 95.0, "timeWindow": {"rolling": {"count": 30, "unit": "DAY"}}}],
                "events": {"validEvents": {"where": ""}, "goodEvents": {"where": ""}},
            },
        ]
        results = slo_transformer.transform_all(slos)
        assert len(results) == 2
        assert all(r.success for r in results)


# ═════════════════════════════════════════════════════════════════════════════
# WorkloadTransformer
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def workload_transformer():
    return WorkloadTransformer()


class TestWorkloadTransformResult:
    def test_should_default_lists(self):
        r = WorkloadTransformResult(success=True)
        assert r.warnings == []
        assert r.errors == []


class TestWorkloadTransform:
    def test_should_transform_workload_with_collection(self, workload_transformer):
        nr = {
            "name": "Production Services",
            "collection": [
                {"name": "web-app", "type": "APPLICATION"},
                {"name": "api-server", "type": "APM_APPLICATION"},
            ],
        }
        result = workload_transformer.transform(nr)
        assert result.success is True
        mz = result.management_zone
        assert mz["name"] == "[Migrated] Production Services"
        assert len(mz["rules"]) == 2

    def test_should_create_tag_rule_when_no_entities(self, workload_transformer):
        nr = {"name": "Empty Workload", "collection": [], "entitySearchQueries": []}
        result = workload_transformer.transform(nr)
        assert result.success is True
        assert len(result.management_zone["rules"]) == 1  # tag-based fallback
        assert "tag(" in result.management_zone["rules"][0]["entitySelector"]

    def test_should_handle_unmapped_entity_types(self, workload_transformer):
        nr = {
            "name": "Mixed",
            "collection": [
                {"name": "dash-1", "type": "DASHBOARD"},  # No DT equivalent
            ],
        }
        result = workload_transformer.transform(nr)
        assert result.success is True
        assert len(result.warnings) > 0


class TestWorkloadTransformEntitySearchQueries:
    def test_should_convert_type_query(self, workload_transformer):
        nr = {
            "name": "Apps",
            "entitySearchQueries": [
                {"query": "type = 'APPLICATION'"}
            ],
        }
        result = workload_transformer.transform(nr)
        assert result.success is True
        rules = result.management_zone["rules"]
        assert len(rules) >= 1
        assert "SERVICE" in rules[0]["entitySelector"]

    def test_should_convert_name_like_query(self, workload_transformer):
        nr = {
            "name": "Prod",
            "entitySearchQueries": [
                {"query": "type = 'APPLICATION' AND name LIKE 'production%'"}
            ],
        }
        result = workload_transformer.transform(nr)
        assert result.success is True
        rules = result.management_zone["rules"]
        assert any("entityName.contains" in r["entitySelector"] for r in rules)

    def test_should_convert_tag_query(self, workload_transformer):
        nr = {
            "name": "Tagged",
            "entitySearchQueries": [
                {"query": "type = 'HOST' AND tags.environment = 'production'"}
            ],
        }
        result = workload_transformer.transform(nr)
        assert result.success is True
        rules = result.management_zone["rules"]
        assert any("tag(" in r["entitySelector"] for r in rules)


class TestWorkloadParseEntityQuery:
    def test_should_extract_entity_type(self, workload_transformer):
        parsed = workload_transformer._parse_entity_query("type = 'APPLICATION'")
        assert parsed["entity_type"] == "APPLICATION"

    def test_should_extract_host_type(self, workload_transformer):
        parsed = workload_transformer._parse_entity_query("type = 'HOST'")
        assert parsed["entity_type"] == "HOST"

    def test_should_extract_name_filter(self, workload_transformer):
        parsed = workload_transformer._parse_entity_query("name LIKE 'prod%'")
        assert parsed["name_filter"] == "prod"

    def test_should_extract_tags(self, workload_transformer):
        parsed = workload_transformer._parse_entity_query("tags.env = 'prod'")
        assert ("env", "prod") in parsed["tags"]


class TestWorkloadCreateRules:
    def test_should_create_name_rule(self, workload_transformer):
        rule = workload_transformer._create_name_rule("SERVICE", "my-app")
        assert rule["type"] == "ME"
        assert rule["enabled"] is True
        assert 'entityName.equals("my-app")' in rule["entitySelector"]

    def test_should_create_tag_rule(self, workload_transformer):
        rule = workload_transformer._create_tag_rule("My Workload")
        assert 'tag("migrated-workload:my-workload")' in rule["entitySelector"]

    def test_should_sanitize_tag_value(self, workload_transformer):
        rule = workload_transformer._create_tag_rule("Special (chars) here!")
        selector = rule["entitySelector"]
        assert "(" not in selector.split("tag(")[1].split(")")[0].replace("migrated-workload:", "")


class TestWorkloadTransformAll:
    def test_should_transform_multiple_workloads(self, workload_transformer):
        workloads = [
            {"name": "W1", "collection": [{"name": "app1", "type": "APPLICATION"}]},
            {"name": "W2", "collection": [{"name": "host1", "type": "HOST"}]},
        ]
        results = workload_transformer.transform_all(workloads)
        assert len(results) == 2
        assert all(r.success for r in results)
