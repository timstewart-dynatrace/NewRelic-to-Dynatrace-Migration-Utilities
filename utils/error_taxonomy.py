"""
Centralized error / warning taxonomy (Phase 22).

Transformers historically produced ad-hoc warning strings that drift
apart across modules. This module defines a small, stable enum that
every transformer / client / exporter / validator uses when attaching
warnings or errors to a result.

The taxonomy is intentionally coarse — finer detail belongs in the
human-readable message. The code lets downstream reporting group and
filter at a glance.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class WarningCode(str, Enum):
    """Stable warning codes attached to migration artifacts.

    Subset naming convention: 3–4 uppercase letters describing the
    category. The string values are serializable and appear in reports.
    """

    # Confidence & translation fidelity.
    CONFIDENCE_LOW = "CONFIDENCE_LOW"
    CONFIDENCE_MEDIUM = "CONFIDENCE_MEDIUM"

    # Schema & shape issues.
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    UNSUPPORTED_WIDGET = "UNSUPPORTED_WIDGET"
    UNSUPPORTED_CONDITION = "UNSUPPORTED_CONDITION"
    UNSUPPORTED_EVENT_TYPE = "UNSUPPORTED_EVENT_TYPE"

    # Out-of-tool responsibilities.
    SECRET_MANUAL = "SECRET_MANUAL"
    AGENT_MANUAL = "AGENT_MANUAL"
    SYMBOLICATION_MANUAL = "SYMBOLICATION_MANUAL"
    CODE_SIDE_MIGRATION = "CODE_SIDE_MIGRATION"

    # Davis / platform auto-behavior.
    DAVIS_REPLACES = "DAVIS_REPLACES"
    SMARTSCAPE_AUTO = "SMARTSCAPE_AUTO"

    # Gen2 ↔ Gen3 runway.
    LEGACY_ONLY_PATH = "LEGACY_ONLY_PATH"
    GEN3_API_MISSING = "GEN3_API_MISSING"

    # Runtime / environment.
    RATE_LIMITED = "RATE_LIMITED"
    TENANT_CAPABILITY = "TENANT_CAPABILITY"

    # Data limits.
    TRUNCATED = "TRUNCATED"
    EMPTY_INPUT = "EMPTY_INPUT"


class ErrorCode(str, Enum):
    """Stable error codes — errors halt the migration for that entity."""

    TRANSFORM_FAILED = "TRANSFORM_FAILED"
    IMPORT_FAILED = "IMPORT_FAILED"
    AUTH_FAILED = "AUTH_FAILED"
    INVALID_INPUT = "INVALID_INPUT"
    UNSUPPORTED_PROVIDER = "UNSUPPORTED_PROVIDER"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


@dataclass
class CodedMessage:
    """Structured warning/error combining a stable code with a message.

    Transformers can still attach plain strings for backward compat, but
    new code should prefer this shape so reports can group.
    """

    code: str  # WarningCode | ErrorCode value
    message: str
    entity_ref: Optional[str] = None  # optional pointer to the entity it's about

    def __str__(self) -> str:
        if self.entity_ref:
            return f"[{self.code}] {self.entity_ref}: {self.message}"
        return f"[{self.code}] {self.message}"


def warn(code: WarningCode, message: str, entity_ref: Optional[str] = None) -> CodedMessage:
    return CodedMessage(code=code.value, message=message, entity_ref=entity_ref)


def error(code: ErrorCode, message: str, entity_ref: Optional[str] = None) -> CodedMessage:
    return CodedMessage(code=code.value, message=message, entity_ref=entity_ref)
