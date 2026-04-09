"""
NRQL-to-DQL Compiler -- AST node definitions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Union

# -- Base --

@dataclass
class ASTNode:
    pass

# -- Expressions --

@dataclass
class StarExpr(ASTNode):
    """count(*)"""
    pass

@dataclass
class LiteralExpr(ASTNode):
    value: Any   # int, float, str, bool, None

@dataclass
class FieldRef(ASTNode):
    name: str    # e.g. 'http.response.statusCode', 'appName'

@dataclass
class FunctionCall(ASTNode):
    name: str
    args: List[ASTNode]
    where_clause: Optional['Condition'] = None   # for filter(), percentage()

@dataclass
class BinaryOp(ASTNode):
    op: str      # +, -, *, /, %
    left: ASTNode
    right: ASTNode

@dataclass
class UnaryMinus(ASTNode):
    operand: ASTNode

@dataclass
class TimeInterval(ASTNode):
    """1 minute, 5 seconds, etc."""
    value: Union[int, float]
    unit: str    # second, minute, hour, day, week, month

# -- Conditions --

@dataclass
class Condition(ASTNode):
    pass

@dataclass
class ComparisonCond(Condition):
    op: str      # =, !=, <, >, <=, >=
    left: ASTNode
    right: ASTNode

@dataclass
class LogicalCond(Condition):
    op: str      # AND, OR
    left: Condition
    right: Condition

@dataclass
class NotCond(Condition):
    operand: Condition

@dataclass
class IsNullCond(Condition):
    expr: ASTNode
    negated: bool = False   # IS NOT NULL

@dataclass
class InListCond(Condition):
    expr: ASTNode
    values: List[ASTNode]
    negated: bool = False

@dataclass
class InSubqueryCond(Condition):
    expr: ASTNode
    subquery: 'Query'
    negated: bool = False

@dataclass
class LikeCond(Condition):
    expr: ASTNode
    pattern: str
    negated: bool = False

@dataclass
class RLikeCond(Condition):
    expr: ASTNode
    pattern: str
    negated: bool = False

# -- Clauses & Query --

@dataclass
class SelectItem(ASTNode):
    expression: ASTNode
    alias: Optional[str] = None

@dataclass
class FacetItem(ASTNode):
    expression: ASTNode
    alias: Optional[str] = None

@dataclass
class TimeseriesClause(ASTNode):
    interval: Optional[str] = None   # 'AUTO', '1 minute', None
    slide_by: Optional[str] = None   # 'AUTO', 'MAX', '1 minute', None

@dataclass
class LimitClause(ASTNode):
    value: Union[int, str]   # number or 'MAX'

@dataclass
class OrderByClause(ASTNode):
    expression: ASTNode
    direction: str = 'ASC'

@dataclass
class JoinClause(ASTNode):
    join_type: str             # 'INNER' or 'LEFT'
    subquery: 'Query'
    on_left: Optional[str] = None    # parent key (or None if same key)
    on_right: Optional[str] = None   # subquery key

@dataclass
class Query(ASTNode):
    select_items: List[SelectItem]
    from_clause: str
    where_clause: Optional[Condition] = None
    facet_items: Optional[List[FacetItem]] = None
    timeseries: Optional[TimeseriesClause] = None
    since_raw: Optional[str] = None
    until_raw: Optional[str] = None
    limit: Optional[LimitClause] = None
    order_by: Optional[OrderByClause] = None
    compare_with_raw: Optional[str] = None
    extrapolate: bool = False
    join_clause: Optional[JoinClause] = None
    facet_order_by: Optional[ASTNode] = None  # FACET ... ORDER BY agg()
    with_timezone: Optional[str] = None
    predict: bool = False
