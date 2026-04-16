"""
Network Performance Monitoring (NPM) Transformer — Gen3 target.

NR Network Performance Monitoring (KTranslate) configs (SNMP device
targets, flow collection endpoints, custom profiles) map to Dynatrace
Network monitoring via:

  builtin:network.snmp-device          -- per-device config
  builtin:network.netflow              -- flow collector config

DT's Network app is a superset — device discovery is auto in most cases,
so the transformer's job is mostly to carry forward community strings,
custom polling intervals, and flow source IPs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class NPMTransformResult:
    success: bool
    device_envelopes: List[Dict[str, Any]] = field(default_factory=list)
    netflow_envelope: Optional[Dict[str, Any]] = None
    runbook: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class NPMTransformer:
    """NR NPM config -> DT Network monitoring settings."""

    def transform(self, nr_config: Dict[str, Any]) -> NPMTransformResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            devices = nr_config.get("snmpDevices") or []
            flow = nr_config.get("netflow") or {}

            device_envelopes: List[Dict[str, Any]] = []
            for d in devices:
                device_envelopes.append(
                    {
                        "schemaId": "builtin:network.snmp-device",
                        "scope": "environment",
                        "value": {
                            "name": f"[Migrated] {d.get('name', 'device')}",
                            "ipAddress": d.get("ipAddress", ""),
                            "snmpVersion": d.get("snmpVersion", "2c"),
                            "community": "<rotate-after-import>",
                            "pollIntervalSeconds": int(
                                d.get("pollIntervalSeconds", 60)
                            ),
                            "enabled": bool(d.get("enabled", True)),
                        },
                    }
                )
                if d.get("community"):
                    warnings.append(
                        f"SNMP community for device '{d.get('name')}' will NOT be "
                        "migrated — operator re-enters the secret in DT."
                    )

            netflow_envelope: Optional[Dict[str, Any]] = None
            if flow:
                netflow_envelope = {
                    "schemaId": "builtin:network.netflow",
                    "scope": "environment",
                    "value": {
                        "enabled": bool(flow.get("enabled", True)),
                        "listenPort": int(flow.get("listenPort", 2055)),
                        "sourceSubnets": flow.get("sourceSubnets") or [],
                        "activeGateReference": "<pick-ActiveGate-after-import>",
                    },
                }

            runbook = {
                "activegate_requirement": (
                    "DT Network monitoring requires an ActiveGate with the "
                    "NetFlow + SNMP modules enabled. Install or pick an "
                    "existing ActiveGate before applying device envelopes."
                ),
                "ktranslate_uninstall": [
                    "Stop the KTranslate container: `docker stop ktranslate`",
                    "Remove the NR infrastructure-agent NPM package if bundled.",
                ],
            }

            logger.info(
                "Transformed NPM config",
                devices=len(device_envelopes),
                netflow=netflow_envelope is not None,
            )
            return NPMTransformResult(
                success=True,
                device_envelopes=device_envelopes,
                netflow_envelope=netflow_envelope,
                runbook=runbook,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("NPM transformation failed", error=str(exc))
            return NPMTransformResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, configs: List[Dict[str, Any]]
    ) -> List[NPMTransformResult]:
        return [self.transform(c) for c in configs]
