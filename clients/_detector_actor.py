"""executionSettings.actor handling for Davis anomaly detectors (D16).

The Settings API rejects detectors whose executionSettings.actor is null,
missing, or not a service user on the tenant ("Provided actor is not a valid
service user or access is restricted"; verified with
`dtctl create settings --validate-only`). The actor is tenant configuration
(DYNATRACE_DETECTOR_ACTOR), so transformers emit `executionSettings: {}` and
import / IaC export fill it in.
"""

from __future__ import annotations

from typing import Any, Dict

DETECTOR_SCHEMA_ID = "builtin:davis.anomaly-detectors"
DETECTOR_ACTOR_PLACEHOLDER = "__DETECTOR_ACTOR__"


def with_detector_actor(envelope: Dict[str, Any], actor: str) -> Dict[str, Any]:
    """Copy of a detector envelope with executionSettings.actor set (no-op for other schemas)."""
    if envelope.get("schemaId") != DETECTOR_SCHEMA_ID:
        return envelope
    value = dict(envelope.get("value") or {})
    settings = {k: v for k, v in (value.get("executionSettings") or {}).items() if v is not None}
    settings["actor"] = actor
    value["executionSettings"] = settings
    return {**envelope, "value": value}
