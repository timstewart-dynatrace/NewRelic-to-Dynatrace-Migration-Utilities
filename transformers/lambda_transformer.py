"""
Lambda Transformer — Gen3 target.

Converts New Relic Lambda monitoring config into Dynatrace Lambda-extension
guidance:

  NR Lambda function (New Relic CloudWatchMetricStream or Lambda layer)
    -> DT serverless monitoring (DT Lambda extension layer + env vars)
    -> Per-function Settings 2.0 envelope (`builtin:aws.services.lambda`
        where applicable for tagging / log forwarding)
    -> Runbook artifact listing layer ARN, env vars, and IAM changes

The transformer does not rewrite CloudFormation/SAM/CDK by itself; it emits
the information an operator needs to apply via their IaC of choice. The
runbook artifact is attached to each `LambdaTransformResult`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


# Dynatrace public Lambda extension layer ARNs vary by region + architecture
# + runtime family. The resolver accepts a (region, arch, runtime) triple
# and emits the canonical layer ARN suffix; operators substitute the
# account id when applying.
_DT_LAMBDA_LAYER_SUFFIX = {
    # (arch, runtime_family) -> layer short-name
    ("x86_64", "nodejs"): "Dynatrace_OneAgent_Nodejs",
    ("arm64", "nodejs"): "Dynatrace_OneAgent_Nodejs_ARM64",
    ("x86_64", "python"): "Dynatrace_OneAgent_Python",
    ("arm64", "python"): "Dynatrace_OneAgent_Python_ARM64",
    ("x86_64", "java"): "Dynatrace_OneAgent_Java",
    ("x86_64", "dotnet"): "Dynatrace_OneAgent_Dotnet",
}

_RUNTIME_FAMILY = {
    "nodejs": "nodejs",
    "nodejs12.x": "nodejs",
    "nodejs14.x": "nodejs",
    "nodejs16.x": "nodejs",
    "nodejs18.x": "nodejs",
    "nodejs20.x": "nodejs",
    "python3.8": "python",
    "python3.9": "python",
    "python3.10": "python",
    "python3.11": "python",
    "python3.12": "python",
    "java8": "java",
    "java11": "java",
    "java17": "java",
    "java21": "java",
    "dotnet6": "dotnet",
    "dotnet8": "dotnet",
}


@dataclass
class LambdaTransformResult:
    """Result of NR Lambda -> DT Lambda extension translation."""

    success: bool
    settings_envelopes: List[Dict[str, Any]] = field(default_factory=list)
    runbook: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class LambdaTransformer:
    """NR Lambda monitoring config -> DT Lambda extension guidance (Gen3)."""

    def transform(self, nr_function: Dict[str, Any]) -> LambdaTransformResult:
        """Translate a single NR-monitored Lambda function.

        Args:
            nr_function: dict with keys `name`, `region`, `runtime`, `arch`
                (default `x86_64`), `handler`, `env` (dict), `accountId`.
        """
        warnings: List[str] = []
        errors: List[str] = []
        try:
            name = nr_function.get("name", "unnamed-lambda")
            region = nr_function.get("region", "us-east-1")
            runtime = str(nr_function.get("runtime", "")).lower()
            arch = str(nr_function.get("arch", "x86_64"))
            family = _RUNTIME_FAMILY.get(runtime)
            if family is None:
                warnings.append(
                    f"Runtime '{runtime}' for Lambda '{name}' has no direct "
                    "Dynatrace layer mapping; operator must install the generic "
                    "OTel layer or skip this function."
                )
                family = "generic"
            layer_suffix = _DT_LAMBDA_LAYER_SUFFIX.get((arch, family))
            if layer_suffix is None and family != "generic":
                warnings.append(
                    f"No DT layer known for arch={arch} runtime_family={family}; "
                    "fallback to OTel."
                )

            env_updates = {
                "DT_TENANT": "<set-to-DYNATRACE_ENVIRONMENT_URL>",
                "DT_CONNECTION_AUTH_TOKEN": "<set-to-DYNATRACE_API_TOKEN>",
                "DT_OPEN_TELEMETRY_ENABLE_INTEGRATION": "true",
                "DT_CLUSTER_ID": "<optional, omit unless multi-tenant>",
            }

            # The DT Lambda extension relies on a Settings 2.0 config on the
            # tenant side (log forwarding from Lambda CloudWatch logs). Emit
            # an aws.services envelope that tags the function for the
            # extension.
            settings_envelope = {
                "schemaId": "builtin:cloud.aws",
                "scope": "environment",
                "value": {
                    "label": f"[Migrated] lambda:{name}",
                    "authenticationData": {
                        # operator fills after import
                        "type": "ROLE",
                        "roleArn": "arn:aws:iam::<account>:role/dynatrace-monitoring",
                    },
                    "taggingStrategy": "TO_BE_MONITORED",
                    "tagsToMonitor": [{"name": "dt-managed", "value": "true"}],
                    "supportingServicesToMonitor": [
                        {"name": "lambda", "monitoredMetrics": ["*"]}
                    ],
                    "regions": [region],
                },
            }

            runbook = {
                "function": name,
                "region": region,
                "runtime": runtime,
                "arch": arch,
                "layer_arn_template": (
                    f"arn:aws:lambda:{region}:<dt-account-id>:layer:"
                    f"{layer_suffix or 'Dynatrace_OTel_Extension'}:<version>"
                ),
                "env_vars_to_set": env_updates,
                "iam_changes": [
                    "Grant dynatrace-monitoring role permission to read "
                    "CloudWatch log group /aws/lambda/<function-name>.",
                ],
                "post_deploy_check": (
                    "Invoke the function once; verify a Davis service appears "
                    "within 5 minutes in Dynatrace with the function name."
                ),
            }

            logger.info(
                "Transformed Lambda to Gen3 guidance",
                name=name,
                region=region,
                family=family,
            )
            return LambdaTransformResult(
                success=True,
                settings_envelopes=[settings_envelope],
                runbook=runbook,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Lambda transformation failed", error=str(exc))
            return LambdaTransformResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, functions: List[Dict[str, Any]]
    ) -> List[LambdaTransformResult]:
        results = [self.transform(f) for f in functions]
        successful = sum(1 for r in results if r.success)
        logger.info(
            f"Transformed {successful}/{len(results)} Lambda functions to Gen3 guidance"
        )
        return results
