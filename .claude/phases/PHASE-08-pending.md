# Phase 08 — Export Formats: Monaco & Terraform
Status: PENDING

## Goal
Generate config-as-code output (Monaco YAML, Terraform HCL) from migrated configurations, enabling review-before-apply workflows.

## Tasks
- [ ] Monaco exporter (YAML project structure)
- [ ] Terraform exporter (.tf files with HCL resources)
- [ ] CLI: export-monaco, export-terraform subcommands
- [ ] Tests for both exporters
- [ ] Phase gate: docs, memories, commit/push, v1.2.0

## Acceptance Criteria
- Monaco output is valid Monaco v2 project structure
- Terraform output is valid HCL with dynatrace provider resources
- Both accept --output directory flag
- All new code has tests

## Decisions Made This Phase
(append as you go)
