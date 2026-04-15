"""Ruby APM agent migration."""

from __future__ import annotations

from typing import Any, Dict

from .base import AgentOrchestrator, AgentResult


class RubyAgent(AgentOrchestrator):
    LANGUAGE = "ruby"

    def uninstall_nr(self, host: Dict[str, Any], dry_run: bool = True) -> AgentResult:
        plan = self._plan(host, "uninstall_nr")
        self._action(
            plan,
            "remove-gem",
            "Remove the newrelic_rpm gem from Gemfile + bundle lock",
            "# edit Gemfile, remove `gem 'newrelic_rpm'`\nbundle install",
        )
        self._action(
            plan,
            "delete-config",
            "Remove config/newrelic.yml",
            "rm -f config/newrelic.yml",
        )
        self._action(
            plan,
            "restart-app",
            "Restart puma / unicorn / passenger",
            "systemctl restart <app-service>",
        )
        return self._ok(plan)

    def install_oneagent(self, host: Dict[str, Any], dry_run: bool = True) -> AgentResult:
        plan = self._plan(host, "install_oneagent")
        self._action(
            plan,
            "host-oneagent",
            "Install host-level OneAgent (auto-instruments Ruby)",
            "curl -o /tmp/Dynatrace-OneAgent.sh "
            "'${DT_URL}/api/v1/deployment/installer/agent/unix/default/latest' "
            "-H 'Authorization: Api-Token ${DT_PAAS_TOKEN}' && "
            "sudo /bin/sh /tmp/Dynatrace-OneAgent.sh",
        )
        return self._ok(plan)

    def install_otel_fallback(
        self, host: Dict[str, Any], dry_run: bool = True
    ) -> AgentResult:
        plan = self._plan(host, "install_otel")
        self._action(
            plan,
            "add-otel-gem",
            "Add OTel instrumentation gems",
            "bundle add opentelemetry-sdk opentelemetry-instrumentation-all opentelemetry-exporter-otlp",
        )
        self._action(
            plan,
            "configure-env",
            "Set OTLP env vars; require 'opentelemetry/sdk' at boot",
            "export OTEL_EXPORTER_OTLP_ENDPOINT=${DT_URL}/api/v2/otlp\n"
            "export OTEL_EXPORTER_OTLP_HEADERS='Authorization=Api-Token ${DT_API_TOKEN}'",
        )
        return self._ok(plan)

    def verify(self, host: Dict[str, Any]) -> AgentResult:
        plan = self._plan(host, "verify")
        self._action(
            plan,
            "check-ruby-process",
            "Confirm OneAgent monitors the Ruby worker process",
            "sudo /opt/dynatrace/oneagent/agent/tools/oneagentctl "
            "--get-monitored-processes | grep -E '(puma|unicorn|passenger)'",
        )
        return self._ok(plan)
