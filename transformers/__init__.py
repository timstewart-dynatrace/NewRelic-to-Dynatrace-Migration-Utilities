"""Transformer modules for converting New Relic entities to Dynatrace format."""

from .ai_monitoring_transformer import AIMonitoringTransformer
from .aiops_transformer import AIOpsTransformer
from .alert_transformer import AlertTransformer
from .baseline_alert_transformer import BaselineAlertTransformer
from .browser_rum_transformer import BrowserRUMTransformer
from .change_tracking_transformer import ChangeTrackingTransformer
from .cloud_integration_transformer import CloudIntegrationTransformer
from .cloudwatch_metric_streams_transformer import (
    CloudWatchMetricStreamsTransformer,
)
from .custom_entity_transformer import CustomEntityTransformer
from .custom_event_ingest_transformer import CustomEventIngestTransformer
from .custom_instrumentation_translator import CustomInstrumentationTranslator
from .dashboard_transformer import DashboardTransformer
from .database_monitoring_transformer import DatabaseMonitoringTransformer
from .drop_rule_transformer import DropRuleTransformer
from .identity_transformer import IdentityTransformer
from .infrastructure_transformer import InfrastructureTransformer
from .key_transaction_transformer import KeyTransactionTransformer
from .kubernetes_transformer import KubernetesTransformer
from .lambda_transformer import LambdaTransformer
from .log_archive_transformer import LogArchiveTransformer
from .log_obfuscation_transformer import LogObfuscationTransformer
from .log_parsing_transformer import LogParsingTransformer
from .lookup_table_transformer import LookupTableTransformer
from .maintenance_window_transformer import MaintenanceWindowTransformer
from .mapping_rules import ENTITY_MAPPINGS, EntityMapper
from .metric_normalization_transformer import MetricNormalizationTransformer
from .metric_transform import MetricTransform, MetricTransformRegistry
from .mobile_rum_transformer import MobileRUMTransformer
from .non_nrql_alert_transformer import NonNRQLAlertTransformer
from .npm_transformer import NPMTransformer
from .nrql_converter import NRQLtoDQLConverter
from .on_host_integration_transformer import OnHostIntegrationTransformer
from .otel_collector_transformer import OTelCollectorTransformer
from .otel_metrics_transformer import OTelMetricsTransformer
from .prometheus_transformer import PrometheusTransformer
from .saved_filter_notebook_transformer import SavedFilterNotebookTransformer
from .security_signals_transformer import SecuritySignalsTransformer
from .slo_transformer import SLOTransformer
from .statsd_transformer import StatsDTransformer
from .synthetic_specialized_transformer import SyntheticSpecializedTransformer
from .synthetic_transformer import SyntheticTransformer
from .tag_transformer import TagTransformer
from .vulnerability_transformer import VulnerabilityTransformer
from .workload_transformer import WorkloadTransformer

__all__ = [
    "EntityMapper",
    "ENTITY_MAPPINGS",
    "DashboardTransformer",
    "AlertTransformer",
    "SyntheticTransformer",
    "SLOTransformer",
    "WorkloadTransformer",
    "InfrastructureTransformer",
    "LogParsingTransformer",
    "TagTransformer",
    "DropRuleTransformer",
    "BrowserRUMTransformer",
    "MobileRUMTransformer",
    "LambdaTransformer",
    "CustomInstrumentationTranslator",
    "NonNRQLAlertTransformer",
    "BaselineAlertTransformer",
    "LookupTableTransformer",
    "MaintenanceWindowTransformer",
    "ChangeTrackingTransformer",
    "CustomEventIngestTransformer",
    "IdentityTransformer",
    "LogObfuscationTransformer",
    "CloudIntegrationTransformer",
    "KubernetesTransformer",
    "AIOpsTransformer",
    "VulnerabilityTransformer",
    "NPMTransformer",
    "AIMonitoringTransformer",
    "PrometheusTransformer",
    "KeyTransactionTransformer",
    "OTelMetricsTransformer",
    "StatsDTransformer",
    "CloudWatchMetricStreamsTransformer",
    "MetricTransform",
    "MetricTransformRegistry",
    "DatabaseMonitoringTransformer",
    "OnHostIntegrationTransformer",
    "SecuritySignalsTransformer",
    "CustomEntityTransformer",
    "LogArchiveTransformer",
    "MetricNormalizationTransformer",
    "SyntheticSpecializedTransformer",
    "SavedFilterNotebookTransformer",
    "OTelCollectorTransformer",
    # Alias for TS-parity: nrql-engine calls this CustomEventTransformer;
    # Python named it CustomEventIngestTransformer in Phase 17. Both work.
    "CustomEventTransformer",
    "NRQLtoDQLConverter",
]

# Naming alias — TS sibling uses `CustomEventTransformer`; Python's
# Phase-17 name was `CustomEventIngestTransformer`. Keep both pointing
# at the same implementation so code written against either name
# continues to work.
CustomEventTransformer = CustomEventIngestTransformer
