"""SLOTransformer — Gen3 Platform SLO output (`/platform/slo/v1/slos`)."""

from transformers.slo_transformer import SLOTransformer


def _nr_slo(valid_where="", good_where="", unit="DAY", count=7, target=99.0):
    return {
        "name": "svc-slo",
        "objectives": [{"target": target, "timeWindow": {"rolling": {"count": count, "unit": unit}}}],
        "events": {
            "validEvents": {"from": "Transaction", "where": valid_where},
            "goodEvents": {"from": "Transaction", "where": good_where},
        },
    }


class TestPlatformSloShape:
    def test_emits_platform_slo_body_not_settings_envelope(self):
        r = SLOTransformer().transform(_nr_slo("appName = 'checkout'", "appName = 'checkout' AND httpResponseCode = '200' status"))
        assert r.success
        assert set(r.slo) >= {"name", "description", "criteria", "customSli", "tags"}
        assert "schemaId" not in r.slo and "metricExpression" not in str(r.slo)
        crit = r.slo["criteria"][0]
        assert crit["timeframeFrom"] == "now-7d" and crit["timeframeTo"] == "now"
        assert crit["warning"] > crit["target"]

    def test_availability_indicator_is_smartscape_dql(self):
        r = SLOTransformer().transform(_nr_slo("appName = 'checkout'", "error IS FALSE"))
        indicator = r.slo["customSli"]["indicator"]
        assert indicator.startswith("timeseries {")
        assert "dt.service.request.failure_count" in indicator
        assert "by: { dt.smartscape.service }" in indicator
        assert 'contains(entityName, "checkout")' in indicator
        assert "dt.entity" not in indicator and "entitySelector" not in indicator

    def test_latency_threshold_parsed_from_good_events_seconds(self):
        r = SLOTransformer().transform(_nr_slo("appName = 'api'", "duration < 0.25"))
        indicator = r.slo["customSli"]["indicator"]
        assert "total[] <= 250000" in indicator  # 250ms in microseconds
        assert any("250ms" in w for w in r.warnings)

    def test_latency_without_threshold_defaults_and_warns(self):
        r = SLOTransformer().transform(_nr_slo("appName = 'api'", "latency is fine"))
        assert "total[] <= 1000000" in r.slo["customSli"]["indicator"]
        assert any("defaulted to 1000ms" in w for w in r.warnings)

    def test_missing_service_warns_and_does_not_filter(self):
        r = SLOTransformer().transform(_nr_slo("", "error IS FALSE"))
        assert "filter contains" not in r.slo["customSli"]["indicator"]
        assert any("Could not determine the service" in w for w in r.warnings)

    def test_week_and_month_windows(self):
        week = SLOTransformer().transform(_nr_slo(unit="WEEK", count=2))
        assert week.slo["criteria"][0]["timeframeFrom"] == "now-2w"
        month = SLOTransformer().transform(_nr_slo(unit="MONTH", count=1))
        assert month.slo["criteria"][0]["timeframeFrom"] == "now-30d"
        assert any("approximated as 30 days" in w for w in month.warnings)

    def test_original_nrql_preserved_in_description(self):
        r = SLOTransformer().transform(_nr_slo("appName = 'x'", "error IS FALSE"))
        assert "Valid: FROM Transaction WHERE appName = 'x'" in r.slo["description"]

    def test_no_objectives_fails(self):
        r = SLOTransformer().transform({"name": "empty"})
        assert not r.success and r.errors
