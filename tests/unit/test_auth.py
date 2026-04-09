"""Tests for utils/auth.py — auth header detection, OAuth flow, duration conversion."""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.auth import get_auth_header, get_dt_oauth_token, ms_to_dql_duration, nrql_comment


class TestGetAuthHeader:
    def test_should_return_api_token_for_dt0c01(self):
        assert get_auth_header("dt0c01.ABCDEF") == "Api-Token dt0c01.ABCDEF"

    def test_should_return_bearer_for_other_tokens(self):
        assert get_auth_header("eyJhbGciOi...") == "Bearer eyJhbGciOi..."

    def test_should_return_bearer_for_empty_string(self):
        assert get_auth_header("sometoken") == "Bearer sometoken"


class TestNrqlComment:
    def test_should_format_as_single_line_comment(self):
        result = nrql_comment("SELECT count(*)\n  FROM Transaction\n  WHERE x = 1")
        assert result == "// Original NRQL: SELECT count(*) FROM Transaction WHERE x = 1"

    def test_should_handle_empty_string(self):
        assert nrql_comment("") == "// Original NRQL: "


class TestMsToDqlDuration:
    def test_should_convert_days(self):
        assert ms_to_dql_duration(86_400_000) == "1d"
        assert ms_to_dql_duration(172_800_000) == "2d"

    def test_should_convert_hours(self):
        assert ms_to_dql_duration(3_600_000) == "1h"
        assert ms_to_dql_duration(7_200_000) == "2h"

    def test_should_convert_minutes(self):
        assert ms_to_dql_duration(60_000) == "1m"
        assert ms_to_dql_duration(300_000) == "5m"

    def test_should_convert_seconds(self):
        assert ms_to_dql_duration(1000) == "1s"
        assert ms_to_dql_duration(5000) == "5s"

    def test_should_convert_milliseconds(self):
        assert ms_to_dql_duration(500) == "500ms"
        assert ms_to_dql_duration(1) == "1ms"

    def test_should_handle_zero(self):
        assert ms_to_dql_duration(0) == "0s"

    def test_should_handle_negative(self):
        assert ms_to_dql_duration(-100) == "0s"

    def test_should_handle_fractional_ms(self):
        result = ms_to_dql_duration(0.5)
        assert "us" in result or "ms" in result


class TestGetDtOauthToken:
    def test_should_return_none_without_credentials(self):
        assert get_dt_oauth_token("", "", "") is None

    def test_should_return_token_on_success(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"access_token": "test-oauth-token"}
        mock_resp.raise_for_status.return_value = None

        with patch("utils.auth.requests.post", return_value=mock_resp):
            token = get_dt_oauth_token("client-id", "client-secret", "scope1 scope2")
            assert token == "test-oauth-token"

    def test_should_return_none_on_failure(self):
        import requests as req
        with patch("utils.auth.requests.post", side_effect=req.exceptions.ConnectionError("fail")):
            token = get_dt_oauth_token("client-id", "client-secret", "scope1")
            assert token is None
