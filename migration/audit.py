"""
Post-migration audit (Phase 20).

Compares a baseline export (typically `output/transformed/dynatrace_config.json`
from a previous migrate run, or the live snapshot from `DynatraceClient.backup_all()`)
against a fresh live snapshot from the target tenant. Surfaces drift in
four categories:

  RENAMED   — same id, different display name
  DELETED   — present in baseline, absent in live
  MODIFIED  — present in both, differing payload (Settings 2.0 `value`)
  EXTRA     — present in live with a `migrated.from == newrelic` marker
              but absent in baseline (rogue manual edits, or replays)

The audit is read-only — no DT writes. Exit status:

  0 — no drift
  1 — drift detected (renamed / deleted / modified / extra > 0)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


@dataclass
class AuditDrift:
    kind: str  # RENAMED | DELETED | MODIFIED | EXTRA
    entity_type: str
    entity_id: str
    name: str
    detail: Optional[str] = None


@dataclass
class AuditReport:
    drifts: List[AuditDrift] = field(default_factory=list)

    def has_drift(self) -> bool:
        return len(self.drifts) > 0

    def by_kind(self) -> Dict[str, List[AuditDrift]]:
        out: Dict[str, List[AuditDrift]] = {}
        for d in self.drifts:
            out.setdefault(d.kind, []).append(d)
        return out

    def to_json(self) -> str:
        return json.dumps(
            {
                "drift_count": len(self.drifts),
                "by_kind": {
                    k: [d.__dict__ for d in v]
                    for k, v in self.by_kind().items()
                },
            },
            indent=2,
        )


# ---------------------------------------------------------------------------
# Live snapshot helpers
# ---------------------------------------------------------------------------


def live_snapshot(dt_client: Any) -> Dict[str, List[Dict[str, Any]]]:
    """Pull the Gen3 live snapshot from a DynatraceClient.

    Returns one list per Gen3 entity bucket. Mirrors the keys produced by
    `DynatraceClient.backup_all()` minus metadata.
    """
    backup = dt_client.backup_all()
    return {
        k: v
        for k, v in backup.items()
        if k != "metadata" and isinstance(v, list)
    }


def load_baseline(path: Path) -> Dict[str, List[Dict[str, Any]]]:
    """Load a baseline transformed_data dict from disk."""
    with path.open() as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Baseline file {path} is not a JSON object")
    return data


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------


# Map of bucket name -> live key name -> id field -> name field. Buckets
# whose names differ between baseline (transformed) and live snapshot are
# normalized here.
_BUCKET_MAP = {
    "anomaly_detectors": ("anomaly_detectors", "objectId", "value.name"),
    "segments": ("segments", "objectId", "value.name"),
    "iam_policies": ("iam_policies", "objectId", "value.name"),
    "synthetic_tests": ("synthetic_tests", "objectId", "value.name"),
    "slos": ("slos", "objectId", "value.name"),
    "openpipeline_processors": ("openpipeline_logs", "objectId", "value.name"),
    "dashboards": ("dashboards", "id", "name"),
    "workflows": ("workflows", "id", "title"),
}


def _resolve_path(obj: Dict[str, Any], dotted: str) -> Any:
    cur: Any = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def diff_buckets(
    baseline: Dict[str, List[Dict[str, Any]]],
    live: Dict[str, List[Dict[str, Any]]],
) -> AuditReport:
    """Compute drift between baseline and live for every known Gen3 bucket."""
    report = AuditReport()
    for transformed_bucket, (live_bucket, id_field, name_field) in _BUCKET_MAP.items():
        baseline_items = baseline.get(transformed_bucket, []) or []
        live_items = live.get(live_bucket, []) or []

        # Index live by id (when available); otherwise by name.
        live_by_id: Dict[str, Dict[str, Any]] = {}
        live_by_name: Dict[str, Dict[str, Any]] = {}
        for item in live_items:
            entity_id = _resolve_path(item, id_field) or ""
            entity_name = _resolve_path(item, name_field) or ""
            if entity_id:
                live_by_id[entity_id] = item
            if entity_name:
                live_by_name[entity_name] = item

        seen_live_ids: set = set()
        for b_item in baseline_items:
            b_name = _resolve_path(b_item, name_field) or ""
            b_id = _resolve_path(b_item, id_field) or ""

            # Look up by id first; fall back to name (baseline often has no
            # ids since it's pre-import data).
            live_match = live_by_id.get(b_id) if b_id else None
            matched_via = "id"
            if live_match is None and b_name:
                live_match = live_by_name.get(b_name)
                matched_via = "name"

            if live_match is None:
                report.drifts.append(
                    AuditDrift(
                        kind="DELETED",
                        entity_type=transformed_bucket,
                        entity_id=b_id or b_name,
                        name=b_name,
                        detail="present in baseline, absent in live tenant",
                    )
                )
                continue

            live_id = _resolve_path(live_match, id_field) or ""
            live_name = _resolve_path(live_match, name_field) or ""
            if live_id:
                seen_live_ids.add(live_id)

            if matched_via == "id" and live_name and live_name != b_name:
                report.drifts.append(
                    AuditDrift(
                        kind="RENAMED",
                        entity_type=transformed_bucket,
                        entity_id=live_id,
                        name=live_name,
                        detail=f"baseline name was {b_name!r}",
                    )
                )

            if not _payload_equal(b_item, live_match):
                report.drifts.append(
                    AuditDrift(
                        kind="MODIFIED",
                        entity_type=transformed_bucket,
                        entity_id=live_id or live_name,
                        name=live_name or b_name,
                        detail="payload value differs from baseline",
                    )
                )

        # Find rogue extras: live entities that are tagged as migrated from
        # New Relic (so we expect them in the baseline) but aren't present.
        for item in live_items:
            live_id = _resolve_path(item, id_field) or ""
            if live_id in seen_live_ids:
                continue
            if not _looks_migrated(item):
                continue
            report.drifts.append(
                AuditDrift(
                    kind="EXTRA",
                    entity_type=transformed_bucket,
                    entity_id=live_id,
                    name=_resolve_path(item, name_field) or "(unnamed)",
                    detail="present in live tenant w/ migrated.from marker; not in baseline",
                )
            )
    return report


def _payload_equal(baseline_item: Dict[str, Any], live_item: Dict[str, Any]) -> bool:
    """Compare just the `value` payloads (Settings 2.0) or content (docs/wfs).

    Stripping wrapper fields (objectId, version, modificationInfo, etc.)
    so cosmetic round-trip differences don't produce false positives.
    """
    b = baseline_item.get("value", baseline_item)
    l = live_item.get("value", live_item)
    return _normalize(b) == _normalize(l)


def _normalize(payload: Any) -> Any:
    if isinstance(payload, dict):
        # Strip ephemeral / server-set fields.
        return {
            k: _normalize(v)
            for k, v in payload.items()
            if k not in ("modificationInfo", "version", "objectId", "id", "metadata")
        }
    if isinstance(payload, list):
        return [_normalize(x) for x in payload]
    return payload


def _looks_migrated(live_item: Dict[str, Any]) -> bool:
    """Heuristic: was this live entity created by an earlier migration run?

    Looks for the `migrated.from == newrelic` property (Phase 11 default
    eventTemplate.properties), the `[Migrated]` name prefix, or a tag.
    """
    name = (
        _resolve_path(live_item, "value.name")
        or live_item.get("name")
        or live_item.get("title")
        or ""
    )
    if isinstance(name, str) and name.startswith("[Migrated"):
        return True
    props = _resolve_path(live_item, "value.eventTemplate.properties") or []
    if isinstance(props, list):
        for p in props:
            if isinstance(p, dict) and p.get("key") == "migrated.from" and p.get("value") == "newrelic":
                return True
    description = _resolve_path(live_item, "value.description") or ""
    if isinstance(description, str) and "migrated" in description.lower():
        return True
    return False


def run_audit(
    baseline_path: Path,
    snapshot_loader: Callable[[], Dict[str, List[Dict[str, Any]]]],
) -> AuditReport:
    """High-level orchestration: load baseline, pull live, diff."""
    baseline = load_baseline(baseline_path)
    live = snapshot_loader()
    return diff_buckets(baseline, live)
