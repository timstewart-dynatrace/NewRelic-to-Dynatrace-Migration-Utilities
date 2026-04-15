"""Terraform HCL exporter — Gen3 resources for the `dynatrace-oss/dynatrace` provider.

Emits:

  dashboards              -> dynatrace_document (type="dashboard")
  workflows               -> dynatrace_automation_workflow
  anomaly_detectors       -> dynatrace_generic_setting (schema builtin:davis.anomaly-detectors)
  segments                -> dynatrace_segment
  iam_policies            -> dynatrace_iam_policy
  synthetic_tests         -> dynatrace_generic_setting (schema builtin:synthetic_test)
  slos                    -> dynatrace_slo_v2
  openpipeline_processors -> dynatrace_generic_setting (schema builtin:openpipeline.*)

Legacy (Config v1 / Gen2 classic resource names) emitted by
`exporters/legacy/terraform_v1.py`, reached via `--legacy`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger()


class TerraformExporter:
    """Export Gen3 transformed migration data to Terraform HCL files."""

    _PROVIDER_BLOCK = """\
terraform {
  required_providers {
    dynatrace = {
      source  = "dynatrace-oss/dynatrace"
    }
  }
}

# Gen3 deployments require both auth modes: Api-Token for Settings 2.0 +
# Classic endpoints, and OAuth2 / platform token for Document API and
# Automation API. See the provider's README for the combined-auth recipe.
provider "dynatrace" {
  dt_env_url      = var.dynatrace_env_url
  dt_api_token    = var.dynatrace_api_token
  automation_client_id     = var.dynatrace_oauth_client_id
  automation_client_secret = var.dynatrace_oauth_client_secret
}

variable "dynatrace_env_url" {
  description = "Dynatrace environment URL"
  type        = string
  default     = ""
}

variable "dynatrace_api_token" {
  description = "Dynatrace API token (Settings 2.0)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "dynatrace_oauth_client_id" {
  description = "OAuth2 client id for Gen3 Platform APIs (Document, Automation)"
  type        = string
  default     = ""
}

