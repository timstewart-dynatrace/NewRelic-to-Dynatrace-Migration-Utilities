"""
Workload Transformer — Gen3 target.

Converts New Relic Workloads into Dynatrace Gen3 objects:

  NR Workload  ->  Segment (builtin:segment)
                +  Bucket-scoped IAM policy skeleton

Segments are the Gen3 successor to Management Zones. They are filter
definitions over `_all_data_object` / bucket scopes, expressed as a tree
of Group / Statement nodes (same JSON shape consumed by the
`dynatrace_segment` Terraform resource).

Legacy (Management Zone) behavior is preserved in
`transformers/legacy/workload_transformer_v1.py` and reached via
`--legacy`.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import re

import structlog

logger = structlog.get_logger()


@dataclass
class WorkloadTransformResult:
    """Result of workload -> Segment + IAM translation (Gen3)."""

    success: bool
    segment: Optional[Dict[str, Any]] = None
    iam_policy: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class WorkloadTransformer:
    """NR Workload -> DT Segment + IAM policy skeleton (Gen3)."""

    ENTITY_TYPE_MAP = {
        "APPLICATION": "SERVICE",
        "APM_APPLICATION": "SERVICE",
        "BROWSER_APPLICATION": "APPLICATION",
        "MOBILE_APPLICATION": "MOBILE_APPLICATION",
        "HOST": "HOST",
        "INFRASTRUCTURE_HOST": "HOST",
        "SYNTHETIC_MONITOR": "SYNTHETIC_TEST",
        "WORKLOAD": None,
        "DASHBOARD": None,
    }

    def transform(self, nr_workload: Dict[str, Any]) -> WorkloadTransformResult:
        warnings: List[str] = []
        errors: List[str] = []

        try:
            name = nr_workload.get("name", "Unnamed Workload")
            collection = nr_workload.get("collection", []) or []
            queries = nr_workload.get("entitySearchQueries", []) or []

            filter_tree = self._build_filter_tree(name, collection, queries, warnings)
            segment = self._build_segment(name, filter_tree)
            iam_policy = self._build_iam_policy(name)

            logger.info(
                "Transformed workload to Gen3 segment",
                name=name,
                children=len(filter_tree.get("children", [])),
            )
            return WorkloadTransformResult(
                success=True,
                segment=segment,
                iam_policy=iam_policy,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Workload transformation failed", error=str(exc))
            return WorkloadTransformResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    # ------------------------------------------------------------------
    # Segment filter-tree construction
    # ------------------------------------------------------------------

    def _build_filter_tree(
        self,
        workload_name: str,
        collection: List[Dict[str, Any]],
        queries: List[Dict[str, Any]],
        warnings: List[str],
    ) -> Dict[str, Any]:
        """Build a Segment filter tree (Group -> Statement children)."""
        children: List[Dict[str, Any]] = []

        # Phase 25: prefer entity-ID-based statements when GUIDs are available;
        # fall back to exact entity.name == (not contains) when the NR collection
        # carries names. This closes Gen2-only capability #4.
        by_type_ids: Dict[str, List[str]] = {}  # dt_type -> [guid1, ...]
        by_type_names: Dict[str, List[str]] = {}  # dt_type -> [name1, ...]
        for entity in collection:
            etype = entity.get("type", "UNKNOWN")
            ename = entity.get("name", "")
            eguid = entity.get("guid", "")
            dt_type = self.ENTITY_TYPE_MAP.get(etype)
            if dt_type is None:
                warnings.append(
                    f"Entity type '{etype}' for '{ename}' has no Gen3 segment mapping."
                )
                continue
            if eguid:
                by_type_ids.setdefault(dt_type, []).append(eguid)
            else:
                by_type_names.setdefault(dt_type, []).append(ename)

        for dt_type, guids in by_type_ids.items():
            children.append(
                {
                    "type": "Group",
                    "logicalOperator": "OR",
                    "children": [
                        self._statement("dt.entity.type", "=", dt_type),
                        {
                            "type": "Group",
                            "logicalOperator": "OR",
                            "children": [
                                self._statement("dt.entity.id", "=", g) for g in guids
                            ],
                        },
                    ],
                }
            )

        for dt_type, names in by_type_names.items():
            children.append(
                {
                    "type": "Group",
                    "logicalOperator": "OR",
                    "children": [
                        self._statement("dt.entity.type", "=", dt_type),
                        {
                            "type": "Group",
                            "logicalOperator": "OR",
                            "children": [
                                self._statement("entity.name", "=", n) for n in names
                            ],
                        },
                    ],
                }
            )

        for q in queries:
            parsed = self._parse_entity_query(q.get("query", ""))
            dt_type = self.ENTITY_TYPE_MAP.get(parsed["entity_type"]) if parsed["entity_type"] else None
            if not dt_type:
                warnings.append(
                    f"Could not map entity search query to a Gen3 segment filter: "
                    f"'{q.get('query', '')[:100]}'"
                )
                continue
            group_children: List[Dict[str, Any]] = [
                self._statement("dt.entity.type", "=", dt_type)
            ]
            if parsed["name_filter"]:
                group_children.append(
                    self._statement("entity.name", "contains", parsed["name_filter"])
                )
            for tag_key, tag_value in parsed["tags"]:
                group_children.append(
                    self._statement(f"tags.{tag_key}", "=", tag_value)
                )
            children.append(
                {
                    "type": "Group",
                    "logicalOperator": "AND",
                    "children": group_children,
                }
            )

        if not children:
            # Fallback: tag-based selection driven by a migration marker tag.
            tag_value = self._slug(workload_name)
            warnings.append(
                f"Workload '{workload_name}' could not be converted to specific filters. "
                f"Emitted a tag-based fallback: apply tag 'migrated-workload:{tag_value}' "
                "to relevant entities."
            )
            children.append(
                self._statement("tags.migrated-workload", "=", tag_value)
            )

        return {"type": "Group", "logicalOperator": "OR", "children": children}

    @staticmethod
    def _statement(key: str, op: str, value: str) -> Dict[str, Any]:
        return {
            "type": "Statement",
            "key": {"value": key},
            "operator": {"value": op},
            "value": {"value": value},
        }

    # ------------------------------------------------------------------
    # Segment wrapper (builtin:segment schema)
    # ------------------------------------------------------------------

    def _build_segment(self, name: str, filter_tree: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "schemaId": "builtin:segment",
            "scope": "environment",
            "value": {
                "name": f"[Migrated] {name}",
                "description": f"Migrated from New Relic Workload: {name}",
                "isPublic": False,
                "includes": {
                    "items": [
                        {
                            "dataObject": "_all_data_object",
                            "filter": filter_tree,
                        }
                    ]
                },
            },
        }

    # ------------------------------------------------------------------
    # IAM policy skeleton (bucket-scoped)
    # ------------------------------------------------------------------

    def _build_iam_policy(self, workload_name: str) -> Dict[str, Any]:
        slug = self._slug(workload_name)
        return {
            "schemaId": "builtin:iam.policy",
            "scope": "environment",
            "value": {
                "name": f"workload-{slug}-read",
                "description": (
                    f"Bucket-scoped read policy generated from NR workload '{workload_name}'. "
                    "Bind to appropriate user groups after import."
                ),
                "statementQuery": (
                    'ALLOW storage:logs:read, storage:events:read, storage:metrics:read, storage:spans:read '
                    f'WHERE segment:"[Migrated] {workload_name}"'
                ),
            },
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_entity_query(self, query: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "entity_type": None,
            "name_filter": None,
            "tags": [],
        }
        query_lower = query.lower()

        for pattern, entity_type in (
            ("application", "APPLICATION"),
            ("host", "HOST"),
            ("service", "APM_APPLICATION"),
            ("browser", "BROWSER_APPLICATION"),
            ("mobile", "MOBILE_APPLICATION"),
            ("synthetic", "SYNTHETIC_MONITOR"),
        ):
            if pattern in query_lower:
                result["entity_type"] = entity_type
                break

        name_match = re.search(r"name\s+like\s+'([^']+)'", query, re.IGNORECASE)
        if name_match:
            result["name_filter"] = name_match.group(1).replace("%", "")

        result["tags"] = re.findall(r"tags\.(\w+)\s*=\s*'([^']+)'", query, re.IGNORECASE)
        return result

    @staticmethod
    def _slug(text: str) -> str:
        slug = text.lower().replace(" ", "-")
        return "".join(c if c.isalnum() or c == "-" else "" for c in slug)

    def transform_all(
        self, workloads: List[Dict[str, Any]]
    ) -> List[WorkloadTransformResult]:
        results = [self.transform(w) for w in workloads]
        successful = sum(1 for r in results if r.success)
        logger.info(f"Transformed {successful}/{len(results)} workloads to Gen3 segments")
        return results
