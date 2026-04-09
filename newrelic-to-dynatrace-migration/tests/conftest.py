"""Shared fixtures for NRQL compiler tests."""

import re
import sys
from pathlib import Path

import pytest

# Allow importing from project root until package restructure is complete.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from compiler import NRQLCompiler
except ImportError:
    # Fallback: import directly from the monolith while the package is being built.
    from compiler import NRQLCompiler


@pytest.fixture(scope="session")
def compiler():
    """Session-scoped compiler instance shared across all tests."""
    return NRQLCompiler()


# ---------------------------------------------------------------------------
# Structural-validity constants reused by Group 14 tests
# ---------------------------------------------------------------------------

NRQL_KEYWORDS = [
    "SELECT ", "FACET ", "SINCE ", "UNTIL ", "TIMESERIES ",
    "EXTRAPOLATE", "COMPARE WITH", "LIMIT MAX",
]

NRQL_EVENTS = [
    "FROM Transaction ", "FROM TransactionError ", "FROM Span ",
    "FROM Log ", "FROM Metric ", "FROM SystemSample",
    "FROM ProcessSample", "FROM K8sContainerSample",
    "FROM K8sNodeSample", "FROM K8sPodSample",
    "FROM PageView", "FROM SyntheticCheck", "FROM NetworkSample",
    "FROM StorageSample", "FROM ContainerSample",
    "FROM K8sClusterSample", "FROM K8sDeploymentSample",
    "FROM PageAction", "FROM BrowserInteraction",
    "FROM JavaScriptError", "FROM AjaxRequest",
    "FROM InfrastructureEvent", "FROM AwsLambdaInvocation",
]

INVALID_FUNCS = [
    "uniqueCount(", "median(", "apdex(",
    "bytecountestimate(", "latest(", "earliest(",
]

DQL_RESERVED_ALIASES = {
    "duration", "timestamp", "timeframe", "string",
    "long", "double", "boolean", "ip", "record",
    "array", "fetch", "filter", "summarize", "fields",
    "sort", "limit", "lookup", "join", "append",
    "parse", "from", "to", "by", "in", "is", "not",
    "and", "or", "true", "false", "null",
}


def code_lines(dql: str) -> str:
    """Return only the non-comment lines of DQL output."""
    return "\n".join(
        line for line in dql.split("\n") if not line.strip().startswith("//")
    )


def assert_valid_dql(result):
    """Universal structural validity check mirroring the original V() helper."""
    assert result.success, f"Expected success but got error: {result.error}"
    code = code_lines(result.dql)
    if not code.strip():
        return

    # No NRQL keywords leaked
    for kw in NRQL_KEYWORDS:
        assert kw not in code, f"NRQL keyword leaked: '{kw.strip()}'"

    # No NR event types leaked
    for et in NRQL_EVENTS:
        assert et not in code, f"NR event type leaked: '{et.strip()}'"

    # No invalid functions (unless inside a block comment)
    for fn in INVALID_FUNCS:
        idx = code.find(fn)
        if idx >= 0:
            before = code[max(0, idx - 40):idx]
            assert "/*" in before, f"Invalid function '{fn}'"

    # Balanced parentheses
    depth = 0
    for ch in code:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        assert depth >= 0, "Unbalanced parens (too many closing)"
    assert depth == 0, f"Unbalanced parens ({depth} unclosed)"

    # Balanced backticks, quotes, braces
    assert code.count("`") % 2 == 0, "Unbalanced backticks"
    assert code.count('"') % 2 == 0, "Unbalanced quotes"

    bd = 0
    for ch in code:
        if ch == "{":
            bd += 1
        elif ch == "}":
            bd -= 1
    assert bd == 0, f"Unbalanced braces ({bd})"

    # No empty pipe segments
    assert not re.search(r"\|\s*\|", code), "Empty pipe segment"

    # No aggregations inside fieldsAdd
    for line in code.split("\n"):
        cmd = line.strip().lstrip("| ")
        if cmd.startswith("fieldsAdd "):
            for agg in [
                "sum(", "avg(", "count(", "min(", "max(",
                "countDistinct(", "percentile(",
            ]:
                m2 = re.search(r"=\s*" + re.escape(agg), cmd[10:])
                if m2:
                    assert False, f"Aggregation {agg} in fieldsAdd"

    # Reserved-word aliases must be backtick-quoted
    for line in code.split("\n"):
        cmd = line.strip().lstrip("| ")
        if cmd.startswith(("summarize ", "makeTimeseries ", "timeseries ", "fieldsAdd ")):
            for m2 in re.finditer(r"(?<![`\w])(\w+)\s*=(?!=)", cmd):
                alias = m2.group(1)
                if alias.lower() in DQL_RESERVED_ALIASES:
                    assert f"`{alias}`" in line, f"Bare reserved alias '{alias}'"

    # Digit-prefix aliases must be backtick-quoted
    for line in code.split("\n"):
        for m2 in re.finditer(r"(?<![`\w])(\d\w+)\s*=(?!=)", line):
            alias = m2.group(1)
            assert f"`{alias}`" in line, f"Bare digit-prefix alias '{alias}'"

    # substring must use named params when 3+ args
    for m2 in re.finditer(r"substring\(([^)]+)\)", code):
        args = m2.group(1)
        parts = [p.strip() for p in args.split(",")]
        if len(parts) >= 3:
            assert "from:" in args, "substring without named params"
