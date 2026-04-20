"""Shared HTTP primitives for Dynatrace Gen3 clients.

Consolidates:
- `DynatraceResponse` / `ImportResult` dataclasses
- Rate-limited `requests.Session` with retry adapter
- Auth resolution (OAuth2 platform-token exchange + Api-Token fallback)
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests
import structlog
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = structlog.get_logger()


@dataclass
class DynatraceResponse:
    """Response wrapper for any Dynatrace API call."""

    data: Optional[Any]
    status_code: int
    error: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300


@dataclass
class ImportResult:
    """Result of an import/create operation."""

    entity_type: str
    entity_name: str
    success: bool
    dynatrace_id: Optional[str] = None
    error_message: Optional[str] = None


class OAuth2PlatformTokenProvider:
    """Exchange OAuth2 client credentials for a Dynatrace platform bearer token.

    Required for the Automation API and other Gen3 Platform endpoints. If the
    caller does not supply OAuth2 credentials, higher-level clients fall back
    to the Api-Token header (works for Settings 2.0 / Documents on classic
    auth configurations).
    """

    # 60-second safety margin before expiry so callers get a fresh token.
    _REFRESH_MARGIN_SECONDS = 60

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_url: str = "https://sso.dynatrace.com/sso/oauth2/token",
        scope: str = (
            "settings:objects:read settings:objects:write "
            "automation:workflows:read automation:workflows:write "
            "document:documents:read document:documents:write"
        ),
        resource: Optional[str] = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = token_url
        self.scope = scope
        self.resource = resource
        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0
        self._lock = threading.Lock()

    def bearer_header(self) -> str:
        return f"Bearer {self._fetch_token()}"

    def _fetch_token(self) -> str:
        with self._lock:
            now = time.time()
            if self._access_token and now < self._expires_at:
                return self._access_token

            data = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": self.scope,
            }
            if self.resource:
                data["resource"] = self.resource

            response = requests.post(self.token_url, data=data, timeout=30)
            response.raise_for_status()
            body = response.json()
            self._access_token = body["access_token"]
            expires_in = int(body.get("expires_in", 300))
            self._expires_at = now + max(0, expires_in - self._REFRESH_MARGIN_SECONDS)
            return self._access_token


class HttpTransport:
    """Rate-limited session with retry + auth-header resolution."""

    def __init__(
        self,
        rate_limit: float = 5.0,
        api_token: Optional[str] = None,
        oauth: Optional[OAuth2PlatformTokenProvider] = None,
    ) -> None:
        self.rate_limit = rate_limit
        self._api_token = api_token
        self._oauth = oauth
        self._last_request_time = 0.0

        self.session = requests.Session()
        retries = Retry(
            total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)
        self.session.headers.update({"Content-Type": "application/json"})

    # ------------------------------------------------------------------

    def _rate_limit_wait(self) -> None:
        if self.rate_limit > 0:
            elapsed = time.time() - self._last_request_time
            min_interval = 1.0 / self.rate_limit
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    def _auth_header(self, prefer_oauth: bool) -> str:
        if prefer_oauth and self._oauth is not None:
            return self._oauth.bearer_header()
        if self._api_token:
            return token_auth_header(self._api_token)
        if self._oauth is not None:
            return self._oauth.bearer_header()
        raise RuntimeError(
            "No Dynatrace credentials configured — set DYNATRACE_API_TOKEN "
            "or OAuth2 client credentials."
        )

    # ------------------------------------------------------------------

    def request(
        self,
        method: str,
        url: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        prefer_oauth: bool = False,
        headers: Optional[Dict[str, str]] = None,
        files: Optional[Dict[str, Any]] = None,
    ) -> DynatraceResponse:
        self._rate_limit_wait()
        merged_headers = {"Authorization": self._auth_header(prefer_oauth)}
        if headers:
            merged_headers.update(headers)

        # multipart/form-data requests must NOT send Content-Type: application/json.
        # `requests` auto-computes `Content-Type: multipart/form-data; boundary=...`
        # when `files=` is passed, BUT the session default header set at
        # construction time (`{"Content-Type": "application/json"}`) gets merged
        # into the prepared request and WINS over the auto-computed value —
        # resulting in a multipart body with the wrong Content-Type header, which
        # Gen3 tenants reject with 415 Unsupported Media Type.
        #
        # Passing ``Content-Type=None`` in the call-level headers tells requests
        # to drop the session default, letting its multipart-boundary
        # computation set the correct header.
        if files is not None:
            merged_headers["Content-Type"] = None

        try:
            request_kwargs: Dict[str, Any] = {
                "method": method,
                "url": url,
                "params": params,
                "headers": merged_headers,
                "timeout": 60,
            }
            if files is not None:
                # Session default Content-Type is application/json; pass files
                # positional so `requests` computes the multipart boundary.
                request_kwargs["files"] = files
            else:
                request_kwargs["json"] = data
            response = self.session.request(**request_kwargs)
            response_data: Optional[Any] = None
            if response.content:
                try:
                    response_data = response.json()
                except json.JSONDecodeError:
                    response_data = response.text

            if response.status_code >= 400:
                error_msg = (
                    str(response_data) if response_data else response.reason
                )
                return DynatraceResponse(
                    data=response_data,
                    status_code=response.status_code,
                    error=error_msg,
                )
            return DynatraceResponse(
                data=response_data, status_code=response.status_code
            )
        except requests.exceptions.RequestException as exc:
            logger.error("Dynatrace API error", error=str(exc))
            return DynatraceResponse(data=None, status_code=0, error=str(exc))

    # Convenience wrappers --------------------------------------------

    def get(self, url: str, **kwargs: Any) -> DynatraceResponse:
        return self.request("GET", url, **kwargs)

    def post(
        self, url: str, data: Dict[str, Any], **kwargs: Any
    ) -> DynatraceResponse:
        return self.request("POST", url, data=data, **kwargs)

    def post_multipart(
        self,
        url: str,
        files: Dict[str, Any],
        *,
        prefer_oauth: bool = False,
    ) -> DynatraceResponse:
        """POST multipart/form-data — for Gen3 Document API uploads.

        ``files`` follows the ``requests`` library convention:
          - ``{"field": (None, "value")}`` → plain form field
          - ``{"field": ("name.ext", body, "mime/type")}`` → file part

        Content-Type header is auto-computed by ``requests`` with the
        correct boundary; any caller/session default ``application/json``
        is stripped because Gen3 tenants 415 on the wrong media type.
        """
        return self.request(
            "POST", url, files=files, prefer_oauth=prefer_oauth
        )

    def put(
        self, url: str, data: Dict[str, Any], **kwargs: Any
    ) -> DynatraceResponse:
        return self.request("PUT", url, data=data, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> DynatraceResponse:
        return self.request("DELETE", url, **kwargs)


# --------------------------------------------------------------------------


def platform_url(environment_url: str) -> str:
    """Map an environment URL to its Platform (apps.) equivalent.

    Document API + Automation API live on the `apps.` subdomain for SaaS
    tenants; managed/classic tenants expose the same hostname.
    """
    return environment_url.replace(".live.", ".apps.").rstrip("/")


def settings_v2_base(environment_url: str) -> str:
    """Return the Settings 2.0 base URL appropriate for the tenant generation.

    Gen3 SaaS tenants (hostname contains ``.apps.``, e.g.
    ``abc.apps.dynatrace.com`` or ``abc.apps.dynatracelabs.com``) expose
    Settings 2.0 under ``/platform/classic/environment-api/v2`` and reject
    requests to the Classic ``/api/v2`` path with 404. Classic SaaS
    (``.live.``) and Managed tenants keep ``/api/v2``.

    Returns the full base URL including ``/api/v2`` or
    ``/platform/classic/environment-api/v2`` — callers append
    ``/settings/schemas``, ``/settings/objects``, etc.
    """
    base = environment_url.rstrip("/")
    if ".apps." in base:
        return f"{base}/platform/classic/environment-api/v2"
    return f"{base}/api/v2"


def token_auth_header(token: str) -> str:
    """Pick ``Authorization`` header scheme based on Dynatrace token prefix.

    Dynatrace ships two distinct token families:

    * ``dt0c01.*``  — Classic Api-Token  → ``Authorization: Api-Token <t>``
    * ``dt0s01.*``  — Platform OAuth2-issued token
    * ``dt0s16.*``  — Platform Token (static)

    Both ``dt0s01.*`` and ``dt0s16.*`` authenticate against Gen3 APIs
    (Document, Automation, Settings-on-apps) as Bearer tokens. Sending a
    Platform Token with the ``Api-Token`` scheme against an ``.apps.``
    tenant produces::

        401 "Unsupported authorization scheme 'Api-Token'. Dynatrace
        platform accepts Bearer authentication only."
    """
    if token.startswith("dt0c01."):
        return f"Api-Token {token}"
    return f"Bearer {token}"
