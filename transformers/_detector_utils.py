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
  confidence; or
* a fallback string that is always **valid DQL** and preserves the
  original NRQL as a ``//`` comment, when conversion fails or
  ``LOW``-confidence. The fallback lets the detector create so the
  operator can fix the query in-place in the UI rather than losing
  the detector entirely.
"""

from __future__ import annotations

from typing import List, Optional

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

    - Empty / whitespace NRQL → ``timeseries count()`` placeholder (harmless
      valid DQL so the detector creates; operator can edit in-place).
    - HIGH/MEDIUM conversion → the converter's DQL output.
    - LOW or failed conversion → ``// UNCONVERTED NRQL: <original>\\n``
      ``timeseries count()``. The comment preserves the NRQL for
      operator review; the trailing ``timeseries count()`` keeps the
      payload server-validatable.

    Appends a descriptive entry to ``warnings`` (if provided) when the
    fallback path fires so the migration summary flags what needs
    manual attention.
    """
    if not nrql or not nrql.strip():
        return "timeseries count()"

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
        return result.dql

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
    ends with a trivially valid ``timeseries count()`` so tenant-side
    DQL validation passes.
    """
    # Collapse whitespace in the NRQL so the comment stays single-line.
    one_line = " ".join(nrql.split())
    return f"// UNCONVERTED NRQL: {one_line}\ntimeseries count()"
