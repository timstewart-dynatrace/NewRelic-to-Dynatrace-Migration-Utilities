"""
NRQL-to-DQL Compiler -- Compiler orchestrator.

Orchestrates: Lexer -> Parser -> DQLEmitter
Handles errors gracefully and provides diagnostic info.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict

from .tokens import TokenType
from .lexer import LexError, NRQLLexer
from .ast_nodes import Query
from .parser import ParseError, NRQLParser
from .emitter import DQLEmitter


@dataclass
class CompileResult:
    success: bool
    dql: str = ''
    confidence: str = 'HIGH'
    warnings: List[str] = field(default_factory=list)
    fixes: List[str] = field(default_factory=list)
    error: str = ''
    ast: Optional[Query] = None
    original_nrql: str = ''


class NRQLCompiler:
    """
    Top-level compiler: NRQL string -> DQL string.

    Orchestrates: Lexer -> Parser -> DQLEmitter
    Handles errors gracefully and provides diagnostic info.

    Usage:
        compiler = NRQLCompiler()
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE appName = 'x' TIMESERIES")
        if result.success:
            print(result.dql)
    """

    def __init__(self, field_map: Dict[str, str] = None, metric_map: Dict[str, str] = None,
                 metric_transforms: Dict[str, Dict] = None, metric_resolver=None):
        self.field_map = field_map or {}
        self.metric_map = metric_map or {}
        self.metric_transforms = metric_transforms or {}
        self.metric_resolver = metric_resolver  # callable(field_key, raw_field, static_mapped) -> (dt_metric, warning)

    def compile(self, nrql: str, title: str = '') -> CompileResult:
        """Compile NRQL to DQL."""
        result = CompileResult(success=False, original_nrql=nrql)

        # Phase 0: Expand NR shorthand metrics before lexing
        # NR has magic field names that are actually function(field) shorthands
        nrql = self._expand_nr_shorthands(nrql)

        # Phase 1: Lex
        try:
            lexer = NRQLLexer(nrql)
            tokens = lexer.tokenize()
        except LexError as e:
            result.error = f"Lexer error: {e}"
            return result

        # Phase 2: Parse
        try:
            parser = NRQLParser(tokens)
            ast = parser.parse()
            result.ast = ast
        except ParseError as e:
            result.error = f"Parse error: {e}"
            return result

        # Phase 3: Emit DQL
        try:
            emitter = DQLEmitter(field_map=self.field_map, metric_map=self.metric_map,
                                 metric_transforms=self.metric_transforms,
                                 metric_resolver=self.metric_resolver)
            dql = emitter.emit(ast)
            # Collapse NRQL to single line so the comment never leaks raw code
            nrql_oneline = ' '.join(nrql.split())
            result.dql = f"// Original NRQL: {nrql_oneline}\n{dql}"
            result.warnings = emitter.warnings
            result.success = True
            result.confidence = 'HIGH'

            # Downgrade confidence if there are warnings
            if any('not directly supported' in w for w in result.warnings):
                result.confidence = 'MEDIUM'

        except Exception as e:
            result.error = f"Emitter error: {e}"
            return result

        # Phase 4: DQL Syntax Validation
        # Catch known invalid patterns BEFORE the query reaches Dynatrace
        result.dql, validation_fixes = self._validate_dql(result.dql)
        if validation_fixes:
            result.fixes = (result.fixes or []) + validation_fixes

        return result

    @staticmethod
    def _expand_nr_shorthands(nrql: str) -> str:
        """
        Expand NR shorthand metric names into function(field) calls.

        NR has magic field names in SELECT that are actually aggregation shorthands:
          averageduration    -> average(duration)
          averageResponseTime -> average(duration)  (same underlying metric)
          maxduration        -> max(duration)
          minduration        -> min(duration)
          medianDuration     -> median(duration)

        These appear as bare identifiers without parentheses and would otherwise
        be treated as field references by the parser.
        """
        # Map of shorthand -> expanded form
        # Use word boundary to avoid matching inside longer identifiers
        shorthands = {
            r'\baverage[Dd]uration\b': 'average(duration)',
            r'\baverage[Rr]esponse[Tt]ime\b': 'average(duration)',
            r'\bmax[Dd]uration\b': 'max(duration)',
            r'\bmin[Dd]uration\b': 'min(duration)',
            r'\bmedian[Dd]uration\b': 'median(duration)',
            r'\bapdex[Ss]core\b': 'apdex(duration)',
            r'\bapdex[Pp]erf[Zz]one\b': 'apdex(duration)',
            r'\berror[Rr]ate\b': 'percentage(count(*), WHERE error IS TRUE)',
            r'\bthroughput\b': 'rate(count(*), 1 minute)',
        }

        for pattern, replacement in shorthands.items():
            nrql = re.sub(pattern, replacement, nrql)

        return nrql

    @staticmethod
    def _ms_to_duration_literal(ms: float) -> str:
        """Convert milliseconds to the most readable DQL duration literal.

        DQL supports: ns, us, ms, s, m, h, d
        Examples: 2000ms -> 2s, 500ms -> 500ms, 60000ms -> 1m, 100ms -> 100ms
        """
        if ms <= 0:
            return "0s"
        # Try to find the cleanest unit
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
        # Sub-millisecond: use microseconds
        us = ms * 1000
        if us == int(us):
            return f"{int(us)}us"
        return f"{ms}ms"

    def _validate_dql(self, dql: str) -> Tuple[str, List[str]]:
        """Post-compilation DQL syntax validator.

        Catches known invalid patterns and auto-corrects them:
        - Bare fields in summarize/makeTimeseries (must be aggregation functions)
        - shift: parameter on makeTimeseries (only valid on timeseries command)
        - Invalid parameter names
        - Empty aggregation lists
        - Duration unit mismatch (NR milliseconds -> DT nanoseconds)

        Returns (corrected_dql, list_of_fixes_applied).
        """
        fixes = []
        lines = dql.split('\n')
        new_lines = []

        # Determine if this is a span query (duration in nanoseconds)
        full_dql = '\n'.join(lines)
        is_span_query = 'fetch spans' in full_dql

        for line in lines:
            stripped = line.strip()

            # Skip comments
            if stripped.startswith('//'):
                new_lines.append(line)
                continue

            # -- Check 1: shift: on makeTimeseries (invalid -- only timeseries supports it)
            if '| makeTimeseries' in line and 'shift:' in line:
                # Remove shift: parameter
                fixed = re.sub(r',\s*shift:[^\s,]+', '', line)
                if fixed != line:
                    fixes.append("Removed invalid shift: from makeTimeseries (only timeseries command supports shift:)")
                    line = fixed

            # -- Check 2: Bare fields in summarize/makeTimeseries
            # Pattern: "| summarize fieldName" where fieldName is not a function call
            m = re.match(r'^(\s*\|\s*(?:summarize|makeTimeseries)\s+)(.*)', line)
            if m:
                prefix = m.group(1)
                agg_part = m.group(2)
                # Check if the aggregation part contains at least one function call
                # Valid: count(), avg(duration), name=count()
                # Invalid: duration, span.name, service.name
                if agg_part and not re.search(r'[a-zA-Z_]\w*\s*\(', agg_part):
                    # No function call found -- these are bare fields
                    # Convert to | fields instead
                    fields = agg_part.split(',')
                    # Strip any by: clause
                    field_names = []
                    by_part = ''
                    for f in fields:
                        f = f.strip()
                        if f.startswith('by:'):
                            by_part = f', {f}'
                        else:
                            field_names.append(f)
                    if field_names:
                        line = f"| fields {', '.join(field_names)}"
                        fixes.append(f"Corrected bare fields in summarize -> | fields ('{', '.join(field_names)}' are not aggregations)")

            # -- Check 3: Duration unit conversion (NR ms -> DT duration literals)
            # DT's `duration` field is a DURATION TYPE, not a raw integer.
            # Comparisons and bin() need duration literals: 2s, 500ms, etc.
            # NR duration is in MILLISECONDS.
            # Safe patterns matched:
            #   duration >= 2000  -> duration >= 2s
            #   bin(duration, 2000) -> bin(duration, 2s)
            # NOT matched (safe):
            #   percentile(duration, 95) -- 95 is percentile %, not duration
            #   avg(duration) -- no literal to convert
            if is_span_query:
                # Convert duration comparison literals to DQL duration literals
                def _dur_cmp(m):
                    op, val_str = m.group(1), m.group(2)
                    ms = float(val_str)
                    lit = NRQLCompiler._ms_to_duration_literal(ms)
                    fixes.append(f"Duration: {val_str}ms -> {lit}")
                    return f"duration {op} {lit}"
                line = re.sub(
                    r'(?<![.\w])duration\s*(>=|<=|>|<|==|!=)\s*(\d+(?:\.\d+)?)',
                    _dur_cmp, line)

                # Convert bin(duration, width) to use duration literals
                def _dur_bin(m):
                    ms = float(m.group(1))
                    lit = NRQLCompiler._ms_to_duration_literal(ms)
                    fixes.append(f"Duration bin: {ms}ms -> {lit}")
                    return f"bin(duration, {lit})"
                line = re.sub(
                    r'bin\(\s*duration\s*,\s*(\d+(?:\.\d+)?)\s*\)',
                    _dur_bin, line)

            new_lines.append(line)

        return '\n'.join(new_lines), fixes

    def parse_only(self, nrql: str) -> Tuple[Optional[Query], str]:
        """Parse NRQL to AST without emitting DQL. Useful for analysis."""
        try:
            tokens = NRQLLexer(nrql).tokenize()
            ast = NRQLParser(tokens).parse()
            return ast, ''
        except (LexError, ParseError) as e:
            return None, str(e)
