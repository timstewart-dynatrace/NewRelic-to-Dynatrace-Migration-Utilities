"""Core NRQL-to-DQL converter using the AST compiler with post-processing.

This is the main conversion engine. It orchestrates:
  1. AST compiler (primary path) for structural correctness
  2. Post-AST cleanup for dashboard-specific adjustments
  3. Regex fallback (deprecated) for queries the AST can't handle yet
  4. DQL output sanitizer (final gate) for known-bad patterns
  5. Live DT Grail API validation (optional)
  6. SLO migration (optional)
"""

import base64 as b64
import json
import logging
import os
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from compiler import NRQLCompiler
from validators import DQLSyntaxValidator

from .nrql_mapping_rules import (
    AGG_MAP,
    ATTR_MAP,
    EVENT_TYPE_MAP,
    METRIC_MAP,
    METRIC_TRANSFORMS,
)

# DTEnvironmentRegistry is optional -- only used for live validation
try:
    from registry.environment import DTEnvironmentRegistry  # type: ignore[import-untyped]
except ImportError:
    DTEnvironmentRegistry = None  # type: ignore[misc,assignment]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SSL context for NR / DT API calls (used only inside this module)
# ---------------------------------------------------------------------------
_SSL_CONTEXT = ssl.create_default_context()
_SSL_CONTEXT.check_hostname = False
_SSL_CONTEXT.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------------------
# Utility helpers (module-private)
# ---------------------------------------------------------------------------

def _nrql_comment(nrql: str) -> str:
    """Format NRQL as a safe single-line DQL comment.

    Multi-line NRQL must be collapsed to one line so continuation lines
    don't leak raw NRQL code into the DQL body (DT would try to parse them).
    """
    return "// Original NRQL: " + " ".join(nrql.split())


def _ms_to_dql_duration(ms: float) -> str:
    """Convert milliseconds to the most readable DQL duration literal.

    DQL duration type requires literals like 2s, 500ms, 1m -- NOT raw
    nanosecond integers.
    Examples: 2000 -> '2s', 500 -> '500ms', 60000 -> '1m', 0.5 -> '500us'
    """
    if ms <= 0:
        return "0s"
    if ms >= 86_400_000 and ms % 86_400_000 == 0:
        return f"{int(ms // 86_400_000)}d"
    if ms >= 3_600_000 and ms % 3_600_000 == 0:
        return f"{int(ms // 3_600_000)}h"
    if ms >= 60_000 and ms % 60_000 == 0:
        return f"{int(ms // 60_000)}m"
    if ms >= 1000 and ms % 1000 == 0:
        return f"{int(ms // 1000)}s"
    if ms == int(ms):
        return f"{int(ms)}ms"
    us = ms * 1000
    if us == int(us):
        return f"{int(us)}us"
    return f"{ms}ms"


# ---------------------------------------------------------------------------
# Stub classes for converters not yet extracted into the package.
# These will be replaced once the converter classes are moved to
# nrql_migrator/transformers/converters.py
# ---------------------------------------------------------------------------

class _StubConverter:
    """No-op stub for converters not yet wired into the package."""

    def convert(self, *args, **kwargs):
        return None

    def convert_rate(self, *args, **kwargs):
        return None

    def convert_derivative(self, *args, **kwargs):
        return None

    def handle(self, *args, **kwargs):
        return (False, args[1] if len(args) > 1 else "", None)


def _load_converters():
    """Try to import extracted converter classes; fall back to stubs."""
    try:
        from .converters import (  # type: ignore[import-untyped]
            AparseConverter,
            BucketPercentileConverter,
            CompareWithConverter,
            ExtrapolateHandler,
            FunnelConverter,
            RateDerivativeConverter,
            RegexToDPLConverter,
            WithAsConverter,
        )
        return {
            "regex_to_dpl": RegexToDPLConverter,
            "aparse": AparseConverter,
            "rate": RateDerivativeConverter,
            "compare": CompareWithConverter,
            "funnel": FunnelConverter,
            "extrapolate": ExtrapolateHandler,
            "bucket_percentile": BucketPercentileConverter,
            "with_as": WithAsConverter,
        }
    except ImportError:
        logger.debug("Converter classes not yet extracted -- using stubs")
        return None


# ---------------------------------------------------------------------------
# Stub for DQLValidator (the *fixer* class, distinct from DQLSyntaxValidator)
# ---------------------------------------------------------------------------

class _DQLValidatorStub:
    """Minimal stub for the DQL fixer until it is extracted."""

    def validate_and_fix(self, dql: str, context: str = "") -> Tuple[str, List[str]]:
        return dql, []

    # Attribute-level stubs used by _attempt_dql_fix
    def _fix_as_aliases(self, dql: str) -> str:
        return dql

    def _fix_percentile_naming(self, dql: str) -> str:
        return dql

    def _fix_nrql_subqueries(self, dql: str) -> str:
        return dql


def _load_dql_validator():
    """Try to import the extracted DQLValidator (fixer); fall back to stub."""
    try:
        from validators.dql_fixer import DQLValidator  # type: ignore[import-untyped]
        return DQLValidator
    except ImportError:
        logger.debug("DQLValidator (fixer) not yet extracted -- using stub")
        return _DQLValidatorStub


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ConversionResult:
    """Result of a single NRQL to DQL conversion."""

    original_nrql: str
    dql: str
    fixes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    confidence: str = "HIGH"  # HIGH, MEDIUM, LOW
    success: bool = True


# ============================================================================
# NRQLtoDQLConverter
# ============================================================================

