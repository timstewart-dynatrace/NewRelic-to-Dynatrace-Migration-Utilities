"""Tests for transformers/nrql_mapping_rules.py — NRQL-to-DQL mapping tables."""

import pytest

from transformers.nrql_mapping_rules import AGG_MAP, ATTR_MAP, EVENT_TYPE_MAP


# ─── EVENT_TYPE_MAP ──────────────────────────────────────────────────────────


class TestEventTypeMap:
    """Core NR event types map to correct DT data sources."""

    def test_should_map_transaction_to_spans(self):
        assert EVENT_TYPE_MAP['transaction'] == 'spans'

    def test_should_map_transactionerror_to_spans(self):
        assert EVENT_TYPE_MAP['transactionerror'] == 'spans'

    def test_should_map_span_to_spans(self):
        assert EVENT_TYPE_MAP['span'] == 'spans'

    def test_should_map_log_to_logs(self):
        assert EVENT_TYPE_MAP['log'] == 'logs'

    def test_should_map_metric_to_metric(self):
        assert EVENT_TYPE_MAP['metric'] == 'METRIC'

    def test_should_map_systemsample_to_metric(self):
        assert EVENT_TYPE_MAP['systemsample'] == 'METRIC'

    def test_should_map_processsample_to_metric(self):
        assert EVENT_TYPE_MAP['processsample'] == 'METRIC'

    def test_should_map_k8s_node_sample(self):
        assert EVENT_TYPE_MAP['k8snodesample'] == 'K8S_NODE_METRIC'

    def test_should_map_k8s_container_sample(self):
        assert EVENT_TYPE_MAP['k8scontainersample'] == 'K8S_WORKLOAD_METRIC'

    def test_should_map_k8s_pod_sample(self):
        assert EVENT_TYPE_MAP['k8spodsample'] == 'K8S_POD_METRIC'

    def test_should_map_syntheticcheck(self):
        assert EVENT_TYPE_MAP['syntheticcheck'] == 'dt.synthetic.http.request'

    def test_should_map_pageview_to_bizevents(self):
        assert EVENT_TYPE_MAP['pageview'] == 'bizevents'

    def test_should_map_browserinteraction_to_bizevents(self):
        assert EVENT_TYPE_MAP['browserinteraction'] == 'bizevents'

    def test_should_map_javascripterror_to_bizevents(self):
        assert EVENT_TYPE_MAP['javascripterror'] == 'bizevents'

    def test_should_map_infrastructureevent_to_events(self):
        assert EVENT_TYPE_MAP['infrastructureevent'] == 'events'

    def test_should_map_lambda_to_spans(self):
        assert EVENT_TYPE_MAP['awslambdainvocation'] == 'spans'

    def test_should_map_mobile_events_to_bizevents(self):
        assert EVENT_TYPE_MAP['mobilesession'] == 'bizevents'
        assert EVENT_TYPE_MAP['mobilecrash'] == 'bizevents'

    def test_should_map_custom_events_to_bizevents(self):
        assert EVENT_TYPE_MAP['nrcustomappevent'] == 'bizevents'
        assert EVENT_TYPE_MAP['nrcustomevent'] == 'bizevents'


# ─── AGG_MAP ─────────────────────────────────────────────────────────────────


