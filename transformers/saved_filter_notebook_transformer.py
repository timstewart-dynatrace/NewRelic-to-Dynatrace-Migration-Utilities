"""
Saved-Filter Notebook Transformer — Gen3 target.

NR Saved Filters + Data App widgets map to Dynatrace Notebooks
(Document API `type == 'notebook'`). Each NR Data App entry becomes a
cell; NRQL queries translate to DQL; markdown cells carry over.

This is distinct from `DashboardTransformer`: dashboards are tiled and
always-on, notebooks are cell-based and authored. NR's saved-filter
pattern (name a filter set + attach it to a data app) maps cleanly to
notebook cells with pre-populated variable values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

from .nrql_converter import NRQLtoDQLConverter

logger = structlog.get_logger()


@dataclass
class SavedFilterNotebookResult:
    success: bool
    notebook_content: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class SavedFilterNotebookTransformer:
    """NR Saved Filter / Data App -> DT Notebook (Document API)."""

    def __init__(self, registry=None) -> None:
        self._nrql_converter = NRQLtoDQLConverter(registry=registry)

    def transform(self, nr_app: Dict[str, Any]) -> SavedFilterNotebookResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            name = nr_app.get("name", "unnamed-notebook")
            description = nr_app.get("description", "")
            cells_in = nr_app.get("cells") or []
            default_filters = nr_app.get("defaultFilters") or {}

            notebook_cells: List[Dict[str, Any]] = []
            for idx, cell in enumerate(cells_in):
                cell_type = str(cell.get("type", "nrql")).lower()
                if cell_type == "markdown":
                    notebook_cells.append(
                        {
                            "id": f"cell-{idx}",
                            "type": "markdown",
                            "content": cell.get("content", ""),
                        }
                    )
                elif cell_type == "nrql":
                    nrql = cell.get("query", "")
                    conv = self._nrql_converter.convert(
                        nrql, title=cell.get("title", "")
                    )
                    if not conv.success or conv.confidence != "HIGH":
                        warnings.append(
                            f"Notebook cell {idx} '{cell.get('title', '')}' "
                            f"converted with {conv.confidence} confidence."
                        )
                    notebook_cells.append(
                        {
                            "id": f"cell-{idx}",
                            "type": "dql",
                            "title": cell.get("title", f"Cell {idx + 1}"),
                            "query": conv.dql,
                            "visualization": cell.get("visualization", "table"),
                        }
                    )
                else:
                    warnings.append(
                        f"Unknown cell type '{cell_type}' in notebook '{name}' — skipped."
                    )

            notebook_content = {
                "version": 1,
                "name": f"[Migrated notebook] {name}",
                "description": description
                or f"Migrated from New Relic Data App '{name}'.",
                "cells": notebook_cells,
                "defaultVariableValues": dict(default_filters),
            }

            logger.info(
                "Transformed saved-filter notebook",
                name=name,
                cells=len(notebook_cells),
            )
            return SavedFilterNotebookResult(
                success=True,
                notebook_content=notebook_content,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Saved-filter notebook transformation failed", error=str(exc))
            return SavedFilterNotebookResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, apps: List[Dict[str, Any]]
    ) -> List[SavedFilterNotebookResult]:
        return [self.transform(a) for a in apps]
