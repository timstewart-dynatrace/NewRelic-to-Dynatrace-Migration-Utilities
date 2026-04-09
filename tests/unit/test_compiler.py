"""
NRQL Compiler Test Suite
========================
283 test cases extracted from the original ``run_tests()`` harness in
``nrql_compiler.py``.  Each test class corresponds to a numbered group in
that harness.

Import target is ``nrql_migrator.compiler``; a fallback to the monolith
``nrql_compiler`` is wired in ``conftest.py``.
"""



# Re-use helpers from conftest
from tests.conftest import assert_valid_dql, code_lines


# ---------------------------------------------------------------------------
# Group 1: The 5 Original Bug Fixes
# ---------------------------------------------------------------------------
class TestOriginalBugFixes:
    """Group 1 -- the five bugs that motivated the compiler rewrite."""

    def test_bug1_duplicate_count_dedup(self, compiler):
        result = compiler.compile(
            "SELECT count(*) as total, count(*) as success FROM Transaction "
            "WHERE appName = 'prod-auth-api' AND request.headers.kind = 'server' "
            "AND net.protocol.name = 'http' TIMESERIES"
        )
        assert result.success
        assert "makeTimeseries" in result.dql
        assert "total=count()" in result.dql
        assert "success=count()" in result.dql

    def test_bug2_percentile_naming(self, compiler):
        result = compiler.compile(
            "SELECT percentile(duration, 99) FROM Transaction "
            "WHERE appName = 'prod-auth-api' AND kind = 'client' FACET http.url TIMESERIES"
        )
        assert result.success
        assert "p99=percentile(duration, 99)" in result.dql
        assert "by:" in result.dql

    def test_bug3_triple_count_single(self, compiler):
        result = compiler.compile(
            "SELECT count(*), count(*), count(*) FROM Transaction "
            "WHERE appName = 'prod-user-domain-api' TIMESERIES"
        )
        assert result.success
        code = "\n".join(
            l for l in result.dql.split("\n")
            if "makeTimeseries" in l or "summarize" in l
        )
        assert code.count("count()") <= 1, (
            f"Found {code.count('count()')} count() in aggregation line: {code}"
        )

    def test_bug4_subquery_to_lookup(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction WHERE appName = 'prod-auth-api' "
            "AND http.route = '/auth-api/v1/oauth/token' "
            "AND trace.id IN (FROM Span SELECT trace.id WHERE appName = 'prod-auth-api' "
            "AND grant_type = 'punchthru') FACET httpResponseCode TIMESERIES"
        )
        assert result.success
        code = code_lines(result.dql)
        assert "lookup [fetch spans" in code
        assert "isNotNull(sub.trace.id)" in code
        assert "FROM Span SELECT" not in code

    def test_bug5_as_alias_to_equals_expr(self, compiler):
        result = compiler.compile(
            "SELECT count(*) as Occurrences, max(timestamp) as Latest FROM Log "
            "WHERE service.name = 'prod-user-integration-api' AND level = 'ERROR' "
            "FACET substring(logger, indexOf(logger, '.', -1) + 1) as Logger, "
            "error.message as Message"
        )
        assert result.success
        code = code_lines(result.dql)
        assert "Logger=substring" in code
        assert "Message=error.message" in code
        assert " as Logger" not in code
        assert " as Message" not in code


# ---------------------------------------------------------------------------
# Group 2: Core Conversions
# ---------------------------------------------------------------------------
class TestCoreConversions:
    """Group 2 -- basic NRQL-to-DQL translation patterns."""

    def test_simple_count(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction WHERE appName = 'my-api' TIMESERIES"
        )
        assert result.success
        assert "fetch spans" in result.dql
        assert 'service.name == "my-api"' in result.dql
        assert "makeTimeseries count()" in result.dql

    def test_average_with_facet(self, compiler):
        result = compiler.compile(
            "SELECT average(duration) FROM Transaction WHERE appName = 'api' FACET name TIMESERIES"
        )
        assert result.success
        assert "avg(duration)" in result.dql
        assert "by: {span.name}" in result.dql

    def test_non_timeseries_aggregation(self, compiler):
        result = compiler.compile(
            "SELECT count(*), average(duration) FROM Transaction WHERE appName = 'api'"
        )
        assert result.success
        assert "summarize" in result.dql
        assert "makeTimeseries" not in result.dql

    def test_log_query(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Log WHERE level = 'ERROR' AND message LIKE '%timeout%'"
        )
        assert result.success
        assert "fetch logs" in result.dql
        assert 'loglevel == "ERROR"' in result.dql
        assert 'contains(content, "timeout")' in result.dql

    def test_multiple_aggregations(self, compiler):
        result = compiler.compile(
            "SELECT count(*), average(duration), max(duration) FROM Transaction TIMESERIES"
        )
        assert result.success
        assert "makeTimeseries {count(), avg(duration), max(duration)}" in result.dql

    def test_unique_count_to_count_distinct_exact(self, compiler):
        result = compiler.compile(
            "SELECT uniqueCount(host) FROM Transaction WHERE appName = 'api'"
        )
        assert result.success
        assert "countDistinctExact(host.name)" in result.dql

    def test_field_mapping_http_response_code(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction WHERE httpResponseCode >= 500 TIMESERIES"
        )
        assert result.success
        assert "http.response.status_code >= 500" in result.dql


# ---------------------------------------------------------------------------
# Group 3: NR-Specific Functions
# ---------------------------------------------------------------------------
class TestNRFunctions:
    """Group 3 -- New Relic function translations."""

    def test_percentage_to_count_if(self, compiler):
        result = compiler.compile(
            "SELECT percentage(count(*), WHERE duration > 1) FROM Transaction TIMESERIES"
        )
        assert result.success
        assert "countIf(duration > 1ms)" in result.dql
        assert "fieldsAdd" in result.dql
        assert "toDouble" in result.dql

    def test_filter_count_to_count_if(self, compiler):
        result = compiler.compile(
            "SELECT filter(count(*), WHERE httpResponseCode >= 500) FROM Transaction TIMESERIES"
        )
        assert result.success
        assert "countIf(http.response.status_code >= 500)" in result.dql

    def test_filter_average_to_avg_if(self, compiler):
        result = compiler.compile(
            "SELECT filter(average(duration), WHERE error IS NOT NULL) FROM Transaction TIMESERIES"
        )
        assert result.success
        assert "avgIf(duration, isNotNull(error))" in result.dql

    def test_rate_to_count_with_warning(self, compiler):
        result = compiler.compile(
            "SELECT rate(count(*), 1 minute) FROM Transaction TIMESERIES"
        )
        assert result.success
        assert "count()" in result.dql
        assert result.warnings and any("rate()" in w for w in result.warnings)

    def test_multi_percentile_expansion(self, compiler):
        result = compiler.compile(
            "SELECT percentile(duration, 50, 90, 95, 99) FROM Transaction TIMESERIES"
        )
        assert result.success
        assert "p50=percentile(duration, 50)" in result.dql
        assert "p99=percentile(duration, 99)" in result.dql

    def test_median_to_percentile_50(self, compiler):
        result = compiler.compile(
            "SELECT median(duration) FROM Transaction TIMESERIES"
        )
        assert result.success
        assert "percentile(duration, 50)" in result.dql


# ---------------------------------------------------------------------------
# Group 4: Conditions
# ---------------------------------------------------------------------------
class TestConditions:
    """Group 4 -- WHERE clause operator translations."""

    def test_equals_to_double_equals(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction WHERE appName = 'x'"
        )
        assert result.success
        assert 'service.name == "x"' in result.dql

    def test_is_null_is_not_null(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction WHERE error IS NOT NULL AND host IS NULL"
        )
        assert result.success
        assert "isNotNull(error)" in result.dql
        assert "isNull(host.name)" in result.dql

    def test_in_list(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction WHERE appName IN ('a', 'b', 'c')"
        )
        assert result.success
        assert 'in(service.name, {"a", "b", "c"})' in result.dql

    def test_not_in(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction WHERE appName NOT IN ('x')"
        )
        assert result.success
        assert 'not in(service.name, {"x"})' in result.dql

    def test_like_contains(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction WHERE name LIKE '%payment%'"
        )
        assert result.success
        assert 'contains(span.name, "payment")' in result.dql

    def test_like_starts_with(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction WHERE httpResponseCode LIKE '2%'"
        )
        assert result.success
        assert 'startsWith(toString(http.response.status_code), "2")' in result.dql

    def test_complex_and_or(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction WHERE (appName = 'a' OR appName = 'b') AND error IS NOT NULL"
        )
        assert result.success
        assert 'service.name == "a" or service.name == "b"' in result.dql
        assert "isNotNull(error)" in result.dql


# ---------------------------------------------------------------------------
# Group 5: Arithmetic Expressions
# ---------------------------------------------------------------------------
class TestArithmetic:
    """Group 5 -- arithmetic expression handling."""

    def test_error_percentage_calculation(self, compiler):
        result = compiler.compile(
            "SELECT filter(count(*), WHERE httpResponseCode >= 500) / "
            "filter(count(*), WHERE httpResponseCode IS NOT NULL) * 100 "
            "FROM Transaction TIMESERIES"
        )
        assert result.success
        assert "countIf(http.response.status_code >= 500)" in result.dql
        assert "countIf(isNotNull(http.response.status_code))" in result.dql
        assert "* 100" in result.dql

    def test_unary_minus(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction WHERE duration > -1"
        )
        assert result.success
        assert "duration > -1" in result.dql


