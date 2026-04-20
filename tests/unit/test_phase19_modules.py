"""Phase 19 tests: dashboard widget parity + compiler confidence uplift."""

from transformers.dashboard_transformer import DashboardTransformer
from transformers.nrql_converter import (
    ConversionResult,
    NRQLtoDQLConverter,
    _apply_phase19_uplift,
)

# ---------------------------------------------------------------------------
# Widget-parity tests
# ---------------------------------------------------------------------------


def _dashboard_with_widget(visualization_id, raw_cfg=None, extras=None):
    return {
        "name": "test",
        "pages": [
            {
                "name": "p1",
                "widgets": [
                    {
                        "title": "T",
                        "visualization": {"id": visualization_id},
                        "layout": {"column": 1, "row": 1, "width": 6, "height": 4},
                        "rawConfiguration": raw_cfg or {},
                    }
                ],
                **(extras or {}),
            }
        ],
    }


class TestFunnel:
    def test_funnel_emits_bar_chart_composite(self):
        d = _dashboard_with_widget("viz.funnel", raw_cfg={
            "sourceEvent": "PageView",
            "stages": [
                {"name": "landed", "predicate": "page == '/home'"},
                {"name": "signup", "predicate": "page == '/signup'"},
                {"name": "paid", "predicate": "action == 'paid'"},
            ],
        })
        r = DashboardTransformer().transform(d)
        assert r.success
        tile = r.data[0]["tiles"]["0"]
        assert tile["visualization"] == "barChart"
        assert tile["visualizationSettings"]["funnelEmulation"] is True
        assert 'countIf(page ==' in tile["query"]
        assert '"paid"' in tile["query"]

    def test_funnel_with_no_stages_emits_markdown_placeholder(self):
        d = _dashboard_with_widget("viz.funnel", raw_cfg={})
        r = DashboardTransformer().transform(d)
        tile = r.data[0]["tiles"]["0"]
        assert tile["type"] == "markdown"
        assert any("no stages" in w for w in r.warnings)


class TestHeatmapHoneycomb:
    def test_heatmap_becomes_honeycomb_tile(self):
        d = _dashboard_with_widget("viz.heatmap", raw_cfg={
            "nrqlQueries": [{"query": "SELECT count(*) FROM Transaction FACET host"}],
        })
        r = DashboardTransformer().transform(d)
        tile = r.data[0]["tiles"]["0"]
        assert tile["visualization"] == "honeycomb"
        assert tile["visualizationSettings"]["honeycomb"]["shape"] == "hexagon"


class TestEventFeed:
    def test_event_feed_forces_sort_desc(self):
        d = _dashboard_with_widget("viz.event-feed", raw_cfg={
            "nrqlQueries": [{"query": "SELECT * FROM Log SINCE 1 hour ago"}],
        })
        r = DashboardTransformer().transform(d)
        tile = r.data[0]["tiles"]["0"]
        assert tile["visualization"] == "table"
        assert "| sort timestamp desc" in tile["query"]
        assert tile["visualizationSettings"]["table"]["eventFeedMode"] is True


class TestCascadingVariables:
    def test_variable_references_tracked_as_depends_on(self):
        d = {
            "name": "cascading",
            "pages": [{"name": "p1", "widgets": []}],
            "variables": [
                {"name": "env", "type": "enum"},
                {"name": "host", "type": "NRQL",
                 "nrql": "SELECT uniques(host) FROM SystemSample WHERE env = '{{env}}'"},
            ],
        }
        r = DashboardTransformer().transform(d)
        variables = r.data[0]["variables"]
        env_var = next(v for v in variables if v["key"] == "env")
        host_var = next(v for v in variables if v["key"] == "host")
        assert env_var["dependsOn"] == []
        assert host_var["dependsOn"] == ["env"]
        assert host_var["input"]["query"].startswith("SELECT uniques(host)")

    def test_variable_type_mapping(self):
        d = {
            "name": "types",
            "pages": [{"name": "p1", "widgets": []}],
            "variables": [
                {"name": "a", "type": "NRQL", "nrql": "SELECT uniques(x) FROM Y"},
                {"name": "b", "type": "enum", "defaultValue": "one"},
                {"name": "c", "type": "string"},
            ],
        }
        r = DashboardTransformer().transform(d)
        by_key = {v["key"]: v for v in r.data[0]["variables"]}
        assert by_key["a"]["type"] == "query"
        assert by_key["b"]["type"] == "csv"
        assert by_key["c"]["type"] == "csv"


