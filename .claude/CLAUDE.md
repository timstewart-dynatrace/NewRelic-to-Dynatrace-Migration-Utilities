# New Relic to Dynatrace Migration Tool

**ALWAYS** ask clarifying questions and **ALWAYS** provide a plan **BEFORE** making changes.

## Project Summary

Universal migration tool for converting New Relic monitoring configurations to Dynatrace. Migrates dashboards (with a real NRQL-to-DQL compiler), alerts, synthetic monitors, SLOs, and workloads. Three-phase pipeline: Export (NR NerdGraph) -> Transform -> Import (DT APIs). Supports config-as-code export (Monaco, Terraform).

**Last Updated:** 2026-09-16
**Version:** 2.0.0 (+ PRs #16–24 Gen3-tenant correctness fixes; unreleased: `preflight` scope diagnostics)
**Phases Completed:** 0-26 + 19b + 3rd-pass + Phase 25 (all complete)

## Quick Reference

```bash
# Run tests (1183 unit + 158 legacy + 14 env-gated integration; 48 files)
pytest tests/ -v

# Probe target tenant for Gen3 API access + missing token scopes
python migrate.py preflight

# Integration tests (requires .env with real credentials)
RUN_INTEGRATION_TESTS=1 pytest tests/integration/ -v

# Compile single query
python migrate.py compile "SELECT count(*) FROM Transaction"

# Interactive REPL
python migrate.py compile --interactive

# Batch compile from file
python migrate.py compile --file examples/example_queries.nrql

# Batch CSV/Excel
python migrate.py batch --file queries.csv --output results.csv

# Reference table
python migrate.py reference

# Full migration
python migrate.py migrate --dry-run          # Preview what would be created
python migrate.py migrate --full             # Execute migration
python migrate.py migrate --diff             # Compare against live DT
python migrate.py migrate --retry failed.json # Retry failed entities

# Config-as-code export
python migrate.py export-monaco --input ./output --output ./monaco-out
python migrate.py export-terraform --input ./output --output ./tf-out

# SLO audit
python migrate.py audit-slos

# Version
python migrate.py --version
```

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Runtime | Python 3.9+ | Broad compatibility |
| Config | Pydantic + python-dotenv | Typed settings from .env |
| CLI | Click + Rich | Subcommands with progress display |
| Logging | structlog | Structured logging |
| HTTP | requests | API clients |
| Testing | pytest + hypothesis | 1183 unit (incl 36 property-based + wire-level Gen3 regressions) + 158 legacy + 14 integration tests |

## Architecture

```
EXPORT (NR NerdGraph)  ->  TRANSFORM  ->  IMPORT (DT APIs)
                                      ->  EXPORT (Monaco / Terraform)

Gen3 Default Transformers (40+):          Targets:
  DashboardTransformer (AST compiler)       Grail Dashboards (Document API)
  AlertTransformer + NotificationTfmr       Workflows + Davis Anomaly Detectors
  SyntheticTransformer                      builtin:synthetic_test
  SLOTransformer                            builtin:monitoring.slo
  WorkloadTransformer                       builtin:segment + IAM policy
  InfrastructureTransformer                 Davis Anomaly Detectors + Workflows
  LogParsingTransformer                     OpenPipeline DPL processors
  TagTransformer                            OpenPipeline enrichment
  DropRuleTransformer                       OpenPipeline drop/removeFields
  BrowserRUMTransformer                     builtin:rum.web.app-config
  MobileRUMTransformer                      builtin:mobile-application
  LambdaTransformer                         DT Lambda extension layer ARNs
  CloudIntegrationTransformer               builtin:cloud.{aws,azure,gcp}
  KubernetesTransformer                     DynaKube CR + Helm values
  AIOpsTransformer                          Workflows + enrichments + detectors
  VulnerabilityTransformer                  builtin:appsec.vulnerability-*
  + 24 more (see docs/COVERAGE.md for full inventory)

NRQL Compiler Pipeline:
  NRQL string -> Shorthands -> Lexer -> Token[] -> Parser -> AST ->
  DQLEmitter -> DQL string -> Phase19Uplift -> ConfidenceSync

Gen2 Legacy (via --legacy):       Gen3 Default Targets:
  transformers/legacy/               Workflows + Davis Detectors
  clients/legacy/                    Segments + IAM policies
  exporters/legacy/                  OpenPipeline processors
                                     Document API dashboards/notebooks
```

### Transformer Interface Standard

All transformers follow a consistent pattern:
- **Result class**: `{Entity}TransformResult` dataclass with `success`, `warnings`, `errors`
- **Method**: `transform(nr_entity) -> {Entity}TransformResult` (single item)
- **Batch**: `transform_all(items) -> List[{Entity}TransformResult]`

## Key Directories

| Path | Purpose |
|------|---------|
| `compiler/` | NRQL-to-DQL AST compiler (309 compiler tests) + `shorthands.py` |
| `clients/` | Gen3 facade: Settings 2.0 + Document + Automation + OAuth2; legacy Config v1 under `clients/legacy/` |
| `transformers/` | 40+ entity transformers (Gen3 default) + NRQL converter + mapping tables + `mappings/` submodules + `metric_transform.py` plugin hook; legacy Gen2 under `transformers/legacy/` |
| `validators/` | DQL syntax validator + 24-rule auto-fixer (parity with nrql-engine) |
| `registry/` | DTEnvironmentRegistry (metrics, entities, segments, dashboards, locations) + SLOAuditor |
| `migration/` | Rollback, checkpoint, incremental, reports, retry, diff, `canary.py` (Phase 20), `audit.py` (Phase 20) |
| `agents/` | Per-language APM agent migration orchestrator (7 languages) |
| `scripts/` | `fetch_dt_schemas.py` (Settings 2.0 schema fixtures for offline validation) |
| `exporters/` | Gen3 Monaco v2 YAML + Gen3 Terraform HCL; legacy exporters under `exporters/legacy/` |
| `tools/` | `nrdb_archive.py` (pre-decommission JSONL snapshot) |
| `config/` | Pydantic BaseSettings from .env + `project_links.py` URL registry |
| `utils/` | Logging, auth (OAuth), validators, `error_taxonomy.py` (WarningCode/ErrorCode) |
| `examples/` | Sample NRQL queries for batch testing |
| `docs/` | `COVERAGE.md`, `migration-coverage.md`, `gen2-only-capabilities.md`, `out-of-scope.md`, `validation.md`, `architecture.md`, `nrql-engine-sync-audit.md`, `token-scopes.md` (Platform/Classic token scopes), `quickstart.md`, `migration-guide.md` |
| `tests/` | 1183 unit (incl 36 Hypothesis + wire-level `TestAnomalyDetectorWirePayload` / `TestMultipartContentTypeWire` / `TestAnalyzerInputQueryIsDql`) + 14 integration tests; `tests/legacy/` (158) for Gen2 paths; `tests/integration/` for schema/IaC validation (env-gated) |

## Rules

### Always active
@.claude/rules/architecture.md
@.claude/rules/python.md
@.claude/rules/testing.md
@.claude/rules/development.md
@.claude/rules/deployment.md
@.claude/rules/gen3-apis.md

## Skills

Two sources. **Dynatrace-maintained** skills (`dynatrace-for-ai`, Apache-2.0, `github.com/Dynatrace/dynatrace-for-ai`) are authoritative for DQL syntax, Smartscape, dashboards/notebooks JSON, and alerting — prefer them when they disagree with the template skills. **Template** skills (`VisualCode-AI-Template`) cover NRQL translation, APIs, IaC, and IAM, which `dynatrace-for-ai` does not.

### Always active — DQL, Smartscape, documents, alerting (dynatrace-for-ai)
@/Users/Shared/GitHub/PROJECTS/CLAUDE/dynatrace-for-ai/skills/dt-dql-essentials/SKILL.md
@/Users/Shared/GitHub/PROJECTS/CLAUDE/dynatrace-for-ai/skills/dt-migration/SKILL.md
@/Users/Shared/GitHub/PROJECTS/CLAUDE/dynatrace-for-ai/skills/dt-app-dashboards/SKILL.md
@/Users/Shared/GitHub/PROJECTS/CLAUDE/dynatrace-for-ai/skills/dt-app-notebooks/SKILL.md
@/Users/Shared/GitHub/PROJECTS/CLAUDE/dynatrace-for-ai/skills/dt-alerting/SKILL.md

### Always active — NRQL translation, APIs, config-as-code (template)
@/Users/Shared/GitHub/PROJECTS/CLAUDE/VisualCode-AI-Template/SKILLS/nrql-to-dql/SKILL.md
@/Users/Shared/GitHub/PROJECTS/CLAUDE/VisualCode-AI-Template/SKILLS/dynatrace-apis/SKILL.md
@/Users/Shared/GitHub/PROJECTS/CLAUDE/VisualCode-AI-Template/SKILLS/dynatrace-document-api/SKILL.md
@/Users/Shared/GitHub/PROJECTS/CLAUDE/VisualCode-AI-Template/SKILLS/dynatrace-monaco/SKILL.md
@/Users/Shared/GitHub/PROJECTS/CLAUDE/VisualCode-AI-Template/SKILLS/dynatrace-terraform/SKILL.md

### Always active — documentation + graphics (template)
@/Users/Shared/GitHub/PROJECTS/CLAUDE/VisualCode-AI-Template/SKILLS/svg-graphics/SKILL.md

### Always active — Gen3 transformer targets (template)
@/Users/Shared/GitHub/PROJECTS/CLAUDE/VisualCode-AI-Template/SKILLS/dynatrace-workflow/SKILL.md
@/Users/Shared/GitHub/PROJECTS/CLAUDE/VisualCode-AI-Template/SKILLS/dynatrace-iam/SKILL.md
@/Users/Shared/GitHub/PROJECTS/CLAUDE/VisualCode-AI-Template/SKILLS/dynatrace-entity-tagging/SKILL.md
@/Users/Shared/GitHub/PROJECTS/CLAUDE/VisualCode-AI-Template/SKILLS/dynatrace-lookup-tables/SKILL.md
@/Users/Shared/GitHub/PROJECTS/CLAUDE/VisualCode-AI-Template/SKILLS/k8s-dynatrace-operator/SKILL.md
@/Users/Shared/GitHub/PROJECTS/CLAUDE/VisualCode-AI-Template/SKILLS/dynatrace-account-management/SKILL.md

Replaced by dynatrace-for-ai equivalents (do not re-add): `dynatrace-dql` → `dt-dql-essentials`, `dynatrace-notebook-authoring` → `dt-app-notebooks`, `dynatrace-alert-routing` → `dt-alerting`.

### On demand — reference material (read when relevant, not imported)
- `/Users/Shared/GitHub/PROJECTS/CLAUDE/dynatrace-for-ai/skills/dt-migration/references/` — full classic→Smartscape type table, `entityName`/`entityAttr`/`classicEntitySelector` rewrites, special cases (host/process/container groups)
- `/Users/Shared/GitHub/PROJECTS/CLAUDE/dynatrace-for-ai/skills/dt-dql-essentials/references/dql/` — per-command and per-function DQL reference
- `/Users/Shared/GitHub/PROJECTS/CLAUDE/dynatrace-for-ai/skills/dt-alerting/references/anomaly-detectors.md` — full static/adaptive/seasonal detector payloads
- `/Users/Shared/GitHub/PROJECTS/CLAUDE/dynatrace-for-ai/skills/dt-alerting/references/workflow-notifications.md` — problem-trigger workflows, `dt.alert_group` routing
- `/Users/Shared/GitHub/PROJECTS/CLAUDE/dynatrace-for-ai/skills/dt-app-dashboards/assets/` — `ExampleDashboard.json`, `visualization-settings.reference.jsonc`

## Key Constraints

- **No hardcoded credentials** — all secrets via .env / environment variables
- **Community project** — not officially supported by Dynatrace
- **Feature branches** — never commit features directly to main
- **Compiler vs Converter** — `compiler/` handles pure NRQL->DQL translation. `transformers/nrql_converter.py` wraps it with post-processing, auto-fixes, Phase 19 confidence uplift, Phase 23 `MetricTransform` plugin hook, and numeric confidence-score sync.
- **Gen3 default vs `--legacy`** — All transformers, clients, and exporters emit Gen3 objects by default. Gen2 code lives under `*/legacy/` and is only reachable via `--legacy` CLI flag or `MIGRATION_LEGACY_MODE=true` env var. See `docs/gen2-only-capabilities.md` for the 8 capabilities only `--legacy` provides.
- **DQL validation** — structurally valid DQL doesn't guarantee data returns. Field existence requires live validation against Grail API. See `docs/validation.md` for the 6-tier validation strategy.
- **nrql-engine parity** — the TS sibling at `/Users/Shared/GitHub/PROJECTS/NewRelic/nrql-engine/` is kept at parity (53/53 transformer files covered). CI `nrql-engine-parity` job guards drift. See `docs/nrql-engine-sync-audit.md`.
- **Phase gates** — Every phase must have complete tests, documentation, and memory updates before moving to the next phase. All phases (0–26 + 19b + 3rd-pass + 25 + 15) are complete as of v2.0.0.
- **Emitted DQL must be Smartscape-first** — `dt.entity.*`, `entityName()`, `entityAttr()`, and `classicEntitySelector()` are deprecated. See `.claude/rules/gen3-apis.md` §7.
- **Gen3 API correctness** — Producing requests that Gen3 SaaS (`.apps.*`) tenants accept has several non-obvious rules (auth-by-token-prefix, `/platform/classic/environment-api/v2` settings path, multipart Document API, dict-shaped `tasks`, DQL in `analyzer.input`, v1.0.14 `builtin:davis.anomaly-detectors` shape). See `.claude/rules/gen3-apis.md` before writing new code that talks to a Gen3 tenant.
- **Gen3 SKIPPED entities** — Synthetic monitors, Grail segments, and IAM policies are deliberately SKIPPED in `migrate.py::_import_phase` (per-facet emission / Platform API / Account Management API not wired). Envelopes still get built; only the POST step is skipped. Don't re-enable without building the right Gen3 client. See `.claude/rules/gen3-apis.md`.
