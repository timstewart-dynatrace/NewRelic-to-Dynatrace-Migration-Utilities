"""Monaco (Dynatrace config-as-code) exporter."""

import json
import re

import yaml
from pathlib import Path
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger()


class MonacoExporter:
    """Export transformed migration data to Monaco v2 project structure."""

    SCHEMA_MAP = {
        "alerting_profiles": "builtin:alerting.profile",
        "metric_events": "builtin:anomaly-detection.metric-events",
        "management_zones": "builtin:management-zones",
        "auto_tags": "builtin:tags.auto-tagging",
    }

    def export(self, transformed_data: Dict[str, Any], output_dir: Path) -> Dict[str, int]:
        """Create Monaco project structure from transformed data.

        Args:
            transformed_data: Dictionary of entity types to lists of entities.
            output_dir: Root directory for the Monaco project output.

        Returns:
            Summary dict mapping entity type to count of exported entities.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        summary: Dict[str, int] = {}

        # Write project.yaml
        project_yaml = {"project": "migrated-project"}
        (output_dir / "project.yaml").write_text(
            yaml.dump(project_yaml, default_flow_style=False)
        )
        logger.info("Created project.yaml", output_dir=str(output_dir))

        # Dashboards
        if "dashboards" in transformed_data:
            dashboards = transformed_data["dashboards"]
            dash_dir = output_dir / "dashboards"
            dash_dir.mkdir(parents=True, exist_ok=True)
            for dashboard in dashboards:
                name = dashboard.get("name", "unnamed")
                safe = self._safe_name(name)
                (dash_dir / f"{safe}.json").write_text(
                    json.dumps(dashboard, indent=2)
                )
            summary["dashboards"] = len(dashboards)
            logger.info("Exported dashboards", count=len(dashboards))

        # Settings-based entities
        for entity_type, schema_id in self.SCHEMA_MAP.items():
            if entity_type not in transformed_data:
                continue
            entities = transformed_data[entity_type]
            type_dir = output_dir / entity_type
            type_dir.mkdir(parents=True, exist_ok=True)

            for entity in entities:
                name = entity.get("name", "unnamed")
                safe = self._safe_name(name)

                # Write Monaco config YAML
                config_yaml = {
                    "configs": [
                        {
                            "id": f"migrated-{safe}",
                            "type": {
                                "settings": {
                                    "schema": schema_id,
                                    "scope": "environment",
                                }
                            },
                            "config": {
                                "name": name,
                                "template": f"{safe}.json",
                            },
                        }
                    ]
                }
                (type_dir / f"{safe}.yaml").write_text(
                    yaml.dump(config_yaml, default_flow_style=False)
                )

                # Write JSON body
                (type_dir / f"{safe}.json").write_text(
                    json.dumps(entity, indent=2)
                )

            summary[entity_type] = len(entities)
            logger.info("Exported settings entities", type=entity_type, count=len(entities))

        # Synthetic monitors
        for monitor_type in ("http_monitors", "browser_monitors"):
            if monitor_type not in transformed_data:
                continue
            monitors = transformed_data[monitor_type]
            synth_dir = output_dir / "synthetic-monitors"
            synth_dir.mkdir(parents=True, exist_ok=True)

            for monitor in monitors:
                name = monitor.get("name", "unnamed")
                safe = self._safe_name(name)
                (synth_dir / f"{safe}.json").write_text(
                    json.dumps(monitor, indent=2)
                )

            summary[monitor_type] = len(monitors)
            logger.info("Exported synthetic monitors", type=monitor_type, count=len(monitors))

        # SLOs
        if "slos" in transformed_data:
            slos = transformed_data["slos"]
            slo_dir = output_dir / "slos"
            slo_dir.mkdir(parents=True, exist_ok=True)

            for slo in slos:
                name = slo.get("name", "unnamed")
                safe = self._safe_name(name)
                (slo_dir / f"{safe}.json").write_text(
                    json.dumps(slo, indent=2)
                )

            summary["slos"] = len(slos)
            logger.info("Exported SLOs", count=len(slos))

        logger.info("Monaco export complete", summary=summary)
        return summary

    @staticmethod
    def _safe_name(name: str) -> str:
        """Convert a display name to a filesystem-safe identifier.

        Lowercase, replace spaces and special characters with hyphens,
        collapse multiple hyphens, strip leading/trailing hyphens,
        and truncate to 50 characters.
        """
        safe = name.lower()
        safe = re.sub(r"[^a-z0-9]+", "-", safe)
        safe = re.sub(r"-+", "-", safe)
        safe = safe.strip("-")
        return safe[:50]
