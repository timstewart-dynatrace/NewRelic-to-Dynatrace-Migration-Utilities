"""
Custom Instrumentation Translator.

Translates New Relic SDK call sites (`newrelic.*()`) into Dynatrace-native
equivalents (OneAgent SDK for server languages, OpenTelemetry API where a
one-to-one OneAgent SDK mapping does not exist).

The v1 implementation is **pattern-matcher-based** rather than a full
per-language AST: it recognizes the common NR call shapes, emits a
suggested replacement, and produces a human-readable diff. It is
intentionally side-effect-free — it never rewrites customer code. The
operator pastes the suggested replacement, reviews it, and commits.

This keeps the tool framework-agnostic (Node/Express, Python/Flask,
Java/Spring all look the same from the NR SDK's surface) and avoids
invalidating customer code by misparsing macros / decorators / TS
generics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class TranslationSuggestion:
    """One suggested code replacement for a single NR SDK call site."""

    language: str
    file: str
    line: int
    original: str
    replacement: str
    api_category: str  # custom_event | custom_attribute | metric | error | txn_name | segment
    confidence: str  # HIGH | MEDIUM | LOW
    notes: str = ""


@dataclass
class CustomInstrumentationResult:
    """Result of scanning one file."""

    success: bool
    suggestions: List[TranslationSuggestion] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Patterns — keyed by (language, category). Each pattern provides:
#   regex  -> matches the NR call
#   build  -> callable(groups) -> replacement string
# ---------------------------------------------------------------------------

_PATTERNS = {
    # ------------------ JavaScript / Node.js / Browser ------------------
    ("javascript", "custom_event"): {
        "regex": re.compile(
            r"newrelic\.recordCustomEvent\(\s*(['\"])(?P<type>[^'\"]+)\1\s*,\s*(?P<attrs>\{[^}]*\})\s*\)"
        ),
        "build": lambda m: (
            "// DT: send as bizevent via the Grail ingest API\n"
            f"await fetch('${{DT_URL}}/platform/classic/environment-api/v2/bizevents/ingest', {{\n"
            f"  method: 'POST',\n"
            f"  headers: {{ Authorization: 'Api-Token ${{DT_API_TOKEN}}', 'Content-Type': 'application/cloudevent+json' }},\n"
            f"  body: JSON.stringify({{ specversion: '1.0', type: '{m.group('type')}', data: {m.group('attrs')} }})\n"
            f"}});"
        ),
        "confidence": "HIGH",
    },
    ("javascript", "custom_attribute"): {
        "regex": re.compile(
            r"newrelic\.addCustomAttribute\(\s*(['\"])(?P<key>[^'\"]+)\1\s*,\s*(?P<value>[^)]+)\s*\)"
        ),
        "build": lambda m: (
            "// DT: set via OneAgent SDK request-attribute (requires Node SDK setup)\n"
            f"require('@dynatrace/oneagent-sdk').createInstance().traceIncomingHttpRequest(...).setRequestAttribute('{m.group('key')}', {m.group('value')});"
        ),
        "confidence": "MEDIUM",
    },
    ("javascript", "metric"): {
        "regex": re.compile(
            r"newrelic\.recordMetric\(\s*(['\"])(?P<name>[^'\"]+)\1\s*,\s*(?P<value>[^)]+)\s*\)"
        ),
        "build": lambda m: (
            "// DT: use OTel Meter API\n"
            f"const meter = require('@opentelemetry/api').metrics.getMeter('app');\n"
            f"meter.createHistogram('{m.group('name')}').record({m.group('value')});"
        ),
        "confidence": "HIGH",
    },
    ("javascript", "error"): {
        "regex": re.compile(
            r"newrelic\.noticeError\(\s*(?P<err>[^,)]+)(?:,\s*(?P<attrs>\{[^}]*\}))?\s*\)"
        ),
        "build": lambda m: (
            "// DT: record exception on active OTel span\n"
            f"const {{ trace }} = require('@opentelemetry/api');\n"
            f"trace.getActiveSpan()?.recordException({m.group('err')});"
            + (f"\ntrace.getActiveSpan()?.setAttributes({m.group('attrs')});" if m.group('attrs') else "")
        ),
        "confidence": "HIGH",
    },
    ("javascript", "txn_name"): {
        "regex": re.compile(
            r"newrelic\.setTransactionName\(\s*(['\"])(?P<name>[^'\"]+)\1\s*\)"
        ),
        "build": lambda m: (
            "// DT: create a request-naming rule in DT settings "
            f"(builtin:service.request-naming) targeting '{m.group('name')}'. "
            "Runtime override of the service/request name is not supported in DT; "
            "use a classifier rule in DT settings instead."
        ),
        "confidence": "LOW",
    },
    ("javascript", "segment_start"): {
        "regex": re.compile(
            r"const\s+(?P<var>\w+)\s*=\s*newrelic\.startSegment\(\s*(['\"])(?P<name>[^'\"]+)\2"
        ),
        "build": lambda m: (
            f"const {m.group('var')} = require('@opentelemetry/api').trace.getTracer('app').startSpan('{m.group('name')}');"
        ),
        "confidence": "HIGH",
    },
    ("javascript", "segment_end"): {
        "regex": re.compile(r"(?P<var>\w+)\.end\(\)"),
        "build": lambda m: f"{m.group('var')}.end();  // OTel span end (was NR segment end)",
        "confidence": "MEDIUM",  # ambiguous — end() is common; flag for review
    },
    # ------------------ Python ------------------
    ("python", "custom_event"): {
        "regex": re.compile(
            r"newrelic\.agent\.record_custom_event\(\s*(['\"])(?P<type>[^'\"]+)\1\s*,\s*(?P<attrs>\{[^}]*\})\s*\)"
        ),
        "build": lambda m: (
            "# DT: send as bizevent via Grail ingest API\n"
            f"import requests, os\n"
            f"requests.post(os.environ['DT_URL'] + '/platform/classic/environment-api/v2/bizevents/ingest',\n"
            f"    headers={{'Authorization': f\"Api-Token {{os.environ['DT_API_TOKEN']}}\", 'Content-Type': 'application/cloudevent+json'}},\n"
            f"    json={{'specversion': '1.0', 'type': '{m.group('type')}', 'data': {m.group('attrs')}}})"
        ),
        "confidence": "HIGH",
    },
    ("python", "custom_attribute"): {
        "regex": re.compile(
            r"newrelic\.agent\.add_custom_attribute\(\s*(['\"])(?P<key>[^'\"]+)\1\s*,\s*(?P<value>[^)]+)\s*\)"
        ),
        "build": lambda m: (
            "# DT: OneAgent SDK Python request attribute\n"
            f"import oneagent\n"
            f"oneagent.get_sdk().trace_incoming_web_request(...).add_custom_request_attribute('{m.group('key')}', {m.group('value')})"
        ),
        "confidence": "MEDIUM",
    },
    ("python", "metric"): {
        "regex": re.compile(
            r"newrelic\.agent\.record_custom_metric\(\s*(['\"])(?P<name>[^'\"]+)\1\s*,\s*(?P<value>[^)]+)\s*\)"
        ),
        "build": lambda m: (
            "# DT: OTel Meter API\n"
            f"from opentelemetry import metrics\n"
            f"metrics.get_meter('app').create_histogram('{m.group('name')}').record({m.group('value')})"
        ),
        "confidence": "HIGH",
    },
    ("python", "error"): {
        "regex": re.compile(
            r"newrelic\.agent\.notice_error\(\s*\)"  # often called inside an except block
        ),
        "build": lambda m: (
            "# DT: record exception on active OTel span\n"
            "from opentelemetry import trace as _dt_trace\n"
            "_dt_trace.get_current_span().record_exception(_exc_var)"
        ),
        "confidence": "MEDIUM",
        "notes": "NR picks up exc_info() automatically; in OTel the exception instance must be passed explicitly.",
    },
    ("python", "txn_name"): {
        "regex": re.compile(
            r"newrelic\.agent\.set_transaction_name\(\s*(['\"])(?P<name>[^'\"]+)\1\s*\)"
        ),
        "build": lambda m: (
            f"# DT: use request-naming rule (builtin:service.request-naming) "
            f"targeting '{m.group('name')}' — no runtime equivalent."
        ),
        "confidence": "LOW",
    },
    # ------------------ Java ------------------
    ("java", "custom_event"): {
        "regex": re.compile(
            r"NewRelic\.getAgent\(\)\.getInsights\(\)\.recordCustomEvent\(\s*\"(?P<type>[^\"]+)\"\s*,\s*(?P<attrs>Map[^)]+)\s*\)"
        ),
        "build": lambda m: (
            "// DT: use OneAgent SDK or OTel API; bizevent ingest via HttpClient\n"
            "HttpClient.newHttpClient().send(HttpRequest.newBuilder()\n"
            "    .uri(URI.create(System.getenv(\"DT_URL\") + \"/platform/classic/environment-api/v2/bizevents/ingest\"))\n"
            "    .header(\"Authorization\", \"Api-Token \" + System.getenv(\"DT_API_TOKEN\"))\n"
            "    .header(\"Content-Type\", \"application/cloudevent+json\")\n"
            f"    .POST(HttpRequest.BodyPublishers.ofString(buildBizevent(\"{m.group('type')}\", {m.group('attrs')})))\n"
            "    .build(), HttpResponse.BodyHandlers.ofString());"
        ),
        "confidence": "MEDIUM",
    },
    ("java", "custom_attribute"): {
        "regex": re.compile(
            r"NewRelic\.addCustomParameter\(\s*\"(?P<key>[^\"]+)\"\s*,\s*(?P<value>[^)]+)\s*\)"
        ),
        "build": lambda m: (
            "// DT: OneAgent SDK custom request attribute\n"
            "com.dynatrace.oneagent.sdk.OneAgentSDKFactory.createInstance()\n"
            f"    .addCustomRequestAttribute(\"{m.group('key')}\", {m.group('value')});"
        ),
        "confidence": "HIGH",
    },
    ("java", "error"): {
        "regex": re.compile(r"NewRelic\.noticeError\(\s*(?P<err>[^)]+)\s*\)"),
        "build": lambda m: (
            "// DT: record exception on active OTel span\n"
            f"io.opentelemetry.api.trace.Span.current().recordException({m.group('err')});"
        ),
        "confidence": "HIGH",
    },
}


# Map filename suffix -> language.
_LANG_BY_SUFFIX = {
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "javascript",
    ".tsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".py": "python",
    ".java": "java",
    ".kt": "java",  # Kotlin uses the same NR Java SDK API
}


class CustomInstrumentationTranslator:
    """Scan source files for NR SDK call sites and emit replacement suggestions."""

    def detect_language(self, file: str) -> Optional[str]:
        for suffix, lang in _LANG_BY_SUFFIX.items():
            if file.endswith(suffix):
                return lang
        return None

    def scan_text(
        self, text: str, file: str, language: Optional[str] = None
    ) -> CustomInstrumentationResult:
        warnings: List[str] = []
        errors: List[str] = []
        suggestions: List[TranslationSuggestion] = []

        lang = language or self.detect_language(file)
        if lang is None:
            warnings.append(
                f"Unknown language for '{file}' — translator only supports "
                ", ".join(sorted(set(_LANG_BY_SUFFIX.values()))) + "."
            )
            return CustomInstrumentationResult(
                success=True, warnings=warnings
            )

        lines = text.splitlines()
        for (pattern_lang, category), spec in _PATTERNS.items():
            if pattern_lang != lang:
                continue
            for match in spec["regex"].finditer(text):
                line_no = text.count("\n", 0, match.start()) + 1
                replacement = spec["build"](match)
                suggestions.append(
                    TranslationSuggestion(
                        language=lang,
                        file=file,
                        line=line_no,
                        original=match.group(0),
                        replacement=replacement,
                        api_category=category,
                        confidence=spec["confidence"],
                        notes=spec.get("notes", ""),
                    )
                )

        logger.info(
            "Scanned file for NR SDK calls",
            file=file,
            language=lang,
            suggestions=len(suggestions),
        )
        return CustomInstrumentationResult(
            success=True, suggestions=suggestions, warnings=warnings
        )

    def render_diff(self, result: CustomInstrumentationResult) -> str:
        """Render a human-readable diff report of all suggestions."""
        lines: List[str] = []
        for s in result.suggestions:
            lines.append(
                f"--- {s.file}:{s.line}   [{s.api_category}] confidence={s.confidence}"
            )
            lines.append(f"- {s.original}")
            for repl_line in s.replacement.splitlines():
                lines.append(f"+ {repl_line}")
            if s.notes:
                lines.append(f"  ^ {s.notes}")
            lines.append("")
        return "\n".join(lines)
