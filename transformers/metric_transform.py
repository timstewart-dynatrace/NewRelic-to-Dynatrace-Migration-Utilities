"""
MetricTransform plugin protocol.

Ported from nrql-engine TS sibling
(`src/transformers/metric-transform.interface.ts`). Lets operators
inject project-specific metric renames into the NRQL→DQL pipeline
without forking the codebase.

Usage::

    from transformers.metric_transform import MetricTransform
    from transformers.nrql_converter import NRQLtoDQLConverter

    def rename_customer_metric(field_key, raw_field, static_mapped):
        if field_key == "custom_latency_ms":
            return ("dt.apps.custom.latency", None)
        return None  # fall through to default mapping

    converter = NRQLtoDQLConverter()
    converter.register_metric_transform(rename_customer_metric)

A resolver returns either `(dt_metric_key, optional_warning)` to
override the default mapping, or `None` to let the default logic run.
Multiple resolvers are tried in registration order; the first
non-`None` wins.
"""

from __future__ import annotations

from typing import Callable, Optional, Tuple

# Signature matches the existing `metric_resolver` slot in NRQLCompiler.
MetricTransform = Callable[
    [str, str, Optional[str]],  # field_key, raw_field, static_mapped
    Optional[Tuple[str, Optional[str]]],  # (dt_metric_key, warning) or None
]


class MetricTransformRegistry:
    """Ordered list of MetricTransform callables with a resolver facade.

    Attached to `NRQLtoDQLConverter`; the converter wires its internal
    resolver slot through this registry so multiple operator hooks
    compose cleanly.
    """

    def __init__(self) -> None:
        self._transforms: list[MetricTransform] = []

    def register(self, transform: MetricTransform) -> None:
        """Append a transform to the end of the resolver chain."""
        self._transforms.append(transform)

    def clear(self) -> None:
        self._transforms.clear()

    def resolve(
        self, field_key: str, raw_field: str, static_mapped: Optional[str]
    ) -> Optional[Tuple[str, Optional[str]]]:
        """Run the chain; return the first non-None result."""
        for transform in self._transforms:
            result = transform(field_key, raw_field, static_mapped)
            if result is not None:
                return result
        return None

    def __len__(self) -> int:
        return len(self._transforms)
