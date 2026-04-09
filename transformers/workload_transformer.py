"""
Workload Transformer - Converts New Relic Workloads to Dynatrace Management Zones.
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class WorkloadTransformResult:
    """Result of workload transformation."""
    success: bool
    management_zone: Optional[Dict[str, Any]] = None
    warnings: List[str] = None
    errors: List[str] = None

    def __post_init__(self):
        self.warnings = self.warnings or []
        self.errors = self.errors or []


class WorkloadTransformer:
    """
    Transforms New Relic Workloads to Dynatrace Management Zones.

    New Relic Workloads:
    - Group entities for collective monitoring
    - Can use entity GUIDs or search queries
    - Support health status aggregation

    Dynatrace Management Zones:
    - Group entities using rules
    - Support dimension filters, entity selectors
    - Used for access control and dashboards
    """

    # Entity type mapping from New Relic to Dynatrace
    ENTITY_TYPE_MAP = {
        "APPLICATION": "SERVICE",
        "APM_APPLICATION": "SERVICE",
        "BROWSER_APPLICATION": "APPLICATION",
        "MOBILE_APPLICATION": "MOBILE_APPLICATION",
        "HOST": "HOST",
        "INFRASTRUCTURE_HOST": "HOST",
        "SYNTHETIC_MONITOR": "SYNTHETIC_TEST",
        "WORKLOAD": None,  # Workloads don't map directly
        "DASHBOARD": None,  # Dashboards aren't entities in DT management zones
    }

    def __init__(self):
        pass

    def transform(self, nr_workload: Dict[str, Any]) -> WorkloadTransformResult:
        """Transform a New Relic Workload to Dynatrace Management Zone."""
        warnings = []
        errors = []

        try:
            workload_name = nr_workload.get("name", "Unnamed Workload")

            # Get entities in the workload
            collection = nr_workload.get("collection", [])
            entity_search_queries = nr_workload.get("entitySearchQueries", [])

            # Build management zone rules
            rules = []

            # Convert direct entity collection to rules
            if collection:
                collection_rules = self._convert_collection_to_rules(
                    collection,
                    warnings
                )
                rules.extend(collection_rules)

            # Convert entity search queries to rules
            if entity_search_queries:
                query_rules = self._convert_queries_to_rules(
                    entity_search_queries,
                    warnings
                )
                rules.extend(query_rules)

            # If no rules generated, create a tag-based rule
            if not rules:
                warnings.append(
                    f"Workload '{workload_name}' could not be converted to specific rules. "
                    "A tag-based rule has been created. Apply the tag to relevant entities."
                )
                rules.append(self._create_tag_rule(workload_name))

            # Build Dynatrace Management Zone
            dt_management_zone = {
                "name": f"[Migrated] {workload_name}",
                "description": f"Migrated from New Relic Workload: {workload_name}",
                "rules": rules
            }

            logger.info(
                "Transformed workload to management zone",
                name=workload_name,
                rules_count=len(rules)
            )

            return WorkloadTransformResult(
                success=True,
                management_zone=dt_management_zone,
                warnings=warnings
            )

        except Exception as e:
            logger.error("Workload transformation failed", error=str(e))
            return WorkloadTransformResult(
                success=False,
                errors=[f"Transformation error: {str(e)}"]
            )

    def _convert_collection_to_rules(
        self,
        collection: List[Dict[str, Any]],
        warnings: List[str]
    ) -> List[Dict[str, Any]]:
        """Convert a collection of entities to management zone rules."""
        rules = []
        entities_by_type: Dict[str, List[str]] = {}

        # Group entities by type
        for entity in collection:
            entity_type = entity.get("type", "UNKNOWN")
            entity_name = entity.get("name", "")

            dt_type = self.ENTITY_TYPE_MAP.get(entity_type)
            if dt_type:
                if dt_type not in entities_by_type:
                    entities_by_type[dt_type] = []
                entities_by_type[dt_type].append(entity_name)
            else:
                warnings.append(
                    f"Entity type '{entity_type}' for '{entity_name}' "
                    "does not have a direct Dynatrace equivalent"
                )

        # Create rules for each entity type
        for dt_type, entity_names in entities_by_type.items():
            if len(entity_names) <= 10:
                # Create name-based conditions for small sets
                for name in entity_names:
                    rule = self._create_name_rule(dt_type, name)
                    rules.append(rule)
            else:
                # For large sets, suggest using tags
                warnings.append(
                    f"Workload contains {len(entity_names)} {dt_type} entities. "
                    "Consider using tags for better management. Creating name-based rules."
                )
                for name in entity_names:
                    rule = self._create_name_rule(dt_type, name)
                    rules.append(rule)

        return rules

    def _convert_queries_to_rules(
        self,
        queries: List[Dict[str, Any]],
        warnings: List[str]
    ) -> List[Dict[str, Any]]:
        """Convert entity search queries to management zone rules."""
        rules = []

        for query_obj in queries:
            query = query_obj.get("query", "")

            # Parse the query to extract conditions
            parsed = self._parse_entity_query(query)

            if parsed["entity_type"]:
                dt_type = self.ENTITY_TYPE_MAP.get(parsed["entity_type"])
                if dt_type:
                    rule = {
                        "type": "ME",
                        "enabled": True,
                        "entitySelector": f"type(\"{dt_type}\")"
                    }

                    # Add name filter if present
                    if parsed["name_filter"]:
                        rule["entitySelector"] += f",entityName.contains(\"{parsed['name_filter']}\")"

                    # Add tag filter if present
                    if parsed["tags"]:
                        for tag_key, tag_value in parsed["tags"]:
                            rule["entitySelector"] += f",tag(\"{tag_key}:{tag_value}\")"

                    rules.append(rule)
                else:
                    warnings.append(
                        f"Query entity type '{parsed['entity_type']}' "
                        "could not be mapped to Dynatrace"
                    )
            else:
                warnings.append(
                    f"Could not parse query: {query[:100]}... "
                    "Manual rule creation may be required."
                )

        return rules

    def _parse_entity_query(self, query: str) -> Dict[str, Any]:
        """
        Parse a New Relic entity search query.

        Example queries:
        - "type = 'APPLICATION'"
        - "name LIKE 'production%'"
        - "tags.environment = 'prod'"
        """
        result = {
            "entity_type": None,
            "name_filter": None,
            "tags": []
        }

        query_lower = query.lower()

        # Extract entity type
        if "type" in query_lower:
            # Simple extraction - look for common patterns
            type_patterns = [
                ("application", "APPLICATION"),
                ("host", "HOST"),
                ("service", "APM_APPLICATION"),
                ("browser", "BROWSER_APPLICATION"),
                ("mobile", "MOBILE_APPLICATION"),
                ("synthetic", "SYNTHETIC_MONITOR"),
            ]

            for pattern, entity_type in type_patterns:
                if pattern in query_lower:
                    result["entity_type"] = entity_type
                    break

        # Extract name filter
        if "name" in query_lower:
            # Look for LIKE patterns
            import re
            name_match = re.search(r"name\s+like\s+'([^']+)'", query, re.IGNORECASE)
            if name_match:
                result["name_filter"] = name_match.group(1).replace("%", "")

        # Extract tags
        if "tags." in query_lower:
            import re
            tag_matches = re.findall(r"tags\.(\w+)\s*=\s*'([^']+)'", query, re.IGNORECASE)
            result["tags"] = tag_matches

        return result

    def _create_name_rule(self, entity_type: str, name: str) -> Dict[str, Any]:
        """Create a management zone rule based on entity name."""
        return {
            "type": "ME",
            "enabled": True,
            "entitySelector": f"type(\"{entity_type}\"),entityName.equals(\"{name}\")"
        }

    def _create_tag_rule(self, workload_name: str) -> Dict[str, Any]:
        """Create a tag-based management zone rule."""
        # Sanitize workload name for tag value
        tag_value = workload_name.lower().replace(" ", "-")
        tag_value = "".join(c if c.isalnum() or c == "-" else "" for c in tag_value)

        return {
            "type": "ME",
            "enabled": True,
            "entitySelector": f"tag(\"migrated-workload:{tag_value}\")"
        }

    def transform_all(
        self,
        workloads: List[Dict[str, Any]]
    ) -> List[WorkloadTransformResult]:
        """Transform multiple workloads."""
        results = []

        for workload in workloads:
            result = self.transform(workload)
            results.append(result)

        successful = sum(1 for r in results if r.success)
        logger.info(f"Transformed {successful}/{len(results)} workloads to management zones")

        return results
