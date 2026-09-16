"""Phase 19b — nrql-engine compiler-parity regression tests.

These tests pin the Python compiler's behavior against nrql-engine
(`/Users/Shared/GitHub/PROJECTS/NewRelic/nrql-engine/`) for three compiler items:

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

    # Exact strings shared with TS DQLEmitter.K8S_ENTITY_FIELDS (Smartscape, gen3-apis.md §7).
    EXPECTED_ENTITY_FIELD_DQL = {
        "isready": (
            'smartscapeNodes K8S_DEPLOYMENT, K8S_STATEFULSET, K8S_REPLICASET\n'
            '| parse k8s.object, "JSON:config"\n'
            '| fieldsAdd desiredReplicas = config[`spec`][`replicas`], '
            'readyReplicas = config[`status`][`readyReplicas`]'
        ),
        "status": (
            'smartscapeNodes K8S_DEPLOYMENT, K8S_DAEMONSET, K8S_STATEFULSET, K8S_REPLICASET, '
            'K8S_REPLICATIONCONTROLLER, K8S_JOB, K8S_DEPLOYMENTCONFIG\n'
            '| parse k8s.object, "JSON:config"\n'
            '| fieldsAdd desiredReplicas = config[`spec`][`replicas`], '
            'readyReplicas = config[`status`][`readyReplicas`], '
            'availableReplicas = config[`status`][`availableReplicas`]'
        ),
        "isscheduled": (
            'smartscapeNodes K8S_POD\n'
            '| parse k8s.object, "JSON:config"\n'
            '| fieldsAdd phase = config[`status`][`phase`]'
        ),
    }

    def test_entity_fields_use_smartscape(self):
        for key, expected in self.EXPECTED_ENTITY_FIELD_DQL.items():
            assert DQLEmitter.K8S_ENTITY_FIELDS[key]["dql"] == expected, f"Entity-field drift for {key}"
            assert "dt.entity" not in DQLEmitter.K8S_ENTITY_FIELDS[key]["dql"]


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
        "ClassicEntityReferences",
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


# ---------------------------------------------------------------------------
# 5. Smartscape-first emission (gen3-apis.md §7) — mirrored in TS
#    tests/compiler/smartscape-parity.test.ts
# ---------------------------------------------------------------------------


class TestSmartscapeParity:
    """Same inputs / expected outputs as the TS parity suite."""

    def test_entity_name_by_context(self, compiler):
        cases = {
            "SELECT count(*) FROM Transaction WHERE entityName = 'svc'": 'service.name == "svc"',
            "SELECT average(cpuPercent) FROM SystemSample FACET entityName": "by: {host.name}",
            "SELECT average(apm.service.transaction.duration) FROM Metric FACET entity.name":
                "by: {dt.service.name}",
            "SELECT average(cpuUsedCores) FROM K8sContainerSample FACET entityName":
                "by: {k8s.workload.name}",
        }
        for nrql, expected in cases.items():
            result = compiler.compile(nrql)
            assert result.success, nrql
            assert expected in result.dql, (nrql, result.dql)
            assert "dt.entity" not in result.dql, (nrql, result.dql)

    def test_entity_guid_maps_to_smartscape_service(self):
        assert DQLEmitter().field_map["entityguid"] == "dt.smartscape.service"

    def test_show_event_types_has_no_classic_fetch(self, compiler):
        result = compiler.compile("SHOW EVENT TYPES")
        assert "dt.entity" not in result.dql

    FIXER_CASES = [
        ("fetch dt.entity.host\n| fields entity.name, id", "smartscapeNodes HOST\n| fields name, id"),
        (
            "timeseries avg(dt.host.cpu.usage), by: {dt.entity.host}\n| fieldsAdd n = entityName(dt.entity.host)",
            "timeseries avg(dt.host.cpu.usage), by: {dt.smartscape.host}\n| fieldsAdd n = getNodeName(dt.smartscape.host)",
        ),
        (
            'fetch spans\n| filter dt.entity.process_group_instance == "PROCESS_GROUP_INSTANCE-18AA85290DF3D5D2"',
            '// NOTE: classic entity IDs wrapped in toSmartscapeId(); verify they resolve '
            '(IDs do not always carry over)\n'
            'fetch spans\n| filter dt.smartscape.process == toSmartscapeId("PROCESS_GROUP_INSTANCE-18AA85290DF3D5D2")',
        ),
    ]

    def test_fixer_rewrites_one_to_one(self):
        for dql, expected in self.FIXER_CASES:
            assert DQLFixer().validate_and_fix(dql)[0] == expected

    def test_fixer_annotates_but_does_not_rewrite(self):
        for dql, note in [
            ("fetch dt.entity.cloud_application\n| fields entity.name", "maps to several Smartscape types"),
            ('fetch logs | filter in(dt.entity.host, classicEntitySelector("type(host)"))',
             "classicEntitySelector is deprecated"),
            ('fetch spans | filter dt.entity.process_group == "x"', "has no Smartscape entity"),
            ('fetch spans | fieldsAdd t = entityAttr(dt.entity.host, "tags")', "entityAttr() is deprecated"),
        ]:
            out = DQLFixer().validate_and_fix(dql)[0]
            code = "\n".join(ln for ln in out.split("\n") if not ln.startswith("//"))
            assert note in out, out
            assert code == dql if "entityAttr" not in dql else "dt.smartscape.host" in code

    def test_fixer_leaves_comments_and_clean_dql_alone(self):
        dql = "// Original NRQL: FROM dt.entity.host\nfetch spans\n| summarize count()"
        assert DQLFixer().validate_and_fix(dql)[0] == dql

    def test_fixer_is_idempotent(self):
        for dql, _ in self.FIXER_CASES:
            once = DQLFixer().validate_and_fix(dql)[0]
            assert DQLFixer().validate_and_fix(once)[0] == once


class TestPlatformSloIndicatorWirePayload:
    """The Platform SLO POST body's customSli.indicator must be Smartscape DQL."""

    def _capture(self, slo_type):
        import json
        from unittest.mock import MagicMock, patch

        from transformers.nrql_converter import NRQLtoDQLConverter

        conv = NRQLtoDQLConverter()
        conv._dt_url = "https://abc123.apps.dynatrace.com"
        conv._dt_token = "dt0s16.test"
        captured = {}

        def fake_urlopen(req, **kw):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode("utf-8"))
            resp = MagicMock()
            resp.read.return_value = b'{"id": "slo-1"}'
            resp.__enter__.return_value = resp
            return resp

        with patch.object(conv, "_check_existing_slo_in_dt", return_value=None), \
                patch("transformers.nrql_converter.urllib.request.urlopen", side_effect=fake_urlopen):
            ok, _, _ = conv._create_slo_in_dt({
                "guid": "g1", "name": "checkout availability", "target": 99.5,
                "slo_type": slo_type, "service_name": "checkout",
            })
        assert ok
        return captured

    def test_availability_indicator_is_smartscape(self):
        cap = self._capture("availability")
        assert cap["url"].endswith("/platform/slo/v1/slos")
        indicator = cap["body"]["customSli"]["indicator"]
        assert "by: { dt.smartscape.service }" in indicator
        assert "getNodeName(dt.smartscape.service)" in indicator
        assert "dt.entity" not in indicator and "entityName(" not in indicator

    def test_latency_indicator_is_smartscape(self):
        indicator = self._capture("latency")["body"]["customSli"]["indicator"]
        assert "by: { dt.smartscape.service }" in indicator
        assert "dt.entity" not in indicator


