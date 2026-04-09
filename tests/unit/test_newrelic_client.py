"""Tests for NewRelicClient — all public methods with mocked HTTP."""

import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from clients.newrelic_client import NewRelicClient, NerdGraphResponse


@pytest.fixture
def client():
    return NewRelicClient(api_key="NRAK-TEST", account_id="12345", rate_limit=0)


def _mock_response(data, errors=None, status_code=200):
    """Create a mock requests.Response."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = {"data": data, "errors": errors}
    mock.raise_for_status.return_value = None
    return mock


class TestNerdGraphResponse:
    def test_should_be_success_with_no_errors(self):
        r = NerdGraphResponse(data={"test": 1}, errors=None)
        assert r.is_success is True

    def test_should_be_success_with_empty_errors(self):
        r = NerdGraphResponse(data={"test": 1}, errors=[])
        assert r.is_success is True

    def test_should_not_be_success_with_errors(self):
        r = NerdGraphResponse(data=None, errors=[{"message": "bad"}])
        assert r.is_success is False


class TestNewRelicClientInit:
    def test_should_set_us_endpoint_by_default(self):
        c = NewRelicClient("key", "123", rate_limit=0)
        assert "api.newrelic.com" in c.graphql_endpoint

    def test_should_set_eu_endpoint(self):
        c = NewRelicClient("key", "123", region="EU", rate_limit=0)
        assert "api.eu.newrelic.com" in c.graphql_endpoint

    def test_should_set_api_key_header(self):
        c = NewRelicClient("NRAK-TEST", "123", rate_limit=0)
        assert c.session.headers["API-Key"] == "NRAK-TEST"


class TestExecuteQuery:
    def test_should_return_data_on_success(self, client):
        with patch.object(client.session, 'post', return_value=_mock_response({"result": 42})):
            resp = client.execute_query("{ actor { user { name } } }")
            assert resp.is_success
            assert resp.data["result"] == 42

    def test_should_return_error_on_http_failure(self, client):
        import requests as req
        with patch.object(client.session, 'post', side_effect=req.exceptions.ConnectionError("Connection failed")):
            resp = client.execute_query("{ actor { } }")
            assert resp.is_success is False
            assert len(resp.errors) == 1

    def test_should_pass_variables(self, client):
        with patch.object(client.session, 'post', return_value=_mock_response({})) as mock_post:
            client.execute_query("query($id: Int!)", {"id": 1})
            call_kwargs = mock_post.call_args
            payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
            assert "variables" in str(call_kwargs)


class TestGetDashboards:
    def test_should_return_dashboards(self, client):
        search_data = {
            "actor": {
                "entitySearch": {
                    "results": {
                        "entities": [{"guid": "abc", "name": "Test"}],
                        "nextCursor": None
                    }
                }
            }
        }
        detail_data = {
            "actor": {
                "entity": {"guid": "abc", "name": "Test", "pages": []}
            }
        }
        with patch.object(client.session, 'post') as mock:
            mock.side_effect = [
                _mock_response(search_data),
                _mock_response(detail_data),
            ]
            dashboards = client.get_all_dashboards()
            assert len(dashboards) == 1
            assert dashboards[0]["name"] == "Test"

    def test_should_return_empty_on_error(self, client):
        with patch.object(client.session, 'post', return_value=_mock_response(None, [{"message": "err"}])):
            dashboards = client.get_all_dashboards()
            assert dashboards == []


class TestGetDashboardDefinition:
    def test_should_return_full_definition(self, client):
        data = {"actor": {"entity": {"guid": "abc", "name": "My Dash", "pages": []}}}
        with patch.object(client.session, 'post', return_value=_mock_response(data)):
            result = client.get_dashboard_definition("abc")
            assert result["name"] == "My Dash"

    def test_should_return_none_on_error(self, client):
        with patch.object(client.session, 'post', return_value=_mock_response(None, [{"message": "err"}])):
            result = client.get_dashboard_definition("abc")
            assert result is None


class TestGetAlertPolicies:
    def test_should_return_policies_with_conditions(self, client):
        policy_data = {
            "actor": {"account": {"alerts": {"policiesSearch": {
                "policies": [{"id": "1", "name": "Critical"}],
                "nextCursor": None
            }}}}
        }
        condition_data = {
            "actor": {"account": {"alerts": {"nrqlConditionsSearch": {
                "nrqlConditions": [{"id": "c1", "name": "High Error Rate"}],
                "nextCursor": None
            }}}}
        }
        with patch.object(client.session, 'post') as mock:
            mock.side_effect = [
                _mock_response(policy_data),
                _mock_response(condition_data),
            ]
            policies = client.get_all_alert_policies()
            assert len(policies) == 1
            assert policies[0]["name"] == "Critical"
            assert len(policies[0]["conditions"]) == 1


class TestGetAlertConditions:
    def test_should_return_nrql_conditions(self, client):
        data = {
            "actor": {"account": {"alerts": {"nrqlConditionsSearch": {
                "nrqlConditions": [
                    {"id": "c1", "name": "Latency"},
                    {"id": "c2", "name": "Errors"},
                ],
                "nextCursor": None
            }}}}
        }
        with patch.object(client.session, 'post', return_value=_mock_response(data)):
            conditions = client.get_alert_conditions("policy-1")
            assert len(conditions) == 2
            assert all(c["conditionType"] == "NRQL" for c in conditions)


class TestGetNotificationChannels:
    def test_should_return_channels(self, client):
        data = {
            "actor": {"account": {"aiNotifications": {"destinations": {
                "entities": [{"id": "n1", "name": "Slack", "type": "SLACK"}],
                "nextCursor": None
            }}}}
        }
        with patch.object(client.session, 'post', return_value=_mock_response(data)):
            channels = client.get_notification_channels()
            assert len(channels) == 1
            assert channels[0]["type"] == "SLACK"


class TestGetSyntheticMonitors:
    def test_should_return_monitors_with_details(self, client):
        search_data = {
            "actor": {"entitySearch": {"results": {
                "entities": [{"guid": "mon1", "name": "Health Check"}],
                "nextCursor": None
            }}}
        }
        detail_data = {
            "actor": {"entity": {"guid": "mon1", "name": "Health Check", "monitorType": "SIMPLE"}}
        }
        with patch.object(client.session, 'post') as mock:
            mock.side_effect = [_mock_response(search_data), _mock_response(detail_data)]
            monitors = client.get_all_synthetic_monitors()
            assert len(monitors) == 1

    def test_should_return_monitor_details(self, client):
        data = {"actor": {"entity": {"guid": "m1", "monitorType": "BROWSER"}}}
        with patch.object(client.session, 'post', return_value=_mock_response(data)):
            result = client.get_synthetic_monitor_details("m1")
            assert result["monitorType"] == "BROWSER"

    def test_should_return_monitor_script(self, client):
        data = {"actor": {"account": {"synthetics": {"script": {"text": "console.log('ok')"}}}}}
        with patch.object(client.session, 'post', return_value=_mock_response(data)):
            script = client.get_synthetic_monitor_script("m1")
            assert script == "console.log('ok')"

    def test_should_return_none_for_no_script(self, client):
        data = {"actor": {"account": {"synthetics": {"script": None}}}}
        with patch.object(client.session, 'post', return_value=_mock_response(data)):
            assert client.get_synthetic_monitor_script("m1") is None


class TestGetSLOs:
    def test_should_return_slos(self, client):
        data = {
            "actor": {"account": {"serviceLevel": {"indicators": {
                "entities": [{"guid": "slo1", "name": "Availability"}],
                "nextCursor": None
            }}}}
        }
        with patch.object(client.session, 'post', return_value=_mock_response(data)):
            slos = client.get_all_slos()
            assert len(slos) == 1
            assert slos[0]["name"] == "Availability"


class TestGetWorkloads:
    def test_should_return_workloads_with_details(self, client):
        search_data = {
            "actor": {"entitySearch": {"results": {
                "entities": [{"guid": "w1", "name": "Production"}],
                "nextCursor": None
            }}}
        }
        detail_data = {
            "actor": {"entity": {"guid": "w1", "name": "Production", "collection": []}}
        }
        with patch.object(client.session, 'post') as mock:
            mock.side_effect = [_mock_response(search_data), _mock_response(detail_data)]
            workloads = client.get_all_workloads()
            assert len(workloads) == 1

    def test_should_return_workload_details(self, client):
        data = {"actor": {"entity": {"guid": "w1", "name": "Prod", "collection": []}}}
        with patch.object(client.session, 'post', return_value=_mock_response(data)):
            result = client.get_workload_details("w1")
            assert result["name"] == "Prod"


class TestExportAll:
    def test_should_export_all_entity_types(self, client):
        empty_search = {"actor": {"entitySearch": {"results": {"entities": [], "nextCursor": None}}}}
        empty_policies = {"actor": {"account": {"alerts": {"policiesSearch": {"policies": [], "nextCursor": None}}}}}
        empty_channels = {"actor": {"account": {"aiNotifications": {"destinations": {"entities": [], "nextCursor": None}}}}}
        empty_slos = {"actor": {"account": {"serviceLevel": {"indicators": {"entities": [], "nextCursor": None}}}}}

        with patch.object(client.session, 'post') as mock:
            mock.return_value = _mock_response(empty_search)
            # Override for specific queries
            mock.side_effect = [
                _mock_response(empty_search),     # dashboards
                _mock_response(empty_policies),    # alerts
                _mock_response(empty_channels),    # notifications
                _mock_response(empty_search),      # synthetics
                _mock_response(empty_slos),        # slos
                _mock_response(empty_search),      # workloads
            ]
            result = client.export_all()
            assert "metadata" in result
            assert "dashboards" in result
            assert "alert_policies" in result
            assert "slos" in result
            assert "workloads" in result
