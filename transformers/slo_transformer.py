"""
SLO Transformer — Gen3 target.

Emits Platform SLO API request bodies (`POST /platform/slo/v1/slos`) with a
DQL `customSli.indicator` grouped by `dt.smartscape.service`. The same body
is the Monaco `slo-v2` template and maps 1:1 onto the Terraform
`dynatrace_platform_slo` resource.

Classic `builtin:monitoring.slo` (metric-selector SLOs) is no longer emitted.
Legacy (Config v1 `/slo`) behavior is preserved in
`transformers/legacy/slo_transformer_v1.py`.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

from ._slo_utils import (
    DEFAULT_LATENCY_THRESHOLD_MS,
    availability_indicator,
    build_platform_slo,
    latency_indicator,
)
from .mapping_rules import SLO_TIME_UNIT_MAP

logger = structlog.get_logger()

_SERVICE_NAME_RE = re.compile(
    r"\b(?:appName|entityName|entity\.name|service\.name)\s*=\s*'([^']+)'", re.IGNORECASE
)
_DURATION_THRESHOLD_RE = re.compile(r"\bduration\s*<=?\s*([\d.]+)", re.IGNORECASE)


@dataclass
class SLOTransformResult:
    """Result of SLO transformation (Gen3 Platform SLO)."""

    success: bool
    slo: Optional[Dict[str, Any]] = None  # Platform SLO API request body
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class SLOTransformer:
    """
    Transforms New Relic Service Level Objectives to Dynatrace Platform SLOs.

    New Relic SLO concepts:
    - SLI (Service Level Indicator): Defined by good/valid events queries
    - SLO: Target percentage over a time window
    - Time Window: Rolling period (days, weeks, months)

    Dynatrace Platform SLO concepts:
    - customSli.indicator: DQL producing an `sli` percentage series
    - criteria: target / warning over a relative timeframe
    """

    def __init__(self):
        pass

    def transform(self, nr_slo: Dict[str, Any]) -> SLOTransformResult:
        """Transform a New Relic SLO to Dynatrace format."""
        warnings: List[str] = []
        errors: List[str] = []

        try:
            slo_name = nr_slo.get("name", "Unnamed SLO")
            description = nr_slo.get("description", "")

            objectives = nr_slo.get("objectives", [])
            if not objectives:
                errors.append(f"SLO '{slo_name}' has no objectives defined")
                return SLOTransformResult(success=False, errors=errors)

            objective = objectives[0]
            target = objective.get("target", 99.0)

            time_window = objective.get("timeWindow", {})
            rolling = time_window.get("rolling", {})
            window_count = rolling.get("count", 7)
            window_unit = rolling.get("unit", "DAY")

            events = nr_slo.get("events", {})

            dt_slo = self._build_dynatrace_slo(
                name=slo_name,
                description=description,
                target=target,
                window_count=window_count,
                window_unit=window_unit,
                events=events,
                warnings=warnings,
                guid=nr_slo.get("guid") or nr_slo.get("id"),
            )

            logger.info("Transformed SLO", name=slo_name, target=target)

            return SLOTransformResult(success=True, slo=dt_slo, warnings=warnings)

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
        warnings: List[str],
        guid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build a Platform SLO request body."""
        timeframe_from = self._build_timeframe(
            window_count, SLO_TIME_UNIT_MAP.get(window_unit, "DAY"), warnings
        )
        indicator = self._build_indicator(events, warnings)

        original = self._original_nrql(events)
        full_description = description or "Migrated from New Relic"
        if original:
            full_description += f"\n\n--- Original NR SLI ---\n{original}"

        return build_platform_slo(
            name=f"[Migrated] {name}",
            description=full_description,
            target=target,
            indicator=indicator,
            timeframe_from=timeframe_from,
            tags=["MigratedFromNR:true"],
            external_id=f"nr-slo-{guid}" if guid else None,
        )

    def _build_timeframe(self, count: int, unit: str, warnings: List[str]) -> str:
        """Relative DQL timeframe for the SLO criteria."""
        if unit == "WEEK":
            return f"now-{count}w"
        if unit == "MONTH":
            warnings.append(
                f"NR SLO window of {count} month(s) approximated as {count * 30} days."
            )
            return f"now-{count * 30}d"
        return f"now-{count}d"

    def _build_indicator(self, events: Dict[str, Any], warnings: List[str]) -> str:
        """DQL SLI from the NR good/valid events definition."""
        valid_query = (events.get("validEvents") or {}).get("where", "") or ""
        good_query = (events.get("goodEvents") or {}).get("where", "") or ""
        bad_query = (events.get("badEvents") or {}).get("where", "") or ""
        all_where = " ".join((valid_query, good_query, bad_query))

        service_name = self._extract_service_name(all_where)
        if not service_name:
            warnings.append(
                "Could not determine the service from the NR SLI; the indicator covers "
                "all services. Add a filter (e.g. contains(entityName, \"<service>\"))."
            )

        slo_type = self._detect_slo_type(valid_query, good_query)

        if slo_type in ("availability", "error_rate"):
            warnings.append(
                f"SLO appears to be {slo_type.replace('_', '-')} based. "
                "Using service success-rate SLI (dt.service.request.count / failure_count)."
            )
            return availability_indicator(service_name)

        if slo_type == "latency":
            threshold_ms = self._extract_latency_threshold_ms(good_query)
            if threshold_ms is None:
                threshold_ms = DEFAULT_LATENCY_THRESHOLD_MS
                warnings.append(
                    f"SLO appears to be latency-based but no duration threshold was found; "
                    f"defaulted to {threshold_ms}ms."
                )
            else:
                warnings.append(
                    f"SLO appears to be latency-based. Using {threshold_ms}ms response-time threshold."
                )
            return latency_indicator(threshold_ms, service_name)

        warnings.append(
            f"Could not automatically determine SLO type. "
            f"Original queries - Valid: {valid_query[:50]}..., Good: {good_query[:50]}... "
            "Defaulted to service success-rate SLI; manual review required."
        )
        return availability_indicator(service_name)

    @staticmethod
    def _extract_service_name(where: str) -> Optional[str]:
        match = _SERVICE_NAME_RE.search(where)
        return match.group(1) if match else None

    @staticmethod
    def _extract_latency_threshold_ms(good_query: str) -> Optional[int]:
        """NR `duration` is in seconds."""
        match = _DURATION_THRESHOLD_RE.search(good_query)
        if not match:
            return None
        return int(round(float(match.group(1)) * 1000))

    @staticmethod
    def _original_nrql(events: Dict[str, Any]) -> str:
        lines = []
        for key, label in (("validEvents", "Valid"), ("goodEvents", "Good"), ("badEvents", "Bad")):
            ev = events.get(key) or {}
            if ev.get("from") or ev.get("where"):
                lines.append(f"{label}: FROM {ev.get('from', '?')} WHERE {ev.get('where') or 'N/A'}")
        return "\n".join(lines)

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
