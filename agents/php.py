"""PHP APM agent migration."""

from __future__ import annotations

from typing import Any, Dict

from .base import AgentOrchestrator, AgentResult


class PHPAgent(AgentOrchestrator):
    LANGUAGE = "php"

    def uninstall_nr(self, host: Dict[str, Any], dry_run: bool = True) -> AgentResult:
        plan = self._plan(host, "uninstall_nr")
        self._action(
            plan,
            "uninstall-nr-pkg",
            "Remove the NR PHP agent package",
            "sudo apt-get remove -y newrelic-php5 newrelic-daemon "
            "# or: sudo yum remove newrelic-php5 newrelic-daemon",
        )
        self._action(
            plan,
            "remove-ini-loader",
            "Remove newrelic.ini from php.d includes",
            "sudo rm -f /etc/php/*/mods-available/newrelic.ini "
            "/etc/php/*/*/conf.d/*-newrelic.ini",
        )
        self._action(
            plan,
            "stop-daemon",
            "Stop the newrelic-daemon",
            "sudo systemctl stop newrelic-daemon && sudo systemctl disable newrelic-daemon",
        )
        self._action(
            plan,
            "restart-fpm",
            "Restart php-fpm so the extension unload takes effect",
            "sudo systemctl restart php-fpm",
        )
        return self._ok(plan)

    def install_oneagent(self, host: Dict[str, Any], dry_run: bool = True) -> AgentResult:
        plan = self._plan(host, "install_oneagent")
        self._action(
            plan,
            "host-oneagent",
            "Install host-level OneAgent (ships the PHP probe)",
            "curl -o /tmp/Dynatrace-OneAgent.sh "
            "'${DT_URL}/api/v1/deployment/installer/agent/unix/default/latest' "
            "-H 'Authorization: Api-Token ${DT_PAAS_TOKEN}' && "
            "sudo /bin/sh /tmp/Dynatrace-OneAgent.sh",
        )
        self._action(
            plan,
            "restart-fpm-again",
            "Restart php-fpm so the DT PHP probe injects",
            "sudo systemctl restart php-fpm nginx",
        )
        return self._ok(plan)

    def install_otel_fallback(
        self, host: Dict[str, Any], dry_run: bool = True
    ) -> AgentResult:
        plan = self._plan(host, "install_otel")
        self._action(
            plan,
            "install-otel-ext",
            "Install the OTel PHP extension",
            "sudo pecl install opentelemetry",
        )
        self._action(
            plan,
            "configure-env",
            "Set OTLP env vars",
            "OTEL_EXPORTER_OTLP_ENDPOINT=${DT_URL}/api/v2/otlp\n"
            "OTEL_EXPORTER_OTLP_HEADERS='Authorization=Api-Token ${DT_API_TOKEN}'",
        )
        return self._ok(plan)

    def verify(self, host: Dict[str, Any]) -> AgentResult:
        plan = self._plan(host, "verify")
        self._action(
            plan,
            "check-php-loaded",
            "Verify php lists the Dynatrace extension",
            "php -m | grep -i dynatrace",
        )
        return self._ok(plan)
