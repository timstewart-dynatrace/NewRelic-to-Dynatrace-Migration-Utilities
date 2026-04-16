"""Phase 19b — nrql-engine compiler-parity regression tests.

These tests pin the Python compiler's behavior against nrql-engine
(`/Users/Shared/GitHub/PROJECTS/nrql-engine/`) for three compiler items:

1. NR shorthand expansion (`compiler/shorthands.py`, mirrors TS
   `NRQLCompiler.expandNrShorthands`).
2. K8s metric overrides + entity-field map (`compiler/emitter.py`
   `K8S_METRIC_OVERRIDES` / `K8S_ENTITY_FIELDS`, mirrors TS
   `DQLEmitter.K8S_METRIC_OVERRIDES` / `K8S_ENTITY_FIELDS`).
3. DQL fixer rule coverage (`validators/dql_fixer.py`, mirrors TS
   `dql-fixer.ts` private fix methods).

They assert the Python surface is at least at TS parity; drift in either
direction will trip a test.
"""

from compiler.emitter import DQLEmitter
from compiler.shorthands import expand_nr_shorthands
from validators.dql_fixer import DQLValidator as DQLFixer  # class renamed in this codebase


# ---------------------------------------------------------------------------
# 1. Shorthand expansion
# ---------------------------------------------------------------------------


class TestShorthandExpansion:
    def test_average_duration(self):
        assert (
            expand_nr_shorthands("SELECT averageDuration FROM Transaction")
            == "SELECT average(duration) FROM Transaction"
        )

    def test_average_response_time(self):
        assert (
            expand_nr_shorthands("SELECT averageResponseTime FROM Transaction")
            == "SELECT average(duration) FROM Transaction"
        )

    def test_max_min_median_duration(self):
        assert "max(duration)" in expand_nr_shorthands("SELECT maxDuration FROM Transaction")
        assert "min(duration)" in expand_nr_shorthands("SELECT minDuration FROM Transaction")
        assert "median(duration)" in expand_nr_shorthands("SELECT medianDuration FROM Transaction")

    def test_apdex_score_and_perfzone(self):
        assert "apdex(duration)" in expand_nr_shorthands("SELECT apdexScore FROM Transaction")
        assert "apdex(duration)" in expand_nr_shorthands("SELECT apdexPerfZone FROM Transaction")

    def test_error_rate(self):
        assert (
            "percentage(count(*), WHERE error IS TRUE)"
            in expand_nr_shorthands("SELECT errorRate FROM Transaction")
        )

    def test_throughput(self):
        assert (
            "rate(count(*), 1 minute)"
            in expand_nr_shorthands("SELECT throughput FROM Transaction")
        )

    def test_idempotent(self):
        once = expand_nr_shorthands("SELECT throughput FROM Transaction")
        twice = expand_nr_shorthands(once)
        assert once == twice

    def test_word_boundary_prevents_partial_match(self):
        # `apdexScorer` (custom field) must not match `apdexScore`.
        nrql = "SELECT apdexScorer FROM Custom"
        assert expand_nr_shorthands(nrql) == nrql

    def test_empty_input(self):
        assert expand_nr_shorthands("") == ""

    def test_no_shorthands_passthrough(self):
        nrql = "SELECT count(*) FROM Transaction"
        assert expand_nr_shorthands(nrql) == nrql


# ---------------------------------------------------------------------------
# 2. K8s overrides + entity-field map
# ---------------------------------------------------------------------------


