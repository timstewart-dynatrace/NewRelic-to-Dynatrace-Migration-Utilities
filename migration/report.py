"""Conversion report — tracks NRQL-to-DQL conversion quality for manual review."""

import json
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class ConversionReport:
    """Collects NRQL-to-DQL conversion results and generates review reports."""

    entries: List[Dict] = field(default_factory=list)

    def add_query(
        self,
        original_nrql: str,
        converted_dql: str,
        confidence: str,
        warnings: Optional[List[str]] = None,
        fixes: Optional[List[str]] = None,
        dashboard_name: str = "",
        widget_title: str = "",
    ) -> None:
        """Add a converted query to the report."""
        self.entries.append(
            {
                "original_nrql": original_nrql,
                "converted_dql": converted_dql,
                "confidence": confidence.upper(),
                "warnings": warnings or [],
                "fixes": fixes or [],
                "dashboard_name": dashboard_name,
                "widget_title": widget_title,
            }
        )

    def summary(self) -> Dict:
        """Return aggregate statistics about conversion results."""
        counts = {"total": len(self.entries), "high_confidence": 0, "medium_confidence": 0, "low_confidence": 0, "failed": 0, "needs_review": 0}
        for entry in self.entries:
            conf = entry["confidence"]
            if conf == "HIGH":
                counts["high_confidence"] += 1
            elif conf == "MEDIUM":
                counts["medium_confidence"] += 1
                counts["needs_review"] += 1
            elif conf == "LOW":
                counts["low_confidence"] += 1
                counts["needs_review"] += 1
            elif conf == "FAILED":
                counts["failed"] += 1
                counts["needs_review"] += 1
        return counts

    def get_review_queries(self) -> List[Dict]:
        """Return entries with confidence != HIGH (needing manual review)."""
        return [e for e in self.entries if e["confidence"] != "HIGH"]

    def generate_json(self, path: Path) -> None:
        """Write full report as JSON (entries + summary)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        report = {"summary": self.summary(), "entries": self.entries}
        path.write_text(json.dumps(report, indent=2))
        logger.info("json_report_generated", path=str(path), total=len(self.entries))

    def generate_html(self, path: Path) -> None:
        """Write an HTML report with summary stats and query details table."""
        path.parent.mkdir(parents=True, exist_ok=True)
        stats = self.summary()

        badge_colors = {
            "HIGH": "#28a745",
            "MEDIUM": "#ffc107",
            "LOW": "#fd7e14",
            "FAILED": "#dc3545",
        }

        rows = []
        for entry in self.entries:
            conf = entry["confidence"]
            color = badge_colors.get(conf, "#6c757d")
            needs_review = conf in ("MEDIUM", "LOW", "FAILED")
            row_style = ' style="background-color: #fff3cd;"' if needs_review else ""

            warnings_html = "<br>".join(escape(w) for w in entry["warnings"]) if entry["warnings"] else "&mdash;"

            rows.append(
                f"<tr{row_style}>"
                f"<td>{escape(entry['dashboard_name'])}</td>"
                f"<td>{escape(entry['widget_title'])}</td>"
                f'<td><span style="background:{color};color:#fff;padding:2px 8px;border-radius:4px;font-size:0.85em;">{conf}</span></td>'
                f"<td><code>{escape(entry['original_nrql'])}</code></td>"
                f"<td><code>{escape(entry['converted_dql'])}</code></td>"
                f"<td>{warnings_html}</td>"
                f"</tr>"
            )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>NRQL to DQL Conversion Report</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 2em; color: #333; }}
h1 {{ margin-bottom: 0.5em; }}
table {{ border-collapse: collapse; width: 100%; margin-bottom: 2em; }}
th, td {{ border: 1px solid #dee2e6; padding: 8px 12px; text-align: left; vertical-align: top; }}
th {{ background: #f8f9fa; }}
code {{ font-size: 0.9em; word-break: break-all; }}
.summary-table {{ width: auto; margin-bottom: 2em; }}
.summary-table td {{ min-width: 80px; }}
</style>
</head>
<body>
<h1>NRQL to DQL Conversion Report</h1>

<h2>Summary</h2>
<table class="summary-table">
<tr><th>Total Queries</th><td>{stats['total']}</td></tr>
<tr><th>High Confidence</th><td>{stats['high_confidence']}</td></tr>
<tr><th>Medium Confidence</th><td>{stats['medium_confidence']}</td></tr>
<tr><th>Low Confidence</th><td>{stats['low_confidence']}</td></tr>
<tr><th>Failed</th><td>{stats['failed']}</td></tr>
<tr><th>Needs Review</th><td>{stats['needs_review']}</td></tr>
</table>

<h2>Query Details</h2>
<table>
<thead>
<tr><th>Dashboard</th><th>Widget</th><th>Confidence</th><th>Original NRQL</th><th>Converted DQL</th><th>Warnings</th></tr>
</thead>
<tbody>
{"".join(rows)}
</tbody>
</table>
</body>
</html>"""

        path.write_text(html)
        logger.info("html_report_generated", path=str(path), total=len(self.entries))
