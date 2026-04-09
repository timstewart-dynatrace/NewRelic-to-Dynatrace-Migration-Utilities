"""
NRQL-to-DQL Compiler -- DQL Emitter.

Walks the NRQL AST and emits valid DQL.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .ast_nodes import (
    ASTNode,
    BinaryOp,
    ComparisonCond,
    Condition,
    FacetItem,
    FieldRef,
    FunctionCall,
    InListCond,
    InSubqueryCond,
    IsNullCond,
    LikeCond,
    LiteralExpr,
    LogicalCond,
    NotCond,
    Query,
    RLikeCond,
    SelectItem,
    StarExpr,
    TimeInterval,
    TimeseriesClause,
    UnaryMinus,
)
from .parser import AGG_FUNCTIONS


def _parse_compare_shift(raw: str) -> Optional[str]:
    """Convert NR COMPARE WITH time expression to DQL shift: duration.

    '1 week ago' -> '-7d'
    '1 day ago'  -> '-1d'
    '7 days ago' -> '-7d'
    '24 hours ago' -> '-24h'
    '1 month ago' -> '-30d'
    """
    m = re.match(r'(\d+)\s+(week|day|hour|minute|month|second)s?\s+ago',
                 raw.strip(), re.IGNORECASE)
    if not m:
        return None
    val = int(m.group(1))
    unit = m.group(2).lower()
    unit_map = {
        'week': ('d', 7), 'day': ('d', 1), 'hour': ('h', 1),
        'minute': ('m', 1), 'month': ('d', 30), 'second': ('s', 1),
    }
    suffix, mult = unit_map.get(unit, ('d', 1))
    return f"-{val * mult}{suffix}"


# NR event type -> query classification (determines which DQL shape to use)
# METRIC/K8S_* -> timeseries command; everything else -> fetch command
QUERY_CLASS_MAP = {
    'transaction': 'spans', 'transactionerror': 'spans', 'span': 'spans',
    'log': 'logs', 'logevent': 'logs',
    # Metric sources -> timeseries command
    'metric': 'METRIC', 'systemsample': 'METRIC', 'processsample': 'METRIC',
    'networksample': 'METRIC', 'storagesample': 'METRIC', 'containersample': 'METRIC',
    # K8s -> timeseries with K8s metric mapping
    'k8snodesample': 'K8S_NODE_METRIC', 'k8scontainersample': 'K8S_WORKLOAD_METRIC',
    'k8spodsample': 'K8S_POD_METRIC', 'k8sclustersample': 'K8S_CLUSTER_METRIC',
    'k8sdeploymentsample': 'K8S_WORKLOAD_METRIC',
    # Browser/RUM
    'pageview': 'bizevents', 'pageaction': 'bizevents',
    'browserinteraction': 'bizevents', 'ajaxrequest': 'bizevents',
    'javascripterror': 'bizevents',
    # Synthetic
    'syntheticcheck': 'dt.synthetic.http.request', 'syntheticsrequest': 'dt.synthetic.http.request',
    # Events
    'infrastructureevent': 'EVENTS',
    # Lambda / Custom
    'awslambdainvocation': 'spans', 'nrcustomappevent': 'bizevents',
}

# For backward compat -- the old name still used in emit_lookup
EVENT_TYPE_MAP = QUERY_CLASS_MAP

# NR function -> DQL function
FUNC_MAP = {
    'count': 'count', 'sum': 'sum', 'average': 'avg', 'avg': 'avg',
    'max': 'max', 'min': 'min', 'percentile': 'percentile',
    'stddev': 'stddev', 'rate': 'count',  # rate not directly supported; stddev IS native in DQL summarize
    'variance': 'variance',  # DQL native variance() aggregation
    'uniquecount': 'countDistinctExact', 'uniques': 'collectDistinct',
    'latest': 'takeLast', 'earliest': 'takeFirst', 'last': 'takeLast', 'first': 'takeFirst',
    'median': 'percentile',  # -> percentile(field, 50)
    # String
    'substring': 'substring', 'indexof': 'indexOf', 'length': 'stringLength',
    'concat': 'concat', 'lower': 'lower', 'upper': 'upper',
    'capture': 'extract', 'aparse': 'parse',
    'replace': 'replaceAll', 'trim': 'trim',
    'startswith': 'startsWith', 'endswith': 'endsWith',
    # Math
    'abs': 'abs', 'ceil': 'ceil', 'floor': 'floor', 'round': 'round',
    'sqrt': 'sqrt', 'pow': 'pow', 'log': 'log', 'log10': 'log10', 'exp': 'exp',
    'ln': 'log',  # ln(x) is natural log = log(x) in DQL
    'cbrt': 'cbrt', 'sign': 'sign',
    # Time
    'dateof': 'formatTimestamp', 'hourof': 'getHour', 'minuteof': 'getMinute',
    'dayofweek': 'getDayOfWeek', 'weekof': 'getWeekOfYear',
    'monthof': 'getMonth', 'yearof': 'getYear',
    # Type
    'numeric': 'toDouble', 'string': 'toString',
    'toDouble': 'toDouble', 'toLong': 'toLong', 'toNumber': 'toNumber',
    'toBoolean': 'toBoolean', 'toTimestamp': 'toTimestamp',
    # If
    'if': 'if',
    # Boolean matching functions (NR WHERE helpers -> DQL string functions)
    'matchesphrase': 'contains', 'matchesvalue': 'contains',
    # Phase 2-3 additions
    'buckets': 'bin',
    'aggregationendtime': 'end',
}

# NR filter() -> DQL funcIf mapping
FILTER_IF_MAP = {
    'count': 'countIf', 'sum': 'sumIf', 'average': 'avgIf', 'avg': 'avgIf',
    'max': 'maxIf', 'min': 'minIf',
}

# NR field -> DT field (common attributes)
FIELD_MAP = {
    'appname': 'service.name', 'appName': 'service.name',
    'transactionname': 'span.name', 'name': 'span.name',
    'duration': 'duration', 'duration.ms': 'duration',
    'databaseduration': 'db.duration', 'externalduration': 'http.duration',
    'host': 'host.name', 'hostname': 'host.name', 'fullhostname': 'host.name',
    'httpresponsecode': 'http.response.status_code',
    'httpResponseCode': 'http.response.status_code',
    'http.statuscode': 'http.response.status_code',
    'http.statusCode': 'http.response.status_code',
    'response.status': 'http.response.status_code',
    'httpresponsestatuscode': 'http.response.status_code',
    'request.uri': 'http.request.path', 'request.url': 'http.request.path',
    'request.method': 'http.request.method',
    'http.method': 'http.request.method', 'httpmethod': 'http.request.method',
    'http.url': 'http.request.path', 'httpurl': 'http.request.path',
    'error.message': 'error.message',
    'entityguid': 'dt.entity.service', 'entityname': 'dt.entity.name',
    'entity.name': 'dt.entity.name',
    'cpupercent': 'host.cpu.usage', 'memoryusedpercent': 'host.memory.usage',
    'diskusedpercent': 'host.disk.usage',
    'message': 'content', 'level': 'loglevel', 'log.level': 'loglevel',
    # K8s
    'k8s.containername': 'k8s.container.name', 'k8s.podname': 'k8s.pod.name',
    'k8s.clustername': 'k8s.cluster.name', 'k8s.namespacename': 'k8s.namespace.name',
    'k8s.nodename': 'k8s.node.name', 'k8s.deploymentname': 'k8s.deployment.name',
    'clustername': 'k8s.cluster.name', 'podname': 'k8s.pod.name',
    'namespace': 'k8s.namespace.name', 'namespacename': 'k8s.namespace.name',
    'containername': 'k8s.container.name', 'nodename': 'k8s.node.name',
    # Browser/RUM
    'pageurl': 'page.url', 'pageUrl': 'page.url',
    'userAgentName': 'browser.name', 'useragentname': 'browser.name',
    'userAgentOS': 'os.name', 'useragentos': 'os.name',
    'city': 'geo.city', 'regionCode': 'geo.region', 'countryCode': 'geo.country',
    'deviceType': 'device.type', 'devicetype': 'device.type',
    # Span/Trace IDs (critical for subquery joins)
    'parentId': 'span.parent_id', 'parentid': 'span.parent_id',
    'parent.id': 'span.parent_id',
    'id': 'span.id',
    'traceId': 'trace_id', 'traceid': 'trace_id',
    'guid': 'span.id',
    'nr.guid': 'span.id',
    # Duration variants
    'Duration.Seconds': 'duration', 'duration.seconds': 'duration',
    'Duration.seconds': 'duration', 'duration.Seconds': 'duration',
    'Duration.Ms': 'duration', 'Duration.ms': 'duration',
    'durationMs': 'duration', 'Duration.Minutes': 'duration',
    # Transaction metadata
    'transactiontype': 'span.kind', 'transactionType': 'span.kind',
    'error': 'error', 'error.class': 'error.type',
    'errortype': 'error.type', 'errorType': 'error.type',
    'errormessage': 'error.message', 'errorMessage': 'error.message',
    'response.status': 'http.response.status_code',
    'response.statuscode': 'http.response.status_code',
    'databasecallcount': 'db.call_count', 'databaseCallCount': 'db.call_count',
    'externalcallcount': 'http.call_count', 'externalCallCount': 'http.call_count',
    'deploymentname': 'k8s.deployment.name', 'deploymentName': 'k8s.deployment.name',
}


class DQLEmitter:
    """Walk the NRQL AST and emit valid DQL.

    Handles ALL query types:
    - Span/Transaction queries -> fetch spans | makeTimeseries/summarize
    - Log queries -> fetch logs | ...
    - Metric queries (SystemSample, Metric) -> timeseries func(dt.metric)
    - K8s queries -> timeseries func(dt.kubernetes.metric)
    - Events queries -> fetch events | fields
    - Browser/RUM -> fetch bizevents | ...
    """

    # K8s context-specific metric overrides.
    # Some NR fields (memoryUsedBytes, cpuPercent, etc.) appear in both host and K8s contexts.
    # When FROM is K8sContainerSample/K8sNodeSample, these must map to dt.kubernetes.* metrics.
    K8S_METRIC_OVERRIDES = {
        'memoryusedbytes': 'dt.kubernetes.container.memory_working_set',
        'memoryused': 'dt.kubernetes.container.memory_working_set',
        'cpuusedbytes': 'dt.kubernetes.container.cpu_usage',
        'cpupercent': 'dt.kubernetes.container.cpu_usage',
        'diskused': 'dt.kubernetes.persistentvolumeclaim.used',
        'diskusedbytes': 'dt.kubernetes.persistentvolumeclaim.used',
        'restartcount': 'dt.kubernetes.container.restarts',
        'restartcountdelta': 'dt.kubernetes.container.restarts',
        'cpuusedcores': 'dt.kubernetes.container.cpu_usage',
        'memoryworkingsetbytes': 'dt.kubernetes.container.memory_working_set',
    }

    # K8s fields that are NOT valid timeseries metrics -- they need entity queries instead.
    # When encountered, _emit_metric_query redirects to an entity-based DQL fetch.
    K8S_ENTITY_FIELDS = {
        'isready': {
            'dql': (
                'fetch dt.entity.cloud_application'
                ' | fields entity.name, readyReplicas = readyReplicas, desiredReplicas = desiredReplicas'
            ),
            'note': '// isReady -> DT uses entity properties, not timeseries metrics. '
                    'Compare readyReplicas vs desiredReplicas for readiness.',
        },
        'status': {
            'dql': (
                'fetch dt.entity.cloud_application'
                ' | fields entity.name, status = cloudApplicationStatus'
            ),
            'note': '// status -> DT uses entity properties for workload status.',
        },
        'isscheduled': {
            'dql': (
                'fetch dt.entity.cloud_application_instance'
                ' | fields entity.name, phase = cloudApplicationInstancePhase'
            ),
            'note': '// isScheduled -> DT uses entity phase property, not timeseries metrics.',
        },
    }

    DQL_RESERVED_WORDS = {
        'duration', 'timestamp', 'timeframe', 'string', 'long', 'double',
        'boolean', 'ip', 'record', 'array', 'true', 'false', 'null',
        'fetch', 'filter', 'summarize', 'fields', 'sort', 'limit',
        'lookup', 'join', 'append', 'parse', 'from', 'to', 'by',
        'asc', 'desc', 'not', 'and', 'or', 'in', 'is',
    }

    # Fields that are custom metric dimensions -- do NOT remap in metric context.
    # In METRIC/K8S queries, these are dimension names on custom metrics (e.g.,
    # Confluent Cloud kafka metrics use 'id', 'topic', 'target' as dimensions).
    # In span/log context, they should be mapped normally.
    METRIC_DIMENSION_PASSTHROUGH = {
        'id', 'target', 'topic', 'consumer_group', 'partition',
        'cluster_id', 'principal_id', 'type', 'name', 'mode',
    }

    def __init__(self, field_map: Dict[str, str] = None, metric_map: Dict[str, str] = None,
                 metric_transforms: Dict[str, Dict] = None, metric_resolver=None):
        self.field_map = {**FIELD_MAP, **(field_map or {})}
        self.metric_map = metric_map or {}
        self.metric_transforms = metric_transforms or {}
        self.metric_resolver = metric_resolver  # callable(field_key, raw_field) -> (dt_metric, warning)
        self.warnings: List[str] = []
        self._agg_counter = 0  # for auto-naming aggregations

    def emit(self, query: Query) -> str:
        """Emit a complete DQL query from an NRQL AST."""
        self.warnings = []
        self._agg_counter = 0
        self._histogram_bin_expr = None  # Set by histogram() handler for by:{bin()} injection
        self._funnel_steps = []  # Set by funnel() handler for conversion rate fieldsAdd
        self._query_class = 'spans'  # Default; updated below after classify

        # Handle SHOW EVENT TYPES
        if query.from_clause == '__SHOW_EVENT_TYPES__':
            self.warnings.append("SHOW EVENT TYPES -> use DT Schema browser or: fetch dt.entity.type")
            return ("// SHOW EVENT TYPES has no direct DQL equivalent\n"
                    "// In Dynatrace, use the Schema browser in Notebooks/Dashboards\n"
                    "// or query: fetch dt.entity.type | fields entity.type | dedup entity.type")

        from_type = query.from_clause.lower().replace('_', '').replace('-', '')
        query_class = self._classify_query(from_type)
        self._query_class = query_class  # Store for context-aware field mapping

        if query_class == 'METRIC':
            dql = self._emit_metric_query(query, from_type)
        elif query_class.startswith('K8S_'):
            dql = self._emit_metric_query(query, from_type)
        elif query_class == 'EVENTS':
            dql = self._emit_events_query(query)
        else:
            dql = self._emit_fetch_query(query, query_class)

        # Validate emitted DQL for nested aggregation errors
        dql = self._validate_no_nested_aggregations(dql)

        # COMPARE WITH handling
        # DQL shift: parameter ONLY works on the `timeseries` command (metric queries).
        # It does NOT work on `makeTimeseries` (span/event queries).
        # For makeTimeseries, time comparison requires append[] with shifted subquery,
        # which is too complex to auto-generate. Add comment for manual overlay.
        if query.compare_with_raw:
            shift_dur = _parse_compare_shift(query.compare_with_raw)
            # Check for timeseries command (metric queries use standalone 'timeseries',
            # span queries use '| makeTimeseries')
            has_ts_cmd = ('| timeseries ' in dql or
                          any(l.strip().startswith('timeseries ') for l in dql.split('\n')))
            has_make_ts = 'makeTimeseries' in dql
            if shift_dur and has_ts_cmd and not has_make_ts:
                # Metric queries: timeseries command supports shift: natively
                lines = dql.split('\n')
                for i, line in enumerate(lines):
                    if '| timeseries ' in line or line.strip().startswith('timeseries '):
                        lines[i] = line.rstrip() + f", shift:{shift_dur}"
                        break
                dql = '\n'.join(lines)
                self.warnings.append(
                    f"COMPARE WITH {query.compare_with_raw} -> DQL shift:{shift_dur} "
                    f"(overlays current + shifted series)"
                )
            elif shift_dur:
                # Span/event queries: generate append subquery with shifted time range
                dql = self._emit_compare_with_append(dql, query, shift_dur)
            else:
                self.warnings.append(
                    f"COMPARE WITH {query.compare_with_raw}: could not parse time shift"
                )

        # EXTRAPOLATE -- NR statistical extrapolation for sampled data
        if query.extrapolate:
            dql += "\n// EXTRAPOLATE -> DT does not sample span data; full fidelity by default"
            self.warnings.append(
                "EXTRAPOLATE removed: DT Grail stores full-fidelity data, no sampling"
            )

        # JOIN clause -- emit as DQL lookup
        if query.join_clause:
            dql = self._emit_join_clause(query, dql)

        # FACET ... ORDER BY -- emit as comment (DQL doesn't have facet selection override)
        if query.facet_order_by:
            order_expr = self._emit_expr(query.facet_order_by)
            dql += f"\n// FACET ORDER BY {order_expr} -> DQL sorts by first summarize column; reorder SELECT to match"
            self.warnings.append(
                f"FACET ORDER BY {order_expr}: DQL uses first aggregation for facet selection. "
                f"Reorder SELECT columns to achieve equivalent."
            )

        # SLIDE BY -> DQL rolling() window function
        # NR: TIMESERIES 1 hour SLIDE BY 5 minutes = 1h window sliding every 5m
        # DQL: makeTimeseries ..., interval: 5m | fieldsAdd rolling(avg, 12)  [12 = 60/5]
        if query.timeseries and query.timeseries.slide_by:
            sb = query.timeseries.slide_by
            window_interval = query.timeseries.interval

            # Parse both intervals to seconds for ratio calculation
            window_secs = self._interval_to_seconds(window_interval)
            slide_secs = self._interval_to_seconds(sb)

            if window_secs and slide_secs and slide_secs > 0:
                rolling_points = max(2, window_secs // slide_secs)
                slide_dql = self._format_interval(
                    type('TS', (), {'interval': sb})()
                )

                if slide_dql:
                    # Replace interval: in existing DQL with slide interval
                    # (the window interval was already emitted, we need the slide interval instead)
                    if 'interval: ' in dql:
                        dql = re.sub(r'interval: \S+', f'interval: {slide_dql}', dql)
                    elif 'makeTimeseries' in dql:
                        # No interval was set (AUTO/MAX) -- add the slide interval
                        dql = dql.replace('makeTimeseries ', 'makeTimeseries ', 1)
                        # Find the makeTimeseries line and add interval
                        lines = dql.split('\n')
                        for i, line in enumerate(lines):
                            if 'makeTimeseries' in line:
                                lines[i] = line.rstrip() + f", interval: {slide_dql}"
                                break
                        dql = '\n'.join(lines)

                    # Extract aggregation names from makeTimeseries/timeseries line
                    # and add rolling() for each
                    agg_names = self._extract_agg_names_from_dql(dql)
                    if agg_names:
                        rolling_lines = []
                        for agg_name, agg_func in agg_names:
                            # Map NR aggregation to rolling function
                            rolling_func = self._agg_to_rolling_func(agg_func)
                            new_name = f"sliding_{agg_name}" if agg_name else f"sliding_{rolling_func}"
                            rolling_lines.append(
                                f"| fieldsAdd {new_name} = rolling({rolling_func}, {rolling_points})"
                            )
                        dql += '\n' + '\n'.join(rolling_lines)

                self.warnings.append(
                    f"SLIDE BY {sb} -> rolling() with {rolling_points}-point window "
                    f"(interval: {slide_dql or sb}). "
                    f"Original columns contain raw per-interval values; "
                    f"sliding_* columns contain the smoothed rolling window."
                )
            elif window_secs and sb.upper() in ('AUTO', 'MAX'):
                # SLIDE BY AUTO/MAX: NR picks a slide interval automatically.
                # DQL equivalent: keep the window interval and use rolling(3) as a
                # sensible default (3-point moving average/sum smoothing).
                agg_names = self._extract_agg_names_from_dql(dql)
                if agg_names:
                    rolling_lines = []
                    for agg_name, agg_func in agg_names:
                        rolling_func = self._agg_to_rolling_func(agg_func)
                        new_name = f"sliding_{agg_name}" if agg_name else f"sliding_{rolling_func}"
                        rolling_lines.append(
                            f"| fieldsAdd {new_name} = rolling({rolling_func}, 3)"
                        )
                    dql += '\n' + '\n'.join(rolling_lines)
                self.warnings.append(
                    f"SLIDE BY {sb} -> rolling() with 3-point window (auto). "
                    f"Adjust the rolling point count to tune smoothing."
                )
            else:
                # Can't calculate ratio -- emit guidance
                dql += (f"\n// SLIDE BY {sb} -> adjust makeTimeseries interval and apply rolling()")
                self.warnings.append(
                    f"SLIDE BY {sb}: couldn't auto-convert. "
                    f"Set interval to slide value and use rolling() window function."
                )

        # PREDICT -- DT uses Davis AI for predictions
        if query.predict:
            dql += "\n// PREDICT -> use Dynatrace Davis AI predictions or forecasting API"
            self.warnings.append("PREDICT: use Davis AI anomaly detection for forecasting in DT")

        # WITH TIMEZONE -- DT uses UTC internally
        if query.with_timezone:
            dql += f"\n// WITH TIMEZONE '{query.with_timezone}' -> DT stores UTC; apply TZ in dashboard settings"
            self.warnings.append(
                f"WITH TIMEZONE '{query.with_timezone}': DT uses UTC. "
                f"Set timezone in dashboard/notebook display settings."
            )

        return dql

    def _emit_compare_with_append(self, dql: str, query: Query, shift_dur: str) -> str:
        """Generate append subquery for COMPARE WITH on span/event queries.

        Duplicates the pipeline with a shifted time range so DT can overlay
        current vs. comparison data.
        E.g., COMPARE WITH 1 day ago with from:now()-1h produces:
          append [<same pipeline with from:now()-1d-1h, to:now()-1d>]
        """
        # Parse the shift duration value and unit for arithmetic
        shift_match = re.match(r'-(\d+)([dhms])', shift_dur)
        if not shift_match:
            self.warnings.append(
                f"COMPARE WITH {query.compare_with_raw}: could not generate append subquery"
            )
            return dql

        shift_val = shift_match.group(1)
        shift_unit = shift_match.group(2)

        # Build the shifted pipeline: replace fetch line's time range
        lines = dql.split('\n')
        # Skip comment lines at the top
        pipeline_lines = []
        comment_lines = []
        for line in lines:
            if line.strip().startswith('//') and not pipeline_lines:
                comment_lines.append(line)
            else:
                pipeline_lines.append(line)

        if not pipeline_lines:
            return dql

        # Build the append block by adjusting the fetch line with shifted time
        shifted_lines = []
        for line in pipeline_lines:
            stripped = line.strip()
            if stripped.startswith('fetch '):
                # Add shifted time range to fetch
                shifted_lines.append(
                    f"{stripped}, from:now()-{shift_val}{shift_unit}-1h, to:now()-{shift_val}{shift_unit}"
                )
            else:
                shifted_lines.append(stripped)

        # Add a fieldsAdd to label the comparison period
        shifted_pipeline = '\n'.join(shifted_lines)
        label_line = f'| fieldsAdd _comparison = "previous ({query.compare_with_raw})"'

        # Also label the current period
        current_label = '| fieldsAdd _comparison = "current"'

        result = '\n'.join(comment_lines + pipeline_lines)
        result += f"\n{current_label}"
        result += f"\n| append [\n{shifted_pipeline}\n{label_line}\n]"

        self.warnings.append(
            f"COMPARE WITH {query.compare_with_raw} -> append subquery with "
            f"shifted time range ({shift_dur}). Use _comparison field to distinguish periods."
        )

        return result

    def _emit_join_clause(self, query: Query, base_dql: str) -> str:
        """Emit JOIN as DQL lookup command."""
        jc = query.join_clause
        sub = jc.subquery

        # Determine subquery fetch type
        sub_from = sub.from_clause.lower().replace('_', '').replace('-', '')
        sub_class = self._classify_query(sub_from)
        if sub_class in ('METRIC',) or sub_class.startswith('K8S_'):
            sub_fetch = f"timeseries /* {sub.from_clause} */"
        else:
            sub_fetch = f"fetch {sub_class}"

        # Build subquery filter
        sub_filter = ''
        if sub.where_clause:
            sub_filter = f"\n| filter {self._emit_condition(sub.where_clause)}"

        # Build subquery fields from select items
        sub_fields = []
        for item in sub.select_items:
            expr_str = self._emit_agg_expr(item.expression)
            if item.alias:
                sub_fields.append(f"{self._sanitize_alias(item.alias)}={expr_str}")
            else:
                sub_fields.append(expr_str)

        # Build lookup command
        on_left = self._map_field(jc.on_left) if jc.on_left else 'id'
        on_right = self._map_field(jc.on_right) if jc.on_right else on_left

        join_type_str = "// LEFT " if jc.join_type == 'LEFT' else "// "
        sub_fields_str = ', '.join(sub_fields) if sub_fields else '*'

        lookup_line = (
            f'| lookup [{sub_fetch}{sub_filter} | fields {on_right}, {sub_fields_str}], '
            f'sourceField:{on_left}, lookupField:{on_right}, prefix:"sub."'
        )

        self.warnings.append(
            f"{jc.join_type} JOIN on {jc.on_left}={jc.on_right}: converted to DQL lookup command"
        )

        return f"{join_type_str}JOIN converted to lookup\n{base_dql}\n{lookup_line}"

    def _classify_query(self, from_type: str) -> str:
        """Determine which DQL shape to use."""
        mapped = QUERY_CLASS_MAP.get(from_type, '')
        if mapped:
            return mapped
        # Heuristics
        if 'metric' in from_type or 'sample' in from_type:
            return 'METRIC'
        if 'log' in from_type:
            return 'logs'
        if 'event' in from_type:
            return 'EVENTS'
        if 'span' in from_type or 'transaction' in from_type:
            return 'spans'
        return 'spans'

    # -- METRIC QUERIES (timeseries command) --

    @staticmethod
    def _format_interval(ts: Optional[TimeseriesClause]) -> Optional[str]:
        """Convert NRQL TIMESERIES interval to DQL interval: value.
        Returns None for AUTO/MAX/empty (let DT auto-select bucket size)."""
        if not ts or not ts.interval:
            return None
        if ts.interval.upper() in ('AUTO', 'MAX'):
            return None
        m = re.match(
            r'(\d+(?:\.\d+)?)\s*'
            r'(second|seconds|sec|s|minute|minutes|min|m|hour|hours|hr|h|day|days|d|week|weeks|w)$',
            ts.interval.strip(), re.IGNORECASE
        )
        if not m:
            return None
        val = m.group(1)
        unit = m.group(2).lower()
        unit_map = {
            'second': 's', 'seconds': 's', 'sec': 's', 's': 's',
            'minute': 'm', 'minutes': 'm', 'min': 'm', 'm': 'm',
            'hour': 'h', 'hours': 'h', 'hr': 'h', 'h': 'h',
            'day': 'd', 'days': 'd', 'd': 'd',
            'week': 'w', 'weeks': 'w', 'w': 'w',
        }
        dql_unit = unit_map.get(unit, 'm')
        if '.' in val and val.endswith('.0'):
            val = val[:-2]
        return f"{val}{dql_unit}"

    @staticmethod
    def _interval_to_seconds(interval_str: Optional[str]) -> Optional[int]:
        """Convert NR interval string to seconds. Returns None if unparseable."""
        if not interval_str or interval_str.upper() in ('AUTO', 'MAX'):
            return None
        m = re.match(
            r'(\d+(?:\.\d+)?)\s*'
            r'(second|seconds|sec|s|minute|minutes|min|m|hour|hours|hr|h|day|days|d|week|weeks|w)$',
            interval_str.strip(), re.IGNORECASE
        )
        if not m:
            return None
        val = float(m.group(1))
        unit = m.group(2).lower()
        unit_secs = {
            'second': 1, 'seconds': 1, 'sec': 1, 's': 1,
            'minute': 60, 'minutes': 60, 'min': 60, 'm': 60,
            'hour': 3600, 'hours': 3600, 'hr': 3600, 'h': 3600,
            'day': 86400, 'days': 86400, 'd': 86400,
            'week': 604800, 'weeks': 604800, 'w': 604800,
        }
        return int(val * unit_secs.get(unit, 60))

    @staticmethod
    def _extract_agg_names_from_dql(dql: str) -> List[Tuple[str, str]]:
        """Extract (name, function) pairs from makeTimeseries/timeseries line.

        Examples:
            'makeTimeseries avg(duration)' -> [('avg', 'avg')]
            'makeTimeseries total=count(), by:...' -> [('total', 'count')]
            'makeTimeseries p95=percentile(duration, 95), cnt=count()' -> [('p95', 'percentile'), ('cnt', 'count')]
        """
        results = []
        for line in dql.split('\n'):
            stripped = line.strip().lstrip('| ')
            if not (stripped.startswith('makeTimeseries') or stripped.startswith('timeseries')):
                continue
            # Extract the aggregation part (everything after the command, before by:/interval:/filter:)
            cmd_end = stripped.find(' ') + 1
            agg_part = stripped[cmd_end:]
            # Remove by:{...}, interval:, filter:, shift:
            agg_part = re.sub(r',\s*(by:\s*\{[^}]*\}|interval:\s*\S+|filter:\s*.+|shift:\s*\S+)', '', agg_part)

            # Parse individual aggregations: name=func(args) or func(args)
            # Split on commas that aren't inside parentheses
            depth = 0
            current = ''
            parts = []
            for ch in agg_part:
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                elif ch == ',' and depth == 0:
                    parts.append(current.strip())
                    current = ''
                    continue
                current += ch
            if current.strip():
                parts.append(current.strip())

            for part in parts:
                # Named: name=func(args)
                m = re.match(r'(\w+)\s*=\s*(\w+)\s*\(', part)
                if m:
                    results.append((m.group(1), m.group(2)))
                    continue
                # Unnamed: func(args)
                m = re.match(r'(\w+)\s*\(', part)
                if m:
                    results.append((m.group(1), m.group(1)))
            break  # Only process first matching line
        return results

    @staticmethod
    def _agg_to_rolling_func(agg_func: str) -> str:
        """Map DQL aggregation function to rolling() function name.
        rolling() supports: avg, sum, min, max, count, median, stddev."""
        mapping = {
            'avg': 'avg', 'count': 'sum', 'countIf': 'sum',
            'sum': 'sum', 'min': 'min', 'max': 'max',
            'percentile': 'avg', 'countDistinctExact': 'avg', 'countDistinctApprox': 'avg',
            'stddev': 'stddev', 'median': 'median', 'variance': 'avg',
        }
        return mapping.get(agg_func, 'avg')

    def _emit_metric_query(self, query: Query, from_type: str) -> str:
        """Emit metric-type queries: timeseries func(dt.metric), by:{}, filter:{}

        Handles three patterns:
        1. Simple: SELECT avg(cpuPercent) -> timeseries avg(dt.host.cpu.usage)
        2. Transform: SELECT latest(errorRate) -> calculated expression from METRIC_TRANSFORMS
        3. Arithmetic: SELECT (latest(a)/latest(b))*100 -> timeseries with fieldsAdd
        4. Entity: SELECT latest(isReady) -> entity fetch (not a valid timeseries metric)
        """
        parts_notes: List[str] = []

        # Detect K8s context for context-aware metric resolution
        query_class = self._classify_query(from_type)
        self._current_k8s_context = query_class.startswith('K8S_') if query_class else False

        # -- K8s entity field interception --
        # Some K8s fields (isReady, status, isScheduled) are entity properties, not
        # timeseries metrics.  Detect them early and emit entity fetch DQL instead.
        if self._current_k8s_context:
            agg_preview = self._extract_metric_aggs(query.select_items)
            if agg_preview:
                first_raw_key = agg_preview[0][2].lower().replace('.', '').replace('_', '').replace('`', '')
                entity_info = self.K8S_ENTITY_FIELDS.get(first_raw_key)
                if entity_info:
                    dql = entity_info['dql']
                    # Append cluster/namespace filter from WHERE clause if present
                    if query.where_clause:
                        filter_str = self._emit_condition(query.where_clause)
                        dql += f"\n| filter {filter_str}"
                    return entity_info['note'] + '\n' + dql

        # Build filter string
        filter_str = ''
        if query.where_clause:
            remaining, metric_conds = self._split_metric_conditions(query.where_clause)
            if remaining:
                f = self._emit_condition(remaining)
                filter_str = f", filter:{{{f}}}"
            if metric_conds:
                parts_notes.append(
                    f"// NOTE: Metric-based filtering ({', '.join(metric_conds)}) "
                    f"applied as post-aggregation threshold in DT"
                )

        # Build by string
        by_str = ''
        if query.facet_items:
            by_items = self._emit_facet_items(query.facet_items)
            by_str = f", by: {{{by_items}}}"

        # Analyze SELECT items for arithmetic-between-aggs patterns
        for item in query.select_items:
            if self._is_computed_metric_expr(item.expression):
                # Pattern 3: arithmetic between aggregations
                dql = self._emit_computed_metric(item, by_str, filter_str)
                if parts_notes:
                    return '\n'.join(parts_notes) + '\n' + dql
                return dql

        # Patterns 1 & 2: simple aggregation or transform
        agg_items = self._extract_metric_aggs(query.select_items)

        if not agg_items:
            return self._emit_fetch_query(query, 'spans')

        # Check first metric for METRIC_TRANSFORMS
        first_func, first_field, first_raw = agg_items[0]
        field_key = first_raw.lower().replace('.', '').replace('_', '').replace('`', '')
        transform = self.metric_transforms.get(field_key)

        if transform:
            dql = self._emit_metric_transform(transform, by_str, filter_str)
            if len(agg_items) > 1:
                extras = [raw for _, _, raw in agg_items[1:]]
                parts_notes.append(f"// NOTE: Additional metrics in original: {', '.join(extras)}")
            if parts_notes:
                return '\n'.join(parts_notes) + '\n' + dql
            return dql

        # Pattern 1: simple metric(s)
        dt_metric = self._resolve_metric_field(field_key, first_raw)
        dt_func = self._map_metric_agg(first_func)

        interval_str = self._format_interval(query.timeseries)
        interval_part = f", interval: {interval_str}" if interval_str else ""

        if len(agg_items) > 1:
            # Multiple simple metrics: emit all as multi-metric timeseries with braces
            ts_parts = []
            for func_name, field_name, raw in agg_items:
                fk = raw.lower().replace('.', '').replace('_', '').replace('`', '')
                resolved = self._resolve_metric_field(fk, raw)
                mapped_func = self._map_metric_agg(func_name)
                alias = self._sanitize_alias(raw.split('.')[-1] if '.' in raw else raw)
                ts_parts.append(f"{alias} = {mapped_func}({resolved})")
            dql = f"timeseries {{{', '.join(ts_parts)}}}{by_str}{filter_str}{interval_part}"
        else:
            dql = f"timeseries {dt_func}({dt_metric}){by_str}{filter_str}{interval_part}"

        if parts_notes:
            return '\n'.join(parts_notes) + '\n' + dql
        return dql

    def _is_computed_metric_expr(self, node: ASTNode) -> bool:
        """Check if expression is arithmetic between multiple aggregation calls.
        e.g., (latest(a)/latest(b))*100"""
        if isinstance(node, BinaryOp):
            has_agg_left = self._contains_agg(node.left)
            has_agg_right = self._contains_agg(node.right)
            # Arithmetic between two agg branches, or agg with literal
            if has_agg_left and (has_agg_right or isinstance(node.right, LiteralExpr)):
                # Need at least 2 distinct agg calls to qualify
                aggs = []
                self._collect_aggs(node, aggs)
                return len(aggs) >= 2
        return False

    def _contains_agg(self, node: ASTNode) -> bool:
        """Check if node tree contains any aggregation function call."""
        if isinstance(node, FunctionCall) and node.name.lower() in AGG_FUNCTIONS:
            return True
        if isinstance(node, BinaryOp):
            return self._contains_agg(node.left) or self._contains_agg(node.right)
        if isinstance(node, UnaryMinus):
            return self._contains_agg(node.operand)
        return False

    def _collect_aggs(self, node: ASTNode, aggs: List):
        """Collect all aggregation FunctionCall nodes from expression tree."""
        if isinstance(node, FunctionCall) and node.name.lower() in AGG_FUNCTIONS:
            aggs.append(node)
        elif isinstance(node, BinaryOp):
            self._collect_aggs(node.left, aggs)
            self._collect_aggs(node.right, aggs)
        elif isinstance(node, UnaryMinus):
            self._collect_aggs(node.operand, aggs)

    def _emit_computed_metric(self, item: SelectItem, by_str: str, filter_str: str) -> str:
        """Emit a computed metric expression as multi-metric timeseries + fieldsAdd.

        Input AST: (latest(fsInodesUsed) / latest(fsInodes)) * 100 as fsInodeCapacityUtilization
        Output DQL:
            timeseries m1 = avg(dt.kubernetes.node.filesystem.inodes_used),
                       m2 = avg(dt.kubernetes.node.filesystem.inodes){by}{filter}
            | fieldsAdd fsInodeCapacityUtilization = (toDouble(m1) / toDouble(m2)) * 100
        """
        # Collect all aggregation calls
        aggs: List[FunctionCall] = []
        self._collect_aggs(item.expression, aggs)

        # Assign temp names and resolve metrics
        agg_aliases: Dict[int, str] = {}  # id(agg_node) -> alias name
        ts_parts: List[str] = []

        for i, agg in enumerate(aggs):
            alias = f"m{i+1}"
            agg_aliases[id(agg)] = alias

            # Get field and resolve to DT metric
            raw_field = ''
            if agg.args and not isinstance(agg.args[0], StarExpr):
                raw_field = self._extract_field_name(agg.args[0])
            field_key = raw_field.lower().replace('.', '').replace('_', '').replace('`', '')
            dt_metric = self._resolve_metric_field(field_key, raw_field)
            dt_func = self._map_metric_agg(agg.name.lower())

            ts_parts.append(f"{alias} = {dt_func}({dt_metric})")

        # Build timeseries line
        # DQL requires curly braces around multiple aggregations to disambiguate
        # from named parameters like by: and filter:
        if len(ts_parts) > 1:
            dql = f"timeseries {{{', '.join(ts_parts)}}}{by_str}{filter_str}"
        else:
            dql = f"timeseries {ts_parts[0]}{by_str}{filter_str}"

        # Build the arithmetic expression with alias references
        calc_expr = self._emit_computed_expr(item.expression, agg_aliases)

        # Result name
        result_name = self._sanitize_alias(item.alias) if item.alias else 'result'

        dql += f"\n| fieldsAdd {result_name} = {calc_expr}"

        return dql

    def _emit_computed_expr(self, node: ASTNode, agg_aliases: Dict[int, str]) -> str:
        """Emit arithmetic expression with agg calls replaced by toDouble(alias) refs."""
        if isinstance(node, FunctionCall) and node.name.lower() in AGG_FUNCTIONS:
            alias = agg_aliases.get(id(node), 'unknown')
            return f"toDouble({alias})"
        if isinstance(node, BinaryOp):
            left = self._emit_computed_expr(node.left, agg_aliases)
            right = self._emit_computed_expr(node.right, agg_aliases)
            return f"({left} {node.op} {right})"
        if isinstance(node, LiteralExpr):
            v = node.value
            if isinstance(v, (int, float)):
                return f"{float(v)}" if isinstance(v, int) else str(v)
            return str(v)
        if isinstance(node, UnaryMinus):
            inner = self._emit_computed_expr(node.operand, agg_aliases)
            return f"-{inner}"
        # Fallback
        return self._emit_expr(node)

    def _emit_metric_transform(self, transform: Dict, by_str: str, filter_str: str) -> str:
        """Emit a METRIC_TRANSFORMS calculated expression."""
        ttype = transform['type']
        note = transform.get('note', '')

        if ttype == 'calculated':
            template = transform.get('dql_single', transform['dql'])
            dql = template.replace('{by}', by_str).replace('{filter}', filter_str)
        elif ttype == 'multi_metric':
            dql = transform['dql'].replace('{by}', by_str).replace('{filter}', filter_str)
        elif ttype == 'unit_convert':
            metric = transform['metric']
            post_calc = transform.get('post_calc', '')
            alias = metric.split('.')[-1][:12]
            dql = f"timeseries {alias} = avg({metric}){by_str}{filter_str}"
            if post_calc:
                dql += f"\n{post_calc.replace('{alias}', alias)}"
        else:
            dql = f"// Unknown transform type: {ttype}"

        if note:
            dql = f"// {note}\n{dql}"
        return dql

    def _extract_metric_aggs(self, items: List[SelectItem]) -> List[Tuple[str, str, str]]:
        """Extract (func, dt_func, raw_field) tuples from SELECT items for metric queries."""
        results = []
        for item in items:
            extracted = self._walk_for_agg(item.expression)
            if extracted:
                results.extend(extracted)
        return results

    def _walk_for_agg(self, node: ASTNode) -> List[Tuple[str, str, str]]:
        """Walk expression tree to find aggregation function calls."""
        if isinstance(node, FunctionCall):
            if node.name.lower() in AGG_FUNCTIONS:
                raw_field = ''
                if node.args and not isinstance(node.args[0], StarExpr):
                    raw_field = self._extract_field_name(node.args[0])
                return [(node.name.lower(), node.name.lower(), raw_field)]
        if isinstance(node, BinaryOp):
            left = self._walk_for_agg(node.left)
            right = self._walk_for_agg(node.right)
            return (left or []) + (right or [])
        return []

    def _extract_field_name(self, node: ASTNode) -> str:
        """Get raw field name from expression node."""
        if isinstance(node, FieldRef):
            return node.name
        if isinstance(node, FunctionCall):
            # nested: avg(something(field))
            if node.args:
                return self._extract_field_name(node.args[0])
        return ''

    def _resolve_metric_field(self, field_key: str, raw_field: str) -> str:
        """Resolve NR field to DT metric.

        Resolution order:
        1. K8s context overrides (when query is FROM K8s*Sample)
        2. Static METRIC_MAP (fast, known mappings)
        3. Live registry resolver (validates metric exists, fuzzy finds correction)
        4. Passthrough with warning
        """
        # 0. K8s context overrides
        if getattr(self, '_current_k8s_context', False):
            k8s_metric = self.K8S_METRIC_OVERRIDES.get(field_key)
            if k8s_metric:
                return k8s_metric

        # 1. Static map
        dt_metric = self.metric_map.get(field_key)
        if dt_metric:
            # If we have a live resolver, validate this mapping actually exists
            if self.metric_resolver:
                validated, warning = self.metric_resolver(field_key, raw_field, dt_metric)
                if warning:
                    self.warnings.append(warning)
                return validated
            return dt_metric

        # 2. Live resolver (handles fuzzy matching, text search)
        if self.metric_resolver:
            resolved, warning = self.metric_resolver(field_key, raw_field, None)
            if warning:
                self.warnings.append(warning)
            if resolved:
                return resolved

        # Already a DT metric?
        if raw_field.startswith('dt.') or raw_field.startswith('builtin:'):
            return raw_field

        # 3. Passthrough with warning
        self.warnings.append(f"Unknown metric '{raw_field}' -- no METRIC_MAP entry, no live registry match")
        return raw_field

    def _map_metric_agg(self, func: str) -> str:
        """Map aggregation function for timeseries command.
        timeseries only supports: sum, avg, min, max, count, percentile, countDistinct"""
        func_low = func.lower()
        if func_low in ('latest', 'last', 'first', 'earliest', 'average'):
            return 'avg'
        # Special metric-context functions
        if func_low == 'derivative':
            self.warnings.append("derivative() -> DQL delta() in timeseries context")
            return 'delta'
        if func_low == 'bucketpercentile':
            self.warnings.append("bucketPercentile() -> DQL percentile() for Prometheus histograms")
            return 'percentile'
        dt = FUNC_MAP.get(func_low, func_low)
        # Validate it's a valid timeseries aggregation
        valid_ts = {'sum', 'avg', 'min', 'max', 'count', 'countIf',
                    'countDistinctExact', 'countDistinctApprox',
                    'percentile', 'stddev', 'variance', 'delta'}
        if dt not in valid_ts:
            self.warnings.append(f"'{dt}' not valid for timeseries -- using avg")
            return 'avg'
        return dt

    def _split_metric_conditions(self, cond: Condition) -> Tuple[Optional[Condition], List[str]]:
        """Split WHERE clause into entity-filterable and metric-value conditions.
        Metric conditions like 'memoryUsedBytes > 1000' can't go in timeseries filter:."""
        metric_fields = {
            'allocatablememoryutilization', 'memoryusedbytes', 'memoryavailablebytes',
            'fscapacityutilization', 'fsavailablebytes', 'fsinodesused', 'fsinodes',
            'cpuusedbytes', 'allocatablecpuutilization', 'fsinodescapacityutilization',
        }
        stripped: List[str] = []

        def walk(c: Condition) -> Optional[Condition]:
            if isinstance(c, ComparisonCond):
                if isinstance(c.left, FieldRef) and c.left.name.lower().replace('.','').replace('_','') in metric_fields:
                    stripped.append(c.left.name)
                    return None
                return c
            if isinstance(c, LogicalCond):
                left = walk(c.left)
                right = walk(c.right)
                if left is None and right is None: return None
                if left is None: return right
                if right is None: return left
                return LogicalCond(c.op, left, right)
            if isinstance(c, NotCond):
                inner = walk(c.operand)
                return NotCond(inner) if inner else None
            return c

        remaining = walk(cond)
        return remaining, stripped

    # -- EVENTS QUERIES (fetch events) --

    def _emit_events_query(self, query: Query) -> str:
        """Emit InfrastructureEvent -> fetch events | fields | filter"""
        parts: List[str] = ['fetch events']

        if query.where_clause:
            parts.append(f"| filter {self._emit_condition(query.where_clause)}")

        # Select -> fields
        field_exprs = [self._emit_expr(item.expression) for item in query.select_items
                       if not self._is_agg_expr(item.expression)]
        if field_exprs:
            parts.append(f"| fields {', '.join(field_exprs)}")

        if query.limit and query.limit.value != 'MAX':
            parts.append(f"| limit {query.limit.value}")

        return '\n'.join(parts)

    # -- FETCH QUERIES (spans, logs, bizevents, etc.) --

    def _emit_fetch_query(self, query: Query, fetch_type: str) -> str:
        """Emit standard fetch queries: fetch type | filter | makeTimeseries/summarize"""
        parts: List[str] = []

        # 1. fetch <type>
        parts.append(f"fetch {fetch_type}")

        # 1b. Auto-filter for TransactionError -> only error spans
        from_type = query.from_clause.lower().replace('_', '').replace('-', '')
        if from_type == 'transactionerror':
            parts.append('| filter otel.status_code == "ERROR"')

        # 2. Filter -- extract subqueries for separate lookup steps
        subqueries: List[InSubqueryCond] = []
        remaining_where = None
        if query.where_clause:
            remaining_where, subqueries = self._extract_subqueries(query.where_clause)

        if remaining_where:
            filter_str = self._emit_condition(remaining_where)
            parts.append(f"| filter {filter_str}")

        # 3. Lookup steps from subqueries
        for sq in subqueries:
            self._emit_lookup(sq, parts)

        # 4. Aggregation
        has_agg = self._has_aggregation(query.select_items)
        has_ts = query.timeseries is not None

        if has_ts or has_agg:
            cmd = 'makeTimeseries' if has_ts else 'summarize'
            by_clause = ''

            # -- CASES in FACET handling --
            # DQL's by:{} clause only accepts field references, not computed
            # expressions like if(contains(...)). When FACET contains CASES
            # (which emits if/else chains), we must:
            #   1. Emit fieldsAdd to create computed grouping column(s)
            #   2. Reference the column name in by:{}
            facet_fields_add = []
            if query.facet_items:
                has_cases = any(
                    isinstance(fi.expression, FunctionCall) and fi.expression.name.lower() == 'cases'
                    for fi in query.facet_items
                )
                if has_cases:
                    # Pre-compute CASES expressions as fieldsAdd columns
                    by_refs = []
                    for i, item in enumerate(query.facet_items):
                        if isinstance(item.expression, FunctionCall) and item.expression.name.lower() == 'cases':
                            col_name = item.alias or f'_category_{i+1}'
                            col_name = self._sanitize_alias(col_name)
                            cases_expr = self._emit_expr(item.expression)
                            facet_fields_add.append(f"{col_name} = {cases_expr}")
                            by_refs.append(col_name)
                        else:
                            expr_str = self._emit_expr(item.expression)
                            if item.alias:
                                by_refs.append(f"{self._sanitize_alias(item.alias)}={expr_str}")
                            else:
                                by_refs.append(expr_str)
                    by_clause = f", by: {{{', '.join(by_refs)}}}"
                else:
                    by_items = self._emit_facet_items(query.facet_items)
                    by_clause = f", by: {{{by_items}}}"

            # Emit fieldsAdd for CASES before aggregation
            for fa in facet_fields_add:
                parts.append(f"| fieldsAdd {fa}")

            # Interval for makeTimeseries
            interval_clause = ''
            if has_ts:
                interval_str = self._format_interval(query.timeseries)
                if interval_str:
                    interval_clause = f", interval: {interval_str}"

            # Check for computed-aggregation expressions that need decomposition
            # (cdfPercentage, percentage(), arithmetic between aggs)
            decomposed = self._decompose_computed_aggs(
                query.select_items, is_timeseries=has_ts)

            if decomposed:
                agg_exprs, fields_add = decomposed
                # Inject histogram bin if set during expression emission
                if self._histogram_bin_expr:
                    if by_clause:
                        by_clause = by_clause.rstrip('}') + f", {self._histogram_bin_expr}}}"
                    else:
                        by_clause = f", by: {{{self._histogram_bin_expr}}}"
                    self._histogram_bin_expr = None
                agg_str = self._format_agg_list(cmd, agg_exprs)
                parts.append(f"| {cmd} {agg_str}{by_clause}{interval_clause}")
                for fa in fields_add:
                    parts.append(f"| fieldsAdd {fa}")
                # DO NOT use fieldsRemove here. DT visualization requires all
                # makeTimeseries columns for data mapping (Time, Values, Names).
                # Removing _m1/_m2 intermediates causes "No field available" errors.
                # Extra columns are harmless -- users toggle them off in chart legend.
            else:
                agg_exprs = self._emit_aggregations(
                    query.select_items, needs_naming=has_ts)
                # Inject histogram bin if set during expression emission
                if self._histogram_bin_expr:
                    if by_clause:
                        by_clause = by_clause.rstrip('}') + f", {self._histogram_bin_expr}}}"
                    else:
                        by_clause = f", by: {{{self._histogram_bin_expr}}}"
                    self._histogram_bin_expr = None
                agg_str = self._format_agg_list(cmd, agg_exprs)
                parts.append(
                    f"| {cmd} {agg_str}{by_clause}{interval_clause}")
        else:
            # No aggregation -- project fields
            field_exprs = [self._emit_expr(item.expression) for item in query.select_items]
            parts.append(f"| fields {', '.join(field_exprs)}")
            if query.facet_items:
                by_items = self._emit_facet_items(query.facet_items)
                parts.append(f"| summarize by: {{{by_items}}}")

        # 4b. Funnel conversion rates (if funnel was decomposed into countIf steps)
        if self._funnel_steps and len(self._funnel_steps) >= 2:
            for i in range(len(self._funnel_steps) - 1):
                step_cur = self._funnel_steps[i][0]
                step_next = self._funnel_steps[i + 1][0]
                label_cur = self._funnel_steps[i][1]
                label_next = self._funnel_steps[i + 1][1]
                safe_cur = re.sub(r'[^a-zA-Z0-9_]', '_', label_cur)
                safe_next = re.sub(r'[^a-zA-Z0-9_]', '_', label_next)
                parts.append(
                    f"| fieldsAdd conv_{safe_cur}_to_{safe_next} = "
                    f"(toDouble({step_next}) / toDouble({step_cur})) * 100.0"
                )
            self._funnel_steps = []

        # 5. Sort
        if query.order_by:
            direction = "asc" if query.order_by.direction == 'ASC' else "desc"
            expr = self._emit_expr(query.order_by.expression)
            parts.append(f"| sort {expr} {direction}")

        # 6. Limit
        if query.limit and query.limit.value != 'MAX':
            parts.append(f"| limit {query.limit.value}")

        return '\n'.join(parts)

    # -- Aggregations --

    def _has_aggregation(self, items: List[SelectItem]) -> bool:
        return any(self._is_agg_expr(item.expression) for item in items)

    def _is_agg_expr(self, node: ASTNode) -> bool:
        if isinstance(node, FunctionCall):
            if node.name.lower() in AGG_FUNCTIONS:
                return True
            # Arithmetic on aggregations
        if isinstance(node, BinaryOp):
            return self._is_agg_expr(node.left) or self._is_agg_expr(node.right)
        if isinstance(node, UnaryMinus):
            return self._is_agg_expr(node.operand)
        return False

    def _sanitize_alias(self, alias: str) -> str:
        """Sanitize alias for DQL: backtick-escape reserved words, digit-prefixed,
        and special-character identifiers."""
        if not alias:
            return alias
        # Starts with digit -> backtick
        if alias[0].isdigit():
            return f'`{alias}`'
        # DQL reserved word -> backtick
        if alias.lower() in self.DQL_RESERVED_WORDS:
            return f'`{alias}`'
        # Contains spaces or special chars -> backtick
        if re.search(r'[^a-zA-Z0-9_]', alias):
            return f'`{alias}`'
        return alias

    def _format_agg_list(self, cmd: str, agg_exprs: List[str]) -> str:
        """Format aggregation list for makeTimeseries/summarize.

        DQL requires curly braces for BOTH makeTimeseries AND summarize
        when multiple aggregations are present. Without braces, the parser
        can't distinguish aliased aggregations from named parameters.

        Single agg:  summarize count()          / makeTimeseries count()
        Multi agg:   summarize {count(), avg(d)} / makeTimeseries {count(), avg(d)}
        """
        # Count actual aggregation items (multi-percentile expansions contain
        # commas within a single list item, so split on ', ' to count real items)
        total_items = 0
        for expr in agg_exprs:
            # Multi-percentile expansions like "p95=percentile(x,95), p99=percentile(x,99)"
            # are a single list item but contain multiple comma-separated aggregations
            total_items += expr.count('), ') + 1

        joined = ', '.join(agg_exprs)

        if total_items > 1 and cmd in ('makeTimeseries', 'summarize'):
            return '{' + joined + '}'
        return joined

    def _emit_aggregations(self, items: List[SelectItem], needs_naming: bool) -> List[str]:
        """Emit SELECT items as DQL aggregation expressions.
        Deduplicates identical expressions without aliases.
        Auto-names positional-ambiguous aggregations in makeTimeseries."""
        seen: Dict[str, str] = {}  # normalized_expr -> emitted_str
        result: List[str] = []

        for item in items:
            expr_str = self._emit_agg_expr(item.expression)

            # Determine alias
            alias = self._sanitize_alias(item.alias) if item.alias else None

            # Dedup: if same expression with no alias, skip
            normalized = expr_str.lower().strip()
            if not alias and normalized in seen:
                continue
            seen[normalized] = expr_str

            # Auto-name if needed (makeTimeseries requires named params for multi-arg funcs)
            # BUT: multi-percentile expansion already embeds aliases (e.g., "p95=percentile(...), p99=...")
            already_named = '=' in expr_str.split('(')[0] if '(' in expr_str else '=' in expr_str
            if alias and already_named:
                # Expression has embedded alias AND user alias -> replace embedded with user's
                # e.g., "p95=percentile(x, 95)" + alias "Percentile" -> "Percentile=percentile(x, 95)"
                # For multi-percentile expansions like "p95=percentile(x,95), p99=percentile(x,99)",
                # keep embedded aliases since user's single alias can't cover multiple expansions
                if ', ' in expr_str and expr_str.count('=') > 1:
                    # Multi-expansion: keep as-is (user alias doesn't apply to split results)
                    result.append(expr_str)
                else:
                    # Single expansion: replace embedded alias with user's
                    eq_pos = expr_str.index('=')
                    result.append(f"{alias}={expr_str[eq_pos+1:]}")
            elif alias:
                result.append(f"{alias}={expr_str}")
            elif already_named:
                # Expression already has embedded alias(es) from multi-percentile expansion
                result.append(expr_str)
            elif needs_naming and self._needs_naming(item.expression):
                auto_name = self._auto_name(item.expression)
                result.append(f"{auto_name}={expr_str}")
            else:
                result.append(expr_str)

        return result

    def _needs_naming(self, node: ASTNode) -> bool:
        """Does this aggregation need an explicit name in makeTimeseries?"""
        if isinstance(node, FunctionCall):
            # percentile(field, N) -- the N is ambiguous as a positional param
            if node.name.lower() == 'percentile' and len(node.args) >= 2:
                return True
            # Any function with 2+ comma-separated args inside makeTimeseries
            if len(node.args) >= 2 and node.name.lower() in AGG_FUNCTIONS:
                return True
        return False

    def _auto_name(self, node: ASTNode) -> str:
        """Generate an automatic alias for an aggregation."""
        if isinstance(node, FunctionCall):
            name = node.name.lower()
            if name == 'percentile' and len(node.args) >= 2:
                pct_arg = node.args[1]
                if isinstance(pct_arg, LiteralExpr) and isinstance(pct_arg.value, (int, float)):
                    return f"p{int(pct_arg.value)}"
            return f"{FUNC_MAP.get(name, name)}_{self._next_counter()}"
        return f"agg_{self._next_counter()}"

    # -- Computed-aggregation decomposition for makeTimeseries --

    def _contains_computed_agg(self, node: ASTNode) -> bool:
        """Check if expression contains arithmetic between aggregations or
        multi-expansion functions (cdfPercentage, percentage) that produce
        expressions invalid in makeTimeseries."""
        if isinstance(node, FunctionCall):
            name_low = node.name.lower()
            # cdfPercentage expands into multiple countIf/count arithmetic
            if name_low == 'cdfpercentage':
                return True
            # percentage(count(*), WHERE cond) -> 100*countIf/count
            if name_low == 'percentage' and node.where_clause:
                return True
        if isinstance(node, BinaryOp):
            # Arithmetic between two aggregation calls
            left_agg = self._is_agg_expr(node.left)
            right_agg = self._is_agg_expr(node.right)
            if left_agg and right_agg:
                return True
            # One side is agg, other is literal -> also invalid in makeTimeseries
            # e.g. countIf(x) / count() * 100
            if left_agg or right_agg:
                return True
        return False

    def _decompose_computed_aggs(self, items: List, is_timeseries: bool):
        """Decompose arithmetic-on-aggregations into component aggs + fieldsAdd.

        For makeTimeseries, expressions like:
            100.0 * countIf(error) / count()
            cdfPercentage(duration, 1000, 2000)
            filter(count(*), WHERE x >= 500) / count(*) * 100

        ...are invalid because makeTimeseries only accepts simple aggregation calls.

        This decomposes them into:
            makeTimeseries _matched=countIf(error), _total=count()
            | fieldsAdd error_pct = 100.0 * toDouble(_matched) / toDouble(_total)

        Returns (agg_strings, fieldsAdd_strings) or None if no decomposition needed.
        """
        if not is_timeseries:
            return None

        needs_decomp = any(
            self._contains_computed_agg(item.expression) for item in items
        )
        if not needs_decomp:
            return None

        agg_strings: List[str] = []
        fields_add: List[str] = []
        counter = [0]
        seen_count: List[str] = []  # track deduplicated count() aliases

        def next_id():
            counter[0] += 1
            return counter[0]

        def get_count_alias():
            """Reuse a single count() aggregation across decomposed items."""
            if not seen_count:
                alias = f"_total_{next_id()}"
                agg_strings.append(f"{alias}=count()")
                seen_count.append(alias)
            return seen_count[0]

        # Pre-scan: if ANY item needs decomposition with a count() total,
        # create the shared count alias NOW so standalone count(*) items
        # that appear earlier can reuse it.
        # IMPORTANT: Only create count() if the expression actually USES count(),
        # not just because there's a BinaryOp with any aggregation.
        def _expr_needs_count(expr):
            """Check if expression actually requires a count() decomposition."""
            if isinstance(expr, FunctionCall):
                if expr.name.lower() in ('cdfpercentage', 'percentage'):
                    return True
                if expr.name.lower() == 'count':
                    return True  # Direct count() usage
            if isinstance(expr, BinaryOp):
                return _expr_needs_count(expr.left) or _expr_needs_count(expr.right)
            return False

        any_needs_count = any(
            _expr_needs_count(item.expression)
            for item in items
        )
        if any_needs_count:
            get_count_alias()  # pre-create _total_1

        for item in items:
            expr = item.expression

            # -- cdfPercentage(field, t1, t2, ...) --
            if (isinstance(expr, FunctionCall)
                    and expr.name.lower() == 'cdfpercentage'
                    and len(expr.args) >= 2):
                field_str = self._emit_expr(expr.args[0])
                total_alias = get_count_alias()

                for i, arg in enumerate(expr.args[1:]):
                    t_str = self._emit_expr(arg)
                    t_label = t_str.replace('.', '_').replace('-', '_')
                    below_alias = f"_below_{t_label}_{next_id()}"
                    agg_strings.append(
                        f"{below_alias}=countIf({field_str} <= {t_str})")
                    pct_name = f"pct_le_{t_label}"
                    fields_add.append(
                        f"{pct_name} = 100.0 * toDouble({below_alias})"
                        f" / toDouble({total_alias})")

                self.warnings.append(
                    "cdfPercentage() -> decomposed into countIf/count "
                    "aggregations + fieldsAdd percentages"
                )
                continue

            # -- percentage(count(*), WHERE cond) --
            if (isinstance(expr, FunctionCall)
                    and expr.name.lower() == 'percentage'
                    and expr.where_clause):
                cond_str = self._emit_condition(expr.where_clause)
                matched_alias = f"_matched_{next_id()}"
                total_alias = get_count_alias()
                agg_strings.append(f"{matched_alias}=countIf({cond_str})")
                result_name = self._sanitize_alias(item.alias) if item.alias else f"percentage_{next_id()}"
                fields_add.append(
                    f"{result_name} = 100.0 * toDouble({matched_alias})"
                    f" / toDouble({total_alias})")
                continue

            # -- BinaryOp between aggregations --
            if (isinstance(expr, BinaryOp)
                    and self._contains_computed_agg(expr)):
                aggs: list = []
                self._collect_aggs(expr, aggs)
                agg_aliases: dict = {}
                for agg in aggs:
                    alias = f"_m{next_id()}"
                    agg_aliases[id(agg)] = alias
                    agg_str = self._emit_agg_expr(agg)
                    # Deduplicate count() across items
                    if agg_str == 'count()' and seen_count:
                        agg_aliases[id(agg)] = seen_count[0]
                    else:
                        agg_strings.append(f"{alias}={agg_str}")
                        if agg_str == 'count()':
                            seen_count.append(alias)
                calc_expr = self._emit_computed_expr(expr, agg_aliases)
                result_name = self._sanitize_alias(item.alias) if item.alias else f"computed_{next_id()}"
                fields_add.append(f"{result_name} = {calc_expr}")
                continue

            # -- Normal aggregation -- pass through --
            agg_str = self._emit_agg_expr(expr)
            # If this is count() and we already have a named count() from
            # a decomposed item, reuse that alias (skip adding a duplicate)
            if agg_str == 'count()' and seen_count:
                # Add a fieldsAdd alias if the user gave it one
                if item.alias:
                    fields_add.append(
                        f"{self._sanitize_alias(item.alias)} = toDouble({seen_count[0]})")
                continue
            if item.alias:
                agg_strings.append(f"{self._sanitize_alias(item.alias)}={agg_str}")
            elif self._needs_naming(expr):
                auto_name = self._auto_name(expr)
                agg_strings.append(f"{auto_name}={agg_str}")
            else:
                agg_strings.append(agg_str)

        # Deduplicate agg_strings (e.g. multiple count() from different items)
        seen = set()
        deduped = []
        for a in agg_strings:
            if a not in seen:
                seen.add(a)
                deduped.append(a)

        return deduped, fields_add

    def _next_counter(self) -> int:
        self._agg_counter += 1
        return self._agg_counter

    def _emit_agg_expr(self, node: ASTNode) -> str:
        """Emit an aggregation expression, handling NR-specific transforms."""
        if isinstance(node, FunctionCall):
            return self._emit_function(node)
        if isinstance(node, BinaryOp):
            left = self._emit_agg_expr(node.left)
            right = self._emit_agg_expr(node.right)
            return f"{left} {node.op} {right}"
        if isinstance(node, UnaryMinus):
            return f"-{self._emit_agg_expr(node.operand)}"
        if isinstance(node, LiteralExpr):
            return self._emit_literal(node)
        return self._emit_expr(node)

    # -- Functions --

    def _emit_function(self, node: FunctionCall) -> str:
        name_low = node.name.lower()

        # -- percentage(count(*), WHERE cond) -> (100.0 * countIf(cond) / count())
        if name_low == 'percentage' and node.where_clause:
            cond_str = self._emit_condition(node.where_clause)
            # Check if the emitted condition contains aggregation functions
            # (e.g., from apdex() decomposition). If so, we have nested
            # aggregations which DQL rejects with NO_NESTED_AGGREGATIONS.
            agg_keywords = ['countIf(', 'count()', 'sum(', 'avg(', 'min(', 'max(', 'percentile(']
            has_nested_agg = any(kw in cond_str for kw in agg_keywords)
            if has_nested_agg:
                self.warnings.append(
                    "percentage() wrapping aggregation functions detected. "
                    "DQL does not support nested aggregations. "
                    "This query needs manual decomposition into: "
                    "summarize step1 aggregations | fieldsAdd percentage calculation"
                )
                return (
                    f"// ERROR: Nested aggregation detected - manual fix required\n"
                    f"// Original: percentage(count(*), WHERE <complex condition>)\n"
                    f"// Fix: Use multi-step pipeline:\n"
                    f"//   | summarize matching = countIf(<simple_condition>), total = count()\n"
                    f"//   | fieldsAdd pct = 100.0 * toDouble(matching) / toDouble(total)\n"
                    f"(100.0 * countIf({cond_str}) / count())"
                )
            return f"(100.0 * countIf({cond_str}) / count())"

        # -- count(*, filter(WHERE cond)) -> countIf(cond)
        # NR allows filter() as a nested argument inside aggregation functions
        if name_low in FILTER_IF_MAP and node.args:
            for arg in node.args:
                if (isinstance(arg, FunctionCall) and
                        arg.name.lower() == 'filter' and arg.where_clause):
                    dt_if = FILTER_IF_MAP[name_low]
                    cond_str = self._emit_condition(arg.where_clause)
                    # Get non-filter, non-star args (e.g., field in sum(field, filter(...)))
                    other_args = [
                        self._emit_expr(a) for a in node.args
                        if a is not arg and not isinstance(a, StarExpr)
                    ]
                    if other_args:
                        return f"{dt_if}({', '.join(other_args)}, {cond_str})"
                    return f"{dt_if}({cond_str})"

        # -- filter(func(field), WHERE cond) -> funcIf(field, cond)
        if name_low == 'filter' and node.where_clause and node.args:
            inner = node.args[0]
            if isinstance(inner, FunctionCall):
                dt_if = FILTER_IF_MAP.get(inner.name.lower())
                if dt_if:
                    field_str = ', '.join(self._emit_expr(a) for a in inner.args) if inner.args else ''
                    cond_str = self._emit_condition(node.where_clause)
                    if field_str and not isinstance(inner.args[0], StarExpr):
                        return f"{dt_if}({field_str}, {cond_str})"
                    else:
                        return f"{dt_if}({cond_str})"
                else:
                    # Generic: func(field) with WHERE -> can't convert to If-variant
                    self.warnings.append(
                        f"filter({inner.name}(...), WHERE ...) has no DQL funcIf equivalent"
                    )

        # -- rate(count(*), 1 minute) -> count() with warning
        if name_low == 'rate':
            self.warnings.append("rate() not directly supported in DQL makeTimeseries; using base aggregation")
            if node.args and isinstance(node.args[0], FunctionCall):
                return self._emit_function(node.args[0])
            return 'count()'

        # -- median(field) -> percentile(field, 50)
        if name_low == 'median':
            if node.args:
                field_str = self._emit_expr(node.args[0])
                return f"percentile({field_str}, 50)"
            return "percentile(duration, 50)"

        # -- stddev(field) -> DQL native stddev() (available in summarize)
        if name_low == 'stddev':
            if node.args:
                field_str = self._emit_expr(node.args[0])
                return f"stddev({field_str})"
            return "stddev(duration)"

        # -- substring(str, start, end) -> substring(str, from:start, to:end)
        # DQL requires named parameters for substring
        if name_low == 'substring' and len(node.args) == 3:
            str_expr = self._emit_expr(node.args[0])
            start_expr = self._emit_expr(node.args[1])
            end_expr = self._emit_expr(node.args[2])
            return f"substring({str_expr}, from:{start_expr}, to:{end_expr})"

        # -- histogram(field, numBars, ceiling, [width]) -> summarize count(), by:{bin(field, width)}
        # NR signature: histogram(attribute, numBars, ceiling)
        #   - numBars: number of bars/buckets to display
        #   - ceiling: upper limit of the histogram range
        #   - width (optional): explicit bar width override
        # DT's bin(field, width) needs width = ceiling / numBars
        if name_low == 'histogram':
            field_expr = self._emit_expr(node.args[0]) if node.args else "duration"
            # Extract bin width from args
            bin_width = None
            if len(node.args) >= 4:
                bin_width = self._emit_expr(node.args[3])
            elif len(node.args) >= 3:
                try:
                    num_bars = float(self._emit_expr(node.args[1]))
                    ceiling = float(self._emit_expr(node.args[2]))
                    if num_bars > 0:
                        raw_width = ceiling / num_bars
                        # Use integer if it divides evenly, float otherwise
                        bin_width = str(int(raw_width)) if raw_width == int(raw_width) else str(raw_width)
                except (ValueError, ZeroDivisionError):
                    bin_width = "1"
            elif len(node.args) >= 2:
                # histogram(field, numBars) -- no ceiling, default to 1s width
                bin_width = "1"
            if not bin_width or bin_width == "0":
                bin_width = "1"

            self.warnings.append(f"histogram({field_expr}) -> count() by bin({field_expr}, {bin_width}) as categoricalBarChart")
            self._histogram_bin_expr = f"bin({field_expr}, {bin_width})"
            return "count()"

        # -- funnel(steps) -> DQL countIf() decomposition with conversion rates
        if name_low == 'funnel':
            # AST args: [column, cond1, label1, cond2, label2, ...]
            # -> summarize step1=countIf(cond1), step2=countIf(cond2), ...
            # -> fieldsAdd conv_1_2 = (step2 / step1) * 100
            self._funnel_steps = []  # Store for post-processing by emit()
            args_iter = iter(node.args)

            # Skip the column argument (first arg, e.g. 'session')
            try:
                next(args_iter)
            except StopIteration:
                return "count()"

            # Collect (condition, label) pairs
            steps = []
            pending_cond = None
            for arg in args_iter:
                if isinstance(arg, (ComparisonCond, LogicalCond, NotCond,
                                    IsNullCond, InListCond, LikeCond, RLikeCond)):
                    pending_cond = arg
                elif isinstance(arg, LiteralExpr) and pending_cond:
                    label = str(arg.value)
                    steps.append((pending_cond, label))
                    pending_cond = None
            # If last condition had no label
            if pending_cond:
                steps.append((pending_cond, f"Step {len(steps)+1}"))

            if not steps:
                return "count()"

            # Build countIf aggregations
            agg_parts = []
            for i, (cond, label) in enumerate(steps, 1):
                safe_label = re.sub(r'[^a-zA-Z0-9_]', '_', label)
                cond_str = self._emit_condition(cond)
                agg_parts.append(f"step{i}_{safe_label}=countIf({cond_str})")

            # Store steps for fieldsAdd conversion rates
            self._funnel_steps = [(f"step{i+1}_{re.sub(r'[^a-zA-Z0-9_]', '_', label)}", label)
                                  for i, (_, label) in enumerate(steps)]

            self.warnings.append(
                f"FUNNEL decomposed into {len(steps)} countIf() steps with conversion rates. "
                f"Use DT's Funnel tile visualization for best results."
            )
            return ', '.join(agg_parts)

        # -- apdex(t:threshold) -> proper DT Apdex calculation
        if name_low == 'apdex':
            # NR apdex forms:
            #   apdex(0.5)              -> threshold only
            #   apdex(duration, 0.5)    -> field + threshold
            #   apdex(duration, t:3)    -> field + t:N syntax
            #   apdex(duration, t:0.5)  -> field + t:N syntax
            #
            # DQL has NO apdex() function. Must decompose into multi-step:
            #   | summarize satisfied=countIf(duration < T), tolerating=countIf(duration >= T and duration < 4T), total=count()
            #   | fieldsAdd apdex = (toDouble(satisfied) + toDouble(tolerating) * 0.5) / toDouble(total)
            #
            # CRITICAL: Cannot use single-expression form because it creates
            # nested aggregations (countIf inside arithmetic inside countIf)
            # which DQL rejects with NO_NESTED_AGGREGATIONS error.
            threshold = 0.5  # default
            if node.args:
                for arg in node.args:
                    if isinstance(arg, LiteralExpr) and isinstance(arg.value, (int, float)):
                        threshold = float(arg.value)
                    elif isinstance(arg, FieldRef):
                        # Check for t:N pattern (tokenized as single identifier)
                        t_match = re.match(r'^t:(\d+(?:\.\d+)?)$', arg.name, re.IGNORECASE)
                        if t_match:
                            threshold = float(t_match.group(1))
            frustrated_t = threshold * 4
            self.warnings.append(
                f"apdex(t:{threshold}) decomposed into multi-step: "
                f"summarize satisfied/tolerating/total then fieldsAdd"
            )
            # Emit as a comment + the multi-step pattern
            # We return just the countIf expressions for use in summarize context,
            # but flag that this needs post-processing into multi-step
            self._apdex_decomposition = {
                'threshold': threshold,
                'frustrated': frustrated_t,
            }
            # Return a placeholder that _emit_select will expand into multi-step
            return (
                f"(countIf(duration < {threshold}s) + "
                f"countIf(duration >= {threshold}s and duration < {frustrated_t}s) * 0.5) "
                f"/ count()"
            )

        # -- CASES(WHERE cond, 'label', ...) -> if(cond, "label", else:if(cond2, "label2", else:"Other"))
        # Also handles: CASES(matchesPhrase(field, val) as 'label', ...) -- bare function conditions
        if name_low == 'cases':
            # Args alternate: condition/expression, label, condition/expression, label, ...
            pairs = []
            i = 0
            while i < len(node.args):
                arg = node.args[i]
                if i + 1 < len(node.args):
                    if isinstance(arg, Condition):
                        cond = self._emit_condition(arg)
                        label = self._emit_expr(node.args[i + 1])
                        pairs.append((cond, label))
                        i += 2
                    elif isinstance(arg, FunctionCall):
                        # Bare function condition: matchesPhrase(field, val) as 'label'
                        # Emit as a DQL boolean expression
                        cond = self._emit_function(arg)
                        label = self._emit_expr(node.args[i + 1])
                        pairs.append((cond, label))
                        i += 2
                    else:
                        i += 1
                else:
                    i += 1
            if not pairs:
                return "\"Other\""
            # Build nested if chain: if(cond1, "label1", else:if(cond2, "label2", else:"Other"))
            # DQL requires the third parameter to be named 'else:'
            result = "\"Other\""
            for cond, label in reversed(pairs):
                result = f"if({cond}, {label}, else:{result})"
            return result

        # -- Multi-percentile: percentile(duration, 50, 90, 95, 99)
        if name_low == 'percentile' and len(node.args) >= 3:
            field_str = self._emit_expr(node.args[0])
            pcts = []
            for a in node.args[1:]:
                if isinstance(a, LiteralExpr):
                    pcts.append(int(a.value))
            return ', '.join(f"p{p}=percentile({field_str}, {p})" for p in pcts)

        # -- count(*) -> count()
        if name_low == 'count':
            if not node.args or (len(node.args) == 1 and isinstance(node.args[0], StarExpr)):
                return "count()"
            # count(field) -> countIf(isNotNull(field))
            if len(node.args) == 1:
                field_str = self._emit_expr(node.args[0])
                return f"countIf(isNotNull({field_str}))"

        # -- derivative(attr, time_interval) -> delta(field) / time
        if name_low == 'derivative':
            if node.args:
                field_str = self._emit_expr(node.args[0])
                if len(node.args) >= 2 and isinstance(node.args[1], TimeInterval):
                    ti = node.args[1]
                    self.warnings.append(
                        f"derivative({field_str}, {ti.value} {ti.unit}) -> "
                        f"DQL delta() or rate() over makeTimeseries interval"
                    )
                    return f"delta({field_str})"
                self.warnings.append("derivative() -> DQL delta() function")
                return f"delta({field_str})"
            return "delta(duration)"

        # -- jparse(jsonStr, 'path') or jparse(jsonStr)[key] -> record field access
        if name_low == 'jparse':
            if node.args:
                field_str = self._emit_expr(node.args[0])
                if len(node.args) >= 2:
                    path_arg = node.args[1]
                    if isinstance(path_arg, LiteralExpr) and isinstance(path_arg.value, str):
                        # jparse(field, '$.key') -> field[`key`]
                        path = path_arg.value.lstrip('$').lstrip('.')
                        return f"{field_str}[`{path}`]"
                self.warnings.append("jparse() -> access JSON fields directly in DQL (record type)")
                return field_str
            return "/* jparse() */"

        # -- clamp_max(value, max) -> if(value > max, max, value)
        if name_low == 'clamp_max':
            if len(node.args) >= 2:
                val_str = self._emit_expr(node.args[0])
                max_str = self._emit_expr(node.args[1])
                return f"if({val_str} > {max_str}, {max_str}, else:{val_str})"
            args_str = ', '.join(self._emit_expr(a) for a in node.args)
            return f"clamp_max({args_str})"

        # -- clamp_min(value, min) -> if(value < min, min, value)
        if name_low == 'clamp_min':
            if len(node.args) >= 2:
                val_str = self._emit_expr(node.args[0])
                min_str = self._emit_expr(node.args[1])
                return f"if({val_str} < {min_str}, {min_str}, else:{val_str})"
            args_str = ', '.join(self._emit_expr(a) for a in node.args)
            return f"clamp_min({args_str})"

        # -- cdfPercentage(attr, threshold1, threshold2, ...) -> countIf(attr <= t)/count()*100
        if name_low == 'cdfpercentage':
            if len(node.args) >= 2:
                field_str = self._emit_expr(node.args[0])
                parts = []
                for arg in node.args[1:]:
                    t_str = self._emit_expr(arg)
                    parts.append(f"(100.0 * countIf({field_str} <= {t_str}) / count())")
                self.warnings.append(
                    "cdfPercentage() -> computed as countIf(field <= threshold) / count() * 100"
                )
                return ', '.join(parts)
            return "/* cdfPercentage() requires field and threshold args */"

        # -- bucketPercentile(bucket_attr, p1, p2, ...) -> percentile(attr, p)
        if name_low == 'bucketpercentile':
            if node.args:
                field_str = self._emit_expr(node.args[0])
                if len(node.args) >= 2:
                    pcts = []
                    for a in node.args[1:]:
                        if isinstance(a, LiteralExpr):
                            pcts.append(int(a.value))
                    self.warnings.append(
                        "bucketPercentile() (Prometheus histogram) -> DQL percentile(). "
                        "Ensure metric uses _bucket suffix."
                    )
                    if pcts:
                        return ', '.join(f"p{p}=percentile({field_str}, {p})" for p in pcts)
                # Default percentiles: 1, 25, 50, 75, 99
                return (f"p1=percentile({field_str}, 1), p25=percentile({field_str}, 25), "
                        f"p50=percentile({field_str}, 50), p75=percentile({field_str}, 75), "
                        f"p99=percentile({field_str}, 99)")
            return "percentile(duration, 50)"

        # -- getField(result, 'key') -> result[`key`]
        if name_low == 'getfield':
            if len(node.args) >= 2:
                obj_str = self._emit_expr(node.args[0])
                key_arg = node.args[1]
                if isinstance(key_arg, LiteralExpr) and isinstance(key_arg.value, str):
                    return f"{obj_str}[`{key_arg.value}`]"
                key_str = self._emit_expr(key_arg)
                return f"{obj_str}[{key_str}]"
            if node.args:
                return self._emit_expr(node.args[0])
            return "/* getField() */"

        # -- cardinality() -> emit warning (no DQL equivalent)
        if name_low == 'cardinality':
            self.warnings.append("cardinality() has no direct DQL equivalent; use countDistinct() on dimensions")
            if node.args:
                field_str = self._emit_expr(node.args[0])
                return f"countDistinct({field_str})"
            return "/* cardinality() -> use DT metric browser */"

        # -- predictLinear(attr, seconds) -> Davis AI forecast
        if name_low == 'predictlinear':
            self.warnings.append("predictLinear() -> use Dynatrace Davis AI predictions")
            if node.args:
                return self._emit_expr(node.args[0])
            return "/* predictLinear() -> Davis AI */"

        # -- blob() -> not supported
        if name_low == 'blob':
            self.warnings.append("blob() binary data handling not supported in DQL")
            if node.args:
                return self._emit_expr(node.args[0])
            return "/* blob() not supported */"

        # -- mapKeys() / mapValues() -> record field access
        if name_low in ('mapkeys', 'mapvalues'):
            self.warnings.append(f"{node.name}() -> use record field access in DQL")
            if node.args:
                return self._emit_expr(node.args[0])
            return f"/* {node.name}() -> record access */"

        # -- keyset() / eventType() -> metadata queries
        if name_low in ('keyset', 'eventtype'):
            self.warnings.append(f"{node.name}() -> use DT Schema browser")
            return f"/* {node.name}() -> use DT Schema browser */"

        # -- bytecountestimate() -> data volume queries
        if name_low == 'bytecountestimate':
            self.warnings.append("bytecountestimate() -> use DT Data Explorer for ingest volume")
            if node.args:
                return f"/* bytecountestimate({self._emit_expr(node.args[0])}) */"
            return "/* bytecountestimate() -> DT Data Explorer */"

        # -- Generic function mapping
        return self._emit_function_call(node)

    def _emit_function_call(self, node: ASTNode) -> str:
        if not isinstance(node, FunctionCall):
            return self._emit_expr(node)
        name_low = node.name.lower()
        dt_func = FUNC_MAP.get(name_low, node.name)

        # DQL if() requires the third parameter to be named 'else:'
        # NR: if(cond, trueVal, falseVal) -> DQL: if(cond, trueVal, else:falseVal)
        if name_low == 'if' and len(node.args) >= 3:
            cond_str = self._emit_condition(node.args[0]) if isinstance(node.args[0], Condition) else self._emit_expr(node.args[0])
            true_str = self._emit_expr(node.args[1])
            false_str = self._emit_expr(node.args[2])
            return f"if({cond_str}, {true_str}, else:{false_str})"

        # DQL indexOf() optional 3rd param must be named 'from:'
        # NR: indexOf(str, substr, startPos) -> DQL: indexOf(str, substr, from:startPos)
        if name_low == 'indexof' and len(node.args) >= 3:
            expr_str = self._emit_expr(node.args[0])
            substr_str = self._emit_expr(node.args[1])
            from_str = self._emit_expr(node.args[2])
            return f"indexOf({expr_str}, {substr_str}, from:{from_str})"

        # DQL round() optional 2nd param must be named 'scale:'
        # NR: round(val, precision) -> DQL: round(val, scale:precision)
        if name_low == 'round' and len(node.args) >= 2:
            val_str = self._emit_expr(node.args[0])
            scale_str = self._emit_expr(node.args[1])
            return f"round({val_str}, scale:{scale_str})"

        # NR: capture(field, 'regex_pattern') -> DQL: parse(field, "DPL_PATTERN")
        # Uses RegexToDPL converter to translate regex named groups to DPL matchers
        if name_low == 'capture' and len(node.args) >= 2:
            field_str = self._emit_expr(node.args[0])
            pattern_arg = node.args[1]
            # Extract the regex string from the literal
            if isinstance(pattern_arg, LiteralExpr):
                regex_str = str(pattern_arg.value).strip("'\"")
                try:
                    from transformers.converters import RegexToDPLConverter
                    converter = RegexToDPLConverter()
                    dpl_pattern, capture_names = converter.convert(regex_str)
                    if dpl_pattern:
                        return f'parse({field_str}, "{dpl_pattern}")'
                except Exception:
                    pass
                # Fallback: emit as extract with original regex
                self.warnings.append(
                    "capture() regex could not be converted to DPL; using extract() with original pattern"
                )
                return f'extract({field_str}, "{regex_str}")'

        args_str = ', '.join(self._emit_expr(a) for a in node.args)
        return f"{dt_func}({args_str})"

    # -- Conditions --

    def _emit_condition(self, cond: Condition) -> str:
        if isinstance(cond, LogicalCond):
            left = self._emit_condition(cond.left)
            right = self._emit_condition(cond.right)
            op = cond.op.lower()  # and, or
            return f"{left} {op} {right}"

        if isinstance(cond, NotCond):
            inner = self._emit_condition(cond.operand)
            return f"not({inner})"

        if isinstance(cond, ComparisonCond):
            # -- INTERCEPT: aparse(field, 'pattern') = 'value' -> field == 'reconstructed' --
            # NR aparse extracts the wildcard portion. If compared to a literal,
            # we can reconstruct the full string and emit a direct equality check.
            if isinstance(cond.left, FunctionCall) and cond.left.name.lower() == 'aparse':
                if len(cond.left.args) >= 2 and isinstance(cond.right, LiteralExpr):
                    field_expr = self._emit_expr(cond.left.args[0])
                    pattern_node = cond.left.args[1]
                    value = str(cond.right.value)
                    op = '==' if cond.op == '=' else cond.op

                    if isinstance(pattern_node, LiteralExpr):
                        pattern = str(pattern_node.value)
                        # Count wildcards (% or *)
                        wildcards = pattern.count('%') + pattern.count('*')
                        if wildcards == 1:
                            # Single wildcard -> reconstruct full string
                            full_str = pattern.replace('%', value).replace('*', value)
                            if op in ('==', '!='):
                                return f'{field_expr} {op} "{full_str}"'
                            else:
                                # For contains/startsWith checks with the pattern prefix
                                prefix = pattern.split('%')[0].split('*')[0]
                                if prefix and op == '==':
                                    return f'startsWith({field_expr}, "{prefix}") and endsWith({field_expr}, "{value}")'

                    # Fallback: use contains for the value part
                    self.warnings.append("aparse() converted to contains() -- verify match logic")
                    return f'contains({field_expr}, "{value}")'

            left = self._emit_expr(cond.left)
            right = self._emit_expr(cond.right)
            op = '==' if cond.op == '=' else cond.op
            # Smart remap: if filtering http.request.path against a full URL, use http.url
            if left == 'http.request.path' and isinstance(cond.right, LiteralExpr):
                val = str(cond.right.value)
                if val.startswith('http://') or val.startswith('https://'):
                    left = 'http.url'
            return f"{left} {op} {right}"

        if isinstance(cond, IsNullCond):
            expr = self._emit_expr(cond.expr)
            return f"isNotNull({expr})" if cond.negated else f"isNull({expr})"

        if isinstance(cond, InListCond):
            expr = self._emit_expr(cond.expr)
            vals = ', '.join(self._emit_expr(v) for v in cond.values)
            neg = "not " if cond.negated else ""
            return f"{neg}in({expr}, {{{vals}}})"

        if isinstance(cond, LikeCond):
            return self._emit_like(cond)

        if isinstance(cond, RLikeCond):
            expr = self._emit_expr(cond.expr)
            neg = "not " if cond.negated else ""
            # Convert RE2 regex to DPL pattern for matches()
            # DPL uses * for .*, ? for ., no anchoring needed
            dpl_pattern = cond.pattern
            dpl_pattern = dpl_pattern.replace('.*', '*').replace('.+', '?*')
            dpl_pattern = dpl_pattern.replace('.', '?')
            # Strip regex anchors
            dpl_pattern = dpl_pattern.lstrip('^').rstrip('$')
            return f'{neg}matches({expr}, "{dpl_pattern}")'

        if isinstance(cond, InSubqueryCond):
            # Should have been extracted already, but emit as comment if not
            self.warnings.append("InSubqueryCond should have been extracted to lookup")
            return "true"

        return "true"

    def _emit_like(self, cond: LikeCond) -> str:
        """Convert LIKE pattern to DQL contains/startsWith/endsWith."""
        expr = self._emit_expr(cond.expr)
        p = cond.pattern
        neg_wrap = lambda s: f"not({s})" if cond.negated else s

        # Smart remap: if filtering http.request.path against full URL pattern, use http.url
        if expr == 'http.request.path' and (p.startswith('http://') or p.startswith('https://')):
            expr = 'http.url'

        # %pattern% -> contains
        if p.startswith('%') and p.endswith('%') and len(p) > 2:
            inner = p[1:-1]
            return neg_wrap(f'contains({expr}, "{inner}")')
        # pattern% -> startsWith
        if p.endswith('%') and not p.startswith('%'):
            inner = p[:-1]
            return neg_wrap(f'startsWith(toString({expr}), "{inner}")')
        # %pattern -> endsWith
        if p.startswith('%') and not p.endswith('%'):
            inner = p[1:]
            return neg_wrap(f'endsWith(toString({expr}), "{inner}")')
        # No wildcard -> exact match
        if '%' not in p:
            op = '!=' if cond.negated else '=='
            return f'{expr} {op} "{p}"'
        # Complex pattern with % in middle -> matchesPhrase
        regex = p.replace('%', '.*').replace('_', '.')
        return neg_wrap(f'matchesPhrase({expr}, "{regex}")')

    # -- Expressions --

    def _emit_expr(self, node: ASTNode) -> str:
        if isinstance(node, StarExpr):
            return '*'
        if isinstance(node, LiteralExpr):
            return self._emit_literal(node)
        if isinstance(node, FieldRef):
            return self._map_field(node.name)
        if isinstance(node, FunctionCall):
            return self._emit_function(node)
        if isinstance(node, BinaryOp):
            left = self._emit_expr(node.left)
            right = self._emit_expr(node.right)
            # Simplify duration.ms/1000 -> duration (DT duration is a typed field,
            # no manual ms->seconds conversion needed)
            if left == 'duration' and node.op == '/' and right in ('1000', '1000.0'):
                return 'duration'
            # Simplify duration*1000 or similar ms conversions
            if left == 'duration' and node.op == '*' and right in ('1000', '1000.0'):
                return 'duration'
            return f"{left} {node.op} {right}"
        if isinstance(node, UnaryMinus):
            return f"-{self._emit_expr(node.operand)}"
        if isinstance(node, TimeInterval):
            return f"{node.value}"
        if isinstance(node, Condition):
            return self._emit_condition(node)
        return str(node)

    def _emit_literal(self, node: LiteralExpr) -> str:
        if isinstance(node.value, str):
            return f'"{node.value}"'
        if isinstance(node.value, bool):
            return 'true' if node.value else 'false'
        if node.value is None:
            return 'null'
        return str(node.value)

    def _validate_no_nested_aggregations(self, dql: str) -> str:
        """Check emitted DQL for nested aggregation patterns.

        DQL error NO_NESTED_AGGREGATIONS occurs when an aggregation function
        contains another aggregation function as an argument. This detects
        common patterns and adds warnings.
        """
        agg_funcs = ['countIf', 'count', 'sum', 'avg', 'min', 'max',
                     'percentile', 'median', 'countDistinctExact', 'countDistinctApprox',
                     'collectArray', 'collectDistinct', 'stddev', 'takeAny', 'takeFirst', 'takeLast']
        agg_pattern = '|'.join(re.escape(f) for f in agg_funcs)

        # Find aggregation calls and check if their arguments contain other agg calls
        # Simple heuristic: find funcName( and check if before the matching ) there's another funcName(
        for func in agg_funcs:
            pattern = func + '('
            idx = 0
            while True:
                idx = dql.find(pattern, idx)
                if idx == -1:
                    break
                # Find matching close paren
                depth = 1
                pos = idx + len(pattern)
                while pos < len(dql) and depth > 0:
                    if dql[pos] == '(':
                        depth += 1
                    elif dql[pos] == ')':
                        depth -= 1
                    pos += 1
                # Extract the argument string
                arg_str = dql[idx + len(pattern):pos - 1]
                # Check if it contains another aggregation function call
                for inner_func in agg_funcs:
                    if inner_func + '(' in arg_str:
                        self.warnings.append(
                            f"NESTED AGGREGATION DETECTED: {func}() contains {inner_func}() "
                            f"which DQL will reject with NO_NESTED_AGGREGATIONS. "
                            f"Decompose into: summarize step | fieldsAdd calculation"
                        )
                        break
                idx = pos
        return dql

    def _map_field(self, name: str) -> str:
        """Map NR field to DT field, with context awareness.

        In METRIC/K8S query contexts, generic dimension field names like
        'id', 'target', 'topic' are preserved as-is because they're custom
        metric dimensions (e.g., Confluent Cloud Kafka metrics).

        In span/log contexts, they get mapped normally (e.g., id -> span.id).
        """
        low = name.lower()

        # In metric context, don't remap ambiguous dimension names
        query_class = getattr(self, '_query_class', 'spans')
        if query_class in ('METRIC',) or (isinstance(query_class, str) and query_class.startswith('K8S_')):
            if low in self.METRIC_DIMENSION_PASSTHROUGH:
                return name  # Preserve as custom metric dimension

        # Check exact match first
        if name in self.field_map:
            return self.field_map[name]
        # Case-insensitive
        if low in self.field_map:
            return self.field_map[low]
        # Pass through unmapped fields
        return name

    # -- FACET items --

    def _emit_facet_items(self, items: List[FacetItem]) -> str:
        """Emit FACET items as DQL by: clause content.
        DQL uses alias=expr, not expr as alias."""
        parts = []
        for item in items:
            expr_str = self._emit_expr(item.expression)
            if item.alias:
                parts.append(f"{self._sanitize_alias(item.alias)}={expr_str}")
            else:
                parts.append(expr_str)
        return ', '.join(parts)

    # -- Subquery extraction --

    def _extract_subqueries(self, cond: Condition) -> Tuple[Optional[Condition], List[InSubqueryCond]]:
        """Extract InSubqueryCond nodes from a condition tree.
        Returns (remaining_condition, [subquery_conditions])."""
        subqueries: List[InSubqueryCond] = []

        def walk(c: Condition) -> Optional[Condition]:
            if isinstance(c, InSubqueryCond):
                subqueries.append(c)
                return None  # Remove from tree
            if isinstance(c, LogicalCond):
                left = walk(c.left)
                right = walk(c.right)
                if left is None and right is None:
                    return None
                if left is None:
                    return right
                if right is None:
                    return left
                return LogicalCond(c.op, left, right)
            if isinstance(c, NotCond):
                inner = walk(c.operand)
                if inner is None:
                    return None
                return NotCond(inner)
            return c

        remaining = walk(cond)
        return remaining, subqueries

    def _emit_lookup(self, sq: InSubqueryCond, parts: List[str]):
        """Emit a DQL lookup command from a subquery IN condition.

        IN (subquery)     -> lookup + filter isNotNull(sub.field) -- keep matches
        NOT IN (subquery) -> lookup + filter isNull(sub.field)    -- keep non-matches
        """
        field = self._emit_expr(sq.expr)
        sub = sq.subquery
        sub_from = sub.from_clause.lower().replace('_', '').replace('-', '')
        # Subqueries are always against fetchable types (spans, logs, etc.)
        fetch_map = {'transaction': 'spans', 'span': 'spans', 'log': 'logs',
                     'transactionerror': 'spans', 'pageview': 'bizevents'}
        fetch_type = fetch_map.get(sub_from, 'spans')
        sel_field = self._emit_expr(sub.select_items[0].expression)

        sub_filter = ''
        if sub.where_clause:
            sub_filter = f" | filter {self._emit_condition(sub.where_clause)}"

        parts.append(
            f'| lookup [fetch {fetch_type}{sub_filter} | fields {sel_field}], '
            f'sourceField:{field}, lookupField:{sel_field}, prefix:"sub."'
        )

        # IN -> keep matched rows; NOT IN -> keep unmatched rows
        null_check = 'isNull' if sq.negated else 'isNotNull'
        parts.append(f'| filter {null_check}(sub.{sel_field})')