class TestGuidResolutionUsesDimensions:
    GUID = "MTIzNDU2fElORlJBfE5BfDEyMzQ1Njc4OQ"

    def _convert(self, entity_type, name):
        from transformers.nrql_converter import NRQLtoDQLConverter

        conv = NRQLtoDQLConverter()
        conv.load_guid_mappings({self.GUID: name}, {self.GUID: entity_type})
        return conv.convert(f"SELECT count(*) FROM Transaction WHERE entity.guid = '{self.GUID}'")

    def test_host_guid_resolves_to_host_name(self):
        result = self._convert("HOST", "web-01")
        assert 'host.name == "web-01"' in result.dql
        assert "dt.entity" not in result.dql

    def test_other_guid_resolves_to_service_name_with_warning(self):
        result = self._convert("MONITOR", "ping")
        assert 'service.name == "ping"' in result.dql
        assert "dt.entity" not in result.dql
        assert any("verify the dimension" in w for w in result.warnings)


class TestPlatformSloParity:
    """Exact strings shared with TS tests/transformers/slo-parity.test.ts."""

    AVAILABILITY_CHECKOUT = "timeseries {\n  total=sum(dt.service.request.count),\n  failures=sum(dt.service.request.failure_count)\n}, by: { dt.smartscape.service }\n| fieldsAdd entityName = getNodeName(dt.smartscape.service)\n| filter contains(entityName, \"checkout\")\n| fieldsAdd sli=(((total[]-failures[])/total[])*(100))\n| fieldsRemove total, failures"
    LATENCY_250_API = "timeseries total=avg(dt.service.request.response_time), default:0, by: { dt.smartscape.service }\n| fieldsAdd entityName = getNodeName(dt.smartscape.service)\n| filter contains(entityName, \"api\")\n| fieldsAdd high=iCollectArray(if(total[] > 250000, total[]))\n| fieldsAdd low=iCollectArray(if(total[] <= 250000, total[]))\n| fieldsAdd highRespTimes=iCollectArray(if(isNull(high[]), 0, else: 1))\n| fieldsAdd lowRespTimes=iCollectArray(if(isNull(low[]), 0, else: 1))\n| fieldsAdd sli=100*(lowRespTimes[]/(lowRespTimes[]+highRespTimes[]))\n| fieldsRemove total, high, low, highRespTimes, lowRespTimes"

    def test_indicators_match_ts(self):
        from transformers._slo_utils import availability_indicator, latency_indicator

        assert availability_indicator("checkout") == self.AVAILABILITY_CHECKOUT
        assert latency_indicator(250, "api") == self.LATENCY_250_API

    def test_body_and_warning_match_ts(self):
        from transformers._slo_utils import build_platform_slo, default_warning

        assert [default_warning(t) for t in (99.9, 95, 99.5)] == [99.95, 97.5, 99.75]
        assert build_platform_slo(
            name="n", description="d", target=99.5, indicator="i", tags=["t"], external_id="e"
        ) == {
            "name": "n", "description": "d",
            "criteria": [{"target": 99.5, "warning": 99.75, "timeframeFrom": "now-7d", "timeframeTo": "now"}],
            "customSli": {"indicator": "i"}, "tags": ["t"], "externalId": "e",
        }
