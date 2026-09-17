"""Shared helpers for Davis anomaly-detector emission.

The Gen3 ``builtin:davis.anomaly-detectors`` schema puts the metric
expression in ``analyzer.input`` as a ``{key: "query", value: "<DQL>"}``
entry. The tenant server-validates the value as DQL syntax — sending
NRQL (or anything that starts with ``SELECT`` / ``FROM``) produces::

    400 "Error parsing parameter 'query'. Invalid DQL query.
         `FROM` isn't allowed here."

``nrql_to_analyzer_query`` routes the raw NRQL source through
:class:`~transformers.nrql_converter.NRQLtoDQLConverter` and returns:

* the translated DQL, when conversion succeeds with HIGH or MEDIUM
  confidence **and** the result is (or can be rewritten into) a timeseries; or
* a fallback string that is always **valid, inert DQL** and preserves the
  original NRQL as a ``//`` comment. The fallback lets the detector create so
  the operator can fix the query in-place in the UI rather than losing
  the detector entirely.

Anomaly-detector analyzers only accept timeseries results. Verified live
(docs/live-validation-2026-09.md, D1): ``fetch … | summarize …`` fails with
"No valid time series records found"; ``fetch … | makeTimeseries …`` works.
The old placeholder ``timeseries count()`` is also invalid (D11: count() needs
a metric key).
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from .nrql_converter import NRQLtoDQLConverter

# Cached converter — creating one is relatively expensive (loads the
# compiler, mapping tables, converters). All detector transformers
# share this single instance.
_CONVERTER: Optional[NRQLtoDQLConverter] = None


def _get_converter() -> NRQLtoDQLConverter:
    global _CONVERTER
    if _CONVERTER is None:
        _CONVERTER = NRQLtoDQLConverter()
    return _CONVERTER


def nrql_to_analyzer_query(
    nrql: str,
    *,
    warnings: Optional[List[str]] = None,
) -> str:
    """Translate NR NRQL to DQL for an anomaly-detector analyzer.input entry.

    - Empty / whitespace NRQL → ``FALLBACK_QUERY`` (valid, inert timeseries so the
      detector creates but never fires; operator can edit in-place).
    - HIGH/MEDIUM conversion → the converter's DQL, normalised to a timeseries by
      :func:`ensure_timeseries` (``summarize`` → ``makeTimeseries``).
    - LOW or failed conversion → ``// UNCONVERTED NRQL: <original>\\n``
      ``FALLBACK_QUERY``. The comment preserves the NRQL for
      operator review; the trailing inert timeseries keeps the
      payload valid. Also used when the DQL cannot be made a timeseries.

    Appends a descriptive entry to ``warnings`` (if provided) when the
    fallback path fires so the migration summary flags what needs
    manual attention.
    """
    if not nrql or not nrql.strip():
        return FALLBACK_QUERY

    converter = _get_converter()
    try:
        result = converter.convert(nrql)
    except Exception as exc:  # noqa: BLE001 — any converter failure is non-fatal
        if warnings is not None:
            warnings.append(
                f"NRQL→DQL conversion raised ({exc}); detector emitted "
                f"with placeholder query + original NRQL preserved as "
                f"comment."
            )
        return _fallback(nrql)

    confidence = (result.confidence or "").upper()
    if result.success and result.dql and confidence in ("HIGH", "MEDIUM"):
        timeseries_dql = ensure_timeseries(result.dql)
        if timeseries_dql is not None:
            return timeseries_dql
        if warnings is not None:
            warnings.append(
                "Converted DQL is not a timeseries (anomaly detectors require "
                "timeseries/makeTimeseries); detector emitted with an inert "
                "placeholder query + original NRQL preserved as comment."
            )
        return _fallback(nrql)

    if warnings is not None:
        warnings.append(
            f"NRQL→DQL conversion was {confidence or 'UNKNOWN'}; detector "
            f"emitted with placeholder query + original NRQL preserved as "
            f"comment for operator review."
        )
    return _fallback(nrql)


def _fallback(nrql: str) -> str:
    """Format a LOW-confidence fallback — comment + valid DQL placeholder.

    Starts with ``//`` (a DQL comment) so wire-level regression tests
    that guard against leaked NRQL (``SELECT``/``FROM``) succeed, and
    ends with the inert ``FALLBACK_QUERY`` so the analyzer accepts it.
    """
    # Collapse whitespace in the NRQL so the comment stays single-line.
    one_line = " ".join(nrql.split())
    return f"// UNCONVERTED NRQL: {one_line}\n{FALLBACK_QUERY}"


# Valid timeseries that matches no data, so an unconverted detector can never
# fire (verified live: analyzer reports "no input data", no alert).
FALLBACK_QUERY = (
    'timeseries unconverted = count(dt.host.cpu.usage), '
    'filter:{host.name == "__nr_migration_unconverted__"}'
)

_AGG_FUNC_RE = re.compile(
    r"\b(count|countIf|countDistinct|countDistinctExact|countDistinctApprox|sum|avg|min|max|"
    r"percentile|median|stddev|variance)\s*\("
)
# Stages after `summarize` that can be dropped without changing the aggregate.
_TRAILING_OK = {"sort", "limit"}


def _split_top_level(text: str, sep: str = ",") -> List[str]:
    parts, depth, cur, quote = [], 0, [], ""
    for ch in text:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur).strip())
    return parts


def _call_span(text: str, start: int) -> int:
    """Index just past the balanced ``(...)`` that opens at/after ``start``."""
    depth = 0
    for i in range(text.index("(", start), len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
    raise ValueError("unbalanced parentheses")


def _is_single_call(expr: str) -> bool:
    m = _AGG_FUNC_RE.match(expr)
    return bool(m) and _call_span(expr, 0) == len(expr)


def _rewrite_summarize(body: str) -> Optional[Tuple[str, List[str], List[str]]]:
    """``summarize`` body -> (makeTimeseries body, post fieldsAdd items, temp names)."""
    items = _split_top_level(body)
    by = [i for i in items if re.match(r"^by\s*:", i)]
    aggs = [i for i in items if not re.match(r"^by\s*:", i)]
    if not aggs:
        return None
    named: List[str] = []
    post: List[str] = []
    temps: List[str] = []
    for idx, item in enumerate(aggs):
        m = re.match(r"^([A-Za-z_][\w.]*|`[^`]+`)\s*=\s*(.+)$", item, re.S)
        alias, expr = (m.group(1), m.group(2).strip()) if m else (None, item)
        if _is_single_call(expr):
            named.append(f"{alias} = {expr}" if alias else expr)
            continue
        # Arithmetic over aggregations (e.g. percentage): compute each call as a
        # series, then combine element-wise.
        out, pos, found = [], 0, False
        for call in _AGG_FUNC_RE.finditer(expr):
            if call.start() < pos:
                continue
            end = _call_span(expr, call.start())
            name = f"nr_agg{len(temps)}"
            temps.append(name)
            named.append(f"{name} = {expr[call.start():end]}")
            out.append(expr[pos:call.start()] + f"{name}[]")
            pos, found = end, True
        if not found:
            return None
        out.append(expr[pos:])
        post.append(f"{alias or f'value{idx}'} = {''.join(out)}")
    agg_part = named[0] if len(named) == 1 else "{ " + ", ".join(named) + " }"
    return ", ".join([agg_part] + by), post, temps


def ensure_timeseries(dql: str) -> Optional[str]:
    """Return ``dql`` as a timeseries query for an analyzer, or None if unsafe."""
    lines = dql.split("\n")
    comments = [ln for ln in lines if ln.lstrip().startswith("//")]
    code = [ln for ln in lines if ln.strip() and not ln.lstrip().startswith("//")]
    if not code:
        return None
    stages = [ln.strip().lstrip("|").strip() for ln in code]
    head = stages[0]
    def cmd(stage: str) -> str:
        return stage.split(None, 1)[0] if stage else ""

    if cmd(head) == "timeseries" and not any(cmd(s) == "summarize" for s in stages[1:]):
        return dql
    if cmd(head) != "fetch":
        return None
    if any(cmd(s) == "makeTimeseries" for s in stages) and not any(cmd(s) == "summarize" for s in stages):
        return dql
    idx = [i for i, s in enumerate(stages) if cmd(s) == "summarize"]
    if len(idx) != 1:
        return None
    i = idx[0]
    if any(s.split(None, 1)[0] not in _TRAILING_OK for s in stages[i + 1:]):
        return None
    try:
        rewritten = _rewrite_summarize(stages[i][len("summarize"):].strip())
    except ValueError:
        return None
    if rewritten is None:
        return None
    body, post, temps = rewritten
    out = stages[:i] + [f"makeTimeseries {body}"]
    if post:
        out.append("fieldsAdd " + ", ".join(post))
        out.append("fieldsRemove " + ", ".join(temps))
    query = out[0] + "".join(f"\n| {s}" for s in out[1:])
    return "\n".join(comments + [query])
