"""Shared helpers for Gen3 Automation workflow emission.

The Gen3 Automation API (`/platform/automation/v1/workflows`) expects
`tasks` as a **dict keyed by task id**, not a list. Sending a list
produces:

    {"tasks": ["Input should be a valid dictionary"]}

Transformers historically built `tasks` as a list for ordering
convenience. `tasks_list_to_dict` converts that list into the shape the
API wants while preserving insertion order and uniqueness of keys.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_TASK_ID_CHARS = re.compile(r"[^a-zA-Z0-9_]")


def _slug_task_id(name: str, fallback: str) -> str:
    """Normalize a task name to a valid task id.

    Automation workflow task ids are referenced in JavaScript
    expressions (`result("task_id")`), so we keep them to identifier
    characters only.
    """
    slug = _TASK_ID_CHARS.sub("_", (name or "").strip()).strip("_").lower()
    return slug or fallback


def tasks_list_to_dict(tasks: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Convert an ordered list of task dicts to the Gen3 `tasks` shape.

    Keys are derived from each task's ``name`` field. Collisions get a
    numeric suffix (``send_email``, ``send_email_2``, …) so order and
    uniqueness are both preserved.

    A list-shaped input is the legacy convention across every
    migrator transformer that emits workflows. The API only accepts a
    dict — passing a list returns 400 with ``{"tasks": ["Input should
    be a valid dictionary"]}``.
    """
    if isinstance(tasks, dict):
        return tasks  # already converted — idempotent
    out: Dict[str, Dict[str, Any]] = {}
    for idx, task in enumerate(tasks):
        base_id = _slug_task_id(task.get("name", ""), fallback=f"task_{idx}")
        task_id = base_id
        bump = 2
        while task_id in out:
            task_id = f"{base_id}_{bump}"
            bump += 1
        out[task_id] = task
    return out


# ---------------------------------------------------------------------------
# Detector <-> workflow linkage (davis-problem trigger)
# ---------------------------------------------------------------------------
#
# Verified live (docs/live-validation-2026-09.md, D3/D4):
# * Workflow triggers are `trigger.eventTrigger.triggerConfiguration`
#   `{type: "davis-problem" | "davis-event" | "event", value: {...}}`; there is no
#   `detectorIds` field.
# * Problem records do not carry detector `eventTemplate.properties`, but a
#   problem's `event.name` equals its contributing detector event's name
#   (466/466 CUSTOM_ALERT problems). Linkage is therefore by event-name prefix.
# * Workflow customFilter accepts `matchesValue()` wildcards; `startsWith()` is
#   not enabled for OpenPipeline matchers.

MIGRATED_EVENT_PREFIX = "[Migrated]"

PROBLEM_CATEGORIES = ("availability", "error", "slowdown", "resource", "custom", "monitoringUnavailable")

# NR severity-ladder severities that correspond to Davis problem categories.
_SEVERITY_TO_CATEGORY = {
    "AVAILABILITY": "availability",
    "ERROR": "error",
    "SLOWDOWN": "slowdown",
    "PERFORMANCE": "slowdown",
    "RESOURCE": "resource",
    "RESOURCE_CONTENTION": "resource",
    "CUSTOM": "custom",
    "CUSTOM_ALERT": "custom",
}


def _link_group(group: str) -> str:
    # `*` is a matchesValue wildcard and cannot be escaped (verified with
    # `dtctl verify openpipeline-matcher`), so keep it out of linkage names.
    return group.replace("*", "-")


def migrated_event_name(group: str, item: str) -> str:
    """Davis event (and resulting problem) name for a migrated detector."""
    return f"{MIGRATED_EVENT_PREFIX} {_link_group(group)} | {item}"


def migrated_event_filter(group: str) -> str:
    """customFilter matching every problem raised by detectors in ``group``."""
    prefix = f"{MIGRATED_EVENT_PREFIX} {_link_group(group)} | "
    prefix = prefix.replace("\\", "\\\\").replace('"', '\\"')
    return f'matchesValue(event.name, "{prefix}*")'


def davis_problem_trigger(
    custom_filter: str = "",
    *,
    severity: str = "",
    entity_tags: Optional[Dict[str, Any]] = None,
    active: bool = True,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Automation workflow trigger for Davis problems."""
    categories = {c: True for c in PROBLEM_CATEGORIES}
    if severity:
        category = _SEVERITY_TO_CATEGORY.get(severity.upper())
        if category:
            categories = {c: c == category for c in PROBLEM_CATEGORIES}
        elif warnings is not None:
            warnings.append(
                f"NR severity '{severity}' has no Davis problem category; workflow "
                "triggers on all categories."
            )
    return {
        "eventTrigger": {
            "isActive": active,
            "triggerConfiguration": {
                "type": "davis-problem",
                "value": {
                    "analysisReady": False,
                    "categories": categories,
                    "customFilter": custom_filter,
                    "entityTags": dict(entity_tags or {}),
                    "entityTagsMatch": "all",
                    "onProblemClose": False,
                },
            },
        }
    }
