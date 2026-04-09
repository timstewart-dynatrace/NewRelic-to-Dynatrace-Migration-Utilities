"""Tests for migration.report — ConversionReport with JSON/HTML generation."""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from migration.report import ConversionReport


class TestConversionReport:
    def test_should_add_query(self):
        report = ConversionReport()
        report.add_query(
            original_nrql="SELECT count(*) FROM Transaction",
            converted_dql="fetch logs | summarize count()",
            confidence="HIGH",
        )
        assert len(report.entries) == 1
        assert report.entries[0]["original_nrql"] == "SELECT count(*) FROM Transaction"
        assert report.entries[0]["confidence"] == "HIGH"

    def test_should_compute_summary(self):
        report = ConversionReport()
        report.add_query("q1", "d1", "HIGH")
        report.add_query("q2", "d2", "MEDIUM", warnings=["approx"])
        report.add_query("q3", "d3", "LOW")
        report.add_query("q4", "", "FAILED")
        stats = report.summary()
        assert stats["total"] == 4
        assert stats["high_confidence"] == 1
        assert stats["medium_confidence"] == 1
        assert stats["low_confidence"] == 1
        assert stats["failed"] == 1
        assert stats["needs_review"] == 3

    def test_should_generate_json(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            report = ConversionReport()
            report.add_query("SELECT 1", "fetch logs", "HIGH", dashboard_name="Dash1")
            report.add_query("SELECT 2", "fetch spans", "MEDIUM", warnings=["check field"])
            path = Path(tmp_dir) / "report.json"
            report.generate_json(path)

            data = json.loads(path.read_text())
            assert "summary" in data
            assert "entries" in data
            assert data["summary"]["total"] == 2
            assert len(data["entries"]) == 2
            assert data["entries"][0]["dashboard_name"] == "Dash1"
        finally:
            shutil.rmtree(tmp_dir)

    def test_should_generate_html(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            report = ConversionReport()
            report.add_query("SELECT count(*) FROM Transaction", "fetch logs | summarize count()", "HIGH", dashboard_name="TestDash", widget_title="Widget1")
            path = Path(tmp_dir) / "report.html"
            report.generate_html(path)

            html = path.read_text()
            assert "<!DOCTYPE html>" in html
            assert "Conversion Report" in html
            assert "TestDash" in html
            assert "Widget1" in html
            assert "HIGH" in html
            assert "<table" in html
        finally:
            shutil.rmtree(tmp_dir)

    def test_should_get_review_queries(self):
        report = ConversionReport()
        report.add_query("q1", "d1", "HIGH")
        report.add_query("q2", "d2", "MEDIUM")
        report.add_query("q3", "d3", "LOW")
        report.add_query("q4", "d4", "HIGH")
        review = report.get_review_queries()
        assert len(review) == 2
        confidences = [e["confidence"] for e in review]
        assert "HIGH" not in confidences
        assert "MEDIUM" in confidences
        assert "LOW" in confidences

    def test_should_start_empty(self):
        report = ConversionReport()
        assert report.entries == []
        assert len(report.entries) == 0

    def test_should_count_failed_queries(self):
        report = ConversionReport()
        report.add_query("q1", "", "FAILED")
        report.add_query("q2", "", "FAILED")
        report.add_query("q3", "dql3", "HIGH")
        failed = [e for e in report.entries if not e["converted_dql"]]
        assert len(failed) == 2
        stats = report.summary()
        assert stats["failed"] == 2

    def test_should_handle_no_entries(self):
        report = ConversionReport()
        stats = report.summary()
        assert stats["total"] == 0
        assert stats["high_confidence"] == 0
        assert stats["medium_confidence"] == 0
        assert stats["low_confidence"] == 0
        assert stats["failed"] == 0
        assert stats["needs_review"] == 0
