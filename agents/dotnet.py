"""Microsoft .NET (Framework + Core) APM agent migration."""

from __future__ import annotations

from typing import Any, Dict

from .base import AgentOrchestrator, AgentResult


class DotNetAgent(AgentOrchestrator):
    LANGUAGE = "dotnet"

    def uninstall_nr(self, host: Dict[str, Any], dry_run: bool = True) -> AgentResult:
        plan = self._plan(host, "uninstall_nr")
        self._action(
            plan,
            "stop-iis",
            "Stop IIS / the app service to release the profiler DLL",
            "iisreset /stop",
        )
        self._action(
            plan,
            "uninstall-nr-agent",
            "Uninstall the NR .NET agent MSI / deb / apk",
            "msiexec /x {NewRelicAgent.msi} /qn  # Windows\n"
            "# OR: sudo apt-get remove newrelic-dotnet-agent   # Linux",
        )
        self._action(
            plan,
            "clean-profiler-env-vars",
            "Remove COR_ENABLE_PROFILING / CORECLR_* env vars set for NR",
            '[Environment]::SetEnvironmentVariable("COR_ENABLE_PROFILING", $null, "Machine")\n'
            '[Environment]::SetEnvironmentVariable("CORECLR_ENABLE_PROFILING", $null, "Machine")',
        )
        return self._ok(plan)

    def install_oneagent(self, host: Dict[str, Any], dry_run: bool = True) -> AgentResult:
        plan = self._plan(host, "install_oneagent")
        self._action(
            plan,
            "install-oneagent",
            "Run the Dynatrace OneAgent installer (bundles the .NET profiler)",
            "Start-Process Dynatrace-OneAgent-Windows.exe "
            "'--set-app-log-content-access=true --set-host-group=${DT_HOST_GROUP}'",
        )
        self._action(
            plan,
            "restart-iis",
            "Restart IIS so worker processes pick up the DT profiler",
            "iisreset /start",
        )
        return self._ok(plan)

    def install_otel_fallback(
        self, host: Dict[str, Any], dry_run: bool = True
    ) -> AgentResult:
        plan = self._plan(host, "install_otel")
        self._action(
            plan,
            "install-otel-autoinstr",
            "Install OTel .NET auto-instrumentation",
            "dotnet tool install --global OpenTelemetry.AutoInstrumentation",
        )
        self._action(
            plan,
            "configure-otel",
            "Set OTel OTLP env vars pointing at DT",
            "$env:OTEL_EXPORTER_OTLP_ENDPOINT = '${DT_URL}/api/v2/otlp'\n"
            "$env:OTEL_EXPORTER_OTLP_HEADERS = 'Authorization=Api-Token ${DT_API_TOKEN}'",
        )
        return self._ok(plan)

    def verify(self, host: Dict[str, Any]) -> AgentResult:
        plan = self._plan(host, "verify")
        self._action(
            plan,
            "check-oneagent-state",
            "Confirm OneAgent Windows service is running",
            "Get-Service -Name 'Dynatrace OneAgent' | Select-Object Status",
        )
        return self._ok(plan)
