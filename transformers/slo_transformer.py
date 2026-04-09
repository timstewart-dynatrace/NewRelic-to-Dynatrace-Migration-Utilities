"""
SLO Transformer - Converts New Relic SLOs to Dynatrace format.
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass
import structlog

from .mapping_rules import SLO_TIME_UNIT_MAP

logger = structlog.get_logger()


@dataclass
class SLOTransformResult:
    """Result of SLO transformation."""
    success: bool
    slo: Optional[Dict[str, Any]] = None
    warnings: List[str] = None
    errors: List[str] = None

    def __post_init__(self):
        self.warnings = self.warnings or []
        self.errors = self.errors or []


class SLOTransformer:
    """
    Transforms New Relic Service Level Objectives to Dynatrace SLOs.

    New Relic SLO concepts:
    - SLI (Service Level Indicator): Defined by good/valid events queries
    - SLO: Target percentage over a time window
    - Time Window: Rolling period (days, weeks, months)

    Dynatrace SLO concepts:
    - SLO: Combined indicator and objective
    - Metric Expression: Defines the success rate calculation
    - Evaluation Type: Rolling or calendar-based
    """

    def __init__(self):
        pass

    def transform(self, nr_slo: Dict[str, Any]) -> SLOTransformResult:
        """Transform a New Relic SLO to Dynatrace format."""
        warnings = []
        errors = []

        try:
            slo_name = nr_slo.get("name", "Unnamed SLO")
            description = nr_slo.get("description", "")

            # Get objectives (targets)
            objectives = nr_slo.get("objectives", [])
            if not objectives:
                errors.append(f"SLO '{slo_name}' has no objectives defined")
                return SLOTransformResult(success=False, errors=errors)

            # Use the first objective
            objective = objectives[0]
            target = objective.get("target", 99.0)

            # Get time window
            time_window = objective.get("timeWindow", {})
            rolling = time_window.get("rolling", {})
            window_count = rolling.get("count", 7)
            window_unit = rolling.get("unit", "DAY")

            # Get events (SLI definition)
            events = nr_slo.get("events", {})

            # Build Dynatrace SLO
            dt_slo = self._build_dynatrace_slo(
                name=slo_name,
                description=description,
                target=target,
                window_count=window_count,
                window_unit=window_unit,
                events=events,
                warnings=warnings
            )

            logger.info(
                "Transformed SLO",
                name=slo_name,
                target=target
            )

            return SLOTransformResult(
                success=True,
                slo=dt_slo,
                warnings=warnings
            )

        except Exception as e:
            logger.error("SLO transformation failed", error=str(e))
            return SLOTransformResult(
                success=False,
                errors=[f"Transformation error: {str(e)}"]
            )

    def _build_dynatrace_slo(
        self,
        name: str,
        description: str,
        target: float,
        window_count: int,
        window_unit: str,
        events: Dict[str, Any],
        warnings: List[str]
    ) -> Dict[str, Any]:
        """Build a Dynatrace SLO configuration."""
        # Map time window unit
        dt_time_unit = SLO_TIME_UNIT_MAP.get(window_unit, "DAY")

        # Calculate timeframe string
        timeframe = self._build_timeframe(window_count, dt_time_unit)

        # Build metric expression from events
        metric_expression = self._build_metric_expression(events, warnings)

        dt_slo = {
            "name": f"[Migrated] {name}",
            "description": description or f"Migrated from New Relic",
            "metricName": self._sanitize_metric_name(name),
            "metricExpression": metric_expression,
            "evaluationType": "AGGREGATE",
            "filter": "",
            "target": target,
            "warning": target - 1.0,  # Warning at 1% below target
            "timeframe": timeframe,
            "enabled": True
        }

        return dt_slo

    def _build_timeframe(self, count: int, unit: str) -> str:
        """Build Dynatrace timeframe string."""
        # Dynatrace uses ISO 8601 duration format or relative strings
        unit_map = {
            "DAY": "d",
            "WEEK": "w",
            "MONTH": "M"
        }

        suffix = unit_map.get(unit, "d")
        return f"-{count}{suffix}"

    def _build_metric_expression(
        self,
        events: Dict[str, Any],
        warnings: List[str]
    ) -> str:
        """
        Build Dynatrace metric expression from New Relic events.

        New Relic SLI is typically: (good events / valid events) * 100

        Dynatrace metric expressions use DQL-like syntax.
        """
        valid_events = events.get("validEvents", {})
        good_events = events.get("goodEvents", {})
        bad_events = events.get("badEvents", {})

        valid_query = valid_events.get("where", "")
        good_query = good_events.get("where", "")
        bad_query = bad_events.get("where", "")

        # Analyze the queries to determine SLO type
        slo_type = self._detect_slo_type(valid_query, good_query)

        if slo_type == "availability":
            # Service availability SLO
            warnings.append(
                "SLO appears to be availability-based. Using builtin service availability metric."
            )
            return "(100)*(builtin:service.availability:filter(and(in(\"dt.entity.service\",entitySelector(\"type(service)\")))))"

        elif slo_type == "error_rate":
            # Error-based SLO
            warnings.append(
                "SLO appears to be error-rate based. Using builtin service error rate metric."
            )
            return "(100)*(builtin:service.errors.total.successRate:filter(and(in(\"dt.entity.service\",entitySelector(\"type(service)\")))))"

        elif slo_type == "latency":
            # Latency-based SLO
            warnings.append(
                "SLO appears to be latency-based. Manual configuration recommended for specific thresholds."
            )
            return "(100)*((builtin:service.response.time:avg:partition(\"latency\",value(\"good\",lt(1000000))):filter(and(in(\"dt.entity.service\",entitySelector(\"type(service)\"))))):splitBy():count:default(0))/(builtin:service.requestCount.total:filter(and(in(\"dt.entity.service\",entitySelector(\"type(service)\"))))):splitBy():sum)"

        else:
            # Generic placeholder
            warnings.append(
                f"Could not automatically determine SLO metric type. "
                f"Original queries - Valid: {valid_query[:50]}..., Good: {good_query[:50]}... "
                "Manual configuration required."
            )
            return "(100)*(builtin:service.availability)"

    def _detect_slo_type(self, valid_query: str, good_query: str) -> str:
        """Detect the type of SLO based on queries."""
        queries = (valid_query + " " + good_query).lower()

        if "error" in queries:
            return "error_rate"
        elif "duration" in queries or "latency" in queries or "response" in queries:
            return "latency"
        elif "status" in queries or "available" in queries:
            return "availability"
        else:
            return "unknown"

    def _sanitize_metric_name(self, name: str) -> str:
        """Sanitize SLO name for use as metric name."""
        # Replace spaces and special characters
        sanitized = name.lower()
        sanitized = sanitized.replace(" ", "_")
        sanitized = "".join(c if c.isalnum() or c == "_" else "" for c in sanitized)
        return f"slo.migrated.{sanitized}"

    def transform_all(
        self,
        slos: List[Dict[str, Any]]
    ) -> List[SLOTransformResult]:
        """Transform multiple SLOs."""
        results = []

        for slo in slos:
            result = self.transform(slo)
            results.append(result)

        successful = sum(1 for r in results if r.success)
        logger.info(f"Transformed {successful}/{len(results)} SLOs")

        return results
