"""
Kubernetes Transformer — Gen3 target.

New Relic Kubernetes integration config (nri-kubernetes DaemonSet + infra
agent) maps to Dynatrace Kubernetes monitoring via DynaKube — the CR
managed by the Dynatrace Operator. This transformer emits a DynaKube
manifest (YAML-serializable dict) plus a Helm values fragment.

Node-level vs pod-level scope is preserved by setting
`spec.oneAgent.hostMonitoring.enabled` and
`spec.oneAgent.cloudNativeFullStack.enabled` to match NR's deployment
mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class KubernetesTransformResult:
    success: bool
    dynakube_manifest: Optional[Dict[str, Any]] = None
    helm_values: Optional[Dict[str, Any]] = None
    runbook: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class KubernetesTransformer:
    """NR K8s integration -> DynaKube manifest + Helm values (Gen3)."""

    def transform(
        self, nr_cluster: Dict[str, Any]
    ) -> KubernetesTransformResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            cluster_name = nr_cluster.get("clusterName", "unnamed-cluster")
            mode = str(nr_cluster.get("mode", "full_stack")).lower()
            api_url = nr_cluster.get("dtApiUrl", "<set-DT-API-URL>")
            namespaces = nr_cluster.get("namespaces") or []
            labels = nr_cluster.get("labels") or {}

            host_monitoring_only = mode in ("host_only", "infra_only")
            full_stack = not host_monitoring_only
            if mode not in ("full_stack", "host_only", "infra_only"):
                warnings.append(
                    f"Unknown K8s mode '{mode}' — defaulting to "
                    "cloudNativeFullStack. Review before apply."
                )

            dynakube = {
                "apiVersion": "dynatrace.com/v1beta3",
                "kind": "DynaKube",
                "metadata": {
                    "name": cluster_name.lower().replace("_", "-"),
                    "namespace": "dynatrace",
                    "annotations": {
                        "feature.dynatrace.com/automatic-kubernetes-api-monitoring": "true",
                    },
                },
                "spec": {
                    "apiUrl": api_url,
                    "tokens": cluster_name.lower().replace("_", "-") + "-tokens",
                    "skipCertCheck": False,
                    "oneAgent": {
                        "cloudNativeFullStack": (
                            {
                                "args": [],
                                "env": [
                                    {"name": "DT_K8S_CLUSTER_NAME", "value": cluster_name},
                                ],
                            }
                            if full_stack
                            else {}
                        ),
                        "hostMonitoring": (
                            {"args": []}
                            if host_monitoring_only
                            else {}
                        ),
                    },
                    "activeGate": {
                        "capabilities": [
                            "routing",
                            "kubernetes-monitoring",
                            "dynatrace-api",
                        ],
                        "replicas": 2,
                    },
                },
            }

            if namespaces:
                dynakube["spec"]["namespaceSelector"] = {
                    "matchExpressions": [
                        {"key": "name", "operator": "In", "values": list(namespaces)}
                    ]
                }

            helm_values = {
                "installCRD": True,
                "platform": "kubernetes",
                "webhook": {"hostNetwork": False},
                "dynakube": dynakube,
                "customLabels": labels,
            }

            runbook = {
                "cluster": cluster_name,
                "mode": mode,
                "pre_apply_steps": [
                    "helm repo add dynatrace https://raw.githubusercontent.com/Dynatrace/dynatrace-operator/main/config/helm/repos/stable",
                    "helm install dynatrace-operator dynatrace/dynatrace-operator -n dynatrace --create-namespace",
                    "Create the token secret: kubectl create secret generic <name>-tokens --from-literal=apiToken=<DT_API_TOKEN> --from-literal=dataIngestToken=<INGEST>",
                    "kubectl apply -f dynakube.yaml",
                ],
                "nri_kubernetes_uninstall": [
                    "helm uninstall newrelic-bundle -n newrelic",
                    "kubectl delete namespace newrelic",
                ],
            }

            logger.info(
                "Transformed K8s cluster config to DynaKube",
                cluster=cluster_name,
                mode=mode,
                namespaces=len(namespaces),
            )
            return KubernetesTransformResult(
                success=True,
                dynakube_manifest=dynakube,
                helm_values=helm_values,
                runbook=runbook,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Kubernetes transformation failed", error=str(exc))
            return KubernetesTransformResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, clusters: List[Dict[str, Any]]
    ) -> List[KubernetesTransformResult]:
        return [self.transform(c) for c in clusters]
