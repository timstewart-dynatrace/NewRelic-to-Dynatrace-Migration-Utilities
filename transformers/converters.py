"""Specialized NRQL-to-DQL converters for complex patterns."""
import re
from typing import Any, Dict, List, Optional, Tuple


class RegexToDPLConverter:
    """
    Converts RE2 regex patterns to Dynatrace Pattern Language (DPL).

    Strategy:
    1. Extract named capture groups first, converting inner patterns
    2. Convert remaining regex to DPL matchers
    3. Wrap literal text in quotes
    4. Output format: MATCHER:export_name (no spaces around colon)
    """

    DPL_KEYWORDS = {'INT', 'LONG', 'WORD', 'ALPHA', 'ALNUM', 'DIGIT', 'SPACE', 'NSPACE',
                    'IPV4', 'IPV6', 'IPADDR', 'TIMESTAMP', 'ISO8601', 'LD', 'DATA',
                    'UPPER', 'LOWER', 'EOL', 'DQS', 'SQS', 'JSON', 'BOOLEAN',
                    'DOUBLE', 'FLOAT', 'HEXINT'}

    def convert(self, regex_pattern: str) -> Tuple[str, List[str]]:
        """Convert RE2 regex to DPL pattern. Returns (dpl_pattern, capture_names)."""
        capture_names = []
        segments = []  # list of (type, content) tuples: ('matcher', 'INT:name') or ('literal', 'text')

        pos = 0
        pattern = regex_pattern

        # Strip anchors
        if pattern.startswith('^'):
            pattern = pattern[1:]
        if pattern.endswith('$'):
            pattern = pattern[:-1]

        while pos < len(pattern):
            # Named capture group: (?P<name>inner)
            named_match = re.match(r'\(\?P<(\w+)>([^)]*)\)', pattern[pos:])
            if named_match:
                name = named_match.group(1)
                inner = named_match.group(2)
                capture_names.append(name)
                dpl_type = self._inner_to_dpl_type(inner)
                segments.append(('matcher', f'{dpl_type}:{name}'))
                pos += named_match.end()
                continue

            # Unnamed capture group: (inner)
            unnamed_match = re.match(r'\(([^?][^)]*)\)', pattern[pos:])
            if unnamed_match:
                inner = unnamed_match.group(1)
                group_name = f'group{len(capture_names) + 1}'
                capture_names.append(group_name)
                dpl_type = self._inner_to_dpl_type(inner)
                segments.append(('matcher', f'{dpl_type}:{group_name}'))
                pos += unnamed_match.end()
                continue

            # Whitespace shorthand with quantifier: \s+, \s*, \s
            ws_match = re.match(r'\\s([+*?]?)', pattern[pos:])
            if ws_match:
                q = ws_match.group(1) or ''
                segments.append(('matcher', f'SPACE{q}'))
                pos += ws_match.end()
                continue

            # Non-whitespace shorthand: \S+, \S*, \S
            nws_match = re.match(r'\\S([+*?]?)', pattern[pos:])
            if nws_match:
                q = nws_match.group(1) or ''
                segments.append(('matcher', f'NSPACE{q}'))
                pos += nws_match.end()
                continue

            # Word shorthand with quantifier: \w+, \w*
            word_match = re.match(r'\\w([+*?]?)', pattern[pos:])
            if word_match:
                q = word_match.group(1)
                if q == '+':
                    segments.append(('matcher', 'WORD'))
                elif q == '*':
                    segments.append(('matcher', 'WORD?'))
                else:
                    segments.append(('matcher', 'ALNUM'))
                pos += word_match.end()
                continue

            # Digit with quantifier: \d+, \d*, \d{n}, \d{n,m}
            digit_match = re.match(r'\\d(\{[^}]+\}|[+*?]?)', pattern[pos:])
            if digit_match:
                q = digit_match.group(1)
                if q in ('+', '{1,}', ''):
                    # \d+ or \d -> use INT for sequences
                    segments.append(('matcher', 'INT' if q == '+' else 'DIGIT'))
                elif q == '*':
                    segments.append(('matcher', 'INT?'))
                elif q.startswith('{'):
                    # \d{3} -> INT for fixed-width numeric
                    segments.append(('matcher', 'INT'))
                else:
                    segments.append(('matcher', 'DIGIT'))
                pos += digit_match.end()
                continue

            # Character class: [...]
            cc_match = re.match(r'\[([^\]]+)\]([+*?]?)', pattern[pos:])
            if cc_match:
                cc_inner = cc_match.group(1)
                q = cc_match.group(2) or ''
                dpl_cc = self._char_class_to_dpl(cc_inner, q)
                segments.append(('matcher', dpl_cc))
                pos += cc_match.end()
                continue

            # Dot with quantifier: .+, .*, .
            dot_match = re.match(r'\.([+*?])', pattern[pos:])
            if dot_match and pos > 0 and pattern[pos-1] != '\\':
                q = dot_match.group(1)
                if q == '+':
                    segments.append(('matcher', 'LD'))
                elif q == '*':
                    segments.append(('matcher', 'LD?'))
                else:
                    segments.append(('matcher', 'LD'))
                pos += dot_match.end()
                continue

            # Escaped characters
            if pattern[pos] == '\\' and pos + 1 < len(pattern):
                next_ch = pattern[pos + 1]
                if next_ch == 'b':
                    # Word boundary - skip in DPL
                    pos += 2
                    continue
                elif next_ch == 'W':
                    segments.append(('matcher', 'SPACE'))
                    pos += 2
                    continue
                elif next_ch == 'D':
                    segments.append(('matcher', 'ALPHA'))
                    pos += 2
                    continue
                else:
                    # Escaped literal: \. \/ \- \[ etc.
                    segments.append(('literal', next_ch))
                    pos += 2
                    continue

            # Alternation group: (A|B|C) -- not a capture
            alt_match = re.match(r'\((\?:)?([^)]+)\)', pattern[pos:])
            if alt_match and '|' in alt_match.group(2):
                alts = alt_match.group(2).split('|')
                # In DPL: ('A' | 'B' | 'C')
                alt_strs = [f"'{a}'" for a in alts]
                segments.append(('matcher', f"({' | '.join(alt_strs)})"))
                pos += alt_match.end()
                continue

            # Regular literal character
            if pattern[pos] not in '()[]\\^$.*+?{}|':
                # Accumulate literal text
                lit_end = pos
                while lit_end < len(pattern) and pattern[lit_end] not in '()[]\\^$.*+?{}|':
                    lit_end += 1
                segments.append(('literal', pattern[pos:lit_end]))
                pos = lit_end
            else:
                # Skip unhandled metacharacter
                pos += 1

        # Build DPL string
        dpl_parts = []
        for stype, content in segments:
            if stype == 'literal':
                dpl_parts.append(f"'{content}'")
            else:
                dpl_parts.append(content)

        return ' '.join(dpl_parts), capture_names

    def _inner_to_dpl_type(self, inner: str) -> str:
        """Convert the inner pattern of a capture group to a DPL matcher type."""
        inner = inner.strip()

        # IP address patterns
        if re.match(r'\\d\{1,3\}.*\\d\{1,3\}.*\\d\{1,3\}.*\\d\{1,3\}', inner):
            return 'IPV4'

        # ISO timestamp
        if r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}' in inner:
            return 'ISO8601'
        if r'\d{4}-\d{2}-\d{2}' in inner and 'T' in inner:
            return 'ISO8601'
        if re.match(r'\\d\{4\}[-./]\\d\{2\}[-./]\\d\{2\}', inner):
            return 'TIMESTAMP'

        # Pure digit patterns
        if inner in (r'\d+', r'[0-9]+', r'\d{1,}'):
            return 'INT'
        if re.match(r'^\\d\{\d+(,\d+)?\}$', inner):
            return 'INT'
        if inner == r'\d':
            return 'DIGIT'

        # Word patterns
        if inner in (r'\w+', r'[a-zA-Z0-9_]+'):
            return 'WORD'
        if inner == r'\w':
            return 'ALNUM'

        # Alpha patterns
        if inner in (r'[a-zA-Z]+', r'[A-Za-z]+'):
            return 'ALPHA+'
        if inner in (r'[A-Z]+',):
            return 'UPPER+'
        if inner in (r'[a-z]+',):
            return 'LOWER+'

        # Non-whitespace (common for URLs, tokens)
        if inner in (r'\S+', r'[^ ]+', r'[^\s]+'):
            return 'NSPACE+'

        # Character classes with negation
        neg_match = re.match(r'^\[\^([^\]]+)\]\+?$', inner)
        if neg_match:
            excluded = neg_match.group(1)
            if excluded == '"':
                return 'DQS'  # Everything except double quote
            elif excluded == "'":
                return 'SQS'  # Everything except single quote
            elif '/' in excluded or ' ' in excluded:
                return 'NSPACE+'  # Non-space, non-slash
            else:
                return 'LD'

        # Character classes with specific chars
        cc_match = re.match(r'^\[([^\]]+)\]([+*?]?)$', inner)
        if cc_match:
            chars = cc_match.group(1)
            q = cc_match.group(2) or '+'
            return self._char_class_to_dpl(chars, q)

        # Alternation: INFO|WARN|ERROR|DEBUG
        if '|' in inner and not inner.startswith('('):
            alts = inner.split('|')
            return f"({' | '.join(repr(a) for a in alts)})"

        # Wildcard .+ or .*
        if inner in ('.+', '.*'):
            return 'LD'

        # Default: line data
        return 'LD'

    def _char_class_to_dpl(self, cc_inner: str, quantifier: str) -> str:
        """Convert a character class like [a-zA-Z0-9.-] to DPL matcher."""
        q = quantifier

        if cc_inner in ('a-zA-Z', 'A-Za-z'):
            return f'ALPHA{q}'
        if cc_inner in ('a-zA-Z0-9', 'A-Za-z0-9', '0-9a-zA-Z'):
            return f'ALNUM{q}'
        if cc_inner == '0-9':
            return 'INT' if q in ('+', '') else f'DIGIT{q}'
        if cc_inner == 'A-Z':
            return f'UPPER{q}'
        if cc_inner == 'a-z':
            return f'LOWER{q}'
        if cc_inner.startswith('^'):
            # Negated class
            excluded = cc_inner[1:]
            if ' ' in excluded or '\\s' in excluded:
                return f'NSPACE{q}'
            if '"' in excluded:
                return f'DQS'
            return f'LD{q}'

        # Complex character class with dots, dashes etc: keep as LD
        if '\\w' in cc_inner or 'a-z' in cc_inner:
            return f'WORD{q}' if q else 'WORD'

        return f'LD{q}'


