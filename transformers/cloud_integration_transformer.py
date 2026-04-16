"""
Cloud Integration Transformer — Gen3 target.

New Relic cloud integrations (AWS, Azure, GCP) map to Dynatrace native
cloud integrations via Settings 2.0 schemas:

  NR AWS link account  -> builtin:cloud.aws   + IAM role scaffold
  NR Azure link        -> builtin:cloud.azure + app registration scaffold
  NR GCP link          -> builtin:cloud.gcp   + service-account scaffold

Per-service mapping covers the most common NR-monitored services:
RDS / DynamoDB / EC2 / EKS / Lambda on AWS; VMs / SQL / App Service / AKS
on Azure; GKE / BigQuery / Cloud SQL on GCP.

Secrets (IAM role ARN, app registration client secret, service-account
key) are never emitted in the transformer output — the runbook lists
what the operator must re-create and apply.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


# NR-monitored AWS service -> DT `supportingServicesToMonitor` entry.
_AWS_SERVICE_MAP = {
    "ec2": {"name": "ec2", "monitoredMetrics": ["*"]},
    "rds": {"name": "rds", "monitoredMetrics": ["*"]},
    "dynamodb": {"name": "dynamodb", "monitoredMetrics": ["*"]},
    "eks": {"name": "eks", "monitoredMetrics": ["*"]},
    "lambda": {"name": "lambda", "monitoredMetrics": ["*"]},
    "s3": {"name": "s3", "monitoredMetrics": ["*"]},
    "alb": {"name": "alb", "monitoredMetrics": ["*"]},
    "elb": {"name": "elb", "monitoredMetrics": ["*"]},
    "sqs": {"name": "sqs", "monitoredMetrics": ["*"]},
    "sns": {"name": "sns", "monitoredMetrics": ["*"]},
    "kinesis": {"name": "kinesis_streams", "monitoredMetrics": ["*"]},
    "elasticache": {"name": "elasticache", "monitoredMetrics": ["*"]},
    "cloudfront": {"name": "cloudfront", "monitoredMetrics": ["*"]},
    "apigateway": {"name": "apigateway", "monitoredMetrics": ["*"]},
    "route53": {"name": "route53", "monitoredMetrics": ["*"]},
    "billing": {"name": "billing", "monitoredMetrics": ["*"]},
}

# NR-monitored Azure service -> DT services monitor block.
_AZURE_SERVICE_MAP = {
    "vms": "microsoft.compute/virtualmachines",
    "sql": "microsoft.sql/servers/databases",
    "appservice": "microsoft.web/sites",
    "aks": "microsoft.containerservice/managedclusters",
    "storage": "microsoft.storage/storageaccounts",
    "functions": "microsoft.web/sites/functions",
    "cosmosdb": "microsoft.documentdb/databaseaccounts",
    "servicebus": "microsoft.servicebus/namespaces",
}

# NR-monitored GCP service -> DT GCP service entry.
_GCP_SERVICE_MAP = {
    "gke": {"service": "kubernetes"},
    "bigquery": {"service": "bigquery"},
    "cloudsql": {"service": "cloudsql"},
    "cloudfunctions": {"service": "cloud_functions"},
    "cloudrun": {"service": "cloud_run"},
    "pubsub": {"service": "pubsub"},
    "storage": {"service": "storage"},
    "compute": {"service": "compute"},
}


@dataclass
class CloudIntegrationResult:
    success: bool
    envelope: Optional[Dict[str, Any]] = None
    runbook: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class CloudIntegrationTransformer:
    """NR cloud integration -> DT cloud integration Settings 2.0."""

    def transform(self, nr_integration: Dict[str, Any]) -> CloudIntegrationResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            provider = str(nr_integration.get("provider", "")).lower()
            if provider == "aws":
                return self._aws(nr_integration, warnings)
            if provider == "azure":
                return self._azure(nr_integration, warnings)
            if provider == "gcp":
                return self._gcp(nr_integration, warnings)
            return CloudIntegrationResult(
                success=False,
                errors=[
                    f"Unsupported provider '{provider}'. Supported: aws, azure, gcp."
                ],
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Cloud integration transformation failed", error=str(exc))
            return CloudIntegrationResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    # ------------------------------------------------------------------

    def _aws(
        self, nr: Dict[str, Any], warnings: List[str]
    ) -> CloudIntegrationResult:
        name = nr.get("name", "unnamed-aws-link")
        account_id = nr.get("awsAccountId", "")
        regions = nr.get("regions") or ["us-east-1"]
        services = nr.get("services") or list(_AWS_SERVICE_MAP)
        tags_to_monitor = nr.get("tagsToMonitor") or [
            {"name": "dt-managed", "value": "true"}
        ]

        supporting = []
        for svc in services:
            key = svc.lower()
            mapping = _AWS_SERVICE_MAP.get(key)
            if mapping is None:
                warnings.append(
                    f"AWS service '{svc}' has no direct DT mapping — skipped."
                )
                continue
            supporting.append(mapping)

        envelope = {
            "schemaId": "builtin:cloud.aws",
            "scope": "environment",
            "value": {
                "label": f"[Migrated] {name}",
                "authenticationData": {
                    "type": "ROLE",
                    "accountId": account_id,
                    "roleArn": f"arn:aws:iam::{account_id}:role/dynatrace-monitoring",
                    "externalId": "<fill-after-import>",
                },
                "partitionType": "AWS_DEFAULT",
                "taggingStrategy": "TO_BE_MONITORED",
                "tagsToMonitor": tags_to_monitor,
                "supportingServicesToMonitor": supporting,
                "regions": list(regions),
            },
        }

        runbook = {
            "provider": "aws",
            "iam_policy_required": [
                "cloudwatch:Get*", "cloudwatch:List*",
                "tag:GetResources", "tag:GetTagKeys",
                "logs:DescribeLogGroups", "logs:FilterLogEvents",
                "lambda:ListFunctions", "rds:DescribeDBInstances",
                "ec2:Describe*", "eks:DescribeCluster", "eks:ListClusters",
            ],
            "trust_policy": (
                "Allow sts:AssumeRole from the Dynatrace-hosted principal "
                "(arn:aws:iam::509560245411:root for SaaS). Use externalId "
                "returned by DT after initial create."
            ),
            "post_import_steps": [
                "Create or update the dynatrace-monitoring IAM role in your AWS account.",
                "Apply the trust policy with DT-provided externalId.",
                "Save the integration in DT; wait ~5 minutes for metrics to appear.",
            ],
        }

        return CloudIntegrationResult(
            success=True, envelope=envelope, runbook=runbook, warnings=warnings
        )

    def _azure(
        self, nr: Dict[str, Any], warnings: List[str]
    ) -> CloudIntegrationResult:
        name = nr.get("name", "unnamed-azure-link")
        subscription = nr.get("subscriptionId", "")
        tenant = nr.get("tenantId", "")
        services = nr.get("services") or list(_AZURE_SERVICE_MAP)

        svc_list = []
        for svc in services:
            azure_resource = _AZURE_SERVICE_MAP.get(svc.lower())
            if azure_resource is None:
                warnings.append(
                    f"Azure service '{svc}' has no direct DT mapping — skipped."
                )
                continue
            svc_list.append({"name": azure_resource})

        envelope = {
            "schemaId": "builtin:cloud.azure",
            "scope": "environment",
            "value": {
                "label": f"[Migrated] {name}",
                "appId": "<fill-after-app-registration>",
                "directoryId": tenant,
                "subscriptionId": subscription,
                "monitorResources": svc_list,
                "autoTagging": True,
            },
        }

        runbook = {
            "provider": "azure",
            "app_registration_steps": [
                "Create an Azure AD app registration for Dynatrace.",
                "Grant the app Reader role on the target subscription(s).",
                "Copy appId into the envelope; create a client secret and "
                "paste it into DT (secrets never migrate).",
            ],
        }

        return CloudIntegrationResult(
            success=True, envelope=envelope, runbook=runbook, warnings=warnings
        )

    def _gcp(
        self, nr: Dict[str, Any], warnings: List[str]
    ) -> CloudIntegrationResult:
        name = nr.get("name", "unnamed-gcp-link")
        project_id = nr.get("projectId", "")
        services = nr.get("services") or list(_GCP_SERVICE_MAP)

        svc_list = []
        for svc in services:
            mapped = _GCP_SERVICE_MAP.get(svc.lower())
            if mapped is None:
                warnings.append(
                    f"GCP service '{svc}' has no direct DT mapping — skipped."
                )
                continue
            svc_list.append(mapped)

        envelope = {
            "schemaId": "builtin:cloud.gcp",
            "scope": "environment",
            "value": {
                "label": f"[Migrated] {name}",
                "projectId": project_id,
                "services": svc_list,
                "serviceAccountKeyFingerprint": "<fill-after-key-upload>",
            },
        }

        runbook = {
            "provider": "gcp",
            "service_account_steps": [
                "Create a GCP service account with roles/monitoring.viewer, "
                "roles/logging.viewer, roles/container.viewer.",
                "Generate a JSON key for the service account.",
                "Upload the key to DT via the cloud integration UI — "
                "the key never leaves the operator's machine.",
            ],
        }

        return CloudIntegrationResult(
            success=True, envelope=envelope, runbook=runbook, warnings=warnings
        )

    def transform_all(
        self, integrations: List[Dict[str, Any]]
    ) -> List[CloudIntegrationResult]:
        return [self.transform(i) for i in integrations]
