# Phase 13 — Exporters: Monaco + Terraform Emit Gen3
Status: PENDING

## Goal
`exporters/monaco.py` and `exporters/terraform.py` emit Gen3 resources by default. Gen2 emission preserved under `exporters/legacy/` for Phase 14's `--legacy` flag.

## Terraform Resource Map (Gen3 default)
| Entity | Terraform resource |
|---|---|
| Dashboard | `dynatrace_document` (type=dashboard) |
| Workflow | `dynatrace_automation_workflow` |
| Segment | `dynatrace_segment` |
| Anomaly detector | `dynatrace_davis_anomaly_detectors` (or `dynatrace_generic_setting` w/ `builtin:davis.anomaly-detectors`) |
| OpenPipeline | `dynatrace_generic_setting` w/ `builtin:openpipeline.*` schemas |
| Synthetic | `dynatrace_http_monitor` / `dynatrace_browser_monitor` |
| SLO | `dynatrace_slo_v2` |

## Monaco Resource Map (Gen3 default)
- Emit Settings 2.0 YAML (schema-based) under `projects/<name>/settings/<schema-id>/`
- Emit Document API YAML for dashboards
- Emit Workflow YAML for Automation API
- Drop classic `config/v1` YAML shapes from default output

## Tasks
- [ ] Update `exporters/terraform.py` to emit the resource map above
- [ ] Update `exporters/monaco.py` to emit Settings 2.0 + Document + Automation YAML
- [ ] Copy current (Gen2) exporter logic into `exporters/legacy/` as `monaco_v1.py` / `terraform_v1.py`
- [ ] Add fixture-based tests: emit a sample alert → verify Gen3 HCL + Gen3 YAML output shape
- [ ] Verify generated Terraform parses with `terraform validate` against `dynatrace-oss/dynatrace` provider
- [ ] Verify generated Monaco parses with `monaco deploy --dry-run` against a test manifest

## Acceptance Criteria
- Default export command produces zero Gen2 resource references
- Legacy exporters reachable only via Phase 14 flag
- All 8 Monaco + 7 Terraform exporter tests updated for Gen3 assertions; legacy tests relocated
- `terraform validate` and `monaco deploy --dry-run` both succeed on generated output

## Decisions Made This Phase
(append as you go)
