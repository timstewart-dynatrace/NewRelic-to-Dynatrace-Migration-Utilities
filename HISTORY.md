# HISTORY

A running record of ownership, location, and branding changes for this
project and its siblings. New entries go at the top.

## 2026-04-15 — Planned relocation of `nrql-engine` to `dynatrace-dma`

The TypeScript sibling project `nrql-engine` (currently hosted under the
`timstewart-dynatrace` GitHub org) is planned to relocate to a canonical
`dynatrace-dma` org. This repo (`Dynatrace-NewRelic`) stays where it is
for now.

When the relocation lands:

- Update `docs/project_links.py` → `NRQL_ENGINE_URL` to the new canonical URL
- Move "planned future home: dynatrace-dma" language to "canonical home"
- Keep this HISTORY entry as the permanent breadcrumb for the old URL
- Ask the user before pushing any force-updates to docs that carry
  hardcoded URLs (per the release-hold directive in effect since
  2026-04-15)

**Old canonical URL (still active at audit time):**
`https://github.com/timstewart-dynatrace/nrql-engine`

**Future canonical URL (expected):**
`https://github.com/dynatrace-dma/nrql-engine` (exact slug TBD)

## 2026-04-14 → 2026-04-15 — Gen3 refactor (v2.0.0 prep)

Internal refactor from Gen2 (Alerting Profiles, Management Zones,
Auto-Tag Rules, Problem Notifications, Config v1 Dashboards/Synthetics)
to Gen3 (Workflows, Davis Anomaly Detectors, Segments, OpenPipeline
enrichment, Document API dashboards, Settings 2.0 synthetic/SLO). Gen2
is preserved under `transformers/legacy/`, `clients/legacy/`, and
`exporters/legacy/` behind a `--legacy` CLI flag.

Phases 11–14 landed the refactor. Phases 16–19 closed P0 and P1
coverage gaps (agents, RUM, Mobile, Lambda, custom instrumentation,
non-NRQL alerts, baseline/outlier, lookup tables, maintenance windows,
change tracking, custom events, identity, log obfuscation, cloud
integrations, K8s, AIOps, vulnerability, NPM, AI monitoring,
Prometheus, widget parity, compiler confidence uplift). Phase 19b
pinned nrql-engine parity for compiler-level items. Release (version
bump, tag, merge) is on hold per user directive pending final review.

## Pre-2026-04-14 — See CHANGELOG.md

All pre-Gen3 history lives in `CHANGELOG.md`. Phases 0–10 were tracked
in `.claude/phases/PHASE-00-done.md` through `PHASE-10-done.md`.
