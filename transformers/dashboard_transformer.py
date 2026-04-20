"""
Dashboard Transformer — Gen3 target.

Emits the Dynatrace Grail-native dashboard JSON consumed by the Document
API (schema `type == 'dashboard'`, `version: 13`). Tiles are keyed by
string indices in a `tiles` map with a parallel `layouts` map, and every
data tile carries a DQL query — no Config v1 dashboard fallback on the
default path.

Multi-page NR dashboards still yield one Gen3 dashboard per page.

Legacy (Config v1 dashboard) behavior is preserved in
`transformers/legacy/dashboard_transformer_v1.py`.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

import structlog

from .mapping_rules import EntityMapper
from .nrql_converter import NRQLtoDQLConverter

logger = structlog.get_logger()


# Gen3 visualization names (the Grail dashboard `visualization` string
# on data tiles). Mapped from NR widget ids.
_VIZ_MAP_GEN3 = {
    "viz.line": "lineChart",
    "viz.area": "areaChart",
    "viz.bar": "barChart",
    "viz.pie": "pieChart",
    "viz.stacked-bar": "barChart",
    # Heatmap now uses the Gen3 honeycomb tile (Phase 19 — was "heatmap" fallback).
    "viz.heatmap": "honeycomb",
    "viz.table": "table",
    "viz.billboard": "singleValue",
    "viz.markdown": "markdown",
    "viz.histogram": "histogram",
    "viz.json": "table",
    "viz.bullet": "singleValue",
    # Funnel renders as a composite of barChart stages (Phase 19 — was "table").
    "viz.funnel": "funnel",  # handled specially in _transform_widget
    # Event feed renders as a table with a canonical timestamp sort (Phase 19).
    "viz.event-feed": "table",
    "viz.inline": "singleValue",
}


# NR dashboard permission -> DT Document sharing block.
_PERMISSION_MAP = {
    "PUBLIC_READ_ONLY": {"access": ["read"], "scope": "public"},
    "PUBLIC_READ_WRITE": {"access": ["read", "write"], "scope": "public"},
    "PRIVATE": {"access": [], "scope": "private"},
}

_GRID_W = 4   # Gen3 columns per NR column
_GRID_H = 4   # Gen3 rows per NR row


@dataclass
class DashboardTransformResult:
    """Result of NR dashboard -> Gen3 Grail dashboard translation.

    Each element of `data` is a Document-API-ready JSON blob (the
    `content` payload of a `documentsClient.createDocument` call where
    `type='dashboard'`).
    """

    success: bool
    data: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class DashboardTransformer:
    """NR dashboard -> Gen3 Grail dashboard JSON (Document API payload)."""

    def __init__(self, registry=None) -> None:
        self.mapper = EntityMapper()
        self._nrql_converter = NRQLtoDQLConverter(registry=registry)

    def transform(self, nr_dashboard: Dict[str, Any]) -> DashboardTransformResult:
        dashboards: List[Dict[str, Any]] = []
        all_warnings: List[str] = []

        try:
            pages = nr_dashboard.get("pages", []) or []
            if not pages:
                return DashboardTransformResult(
                    success=False, errors=["Dashboard has no pages"]
                )

            for page_index, page in enumerate(pages):
                dash, warns = self._transform_page(
                    nr_dashboard=nr_dashboard,
                    page=page,
                    page_index=page_index,
                    total_pages=len(pages),
                )
                if dash is not None:
                    dashboards.append(dash)
                all_warnings.extend(warns)
        except Exception as exc:  # noqa: BLE001
            logger.error("Dashboard transformation failed", error=str(exc))
            return DashboardTransformResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

        return DashboardTransformResult(
            success=True, data=dashboards, warnings=all_warnings
        )

    def _transform_page(
        self,
        nr_dashboard: Dict[str, Any],
        page: Dict[str, Any],
        page_index: int,
        total_pages: int,
    ):
        warnings: List[str] = []
        base_name = nr_dashboard.get("name", "Untitled Dashboard")
        page_name = page.get("name", f"Page {page_index + 1}")
        name = f"{base_name} - {page_name}" if total_pages > 1 else base_name

        tiles: Dict[str, Any] = {}
        layouts: Dict[str, Any] = {}

        for i, widget in enumerate(page.get("widgets", []) or []):
            tile, layout, wwarn = self._transform_widget(widget)
            key = str(i)
            tiles[key] = tile
            layouts[key] = layout
            warnings.extend(wwarn)

        variables = self._transform_variables(
            nr_dashboard.get("variables", []) or []
        )
        saved_views = self._transform_saved_filters(
            nr_dashboard.get("savedFilters", []) or []
            or page.get("savedFilters", []) or []
        )
        sharing = _PERMISSION_MAP.get(
            str(nr_dashboard.get("permissions", "PRIVATE")).upper(),
            _PERMISSION_MAP["PRIVATE"],
        )

        dashboard = {
            "version": 13,
            "name": name,
            "description": nr_dashboard.get("description")
            or page.get("description")
            or f"Migrated from New Relic dashboard '{base_name}'.",
            "variables": variables,
            "tiles": tiles,
            "layouts": layouts,
            "savedViews": saved_views,
            "sharing": sharing,
            "settings": {
                "gridLayout": {"columns": 24},
                "theme": "auto",
            },
        }

        if sharing["scope"] == "public" and not sharing["access"]:
            warnings.append(
                f"Permissions for '{name}' resolved to public with no access — "
                "operator should verify DT Document sharing after import."
            )

        logger.info(
            "Transformed Gen3 dashboard page",
            name=name,
            tiles=len(tiles),
            variables=len(variables),
            saved_views=len(saved_views),
        )
        return dashboard, warnings

    # ------------------------------------------------------------------
    # Widgets → tiles
    # ------------------------------------------------------------------

    def _transform_widget(self, widget: Dict[str, Any]):
        warnings: List[str] = []
        viz_id = (widget.get("visualization") or {}).get("id", "")
        visualization = _VIZ_MAP_GEN3.get(viz_id, "table")
        title = widget.get("title", "Untitled")
        raw = widget.get("rawConfiguration", {}) or {}

        if viz_id == "viz.markdown":
            tile = {
                "type": "markdown",
                "title": title,
                "content": raw.get("text", ""),
            }
        elif viz_id == "viz.funnel":
            tile, funnel_warns = self._funnel_composite_tile(title, raw)
            warnings.extend(funnel_warns)
        elif viz_id == "viz.event-feed":
            tile, feed_warns = self._event_feed_tile(title, raw)
            warnings.extend(feed_warns)
        elif viz_id == "viz.heatmap":
            tile, hm_warns = self._honeycomb_tile(title, raw)
            warnings.extend(hm_warns)
        else:
            nrql_queries = raw.get("nrqlQueries", []) or []
            query = nrql_queries[0].get("query", "") if nrql_queries else ""
            dql_result = self._convert_nrql_to_dql(query, title) if query else {
                "dql": "",
                "warnings": [],
                "fully_converted": False,
                "confidence": "LOW",
            }
            warnings.extend(dql_result["warnings"])
            if query and not dql_result["fully_converted"]:
                warnings.append(
                    f"Tile '{title}' converted with {dql_result.get('confidence', 'UNKNOWN')} "
                    f"confidence. Original NRQL: {query[:100]}..."
                )
            tile = {
                "type": "data",
                "title": title,
                "query": dql_result["dql"],
                "visualization": visualization,
                "visualizationSettings": {"chartSettings": {"legend": {"hidden": False}}},
            }

        layout = self._transform_layout(widget.get("layout", {}) or {})
        return tile, layout, warnings

    # ------------------------------------------------------------------
    # Phase 19 widget renderers
    # ------------------------------------------------------------------

    def _funnel_composite_tile(self, title: str, raw: Dict[str, Any]):
        """NR funnel -> a Gen3 barChart tile with stages.

        A true funnel is multi-query; we collapse the stages into a single
        DQL expression `makeTimeseries count(), by:{stage}` where `stage` is
        derived from the `WHERE <stage predicate>` clause of each NR leg.
        The barChart with `orientation: horizontal` + sorted stages gives
        the funnel look without a separate tile per stage.
        """
        warnings: List[str] = []
        stages = raw.get("stages") or []
        nrql_queries = raw.get("nrqlQueries") or []
        stage_names: List[str] = []
        predicates: List[str] = []
        # NR funnels often encode stage predicates in a single NRQL FUNNEL
        # clause or as a list. Support both shapes.
        if stages:
            for s in stages:
                stage_names.append(s.get("name", "stage"))
                predicates.append(s.get("predicate", "true"))
        elif nrql_queries:
            # Flatten each leg into its name + predicate.
            for q in nrql_queries:
                stage_names.append(q.get("name", "stage"))
                predicates.append(q.get("query", ""))

        if not stage_names:
            warnings.append(
                f"Funnel tile '{title}' has no stages — emitted a markdown "
                "placeholder instead of a chart."
            )
            return (
                {
                    "type": "markdown",
                    "title": title,
                    "content": "_Funnel with no stages — reconfigure in DT._",
                },
                warnings,
            )

        base_event = raw.get("sourceEvent", "PageView")
        # Emit one countIf() per stage as separate fields; DT barChart plots them.
        count_ifs = ",\n  ".join(
            f'"{name}" = countIf({pred or "true"})'
            for name, pred in zip(stage_names, predicates)
        )
        dql = (
            f"fetch bizevents, from:now()-1d\n"
            f'| filter event.type == "{base_event}"\n'
            f"| summarize {{\n  {count_ifs}\n}}"
        )
        tile = {
            "type": "data",
            "title": title,
            "query": dql,
            "visualization": "barChart",
            "visualizationSettings": {
                "chartSettings": {
                    "legend": {"hidden": False},
                    "layout": "horizontal",
                    "sortCriterion": "desc",
                },
                "funnelEmulation": True,
            },
        }
        warnings.append(
            f"Funnel tile '{title}' emitted as a composite barChart. "
            "Validate stage counts in DT after import."
        )
        return tile, warnings

    def _event_feed_tile(self, title: str, raw: Dict[str, Any]):
        warnings: List[str] = []
        nrql_queries = raw.get("nrqlQueries") or []
        query = nrql_queries[0].get("query", "") if nrql_queries else ""
        dql_result = self._convert_nrql_to_dql(query, title) if query else {
            "dql": "", "warnings": [], "fully_converted": True, "confidence": "HIGH",
        }
        warnings.extend(dql_result["warnings"])
        # Force a canonical timestamp sort for event-feed semantics.
        dql = dql_result["dql"] or "fetch events, from:now()-1d"
        if "| sort" not in dql:
            dql = f"{dql}\n| sort timestamp desc"
        tile = {
            "type": "data",
            "title": title,
            "query": dql,
            "visualization": "table",
            "visualizationSettings": {
                "chartSettings": {"legend": {"hidden": True}},
                "table": {
                    "columnAttributes": [
                        {"name": "timestamp", "width": "160px", "fixed": True},
                    ],
                    "eventFeedMode": True,
                },
            },
        }
        return tile, warnings

    def _honeycomb_tile(self, title: str, raw: Dict[str, Any]):
        warnings: List[str] = []
        nrql_queries = raw.get("nrqlQueries") or []
        query = nrql_queries[0].get("query", "") if nrql_queries else ""
        dql_result = self._convert_nrql_to_dql(query, title) if query else {
            "dql": "", "warnings": [], "fully_converted": False, "confidence": "LOW",
        }
        warnings.extend(dql_result["warnings"])
        tile = {
            "type": "data",
            "title": title,
            "query": dql_result["dql"],
            "visualization": "honeycomb",
            "visualizationSettings": {
                "honeycomb": {
                    "shape": "hexagon",
                    "colorMode": "byValue",
                    "legend": {"hidden": False},
                },
            },
        }
        return tile, warnings

    @staticmethod
    def _transform_layout(layout: Dict[str, Any]) -> Dict[str, Any]:
        column = (layout.get("column", 1) or 1) - 1
        row = (layout.get("row", 1) or 1) - 1
        width = layout.get("width", 4)
        height = layout.get("height", 3)
        return {
            "x": column * _GRID_W,
            "y": row * _GRID_H,
            "w": width * _GRID_W,
            "h": height * _GRID_H,
        }

    # ------------------------------------------------------------------

    def _convert_nrql_to_dql(self, nrql: str, title: str = "") -> Dict[str, Any]:
        result = self._nrql_converter.convert(nrql, title or "query")
        return {
            "dql": result.dql,
            "warnings": result.warnings,
            "fully_converted": result.success and result.confidence == "HIGH",
            "confidence": result.confidence,
            "fixes": result.fixes,
        }

    @staticmethod
    def _transform_variables(variables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Gen3 dashboard variables with cascading dependency resolution.

        NR variables can reference other variables via `{{varName}}` inside
        their NRQL source. Gen3 honors this same `{{varName}}` syntax in
        the variable's input query, so we carry references through unchanged
        and additionally emit a `dependsOn` array so DT renders them in
        dependency order.
        """
        import re
        out: List[Dict[str, Any]] = []
        names_in_order = [v.get("name", "var") for v in variables]
        for var in variables:
            nrql_source = var.get("nrql", "") or var.get("query", "")
            var_type = str(var.get("type", "NRQL")).lower()
            depends_on = [
                ref
                for ref in re.findall(r"\{\{(\w+)\}\}", nrql_source)
                if ref in names_in_order
            ]
            out.append(
                {
                    "key": var.get("name", "var"),
                    "type": _gen3_variable_type(var_type),
                    "visible": bool(var.get("visible", True)),
                    "input": {
                        "query": nrql_source,
                        "type": "dql" if var_type == "nrql" else "csv",
                    },
                    "multiSelect": bool(var.get("isMultiSelection", False)),
                    "defaultValue": var.get("defaultValue", ""),
                    # Phase 19: dependency order for cascading variables.
                    "dependsOn": depends_on,
                }
            )
        return out

    @staticmethod
    def _transform_saved_filters(saved_filters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """NR saved filter sets -> Document `savedViews` entries.

        Each NR saved filter is a named set of variable assignments. Gen3
        exposes these under `savedViews` on the dashboard Document so users
        can flip between them.
        """
        views: List[Dict[str, Any]] = []
        for sf in saved_filters:
            views.append(
                {
                    "name": sf.get("name", "saved-view"),
                    "description": sf.get("description", ""),
                    "variableValues": sf.get("variableAssignments") or {},
                }
            )
        return views

    def transform_all(
        self, dashboards: List[Dict[str, Any]]
    ) -> List[DashboardTransformResult]:
        results = [self.transform(d) for d in dashboards]
        successful = sum(1 for r in results if r.success)
        total_pages = sum(len(r.data) for r in results if r.success)
        logger.info(
            f"Transformed {successful}/{len(results)} dashboards ({total_pages} Gen3 pages)"
        )
        return results


def _gen3_variable_type(nr_type: str) -> str:
    """Map NR variable type to Gen3 variable type."""
    return {
        "nrql": "query",
        "enum": "csv",
        "string": "csv",
    }.get(str(nr_type).lower(), "query")
