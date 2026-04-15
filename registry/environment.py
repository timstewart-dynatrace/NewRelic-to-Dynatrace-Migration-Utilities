"""
Dynatrace Environment Registry -- Live validation against the real environment.

Central registry that lazy-loads live data from the Dynatrace environment.

Provides:
  - Metric Registry:    Validate dt.* metric keys exist, fuzzy-find corrections
  - Entity Registry:    Resolve service/host/process names and IDs
  - Dashboard Registry: Check for existing dashboards before creating duplicates
  - Segment Registry:   Map NR account/policy scope to DT segments (Gen3
                        replacement for Management Zones)
  - Synthetic Location Registry: Map NR locations to DT public/private locations

All registries are lazy-loaded -- only fetched when first accessed.
Shared across SLOAuditor, NRQLtoDQLConverter, DashboardMigrator, etc.

APIs used (Gen3 default):
  Metrics v2:      GET /api/v2/metrics                        (.live.)
  Entities v2:     GET /api/v2/entities                       (.live.)
  Documents v1:    GET /platform/document/v1/documents         (.apps.)
  Settings v2:     GET /api/v2/settings/objects                (.live.)
                    - builtin:segment (Gen3 replacement for Management Zones)
  Synthetic v2:    GET /api/v2/synthetic/locations             (.live.)
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger()


class DTEnvironmentRegistry:
    """
    Central registry that lazy-loads live data from the Dynatrace environment.

    Provides:
      - Metric Registry:    Validate dt.* metric keys exist, fuzzy-find corrections
      - Entity Registry:    Resolve service/host/process names and IDs
      - Dashboard Registry: Check for existing dashboards before creating duplicates
      - Segment Registry:   Map NR account/policy scope to DT segments
                            (Gen3 replacement for Management Zones)
      - Synthetic Location Registry: Map NR locations to DT public/private locations

    All registries are lazy-loaded -- only fetched when first accessed.
    """

    # Semantic synonyms for fuzzy matching (metrics + entities)
    SYNONYMS = {
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

    def __init__(self, dt_url: str, oauth_token: str = '', api_token: str = '') -> None:
        """
        Args:
            dt_url: Base DT environment URL (either .apps. or .live.)
            oauth_token: OAuth Bearer token for Platform APIs
            api_token: Api-Token for Classic APIs (Metrics v2, Entities v2)
        """
        self.dt_url = dt_url.rstrip('/')
        self.platform_url = self.dt_url.replace('.live.', '.apps.')
        self.live_url = self.dt_url.replace('.apps.', '.live.')
        self.oauth_token = oauth_token
        self.api_token = api_token

        # Lazy-loaded registries
        self._metrics: Optional[set] = None              # set of valid metric keys
        self._metric_display_names: Dict[str, str] = {}  # key -> displayName
        self._metric_units: Dict[str, str] = {}          # key -> unit
        self._metric_search_cache: Dict[str, Optional[str]] = {}  # bad_key -> best_match

        self._entities: Optional[Dict[str, Dict]] = None  # dict: entity_id -> {name, type, tags}
        self._entity_name_index: Dict[str, List[str]] = {}  # lowercase name -> [entity_ids]
        self._entity_type_index: Dict[str, List[str]] = {}  # type -> [entity_ids]

        self._dashboards: Optional[Dict[str, Dict]] = None  # dict: doc_id -> {name, owner, modified}
        self._dashboard_name_index: Dict[str, List[str]] = {}  # lowercase name -> [doc_ids]

        self._mgmt_zones: Optional[Dict[str, Dict]] = None  # dict: mz_id -> {name, rules}
        self._mgmt_zone_name_index: Dict[str, str] = {}     # lowercase name -> mz_id

        self._synth_locations: Optional[Dict[str, Dict]] = None  # dict: location_id -> {name, type, city, ...}
        self._synth_location_name_index: Dict[str, str] = {}    # lowercase city/name -> location_id

        self._load_errors: List[str] = []  # Track API errors for reporting

        # DQL live validation cache
        self._dql_validation_cache: Dict[int, Tuple] = {}  # dql_hash -> (valid, error_msg)

    # --- HTTP helpers --------------------------------------------------------

    def _api_get(self, url: str, domain: str = 'live') -> Optional[Dict]:
        """
        GET request to DT API.
        domain='live'     -> .live. domain, prefers Api-Token
        domain='platform' -> .apps. domain, requires Bearer OAuth
        """
        if domain == 'platform':
            if not self.oauth_token:
                return None
            auth = f'Bearer {self.oauth_token}'
        elif self.api_token:
            auth = f'Api-Token {self.api_token}'
        elif self.oauth_token:
            auth = f'Bearer {self.oauth_token}'
        else:
            return None

        headers = {'Authorization': auth, 'Accept': 'application/json'}
        try:
            req = urllib.request.Request(url, headers=headers, method='GET')
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            body = ''
            try:
                body = e.read().decode('utf-8')[:200]
            except Exception:
                pass
            self._load_errors.append(f"HTTP {e.code} on {url[:80]}: {body}")
            # Retry with OAuth if Api-Token failed
            if domain == 'live' and self.api_token and self.oauth_token and e.code in (401, 403):
                headers['Authorization'] = f'Bearer {self.oauth_token}'
                try:
                    req = urllib.request.Request(url, headers=headers, method='GET')
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        return json.loads(resp.read().decode('utf-8'))
                except Exception:
                    pass
            return None
        except Exception as e:
            self._load_errors.append(f"Error on {url[:80]}: {str(e)[:100]}")
            return None

    def _api_post(self, url: str, payload: Dict, domain: str = 'platform') -> Tuple[Optional[Dict], int]:
        """
        POST request to DT API.
        Returns (response_dict, status_code).
        """
        if domain == 'platform':
            if not self.oauth_token:
                return None, 0
            auth = f'Bearer {self.oauth_token}'
        elif self.api_token:
            auth = f'Api-Token {self.api_token}'
        elif self.oauth_token:
            auth = f'Bearer {self.oauth_token}'
        else:
            return None, 0

        headers = {
            'Authorization': auth,
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        data = json.dumps(payload).encode('utf-8')
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode('utf-8')), resp.status
        except urllib.error.HTTPError as e:
            body = ''
            try:
                body = e.read().decode('utf-8')
            except Exception:
                pass
            try:
                return json.loads(body), e.code
            except Exception:
                return {'error': {'message': body[:500]}}, e.code
        except Exception as e:
            return {'error': {'message': str(e)}}, 0

    # --- DQL Live Validation -------------------------------------------------

    def validate_dql_syntax(self, dql: str) -> Tuple[Optional[bool], str, Optional[Dict]]:
        """
        Validate DQL syntax by submitting to the Grail query API with minimal execution.

        Uses a 1-second timeframe and maxResultRecords=1 to minimize cost.
        The API parses the DQL and returns syntax errors before execution,
        so even queries against missing data will validate syntax correctly.

        Returns:
            (is_valid, error_message, error_details)
            - (True, '', None)                     -- valid DQL
            - (False, 'error text', {details})     -- invalid DQL with error info
            - (None, 'unavailable', None)          -- API not reachable (skip validation)
        """
        if not self.oauth_token:
            return None, 'No OAuth token -- live validation unavailable', None

        # Strip comments from DQL for validation
        dql_clean = '\n'.join(
            line for line in dql.split('\n')
            if line.strip() and not line.strip().startswith('//')
        ).strip()

        if not dql_clean:
            return None, 'Empty DQL after stripping comments', None

        # Check cache
        cache_key = hash(dql_clean)
        if cache_key in self._dql_validation_cache:
            return self._dql_validation_cache[cache_key]

        # Submit to Grail query API
        url = f"{self.platform_url}/platform/storage/query/v1/query:execute"
        # Grail API requires ISO 8601 timestamps, not relative strings
        now = datetime.now(timezone.utc)
        two_hours_ago = now - timedelta(hours=2)
        payload = {
            "query": dql_clean,
            "defaultTimeframeStart": two_hours_ago.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "defaultTimeframeEnd": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "maxResultRecords": 1,
            "requestTimeoutMilliseconds": 5000,
            "locale": "en_US"
        }

        response, status = self._api_post(url, payload, domain='platform')

        if response is None:
            result = (None, 'API unreachable', None)
            self._dql_validation_cache[cache_key] = result
            return result

        # Parse response
        if status == 200:
            # Query executed successfully -- DQL is valid
            result = (True, '', None)
            self._dql_validation_cache[cache_key] = result
            return result

        # Extract error details
        error_msg = ''
        error_details = None

        if isinstance(response, dict):
            error = response.get('error', {})
            if isinstance(error, dict):
                error_msg = error.get('message', '')
                error_details = error
                # DT error format often includes constraintViolations
                violations = error.get('constraintViolations', [])
                if violations:
                    error_msg = '; '.join(
                        v.get('message', '') for v in violations if v.get('message')
                    )
            elif isinstance(error, str):
                error_msg = error

            # Some errors come in 'errorMessage' field directly
            if not error_msg:
                error_msg = response.get('errorMessage', response.get('message', str(response)[:200]))

        # 400 = syntax/semantic error (what we want to catch)
        #        BUT some 400s are authorization errors, not syntax errors
        # 403 = missing scope (valid syntax but can't execute)
        # 429 = rate limited

        # Authorization / permissions errors -- DQL parsed OK but token lacks table access
        auth_error_patterns = [
            'not_authorized_for_table',
            'not authorized',
            'permission',
            'scope',
            'access denied',
            'forbidden',
        ]
        error_lower = error_msg.lower()
        is_auth_error = any(p in error_lower for p in auth_error_patterns)

        if status == 403 or (status == 400 and is_auth_error):
            # DQL parsed OK but we lack permissions -- syntax is valid
            result = (True, f'[AUTH] {error_msg}', None)
            self._dql_validation_cache[cache_key] = result
            return result

        if status == 429:
            # Rate limited -- don't cache, skip validation
            return None, 'Rate limited -- skipping validation', None

        result = (False, error_msg, error_details)
        self._dql_validation_cache[cache_key] = result
        return result

    def parse_dql_error(self, error_msg: str) -> Dict[str, str]:
        """
        Parse a DQL error message into structured hints for auto-fix.

        DT error messages follow patterns like:
        - "'X' isn't allowed here"
        - "Too many positional parameters"
        - "Unknown function 'X'"
        - "Column 'X' does not exist"
        - "Unexpected token 'X' at line N, column M"

        Returns dict with:
            error_type: 'syntax'|'function'|'column'|'parameter'|'unknown'
            bad_token: the problematic token if identifiable
            position: line:col if available
            suggestion: potential fix hint
        """
        result: Dict[str, str] = {'error_type': 'unknown', 'bad_token': '', 'position': '', 'suggestion': ''}

        # "isn't allowed here" -- wrong keyword/syntax
        m = re.search(r"[`'\"](.+?)[`'\"].*?isn't allowed here", error_msg, re.IGNORECASE)
        if m:
            result['error_type'] = 'syntax'
            result['bad_token'] = m.group(1)
            if m.group(1).lower() == 'as':
                result['suggestion'] = "Use 'alias=expr' instead of 'expr as alias'"
            elif m.group(1) == '(':
                result['suggestion'] = "Check for NRQL subqueries or function syntax"
            return result

        # "Too many positional parameters"
        if 'positional parameter' in error_msg.lower():
            result['error_type'] = 'parameter'
            result['suggestion'] = "Name aggregation parameters (e.g., p99=percentile(duration, 99))"
            return result

        # "Unknown function"
        m = re.search(r"[Uu]nknown function\s+[`'\"]?(\w+)[`'\"]?", error_msg)
        if m:
            result['error_type'] = 'function'
            result['bad_token'] = m.group(1)
            return result

        # "Column does not exist"
        m = re.search(r"[Cc]olumn\s+[`'\"]?(.+?)[`'\"]?\s+does not exist", error_msg)
        if m:
            result['error_type'] = 'column'
            result['bad_token'] = m.group(1)
            return result

        # Line/column position
        m = re.search(r'line\s+(\d+).*?column\s+(\d+)', error_msg, re.IGNORECASE)
        if m:
            result['position'] = f"{m.group(1)}:{m.group(2)}"

        return result

    def _paginate(self, base_url: str, items_key: str, domain: str = 'live',
                  max_pages: int = 20) -> List[Dict]:
        """Generic paginated fetch. Returns all items across pages."""
        all_items: List[Dict] = []
        url: Optional[str] = base_url
        pages = 0

        while url and pages < max_pages:
            data = self._api_get(url, domain=domain)
            if not data:
                break

            items = data.get(items_key, [])
            if isinstance(data, list):
                items = data
            all_items.extend(items)

            next_key = data.get('nextPageKey')
            if next_key:
                sep = '&' if '?' in base_url else '?'
                url = f"{base_url}{sep}nextPageKey={urllib.parse.quote(next_key)}"
            else:
                url = None
            pages += 1

        return all_items

    # --- Metric Registry -----------------------------------------------------

    def _load_metrics(self) -> None:
        """Fetch all dt.* and builtin:* metrics from the environment."""
        if self._metrics is not None:
            return

        self._metrics = set()
        self._metric_display_names = {}
        self._metric_units = {}

        for selector in ['dt.*', 'builtin:*']:
            encoded = urllib.parse.quote(selector, safe='*')
            url = f"{self.live_url}/api/v2/metrics?metricSelector={encoded}&fields=displayName,unit&pageSize=500"
            page = 0

            while url and page < 20:
                data = self._api_get(url)
                if not data:
                    break

                for m in data.get('metrics', []):
                    key = m.get('metricId', '')
                    if key:
                        self._metrics.add(key)
                        if m.get('displayName'):
                            self._metric_display_names[key] = m['displayName']
                        if m.get('unit'):
                            self._metric_units[key] = m['unit']

                next_key = data.get('nextPageKey')
                url = f"{self.live_url}/api/v2/metrics?nextPageKey={urllib.parse.quote(next_key)}" if next_key else None
                page += 1

    def metric_exists(self, key: str) -> bool:
        """Check if a metric key exists in the environment."""
        self._load_metrics()
        return key in self._metrics

    def get_metric_info(self, key: str) -> Optional[Dict]:
        """Get display name and unit for a metric."""
        self._load_metrics()
        if key not in self._metrics:
            return None
        return {
            'key': key,
            'displayName': self._metric_display_names.get(key, ''),
            'unit': self._metric_units.get(key, '')
        }

    def find_metric(self, bad_key: str) -> Optional[str]:
        """
        Fuzzy-find the correct metric key for a non-existent one.
        Uses token overlap + semantic synonyms + DT text search fallback.
        """
        if bad_key in self._metric_search_cache:
            return self._metric_search_cache[bad_key]

        self._load_metrics()

        bad_tokens = self._tokenize(bad_key)
        best_match: Optional[str] = None
        best_score = 0.0

        for candidate in self._metrics:
            if not candidate.startswith('dt.'):
                continue
            cand_tokens = self._tokenize(candidate)
            score = self._token_similarity(bad_tokens, cand_tokens)

            # Prefix bonus
            if '.'.join(bad_key.split('.')[:2]) == '.'.join(candidate.split('.')[:2]):
                score += 0.3

            # Length similarity bonus
            len_ratio = min(len(bad_key), len(candidate)) / max(len(bad_key), len(candidate))
            score += len_ratio * 0.1

            if score > best_score:
                best_score = score
                best_match = candidate

        # DT text search fallback
        if best_score < 0.5:
            search_terms = ' '.join(bad_tokens - {'dt', 'builtin'})
            if search_terms:
                encoded = urllib.parse.quote(search_terms)
                url = f"{self.live_url}/api/v2/metrics?text={encoded}&fields=displayName&pageSize=5"
                data = self._api_get(url)
                if data:
                    for m in data.get('metrics', []):
                        key = m.get('metricId', '')
                        if key and key.startswith('dt.'):
                            cand_tokens = self._tokenize(key)
                            score = self._token_similarity(bad_tokens, cand_tokens)
                            if '.'.join(bad_key.split('.')[:2]) == '.'.join(key.split('.')[:2]):
                                score += 0.3
                            if score > best_score:
                                best_score = score
                                best_match = key

        result = best_match if best_score >= 0.4 else None
        self._metric_search_cache[bad_key] = result
        return result

    def validate_metric_map(self, metric_map: Dict[str, str]) -> Dict[str, Dict]:
        """
        Validate every target in a NR->DT metric mapping dict.
        Returns dict of invalid entries: {nr_key: {target, exists, suggestion}}
        """
        self._load_metrics()
        invalid: Dict[str, Dict] = {}

        for nr_key, dt_target in metric_map.items():
            if not dt_target.startswith('dt.'):
                continue
            if dt_target not in self._metrics:
                suggestion = self.find_metric(dt_target)
                invalid[nr_key] = {
                    'target': dt_target,
                    'exists': False,
                    'suggestion': suggestion,
                    'display_name': self._metric_display_names.get(suggestion, '') if suggestion else ''
                }

        return invalid

    def get_all_metrics(self, prefix: str = 'dt.') -> set:
        """Get all metric keys with given prefix."""
        self._load_metrics()
        return {k for k in self._metrics if k.startswith(prefix)}

    # --- Entity Registry -----------------------------------------------------

    def _load_entities(self, entity_type: Optional[str] = None) -> None:
        """
        Fetch entities from the environment.
        entity_type: 'SERVICE', 'HOST', 'PROCESS_GROUP', etc. None = all common types.
        """
        if self._entities is not None and entity_type is None:
            return
        if entity_type and entity_type in self._entity_type_index:
            return

        if self._entities is None:
            self._entities = {}
            self._entity_name_index = {}
            self._entity_type_index = {}

        types_to_fetch = [entity_type] if entity_type else [
            'SERVICE', 'HOST', 'PROCESS_GROUP', 'APPLICATION',
            'SYNTHETIC_TEST', 'HTTP_CHECK'
        ]

        for etype in types_to_fetch:
            if etype in self._entity_type_index:
                continue

            selector = urllib.parse.quote(f'type("{etype}")')
            url = (f"{self.live_url}/api/v2/entities?entitySelector={selector}"
                   f"&fields=properties,tags&pageSize=500")

            entities = self._paginate(url, 'entities')
            self._entity_type_index[etype] = []

            for e in entities:
                eid = e.get('entityId', '')
                name = e.get('displayName', '')
                tags: Dict[str, Any] = {}
                for t in e.get('tags', []):
                    if t.get('value'):
                        tags[t['key']] = t['value']
                    else:
                        tags[t['key']] = True

                self._entities[eid] = {
                    'id': eid, 'name': name, 'type': etype,
                    'properties': e.get('properties', {}),
                    'tags': tags
                }
                self._entity_type_index[etype].append(eid)

                # Name index (lowercase, multiple entities can share names)
                lower_name = name.lower()
                if lower_name not in self._entity_name_index:
                    self._entity_name_index[lower_name] = []
                self._entity_name_index[lower_name].append(eid)

    def find_entity(self, name: str, entity_type: Optional[str] = None) -> Optional[Dict]:
        """
        Find a DT entity by name (exact or fuzzy).
        Returns {id, name, type, properties, tags} or None.
        """
        self._load_entities(entity_type)

        lower = name.lower()

        # Exact match
        if lower in self._entity_name_index:
            ids = self._entity_name_index[lower]
            if entity_type:
                ids = [i for i in ids if self._entities[i]['type'] == entity_type]
            if ids:
                return self._entities[ids[0]]

        # Contains match (NR names often differ slightly)
        best: Optional[Dict] = None
        best_score = 0.0
        for idx_name, ids in self._entity_name_index.items():
            if entity_type:
                ids = [i for i in ids if self._entities[i]['type'] == entity_type]
            if not ids:
                continue

            # Score: prefer contains match, then token overlap
            if lower in idx_name or idx_name in lower:
                score = 0.8
            else:
                name_tokens = self._tokenize(lower)
                idx_tokens = self._tokenize(idx_name)
                score = self._token_similarity(name_tokens, idx_tokens)

            if score > best_score:
                best_score = score
                best = self._entities[ids[0]]

        return best if best_score >= 0.5 else None

    def find_entities_by_type(self, entity_type: str) -> List[Dict]:
        """Get all entities of a type."""
        self._load_entities(entity_type)
        ids = self._entity_type_index.get(entity_type, [])
        return [self._entities[eid] for eid in ids]

    def entity_exists(self, name: str, entity_type: Optional[str] = None) -> bool:
        """Quick check if an entity with this name exists."""
        return self.find_entity(name, entity_type) is not None

    def resolve_service_name(self, nr_name: str) -> Tuple[Optional[str], float]:
        """
        Given a New Relic service/app name, find the matching DT service.
        Returns (dt_entity_id, confidence) or (None, 0).

        NR names often look like: 'ecomr4-web', 'api-products-v1'
        DT names may differ:      'ecomr4-web', 'API Products V1'
        """
        entity = self.find_entity(nr_name, 'SERVICE')
        if entity:
            # Calculate confidence based on match quality
            lower_nr = nr_name.lower()
            lower_dt = entity['name'].lower()
            if lower_nr == lower_dt:
                return entity['id'], 1.0
            elif lower_nr in lower_dt or lower_dt in lower_nr:
                return entity['id'], 0.8
            else:
                return entity['id'], 0.5
        return None, 0.0

    # --- Dashboard Registry --------------------------------------------------

    def _load_dashboards(self) -> None:
        """Fetch all existing dashboards from Documents API."""
        if self._dashboards is not None:
            return

        self._dashboards = {}
        self._dashboard_name_index = {}

        url = f"{self.platform_url}/platform/document/v1/documents?filter=type%3D%3D'dashboard'&page-size=500"
        data = self._api_get(url, domain='platform')
        if not data:
            return

        for doc in data.get('documents', []):
            doc_id = doc.get('id', '')
            name = doc.get('name', '')
            self._dashboards[doc_id] = {
                'id': doc_id, 'name': name,
                'owner': doc.get('owner', ''),
                'modificationInfo': doc.get('modificationInfo', {})
            }
            lower = name.lower()
            if lower not in self._dashboard_name_index:
                self._dashboard_name_index[lower] = []
            self._dashboard_name_index[lower].append(doc_id)

        # Handle pagination
        while data.get('nextPageKey'):
            next_key = data['nextPageKey']
            next_url = f"{self.platform_url}/platform/document/v1/documents?nextPageKey={urllib.parse.quote(next_key)}"
            data = self._api_get(next_url, domain='platform')
            if not data:
                break
            for doc in data.get('documents', []):
                doc_id = doc.get('id', '')
                name = doc.get('name', '')
                self._dashboards[doc_id] = {
                    'id': doc_id, 'name': name,
                    'owner': doc.get('owner', ''),
                    'modificationInfo': doc.get('modificationInfo', {})
                }
                lower = name.lower()
                if lower not in self._dashboard_name_index:
                    self._dashboard_name_index[lower] = []
                self._dashboard_name_index[lower].append(doc_id)

    def dashboard_exists(self, name: str) -> Optional[str]:
        """Check if a dashboard with this name exists. Returns doc_id or None."""
        self._load_dashboards()
        lower = name.lower()
        ids = self._dashboard_name_index.get(lower, [])
        return ids[0] if ids else None

    def find_dashboard(self, name: str) -> Optional[Dict]:
        """Find dashboard by exact or fuzzy name match."""
        self._load_dashboards()
        lower = name.lower()

        # Exact
        if lower in self._dashboard_name_index:
            return self._dashboards[self._dashboard_name_index[lower][0]]

        # Fuzzy
        best: Optional[Dict] = None
        best_score = 0.0
        for dash_name, ids in self._dashboard_name_index.items():
            if lower in dash_name or dash_name in lower:
                score = 0.8
            else:
                score = self._token_similarity(self._tokenize(lower), self._tokenize(dash_name))
            if score > best_score:
                best_score = score
                best = self._dashboards[ids[0]]

        return best if best_score >= 0.6 else None

    def list_dashboards(self) -> List[Dict]:
        """List all dashboards."""
        self._load_dashboards()
        return list(self._dashboards.values())

    # --- Segment Registry (Gen3 replacement for Management Zones) -----------

    def _load_segments(self) -> None:
        """Fetch Gen3 segments (`builtin:segment`)."""
        if self._mgmt_zones is not None:
            return

        self._mgmt_zones = {}
        self._mgmt_zone_name_index = {}

        # Settings v2 API — Gen3 segment schema
        url = f"{self.live_url}/api/v2/settings/objects?schemaIds=builtin:segment&pageSize=500"
        items = self._paginate(url, 'items')

        for item in items:
            obj_id = item.get('objectId', '')
            value = item.get('value', {})
            name = value.get('name', '')
            includes = value.get('includes', {})

            self._mgmt_zones[obj_id] = {
                'id': obj_id, 'name': name, 'includes': includes
            }
            self._mgmt_zone_name_index[name.lower()] = obj_id

    def find_segment(self, name: str) -> Optional[Dict]:
        """Find a Gen3 segment by name (exact or fuzzy)."""
        self._load_segments()
        lower = name.lower()

        if lower in self._mgmt_zone_name_index:
            return self._mgmt_zones[self._mgmt_zone_name_index[lower]]

        best: Optional[Dict] = None
        best_score = 0.0
        for seg_name, seg_id in self._mgmt_zone_name_index.items():
            if lower in seg_name or seg_name in lower:
                score = 0.8
            else:
                score = self._token_similarity(self._tokenize(lower), self._tokenize(seg_name))
            if score > best_score:
                best_score = score
                best = self._mgmt_zones[seg_id]

        return best if best_score >= 0.5 else None

    def list_segments(self) -> List[Dict]:
        """List all Gen3 segments."""
        self._load_segments()
        return list(self._mgmt_zones.values())

    # --- Synthetic Location Registry -----------------------------------------

    def _load_synthetic_locations(self) -> None:
        """Fetch all synthetic locations (public + private)."""
        if self._synth_locations is not None:
            return

        self._synth_locations = {}
        self._synth_location_name_index = {}

        url = f"{self.live_url}/api/v2/synthetic/locations?type=PUBLIC"
        data = self._api_get(url)
        if data:
            for loc in data.get('locations', []):
                self._index_synth_location(loc)

        url = f"{self.live_url}/api/v2/synthetic/locations?type=PRIVATE"
        data = self._api_get(url)
        if data:
            for loc in data.get('locations', []):
                self._index_synth_location(loc)

    def _index_synth_location(self, loc: Dict) -> None:
        """Index a synthetic location for lookup."""
        loc_id = loc.get('entityId', '')
        name = loc.get('name', '')
        city = loc.get('city', '')
        loc_type = loc.get('type', '')

        self._synth_locations[loc_id] = {
            'id': loc_id, 'name': name, 'city': city,
            'type': loc_type,
            'countryCode': loc.get('countryCode', ''),
            'regionCode': loc.get('regionCode', ''),
            'cloudPlatform': loc.get('cloudPlatform', ''),
            'status': loc.get('status', '')
        }

        # Index by name, city, and various tokens
        for key in [name.lower(), city.lower()]:
            if key and key not in self._synth_location_name_index:
                self._synth_location_name_index[key] = loc_id

    def find_synthetic_location(self, nr_location: str) -> Optional[Dict]:
        """
        Map a New Relic location name to a DT synthetic location.
        NR: 'AWS_US_EAST_1', 'Columbus, OH, USA', 'Portland, OR, USA'
        DT: 'N. Virginia', 'Columbus', 'Portland'
        """
        self._load_synthetic_locations()
        lower = nr_location.lower()

        # Direct match
        if lower in self._synth_location_name_index:
            return self._synth_locations[self._synth_location_name_index[lower]]

        # Extract city from NR format: "Columbus, OH, USA" -> "columbus"
        city = lower.split(',')[0].strip()
        if city in self._synth_location_name_index:
            return self._synth_locations[self._synth_location_name_index[city]]

        # AWS region -> DT location: AWS_US_EAST_1 -> N. Virginia
        aws_to_city = {
            'us_east_1': 'n. virginia', 'us_east_2': 'ohio',
            'us_west_1': 'n. california', 'us_west_2': 'oregon',
            'eu_west_1': 'ireland', 'eu_west_2': 'london',
            'eu_central_1': 'frankfurt', 'ap_southeast_1': 'singapore',
            'ap_southeast_2': 'sydney', 'ap_northeast_1': 'tokyo',
            'ap_south_1': 'mumbai', 'sa_east_1': 'sao paulo',
        }
        nr_clean = lower.replace('aws_', '').replace('azure_', '').replace('gcp_', '')
        mapped_city = aws_to_city.get(nr_clean)
        if mapped_city and mapped_city in self._synth_location_name_index:
            return self._synth_locations[self._synth_location_name_index[mapped_city]]

        # Fuzzy token match
        best: Optional[Dict] = None
        best_score = 0.0
        nr_tokens = self._tokenize(lower)
        for loc_name, loc_id in self._synth_location_name_index.items():
            loc_tokens = self._tokenize(loc_name)
            score = self._token_similarity(nr_tokens, loc_tokens)
            if score > best_score:
                best_score = score
                best = self._synth_locations.get(loc_id)

        return best if best_score >= 0.5 else None

    def list_synthetic_locations(self, loc_type: Optional[str] = None) -> List[Dict]:
        """List synthetic locations, optionally filtered by type (PUBLIC/PRIVATE)."""
        self._load_synthetic_locations()
        locs = list(self._synth_locations.values())
        if loc_type:
            locs = [l for l in locs if l['type'] == loc_type]
        return locs

    # --- Shared utilities ----------------------------------------------------

    @staticmethod
    def _tokenize(s: str) -> set:
        """Split a string into lowercase tokens on . _ and space."""
        tokens: set = set()
        for part in re.split(r'[._\s:]+', s):
            if part:
                tokens.add(part.lower())
        return tokens

    def _token_similarity(self, tokens_a: set, tokens_b: set) -> float:
        """Jaccard similarity with semantic synonym support."""
        if not tokens_a or not tokens_b:
            return 0.0

        direct_overlap = tokens_a & tokens_b

        synonym_overlap: set = set()
        for ta in tokens_a:
            if ta in direct_overlap:
                continue
            synonyms = self.SYNONYMS.get(ta, set())
            for tb in tokens_b:
                if tb in synonyms or ta in self.SYNONYMS.get(tb, set()):
                    synonym_overlap.add(ta)
                    break

        total = len(direct_overlap) + len(synonym_overlap) * 0.8
        union = tokens_a | tokens_b
        return total / len(union) if union else 0.0

    # --- Reporting -----------------------------------------------------------

    def summary(self) -> Dict[str, int]:
        """Return counts of loaded registry items."""
        s: Dict[str, int] = {}
        if self._metrics is not None:
            s['metrics'] = len(self._metrics)
            s['metrics_grail'] = sum(1 for k in self._metrics if k.startswith('dt.'))
            s['metrics_classic'] = sum(1 for k in self._metrics if k.startswith('builtin:'))
        if self._entities is not None:
            s['entities'] = len(self._entities)
            for etype, ids in self._entity_type_index.items():
                s[f'entities_{etype.lower()}'] = len(ids)
        if self._dashboards is not None:
            s['dashboards'] = len(self._dashboards)
        if self._mgmt_zones is not None:
            s['segments'] = len(self._mgmt_zones)
        if self._synth_locations is not None:
            s['synthetic_locations'] = len(self._synth_locations)
        if self._load_errors:
            s['load_errors'] = len(self._load_errors)
        return s

    def print_summary(self) -> None:
        """Log human-readable summary of loaded registries."""
        s = self.summary()
        if not s:
            logger.info("Registry: nothing loaded yet")
            return

        logger.info("DT Environment Registry:")
        if 'metrics' in s:
            logger.info(
                "  Metrics: %d (%d Grail, %d Classic)",
                s['metrics'],
                s.get('metrics_grail', 0),
                s.get('metrics_classic', 0),
            )
        if 'entities' in s:
            types_str = ', '.join(
                f"{v} {k.replace('entities_', '')}"
                for k, v in s.items() if k.startswith('entities_')
            )
            logger.info("  Entities: %d (%s)", s['entities'], types_str)
        if 'dashboards' in s:
            logger.info("  Dashboards: %d", s['dashboards'])
        if 'segments' in s:
            logger.info("  Segments: %d", s['segments'])
        if 'synthetic_locations' in s:
            logger.info("  Synthetic Locations: %d", s['synthetic_locations'])
        if 'load_errors' in s:
            logger.warning("  Load errors: %d", s['load_errors'])
