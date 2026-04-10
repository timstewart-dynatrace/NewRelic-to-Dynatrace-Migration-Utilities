"""Roundtrip compilation tests: NRQL -> DQL, optionally validated against live DT."""
import os

from compiler.compiler import NRQLCompiler
from clients.dynatrace_client import DynatraceClient
from tests.integration.conftest import requires_dt, requires_integration


@requires_integration()
class TestCompileRoundtrip:
    def test_should_compile_simple_query(self):
        """Compile a basic NRQL query and verify the result is valid DQL."""
        compiler = NRQLCompiler()
        result = compiler.compile("SELECT count(*) FROM Transaction SINCE 1 hour ago")
        assert result.success, f"Compilation failed: {result.error}"
        assert "fetch" in result.dql

    @requires_dt()
    def test_should_compile_and_validate_against_dt(self):
        """Compile a query and validate the DQL against a live Dynatrace environment.

        Uses validate_connection as a connectivity check, then attempts to run the
        compiled DQL through the Grail API. A 400 response indicates invalid DQL;
        a 200 (even with empty results) indicates structurally valid DQL.
        """
        compiler = NRQLCompiler()
        result = compiler.compile("SELECT count(*) FROM Transaction SINCE 1 hour ago")
        assert result.success, f"Compilation failed: {result.error}"

        client = DynatraceClient(
            api_token=os.environ["DYNATRACE_API_TOKEN"],
            environment_url=os.environ.get("DYNATRACE_ENVIRONMENT_URL", "https://localhost"),
        )
        assert client.validate_connection(), "Cannot connect to Dynatrace environment"

        # Extract the DQL body (skip the // Original NRQL comment line)
        dql_lines = [
            line for line in result.dql.splitlines() if not line.strip().startswith("//")
        ]
        dql_body = "\n".join(dql_lines).strip()

        # Execute the DQL via Grail query endpoint
        url = f"{client.api_v2}/dql/query"
        response = client.post(url, {"query": dql_body, "defaultTimeframeStart": "now()-1h"})
        # 200 = valid DQL (results may be empty), 400 = syntax error
        assert response.is_success, f"DQL validation failed ({response.status_code}): {response.error}"
