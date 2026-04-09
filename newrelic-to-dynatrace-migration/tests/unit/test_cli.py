"""Tests for CLI commands: compile (interactive, file, output) and reference."""

import os
import tempfile

import pytest
from click.testing import CliRunner

# Add project root to path so migrate.py imports work
import sys
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
