"""
DQL Syntax Validator.

Validates DQL syntax based on Dynatrace's DQL grammar rules.
Catches common NRQL->DQL conversion errors BEFORE upload.
"""

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class DQLValidationError:
    line: int
    column: int
    message: str
    severity: str  # ERROR, WARNING


@dataclass
class DQLValidationResult:
    valid: bool
    errors: List[DQLValidationError]
    query: str


class DQLSyntaxValidator:
    """
    Validates DQL syntax based on Dynatrace's DQL grammar rules.
    Catches common NRQL->DQL conversion errors BEFORE upload.
    """

    # Case-INSENSITIVE patterns (things that are wrong regardless of case)
    INVALID_PATTERNS_ICASE = [
        # Single = for comparison (should be ==)
        (r'(?<![=!<>])\s*=\s*(?![=])"', "Single '=' used for comparison -- use '==' instead"),
        (r'(?<![=!<>])\s*=\s*(?![=])\d', "Single '=' used for comparison -- use '==' instead"),
        (r'(?<![=!<>])\s*=\s*(?![=])\$', "Single '=' used for comparison -- use '==' instead"),

        # !== is not valid DQL (should be !=)
        (r'!==', "'!==' is not valid in DQL -- use '!=' instead"),

        # Single quotes for strings (should be double quotes)
        (r"==\s*'[^']*'", "Single quotes used for string -- use double quotes in DQL"),

        # LIKE keyword
        (r'\bLIKE\b', "'LIKE' is not valid in DQL -- use contains(), startsWith(), or endsWith()"),

        # <> for not equal
        (r'<>', "'<>' should be '!=' in DQL"),

        # Double pipes
        (r'\|\|', "'||' is not valid in DQL -- use 'or' for logical OR"),

        # Semicolons
        (r';(?!\s*$)', "Semicolons are not used in DQL"),

        # NR-specific functions
        (r'\bpercentage\s*\(', "'percentage()' is not a valid DQL function -- use countIf()/count()"),
        (r'countIf\s*\([^)]*countIf\s*\(', "Nested aggregation: countIf() inside countIf() -- DQL error NO_NESTED_AGGREGATIONS"),
        (r'countIf\s*\([^)]*\bcount\s*\(', "Nested aggregation: count() inside countIf() -- DQL error NO_NESTED_AGGREGATIONS"),
        (r'\bsum\s*\([^)]*\bavg\s*\(', "Nested aggregation: avg() inside sum() -- DQL error NO_NESTED_AGGREGATIONS"),
        (r'\bmax\s*\([^)]*\bcount\s*\(', "Nested aggregation: count() inside max() -- DQL error NO_NESTED_AGGREGATIONS"),
        (r'\buniqueCount\s*\(', "'uniqueCount()' should be 'countDistinct()' in DQL"),
        (r'\bfunnel\s*\(', "'funnel()' is not available in DQL"),

        # Malformed contains/startsWith/endsWith - must have parentheses around them for negation
        # Wrong: not contains(x, y)  or  contains(not, y)
        # Right: not(contains(x, y))
        (r'\bnot\s+contains\s*\(', "'not contains()' is invalid -- use 'not(contains(field, value))'"),
        (r'\bcontains\s*\(\s*not\s*,', "'contains(not, ...)' is invalid -- use 'not(contains(field, value))'"),
        (r'\bnot\s+startsWith\s*\(', "'not startsWith()' is invalid -- use 'not(startsWith(field, value))'"),
        (r'\bnot\s+endsWith\s*\(', "'not endsWith()' is invalid -- use 'not(endsWith(field, value))'"),

        # takeLast/takeFirst in timeseries/makeTimeseries (only valid in summarize)
        (r'(?:make)?[Tt]imeseries\s+.*\btakeLast\s*\(', "'takeLast()' is not valid in timeseries/makeTimeseries -- use avg(), max(), or sum()"),
        (r'(?:make)?[Tt]imeseries\s+.*\btakeFirst\s*\(', "'takeFirst()' is not valid in timeseries/makeTimeseries -- use avg(), max(), or sum()"),
        (r'(?:make)?[Tt]imeseries\s+.*\btakeAny\s*\(', "'takeAny()' is not valid in timeseries/makeTimeseries -- use avg(), max(), or sum()"),
    ]

    # Case-SENSITIVE patterns (where case matters)
    INVALID_PATTERNS_CASE = [
        # WHERE keyword (uppercase only - lowercase 'where' inside strings is fine)
        (r'\bWHERE\b', "'WHERE' is not valid in DQL -- use 'filter' instead"),

        # AND/OR uppercase (lowercase is correct)
        (r'\bAND\b', "'AND' should be lowercase 'and' in DQL"),
        (r'\bOR\b', "'OR' should be lowercase 'or' in DQL"),
        (r'\bNOT\b', "'NOT' should be lowercase 'not' in DQL"),

        # IS NULL uppercase
        (r'\bIS\s+NULL\b', "'IS NULL' should be 'isNull(field)' in DQL"),
        (r'\bIS\s+NOT\s+NULL\b', "'IS NOT NULL' should be 'isNotNull(field)' in DQL"),

        # FACET keyword
        (r'\bFACET\b', "'FACET' is not valid in DQL -- use 'by: {field}' instead"),

        # SELECT keyword
        (r'\bSELECT\b', "'SELECT' is not valid in DQL"),

        # FROM keyword (uppercase)
        (r'\bFROM\b', "'FROM' is not valid in DQL -- use 'fetch <type>'"),

        # SINCE/UNTIL keywords
        (r'\bSINCE\b', "'SINCE' is not valid in DQL -- use from: parameter"),
        (r'\bUNTIL\b', "'UNTIL' is not valid in DQL -- use to: parameter"),
    ]

    def validate(self, dql: str) -> DQLValidationResult:
        """Validate a DQL query and return detailed results."""
        errors: List[DQLValidationError] = []

        # Skip validation for comment-only or empty queries
        lines = dql.strip().split('\n')
        non_comment_lines = [l for l in lines if l.strip() and not l.strip().startswith('//')]

        if not non_comment_lines:
            return DQLValidationResult(valid=True, errors=[], query=dql)

        dql_only = '\n'.join(non_comment_lines)

        # Check case-insensitive patterns
        for pattern, message in self.INVALID_PATTERNS_ICASE:
            try:
                for match in re.finditer(pattern, dql_only, re.IGNORECASE):
                    line_num, col = self._get_position(dql_only, match.start())
                    errors.append(DQLValidationError(
                        line=line_num,
                        column=col,
                        message=message,
                        severity="ERROR"
                    ))
            except re.error:
                continue

        # Check case-sensitive patterns (NO re.IGNORECASE)
        for pattern, message in self.INVALID_PATTERNS_CASE:
            try:
                for match in re.finditer(pattern, dql_only):  # No IGNORECASE!
                    line_num, col = self._get_position(dql_only, match.start())
                    errors.append(DQLValidationError(
                        line=line_num,
                        column=col,
                        message=message,
                        severity="ERROR"
                    ))
            except re.error:
                continue

        # Check balanced parentheses
        paren_error = self._check_balanced_parens(dql_only)
        if paren_error:
            errors.append(paren_error)

        # Check balanced braces
        brace_error = self._check_balanced_braces(dql_only)
        if brace_error:
            errors.append(brace_error)

        # Check first command
        first_cmd_error = self._check_first_command(dql_only)
        if first_cmd_error:
            errors.append(first_cmd_error)

        # Check performance anti-patterns (warnings, not errors)
        anti_pattern_warnings = self._check_anti_patterns(dql_only)
        errors.extend(anti_pattern_warnings)

        return DQLValidationResult(
            valid=len([e for e in errors if e.severity == "ERROR"]) == 0,
            errors=errors,
            query=dql
        )

    def _get_position(self, text: str, index: int) -> Tuple[int, int]:
        """Get line number and column from character index."""
        lines = text[:index].split('\n')
        line_num = len(lines)
        col = len(lines[-1]) + 1 if lines else 1
        return line_num, col

    def _check_balanced_parens(self, dql: str) -> Optional[DQLValidationError]:
        """Check for balanced parentheses."""
        count = 0
        for i, char in enumerate(dql):
            if char == '(':
                count += 1
            elif char == ')':
                count -= 1
                if count < 0:
                    line, col = self._get_position(dql, i)
                    return DQLValidationError(
                        line=line, column=col,
                        message="Unbalanced parentheses -- extra ')'",
                        severity="ERROR"
                    )
        if count > 0:
            return DQLValidationError(
                line=1, column=1,
                message=f"Unbalanced parentheses -- missing {count} closing ')'",
                severity="ERROR"
            )
        return None

    def _check_balanced_braces(self, dql: str) -> Optional[DQLValidationError]:
        """Check for balanced braces."""
        count = 0
        for i, char in enumerate(dql):
            if char == '{':
                count += 1
            elif char == '}':
                count -= 1
                if count < 0:
                    line, col = self._get_position(dql, i)
                    return DQLValidationError(
                        line=line, column=col,
                        message="Unbalanced braces -- extra '}'",
                        severity="ERROR"
                    )
        if count > 0:
            return DQLValidationError(
                line=1, column=1,
                message=f"Unbalanced braces -- missing {count} closing '}}'",
                severity="ERROR"
            )
        return None

    def _check_first_command(self, dql: str) -> Optional[DQLValidationError]:
        """Check that query starts with valid DQL command."""
        valid_starts = {'fetch', 'timeseries', 'data'}

        for line in dql.split('\n'):
            line = line.strip()
            if line and not line.startswith('//'):
                first_word = line.split()[0].lower() if line.split() else ''
                if first_word not in valid_starts:
                    return DQLValidationError(
                        line=1, column=1,
                        message=f"DQL must start with 'fetch', 'timeseries', or 'data', not '{first_word}'",
                        severity="ERROR"
                    )
                break
        return None

    def _check_anti_patterns(self, dql: str) -> List[DQLValidationError]:
        """Check for DQL performance anti-patterns (emit warnings, not errors).

        Based on Dynatrace DQL best practices:
        - Filter early, sort last, limit last
        - Avoid sort before filter
        - Avoid limit before summarize
        - Avoid negation filters (prefer filterOut)
        """
        warnings: List[DQLValidationError] = []
        lines = dql.strip().split('\n')

        # Parse pipeline stages in order
        stages = []
        for line in lines:
            stripped = line.strip().lstrip('| ')
            if not stripped or stripped.startswith('//'):
                continue
            cmd = stripped.split()[0].lower() if stripped.split() else ''
            stages.append(cmd)

        # Anti-pattern: sort immediately after fetch (before filter)
        for i, stage in enumerate(stages):
            if stage == 'sort' and i > 0:
                # Check if there's a filter before this sort
                has_filter_before = any(s in ('filter', 'filterout', 'search') for s in stages[:i])
                if not has_filter_before and stages[0] in ('fetch',):
                    warnings.append(DQLValidationError(
                        line=1, column=1,
                        message="Performance: 'sort' before any filter -- filter first, sort last",
                        severity="WARNING"
                    ))
                break  # Only check first sort

        # Anti-pattern: limit before summarize
        limit_idx = None
        summarize_idx = None
        for i, stage in enumerate(stages):
            if stage == 'limit' and limit_idx is None:
                limit_idx = i
            if stage in ('summarize', 'maketimeseries') and summarize_idx is None:
                summarize_idx = i

        if limit_idx is not None and summarize_idx is not None and limit_idx < summarize_idx:
            warnings.append(DQLValidationError(
                line=1, column=1,
                message="Performance: 'limit' before 'summarize' aggregates over a subset -- summarize first, limit last",
                severity="WARNING"
            ))

        return warnings
