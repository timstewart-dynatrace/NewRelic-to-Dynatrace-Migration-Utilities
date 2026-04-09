"""Tests for transformers/mapping_rules.py — EntityMapper and value mappings."""

import pytest

from transformers.mapping_rules import (
    EntityMapper,
    TransformationType,
    FieldMapping,
    EntityMapping,
    VISUALIZATION_TYPE_MAP,
    CHART_TYPE_MAP,
    ALERT_PRIORITY_MAP,
    OPERATOR_MAP,
    SYNTHETIC_MONITOR_TYPE_MAP,
    MONITOR_PERIOD_MAP,
    NOTIFICATION_TYPE_MAP,
    AGGREGATION_MAP,
    FILL_OPTION_MAP,
    SLO_TIME_UNIT_MAP,
    THRESHOLD_OCCURRENCES_MAP,
    ENTITY_MAPPINGS,
)


# ─── Mapping dictionaries ───────────────────────────────────────────────────


class TestVisualizationTypeMap:
    def test_should_map_line_to_data_explorer(self):
        assert VISUALIZATION_TYPE_MAP["viz.line"] == "DATA_EXPLORER"

    def test_should_map_billboard_to_single_value(self):
        assert VISUALIZATION_TYPE_MAP["viz.billboard"] == "SINGLE_VALUE"

    def test_should_map_markdown(self):
        assert VISUALIZATION_TYPE_MAP["viz.markdown"] == "MARKDOWN"

    def test_should_map_all_chart_types(self):
        expected_types = {"DATA_EXPLORER", "SINGLE_VALUE", "MARKDOWN"}
        assert set(VISUALIZATION_TYPE_MAP.values()).issubset(expected_types)


class TestChartTypeMap:
    def test_should_map_line(self):
        assert CHART_TYPE_MAP["LINE"] == "LINE"

    def test_should_map_stacked_bar_to_column(self):
        assert CHART_TYPE_MAP["STACKED_BAR"] == "COLUMN"


class TestAlertPriorityMap:
    def test_should_map_critical_to_error(self):
        assert ALERT_PRIORITY_MAP["critical"] == "ERROR"

    def test_should_map_warning_to_warn(self):
        assert ALERT_PRIORITY_MAP["warning"] == "WARN"


class TestOperatorMap:
    def test_should_map_above(self):
        assert OPERATOR_MAP["ABOVE"] == "ABOVE"

    def test_should_map_below(self):
        assert OPERATOR_MAP["BELOW"] == "BELOW"

    def test_should_map_above_or_equals(self):
        assert OPERATOR_MAP["ABOVE_OR_EQUALS"] == "ABOVE_OR_EQUAL"


class TestSyntheticMonitorTypeMap:
    def test_should_map_simple_to_http(self):
        assert SYNTHETIC_MONITOR_TYPE_MAP["SIMPLE"] == "HTTP"

    def test_should_map_browser(self):
        assert SYNTHETIC_MONITOR_TYPE_MAP["BROWSER"] == "BROWSER"

    def test_should_map_script_api_to_http(self):
        assert SYNTHETIC_MONITOR_TYPE_MAP["SCRIPT_API"] == "HTTP"


class TestMonitorPeriodMap:
    def test_should_map_every_minute(self):
        assert MONITOR_PERIOD_MAP["EVERY_MINUTE"] == 1

    def test_should_map_every_hour(self):
        assert MONITOR_PERIOD_MAP["EVERY_HOUR"] == 60

    def test_should_map_every_day(self):
        assert MONITOR_PERIOD_MAP["EVERY_DAY"] == 1440


class TestNotificationTypeMap:
    def test_should_map_email(self):
        assert NOTIFICATION_TYPE_MAP["EMAIL"] == "email"

    def test_should_map_slack(self):
        assert NOTIFICATION_TYPE_MAP["SLACK"] == "slack"

    def test_should_map_pagerduty(self):
        assert NOTIFICATION_TYPE_MAP["PAGERDUTY"] == "pagerduty"


class TestEntityMappingsExport:
    def test_should_contain_all_mapping_categories(self):
        expected = {
            "visualization_types", "chart_types", "alert_priorities",
            "operators", "threshold_occurrences", "synthetic_monitor_types",
            "monitor_periods", "notification_types", "aggregations",
            "fill_options", "slo_time_units",
        }
        assert set(ENTITY_MAPPINGS.keys()) == expected


# ─── EntityMapper ────────────────────────────────────────────────────────────


@pytest.fixture
def mapper():
    return EntityMapper()


class TestEntityMapperInit:
    def test_should_register_default_mappings(self, mapper):
        assert mapper.get_mapping("dashboard") is not None
        assert mapper.get_mapping("alert_policy") is not None
        assert mapper.get_mapping("alert_condition") is not None
        assert mapper.get_mapping("synthetic_monitor") is not None
        assert mapper.get_mapping("slo") is not None
        assert mapper.get_mapping("workload") is not None

    def test_should_return_none_for_unknown_type(self, mapper):
        assert mapper.get_mapping("nonexistent") is None