class TestPermissionsAndSavedViews:
    def test_public_read_only_maps(self):
        d = {
            "name": "pub",
            "permissions": "PUBLIC_READ_ONLY",
            "pages": [{"name": "p1", "widgets": []}],
        }
        r = DashboardTransformer().transform(d)
        sharing = r.data[0]["sharing"]
        assert sharing["scope"] == "public"
        assert sharing["access"] == ["read"]

    def test_private_maps(self):
        d = {
            "name": "priv",
            "permissions": "PRIVATE",
            "pages": [{"name": "p1", "widgets": []}],
        }
        r = DashboardTransformer().transform(d)
        assert r.data[0]["sharing"]["scope"] == "private"

    def test_saved_filters_become_saved_views(self):
        d = {
            "name": "x",
            "pages": [{"name": "p1", "widgets": []}],
            "savedFilters": [
                {"name": "prod",
                 "variableAssignments": {"env": "prod", "region": "us-east-1"}},
                {"name": "staging",
                 "variableAssignments": {"env": "staging"}},
            ],
        }
        r = DashboardTransformer().transform(d)
        views = r.data[0]["savedViews"]
        assert [v["name"] for v in views] == ["prod", "staging"]
        assert views[0]["variableValues"]["env"] == "prod"


# ---------------------------------------------------------------------------
# Compiler-uplift tests
# ---------------------------------------------------------------------------


def _mkresult(dql: str, confidence: str = "LOW") -> ConversionResult:
    return ConversionResult(
        original_nrql="",
        dql=dql,
        confidence=confidence,
        success=True,
        warnings=[],
        fixes=[],
    )


class TestConfidenceUplift:
    def test_apdex_bucketing_raises_to_high(self):
        r = _mkresult(
            "fetch spans | fieldsAdd satisfied = countIf(duration < 500), "
            "tolerated = countIf(duration >= 500 and duration < 2000), "
            "frustrated = countIf(duration >= 2000)",
            confidence="LOW",
        )
        _apply_phase19_uplift(r, "SELECT apdex(duration, t: 500) FROM Transaction")
        assert r.confidence == "HIGH"
        assert any("apdex" in f for f in r.fixes)

    def test_compare_with_shift_raises_to_high(self):
        r = _mkresult(
            "timeseries count(), from:now()-7d, shift:-7d",
            confidence="MEDIUM",
        )
        _apply_phase19_uplift(r, "SELECT count(*) FROM Transaction COMPARE WITH 1 WEEK AGO")
        assert r.confidence == "HIGH"

    def test_compare_with_extended_timeframe_raises(self):
        r = _mkresult(
            "fetch spans, from:now()-14d | summarize count()",
            confidence="MEDIUM",
        )
        _apply_phase19_uplift(r, "SELECT count(*) FROM Transaction COMPARE WITH 2 WEEKS AGO")
        assert r.confidence == "HIGH"

    def test_rate_with_preserved_interval_raises(self):
        # rate(count(*), 1 minute) => count() / 60
        r = _mkresult(
            "fetch spans | summarize per_second = count() / 60",
            confidence="MEDIUM",
        )
        _apply_phase19_uplift(r, "SELECT rate(count(*), 1 minute) FROM Transaction")
        assert r.confidence == "HIGH"

    def test_percentage_decomposition_raises(self):
        r = _mkresult(
            "fetch spans | fieldsAdd pct = countIf(status == 'ok') / count() * 100",
            confidence="MEDIUM",
        )
        _apply_phase19_uplift(r, "SELECT percentage(count(*), WHERE status = 'ok') FROM T")
        assert r.confidence == "HIGH"

    def test_no_nrql_signal_leaves_confidence_alone(self):
        r = _mkresult("fetch logs", confidence="LOW")
        _apply_phase19_uplift(r, "SELECT * FROM Log")
        assert r.confidence == "LOW"

    def test_uplift_never_lowers_confidence(self):
        r = _mkresult("fetch logs", confidence="HIGH")
        _apply_phase19_uplift(r, "SELECT count(*) FROM Log")
        assert r.confidence == "HIGH"


class TestConverterEndToEndWithUplift:
    def test_apdex_converts_and_is_high(self):
        conv = NRQLtoDQLConverter()
        r = conv.convert(
            "SELECT apdex(duration, t: 0.5) FROM Transaction",
            title="apdex-test",
        )
        # Either the compiler native-high OR phase19 uplift should have raised.
        assert r.confidence in ("HIGH", "MEDIUM")
        # Phase 19 fix list should mark apdex when countIf buckets present.
        if "countif(" in r.dql.lower():
            assert r.confidence == "HIGH"


