"""
Database Monitoring Transformer — Gen3 target.

NR Database Monitoring (NRDM) config for MySQL / PostgreSQL / MSSQL /
Oracle / MongoDB / Redis / Cassandra / MariaDB / DB2 / SAP HANA maps
to Dynatrace DB extensions (`builtin:dynatrace.extension.db.*`).

Output per DB:
  - Settings 2.0 envelope for the DT DB extension with connection metadata
  - Credential-rotation runbook item (secrets never migrate)
  - Query-performance metric mapping notes (DT auto-captures via OneAgent)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


# NR DB type -> DT extension schema id + OneAgent technology family.
_DB_EXTENSION_MAP = {
    "mysql": ("builtin:dynatrace.extension.db.mysql", "MYSQL"),
    "postgresql": ("builtin:dynatrace.extension.db.postgres", "POSTGRESQL"),
    "postgres": ("builtin:dynatrace.extension.db.postgres", "POSTGRESQL"),
    "mssql": ("builtin:dynatrace.extension.db.mssql", "MSSQL"),
    "sqlserver": ("builtin:dynatrace.extension.db.mssql", "MSSQL"),
    "oracle": ("builtin:dynatrace.extension.db.oracle", "ORACLE"),
    "mongodb": ("builtin:dynatrace.extension.db.mongodb", "MONGODB"),
    "redis": ("builtin:dynatrace.extension.db.redis", "REDIS"),
    "cassandra": ("builtin:dynatrace.extension.db.cassandra", "CASSANDRA"),
    "mariadb": ("builtin:dynatrace.extension.db.mariadb", "MARIADB"),
    "db2": ("builtin:dynatrace.extension.db.db2", "DB2"),
    "saphana": ("builtin:dynatrace.extension.db.saphana", "SAP_HANA"),
}


@dataclass
class DatabaseMonitoringResult:
    success: bool
    envelope: Optional[Dict[str, Any]] = None
    runbook: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class DatabaseMonitoringTransformer:
    """NR Database Monitoring config -> DT DB extension Settings 2.0."""

    def transform(self, nr_config: Dict[str, Any]) -> DatabaseMonitoringResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            name = nr_config.get("name", "unnamed-db")
            db_type = str(nr_config.get("dbType", "")).lower()
            host = nr_config.get("host", "")
            port = nr_config.get("port")
            username = nr_config.get("username", "")
            databases = nr_config.get("databases") or []

            mapping = _DB_EXTENSION_MAP.get(db_type)
            if mapping is None:
                warnings.append(
                    f"DB type '{db_type}' has no direct DT extension mapping. "
                    "Supported: " + ", ".join(sorted(_DB_EXTENSION_MAP))
                )
                return DatabaseMonitoringResult(
                    success=False,
                    errors=[f"Unsupported DB type: {db_type}"],
                    warnings=warnings,
                )
            schema_id, technology = mapping

            envelope = {
                "schemaId": schema_id,
                "scope": "environment",
                "value": {
                    "name": f"[Migrated] {name}",
                    "enabled": True,
                    "host": host,
                    "port": port,
                    "username": username,
                    "password": "<rotate-after-import>",
                    "databases": list(databases),
                    "collectQueryPerformance": bool(
                        nr_config.get("collectQueryPerformance", True)
                    ),
                    "collectionIntervalSeconds": int(
                        nr_config.get("collectionIntervalSeconds", 60)
                    ),
                },
            }

            runbook = {
                "technology": technology,
                "secret_rotation_steps": [
                    f"In DT, navigate to Settings > Monitored technologies > {technology} and create a new credential.",
                    "Paste the DB password into the credential form (never commit it to source).",
                    "Reference the credential via DT vault alias in the envelope after import.",
                ],
                "oneagent_note": (
                    "OneAgent automatically captures wire-level DB query "
                    f"timings for {technology}. The extension above captures "
                    "internal DB metrics (locks, buffer pool, replication lag). "
                    "Both are usually enabled together."
                ),
            }

            logger.info(
                "Transformed DB monitoring config",
                name=name,
                db_type=db_type,
            )
            return DatabaseMonitoringResult(
                success=True,
                envelope=envelope,
                runbook=runbook,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("DB monitoring transformation failed", error=str(exc))
            return DatabaseMonitoringResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, configs: List[Dict[str, Any]]
    ) -> List[DatabaseMonitoringResult]:
        return [self.transform(c) for c in configs]