class TestAggMap:
    """NR aggregation/function names map to DQL equivalents."""

    # Core aggregations
    def test_should_map_count(self):
        assert AGG_MAP['count'] == 'count()'

    def test_should_map_sum(self):
        assert AGG_MAP['sum'] == 'sum'

    def test_should_map_average(self):
        assert AGG_MAP['average'] == 'avg'

    def test_should_map_avg(self):
        assert AGG_MAP['avg'] == 'avg'

    def test_should_map_percentile(self):
        assert AGG_MAP['percentile'] == 'percentile'

    def test_should_map_stddev(self):
        assert AGG_MAP['stddev'] == 'stddev'

    # NR-specific to DQL
    def test_should_map_latest_to_takelast(self):
        assert AGG_MAP['latest'] == 'takeLast'

    def test_should_map_earliest_to_takefirst(self):
        assert AGG_MAP['earliest'] == 'takeFirst'

    def test_should_map_uniquecount_to_countdistinct(self):
        assert AGG_MAP['uniquecount'] == 'countDistinct'

    def test_should_map_uniques_to_collectdistinct(self):
        assert AGG_MAP['uniques'] == 'collectDistinct'

    # String functions
    def test_should_map_length_to_stringlength(self):
        assert AGG_MAP['length'] == 'stringLength'

    def test_should_map_concat(self):
        assert AGG_MAP['concat'] == 'concat'

    # Math functions
    def test_should_map_pow_to_power(self):
        assert AGG_MAP['pow'] == 'power'

    # Time functions
    def test_should_map_hourol_to_gethour(self):
        assert AGG_MAP['hourOf'] == 'getHour'

    def test_should_map_dayofweek(self):
        assert AGG_MAP['dayOfWeek'] == 'getDayOfWeek'

    def test_should_map_weekof_to_getweekofyear(self):
        assert AGG_MAP['weekOf'] == 'getWeekOfYear'

    # New additions from DQL Grail reference
    def test_should_map_countif(self):
        assert AGG_MAP['countif'] == 'countIf'

    def test_should_map_variance(self):
        assert AGG_MAP['variance'] == 'variance'

    def test_should_map_correlation(self):
        assert AGG_MAP['correlation'] == 'correlation'

    def test_should_map_collectarray(self):
        assert AGG_MAP['collectarray'] == 'collectArray'

    def test_should_map_takeany(self):
        assert AGG_MAP['takeany'] == 'takeAny'

    def test_should_map_takemax(self):
        assert AGG_MAP['takemax'] == 'takeMax'

    def test_should_map_countdistinctapprox(self):
        assert AGG_MAP['countdistinctapprox'] == 'countDistinctApprox'

    # String functions from Grail reference
    def test_should_map_indexof(self):
        assert AGG_MAP['indexof'] == 'indexOf'

    def test_should_map_startswith(self):
        assert AGG_MAP['startswith'] == 'startsWith'

    def test_should_map_endswith(self):
        assert AGG_MAP['endswith'] == 'endsWith'

    def test_should_map_contains(self):
        assert AGG_MAP['contains'] == 'contains'

    def test_should_map_matchesvalue(self):
        assert AGG_MAP['matchesvalue'] == 'matchesValue'

    def test_should_map_matchesphrase(self):
        assert AGG_MAP['matchesphrase'] == 'matchesPhrase'

    def test_should_map_trim(self):
        assert AGG_MAP['trim'] == 'trim'

    # Array functions from Grail reference
    def test_should_map_arrayavg(self):
        assert AGG_MAP['arrayavg'] == 'arrayAvg'

    def test_should_map_arraydelta(self):
        assert AGG_MAP['arraydelta'] == 'arrayDelta'

    def test_should_map_arraymovingavg(self):
        assert AGG_MAP['arraymovingavg'] == 'arrayMovingAvg'

    # Boolean/conditional
    def test_should_map_isnull(self):
        assert AGG_MAP['isnull'] == 'isNull'

    def test_should_map_isnotnull(self):
        assert AGG_MAP['isnotnull'] == 'isNotNull'

    def test_should_map_coalesce(self):
        assert AGG_MAP['coalesce'] == 'coalesce'

    # Type conversion
    def test_should_map_tolong(self):
        assert AGG_MAP['tolong'] == 'toLong'

    def test_should_map_todouble(self):
        assert AGG_MAP['todouble'] == 'toDouble'

    def test_should_map_numeric_to_todouble(self):
        assert AGG_MAP['numeric'] == 'toDouble'


# ─── ATTR_MAP ────────────────────────────────────────────────────────────────


class TestAttrMap:
    """NR attribute names map to DT attribute names."""

    def test_should_map_appname_to_service_name(self):
        assert ATTR_MAP['appName'] == 'service.name'

    def test_should_map_host_to_host_name(self):
        assert ATTR_MAP['host'] == 'host.name'

    def test_should_map_duration(self):
        assert 'duration' in ATTR_MAP

    def test_should_have_http_attributes(self):
        # Check common HTTP attributes exist
        http_attrs = [k for k in ATTR_MAP if 'http' in k.lower() or 'Http' in k]
        assert len(http_attrs) > 0

    def test_should_have_k8s_attributes(self):
        k8s_attrs = [k for k in ATTR_MAP if 'k8s' in k.lower()]
        assert len(k8s_attrs) > 0
