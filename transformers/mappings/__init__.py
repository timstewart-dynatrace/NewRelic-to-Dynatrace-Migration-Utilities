"""
Per-concern import surface for the NRQL mapping tables (Phase 23, parity
with `nrql-engine`'s `default-metric-map.ts` pattern).

`transformers/nrql_mapping_rules.py` remains the canonical single source
of truth (all tables are defined there). This package exposes each
table in its own submodule so operators and downstream consumers can
import a single concern::

    # Before — had to pull the whole module:
    from transformers.nrql_mapping_rules import METRIC_MAP

    # After — scoped import:
    from transformers.mappings.metrics import METRIC_MAP
    from transformers.mappings.attributes import ATTR_MAP
    from transformers.mappings.aggregations import AGG_MAP
    from transformers.mappings.event_types import EVENT_TYPE_MAP

Operators who want to override one table (e.g. add customer-specific
metric renames) can:

1. Use the `MetricTransform` plugin hook
   (`transformers.metric_transform`), or
2. Monkey-patch a single submodule here without touching the monolith.
"""

from .aggregations import AGG_MAP
from .attributes import ATTR_MAP
from .event_types import EVENT_TYPE_MAP
from .metric_transforms import METRIC_TRANSFORMS
from .metrics import METRIC_MAP
from .visualizations import VIZ_MAP

__all__ = [
    "AGG_MAP",
    "ATTR_MAP",
    "EVENT_TYPE_MAP",
    "METRIC_MAP",
    "METRIC_TRANSFORMS",
    "VIZ_MAP",
]
