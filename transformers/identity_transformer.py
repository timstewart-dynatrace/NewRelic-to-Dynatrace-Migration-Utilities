"""
Identity Transformer — Gen3 target.

New Relic identity primitives map to Dynatrace IAM:

  NR Users            -> builtin:iam.users        (user records)
  NR Teams            -> builtin:iam.groups       (group records)
  NR Roles            -> builtin:iam.policy       (policy statements)
  NR SAML config      -> builtin:identity.saml    (IdP metadata)
  NR SCIM             -> SCIM provisioning config (documentation)
  NR API keys         -> DT API tokens           (operator re-creates; secrets
                                                  never migrate)
  NR Service accounts -> DT OAuth2 clients       (documentation)

API keys and SAML certificates are explicitly non-migratable (secrets);
the transformer emits them as runbook items rather than Settings payloads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


# NR role -> DT built-in policy approximation.
_ROLE_TO_POLICY = {
    "admin": 'ALLOW * WHERE true',
    "All product admin": 'ALLOW * WHERE true',
    "user": (
        'ALLOW storage:logs:read, storage:events:read, storage:metrics:read, '
        'storage:spans:read'
    ),
    "read_only": (
        'ALLOW storage:logs:read, storage:events:read, storage:metrics:read'
    ),
    "Manage alerts": (
        'ALLOW settings:objects:read, settings:objects:write '
        'WHERE schema == "builtin:davis.anomaly-detectors" OR '
        'schema == "builtin:deployment.maintenance"'
    ),
    "Manage dashboards": (
        'ALLOW document:documents:read, document:documents:write '
        'WHERE type == "dashboard"'
    ),
}


@dataclass
class IdentityTransformResult:
    success: bool
    user_envelopes: List[Dict[str, Any]] = field(default_factory=list)
    group_envelopes: List[Dict[str, Any]] = field(default_factory=list)
    policy_envelopes: List[Dict[str, Any]] = field(default_factory=list)
    saml_envelope: Optional[Dict[str, Any]] = None
    runbook: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class IdentityTransformer:
    """Translate NR identity export to DT IAM Settings 2.0 envelopes."""

    def transform(self, nr_identity: Dict[str, Any]) -> IdentityTransformResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            users_in = nr_identity.get("users", []) or []
            teams_in = nr_identity.get("teams", []) or []
            roles_in = nr_identity.get("roles", []) or []
            saml_in = nr_identity.get("saml")
            scim_in = nr_identity.get("scim")
            api_keys_in = nr_identity.get("apiKeys", []) or []
            service_accounts_in = nr_identity.get("serviceAccounts", []) or []

            user_envelopes = [self._user_envelope(u) for u in users_in]
            group_envelopes = [self._group_envelope(t) for t in teams_in]
            policy_envelopes = [
                self._policy_envelope(r, warnings) for r in roles_in
            ]

            saml_envelope: Optional[Dict[str, Any]] = None
            if saml_in:
                saml_envelope = self._saml_envelope(saml_in, warnings)

            runbook = {
                "api_keys": [
                    {
                        "name": k.get("name", ""),
                        "type": k.get("type", ""),
                        "action": (
                            "Re-create as DT API token (Api-Token scope varies) "
                            "or OAuth2 client for Platform APIs. Secrets never "
                            "migrate."
                        ),
                    }
                    for k in api_keys_in
                ],
                "service_accounts": [
                    {
                        "name": sa.get("name", ""),
                        "action": "Register a new OAuth2 client in DT account settings.",
                    }
                    for sa in service_accounts_in
                ],
                "scim_config": (
                    {
                        "nr_bridge": scim_in.get("bridgeUrl"),
                        "action": (
                            "Configure DT SCIM bridge or direct IdP connector. "
                            "Map NR user attributes to DT user fields (email, "
                            "displayName, groups)."
                        ),
                    }
                    if scim_in
                    else None
                ),
            }

            if api_keys_in:
                warnings.append(
                    f"{len(api_keys_in)} API keys listed — secrets do not migrate. "
                    "Operator must re-issue DT tokens with matching scopes."
                )
            if saml_in and saml_in.get("signingCertificate"):
                warnings.append(
                    "SAML signing certificate present in export; do not commit "
                    "to source control. Upload directly in DT identity settings."
                )

            logger.info(
                "Transformed identity export",
                users=len(user_envelopes),
                groups=len(group_envelopes),
                policies=len(policy_envelopes),
                saml=saml_envelope is not None,
            )
            return IdentityTransformResult(
                success=True,
                user_envelopes=user_envelopes,
                group_envelopes=group_envelopes,
                policy_envelopes=policy_envelopes,
                saml_envelope=saml_envelope,
                runbook=runbook,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Identity transformation failed", error=str(exc))
            return IdentityTransformResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    # ------------------------------------------------------------------

    def _user_envelope(self, u: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "schemaId": "builtin:iam.users",
            "scope": "environment",
            "value": {
                "email": u.get("email", ""),
                "name": u.get("name") or u.get("email", ""),
                "userType": _map_user_type(u.get("type")),
                "groups": u.get("teams", []),
                "enabled": bool(u.get("enabled", True)),
            },
        }

    def _group_envelope(self, t: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "schemaId": "builtin:iam.groups",
            "scope": "environment",
            "value": {
                "name": t.get("name", "unnamed-group"),
                "description": t.get("description", ""),
                "members": t.get("memberEmails", []),
                "policies": t.get("assignedPolicies", []),
            },
        }

    def _policy_envelope(
        self, r: Dict[str, Any], warnings: List[str]
    ) -> Dict[str, Any]:
        name = r.get("name", "unnamed-role")
        statement = _ROLE_TO_POLICY.get(
            name.lower(), _ROLE_TO_POLICY.get(name)
        )
        if statement is None:
            statement = (
                "ALLOW storage:*:read WHERE true  "
                "-- placeholder, review and tighten"
            )
            warnings.append(
                f"Role '{name}' has no direct DT policy mapping — emitted a "
                "read-all placeholder; review before binding."
            )
        return {
            "schemaId": "builtin:iam.policy",
            "scope": "environment",
            "value": {
                "name": f"migrated-{_slug(name)}",
                "description": r.get(
                    "description", f"Migrated from NR role '{name}'."
                ),
                "statementQuery": statement,
            },
        }

    def _saml_envelope(
        self, saml_in: Dict[str, Any], warnings: List[str]
    ) -> Dict[str, Any]:
        return {
            "schemaId": "builtin:identity.saml",
            "scope": "environment",
            "value": {
                "enabled": bool(saml_in.get("enabled", True)),
                "issuerUri": saml_in.get("issuer", ""),
                "ssoUrl": saml_in.get("ssoUrl", ""),
                "entityId": saml_in.get("entityId", ""),
                # Upload cert separately — never inline.
                "signingCertificateReference": "(upload via DT UI)",
                "attributeMappings": saml_in.get("attributeMappings", {}),
            },
        }


def _map_user_type(nr_type: Optional[str]) -> str:
    mapping = {
        "FULL_USER": "FULL",
        "CORE_USER": "STANDARD",
        "BASIC_USER": "LIMITED",
    }
    return mapping.get(str(nr_type).upper(), "STANDARD")


def _slug(text: str) -> str:
    safe = text.lower()
    safe = "".join(c if c.isalnum() or c in ("-", "_") else "-" for c in safe)
    return safe.strip("-") or "policy"
