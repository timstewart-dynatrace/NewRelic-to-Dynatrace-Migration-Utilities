# Complete Guide: Transitioning from New Relic to Dynatrace

This guide covers the full end-to-end process for migrating your observability platform from New Relic to Dynatrace using the `nr-migrate` tool. It is organized into phases that can be executed over days or weeks depending on the size of your environment.

---

## Table of Contents

- [Phase 1: Planning & Inventory](#phase-1-planning--inventory)
- [Phase 2: Environment Setup](#phase-2-environment-setup)
- [Phase 3: Deploy Dynatrace Instrumentation](#phase-3-deploy-dynatrace-instrumentation)
- [Phase 4: Audit Your New Relic Configuration](#phase-4-audit-your-new-relic-configuration)
- [Phase 5: Compile & Validate Queries](#phase-5-compile--validate-queries)
- [Phase 6: Dry-Run Migration](#phase-6-dry-run-migration)
- [Phase 7: Execute Migration](#phase-7-execute-migration)
- [Phase 8: Validate & Tune](#phase-8-validate--tune)
- [Phase 9: Decommission New Relic](#phase-9-decommission-new-relic)
- [Appendix A: Entity Mapping Reference](#appendix-a-entity-mapping-reference)
- [Appendix B: CLI Command Reference](#appendix-b-cli-command-reference)
- [Appendix C: Troubleshooting](#appendix-c-troubleshooting)

---

## Phase 1: Planning & Inventory

Before touching any tool, document what you have and what you need.

### 1.1 Inventory your New Relic estate

Log into New Relic and count your assets across each category:

| Entity Type | Where to Find in NR | What Migrates |
|-------------|---------------------|---------------|
| Dashboards | Dashboards tab | Pages, widgets, NRQL queries, layout |
| Alert Policies | Alerts & AI > Alert Policies | Conditions, thresholds, notification channels |
| Synthetic Monitors | Synthetic Monitoring | Ping, API, browser monitors |
| SLOs | Service Levels | Objectives, metric expressions, time windows |
| Workloads | Workloads tab | Entity collections, search queries |
| Notification Channels | Alerts & AI > Destinations | Email, Slack, PagerDuty, webhook |
| Infrastructure Conditions | Alerts & AI > Conditions (Infra) | Host/process metric thresholds |
| Log Parsing Rules | Logs > Parsing | Grok/regex parsing rules |
| Drop Rules | Data Management > Drop Filters | Ingest exclusion rules |
| Tags | Entity tags | Key-value pairs on entities |

### 1.2 Identify what requires manual work

Not everything migrates automatically. Flag these for manual attention:

- **Custom instrumentation** -- New Relic APM custom attributes, custom events, and custom metrics need equivalent Dynatrace instrumentation (OneAgent extensions, OpenTelemetry, or Metric Ingestion API).
- **Scripted browser monitors** -- Complex Selenium-based scripts require rewriting for Dynatrace Synthetic. Simple navigation scripts may convert.
- **Dashboard variables** -- NR template variables have limited auto-conversion. Plan to recreate these in Dynatrace.
- **NRQL queries using NR-specific functions** -- Functions like `apdex()`, `funnel()`, or `cohort()` have no direct DQL equivalent. The compiler will flag these with `/* TODO */` markers.
- **Historical telemetry data** -- Only configuration is migrated, not data. Historical metrics, logs, and traces stay in New Relic until retention expires.

### 1.3 Set a timeline

| Milestone | Typical Duration |
|-----------|-----------------|
| Planning & inventory | 1-2 days |
| Dynatrace instrumentation deployed | 1-2 weeks |
| Dual-run period (both platforms active) | 2-4 weeks |
| Configuration migration | 1-2 days |
| Validation & tuning | 1-2 weeks |
| New Relic decommission | 1 day |

The dual-run period is critical. You need Dynatrace collecting data before migrated dashboards and alerts will return results.

---

## Phase 2: Environment Setup

### 2.1 Install the migration tool

```bash
git clone https://github.com/timstewart-dynatrace/Dynatrace-NewRelic.git
cd Dynatrace-NewRelic
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Verify
python migrate.py --version
```

### 2.2 Create API credentials

#### New Relic User API Key

1. Go to [one.newrelic.com/api-keys](https://one.newrelic.com/api-keys)
2. Click **Create a key**
3. Key type: **User**
4. The key will start with `NRAK-`
5. This key inherits the permissions of the user who creates it -- use an admin account for full export access

#### Dynatrace API Token

1. Go to **Settings > Integration > Dynatrace API** (or **Access Tokens** in newer environments)
2. Click **Generate new token**
3. Enable these scopes:

| Scope | Used For |
|-------|----------|
| `Read configuration` | Reading existing dashboards, monitors |
| `Write configuration` | Creating dashboards, metric events |
| `Read settings` | Reading alerting profiles, management zones |
| `Write settings` | Creating alerting profiles, management zones, auto-tags |
| `Create and read synthetic monitors, locations, and nodes` | Importing synthetic monitors |
| `Read SLO` | Checking existing SLOs |
| `Write SLO` | Creating SLOs |

4. The token will start with `dt0c01.`

### 2.3 Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```bash
# Required -- New Relic
NEW_RELIC_API_KEY=NRAK-XXXXXXXXXXXXXXXXXXXXXXXXXXXX
NEW_RELIC_ACCOUNT_ID=1234567
NEW_RELIC_REGION=US                    # US or EU

# Required -- Dynatrace
DYNATRACE_API_TOKEN=dt0c01.XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
DYNATRACE_ENVIRONMENT_URL=https://abc12345.live.dynatrace.com

# Optional -- Migration settings
MIGRATION_DRY_RUN=false                # Default: false
MIGRATION_OUTPUT_DIR=./output          # Default: ./output
MIGRATION_BATCH_SIZE=50                # Entities per API call batch
MIGRATION_RATE_LIMIT=5.0               # Max requests/sec to APIs
MIGRATION_CONTINUE_ON_ERROR=true       # Don't stop on individual failures
MIGRATION_BACKUP=true                  # Save rollback manifest
LOG_LEVEL=INFO                         # DEBUG for verbose output
```

### 2.4 Validate credentials

```bash
# This connects to both APIs and validates access
python migrate.py migrate --dry-run --components dashboards
```

If credentials are invalid, you will see a `Configuration error` with specifics about which key failed validation.

---

## Phase 3: Deploy Dynatrace Instrumentation

**This phase must happen before migrating dashboards and alerts.** Migrated DQL queries reference Dynatrace data objects (`spans`, `logs`, `dt.entity.host`, etc.) that only exist after instrumentation is active.

### 3.1 Install OneAgent

Deploy OneAgent on all hosts currently instrumented by New Relic APM agents:

- **Linux/Windows**: Download from **Deploy Dynatrace > Start installation**
- **Kubernetes**: Use the [Dynatrace Operator](https://docs.dynatrace.com/docs/setup-and-configuration/setup-on-k8s)
- **Cloud platforms**: AWS, Azure, GCP integrations in **Settings > Cloud and virtualization**

### 3.2 Configure data ingest

Map your New Relic data sources to Dynatrace equivalents:

| New Relic Source | Dynatrace Equivalent |
|-----------------|---------------------|
| APM agents (Java, .NET, Node, Python, etc.) | OneAgent (auto-instrumented) |
| Infrastructure agent | OneAgent (host monitoring is built-in) |
| Browser agent | Real User Monitoring (RUM) via OneAgent JS |
| Mobile agent | Mobile RUM |
| Logs-in-Context | Log Monitoring (auto-detected from OneAgent) |
| OpenTelemetry | OTLP ingest endpoint |
| Prometheus metrics | Prometheus integration or Metric Ingestion API |
| Custom events / metrics | Metric Ingestion API or Business Events API |

### 3.3 Verify data is flowing

Wait at least 15-30 minutes after deployment, then confirm in Dynatrace:

- **Hosts**: Smartscape or `fetch dt.entity.host` in Notebooks
- **Services**: `fetch dt.entity.service`
- **Traces**: `fetch spans | limit 10`
- **Logs**: `fetch logs | limit 10`
- **Metrics**: `timeseries avg(dt.host.cpu.usage)`

If data is not flowing, check the OneAgent connection status in **Deployment status**.

### 3.4 Run both platforms in parallel

Keep New Relic agents running alongside Dynatrace during the dual-run period. This lets you:
- Compare metrics between platforms
- Validate that DQL queries return similar data to NRQL originals
- Fall back to New Relic if issues arise

---

## Phase 4: Audit Your New Relic Configuration

### 4.1 Compile your NRQL queries first

Before migrating dashboards or alerts, test your NRQL queries individually to identify conversion issues early.

#### Interactive mode (explore one at a time)

```bash
python migrate.py compile --interactive
```

Type any NRQL query and see the DQL output, confidence score, and warnings.

#### Batch compile from a file

Create a file with your most critical queries (one per line, `#` for comments):

```bash
# Save your critical queries to a file
cat > critical_queries.nrql << 'EOF'
# Production dashboard queries
SELECT count(*) FROM Transaction WHERE appName = 'checkout-service' SINCE 1 hour ago
SELECT average(duration) FROM Transaction FACET appName TIMESERIES
SELECT percentile(duration, 50, 95, 99) FROM Transaction FACET name SINCE 1 day ago
SELECT percentage(count(*), WHERE error IS true) FROM Transaction FACET appName
# Alert condition queries
SELECT count(*) FROM TransactionError WHERE appName = 'api-gateway' SINCE 5 minutes ago
SELECT average(cpuPercent) FROM SystemSample FACET hostname SINCE 10 minutes ago
EOF

# Compile all at once
python migrate.py compile --file critical_queries.nrql --output compiled_results.txt
```

#### Batch compile from CSV/Excel

If your team tracks queries in a spreadsheet:

```bash
# CSV must have a column named "nrql" (or specify --nrql-column)
python migrate.py batch --file queries.csv --output results.csv
```

Output CSV includes: `nrql`, `dql`, `confidence`, `warnings`

### 4.2 Review the reference table

See all supported NRQL-to-DQL mappings:

```bash
# Quick reference of common patterns
python migrate.py reference

# Full mapping tables (230 metrics, 72 attributes, 90+ aggregations, 34 event types)
python migrate.py reference --mappings
```

### 4.3 Understand confidence scores

| Score | Meaning | Action |
|-------|---------|--------|
| HIGH | Direct 1:1 mapping, fully automated | No action needed |
| MEDIUM | Converted with assumptions or approximations | Review the DQL output |
| LOW | Partial conversion, may need manual adjustment | Manual editing required |
| FAILED | Could not convert | Rewrite manually in DQL |

Focus your manual review effort on MEDIUM and LOW confidence queries. HIGH confidence queries have been tested against 292 patterns.

---

## Phase 5: Compile & Validate Queries

### 5.1 Export from New Relic (without importing)

```bash
python migrate.py migrate --export-only
```

This calls the New Relic NerdGraph API and saves all entity configurations to `./output/exports/newrelic_export.json`. Nothing is written to Dynatrace.

Inspect the export:

```bash
# See what was exported
python -c "
import json
data = json.load(open('output/exports/newrelic_export.json'))
for key, val in data.items():
    if isinstance(val, list):
        print(f'{key}: {len(val)} entities')
"
```

### 5.2 Selective export

If you only want specific components:

```bash
# Only dashboards and alerts
python migrate.py migrate --export-only --components dashboards,alerts

# See all available components
python migrate.py migrate --list-components
```

Available components: `dashboards`, `alerts`, `synthetics`, `slos`, `workloads`, `notification_channels`, `infrastructure`, `log_parsing`, `tags`, `drop_rules`

### 5.3 Generate a conversion quality report

```bash
python migrate.py migrate --dry-run --report
```

This generates:
- `./output/reports/conversion-report.json` -- structured data
- `./output/reports/conversion-report.html` -- visual report

Open the HTML report in a browser. It shows:
- Side-by-side NRQL/DQL for every query
- Color-coded confidence badges
- Yellow highlighting for queries that need review
- Summary counts (HIGH/MEDIUM/LOW/FAILED)

**Action items from the report:**
1. Queries marked FAILED -- rewrite manually in DQL
2. Queries marked LOW -- review and adjust the generated DQL
3. Queries with `/* TODO */` markers -- replace with valid DQL
4. Queries with warnings -- check if the warning affects correctness

---

## Phase 6: Dry-Run Migration

### 6.1 Full dry-run

```bash
python migrate.py migrate --dry-run
```

This runs the complete pipeline (export, transform, validate) without writing anything to Dynatrace. Output:
- Summary table showing entity counts per type
- Preview file at `./output/preview/transformed_preview.json`
- Any warnings or errors encountered

### 6.2 Diff against live Dynatrace

If you already have some configurations in Dynatrace (manually created or from a previous migration):

```bash
python migrate.py migrate --dry-run --diff
```

The diff report shows what would happen to each entity:

| Action | Meaning | Risk |
|--------|---------|------|
| **CREATE** | Entity does not exist in DT | Safe -- will create new |
| **UPDATE** | Name match found in DT | Moderate -- will overwrite existing |
| **CONFLICT** | Multiple matches found | High -- requires manual resolution |
| **ORPHAN** | Exists in DT but not in NR export | None -- left untouched |

**Review UPDATE and CONFLICT items carefully before proceeding.**

### 6.3 Review the transformed output

```bash
# Pretty-print the transformed configuration
python -c "
import json
data = json.load(open('output/transformed/dynatrace_config.json'))
for key, val in data.items():
    if isinstance(val, list) and val:
        print(f'\n=== {key} ({len(val)} items) ===')
        print(json.dumps(val[0], indent=2)[:500])
        print('...')
"
```

Look for:
- Dashboard names are correct
- Alert thresholds match the originals
- Synthetic monitor URLs are correct
- SLO targets match the originals

---

## Phase 7: Execute Migration

### 7.1 Start with a single component

Don't migrate everything at once. Start with the lowest-risk component:

```bash
# Dashboards are read-only and low-risk
python migrate.py migrate --full --components dashboards
```

Verify in Dynatrace that the dashboards appear and display data correctly.

### 7.2 Migrate remaining components incrementally

```bash
# Alerts (requires notification_channels first if you have channels)
python migrate.py migrate --full --components notification_channels
python migrate.py migrate --full --components alerts

# Synthetic monitors
python migrate.py migrate --full --components synthetics

# SLOs
python migrate.py migrate --full --components slos

# Workloads -> Management Zones
python migrate.py migrate --full --components workloads

# Infrastructure conditions, log parsing, tags, drop rules
python migrate.py migrate --full --components infrastructure,log_parsing,tags,drop_rules
```

### 7.3 Or migrate everything at once

If you've validated thoroughly with dry-run and diff:

```bash
python migrate.py migrate --full
```

### 7.4 Handle failures

After migration, check for failed entities:

```bash
# Failed entities are saved automatically
cat output/failed-entities.json
```

Retry only the failures:

```bash
python migrate.py migrate --retry output/failed-entities.json
```

### 7.5 Resume after interruption

If the migration was interrupted (network timeout, rate limiting):

```bash
python migrate.py migrate --full --resume
```

This picks up from the last checkpoint, skipping entities that were already imported.

### 7.6 Rollback if needed

Every `--full` migration creates a rollback manifest. If something went wrong:

```bash
python migrate.py migrate --rollback output/rollback-manifest.json
```

This deletes all entities that were created during the migration. You will be prompted for confirmation.

---

## Phase 8: Validate & Tune

### 8.1 Validate dashboards

For each migrated dashboard in Dynatrace:

1. Open the dashboard
2. Verify all tiles display data (not "No data")
3. Compare values against the same dashboard in New Relic
4. Check time range behavior

**Common issues:**
- "No data" on a tile -- the DQL query references a data object that hasn't received data yet, or the field mapping is incorrect
- Layout differences -- Dynatrace uses pixel-based layout vs NR's 12-column grid. Some manual adjustment may be needed
- Missing variables -- dashboard variables need manual recreation

### 8.2 Validate alerts

1. Go to **Settings > Anomaly Detection > Metric events** to see migrated metric events
2. Check each condition's DQL query in the Dynatrace query editor
3. Verify thresholds match the original NR conditions
4. Confirm alerting profiles are connected to the right notification channels

**Test an alert:**
- Temporarily lower a threshold to trigger an alert
- Verify the notification reaches the correct destination
- Reset the threshold

### 8.3 Validate synthetic monitors

1. Go to **Synthetic** in Dynatrace
2. Check each monitor is executing (green status)
3. Verify URLs, frequency, and locations are correct
4. For scripted monitors, run a manual execution and check results

### 8.4 Audit SLOs

```bash
python migrate.py audit-slos
```

This checks each SLO in Dynatrace against the environment:
- Are the referenced metrics available?
- Are aggregation functions valid?
- Are time windows correct?

### 8.5 Incremental updates

If you make changes in New Relic during the transition period, re-sync:

```bash
# Only processes entities that changed since last run
python migrate.py migrate --full --incremental
```

---

## Phase 9: Decommission New Relic

Only proceed when all of these are true:

- [ ] All dashboards display correct data in Dynatrace
- [ ] All alerts are firing correctly and reaching the right teams
- [ ] All synthetic monitors are running and passing
- [ ] All SLOs are tracking correctly
- [ ] Teams have been using Dynatrace for at least 2 weeks without falling back to New Relic
- [ ] No critical queries returned FAILED or LOW confidence without manual fixes
- [ ] Stakeholders have signed off on the migration

### 9.1 Remove New Relic agents

- Uninstall New Relic APM agents from application servers
- Remove New Relic Infrastructure agents from hosts
- Remove New Relic browser agent snippets from frontend code
- Remove New Relic mobile SDK from mobile apps

### 9.2 Clean up New Relic

- Disable or mute all alert policies (don't delete yet -- keep as reference)
- Disable synthetic monitors
- Revoke API keys created for the migration

### 9.3 Archive migration artifacts

```bash
# Keep the migration output for reference
tar czf migration-archive-$(date +%Y%m%d).tar.gz output/
```

Save the following files:
- `output/exports/newrelic_export.json` -- original NR configuration
- `output/reports/conversion-report.html` -- conversion quality report
- `output/rollback-manifest.json` -- entity ID mapping (NR -> DT)

### 9.4 Cancel New Relic subscription

After the retention period on your NR data expires and you're confident in Dynatrace, cancel your New Relic subscription.

---

## Alternative: Config-as-Code Export

Instead of importing directly to Dynatrace via API, you can export to configuration-as-code formats for review, version control, and repeatable deployment.

### Monaco (Dynatrace native)

```bash
# Step 1: Export from NR and transform
python migrate.py migrate --export-only

# Step 2: Generate Monaco project
python migrate.py export-monaco --input ./output --output ./monaco-project

# Step 3: Review the generated configs
ls monaco-project/
# dashboards/  alerting_profiles/  metric_events/  management_zones/
# synthetic_monitors/  slos/  project.yaml

# Step 4: Commit to version control
cd monaco-project
git init && git add . && git commit -m "feat: initial NR migration configs"

# Step 5: Deploy to Dynatrace
monaco deploy -e prod
```

### Terraform

```bash
# Step 1: Export from NR and transform
python migrate.py migrate --export-only

# Step 2: Generate Terraform configs
python migrate.py export-terraform --input ./output --output ./terraform-project

# Step 3: Review the generated HCL
ls terraform-project/
# provider.tf  dashboards.tf  alerts.tf  slos.tf  synthetics.tf
# management_zones.tf  terraform.tfvars

# Step 4: Initialize and plan
cd terraform-project
terraform init
terraform plan       # Review what will be created

# Step 5: Apply
terraform apply

# Rollback if needed
terraform destroy
```

**When to use config-as-code instead of direct import:**
- You have a GitOps workflow for infrastructure
- Multiple environments (dev, staging, prod) need the same configs
- You want code review before deployment
- You need repeatable, version-controlled deployments

---

## Appendix A: Entity Mapping Reference

### Entity Type Mapping

| New Relic | Dynatrace | API Used | Notes |
|-----------|-----------|----------|-------|
| Dashboard (multi-page) | Dashboard (one per page) | Documents API v2 | Multi-page dashboards become multiple DT dashboards |
| Alert Policy | Alerting Profile | Settings API v2 | 1:1 mapping |
| NRQL Condition | Metric Event | Settings API v2 | Query converted to DQL |
| Notification Channel | Problem Notification | Settings API v2 | Type-specific schemas |
| Ping Monitor | HTTP Monitor | Synthetic API | Direct mapping |
| API Monitor | HTTP Monitor | Synthetic API | Multi-step handling |
| Browser Monitor | Browser Monitor | Synthetic API | Script adaptation needed |
| SLO | SLO | SLO API v2 | Metric expression conversion |
| Workload | Management Zone | Settings API v2 | Selector rule conversion |
| Infra Condition | Metric Event | Settings API v2 | Host/process thresholds |
| Log Parsing Rule | Processing Rule | Settings API v2 | Grok to DPL conversion |
| Entity Tags | Auto-Tag Rules | Settings API v2 | Key-value pair mapping |
| Drop Rules | Ingest Rules | Settings API v2 | Filter expression conversion |

### NRQL-to-DQL Quick Reference

| NRQL Pattern | DQL Equivalent |
|-------------|----------------|
| `SELECT count(*) FROM Transaction` | `fetch spans \| summarize count()` |
| `SELECT average(duration) FROM Transaction` | `fetch spans \| summarize avg(duration)` |
| `FACET appName` | `by:{appName}` |
| `TIMESERIES` | `\| makeTimeseries` |
| `SINCE 1 hour ago` | `from:now()-1h` (on fetch) |
| `WHERE error IS true` | `\| filter error == true` |
| `LIMIT 100` | `\| limit 100` |
| `AS 'Label'` | `, alias:Label` |

### Event Type Mapping (34 types)

| New Relic Event Type | Dynatrace Data Object |
|---------------------|----------------------|
| `Transaction` | `spans` |
| `TransactionError` | `spans` (filtered on error) |
| `SystemSample` | `dt.entity.host` metrics |
| `ProcessSample` | `dt.entity.process_group` metrics |
| `NetworkSample` | `dt.entity.host` network metrics |
| `Log` | `logs` |
| `PageView` | `rum` |
| `BrowserInteraction` | `rum` |
| `SyntheticCheck` | `dt.entity.synthetic_monitor` |
| `Metric` | `timeseries` |

For the complete mapping tables (230 metrics, 72 attributes, 90+ aggregations):

```bash
python migrate.py reference --mappings
```

---

## Appendix B: CLI Command Reference

### Migration Commands

```bash
# Full migration pipeline
python migrate.py migrate --full [--components X,Y] [--output DIR]

# Export only (NR -> local files)
python migrate.py migrate --export-only [--components X,Y]

# Import only (local files -> DT)
python migrate.py migrate --import-only --input DIR

# Preview without changes
python migrate.py migrate --dry-run

# Compare against live DT
python migrate.py migrate --dry-run --diff

# Generate quality report
python migrate.py migrate --dry-run --report

# Incremental (skip unchanged)
python migrate.py migrate --full --incremental

# Resume interrupted run
python migrate.py migrate --full --resume

# Retry failures
python migrate.py migrate --retry output/failed-entities.json

# Rollback
python migrate.py migrate --rollback output/rollback-manifest.json

# List available components
python migrate.py migrate --list-components
```

### Compiler Commands

```bash
# Single query
python migrate.py compile "SELECT count(*) FROM Transaction"

# Interactive REPL
python migrate.py compile --interactive

# Batch from file
python migrate.py compile --file queries.nrql [--output results.txt]

# CSV/Excel batch
python migrate.py batch --file queries.csv --output results.csv [--nrql-column name]

# Reference table
python migrate.py reference [--mappings]
```

### Other Commands

```bash
# SLO audit
python migrate.py audit-slos

# Config-as-code export
python migrate.py export-monaco --input ./output --output ./monaco-out
python migrate.py export-terraform --input ./output --output ./tf-out

# Version
python migrate.py --version
```

---

## Appendix C: Troubleshooting

### Setup Issues

| Problem | Cause | Solution |
|---------|-------|----------|
| `Configuration error: Invalid NR API key` | Key doesn't start with `NRAK-` | Regenerate at one.newrelic.com/api-keys |
| `Configuration error: Invalid DT token` | Token doesn't start with `dt0c01.` | Regenerate in Dynatrace Settings |
| `Configuration error: Invalid environment URL` | URL format wrong | Must be `https://<id>.live.dynatrace.com` |
| `ModuleNotFoundError` | Virtual env not activated | `source .venv/bin/activate` |

### Export Issues

| Problem | Cause | Solution |
|---------|-------|----------|
| `Failed to export dashboards` | Insufficient NR permissions | Use admin user API key |
| Empty export (0 entities) | Wrong account ID | Verify `NEW_RELIC_ACCOUNT_ID` in `.env` |
| Timeout during export | Large account, rate limiting | Reduce `MIGRATION_RATE_LIMIT` to 2.0 |

### Compilation Issues

| Problem | Cause | Solution |
|---------|-------|----------|
| `/* TODO */` in DQL output | Unsupported NRQL function | Rewrite manually using DQL reference |
| LOW confidence score | Approximate mapping used | Review and adjust the generated DQL |
| FAILED confidence | Could not parse NRQL | Check for syntax errors in the original query |

### Import Issues

| Problem | Cause | Solution |
|---------|-------|----------|
| `403 Forbidden` | Missing DT token scopes | Add required scopes (see Phase 2.2) |
| `429 Too Many Requests` | Rate limit exceeded | Reduce `MIGRATION_RATE_LIMIT` in `.env` |
| Dashboard shows "No data" | DT not receiving data yet | Wait for OneAgent to collect data (Phase 3) |
| Partial import failure | Some entities failed | Use `--retry output/failed-entities.json` |
| Need to undo everything | Migration went wrong | Use `--rollback output/rollback-manifest.json` |

### Validation Issues

| Problem | Cause | Solution |
|---------|-------|----------|
| SLO audit reports missing metrics | Metric not ingested | Verify OneAgent is monitoring the service |
| Alert not firing | Threshold too high / query wrong | Test in DT query editor, lower threshold |
| Synthetic monitor failing | URL not accessible from DT locations | Check monitor locations and firewall rules |
