"""Node.js APM agent migration."""

from __future__ import annotations

from typing import Any, Dict

from .base import AgentOrchestrator, AgentResult


class NodeAgent(AgentOrchestrator):
    LANGUAGE = "nodejs"

    def uninstall_nr(self, host: Dict[str, Any], dry_run: bool = True) -> AgentResult:
        plan = self._plan(host, "uninstall_nr")
        self._action(
            plan,
            "uninstall-npm-pkg",
            "Remove the `newrelic` npm dependency",
            "npm uninstall newrelic  # or: yarn remove newrelic / pnpm remove newrelic",
        )
        self._action(
            plan,
            "remove-require",
            "Remove `require('newrelic')` from the app entrypoint",
            "# edit index.js / server.js / app.js and delete the leading "
            "require('newrelic') line",
        )
        self._action(
            plan,
            "delete-config",
            "Remove newrelic.js config file if present",
            "rm -f newrelic.js .newrelic.js",
        )
        return self._ok(plan)

    def install_oneagent(self, host: Dict[str, Any], dry_run: bool = True) -> AgentResult:
        plan = self._plan(host, "install_oneagent")
        self._action(
            plan,
            "host-oneagent",
            "Install host-level OneAgent (auto-instruments Node processes)",
            "curl -o /tmp/Dynatrace-OneAgent.sh "
            "'${DT_URL}/api/v1/deployment/installer/agent/unix/default/latest' "
            "-H 'Authorization: Api-Token ${DT_PAAS_TOKEN}' && "
            "sudo /bin/sh /tmp/Dynatrace-OneAgent.sh",
        )
        self._action(
            plan,
            "restart-node",
            "Restart the Node.js process so OneAgent attaches",
            "pm2 restart all  # or: systemctl restart <app>",
        )
        return self._ok(plan)

    def install_otel_fallback(
        self, host: Dict[str, Any], dry_run: bool = True
    ) -> AgentResult:
        plan = self._plan(host, "install_otel")
        self._action(
            plan,
            "install-otel-pkg",
            "Install OTel Node.js auto-instrumentation",
            "npm install --save @opentelemetry/api @opentelemetry/auto-instrumentations-node",
        )
        self._action(
            plan,
            "configure-env",
            "Set OTLP env vars and require the auto-instrumentation preload",
            "export OTEL_EXPORTER_OTLP_ENDPOINT=${DT_URL}/api/v2/otlp\n"
            "export OTEL_EXPORTER_OTLP_HEADERS='Authorization=Api-Token ${DT_API_TOKEN}'\n"
            "export NODE_OPTIONS='--require @opentelemetry/auto-instrumentations-node/register'",
        )
        return self._ok(plan)

    def verify(self, host: Dict[str, Any]) -> AgentResult:
        plan = self._plan(host, "verify")
        self._action(
            plan,
            "check-process-attached",
            "Confirm OneAgent lists the node process as monitored",
            "sudo /opt/dynatrace/oneagent/agent/tools/oneagentctl "
            "--get-monitored-processes | grep node",
        )
        return self._ok(plan)
