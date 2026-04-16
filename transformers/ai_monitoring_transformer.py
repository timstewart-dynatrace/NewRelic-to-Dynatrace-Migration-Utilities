"""
AI Monitoring Transformer — Gen3 target.

NR AI Monitoring (LLM observability, model performance) maps to Dynatrace
AI Observability. Model registry entries, inference events, and LLM
cost-tracking configs convert as follows:

  NR AI model record      -> DT AI Observability model entry
                             (`builtin:ai.observability.model`)
  NR InferenceEvent       -> DT bizevent with `event.category == "AI_INFERENCE"`
  NR LLM cost tracking    -> DT DPS + Workflow alert on threshold
                             (not a single settings object)

The runbook lists what the operator must wire on the vendor side
(OpenAI / Anthropic / custom) to begin emitting AI events that DT
recognizes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class AIMonitoringResult:
    success: bool
    model_envelopes: List[Dict[str, Any]] = field(default_factory=list)
    inference_event_mapping: Optional[str] = None
    runbook: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class AIMonitoringTransformer:
    """NR AI Monitoring -> DT AI Observability."""

    def transform(self, nr_config: Dict[str, Any]) -> AIMonitoringResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            models = nr_config.get("models") or []
            providers = nr_config.get("providers") or []

            model_envelopes: List[Dict[str, Any]] = []
            for m in models:
                model_envelopes.append(
                    {
                        "schemaId": "builtin:ai.observability.model",
                        "scope": "environment",
                        "value": {
                            "name": m.get("name", "unnamed-model"),
                            "provider": m.get("provider", ""),
                            "modelId": m.get("modelId", ""),
                            "costPer1kInputTokens": m.get("costPer1kInputTokens"),
                            "costPer1kOutputTokens": m.get("costPer1kOutputTokens"),
                            "enabled": bool(m.get("enabled", True)),
                        },
                    }
                )

            inference_mapping = (
                "# NRQL:  FROM InferenceEvent SELECT count(*), "
                "average(duration) WHERE modelName = 'gpt-4' FACET userId\n"
                "# DQL:   fetch bizevents, from:now()-1d\n"
                "#        | filter event.category == \"AI_INFERENCE\" "
                "and model.name == \"gpt-4\"\n"
                "#        | summarize count(), avg(duration), by:{user.id}"
            )

            runbook = {
                "providers": providers,
                "instrumentation_notes": [
                    "DT AI Observability ingests inference events via OTel span "
                    "events with `gen_ai.*` attributes. Wire the OTel LLM "
                    "instrumentation library (openllmetry) in your app.",
                    "OneAgent Java/Python automatically captures OpenAI / "
                    "Anthropic / Bedrock calls in recent versions.",
                ],
                "cost_tracking": (
                    "NR LLM cost reports live in NR dashboards; in DT replicate "
                    "them as bizevent queries + a dashboard tile — no direct "
                    "migration path."
                ),
            }

            if not models:
                warnings.append(
                    "No models declared in NR config. DT AI Observability will "
                    "auto-discover models from OTel attributes; manual model "
                    "registry entries are optional."
                )

            logger.info(
                "Transformed AI Monitoring config",
                models=len(models),
                providers=len(providers),
            )
            return AIMonitoringResult(
                success=True,
                model_envelopes=model_envelopes,
                inference_event_mapping=inference_mapping,
                runbook=runbook,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("AI monitoring transformation failed", error=str(exc))
            return AIMonitoringResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, configs: List[Dict[str, Any]]
    ) -> List[AIMonitoringResult]:
        return [self.transform(c) for c in configs]