# ---------------------------------------------------------------------------
# Group 6: Edge Cases
# ---------------------------------------------------------------------------
class TestEdgeCases:
    """Group 6 -- edge cases in NRQL syntax."""

    def test_limit_clause(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction FACET appName LIMIT 20"
        )
        assert result.success
        assert "limit 20" in result.dql

    def test_order_by(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction FACET appName ORDER BY count(*) DESC"
        )
        assert result.success
        assert "sort count() desc" in result.dql

    def test_since_until_captured(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction SINCE 1 hour ago UNTIL 5 minutes ago TIMESERIES"
        )
        assert result.success
        assert "makeTimeseries count()" in result.dql
        assert result.ast and result.ast.since_raw == "1 hour ago"

    def test_backtick_quoted_field(self, compiler):
        result = compiler.compile(
            "SELECT average(`k8s.container.cpuUsedCores`) FROM Metric WHERE appName = 'api'"
        )
        assert result.success
        assert "avg(k8s.container.cpuUsedCores)" in result.dql

    def test_string_with_escaped_quotes(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction WHERE name = 'it''s a test'"
        )
        assert result.success
        assert "it's a test" in result.dql

    def test_multiple_facet_items_with_aliases(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction FACET appName as Service, host as Host"
        )
        assert result.success
        assert "Service=service.name" in result.dql
        assert "Host=host.name" in result.dql

    def test_empty_count_star(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Log")
        assert result.success
        assert "fetch logs" in result.dql
        assert "count()" in result.dql

    def test_boolean_comparison(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction WHERE error = true TIMESERIES"
        )
        assert result.success
        assert "error == true" in result.dql


# ---------------------------------------------------------------------------
# Group 7: Real-World Complex Queries
# ---------------------------------------------------------------------------
class TestRealWorldQueries:
    """Group 7 -- complex production queries."""

    def test_auth_api_p99_latency_by_url_path(self, compiler):
        result = compiler.compile(
            "SELECT percentile(duration, 99) FROM Transaction "
            "WHERE appName = 'prod-auth-api' AND span.kind = 'client' "
            "AND net.protocol.name = 'http' "
            "AND NOT name LIKE '%userpassword%' AND name LIKE '%panamax%' "
            "FACET http.url TIMESERIES"
        )
        assert result.success
        assert "p99=percentile(duration, 99)" in result.dql
        code = code_lines(result.dql)
        assert 'not(contains(span.name, "userpassword"))' in code
        assert 'contains(span.name, "panamax")' in code

    def test_user_domain_server_count(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction WHERE appName = 'prod-user-domain-api' "
            "AND span.kind = 'server' TIMESERIES"
        )
        assert result.success
        assert "makeTimeseries count()" in result.dql
        assert 'span.kind == "server"' in result.dql

    def test_integration_api_error_log_analysis(self, compiler):
        result = compiler.compile(
            "SELECT count(*) as Occurrences, max(timestamp) as Latest FROM Log "
            "WHERE service.name = 'prod-user-integration-api' AND level = 'ERROR' "
            "FACET substring(logger, indexOf(logger, '.', -1) + 1) as Logger, "
            "error.message as Message"
        )
        assert result.success
        assert "Occurrences=count()" in result.dql
        assert "Latest=max(timestamp)" in result.dql
        code = code_lines(result.dql)
        assert "Logger=substring" in code
        assert "Message=error.message" in code


# ---------------------------------------------------------------------------
# Group 8: Metric Queries (timeseries command)
# ---------------------------------------------------------------------------
class TestMetricQueries:
    """Group 8 -- SystemSample/Metric queries using timeseries."""

    def test_system_sample_to_timeseries(self, compiler):
        result = compiler.compile(
            "SELECT average(cpuPercent) FROM SystemSample WHERE hostname = 'web-1' TIMESERIES"
        )
        assert result.success
        assert "timeseries avg(" in result.dql
        code = code_lines(result.dql)
        assert "fetch" not in code
        assert "makeTimeseries" not in code

    def test_system_sample_memory(self, compiler):
        result = compiler.compile(
            "SELECT average(memoryUsedPercent) FROM SystemSample FACET hostname TIMESERIES"
        )
        assert result.success
        assert "timeseries avg(" in result.dql
        assert "by: {host.name}" in result.dql

    def test_metric_query_passthrough(self, compiler):
        result = compiler.compile(
            "SELECT sum(cpuPercent) FROM Metric WHERE appName = 'api' TIMESERIES"
        )
        assert result.success
        assert "timeseries sum(" in result.dql

    def test_latest_on_metric_to_avg(self, compiler):
        result = compiler.compile(
            "SELECT latest(cpuPercent) FROM SystemSample FACET hostname"
        )
        assert result.success
        assert "timeseries avg(" in result.dql


# ---------------------------------------------------------------------------
# Group 9: K8s Queries
# ---------------------------------------------------------------------------
class TestK8sQueries:
    """Group 9 -- Kubernetes sample queries."""

    def test_k8s_node_sample_basic(self, compiler):
        result = compiler.compile(
            "SELECT latest(memoryUsedBytes) FROM K8sNodeSample FACET nodeName TIMESERIES"
        )
        assert result.success
        assert "timeseries avg(" in result.dql
        assert "by: {k8s.node.name}" in result.dql

    def test_k8s_container_sample(self, compiler):
        result = compiler.compile(
            "SELECT average(cpuUsedCores) FROM K8sContainerSample FACET containerName TIMESERIES"
        )
        assert result.success
        assert "timeseries" in result.dql
        assert "by: {k8s.container.name}" in result.dql

    def test_k8s_metric_filter_stripping(self, compiler):
        result = compiler.compile(
            "SELECT latest(allocatableMemoryUtilization) FROM K8sNodeSample "
            "WHERE allocatableMemoryUtilization < 90 AND clusterName = 'prod' FACET nodeName"
        )
        assert result.success
        assert "k8s.cluster.name" in result.dql
        code = code_lines(result.dql)
        assert "allocatableMemoryUtilization <" not in code

    def test_k8s_computed_metric(self, compiler):
        result = compiler.compile(
            "SELECT (latest(fsInodesUsed)/latest(fsInodes))*100 as fsInodeCapacityUtilization "
            "FROM K8sNodeSample WHERE clusterName = 'prod' FACET nodeName TIMESERIES"
        )
        assert result.success
        assert "timeseries" in result.dql
        assert "fieldsAdd" in result.dql
        assert "fsInodeCapacityUtilization" in result.dql
        assert "toDouble" in result.dql
        code = code_lines(result.dql)
        assert "fetch" not in code
        assert "makeTimeseries" not in code

    def test_k8s_computed_bare_aggs_parenthesized_where_arithmetic(self, compiler):
        result = compiler.compile(
            "SELECT (latest(fsInodesUsed)/latest(fsInodes))*100 as fsInodeCapacityUtilization, "
            "latest(fsInodesUsed), latest(fsInodes) FROM K8sNodeSample "
            "WHERE (fsInodesUsed/fsInodes)*100 < 90 AND clusterName LIKE 'usf-moxe%' "
            "FACET nodeName TIMESERIES"
        )
        assert result.success
        assert "timeseries" in result.dql
        assert "fieldsAdd" in result.dql
        assert "fsInodeCapacityUtilization" in result.dql
        assert "toDouble" in result.dql


# ---------------------------------------------------------------------------
# Group 10: Events & Special Types
# ---------------------------------------------------------------------------
class TestEventsQueries:
    """Group 10 -- InfrastructureEvent, histogram, PageView."""

    def test_infrastructure_event_to_fetch_events(self, compiler):
        result = compiler.compile(
            "SELECT summary, category FROM InfrastructureEvent WHERE category = 'kubernetes' LIMIT 50"
        )
        assert result.success
        assert "fetch events" in result.dql
        assert "filter" in result.dql
        assert "limit 50" in result.dql

    def test_histogram_to_count_with_bin(self, compiler):
        result = compiler.compile(
            "SELECT histogram(duration) FROM Transaction WHERE appName = 'api'"
        )
        assert result.success
        assert "fetch spans" in result.dql
        assert "count()" in result.dql
        assert "bin(duration" in result.dql
        assert any("histogram" in w for w in result.warnings)

    def test_page_view_browser_query(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM PageView WHERE pageUrl LIKE '%checkout%' FACET userAgentName"
        )
        assert result.success
        assert "fetch bizevents" in result.dql
        assert "page.url" in result.dql
        assert "browser.name" in result.dql


# ---------------------------------------------------------------------------
# Group 11: Structural Completeness
# ---------------------------------------------------------------------------
class TestStructuralCompleteness:
    """Group 11 -- COMPARE WITH, EXTRAPOLATE, CTE, apdex, FACET CASES."""

    def test_compare_with_warning(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction COMPARE WITH 1 week ago TIMESERIES"
        )
        assert result.success
        assert "shift:" not in result.dql
        assert any("COMPARE WITH" in w for w in result.warnings)

    def test_extrapolate_full_fidelity_comment(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction EXTRAPOLATE"
        )
        assert result.success
        assert "full fidelity" in result.dql
        assert any("EXTRAPOLATE" in w for w in result.warnings)

    def test_with_as_cte_inlined(self, compiler):
        result = compiler.compile(
            "WITH errors AS (SELECT count(*) FROM TransactionError WHERE appName = 'api') "
            "SELECT count(*) FROM errors WHERE error.class = 'TimeoutError'"
        )
        assert result.success
        assert "fetch spans" in result.dql
        assert 'service.name == "api"' in result.dql
        assert "error.class" in result.dql

    def test_apdex_calculated_approximation(self, compiler):
        result = compiler.compile(
            "SELECT apdex(0.5) FROM Transaction WHERE appName = 'api'"
        )
        assert result.success
        assert "countIf" in result.dql
        assert "duration" in result.dql
        assert any("apdex" in w for w in result.warnings)

    def test_facet_cases(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction FACET CASES(WHERE duration < 0.5 AS 'Fast', "
            "WHERE duration < 2 AS 'Normal', WHERE duration >= 2 AS 'Slow')"
        )
        assert result.success
        assert "fieldsAdd" in result.dql
        assert "if(" in result.dql
        assert '"Fast"' in result.dql
        assert "by: {_category_" in result.dql


# ---------------------------------------------------------------------------
# Group 12: Real-World Parser Gaps
# ---------------------------------------------------------------------------
class TestParserGaps:
    """Group 12 -- parser gaps discovered from real-world queries."""

    def test_from_first_syntax_from_span_select(self, compiler):
        result = compiler.compile(
            "FROM Span SELECT count(*) WHERE entity.name = 'my-api' FACET http.route TIMESERIES"
        )
        assert result.success
        assert "fetch spans" in result.dql
        assert "makeTimeseries" in result.dql
        assert "dt.entity.name" in result.dql

    def test_from_log_select(self, compiler):
        result = compiler.compile(
            "FROM Log SELECT count(*) WHERE container_name = 'nginx' FACET level"
        )
        assert result.success
        assert "fetch logs" in result.dql
        assert "container_name" in result.dql

    def test_from_metric_select(self, compiler):
        result = compiler.compile(
            "FROM Metric SELECT average(apm.service.transaction.duration) WHERE appName = 'api'"
        )
        assert result.success
        assert "timeseries" in result.dql
        assert "service.name" in result.dql

    def test_sql_comments_stripped(self, compiler):
        result = compiler.compile(
            "SELECT average(duration) -- this is a comment\nFROM Transaction WHERE appName = 'api'"
        )
        assert result.success
        assert "fetch spans" in result.dql
        assert "avg(duration)" in result.dql

    def test_semicolons_ignored(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction WHERE appName = 'api';"
        )
        assert result.success
        assert "fetch spans" in result.dql
        assert "count()" in result.dql

    def test_scientific_notation_10e8(self, compiler):
        result = compiler.compile(
            "SELECT rate((bytecountestimate() / 10e8) * .30, 1 month) FROM Span"
        )
        assert result.success

    def test_is_true_is_false(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM TransactionError WHERE error IS NOT FALSE AND appId IN ('123')"
        )
        assert result.success
        assert "error != false" in result.dql
        assert "appId" in result.dql

    def test_or_coalesce_in_function_args(self, compiler):
        result = compiler.compile(
            "SELECT average(memoryFreePercent OR memoryFreeBytes/memoryTotalBytes*100) "
            "FROM SystemSample TIMESERIES FACET hostname"
        )
        assert result.success
        assert "timeseries" in result.dql

    def test_from_span_select_with_aliases(self, compiler):
        result = compiler.compile(
            "FROM Span SELECT count(*) AS 'Total', average(duration.ms) AS 'Avg' "
            "WHERE entity.name = 'api' COMPARE WITH 1 week ago"
        )
        assert result.success
        assert "fetch spans" in result.dql
        assert "Total=count()" in result.dql
        assert any("COMPARE WITH" in w for w in result.warnings)

    def test_cases_in_mid_facet_position(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Span WHERE http.route = '/api' FACET http.statusCode, "
            "CASES(WHERE http.statusCode >= 200 AND http.statusCode < 400 AS 'Success', "
            "WHERE http.statusCode >= 400 AS 'Error') COMPARE WITH 1 week ago"
        )
        assert result.success
        assert "fetch spans" in result.dql
        assert "if(" in result.dql
        assert '"Success"' in result.dql

    def test_with_inline_from_first_aparse(self, compiler):
        result = compiler.compile(
            "FROM Span WITH aparse(host.name, 'search-cron-*-job%') AS (job) "
            "SELECT average(duration.ms) WHERE service.name = 'api'"
        )
        assert result.success
        assert "fetch spans" in result.dql
        assert "avg(duration)" in result.dql

    def test_with_inline_select_first(self, compiler):
        result = compiler.compile(
            "SELECT average(k8s.container.cpuUsedCores) FROM Metric "
            "WITH aparse(k8s.jobName, 'search-cron-*') AS (job) WHERE containerName = 'api'"
        )
        assert result.success
        assert "timeseries" in result.dql

    def test_template_variables(self, compiler):
        result = compiler.compile(
            "SELECT average(k8s.container.cpuUsedCores) FROM Metric "
            "WHERE k8s.containerName = {{api}} AND k8s.clusterName = 'prod'"
        )
        assert result.success
        assert "timeseries" in result.dql

    def test_bracket_access_field(self, compiler):
        result = compiler.compile(
            "SELECT sum(apm.service.error.count['count']) / count(apm.service.transaction.duration) "
            "FROM Metric WHERE appName = 'api'"
        )
        assert result.success
        assert "timeseries" in result.dql

    def test_if_condition_in_select(self, compiler):
        result = compiler.compile(
            "FROM Log SELECT trace.id, level, if(level='ERROR', context, '') as error "
            "WHERE service.name = 'api' LIMIT 20"
        )
        assert result.success
        assert "fetch logs" in result.dql
        assert "if(" in result.dql
        assert "limit 20" in result.dql


# ---------------------------------------------------------------------------
# Group 13: High Priority Gaps (SLIDE BY, derivative, jparse, FACET ORDER BY)
# ---------------------------------------------------------------------------
class TestHighPriorityGaps:
    """Group 13 -- high-priority gaps: SLIDE BY, derivative, jparse, FACET ORDER BY."""

    def test_slide_by_clause(self, compiler):
        result = compiler.compile(
            "SELECT average(duration) FROM Transaction TIMESERIES 5 minutes SLIDE BY 1 minute"
        )
        assert result.success
        assert "rolling(" in result.dql
        assert "interval: 1m" in result.dql

    def test_slide_by_auto(self, compiler):
        result = compiler.compile(
            "SELECT average(duration) FROM Transaction TIMESERIES 5 minutes SLIDE BY AUTO"
        )
        assert result.success
        assert "rolling(" in result.dql

    def test_slide_by_max(self, compiler):
        result = compiler.compile(
            "SELECT average(duration) FROM Transaction TIMESERIES 5 minutes SLIDE BY MAX"
        )
        assert result.success
        assert "rolling(" in result.dql

    def test_timeseries_max_no_slide_by(self, compiler):
        result = compiler.compile(
            "SELECT average(duration) FROM Transaction TIMESERIES MAX"
        )
        assert result.success

    def test_derivative_function(self, compiler):
        result = compiler.compile(
            "SELECT derivative(count(*), 1 minute) FROM Transaction TIMESERIES"
        )
        assert result.success
        assert "delta(" in result.dql

    def test_derivative_simple(self, compiler):
        result = compiler.compile(
            "FROM Metric SELECT derivative(apm.service.transaction.duration) TIMESERIES"
        )
        assert result.success
        assert "delta(" in result.dql

    def test_jparse_with_path(self, compiler):
        result = compiler.compile(
            "FROM Log SELECT jparse(message, '$.error.code') WHERE service.name = 'api'"
        )
        assert result.success
        assert "[`error.code`]" in result.dql

    def test_jparse_simple(self, compiler):
        result = compiler.compile(
            "FROM Log SELECT jparse(message) WHERE level = 'ERROR'"
        )
        assert result.success

    def test_facet_order_by_aggregate(self, compiler):
        result = compiler.compile(
            "FROM Transaction SELECT average(duration) TIMESERIES FACET appName ORDER BY max(responseSize)"
        )
        assert result.success
        assert "FACET ORDER BY" in result.dql

    def test_facet_order_by_preserves_sort(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction FACET appName ORDER BY count(*) DESC"
        )
        assert result.success
        assert "sort count() desc" in result.dql
        assert "FACET ORDER BY" in result.dql


# ---------------------------------------------------------------------------
# Group 14: Medium Priority Gaps (JOIN, clamp, buckets, cdf, etc.)
# ---------------------------------------------------------------------------
class TestMediumPriorityGaps:
    """Group 14 (original numbering: phase 2 medium gaps) -- clamp, cdf, JOIN, etc."""

    def test_clamp_max(self, compiler):
        result = compiler.compile(
            "SELECT clamp_max(average(duration), 10) FROM Transaction"
        )
        assert result.success
        assert "if(avg(duration) > 10, 10, else:avg(duration))" in result.dql

    def test_clamp_min(self, compiler):
        result = compiler.compile(
            "SELECT clamp_min(average(duration), 1) FROM Transaction"
        )
        assert result.success
        assert "if(avg(duration) < 1, 1, else:avg(duration))" in result.dql

    def test_clamp_max_and_min_combined(self, compiler):
        result = compiler.compile(
            "SELECT clamp_max(average(duration), 10), clamp_min(average(duration), 1) FROM Transaction"
        )
        assert result.success
        assert "if(" in result.dql
        assert "> 10" in result.dql
        assert "< 1" in result.dql

    def test_cdf_percentage(self, compiler):
        result = compiler.compile(
            "FROM PageView SELECT cdfPercentage(firstPaint, 0.5, 1.0)"
        )
        assert result.success
        assert "countIf(" in result.dql
        assert "<= 0.5" in result.dql
        assert "<= 1.0" in result.dql

    def test_bucket_percentile_specific(self, compiler):
        result = compiler.compile(
            "SELECT bucketPercentile(duration_bucket, 50, 75, 90) FROM Metric"
        )
        assert result.success
        assert "percentile(" in result.dql

    def test_bucket_percentile_default(self, compiler):
        result = compiler.compile(
            "SELECT bucketPercentile(duration_bucket) FROM Metric"
        )
        assert result.success
        assert "percentile(duration_bucket" in result.dql

    def test_get_field(self, compiler):
        result = compiler.compile(
            "SELECT getField(percentile(duration, 95), '95.0') FROM Transaction"
        )
        assert result.success
        assert "[`95.0`]" in result.dql

    def test_inner_join_with_subquery(self, compiler):
        result = compiler.compile(
            "FROM PageView JOIN (FROM PageAction SELECT count(*) FACET session, currentUrl) ON session "
            "SELECT count(*) FACET browserTransactionName"
        )
        assert result.success
        assert "lookup" in result.dql

    def test_left_join_with_subquery(self, compiler):
        result = compiler.compile(
            "FROM PageView LEFT JOIN (FROM PageAction SELECT count(*) FACET session) ON session "
            "SELECT count(*) FACET browserTransactionName"
        )
        assert result.success
        assert "lookup" in result.dql
        assert "LEFT" in result.dql

    def test_join_with_different_keys(self, compiler):
        result = compiler.compile(
            "FROM Transaction JOIN (FROM Metric SELECT average(duration) FACET appName) ON name = appName "
            "SELECT average(duration)"
        )
        assert result.success
        assert "lookup" in result.dql

    # -- Low priority gaps (originally Group 12 phase 3) --

    def test_with_timezone(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction SINCE Monday UNTIL Tuesday WITH TIMEZONE 'America/New_York'"
        )
        assert result.success
        assert "America/New_York" in result.dql

    def test_predict_clause(self, compiler):
        result = compiler.compile(
            "FROM Transaction SELECT count(*) WHERE error IS TRUE TIMESERIES PREDICT"
        )
        assert result.success
        assert "PREDICT" in result.dql
        assert "Davis AI" in result.dql

    def test_show_event_types(self, compiler):
        result = compiler.compile("SHOW EVENT TYPES SINCE 1 day ago")
        assert result.success
        assert "SHOW EVENT TYPES" in result.dql
        assert "Schema browser" in result.dql

    def test_ln_to_log(self, compiler):
        result = compiler.compile(
            "SELECT ln(duration) FROM Transaction LIMIT 10"
        )
        assert result.success
        assert "log(duration)" in result.dql

    def test_cardinality(self, compiler):
        result = compiler.compile(
            "SELECT cardinality(appName) FROM Transaction"
        )
        assert result.success
        assert "countDistinct(" in result.dql

    def test_predict_linear(self, compiler):
        result = compiler.compile(
            "SELECT predictLinear(cpuPercent, 3600) FROM SystemSample"
        )
        assert result.success

    def test_blob_passthrough(self, compiler):
        result = compiler.compile("SELECT blob(message) FROM Log LIMIT 5")
        assert result.success

    def test_map_keys_passthrough(self, compiler):
        result = compiler.compile("SELECT mapKeys(tags) FROM Transaction")
        assert result.success

    def test_map_values_passthrough(self, compiler):
        result = compiler.compile("SELECT mapValues(tags) FROM Transaction")
        assert result.success

    def test_keyset_metadata(self, compiler):
        result = compiler.compile("SELECT keyset() FROM Transaction")
        assert result.success
        assert "Schema browser" in result.dql

    def test_event_type_metadata(self, compiler):
        result = compiler.compile("SELECT eventType() FROM Transaction")
        assert result.success
        assert "Schema browser" in result.dql

    def test_bytecountestimate_ingest(self, compiler):
        result = compiler.compile(
            "SELECT bytecountestimate() FROM Transaction SINCE 1 day ago"
        )
        assert result.success
        assert "bytecountestimate" in result.dql

    def test_aggregationendtime(self, compiler):
        result = compiler.compile(
            "SELECT aggregationendtime(), count(*) FROM Transaction TIMESERIES 1 hour"
        )
        assert result.success
        assert "end(" in result.dql

    def test_buckets_to_bin(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction FACET buckets(duration, 10, 5)"
        )
        assert result.success
        assert "bin(" in result.dql

    # -- Combinations & edge cases (originally Group 13) --

    def test_slide_by_plus_facet_order_by_combined(self, compiler):
        result = compiler.compile(
            "SELECT average(duration) FROM Transaction "
            "FACET appName ORDER BY max(duration) "
            "TIMESERIES 5 minutes SLIDE BY 1 minute"
        )
        assert result.success
        assert "SLIDE BY" in result.dql
        assert "FACET ORDER BY" in result.dql

    def test_derivative_timeseries_facet(self, compiler):
        result = compiler.compile(
            "SELECT derivative(count(*), 1 minute) FROM Transaction TIMESERIES FACET appName"
        )
        assert result.success
        assert "delta(" in result.dql

    def test_clamp_plus_jparse_in_same_query(self, compiler):
        result = compiler.compile(
            "FROM Log SELECT clamp_max(numeric(jparse(message, '$.latency')), 1000) WHERE level = 'INFO'"
        )
        assert result.success
        assert "if(" in result.dql
        assert "1000" in result.dql

    def test_with_timezone_plus_compare_with(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction SINCE 1 day ago COMPARE WITH 1 week ago "
            "WITH TIMEZONE 'America/Chicago'"
        )
        assert result.success
        assert "America/Chicago" in result.dql
        assert "shift:" not in result.dql

    def test_predict_plus_timeseries(self, compiler):
        result = compiler.compile(
            "SELECT average(duration) FROM Transaction TIMESERIES 1 hour PREDICT"
        )
        assert result.success
        assert "Davis AI" in result.dql

    # -- Subquery / Lookup tests --

    def test_in_select_subquery_to_lookup(self, compiler):
        result = compiler.compile(
            "FROM Span SELECT duration, db.statement WHERE service.name = 'my-api' "
            "AND parentId in (SELECT id from Span where service.name = 'my-api' "
            "and name = 'list-cmd-01' limit max) limit max"
        )
        assert result.success
        assert "lookup [fetch spans" in result.dql
        assert "sourceField:span.parent_id" in result.dql
        assert "lookupField:span.id" in result.dql
        assert "isNotNull(sub.span.id)" in result.dql

    def test_in_from_subquery_to_lookup(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Span WHERE service.name = 'order-api' "
            "AND trace.id IN (FROM Span SELECT trace.id WHERE appName = 'auth-api' "
            "AND name = 'authenticate') FACET name TIMESERIES"
        )
        assert result.success
        assert "lookup [fetch spans" in result.dql
        assert "sourceField:trace.id" in result.dql
        assert "lookupField:trace.id" in result.dql
        assert "isNotNull(sub.trace.id)" in result.dql

    def test_not_in_subquery_to_lookup_is_null(self, compiler):
        result = compiler.compile(
            "FROM Span SELECT count(*) WHERE name NOT IN (SELECT name FROM Span WHERE error.class IS NOT NULL)"
        )
        assert result.success
        assert "lookup [fetch spans" in result.dql
        assert "isNull(sub.span.name)" in result.dql

    def test_duration_ms_div_1000_simplification(self, compiler):
        result = compiler.compile(
            "SELECT (duration.ms)/1000 as seconds FROM Span WHERE name = 'mongodb.find'"
        )
        assert result.success
        assert "duration" in result.dql
        assert "/ 1000" not in result.dql


# ---------------------------------------------------------------------------
# Group 14: 100% Conversion Guarantee -- Structural Validity
# ---------------------------------------------------------------------------


# -- 14a: Every aggregation function --
class TestG14Aggregations:
    """Group 14a -- every aggregation function produces valid DQL."""

    def test_count_star(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction")
        assert_valid_dql(result)
        assert "count()" in code_lines(result.dql)

    def test_sum_field(self, compiler):
        result = compiler.compile("SELECT sum(duration) FROM Transaction")
        assert_valid_dql(result)
        assert "sum(duration)" in code_lines(result.dql)

    def test_average_field(self, compiler):
        result = compiler.compile("SELECT average(duration) FROM Transaction")
        assert_valid_dql(result)
        assert "avg(duration)" in code_lines(result.dql)

    def test_max_field(self, compiler):
        result = compiler.compile("SELECT max(duration) FROM Transaction")
        assert_valid_dql(result)
        assert "max(duration)" in code_lines(result.dql)

    def test_min_field(self, compiler):
        result = compiler.compile("SELECT min(duration) FROM Transaction")
        assert_valid_dql(result)
        assert "min(duration)" in code_lines(result.dql)

    def test_percentile_f_95(self, compiler):
        result = compiler.compile("SELECT percentile(duration, 95) FROM Transaction")
        assert_valid_dql(result)
        assert "percentile(duration, 95)" in code_lines(result.dql)

    def test_percentile_multi(self, compiler):
        result = compiler.compile("SELECT percentile(duration, 50, 90, 95, 99) FROM Transaction")
        assert_valid_dql(result)
        code = code_lines(result.dql)
        assert "p50=" in code
        assert "p99=" in code

    def test_unique_count_to_count_distinct_exact(self, compiler):
        result = compiler.compile("SELECT uniqueCount(appName) FROM Transaction")
        assert_valid_dql(result)
        assert "countDistinctExact(service.name)" in code_lines(result.dql)

    def test_uniques_to_collect_distinct(self, compiler):
        result = compiler.compile("SELECT uniques(appName) FROM Transaction")
        assert_valid_dql(result)
        assert "collectDistinct(service.name)" in code_lines(result.dql)

    def test_latest_to_take_last(self, compiler):
        result = compiler.compile("SELECT latest(duration) FROM Transaction")
        assert_valid_dql(result)
        assert "takeLast(duration)" in code_lines(result.dql)

    def test_earliest_to_take_first(self, compiler):
        result = compiler.compile("SELECT earliest(timestamp) FROM Transaction")
        assert_valid_dql(result)
        assert "takeFirst(timestamp)" in code_lines(result.dql)

    def test_median_to_percentile_50(self, compiler):
        result = compiler.compile("SELECT median(duration) FROM Transaction")
        assert_valid_dql(result)
        assert "percentile(duration, 50)" in code_lines(result.dql)

    def test_stddev(self, compiler):
        result = compiler.compile("SELECT stddev(duration) FROM Transaction")
        assert_valid_dql(result)
        assert "stddev(" in code_lines(result.dql)

    def test_rate_count_1m(self, compiler):
        result = compiler.compile("SELECT rate(count(*), 1 minute) FROM Transaction")
        assert_valid_dql(result)

    def test_percentage_to_count_if(self, compiler):
        result = compiler.compile("SELECT percentage(count(*), WHERE duration > 1) FROM Transaction")
        assert_valid_dql(result)
        assert "countIf(" in code_lines(result.dql)

    def test_filter_count_to_count_if(self, compiler):
        result = compiler.compile("SELECT filter(count(*), WHERE error IS true) FROM Transaction")
        assert_valid_dql(result)
        assert "countIf(" in code_lines(result.dql)

    def test_filter_sum_to_sum_if(self, compiler):
        result = compiler.compile("SELECT filter(sum(duration), WHERE error IS true) FROM Transaction")
        assert_valid_dql(result)
        assert "sumIf(" in code_lines(result.dql)

    def test_filter_avg_to_avg_if(self, compiler):
        result = compiler.compile("SELECT filter(average(duration), WHERE duration > 1) FROM Transaction")
        assert_valid_dql(result)
        assert "avgIf(" in code_lines(result.dql)

    def test_apdex_no_raw_apdex(self, compiler):
        result = compiler.compile("SELECT apdex(duration, 0.5) FROM Transaction")
        assert_valid_dql(result)
        assert "apdex(" not in code_lines(result.dql)

    def test_histogram_to_bin(self, compiler):
        result = compiler.compile("SELECT histogram(duration, 10, 20) FROM Transaction")
        assert_valid_dql(result)
        assert "bin(" in code_lines(result.dql)

    def test_derivative_count_1m(self, compiler):
        result = compiler.compile("SELECT derivative(count(*), 1 minute) FROM Transaction TIMESERIES")
        assert_valid_dql(result)
        assert "delta(" in code_lines(result.dql)

    def test_cdf_percentage(self, compiler):
        result = compiler.compile("FROM PageView SELECT cdfPercentage(duration, 1, 3, 5)")
        assert_valid_dql(result)
        assert "countIf(" in code_lines(result.dql)


# -- 14b: Every scalar/string/math function --
class TestG14ScalarFunctions:
    """Group 14b -- scalar, string, and math functions."""

    def test_substring_3_arg_named(self, compiler):
        result = compiler.compile("SELECT substring(request.uri, 0, 50) FROM Transaction LIMIT 10")
        assert_valid_dql(result)
        code = code_lines(result.dql)
        assert "from:0" in code
        assert "to:50" in code

    def test_substring_2_arg(self, compiler):
        result = compiler.compile("SELECT substring(request.uri, 5) FROM Transaction LIMIT 10")
        assert_valid_dql(result)
        assert "substring(" in code_lines(result.dql)

    def test_index_of(self, compiler):
        result = compiler.compile("SELECT indexOf(name, '.') FROM Transaction LIMIT 10")
        assert_valid_dql(result)
        assert "indexOf(span.name" in code_lines(result.dql)

    def test_length_to_string_length(self, compiler):
        result = compiler.compile("SELECT length(name) FROM Transaction LIMIT 10")
        assert_valid_dql(result)
        assert "stringLength(span.name" in code_lines(result.dql)

    def test_lower(self, compiler):
        result = compiler.compile("SELECT lower(name) FROM Transaction LIMIT 10")
        assert_valid_dql(result)
        assert "lower(span.name" in code_lines(result.dql)

    def test_upper(self, compiler):
        result = compiler.compile("SELECT upper(name) FROM Transaction LIMIT 10")
        assert_valid_dql(result)
        assert "upper(span.name" in code_lines(result.dql)

    def test_concat(self, compiler):
        result = compiler.compile("SELECT concat(appName, '-', name) FROM Transaction LIMIT 10")
        assert_valid_dql(result)
        assert "concat(service.name" in code_lines(result.dql)

    def test_abs(self, compiler):
        result = compiler.compile("SELECT abs(duration - 1) FROM Transaction LIMIT 10")
        assert_valid_dql(result)
        assert "abs(" in code_lines(result.dql)

    def test_ceil(self, compiler):
        result = compiler.compile("SELECT ceil(duration) FROM Transaction LIMIT 10")
        assert_valid_dql(result)
        assert "ceil(" in code_lines(result.dql)

    def test_floor(self, compiler):
        result = compiler.compile("SELECT floor(duration) FROM Transaction LIMIT 10")
        assert_valid_dql(result)
        assert "floor(" in code_lines(result.dql)

    def test_round(self, compiler):
        result = compiler.compile("SELECT round(duration, 2) FROM Transaction LIMIT 10")
        assert_valid_dql(result)
        assert "round(" in code_lines(result.dql)

    def test_sqrt(self, compiler):
        result = compiler.compile("SELECT sqrt(duration) FROM Transaction LIMIT 10")
        assert_valid_dql(result)
        assert "sqrt(" in code_lines(result.dql)

    def test_pow(self, compiler):
        result = compiler.compile("SELECT pow(duration, 2) FROM Transaction LIMIT 10")
        assert_valid_dql(result)
        assert "pow(" in code_lines(result.dql)

    def test_log10(self, compiler):
        result = compiler.compile("SELECT log10(duration) FROM Transaction LIMIT 10")
        assert_valid_dql(result)
        assert "log10(" in code_lines(result.dql)

    def test_ln_to_log(self, compiler):
        result = compiler.compile("SELECT ln(duration) FROM Transaction LIMIT 10")
        assert_valid_dql(result)
        assert "log(duration" in code_lines(result.dql)

    def test_exp(self, compiler):
        result = compiler.compile("SELECT exp(duration) FROM Transaction LIMIT 10")
        assert_valid_dql(result)
        assert "exp(" in code_lines(result.dql)

    def test_numeric_to_to_double(self, compiler):
        result = compiler.compile("SELECT numeric('123') FROM Transaction LIMIT 10")
        assert_valid_dql(result)
        assert "toDouble(" in code_lines(result.dql)

    def test_string_to_to_string(self, compiler):
        result = compiler.compile("SELECT string(httpResponseCode) FROM Transaction LIMIT 10")
        assert_valid_dql(result)
        assert "toString(" in code_lines(result.dql)

    def test_if_cond_a_b(self, compiler):
        result = compiler.compile("SELECT if(duration > 1, 'slow', 'fast') FROM Transaction LIMIT 10")
        assert_valid_dql(result)
        assert "if(" in code_lines(result.dql)


# -- 14c: Every time function --
class TestG14TimeFunctions:
    """Group 14c -- time functions."""

    def test_date_of_to_format_timestamp(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction FACET dateOf(timestamp)")
        assert_valid_dql(result)
        assert "formatTimestamp(" in code_lines(result.dql)

    def test_hour_of_to_get_hour(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction FACET hourOf(timestamp)")
        assert_valid_dql(result)
        assert "getHour(" in code_lines(result.dql)

    def test_minute_of_to_get_minute(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction FACET minuteOf(timestamp)")
        assert_valid_dql(result)
        assert "getMinute(" in code_lines(result.dql)

    def test_day_of_week_to_get_day_of_week(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction FACET dayOfWeek(timestamp)")
        assert_valid_dql(result)
        assert "getDayOfWeek(" in code_lines(result.dql)

    def test_week_of_to_get_week_of_year(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction FACET weekOf(timestamp)")
        assert_valid_dql(result)
        assert "getWeekOfYear(" in code_lines(result.dql)

    def test_month_of_to_get_month(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction FACET monthOf(timestamp)")
        assert_valid_dql(result)
        assert "getMonth(" in code_lines(result.dql)

    def test_year_of_to_get_year(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction FACET yearOf(timestamp)")
        assert_valid_dql(result)
        assert "getYear(" in code_lines(result.dql)

    def test_aggregationendtime_to_end(self, compiler):
        result = compiler.compile("SELECT aggregationendtime(), count(*) FROM Transaction TIMESERIES 1 hour")
        assert_valid_dql(result)
        assert "end(" in code_lines(result.dql)


# -- 14d: Every event type -> DQL data source --
class TestG14EventTypes:
    """Group 14d -- event type to DQL data source mapping."""

    def test_transaction_to_spans(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction")
        assert_valid_dql(result)
        assert "fetch spans" in code_lines(result.dql)

    def test_transaction_error_to_spans_error(self, compiler):
        result = compiler.compile("SELECT count(*) FROM TransactionError")
        assert_valid_dql(result)
        code = code_lines(result.dql)
        assert "fetch spans" in code
        assert "otel.status_code" in code

    def test_span_to_spans(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Span")
        assert_valid_dql(result)
        assert "fetch spans" in code_lines(result.dql)

    def test_log_to_logs(self, compiler):
        result = compiler.compile("FROM Log SELECT count(*)")
        assert_valid_dql(result)
        assert "fetch logs" in code_lines(result.dql)

    def test_log_event_to_logs(self, compiler):
        result = compiler.compile("SELECT count(*) FROM LogEvent")
        assert_valid_dql(result)
        assert "fetch logs" in code_lines(result.dql)

    def test_system_sample_to_metric(self, compiler):
        result = compiler.compile("SELECT average(cpuPercent) FROM SystemSample TIMESERIES")
        assert_valid_dql(result)
        assert "timeseries" in code_lines(result.dql)

    def test_process_sample_to_metric(self, compiler):
        result = compiler.compile("SELECT average(cpuPercent) FROM ProcessSample TIMESERIES")
        assert_valid_dql(result)
        assert "timeseries" in code_lines(result.dql)

    def test_network_sample_to_metric(self, compiler):
        result = compiler.compile("SELECT average(transmitBytesPerSecond) FROM NetworkSample TIMESERIES")
        assert_valid_dql(result)
        assert "timeseries" in code_lines(result.dql)

    def test_k8s_container_sample_to_k8s(self, compiler):
        result = compiler.compile("SELECT average(cpuUsedCores) FROM K8sContainerSample TIMESERIES")
        assert_valid_dql(result)
        assert "timeseries" in code_lines(result.dql)

    def test_k8s_node_sample_to_k8s(self, compiler):
        result = compiler.compile("SELECT average(cpuUsedCores) FROM K8sNodeSample TIMESERIES")
        assert_valid_dql(result)
        assert "timeseries" in code_lines(result.dql)

    def test_k8s_pod_sample_to_k8s(self, compiler):
        result = compiler.compile("SELECT average(cpuUsedCores) FROM K8sPodSample TIMESERIES")
        assert_valid_dql(result)
        assert "timeseries" in code_lines(result.dql)

    def test_k8s_cluster_sample_to_k8s(self, compiler):
        result = compiler.compile("SELECT count(*) FROM K8sClusterSample")
        assert_valid_dql(result)

    def test_k8s_deployment_sample_to_k8s(self, compiler):
        result = compiler.compile("SELECT count(*) FROM K8sDeploymentSample")
        assert_valid_dql(result)

    def test_page_view_to_bizevents(self, compiler):
        result = compiler.compile("SELECT count(*) FROM PageView")
        assert_valid_dql(result)
        assert "fetch bizevents" in code_lines(result.dql)

    def test_page_action_to_bizevents(self, compiler):
        result = compiler.compile("SELECT count(*) FROM PageAction")
        assert_valid_dql(result)
        assert "fetch bizevents" in code_lines(result.dql)

    def test_browser_interaction_to_bizevents(self, compiler):
        result = compiler.compile("SELECT count(*) FROM BrowserInteraction")
        assert_valid_dql(result)
        assert "fetch bizevents" in code_lines(result.dql)

    def test_javascript_error_to_bizevents(self, compiler):
        result = compiler.compile("SELECT count(*) FROM JavaScriptError")
        assert_valid_dql(result)
        assert "fetch bizevents" in code_lines(result.dql)

    def test_ajax_request_to_bizevents(self, compiler):
        result = compiler.compile("SELECT count(*) FROM AjaxRequest")
        assert_valid_dql(result)
        assert "fetch bizevents" in code_lines(result.dql)

    def test_synthetic_check_to_synthetic(self, compiler):
        result = compiler.compile("SELECT count(*) FROM SyntheticCheck")
        assert_valid_dql(result)
        assert "dt.synthetic" in code_lines(result.dql)

    def test_infrastructure_event_to_events(self, compiler):
        result = compiler.compile("SELECT count(*) FROM InfrastructureEvent")
        assert_valid_dql(result)

    def test_aws_lambda_invocation_to_spans(self, compiler):
        result = compiler.compile("SELECT count(*) FROM AwsLambdaInvocation")
        assert_valid_dql(result)
        assert "fetch spans" in code_lines(result.dql)

    def test_nr_custom_app_event_to_bizevents(self, compiler):
        result = compiler.compile("SELECT count(*) FROM NrCustomAppEvent")
        assert_valid_dql(result)
        assert "fetch bizevents" in code_lines(result.dql)


# -- 14e: Critical field mappings --
class TestG14FieldMappings:
    """Group 14e -- field name mapping from NR to DQL."""

    def test_app_name_to_service_name(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE appName = 'x'")
        assert_valid_dql(result)
        assert "service.name" in code_lines(result.dql)

    def test_host_to_host_name(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction FACET host")
        assert_valid_dql(result)
        assert "host.name" in code_lines(result.dql)

    def test_hostname_to_host_name(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction FACET hostname")
        assert_valid_dql(result)
        assert "host.name" in code_lines(result.dql)

    def test_http_response_code_to_status_code(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction FACET httpResponseCode")
        assert_valid_dql(result)
        assert "http.response.status_code" in code_lines(result.dql)

    def test_http_status_code_to_status_code(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE http.statusCode = 200")
        assert_valid_dql(result)
        assert "http.response.status_code" in code_lines(result.dql)

    def test_transaction_type_to_span_kind(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE transactionType = 'Web'")
        assert_valid_dql(result)
        code = code_lines(result.dql)
        assert "span.kind" in code
        assert "transactionType" not in code

    def test_request_uri_to_http_request_path(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE request.uri LIKE '%api%'")
        assert_valid_dql(result)
        assert "http.request.path" in code_lines(result.dql)

    def test_request_method_to_http_request_method(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction FACET request.method")
        assert_valid_dql(result)
        assert "http.request.method" in code_lines(result.dql)

    def test_error_type_mapping(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction FACET errorType")
        assert_valid_dql(result)
        code = code_lines(result.dql)
        assert "error.type" in code
        assert "errorType" not in code

    def test_error_message_mapping(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction FACET errorMessage")
        assert_valid_dql(result)
        assert "error.message" in code_lines(result.dql)

    def test_message_to_content(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Log WHERE message LIKE '%error%'")
        assert_valid_dql(result)
        assert "content" in code_lines(result.dql)

    def test_level_to_loglevel(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Log WHERE level = 'ERROR'")
        assert_valid_dql(result)
        assert "loglevel" in code_lines(result.dql)

    def test_trace_id_to_trace_id(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction FACET traceId")
        assert_valid_dql(result)
        assert "trace_id" in code_lines(result.dql)

    def test_parent_id_to_span_parent_id(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Span FACET parentId")
        assert_valid_dql(result)
        assert "span.parent_id" in code_lines(result.dql)

    def test_cluster_name_to_k8s_cluster_name(self, compiler):
        result = compiler.compile("SELECT count(*) FROM K8sContainerSample WHERE clusterName = 'test'")
        assert_valid_dql(result)
        assert "k8s.cluster.name" in code_lines(result.dql)

    def test_pod_name_to_k8s_pod_name(self, compiler):
        result = compiler.compile("SELECT count(*) FROM K8sContainerSample FACET podName")
        assert_valid_dql(result)
        assert "k8s.pod.name" in code_lines(result.dql)

    def test_container_name_to_k8s_container_name(self, compiler):
        result = compiler.compile("SELECT count(*) FROM K8sContainerSample FACET containerName")
        assert_valid_dql(result)
        assert "k8s.container.name" in code_lines(result.dql)

    def test_node_name_to_k8s_node_name(self, compiler):
        result = compiler.compile("SELECT count(*) FROM K8sNodeSample FACET nodeName")
        assert_valid_dql(result)
        assert "k8s.node.name" in code_lines(result.dql)

    def test_namespace_name_to_k8s_namespace_name(self, compiler):
        result = compiler.compile("SELECT count(*) FROM K8sContainerSample FACET namespaceName")
        assert_valid_dql(result)
        assert "k8s.namespace.name" in code_lines(result.dql)

    def test_deployment_name_to_k8s_deployment_name(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction FACET deploymentName")
        assert_valid_dql(result)
        code = code_lines(result.dql)
        assert "k8s.deployment.name" in code
        assert "deploymentName" not in code

    def test_page_url_to_page_url(self, compiler):
        result = compiler.compile("SELECT count(*) FROM PageView FACET pageUrl")
        assert_valid_dql(result)
        assert "page.url" in code_lines(result.dql)

    def test_user_agent_name_to_browser_name(self, compiler):
        result = compiler.compile("SELECT count(*) FROM PageView FACET userAgentName")
        assert_valid_dql(result)
        assert "browser.name" in code_lines(result.dql)

    def test_database_call_count_to_db_call_count(self, compiler):
        result = compiler.compile("SELECT sum(databaseCallCount) FROM Transaction")
        assert_valid_dql(result)
        code = code_lines(result.dql)
        assert "db.call_count" in code
        assert "databaseCallCount" not in code

    def test_external_call_count_to_http_call_count(self, compiler):
        result = compiler.compile("SELECT sum(externalCallCount) FROM Transaction")
        assert_valid_dql(result)
        code = code_lines(result.dql)
        assert "http.call_count" in code
        assert "externalCallCount" not in code


# -- 14f: Every operator/condition type --
class TestG14Operators:
    """Group 14f -- operator and condition translations."""

    def test_eq_to_double_eq(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE appName = 'test'")
        assert_valid_dql(result)
        assert '== "test"' in code_lines(result.dql)

    def test_neq_preserved(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE appName != 'test'")
        assert_valid_dql(result)
        assert '!= "test"' in code_lines(result.dql)

    def test_gt_preserved(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE duration > 1")
        assert_valid_dql(result)
        assert "> 1" in code_lines(result.dql)

    def test_gte_preserved(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE duration >= 0.5")
        assert_valid_dql(result)
        assert ">= 500us" in code_lines(result.dql)

    def test_lt_preserved(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE duration < 2")
        assert_valid_dql(result)
        assert "< 2" in code_lines(result.dql)

    def test_lte_preserved(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE duration <= 10")
        assert_valid_dql(result)
        assert "<= 10" in code_lines(result.dql)

    def test_is_null(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE error IS NULL")
        assert_valid_dql(result)
        assert "isNull(" in code_lines(result.dql)

    def test_is_not_null(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE error IS NOT NULL")
        assert_valid_dql(result)
        assert "isNotNull(" in code_lines(result.dql)

    def test_in_list(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE appName IN ('a', 'b', 'c')")
        assert_valid_dql(result)
        assert 'in(service.name, {"a", "b", "c"})' in code_lines(result.dql)

    def test_not_in_list(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE appName NOT IN ('x', 'y')")
        assert_valid_dql(result)
        assert 'not in(service.name, {"x", "y"})' in code_lines(result.dql)

    def test_like_contains(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE name LIKE '%payment%'")
        assert_valid_dql(result)
        assert "contains(" in code_lines(result.dql)

    def test_like_starts_with(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE name LIKE 'api/%'")
        assert_valid_dql(result)
        assert "startsWith(" in code_lines(result.dql)

    def test_like_ends_with(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE name LIKE '%/health'")
        assert_valid_dql(result)
        assert "endsWith(" in code_lines(result.dql)

    def test_not_like_to_not_contains(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE name NOT LIKE '%test%'")
        assert_valid_dql(result)
        assert "not(contains(" in code_lines(result.dql)

    def test_rlike_no_raw_rlike(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE name RLIKE '.*api.*'")
        assert_valid_dql(result)
        assert "RLIKE" not in code_lines(result.dql)

    def test_is_true(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE error IS true")
        assert_valid_dql(result)
        assert "== true" in code_lines(result.dql)

    def test_is_false(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE error IS false")
        assert_valid_dql(result)
        assert "== false" in code_lines(result.dql)

    def test_and_preserved(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE appName = 'a' AND duration > 1")
        assert_valid_dql(result)
        assert " and " in code_lines(result.dql)

    def test_or_preserved(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE appName = 'a' OR appName = 'b'")
        assert_valid_dql(result)
        assert " or " in code_lines(result.dql)

    def test_nested_and_or(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction WHERE (appName = 'a' OR appName = 'b') AND duration > 1")
        assert_valid_dql(result)
        code = code_lines(result.dql)
        assert " or " in code
        assert " and " in code


# -- 14g: Every alias edge case --
class TestG14Aliases:
    """Group 14g -- reserved-word and special-character aliases."""

    def test_alias_duration_backticked(self, compiler):
        result = compiler.compile("SELECT average(duration) AS 'duration' FROM Transaction")
        assert_valid_dql(result)
        assert "`duration`=" in code_lines(result.dql)

    def test_alias_timestamp_backticked(self, compiler):
        result = compiler.compile("SELECT max(timestamp) AS 'timestamp' FROM Transaction")
        assert_valid_dql(result)
        assert "`timestamp`=" in code_lines(result.dql)

    def test_alias_from_backticked(self, compiler):
        result = compiler.compile("SELECT count(*) AS 'from' FROM Transaction")
        assert_valid_dql(result)
        assert "`from`=" in code_lines(result.dql)

    def test_alias_to_backticked(self, compiler):
        result = compiler.compile("SELECT count(*) AS 'to' FROM Transaction")
        assert_valid_dql(result)
        assert "`to`=" in code_lines(result.dql)

    def test_alias_in_backticked(self, compiler):
        result = compiler.compile("SELECT count(*) AS 'in' FROM Transaction")
        assert_valid_dql(result)
        assert "`in`=" in code_lines(result.dql)

    def test_alias_filter_backticked(self, compiler):
        result = compiler.compile("SELECT count(*) AS 'filter' FROM Transaction")
        assert_valid_dql(result)
        assert "`filter`=" in code_lines(result.dql)

    def test_alias_fetch_backticked(self, compiler):
        result = compiler.compile("SELECT count(*) AS 'fetch' FROM Transaction")
        assert_valid_dql(result)
        assert "`fetch`=" in code_lines(result.dql)

    def test_alias_sort_backticked(self, compiler):
        result = compiler.compile("SELECT count(*) AS 'sort' FROM Transaction")
        assert_valid_dql(result)
        assert "`sort`=" in code_lines(result.dql)

    def test_alias_not_backticked(self, compiler):
        result = compiler.compile("SELECT count(*) AS 'not' FROM Transaction")
        assert_valid_dql(result)
        assert "`not`=" in code_lines(result.dql)

    def test_alias_true_backticked(self, compiler):
        result = compiler.compile("SELECT count(*) AS 'true' FROM Transaction")
        assert_valid_dql(result)
        assert "`true`=" in code_lines(result.dql)

    def test_alias_null_backticked(self, compiler):
        result = compiler.compile("SELECT count(*) AS 'null' FROM Transaction")
        assert_valid_dql(result)
        assert "`null`=" in code_lines(result.dql)

    def test_alias_2xx_digit_prefix(self, compiler):
        result = compiler.compile(
            "SELECT percentage(count(*), WHERE http.statusCode >= 200 AND http.statusCode < 300) "
            "AS '2XX' FROM Transaction"
        )
        assert_valid_dql(result)
        assert "`2XX`" in code_lines(result.dql)

    def test_alias_4xx_digit_prefix(self, compiler):
        result = compiler.compile(
            "SELECT percentage(count(*), WHERE http.statusCode >= 400 AND http.statusCode < 500) "
            "AS '4XX' FROM Transaction"
        )
        assert_valid_dql(result)
        assert "`4XX`" in code_lines(result.dql)

    def test_alias_5xx_digit_prefix(self, compiler):
        result = compiler.compile(
            "SELECT percentage(count(*), WHERE http.statusCode >= 500) AS '5XX' FROM Transaction"
        )
        assert_valid_dql(result)
        assert "`5XX`" in code_lines(result.dql)

    def test_alias_dollar_slash_special(self, compiler):
        result = compiler.compile("SELECT count(*) / 1000 AS '$/Month' FROM Transaction")
        assert_valid_dql(result)
        assert "`$/Month`" in code_lines(result.dql)

    def test_alias_space(self, compiler):
        result = compiler.compile("SELECT count(*) / 1000 AS 'Requests thousands' FROM Transaction")
        assert_valid_dql(result)
        assert "`Requests thousands`" in code_lines(result.dql)

    def test_alias_dot(self, compiler):
        result = compiler.compile("SELECT average(duration) AS 'Avg.Duration' FROM Transaction")
        assert_valid_dql(result)
        assert "`Avg.Duration`" in code_lines(result.dql)

    def test_alias_parens(self, compiler):
        result = compiler.compile("SELECT count(*) AS 'Count (total)' FROM Transaction")
        assert_valid_dql(result)

    def test_alias_ampersand(self, compiler):
        result = compiler.compile("SELECT count(*) AS 'P&L' FROM Transaction")
        assert_valid_dql(result)


# -- 14h: Timeseries, Compare With, Slide By --
class TestG14Timeseries:
    """Group 14h -- timeseries, compare with, slide by."""

    def test_timeseries_to_make_timeseries(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction TIMESERIES")
        assert_valid_dql(result)
        assert "makeTimeseries" in code_lines(result.dql)

    def test_timeseries_5m_interval(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction TIMESERIES 5 minutes")
        assert_valid_dql(result)
        assert "interval: 5m" in code_lines(result.dql)

    def test_timeseries_1h_interval(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction TIMESERIES 1 hour")
        assert_valid_dql(result)
        assert "interval: 1h" in code_lines(result.dql)

    def test_timeseries_auto_no_interval(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction TIMESERIES AUTO")
        assert_valid_dql(result)
        code = code_lines(result.dql)
        assert "makeTimeseries" in code
        assert "interval:" not in code

    def test_since_until_stripped(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction SINCE 1 hour ago UNTIL 30 minutes ago")
        assert_valid_dql(result)
        code = code_lines(result.dql)
        assert "SINCE" not in code
        assert "UNTIL" not in code

    def test_extrapolate_stripped(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction EXTRAPOLATE")
        assert_valid_dql(result)
        assert "EXTRAPOLATE" not in code_lines(result.dql)

    def test_compare_with_metric_shift(self, compiler):
        result = compiler.compile("SELECT average(cpuPercent) FROM SystemSample TIMESERIES COMPARE WITH 1 week ago")
        assert_valid_dql(result)
        assert "shift:-7d" in code_lines(result.dql)

    def test_compare_with_span_comment(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction TIMESERIES COMPARE WITH 1 day ago")
        assert_valid_dql(result)

    def test_slide_by_to_rolling(self, compiler):
        result = compiler.compile("SELECT average(duration) FROM Transaction TIMESERIES 5 minutes SLIDE BY 1 minute")
        assert_valid_dql(result)
        assert "rolling(" in code_lines(result.dql)

    def test_slide_by_auto_to_rolling(self, compiler):
        result = compiler.compile("SELECT average(duration) FROM Transaction TIMESERIES 10 minutes SLIDE BY AUTO")
        assert_valid_dql(result)
        assert "rolling(" in code_lines(result.dql)

    def test_limit_n(self, compiler):
        result = compiler.compile("SELECT count(*) FROM Transaction FACET appName LIMIT 25")
        assert_valid_dql(result)
        assert "limit 25" in code_lines(result.dql)


# -- 14i: Complex real-world patterns --
class TestG14RealWorldPatterns:
    """Group 14i -- complex real-world patterns."""

    def test_error_rate_filter_filter_times_100(self, compiler):
        result = compiler.compile(
            "SELECT filter(count(*), WHERE error IS true) / filter(count(*), WHERE duration > 0) * 100 "
            "AS 'Error Rate' FROM Transaction WHERE appName = 'prod-order-api' TIMESERIES"
        )
        assert_valid_dql(result)
        assert "countIf(" in code_lines(result.dql)

    def test_multi_percentage_status_codes(self, compiler):
        result = compiler.compile(
            "SELECT percentage(count(http.statusCode), WHERE http.statusCode >= 200 AND http.statusCode < 300) AS '2XX', "
            "percentage(count(http.statusCode), WHERE http.statusCode >= 400 AND http.statusCode < 500) AS '4XX', "
            "percentage(count(http.statusCode), WHERE http.statusCode >= 500) AS '5XX' "
            "FROM Transaction WHERE appName = 'prod-auth-api' TIMESERIES"
        )
        assert_valid_dql(result)
        assert "countIf(" in code_lines(result.dql)

    def test_k8s_memory_util_multi_metric(self, compiler):
        result = compiler.compile(
            "SELECT latest(memoryUsedBytes) / latest(memoryLimitBytes) * 100 "
            "FROM K8sContainerSample WHERE clusterName = 'app-prod' FACET podName TIMESERIES"
        )
        assert_valid_dql(result)

    def test_log_error_by_service_and_level(self, compiler):
        result = compiler.compile(
            "FROM Log SELECT count(*) WHERE level IN ('ERROR', 'FATAL') FACET service.name, level TIMESERIES"
        )
        assert_valid_dql(result)
        assert "fetch logs" in code_lines(result.dql)

    def test_throughput_multi_app(self, compiler):
        result = compiler.compile(
            "SELECT rate(count(*), 1 minute) FROM Transaction "
            "WHERE appName IN ('api-1', 'api-2', 'api-3') FACET appName TIMESERIES"
        )
        assert_valid_dql(result)
        assert "in(service.name" in code_lines(result.dql)

    def test_subquery_trace_correlation(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction WHERE appName = 'order-api' "
            "AND trace.id IN (FROM Span SELECT trace.id WHERE appName = 'auth-api' "
            "AND name = 'authenticate') FACET httpResponseCode TIMESERIES"
        )
        assert_valid_dql(result)
        assert "lookup" in code_lines(result.dql)

    def test_funnel_analysis(self, compiler):
        result = compiler.compile(
            "SELECT funnel(session, WHERE page = '/home' AS 'Home', "
            "WHERE page = '/cart' AS 'Cart', WHERE page = '/checkout' AS 'Checkout') FROM PageView"
        )
        assert_valid_dql(result)
        assert "countIf(" in code_lines(result.dql)

    def test_count_avg_p95_filter_combined(self, compiler):
        result = compiler.compile(
            "SELECT count(*) AS 'Total', average(duration) AS 'Avg', "
            "percentile(duration, 95) AS 'P95', "
            "filter(count(*), WHERE error IS true) AS 'Errors' "
            "FROM Transaction WHERE appName = 'prod-api' TIMESERIES"
        )
        assert_valid_dql(result)
        assert "countIf(" in code_lines(result.dql)

    def test_infra_cpu_with_hostname_filter(self, compiler):
        result = compiler.compile(
            "SELECT average(cpuPercent) FROM SystemSample WHERE hostname LIKE 'prod-%' FACET hostname TIMESERIES"
        )
        assert_valid_dql(result)
        assert "timeseries" in code_lines(result.dql)

    def test_clamp_max_clamp_min_combined(self, compiler):
        result = compiler.compile(
            "SELECT clamp_max(average(duration), 10), clamp_min(count(*), 0) FROM Transaction"
        )
        assert_valid_dql(result)
        assert "if(" in code_lines(result.dql)

    def test_from_prefix_non_standard_order(self, compiler):
        result = compiler.compile(
            "FROM Transaction SELECT count(*), average(duration) WHERE appName = 'test' FACET appName TIMESERIES AUTO"
        )
        assert_valid_dql(result)
        code = code_lines(result.dql)
        assert "fetch spans" in code
        assert "service.name" in code

    def test_custom_event_facet_limit(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM NrCustomAppEvent WHERE eventType = 'OrderPlaced' FACET customerSegment LIMIT 20"
        )
        assert_valid_dql(result)
        assert "limit 20" in code_lines(result.dql)


# -- 14j: Session 69 regression tests --
class TestG14Session69:
    """Group 14j -- Session 69 regression: CASES/matchesPhrase, multi-line, apdex t:N."""

    def test_matches_phrase_in_cases(self, compiler):
        result = compiler.compile(
            'SELECT count(*) FROM BrowserInteraction FACET CASES '
            '(matchesPhrase(targetUrl, "/search2") as \'Coveo\', '
            'matchesPhrase(targetUrl, "/search") as \'Legacy\')'
        )
        assert_valid_dql(result)
        code = code_lines(result.dql)
        assert "contains(targetUrl" in code
        assert '"Coveo"' in code
        assert '"Legacy"' in code

    def test_nrql_comment_single_line(self, compiler):
        result = compiler.compile("SELECT\n  count(*)\nFROM\n  Transaction")
        assert_valid_dql(result)
        first_line = result.dql.split("\n")[0]
        assert "\n" not in first_line or first_line.startswith("//")

    def test_apdex_t_3_threshold(self, compiler):
        result = compiler.compile("SELECT apdex(duration, t:3) FROM BrowserInteraction")
        assert_valid_dql(result)
        code = code_lines(result.dql)
        assert "countIf(duration < 3.0" in code
        assert "countIf(duration >= 3.0" in code

    def test_apdex_t_05_threshold(self, compiler):
        result = compiler.compile("SELECT apdex(duration, t:0.5) FROM BrowserInteraction")
        assert_valid_dql(result)
        code = code_lines(result.dql)
        assert "countIf(duration < 0.5" in code
        assert "countIf(duration >= 0.5" in code

    def test_k8s_is_ready_entity_fetch(self, compiler):
        result = compiler.compile("SELECT latest(isReady) FROM K8sPodSample WHERE clusterName = 'prod'")
        assert_valid_dql(result)
        code = code_lines(result.dql)
        assert "entity" in code
        assert "timeseries" not in code


# -- 14k: Audit fixes --
class TestG14AuditFixes:
    """Group 14k -- audit fixes: context-aware mapping, nested aggregation detection."""

    def test_metric_context_preserves_id_dimension(self, compiler):
        result = compiler.compile(
            "SELECT latest(consumer_lag) FROM Metric WHERE id = 'lkc_123' FACET topic"
        )
        assert_valid_dql(result)
        assert "span.id" not in code_lines(result.dql)

    def test_metric_context_preserves_target_dimension(self, compiler):
        result = compiler.compile(
            "SELECT average(kafka.consumer.lag) FROM Metric WHERE target = 'my-cluster'"
        )
        assert_valid_dql(result)
        assert "http.route" not in code_lines(result.dql)

    def test_span_context_maps_entity_name(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction WHERE entity.name = 'my-svc'"
        )
        assert_valid_dql(result)
        assert "dt.entity.name" in code_lines(result.dql)

    def test_percentage_simple_no_nested_agg(self, compiler):
        result = compiler.compile(
            "SELECT percentage(count(*), WHERE error IS TRUE) FROM Transaction"
        )
        assert_valid_dql(result)
        code = code_lines(result.dql)
        assert "countIf" in code
        assert "count()" in code

    def test_apdex_produces_warning(self, compiler):
        result = compiler.compile("SELECT apdex(duration, t:0.5) FROM Transaction")
        assert_valid_dql(result)
        assert "countIf" in code_lines(result.dql)
        assert any("apdex" in w for w in result.warnings)

    def test_multi_metric_gets_braces(self, compiler):
        result = compiler.compile(
            "SELECT average(cpuPercent), average(memoryUsedPercent) FROM SystemSample FACET hostname TIMESERIES"
        )
        assert_valid_dql(result)
        assert "timeseries {" in code_lines(result.dql)

    def test_metric_filter_uses_braces(self, compiler):
        result = compiler.compile(
            "SELECT average(cpuPercent) FROM SystemSample WHERE hostname = 'web-1' TIMESERIES"
        )
        assert_valid_dql(result)
        assert "filter:{" in code_lines(result.dql)


# ═════════════════════════════════════════════════════════════════════════════
# Phase 1 regression tests
# ═════════════════════════════════════════════════════════════════════════════


class TestCompareWithAppend:
    """COMPARE WITH on span/event queries should generate append subquery."""

    def test_compare_with_day_over_day(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction COMPARE WITH 1 day ago SINCE 1 hour ago"
        )
        assert result.success
        assert "append" in result.dql
        assert "from:now()-1d" in result.dql
        assert '_comparison = "current"' in result.dql
        assert '_comparison = "previous' in result.dql

    def test_compare_with_week_over_week(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction COMPARE WITH 1 week ago"
        )
        assert result.success
        assert "append" in result.dql
        assert "from:now()-7d" in result.dql

    def test_compare_with_facet(self, compiler):
        result = compiler.compile(
            "SELECT count(*) FROM Transaction FACET appName COMPARE WITH 1 day ago"
        )
        assert result.success
        assert "append" in result.dql
        assert "by:" in result.dql
        # Both current and shifted pipelines should have the facet
        dql = result.dql
        assert dql.count("by:") >= 2  # once in current, once in append

    def test_compare_with_metric_still_uses_shift(self, compiler):
        """Metric queries should still use shift: parameter, not append."""
        result = compiler.compile(
            "SELECT average(cpuPercent) FROM SystemSample COMPARE WITH 1 day ago TIMESERIES"
        )
        assert result.success
        assert "shift:-1d" in result.dql
        assert "append" not in result.dql


class TestCaptureFunction:
    """capture() should convert regex to DQL parse() with DPL pattern."""

    def test_capture_named_groups(self, compiler):
        result = compiler.compile(
            r"SELECT capture(message, '(?P<method>\w+)\s+(?P<path>/\S+)') FROM Log"
        )
        assert result.success
        assert "parse(" in result.dql
        assert "method" in result.dql
        assert "path" in result.dql

    def test_capture_digit_group(self, compiler):
        result = compiler.compile(
            r"SELECT capture(message, '(?P<status>\d+)') FROM Log"
        )
        assert result.success
        assert "parse(" in result.dql
        assert "status" in result.dql

    def test_capture_preserves_field_mapping(self, compiler):
        """capture() on 'message' should map to DT 'content' field."""
        result = compiler.compile(
            r"SELECT capture(message, '(?P<code>\d+)') FROM Log"
        )
        assert result.success
        assert "content" in result.dql  # message -> content mapping


class TestNestedFilterInAggregation:
    """count(*, filter(WHERE ...)) should convert to countIf(...)."""

    def test_count_with_filter(self, compiler):
        result = compiler.compile(
            "SELECT count(*, filter(WHERE error IS TRUE)) FROM Transaction"
        )
        assert result.success
        assert "countIf(" in result.dql
        assert "error == true" in result.dql

    def test_sum_with_filter(self, compiler):
        result = compiler.compile(
            "SELECT sum(duration, filter(WHERE appName = 'api')) FROM Transaction"
        )
        assert result.success
        assert "sumIf(" in result.dql
        assert "duration" in result.dql

    def test_average_with_filter(self, compiler):
        result = compiler.compile(
            "SELECT average(duration, filter(WHERE httpResponseCode >= 500)) FROM Transaction"
        )
        assert result.success
        assert "avgIf(" in result.dql
        assert "duration" in result.dql
