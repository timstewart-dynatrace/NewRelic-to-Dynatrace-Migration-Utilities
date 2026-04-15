"""
Lookup Table Transformer — Gen3 target.

New Relic supports `WHERE key IN (SELECT x FROM lookupTable)` patterns
using NR lookup tables (CSV uploads referenced by name). Dynatrace has
two equivalents:

  * DQL `lookup` subquery — dynamic (pulled at query time)
  * DT resource-store lookup file — static (CSV uploaded once)

This transformer translates a NR lookup-table name + its rows into:
  1. A Resource Store JSONL payload ready for upload
  2. A DQL fragment (`| lookup [fetch <bucket>...], sourceField:..., lookupField:..., fields:{...}`)
     that replaces the NR `WHERE ... IN (SELECT ...)` clause

The DQL fragment is intended for injection into anomaly-detector source
queries or dashboard tiles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class LookupTableResult:
    success: bool
    resource_store_jsonl: str = ""
    resource_store_upload_metadata: Optional[Dict[str, Any]] = None
    dql_fragment: str = ""
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class LookupTableTransformer:
    """Convert NR lookup tables to DT resource-store + DQL lookup fragments."""

    def transform(self, nr_table: Dict[str, Any]) -> LookupTableResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            name = nr_table.get("name", "unnamed-lookup")
            lookup_field = nr_table.get("lookupField") or nr_table.get("keyField") or "id"
            source_field = nr_table.get("sourceField", lookup_field)
            rows = nr_table.get("rows", []) or []
            fields_to_emit = nr_table.get("returnFields") or []

            if not rows:
                warnings.append(
                    f"Lookup table '{name}' is empty — emitted an empty "
                    "JSONL payload; operator should verify source data."
                )

            # Resource-store JSONL: one record per line
            jsonl_lines = [json.dumps(r) for r in rows]
            jsonl = "\n".join(jsonl_lines)

            safe_name = "".join(
                c if c.isalnum() or c in ("-", "_") else "-" for c in name.lower()
            )[:80]
            upload_metadata = {
                "filePath": f"/lookups/migrated-{safe_name}",
                "parsePattern": "HEADER,PAYLOAD",
                "lookupField": lookup_field,
                "overwrite": True,
                "displayName": f"[Migrated] {name}",
            }

            fetch_expr = f'fetch "dt.resource.store.lookup_table", filter:filePath=="/lookups/migrated-{safe_name}"'
            fields_list = (
                "{" + ", ".join(fields_to_emit) + "}" if fields_to_emit else "{}"
            )
            dql_fragment = (
                f"| lookup [{fetch_expr}], "
                f"sourceField:{source_field}, "
                f"lookupField:{lookup_field}, "
                f"fields:{fields_list}"
            )

            logger.info(
                "Transformed lookup table",
                name=name,
                rows=len(rows),
                fields=len(fields_to_emit),
            )
            return LookupTableResult(
                success=True,
                resource_store_jsonl=jsonl,
                resource_store_upload_metadata=upload_metadata,
                dql_fragment=dql_fragment,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Lookup table transformation failed", error=str(exc))
            return LookupTableResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, tables: List[Dict[str, Any]]
    ) -> List[LookupTableResult]:
        return [self.transform(t) for t in tables]
