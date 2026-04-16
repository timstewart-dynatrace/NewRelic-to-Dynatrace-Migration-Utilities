"""Go APM agent migration.

Go has no runtime-attached agent; NR uses an SDK linked at build time. DT
does not publish a comparable auto-agent for Go — OpenTelemetry SDK is
the recommended path. This module emits OTel-only guidance; OneAgent is
reported as N/A.
"""

from __future__ import annotations

from typing import Any, Dict

from .base import AgentOrchestrator, AgentResult


class GoAgent(AgentOrchestrator):
    LANGUAGE = "go"

    def uninstall_nr(self, host: Dict[str, Any], dry_run: bool = True) -> AgentResult:
        plan = self._plan(host, "uninstall_nr")
        self._action(
            plan,
            "remove-go-mod",
            "Drop the `github.com/newrelic/go-agent/v3/newrelic` dependency",
            "go mod edit -droprequire=github.com/newrelic/go-agent/v3 && go mod tidy",
        )
        self._action(
            plan,
            "remove-instrumented-calls",
            "Delete `newrelic.StartTransaction`, `txn.End()`, handler wrappers",
            "# operator edit: grep -rn 'newrelic\\.' . and remove each call site",
        )
        self._action(
            plan,
            "rebuild-binary",
            "Rebuild the binary without NR SDK",
            "go build -o /usr/local/bin/${APP} ./...",
        )
        return self._ok(plan)

    def install_oneagent(self, host: Dict[str, Any], dry_run: bool = True) -> AgentResult:
        """OneAgent does not auto-instrument Go — return a result flagging OTel."""
        return AgentResult(
            success=False,
            warnings=[
                "Dynatrace OneAgent does not auto-instrument Go binaries. "
                "Use the OTel fallback path instead."
            ],
        )

    def install_otel_fallback(
        self, host: Dict[str, Any], dry_run: bool = True
    ) -> AgentResult:
        plan = self._plan(host, "install_otel")
        self._action(
            plan,
            "add-otel-modules",
            "Add OTel SDK + gRPC OTLP exporter modules",
            "go get go.opentelemetry.io/otel "
            "go.opentelemetry.io/otel/sdk "
            "go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc",
        )
        self._action(
            plan,
            "wire-provider",
            "In main.go, initialize a tracer provider pointing at DT OTLP",
            "// init tracer with:\n"
            "//   otlptracegrpc.WithEndpoint(\"${DT_URL_HOST}:443\")\n"
            "//   otlptracegrpc.WithHeaders(map[string]string{\"Authorization\": \"Api-Token ${DT_API_TOKEN}\"})\n"
            "//   resource.WithAttributes(semconv.ServiceName(\"${APP_NAME}\"))",
        )
        self._action(
            plan,
            "wrap-handlers",
            "Replace NR handler wrappers with `otelhttp.NewHandler`",
            "# operator edit: import go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp",
        )
        return self._ok(plan)

    def verify(self, host: Dict[str, Any]) -> AgentResult:
        plan = self._plan(host, "verify")
        self._action(
            plan,
            "send-test-span",
            "Hit the service; confirm a span arrives in DT traces within 2 min",
            "curl -s http://localhost:${APP_PORT}/healthz",
        )
        return self._ok(plan)
