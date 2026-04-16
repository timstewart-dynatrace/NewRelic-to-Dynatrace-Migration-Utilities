"""Shared base classes for per-language APM agent migration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class AgentAction:
    """A single step in an agent migration plan.

    Actions are declarative: the tool emits them; an operator or
    orchestration layer executes them. Each action has a unique `id`
    within its plan for rollback.
    """

    id: str
    description: str
    command: str
    expected_exit_code: int = 0
    rollback_command: Optional[str] = None


@dataclass
class AgentActionPlan:
    """An ordered list of AgentAction items for a single host."""

    host: str
    language: str
    phase: str  # "uninstall_nr" | "install_oneagent" | "install_otel" | "verify"
    actions: List[AgentAction] = field(default_factory=list)

    def add(self, action: AgentAction) -> None:
        self.actions.append(action)


@dataclass
class AgentResult:
    """Outcome of a single agent-migration phase."""

    success: bool
    plan: Optional[AgentActionPlan] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class AgentOrchestrator:
    """Base class — per-language agents subclass this."""

    LANGUAGE: str = ""

    def uninstall_nr(
        self, host: Dict[str, Any], dry_run: bool = True
    ) -> AgentResult:
        raise NotImplementedError

    def install_oneagent(
        self, host: Dict[str, Any], dry_run: bool = True
    ) -> AgentResult:
        raise NotImplementedError

    def install_otel_fallback(
        self, host: Dict[str, Any], dry_run: bool = True
    ) -> AgentResult:
        raise NotImplementedError

    def verify(self, host: Dict[str, Any]) -> AgentResult:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Helpers available to subclasses
    # ------------------------------------------------------------------

    def _plan(self, host: Dict[str, Any], phase: str) -> AgentActionPlan:
        return AgentActionPlan(
            host=host.get("name", host.get("hostname", "unknown")),
            language=self.LANGUAGE,
            phase=phase,
        )

    def _action(
        self,
        plan: AgentActionPlan,
        id_suffix: str,
        description: str,
        command: str,
        rollback: Optional[str] = None,
    ) -> None:
        plan.add(
            AgentAction(
                id=f"{plan.phase}.{self.LANGUAGE}.{id_suffix}",
                description=description,
                command=command,
                rollback_command=rollback,
            )
        )

    @staticmethod
    def _ok(plan: AgentActionPlan) -> AgentResult:
        return AgentResult(success=True, plan=plan)
