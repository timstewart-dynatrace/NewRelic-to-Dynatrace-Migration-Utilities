"""Terraform HCL exporter for Dynatrace provider."""

import json
import re
from pathlib import Path
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger()


class TerraformExporter:
    """Export transformed migration data to Terraform HCL files."""

    RESOURCE_MAP = {
        "dashboards": "dynatrace_json_dashboard",
        "alerting_profiles": "dynatrace_alerting_profile",
        "metric_events": "dynatrace_metric_events",
        "management_zones": "dynatrace_management_zone_v2",
        "http_monitors": "dynatrace_http_monitor",
        "browser_monitors": "dynatrace_browser_monitor",
        "slos": "dynatrace_slo_v2",
    }

    _PROVIDER_BLOCK = """\
terraform {
  required_providers {
    dynatrace = {
      source  = "dynatrace-oss/dynatrace"
    }
  }
}

provider "dynatrace" {
  dt_env_url   = var.dynatrace_env_url
  dt_api_token = var.dynatrace_api_token
}

variable "dynatrace_env_url" {
  description = "Dynatrace environment URL"
  type        = string
  default     = ""
}

variable "dynatrace_api_token" {
  description = "Dynatrace API token"
  type        = string
  sensitive   = true
  default     = ""
}
"""

    def export(self, transformed_data: Dict[str, Any], output_dir: Path) -> Dict[str, int]:
        """Create Terraform files from transformed data.

        Args:
            transformed_data: Dictionary of entity types to lists of entities.
            output_dir: Root directory for Terraform output.

        Returns:
            Summary dict mapping entity type to count of exported resources.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        summary: Dict[str, int] = {}

        # Write provider.tf
        (output_dir / "provider.tf").write_text(self._PROVIDER_BLOCK)
        logger.info("Created provider.tf", output_dir=str(output_dir))

        for entity_type, resource_type in self.RESOURCE_MAP.items():
            if entity_type not in transformed_data:
                continue

            entities = transformed_data[entity_type]
            if not entities:
                continue

            lines: List[str] = []
            for entity in entities:
                name = entity.get("name", "unnamed")
                res_name = self._resource_name(name)

                if entity_type == "dashboards":
                    # JSON dashboard — use content = jsonencode(...)
                    content_json = json.dumps(entity, indent=2)
                    lines.append(
                        f'resource "{resource_type}" "migrated_{res_name}" {{\n'
                        f"  content = jsonencode({content_json})\n"
                        f"}}\n"
                    )
                else:
                    # Non-JSON resources — emit individual HCL fields
                    lines.append(
                        f'resource "{resource_type}" "migrated_{res_name}" {{\n'
                    )
                    for key, value in entity.items():
                        hcl_key = self._resource_name(key)
                        lines.append(f"  {hcl_key} = {self._to_hcl_value(value)}\n")
                    lines.append("}\n")

            tf_content = "\n".join(lines)
            (output_dir / f"{entity_type}.tf").write_text(tf_content)
            summary[entity_type] = len(entities)
            logger.info("Exported Terraform resources", type=entity_type, count=len(entities))

        logger.info("Terraform export complete", summary=summary)
        return summary

    @staticmethod
    def _resource_name(name: str) -> str:
        """Convert a display name to a Terraform-safe resource name.

        Lowercase, replace non-alphanumeric characters with underscores,
        collapse multiple underscores, and strip leading/trailing underscores.
        """
        safe = name.lower()
        safe = re.sub(r"[^a-z0-9]+", "_", safe)
        safe = re.sub(r"_+", "_", safe)
        safe = safe.strip("_")
        return safe

    @staticmethod
    def _to_hcl_value(val: Any) -> str:
        """Convert a Python value to an HCL literal string.

        Handles strings, numbers, booleans, lists, and dicts.
        """
        if isinstance(val, bool):
            return "true" if val else "false"
        if isinstance(val, (int, float)):
            return str(val)
        if isinstance(val, str):
            escaped = val.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        if isinstance(val, list):
            items = ", ".join(TerraformExporter._to_hcl_value(v) for v in val)
            return f"[{items}]"
        if isinstance(val, dict):
            return f"jsonencode({json.dumps(val)})"
        return f'"{val}"'