variable "dynatrace_oauth_client_secret" {
  description = "OAuth2 client secret for Gen3 Platform APIs"
  type        = string
  sensitive   = true
  default     = ""
}
"""

    # ------------------------------------------------------------------

    def export(
        self, transformed_data: Dict[str, Any], output_dir: Path
    ) -> Dict[str, int]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        summary: Dict[str, int] = {}

        (output_dir / "provider.tf").write_text(self._PROVIDER_BLOCK)
        logger.info("Created Gen3 provider.tf", output_dir=str(output_dir))

        writers = (
            ("dashboards", self._emit_dashboards),
            ("workflows", self._emit_workflows),
            ("anomaly_detectors", self._emit_anomaly_detectors),
            ("segments", self._emit_segments),
            ("iam_policies", self._emit_iam_policies),
            ("synthetic_tests", self._emit_synthetic_tests),
            ("slos", self._emit_slos),
            ("openpipeline_processors", self._emit_openpipeline),
        )

        for key, writer in writers:
            items = transformed_data.get(key) or []
            if not items:
                continue
            content = writer(items)
            if content:
                (output_dir / f"{key}.tf").write_text(content)
                summary[key] = len(items)
                logger.info(
                    "Exported Gen3 Terraform resources",
                    type=key,
                    count=len(items),
                )

        logger.info("Terraform Gen3 export complete", summary=summary)
        return summary

    # ------------------------------------------------------------------
    # Per-entity emitters
    # ------------------------------------------------------------------

    def _emit_dashboards(self, dashboards: List[Dict[str, Any]]) -> str:
        lines: List[str] = []
        for d in dashboards:
            name = d.get("name", "unnamed")
            res = self._resource_name(name)
            content = json.dumps(d, indent=2)
            lines.append(
                f'resource "dynatrace_document" "{res}" {{\n'
                f'  type    = "dashboard"\n'
                f'  name    = "{self._escape(name)}"\n'
                f'  private = false\n'
                f'  content = jsonencode({content})\n'
                f"}}\n"
            )
        return "\n".join(lines)

    def _emit_workflows(self, workflows: List[Dict[str, Any]]) -> str:
        lines: List[str] = []
        for wf in workflows:
            title = wf.get("title", "unnamed workflow")
            res = self._resource_name(title)
            description = wf.get("description", "")
            # Tasks and trigger are JSON-shaped; pass through jsonencode.
            trigger_json = json.dumps(wf.get("trigger", {}))
            lines.append(
                f'resource "dynatrace_automation_workflow" "{res}" {{\n'
                f'  title       = "{self._escape(title)}"\n'
                f'  description = "{self._escape(description)}"\n'
                f"  private     = false\n"
                f"  # Trigger + tasks serialized as JSON — the provider parses\n"
                f"  # these into the underlying Workflows API payload.\n"
                f"  definition  = jsonencode({json.dumps(wf)})\n"
                f"}}\n"
            )
        return "\n".join(lines)

    def _emit_anomaly_detectors(
        self, detectors: List[Dict[str, Any]]
    ) -> str:
        return self._emit_generic_settings(
            detectors, resource_prefix="detector"
        )

    def _emit_synthetic_tests(
        self, synthetics: List[Dict[str, Any]]
    ) -> str:
        return self._emit_generic_settings(
            synthetics, resource_prefix="synthetic"
        )

    def _emit_openpipeline(
        self, processors: List[Dict[str, Any]]
    ) -> str:
        return self._emit_generic_settings(
            processors, resource_prefix="openpipeline"
        )

    def _emit_segments(self, segments: List[Dict[str, Any]]) -> str:
        lines: List[str] = []
        for env in segments:
            value = env.get("value", env)
            name = value.get("name", "unnamed-segment")
            res = self._resource_name(name)
            description = value.get("description", "")
            includes = value.get("includes", {})
            lines.append(
                f'resource "dynatrace_segment" "{res}" {{\n'
                f'  name        = "{self._escape(name)}"\n'
                f'  description = "{self._escape(description)}"\n'
                f"  is_public   = false\n"
                f"  includes {{\n"
                f"    items {{\n"
                f'      data_object = "_all_data_object"\n'
                f"      filter      = jsonencode("
                f"{json.dumps(includes.get('items', [{}])[0].get('filter', {}))}"
                f")\n"
                f"    }}\n"
                f"  }}\n"
                f"}}\n"
            )
        return "\n".join(lines)

    def _emit_iam_policies(
        self, policies: List[Dict[str, Any]]
    ) -> str:
        lines: List[str] = []
        for env in policies:
            value = env.get("value", env)
            name = value.get("name", "unnamed-policy")
            res = self._resource_name(name)
            statement = value.get("statementQuery", "")
            description = value.get("description", "")
            lines.append(
                f'resource "dynatrace_iam_policy" "{res}" {{\n'
                f'  name            = "{self._escape(name)}"\n'
                f'  description     = "{self._escape(description)}"\n'
                f'  statement_query = "{self._escape(statement)}"\n'
                f"}}\n"
            )
        return "\n".join(lines)

    def _emit_slos(self, slos: List[Dict[str, Any]]) -> str:
        lines: List[str] = []
        for env in slos:
            value = env.get("value", env)
            name = value.get("name", "unnamed-slo")
            res = self._resource_name(name)
            lines.append(
                f'resource "dynatrace_slo_v2" "{res}" {{\n'
                f'  name              = "{self._escape(name)}"\n'
                f"  enabled           = {str(value.get('enabled', True)).lower()}\n"
                f'  metric_expression = "{self._escape(str(value.get("metricExpression", "")))}"\n'
                f'  evaluation_type   = "{value.get("evaluationType", "AGGREGATE")}"\n'
                f'  evaluation_window = "{value.get("timeframe", "-7d")}"\n'
                f'  filter            = "{self._escape(value.get("filter", ""))}"\n'
                f"  target_success    = {value.get('target', 99.0)}\n"
                f"  target_warning    = {value.get('warning', 99.5)}\n"
                f"}}\n"
            )
        return "\n".join(lines)

    def _emit_generic_settings(
        self, envelopes: List[Dict[str, Any]], resource_prefix: str
    ) -> str:
        """Emit Settings 2.0 envelopes via `dynatrace_generic_setting`.

        The provider's generic-setting resource accepts a `schema` id and a
        JSON-encoded `value`. This is the canonical escape hatch for Gen3
        schemas that do not yet have first-class TF resources.
        """
        lines: List[str] = []
        for idx, env in enumerate(envelopes):
            schema = env.get("schemaId", "builtin:unknown")
            value = env.get("value", {})
            name = value.get("name") or value.get("id") or f"{resource_prefix}-{idx}"
            res = self._resource_name(name)
            lines.append(
                f'resource "dynatrace_generic_setting" "{res}" {{\n'
                f'  schema = "{schema}"\n'
                f'  scope  = "{env.get("scope", "environment")}"\n'
                f"  value  = jsonencode({json.dumps(value)})\n"
                f"}}\n"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------

    @staticmethod
    def _resource_name(name: str) -> str:
        safe = name.lower()
        safe = re.sub(r"[^a-z0-9]+", "_", safe)
        safe = re.sub(r"_+", "_", safe).strip("_")
        return safe or "resource"

    @staticmethod
    def _escape(val: str) -> str:
        return str(val).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