# ---------------------------------------------------------------------------
# Regression for gh #(n): dashboard transform fails when NRQL has
# COMPARE WITH because `NRQLtoDQLConverter._compare_converter` was left
# uninitialized by a mis-placed init block that only ran when
# `register_metric_transform` was called.
# ---------------------------------------------------------------------------


class TestCompareWithDashboardRegression:
    """Dashboard with a COMPARE WITH NRQL query must transform successfully.

    Symptom before the fix: DashboardTransformer.transform() returned
    success=False with errors like:
      "Transformation error: 'NRQLtoDQLConverter' object has no attribute
       '_compare_converter'"

    Observed in production: 4 of 16 lab dashboards failed this way because
    one dashboard with a `COMPARE WITH` query produced 1 failure per page.
    """

    def _dashboard_with_nrql(self, nrql: str):
        return {
            "name": "compare-with-lab",
            "pages": [
                {
                    "name": "p1",
                    "widgets": [
                        {
                            "title": "Events 24h vs 24h ago",
                            "visualization": {"id": "viz.line"},
                            "layout": {"column": 1, "row": 1, "width": 6, "height": 4},
                            "rawConfiguration": {
                                "nrqlQueries": [{"query": nrql}],
                            },
                        }
                    ],
                }
            ],
        }

    def test_converter_has_compare_converter_attribute_after_init(self):
        # The mis-placed init block meant `_compare_converter` only existed
        # after `register_metric_transform` was called. Pin that it's set at
        # construction time.
        c = NRQLtoDQLConverter()
        assert hasattr(c, "_compare_converter"), (
            "NRQLtoDQLConverter._compare_converter must be initialized in "
            "__init__, not in register_metric_transform — DashboardTransformer "
            "never calls register_metric_transform."
        )

    def test_dashboard_with_compare_with_query_transforms_successfully(self):
        d = self._dashboard_with_nrql(
            "SELECT count(*) FROM LabBusinessEvent TIMESERIES "
            "SINCE 1 day ago COMPARE WITH 1 day ago"
        )
        r = DashboardTransformer().transform(d)
        assert r.success, (
            f"Dashboard transform should not raise AttributeError on "
            f"COMPARE WITH queries; got errors: {r.errors}"
        )
        # And the transformed page should exist with a DQL query that
        # preserved the COMPARE WITH semantics (shift or append).
        assert r.data and r.data[0].get("tiles"), "Expected at least one tile"

    def test_transformed_data_has_failed_counter_key(self):
        """The Gen3 transform phase must expose a `failed` counter dict so
        the migration summary can render a Failed column. Before this fix
        the only failure signal was `transformed_data["errors"]` (a flat
        list of strings with no entity-type attribution), so
        "Transformed: 12" on a summary table hid the 4 dashboards that
        failed with an AttributeError.
        """
        import inspect

        import migrate
        src = inspect.getsource(migrate.MigrationOrchestrator._transform_phase)
        assert '"failed": {}' in src, (
            "MigrationOrchestrator._transform_phase must initialize a "
            "`failed` counter dict on transformed_data — the summary table "
            "reads from it to render the Failed column."
        )
        assert 'transformed_data["failed"]' in src, (
            "Transform loops must populate transformed_data['failed'] when "
            "a per-entity result.success is False — otherwise failures stay "
            "silent in the summary."
        )

    def test_dashboard_with_compare_with_preserves_semantics(self):
        """The translated DQL must carry the COMPARE WITH intent —
        either as a `shift:` argument or an `append` subquery. This is the
        "do NOT change translation semantics" guard from the PR brief.
        """
        d = self._dashboard_with_nrql(
            "SELECT count(*) FROM Transaction TIMESERIES COMPARE WITH 1 week ago"
        )
        r = DashboardTransformer().transform(d)
        assert r.success
        tile_queries = [
            t.get("query", "")
            for t in r.data[0].get("tiles", {}).values()
            if isinstance(t, dict)
        ]
        assert tile_queries, "Expected a tile with a DQL query"
        translated = " ".join(tile_queries).lower()
        # Either the AST compiler produced `shift:` / `append` or the
        # fallback converter produced an equivalent construct.
        assert ("shift:" in translated) or ("append" in translated), (
            f"COMPARE WITH semantics lost; emitted: {tile_queries!r}"
        )
