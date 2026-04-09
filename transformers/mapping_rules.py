"""
Entity mapping rules between New Relic and Dynatrace.

This module defines the comprehensive mapping between New Relic concepts
and their Dynatrace equivalents, including field mappings, value transformations,
and default values.
"""

from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum


class TransformationType(Enum):
    """Types of transformations that can be applied."""
    DIRECT = "direct"           # Direct value copy
    MAPPED = "mapped"           # Value mapping through a lookup
    COMPUTED = "computed"       # Computed/calculated value
    TEMPLATE = "template"       # Template-based transformation
    CUSTOM = "custom"           # Custom function transformation


@dataclass
class FieldMapping:
    """Defines how a single field is mapped between systems."""
    source_field: str
    target_field: str
    transformation: TransformationType = TransformationType.DIRECT
    value_map: Optional[Dict[str, Any]] = None
    default_value: Any = None
    transform_func: Optional[Callable] = None
    required: bool = False


@dataclass
class EntityMapping:
    """Defines complete mapping for an entity type."""
    source_type: str
    target_type: str
    field_mappings: List[FieldMapping] = field(default_factory=list)
    pre_transform_func: Optional[Callable] = None
    post_transform_func: Optional[Callable] = None


# =============================================================================
# Value Mappings
# =============================================================================

# New Relic visualization type to Dynatrace tile type
VISUALIZATION_TYPE_MAP = {
    "viz.line": "DATA_EXPLORER",
    "viz.area": "DATA_EXPLORER",
    "viz.bar": "DATA_EXPLORER",
    "viz.billboard": "SINGLE_VALUE",
    "viz.pie": "DATA_EXPLORER",
    "viz.table": "DATA_EXPLORER",
    "viz.markdown": "MARKDOWN",
    "viz.json": "DATA_EXPLORER",
    "viz.bullet": "DATA_EXPLORER",
    "viz.funnel": "DATA_EXPLORER",
    "viz.heatmap": "DATA_EXPLORER",
    "viz.histogram": "DATA_EXPLORER",
    "viz.stacked-bar": "DATA_EXPLORER",
    "viz.scatter": "DATA_EXPLORER",
}

# New Relic chart type to Dynatrace chart config
CHART_TYPE_MAP = {
    "LINE": "LINE",
    "AREA": "AREA",
    "STACKED_AREA": "AREA",
    "BAR": "BAR",
    "STACKED_BAR": "COLUMN",
    "PIE": "PIE",
}

# New Relic alert priority to Dynatrace severity
ALERT_PRIORITY_MAP = {
    "critical": "ERROR",
    "warning": "WARN",
    "info": "WARN",
}

# New Relic operator to Dynatrace comparison
OPERATOR_MAP = {
    "ABOVE": "ABOVE",
    "BELOW": "BELOW",
    "EQUALS": "EQUALS",
    "ABOVE_OR_EQUALS": "ABOVE_OR_EQUAL",
    "BELOW_OR_EQUALS": "BELOW_OR_EQUAL",
}

# New Relic threshold occurrences to Dynatrace violation settings
THRESHOLD_OCCURRENCES_MAP = {
    "ALL": "ALL",
    "AT_LEAST_ONCE": "AT_LEAST_ONCE",
}

# New Relic synthetic monitor type to Dynatrace monitor type
SYNTHETIC_MONITOR_TYPE_MAP = {
    "SIMPLE": "HTTP",           # Ping/simple monitors
    "BROWSER": "BROWSER",       # Browser scripted monitors
    "SCRIPT_BROWSER": "BROWSER",
    "SCRIPT_API": "HTTP",       # API scripted monitors
    "CERT_CHECK": "HTTP",       # Certificate check
    "BROKEN_LINKS": "HTTP",     # Broken links monitor
}

