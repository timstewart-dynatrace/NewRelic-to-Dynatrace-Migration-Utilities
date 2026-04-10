"""
NRQL-to-DQL Compiler -- Recursive-descent parser.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .ast_nodes import (
    ASTNode,
    BinaryOp,
    ComparisonCond,
    Condition,
    FacetItem,
    FieldRef,
    FunctionCall,
    InListCond,
    InSubqueryCond,
    IsNullCond,
    JoinClause,
    LikeCond,
    LimitClause,
    LiteralExpr,
    LogicalCond,
    NotCond,
    OrderByClause,
    Query,
    RLikeCond,
    SelectItem,
    StarExpr,
    TimeInterval,
    TimeseriesClause,
    UnaryMinus,
)
from .tokens import Token, TokenType

TIME_UNITS = {'second', 'seconds', 'sec', 's',
              'minute', 'minutes', 'min',
              'hour', 'hours', 'hr', 'h',
              'day', 'days', 'd',
              'week', 'weeks', 'w',
              'month', 'months'}

# Functions that accept a WHERE clause as their last argument
WHERE_FUNCTIONS = {'percentage', 'filter', 'apdex', 'funnel'}

# Known aggregation functions (used to detect aggregation context)
AGG_FUNCTIONS = {'count', 'sum', 'average', 'avg', 'max', 'min', 'percentile',
                 'uniquecount', 'uniques', 'latest', 'earliest', 'last', 'first',
                 'median', 'stddev', 'rate', 'filter', 'percentage', 'apdex',
                 'funnel', 'histogram', 'cdfpercentage', 'countdistinct',
                 'bucketpercentile', 'derivative', 'cardinality',
                 'aggregationendtime', 'predictlinear'}


class ParseError(Exception):
    def __init__(self, msg: str, pos: int = -1):
        self.pos = pos
        super().__init__(msg)


class NRQLParser:
    """Recursive-descent parser for NRQL -> AST."""

    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    # -- Helpers --

    def _cur(self) -> Token:
        return self.tokens[min(self.pos, len(self.tokens) - 1)]

    def _peek(self, offset: int = 0) -> Token:
        idx = self.pos + offset
        return self.tokens[min(idx, len(self.tokens) - 1)]

    def _at_end(self) -> bool:
        return self._cur().type == TokenType.EOF

    def _check(self, *types: TokenType) -> bool:
        return self._cur().type in types

    def _match(self, *types: TokenType) -> Optional[Token]:
        if self._cur().type in types:
            t = self._cur()
            self.pos += 1
            return t
        return None

    def _expect(self, tt: TokenType) -> Token:
        t = self._cur()
        if t.type != tt:
            raise ParseError(
                f"Expected {tt.name}, got {t.type.name} ('{t.value}') at pos {t.pos}",
                t.pos
            )
        self.pos += 1
        return t

    def _check_ident(self, *names: str) -> bool:
        """Check if current token is an identifier with one of the given names (case-insensitive)."""
        t = self._cur()
        if t.type == TokenType.IDENTIFIER:
            return t.value.lower() in {n.lower() for n in names}
        if t.type == TokenType.MAX_KW:
            return 'max' in {n.lower() for n in names}
        return False

    # -- Top-level query --

    def parse(self) -> Query:
        # Handle SHOW EVENT TYPES
        if self._check_ident('show'):
            return self._parse_show_event_types()
        # Handle WITH...AS CTEs by inlining
        if self._check(TokenType.WITH):
            return self._parse_with_cte()
        # Handle FROM-first syntax: FROM EventType SELECT ...
        if self._check(TokenType.FROM):
            return self._parse_from_first()
        q = self._parse_query()
        if not self._at_end():
            raise ParseError(f"Unexpected token: {self._cur()}", self._cur().pos)
        return q

    def _parse_show_event_types(self) -> Query:
        """Parse SHOW EVENT TYPES [SINCE ...] -- metadata query."""
        self.pos += 1  # skip 'show'
        # Consume 'event' and 'types' identifiers
        if self._check_ident('event'):
            self.pos += 1
        if self._check_ident('types'):
            self.pos += 1
        since = None
        if self._check(TokenType.SINCE):
            self.pos += 1
            since = self._consume_time_expr()
        # Return a synthetic query that the emitter can recognize
        return Query(
            select_items=[SelectItem(expression=FunctionCall('SHOW_EVENT_TYPES', []))],
            from_clause='__SHOW_EVENT_TYPES__',
            since_raw=since,
        )

    def _peek_with_timezone(self) -> bool:
        """Check if current WITH is followed by TIMEZONE (to distinguish from WITH...AS)."""
        if not self._check(TokenType.WITH):
            return False
        nxt = self._peek(1)
        return nxt.type == TokenType.IDENTIFIER and nxt.value.lower() == 'timezone'

    def _try_parse_join(self) -> Optional[JoinClause]:
        """Try to parse [INNER|LEFT] JOIN (subquery) ON [leftKey =] rightKey after FROM clause."""
        join_type = 'INNER'
        if self._check_ident('inner'):
            join_type = 'INNER'
            self.pos += 1
        elif self._check_ident('left'):
            join_type = 'LEFT'
            self.pos += 1

        if not self._check_ident('join'):
            # If we consumed inner/left but no join follows, back up
            if join_type != 'INNER' or (join_type == 'INNER' and self.pos > 0):
                # Only back up if we actually consumed a token
                pass
            return None

        self.pos += 1  # consume 'join'
        self._expect(TokenType.LPAREN)
        # Parse the subquery (can be FROM-first or SELECT-first)
        if self._check(TokenType.FROM):
            sub = self._parse_from_first()
        else:
            sub = self._parse_query()
        self._expect(TokenType.RPAREN)

        # Parse ON clause
        on_left = None
        on_right = None
        if self._check_ident('on'):
            self.pos += 1
            # Could be: ON key  or  ON leftKey = rightKey
            key1_tok = self._cur()
            if key1_tok.type in (TokenType.IDENTIFIER, TokenType.MAX_KW):
                key1 = key1_tok.value
                self.pos += 1
                if self._match(TokenType.EQ):
                    # ON leftKey = rightKey
                    key2_tok = self._cur()
                    if key2_tok.type in (TokenType.IDENTIFIER, TokenType.MAX_KW):
                        key2 = key2_tok.value
                        self.pos += 1
                        on_left = key1
                        on_right = key2
                    else:
                        on_left = key1
                        on_right = key1
                else:
                    # ON key (same on both sides)
                    on_left = key1
                    on_right = key1

        return JoinClause(join_type=join_type, subquery=sub,
                          on_left=on_left, on_right=on_right)

    def _parse_from_first(self) -> Query:
        """Parse NR FROM-first syntax: FROM EventType [JOIN ...] [WITH ...] SELECT ... WHERE ... etc.
        Rewrites to standard SELECT...FROM internally.
        Also handles: FROM EventType WITH aparse(field, 'pat') AS (alias) SELECT ..."""
        self._expect(TokenType.FROM)
        from_tok = self._cur()
        if from_tok.type in (TokenType.IDENTIFIER, TokenType.MAX_KW):
            from_type = from_tok.value
            self.pos += 1
        else:
            raise ParseError(f"Expected event type after FROM, got {from_tok}", from_tok.pos)

        # Handle JOIN: FROM Event [INNER|LEFT] JOIN (subquery) ON key
        join_clause = self._try_parse_join()

        # Handle inline WITH (computed columns): FROM Span WITH aparse(...) AS (alias) SELECT ...
        # But NOT WITH TIMEZONE -- that's a separate clause at end
        if self._check(TokenType.WITH) and not self._peek_with_timezone():
            self.pos += 1  # skip WITH
            # Consume everything until we hit SELECT
            depth = 0
            while not self._at_end():
                if self._check(TokenType.LPAREN):
                    depth += 1
                elif self._check(TokenType.RPAREN):
                    depth -= 1
                elif self._check(TokenType.SELECT) and depth == 0:
                    break
                self.pos += 1

        self._expect(TokenType.SELECT)
        select_items = self._parse_select_list()

        where = None; facet = None; timeseries = None
        since = None; until = None; limit = None
        order_by = None; compare_with = None; extrapolate = False
        facet_order_by = None; with_timezone = None; predict = False

        while not self._at_end():
            if self._check(TokenType.WHERE):
                self.pos += 1
                where = self._parse_condition()
            elif self._check(TokenType.FACET):
                self.pos += 1
                facet = self._parse_facet_list()
                fob, fob_order = self._try_parse_facet_order_by()
                if fob:
                    facet_order_by = fob
                    order_by = fob_order
            elif self._check(TokenType.TIMESERIES):
                self.pos += 1
                timeseries = self._parse_timeseries_clause()
            elif self._check_ident('predict'):
                self.pos += 1
                predict = True
            elif self._check(TokenType.SINCE):
                self.pos += 1
                since = self._consume_time_expr()
            elif self._check(TokenType.UNTIL):
                self.pos += 1
                until = self._consume_time_expr()
            elif self._check(TokenType.LIMIT):
                self.pos += 1
                if self._check(TokenType.MAX_KW):
                    self.pos += 1
                    limit = LimitClause(value='MAX')
                else:
                    limit = LimitClause(value=int(self._expect(TokenType.NUMBER).value))
            elif self._check(TokenType.ORDER):
                self.pos += 1
                self._expect(TokenType.BY)
                expr = self._parse_expression()
                direction = 'ASC'
                if self._match(TokenType.ASC): direction = 'ASC'
                elif self._match(TokenType.DESC): direction = 'DESC'
                order_by = OrderByClause(expression=expr, direction=direction)
            elif self._check(TokenType.COMPARE):
                self.pos += 1
                self._expect(TokenType.WITH)
                compare_with = self._consume_time_expr()
            elif self._check(TokenType.EXTRAPOLATE):
                self.pos += 1
                extrapolate = True
            elif self._check(TokenType.WITH) and self._peek_with_timezone():
                self.pos += 1  # skip WITH
                self.pos += 1  # skip 'timezone' identifier
                with_timezone = self._expect(TokenType.STRING).value
            else:
                break

        return Query(
            select_items=select_items, from_clause=from_type,
            where_clause=where, facet_items=facet, timeseries=timeseries,
            since_raw=since, until_raw=until, limit=limit,
            order_by=order_by, compare_with_raw=compare_with,
            extrapolate=extrapolate, join_clause=join_clause,
            facet_order_by=facet_order_by, with_timezone=with_timezone,
            predict=predict,
        )

    def _parse_with_cte(self) -> Query:
        """Parse: WITH name AS (subquery) SELECT ... FROM name ...
        Strategy: inline the CTE -- replace name references in FROM with the subquery's FROM."""
        self._expect(TokenType.WITH)
        cte_name_tok = self._cur()
        if cte_name_tok.type not in (TokenType.IDENTIFIER, TokenType.MAX_KW):
            raise ParseError(f"Expected CTE name, got {cte_name_tok}", cte_name_tok.pos)
        cte_name = cte_name_tok.value
        self.pos += 1
        self._expect(TokenType.AS)
        self._expect(TokenType.LPAREN)
        # Parse inner query
        inner = self._parse_query()
        self._expect(TokenType.RPAREN)
        # Parse outer query
        outer = self._parse_query()
        # If outer's FROM matches CTE name, replace with inner's FROM and merge WHERE
        if outer.from_clause.lower() == cte_name.lower():
            outer.from_clause = inner.from_clause
            # Merge WHERE clauses (inner AND outer)
            if inner.where_clause and outer.where_clause:
                outer.where_clause = LogicalCond('AND', inner.where_clause, outer.where_clause)
            elif inner.where_clause:
                outer.where_clause = inner.where_clause
        return outer

    def _parse_query(self) -> Query:
        self._expect(TokenType.SELECT)
        select_items = self._parse_select_list()
        self._expect(TokenType.FROM)
        # FROM clause: could be an identifier or a keyword used as event type
        from_tok = self._cur()
        if from_tok.type in (TokenType.IDENTIFIER, TokenType.MAX_KW):
            from_type = from_tok.value
            self.pos += 1
        else:
            raise ParseError(f"Expected event type after FROM, got {from_tok}", from_tok.pos)

        # Handle JOIN: SELECT ... FROM Event [INNER|LEFT] JOIN (subquery) ON key
        join_clause = self._try_parse_join()

        # Handle inline WITH (computed columns): SELECT ... FROM Metric WITH aparse(...) AS (alias) WHERE ...
        # But NOT WITH TIMEZONE -- that's a separate clause at end
        if self._check(TokenType.WITH) and not self._peek_with_timezone():
            self.pos += 1  # skip WITH
            depth = 0
            while not self._at_end():
                if self._check(TokenType.LPAREN):
                    depth += 1
                elif self._check(TokenType.RPAREN):
                    depth -= 1
                    if depth < 0:
                        depth = 0
                # Stop at clause keywords when not inside parens
                elif depth == 0 and self._check(TokenType.WHERE, TokenType.FACET,
                        TokenType.TIMESERIES, TokenType.SINCE, TokenType.UNTIL,
                        TokenType.LIMIT, TokenType.ORDER, TokenType.COMPARE,
                        TokenType.EXTRAPOLATE):
                    break
                self.pos += 1

        where = None; facet = None; timeseries = None
        since = None; until = None; limit = None
        order_by = None; compare_with = None; extrapolate = False
        facet_order_by = None; with_timezone = None; predict = False

        while not self._at_end():
            if self._check(TokenType.WHERE):
                self.pos += 1
                where = self._parse_condition()
            elif self._check(TokenType.FACET):
                self.pos += 1
                facet = self._parse_facet_list()
                fob, fob_order = self._try_parse_facet_order_by()
                if fob:
                    facet_order_by = fob
                    order_by = fob_order
            elif self._check(TokenType.TIMESERIES):
                self.pos += 1
                timeseries = self._parse_timeseries_clause()
            elif self._check_ident('predict'):
                self.pos += 1
                predict = True
            elif self._check(TokenType.SINCE):
                self.pos += 1
                since = self._consume_time_expr()
            elif self._check(TokenType.UNTIL):
                self.pos += 1
                until = self._consume_time_expr()
            elif self._check(TokenType.LIMIT):
                self.pos += 1
                if self._check(TokenType.MAX_KW):
                    self.pos += 1
                    limit = LimitClause(value='MAX')
                else:
                    limit = LimitClause(value=int(self._expect(TokenType.NUMBER).value))
            elif self._check(TokenType.ORDER):
                self.pos += 1
                self._expect(TokenType.BY)
                expr = self._parse_expression()
                direction = 'ASC'
                if self._match(TokenType.ASC): direction = 'ASC'
                elif self._match(TokenType.DESC): direction = 'DESC'
                order_by = OrderByClause(expression=expr, direction=direction)
            elif self._check(TokenType.COMPARE):
                self.pos += 1
                self._expect(TokenType.WITH)
                compare_with = self._consume_time_expr()
            elif self._check(TokenType.EXTRAPOLATE):
                self.pos += 1
                extrapolate = True
            elif self._check(TokenType.WITH) and self._peek_with_timezone():
                self.pos += 1  # skip WITH
                self.pos += 1  # skip 'timezone' identifier
                with_timezone = self._expect(TokenType.STRING).value
            else:
                break

        return Query(
            select_items=select_items, from_clause=from_type,
            where_clause=where, facet_items=facet, timeseries=timeseries,
            since_raw=since, until_raw=until, limit=limit,
            order_by=order_by, compare_with_raw=compare_with,
            extrapolate=extrapolate, join_clause=join_clause,
            facet_order_by=facet_order_by, with_timezone=with_timezone,
            predict=predict,
        )

    # -- SELECT list --

    def _parse_select_list(self) -> List[SelectItem]:
        items = [self._parse_select_item()]
        while self._match(TokenType.COMMA):
            items.append(self._parse_select_item())
        return items

    def _parse_select_item(self) -> SelectItem:
        expr = self._parse_expression()
        alias = None
        if self._match(TokenType.AS):
            # Alias can be identifier or string
            tok = self._cur()
            if tok.type == TokenType.IDENTIFIER:
                alias = tok.value; self.pos += 1
            elif tok.type == TokenType.STRING:
                alias = tok.value; self.pos += 1
            elif tok.type == TokenType.MAX_KW:
                alias = tok.value; self.pos += 1
            else:
                raise ParseError(f"Expected alias name after AS, got {tok}", tok.pos)
        return SelectItem(expression=expr, alias=alias)

    # -- FACET list --

    def _parse_facet_list(self) -> List[FacetItem]:
        # Handle FACET CASES(...)
        if self._check(TokenType.CASES):
            self.pos += 1
            # CASES is complex -- parse as a special function call
            self._expect(TokenType.LPAREN)
            args = self._parse_cases_args()
            self._expect(TokenType.RPAREN)
            return [FacetItem(expression=FunctionCall('cases', args))]

        items = [self._parse_facet_item()]
        while self._match(TokenType.COMMA):
            items.append(self._parse_facet_item())
        return items

    def _parse_facet_item(self) -> FacetItem:
        # Handle CASES(...) appearing as a facet item (not just first position)
        if self._check(TokenType.CASES):
            self.pos += 1
            self._expect(TokenType.LPAREN)
            args = self._parse_cases_args()
            self._expect(TokenType.RPAREN)
            return FacetItem(expression=FunctionCall('cases', args))
        expr = self._parse_expression()
        alias = None
        if self._match(TokenType.AS):
            tok = self._cur()
            if tok.type in (TokenType.IDENTIFIER, TokenType.STRING, TokenType.MAX_KW):
                alias = tok.value; self.pos += 1
            else:
                raise ParseError(f"Expected alias after AS in FACET, got {tok}", tok.pos)
        return FacetItem(expression=expr, alias=alias)

    def _parse_cases_args(self) -> List[ASTNode]:
        """Parse CASES(WHERE cond AS 'label', WHERE cond2 AS 'label2', ...)
        Also handles:
        - WHERE cond, 'label' (comma-separated variant)
        - matchesPhrase(field, val) as 'label' (bare function without WHERE)"""
        args: list[ASTNode] = []
        while not self._check(TokenType.RPAREN) and not self._at_end():
            if self._match(TokenType.WHERE):
                cond = self._parse_condition()
                args.append(cond)
                # Label can follow with AS or comma
                if self._match(TokenType.AS):
                    args.append(self._parse_expression())
                elif self._check(TokenType.COMMA):
                    self._match(TokenType.COMMA)
                    if not self._check(TokenType.WHERE) and not self._check(TokenType.RPAREN):
                        args.append(self._parse_expression())
                        self._match(TokenType.COMMA)
                    continue
            else:
                # Bare expression (e.g., matchesPhrase(targetUrl, "/search") as 'label')
                args.append(self._parse_expression())
                # Check for AS alias after bare expression
                if self._match(TokenType.AS):
                    args.append(self._parse_expression())
            self._match(TokenType.COMMA)  # optional trailing comma
        return args

    def _try_parse_facet_order_by(self) -> Tuple[Optional[ASTNode], Optional[OrderByClause]]:
        """Try to parse FACET ... ORDER BY expr [ASC|DESC] immediately after facet items.
        Returns (facet_order_by_expr, order_by_clause) or (None, None)."""
        if not self._check(TokenType.ORDER):
            return None, None
        saved = self.pos
        self.pos += 1
        if not self._check(TokenType.BY):
            self.pos = saved
            return None, None
        self.pos += 1
        expr = self._parse_expression()
        direction = 'DESC'  # FACET ORDER BY defaults to DESC
        if self._match(TokenType.ASC): direction = 'ASC'
        elif self._match(TokenType.DESC): direction = 'DESC'
        return expr, OrderByClause(expression=expr, direction=direction)

    # -- TIMESERIES --

    def _parse_timeseries_clause(self) -> TimeseriesClause:
        if self._check(TokenType.AUTO):
            self.pos += 1
            slide = self._parse_slide_by()
            return TimeseriesClause(interval='AUTO', slide_by=slide)
        if self._check(TokenType.MAX_KW):
            self.pos += 1
            slide = self._parse_slide_by()
            return TimeseriesClause(interval='MAX', slide_by=slide)
        if self._check(TokenType.NUMBER):
            val = self._cur().value
            self.pos += 1
            unit = self._consume_time_unit()
            if unit:
                slide = self._parse_slide_by()
                return TimeseriesClause(interval=f"{val} {unit}", slide_by=slide)
            else:
                slide = self._parse_slide_by()
                return TimeseriesClause(interval=str(val), slide_by=slide)
        return TimeseriesClause()

    def _parse_slide_by(self) -> Optional[str]:
        """Parse optional SLIDE BY clause after TIMESERIES interval."""
        if not self._check_ident('slide'):
            return None
        self.pos += 1  # consume 'slide'
        self._expect(TokenType.BY)
        if self._check(TokenType.AUTO):
            self.pos += 1
            return 'AUTO'
        if self._check(TokenType.MAX_KW):
            self.pos += 1
            return 'MAX'
        if self._check(TokenType.NUMBER):
            val = self._cur().value
            self.pos += 1
            unit = self._consume_time_unit()
            if unit:
                return f"{val} {unit}"
            return str(val)
        return None

    def _consume_time_unit(self) -> Optional[str]:
        """If current token is a time unit identifier, consume and return it."""
        t = self._cur()
        if t.type == TokenType.IDENTIFIER and t.value.lower() in TIME_UNITS:
            self.pos += 1
            return str(t.value.lower())
        if t.type == TokenType.MAX_KW:
            # 'max' is not a time unit
            return None
        return None

    def _consume_time_expr(self) -> str:
        """Consume a time expression as raw text (SINCE/UNTIL/COMPARE WITH).
        Examples: '1 hour ago', '2024-01-01', 'yesterday', MAX"""
        parts = []
        if self._check(TokenType.MAX_KW):
            self.pos += 1
            return 'MAX'
        # Consume tokens until we hit a clause keyword
        clause_kws = {TokenType.WHERE, TokenType.FACET, TokenType.TIMESERIES,
                      TokenType.SINCE, TokenType.UNTIL, TokenType.LIMIT,
                      TokenType.ORDER, TokenType.COMPARE, TokenType.EXTRAPOLATE, TokenType.EOF}
        while not self._at_end() and self._cur().type not in clause_kws:
            t = self._cur()
            if t.type == TokenType.STRING:
                parts.append(f"'{t.value}'")
            elif t.type == TokenType.NUMBER:
                parts.append(str(t.value))
            elif t.type == TokenType.AGO:
                parts.append('ago')
            elif t.type == TokenType.IDENTIFIER:
                parts.append(t.value)
            elif t.type == TokenType.MAX_KW:
                parts.append(t.value)
            elif t.type == TokenType.MINUS:
                parts.append('-')
            else:
                break
            self.pos += 1
        return ' '.join(parts)

    # -- Conditions (WHERE clause) --

    def _parse_condition(self) -> Condition:
        return self._parse_or()

    def _parse_or(self) -> Condition:
        left = self._parse_and()
        while self._match(TokenType.OR):
            right = self._parse_and()
            left = LogicalCond('OR', left, right)
        return left

    def _parse_and(self) -> Condition:
        left = self._parse_not()
        while self._match(TokenType.AND):
            right = self._parse_not()
            left = LogicalCond('AND', left, right)
        return left

    def _parse_not(self) -> Condition:
        if self._match(TokenType.NOT):
            return NotCond(self._parse_not())
        return self._parse_primary_condition()

    def _parse_primary_condition(self) -> Condition:
        # Parenthesized -- could be a grouped condition OR an arithmetic expression
        if self._check(TokenType.LPAREN):
            # Try as grouped condition first (backtrack if fails)
            saved_pos = self.pos
            try:
                self.pos += 1  # skip (
                cond = self._parse_condition()
                self._expect(TokenType.RPAREN)
                return cond
            except ParseError:
                # Not a grouped condition -- backtrack and parse as expression comparison
                self.pos = saved_pos

        # Bare boolean function conditions: isNotNull(field), isNull(field)
        # NR allows these as standalone WHERE conditions without a comparison operator
        if self._check(TokenType.IDENTIFIER):
            func_name = self._cur().value.lower()
            if func_name in ('isnotnull', 'isnull') and self._peek(1).type == TokenType.LPAREN:
                self.pos += 1  # skip function name
                self.pos += 1  # skip (
                inner_expr = self._parse_expression()
                self._expect(TokenType.RPAREN)
                return IsNullCond(expr=inner_expr, negated=(func_name == 'isnotnull'))

        # Parse left-hand expression (includes parenthesized arithmetic like (a/b)*100)
        left = self._parse_expression()

        # IS [NOT] NULL / IS [NOT] TRUE / IS [NOT] FALSE
        if self._check(TokenType.IS):
            self.pos += 1
            negated = bool(self._match(TokenType.NOT))
            if self._check(TokenType.NULL):
                self.pos += 1
                return IsNullCond(expr=left, negated=negated)
            elif self._check(TokenType.TRUE):
                self.pos += 1
                # IS TRUE -> field == true,  IS NOT TRUE -> field != true
                op = '!=' if negated else '=='
                return ComparisonCond(left=left, op=op, right=LiteralExpr(True))
            elif self._check(TokenType.FALSE):
                self.pos += 1
                # IS FALSE -> field == false,  IS NOT FALSE -> field != false
                op = '!=' if negated else '=='
                return ComparisonCond(left=left, op=op, right=LiteralExpr(False))
            else:
                self._expect(TokenType.NULL)  # Will raise proper error

        # [NOT] IN (...)
        negated = False
        if self._check(TokenType.NOT):
            # Peek ahead for IN or LIKE
            if self._peek(1).type in (TokenType.IN, TokenType.LIKE, TokenType.RLIKE):
                self.pos += 1
                negated = True

        if self._match(TokenType.IN):
            return self._parse_in_clause(left, negated)

        # [NOT] LIKE
        if self._match(TokenType.LIKE):
            pattern = self._expect(TokenType.STRING).value
            return LikeCond(expr=left, pattern=pattern, negated=negated)

        # [NOT] RLIKE
        if self._match(TokenType.RLIKE):
            # Handle r'...' raw string prefix (NR syntax)
            if self._check(TokenType.IDENTIFIER) and self._cur().value.lower() == 'r':
                self.pos += 1  # skip 'r' prefix
            pattern = self._expect(TokenType.STRING).value
            return RLikeCond(expr=left, pattern=pattern, negated=negated)

        # Comparison: =, !=, <, >, <=, >=
        op_map = {
            TokenType.EQ: '=', TokenType.NEQ: '!=',
            TokenType.LT: '<', TokenType.GT: '>',
            TokenType.LTE: '<=', TokenType.GTE: '>=',
        }
        for tt, op_str in op_map.items():
            if self._match(tt):
                right = self._parse_expression()
                return ComparisonCond(op=op_str, left=left, right=right)

        raise ParseError(
            f"Expected comparison operator after expression, got {self._cur()}",
            self._cur().pos
        )

    def _parse_in_clause(self, left: ASTNode, negated: bool) -> Condition:
        self._expect(TokenType.LPAREN)
        # Check for subquery: IN (FROM Type SELECT ...) or IN (SELECT expr FROM Type WHERE ...)
        if self._check(TokenType.FROM) or self._check(TokenType.SELECT):
            subquery = self._parse_subquery()
            self._expect(TokenType.RPAREN)
            return InSubqueryCond(expr=left, subquery=subquery, negated=negated)
        # Value list
        values = [self._parse_expression()]
        while self._match(TokenType.COMMA):
            values.append(self._parse_expression())
        self._expect(TokenType.RPAREN)
        return InListCond(expr=left, values=values, negated=negated)

    def _parse_subquery(self) -> Query:
        """Parse subquery in either NR syntax:
           FROM Type SELECT expr [WHERE condition] [LIMIT MAX]
           SELECT expr FROM Type [WHERE condition] [LIMIT MAX]
        """
        if self._check(TokenType.SELECT):
            # SELECT-first: SELECT expr FROM Type [WHERE ...] [LIMIT MAX]
            self._expect(TokenType.SELECT)
            sel = [self._parse_select_item()]
            self._expect(TokenType.FROM)
            from_tok = self._cur()
            if from_tok.type in (TokenType.IDENTIFIER, TokenType.MAX_KW):
                from_type = from_tok.value; self.pos += 1
            else:
                raise ParseError(f"Expected event type in subquery, got {from_tok}", from_tok.pos)
        else:
            # FROM-first: FROM Type SELECT expr [WHERE ...]
            self._expect(TokenType.FROM)
            from_tok = self._cur()
            if from_tok.type in (TokenType.IDENTIFIER, TokenType.MAX_KW):
                from_type = from_tok.value; self.pos += 1
            else:
                raise ParseError(f"Expected event type in subquery, got {from_tok}", from_tok.pos)
            self._expect(TokenType.SELECT)
            sel = [self._parse_select_item()]

        where = None
        if self._check(TokenType.WHERE):
            self.pos += 1
            where = self._parse_condition()

        # Handle LIMIT [MAX|number] inside subquery -- consume but ignore
        if self._check(TokenType.LIMIT):
            self.pos += 1  # skip LIMIT
            if self._check(TokenType.MAX_KW) or self._check(TokenType.NUMBER):
                self.pos += 1  # skip MAX or number

        return Query(select_items=sel, from_clause=from_type, where_clause=where)

    # -- Expressions (arithmetic) --

    def _parse_expression(self) -> ASTNode:
        return self._parse_additive()

    def _parse_additive(self) -> ASTNode:
        left = self._parse_multiplicative()
        while self._check(TokenType.PLUS, TokenType.MINUS):
            op = '+' if self._cur().type == TokenType.PLUS else '-'
            self.pos += 1
            right = self._parse_multiplicative()
            left = BinaryOp(op, left, right)
        return left

    def _parse_multiplicative(self) -> ASTNode:
        left = self._parse_unary()
        while self._check(TokenType.STAR, TokenType.SLASH, TokenType.PERCENT):
            t = self._cur()
            op = {TokenType.STAR: '*', TokenType.SLASH: '/', TokenType.PERCENT: '%'}[t.type]
            self.pos += 1
            right = self._parse_unary()
            left = BinaryOp(op, left, right)
        return left

    def _parse_unary(self) -> ASTNode:
        if self._match(TokenType.MINUS):
            return UnaryMinus(self._parse_unary())
        return self._parse_primary()

    def _parse_primary(self) -> ASTNode:
        t = self._cur()

        # Star (wildcard)
        if t.type == TokenType.STAR:
            self.pos += 1
            return StarExpr()

        # Number literal
        if t.type == TokenType.NUMBER:
            self.pos += 1
            # Check for time interval: NUMBER IDENTIFIER(time_unit)
            if (self._cur().type == TokenType.IDENTIFIER and
                    self._cur().value.lower() in TIME_UNITS):
                unit = self._cur().value.lower()
                self.pos += 1
                return TimeInterval(value=t.value, unit=unit)
            return LiteralExpr(t.value)

        # String literal
        if t.type == TokenType.STRING:
            self.pos += 1
            return LiteralExpr(t.value)

        # Boolean / null
        if t.type == TokenType.TRUE:
            self.pos += 1; return LiteralExpr(True)
        if t.type == TokenType.FALSE:
            self.pos += 1; return LiteralExpr(False)
        if t.type == TokenType.NULL:
            self.pos += 1; return LiteralExpr(None)

        # Parenthesized expression
        if t.type == TokenType.LPAREN:
            self.pos += 1
            expr = self._parse_expression()
            self._expect(TokenType.RPAREN)
            return expr

        # Identifier: function call or field reference
        if t.type in (TokenType.IDENTIFIER, TokenType.MAX_KW):
            name = t.value
            self.pos += 1
            # Function call?
            if self._check(TokenType.LPAREN):
                self.pos += 1  # consume (
                args, where_clause = self._parse_function_args(name)
                self._expect(TokenType.RPAREN)
                return FunctionCall(name=name, args=args, where_clause=where_clause)
            return FieldRef(name)

        raise ParseError(f"Expected expression, got {t}", t.pos)

    def _parse_function_args(self, func_name: str) -> Tuple[List[ASTNode], Optional[Condition]]:
        """Parse function arguments, handling WHERE inside filter()/percentage(),
        if(condition, trueVal, falseVal), funnel(col, WHERE...AS pairs), and OR coalesce pattern."""
        args: List[ASTNode] = []
        where_clause: Optional[Condition] = None

        if self._check(TokenType.RPAREN):
            return args, None

        # NR's filter(WHERE cond) -- used as nested arg in count(*, filter(WHERE ...))
        # WHERE appears immediately with no leading expression arg
        if func_name.lower() == 'filter' and self._check(TokenType.WHERE):
            self.pos += 1  # skip WHERE
            where_clause = self._parse_condition()
            return args, where_clause

        # NR's if(condition, trueVal, falseVal) -- first arg is a condition
        if func_name.lower() == 'if':
            cond = self._parse_condition()
            args.append(cond)
            while self._match(TokenType.COMMA):
                args.append(self._parse_expression())
            return args, None

        # NR's funnel(column, WHERE cond AS 'label', WHERE cond AS 'label', ...)
        # Parse like CASES: first arg is column, then WHERE/AS pairs
        if func_name.lower() == 'funnel':
            args.append(self._parse_expression())  # column (e.g. session)
            self._match(TokenType.COMMA)  # consume comma after column
            while not self._check(TokenType.RPAREN) and not self._at_end():
                if self._check(TokenType.WHERE):
                    self.pos += 1  # skip WHERE
                    cond = self._parse_condition()
                    args.append(cond)
                    if self._match(TokenType.AS):
                        args.append(self._parse_expression())  # label string
                else:
                    args.append(self._parse_expression())
                self._match(TokenType.COMMA)  # optional separator
            return args, None

        args.append(self._parse_expression())

        # Handle NR OR-coalesce inside function args: average(fieldA OR fieldB)
        # This means "use fieldA, or if null, fieldB". We take the first arg.
        if self._check(TokenType.OR):
            self.pos += 1  # skip OR
            # Consume the rest until RPAREN, discarding the fallback expression
            depth = 1
            while not self._at_end() and depth > 0:
                if self._check(TokenType.LPAREN):
                    depth += 1
                elif self._check(TokenType.RPAREN):
                    if depth == 1:
                        break
                    depth -= 1
                self.pos += 1
            return args, None

        while self._match(TokenType.COMMA):
            # Check for WHERE in functions that support it
            if (func_name.lower() in WHERE_FUNCTIONS and self._check(TokenType.WHERE)):
                self.pos += 1
                where_clause = self._parse_condition()
                break
            args.append(self._parse_expression())

        return args, where_clause