class AparseConverter:
    """Converts NRQL aparse() anchor patterns (% delimiters) to DPL."""

    def convert(self, pattern: str) -> Tuple[str, List[str]]:
        """Convert aparse pattern to DPL. Returns (dpl_pattern, capture_names)."""
        capture_names = []
        dpl_parts = []
        parts = pattern.split('%')

        for i, part in enumerate(parts):
            if i % 2 == 0:
                if part: dpl_parts.append(f"'{part}'")
            else:
                capture_names.append(part)
                dpl_type = self._infer_type(part)
                dpl_parts.append(f'{dpl_type}:{part}')

        return ' '.join(dpl_parts), capture_names

    def _infer_type(self, name: str) -> str:
        name_lower = name.lower()
        if 'ip' in name_lower or 'addr' in name_lower: return 'IPADDR'
        elif 'port' in name_lower or 'code' in name_lower or 'num' in name_lower or 'count' in name_lower: return 'INT'
        elif 'time' in name_lower or 'date' in name_lower: return 'TIMESTAMP'
        elif 'user' in name_lower or 'name' in name_lower: return 'WORD'
        elif 'email' in name_lower: return 'NSPACE'
        elif 'url' in name_lower or 'path' in name_lower: return 'NSPACE'
        elif 'msg' in name_lower or 'message' in name_lower: return 'LD'
        else: return 'LD'


