"""
Legacy Request-Naming Transformer (Gen2-only fallback).

Ported from nrql-engine `src/transformers/legacy-request-naming.transformer.ts`.

The default `CustomInstrumentationTranslator` emits a source-code
comment pointing operators at a DT request-naming rule for each
`newrelic.setTransactionName()` call site. For tenants running classic
DT, this transformer instead emits **concrete
`builtin:request-naming.request-naming-rules` Settings 2.0 payloads**
per call site — one rule per category × service combination.

Reached only via `--legacy`. Gen3 customers use
`CustomInstrumentationTranslator` which also emits code-level
replacements (OneAgent SDK / OTel span attributes), which is the
preferred forward path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger()


@dataclass
class RequestNamingResult:
    success: bool
    rule_envelopes: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class LegacyRequestNamingTransformer:
    """NR setTransactionName call sites -> DT request-naming rules."""

    def transform(self, nr_input: Dict[str, Any]) -> RequestNamingResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            sites = nr_input.get("sites") or []
            if not sites:
                warnings.append("No call sites provided; no rules emitted.")
                return RequestNamingResult(success=True, warnings=warnings)

            rule_envelopes: List[Dict[str, Any]] = []
            for site in sites:
                category = site.get("category", "Custom")
                name = site.get("name", "")
                service_name = site.get("serviceName", "")
                http_method = site.get("httpMethod", "")
                url_pattern = site.get("urlPathPattern", "")

                if not name or not service_name:
                    warnings.append(
                        f"Skipping call site — both `name` and `serviceName` required (got name={name!r}, "
                        f"service={service_name!r})."
                    )
                    continue

                conditions: List[Dict[str, Any]] = [
                    {
                        "attribute": "SERVICE_NAME",
                        "comparisonInfo": {
                            "type": "STRING",
                            "operator": "EQUALS",
                            "value": service_name,
                        },
                    }
                ]
                if http_method:
                    conditions.append(
                        {
                            "attribute": "HTTP_REQUEST_METHOD",
                            "comparisonInfo": {
                                "type": "STRING",
                                "operator": "EQUALS",
                                "value": http_method.upper(),
                            },
                        }
                    )
                if url_pattern:
                    conditions.append(
                        {
                            "attribute": "URL_PATH",
                            "comparisonInfo": {
                                "type": "STRING",
                                "operator": "REGEX_MATCHES",
                                "value": url_pattern,
                            },
                        }
                    )

                rule_envelopes.append(
                    {
                        "schemaId": "builtin:request-naming.request-naming-rules",
                        "scope": "environment",
                        "value": {
                            "enabled": True,
                            "namePattern": name,
                            "category": category,
                            "conditions": conditions,
                            "placeholders": [],
                        },
                    }
                )

            logger.info(
                "Transformed request-naming sites (legacy)",
                sites=len(sites),
                rules=len(rule_envelopes),
            )
            return RequestNamingResult(
                success=True, rule_envelopes=rule_envelopes, warnings=warnings
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Request-naming transformation failed", error=str(exc))
            return RequestNamingResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, inputs: List[Dict[str, Any]]
    ) -> List[RequestNamingResult]:
        return [self.transform(i) for i in inputs]
