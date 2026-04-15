"""Java APM agent migration."""

from __future__ import annotations

from typing import Any, Dict

from .base import AgentOrchestrator, AgentResult


class JavaAgent(AgentOrchestrator):
    LANGUAGE = "java"

    def uninstall_nr(self, host: Dict[str, Any], dry_run: bool = True) -> AgentResult:
        plan = self._plan(host, "uninstall_nr")
        agent_jar = host.get("nr_agent_path", "/opt/newrelic/newrelic.jar")
        self._action(
            plan,
            "remove-javaagent-arg",
            f"Remove `-javaagent:{agent_jar}` from JAVA_TOOL_OPTIONS / startup scripts",
            f"sed -i.bak 's|-javaagent:{agent_jar}||g' /etc/default/*-service",
            rollback=f"mv /etc/default/*-service.bak /etc/default/*-service",
        )
        self._action(
            plan,
            "remove-agent-files",
            "Remove NR agent directory",
            "rm -rf /opt/newrelic",
            rollback="# restore from backup tarball captured before uninstall",
        )
        self._action(
            plan,
            "restart-app",
            "Restart application JVM so -javaagent removal takes effect",
            "systemctl restart <app-service>",
        )
        return self._ok(plan)

    def install_oneagent(self, host: Dict[str, Any], dry_run: bool = True) -> AgentResult:
        plan = self._plan(host, "install_oneagent")
        self._action(
            plan,
            "download-installer",
            "Download OneAgent installer using the environment's paas token",
            "curl -o /tmp/Dynatrace-OneAgent.sh "
            "'${DT_URL}/api/v1/deployment/installer/agent/unix/default/latest?arch=x86&flavor=default' "
            "-H 'Authorization: Api-Token ${DT_PAAS_TOKEN}'",
        )
        self._action(
            plan,
            "run-installer",
            "Execute OneAgent installer (idempotent)",
            "sudo /bin/sh /tmp/Dynatrace-OneAgent.sh "
            "APP_LOG_CONTENT_ACCESS=1 HOST_GROUP=${DT_HOST_GROUP}",
            rollback="sudo /opt/dynatrace/oneagent/agent/tools/uninstall.sh",
        )
        return self._ok(plan)

    def install_otel_fallback(
        self, host: Dict[str, Any], dry_run: bool = True
    ) -> AgentResult:
        plan = self._plan(host, "install_otel")
        self._action(
            plan,
            "download-otel-agent",
            "Download OpenTelemetry Java agent",
            "curl -L -o /opt/otel/opentelemetry-javaagent.jar "
            "https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases/latest/download/opentelemetry-javaagent.jar",
        )
        self._action(
            plan,
            "configure-otel-env",
            "Set OTel env vars pointing at DT OTLP endpoint",
            "export OTEL_EXPORTER_OTLP_ENDPOINT=${DT_URL}/api/v2/otlp\n"
            "export OTEL_EXPORTER_OTLP_HEADERS='Authorization=Api-Token ${DT_API_TOKEN}'\n"
            "export OTEL_SERVICE_NAME=${APP_NAME}",
        )
        return self._ok(plan)

    def verify(self, host: Dict[str, Any]) -> AgentResult:
        plan = self._plan(host, "verify")
        self._action(
            plan,
            "check-oneagent-ctl",
            "Confirm OneAgent is running",
            "sudo /opt/dynatrace/oneagent/agent/tools/oneagentctl --get-state",
        )
        self._action(
            plan,
            "check-service-in-smartscape",
            "Confirm the Java service appears in Smartscape within 5 minutes",
            "curl -s -H 'Authorization: Api-Token ${DT_API_TOKEN}' "
            "'${DT_URL}/api/v2/entities?entitySelector=type(SERVICE),fromRelationships.runsOn(type(HOST),entityId(${HOST_ID}))&fields=+properties.technologies'",
        )
        return self._ok(plan)
