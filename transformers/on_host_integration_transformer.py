"""
On-Host Integration Transformer — Gen3 target.

NR on-host integrations (nri-nginx, nri-haproxy, nri-kafka,
nri-elasticsearch, nri-memcached, nri-couchbase, nri-consul,
nri-apache, nri-etcd, nri-rabbitmq) map to Dynatrace extensions via
Settings 2.0 schema `builtin:dynatrace.extension.<tech>`.

The transformer emits one Settings 2.0 envelope per integration plus
a runbook describing which extension must be activated in the DT
extension hub.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


_INTEGRATION_MAP = {
    "nginx": "builtin:dynatrace.extension.nginx",
    "haproxy": "builtin:dynatrace.extension.haproxy",
    "kafka": "builtin:dynatrace.extension.kafka",
    "rabbitmq": "builtin:dynatrace.extension.rabbitmq",
    "elasticsearch": "builtin:dynatrace.extension.elasticsearch",
    "memcached": "builtin:dynatrace.extension.memcached",
    "couchbase": "builtin:dynatrace.extension.couchbase",
    "consul": "builtin:dynatrace.extension.consul",
    "apache": "builtin:dynatrace.extension.apache",
    "etcd": "builtin:dynatrace.extension.etcd",
    "varnish": "builtin:dynatrace.extension.varnish",
    "zookeeper": "builtin:dynatrace.extension.zookeeper",
}


@dataclass
class OnHostIntegrationResult:
    success: bool
    envelope: Optional[Dict[str, Any]] = None
    runbook: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class OnHostIntegrationTransformer:
    """NR on-host integration config -> DT extension Settings 2.0."""

    def transform(self, nr_config: Dict[str, Any]) -> OnHostIntegrationResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            name = nr_config.get("name", "unnamed-integration")
            tech = str(nr_config.get("integration", "")).lower()
            schema_id = _INTEGRATION_MAP.get(tech)
            if schema_id is None:
                warnings.append(
                    f"Integration '{tech}' has no direct DT extension mapping. "
                    f"Supported: {', '.join(sorted(_INTEGRATION_MAP))}"
                )
                return OnHostIntegrationResult(
                    success=False,
                    errors=[f"Unsupported integration: {tech}"],
                    warnings=warnings,
                )

            envelope = {
                "schemaId": schema_id,
                "scope": "environment",
                "value": {
                    "name": f"[Migrated] {name}",
                    "enabled": True,
                    "endpoints": nr_config.get("endpoints", []) or [],
                    "pollingIntervalSeconds": int(
                        nr_config.get("pollingIntervalSeconds", 30)
                    ),
                    "credentialsReference": "<pick-credential-after-import>",
                },
            }

            runbook = {
                "integration": tech,
                "activation_steps": [
                    f"In DT Settings > Extensions, ensure the {tech} extension is activated on the target host group.",
                    "Create credentials via DT Vault if the integration needs auth (most do not for read-only metrics).",
                    "Install the host-level binary/agent the integration reads from, if not already present.",
                ],
                "nr_cleanup": [
                    f"Remove the nri-{tech} config from /etc/newrelic-infra/integrations.d/ and restart newrelic-infra.",
                ],
            }

            logger.info(
                "Transformed on-host integration",
                name=name,
                tech=tech,
            )
            return OnHostIntegrationResult(
                success=True,
                envelope=envelope,
                runbook=runbook,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("On-host integration transformation failed", error=str(exc))
            return OnHostIntegrationResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, configs: List[Dict[str, Any]]
    ) -> List[OnHostIntegrationResult]:
        return [self.transform(c) for c in configs]
