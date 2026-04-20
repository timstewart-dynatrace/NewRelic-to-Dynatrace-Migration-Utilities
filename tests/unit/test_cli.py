"""Tests for CLI commands: compile (interactive, file, output) and reference."""

import os

# Add project root to path so migrate.py imports work
import sys
import tempfile

import pytest
from click.testing import CliRunner

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from migrate import cli


@pytest.fixture
def runner():
    return CliRunner()


class TestCompileSingleQuery:
    """Test compile subcommand with a single positional argument."""

    def test_should_compile_simple_query(self, runner):
        result = runner.invoke(cli, ["compile", "SELECT count(*) FROM Transaction"])
        assert result.exit_code == 0
        assert "count()" in result.output

    def test_should_show_help_when_no_args(self, runner):
        result = runner.invoke(cli, ["compile"])
        assert result.exit_code != 0 or "Usage" in result.output or "compile" in result.output


class TestCompileInteractive:
    """Test compile --interactive REPL mode."""

    def test_should_compile_query_and_exit(self, runner):
        user_input = "SELECT count(*) FROM Transaction\nquit\n"
        result = runner.invoke(cli, ["compile", "--interactive"], input=user_input)
        assert result.exit_code == 0
        assert "Interactive Mode" in result.output
        assert "count()" in result.output

    def test_should_handle_exit_command(self, runner):
        result = runner.invoke(cli, ["compile", "--interactive"], input="exit\n")
        assert result.exit_code == 0

    def test_should_handle_q_command(self, runner):
        result = runner.invoke(cli, ["compile", "--interactive"], input="q\n")
        assert result.exit_code == 0

    def test_should_skip_empty_lines(self, runner):
        user_input = "\n\nSELECT count(*) FROM Transaction\nquit\n"
        result = runner.invoke(cli, ["compile", "--interactive"], input=user_input)
        assert result.exit_code == 0
        assert "count()" in result.output

    def test_should_show_reference_on_ref_command(self, runner):
        user_input = "ref\nquit\n"
        result = runner.invoke(cli, ["compile", "--interactive"], input=user_input)
        assert result.exit_code == 0
        assert "Quick Reference" in result.output

    def test_should_handle_eof(self, runner):
        result = runner.invoke(cli, ["compile", "--interactive"], input="")
        assert result.exit_code == 0


class TestCompileBatchFile:
    """Test compile --file batch mode."""

    def test_should_compile_queries_from_file(self, runner):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.nrql', delete=False) as f:
            f.write("# Comment line\n")
            f.write("SELECT count(*) FROM Transaction\n")
            f.write("\n")
            f.write("SELECT average(duration) FROM Transaction\n")
            f.name
        try:
            result = runner.invoke(cli, ["compile", "--file", f.name])
            assert result.exit_code == 0
            assert "count()" in result.output
            assert "avg(" in result.output
            assert "2 queries" in result.output
        finally:
            os.unlink(f.name)

    def test_should_write_output_file(self, runner):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.nrql', delete=False) as infile:
            infile.write("SELECT count(*) FROM Transaction\n")
            infile.write("SELECT avg(duration) FROM Transaction\n")

        outpath = tempfile.mktemp(suffix='.dql')

        try:
            result = runner.invoke(cli, ["compile", "--file", infile.name, "--output", outpath])
            assert result.exit_code == 0
            assert "saved to" in result.output.lower() or "Results saved" in result.output

            with open(outpath, 'r') as f:
                content = f.read()
            assert "-- Original:" in content
            assert "count()" in content
        finally:
            os.unlink(infile.name)
            if os.path.exists(outpath):
                os.unlink(outpath)

    def test_should_skip_comments_and_blanks(self, runner):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.nrql', delete=False) as f:
            f.write("# This is a comment\n")
            f.write("\n")
            f.write("   \n")
            f.write("SELECT count(*) FROM Transaction\n")
            f.write("# Another comment\n")

        try:
            result = runner.invoke(cli, ["compile", "--file", f.name])
            assert result.exit_code == 0
            assert "1 queries" in result.output or "Compiled 1" in result.output
        finally:
            os.unlink(f.name)


