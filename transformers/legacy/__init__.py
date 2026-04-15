"""Gen2 (classic-tenant) transformer implementations.

Preserved to support the `--legacy` CLI flag for Dynatrace tenants that
do not yet have Gen3 platform features (Workflows, Segments, OpenPipeline,
Davis Anomaly Detectors, Document API). These modules target the legacy
Config v1 API and Settings 2.0 classic objects:

- Alerting Profile           (Gen2) — replaced by Workflow
- Problem Notification       (Gen2) — replaced by Workflow action tasks
- Metric Event (Config v1)   (Gen2) — replaced by Davis Anomaly Detector
- Management Zone            (Gen2) — replaced by Segment + IAM policy
- Auto-Tag Rule              (Gen2) — replaced by OpenPipeline enrichment
- Config v1 Dashboard        (Gen2) — replaced by Document API dashboard

Do not import from this submodule in default (Gen3) code paths.
"""

from .alert_transformer_v1 import AlertTransformer as LegacyAlertTransformer
from .alert_transformer_v1 import NotificationTransformer as LegacyNotificationTransformer
from .dashboard_transformer_v1 import DashboardTransformer as LegacyDashboardTransformer
from .drop_rule_transformer_v1 import DropRuleTransformer as LegacyDropRuleTransformer
from .infrastructure_transformer_v1 import (
    InfrastructureTransformer as LegacyInfrastructureTransformer,
)
from .log_parsing_transformer_v1 import LogParsingTransformer as LegacyLogParsingTransformer
from .slo_transformer_v1 import SLOTransformer as LegacySLOTransformer
from .synthetic_transformer_v1 import SyntheticTransformer as LegacySyntheticTransformer
from .tag_transformer_v1 import TagTransformer as LegacyTagTransformer
from .workload_transformer_v1 import WorkloadTransformer as LegacyWorkloadTransformer

__all__ = [
    "LegacyAlertTransformer",
    "LegacyNotificationTransformer",
    "LegacyDashboardTransformer",
    "LegacyDropRuleTransformer",
    "LegacyInfrastructureTransformer",
    "LegacyLogParsingTransformer",
    "LegacySLOTransformer",
    "LegacySyntheticTransformer",
    "LegacyTagTransformer",
    "LegacyWorkloadTransformer",
]
