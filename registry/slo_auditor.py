"""SLO audit and migration for Dynatrace."""

import re
import json
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple

import structlog

from .environment import DTEnvironmentRegistry
from utils.auth import get_auth_header

logger = structlog.get_logger()


class SLOAuditor:
    """
    Audits existing Dynatrace Gen3 Platform SLOs by evaluating their live status
    and dynamically validating every metric in their DQL against the environment's
    actual metric registry.

    Phase 1 - Evaluate: Fetch SLOs, check evaluation status (is it returning data?)
    Phase 2 - Discover: Build metric registry from GET /api/v2/metrics (all dt.* metrics)
    Phase 3 - Validate: Extract metric refs from DQL, check each against registry
    Phase 4 - Fix: For invalid metrics, search for correct match and replace

    APIs used:
      Platform SLO API: /platform/slo/v1/slos on .apps. domain (Bearer OAuth)
      Metrics v2 API:   /api/v2/metrics on .live. domain (Bearer OAuth or Api-Token)
    """

    # Aggregations NOT valid in timeseries/makeTimeseries
    INVALID_TIMESERIES_AGGS = {'takeLast', 'takeFirst', 'takeAny', 'collectArray', 'collectDistinct'}

    # Valid timeseries aggregations
    VALID_TIMESERIES_AGGS = {'sum', 'avg', 'min', 'max', 'count', 'percentile', 'countDistinct', 'countIf'}

    # Semantic synonyms for fuzzy metric matching
    # If a token in the bad metric matches a synonym of a token in the candidate, count it
    METRIC_SYNONYMS = {
        'error': {'failure', 'errors', 'failed'},
        'failure': {'error', 'errors', 'failed'},
        'errors': {'error', 'failure', 'failed'},
        'failed': {'error', 'failure', 'errors'},
        'response': {'response_time', 'responsetime', 'latency', 'duration'},
        'latency': {'response', 'response_time', 'duration'},
        'time': {'response_time', 'duration'},
        'success': {'successes', 'successcount'},
        'successes': {'success', 'successcount'},
        'total': {'count', 'all'},
        'bytes': {'bytes_rx', 'bytes_tx', 'bytesrx', 'bytestx'},
        'rx': {'bytes_rx', 'received'},
        'tx': {'bytes_tx', 'sent'},
        'memory': {'mem', 'ram'},
        'mem': {'memory', 'ram'},
        'cpu': {'processor', 'compute'},
        'disk': {'storage', 'volume'},
        'net': {'network', 'nic'},
        'network': {'net', 'nic'},
    }

    def __init__(self, dt_url: str, oauth_token: str, api_token: str = '',
                 registry: Optional[DTEnvironmentRegistry] = None):
        """
        Args:
            dt_url: Base DT environment URL (either .apps. or .live.)
            oauth_token: OAuth Bearer token for Platform SLO API
            api_token: Optional Api-Token for Metrics v2 API (falls back to OAuth)
            registry: Optional shared DTEnvironmentRegistry (avoids duplicate API calls)
        """
        self.dt_url = dt_url.rstrip('/')
        # Platform SLO API -> .apps.dynatrace.com
        self.platform_url = self.dt_url.replace('.live.', '.apps.')
        # Metrics v2 API -> .live.dynatrace.com
        self.live_url = self.dt_url.replace('.apps.', '.live.')
        self.oauth_token = oauth_token
        self.api_token = api_token

        # Use shared registry or create own
        self.registry = registry or DTEnvironmentRegistry(dt_url, oauth_token, api_token)

    # --- HTTP helpers --------------------------------------------------------

    def _platform_request(self, url: str, method: str = 'GET', data: bytes = None) -> Optional[Dict]:
        """Request to Platform API (.apps. domain) with Bearer OAuth."""
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.oauth_token}',
            'Accept': 'application/json'
        }
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8') if hasattr(e, 'read') else ''
            logger.warning("Platform API HTTP error", status_code=e.code, body=body[:300])
            return None
        except Exception as e:
            logger.warning("Platform API error", error=str(e))
            return None

    # --- Delegate to shared registry -----------------------------------------

    def metric_exists(self, metric_key: str) -> bool:
        """Check if a metric key exists in the environment registry."""
        return self.registry.metric_exists(metric_key)

    def find_correct_metric(self, bad_metric: str) -> Optional[str]:
        """Find the correct metric key for a bad/invalid metric reference."""
        return self.registry.find_metric(bad_metric)

    # --- DQL parsing ---------------------------------------------------------

    def extract_metrics_from_dql(self, dql: str) -> List[str]:
        """
        Extract all metric key references from a DQL query.

        Looks for patterns like:
          avg(dt.service.request.response_time)
          sum(dt.service.request.count)
          timeseries avg(dt.host.cpu.usage)
          countIf(dt.service.request.count > 0)
        """
        metrics = []
        if not dql:
            return metrics

        # Pattern 1: agg(metric_key) or agg(metric_key, ...)
        agg_pattern = r'(?:avg|sum|min|max|count|percentile|countIf|countDistinct)\s*\(\s*([a-zA-Z][a-zA-Z0-9._:]+)'
        for match in re.finditer(agg_pattern, dql):
            key = match.group(1).strip()
            # Filter out DQL keywords and known non-metrics
            if key not in ('duration', 'timestamp', 'start_time', 'true', 'false', 'null') \
               and not key.startswith('dt.entity.') \
               and ('.' in key):
                metrics.append(key)

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for m in metrics:
            if m not in seen:
                seen.add(m)
                unique.append(m)

        return unique

    # --- SLO API -------------------------------------------------------------

    def fetch_slos(self) -> List[Dict]:
        """Fetch all Gen3 Platform SLOs."""
        slos = []
        url = f"{self.platform_url}/platform/slo/v1/slos?pageSize=500"

        while url:
            data = self._platform_request(url)
            if not data:
                break

            items = data.get('slos', data.get('items', []))
            if isinstance(data, list):
                items = data
            slos.extend(items)

            next_key = data.get('nextPageKey')
            url = f"{self.platform_url}/platform/slo/v1/slos?nextPageKey={next_key}" if next_key else None

        return slos

    def fetch_slo_detail(self, slo_id: str) -> Optional[Dict]:
        """Fetch full Gen3 SLO definition including DQL."""
        url = f"{self.platform_url}/platform/slo/v1/slos/{slo_id}"
        return self._platform_request(url)

    def update_slo(self, slo_id: str, payload: Dict) -> bool:
        """Update a Gen3 Platform SLO via PUT."""
        url = f"{self.platform_url}/platform/slo/v1/slos/{slo_id}"
        data = json.dumps(payload).encode('utf-8')
        result = self._platform_request(url, method='PUT', data=data)
        return result is not None

    # --- Validation ----------------------------------------------------------

    def validate_dql(self, dql: str) -> Tuple[List[str], List[str], str]:
        """
        Full DQL validation:
        1. Extract all metric references
        2. Validate each against live metric registry
        3. Check DQL syntax issues (bad aggs, NRQL leftovers, etc.)
        4. Build fixed DQL with correct metrics

        Returns: (errors, warnings, fixed_dql)
        """
        errors = []
        warnings = []
        fixed = dql

        if not dql or not dql.strip():
            return errors, warnings, fixed

        # --- Phase 1: Validate metric keys against live registry ---
        metrics = self.extract_metrics_from_dql(dql)

        for metric_key in metrics:
            if metric_key.startswith('builtin:'):
                # Classic metric selector in DQL -- definitely wrong
                correct = self.find_correct_metric(metric_key)
                if correct:
                    errors.append(f"Classic metric '{metric_key}' -> Grail: '{correct}'")
                    fixed = fixed.replace(metric_key, correct)
                else:
                    errors.append(f"Classic metric '{metric_key}' has no Grail equivalent -- "
                                  f"check Built-in Metrics on Grail docs")

            elif metric_key.startswith('dt.'):
                if not self.metric_exists(metric_key):
                    # Metric doesn't exist -- find the right one
                    correct = self.find_correct_metric(metric_key)
                    if correct:
                        info = self.registry.get_metric_info(correct)
                        display = info['displayName'] if info else ''
                        errors.append(f"Metric not found: '{metric_key}' -> "
                                      f"suggested: '{correct}' "
                                      f"({display})")
                        fixed = fixed.replace(metric_key, correct)
                    else:
                        errors.append(f"Metric not found: '{metric_key}' -- "
                                      f"no close match in environment")
                # else: metric exists, all good

            elif '.' in metric_key and not metric_key.startswith(('calc:', 'ext:', 'legacy.')):
                # Unknown prefix -- warn
                warnings.append(f"Unknown metric prefix: '{metric_key}' -- "
                                f"expected dt.* for Grail metrics")

        # --- Phase 2: DQL syntax checks ---
        is_timeseries = bool(re.search(r'\btimeseries\b', dql, re.IGNORECASE))
        is_maketimeseries = bool(re.search(r'\bmakeTimeseries\b', dql, re.IGNORECASE))

        # Invalid aggregations in timeseries context
        if is_timeseries or is_maketimeseries:
            for bad_agg in self.INVALID_TIMESERIES_AGGS:
                pattern = rf'\b{bad_agg}\s*\('
                if re.search(pattern, dql):
                    errors.append(f"'{bad_agg}()' not valid in timeseries -- use avg(), sum(), or max()")
                    fixed = re.sub(rf'\b{bad_agg}\s*\(', 'avg(', fixed)

        # NRQL syntax leftovers
        nr_checks = [
            (r'\bFROM\s+\w+\s+SELECT\b', "Contains NRQL syntax (FROM ... SELECT)"),
            (r'\bSELECT\s+', "Contains NRQL SELECT keyword"),
            (r'\bFACET\s+', "Contains NRQL FACET -- should be 'by:'"),
            (r'\bSINCE\s+\d', "Contains NRQL SINCE -- should be 'from:'"),
        ]
        for pattern, message in nr_checks:
            if re.search(pattern, dql, re.IGNORECASE):
                errors.append(message)

        # Single quotes -> double quotes
        if re.search(r"==\s*'[^']*'", dql):
            warnings.append("Single quotes for string comparison -- DQL uses double quotes")
            fixed = re.sub(r"==\s*'([^']*)'", r'== "\1"', fixed)

        # fieldsRename after makeTimeseries
        if is_maketimeseries and 'fieldsRename' in dql:
            mt_pos = dql.lower().find('maketimeseries')
            fr_pos = dql.lower().find('fieldsrename')
            if fr_pos > mt_pos:
                errors.append("fieldsRename cannot follow makeTimeseries")
                fixed = re.sub(r'\|\s*fieldsRename\s+[^\n]+', '', fixed)

        # Gen3 SLOs should produce an 'sli' field
        if 'sli' not in dql and (is_timeseries or is_maketimeseries):
            warnings.append("Gen3 SLO DQL should produce an 'sli' field")

        # Double dots in metric keys
        for metric in re.findall(r'dt\.[a-zA-Z0-9._]+', dql):
            if '..' in metric:
                errors.append(f"Double dot in metric name: '{metric}'")

        return errors, warnings, fixed

    # --- Main audit flow -----------------------------------------------------

    def audit(self, fix: bool = False) -> Dict:
        """
        Full SLO audit:
        1. Fetch all Platform SLOs + their evaluation status
        2. Build metric registry from live environment
        3. For each SLO: extract DQL, validate every metric, check syntax
        4. Optionally fix broken SLOs

        Returns summary dict.
        """
        logger.info("SLO DQL audit starting", phase="Gen3 Platform -- Live Metric Validation")

        # --- Phase 1: Fetch SLOs ---
        logger.info("Fetching Platform SLOs", platform_url=self.platform_url)
        slos = self.fetch_slos()
        logger.info("Found Gen3 Platform SLOs", count=len(slos))

        if not slos:
            logger.warning("No SLOs found",
                           hint="Check OAuth token has slo:slos:read scope and URL resolves to .apps.dynatrace.com")
            return {'total': 0, 'valid': 0, 'warnings': 0, 'errors': 0, 'fixed': 0, 'details': []}

        # --- Phase 2: Build metric registry ---
        logger.info("Loading metric registry from environment")
        # Trigger lazy load via registry
        self.registry._load_metrics()

        if not self.registry._metrics:
            logger.warning("Could not load metric registry -- metric validation will be skipped",
                           hint="Check Api-Token has metrics.read scope, or OAuth has metric read permissions")
        else:
            grail = sum(1 for k in self.registry._metrics if k.startswith('dt.'))
            classic = sum(1 for k in self.registry._metrics if k.startswith('builtin:'))
            logger.info("Registry loaded", total=len(self.registry._metrics), grail=grail, classic=classic)

        # --- Phase 3: Evaluate each SLO ---
        results = {
            'total': len(slos),
            'valid': 0,
            'warnings': 0,
            'errors': 0,
            'fixed': 0,
            'skipped': 0,
            'metrics_checked': 0,
            'metrics_invalid': 0,
            'details': []
        }

        for slo in slos:
            slo_id = slo.get('id', slo.get('objectId', 'unknown'))
            slo_name = slo.get('name', 'Unnamed')

            # Check evaluation status from list response
            slo_status = slo.get('status', slo.get('evaluationStatus', ''))
            slo_eval_pct = slo.get('evaluatedPercentage', slo.get('sloStatus', None))

            # Get full SLO detail
            detail = self.fetch_slo_detail(slo_id)
            if not detail:
                results['skipped'] += 1
                results['details'].append({
                    'id': slo_id, 'name': slo_name, 'status': 'SKIP',
                    'errors': ['Could not fetch SLO detail']
                })
                continue

            # Extract DQL indicator
            custom_sli = detail.get('customSli', {})
            dql_indicator = ''
            if isinstance(custom_sli, dict):
                dql_indicator = custom_sli.get('indicator', '')

            template_sli = detail.get('templateSli', {})

            # Get target from criteria
            criteria = detail.get('criteria', [{}])
            target = criteria[0].get('target', 0) if criteria else 0

            # Get evaluation info from detail
            eval_status = detail.get('status', detail.get('evaluationStatus', slo_status))
            eval_error = detail.get('error', detail.get('evaluationError', ''))

            all_errors = []
            all_warnings = []
            fixed_dql = dql_indicator

            # Flag if SLO evaluation is erroring
            if eval_error:
                all_errors.append(f"SLO evaluation error: {str(eval_error)[:200]}")

            if eval_status and str(eval_status).upper() in ('ERROR', 'FAILURE', 'NO_DATA'):
                all_errors.append(f"SLO evaluation status: {eval_status}")

            if dql_indicator:
                # Full DQL validation with live metric checking
                errors, warnings, fixed = self.validate_dql(dql_indicator)

                # Track metrics stats
                metrics_in_slo = self.extract_metrics_from_dql(dql_indicator)
                results['metrics_checked'] += len(metrics_in_slo)
                for m in metrics_in_slo:
                    if m.startswith('dt.') and not self.metric_exists(m):
                        results['metrics_invalid'] += 1
                    elif m.startswith('builtin:'):
                        results['metrics_invalid'] += 1

                all_errors.extend(errors)
                all_warnings.extend(warnings)
                fixed_dql = fixed
            elif template_sli:
                template_id = template_sli.get('templateId', template_sli.get('id', 'unknown'))
                all_warnings.append(f"Template-based SLO (template: {template_id})")
            else:
                all_warnings.append("No DQL indicator found")

            # --- Determine status ---
            if all_errors:
                status = 'ERROR'
                results['errors'] += 1
            elif all_warnings:
                status = 'WARNING'
                results['warnings'] += 1
            else:
                status = 'VALID'
                results['valid'] += 1

            # --- Log result ---
            if status == 'ERROR':
                logger.error("SLO audit error", slo_id=slo_id[:30], name=slo_name, target=target)
                for e in all_errors:
                    logger.error("SLO error detail", error=e)
                for w in all_warnings:
                    logger.warning("SLO warning detail", warning=w)

                # Show which metrics were found in DQL
                if dql_indicator:
                    metrics_found = self.extract_metrics_from_dql(dql_indicator)
                    if metrics_found:
                        for m in metrics_found:
                            exists = self.metric_exists(m) if m.startswith('dt.') else False
                            info = self.registry.get_metric_info(m)
                            display = info['displayName'] if info else ''
                            suffix = f" ({display})" if display else ""
                            logger.info("Metric status",
                                        status="OK" if exists else "MISSING",
                                        metric=m, display_name=suffix)

                # Auto-fix
                if fix and fixed_dql != dql_indicator and dql_indicator:
                    logger.info("Auto-fixing DQL indicator", slo_id=slo_id)

                    update_payload = {
                        'name': detail.get('name', slo_name),
                        'customSli': {'indicator': fixed_dql}
                    }
                    if detail.get('criteria'):
                        update_payload['criteria'] = detail['criteria']
                    if detail.get('description'):
                        update_payload['description'] = detail['description']
                    if detail.get('tags'):
                        update_payload['tags'] = detail['tags']
                    if detail.get('segments'):
                        update_payload['segments'] = detail['segments']

                    if self.update_slo(slo_id, update_payload):
                        logger.info("SLO fixed", slo_id=slo_id)
                        results['fixed'] += 1

                        # Show what changed
                        old_metrics = set(self.extract_metrics_from_dql(dql_indicator))
                        new_metrics = set(self.extract_metrics_from_dql(fixed_dql))
                        for old_m in old_metrics - new_metrics:
                            new_m = [n for n in new_metrics - old_metrics
                                     if n.split('.')[:2] == old_m.split('.')[:2]]
                            if new_m:
                                logger.info("Metric replaced", old=old_m, new=new_m[0])
                    else:
                        logger.error("SLO fix failed -- update manually in Service-Level Objectives app",
                                     slo_id=slo_id)

            elif status == 'WARNING':
                logger.warning("SLO audit warning", slo_id=slo_id[:30], name=slo_name)
                for w in all_warnings:
                    logger.warning("SLO warning detail", warning=w)

            results['details'].append({
                'id': slo_id, 'name': slo_name, 'status': status,
                'target': target,
                'eval_status': eval_status,
                'dql': dql_indicator[:300] if dql_indicator else None,
                'metrics': self.extract_metrics_from_dql(dql_indicator) if dql_indicator else [],
                'errors': all_errors, 'warnings': all_warnings,
                'fixed_dql': fixed_dql[:300] if fixed_dql != dql_indicator else None
            })

        # --- Summary ---
        logger.info("SLO audit complete",
                     total=results['total'], valid=results['valid'],
                     warnings=results['warnings'], errors=results['errors'])
        if results['skipped']:
            logger.info("SLOs skipped", count=results['skipped'])
        logger.info("Metrics summary", checked=results['metrics_checked'], invalid=results['metrics_invalid'])
        if fix:
            logger.info("SLOs fixed", count=results['fixed'])

        if results['errors'] > 0 and not fix:
            logger.info("Run with --fix-slos to auto-fix broken SLOs", fixable=results['errors'])

        return results