# New Relic monitor period to Dynatrace frequency (in minutes)
MONITOR_PERIOD_MAP = {
    "EVERY_MINUTE": 1,
    "EVERY_5_MINUTES": 5,
    "EVERY_10_MINUTES": 10,
    "EVERY_15_MINUTES": 15,
    "EVERY_30_MINUTES": 30,
    "EVERY_HOUR": 60,
    "EVERY_6_HOURS": 360,
    "EVERY_12_HOURS": 720,
    "EVERY_DAY": 1440,
}

# New Relic notification channel type to Dynatrace integration type
NOTIFICATION_TYPE_MAP = {
    "EMAIL": "email",
    "SLACK": "slack",
    "PAGERDUTY": "pagerduty",
    "WEBHOOK": "webhook",
    "JIRA": "jira",
    "SERVICENOW": "servicenow",
    "OPSGENIE": "opsgenie",
    "VICTOROPS": "victorops",
}

# New Relic aggregation method to Dynatrace aggregation
AGGREGATION_MAP = {
    "EVENT_FLOW": "AVG",
    "EVENT_TIMER": "AVG",
    "CADENCE": "AVG",
}

# New Relic fill option to Dynatrace deal with gaps
FILL_OPTION_MAP = {
    "NONE": "DROP_DATA",
    "STATIC": "USE_VALUE",
    "LAST_VALUE": "USE_LAST_VALUE",
}

# SLO time window unit mapping
SLO_TIME_UNIT_MAP = {
    "DAY": "DAY",
    "WEEK": "WEEK",
    "MONTH": "MONTH",
}


# =============================================================================
# Entity Mapper Class
# =============================================================================