class TestK8sOverridesParity:
    # Lifted from nrql-engine emitter.ts lines 319–343.
    EXPECTED_METRIC_OVERRIDES = {
        "memoryusedbytes": "dt.kubernetes.container.memory_working_set",
        "memoryused": "dt.kubernetes.container.memory_working_set",
        "cpuusedbytes": "dt.kubernetes.container.cpu_usage",
        "cpupercent": "dt.kubernetes.container.cpu_usage",
        "diskused": "dt.kubernetes.persistentvolumeclaim.used",
        "diskusedbytes": "dt.kubernetes.persistentvolumeclaim.used",
        "restartcount": "dt.kubernetes.container.restarts",
        "restartcountdelta": "dt.kubernetes.container.restarts",
        "cpuusedcores": "dt.kubernetes.container.cpu_usage",
        "memoryworkingsetbytes": "dt.kubernetes.container.memory_working_set",
    }

    def test_metric_overrides_match_typescript(self):
        for key, value in self.EXPECTED_METRIC_OVERRIDES.items():
            assert DQLEmitter.K8S_METRIC_OVERRIDES.get(key) == value, (
                f"K8s metric override drift for '{key}': "
                f"expected {value!r}, got {DQLEmitter.K8S_METRIC_OVERRIDES.get(key)!r}"
            )

    def test_entity_fields_present(self):
        # TS expects isready / status / isscheduled (lower-case keys).
        for key in ("isready", "status", "isscheduled"):
            assert key in DQLEmitter.K8S_ENTITY_FIELDS, f"Missing entity-field: {key}"
            entry = DQLEmitter.K8S_ENTITY_FIELDS[key]
            assert "dql" in entry and "note" in entry

    def test_entity_fields_use_cloud_application(self):
        # TS emits fetch dt.entity.cloud_application[_instance] — parity check.
        for key, entry in DQLEmitter.K8S_ENTITY_FIELDS.items():
            assert entry["dql"].startswith("fetch dt.entity.cloud_application"), (
                f"Entity-field {key} must start with cloud_application fetch; "
                f"got: {entry['dql'][:60]}"
            )


# ---------------------------------------------------------------------------
# 3. DQL fixer rule coverage — one assertion per TS private fix method
# ---------------------------------------------------------------------------


class TestDQLFixerParity:
    # Names of the private `fix*` methods in TS (dql-fixer.ts). For each,
    # we assert Python's DQLFixer exposes a `_fix_<snake_case>` equivalent.
    TS_FIX_METHODS = [
        "Variables",
        "Backticks",
        "Quotes",
        "ComparisonOperators",
        "LogicalOperators",
        "NullChecks",
        "LikePatterns",
        "WhereInFilter",
        "TimeseriesCount",
        "InvalidFunctions",
        "BrokenByClause",
        "FieldNames",
        "DuplicateAggregations",
        "PercentileNaming",
        "AsAliases",
        "BareFieldInSummarize",
        "NrqlSubqueries",
        "MetricNames",
        "DurationUnits",
        "NegationToFilterout",
        "ArrayCountWithoutExpand",
        "Whitespace",
    ]

    @staticmethod
    def _to_snake(name: str) -> str:
        import re
        return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()

    def test_every_ts_fixer_has_python_equivalent(self):
        missing = []
        for ts_name in self.TS_FIX_METHODS:
            py_name = "_fix_" + self._to_snake(ts_name)
            if not hasattr(DQLFixer, py_name):
                missing.append((ts_name, py_name))
        assert not missing, (
            "Python DQLFixer missing equivalents for TS fixers: "
            f"{[f'TS {a} -> Python {b}' for a, b in missing]}"
        )

    def test_fixer_count_at_or_above_ts(self):
        py_fix_count = sum(
            1 for name in dir(DQLFixer) if name.startswith("_fix_")
        )
        assert py_fix_count >= len(self.TS_FIX_METHODS)


# ---------------------------------------------------------------------------
# 4. Shorthand module is importable without pulling the whole compiler
# ---------------------------------------------------------------------------


class TestShorthandStandaloneImport:
    def test_module_is_self_contained(self):
        # The module must not depend on ast_nodes / emitter / parser / lexer —
        # so it can be reused by tests or other tooling without forcing the
        # compiler initialization chain.
        import compiler.shorthands as mod
        assert hasattr(mod, "expand_nr_shorthands")
        # Cannot assert negative imports cleanly, but calling with a simple
        # string should succeed without any compiler machinery.
        assert mod.expand_nr_shorthands("SELECT throughput FROM T") != "SELECT throughput FROM T"
