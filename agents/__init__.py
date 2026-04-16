"""
Per-language APM agent migration orchestrator.

Each submodule targets one New Relic APM language and provides:

  - uninstall_nr(host, dry_run)  : remove the New Relic agent
  - install_oneagent(host, dry_run) : install the Dynatrace OneAgent
  - install_otel_fallback(host, dry_run) : install an OTel SDK instead
  - verify(host) : confirm the swap succeeded

The CLI subcommand is `python migrate.py agents --language <lang>
[--dry-run] [--host <host>]` (see migrate.py).

The orchestrator never executes raw shell commands; it produces
platform-specific **action plans** (an ordered list of commands +
expected outputs) that an operator or an automation layer executes. This
keeps the tool auditable and safe to run against real hosts.
"""

from .base import AgentAction, AgentActionPlan, AgentOrchestrator, AgentResult
from .dotnet import DotNetAgent
from .go_agent import GoAgent
from .java import JavaAgent
from .nodejs import NodeAgent
from .php import PHPAgent
from .python_agent import PythonAgent
from .ruby import RubyAgent

SUPPORTED_LANGUAGES = {
    "java": JavaAgent,
    "dotnet": DotNetAgent,
    "nodejs": NodeAgent,
    "python": PythonAgent,
    "ruby": RubyAgent,
    "php": PHPAgent,
    "go": GoAgent,
}

__all__ = [
    "AgentAction",
    "AgentActionPlan",
    "AgentOrchestrator",
    "AgentResult",
    "DotNetAgent",
    "GoAgent",
    "JavaAgent",
    "NodeAgent",
    "PHPAgent",
    "PythonAgent",
    "RubyAgent",
    "SUPPORTED_LANGUAGES",
]