class EntityMapper:
    """
    Handles mapping of entities between New Relic and Dynatrace.

    This class provides methods to transform New Relic configurations
    into Dynatrace-compatible formats using defined mapping rules.
    """

    def __init__(self):
        self.mappings: Dict[str, EntityMapping] = {}
        self._register_default_mappings()

    def _register_default_mappings(self):
        """Register all default entity mappings."""
        # Dashboard mapping
        self.register_mapping(EntityMapping(
            source_type="dashboard",
            target_type="dashboard",
            field_mappings=[
                FieldMapping(
                    source_field="name",
                    target_field="dashboardMetadata.name",
                    required=True
                ),
                FieldMapping(
                    source_field="description",
                    target_field="dashboardMetadata.description",
                    default_value=""
                ),
                FieldMapping(
                    source_field="permissions",
                    target_field="dashboardMetadata.shared",
                    transformation=TransformationType.MAPPED,
                    value_map={
                        "PUBLIC_READ_ONLY": True,
                        "PUBLIC_READ_WRITE": True,
                        "PRIVATE": False
                    },
                    default_value=False
                ),
            ]
        ))

        # Alert policy mapping
        self.register_mapping(EntityMapping(
            source_type="alert_policy",
            target_type="alerting_profile",
            field_mappings=[
                FieldMapping(
                    source_field="name",
                    target_field="name",
                    required=True
                ),
                FieldMapping(
                    source_field="incidentPreference",
                    target_field="severityRules",
                    transformation=TransformationType.CUSTOM
                ),
            ]
        ))

        # Alert condition mapping
        self.register_mapping(EntityMapping(
            source_type="alert_condition",
            target_type="metric_event",
            field_mappings=[
                FieldMapping(
                    source_field="name",
                    target_field="summary",
                    required=True
                ),
                FieldMapping(
                    source_field="description",
                    target_field="description",
                    default_value=""
                ),
                FieldMapping(
                    source_field="enabled",
                    target_field="enabled",
                    default_value=True
                ),
            ]
        ))

        # Synthetic monitor mapping
        self.register_mapping(EntityMapping(
            source_type="synthetic_monitor",
            target_type="synthetic_monitor",
            field_mappings=[
                FieldMapping(
                    source_field="name",
                    target_field="name",
                    required=True
                ),
                FieldMapping(
                    source_field="monitoredUrl",
                    target_field="script.requests[0].url",
                    required=True
                ),
                FieldMapping(
                    source_field="monitorType",
                    target_field="type",
                    transformation=TransformationType.MAPPED,
                    value_map=SYNTHETIC_MONITOR_TYPE_MAP,
                    default_value="HTTP"
                ),
                FieldMapping(
                    source_field="period",
                    target_field="frequencyMin",
                    transformation=TransformationType.MAPPED,
                    value_map=MONITOR_PERIOD_MAP,
                    default_value=15
                ),
            ]
        ))

        # SLO mapping
        self.register_mapping(EntityMapping(
            source_type="slo",
            target_type="slo",
            field_mappings=[
                FieldMapping(
                    source_field="name",
                    target_field="name",
                    required=True
                ),
                FieldMapping(
                    source_field="description",
                    target_field="description",
                    default_value=""
                ),
                FieldMapping(
                    source_field="objectives[0].target",
                    target_field="target",
                    required=True
                ),
            ]
        ))

        # Workload to Management Zone mapping
        self.register_mapping(EntityMapping(
            source_type="workload",
            target_type="management_zone",
            field_mappings=[
                FieldMapping(
                    source_field="name",
                    target_field="name",
                    required=True
                ),
            ]
        ))

    def register_mapping(self, mapping: EntityMapping):
        """Register an entity mapping."""
        self.mappings[mapping.source_type] = mapping

    def get_mapping(self, source_type: str) -> Optional[EntityMapping]:
        """Get mapping for a source entity type."""
        return self.mappings.get(source_type)

    def map_value(
        self,
        value: Any,
        value_map: Dict[str, Any],
        default: Any = None
    ) -> Any:
        """Map a value through a lookup dictionary."""
        if value is None:
            return default
        return value_map.get(value, default if default is not None else value)

    def get_nested_value(self, obj: Dict, path: str) -> Any:
        """Get a value from a nested dictionary using dot notation."""
        keys = path.split(".")
        current = obj

        for key in keys:
            # Handle array notation like "items[0]"
            if "[" in key:
                key_name = key.split("[")[0]
                index = int(key.split("[")[1].rstrip("]"))
                if isinstance(current, dict) and key_name in current:
                    current = current[key_name]
                    if isinstance(current, list) and len(current) > index:
                        current = current[index]
                    else:
                        return None
                else:
                    return None
            else:
                if isinstance(current, dict) and key in current:
                    current = current[key]
                else:
                    return None

        return current

    def set_nested_value(self, obj: Dict, path: str, value: Any):
        """Set a value in a nested dictionary using dot notation."""
        keys = path.split(".")
        current = obj

        for i, key in enumerate(keys[:-1]):
            # Handle array notation
            if "[" in key:
                key_name = key.split("[")[0]
                index = int(key.split("[")[1].rstrip("]"))

                if key_name not in current:
                    current[key_name] = []
                while len(current[key_name]) <= index:
                    current[key_name].append({})
                current = current[key_name][index]
            else:
                if key not in current:
                    current[key] = {}
                current = current[key]

        # Set the final value
        final_key = keys[-1]
        if "[" in final_key:
            key_name = final_key.split("[")[0]
            index = int(final_key.split("[")[1].rstrip("]"))
            if key_name not in current:
                current[key_name] = []
            while len(current[key_name]) <= index:
                current[key_name].append(None)
            current[key_name][index] = value
        else:
            current[final_key] = value


# =============================================================================
# Comprehensive Entity Mappings Export
# =============================================================================

ENTITY_MAPPINGS = {
    "visualization_types": VISUALIZATION_TYPE_MAP,
    "chart_types": CHART_TYPE_MAP,
    "alert_priorities": ALERT_PRIORITY_MAP,
    "operators": OPERATOR_MAP,
    "threshold_occurrences": THRESHOLD_OCCURRENCES_MAP,
    "synthetic_monitor_types": SYNTHETIC_MONITOR_TYPE_MAP,
    "monitor_periods": MONITOR_PERIOD_MAP,
    "notification_types": NOTIFICATION_TYPE_MAP,
    "aggregations": AGGREGATION_MAP,
    "fill_options": FILL_OPTION_MAP,
    "slo_time_units": SLO_TIME_UNIT_MAP,
}
