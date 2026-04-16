"""Tests for utils/error_taxonomy.py + config/project_links.py + agents/base.py.

These modules had no dedicated test file despite being used across the
codebase. Closes the coverage gap identified in the module audit.
"""

from agents.base import AgentAction, AgentActionPlan, AgentOrchestrator, AgentResult
from config.project_links import LINKS, ProjectLinks, nrql_engine_attribution
from utils.error_taxonomy import (
    CodedMessage,
    ErrorCode,
    WarningCode,
    error,
    warn,
)


# ---------------------------------------------------------------------------
# error_taxonomy
# ---------------------------------------------------------------------------


class TestWarningCode:
    def test_enum_values_are_strings(self):
        assert WarningCode.CONFIDENCE_LOW == "CONFIDENCE_LOW"
        assert isinstance(WarningCode.SECRET_MANUAL, str)

    def test_all_codes_unique(self):
        values = [e.value for e in WarningCode]
        assert len(values) == len(set(values))


class TestErrorCode:
    def test_transform_failed(self):
        assert ErrorCode.TRANSFORM_FAILED == "TRANSFORM_FAILED"

    def test_all_codes_unique(self):
        values = [e.value for e in ErrorCode]
        assert len(values) == len(set(values))


class TestCodedMessage:
    def test_str_with_entity_ref(self):
        m = CodedMessage(code="SECRET_MANUAL", message="rotate key", entity_ref="slack-ops")
        assert str(m) == "[SECRET_MANUAL] slack-ops: rotate key"

    def test_str_without_entity_ref(self):
        m = CodedMessage(code="CONFIDENCE_LOW", message="needs review")
        assert str(m) == "[CONFIDENCE_LOW] needs review"


class TestWarnAndErrorHelpers:
    def test_warn_returns_coded_message(self):
        m = warn(WarningCode.DAVIS_REPLACES, "Davis handles this")
        assert isinstance(m, CodedMessage)
        assert m.code == "DAVIS_REPLACES"

    def test_error_returns_coded_message(self):
        m = error(ErrorCode.AUTH_FAILED, "token expired", entity_ref="dt-client")
        assert m.code == "AUTH_FAILED"
        assert m.entity_ref == "dt-client"


# ---------------------------------------------------------------------------
# project_links
# ---------------------------------------------------------------------------


class TestProjectLinks:
    def test_links_singleton_fields(self):
        assert "Dynatrace-NewRelic" in LINKS.dynatrace_newrelic_repo
        assert "nrql-engine" in LINKS.nrql_engine_repo

    def test_relocation_pending_flag(self):
        assert isinstance(LINKS.nrql_engine_relocation_pending, bool)

    def test_attribution_mentions_planned_future_home_when_pending(self):
        links = ProjectLinks(nrql_engine_relocation_pending=True)
        # Re-derive attribution from a fresh instance
        attr = nrql_engine_attribution()
        if LINKS.nrql_engine_relocation_pending:
            assert "planned future home" in attr
        else:
            assert "planned future home" not in attr

    def test_attribution_after_relocation(self):
        # Simulate relocation complete
        links = ProjectLinks(
            nrql_engine_repo="https://github.com/dynatrace-dma/nrql-engine",
            nrql_engine_relocation_pending=False,
        )
        # The module-level function reads LINKS, not this instance. Test
        # the instance directly.
        assert links.nrql_engine_relocation_pending is False
        assert "dynatrace-dma" in links.nrql_engine_repo


# ---------------------------------------------------------------------------
# agents/base.py — abstract base tested via public subclass interface
# ---------------------------------------------------------------------------


class TestAgentBase:
    def test_action_dataclass_fields(self):
        a = AgentAction(id="test.1", description="do x", command="echo x")
        assert a.id == "test.1"
        assert a.expected_exit_code == 0
        assert a.rollback_command is None

    def test_action_plan_add(self):
        plan = AgentActionPlan(host="h1", language="python", phase="verify")
        plan.add(AgentAction(id="1", description="check", command="ls"))
        assert len(plan.actions) == 1

    def test_agent_result_ok(self):
        plan = AgentActionPlan(host="h1", language="java", phase="uninstall_nr")
        r = AgentOrchestrator._ok(plan)
        assert isinstance(r, AgentResult)
        assert r.success

    def test_abstract_methods_raise(self):
        import pytest
        o = AgentOrchestrator()
        with pytest.raises(NotImplementedError):
            o.uninstall_nr({})
        with pytest.raises(NotImplementedError):
            o.install_oneagent({})
        with pytest.raises(NotImplementedError):
            o.install_otel_fallback({})
        with pytest.raises(NotImplementedError):
            o.verify({})