class RateDerivativeConverter:
    """Converts NRQL rate() and derivative() to DQL timeseries with rate: param."""

    UNIT_MAP = {
        'second': 's', 'seconds': 's', 'sec': 's',
        'minute': 'm', 'minutes': 'm', 'min': 'm',
        'hour': 'h', 'hours': 'h', 'hr': 'h',
        'day': 'd', 'days': 'd',
    }

    def convert_rate(self, rate_expr: str) -> Optional[Tuple[str, str]]:
        """
        Convert rate(agg(field), N unit) to DQL.
        Returns (dql_agg_expr, rate_param) or None.

        NRQL: rate(count(*), 1 minute) -> DQL: count(), rate:1m
        """
        match = re.match(
            r'rate\s*\(\s*(\w+)\s*\(\s*([^)]*)\s*\)\s*,\s*(\d+)\s*(\w+)\s*\)',
            rate_expr, re.IGNORECASE
        )
        if not match: return None

        agg, field, amount, unit = match.groups()
        agg_map = {'count': 'count', 'sum': 'sum', 'avg': 'avg',
                    'average': 'avg', 'min': 'min', 'max': 'max'}
        dql_agg = agg_map.get(agg.lower(), agg.lower())
        dql_unit = self.UNIT_MAP.get(unit.lower(), unit[0].lower())

        if field == '*' or not field:
            return f'{dql_agg}()', f'rate:{amount}{dql_unit}'
        else:
            return f'{dql_agg}({field})', f'rate:{amount}{dql_unit}'

    def convert_derivative(self, deriv_expr: str) -> Optional[Tuple[str, str]]:
        """Convert derivative(agg(field), N unit) -> DQL rate: param."""
        match = re.match(
            r'derivative\s*\(\s*(\w+)\s*\(\s*([^)]*)\s*\)\s*,\s*(\d+)\s*(\w+)\s*\)',
            deriv_expr, re.IGNORECASE
        )
        if not match: return None

        agg, field, amount, unit = match.groups()
        agg_map = {'count': 'count', 'sum': 'sum', 'avg': 'avg',
                    'average': 'avg', 'min': 'min', 'max': 'max'}
        dql_agg = agg_map.get(agg.lower(), agg.lower())
        dql_unit = self.UNIT_MAP.get(unit.lower(), unit[0].lower())

        if field == '*' or not field:
            return f'{dql_agg}()', f'rate:{amount}{dql_unit}'
        else:
            return f'{dql_agg}({field})', f'rate:{amount}{dql_unit}'