class TestEntityMapperRegister:
    def test_should_register_custom_mapping(self, mapper):
        custom = EntityMapping(source_type="custom", target_type="target")
        mapper.register_mapping(custom)
        assert mapper.get_mapping("custom") is not None
        assert mapper.get_mapping("custom").target_type == "target"

    def test_should_override_existing_mapping(self, mapper):
        custom = EntityMapping(source_type="dashboard", target_type="new_type")
        mapper.register_mapping(custom)
        assert mapper.get_mapping("dashboard").target_type == "new_type"


class TestEntityMapperMapValue:
    def test_should_map_known_value(self, mapper):
        result = mapper.map_value("PUBLIC_READ_ONLY", {"PUBLIC_READ_ONLY": True}, False)
        assert result is True

    def test_should_return_default_for_unknown_value(self, mapper):
        result = mapper.map_value("UNKNOWN", {"A": 1}, 42)
        assert result == 42

    def test_should_return_none_value_as_default(self, mapper):
        result = mapper.map_value(None, {"A": 1}, "default")
        assert result == "default"

    def test_should_return_original_when_no_default(self, mapper):
        result = mapper.map_value("UNKNOWN", {"A": 1})
        assert result == "UNKNOWN"


class TestEntityMapperGetNestedValue:
    def test_should_get_simple_key(self, mapper):
        obj = {"name": "test"}
        assert mapper.get_nested_value(obj, "name") == "test"

    def test_should_get_nested_key(self, mapper):
        obj = {"level1": {"level2": "value"}}
        assert mapper.get_nested_value(obj, "level1.level2") == "value"

    def test_should_get_array_index(self, mapper):
        obj = {"items": ["a", "b", "c"]}
        assert mapper.get_nested_value(obj, "items[1]") == "b"

    def test_should_get_nested_array(self, mapper):
        obj = {"items": [{"name": "first"}, {"name": "second"}]}
        assert mapper.get_nested_value(obj, "items[0].name") == "first"

    def test_should_return_none_for_missing_key(self, mapper):
        obj = {"name": "test"}
        assert mapper.get_nested_value(obj, "missing") is None

    def test_should_return_none_for_missing_nested_key(self, mapper):
        obj = {"level1": {}}
        assert mapper.get_nested_value(obj, "level1.level2") is None

    def test_should_return_none_for_out_of_bounds_index(self, mapper):
        obj = {"items": ["a"]}
        assert mapper.get_nested_value(obj, "items[5]") is None


class TestEntityMapperSetNestedValue:
    def test_should_set_simple_key(self, mapper):
        obj = {}
        mapper.set_nested_value(obj, "name", "test")
        assert obj["name"] == "test"

    def test_should_set_nested_key(self, mapper):
        obj = {}
        mapper.set_nested_value(obj, "level1.level2", "value")
        assert obj["level1"]["level2"] == "value"

    def test_should_create_intermediate_dicts(self, mapper):
        obj = {}
        mapper.set_nested_value(obj, "a.b.c", "deep")
        assert obj["a"]["b"]["c"] == "deep"

    def test_should_set_array_value(self, mapper):
        obj = {}
        mapper.set_nested_value(obj, "items[0]", "first")
        assert obj["items"][0] == "first"

    def test_should_set_nested_array_value(self, mapper):
        obj = {}
        mapper.set_nested_value(obj, "items[0].name", "test")
        assert obj["items"][0]["name"] == "test"

    def test_should_extend_array_if_needed(self, mapper):
        obj = {"items": []}
        mapper.set_nested_value(obj, "items[2]", "third")
        assert len(obj["items"]) == 3
        assert obj["items"][2] == "third"


class TestThresholdOccurrencesMap:
    def test_should_map_all(self):
        assert THRESHOLD_OCCURRENCES_MAP["ALL"] == "ALL"

    def test_should_map_at_least_once(self):
        assert THRESHOLD_OCCURRENCES_MAP["AT_LEAST_ONCE"] == "AT_LEAST_ONCE"


class TestFillOptionMap:
    def test_should_map_none(self):
        assert FILL_OPTION_MAP["NONE"] == "DROP_DATA"

    def test_should_map_last_value(self):
        assert FILL_OPTION_MAP["LAST_VALUE"] == "USE_LAST_VALUE"


class TestSLOTimeUnitMap:
    def test_should_map_day(self):
        assert SLO_TIME_UNIT_MAP["DAY"] == "DAY"

    def test_should_map_month(self):
        assert SLO_TIME_UNIT_MAP["MONTH"] == "MONTH"


class TestDefaultMappingFields:
    def test_dashboard_mapping_has_required_name(self, mapper):
        mapping = mapper.get_mapping("dashboard")
        name_field = next(
            f for f in mapping.field_mappings if f.source_field == "name"
        )
        assert name_field.required is True

    def test_slo_mapping_has_target_field(self, mapper):
        mapping = mapper.get_mapping("slo")
        target_field = next(
            f for f in mapping.field_mappings if f.source_field == "objectives[0].target"
        )
        assert target_field.required is True

    def test_alert_condition_mapping_has_name(self, mapper):
        mapping = mapper.get_mapping("alert_condition")
        name_field = next(
            f for f in mapping.field_mappings if f.source_field == "name"
        )
        assert name_field.target_field == "summary"
