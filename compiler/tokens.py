"""
NRQL-to-DQL Compiler -- Token definitions and keyword mappings.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class TokenType(Enum):
    # Keywords
    SELECT = auto(); FROM = auto(); WHERE = auto()
    AND = auto(); OR = auto(); NOT = auto()
    AS = auto(); FACET = auto(); TIMESERIES = auto()
    SINCE = auto(); UNTIL = auto(); LIMIT = auto()
    IN = auto(); LIKE = auto(); RLIKE = auto()
    IS = auto(); NULL = auto(); TRUE = auto(); FALSE = auto()
    COMPARE = auto(); WITH = auto()
    ORDER = auto(); BY = auto(); ASC = auto(); DESC = auto()
    EXTRAPOLATE = auto(); AUTO = auto(); RAW = auto(); AGO = auto()
    CASES = auto(); OFFSET = auto(); MAX_KW = auto()
    # Literals & identifiers
    NUMBER = auto(); STRING = auto(); IDENTIFIER = auto()
    # Operators
    EQ = auto(); NEQ = auto(); LT = auto(); GT = auto()
    LTE = auto(); GTE = auto()
    PLUS = auto(); MINUS = auto(); STAR = auto(); SLASH = auto(); PERCENT = auto()
    # Punctuation
    LPAREN = auto(); RPAREN = auto(); COMMA = auto()
    # End
    EOF = auto()

KEYWORDS = {
    'select': TokenType.SELECT, 'from': TokenType.FROM, 'where': TokenType.WHERE,
    'and': TokenType.AND, 'or': TokenType.OR, 'not': TokenType.NOT,
    'as': TokenType.AS, 'facet': TokenType.FACET, 'timeseries': TokenType.TIMESERIES,
    'since': TokenType.SINCE, 'until': TokenType.UNTIL, 'limit': TokenType.LIMIT,
    'in': TokenType.IN, 'like': TokenType.LIKE, 'rlike': TokenType.RLIKE,
    'is': TokenType.IS, 'null': TokenType.NULL, 'true': TokenType.TRUE, 'false': TokenType.FALSE,
    'compare': TokenType.COMPARE, 'with': TokenType.WITH,
    'order': TokenType.ORDER, 'by': TokenType.BY, 'asc': TokenType.ASC, 'desc': TokenType.DESC,
    'extrapolate': TokenType.EXTRAPOLATE, 'auto': TokenType.AUTO, 'raw': TokenType.RAW,
    'ago': TokenType.AGO, 'cases': TokenType.CASES, 'offset': TokenType.OFFSET,
}

# These identifiers are NOT keywords -- they're valid field/function names
# that happen to look like keywords in some contexts
NON_KEYWORD_IDENTS = {'count', 'average', 'sum', 'max', 'min', 'rate', 'filter',
                       'percentage', 'percentile', 'uniquecount', 'latest', 'earliest',
                       'uniques', 'median', 'stddev', 'apdex', 'funnel', 'histogram',
                       'substring', 'indexof', 'length', 'concat', 'lower', 'upper',
                       'abs', 'ceil', 'floor', 'round', 'if', 'capture', 'aparse',
                       'bytecountestimate', 'allcolumnsearch', 'cardinality',
                       'cdfpercentage', 'derivative', 'eventtype', 'getfield',
                       'keyset', 'mapkeys', 'mapvalues',
                       # Phase 2+3 additions
                       'jparse', 'blob', 'clamp_max', 'clamp_min', 'ln',
                       'buckets', 'bucketpercentile', 'predictlinear',
                       'aggregationendtime', 'inner', 'left', 'join', 'on',
                       'slide', 'predict', 'show', 'event', 'types', 'timezone'}


@dataclass
class Token:
    type: TokenType
    value: Any
    pos: int
    def __repr__(self):
        return f'Token({self.type.name}, {self.value!r})'
