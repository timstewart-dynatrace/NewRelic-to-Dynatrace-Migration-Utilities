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
from typing import Any, Dict, List

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