class CompareWithConverter:
    """Converts NRQL COMPARE WITH -> DQL timeseries shift: parameter."""

    def convert(self, nrql: str) -> Optional[Tuple[str, str]]:
        """
        Extract COMPARE WITH and return (cleaned_nrql, shift_param).
        NRQL: SELECT ... COMPARE WITH 1 day ago -> shift:-1d
        """
        match = re.search(
            r'\s*COMPARE\s+WITH\s+(\d+)\s+(second|minute|hour|day|week|month)s?\s+ago\s*',
            nrql, re.IGNORECASE
        )
        if not match: return None

        amount = int(match.group(1))
        unit = match.group(2).lower()

        unit_map = {'second': 's', 'minute': 'm', 'hour': 'h', 'day': 'd', 'week': 'd', 'month': 'd'}
        if unit == 'week': shift_amount, shift_unit = amount * 7, 'd'
        elif unit == 'month': shift_amount, shift_unit = amount * 30, 'd'
        else: shift_amount, shift_unit = amount, unit_map[unit]

        shift_param = f'shift:-{shift_amount}{shift_unit}'
        cleaned = re.sub(r'\s*COMPARE\s+WITH\s+\d+\s+\w+\s+ago\s*', '', nrql, flags=re.IGNORECASE)
        return cleaned.strip(), shift_param


class FunnelConverter:
    """Converts NRQL funnel() to Dynatrace USQL FUNNEL."""

    def convert(self, nrql: str) -> Optional[Dict[str, Any]]:
        """Returns dict with usql, steps, type='usql', note."""
        match = re.search(
            r'funnel\s*\(\s*(\w+)\s*,\s*(.+?)\s*\)\s*', nrql, re.IGNORECASE
        )
        if not match: return None

        conditions = re.findall(
            r"WHERE\s+(\w+)\s*(=|!=|LIKE)\s*['\"]([^'\"]+)['\"]",
            match.group(2), re.IGNORECASE
        )
        if not conditions: return None

        field_map = {'action': 'useraction.name', 'name': 'useraction.name',
                     'page': 'useraction.name', 'type': 'useraction.type',
                     'application': 'useraction.application', 'app': 'useraction.application'}

        usql_parts = []
        steps = []
        for field, op, value in conditions:
            usql_field = field_map.get(field.lower(), f'useraction.{field}')
            usql_op = '=' if op.upper() in ('=', 'LIKE') else '!='
            usql_parts.append(f'{usql_field}{usql_op}"{value}"')
            steps.append({'field': field, 'op': op, 'value': value})

        return {
            'usql': f"SELECT FUNNEL({', '.join(usql_parts)}) FROM usersession",
            'steps': steps, 'type': 'usql',
            'note': 'Requires User Sessions API, not DQL'
        }


