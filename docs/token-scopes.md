# Dynatrace Token Scopes for Migration

The `migrate.py` tool targets **Dynatrace Gen3 Platform APIs** by default
(Settings 2.0, Document API, Automation API) and falls back to **Classic
Config v1** when invoked with `--legacy`. Each surface requires different
token scopes. This document is the canonical scope reference and is kept in
sync with the output of `python3 migrate.py preflight`.

If `preflight` reports an API as `no`, it prints the specific missing scopes
and remediation steps. Read that output first — this document is the
background reference.

---

## Token Types

| Token type | Prefix | Used for | Recommended for |
|------------|--------|----------|-----------------|
| **Platform Token** | `dt0s16.` | Gen3 Platform APIs (Settings 2.0, Documents, Automation, Grail storage) | **Default** — all new migrations |
| **Classic API Token** | `dt0c01.` | Config v1 APIs only (alerting profiles, metric events, management zones, classic dashboards) | `--legacy` runs against tenants not yet upgraded to Gen3 |
| **OAuth2 client credentials** | *(not a token)* | Same Gen3 surfaces as Platform Token, required for inter-account flows | Account admins automating at scale |

`DYNATRACE_API_TOKEN` accepts any of the three. Default mode assumes
`dt0s16.*` (Platform Token). The `--legacy` flag switches the migrate path
to Classic and expects `dt0c01.*`.

---

## Minimum Scopes — Preflight Probe

These are the scopes the **`preflight` command itself** requires. They give
the command read access to each Gen3 surface so it can report reachability.

| Surface | Endpoint probed | Minimum scopes |
|---------|-----------------|----------------|
| `settings_v2` | `GET /api/v2/settings/schemas` | `settings:schemas:read`, `settings:objects:read` |
| `document_api` | `GET /platform/document/v1/documents` | `document:documents:read` |
| `automation_api` | `GET /platform/automation/v1/workflows` | `automation:workflows:read` |

Provision these first, then run `python3 migrate.py preflight`. The command
exits 0 only when all three are reachable.

---

## Recommended Scopes — Full Migrate Run

For `python3 migrate.py migrate` you need the minimum scopes **plus write
access** on every surface migrate creates entities on.

| Surface | Scopes |
|---------|--------|
| `settings_v2` | `settings:schemas:read`, `settings:objects:read`, `settings:objects:write` |
| `document_api` | `document:documents:read`, `document:documents:write` |
| `automation_api` | `automation:workflows:read`, `automation:workflows:write`, `automation:workflows:run` |
| Grail (read) | `storage:logs:read`, `storage:events:read`, `storage:metrics:read`, `storage:spans:read`, `storage:entities:read`, `storage:buckets:read` |

Grail read scopes are used during transform and validation (log obfuscation
field lookups, entity enrichment, SLO burn-rate verification). They are not
probed by `preflight` because a Platform Token can reach Documents and
Automation without them, but migrate needs them end-to-end.

---

## Legacy Mode Scopes (`--legacy`)

When running `migrate --legacy`, the tool uses the Classic Config v1 APIs
instead of Gen3. Use a classic `dt0c01.*` token with these scopes:

| Capability | Scopes |
|------------|--------|
| Read classic config | `ReadConfig` |
| Write classic config (alerting profiles, metric events, management zones) | `WriteConfig` |
| Classic dashboards | `DataExport` (export), `WriteConfig` (import) |
| Classic synthetic | `ExternalSyntheticIntegration` |
| Events ingest | `events.ingest` |

Classic tokens do **not** accept the Platform scopes (`settings:*`,
`document:*`, `automation:*`, `storage:*`). If you provision those on a
classic token they will be silently dropped.

---

## How to Add Scopes in the Dynatrace UI

1. Log in to your Dynatrace tenant.
2. Open **Access Tokens** (from the Settings menu, or search for "access
   tokens").
3. Click your token — or create a new one (name it clearly, e.g.
   `nrdt-migrate-<yourname>`).
4. In the **Scopes** section, click **Add scope** and search by name.
5. Add each scope from the "Recommended Scopes — Full Migrate Run" table
   above.
6. Save the token. Export it:

   ```bash
   export DYNATRACE_API_TOKEN="dt0s16.AAAAA.BBBBB..."
   export DYNATRACE_ENVIRONMENT_URL="https://<env-id>.live.dynatrace.com"
   ```

7. Verify:

   ```bash
   python3 migrate.py preflight
   ```

Platform Tokens are revocable at any time and do not expire automatically
— treat them like any other secret.

---

## Verifying a Single Scope with `curl`

If preflight reports a 401/403 on one specific API, you can isolate the
failure with a raw HTTP call. Replace `$DT_URL` and `$DT_TOKEN` with your
values.

```bash
# settings_v2 — requires settings:schemas:read
curl -sS -H "Authorization: Api-Token $DT_TOKEN" \
  "$DT_URL/api/v2/settings/schemas?pageSize=1"

# document_api — requires document:documents:read
# (note: Document API lives on the apps. subdomain)
APPS_URL=$(echo "$DT_URL" | sed 's/\.live\./.apps./')
curl -sS -H "Authorization: Api-Token $DT_TOKEN" \
  "$APPS_URL/platform/document/v1/documents?pageSize=1"

# automation_api — requires automation:workflows:read
curl -sS -H "Authorization: Api-Token $DT_TOKEN" \
  "$APPS_URL/platform/automation/v1/workflows?pageSize=1"
```

- **200** → scope is present and the API is reachable.
- **401** → token is invalid or expired.
- **403** → token is valid but lacks the scope — add it in the UI.
- **404** → the tenant does not expose this Gen3 surface. Run `migrate` with
  `--legacy` until the tenant is upgraded.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `preflight` shows `settings_v2: no` (403) | Token missing `settings:schemas:read` or `settings:objects:read` | Add both scopes in the UI |
| `preflight` shows `document_api: no` (403) | Token missing `document:documents:read` | Add the scope |
| `preflight` shows `automation_api: no` (404) | Tenant is Classic/Managed without Gen3 | Run `migrate --legacy` until the tenant is upgraded |
| `preflight` shows all three `no` (0/network) | `DYNATRACE_ENVIRONMENT_URL` wrong or unreachable | Confirm the URL is the SaaS `.live.dynatrace.com` host and reachable from your machine |
| `migrate` fails mid-run with "403 on settings:objects:write" | Preflight scopes sufficient for read but not write | Add `settings:objects:write` to the token |
| `migrate` fails querying Grail inside a workflow | Missing `storage:*:read` scopes | Add every scope from the Grail row above |
