# NewRelic to Dynatrace Migration: GitHub & Community Solutions

## Overview

This document catalogs available GitHub repositories, tools, and community-submitted solutions for exporting configuration and entities from New Relic for migration to Dynatrace. **Note:** As of January 2026, there is no direct, automated "NewRelic-to-Dynatrace" migration tool. Migration requires a combination of export tools from New Relic and import tools for Dynatrace.

---

## 1. New Relic Export Tools

### 1.1 Official New Relic Account Migration Tool
- **Repository:** [newrelic-experimental/nr-account-migration](https://github.com/newrelic-experimental/nr-account-migration)
- **Description:** Python scripts for bulk migration of New Relic configurations between New Relic accounts
- **Capabilities:**
  - Synthetic monitors
  - Alert policies and conditions (NRQL, APM, Browser, Synthetic, Infrastructure, Multi-location)
  - Notification destinations, channels, and workflows (email, webhook, PagerDuty, OpsGenie)
  - Dashboards
  - APM app configurations (apdex_threshold, end_user_apdex_threshold, enable_real_user_monitoring)
  - Entity tags (for APM apps, Browser apps, Synthetic monitors, Mobile apps, Workloads)
- **Use for Dynatrace:** Export configurations to JSON format, then manually translate/import to Dynatrace

### 1.2 New Relic Dashboard Export Utility
- **Repository:** [jsbnr/nr-dashboard-export-utility](https://github.com/jsbnr/nr-dashboard-export-utility)
- **Description:** Node.js script for exporting New Relic dashboards to PDF/PNG or Slack
- **Use for Dynatrace:** Export dashboard snapshots for reference when recreating in Dynatrace

### 1.3 NerdGraph API (GraphQL)
- **Documentation:** [New Relic NerdGraph API](https://docs.newrelic.com/docs/apis/nerdgraph/get-started/introduction-new-relic-nerdgraph/)
- **Capabilities:**
  - Export dashboards as JSON
  - Export alert policies and conditions
  - Export synthetic monitors
  - Export entity configurations
  - Historical data export
- **Key Queries:**
  ```graphql
  # List all dashboards
  { actor { entitySearch(queryBuilder: {type: DASHBOARD}) { 
    results { entities { ... on DashboardEntityOutline { guid name accountId } } } } } }
  
  # Export specific dashboard
  { actor { entity(guid: "YOUR_DASHBOARD_GUID") { 
    ... on DashboardEntity { name permissions pages { name widgets { ... } } } } } }
  ```

### 1.4 New Relic Synthetics REST API
- **Documentation:** [Synthetics REST API](https://docs.newrelic.com/docs/apis/synthetics-rest-api/monitor-examples/manage-synthetics-monitors-rest-api/)
- **Capabilities:**
  - List all monitors: `GET $API_ENDPOINT/v3/monitors`
  - Export monitor scripts: `GET $API_ENDPOINT/v3/monitors/$MONITOR_ID/script`
  - Export monitor configurations as JSON

### 1.5 New Relic Terraform Provider
- **Registry:** [newrelic/newrelic Terraform Provider](https://registry.terraform.io/providers/newrelic/newrelic/latest)
- **Use for Migration:**
  - Export existing resources using `terraform import`
  - Generate Terraform state from existing New Relic configuration
  - Use as intermediate format for migration

---

## 2. Dynatrace Import Tools

### 2.1 Dynatrace Configuration as Code (Monaco)
- **Repository:** [Dynatrace/dynatrace-configuration-as-code](https://github.com/Dynatrace/dynatrace-configuration-as-code)
- **Documentation:** [Monaco Documentation](https://docs.dynatrace.com/docs/deliver/configuration-as-code/monaco)
- **Description:** Official Dynatrace CLI for managing configuration as code
- **Capabilities:**
  - Deploy configurations from YAML/JSON files
  - Supports: Alerting profiles, Dashboards, Management zones, Auto-tags, SLOs, Synthetic monitors, Request attributes, Calculated metrics, and more
  - Download existing configurations: `monaco download`
  - Deploy configurations: `monaco deploy`
- **Use for Migration:** Create Monaco-compatible YAML/JSON files from exported New Relic configurations

### 2.2 Dynatrace Terraform Provider
- **Repository:** [dynatrace-oss/terraform-provider-dynatrace](https://github.com/dynatrace-oss/terraform-provider-dynatrace)
- **Registry:** [Terraform Registry](https://registry.terraform.io/providers/dynatrace-oss/dynatrace/latest)
- **Description:** Official Dynatrace Terraform provider with export utility
- **Key Features:**
  - Export utility: `./terraform-provider-dynatrace -export`
  - Import configurations: `terraform apply`
  - Supports all major Dynatrace configuration types
- **Export Examples:**
  ```bash
  # Export all configurations
  ./terraform-provider-dynatrace -export
  
  # Export specific resource type
  ./terraform-provider-dynatrace -export dynatrace_alerting
  
  # Export with dependencies
  ./terraform-provider-dynatrace -export -ref dynatrace_dashboard
  ```

### 2.3 Dynatrace Configuration Exporter (Community)
- **Repository:** [juliusloman/dynatrace-configuration-exporter](https://github.com/juliusloman/dynatrace-configuration-exporter)
- **Description:** Shell script to dump and synchronize Dynatrace configurations
- **Use:** Export/import configurations between Dynatrace environments

---

## 3. OpenTelemetry-Based Migration Path

### 3.1 OpenTelemetry as Migration Bridge
- **Concept:** Use OpenTelemetry as an intermediate layer for telemetry data migration
- **Benefits:**
  - Vendor-neutral instrumentation
  - Same data format accepted by both platforms
  - Can send data to multiple backends during transition period

### 3.2 Dynatrace OTLP Endpoints
- **Documentation:** [Dynatrace OpenTelemetry](https://docs.dynatrace.com/docs/ingest-from/opentelemetry)
- **Endpoints:**
  - Traces: `https://{env-id}.live.dynatrace.com/api/v2/otlp/v1/traces`
  - Metrics: `https://{env-id}.live.dynatrace.com/api/v2/otlp/v1/metrics`
  - Logs: `https://{env-id}.live.dynatrace.com/api/v2/otlp/v1/logs`

### 3.3 Dynatrace OpenTelemetry Collector
- **Repository:** [Dynatrace/dynatrace-otel-collector](https://github.com/dynatrace-oss/dynatrace-otel-collector)
- **Description:** Customized OpenTelemetry Collector build for Dynatrace

---

## 4. Query Language Migration

### 4.1 NRQL to DQL Conversion
- **No automated converter exists** - Manual translation required
- **Key Differences:**

| NRQL (New Relic) | DQL (Dynatrace) |
|------------------|-----------------|
| `SELECT ... FROM ...` | `fetch <datatype>` |
| `WHERE field = 'value'` | `| filter field == "value"` |
| `FACET fieldname` | `| summarize by: {fieldname}` |
| `SINCE 1 hour ago` | `from: now()-1h` |
| `TIMESERIES` | `| timeseries` |

- **Community Discussion:** [Dynatrace Community - NRQL to DQL](https://community.dynatrace.com/t5/DQL/Using-Regex-on-Custom-Metric-entity-object-metric-series-Via-DQL/m-p/265355)

---

## 5. Community Discussions & Resources

### 5.1 Dynatrace Community Threads
- **Synthetic Monitor Migration:** [Move Synthetic Monitoring from NewRelic to Dynatrace](https://community.dynatrace.com/t5/Synthetic-Monitoring/Move-Synthetic-Monitoring-as-1-bigbang-from-NewRelic-to/td-p/242649)
  - **Conclusion:** No automated solution exists; manual recreation required
  
- **Data Ingestion from New Relic:** [Ingest monitoring data from New Relic into Dynatrace](https://community.dynatrace.com/t5/Open-Q-A/Is-it-possible-to-ingest-monitoring-data-from-New-Relic-into/m-p/221473)
  - **Conclusion:** No direct integration; use OpenTelemetry or custom integrations

### 5.2 Comparison Resources
- [SigNoz: Dynatrace vs New Relic Comparison](https://signoz.io/comparisons/dynatrace-vs-newrelic/)

---

## 6. Recommended Migration Workflow

### Step 1: Export from New Relic
1. Use **NerdGraph API** to export dashboards, alerts, and entity configurations as JSON
2. Use **Synthetics REST API** to export synthetic monitor scripts
3. Use **nr-account-migration** tool to bulk export configurations
4. Document NRQL queries for later manual conversion

### Step 2: Transform Configurations
1. Map New Relic concepts to Dynatrace equivalents:
   - NR Alert Policies → DT Alerting Profiles
   - NR Dashboards → DT Dashboards
   - NR Synthetic Monitors → DT Synthetic Monitors (HTTP, Browser, API)
   - NR APM → DT OneAgent/OpenTelemetry
2. Convert NRQL queries to DQL manually
3. Create Monaco YAML files or Terraform HCL from exported JSON

### Step 3: Import to Dynatrace
1. Use **Monaco CLI** for configuration deployment
2. Use **Dynatrace Terraform Provider** for infrastructure-as-code approach
3. Use **Dynatrace APIs** for programmatic configuration

### Step 4: Parallel Running (Recommended)
1. Run both platforms simultaneously during transition
2. Use OpenTelemetry to send telemetry to both platforms
3. Validate data consistency before full cutover

---

## 7. Limitations & Gaps

| Feature | Migration Support |
|---------|-------------------|
| Dashboards | Manual recreation required (no JSON compatibility) |
| Alert Conditions | Manual translation (different condition types) |
| Synthetic Monitors | Manual script adaptation (different scripting APIs) |
| NRQL → DQL | Manual query translation required |
| Historical Data | Not transferable between platforms |
| Entity Relationships | Auto-discovered by Dynatrace OneAgent |

---

## 8. Additional Resources

### GitHub Organizations
- [New Relic Experimental](https://github.com/newrelic-experimental) - Official experimental tools
- [Dynatrace OSS](https://github.com/dynatrace-oss) - Open source Dynatrace tools
- [Dynatrace Official](https://github.com/dynatrace) - Official Dynatrace repositories

### Documentation
- [New Relic API Documentation](https://docs.newrelic.com/docs/apis/)
- [Dynatrace API Documentation](https://docs.dynatrace.com/docs/dynatrace-api)
- [Dynatrace Monaco Documentation](https://docs.dynatrace.com/docs/deliver/configuration-as-code/monaco)
- [Dynatrace Terraform Documentation](https://docs.dynatrace.com/docs/deliver/configuration-as-code/terraform)

---

*Document compiled: January 2026*
*Note: Tool availability and features may change. Always verify with the latest repository documentation.*
