"""DQL syntax validator and auto-fixer."""
import re
from typing import List, Tuple


def ms_to_dql_duration(ms: float) -> str:
    """Convert milliseconds to the most readable DQL duration literal."""
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


class DQLValidator:
    """Validates and fixes DQL syntax issues"""

    def __init__(self):
        self.fixes = []

    def validate_and_fix(self, dql: str, context: str = "") -> Tuple[str, List[str]]:
        """
        Validate DQL and fix any syntax issues.
        Returns (fixed_dql, list_of_fixes_applied)
        """
        self.fixes = []

        if not dql or not dql.strip():
            return dql, []

        # Apply fixes in order
        dql = self._fix_variables(dql)
        dql = self._fix_backticks(dql)
        dql = self._fix_quotes(dql)
        dql = self._fix_comparison_operators(dql)
        dql = self._fix_logical_operators(dql)
        dql = self._fix_null_checks(dql)
        dql = self._fix_like_patterns(dql)
        dql = self._fix_where_in_filter(dql)
        dql = self._fix_timeseries_count(dql, context)
        dql = self._fix_invalid_functions(dql)
        dql = self._fix_broken_by_clause(dql)
        dql = self._fix_field_names(dql)
        dql = self._fix_duplicate_aggregations(dql)
        dql = self._fix_percentile_naming(dql)
        dql = self._fix_as_aliases(dql)
        dql = self._fix_bare_field_in_summarize(dql)
        dql = self._fix_nrql_subqueries(dql)
        dql = self._fix_metric_names(dql)
        dql = self._fix_duration_units(dql)
        dql = self._fix_negation_to_filterout(dql)
        dql = self._fix_array_count_without_expand(dql)
        dql = self._fix_whitespace(dql)

        return dql, self.fixes

    def _fix_where_in_filter(self, dql: str) -> str:
        """Fix 'where' keyword inside filter clauses - should be 'and'"""
        # Pattern: | filter ... where ... (where should be and)
        # But don't replace 'where' inside strings
        lines = dql.split('\n')
        fixed_lines = []

        for line in lines:
            if '| filter' in line.lower() or line.strip().lower().startswith('filter'):
                # Replace 'where' with 'and' but preserve strings
                # Simple approach: split on 'where' (case insensitive) outside quotes
                result = []
                in_string = False
                quote_char = None
                i = 0
                line_lower = line.lower()

                while i < len(line):
                    # Track string boundaries
                    if line[i] in '"\'':
                        if not in_string:
                            in_string = True
                            quote_char = line[i]
                        elif line[i] == quote_char:
                            in_string = False
                        result.append(line[i])
                        i += 1
                    elif not in_string and line_lower[i:i+5] == 'where':
                        result.append('and')
                        i += 5
                        self.fixes.append("Changed 'where' to 'and' in filter clause")
                    else:
                        result.append(line[i])
                        i += 1

                fixed_lines.append(''.join(result))
            else:
                fixed_lines.append(line)

        return '\n'.join(fixed_lines)

    def _fix_duplicate_aggregations(self, dql: str) -> str:
        """Fix duplicate aggregation functions like count(), count(), count()"""

        # Match the aggregation list after makeTimeseries or summarize
        for cmd in ['makeTimeseries', 'summarize']:
            pattern = rf'({cmd}\s+)(.*?)(\s*,\s*by:\s*\{{|$)'
            match = re.search(pattern, dql, re.IGNORECASE | re.DOTALL)
            if not match:
                continue

            prefix = match.group(1)
            agg_section = match.group(2).strip()
            suffix = match.group(3)

            # Split aggregations on commas (but not commas inside parentheses)
            aggs = []
            depth = 0
            current = ''
            for ch in agg_section:
                if ch in ('(', '{', '['):
                    depth += 1
                    current += ch
                elif ch in (')', '}', ']'):
                    depth -= 1
                    current += ch
                elif ch == ',' and depth == 0:
                    aggs.append(current.strip())
                    current = ''
                else:
                    current += ch
            if current.strip():
                aggs.append(current.strip())

            if len(aggs) <= 1:
                continue

            # Deduplicate: keep unique aggregations only
            seen = {}
            unique_aggs = []
            for agg in aggs:
                # Normalize for comparison: strip alias prefix (e.g., "total = count()" -> "count()")
                normalized = re.sub(r'^\w+\s*=\s*', '', agg).strip().lower()
                if normalized not in seen:
                    seen[normalized] = agg
                    unique_aggs.append(agg)

            if len(unique_aggs) < len(aggs):
                removed = len(aggs) - len(unique_aggs)
                dql = dql[:match.start()] + prefix + ', '.join(unique_aggs) + suffix + dql[match.end():]
                self.fixes.append(f"Removed {removed} duplicate aggregation(s)")

        return dql

    def _fix_percentile_naming(self, dql: str) -> str:
        """
        Fix unnamed percentile() in makeTimeseries/summarize.

        DQL requires named aggregations when percentile has a second argument,
        because the comma is ambiguous to the parser.

        BAD:  makeTimeseries percentile(duration, 99), by: {...}
        GOOD: makeTimeseries p99=percentile(duration, 99), by: {...}
        """
        # Only process if there's a percentile in a makeTimeseries/summarize context
        has_context = False
        for cmd in ['makeTimeseries', 'summarize']:
            if cmd.lower() in dql.lower() and 'percentile(' in dql.lower():
                has_context = True
                break

        if not has_context:
            return dql

        # Match percentile(field, N) -- we'll check for existing alias separately
        pattern = r'percentile\s*\(\s*([^,)]+?)\s*,\s*(\d+)\s*\)'

        def name_percentile(match):
            full = match.group(0)
            field = match.group(1).strip()
            pct = match.group(2).strip()

            # Check if already named: look for "alias=" immediately before
            # Use match.string (the current string being processed) for accurate offsets
            start = match.start()
            prefix = match.string[max(0, start - 30):start]
            if re.search(r'\w+\s*=\s*$', prefix):
                return full  # Already named, don't touch

            return f'p{pct}=percentile({field}, {pct})'

        new_dql = re.sub(pattern, name_percentile, dql)
        if new_dql != dql:
            self.fixes.append("Named percentile aggregation (DQL requires alias for positional params)")
            dql = new_dql

        # Defensive: clean up any double-alias like "p95=p95=expr" -> "p95=expr"
        dql = re.sub(r'(\b\w+)=\1=', r'\1=', dql)

        # Sanitize numeric-leading aliases: 95th=expr -> _95th=expr
        dql = re.sub(r'(?<=[\s,])(\d+\w*)=(?!=)', r'_\1=', dql)

        return dql

    def _fix_as_aliases(self, dql: str) -> str:
        """
        Fix 'expression as alias' syntax in by: clauses.

        DQL uses 'alias=expression' not 'expression as alias'.

        BAD:  by: {substring(logger, ...) as Logger, error.message as Message}
        GOOD: by: {Logger=substring(logger, ...), Message=error.message}
        """
        # Find by: {...} clauses
        by_pattern = r'(by:\s*\{)(.*?)(\})'

        def fix_by_aliases(match):
            prefix = match.group(1)
            content = match.group(2)
            suffix = match.group(3)

            if ' as ' not in content.lower():
                return match.group(0)

            # Split on commas respecting parentheses depth
            parts = []
            depth = 0
            current = ''
            for ch in content:
                if ch in ('(', '{', '['):
                    depth += 1
                    current += ch
                elif ch in (')', '}', ']'):
                    depth -= 1
                    current += ch
                elif ch == ',' and depth == 0:
                    parts.append(current.strip())
                    current = ''
                else:
                    current += ch
            if current.strip():
                parts.append(current.strip())

            fixed_parts = []
            changed = False
            for part in parts:
                # Match: expression as alias (case insensitive, respecting parens)
                as_match = re.match(r'^(.+?)\s+[Aa][Ss]\s+"?(\w+)"?$', part.strip())
                if as_match:
                    expr = as_match.group(1).strip()
                    alias = as_match.group(2).strip()
                    fixed_parts.append(f'{alias}={expr}')
                    changed = True
                else:
                    fixed_parts.append(part)

            if changed:
                self.fixes.append("Converted 'expr as alias' to 'alias=expr' in by: clause")
                return prefix + ', '.join(fixed_parts) + suffix

            return match.group(0)

        dql = re.sub(by_pattern, fix_by_aliases, dql, flags=re.DOTALL)
        return dql

    def _fix_bare_field_in_summarize(self, dql: str) -> str:
        """
        Fix bare fields in summarize/makeTimeseries that aren't aggregations.

        BAD:  summarize duration
        GOOD: summarize avg(duration)

        BAD:  makeTimeseries duration
        GOOD: makeTimeseries avg(duration)

        Also handles: summarize takeLast(field) -> summarize avg(field)
        (takeLast is not a valid DQL aggregation for summarize/makeTimeseries)
        """
        # Known DQL aggregation functions
        valid_aggs = {
            'count', 'sum', 'avg', 'min', 'max', 'percentile', 'median',
            'countif', 'sumif', 'avgif', 'countdistinct', 'collectarray',
            'collectdistinct', 'takefirst', 'takelast', 'takeany', 'stdev',
            'variance', 'delta', 'rate',
        }
        # These are NOT valid in makeTimeseries
        invalid_ts_aggs = {'takelast', 'takefirst', 'takeany', 'collectarray', 'collectdistinct'}

        for cmd in ['makeTimeseries', 'summarize']:
            pattern = re.compile(
                rf'(\|\s*{cmd}\s+)(.*?)(\s*(?:,\s*by:|$))',
                re.IGNORECASE | re.DOTALL
            )
            match = pattern.search(dql)
            if not match:
                continue

            prefix = match.group(1)
            agg_section = match.group(2).strip()
            suffix = match.group(3)

            # Parse individual aggregation expressions
            # Split by comma, but respect parentheses
            parts = []
            depth = 0
            current = ''
            for ch in agg_section:
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                elif ch == ',' and depth == 0:
                    parts.append(current.strip())
                    current = ''
                    continue
                current += ch
            if current.strip():
                parts.append(current.strip())

            fixed_parts = []
            changed = False
            for part in parts:
                # Check if this part starts with a known aggregation
                func_match = re.match(r'(\w+)\s*=\s*(\w+)\s*\(', part)
                if not func_match:
                    func_match = re.match(r'(\w+)\s*\(', part)

                if func_match:
                    func_name = func_match.group(func_match.lastindex).lower()
                    # Fix invalid timeseries aggs
                    if cmd.lower() == 'maketimeseries' and func_name in invalid_ts_aggs:
                        part = re.sub(rf'\b{func_name}\s*\(', 'avg(', part, flags=re.IGNORECASE)
                        self.fixes.append(f"{func_name}() -> avg() (not valid in makeTimeseries)")
                        changed = True
                    elif func_name in valid_aggs:
                        pass  # Valid, keep as is
                    else:
                        # Unknown function -- might be OK, leave it
                        pass
                else:
                    # Bare field name with no aggregation -- wrap in avg()
                    alias_match = re.match(r'(\w+)\s*=\s*(.+)', part)
                    if alias_match:
                        alias = alias_match.group(1)
                        field = alias_match.group(2).strip()
                        part = f"{alias}=avg({field})"
                    else:
                        part = f"avg({part})"
                    self.fixes.append(f"Wrapped bare field '{part}' in avg() for {cmd}")
                    changed = True

                fixed_parts.append(part)

            if changed:
                new_agg_section = ', '.join(fixed_parts)
                dql = dql[:match.start()] + prefix + new_agg_section + suffix + dql[match.end():]

        return dql

    def _fix_nrql_subqueries(self, dql: str) -> str:
        """
        Fix NRQL subqueries that were passed through literally.

        BAD:  filter ... and in(trace.id, FROM Span SELECT trace.id and ...)
        GOOD: lookup [fetch spans | filter ...] joined on trace.id
        """
        # Detect NRQL subquery remnants -- by the time DQL reaches the validator,
        # WHERE has been converted to 'and', so we match both forms.
        # The key signature is: FROM <Type> SELECT <field> inside the DQL

        # Check if there's even a subquery remnant
        if 'FROM ' not in dql or 'SELECT ' not in dql:
            # Check non-comment lines only
            code_lines = [l for l in dql.split('\n') if not l.strip().startswith('//')]
            code = '\n'.join(code_lines)
            if 'FROM ' not in code and 'SELECT ' not in code:
                return dql

        # Pattern: in(field, FROM Type SELECT field and/WHERE conditions)
        pattern1 = r'in\s*\(\s*(\w[\w.]*)\s*,\s*FROM\s+(\w+)\s+SELECT\s+(\w[\w.]*)(?:\s+(?:WHERE|and)\s+(.+?))?\s*\)'
        # Pattern: field in (FROM Type SELECT field and/WHERE conditions)
        pattern2 = r'(\w[\w.]*)\s+in\s*\(\s*FROM\s+(\w+)\s+SELECT\s+(\w[\w.]*)(?:\s+(?:WHERE|and)\s+(.+?))?\s*\)'

        def convert_subquery(match, is_in_func=False):
            if is_in_func:
                field = match.group(1).strip()
                source_type = match.group(2).strip()
                select_field = match.group(3).strip()
                conditions = (match.group(4) or '').strip()
            else:
                field = match.group(1).strip()
                source_type = match.group(2).strip()
                select_field = match.group(3).strip()
                conditions = (match.group(4) or '').strip()

            # Map NR source to DQL
            source_map = {
                'Span': 'spans', 'Transaction': 'spans',
                'Log': 'logs', 'SystemSample': 'dt.entity.host',
            }
            dt_source = source_map.get(source_type, 'spans')

            # Clean conditions
            if conditions:
                w = conditions
                w = re.sub(r"(\w)\s*=\s*(?!=)", r'\1 == ', w)
                w = re.sub(r'\bAND\b', 'and', w, flags=re.IGNORECASE)
                w = re.sub(r'\bappName\b', 'service.name', w)
                sub_filter = f' | filter {w}'
            else:
                sub_filter = ''

            lookup_dql = (f'lookup [fetch {dt_source}{sub_filter} '
                         f'| fields {select_field}], '
                         f'sourceField:{field}, lookupField:{select_field}, prefix:"sub."')

            self.fixes.append(f"Converted NRQL subquery to DQL lookup on {field}")
            return lookup_dql

        new_dql = dql
        new_dql = re.sub(pattern1, lambda m: convert_subquery(m, True), new_dql, flags=re.IGNORECASE | re.DOTALL)
        new_dql = re.sub(pattern2, lambda m: convert_subquery(m, False), new_dql, flags=re.IGNORECASE | re.DOTALL)

        if new_dql != dql:
            # Restructure: lookup can't be inside a filter -- move to separate pipeline step
            lines = new_dql.split('\n')
            fixed_lines = []
            for line in lines:
                stripped = line.strip()
                if 'lookup [' in stripped and ('| filter' in stripped or stripped.startswith('filter')):
                    lookup_match = re.search(
                        r'(lookup\s+\[fetch\s+.+?\]\s*,\s*sourceField:\s*(\w[\w.]*)\s*,\s*lookupField:\s*\w[\w.]*\s*,\s*prefix:\s*"(\w+)\.?")',
                        stripped
                    )
                    if lookup_match:
                        lookup_stmt = lookup_match.group(1)
                        source_field = lookup_match.group(2)
                        prefix = lookup_match.group(3)

                        # Remove the lookup from the filter
                        filter_clean = stripped[:lookup_match.start()].rstrip()
                        # Clean trailing 'and'
                        filter_clean = re.sub(r'\s+and\s*$', '', filter_clean)

                        if filter_clean.strip():
                            fixed_lines.append(filter_clean)
                        fixed_lines.append(f'| {lookup_stmt}')
                        fixed_lines.append(f'| filter isNotNull({prefix}.{source_field})')
                    else:
                        fixed_lines.append(line)
                else:
                    fixed_lines.append(line)

            new_dql = '\n'.join(fixed_lines)

        return new_dql

    def _fix_metric_names(self, dql: str) -> str:
        """Fix metric names with colons that get misinterpreted as parameters"""
        # Pattern: builtin:something.something - needs to be quoted
        # Match metric names in aggregation functions and quote them

        def quote_metric(match):
            func = match.group(1)
            metric = match.group(2)
            self.fixes.append(f"Quoted metric name: {metric}")
            return f'{func}("{metric}"'

        # Match unquoted metric names with colons in aggregation functions
        # Pattern: max(builtin:... or avg(builtin:...
        dql = re.sub(
            r'\b(max|min|avg|sum|count)\(\s*(builtin:[a-zA-Z0-9_.]+)',
            quote_metric,
            dql
        )

        return dql

    def _fix_broken_by_clause(self, dql: str) -> str:
        """Fix broken by: clauses that have WHERE mixed in"""
        # Pattern: by: {field WHERE ...} - this is invalid
        match = re.search(r'by:\s*\{([^}]*)\s+WHERE\s+[^}]*\}', dql, re.IGNORECASE)
        if match:
            # Extract just the field names before WHERE
            fields_part = match.group(1).strip()
            # Clean up the by clause to just have fields
            old_by = match.group(0)
            new_by = f"by: {{{fields_part}}}"
            dql = dql.replace(old_by, new_by)
            self.fixes.append("Removed invalid WHERE from by: clause")

        return dql

    def _fix_quotes(self, dql: str) -> str:
        """DQL uses double quotes for strings, not single quotes"""
        # Find single-quoted strings (not inside double quotes)
        # Pattern: 'something' but not already "something"

        def replace_single_quotes(match):
            content = match.group(1)
            # Don't replace if it contains double quotes
            if '"' in content:
                return match.group(0)
            self.fixes.append(f"Changed single quotes to double quotes: '{content}'")
            return f'"{content}"'

        # Match single-quoted strings
        result = re.sub(r"'([^']*)'", replace_single_quotes, dql)
        return result

    def _fix_variables(self, dql: str) -> str:
        """Convert NR template variables {{var}} to DT format $var"""
        def replace_var(match):
            var_name = match.group(1)
            self.fixes.append(f"Converted variable {{{{{var_name}}}}} to ${var_name}")
            return f"${var_name}"

        result = re.sub(r'\{\{(\w+)\}\}', replace_var, dql)
        return result

    def _fix_backticks(self, dql: str) -> str:
        """Fix backtick-quoted field names, but preserve backticks where needed.

        Preserves backticks for:
        - DQL reserved/type words (duration, timestamp, string, etc.)
        - Identifiers starting with digits (4XX, 5XX)
        - Identifiers with special characters (/, $, spaces, hyphens)
        - fieldsRename lines (always need backticks for display names)
        """
        DQL_RESERVED = {
            'duration', 'timestamp', 'timeframe', 'string', 'long', 'double',
            'boolean', 'ip', 'record', 'array', 'true', 'false', 'null',
            'fetch', 'filter', 'summarize', 'fields', 'sort', 'limit',
            'lookup', 'join', 'append', 'parse', 'from', 'to', 'by',
            'asc', 'desc', 'not', 'and', 'or', 'in', 'is',
        }

        def needs_backticks(field: str) -> bool:
            """Check if a field name needs backtick escaping in DQL."""
            if not field:
                return False
            # Starts with digit
            if field[0].isdigit():
                return True
            # Is a DQL reserved word
            if field.lower() in DQL_RESERVED:
                return True
            # Contains special characters (not just alphanumeric, dots, underscores)
            if re.search(r'[^a-zA-Z0-9._]', field):
                return True
            return False

        def clean_backtick(match):
            field = match.group(1)
            # Convert NR k8s field names to DT format
            field_map = {
                'k8s.podName': 'k8s.pod.name',
                'k8s.containerName': 'k8s.container.name',
                'k8s.clusterName': 'k8s.cluster.name',
                'k8s.namespaceName': 'k8s.namespace.name',
                'k8s.deploymentName': 'k8s.deployment.name',
                'k8s.nodeName': 'k8s.node.name',
            }
            if field in field_map:
                self.fixes.append(f"Converted `{field}` to {field_map[field]}")
                return field_map[field]
            # Keep backticks if the field needs them
            if needs_backticks(field):
                return f'`{field}`'
            return field

        # Process line by line to skip fieldsRename lines
        lines = dql.split('\n')
        result_lines = []
        for line in lines:
            stripped = line.strip().lstrip('| ')
            if stripped.startswith('fieldsRename'):
                # Preserve backticks in fieldsRename - they're intentional
                result_lines.append(line)
            else:
                result_lines.append(re.sub(r'`([^`]+)`', clean_backtick, line))

        return '\n'.join(result_lines)

    def _fix_comparison_operators(self, dql: str) -> str:
        """Fix comparison operator syntax for DQL"""
        # <> is not valid in DQL, use !=
        if '<>' in dql:
            dql = dql.replace('<>', '!=')
            self.fixes.append("Changed '<>' to '!='")

        # CRITICAL: DQL uses == for equality, not =
        # But we need to be careful not to change:
        # - != (not equal)
        # - >= (greater than or equal)
        # - <= (less than or equal)
        # - == (already correct)
        # - Variable assignments in comments

        # Pattern: single = surrounded by spaces with value on right side
        # Match: field = "value" or field = $var or field = number
        # Don't match: !=, >=, <=, ==
        def fix_single_equals(match):
            before = match.group(1)
            after = match.group(2)
            self.fixes.append(f"Changed '=' to '==' for equality comparison")
            return f"{before}=={after}"

        # Don't convert = to == in fieldsAdd statements (those are assignments)
        # Split DQL by lines and only fix lines that aren't fieldsAdd
        lines = dql.split('\n')
        fixed_lines = []
        for line in lines:
            # Skip fieldsAdd lines - they use = for assignment
            if 'fieldsAdd' in line or 'fieldsRemove' in line or 'fieldsRename' in line:
                fixed_lines.append(line)
                continue

            # Match single = that's not part of !=, >=, <=, ==
            # Look for: word/field = "value" or word/field = $var or word/field = number
            line = re.sub(
                r'(\s)=(\s*")',  # = "string"
                fix_single_equals,
                line
            )
            line = re.sub(
                r'(\s)=(\s*\$)',  # = $variable
                fix_single_equals,
                line
            )
            line = re.sub(
                r'(\s)=(\s*\d)',  # = number
                fix_single_equals,
                line
            )
            # Also handle field=value without spaces
            line = re.sub(
                r'([a-zA-Z_][\w.]*)=(")',  # field="value" without spaces
                lambda m: f'{m.group(1)}=={m.group(2)}',
                line
            )
            fixed_lines.append(line)

        return '\n'.join(fixed_lines)

    def _fix_logical_operators(self, dql: str) -> str:
        """DQL uses lowercase and/or"""
        # AND -> and (case insensitive, word boundary)
        if re.search(r'\bAND\b', dql):
            dql = re.sub(r'\bAND\b', 'and', dql)
            self.fixes.append("Changed 'AND' to 'and'")

        # OR -> or
        if re.search(r'\bOR\b', dql):
            dql = re.sub(r'\bOR\b', 'or', dql)
            self.fixes.append("Changed 'OR' to 'or'")

        # NOT -> not (but be careful with isNotNull)
        if re.search(r'\bNOT\b(?!\s*[Nn]ull)', dql):
            dql = re.sub(r'\bNOT\b(?!\s*[Nn]ull)', 'not', dql)
            self.fixes.append("Changed 'NOT' to 'not'")

        return dql

    def _fix_null_checks(self, dql: str) -> str:
        """Fix NULL check syntax"""
        # IS NOT NULL -> isNotNull(field)
        # Handle regular fields, backtick-quoted fields, and hyphenated fields (like correlation-id)
        # Pattern: field IS NOT NULL or `field` IS NOT NULL or hyphen-field IS NOT NULL
        match = re.search(r'(`[^`]+`|[\w.-]+)\s+IS\s+NOT\s+NULL', dql, re.IGNORECASE)
        if match:
            field = match.group(1).strip('`')  # Remove backticks if present
            dql = re.sub(
                r'(`[^`]+`|[\w.-]+)\s+IS\s+NOT\s+NULL',
                lambda m: f'isNotNull({m.group(1).strip("`")})',
                dql,
                flags=re.IGNORECASE
            )
            self.fixes.append(f"Changed 'IS NOT NULL' to 'isNotNull()'")

        # IS NULL -> isNull(field)
        match = re.search(r'(`[^`]+`|[\w.-]+)\s+IS\s+NULL\b', dql, re.IGNORECASE)
        if match:
            field = match.group(1).strip('`')
            dql = re.sub(
                r'(`[^`]+`|[\w.-]+)\s+IS\s+NULL\b',
                lambda m: f'isNull({m.group(1).strip("`")})',
                dql,
                flags=re.IGNORECASE
            )
            self.fixes.append(f"Changed 'IS NULL' to 'isNull()'")

        return dql

    def _fix_like_patterns(self, dql: str) -> str:
        """Convert LIKE patterns to DQL functions"""
        # LIKE '%value%' -> contains("value")
        def convert_like(match):
            field = match.group(1)
            pattern = match.group(2)

            # Determine pattern type
            starts_with_wildcard = pattern.startswith('%')
            ends_with_wildcard = pattern.endswith('%')

            # Remove wildcards
            value = pattern.strip('%')

            if starts_with_wildcard and ends_with_wildcard:
                self.fixes.append(f"Changed '{field} LIKE' to 'contains()'")
                return f'contains({field}, "{value}")'
            elif starts_with_wildcard:
                self.fixes.append(f"Changed '{field} LIKE' to 'endsWith()'")
                return f'endsWith({field}, "{value}")'
            elif ends_with_wildcard:
                self.fixes.append(f"Changed '{field} LIKE' to 'startsWith()'")
                return f'startsWith({field}, "{value}")'
            else:
                self.fixes.append(f"Changed '{field} LIKE' to '=='")
                return f'{field} == "{value}"'

        # Match LIKE patterns with single or double quotes
        dql = re.sub(
            r"(\w+[\w.]*)\s+LIKE\s+['\"]([^'\"]+)['\"]",
            convert_like,
            dql,
            flags=re.IGNORECASE
        )

        # Also handle NOT LIKE - DQL syntax: not(contains(field, "value"))
        def convert_not_like(match):
            field = match.group(1)
            pattern = match.group(2)
            value = pattern.strip('%')

            self.fixes.append(f"Changed '{field} NOT LIKE' to 'not(contains())'")
            return f'not(contains({field}, "{value}"))'

        dql = re.sub(
            r"(\w+[\w.]*)\s+NOT\s+LIKE\s+['\"]([^'\"]+)['\"]",
            convert_not_like,
            dql,
            flags=re.IGNORECASE
        )

        return dql

    def _fix_timeseries_count(self, dql: str, context: str = "") -> str:
        """
        Fix timeseries count() - this is the most critical fix.
        timeseries requires a metric key, count() alone is invalid.
        NOTE: Don't match makeTimeseries which is valid!
        """
        # Check for standalone timeseries count() (not makeTimeseries)
        # Use negative lookbehind to exclude makeTimeseries
        if re.search(r'(?<!make)timeseries\s+count\(\s*\)', dql, re.IGNORECASE):
            # This is invalid - need to convert to fetch + summarize
            self.fixes.append("Converted invalid 'timeseries count()' to 'fetch + summarize'")
            dql = self._convert_timeseries_count_to_fetch(dql, context)

        return dql

    def _convert_timeseries_count_to_fetch(self, dql: str, context: str = "") -> str:
        """Convert timeseries count() to proper fetch + summarize"""
        # Extract any existing clauses
        by_match = re.search(r',\s*by:\s*\{([^}]*)\}', dql)
        filter_match = re.search(r',\s*filter:\s*(.+?)(?:,\s*by:|$)', dql)

        by_clause = by_match.group(1).strip() if by_match else ""
        filter_clause = filter_match.group(1).strip().rstrip(',') if filter_match else ""

        # Determine data source from context
        context_lower = context.lower()
        if 'log' in context_lower:
            source = 'logs'
        elif 'synthetic' in context_lower or 'monitor' in context_lower:
            source = 'dt.synthetic.http.request'
        elif 'error' in context_lower:
            source = 'spans'
        else:
            source = 'spans'

        # Build new query
        parts = [f"fetch {source}"]

        if filter_clause:
            parts.append(f"filter {filter_clause}")

        if by_clause:
            parts.append(f"summarize count(), by: {{{by_clause}}}")
        else:
            parts.append("summarize count()")

        return '\n| '.join(parts)

    def _fix_invalid_functions(self, dql: str) -> str:
        """Fix invalid or unsupported functions"""
        # uniqueCount -> countDistinct
        if 'uniqueCount(' in dql or 'uniquecount(' in dql:
            dql = re.sub(r'uniqueCount\(', 'countDistinct(', dql, flags=re.IGNORECASE)
            self.fixes.append("Changed 'uniqueCount()' to 'countDistinct()'")

        # average -> avg
        if re.search(r'\baverage\(', dql, re.IGNORECASE):
            dql = re.sub(r'\baverage\(', 'avg(', dql, flags=re.IGNORECASE)
            self.fixes.append("Changed 'average()' to 'avg()'")

        # latest -> takeAny
        if 'latest(' in dql:
            dql = re.sub(r'latest\(', 'takeAny(', dql, flags=re.IGNORECASE)
            self.fixes.append("Changed 'latest()' to 'takeAny()'")

        # Handle NR-specific SLI metrics - add warning comment
        # Check in both the original NRQL comment and the DQL itself
        # Skip if already has the new format comment
        if 'newrelic.sli.' in dql.lower() or 'sli.good' in dql.lower() or 'sli.valid' in dql.lower():
            if '// NOTE: NR SLI metrics' not in dql and 'fetch slo' not in dql.lower():
                pass  # Let the converter handle this with the better message

        # Handle clamp_max/clamp_min - these are now preprocessed to if()
        # Only add note if unconverted ones remain
        if 'clamp_max(' in dql.lower() or 'clamp_min(' in dql.lower():
            if '// NOTE: clamp' not in dql.lower():
                dql = "// NOTE: clamp_max/clamp_min converted to if() - verify logic\n" + dql
                self.fixes.append("Added note about clamp function conversion")

        # Handle histogram - convert to count() + bin() for categoricalBarChart visualization
        # NRQL: histogram(field, ceiling, numBars, width)
        # DQL: summarize count(), by:{bin(field, width)}
        histogram_match = re.search(r'\bhistogram\s*\(\s*([^,]+)(?:\s*,\s*(\d+(?:\.\d+)?)(?:\s*,\s*(\d+(?:\.\d+)?)(?:\s*,\s*(\d+(?:\.\d+)?))?)?)?\s*\)', dql, re.IGNORECASE)
        if histogram_match:
            field = histogram_match.group(1).strip()
            if field == 'duration.ms':
                field = 'duration'

            # Calculate bin width
            ceiling = histogram_match.group(2)
            num_bars = histogram_match.group(3)
            explicit_w = histogram_match.group(4)
            if explicit_w:
                bin_w = int(float(explicit_w))
            elif ceiling and num_bars:
                bin_w = int(float(ceiling) / float(num_bars))
            else:
                bin_w = 1000

            # Use DQL duration literal for duration field
            if field == 'duration':
                bin_expr = ms_to_dql_duration(bin_w)
            else:
                bin_expr = str(bin_w)

            # Replace histogram() call with count(), by:{bin(field, width)}
            dql = re.sub(
                r'\bhistogram\s*\(\s*[^)]+\)',
                f'count(), by: {{bin({field}, {bin_expr})}}',
                dql,
                flags=re.IGNORECASE
            )

            # Fix "| summarize count(), by:..." (correct) or "| makeTimeseries count(), by:..."
            # No further fixup needed since the replacement is valid DQL

            if '// NOTE: histogram' not in dql.lower():
                self.fixes.append("histogram() -> count() + bin() for categoricalBarChart")

        # Handle cdfPercentage - not available
        if 'cdfpercentage(' in dql.lower():
            if '// NOTE: cdfPercentage' not in dql:
                dql = "// NOTE: cdfPercentage() not available in DQL\n" + dql
                self.fixes.append("Added note about cdfPercentage not available")

        # aparse() is now handled by AparseConverter in NRQLtoDQLConverter with real DPL conversion
        # (no longer converting to extract() here)

        # Handle percentage() - NR-specific function
        # percentage(count(field), where condition) -> need to calculate manually
        # This is complex and can't be directly converted
        if 'percentage(' in dql.lower():
            if '// NOTE: percentage()' not in dql:
                dql = "// NOTE: NR percentage() function needs manual conversion in DQL\n// Use: (countIf(condition) / count()) * 100\n" + dql
                self.fixes.append("Added note about percentage() needing manual conversion")

        return dql

    def _fix_field_names(self, dql: str) -> str:
        """Fix common field name issues"""
        # Fields with hyphens need backticks in DQL
        # e.g., some-field -> `some-field`
        # But only if not already backticked

        # This is a complex fix - for now just note if there are potential issues
        if re.search(r'(?<![`])\b\w+-\w+\b(?![`])', dql):
            # Has hyphenated field not in backticks
            # For safety, we'll just note this as a warning
            pass

        return dql

    def _fix_duration_units(self, dql: str) -> str:
        """Fix common duration unit mistakes in DQL.

        DQL durations in Dynatrace are often nanoseconds, not milliseconds.
        resolved_problem_duration is in nanoseconds — dividing by 1000 gives
        microseconds, not seconds. Must divide by 1,000,000,000 for seconds
        or 3,600,000,000,000 for hours.
        """
        # Detect dividing resolved_problem_duration by ms-scale divisors (wrong)
        if 'resolved_problem_duration' in dql:
            # Check for division by 1000 (wrong: gives microseconds not seconds)
            if re.search(r'resolved_problem_duration\s*/\s*1000(?!\d)', dql):
                dql = re.sub(
                    r'(resolved_problem_duration\s*/\s*)1000(?!\d)',
                    r'\g<1>1000000000',
                    dql
                )
                self.fixes.append("Fixed duration divisor: resolved_problem_duration is in nanoseconds, not milliseconds (÷1B for seconds)")

        return dql

    def _fix_negation_to_filterout(self, dql: str) -> str:
        """Suggest filterOut instead of filter not for better performance.

        DQL anti-pattern: `filter not <condition>` is slower than `filterOut <condition>`.
        Only add a comment hint, don't change semantics.
        """
        # Match: | filter not(something) or | filter not something
        if re.search(r'\|\s*filter\s+not\s*[\(]', dql, re.IGNORECASE):
            if '// PERF:' not in dql:
                # Add a performance hint as a comment
                dql = re.sub(
                    r'(\|\s*filter\s+not\s*\()',
                    r'// PERF: Consider using filterOut instead of filter not() for better performance\n\1',
                    dql,
                    count=1,
                    flags=re.IGNORECASE
                )
                self.fixes.append("Added performance hint: filterOut is faster than filter not()")
        return dql

    def _fix_array_count_without_expand(self, dql: str) -> str:
        """Warn when counting array fields without expanding first.

        Common DQL mistake: summarize by:{array_field}, count = count()
        without expanding the array first gives wrong results.
        """
        # Known array fields in Dynatrace
        array_fields = [
            'affected_entity_ids', 'affected_entities', 'tags',
            'management_zones', 'entity.detected_name',
        ]
        for field in array_fields:
            if field in dql:
                # Check if it's used in summarize/by without a prior expand
                if re.search(rf'summarize\b.*\bby:\s*\{{[^}}]*{re.escape(field)}', dql):
                    # Check if expand exists before this summarize
                    if f'expand {field}' not in dql:
                        if f'// NOTE: expand {field}' not in dql:
                            dql = re.sub(
                                rf'(\|\s*summarize\b.*\bby:\s*\{{[^}}]*{re.escape(field)})',
                                rf'// NOTE: expand {field} before summarize for correct counts\n\1',
                                dql,
                                count=1
                            )
                            self.fixes.append(f"Added note: '{field}' should be expanded before summarize")
        return dql

    def _fix_whitespace(self, dql: str) -> str:
        """Clean up whitespace issues"""
        # Remove trailing whitespace from lines
        lines = [line.rstrip() for line in dql.split('\n')]

        # Remove empty lines at start/end
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()

        result = '\n'.join(lines)

        # Fix double pipes (| |) - often caused by joining issues
        result = re.sub(r'\|\s*\|', '|', result)

        # Fix pipe at start of line following another pipe
        result = re.sub(r'\|\s*\n\s*\|', '\n|', result)

        return result
