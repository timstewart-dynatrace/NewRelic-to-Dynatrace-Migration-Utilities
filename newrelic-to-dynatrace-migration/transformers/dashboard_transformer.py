"""
Dashboard Transformer - Converts New Relic dashboards to Dynatrace format.

Uses the AST-based NRQL compiler for accurate query translation (282 tested patterns)
instead of regex-based conversion.
"""

import json
import re
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
import structlog

from .mapping_rules import (
    EntityMapper,
    VISUALIZATION_TYPE_MAP,
    CHART_TYPE_MAP,
)
from .nrql_converter import NRQLtoDQLConverter

logger = structlog.get_logger()


@dataclass
class TransformResult:
    """Result of a transformation operation."""
    success: bool
    data: Optional[Dict[str, Any]] = None
    warnings: List[str] = None
    errors: List[str] = None

    def __post_init__(self):
        self.warnings = self.warnings or []
        self.errors = self.errors or []


class DashboardTransformer:
    """
    Transforms New Relic dashboards to Dynatrace dashboard format.

    Handles:
    - Dashboard metadata conversion
    - Page to dashboard conversion (New Relic dashboards can have multiple pages)
    - Widget/visualization conversion
    - NRQL to DQL query conversion (where possible)
    - Layout transformation
    """

    # Dynatrace tile size unit (typically 38 pixels per unit)
    TILE_UNIT = 38

    # Default tile dimensions
    DEFAULT_TILE_WIDTH = 6
    DEFAULT_TILE_HEIGHT = 4

    def __init__(self, registry=None):
        self.mapper = EntityMapper()
        self._nrql_converter = NRQLtoDQLConverter(registry=registry)

    def transform(self, nr_dashboard: Dict[str, Any]) -> List[TransformResult]:
        """
        Transform a New Relic dashboard to Dynatrace format.

        Returns a list of TransformResults because a multi-page New Relic dashboard
        may be converted to multiple Dynatrace dashboards.
        """
        results = []

        try:
            pages = nr_dashboard.get("pages", [])

            if not pages:
                return [TransformResult(
                    success=False,
                    errors=["Dashboard has no pages"]
                )]

            # Convert each page to a separate Dynatrace dashboard
            for page_index, page in enumerate(pages):
                result = self._transform_page(
                    nr_dashboard=nr_dashboard,
                    page=page,
                    page_index=page_index,
                    total_pages=len(pages)
                )
                results.append(result)

        except Exception as e:
            logger.error("Dashboard transformation failed", error=str(e))
            results.append(TransformResult(
                success=False,
                errors=[f"Transformation error: {str(e)}"]
            ))

        return results

    def _transform_page(
        self,
        nr_dashboard: Dict[str, Any],
        page: Dict[str, Any],
        page_index: int,
        total_pages: int
    ) -> TransformResult:
        """Transform a single dashboard page."""
        warnings = []

        # Build dashboard name
        dashboard_name = nr_dashboard.get("name", "Untitled Dashboard")
        page_name = page.get("name", f"Page {page_index + 1}")

        if total_pages > 1:
            dashboard_name = f"{dashboard_name} - {page_name}"

        # Create Dynatrace dashboard structure
        dt_dashboard = {
            "dashboardMetadata": {
                "name": dashboard_name,
                "shared": self._map_permissions(nr_dashboard.get("permissions")),
                "owner": "migration-tool",
                "tags": ["migrated-from-newrelic"],
                "preset": False,
                "dynamicFilters": {
                    "filters": [],
                    "genericTagFilters": []
                }
            },
            "tiles": []
        }

        # Add description if available
        description = nr_dashboard.get("description") or page.get("description")
        if description:
            dt_dashboard["dashboardMetadata"]["description"] = description

        # Transform widgets to tiles
        widgets = page.get("widgets", [])
        for widget in widgets:
            tile_result = self._transform_widget(widget)
            if tile_result:
                dt_dashboard["tiles"].append(tile_result["tile"])
                if tile_result.get("warnings"):
                    warnings.extend(tile_result["warnings"])

        # Transform variables to dashboard filters
        variables = nr_dashboard.get("variables", [])
        if variables:
            filter_result = self._transform_variables(variables)
            dt_dashboard["dashboardMetadata"]["dynamicFilters"] = filter_result

        logger.info(
            "Transformed dashboard page",
            name=dashboard_name,
            tiles=len(dt_dashboard["tiles"])
        )

        return TransformResult(
            success=True,
            data=dt_dashboard,
            warnings=warnings
        )

    def _transform_widget(self, widget: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Transform a New Relic widget to a Dynatrace tile."""
        warnings = []

        visualization = widget.get("visualization", {})
        viz_id = visualization.get("id", "")

        # Map visualization type to Dynatrace tile type
        tile_type = VISUALIZATION_TYPE_MAP.get(viz_id, "DATA_EXPLORER")

        # Get layout information
        layout = widget.get("layout", {})
        bounds = self._transform_layout(layout)

        # Base tile structure
        tile = {
            "name": widget.get("title", "Untitled"),
            "tileType": tile_type,
            "configured": True,
            "bounds": bounds,
            "tileFilter": {}
        }

        # Handle specific tile types
        if tile_type == "MARKDOWN":
            tile = self._transform_markdown_widget(widget, tile)
        elif tile_type == "SINGLE_VALUE":
            tile = self._transform_billboard_widget(widget, tile, warnings)
        else:
            tile = self._transform_chart_widget(widget, tile, warnings)

        return {"tile": tile, "warnings": warnings}

    def _transform_layout(self, layout: Dict[str, Any]) -> Dict[str, int]:
        """Transform New Relic layout to Dynatrace bounds."""
        # New Relic uses a 12-column grid
        # Dynatrace uses absolute pixel positions

        column = layout.get("column", 1) - 1  # NR is 1-indexed
        row = layout.get("row", 1) - 1
        width = layout.get("width", self.DEFAULT_TILE_WIDTH)
        height = layout.get("height", self.DEFAULT_TILE_HEIGHT)

        return {
            "top": row * self.TILE_UNIT * 2,
            "left": column * self.TILE_UNIT * 2,
            "width": width * self.TILE_UNIT * 2,
            "height": height * self.TILE_UNIT * 2
        }

    def _transform_markdown_widget(
        self,
        widget: Dict[str, Any],
        tile: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Transform markdown widget."""
        raw_config = widget.get("rawConfiguration", {})
        text = raw_config.get("text", "")

        tile["tileType"] = "MARKDOWN"
        tile["markdown"] = text

        return tile

    def _transform_billboard_widget(
        self,
        widget: Dict[str, Any],
        tile: Dict[str, Any],
        warnings: List[str]
    ) -> Dict[str, Any]:
        """Transform billboard (single value) widget using the NRQL compiler."""
        raw_config = widget.get("rawConfiguration", {})
        nrql_queries = raw_config.get("nrqlQueries", [])

        tile["tileType"] = "DATA_EXPLORER"

        if nrql_queries:
            query = nrql_queries[0].get("query", "")
            title = widget.get("title", "Billboard")
            dql_result = self._convert_nrql_to_dql(query, title)

            tile["customName"] = title
            tile["queries"] = [{
                "id": "A",
                "enabled": True,
                "freeText": dql_result["dql"],
                "queryMetaData": {
                    "customName": title
                }
            }]

            if dql_result["warnings"]:
                warnings.extend(dql_result["warnings"])

            if not dql_result["fully_converted"]:
                warnings.append(
                    f"Billboard '{title}' converted with {dql_result.get('confidence', 'UNKNOWN')} "
                    f"confidence. Original NRQL: {query[:100]}..."
                )

        return tile

    def _transform_chart_widget(
        self,
        widget: Dict[str, Any],
        tile: Dict[str, Any],
        warnings: List[str]
    ) -> Dict[str, Any]:
        """Transform chart widgets (line, area, bar, etc.)."""
        raw_config = widget.get("rawConfiguration", {})
        nrql_queries = raw_config.get("nrqlQueries", [])

        tile["tileType"] = "DATA_EXPLORER"

        # Build data explorer configuration
        tile["customName"] = widget.get("title", "Chart")

        if nrql_queries:
            query = nrql_queries[0].get("query", "")

            # Convert NRQL to DQL using the AST compiler
            dql_result = self._convert_nrql_to_dql(query, widget.get("title", "Chart"))

            tile["queries"] = [{
                "id": "A",
                "enabled": True,
                "freeText": dql_result["dql"],
                "queryMetaData": {
                    "customName": widget.get("title", "Query A")
                }
            }]

            if dql_result["warnings"]:
                warnings.extend(dql_result["warnings"])

            if not dql_result["fully_converted"]:
                warnings.append(
                    f"Chart '{widget.get('title')}' NRQL query requires manual review. "
                    f"Original: {query[:100]}..."
                )

        return tile

    def _convert_nrql_to_dql(self, nrql: str, title: str = "") -> Dict[str, Any]:
        """
        Convert NRQL to DQL using the AST-based compiler.

        Uses a formal three-stage compiler (lexer/parser/AST/emitter)
        with 282 tested patterns including apdex, percentage, funnel,
        K8s metrics, subqueries, COMPARE WITH, and more.
        """
        result = self._nrql_converter.convert(nrql, title or "query")

        return {
            "dql": result.converted_dql,
            "warnings": result.warnings,
            "fully_converted": result.success and result.confidence == "HIGH",
            "confidence": result.confidence,
            "fixes_applied": result.fixes_applied,
        }

    def _transform_variables(self, variables: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Transform dashboard variables to Dynatrace filters."""
        filters = []
        tag_filters = []

        for var in variables:
            var_name = var.get("name", "")
            var_type = var.get("type", "")

            # Create a generic tag filter
            tag_filters.append({
                "name": var_name,
                "entityTypes": [],
                "tagFilter": True
            })

        return {
            "filters": filters,
            "genericTagFilters": tag_filters
        }

    def _map_permissions(self, permissions: Optional[str]) -> bool:
        """Map New Relic permissions to Dynatrace shared setting."""
        if not permissions:
            return False

        permission_map = {
            "PUBLIC_READ_ONLY": True,
            "PUBLIC_READ_WRITE": True,
            "PRIVATE": False
        }

        return permission_map.get(permissions, False)

    def transform_all(
        self,
        dashboards: List[Dict[str, Any]]
    ) -> List[TransformResult]:
        """Transform multiple dashboards."""
        all_results = []

        for dashboard in dashboards:
            results = self.transform(dashboard)
            all_results.extend(results)

        successful = sum(1 for r in all_results if r.success)
        logger.info(
            f"Transformed {successful}/{len(all_results)} dashboard pages"
        )

        return all_results
