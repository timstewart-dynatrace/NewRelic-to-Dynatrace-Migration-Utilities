"""
Key Transaction Transformer — Gen3 target.

Ported from nrql-engine TS sibling
(`src/transformers/key-transaction.transformer.ts`). New Relic Key
Transactions carry an apdex T-value, an entity tag, and often a
dedicated alert. The DT equivalent is a *bundle*:

  NR Key Transaction
    -> DT SLO         (Platform SLO API, DQL SLI) using the apdex T-value
    -> OpenPipeline   enrichment tagging the service with
                      `key_transaction=true`
    -> DT Workflow    (Automation API) triggered by Davis events on the
                      tagged service

Emits all three payloads so the orchestrator can push them in a single
migrate step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

from ._slo_utils import build_platform_slo, latency_indicator
from ._workflow_utils import davis_problem_trigger, tasks_list_to_dict

logger = structlog.get_logger()


@dataclass
class KeyTransactionResult:
    success: bool
    slo: Optional[Dict[str, Any]] = None  # Platform SLO API request body
    enrichment_processor: Optional[Dict[str, Any]] = None
    workflow: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class KeyTransactionTransformer:
    """NR Key Transaction → DT SLO + OpenPipeline enrichment + Workflow."""

    def transform(self, nr_kt: Dict[str, Any]) -> KeyTransactionResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            name = nr_kt.get("name", "unnamed-key-transaction")
            service_name = nr_kt.get("applicationName") or nr_kt.get("appName", "")
            apdex_t = float(nr_kt.get("apdexTarget", 0.5))
            duration_threshold_ms = int(apdex_t * 1000)

            slug = _slug(name)
            service_slug = _slug(service_name) if service_name else "unknown-service"

            # --- SLO ---
            slo = build_platform_slo(
                name=f"[Migrated KT] {name}",
                description=(
                    f"Key Transaction SLO migrated from New Relic. "
                    f"Apdex target: {apdex_t}s response-time threshold."
                ),
                target=95.0,
                warning=97.5,
                indicator=latency_indicator(duration_threshold_ms, service_name or None),
                timeframe_from="now-7d",
                tags=["MigratedFromNR:true", f"key_transaction:{slug}"],
            )

            # --- OpenPipeline enrichment — tag the service so other ---
            # --- migrated artifacts can reference the Key Transaction ---
            enrichment_processor = {
                "schemaId": "builtin:openpipeline.logs.pipelines",
                "scope": "environment",
                "value": {
                    "name": f"[Migrated KT tag] {name}",
                    "description": (
                        f"Adds key_transaction={slug} to records for service "
                        f"'{service_name or 'unknown'}'."
                    ),
                    "enabled": True,
                    "processor": {
                        "type": "addFields",
                        "id": f"enrich-kt-{slug}",
                        "matcher": (
                            f'contains(service.name, "{service_name}")'
                            if service_name
                            else "true"
                        ),
                        "fields": [
                            {"name": "key_transaction", "value": slug},
                            {"name": "key_transaction.name", "value": name},
                        ],
                    },
                },
            }

            # --- Workflow — Davis-problem trigger filtered to this KT's entity tag ---
            workflow = {
                "title": f"[Migrated KT] {name}",
                "description": (
                    f"Workflow for Key Transaction '{name}' "
                    f"(apdex T {apdex_t}s; migrated from newrelic.key_transaction)."
                ),
                "isPrivate": False,
                "trigger": davis_problem_trigger(entity_tags={"key_transaction": slug}),
                # Gen3 Automation API requires `tasks` as a dict keyed by task id.
                "tasks": tasks_list_to_dict([
                    {
                        "name": "placeholder_action",
                        "action": "dynatrace.automations:run-javascript",
                        "active": False,
                        "description": (
                            "Attach notification tasks (email / slack / pagerduty) "
                            "using NotificationTransformer-emitted task nodes."
                        ),
                        "input": {"script": "export default () => ({ ok: true });"},
                        "position": {"x": 0, "y": 1},
                    }
                ]),
            }

            if not service_name:
                warnings.append(
                    f"Key Transaction '{name}' has no applicationName — the "
                    "OpenPipeline enrichment will match all records; narrow "
                    "the matcher after import."
                )

            logger.info(
                "Transformed Key Transaction",
                name=name,
                service=service_name,
                apdex_t=apdex_t,
            )
            return KeyTransactionResult(
                success=True,
                slo=slo,
                enrichment_processor=enrichment_processor,
                workflow=workflow,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Key transaction transformation failed", error=str(exc))
            return KeyTransactionResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, kts: List[Dict[str, Any]]
    ) -> List[KeyTransactionResult]:
        return [self.transform(kt) for kt in kts]


def _slug(text: str) -> str:
    import re
    safe = re.sub(r"[^a-z0-9]+", "-", text.lower())
    return re.sub(r"-+", "-", safe).strip("-") or "item"