class TestReferenceCommand:
    """Test reference subcommand."""

    def test_should_display_reference_table(self, runner):
        result = runner.invoke(cli, ["reference"])
        assert result.exit_code == 0
        assert "Quick Reference" in result.output
        assert "count()" in result.output
        assert "avg(field)" in result.output

    def test_should_display_mappings_with_flag(self, runner):
        result = runner.invoke(cli, ["reference", "--mappings"])
        assert result.exit_code == 0
        assert "Aggregation Mappings" in result.output
        assert "Event Type Mappings" in result.output
        assert "Attribute Mappings" in result.output


class TestBatchCommand:
    """Test batch CSV compilation."""

    def test_should_compile_csv_file(self, runner):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("nrql\n")
            f.write("SELECT count(*) FROM Transaction\n")
            f.write("SELECT avg(duration) FROM Transaction\n")

        outpath = tempfile.mktemp(suffix='.csv')
        try:
            result = runner.invoke(cli, ["batch", "--file", f.name, "--output", outpath])
            assert result.exit_code == 0
            assert "2 succeeded" in result.output

            with open(outpath, 'r') as out:
                content = out.read()
            assert "count()" in content
            assert "avg(" in content
        finally:
            os.unlink(f.name)
            if os.path.exists(outpath):
                os.unlink(outpath)

    def test_should_handle_empty_csv(self, runner):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("nrql\n")
        try:
            result = runner.invoke(cli, ["batch", "--file", f.name])
            assert result.exit_code == 0
        finally:
            os.unlink(f.name)


class TestVersionFlag:
    """Test --version flag."""

    def test_should_show_version(self, runner):
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "1.0.0" in result.output or "nr-to-dt-migration" in result.output


class TestCompileExampleQueries:
    """Test that the example queries file compiles successfully."""

    def test_should_compile_all_example_queries(self, runner):
        examples_path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'examples', 'example_queries.nrql'
        )
        if not os.path.exists(examples_path):
            pytest.skip("examples/example_queries.nrql not found")

        result = runner.invoke(cli, ["compile", "--file", examples_path])
        assert result.exit_code == 0
        assert "succeeded" in result.output


class TestCliMetricMapWiring:
    """Regression tests for gh #14.

    The `compile` and `batch` CLI subcommands previously constructed a bare
    `NRQLCompiler()`, so the 230-entry METRIC_MAP never reached the CLI path
    and every metric lookup warned "Unknown metric — no METRIC_MAP entry".
    These tests confirm CLI-compiled queries now resolve to real DT metric
    keys and cover the three host-metric dotted-prefix additions.
    """

    def test_compile_resolves_apm_service_error_count(self, runner):
        result = runner.invoke(
            cli, ["compile", "SELECT sum(`apm.service.error.count`) FROM Metric"]
        )
        assert result.exit_code == 0
        assert "dt.service.request.failure_count" in result.output
        assert "no METRIC_MAP entry" not in result.output

    def test_compile_resolves_host_cpu_percent(self, runner):
        result = runner.invoke(
            cli, ["compile", "SELECT average(host.cpuPercent) FROM SystemSample"]
        )
        assert result.exit_code == 0
        assert "dt.host.cpu.usage" in result.output
        assert "no METRIC_MAP entry" not in result.output

    def test_compile_resolves_host_memory_used_percent(self, runner):
        result = runner.invoke(
            cli, ["compile", "SELECT average(host.memoryUsedPercent) FROM SystemSample"]
        )
        assert result.exit_code == 0
        assert "dt.host.memory.usage" in result.output
        assert "no METRIC_MAP entry" not in result.output

    def test_compile_resolves_host_disk_used_percent(self, runner):
        result = runner.invoke(
            cli, ["compile", "SELECT average(host.diskUsedPercent) FROM SystemSample"]
        )
        assert result.exit_code == 0
        assert "dt.host.disk.used.percent" in result.output
        assert "no METRIC_MAP entry" not in result.output

    def test_batch_compile_resolves_metrics(self, runner):
        # Same wiring path as `compile`; verify batch also picks up METRIC_MAP.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("nrql\n")
            f.write("SELECT average(host.cpuPercent) FROM SystemSample\n")
            csv_path = f.name
        try:
            with tempfile.NamedTemporaryFile(mode="r", suffix=".csv", delete=False) as out:
                out_path = out.name
            result = runner.invoke(cli, ["batch", "--file", csv_path, "--output", out_path])
            assert result.exit_code == 0
            with open(out_path) as f:
                output = f.read()
            assert "dt.host.cpu.usage" in output
        finally:
            os.unlink(csv_path)
            if os.path.exists(out_path):
                os.unlink(out_path)
