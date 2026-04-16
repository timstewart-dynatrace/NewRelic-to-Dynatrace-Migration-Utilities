"""
Canary-mode helpers for the import phase (Phase 20).

Canary mode applies a migration to a fraction of each entity bucket
first, pauses for operator approval, and only then continues with the
rest. The operator's approval gate is a callable so tests can inject a
deterministic auto-approver.

Two-wave semantics:
  * Wave 1: `canary_percent` of each bucket (min 1 entity if the bucket
    is non-empty) is pushed.
  * Wave 2: remaining entities, executed only after `approval_gate()`
    returns True.

The orchestrator's existing `_push` loop wraps each entity bucket with
`CanaryPlan.split(bucket)` to yield the two waves. If `canary_percent`
is None (the default), splitting is a no-op and the original behavior
is preserved.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Tuple, TypeVar

T = TypeVar("T")

ApprovalGate = Callable[[str, int, int], bool]
"""Callable receiving (bucket_name, canary_count, total_count).

Returns True to proceed to wave 2, False to stop. Default production
gate prompts the operator via the CLI; tests inject a no-op auto-approve.
"""


def default_approval_gate(bucket: str, canary_count: int, total: int) -> bool:
    """Default gate — blocks; orchestrator substitutes a CLI prompt."""
    return False


@dataclass(frozen=True)
class CanaryPlan:
    """Parameters controlling canary-mode behavior."""

    canary_percent: Optional[float] = None  # 0 < pct <= 100; None disables canary
    approval_gate: ApprovalGate = default_approval_gate
    min_canary_size: int = 1

    def is_enabled(self) -> bool:
        return self.canary_percent is not None and self.canary_percent < 100

    def split(self, bucket: List[T]) -> Tuple[List[T], List[T]]:
        """Split a bucket into (canary, rest). Returns `(bucket, [])` when
        canary mode is disabled so existing callers are unaffected.
        """
        if not self.is_enabled() or not bucket:
            return list(bucket), []
        pct = max(0.0, min(float(self.canary_percent or 0), 100.0))
        count = max(self.min_canary_size, math.ceil(len(bucket) * pct / 100.0))
        # When canary mode is on (pct < 100), always hold back at least one
        # entity so the approval gate has something to gate.
        max_canary = max(1, len(bucket) - 1)
        count = min(count, max_canary)
        return bucket[:count], bucket[count:]


def auto_approve_gate(*_: object) -> bool:
    """Approval gate used in tests and non-interactive automation runs."""
    return True


def cli_prompt_gate(bucket: str, canary_count: int, total: int) -> bool:
    """Interactive CLI prompt. Returns True iff the operator confirms."""
    import click
    return click.confirm(
        f"Canary wave complete for '{bucket}' "
        f"({canary_count} of {total} entities). Proceed with the rest?",
        default=False,
    )
