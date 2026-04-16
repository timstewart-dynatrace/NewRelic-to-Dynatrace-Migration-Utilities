"""Monaco v2 exporter — Gen3 target.

Produces a Monaco v2 project tree with a `manifest.yaml`, emitting:

  projects/migrated/settings/<schema-id>/<name>.{yaml,json}     -- Settings 2.0
  projects/migrated/documents/<name>.json                       -- Dashboards
  projects/migrated/workflows/<name>.{yaml,json}                -- Workflows

The settings schemas covered by default are the Gen3 targets produced by
the transformers: `builtin:davis.anomaly-detectors`, `builtin:segment`,
`builtin:iam.policy`, `builtin:synthetic_test`, `builtin:monitoring.slo`,
`builtin:openpipeline.*`. Legacy (Config v1 / Gen2 classic) emission lives
in `exporters/legacy/monaco_v1.py` and is reached via `--legacy`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

import structlog
import yaml

logger = structlog.get_logger()


class MonacoExporter:
    """Export Gen3 transformed migration data to a Monaco v2 project."""

    PROJECT_NAME = "migrated"

    _MANIFEST = {
        "manifestVersion": "1.0",
        "projects": [{"name": PROJECT_NAME, "path": PROJECT_NAME}],
        "environmentGroups": [
            {
                "name": "target",
                "environments": [
                    {
                        "name": "target",
                        "url": {"type": "environment", "value": "DYNATRACE_ENV_URL"},
                        "auth": {
                            "token": {
                                "name": "DYNATRACE_API_TOKEN",
                            },
                            "oAuth": {
                                "clientId": {"name": "DT_CLIENT_ID"},
                                "clientSecret": {"name": "DT_CLIENT_SECRET"},
                            },
                        },
                    }
                ],
            }
        ],
    }

    def export(
        self, transformed_data: Dict[str, Any], output_dir: Path
    ) -> Dict[str, int]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        summary: Dict[str, int] = {}

        # manifest.yaml
        (output_dir / "manifest.yaml").write_text(
            yaml.safe_dump(self._MANIFEST, default_flow_style=False, sort_keys=False)
        )
        logger.info("Created Monaco manifest.yaml", output_dir=str(output_dir))

        project_root = output_dir / self.PROJECT_NAME
        project_root.mkdir(parents=True, exist_ok=True)

        # ----- Settings 2.0 envelopes (schema-based) ---------------------
        for key in (
            "anomaly_detectors",
            "segments",
            "iam_policies",
            "synthetic_tests",
            "slos",
            "openpipeline_processors",
        ):
            envelopes = transformed_data.get(key) or []
            if not envelopes:
                continue
            count = self._emit_settings(envelopes, project_root)
            if count:
                summary[key] = count

        # ----- Document API dashboards -----------------------------------
        dashboards = transformed_data.get("dashboards") or []
        if dashboards:
            doc_dir = project_root / "documents"
            doc_dir.mkdir(parents=True, exist_ok=True)
            for d in dashboards:
                name = d.get("name", "unnamed")
                safe = self._safe_name(name)
                (doc_dir / f"{safe}.json").write_text(json.dumps(d, indent=2))
                (doc_dir / f"{safe}.yaml").write_text(
                    yaml.safe_dump(
                        {
                            "configs": [
                                {
                                    "id": f"dashboard-{safe}",
                                    "type": {"document": {"kind": "dashboard"}},
                                    "config": {
                                        "name": name,
                                        "template": f"{safe}.json",
                                    },
                                }
                            ]
                        },
                        sort_keys=False,
                    )
                )
            summary["dashboards"] = len(dashboards)
            logger.info("Exported Gen3 dashboards", count=len(dashboards))

        # ----- Automation workflows --------------------------------------
        workflows = transformed_data.get("workflows") or []
        if workflows:
            wf_dir = project_root / "workflows"
            wf_dir.mkdir(parents=True, exist_ok=True)
            for wf in workflows:
                title = wf.get("title", "unnamed-workflow")
                safe = self._safe_name(title)
                (wf_dir / f"{safe}.json").write_text(json.dumps(wf, indent=2))
                (wf_dir / f"{safe}.yaml").write_text(
                    yaml.safe_dump(
                        {
                            "configs": [
                                {
                                    "id": f"workflow-{safe}",
                                    "type": {"automation": {"resource": "workflow"}},
                                    "config": {
                                        "name": title,
                                        "template": f"{safe}.json",
                                    },
                                }
                            ]
                        },
                        sort_keys=False,
                    )
                )
            summary["workflows"] = len(workflows)
            logger.info("Exported Gen3 workflows", count=len(workflows))

        logger.info("Monaco Gen3 export complete", summary=summary)
        return summary

    # ------------------------------------------------------------------

    def _emit_settings(
        self, envelopes: List[Dict[str, Any]], project_root: Path
    ) -> int:
        settings_root = project_root / "settings"
        count = 0
        for env in envelopes:
            schema = env.get("schemaId", "builtin:unknown")
            value = env.get("value", {})
            name = value.get("name") or value.get("id") or f"setting-{count}"
            safe = self._safe_name(name)
            schema_dir = settings_root / self._safe_name(schema)
            schema_dir.mkdir(parents=True, exist_ok=True)

            (schema_dir / f"{safe}.json").write_text(
                json.dumps(value, indent=2)
            )
            (schema_dir / f"{safe}.yaml").write_text(
                yaml.safe_dump(
                    {
                        "configs": [
                            {
                                "id": f"migrated-{safe}",
                                "type": {
                                    "settings": {
                                        "schema": schema,
                                        "scope": env.get("scope", "environment"),
                                    }
                                },
                                "config": {
                                    "name": name,
                                    "template": f"{safe}.json",
                                },
                            }
                        ]
                    },
                    sort_keys=False,
                )
            )
            count += 1
        return count

    @staticmethod
    def _safe_name(name: str) -> str:
        safe = name.lower()
        safe = re.sub(r"[^a-z0-9]+", "-", safe)
        safe = re.sub(r"-+", "-", safe).strip("-")
        return safe[:60] or "unnamed"
