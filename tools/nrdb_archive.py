"""
NRDB pre-decommission archive tool.

Dynatrace Grail cannot ingest historical New Relic data. Before shutting
down the NR account, customers typically want a snapshot of recent
event-type data for compliance or forensic use. This tool pages through
NRQL for each event type and writes one JSONL file per type to a local
directory.

The output is **archive-only** — it is NOT replayable into Dynatrace.
Customers who need live historical data should run both platforms in
parallel during migration, not attempt to backfill.

Exported files:
  <output-dir>/
    manifest.json            # run metadata (account id, since, event types, counts)
    <EventType>.jsonl        # one JSON record per line
    <EventType>.cursor.json  # resume cursor (nextCursor from last successful page)

Resume semantics: if `<EventType>.cursor.json` exists and is non-empty,
the tool picks up from that cursor. Delete the cursor file to force a
full re-export.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import structlog

logger = structlog.get_logger()


# Canonical NR event types that most customers want to snapshot.
DEFAULT_EVENT_TYPES = [
    "Transaction",
    "TransactionError",
    "PageView",
    "PageAction",
    "BrowserInteraction",
    "AjaxRequest",
    "JavaScriptError",
    "MobileSession",
    "MobileCrash",
    "MobileRequest",
    "SystemSample",
    "ProcessSample",
    "SyntheticCheck",
    "SyntheticRequest",
    "Log",
    "InfrastructureEvent",
]


@dataclass
class ArchiveManifest:
    account_id: str
    since: str
    until: Optional[str]
    event_types: List[str]
    output_dir: str
    per_type_counts: Dict[str, int] = field(default_factory=dict)
    per_type_cursors: Dict[str, Optional[str]] = field(default_factory=dict)
    errors: Dict[str, str] = field(default_factory=dict)

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(self.__dict__, indent=2))


class NRDBArchive:
    """Page through NRQL per event type and write JSONL archives."""

    PAGE_SIZE = 2000  # NRQL MAX(LIMIT)

    def __init__(
        self,
        run_query: Callable[[str, Optional[str]], Dict[str, Any]],
        account_id: str,
    ) -> None:
        """
        Args:
            run_query: callable(nrql_string, cursor?) -> {"results": [...],
                "nextCursor": str|None}. The caller is responsible for
                credentials and rate-limiting. (Tests inject a mock.)
            account_id: NR account id (recorded in manifest).
        """
        self._run_query = run_query
        self.account_id = account_id

    # ------------------------------------------------------------------

    def archive(
        self,
        since: str,
        output_dir: str,
        event_types: Optional[Iterable[str]] = None,
        until: Optional[str] = None,
    ) -> ArchiveManifest:
        types = list(event_types or DEFAULT_EVENT_TYPES)
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        manifest = ArchiveManifest(
            account_id=self.account_id,
            since=since,
            until=until,
            event_types=types,
            output_dir=str(out),
        )

        for etype in types:
            try:
                count, cursor = self._archive_event_type(
                    etype, since, until, out
                )
                manifest.per_type_counts[etype] = count
                manifest.per_type_cursors[etype] = cursor
            except Exception as exc:  # noqa: BLE001 — per-type isolation
                logger.error("Archive failed for event type", type=etype, error=str(exc))
                manifest.errors[etype] = str(exc)

        manifest.write(out / "manifest.json")
        logger.info(
            "NRDB archive complete",
            types=len(types),
            total=sum(manifest.per_type_counts.values()),
            errors=len(manifest.errors),
        )
        return manifest

    # ------------------------------------------------------------------

    def _archive_event_type(
        self, etype: str, since: str, until: Optional[str], out: Path
    ):
        jsonl_path = out / f"{etype}.jsonl"
        cursor_path = out / f"{etype}.cursor.json"

        cursor: Optional[str] = None
        if cursor_path.exists():
            try:
                cursor = json.loads(cursor_path.read_text()).get("cursor")
            except Exception:  # noqa: BLE001
                cursor = None

        nrql = (
            f"FROM {etype} SELECT * "
            f"SINCE '{since}'"
            + (f" UNTIL '{until}'" if until else "")
            + f" LIMIT {self.PAGE_SIZE}"
        )

        count = 0
        mode = "a" if cursor else "w"
        with jsonl_path.open(mode) as fh:
            while True:
                response = self._run_query(nrql, cursor)
                for record in response.get("results", []) or []:
                    fh.write(json.dumps(record))
                    fh.write("\n")
                    count += 1
                cursor = response.get("nextCursor")
                cursor_path.write_text(json.dumps({"cursor": cursor}))
                if not cursor:
                    break

        logger.info(
            "Archived event type",
            type=etype,
            records=count,
            file=str(jsonl_path),
        )
        return count, cursor
