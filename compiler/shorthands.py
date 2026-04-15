"""
Pre-lex NRQL shorthand expansion (Phase 19b — ported from nrql-engine).

New Relic users commonly write convenience aliases like `apdexScore`,
`throughput`, or `errorRate` in NRQL queries. Running these through the
lexer as-is produces unknown-function errors. `expand_nr_shorthands`
rewrites them to their canonical NRQL form **before** lexing, so the
rest of the compiler pipeline treats them as normal calls.

Mirrors `NRQLCompiler.expandNrShorthands()` in the TypeScript sibling
(`/Users/Shared/GitHub/PROJECTS/nrql-engine/src/compiler/compiler.ts`
~line 151). Keep the list of patterns in sync across both projects.
"""

from __future__ import annotations

import re
from typing import List, Tuple

# Each entry: (regex pattern, canonical-NRQL replacement).
# `\b...\b` word boundaries prevent partial-word matches inside identifiers.
_SHORTHAND_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\baverage[Dd]uration\b"), "average(duration)"),
    (re.compile(r"\baverage[Rr]esponse[Tt]ime\b"), "average(duration)"),
    (re.compile(r"\bmax[Dd]uration\b"), "max(duration)"),
    (re.compile(r"\bmin[Dd]uration\b"), "min(duration)"),
    (re.compile(r"\bmedian[Dd]uration\b"), "median(duration)"),
    (re.compile(r"\bapdex[Ss]core\b"), "apdex(duration)"),
    (re.compile(r"\bapdex[Pp]erf[Zz]one\b"), "apdex(duration)"),
    (re.compile(r"\berror[Rr]ate\b"), "percentage(count(*), WHERE error IS TRUE)"),
    (re.compile(r"\bthroughput\b"), "rate(count(*), 1 minute)"),
]


def expand_nr_shorthands(nrql: str) -> str:
    """Expand NR shorthand identifiers to canonical NRQL before lexing.

    Idempotent: applying twice yields the same result as applying once
    (because the expanded forms no longer contain shorthand identifiers).
    """
    if not nrql:
        return nrql
    for pattern, replacement in _SHORTHAND_PATTERNS:
        nrql = pattern.sub(replacement, nrql)
    return nrql
