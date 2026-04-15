"""Python APM agent migration."""

from __future__ import annotations

from typing import Any, Dict

from .base import AgentOrchestrator, AgentResult


class PythonAgent(AgentOrchestrator):
    LANGUAGE = "python"

    def uninstall_nr(self, host: Dict[str, Any], dry_run: bool = True) -> AgentResult:
        plan = self._plan(host, "uninstall_nr")
        self._action(
            plan,
            "uninstall-pip",
            "Uninstall the `newrelic` pip package",
            "pip uninstall -y newrelic",
        )
        self._action(
            plan,
            "remove-admin-wrapper",
            "Remove `newrelic-admin run-program` wrapper from launch commands",
            "# edit supervisord.conf / systemd unit / Dockerfile CMD and "
            "strip the `newrelic-admin run-program` prefix",
        )
        self._action(
            plan,
            "delete-config",
            "Remove newrelic.ini",
            "rm -f newrelic.ini /etc/newrelic/newrelic.ini",
        )
        return self._ok(plan)

    def install_oneagent(self, host: Dict[str, Any], dry_run: bool = True) -> AgentResult:
        plan = self._plan(host, "install_oneagent")
        self._action(
            plan,
            "host-oneagent",
            "Install host-level OneAgent (auto-instruments Python WSGI/ASGI)",
            "curl -o /tmp/Dynatrace-OneAgent.sh "
            "'${DT_URL}/api/v1/deployment/installer/agent/unix/default/latest' "
            "-H 'Authorization: Api-Token ${DT_PAAS_TOKEN}' && "
            "sudo /bin/sh /tmp/Dynatrace-OneAgent.sh",
        )
        self._action(
            plan,
            "restart-wsgi",
            "Restart gunicorn / uvicorn / uWSGI so OneAgent attaches",
            "systemctl restart <app-service>",
        )
        return self._ok(plan)

    def install_otel_fallback(
        self, host: Dict[str, Any], dry_run: bool = True
    ) -> AgentResult:
        plan = self._plan(host, "install_otel")
        self._action(
            plan,
            "install-otel-pkgs",
            "Install OTel Python auto-instrumentation",
            "pip install opentelemetry-distro opentelemetry-exporter-otlp && "
            "opentelemetry-bootstrap -a install",
        )
        self._action(
            plan,
            "configure-otel",
            "Set OTLP env vars and run via opentelemetry-instrument",
            "export OTEL_EXPORTER_OTLP_ENDPOINT=${DT_URL}/api/v2/otlp\n"
            "export OTEL_EXPORTER_OTLP_HEADERS='Authorization=Api-Token ${DT_API_TOKEN}'\n"
            "opentelemetry-instrument python app.py",
        )
        return self._ok(plan)

    def verify(self, host: Dict[str, Any]) -> AgentResult:
        plan = self._plan(host, "verify")
        self._action(
            plan,
            "check-service-appears",
            "Confirm Python service is visible in DT Smartscape within 5 min",
            "# use the DT UI or entities API to confirm type(SERVICE),"
            "properties.softwareTechnologies contains PYTHON on this host",
        )
        return self._ok(plan)