class ExtrapolateHandler:
    """Handles NRQL EXTRAPOLATE keyword -> DT auto-sampling or extrapolate:true."""

    def handle(self, nrql: str, dql: str) -> Tuple[str, str, Optional[str]]:
        """Returns (cleaned_nrql, updated_dql, note)."""
        if 'EXTRAPOLATE' not in nrql.upper():
            return nrql, dql, None

        cleaned_nrql = re.sub(r'\s+EXTRAPOLATE\s*', ' ', nrql, flags=re.IGNORECASE).strip()

        if 'countDistinct' in dql:
            updated_dql = re.sub(
                r'countDistinct\(([^)]+)\)',
                r'countDistinct(\1, extrapolate:true)', dql
            )
            return cleaned_nrql, updated_dql, 'Added extrapolate:true to countDistinct'
        else:
            return cleaned_nrql, dql, 'EXTRAPOLATE removed - Dynatrace handles sampling automatically'


class BucketPercentileConverter:
    """Converts NRQL bucketPercentile() -> DQL multiple percentile() calls."""

    def convert(self, expr: str) -> Optional[str]:
        """
        NRQL: bucketPercentile(http_req_duration_bucket, 50, 95, 99)
        DQL:  percentile(http_req_duration, 50), percentile(..., 95), ...
        """
        match = re.match(
            r'bucketPercentile\s*\(\s*([^,]+)\s*,\s*(.+)\s*\)',
            expr, re.IGNORECASE
        )
        if not match: return None

        metric = re.sub(r'_bucket$', '', match.group(1).strip())
        percentiles = [p.strip() for p in match.group(2).split(',')]
        return ', '.join(f'percentile({metric}, {p})' for p in percentiles)


class WithAsConverter:
    """Handles NRQL WITH...AS (CTE) patterns -> DQL inline or append strategy."""

    def convert(self, nrql: str) -> Optional[Dict[str, Any]]:
        cte_match = re.match(
            r'WITH\s+((?:\w+\s+AS\s*\([^)]+\)\s*,?\s*)+)',
            nrql, re.IGNORECASE
        )
        if not cte_match: return None

        cte_defs = re.findall(r'(\w+)\s+AS\s*\(([^)]+)\)', cte_match.group(1), re.IGNORECASE)
        if not cte_defs: return None

        main_query = nrql[cte_match.end():]
        main_match = re.match(r'\s*SELECT\s+(.+)', main_query, re.IGNORECASE)
        if not main_match: return None

        ctes = []
        all_simple = True
        for name, query in cte_defs:
            agg_match = re.search(r'SELECT\s+(\w+)\s*\(\s*([^)]*)\s*\)', query, re.IGNORECASE)
            if agg_match:
                ctes.append({'name': name, 'query': query, 'agg': agg_match.group(1),
                             'field': agg_match.group(2) or '*', 'simple': True})
            else:
                ctes.append({'name': name, 'query': query, 'simple': False})
                all_simple = False

        if all_simple and len(ctes) <= 2:
            return self._inline_strategy(ctes, main_match.group(1))
        else:
            return self._append_strategy(ctes, main_match.group(1))

    def _inline_strategy(self, ctes, main_select):
        agg_map = {'count': 'count', 'sum': 'sum', 'avg': 'avg',
                    'average': 'avg', 'min': 'min', 'max': 'max',
                    'uniquecount': 'countDistinct'}
        agg_parts = []
        for cte in ctes:
            dql_agg = agg_map.get(cte['agg'].lower(), cte['agg'].lower())
            f = cte['field']
            agg_parts.append(f"{cte['name']} = {dql_agg}()" if f == '*' or not f
                             else f"{cte['name']} = {dql_agg}({f})")

        result_expr = main_select
        for cte in ctes:
            result_expr = re.sub(rf'{cte["name"]}\.(\w+)', cte['name'], result_expr)

        dql = f"fetch spans\n| summarize {', '.join(agg_parts)}\n| fieldsAdd result = {result_expr}"
        return {'dql': dql, 'strategy': 'inline', 'ctes': ctes}

    def _append_strategy(self, ctes, main_select):
        dql_parts = [f"// CTE: {c['name']}\n// {c['query']}" for c in ctes]
        dql = '\n'.join(dql_parts) + f"\n\n// Main query needs manual review:\n// SELECT {main_select}"
        return {'dql': dql, 'strategy': 'manual_review', 'ctes': ctes,
                'note': 'Complex CTE requires manual review - use append or join'}