class NRQLtoDQLConverter:
    """Converts NRQL queries to DQL with built-in validation and SLO migration."""

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def __init__(self, registry: "DTEnvironmentRegistry" = None):
        # Load the DQL fixer (validate_and_fix)
        DQLValidatorCls = _load_dql_validator()
        self.validator = DQLValidatorCls()

        self._guid_cache: Dict[str, str] = {}   # Maps GUID -> entity name/details
        self._guid_types: Dict[str, str] = {}   # Maps GUID -> entity type
        self._detected_slos: set = set()         # Track all SERVICE_LEVEL GUIDs

        # Shared environment registry for live metric + entity validation
        self._registry = registry

        # AST compiler -- primary conversion path
        self._ast_compiler = NRQLCompiler(
            field_map=ATTR_MAP,
            metric_map=METRIC_MAP,
            metric_transforms=METRIC_TRANSFORMS,
            metric_resolver=self._live_metric_resolver,
        )

        # Advanced converters -- DPL, rate, COMPARE WITH, funnel, etc.
        _converters = _load_converters()
        if _converters:
            self._regex_to_dpl = _converters["regex_to_dpl"]()
            self._aparse_converter = _converters["aparse"]()
            self._rate_converter = _converters["rate"]()
            self._compare_converter = _converters["compare"]()
            self._funnel_converter = _converters["funnel"]()
            self._with_as_converter = _converters["with_as"]()
            self._extrapolate_handler = _converters["extrapolate"]()
            self._bucket_percentile_converter = _converters["bucket_percentile"]()
        else:
            stub = _StubConverter()
            self._regex_to_dpl = stub
            self._aparse_converter = stub
            self._rate_converter = stub
            self._compare_converter = stub
            self._funnel_converter = stub
            self._with_as_converter = stub
            self._extrapolate_handler = stub
            self._bucket_percentile_converter = stub

        # SLO migration config
        self._nr_api_key: Optional[str] = os.environ.get("NR_API_KEY", None)
        self._dt_url: Optional[str] = None
        self._dt_token: Optional[str] = None
        self._auto_create_slos: bool = False
        self._created_slos: Dict[str, str] = {}     # GUID -> DT SLO ID
        self._slo_details_cache: Dict[str, Dict] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_registry(self, registry: "DTEnvironmentRegistry"):
        """Set or update the environment registry for live validation."""
        self._registry = registry

    def configure_slo_migration(
        self,
        nr_api_key: str = None,
        dt_url: str = None,
        dt_token: str = None,
        auto_create: bool = False,
    ):
        """Configure automatic SLO migration when SERVICE_LEVEL GUIDs are detected.

        Args:
            nr_api_key: New Relic API key for fetching SLO definitions
            dt_url: Dynatrace environment URL (e.g., https://xyz.apps.dynatrace.com)
            dt_token: Dynatrace API token with slo.write permission
            auto_create: If True, automatically create SLOs in DT when detected
        """
        self._nr_api_key = nr_api_key
        self._dt_url = dt_url.rstrip("/") if dt_url else None
        self._dt_token = dt_token
        self._auto_create_slos = auto_create

    def load_guid_mappings(self, mappings: Dict[str, str], types: Dict[str, str] = None):
        """Load pre-resolved GUID to entity name mappings.

        Args:
            mappings: Dict mapping GUID -> entity name (or other identifier)
            types: Optional dict mapping GUID -> entity type
        """
        self._guid_cache.update(mappings)
        if types:
            self._guid_types.update(types)

    def resolve_guids_from_api(self, api_key: str, guids: List[str] = None):
        """Resolve GUIDs by querying New Relic NerdGraph API.

        If guids is None, will use any GUIDs seen during conversion.
        Results are cached for use in subsequent conversions.
        """
        if not guids:
            return

        query = """
        query ($guids: [EntityGuid]!) {
          actor {
            entities(guids: $guids) {
              guid
              name
              entityType
              domain
            }
          }
        }
        """

        # Process in batches of 25
        for i in range(0, len(guids), 25):
            batch = guids[i : i + 25]
            payload = json.dumps({"query": query, "variables": {"guids": batch}}).encode("utf-8")
            headers = {"Content-Type": "application/json", "API-Key": api_key}

            try:
                req = urllib.request.Request("https://api.newrelic.com/graphql", data=payload, headers=headers)
                with urllib.request.urlopen(req, timeout=30, context=_SSL_CONTEXT) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    if "data" in data and "actor" in data["data"]:
                        for entity in data["data"]["actor"].get("entities", []):
                            if entity and entity.get("name"):
                                self._guid_cache[entity["guid"]] = entity["name"]
            except Exception as e:
                logger.warning("Could not resolve GUIDs from API: %s", e)

    # ------------------------------------------------------------------
    # Main conversion entry point
    # ------------------------------------------------------------------

    def convert(self, nrql: str, title: str = "") -> ConversionResult:
        """Convert NRQL to DQL with automatic validation and fixing.

        Returns ConversionResult with all details.
        """
        # Initialize per-query state
        self._current_warnings: List[str] = []
        self._current_original_nrql = nrql  # Preserved for SLI detection

        result = ConversionResult(
            original_nrql=nrql,
            dql="",
            fixes=[],
            warnings=[],
            confidence="HIGH",
            success=True,
        )

        if not nrql or not nrql.strip():
            result.dql = "// Empty query"
            result.confidence = "LOW"
            return result

        original_nrql = nrql

        # =================================================================
        # PRIMARY (AND ONLY) PATH: AST Compiler
        # =================================================================
        nrql_clean = " ".join(nrql.split())
        nrql_upper = nrql_clean.upper()

        if self._ast_compiler:
            ast_result = self._ast_compiler.compile(nrql_clean, title)

            if ast_result.success:
                result.dql = ast_result.dql
                result.confidence = ast_result.confidence
                result.warnings = list(ast_result.warnings)
                result.fixes = list(ast_result.fixes)

                # POST-AST: Apply features the emitter doesn't handle inline
                dql = ast_result.dql

                # COMPARE WITH -> shift: param or extended timeframe
                if "COMPARE WITH" in nrql_upper:
                    compare_result = self._compare_converter.convert(nrql_clean)
                    if compare_result:
                        _, shift_param = compare_result
                        if "timeseries" in dql.lower() and "maketimeseries" not in dql.lower():
                            dql = re.sub(
                                r"(timeseries\s+[^\n]+)",
                                lambda m: f"{m.group(1)}, {shift_param}",
                                dql,
                                count=1,
                            )
                            result.warnings.append(f"COMPARE WITH -> {shift_param}")
                        else:
                            shift_match = re.search(r"shift:-?(\d+\w+)", shift_param)
                            period = shift_match.group(1) if shift_match else "7d"
                            dql = re.sub(
                                r"(fetch\s+\w+)",
                                lambda m: f"{m.group(1)}, from:now()-{period}",
                                dql,
                                count=1,
                            )
                            result.warnings.append(
                                f"COMPARE WITH -> tile timeframe extended to {period} "
                                "(makeTimeseries does not support shift:)"
                            )

                # EXTRAPOLATE -> extrapolate:true on countDistinct
                if "EXTRAPOLATE" in nrql_upper:
                    _, dql, extrap_note = self._extrapolate_handler.handle(nrql, dql)
                    if extrap_note:
                        result.warnings.append(extrap_note)

                result.dql = dql

                # Collect any warnings from sub-methods
                if self._current_warnings:
                    result.warnings.extend(self._current_warnings)

                # PHASE 0: GUID Resolution
                if result.dql:
                    result.dql = self._resolve_guids_in_dql(result.dql, result)

                # PHASE 1: Minimal post-AST processing
                if result.dql:
                    result.dql, post_fixes = self._post_ast_cleanup(result.dql)
                    if post_fixes:
                        result.fixes.extend(post_fixes)

                # PHASE 2: Live DT Grail API validation
                if self._registry and result.dql:
                    result.dql = self._validate_dql_live(result.dql, result)

                return result

            # AST compilation failed -- mark for manual review
            _ast_error = ast_result.error or "Unknown AST error"
            result.warnings.append(f"AST compiler failed: {_ast_error}")
            result.confidence = "LOW"
            logger.warning("AST FAILURE -- needs compiler fix: %s | NRQL: %s", _ast_error, nrql[:300])

        # =================================================================
        # FALLBACK: Regex-based conversion (DEPRECATED -- USE IS TRACKED)
        # =================================================================
        result.confidence = "LOW"
        if "AST compiler failed" not in str(result.warnings):
            result.warnings.append("No AST compiler available -- regex fallback used")

        # PRE-CHECK: Handle NR-specific complex functions
        converted_complex: List[str] = []

        # Convert percentage(count(*), WHERE condition)
        if re.search(r"\bpercentage\s*\(", nrql_clean, re.IGNORECASE):
            nrql_clean = self._convert_percentage_function(nrql_clean)
            converted_complex.append("percentage() -> countIf()/count()*100")

        # Convert filter(func, WHERE condition)
        if re.search(r"\bfilter\s*\(", nrql_clean, re.IGNORECASE):
            nrql_clean = self._convert_filter_function(nrql_clean)
            converted_complex.append("filter() -> funcIf()")

        # Convert apdex(t:threshold)
        if re.search(r"\bapdex\s*\(", nrql_clean, re.IGNORECASE):
            nrql_clean = self._convert_apdex_function(nrql_clean)
            converted_complex.append("apdex() -> calculated formula")

        # Convert cdfPercentage(field, t1, t2, t3, t4)
        if re.search(r"\bcdfPercentage\s*\(", nrql_clean, re.IGNORECASE):
            nrql_clean = self._convert_cdf_percentage_function(nrql_clean)
            converted_complex.append("cdfPercentage() -> countIf() buckets")

        # SPECIAL CASE: histogram() queries
        histogram_match = re.search(
            r"\bhistogram\s*\(\s*([^,\)]+)(?:\s*,\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)(?:\s*,\s*(\d+(?:\.\d+)?))?)?\s*\)",
            nrql_clean,
            re.IGNORECASE,
        )
        if histogram_match:
            hist_field = histogram_match.group(1).strip()
            if hist_field.lower() == "duration.ms":
                hist_field = "duration"

            ceiling = histogram_match.group(2)
            num_bars = histogram_match.group(3)
            explicit_width = histogram_match.group(4)

            if explicit_width:
                bin_width = int(float(explicit_width))
            elif ceiling and num_bars:
                bin_width = int(float(ceiling) / float(num_bars))
            else:
                bin_width = 1000

            if hist_field == "duration":
                bin_expr = _ms_to_dql_duration(bin_width)
            else:
                bin_expr = str(bin_width)

            where_match = re.search(
                r"\bWHERE\s+(.+?)(?:\s+(?:SINCE|UNTIL|TIMESERIES|FACET|LIMIT|ORDER|COMPARE)|\s*$)",
                nrql_clean,
                re.IGNORECASE,
            )
            where_clause = where_match.group(1) if where_match else ""
            converted_where = self._convert_where(where_clause) if where_clause else ""

            if hist_field == "duration" and converted_where:
                def _dur_lit(m):
                    op, val = m.group(1), float(m.group(2))
                    return f"duration {op} {_ms_to_dql_duration(val)}"

                converted_where = re.sub(
                    r"(?<![.\w])duration\s*(>=|<=|>|<|==|!=)\s*(\d+(?:\.\d+)?)",
                    _dur_lit,
                    converted_where,
                )

            event_type = self._extract_from(nrql_clean)
            dt_source = self._map_event_type(event_type) if event_type else "spans"

            dql_parts = [f"fetch {dt_source}"]
            if converted_where:
                dql_parts.append(f"| filter {converted_where}")
            dql_parts.append(f"| summarize count(), by: {{bin({hist_field}, {bin_expr})}}")

            dql = "\n".join(dql_parts)
            result.dql = f"{_nrql_comment(original_nrql)}\n{dql}"
            result.confidence = "HIGH"
            result.warnings.append("histogram() -> count() + bin() as categoricalBarChart visualization")
            return result

        if converted_complex:
            result.warnings.extend(converted_complex)

        try:
            # PREPROCESS: Convert NR-specific syntax before parsing
            nrql_clean = self._preprocess_nrql(nrql_clean)

            # Parse NRQL components
            event_type = self._extract_from(nrql_clean)
            select_clause = self._extract_select(nrql_clean)
            where_clause = self._extract_where(nrql_clean)
            facet_clause = self._extract_facet(nrql_clean)
            limit_value = self._extract_limit(nrql_clean)
            has_timeseries = bool(re.search(r"\bTIMESERIES\b", nrql_clean, re.IGNORECASE))
            has_compare = bool(re.search(r"\bCOMPARE\s+WITH\b", nrql_clean, re.IGNORECASE))

            # === ADVANCED PRE-PROCESSING ===
            self._current_rate_params: List[str] = []
            self._current_shift_param: Optional[str] = None
            self._current_funnel_result = None

            # 1. Handle COMPARE WITH
            if has_compare:
                compare_result = self._compare_converter.convert(nrql_clean)
                if compare_result:
                    nrql_clean, self._current_shift_param = compare_result
                    select_clause = self._extract_select(nrql_clean)
                    where_clause = self._extract_where(nrql_clean)
                    facet_clause = self._extract_facet(nrql_clean)
                    has_timeseries = True

            # 2. Handle EXTRAPOLATE
            has_extrapolate = "EXTRAPOLATE" in nrql_clean.upper()
            if has_extrapolate:
                nrql_clean = re.sub(r"\s+EXTRAPOLATE\s*", " ", nrql_clean, flags=re.IGNORECASE).strip()
                select_clause = self._extract_select(nrql_clean)

            # 3. Handle funnel()
            if "funnel(" in nrql_clean.lower():
                funnel_result = self._funnel_converter.convert(nrql_clean)
                if funnel_result:
                    result.dql = (
                        f"{_nrql_comment(original_nrql)}\n// {funnel_result['note']}\n{funnel_result['usql']}"
                    )
                    result.confidence = "MEDIUM"
                    result.warnings.append(f"funnel() -> USQL: {funnel_result['note']}")
                    return result

            # 4. Handle WITH...AS (CTEs)
            if re.match(r"\s*WITH\s+", nrql_clean, re.IGNORECASE):
                cte_result = self._with_as_converter.convert(nrql_clean)
                if cte_result:
                    result.dql = f"{_nrql_comment(original_nrql)}\n{cte_result['dql']}"
                    result.confidence = "MEDIUM" if cte_result["strategy"] == "inline" else "LOW"
                    if cte_result.get("note"):
                        result.warnings.append(cte_result["note"])
                    result.warnings.append(f"WITH...AS converted via {cte_result['strategy']} strategy")
                    return result

            if not event_type:
                result.dql = f"// Could not parse event type from: {original_nrql}"
                result.confidence = "LOW"
                result.warnings.append("Could not determine event type")
                return result

            # Map event type to DT source
            dt_source = self._map_event_type(event_type)

            # Build DQL based on query type
            if dt_source == "METRIC":
                dql, confidence = self._build_metric_query(
                    select_clause, where_clause, facet_clause, has_timeseries, title
                )
            elif dt_source.startswith("K8S_"):
                dql, confidence = self._build_k8s_metric_query(
                    dt_source, select_clause, where_clause, facet_clause, has_timeseries, title
                )
            elif dt_source == "events":
                dql, confidence = self._build_events_query(
                    select_clause, where_clause, facet_clause, limit_value, title
                )
            else:
                dql, confidence = self._build_fetch_query(
                    dt_source, select_clause, where_clause, facet_clause,
                    limit_value, has_timeseries, title, nrql_clean,
                )

            result.confidence = confidence

            # Validate and fix DQL syntax issues
            dql, fixes = self.validator.validate_and_fix(dql, title)
            result.fixes = fixes

            # Check original NRQL for NR-specific features that need manual conversion
            nrql_lower = nrql.lower()
            warnings_to_add: List[str] = []

            if "newrelic.sli." in nrql_lower or "sli.good" in nrql_lower or "sli.valid" in nrql_lower:
                warnings_to_add.append("// NOTE: NR SLI metrics converted to DT SLO query - verify slo.name filter")
                result.warnings.append("NR SLI metrics converted to DT SLO query")

            if "clamp_max(" in nrql_lower or "clamp_min(" in nrql_lower:
                warnings_to_add.append("// NOTE: clamp_max/clamp_min converted to if() - verify logic")
                result.warnings.append("clamp functions converted to if() expressions")

            if "compare with" in nrql_lower:
                if self._current_shift_param:
                    if "timeseries" in dql.lower() and "maketimeseries" not in dql.lower():
                        dql = re.sub(
                            r"(timeseries\s+[^\n]+)",
                            lambda m: f"{m.group(1)}, {self._current_shift_param}",
                            dql,
                            count=1,
                        )
                        warnings_to_add.append(f"// NOTE: COMPARE WITH -> {self._current_shift_param}")
                        result.warnings.append(f"COMPARE WITH -> {self._current_shift_param} on timeseries")
                    else:
                        shift_match = re.search(r"shift:-?(\d+\w+)", self._current_shift_param)
                        period = shift_match.group(1) if shift_match else "7d"
                        dql = re.sub(
                            r"(fetch\s+\w+)",
                            lambda m: f"{m.group(1)}, from:now()-{period}",
                            dql,
                            count=1,
                        )
                        warnings_to_add.append(f"// NOTE: COMPARE WITH -> tile timeframe extended to {period}")
                        result.warnings.append(f"COMPARE WITH -> tile timeframe extended to {period}")
                else:
                    dql = re.sub(
                        r"(fetch\s+\w+)",
                        lambda m: f"{m.group(1)}, from:now()-7d",
                        dql,
                        count=1,
                    )
                    warnings_to_add.append("// NOTE: COMPARE WITH -> tile timeframe extended to 7d")
                    result.warnings.append("COMPARE WITH -> tile timeframe extended to 7d")

            # Apply rate: params if any were collected
            if hasattr(self, "_current_rate_params") and self._current_rate_params:
                for rate_param in self._current_rate_params:
                    if "timeseries" in dql.lower() and "maketimeseries" not in dql.lower():
                        dql = re.sub(
                            r"(timeseries\s+[^\n]+)",
                            lambda m, rp=rate_param: f"{m.group(1)}, {rp}",
                            dql,
                            count=1,
                        )
                    else:
                        warnings_to_add.append(
                            f"// NOTE: rate: not supported on makeTimeseries. Original rate conversion: {rate_param}"
                        )

            # Apply EXTRAPOLATE post-processing
            if has_extrapolate:
                _, dql, extrap_note = self._extrapolate_handler.handle(nrql, dql)
                if extrap_note:
                    warnings_to_add.append(f"// NOTE: {extrap_note}")
                    result.warnings.append(extrap_note)

            # Add original NRQL as comment
            if warnings_to_add:
                dql = "\n".join(warnings_to_add) + f"\n{_nrql_comment(original_nrql)}\n{dql}"
            else:
                dql = f"{_nrql_comment(original_nrql)}\n{dql}"

            result.dql = dql

            # VALIDATE the converted DQL -- Phase 1: local regex-based checks
            syntax_validator = DQLSyntaxValidator()
            validation = syntax_validator.validate(dql)

            if not validation.valid:
                result.success = False
                result.confidence = "LOW"
                for err in validation.errors:
                    result.warnings.append(f"DQL Syntax Error: {err.message}")

        except Exception as e:
            result.dql = f"// Conversion error: {str(e)}\n// Original: {original_nrql}"
            result.confidence = "LOW"
            result.warnings.append(f"Conversion error: {str(e)}")
            result.success = False

        # Collect any warnings from sub-methods
        if self._current_warnings:
            result.warnings.extend(self._current_warnings)

        # =================================================================
        # PHASE 1: DQL Output Sanitizer (fix known bad patterns)
        # =================================================================
        if result.dql:
            result.dql, sanitize_fixes = self._sanitize_dql_output(result.dql)
            if sanitize_fixes:
                result.fixes.extend(sanitize_fixes)

        # =================================================================
        # PHASE 2: Live DT Grail API validation
        # =================================================================
        if self._registry and result.dql:
            dql_clean = "\n".join(
                line
                for line in result.dql.split("\n")
                if line.strip() and not line.strip().startswith("//")
            ).strip()
            if dql_clean:
                result.dql = self._validate_dql_live(result.dql, result)

        return result

    # ------------------------------------------------------------------
    # Live validation helpers
    # ------------------------------------------------------------------

    def _validate_dql_live(self, dql: str, result: ConversionResult, max_retries: int = 2) -> str:
        """Validate DQL against the live Dynatrace Grail API.

        If syntax errors are detected, attempt targeted auto-fix and re-validate.
        Returns the (possibly fixed) DQL string.
        """
        if not self._registry:
            return dql

        current_dql = dql

        for attempt in range(max_retries + 1):
            is_valid, error_msg, error_details = self._registry.validate_dql_syntax(current_dql)

            if is_valid is None:
                return current_dql

            if is_valid:
                if attempt > 0:
                    result.fixes.append(f"DQL live-validated after {attempt} auto-fix(es)")
                return current_dql

            # Invalid -- try to auto-fix
            if attempt < max_retries:
                parsed = self._registry.parse_dql_error(error_msg)
                fixed_dql = self._attempt_dql_fix(current_dql, parsed, error_msg)

                if fixed_dql and fixed_dql != current_dql:
                    result.fixes.append(
                        f"Live validation fix (attempt {attempt + 1}): "
                        f"{parsed['error_type']} -- {parsed.get('suggestion', error_msg[:80])}"
                    )
                    current_dql = fixed_dql
                    continue

            # Exhausted retries or no fix found
            result.warnings.append(f"DT API syntax error: {error_msg}")
            result.confidence = "LOW"
            error_comment = f"// WARNING: DT VALIDATION ERROR: {error_msg[:120]}"
            if error_comment not in current_dql:
                current_dql = error_comment + "\n" + current_dql
            break

        return current_dql

    def _attempt_dql_fix(self, dql: str, parsed_error: Dict, raw_error: str) -> Optional[str]:
        """Attempt to fix DQL based on parsed error from the DT API.

        Returns fixed DQL or None if no fix is possible.
        """
        error_type = parsed_error.get("error_type", "")
        bad_token = parsed_error.get("bad_token", "")
        # suggestion = parsed_error.get("suggestion", "")

        fixed = dql

        if error_type == "syntax" and bad_token.lower() == "as":
            validator = _DQLValidatorStub()
            try:
                DQLValidatorCls = _load_dql_validator()
                validator = DQLValidatorCls()
            except Exception:
                pass
            fixed = validator._fix_as_aliases(fixed)
            fixed = re.sub(
                r"(\w+\([^)]*\))\s+as\s+\"?(\w+)\"?",
                lambda m: f"{m.group(2)}={m.group(1)}",
                fixed,
                flags=re.IGNORECASE,
            )

        elif error_type == "parameter":
            validator = _DQLValidatorStub()
            try:
                DQLValidatorCls = _load_dql_validator()
                validator = DQLValidatorCls()
            except Exception:
                pass
            fixed = validator._fix_percentile_naming(fixed)

            def name_agg(match):
                func = match.group(1)
                args = match.group(2)
                name = func.lower()
                if "," in args:
                    parts = args.split(",")
                    if len(parts) == 2 and parts[1].strip().isdigit():
                        name = f"p{parts[1].strip()}"
                return f"{name}={func}({args})"

            lines = fixed.split("\n")
            new_lines = []
            for line in lines:
                if ("makeTimeseries" in line or "summarize" in line) and "(" in line:
                    def safe_name_agg(m):
                        inner = re.match(r"(\w+)\((.+)\)", m.group(1))
                        if inner:
                            return name_agg(inner)
                        return m.group(0)

                    line = re.sub(
                        r"(?<!=)((?:avg|sum|min|max|count|percentile|countIf|countDistinct)\s*\([^)]+,[^)]+\))",
                        safe_name_agg,
                        line,
                    )
                new_lines.append(line)
            fixed = "\n".join(new_lines)

        elif error_type == "function" and bad_token:
            func_map = {
                "takeLast": "last",
                "takeFirst": "first",
                "countif": "countIf",
                "avgif": "avgIf",
                "sumif": "sumIf",
                "isnull": "isNull",
                "isnotnull": "isNotNull",
                "tostring": "toString",
                "toint": "toInt",
                "todouble": "toDouble",
            }
            replacement = func_map.get(bad_token.lower(), "")
            if replacement:
                fixed = re.sub(
                    rf"\b{re.escape(bad_token)}\s*\(",
                    f"{replacement}(",
                    fixed,
                    flags=re.IGNORECASE,
                )

        elif error_type == "column" and bad_token:
            column_fix_map = {
                "parentId": "span.parent_id",
                "parentid": "span.parent_id",
                "id": "span.id",
                "guid": "span.id",
                "traceId": "trace_id",
                "traceid": "trace_id",
                "Duration.Seconds": "duration",
                "duration.seconds": "duration",
                "Duration.Ms": "duration",
                "duration.ms": "duration",
                "durationMs": "duration",
                "name": "span.name",
                "transactionName": "span.name",
                "transactionname": "span.name",
                "appName": "service.name",
                "appname": "service.name",
                "entityName": "entity.name",
                "entityname": "entity.name",
                "entityGuid": "dt.entity.service",
                "httpResponseCode": "http.response.status_code",
                "httpresponsecode": "http.response.status_code",
                "http.statusCode": "http.response.status_code",
                "http.statuscode": "http.response.status_code",
                "httpMethod": "http.request.method",
                "httpmethod": "http.request.method",
                "request.uri": "http.request.path",
                "request.url": "http.request.path",
                "host": "host.name",
                "hostname": "host.name",
                "fullHostname": "host.name",
                "k8s.containerName": "k8s.container.name",
                "k8s.podName": "k8s.pod.name",
                "k8s.clusterName": "k8s.cluster.name",
                "k8s.namespaceName": "k8s.namespace.name",
                "clusterName": "k8s.cluster.name",
                "podName": "k8s.pod.name",
                "message": "content",
                "level": "loglevel",
                "log.level": "loglevel",
                "pageUrl": "page.url",
                "userAgentName": "browser.name",
                "userAgentOS": "os.name",
                "city": "geo.city",
                "countryCode": "geo.country",
                "deviceType": "device.type",
            }

            replacement = column_fix_map.get(bad_token)
            if not replacement:
                replacement = column_fix_map.get(bad_token.lower())

            if replacement:
                fixed = re.sub(
                    r"(?<![.\w])" + re.escape(bad_token) + r"(?![.\w])",
                    replacement,
                    fixed,
                )
            elif self._registry:
                entity = self._registry.find_metric(bad_token)
                if entity:
                    fixed = fixed.replace(bad_token, entity)

        # Generic fixes for common patterns in error messages
        if "SELECT" in raw_error or "FROM" in raw_error.split("'")[0:1]:
            validator = _DQLValidatorStub()
            try:
                DQLValidatorCls = _load_dql_validator()
                validator = DQLValidatorCls()
            except Exception:
                pass
            fixed = validator._fix_nrql_subqueries(fixed)

        return fixed if fixed != dql else None

    # ------------------------------------------------------------------
    # Metric / entity validation
    # ------------------------------------------------------------------

    def _validate_dt_metric(self, metric_key: str, source_field: str = "") -> Tuple[str, Optional[str]]:
        """Validate a DT metric key against the live environment registry."""
        if not self._registry:
            return metric_key, None

        if self._registry.metric_exists(metric_key):
            return metric_key, None

        corrected = self._registry.find_metric(metric_key)
        if corrected:
            info = self._registry.get_metric_info(corrected)
            display = info["displayName"] if info else ""
            source_hint = f" (from NR field '{source_field}')" if source_field else ""
            warning = (
                f"Metric '{metric_key}' not found in environment{source_hint} -> "
                f"auto-corrected to '{corrected}' ({display})"
            )
            return corrected, warning
        else:
            source_hint = f" (from NR field '{source_field}')" if source_field else ""
            warning = f"Metric '{metric_key}' not found in environment{source_hint} -- no close match"
            return metric_key, warning

    def _validate_entity_name(self, name: str, entity_type: str = "SERVICE") -> Tuple[str, Optional[str]]:
        """Validate an entity name against the live environment registry."""
        if not self._registry:
            return name, None

        entity = self._registry.find_entity(name, entity_type)
        if entity:
            dt_name = entity["name"]
            if dt_name.lower() == name.lower():
                return dt_name, None
            else:
                warning = f"Entity '{name}' matched to DT entity '{dt_name}' (fuzzy match)"
                return dt_name, warning
        else:
            warning = f"Entity '{name}' not found in DT environment as {entity_type}"
            return name, warning

    def _live_metric_resolver(
        self,
        field_key: str,
        raw_field: str,
        static_mapped: str = None,
    ) -> Tuple[str, Optional[str]]:
        """Bridge method called by the AST compiler's DQLEmitter to resolve metrics."""
        if static_mapped:
            validated, warning = self._validate_dt_metric(static_mapped, raw_field)
            return validated, warning

        if self._registry:
            corrected = self._registry.find_metric(raw_field)
            if corrected:
                info = self._registry.get_metric_info(corrected)
                display = info["displayName"] if info else ""
                warning = f"No METRIC_MAP entry for '{raw_field}' -> live-resolved to '{corrected}' ({display})"
                return corrected, warning

        return None, None

    def _resolve_metric(self, field_key: str, raw_field: str = "") -> Tuple[Optional[str], Optional[str]]:
        """Resolve an NR field to a validated DT metric."""
        dt_metric = METRIC_MAP.get(field_key)

        if dt_metric:
            validated, warning = self._validate_dt_metric(dt_metric, raw_field)
            return validated, warning

        if raw_field and (raw_field.startswith("dt.") or raw_field.startswith("builtin:")):
            validated, warning = self._validate_dt_metric(raw_field, raw_field)
            return validated, warning

        return None, None

    # ------------------------------------------------------------------
    # SLO migration helpers
    # ------------------------------------------------------------------

    def _fetch_slo_details_from_nr(self, guid: str) -> Optional[Dict]:
        """Fetch full SLO definition from New Relic for a specific GUID."""
        if not self._nr_api_key:
            logger.debug("No NR API key configured, cannot fetch SLO details for %s", guid[:30])
            return None

        logger.info("Fetching SLO details from NR for %s...", guid[:30])

        if guid in self._slo_details_cache:
            return self._slo_details_cache[guid]

        query = '''
        {
          actor {
            entity(guid: "%s") {
              guid
              name
              entityType
              tags { key values }
            }
          }
        }
        ''' % guid

        try:
            payload = json.dumps({"query": query}).encode("utf-8")
            headers = {"Content-Type": "application/json", "API-Key": self._nr_api_key}

            req = urllib.request.Request("https://api.newrelic.com/graphql", data=payload, headers=headers)
            with urllib.request.urlopen(req, timeout=30, context=_SSL_CONTEXT) as response:
                data = json.loads(response.read().decode("utf-8"))

                if "errors" in data:
                    logger.debug("NR API returned errors: %s", str(data["errors"])[:200])

                actor_data = data.get("data", {}).get("actor", {})
                entity = actor_data.get("entity")

                if entity:
                    slo_name = entity.get("name", "")
                    tags = {t["key"]: t["values"][0] for t in entity.get("tags", []) if t.get("values")}

                    target_str = tags.get("nr.sloTarget", "99.9%")
                    try:
                        target = float(target_str.replace("%", ""))
                    except Exception:
                        target = 99.9

                    period_str = tags.get("nr.sloPeriod", "7d")
                    try:
                        time_window_days = int(period_str.replace("d", ""))
                    except Exception:
                        time_window_days = 7

                    associated_entity_name = tags.get("nr.associatedEntityName", "")
                    associated_entity_guid = tags.get("nr.associatedEntityGuid", "")

                    slo_info: Dict[str, Any] = {
                        "guid": guid,
                        "name": slo_name,
                        "tags": tags,
                        "target": target,
                        "time_window_days": time_window_days,
                        "description": f"Migrated from New Relic: {slo_name}",
                        "service_name": associated_entity_name,
                        "associated_entity_guid": associated_entity_guid,
                    }

                    if associated_entity_guid:
                        sli_details = self._fetch_sli_nrql_from_associated_entity(
                            associated_entity_guid, slo_name
                        )
                        if sli_details:
                            slo_info.update(sli_details)

                    slo_type, latency_ms = self._infer_slo_type(slo_info)
                    slo_info["slo_type"] = slo_type
                    if latency_ms:
                        slo_info["latency_threshold_ms"] = latency_ms

                    logger.debug(
                        "SLO inferred: type=%s, target=%.1f%%, period=%dd, service=%s",
                        slo_type, target, time_window_days, associated_entity_name,
                    )

                    self._slo_details_cache[guid] = slo_info
                    return slo_info
                else:
                    logger.debug("Entity not found in NR response for GUID %s", guid[:30])

        except Exception as e:
            logger.debug("Exception fetching SLO: %s: %s", type(e).__name__, e)

        return None

    def _fetch_sli_nrql_from_associated_entity(self, service_guid: str, sli_name: str) -> Dict:
        """Fetch the actual NRQL queries for an SLI from its associated service entity."""
        # Build a comprehensive GraphQL query covering all entity types that support serviceLevel
        entity_types = [
            "ApmExternalServiceEntity",
            "ExternalServiceEntity",
            "ApmServiceEntity",
            "BrowserApplicationEntity",
            "MobileApplicationEntity",
            "SyntheticMonitorEntity",
            "WorkloadEntity",
            "GenericServiceEntity",
            "GenericEntity",
        ]

        fragments = "\n".join(
            f"""
              ... on {et} {{
                serviceLevel {{
                  indicators {{
                    name
                    guid
                    events {{
                      validEvents {{ from where }}
                      goodEvents {{ from where }}
                    }}
                  }}
                }}
              }}"""
            for et in entity_types
        )

        query = (
            '{\n  actor {\n    entity(guid: "%s") {\n%s\n    }\n  }\n}' % (service_guid, fragments)
        )

        try:
            payload = json.dumps({"query": query}).encode("utf-8")
            headers = {"Content-Type": "application/json", "API-Key": self._nr_api_key}

            req = urllib.request.Request("https://api.newrelic.com/graphql", data=payload, headers=headers)
            with urllib.request.urlopen(req, timeout=30, context=_SSL_CONTEXT) as response:
                data = json.loads(response.read().decode("utf-8"))

                if "errors" in data:
                    logger.debug(
                        "NR SLI query errors (may be expected for some entity types): %s",
                        str(data["errors"])[:200],
                    )

                entity = data.get("data", {}).get("actor", {}).get("entity", {})
                service_level = entity.get("serviceLevel", {})
                indicators = service_level.get("indicators", [])

                logger.debug("Found %d SLIs on associated entity", len(indicators))

                for indicator in indicators:
                    if indicator.get("name") == sli_name:
                        events = indicator.get("events", {})
                        good_events = events.get("goodEvents", {}) or {}
                        valid_events = events.get("validEvents", {}) or {}

                        result = {
                            "good_events_from": good_events.get("from", ""),
                            "good_events_where": good_events.get("where", ""),
                            "valid_events_from": valid_events.get("from", ""),
                            "valid_events_where": valid_events.get("where", ""),
                        }

                        logger.debug(
                            "SLI NRQL queries found: Good=%s, Valid=%s",
                            result["good_events_from"],
                            result["valid_events_from"],
                        )
                        return result

                logger.debug("SLI '%s' not found in associated entity's indicators", sli_name)

        except Exception as e:
            logger.debug("Error fetching SLI NRQL: %s: %s", type(e).__name__, e)

        return {}

    def _infer_slo_type(self, slo_info: Dict) -> Tuple[str, Optional[int]]:
        """Infer SLO type (latency vs availability) from NRQL queries or name."""
        good_where = slo_info.get("good_events_where", "").lower()
        valid_where = slo_info.get("valid_events_where", "").lower()
        all_nrql = f"{good_where} {valid_where}"

        latency_match = re.search(
            r"(?:duration|responsetime|latency)\s*[<>=]+\s*(\d+(?:\.\d+)?)",
            all_nrql,
            re.IGNORECASE,
        )
        if latency_match:
            threshold_value = float(latency_match.group(1))
            if threshold_value < 100:
                latency_ms = int(threshold_value * 1000)
            else:
                latency_ms = int(threshold_value)
            return ("latency", latency_ms)

        name_lower = slo_info.get("name", "").lower()
        if any(kw in name_lower for kw in ("latency", "response", "duration", "performance")):
            return ("latency", 4000)

        return ("availability", None)

    def _analyze_slo_type(self, slo_info: Dict) -> str:
        """Determine SLO type and extract thresholds from NRQL content."""
        all_nrql = f"{slo_info.get('good_events_nrql', '')} {slo_info.get('valid_events_nrql', '')}".lower()

        latency_match = re.search(
            r"(?:duration|responsetime|latency)\s*[<>=]+\s*(\d+(?:\.\d+)?)",
            all_nrql,
            re.IGNORECASE,
        )
        if latency_match:
            threshold_value = float(latency_match.group(1))
            if threshold_value > 100:
                slo_info["latency_threshold_ms"] = threshold_value
            else:
                slo_info["latency_threshold_ms"] = threshold_value * 1000
            return "latency"

        if "duration" in all_nrql or "latency" in all_nrql:
            slo_info["latency_threshold_ms"] = 4000
            return "latency"

        status_match = re.search(
            r"(?:statuscode|http\.status)\s*[<>=!]+\s*(\d+)", all_nrql, re.IGNORECASE
        )
        if status_match:
            status_threshold = int(status_match.group(1))
            slo_info["status_threshold"] = status_threshold
            if status_threshold >= 400:
                return "error_rate"
            else:
                return "availability"

        if "error" in all_nrql or "http.status" in all_nrql:
            return "error_rate"
        elif "count" in all_nrql:
            return "availability"
        else:
            return "custom"

    def _extract_service_name(self, slo_info: Dict) -> str:
        """Extract service name from SLO NRQL or name."""
        all_nrql = f"{slo_info.get('good_events_nrql', '')} {slo_info.get('valid_events_nrql', '')}"

        patterns = [
            r"entity\.name\s*=\s*['\"]([^'\"]+)['\"]",
            r"appName\s*=\s*['\"]([^'\"]+)['\"]",
            r"service\.name\s*=\s*['\"]([^'\"]+)['\"]",
        ]

        for pattern in patterns:
            match = re.search(pattern, all_nrql, re.IGNORECASE)
            if match:
                return match.group(1)

        slo_name = slo_info.get("name", "")
        if " - " in slo_name:
            return slo_name.split(" - ")[0].strip()

        return ""

    def _check_existing_slo_in_dt(self, slo_name: str) -> Optional[str]:
        """Check if an SLO with this name already exists in Dynatrace."""
        if not self._dt_url or not self._dt_token:
            return None

        try:
            base_url = self._dt_url.replace(".live.", ".apps.")
            url = f"{base_url}/platform/slo/v1/slos?pageSize=500"

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._dt_token}",
            }

            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=30, context=_SSL_CONTEXT) as response:
                data = json.loads(response.read().decode("utf-8"))

                slos = data.get("slos", data.get("items", []))
                if isinstance(data, list):
                    slos = data

                for slo in slos:
                    existing_name = slo.get("name", "")
                    if existing_name.strip().lower() == slo_name.strip().lower():
                        slo_object_id = slo.get("objectId", slo.get("id", ""))
                        logger.info("SLO already exists in DT: '%s' -> %s", existing_name, slo_object_id[:50])
                        return slo_object_id

                next_page = data.get("nextPageKey")
                while next_page:
                    page_url = f"{base_url}/platform/slo/v1/slos?nextPageKey={next_page}"
                    req = urllib.request.Request(page_url, headers=headers, method="GET")
                    with urllib.request.urlopen(req, timeout=30, context=_SSL_CONTEXT) as response:
                        data = json.loads(response.read().decode("utf-8"))
                        slos = data.get("slos", data.get("items", []))
                        if isinstance(data, list):
                            slos = data
                        for slo in slos:
                            existing_name = slo.get("name", "")
                            if existing_name.strip().lower() == slo_name.strip().lower():
                                slo_object_id = slo.get("objectId", slo.get("id", ""))
                                logger.info("SLO already exists in DT: '%s' -> %s", existing_name, slo_object_id[:50])
                                return slo_object_id
                        next_page = data.get("nextPageKey")

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if hasattr(e, "read") else ""
            logger.debug("SLO existence check HTTP error %d: %s", e.code, error_body[:200])
        except Exception as e:
            logger.debug("SLO existence check error: %s", e)

        return None

    def _create_slo_in_dt(self, slo_info: Dict) -> Tuple[bool, str, str]:
        """Create an SLO in Dynatrace using the Platform SLO API (Grail-based).

        Skips creation if SLO with same name already exists, but still returns
        the existing SLO ID so it can be applied to dashboard tiles.
        """
        if not self._dt_url or not self._dt_token:
            return False, "", "DT credentials not configured"

        guid = slo_info.get("guid", "")
        slo_name = slo_info.get("name", "Migrated SLO")

        # Check if already attempted in this run
        if guid in self._created_slos:
            cached = self._created_slos[guid]
            if cached.startswith("FAILED:"):
                return False, "", f"Already attempted (cached failure): {cached}"
            return True, cached, "Already created (cached)"

        # CHECK IF SLO ALREADY EXISTS IN DT before creating
        existing_id = self._check_existing_slo_in_dt(slo_name)
        if existing_id:
            self._created_slos[guid] = existing_id
            self._guid_cache[guid] = slo_name
            self._guid_types[guid] = "SERVICE_LEVEL"
            logger.info("Skipping SLO creation (already exists): %s -> %s", slo_name, existing_id[:50])
            return True, existing_id, f"SLO already exists in DT: {existing_id}"

        # Get target from NR tags or default
        target = slo_info.get("target", 99.9)
        warning = min(target + (100 - target) / 2, 99.99)

        days = slo_info.get("time_window_days", 7)
        timeframe_from = f"now-{days}d"

        slo_type = slo_info.get("slo_type", "availability")
        service_name = slo_info.get("service_name", "")

        entity_name_step = "\n| fieldsAdd entityName = entityName(dt.entity.service)"
        service_filter = ""
        if service_name:
            validated_name, entity_warn = self._validate_entity_name(service_name, "SERVICE")
            if entity_warn:
                logger.warning(entity_warn)
            if validated_name != service_name:
                logger.info("Service name corrected: '%s' -> '%s'", service_name, validated_name)
                service_name = validated_name
            escaped_name = service_name.replace('"', '\\"')
            service_filter = f'\n| filter contains(entityName, "{escaped_name}")'

        if slo_type == "latency":
            # dt.service.request.response_time is in MICROSECONDS
            threshold_ms = slo_info.get("latency_threshold_ms", 4000)
            threshold_us = threshold_ms * 1000

            dql_indicator = (
                f"timeseries total=avg(dt.service.request.response_time), default:0, "
                f"by: {{ dt.entity.service }}{entity_name_step}{service_filter}\n"
                f"| fieldsAdd high=iCollectArray(if(total[] > {threshold_us}, total[]))\n"
                f"| fieldsAdd low=iCollectArray(if(total[] <= {threshold_us}, total[]))\n"
                f"| fieldsAdd highRespTimes=iCollectArray(if(isNull(high[]), 0, else: 1))\n"
                f"| fieldsAdd lowRespTimes=iCollectArray(if(isNull(low[]), 0, else: 1))\n"
                f"| fieldsAdd sli=100*(lowRespTimes[]/(lowRespTimes[]+highRespTimes[]))\n"
                f"| fieldsRemove total, high, low, highRespTimes, lowRespTimes"
            )
        else:
            dql_indicator = (
                f"timeseries {{\n"
                f"  total=sum(dt.service.request.count),\n"
                f"  failures=sum(dt.service.request.failure_count)\n"
                f"}}, by: {{ dt.entity.service }}{entity_name_step}{service_filter}\n"
                f"| fieldsAdd sli=(((total[]-failures[])/total[])*(100))\n"
                f"| fieldsRemove total, failures"
            )

        description = slo_info.get("description", "")
        if not description:
            description = f"Migrated from New Relic: {slo_name}"

        good_from = slo_info.get("good_events_from", "")
        good_where = slo_info.get("good_events_where", "")
        valid_from = slo_info.get("valid_events_from", "")
        valid_where = slo_info.get("valid_events_where", "")

        if good_from or valid_from:
            description += "\n\n--- Original NR SLI NRQL ---"
            if good_from:
                description += f"\nGood Events: FROM {good_from} WHERE {good_where[:200] if good_where else 'N/A'}"
            if valid_from:
                description += f"\nValid Events: FROM {valid_from} WHERE {valid_where[:200] if valid_where else 'N/A'}"

        description = f"{description}\n\n[Migrated from NR GUID: {guid[:40]}...]"

        payload = {
            "name": slo_name,
            "description": description[:1000],
            "criteria": [
                {
                    "target": target,
                    "warning": round(warning, 2),
                    "timeframeFrom": timeframe_from,
                    "timeframeTo": "now",
                }
            ],
            "customSli": {"indicator": dql_indicator},
            "tags": ["MigratedFromNR:true"],
        }

        try:
            base_url = self._dt_url.replace(".live.", ".apps.")
            if ".apps." not in base_url:
                base_url = self._dt_url

            url = f"{base_url}/platform/slo/v1/slos"
            json_payload = json.dumps(payload)
            encoded_data = json_payload.encode("utf-8")

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._dt_token}",
            }

            logger.debug("Creating Platform SLO at %s: %s, target=%.1f%%", url, slo_name, target)

            req = urllib.request.Request(url, data=encoded_data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30, context=_SSL_CONTEXT) as response:
                api_result = json.loads(response.read().decode("utf-8"))

                slo_uuid = api_result.get("id", "")
                slo_object_id = api_result.get("objectId", "")
                slo_id_for_tiles = slo_object_id if slo_object_id else slo_uuid

                self._created_slos[guid] = slo_id_for_tiles
                self._guid_cache[guid] = slo_name
                self._guid_types[guid] = "SERVICE_LEVEL"

                logger.info("Platform SLO created: %s, entity ID: %s", slo_uuid, slo_id_for_tiles[:50])
                return True, slo_id_for_tiles, f"Created Platform SLO: {slo_uuid}"

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if hasattr(e, "read") else ""
            logger.debug("Platform SLO creation HTTP error %d: %s", e.code, error_body[:500])
            self._created_slos[guid] = f"FAILED:{e.code}"
            return False, "", f"HTTP {e.code}: {error_body[:200]}"
        except Exception as e:
            logger.debug("Platform SLO creation exception: %s", e)
            self._created_slos[guid] = f"FAILED:{str(e)[:50]}"
            return False, "", str(e)

    def _handle_slo_guid(self, guid: str) -> Tuple[str, str]:
        """Handle a SERVICE_LEVEL GUID -- fetch details, optionally create in DT."""
        logger.debug("_handle_slo_guid called for %s, auto_create=%s", guid[:30], self._auto_create_slos)

        slo_info = self._fetch_slo_details_from_nr(guid)

        if slo_info:
            slo_name = slo_info.get("name", "")
            if self._auto_create_slos:
                success, slo_id, msg = self._create_slo_in_dt(slo_info)
                if success:
                    return (
                        f'slo.name == "{slo_name}"',
                        f"SLO auto-created in DT (ID: {slo_id}): {slo_name}",
                    )
                else:
                    return (
                        f'slo.name == "{slo_name}"',
                        f"SLO creation failed ({msg}), using name: {slo_name}",
                    )
            else:
                return (
                    f'slo.name == "{slo_name}"',
                    f"SLO resolved: {slo_name} (not auto-created, use --auto-create-slos)",
                )

        return (
            '/* REPLACE: This is an SLO. Use: fetch slo | filter slo.name == "your-slo-name" */',
            "SLO GUID detected but could not fetch details from NR API",
        )

    # ------------------------------------------------------------------
    # GUID resolution
    # ------------------------------------------------------------------

    def _resolve_guids_in_dql(self, dql: str, result: ConversionResult) -> str:
        """Resolve NR entity GUIDs in DQL output to DT entity names."""
        guid_pattern = r'"([A-Za-z0-9+/]{20,}={0,2})"'
        guid_matches = re.findall(guid_pattern, dql)

        if not guid_matches:
            return dql

        for guid in guid_matches:
            if " " in guid or guid.islower():
                continue

            resolved_name = None
            entity_type = ""

            # 1. Check guid_cache first
            if guid in self._guid_cache:
                resolved_name = self._guid_cache[guid]
                entity_type = self._guid_types.get(guid, "")
            else:
                # 2. Try base64 decode to determine entity type
                try:
                    padded = guid + "=" * (4 - len(guid) % 4) if len(guid) % 4 else guid
                    decoded = b64.b64decode(padded).decode("utf-8")
                    parts = decoded.split("|")
                    if len(parts) >= 3:
                        entity_type = parts[1] if len(parts) > 1 else ""
                        entity_subtype = parts[2] if len(parts) > 2 else ""

                        if entity_subtype == "SERVICE_LEVEL":
                            self._detected_slos.add(guid)
                            try:
                                slo_replacement, slo_warning = self._handle_slo_guid(guid)
                                if slo_replacement and "__GUID_PLACEHOLDER__" not in slo_replacement:
                                    resolved_name = None
                                    if "==" not in slo_replacement:
                                        dql = dql.replace(f'"{guid}"', f'"{slo_replacement}"')
                                    else:
                                        dql = dql.replace(f'"{guid}"', slo_replacement)
                                    result.warnings.append(slo_warning)
                                    continue
                            except Exception:
                                pass

                        if not resolved_name and self._nr_api_key:
                            try:
                                self.resolve_guids_from_api(self._nr_api_key, [guid])
                                if guid in self._guid_cache:
                                    resolved_name = self._guid_cache[guid]
                            except Exception:
                                pass
                    else:
                        continue
                except Exception:
                    continue

            # Apply resolution
            if resolved_name:
                entity_type_lower = entity_type.lower() if entity_type else ""
                entity_subtype = self._guid_types.get(guid, "").upper()

                if entity_subtype in ("SERVICE_LEVEL",):
                    new_filter = f'slo.name == "{resolved_name}"'
                elif entity_subtype in ("APM_APPLICATION", "APPLICATION", "SERVICE"):
                    new_filter = f'service.name == "{resolved_name}"'
                else:
                    new_filter = f'dt.entity.name == "{resolved_name}"'

                dql = re.sub(
                    rf'(dt\.entity\.service|dt\.entity\.name|entity\.guid|entityGuid)\s*==\s*"{re.escape(guid)}"',
                    new_filter,
                    dql,
                )
                dql = dql.replace(f'"{guid}"', f'"{resolved_name}"')

                result.warnings.append(f"NR GUID resolved -> {new_filter}")
                result.fixes.append(f"GUID {guid[:20]}... -> {resolved_name}")
            else:
                result.warnings.append(
                    f"NR GUID detected ({entity_type or 'unknown type'}): {guid[:30]}... "
                    f"Replace with dt.entity.name or service.name filter"
                )

        return dql

    # ------------------------------------------------------------------
    # Post-AST cleanup
    # ------------------------------------------------------------------

    def _post_ast_cleanup(self, dql: str) -> Tuple[str, List[str]]:
        """Minimal post-AST cleanup for dashboard-specific adjustments."""
        fixes: List[str] = []

        stripped = dql.strip()
        if not stripped or stripped.startswith("// Empty") or stripped.startswith("// ERROR"):
            return dql, fixes

        # 1. Dashboard tile timeframe: strip hardcoded from:now()-Xd
        if re.search(r"fetch\s+\w+\s*,\s*from:now\(\)", dql):
            dql = re.sub(r"(fetch\s+\w+)\s*,\s*from:now\(\)-\w+", r"\1", dql)
            fixes.append("Removed hardcoded from:now()-Xd -- dashboard tile uses time selector")

        # 2. builtin: prefix in non-metric record queries
        if "builtin:" in dql and "fetch " in dql:
            lines = dql.split("\n")
            new_lines = []
            for line in lines:
                s = line.strip()
                if s.startswith("//"):
                    new_lines.append(line)
                    continue
                cmd = s.lstrip("| ")
                if cmd.startswith(("filter ", "fields ", "fieldsAdd ", "summarize ")):
                    if "builtin:" in line:
                        line = line.replace("builtin:", "")
                        fixes.append("Stripped builtin: prefix from record query")
                new_lines.append(line)
            dql = "\n".join(new_lines)

        # 3. Boolean operators: AND->and, OR->or, NOT->not
        if re.search(r"\bAND\b", dql):
            dql = re.sub(r"\bAND\b", "and", dql)
        if re.search(r"\bOR\b", dql):
            dql = re.sub(r"\bOR\b", "or", dql)
        if re.search(r"\bNOT\b(?!\s*[Nn]ull)", dql):
            dql = re.sub(r"\bNOT\b(?!\s*[Nn]ull)", "not", dql)

        return dql, fixes

    # ------------------------------------------------------------------
    # DQL Output Sanitizer
    # ------------------------------------------------------------------

    def _sanitize_dql_output(self, dql: str) -> Tuple[str, List[str]]:
        """FINAL GATE: Comprehensive DQL output sanitizer.

        Runs on EVERY DQL output from EVERY conversion path.
        """
        fixes: List[str] = []

        stripped = dql.strip()
        if not stripped or stripped.startswith("// Empty") or stripped.startswith("// ERROR"):
            return dql, fixes

        # ==================================================================
        # CHECK 1: Embedded NRQL subqueries
        # ==================================================================
        non_comment_dql = "\n".join(
            line for line in dql.split("\n") if line.strip() and not line.strip().startswith("//")
        )
        has_raw_subquery = bool(re.search(r"\b(?:in|IN)\s*\(\s*(?:SELECT|FROM)\b", non_comment_dql))
        has_lookup = "lookup [" in non_comment_dql or "lookup[" in non_comment_dql

        if has_raw_subquery and not has_lookup:
            sub_match = re.search(r"\b(?:in|IN)\s*\(\s*(SELECT|FROM)\s+[^\n|]{0,80}", non_comment_dql)
            sub_text = sub_match.group(0)[:80] if sub_match else "subquery"

            lines = dql.split("\n")
            cleaned_lines = []
            for line in lines:
                if line.strip().startswith("//"):
                    cleaned_lines.append(line)
                else:
                    cleaned_line = re.sub(
                        r"\s+and\s+\w+(?:\.\w+)*\s+in\s*\(\s*(?:SELECT|FROM)\s+[^\n|]*",
                        "",
                        line,
                        flags=re.IGNORECASE,
                    )
                    if cleaned_line.strip() != line.strip():
                        cleaned_lines.append(cleaned_line)
                    else:
                        cleaned_lines.append(line)
            dql = "\n".join(cleaned_lines)
            fixes.append(f"Removed NRQL subquery (DQL uses lookup/join): {sub_text[:60]}...")

        # ==================================================================
        # CHECK 14: Backtick-escape aliases with special characters
        # ==================================================================
        def _needs_backtick_escape(name: str) -> bool:
            if name.startswith("`") and name.endswith("`"):
                return False
            if name[0:1].isdigit():
                return True
            if re.search(r"[^a-zA-Z0-9_]", name):
                return True
            DQL_RESERVED = {
                "string",
                "long",
                "double",
                "boolean",
                "ip",
                "timestamp",
                "duration",
                "timeframe",
                "record",
                "array",
            }
            if name.lower() in DQL_RESERVED:
                return True
            return False

        lines = dql.split("\n")
        new_lines = []
        for line in lines:
            stripped_line = line.strip()
            if stripped_line.startswith("//"):
                new_lines.append(line)
                continue

            cmd_stripped = stripped_line.lstrip("| ")

            cmd_keyword = None
            for kw in ("summarize ", "fieldsAdd ", "makeTimeseries ", "timeseries "):
                if cmd_stripped.startswith(kw):
                    cmd_keyword = kw
                    break

            if cmd_keyword:
                kw_idx = line.find(cmd_keyword)
                prefix = line[: kw_idx + len(cmd_keyword)]
                content = line[kw_idx + len(cmd_keyword) :]

                def _fix_alias_in_content(m):
                    alias = m.group(1)
                    eq_and_rest = m.group(2)
                    if _needs_backtick_escape(alias):
                        fixes.append(f"Backtick-escaped alias: {alias} -> `{alias}`")
                        return f"`{alias}`{eq_and_rest}"
                    return m.group(0)

                content = re.sub(
                    r"(?<![`a-zA-Z])([A-Za-z$_/\d][A-Za-z0-9$_/. ]*?)\s*(=(?!=))",
                    _fix_alias_in_content,
                    content,
                )
                line = prefix + content

            new_lines.append(line)
        dql = "\n".join(new_lines)

        # ==================================================================
        # CHECK 15: Fix substring() positional parameters
        # ==================================================================
        if "substring(" in dql:

            def _fix_substring(m):
                expr = m.group(1)
                start = m.group(2)
                end = m.group(3)
                fixes.append("Fixed substring positional params -> named from:/to:")
                return f"substring({expr}, from:{start}, to:{end})"

            dql = re.sub(
                r"substring\(([^,]+),\s*(\w+)\s*,\s*(\w+)\s*\)",
                _fix_substring,
                dql,
            )

        # ==================================================================
        # CHECK 16: Strip builtin: prefix in non-metric queries
        # ==================================================================
        if "builtin:" in dql and ("fetch " in dql or "| filter" in dql):
            lines = dql.split("\n")
            new_lines = []
            for line in lines:
                s = line.strip()
                if s.startswith("//"):
                    new_lines.append(line)
                    continue
                cmd = s.lstrip("| ")
                if cmd.startswith(("filter ", "fields ", "fieldsAdd ", "summarize ")):
                    if "builtin:" in line:
                        line = line.replace("builtin:", "")
                        fixes.append("Stripped builtin: prefix from record query (metric-API syntax)")
                new_lines.append(line)
            dql = "\n".join(new_lines)

        # ==================================================================
        # CHECK 17: Aggregations in non-aggregation context
        # ==================================================================
        lines = dql.split("\n")
        new_lines = []
        for line in lines:
            stripped_line = line.strip()
            if stripped_line.startswith("//"):
                new_lines.append(line)
                continue

            cmd = stripped_line.lstrip("| ")
            if cmd.startswith("fieldsAdd "):
                content = cmd[len("fieldsAdd "):]
                alias_match = re.match(r"(\S+)\s*=\s*(sum|avg|count|min|max)\s*\(", content, re.IGNORECASE)
                if alias_match:
                    alias = alias_match.group(1)
                    merged = False
                    for i in range(len(new_lines) - 1, -1, -1):
                        prev_cmd = new_lines[i].strip().lstrip("| ")
                        if prev_cmd.startswith(("timeseries ", "makeTimeseries ", "summarize ")):
                            full_expr = content.strip()
                            new_lines[i] = new_lines[i].rstrip() + f", {full_expr}"
                            fixes.append(f"Moved aggregation '{alias}' from fieldsAdd into timeseries/summarize")
                            merged = True
                            break
                        elif prev_cmd.startswith(("fieldsAdd ", "//")):
                            continue
                        else:
                            break
                    if merged:
                        continue
                    else:
                        new_lines.append(f"// TODO: {stripped_line} -- aggregation not valid in fieldsAdd")
                        fixes.append(f"Flagged aggregation in fieldsAdd: {alias}")
                        continue
            new_lines.append(line)
        dql = "\n".join(new_lines)

        # ==================================================================
        # CHECK 18: Duplicate aliases in same command
        # ==================================================================
        lines = dql.split("\n")
        new_lines = []
        for line in lines:
            stripped_line = line.strip()
            if stripped_line.startswith("//"):
                new_lines.append(line)
                continue
            cmd = stripped_line.lstrip("| ")
            if cmd.startswith(("summarize ", "makeTimeseries ", "timeseries ", "fieldsAdd ")):
                alias_pattern_re = re.compile(r"(?<![a-zA-Z`])(`?[\w.]+`?)\s*=(?!=)")
                aliases = alias_pattern_re.findall(cmd)
                seen_aliases: Dict[str, int] = {}
                for alias in aliases:
                    clean = alias.strip("`")
                    if clean in seen_aliases:
                        seen_aliases[clean] += 1
                        new_alias = f"{alias}_{seen_aliases[clean]}"
                        count = 0

                        def _replace_nth(m, _clean=clean, _new_alias=new_alias, _seen=seen_aliases):
                            nonlocal count
                            if m.group(1).strip("`") == _clean:
                                count += 1
                                if count == _seen[_clean]:
                                    fixes.append(f"Renamed duplicate alias {_clean} -> {_clean}_{_seen[_clean]}")
                                    return f"{_new_alias}="
                            return m.group(0)

                        line = re.sub(r"(?<![a-zA-Z`])(`?[\w.]+`?)\s*=(?!=)", _replace_nth, line)
                    else:
                        seen_aliases[clean] = 1
            new_lines.append(line)
        dql = "\n".join(new_lines)

        # ==================================================================
        # CHECK 19: Backtick-escape field names containing /
        # ==================================================================
        slash_field_pattern = re.compile(r"(?<!`)(\b[a-zA-Z][\w.]*(?:/[\w.]+)+\b)(?!`)")
        if slash_field_pattern.search(dql):
            lines = dql.split("\n")
            new_lines = []
            for line in lines:
                if line.strip().startswith("//"):
                    new_lines.append(line)
                    continue
                segments = re.split(r'("(?:[^"\\]|\\.)*")', line)
                new_segments = []
                for seg in segments:
                    if seg.startswith('"') and seg.endswith('"'):
                        new_segments.append(seg)
                    else:

                        def _fix_slash_field(m):
                            field_val = m.group(1)
                            if field_val.startswith("http") or field_val.startswith("ftp"):
                                return field_val
                            fixes.append(f"Backtick-escaped field with /: {field_val}")
                            return f"`{field_val}`"

                        new_segments.append(slash_field_pattern.sub(_fix_slash_field, seg))
                new_lines.append("".join(new_segments))
            dql = "\n".join(new_lines)

        # ==================================================================
        # CHECK 20: Fix bare NR field names that aren't valid in DQL
        # ==================================================================
        nr_custom_fields = {
            "Item", "Items", "Group", "Groups", "Log", "Logs",
            "MS", "Action", "Type", "Status", "Result", "Value",
            "Message", "Error", "Name", "Id", "Key", "Data",
        }
        for field_name in nr_custom_fields:
            pattern = re.compile(r"(?<![.\w`])" + re.escape(field_name) + r"(?![.\w`])")
            if pattern.search(dql):
                lines = dql.split("\n")
                new_lines = []
                for line in lines:
                    if line.strip().startswith("//"):
                        new_lines.append(line)
                        continue
                    cmd = line.strip().lstrip("| ")
                    if cmd.startswith(("filter ", "summarize ", "fieldsAdd ", "fields ", "sort ")):
                        new_line = pattern.sub(f"`{field_name}`", line)
                        if new_line != line:
                            fixes.append(f"Backtick-escaped NR field name: {field_name}")
                            line = new_line
                    new_lines.append(line)
                dql = "\n".join(new_lines)

        # ==================================================================
        # CHECK 21: Strip ALL remaining NRQL AS keywords from DQL output
        # ==================================================================
        lines = dql.split("\n")
        as_fixed_lines = []
        for line in lines:
            stripped_line = line.strip()
            if stripped_line.startswith("//"):
                as_fixed_lines.append(line)
                continue

            cmd = stripped_line.lstrip("| ")
            if any(cmd.startswith(kw) for kw in ("summarize ", "makeTimeseries ", "fieldsAdd ", "fields ")):
                original_line = line

                def _fix_all_as_in_line(text):
                    kw_match = re.match(
                        r"^(\s*\|?\s*(?:summarize|makeTimeseries|fieldsAdd|fields)\s+)",
                        text,
                        re.IGNORECASE,
                    )
                    if not kw_match:
                        return text
                    prefix_str = kw_match.group(1)
                    body = text[len(prefix_str):]

                    parts: List[str] = []
                    depth = 0
                    current: List[str] = []
                    for ch in body:
                        if ch in ("(", "{", "["):
                            depth += 1
                        elif ch in (")", "}", "]"):
                            depth -= 1
                        elif ch == "," and depth == 0:
                            parts.append("".join(current))
                            current = []
                            continue
                        current.append(ch)
                    if current:
                        parts.append("".join(current))

                    fixed_parts: List[str] = []
                    changed = False
                    for part in parts:
                        stripped_part = part.strip()
                        as_match = re.search(r"\s+[Aa][Ss]\s+['\"]?([^'\"]+?)['\"]?\s*$", stripped_part)
                        if as_match and not stripped_part.startswith("by:"):
                            alias_raw = as_match.group(1).strip()
                            expr = stripped_part[: as_match.start()].strip()
                            if alias_raw.startswith("`") and alias_raw.endswith("`"):
                                alias_clean = alias_raw
                            elif re.search(r"[^a-zA-Z0-9_]", alias_raw) or alias_raw[0:1].isdigit():
                                alias_clean = re.sub(r"[^a-zA-Z0-9_]", "_", alias_raw)
                                if alias_clean[0:1].isdigit():
                                    alias_clean = "_" + alias_clean
                            else:
                                alias_clean = alias_raw
                            fixed_parts.append(f" {alias_clean}={expr}")
                            changed = True
                        else:
                            fixed_parts.append(part)

                    if changed:
                        return prefix_str + ",".join(fixed_parts)
                    return text

                line = _fix_all_as_in_line(line)

                if line != original_line:
                    fixes.append("Converted NRQL 'AS' alias to DQL 'alias=expr' syntax")

            as_fixed_lines.append(line)
        dql = "\n".join(as_fixed_lines)

        # ==================================================================
        # CHECK 22: Fix double-equals in aliases
        # ==================================================================
        lines = dql.split("\n")
        dedup_lines = []
        for line in lines:
            if line.strip().startswith("//"):
                dedup_lines.append(line)
                continue
            original_line = line
            line = re.sub(
                r"(\w+)=(\w+)=(\w+\s*\()",
                lambda m: f"{m.group(1)}={m.group(3)}",
                line,
            )
            line = re.sub(
                r"(\w+)=(\w+)=([^,\s(]+)",
                lambda m: f"{m.group(1)}={m.group(3)}",
                line,
            )
            if line != original_line:
                fixes.append("Fixed double-alias (alias1=alias2=expr -> alias1=expr)")
            dedup_lines.append(line)
        dql = "\n".join(dedup_lines)

        # ==================================================================
        # CHECK 23: Wrap multi-aggregation summarize in curly braces
        # ==================================================================
        def _wrap_summarize_aggs(line: str) -> str:
            sum_match = re.match(r"^(\s*\|?\s*summarize\s+)(.*)", line, re.IGNORECASE)
            if not sum_match:
                return line

            prefix_str = sum_match.group(1)
            rest = sum_match.group(2).strip()

            if rest.startswith("{"):
                return line

            by_clause = ""
            agg_part = rest

            depth = 0
            for i, ch in enumerate(rest):
                if ch in ("(", "{", "["):
                    depth += 1
                elif ch in (")", "}", "]"):
                    depth -= 1
                elif depth == 0 and rest[i:].startswith(", by:"):
                    agg_part = rest[:i]
                    by_clause = rest[i:]
                    break
                elif depth == 0 and rest[i:].startswith(",by:"):
                    agg_part = rest[:i]
                    by_clause = rest[i:]
                    break

            agg_count = 0
            depth = 0
            for ch in agg_part:
                if ch in ("(", "{", "["):
                    depth += 1
                elif ch in (")", "}", "]"):
                    depth -= 1
                elif ch == "," and depth == 0:
                    agg_count += 1
            agg_count += 1

            if agg_count > 1:
                return f"{prefix_str}{{{agg_part}}}{by_clause}"
            return line

        lines = dql.split("\n")
        brace_fixed_lines = []
        for line in lines:
            stripped_line = line.strip()
            if stripped_line.startswith("//"):
                brace_fixed_lines.append(line)
                continue
            cmd = stripped_line.lstrip("| ")
            if cmd.lower().startswith("summarize ") and not cmd.lower().startswith("summarize {"):
                original = line
                line = _wrap_summarize_aggs(line)
                if line != original:
                    fixes.append("Wrapped multi-aggregation summarize in {} (DQL requirement)")
            brace_fixed_lines.append(line)
        dql = "\n".join(brace_fixed_lines)

        # ==================================================================
        # CHECK 24: Fix makeTimeseries with alias=expr (not supported)
        # ==================================================================
        lines = dql.split("\n")
        mt_fixed_lines = []
        for line in lines:
            stripped_line = line.strip()
            if stripped_line.startswith("//"):
                mt_fixed_lines.append(line)
                continue
            cmd = stripped_line.lstrip("| ")
            if cmd.lower().startswith("maketimeseries "):
                original = line
                mt_match = re.match(r"^(\s*\|?\s*makeTimeseries\s+)(.*)", line, re.IGNORECASE)
                if mt_match:
                    mt_prefix = mt_match.group(1)
                    mt_rest = mt_match.group(2)

                    params_part = ""
                    agg_end = len(mt_rest)
                    depth = 0
                    for i, ch in enumerate(mt_rest):
                        if ch in ("(", "{", "["):
                            depth += 1
                        elif ch in (")", "}", "]"):
                            depth -= 1
                        elif depth == 0 and mt_rest[i:].startswith(", by:"):
                            agg_end = i
                            params_part = mt_rest[i:]
                            break
                        elif depth == 0 and mt_rest[i:].startswith(", interval:"):
                            agg_end = i
                            params_part = mt_rest[i:]
                            break

                    agg_portion = mt_rest[:agg_end]

                    def _strip_mt_alias(part):
                        eq_match = re.match(r"^\s*`?(\w+)`?\s*=\s*(?!=)(.+)$", part.strip())
                        if eq_match:
                            return eq_match.group(2).strip()
                        return part.strip()

                    parts_list: List[str] = []
                    depth = 0
                    current_chars: List[str] = []
                    for ch in agg_portion:
                        if ch in ("(", "{", "["):
                            depth += 1
                        elif ch in (")", "}", "]"):
                            depth -= 1
                        elif ch == "," and depth == 0:
                            parts_list.append("".join(current_chars).strip())
                            current_chars = []
                            continue
                        current_chars.append(ch)
                    if current_chars:
                        parts_list.append("".join(current_chars).strip())

                    clean_parts = [_strip_mt_alias(p) for p in parts_list if p.strip()]
                    line = mt_prefix + ", ".join(clean_parts) + params_part

                    if line != original:
                        fixes.append("Stripped aliases from makeTimeseries (not supported, uses auto-column names)")
            mt_fixed_lines.append(line)
        dql = "\n".join(mt_fixed_lines)

        # Final cleanup: remove trailing whitespace on each line
        lines = dql.split("\n")
        dql = "\n".join(line.rstrip() for line in lines)

        return dql, fixes

    # ------------------------------------------------------------------
    # Query builders (regex fallback path)
    # ------------------------------------------------------------------

    def _build_metric_query(
        self,
        select_clause: str,
        where_clause: str,
        facet_clause: str,
        has_timeseries: bool,
        title: str,
    ) -> Tuple[str, str]:
        """Build a DQL query for metric data."""
        confidence = "HIGH"

        agg_match = re.search(
            r"(count|sum|average|avg|max|min|percentile|latest|earliest|first|last)\s*\(\s*`?([^)`]*)`?\s*\)",
            select_clause or "",
            re.IGNORECASE,
        )

        if agg_match:
            func = agg_match.group(1).lower()
            field = agg_match.group(2).strip().strip("`") if agg_match.group(2) else ""

            if func in ["latest", "last", "earliest", "first"]:
                field_key = field.lower().replace(".", "").replace("_", "").replace("`", "") if field else ""
                dt_metric, _metric_warn = self._resolve_metric(field_key, field) if field_key else (None, None)
                if _metric_warn:
                    self._current_warnings.append(_metric_warn)

                if field_key:
                    transform_result = self._apply_metric_transform(field_key, func, where_clause, facet_clause)
                    if transform_result:
                        return transform_result[0], transform_result[1]

                if dt_metric or (field and (field.startswith("builtin:") or field.startswith("dt."))):
                    metric_name = dt_metric if dt_metric else field

                    all_aggs = re.findall(
                        r"(latest|earliest|first|last|average|avg|sum|max|min)\s*\(\s*`?([^)`]*)`?\s*\)",
                        select_clause,
                        re.IGNORECASE,
                    )

                    dql = f"timeseries avg({metric_name})"

                    if facet_clause:
                        dt_facets = self._convert_facet(facet_clause)
                        if dt_facets:
                            dql += f", by: {{{dt_facets}}}"

                    if where_clause:
                        dt_filter = self._convert_where(where_clause)
                        if dt_filter:
                            dql += f", filter: {dt_filter}"

                    if len(all_aggs) > 1:
                        unmapped = []
                        for _, fld in all_aggs[1:]:
                            fld_clean = fld.strip().strip("`")
                            fld_key = fld_clean.lower().replace(".", "").replace("_", "")
                            m, _mw = self._resolve_metric(fld_key, fld_clean)
                            if _mw:
                                self._current_warnings.append(_mw)
                            unmapped.append(m or fld_clean)
                        dql = f"// NOTE: Multiple metrics - additional: {', '.join(unmapped)}\n{dql}"

                    return dql, "HIGH"

                dt_func = "takeLast" if func in ["latest", "last"] else "takeFirst"
                dt_field = self._map_attribute(field) if field else "timestamp"

                all_aggs = re.findall(
                    r"(latest|earliest|first|last)\s*\(\s*`?([^)`]*)`?\s*\)",
                    select_clause,
                    re.IGNORECASE,
                )

                agg_exprs = []
                for f, fld in all_aggs:
                    f_lower = f.lower()
                    dt_f = "takeLast" if f_lower in ["latest", "last"] else "takeFirst"
                    dt_fld = self._map_attribute(fld.strip("`")) if fld else "timestamp"
                    agg_exprs.append(f"{dt_f}({dt_fld})")

                parts = ["fetch spans"]
                if where_clause:
                    dt_filter = self._convert_where(where_clause)
                    parts.append(f"filter {dt_filter}")

                if facet_clause:
                    dt_facets = self._convert_facet(facet_clause)
                    if dt_facets:
                        parts.append(f"summarize {', '.join(agg_exprs)}, by: {{{dt_facets}}}")
                    else:
                        parts.append(f"summarize {', '.join(agg_exprs)}")
                else:
                    parts.append(f"summarize {', '.join(agg_exprs)}")

                return "\n| ".join(parts), "HIGH"

            if func == "count" and (not field or field == "*"):
                return self._build_count_query(where_clause, facet_clause, "spans", title)

            if field and "newrelic.sli" in field.lower():
                return self._convert_sli_query(select_clause, where_clause, title)

            dt_func = AGG_MAP.get(func, func)
            if dt_func == "count()":
                dt_func = "count"

            if dt_func in ("takeLast", "takeFirst", "takeAny"):
                dt_func = "avg"

            if field:
                field_key = field.lower().replace(".", "").replace("_", "").replace("`", "")

                transform_result = self._apply_metric_transform(field_key, func, where_clause, facet_clause)
                if transform_result:
                    return transform_result[0], transform_result[1]

                dt_metric, _metric_warn = self._resolve_metric(field_key, field)
                if _metric_warn:
                    self._current_warnings.append(_metric_warn)

                if dt_metric:
                    dql = f"timeseries {dt_func}({dt_metric})"
                elif field.startswith("builtin:") or field.startswith("dt."):
                    dql = f"timeseries {dt_func}({field})"
                else:
                    parts = [f"// NOTE: Unknown metric field '{field}' - may need manual mapping"]
                    parts.append("fetch spans")
                    if where_clause:
                        dt_filter = self._convert_where(where_clause)
                        parts.append(f"| filter {dt_filter}")
                    if facet_clause:
                        dt_facets = self._convert_facet(facet_clause)
                        if dt_facets:
                            parts.append(f"| summarize count(), by: {{{dt_facets}}}")
                        else:
                            parts.append("| summarize count()")
                    else:
                        parts.append("| summarize count()")
                    return "\n".join(parts), "MEDIUM"
            else:
                if func in ["avg", "average"]:
                    dql = "timeseries avg(builtin:service.response.time)"
                elif func == "sum":
                    dql = "timeseries sum(builtin:service.requestCount.total)"
                else:
                    return self._build_count_query(where_clause, facet_clause, "spans", title)

            if facet_clause:
                dt_facets = self._convert_facet(facet_clause)
                if dt_facets:
                    dql += f", by: {{{dt_facets}}}"

            if where_clause:
                dt_filter = self._convert_where(where_clause)
                dql += f", filter: {dt_filter}"

            return dql, confidence

        return self._build_count_query(where_clause, facet_clause, "spans", title)

    @staticmethod
    def _strip_maketimeseries_aliases(expr: str) -> Tuple[str, List[Tuple[str, str]]]:
        """Strip alias=agg() patterns from an expression for makeTimeseries."""
        rename_pairs: List[Tuple[str, str]] = []
        clean_parts: List[str] = []

        parts: List[str] = []
        depth = 0
        current: List[str] = []
        for ch in expr:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append("".join(current).strip())
                current = []
                continue
            current.append(ch)
        if current:
            parts.append("".join(current).strip())

        for part in parts:
            eq_match = re.match(r"^(\w+)\s*=\s*(?!=)(.+)$", part.strip())
            if eq_match:
                alias_name = eq_match.group(1)
                raw_expr = eq_match.group(2).strip()
                clean_parts.append(raw_expr)
                rename_pairs.append((raw_expr, alias_name))
            else:
                clean_parts.append(part.strip())

        return ", ".join(clean_parts), rename_pairs

    def _build_fetch_query(
        self,
        dt_source: str,
        select_clause: str,
        where_clause: str,
        facet_clause: str,
        limit_value: int,
        has_timeseries: bool,
        title: str,
        original_nrql: str = "",
    ) -> Tuple[str, str]:
        """Build a DQL fetch query for non-metric data."""
        confidence = "HIGH"
        parts = [f"fetch {dt_source}"]

        # Detect and handle subqueries
        subquery_pattern = r"(\w[\w.]*)\s+(?:NOT\s+)?IN\s*\(\s*SELECT\s+(.+?)\s+FROM\s+(\w+)(?:\s+WHERE\s+(.+?))?\s*\)"
        subquery_match = re.search(subquery_pattern, where_clause or "", re.IGNORECASE)
        if subquery_match:
            join_field = subquery_match.group(1)
            sub_from = subquery_match.group(3)
            sub_where = subquery_match.group(4)

            sub_dt_source = self._map_event_type(sub_from) or "spans"
            dt_join_field = self._map_attribute(join_field)

            sub_filter = ""
            if sub_where:
                sub_filter_converted = self._convert_where(sub_where)
                if sub_filter_converted:
                    sub_filter = f" | filter {sub_filter_converted}"

            is_not_in = "NOT IN" in where_clause.upper()
            remaining_where = re.sub(subquery_pattern, "", where_clause or "", flags=re.IGNORECASE).strip()
            remaining_where = re.sub(r"^\s*(AND|OR)\s+", "", remaining_where, flags=re.IGNORECASE).strip()
            remaining_where = re.sub(r"\s+(AND|OR)\s*$", "", remaining_where, flags=re.IGNORECASE).strip()

            join_kind = "leftOuter" if is_not_in else "inner"
            parts.append(
                f"join [fetch {sub_dt_source}{sub_filter} | fields {dt_join_field}], "
                f"on: {{{dt_join_field}}}, kind: {join_kind}"
            )

            if is_not_in:
                parts.append(f"filter isNull(lookup.{dt_join_field})")

            if remaining_where:
                dt_filter = self._convert_where(remaining_where)
                if dt_filter and dt_filter.strip():
                    parts.append(f"filter {dt_filter}")

            self._current_warnings.append(f"Subquery converted to DQL join on {dt_join_field}")
            where_clause = None

        # Add filter
        if where_clause:
            dt_filter = self._convert_where(where_clause)
            if dt_filter and dt_filter.strip():
                parts.append(f"filter {dt_filter}")

        # CDF percentage expressions
        if select_clause and "__cdf_" in select_clause:
            agg_expr = select_clause.strip()
            clean_expr = re.sub(r"__cdf_([^_]+(?:_\d+m?s)?)__", r"\1", agg_expr)

            if has_timeseries:
                mt_clean, mt_renames = self._strip_maketimeseries_aliases(clean_expr)
                if facet_clause:
                    dt_facets = self._convert_facet(facet_clause)
                    if dt_facets:
                        parts.append(f"makeTimeseries {mt_clean}, by: {{{dt_facets}}}")
                    else:
                        parts.append(f"makeTimeseries {mt_clean}")
                else:
                    parts.append(f"makeTimeseries {mt_clean}")
            else:
                if facet_clause:
                    dt_facets = self._convert_facet(facet_clause)
                    if dt_facets:
                        parts.append(f"summarize {clean_expr}, by: {{{dt_facets}}}")
                    else:
                        parts.append(f"summarize {clean_expr}")
                else:
                    parts.append(f"summarize {clean_expr}")

                bucket_names = re.findall(r"(under_\d+m?s)", clean_expr)
                if bucket_names:
                    pct_fields = [f"pct_{name} = 100.0 * {name} / total" for name in bucket_names]
                    parts.append(f"fieldsAdd {', '.join(pct_fields)}")
                    fields_to_remove = ["total"] + bucket_names
                    parts.append(f"fieldsRemove {', '.join(fields_to_remove)}")

            if limit_value:
                parts.append(f"limit {limit_value}")

            return "\n| ".join(parts), "HIGH"

        # Pre-converted DQL expressions (countIf, avgIf, etc.)
        if select_clause and re.search(r"\b(countIf|avgIf|sumIf|maxIf|minIf)\s*\(", select_clause, re.IGNORECASE):
            expr_match = re.search(r"^\s*(.+?)(?:\s+AS\s+['\"]?[\w\s]+['\"]?)?\s*$", select_clause, re.IGNORECASE)
            if expr_match:
                agg_expr = expr_match.group(1).strip()
                agg_expr = re.sub(r"'([^']+)'", r'"\1"', agg_expr)

                if has_timeseries:
                    mt_clean, mt_renames = self._strip_maketimeseries_aliases(agg_expr)
                    if facet_clause:
                        dt_facets = self._convert_facet(facet_clause)
                        if dt_facets:
                            parts.append(f"makeTimeseries {mt_clean}, by: {{{dt_facets}}}")
                        else:
                            parts.append(f"makeTimeseries {mt_clean}")
                    else:
                        parts.append(f"makeTimeseries {mt_clean}")
                else:
                    if facet_clause:
                        dt_facets = self._convert_facet(facet_clause)
                        if dt_facets:
                            parts.append(f"summarize {agg_expr}, by: {{{dt_facets}}}")
                        else:
                            parts.append(f"summarize {agg_expr}")
                    else:
                        parts.append(f"summarize {agg_expr}")

                if limit_value:
                    parts.append(f"limit {limit_value}")

                return "\n| ".join(parts), "HIGH"

        # Parse ALL aggregations
        select_normalized = select_clause or ""

        def normalize_as_alias(match):
            full_expr = match.group(1)
            alias = match.group(2).strip("'\"")
            if (
                alias[0:1].isdigit()
                or re.search(r"[^a-zA-Z0-9_]", alias)
                or alias.lower()
                in {
                    "duration", "timestamp", "timeframe", "string", "long",
                    "double", "boolean", "ip", "record", "array",
                }
            ):
                clean_alias = f"`{alias}`"
            else:
                clean_alias = re.sub(r"[^a-zA-Z0-9_]", "_", alias)
            return f"{clean_alias}={full_expr}"

        select_normalized = re.sub(
            r"(\w+\s*\([^)]*(?:\([^)]*\)[^)]*)*\))\s+[Aa][Ss]\s+['\"]([^'\"]+)['\"]",
            normalize_as_alias,
            select_normalized,
        )
        select_normalized = re.sub(
            r"(\w+\s*\([^)]*(?:\([^)]*\)[^)]*)*\))\s+[Aa][Ss]\s+(\w+)",
            normalize_as_alias,
            select_normalized,
        )

        agg_pattern = (
            r"(?:(\w+)\s*=\s*)?(count|sum|average|avg|max|min|uniquecount|percentile|"
            r"countDistinct|collectDistinct|rate|latest|earliest|last|first|stddev|median)"
            r"\s*\(\s*([^)]*)\s*\)"
        )
        all_aggs = re.findall(agg_pattern, select_normalized, re.IGNORECASE)

        has_rate = any(f.lower() in ("rate", "derivative") for _, f, _ in all_aggs)
        if has_rate:
            filtered = []
            for alias, func, args in all_aggs:
                fl = func.lower()
                if fl in ("rate", "derivative"):
                    filtered.append((alias, func, args))
                elif fl in ("count", "sum", "avg", "average", "min", "max") and not alias:
                    inner_check = re.search(
                        rf"(?:rate|derivative)\s*\([^)]*{func}\s*\(",
                        select_normalized,
                        re.IGNORECASE,
                    )
                    if inner_check:
                        continue
                    filtered.append((alias, func, args))
                else:
                    filtered.append((alias, func, args))
            all_aggs = filtered

        if all_aggs:
            agg_expressions: List[str] = []
            warnings: List[str] = []

            for alias, func, args in all_aggs:
                func_lower = func.lower()
                dt_func = AGG_MAP.get(func_lower, func_lower)

                if func_lower == "rate":
                    rate_match = re.search(r"rate\s*\((.+)\)", select_normalized, re.IGNORECASE)
                    if rate_match:
                        rate_full = f"rate({rate_match.group(1).strip()})"
                    else:
                        rate_full = f"rate({args})" if args else "rate(count(*))"
                    rate_result = self._rate_converter.convert_rate(rate_full)
                    if rate_result:
                        expr, rate_param = rate_result
                        if not hasattr(self, "_current_rate_params"):
                            self._current_rate_params = []
                        self._current_rate_params.append(rate_param)
                        warnings.append(f"rate() -> {expr}, {rate_param}")
                    else:
                        inner_match = re.search(r"(count|sum|avg)\s*\([^)]*\)", args, re.IGNORECASE)
                        if inner_match:
                            expr = "count()" if "count" in inner_match.group(0).lower() else inner_match.group(0)
                        else:
                            expr = "count()"
                        warnings.append(f"rate() -> {expr} (rate: param needs manual addition)")
                elif func_lower == "derivative":
                    deriv_full = f"derivative({args})" if args else "derivative(count(*))"
                    deriv_result = self._rate_converter.convert_derivative(deriv_full)
                    if deriv_result:
                        expr, rate_param = deriv_result
                        if not hasattr(self, "_current_rate_params"):
                            self._current_rate_params = []
                        self._current_rate_params.append(rate_param)
                        warnings.append(f"derivative() -> {expr}, {rate_param}")
                    else:
                        expr = f"avg({args})" if args else "count()"
                        warnings.append("derivative() approximated - review rate calculation")
                elif func_lower == "latest":
                    field = args.strip() if args else "*"
                    if field == "*":
                        expr = "count()" if has_timeseries else "takeLast(timestamp)"
                    else:
                        dt_field = self._map_attribute(field.replace("duration.ms", "duration"))
                        if has_timeseries:
                            expr = f"avg({dt_field})"
                            warnings.append(f"latest({field}) -> avg({dt_field}) for timeseries (takeLast not supported)")
                        else:
                            expr = f"takeLast({dt_field})"
                elif func_lower == "last":
                    field = args.strip() if args else "*"
                    if field == "*":
                        expr = "count()" if has_timeseries else "takeLast(timestamp)"
                    else:
                        dt_field = self._map_attribute(field.replace("duration.ms", "duration"))
                        if has_timeseries:
                            expr = f"avg({dt_field})"
                            warnings.append(f"last({field}) -> avg({dt_field}) for timeseries (takeLast not supported)")
                        else:
                            expr = f"takeLast({dt_field})"
                elif func_lower == "earliest":
                    field = args.strip() if args else "*"
                    if field == "*":
                        expr = "count()" if has_timeseries else "takeFirst(timestamp)"
                    else:
                        dt_field = self._map_attribute(field.replace("duration.ms", "duration"))
                        if has_timeseries:
                            expr = f"avg({dt_field})"
                            warnings.append(f"earliest({field}) -> avg({dt_field}) for timeseries (takeFirst not supported)")
                        else:
                            expr = f"takeFirst({dt_field})"
                elif func_lower == "first":
                    field = args.strip() if args else "*"
                    if field == "*":
                        expr = "count()" if has_timeseries else "takeFirst(timestamp)"
                    else:
                        dt_field = self._map_attribute(field.replace("duration.ms", "duration"))
                        if has_timeseries:
                            expr = f"avg({dt_field})"
                            warnings.append(f"first({field}) -> avg({dt_field}) for timeseries (takeFirst not supported)")
                        else:
                            expr = f"takeFirst({dt_field})"
                elif func_lower == "median":
                    field = args.strip() if args else "duration"
                    dt_field = self._map_attribute(field.replace("duration.ms", "duration"))
                    expr = f"percentile({dt_field}, 50)"
                elif func_lower == "count" or not args or args == "*":
                    expr = "count()"
                elif func_lower == "percentile":
                    args_clean = args.replace("duration.ms", "duration")
                    expr = f"percentile({args_clean})"
                elif func_lower == "uniquecount":
                    field = args.split(",")[0].strip()
                    dt_field = self._map_attribute(field)
                    expr = f"countDistinct({dt_field})"
                elif func_lower == "collectdistinct":
                    expr = f"collectDistinct({args.strip()})"
                else:
                    field = args.split(",")[0].strip()
                    if field == "duration.ms":
                        field = "duration"
                    dt_field = self._map_attribute(field)
                    expr = f"{dt_func}({dt_field})"

                if alias:
                    agg_expressions.append(f"{alias}={expr}")
                else:
                    agg_expressions.append(expr)

            # Check for math operations after aggregations
            math_match = re.search(r"\)\s*([*/+-])\s*(\d+(?:\.\d+)?)", select_clause or "")
            if math_match:
                operator = math_match.group(1)
                operand = math_match.group(2)
                warnings.append(f"Math operation ({operator} {operand}) - add fieldsAdd if needed")

            if hasattr(self, "_current_warnings"):
                self._current_warnings.extend(warnings)

            agg_expr = ", ".join(agg_expressions)

            if has_timeseries:
                rename_pairs: List[Tuple[str, str]] = []
                clean_agg_parts: List[str] = []
                for agg_part in agg_expressions:
                    eq_match = re.match(r"^(\w+)\s*=\s*(.+)$", agg_part.strip())
                    if eq_match:
                        alias_name = eq_match.group(1)
                        raw_expr = eq_match.group(2)
                        clean_agg_parts.append(raw_expr)
                        rename_pairs.append((raw_expr, alias_name))
                    else:
                        clean_agg_parts.append(agg_part)

                clean_agg_expr = ", ".join(clean_agg_parts)

                if facet_clause:
                    dt_facets = self._convert_facet(facet_clause)
                    if dt_facets:
                        parts.append(f"makeTimeseries {clean_agg_expr}, by: {{{dt_facets}}}")
                    else:
                        parts.append(f"makeTimeseries {clean_agg_expr}")
                else:
                    parts.append(f"makeTimeseries {clean_agg_expr}")
            else:
                if facet_clause:
                    dt_facets = self._convert_facet(facet_clause)
                    if dt_facets:
                        parts.append(f"summarize {agg_expr}, by: {{{dt_facets}}}")
                    else:
                        parts.append(f"summarize {agg_expr}")
                else:
                    parts.append(f"summarize {agg_expr}")

        elif select_clause:
            scalar_funcs = [
                "concat", "capture", "aparse", "substring", "lower", "upper", "if",
                "stringlength", "indexof", "trim",
                "power", "log", "log10", "abs", "ceil", "floor", "round", "sqrt", "exp",
                "getdayofmonth", "getmonth", "getyear", "gethour", "getminute",
                "getweekofyear", "formattimestamp", "getsecond", "getdayofweek",
                "todouble", "tostring", "toboolean", "totimestamp",
                "bin",
            ]
            has_scalar_func = any(f"{func}(" in select_clause.lower() for func in scalar_funcs)

            if has_scalar_func:
                fields_add_exprs: List[str] = []
                confidence = "MEDIUM"

                concat_match = re.search(
                    r"concat\s*\(([^)]+)\)\s*(?:[Aa][Ss]\s+['\"]?(\w+)['\"]?)?",
                    select_clause,
                    re.IGNORECASE,
                )
                if concat_match:
                    args_str = concat_match.group(1)
                    alias = concat_match.group(2) or "concatenated"
                    mapped_args = []
                    for arg in args_str.split(","):
                        arg = arg.strip()
                        if (arg.startswith('"') and arg.endswith('"')) or (arg.startswith("'") and arg.endswith("'")):
                            stripped = arg.strip("\"'")
                            mapped_args.append(f'"{stripped}"')
                        else:
                            mapped_args.append(self._map_attribute(arg))
                    fields_add_exprs.append(f'{alias} = concat({", ".join(mapped_args)})')

                capture_match = re.search(
                    r'capture\s*\(([^,]+),\s*[r]?[\'"]([^\'"]+)[\'"]\)\s*(?:[Aa][Ss]\s+[\'"]?(\w+)[\'"]?)?',
                    select_clause,
                    re.IGNORECASE,
                )
                if capture_match:
                    field = self._map_attribute(capture_match.group(1).strip())
                    regex_pattern = capture_match.group(2)
                    dpl_pattern, capture_names = self._regex_to_dpl.convert(regex_pattern)
                    parse_cmd = f'parse {field}, "{dpl_pattern}"'
                    fields_add_exprs.append(f"// capture() -> | {parse_cmd}")
                    if capture_names:
                        self._current_warnings.append(
                            f"capture() -> DPL parse with fields: {', '.join(capture_names)}"
                        )
                    else:
                        self._current_warnings.append(
                            f"capture() -> DPL parse (verify pattern: {dpl_pattern[:40]}...)"
                        )

                aparse_match = re.search(
                    r'aparse\s*\(([^,]+),\s*[\'"]([^\'"]+)[\'"]\)\s*(?:[Aa][Ss]\s+[\'"]?(\w+)[\'"]?)?',
                    select_clause,
                    re.IGNORECASE,
                )
                if aparse_match:
                    field = self._map_attribute(aparse_match.group(1).strip())
                    anchor_pattern = aparse_match.group(2)
                    dpl_pattern, capture_names = self._aparse_converter.convert(anchor_pattern)
                    parse_cmd = f'parse {field}, "{dpl_pattern}"'
                    fields_add_exprs.append(f"// aparse() -> | {parse_cmd}")
                    self._current_warnings.append(
                        f"aparse() -> DPL parse, captures: {', '.join(capture_names)}"
                    )

                if_match = re.search(
                    r'if\s*\(([^,]+),\s*[\'"]?([^\'"]+)[\'"]?,\s*[\'"]?([^\'"]+)[\'"]?\)\s*(?:[Aa][Ss]\s+[\'"]?(\w+)[\'"]?)?',
                    select_clause,
                    re.IGNORECASE,
                )
                if if_match:
                    condition = if_match.group(1).strip()
                    true_val = if_match.group(2).strip()
                    false_val = if_match.group(3).strip()
                    alias = if_match.group(4) or "result"
                    condition = self._convert_where_condition_only(condition)
                    fields_add_exprs.append(f'{alias} = if({condition}, "{true_val}", "{false_val}")')

                if fields_add_exprs:
                    parts.append(f"fieldsAdd {', '.join(fields_add_exprs)}")
                else:
                    func_match = re.search(
                        r"(?:(\w+)\s*=\s*)?(\w+)\s*\((.+)\)",
                        select_clause,
                        re.IGNORECASE,
                    )
                    if func_match:
                        alias = func_match.group(1)
                        func_name = func_match.group(2)
                        func_args = func_match.group(3)
                        mapped_args = []
                        for arg in func_args.split(","):
                            arg = arg.strip()
                            if (
                                arg.startswith('"')
                                or arg.startswith("'")
                                or re.match(r"^-?\d+\.?\d*$", arg)
                                or "(" in arg
                            ):
                                mapped_args.append(arg)
                            else:
                                mapped_args.append(self._map_attribute(arg))
                        result_expr = f'{func_name}({", ".join(mapped_args)})'
                        if alias:
                            parts.append(f"fieldsAdd {alias} = {result_expr}")
                        else:
                            parts.append(f"fieldsAdd {result_expr}")
                    else:
                        parts.append(f"// Scalar function not fully converted: {select_clause[:80]}")
                        self._current_warnings.append("Scalar function requires manual review")
            else:
                fields = self._parse_select_fields(select_clause)
                if fields:
                    dt_fields = [self._map_attribute(f) for f in fields]
                    parts.append(f"fields {', '.join(dt_fields)}")

        if limit_value:
            parts.append(f"limit {limit_value}")

        return "\n| ".join(parts), confidence

    def _convert_sli_query(self, select_clause: str, where_clause: str, title: str) -> Tuple[str, str]:
        """Convert NR SLI metric queries to DT SLO queries."""
        confidence = "MEDIUM"

        slo_guid = None
        guid_match = re.search(r"entity\.guid\s*=\s*['\"]([^'\"]+)['\"]", where_clause, re.IGNORECASE)
        if guid_match:
            slo_guid = guid_match.group(1)

        slo_name = None
        if slo_guid:
            if slo_guid in self._guid_cache:
                slo_name = self._guid_cache[slo_guid]
            elif self._auto_create_slos:
                slo_info = self._fetch_slo_details_from_nr(slo_guid)
                if slo_info:
                    slo_name = slo_info.get("name", "")

        original_nrql = getattr(self, "_current_original_nrql", "") or ""
        query_to_analyze = original_nrql.lower() if original_nrql else select_clause.lower() if select_clause else ""
        title_lower = title.lower() if title else ""

        slo_metric = "slo.status"

        if "error budget" in title_lower or "budget" in title_lower:
            slo_metric = "slo.errorBudget"
        elif "burn" in title_lower and "rate" in title_lower:
            slo_metric = "slo.burnRate"
        elif "target" in title_lower:
            slo_metric = "slo.target"
        elif "clamp_min" in query_to_analyze or "clamp_max" in query_to_analyze:
            slo_metric = "slo.errorBudget"
        elif re.search(r"if\s*\([^)]+\)\s*/\s*\(\s*100\s*-\s*\d+", query_to_analyze):
            slo_metric = "slo.errorBudget"
        elif "newrelic.sli.good" in query_to_analyze and "newrelic.sli.valid" in query_to_analyze:
            if "/" in query_to_analyze and "if(" not in query_to_analyze:
                slo_metric = "slo.status"
            elif "/" not in query_to_analyze:
                slo_metric = "count"
            else:
                slo_metric = "slo.status"
        elif "newrelic.sli.good" in query_to_analyze:
            slo_metric = "goodCount"
        elif "newrelic.sli.valid" in query_to_analyze:
            slo_metric = "validCount"

        if slo_name:
            slo_filter = f'slo.name == "{slo_name}"'
            confidence = "HIGH"
        elif slo_guid:
            slo_filter = f"/* REPLACE with slo.name: NR GUID was {slo_guid[:30]}... */"
            confidence = "LOW"
        else:
            slo_filter = '/* REPLACE: Add slo.name == "Your SLO Name" */'
            confidence = "LOW"

        slo_ref = slo_name if slo_name else f"(NR GUID: {slo_guid[:30]}...)" if slo_guid else "Your SLO Name"

        if slo_metric == "slo.status":
            dql = f'''// SLO STATUS: "{slo_ref}"
// RECOMMENDED: Use the dedicated SLO tile widget in Dashboards
// which displays Status, Error Budget, and Target automatically.
//
// To add: Dashboard > Add tile > Service-Level Objective > Select "{slo_ref}"
//
// If you need a custom DQL visualization, the SLO's underlying query is in the SLO definition.'''

        elif slo_metric == "slo.errorBudget":
            dql = f'''// ERROR BUDGET: "{slo_ref}"
// RECOMMENDED: Use the dedicated SLO tile widget in Dashboards
// The SLO widget includes Error Budget display by default.
//
// To add: Dashboard > Add tile > Service-Level Objective > Select "{slo_ref}"
// Then enable "Error budget" in the tile's Data mapping columns.
//
// Error Budget = (Current Status - Target) / (100 - Target) * 100'''

        elif slo_metric == "slo.burnRate":
            dql = f'''// BURN RATE: "{slo_ref}"
// RECOMMENDED: Use the dedicated SLO tile widget in Dashboards
// Burn rate visualization is included when burn rate alerting is configured.
//
// To add: Dashboard > Add tile > Service-Level Objective > Select "{slo_ref}"
//
// Burn Rate = rate at which error budget is being consumed'''

        elif slo_metric == "slo.target":
            dql = f'''// SLO TARGET: "{slo_ref}"
// RECOMMENDED: Use the dedicated SLO tile widget in Dashboards
// which displays the Target value.
//
// To add: Dashboard > Add tile > Service-Level Objective > Select "{slo_ref}"
// Then enable "Target" in the tile's Data mapping columns.'''

        elif slo_metric in ("goodCount", "validCount", "count"):
            dql = f'''// RAW SLI COUNTS: "{slo_ref}"
// NOTE: Raw good/valid event counts aren't exposed in DT SLO tiles.
// The SLO widget shows Status (percentage) and Error Budget instead.
//
// If you need raw counts, query the underlying data directly:
// fetch spans
// | filter dt.entity.service == "SERVICE-..." // Replace with your service
// | summarize total = count(), good = countIf(duration <= 4s)
// | fieldsAdd sli = 100.0 * good / total'''
            confidence = "LOW"

        else:
            dql = f'''// SLO: "{slo_ref}"
// RECOMMENDED: Use the dedicated SLO tile widget in Dashboards
// To add: Dashboard > Add tile > Service-Level Objective > Select your SLO'''

        return dql, confidence

    def _build_count_query(
        self, where_clause: str, facet_clause: str, source: str, title: str
    ) -> Tuple[str, str]:
        """Build a simple count query using fetch + summarize."""
        parts = [f"fetch {source}"]

        if where_clause:
            dt_filter = self._convert_where(where_clause)
            parts.append(f"filter {dt_filter}")

        if facet_clause:
            dt_facets = self._convert_facet(facet_clause)
            if dt_facets:
                parts.append(f"summarize count(), by: {{{dt_facets}}}")
            else:
                parts.append("summarize count()")
        else:
            parts.append("summarize count()")

        return "\n| ".join(parts), "HIGH"

    def _build_k8s_metric_query(
        self,
        k8s_source: str,
        select_clause: str,
        where_clause: str,
        facet_clause: str,
        has_timeseries: bool,
        title: str,
    ) -> Tuple[str, str]:
        """Build DQL query for Kubernetes metrics."""
        confidence = "MEDIUM"
        notes: List[str] = []

        K8S_METRIC_OVERRIDES = {
            "memoryusedbytes": "dt.kubernetes.container.memory_working_set",
            "memoryused": "dt.kubernetes.container.memory_working_set",
            "cpuusedbytes": "dt.kubernetes.container.cpu_usage",
            "cpupercent": "dt.kubernetes.container.cpu_usage",
            "diskused": "dt.kubernetes.persistentvolumeclaim.used",
            "diskusedbytes": "dt.kubernetes.persistentvolumeclaim.used",
        }

        K8S_ENTITY_FIELDS = {
            "isready": {
                "dql": "timeseries avg(dt.kubernetes.workload.pods_ready), avg(dt.kubernetes.workload.pods_desired)",
                "note": "// isReady -> DT readiness = pods_ready vs pods_desired comparison",
                "confidence": "MEDIUM",
            },
            "status": {
                "dql": (
                    "fetch dt.entity.cloud_application"
                    "\n| fields entity.name, status = cloudApplicationStatus"
                ),
                "note": "// status -> DT entity property (not a timeseries metric)",
                "confidence": "MEDIUM",
            },
            "isscheduled": {
                "dql": (
                    "fetch dt.entity.cloud_application_instance"
                    "\n| fields entity.name, phase = cloudApplicationInstancePhase"
                ),
                "note": "// isScheduled -> DT entity phase property",
                "confidence": "MEDIUM",
            },
        }

        metric_filter_patterns = [
            "allocatablememoryutilization", "memoryusedbytes", "memoryavailablebytes",
            "fscapacityutilization", "fsavailablebytes", "fsinodesused", "fsinodes",
            "cpuusedbytes", "allocatablecpuutilization",
        ]
        where_lower = (where_clause or "").lower()
        has_metric_filter = any(p in where_lower for p in metric_filter_patterns)

        if has_metric_filter:
            notes.append("// NOTE: Metric-based filtering works differently in DT")
            notes.append("// Consider using DT's threshold alerts or post-aggregation filtering")
            confidence = "LOW"

        agg_matches = re.findall(
            r"(latest|last|earliest|first|average|avg|sum|max|min)\s*\(\s*([^)]+)\s*\)",
            select_clause or "",
            re.IGNORECASE,
        )

        if not agg_matches:
            result_tuple = self._build_count_query(where_clause, facet_clause, "dt.entity.cloud_application", title)
            if notes:
                return "\n".join(notes) + "\n" + result_tuple[0], "LOW"
            return result_tuple

        first_field_key = agg_matches[0][1].strip().strip("`").lower().replace(".", "").replace("_", "")
        entity_info = K8S_ENTITY_FIELDS.get(first_field_key)
        if entity_info:
            dql = entity_info["dql"]
            if where_clause:
                dt_filter = self._convert_where(where_clause)
                if dt_filter:
                    if "timeseries" in dql:
                        dql += f", filter: {dt_filter}"
                    else:
                        dql += f"\n| filter {dt_filter}"
            if facet_clause and "timeseries" in dql:
                dt_facets = self._convert_facet(facet_clause)
                if dt_facets:
                    dql += f", by: {{{dt_facets}}}"
            if notes:
                dql = "\n".join(notes) + "\n" + entity_info["note"] + "\n" + dql
            else:
                dql = entity_info["note"] + "\n" + dql
            return dql, entity_info["confidence"]

        dt_metrics: List[Tuple[str, str, str]] = []
        unmapped_metrics: List[str] = []

        for func, field in agg_matches:
            field = field.strip().strip("`")
            field_key = field.lower().replace(".", "").replace("_", "")

            if not dt_metrics:
                transform_result = self._apply_metric_transform(field_key, func.lower(), where_clause, facet_clause)
                if transform_result:
                    dql_val, conf, note_text = transform_result
                    if notes:
                        dql_val = "\n".join(notes) + "\n" + dql_val
                    remaining = [f.strip().strip("`") for _, f in agg_matches[1:]]
                    if remaining:
                        dql_val = f"// NOTE: Additional metrics in original query: {', '.join(remaining)}\n{dql_val}"
                    return dql_val, conf

            k8s_override = K8S_METRIC_OVERRIDES.get(field_key)
            if k8s_override:
                dt_func_name = "avg" if func.lower() in ["latest", "last", "first", "earliest", "average", "avg"] else func.lower()
                dt_metrics.append((dt_func_name, k8s_override, field))
                continue

            dt_metric, _metric_warn = self._resolve_metric(field_key, field)
            if _metric_warn:
                self._current_warnings.append(_metric_warn)
            if dt_metric:
                dt_func_name = "avg" if func.lower() in ["latest", "last", "first", "earliest", "average", "avg"] else func.lower()
                dt_metrics.append((dt_func_name, dt_metric, field))
            else:
                unmapped_metrics.append(field)

        if not dt_metrics:
            parts_list = notes.copy()
            parts_list.append(f"// NOTE: Unknown K8s metrics: {', '.join(unmapped_metrics)} - need manual mapping")
            parts_list.append("// Suggested: Check builtin:cloud.kubernetes.* metrics in DT Metrics browser")
            parts_list.append("fetch dt.entity.kubernetes_node")
            if where_clause:
                dt_filter = self._convert_where(where_clause)
                for pattern in metric_filter_patterns:
                    dt_filter = re.sub(rf"\s*and\s+{pattern}\s*[<>=!]+\s*[\d.]+", "", dt_filter, flags=re.IGNORECASE)
                    dt_filter = re.sub(rf"{pattern}\s*[<>=!]+\s*[\d.]+\s*and\s*", "", dt_filter, flags=re.IGNORECASE)
                dt_filter = dt_filter.strip()
                if dt_filter:
                    parts_list.append(f"| filter {dt_filter}")
            if facet_clause:
                dt_facets = self._convert_facet(facet_clause)
                if dt_facets:
                    parts_list.append(f"| summarize count(), by: {{{dt_facets}}}")
                else:
                    parts_list.append("| summarize count()")
            else:
                parts_list.append("| summarize count()")
            return "\n".join(parts_list), "LOW"

        dt_func_name, dt_metric, original_field = dt_metrics[0]
        dql = f"timeseries {dt_func_name}({dt_metric})"

        if facet_clause:
            dt_facets = self._convert_facet(facet_clause)
            if dt_facets:
                dql += f", by: {{{dt_facets}}}"

        if where_clause:
            dt_filter = self._convert_where(where_clause)
            for pattern in metric_filter_patterns:
                dt_filter = re.sub(rf"\s*and\s+{pattern}\s*[<>=!]+\s*[\d.]+", "", dt_filter, flags=re.IGNORECASE)
                dt_filter = re.sub(rf"{pattern}\s*[<>=!]+\s*[\d.]+\s*and\s*", "", dt_filter, flags=re.IGNORECASE)
                dt_filter = re.sub(rf"{pattern}\s*[<>=!]+\s*[\d.]+", "", dt_filter, flags=re.IGNORECASE)
            dt_filter = dt_filter.strip()
            if dt_filter:
                dql += f", filter: {dt_filter}"

        if unmapped_metrics:
            notes.append(f"// NOTE: Unmapped metrics: {', '.join(unmapped_metrics)}")

        if len(dt_metrics) > 1:
            notes.append(f"// NOTE: Multiple metrics in original - only using first. Others: {[m[2] for m in dt_metrics[1:]]}")

        if notes:
            dql = "\n".join(notes) + "\n" + dql

        return dql, confidence

    def _apply_metric_transform(
        self,
        field_key: str,
        agg_func: str,
        where_clause: str,
        facet_clause: str,
    ) -> Optional[Tuple[str, str, str]]:
        """Check if a field needs a calculated expression instead of simple metric lookup."""
        transform = METRIC_TRANSFORMS.get(field_key)
        if not transform:
            return None

        ttype = transform["type"]
        confidence = transform.get("confidence", "MEDIUM")
        note = transform.get("note", "")

        by_str = ""
        filter_str = ""

        if facet_clause:
            dt_facets = self._convert_facet(facet_clause)
            if dt_facets:
                by_str = f", by: {{{dt_facets}}}"

        if where_clause:
            dt_filter = self._convert_where(where_clause)
            if dt_filter and dt_filter.strip():
                filter_str = f", filter: {dt_filter}"

        if ttype == "calculated":
            dql_template = transform.get("dql_single", transform["dql"])
            dql = dql_template.replace("{by}", by_str).replace("{filter}", filter_str)
            if note:
                dql = f"// {note}\n{dql}"
            return dql, confidence, note

        elif ttype == "multi_metric":
            dql = transform["dql"].replace("{by}", by_str).replace("{filter}", filter_str)
            return dql, confidence, note

        elif ttype == "unit_convert":
            metric = transform["metric"]
            post_calc = transform.get("post_calc", "")

            dt_func = AGG_MAP.get(agg_func, agg_func) if agg_func else "avg"
            if dt_func == "count()":
                dt_func = "count"
            if dt_func in ("takeLast", "takeFirst", "takeAny"):
                dt_func = "avg"

            alias = field_key[:12]
            dql = f"timeseries {alias} = {dt_func}({metric}){by_str}{filter_str}"

            if post_calc:
                post_calc_resolved = post_calc.replace("{alias}", alias)
                dql = f"{dql}\n{post_calc_resolved}"

            if note:
                dql = f"// {note}\n{dql}"

            return dql, confidence, note

        return None

    def _build_events_query(
        self,
        select_clause: str,
        where_clause: str,
        facet_clause: str,
        limit_value: int,
        title: str,
    ) -> Tuple[str, str]:
        """Build DQL query for infrastructure events."""
        parts = ["fetch events"]

        if where_clause:
            dt_filter = self._convert_where(where_clause)
            parts.append(f"filter {dt_filter}")

        if select_clause:
            fields = self._parse_select_fields(select_clause)
            if fields:
                dt_fields = [self._map_attribute(f) for f in fields]
                parts.append(f"fields {', '.join(dt_fields)}")

        if limit_value:
            parts.append(f"limit {limit_value}")

        return "\n| ".join(parts), "MEDIUM"

    # ------------------------------------------------------------------
    # Mapping helpers
    # ------------------------------------------------------------------

    def _map_event_type(self, event_type: str) -> str:
        """Map NR event type to DT data source."""
        event_key = event_type.lower().replace("_", "").replace("-", "")

        if event_key in EVENT_TYPE_MAP:
            return EVENT_TYPE_MAP[event_key]

        if "log" in event_key:
            return "logs"
        elif "metric" in event_key or "sample" in event_key:
            return "METRIC"
        elif "span" in event_key or "transaction" in event_key:
            return "spans"
        elif "synthetic" in event_key:
            return "dt.synthetic.http.request"
        else:
            return "spans"

    def _is_metric_query(self, nrql: str) -> bool:
        """Check if this NRQL targets a metric/K8s event type."""
        from_match = re.search(r"\bFROM\s+(\w+)", nrql, re.IGNORECASE)
        if not from_match:
            return False
        event_type = from_match.group(1).lower().replace("_", "").replace("-", "")
        mapped = EVENT_TYPE_MAP.get(event_type, "")
        if not mapped:
            return "metric" in event_type or "sample" in event_type
        return mapped == "METRIC" or mapped.startswith("K8S_")

    # ------------------------------------------------------------------
    # NRQL preprocessing
    # ------------------------------------------------------------------

    def _preprocess_nrql(self, nrql: str) -> str:
        """Preprocess NRQL to convert NR-specific syntax before parsing."""
        result = nrql

        # 1. clamp_max(x, max) -> if(x > max, max, x)
        def convert_clamp_max(match):
            expr = match.group(1).strip()
            max_val = match.group(2).strip()
            return f"if({expr} > {max_val}, {max_val}, else:{expr})"

        result = re.sub(
            r"clamp_max\s*\(\s*(.+?)\s*,\s*(\d+(?:\.\d+)?)\s*\)",
            convert_clamp_max,
            result,
            flags=re.IGNORECASE,
        )

        # 2. clamp_min(x, min) -> if(x < min, min, x)
        def convert_clamp_min(match):
            expr = match.group(1).strip()
            min_val = match.group(2).strip()
            return f"if({expr} < {min_val}, {min_val}, else:{expr})"

        result = re.sub(
            r"clamp_min\s*\(\s*(.+?)\s*,\s*(\d+(?:\.\d+)?)\s*\)",
            convert_clamp_min,
            result,
            flags=re.IGNORECASE,
        )

        # 3. latest(field) -> last(field)
        result = re.sub(r"\blatest\s*\(", "last(", result, flags=re.IGNORECASE)

        # 4. median(field) -> percentile(field, 50)
        def convert_median(match):
            field = match.group(1).strip()
            return f"percentile({field}, 50)"

        result = re.sub(r"\bmedian\s*\(\s*([^)]+)\s*\)", convert_median, result, flags=re.IGNORECASE)

        # 5. {{variable}} -> $variable
        result = re.sub(r"\{\{(\w+)\}\}", r"$\1", result)

        # 6. Remove backticks from field names
        result = re.sub(r"`([^`]+)`", r"\1", result)

        # 7. uniqueCount() -> countDistinct()
        result = re.sub(r"\buniqueCount\s*\(", "countDistinct(", result, flags=re.IGNORECASE)

        # 8. Multi-percentile expansion
        def convert_multi_percentile(match):
            field = match.group(1).strip()
            percentiles_str = match.group(2).strip()
            percentiles = [p.strip() for p in percentiles_str.split(",") if p.strip()]
            if len(percentiles) <= 1:
                return match.group(0)
            calls = []
            for p in percentiles:
                calls.append(f"p{p}=percentile({field}, {p})")
            return ", ".join(calls)

        result = re.sub(
            r"\bpercentile\s*\(\s*([^,]+?)\s*,\s*(\d+(?:\s*,\s*\d+)+)\s*\)\s*(?:[Aa][Ss]\s+['\"]?[\w\s]+['\"]?)?",
            convert_multi_percentile,
            result,
            flags=re.IGNORECASE,
        )

        # 9. bucketPercentile
        def convert_bucket_percentile(match):
            converted = self._bucket_percentile_converter.convert(match.group(0))
            return converted if converted else match.group(0)

        result = re.sub(
            r"\bbucketPercentile\s*\([^)]+\)",
            convert_bucket_percentile,
            result,
            flags=re.IGNORECASE,
        )

        # 10. Math function conversions
        result = re.sub(r"\bpow\s*\(", "power(", result, flags=re.IGNORECASE)

        def convert_log2(match):
            expr = match.group(1).strip()
            return f"(log({expr}) / log(2))"

        result = re.sub(r"\blog2\s*\(\s*([^)]+)\s*\)", convert_log2, result, flags=re.IGNORECASE)

        # 11. Type casting conversions
        result = re.sub(r"\bnumeric\s*\(", "toDouble(", result, flags=re.IGNORECASE)
        result = re.sub(r"(?<!\w)string\s*\(", "toString(", result, flags=re.IGNORECASE)
        result = re.sub(r"\bboolean\s*\(", "toBoolean(", result, flags=re.IGNORECASE)
        result = re.sub(r"\btoDatetime\s*\(", "toTimestamp(", result, flags=re.IGNORECASE)

        # 12. String function conversions
        result = re.sub(r"\bposition\s*\(", "indexOf(", result, flags=re.IGNORECASE)
        result = re.sub(r"\bltrim\s*\(", "trim(", result, flags=re.IGNORECASE)
        result = re.sub(r"\brtrim\s*\(", "trim(", result, flags=re.IGNORECASE)

        # 12a. length(x) -> stringLength(x)
        result = re.sub(r"(?<!\w)length\s*\(", "stringLength(", result, flags=re.IGNORECASE)

        # 13. Date/time extraction conversions
        result = re.sub(r"\bdayOfMonth\s*\(", "getDayOfMonth(", result, flags=re.IGNORECASE)
        result = re.sub(r"\bmonthOf\s*\(", "getMonth(", result, flags=re.IGNORECASE)
        result = re.sub(r"\byearOf\s*\(", "getYear(", result, flags=re.IGNORECASE)
        result = re.sub(r"\bhourOf\s*\(", "getHour(", result, flags=re.IGNORECASE)
        result = re.sub(r"\bminuteOf\s*\(", "getMinute(", result, flags=re.IGNORECASE)
        result = re.sub(r"\bweekOf\s*\(", "getWeekOfYear(", result, flags=re.IGNORECASE)

        def convert_dateOf(match):
            expr = match.group(1).strip()
            return f'formatTimestamp({expr}, format:"yyyy-MM-dd")'

        result = re.sub(r"\bdateOf\s*\(\s*([^)]+)\s*\)", convert_dateOf, result, flags=re.IGNORECASE)

        # 14. Aggregation function conversions
        def convert_uniques(match):
            field = match.group(1).strip()
            limit = match.group(2)
            if limit:
                return f"collectDistinct({field}, maxLength:{limit.strip()})"
            return f"collectDistinct({field})"

        result = re.sub(
            r"\buniques\s*\(\s*([^,)]+)(?:\s*,\s*(\d+))?\s*\)",
            convert_uniques,
            result,
            flags=re.IGNORECASE,
        )

        result = re.sub(r"\bbuckets\s*\(", "bin(", result, flags=re.IGNORECASE)

        # 15. Window function conversions (partial)
        window_funcs = {
            "windowSum": "sum",
            "windowAvg": "avg",
            "windowCount": "count",
            "windowMax": "max",
            "windowMin": "min",
        }
        for nrql_func, dql_agg in window_funcs.items():
            pattern = rf"\b{nrql_func}\s*\(\s*([^,]+?)\s*,\s*(\d+)\s+(\w+)\s*\)"

            def make_window_converter(fn=nrql_func):
                def convert_window(match):
                    inner_expr = match.group(1).strip()
                    window_size = match.group(2)
                    window_unit = match.group(3)
                    return (
                        f"{inner_expr} /* TODO: NR {fn}({window_size} {window_unit}) "
                        f"- use DQL: timeseries ... | fieldsAdd rolling=arrayCumulativeSum(val) or rollup parameter */"
                    )
                return convert_window

            result = re.sub(pattern, make_window_converter(), result, flags=re.IGNORECASE)

        # 16. Hard/impossible conversions
        def convert_histogram(match):
            args_str = match.group(1).strip()
            parts_list = [a.strip() for a in args_str.split(",")]
            field = parts_list[0] if parts_list else "duration"
            if field == "duration.ms":
                field = "duration"
            if len(parts_list) >= 4:
                width = parts_list[3]
            elif len(parts_list) >= 3:
                try:
                    width = str(int(float(parts_list[1]) / float(parts_list[2])))
                except (ValueError, ZeroDivisionError):
                    width = "1000"
            else:
                width = "1000"
            if field == "duration":
                try:
                    width = _ms_to_dql_duration(float(width))
                except ValueError:
                    width = "1s"
            return f"count(), by: {{bin({field}, {width})}}"

        result = re.sub(
            r"\bhistogram\s*\(\s*([^)]+)\s*\)",
            convert_histogram,
            result,
            flags=re.IGNORECASE,
        )

        def convert_predictLinear(match):
            args_str = match.group(1).strip()
            return f"/* NR predictLinear({args_str}) - No DQL equiv. Use Davis AI anomaly detection or forecast APIs */"

        result = re.sub(
            r"\bpredictLinear\s*\(\s*([^)]+)\s*\)",
            convert_predictLinear,
            result,
            flags=re.IGNORECASE,
        )

        result = re.sub(
            r"\beventType\s*\(\s*\)",
            "/* NR eventType() - DQL: data source is specified in fetch command */",
            result,
            flags=re.IGNORECASE,
        )

        return result

    # ------------------------------------------------------------------
    # NR function converters (regex fallback)
    # ------------------------------------------------------------------

    def _convert_percentage_function(self, nrql: str) -> str:
        """Convert NR percentage() function to DQL equivalent."""
        result = nrql
        pattern = r"\bpercentage\s*\(\s*count\s*\(\s*\*?\s*\)\s*,\s*WHERE\s+(.+?)\s*\)"

        def convert_pct(match):
            condition = match.group(1).strip()
            condition = self._convert_where_condition_only(condition)
            return f"(100.0 * countIf({condition}) / count())"

        result = re.sub(pattern, convert_pct, result, flags=re.IGNORECASE)
        return result

    def _convert_filter_function(self, nrql: str) -> str:
        """Convert NR filter() function to DQL funcIf() equivalent."""
        result = nrql
        pattern = r"\bfilter\s*\(\s*(average|avg|sum|count|max|min)\s*\(\s*([^)]*)\s*\)\s*,\s*WHERE\s+(.+?)\s*\)"

        def convert_filter(match):
            func = match.group(1).lower()
            field = match.group(2).strip() or "*"
            condition = match.group(3).strip()

            func_map = {
                "average": "avgIf",
                "avg": "avgIf",
                "sum": "sumIf",
                "count": "countIf",
                "max": "maxIf",
                "min": "minIf",
            }
            dt_func = func_map.get(func, f"{func}If")
            condition = self._convert_where_condition_only(condition)

            if field == "*" or not field:
                return f"{dt_func}({condition})"
            else:
                return f"{dt_func}({field}, {condition})"

        result = re.sub(pattern, convert_filter, result, flags=re.IGNORECASE)
        return result

    def _convert_apdex_function(self, nrql: str) -> str:
        """Convert NR apdex() function to DQL."""
        result = nrql
        pattern = r"\bapdex\s*\(\s*(?:duration\s*,\s*)?t\s*:\s*(\d+(?:\.\d+)?)\s*\)"

        def convert_apdex(match):
            threshold_sec = float(match.group(1))
            threshold_ns = int(threshold_sec * 1000000000)
            tolerating_ns = threshold_ns * 4
            return (
                f"((countIf(duration < {threshold_ns}) + "
                f"0.5 * countIf(duration >= {threshold_ns} and duration < {tolerating_ns})) / count())"
            )

        result = re.sub(pattern, convert_apdex, result, flags=re.IGNORECASE)
        return result

    def _convert_cdf_percentage_function(self, nrql: str) -> str:
        """Convert NR cdfPercentage() function to DQL."""
        result = nrql
        pattern = r"\bcdfPercentage\s*\(\s*([^,]+)\s*,\s*([^)]+)\s*\)"

        def convert_cdf(match):
            field = match.group(1).strip()
            thresholds_str = match.group(2).strip()
            thresholds = [float(t.strip()) for t in thresholds_str.split(",") if t.strip()]

            is_ms = ".ms" in field.lower()
            field_clean = re.sub(r"\.ms$", "", field, flags=re.IGNORECASE)

            if field_clean.lower() == "duration":
                dt_field = "duration"
            else:
                dt_field = field_clean

            bucket_exprs = ["__cdf_total__=count()"]
            for t in thresholds:
                if is_ms:
                    threshold_ns = int(t * 1000000)
                    label = f"under_{int(t)}ms"
                else:
                    threshold_ns = int(t * 1000000000)
                    label = f"under_{t}s"
                bucket_exprs.append(f"__cdf_{label}__=countIf({dt_field} < {threshold_ns})")

            return ", ".join(bucket_exprs)

        result = re.sub(pattern, convert_cdf, result, flags=re.IGNORECASE)
        return result

    def _convert_where_condition_only(self, condition: str) -> str:
        """Convert just a WHERE condition (not the whole clause) to DQL syntax."""
        result = condition

        result = re.sub(r"(\w+)\s+IS\s+NULL", r"isNull(\1)", result, flags=re.IGNORECASE)
        result = re.sub(r"(\w+)\s+IS\s+NOT\s+NULL", r"isNotNull(\1)", result, flags=re.IGNORECASE)

        result = re.sub(r"(\w+)\s*=\s*'([^']+)'", r'\1 == "\2"', result)
        result = re.sub(r'(\w+)\s*=\s*"([^"]+)"', r'\1 == "\2"', result)
        result = re.sub(r"(\w+)\s*=\s*(\d+)", r"\1 == \2", result)

        result = re.sub(r"\bAND\b", "and", result, flags=re.IGNORECASE)
        result = re.sub(r"\bOR\b", "or", result, flags=re.IGNORECASE)
        result = re.sub(r"\bNOT\b", "not", result, flags=re.IGNORECASE)

        return result

    def _map_attribute(self, attr: str) -> str:
        """Map NR attribute to DT attribute."""
        attr_clean = attr.strip()
        attr_lower = attr_clean.lower()

        if attr_lower in ATTR_MAP:
            return ATTR_MAP[attr_lower]

        attr_key = attr_lower.replace(".", "").replace("_", "")
        if attr_key in ATTR_MAP:
            return ATTR_MAP[attr_key]

        return attr_clean

    def _convert_facet(self, facet_clause: str) -> str:
        """Convert FACET clause to DQL by clause. Returns empty string for unconvertible CASES()."""
        if re.search(r"\bCASES\s*\(", facet_clause, re.IGNORECASE):
            cases_match = re.search(r"CASES\s*\((.+)\)", facet_clause, re.IGNORECASE | re.DOTALL)
            if cases_match:
                cases_content = cases_match.group(1)
                case_pattern = r"WHERE\s+(.+?)\s+AS\s+['\"]([^'\"]+)['\"]"
                cases = re.findall(case_pattern, cases_content, re.IGNORECASE)
                if cases:
                    if_expr = self._build_if_chain(cases)
                    return if_expr
            return ""

        fields = [f.strip() for f in facet_clause.split(",")]
        converted = [self._map_attribute(f) for f in fields]
        return ", ".join(converted)

    def _build_if_chain(self, cases: list) -> str:
        """Build nested if() expression from CASES conditions."""
        if not cases:
            return '"other"'

        converted_cases = []
        for condition, label in cases:
            dql_condition = self._convert_condition_to_dql(condition)
            converted_cases.append((dql_condition, label))

        result = '"other"'
        for condition, label in reversed(converted_cases):
            result = f'if({condition}, "{label}", else:{result})'

        return result

    def _convert_condition_to_dql(self, condition: str) -> str:
        """Convert a single NRQL condition to DQL syntax."""
        result = condition.strip()
        result = re.sub(r"(?<![!<>=])\s*=\s*(?![=])", " == ", result)
        result = re.sub(r"'([^']*)'", r'"\1"', result)
        result = self._map_attribute(result)
        return result

    def _convert_where(self, where_clause: str) -> str:
        """Convert WHERE clause to DQL filter."""
        result = where_clause

        # Handle entity.guid -- NR-specific
        guid_pattern = r"entity\.guid\s*=+\s*['\"]([A-Za-z0-9+/=]{20,})['\"]"
        guid_matches = re.findall(guid_pattern, result, re.IGNORECASE)

        for guid in guid_matches:
            if guid in self._guid_cache:
                entity_name = self._guid_cache[guid]
                entity_type = self._guid_types.get(guid, "")

                if entity_type == "SERVICE_LEVEL":
                    self._detected_slos.add(guid)
                    replacement = f'slo.name == "{entity_name}"'
                    self._current_warnings.append(
                        f'SLO GUID resolved to: {entity_name} -> Use: fetch slo | filter slo.name == "{entity_name}"'
                    )
                elif entity_type in ("APM_APPLICATION", "APPLICATION", "SERVICE"):
                    replacement = f'service.name == "{entity_name}"'
                    self._current_warnings.append(f"Service GUID resolved to: {entity_name}")
                else:
                    replacement = f'dt.entity.name == "{entity_name}"'
                    self._current_warnings.append(f"GUID resolved to: {entity_name}")
            else:
                try:
                    import base64

                    padded = guid + "=" * (4 - len(guid) % 4) if len(guid) % 4 else guid
                    decoded = base64.b64decode(padded).decode("utf-8")
                    parts = decoded.split("|")
                    entity_type = parts[2] if len(parts) > 2 else ""

                    if entity_type == "SERVICE_LEVEL":
                        self._detected_slos.add(guid)
                        replacement, warning = self._handle_slo_guid(guid)
                        self._current_warnings.append(warning)
                    else:
                        replacement = "__GUID_PLACEHOLDER__"
                        self._current_warnings.append(
                            f"GUID filter detected ({entity_type}) - replace with dt.entity filter. "
                            'Example: dt.entity.name == "your-svc-name"'
                        )
                except Exception:
                    replacement = "__GUID_PLACEHOLDER__"
                    self._current_warnings.append(
                        "GUID filter detected - replace with dt.entity filter. "
                        'Example: dt.entity.name == "your-svc-name"'
                    )

            result = re.sub(
                r"entity\.guid\s*=+\s*['\"]" + re.escape(guid) + r"['\"]",
                replacement,
                result,
                flags=re.IGNORECASE,
            )

        # Also catch entityGuid (camelCase variant)
        entity_guid_pattern = r"entityGuid\s*=+\s*['\"]([A-Za-z0-9+/=]{20,})['\"]"
        guid_matches2 = re.findall(entity_guid_pattern, result, re.IGNORECASE)

        for guid in guid_matches2:
            if guid in self._guid_cache:
                entity_name = self._guid_cache[guid]
                entity_type = self._guid_types.get(guid, "")
                if entity_type == "SERVICE_LEVEL":
                    self._detected_slos.add(guid)
                    replacement = f'slo.name == "{entity_name}"'
                    self._current_warnings.append(f"SLO GUID resolved: {entity_name}")
                else:
                    replacement = f'service.name == "{entity_name}"'
                    self._current_warnings.append(f"GUID resolved to: {entity_name}")
            else:
                try:
                    import base64

                    padded = guid + "=" * (4 - len(guid) % 4) if len(guid) % 4 else guid
                    decoded = base64.b64decode(padded).decode("utf-8")
                    parts = decoded.split("|")
                    entity_type = parts[2] if len(parts) > 2 else ""
                    if entity_type == "SERVICE_LEVEL":
                        self._detected_slos.add(guid)
                        replacement, warning = self._handle_slo_guid(guid)
                        self._current_warnings.append(warning)
                    else:
                        replacement = "__GUID_PLACEHOLDER__"
                        self._current_warnings.append("entityGuid filter detected - replace with dt.entity filter")
                except Exception:
                    replacement = "__GUID_PLACEHOLDER__"
                    self._current_warnings.append("entityGuid filter detected - replace with dt.entity filter")

            result = re.sub(
                r"entityGuid\s*=+\s*['\"]" + re.escape(guid) + r"['\"]",
                replacement,
                result,
                flags=re.IGNORECASE,
            )

        # NOT LIKE
        def convert_not_like(match):
            field = match.group(1)
            pattern = match.group(2)
            value = pattern.strip("%")
            return f'not(contains({field}, "{value}"))'

        result = re.sub(
            r"(\w+[\w.]*)\s+NOT\s+LIKE\s+['\"]([^'\"]+)['\"]",
            convert_not_like,
            result,
            flags=re.IGNORECASE,
        )

        # LIKE
        def convert_like(match):
            field = match.group(1)
            pattern = match.group(2)
            starts_wild = pattern.startswith("%")
            ends_wild = pattern.endswith("%")
            value = pattern.strip("%")

            if starts_wild and ends_wild:
                return f'contains({field}, "{value}")'
            elif starts_wild:
                return f'endsWith({field}, "{value}")'
            elif ends_wild:
                return f'startsWith({field}, "{value}")'
            else:
                return f'{field} == "{value}"'

        result = re.sub(
            r"(\w+[\w.]*)\s+LIKE\s+['\"]([^'\"]+)['\"]",
            convert_like,
            result,
            flags=re.IGNORECASE,
        )

        # RLIKE
        def convert_rlike(match):
            field = match.group(1)
            negated = match.group(2) is not None
            pattern = match.group(3)
            func = f'matchesPhrase({field}, "{pattern}")'
            if negated:
                func = f"not({func})"
            return func

        result = re.sub(
            r"(\w+[\w.]*)\s+(NOT\s+)?RLIKE\s+['\"]([^'\"]+)['\"]",
            convert_rlike,
            result,
            flags=re.IGNORECASE,
        )

        # IN clauses
        def convert_in_clause(match):
            field = match.group(1)
            negated = match.group(2) is not None
            values_str = match.group(3)
            values_str = values_str.replace("'", '"')
            func = f"in({field}, {values_str})"
            if negated:
                func = f"not({func})"
            return func

        result = re.sub(
            r"(\w+[\w.]*)\s+(NOT\s+)?IN\s*\(([^)]+)\)",
            convert_in_clause,
            result,
            flags=re.IGNORECASE,
        )

        # BETWEEN
        def convert_between(match):
            field = match.group(1)
            negated = match.group(2) is not None
            low = match.group(3)
            high = match.group(4)
            if negated:
                return f"({field} < {low} or {field} > {high})"
            return f"({field} >= {low} and {field} <= {high})"

        result = re.sub(
            r"(\w+[\w.]*)\s+(NOT\s+)?BETWEEN\s+([^\s]+)\s+AND\s+([^\s]+)",
            convert_between,
            result,
            flags=re.IGNORECASE,
        )

        # IS NOT NULL / IS NULL
        result = re.sub(r"(\w+[\w.]*)\s+IS\s+NOT\s+NULL", r"isNotNull(\1)", result, flags=re.IGNORECASE)
        result = re.sub(r"(\w+[\w.]*)\s+IS\s+NULL\b", r"isNull(\1)", result, flags=re.IGNORECASE)

        # IS true/false
        result = re.sub(r"\bIS\s+true\b", "== true", result, flags=re.IGNORECASE)
        result = re.sub(r"\bIS\s+false\b", "== false", result, flags=re.IGNORECASE)

        # AND/OR/NOT
        result = re.sub(r"\bAND\b", "and", result)
        result = re.sub(r"\bOR\b", "or", result)
        result = re.sub(r"\bNOT\b", "not", result)

        # Quotes
        result = re.sub(r"(?<![!<>])=\s*'([^']*)'", r'== "\1"', result)
        result = re.sub(r"!=\s*'([^']*)'", r'!= "\1"', result)
        result = re.sub(r"(?<![!<>=])\s*=\s*(?![=])", " == ", result)

        # Map attributes
        sorted_attrs = sorted(ATTR_MAP.items(), key=lambda x: len(x[0]), reverse=True)
        for nr_attr, dt_attr in sorted_attrs:
            pattern = r"(?<![.\w])" + re.escape(nr_attr) + r"(?![.\w])"
            result = re.sub(pattern, dt_attr, result, flags=re.IGNORECASE)

        # Replace GUID placeholder
        result = result.replace(
            "__GUID_PLACEHOLDER__",
            '/* REPLACE WITH: service.name == "your-service-name" OR dt.entity.service == "SERVICE-XXXXX" */',
        )

        # Duration unit conversions
        def replace_duration_with_unit(match):
            operator = match.group(1)
            value = float(match.group(2))
            unit = match.group(3).lower()
            multipliers = {
                "ns": 1, "us": 1000, "ms": 1000000,
                "s": 1000000000, "m": 60000000000, "h": 3600000000000,
            }
            ns_value = int(value * multipliers.get(unit, 1000000))
            return f"{operator} {ns_value}"

        result = re.sub(
            r"(>=|<=|>|<|==|!=)\s*(\d+(?:\.\d+)?)(ns|us|ms|s|m|h|d)\b",
            replace_duration_with_unit,
            result,
            flags=re.IGNORECASE,
        )

        # duration.ms conversions
        def convert_duration_ms(match):
            operator = match.group(1)
            value = match.group(2)
            try:
                ns_value = int(float(value) * 1000000)
                return f"duration {operator} {ns_value}"
            except Exception:
                return f"duration {operator} {value}000000"

        result = re.sub(
            r"\bduration\.ms\s*(>=|<=|>|<|==|!=)\s*(\d+(?:\.\d+)?)",
            convert_duration_ms,
            result,
            flags=re.IGNORECASE,
        )

        result = re.sub(r"\bduration\.ms\b", "duration", result, flags=re.IGNORECASE)

        return result

    # ------------------------------------------------------------------
    # NRQL Parsing helpers
    # ------------------------------------------------------------------

    def _parse_select_fields(self, select_clause: str) -> List[str]:
        """Parse field names from SELECT clause."""
        cleaned = re.sub(r"\w+\s*\([^)]*\)", "", select_clause)
        fields = [f.strip() for f in cleaned.split(",") if f.strip()]
        fields = [re.sub(r"\s+AS\s+\w+", "", f, flags=re.IGNORECASE).strip() for f in fields]
        return [f for f in fields if f and f != "*"]

    def _extract_from(self, nrql: str) -> Optional[str]:
        match = re.search(r"\bFROM\s+(\w+)", nrql, re.IGNORECASE)
        return match.group(1).lower() if match else None

    def _extract_select(self, nrql: str) -> Optional[str]:
        select_match = re.search(r"\bSELECT\s+", nrql, re.IGNORECASE)
        if not select_match:
            return None

        start = select_match.end()

        in_single_quote = False
        in_double_quote = False
        i = start
        while i < len(nrql):
            ch = nrql[i]
            if ch == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
            elif ch == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
            elif not in_single_quote and not in_double_quote:
                if nrql[i : i + 4].upper() == "FROM" and (i == 0 or not nrql[i - 1].isalnum()):
                    after = i + 4
                    if after >= len(nrql) or not nrql[after].isalnum():
                        return nrql[start:i].strip()
            i += 1

        return nrql[start:].strip()

    def _extract_where(self, nrql: str) -> Optional[str]:
        def protect_inner_where(s):
            result_chars: List[str] = []
            depth = 0
            i = 0
            while i < len(s):
                if s[i] == "(":
                    depth += 1
                    result_chars.append(s[i])
                elif s[i] == ")":
                    depth -= 1
                    result_chars.append(s[i])
                elif depth > 0 and s[i : i + 5].upper() == "WHERE":
                    result_chars.append("__INNER_WHERE__")
                    i += 4
                else:
                    result_chars.append(s[i])
                i += 1
            return "".join(result_chars)

        protected_nrql = protect_inner_where(nrql)

        match = re.search(
            r"\bWHERE\s+(.+?)(?:\bFACET\b|\bSINCE\b|\bUNTIL\b|\bLIMIT\b|\bTIMESERIES\b|\bCOMPARE\b|$)",
            protected_nrql,
            re.IGNORECASE,
        )
        if match:
            result = match.group(1).strip()
            result = result.replace("__INNER_WHERE__", "where")
            return result

        match = re.search(
            r"\bFACET\s+[^W]+\bWHERE\s+(.+?)(?:\bSINCE\b|\bUNTIL\b|\bLIMIT\b|\bTIMESERIES\b|\bCOMPARE\b|$)",
            protected_nrql,
            re.IGNORECASE,
        )
        if match:
            result = match.group(1).strip()
            result = result.replace("__INNER_WHERE__", "where")
            return result

        return None

    def _extract_facet(self, nrql: str) -> Optional[str]:
        cases_match = re.search(
            r"\bFACET\s+(CASES\s*\(.+?\))\s*(?:TIMESERIES|SINCE|UNTIL|LIMIT|COMPARE|$)",
            nrql,
            re.IGNORECASE | re.DOTALL,
        )
        if cases_match:
            facet_start = nrql.upper().find("FACET")
            if facet_start == -1:
                return None

            cases_start = nrql.upper().find("CASES(", facet_start)
            if cases_start == -1:
                return None

            paren_count = 0
            end_pos = cases_start
            for i, char in enumerate(nrql[cases_start:]):
                if char == "(":
                    paren_count += 1
                elif char == ")":
                    paren_count -= 1
                    if paren_count == 0:
                        end_pos = cases_start + i + 1
                        break

            facet = nrql[facet_start + 6 : end_pos].strip()
            return facet

        match = re.search(
            r"\bFACET\s+(.+?)(?:\bWHERE\b|\bSINCE\b|\bUNTIL\b|\bLIMIT\b|\bTIMESERIES\b|\bCOMPARE\b|$)",
            nrql,
            re.IGNORECASE,
        )
        if match:
            facet = match.group(1).strip()
            facet = re.sub(r"`([^`]+)`", r"\1", facet)
            return facet
        return None

    def _extract_limit(self, nrql: str) -> Optional[int]:
        match = re.search(r"\bLIMIT\s+(\d+)", nrql, re.IGNORECASE)
        return int(match.group(1)) if match else None
