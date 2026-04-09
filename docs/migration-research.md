# Migration Research: Community Tools & Resources

> Research compiled January 2026. Tool availability and features may change.
> Some limitations listed below have since been addressed by this project.

## New Relic Export Tools

| Tool | Type | What It Exports |
|------|------|-----------------|
| [nr-account-migration](https://github.com/newrelic-experimental/nr-account-migration) | Official (experimental) | Synthetics, alerts, notifications, dashboards, APM config, tags |
| [nr-dashboard-export-utility](https://github.com/jsbnr/nr-dashboard-export-utility) | Community | Dashboard snapshots (PDF/PNG) |
| [NerdGraph API](https://docs.newrelic.com/docs/apis/nerdgraph/) | Official API | Dashboards, alerts, synthetics, entities, historical data |
| [Synthetics REST API](https://docs.newrelic.com/docs/apis/synthetics-rest-api/) | Official API | Monitor configs, scripts |
| [New Relic Terraform Provider](https://registry.terraform.io/providers/newrelic/newrelic/latest) | Official | All resources via `terraform import` |

### NerdGraph Query Examples

```graphql
# List all dashboards
{
  actor {
    entitySearch(queryBuilder: {type: DASHBOARD}) {
      results {
        entities {
          ... on DashboardEntityOutline { guid name accountId }
        }
      }
    }
  }
}

# Export specific dashboard
{
  actor {
    entity(guid: "YOUR_DASHBOARD_GUID") {
      ... on DashboardEntity {
        name permissions
        pages { name widgets { ... } }
      }
    }
  }
}
```

## Dynatrace Import Tools

| Tool | Type | What It Imports |
|------|------|-----------------|
| [Monaco CLI](https://github.com/Dynatrace/dynatrace-configuration-as-code) | Official | Alerting profiles, dashboards, management zones, auto-tags, SLOs, synthetics, and more |
| [Terraform Provider](https://github.com/dynatrace-oss/terraform-provider-dynatrace) | Official | All major config types with export utility |
| [Configuration Exporter](https://github.com/juliusloman/dynatrace-configuration-exporter) | Community | Shell script for config sync between DT environments |

## OpenTelemetry Migration Path

Use OpenTelemetry as a vendor-neutral bridge during transition:

| Endpoint | URL |
|----------|-----|
| Traces | `https://{env-id}.live.dynatrace.com/api/v2/otlp/v1/traces` |
| Metrics | `https://{env-id}.live.dynatrace.com/api/v2/otlp/v1/metrics` |
| Logs | `https://{env-id}.live.dynatrace.com/api/v2/otlp/v1/logs` |

See also: [Dynatrace OpenTelemetry Collector](https://github.com/dynatrace-oss/dynatrace-otel-collector)

## NRQL to DQL Reference

| NRQL | DQL |
|------|-----|
| `SELECT ... FROM ...` | `fetch <datatype>` |
| `WHERE field = 'value'` | `\| filter field == "value"` |
| `FACET fieldname` | `\| summarize by: {fieldname}` |
| `SINCE 1 hour ago` | `from: now()-1h` |
| `TIMESERIES` | `\| makeTimeseries` |

> This project's AST compiler now handles 292 tested NRQL patterns automatically.
> Run `python migrate.py reference` for the full mapping table.

## Recommended Migration Workflow

1. **Export** — Use NerdGraph API (or this tool's `migrate --export-only`)
2. **Transform** — Map NR entities to DT equivalents (or this tool's `migrate --dry-run`)
3. **Import** — Use Monaco CLI, Terraform, or this tool's `migrate --full`
4. **Parallel run** — Send telemetry to both platforms via OpenTelemetry during transition

## Entity Mapping

| New Relic | Dynatrace Equivalent |
|-----------|---------------------|
| Alert Policy | Alerting Profile |
| Dashboard | Dashboard |
| Synthetic Monitor | HTTP/Browser Monitor |
| APM | OneAgent / OpenTelemetry |
| NRQL Query | DQL Query |
| Workload | Management Zone |
| SLO | SLO |

## Resources

- [New Relic API Docs](https://docs.newrelic.com/docs/apis/)
- [Dynatrace API Docs](https://docs.dynatrace.com/docs/dynatrace-api)
- [Monaco Docs](https://docs.dynatrace.com/docs/deliver/configuration-as-code/monaco)
- [Dynatrace Terraform Docs](https://docs.dynatrace.com/docs/deliver/configuration-as-code/terraform)
- [New Relic Experimental (GitHub)](https://github.com/newrelic-experimental)
- [Dynatrace OSS (GitHub)](https://github.com/dynatrace-oss)
