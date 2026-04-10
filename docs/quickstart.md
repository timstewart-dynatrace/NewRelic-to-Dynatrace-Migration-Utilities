# Quickstart: New Relic to Dynatrace Migration

This guide walks through a complete migration using the sample data included in this repository. No New Relic account is required.

## Prerequisites

- Python 3.9+
- A Dynatrace environment (for the import step; optional for compile/transform)

## 1. Install

```bash
git clone https://github.com/timstewart-dynatrace/Dynatrace-NewRelic.git
cd Dynatrace-NewRelic
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Try the NRQL Compiler

The fastest way to see the tool in action is compiling individual NRQL queries to DQL.

```bash
# Single query
python migrate.py compile "SELECT count(*) FROM Transaction SINCE 1 hour ago"

# Output:
# fetch spans
# | summarize count()
```

More complex examples:

```bash
# Percentiles with FACET
python migrate.py compile "SELECT percentile(duration, 50, 90, 95, 99) FROM Transaction FACET appName TIMESERIES"

# Error rate percentage
python migrate.py compile "SELECT percentage(count(*), WHERE error IS true) FROM Transaction SINCE 1 hour ago"

# Infrastructure metrics
python migrate.py compile "SELECT average(cpuPercent) FROM SystemSample FACET hostname TIMESERIES"
```

### Interactive Mode

For exploring conversions interactively:

```bash
python migrate.py compile --interactive
```

Type NRQL queries and see DQL output in real time. Type `quit` to exit.

### Batch Compile from File

Compile all queries from the included example file:

```bash
python migrate.py compile --file examples/example_queries.nrql
```

Or save results to a file:

```bash
python migrate.py compile --file examples/example_queries.nrql --output results.txt
```

### NRQL-to-DQL Reference Table

View a quick-reference mapping of common NRQL patterns to DQL:

```bash
python migrate.py reference

# Full mapping tables (metrics, attributes, aggregations)
python migrate.py reference --mappings
```

## 3. Sample Data

The repository includes a sample New Relic export at `examples/sample_nr_export.json` containing:
- 2 dashboards (Production Overview with 7 widgets, API Health with 3 widgets)
- 1 alert policy with 2 conditions (error rate, response time)
- 3 synthetic monitors (ping, API, browser)
- 2 SLOs (API availability, checkout latency)
- 1 workload (E-Commerce Platform with 5 entities)

This file shows the exact data shape the tool expects from the New Relic NerdGraph API. You can use it to:
- Understand what fields each entity type contains
- Test the NRQL compiler against realistic queries extracted from dashboards
- Build your own export scripts if you need custom NR data extraction

### Try the Dashboard Queries

Extract and compile all NRQL queries from the sample dashboards:

```bash
# Pull queries from the sample export and compile them
python -c "
import json
from compiler.compiler import NRQLCompiler
c = NRQLCompiler()
data = json.load(open('examples/sample_nr_export.json'))
for dash in data['dashboards']:
    for page in dash['pages']:
        for widget in page['widgets']:
            for q in widget.get('rawConfiguration', {}).get('nrqlQueries', []):
                r = c.compile(q['query'])
                print(f'NRQL: {q[\"query\"][:80]}')
                print(f'DQL:  {r.dql.splitlines()[-1] if r.success else \"FAILED\"}')
                print(f'Confidence: {r.confidence}')
                print()
"
```

## 4. Full Migration (requires credentials)

For a real migration, you need API credentials from both platforms.

### Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```
NEW_RELIC_API_KEY=NRAK-xxxxxxxxxxxxxxxxxxxx
NEW_RELIC_ACCOUNT_ID=1234567
DYNATRACE_API_TOKEN=dt0c01.xxxxxxxx.xxxxxxxx
DYNATRACE_ENVIRONMENT_URL=https://xxxxx.live.dynatrace.com
```

**New Relic API Key**: Generate at [one.newrelic.com/api-keys](https://one.newrelic.com/api-keys) (User key type).

**Dynatrace API Token**: Create at `Settings > Integration > Dynatrace API` with these scopes:
- `Read configuration` / `Write configuration`
- `Read settings` / `Write settings`
- `Create and read synthetic monitors`
- `Read SLO` / `Write SLO`

### Preview What Would Be Migrated

```bash
python migrate.py migrate --dry-run
```

This exports from New Relic, transforms everything, and shows a summary — but does not create anything in Dynatrace.

### Compare Against Live Dynatrace

```bash
python migrate.py migrate --dry-run --diff
```

Shows which entities would be created (new), updated (name match exists), or conflict.

### Execute the Migration

```bash
python migrate.py migrate --full
```

This runs the complete pipeline: Export from NR, Transform, Import to DT.

### Selective Migration

Migrate only specific components:

```bash
# Only dashboards
python migrate.py migrate --full --components dashboards

# Dashboards and alerts
python migrate.py migrate --full --components dashboards,alerts

# List all available components
python migrate.py migrate --list-components
```

## 5. Incremental and Resumable Migrations

### Incremental Mode

After the first migration, subsequent runs can skip unchanged entities:

```bash
# First run — processes everything
python migrate.py migrate --full --incremental

# Second run — skips unchanged entities, only processes modified ones
python migrate.py migrate --full --incremental
```

The tool uses SHA-256 content hashing to detect changes. State is saved to `.migration-state.json` in the output directory.

### Resume After Failure

If a migration fails partway through (network error, API rate limit), resume where it left off:

```bash
# This picks up from the last successful entity
python migrate.py migrate --full --resume
```

### Retry Failed Entities

Failed entities are saved automatically. Retry them:

```bash
python migrate.py migrate --retry output/failed-entities.json
```

## 6. Config-as-Code Export

Instead of importing directly to Dynatrace, export as configuration files for review:

### Monaco (Dynatrace native config-as-code)

```bash
python migrate.py export-monaco --input ./output --output ./monaco-project
```

Review the generated YAML configs, then apply with Monaco:

```bash
monaco deploy monaco-project
```

### Terraform

```bash
python migrate.py export-terraform --input ./output --output ./terraform-project
```

Review the generated HCL files, then apply:

```bash
cd terraform-project
terraform init
terraform plan
terraform apply
```

## 7. SLO Audit

Validate that your SLOs reference valid Dynatrace metrics:

```bash
python migrate.py audit-slos
```

This checks each SLO's metric expression against the Dynatrace environment and reports any issues.

## Common Patterns

### CSV/Excel Batch Processing

Compile queries from a CSV file (expects a `query` or `nrql` column):

```bash
python migrate.py batch --file queries.csv --output results.csv
```

### Migration with Full Reporting

Generate an HTML report after migration:

```bash
python migrate.py migrate --full --report
```

The report includes side-by-side NRQL/DQL comparisons with confidence scores.

## Troubleshooting

| Issue | Solution |
|-------|---------|
| `Configuration error` | Check `.env` file exists with valid credentials |
| `Failed to connect to Dynatrace` | Verify `DYNATRACE_ENVIRONMENT_URL` and API token scopes |
| NRQL query produces `/* TODO */` | Unsupported NRQL pattern; check warnings for details |
| Dashboard widgets missing | Some NR visualization types don't have DT equivalents; check warnings |
| Low confidence score | Review the DQL output; some mappings are approximate |

## Next Steps

- Review the [NRQL-to-DQL reference table](../README.md) for mapping details
- Check `CHANGELOG.md` for supported patterns and known limitations
- Use `--diff` to compare against your live DT environment before importing
- Start with `--dry-run` on production data before running `--full`
