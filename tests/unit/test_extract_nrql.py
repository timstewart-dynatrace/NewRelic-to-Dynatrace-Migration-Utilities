"""Tests for `migrate.py extract-nrql` subcommand."""
import csv
import json
import os
import sys

from click.testing import CliRunner

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from migrate import cli  # noqa: E402

SAMPLE_EXPORT = {
    "dashboards": [
        {
            "guid": "DASH-1",
            "name": "API overview",
            "pages": [
                {
                    "widgets": [
                        {
                            "rawConfiguration": {
                                "nrqlQueries": [
                                    {"query": "SELECT count(*) FROM Transaction"},
                                    {"query": "SELECT average(duration) FROM Span"},
                                ]
                            }
                        },
                        {
                            "rawConfiguration": {
                                "nrqlQueries": [
                                    # Duplicate with page-1 widget 0 — should dedupe
                                    {"query": "SELECT count(*) FROM Transaction"},
                                ]
                            }
                        },
                    ]
                }
            ],
        }
    ],
    "alert_policies": [
        {
            "id": "POL-1",
            "conditions": [
                {"nrql": {"query": "SELECT percentile(duration, 95) FROM Transaction"}},
                {"query": "SELECT count(*) FROM Log WHERE level = 'ERROR'"},
            ],
        }
    ],
    "slos": [
        {
            "id": "SLO-1",
            "indicator": {
                "from": "SELECT count(*) FROM Transaction WHERE http.status = '200'",
                "where": "",
            },
        }
    ],
    "synthetic_monitors": [],
    "workloads": [],
}


def _make_export(tmp_path, data):
    export_dir = tmp_path / "inventory" / "exports"
    export_dir.mkdir(parents=True)
    (export_dir / "newrelic_export.json").write_text(json.dumps(data))
    return tmp_path / "inventory"


def test_extract_nrql_txt_output(tmp_path):
    inventory = _make_export(tmp_path, SAMPLE_EXPORT)
    output = tmp_path / "all-nrql.txt"

    runner = CliRunner()
    result = runner.invoke(
        cli, ["extract-nrql", "--input", str(inventory), "--output", str(output)]
    )

    assert result.exit_code == 0, result.output
    assert output.exists()

    lines = [ln.strip() for ln in output.read_text().splitlines() if ln.strip()]
    # 2 unique dashboard queries + 2 alert-condition queries + 1 SLO = 5 unique
    # (the duplicate "SELECT count(*) FROM Transaction" collapses)
    assert len(lines) == 5
    assert "SELECT count(*) FROM Transaction" in lines
    assert "SELECT average(duration) FROM Span" in lines
    assert "SELECT percentile(duration, 95) FROM Transaction" in lines
    assert "SELECT count(*) FROM Log WHERE level = 'ERROR'" in lines
    assert "SELECT count(*) FROM Transaction WHERE http.status = '200'" in lines


def test_extract_nrql_csv_output(tmp_path):
    inventory = _make_export(tmp_path, SAMPLE_EXPORT)
    output = tmp_path / "all-nrql.csv"

    runner = CliRunner()
    result = runner.invoke(
        cli, ["extract-nrql", "--input", str(inventory), "--output", str(output)]
    )

    assert result.exit_code == 0, result.output
    assert output.exists()

    with open(output) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert [r["nrql"] for r in rows]  # non-empty
    assert len(rows) == 5
    # Every row has the `nrql` header column
    assert all("nrql" in r for r in rows)


def test_extract_nrql_format_override(tmp_path):
    """--format wins over file extension."""
    inventory = _make_export(tmp_path, SAMPLE_EXPORT)
    output = tmp_path / "all-nrql.txt"  # .txt extension…

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "extract-nrql",
            "--input", str(inventory),
            "--output", str(output),
            "--format", "csv",  # …but request csv
        ],
    )
    assert result.exit_code == 0, result.output
    # Output should be CSV-formatted regardless of the .txt suffix
    first_line = output.read_text().splitlines()[0]
    assert first_line.strip() == "nrql"  # CSV header


def test_extract_nrql_missing_export(tmp_path):
    # Empty dir — no exports/newrelic_export.json
    inventory = tmp_path / "inventory"
    inventory.mkdir()
    output = tmp_path / "out.txt"

    runner = CliRunner()
    result = runner.invoke(
        cli, ["extract-nrql", "--input", str(inventory), "--output", str(output)]
    )
    assert result.exit_code == 1
    assert "Export not found" in result.output


def test_extract_nrql_empty_export(tmp_path):
    """Export with all empty arrays should not error; just write empty output."""
    inventory = _make_export(tmp_path, {
        "dashboards": [], "alert_policies": [], "slos": [],
        "synthetic_monitors": [], "workloads": [],
    })
    output = tmp_path / "all-nrql.txt"

    runner = CliRunner()
    result = runner.invoke(
        cli, ["extract-nrql", "--input", str(inventory), "--output", str(output)]
    )
    assert result.exit_code == 0
    assert "No NRQL queries found" in result.output
    assert output.exists()
    assert output.read_text().strip() == ""


def test_extract_nrql_deduplication(tmp_path):
    """Identical queries appearing in multiple places should be deduped."""
    data = {
        "dashboards": [
            {
                "pages": [
                    {
                        "widgets": [
                            {"rawConfiguration": {"nrqlQueries": [
                                {"query": "SELECT count(*) FROM T"},
                                {"query": "SELECT count(*) FROM T"},  # dup
                                {"query": "SELECT count(*) FROM T"},  # dup
                            ]}},
                        ]
                    }
                ]
            }
        ],
        "alert_policies": [
            {"conditions": [{"nrql": {"query": "SELECT count(*) FROM T"}}]},  # dup
        ],
        "slos": [], "synthetic_monitors": [], "workloads": [],
    }
    inventory = _make_export(tmp_path, data)
    output = tmp_path / "all-nrql.txt"

    runner = CliRunner()
    result = runner.invoke(
        cli, ["extract-nrql", "--input", str(inventory), "--output", str(output)]
    )
    assert result.exit_code == 0
    lines = [ln for ln in output.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1  # All four collapsed to one
