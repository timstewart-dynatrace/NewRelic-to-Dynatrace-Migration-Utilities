# New Relic to Dynatrace Migration Tool

**ALWAYS** ask clarifying questions and **ALWAYS** provide a plan **BEFORE** making changes.

## Project Summary

Universal migration tool for converting New Relic monitoring configurations to Dynatrace. Migrates dashboards (with a real NRQL-to-DQL compiler), alerts, synthetic monitors, SLOs, and workloads. Three-phase pipeline: Export (NR NerdGraph) -> Transform -> Import (DT APIs). Supports config-as-code export (Monaco, Terraform).

**Last Updated:** 2026-04-16
**Version:** 2.0.0
**Phases Completed:** 0-26 + 19b + 3rd-pass + Phase 25 (all complete)

## Quick Reference

```bash
# Run tests (894 unit + 8 integration across 28 files)
pytest tests/ -v

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
| Testing | pytest + hypothesis | 1237 unit (incl 36 property-based) + 8 integration tests |

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
| `compiler/` | NRQL-to-DQL AST compiler (292 tested patterns) + `shorthands.py` |
| `clients/` | Gen3 facade: Settings 2.0 + Document + Automation + OAuth2; legacy Config v1 under `clients/legacy/` |
| `transformers/` | 40+ entity transformers (Gen3 default) + NRQL converter + mapping tables + `mappings/` submodules + `metric_transform.py` plugin hook; legacy Gen2 under `transformers/legacy/` |
| `validators/` | DQL syntax validator + 24-rule auto-fixer (parity with nrql-engine) |
| `registry/` | DTEnvironmentRegistry (metrics, entities, segments, dashboards, locations) + SLOAuditor |
| `migration/` | Rollback, checkpoint, incremental, reports, retry, diff, `canary.py` (Phase 20), `audit.py` (Phase 20) |
| `exporters/` | Gen3 Monaco v2 YAML + Gen3 Terraform HCL; legacy exporters under `exporters/legacy/` |
| `agents/` | Per-language APM agent migration orchestrator (7 languages) |
| `tools/` | `nrdb_archive.py` (pre-decommission JSONL snapshot) |
| `config/` | Pydantic BaseSettings from .env + `project_links.py` URL registry |
| `utils/` | Logging, auth (OAuth), validators, `error_taxonomy.py` (WarningCode/ErrorCode) |
| `examples/` | Sample NRQL queries for batch testing |
| `docs/` | `COVERAGE.md`, `migration-coverage.md`, `gen2-only-capabilities.md`, `out-of-scope.md`, `validation.md`, `architecture.md`, `nrql-engine-sync-audit.md` |
| `tests/` | 1237 unit (incl 36 Hypothesis) + 8 integration tests; `tests/legacy/` for Gen2 paths; `tests/integration/` for schema/IaC validation (env-gated) |

## Rules

### Always active
@.claude/rules/architecture.md
@.claude/rules/python.md
@.claude/rules/testing.md
@.claude/rules/development.md
@.claude/rules/deployment.md

## Skills (domain knowledge from VisualCode-AI-Template/SKILLS/)

### Always active — core compilation + export
@/Users/Shared/GitHub/PROJECTS/VisualCode-AI-Template/SKILLS/dynatrace-dql/SKILL.md
@/Users/Shared/GitHub/PROJECTS/VisualCode-AI-Template/SKILLS/nrql-to-dql/SKILL.md
@/Users/Shared/GitHub/PROJECTS/VisualCode-AI-Template/SKILLS/dynatrace-apis/SKILL.md
@/Users/Shared/GitHub/PROJECTS/VisualCode-AI-Template/SKILLS/dynatrace-document-api/SKILL.md
@/Users/Shared/GitHub/PROJECTS/VisualCode-AI-Template/SKILLS/dynatrace-monaco/SKILL.md
@/Users/Shared/GitHub/PROJECTS/VisualCode-AI-Template/SKILLS/dynatrace-terraform/SKILL.md

### Always active — documentation + graphics
@/Users/Shared/GitHub/PROJECTS/VisualCode-AI-Template/SKILLS/svg-graphics/SKILL.md

### Always active — Gen3 transformer targets (Phase 11–24)
@/Users/Shared/GitHub/PROJECTS/VisualCode-AI-Template/SKILLS/dynatrace-workflow/SKILL.md
@/Users/Shared/GitHub/PROJECTS/VisualCode-AI-Template/SKILLS/dynatrace-alert-routing/SKILL.md
@/Users/Shared/GitHub/PROJECTS/VisualCode-AI-Template/SKILLS/dynatrace-iam/SKILL.md
@/Users/Shared/GitHub/PROJECTS/VisualCode-AI-Template/SKILLS/dynatrace-entity-tagging/SKILL.md
@/Users/Shared/GitHub/PROJECTS/VisualCode-AI-Template/SKILLS/dynatrace-lookup-tables/SKILL.md
@/Users/Shared/GitHub/PROJECTS/VisualCode-AI-Template/SKILLS/dynatrace-notebook-authoring/SKILL.md
@/Users/Shared/GitHub/PROJECTS/VisualCode-AI-Template/SKILLS/k8s-dynatrace-operator/SKILL.md
@/Users/Shared/GitHub/PROJECTS/VisualCode-AI-Template/SKILLS/dynatrace-account-management/SKILL.md

## Key Constraints

- **No hardcoded credentials** — all secrets via .env / environment variables
- **Community project** — not officially supported by Dynatrace
- **Feature branches** — never commit features directly to main
- **Compiler vs Converter** — `compiler/` handles pure NRQL->DQL translation. `transformers/nrql_converter.py` wraps it with post-processing, auto-fixes, Phase 19 confidence uplift, Phase 23 `MetricTransform` plugin hook, and numeric confidence-score sync.
- **Gen3 default vs `--legacy`** — All transformers, clients, and exporters emit Gen3 objects by default. Gen2 code lives under `*/legacy/` and is only reachable via `--legacy` CLI flag or `MIGRATION_LEGACY_MODE=true` env var. See `docs/gen2-only-capabilities.md` for the 8 capabilities only `--legacy` provides.
- **DQL validation** — structurally valid DQL doesn't guarantee data returns. Field existence requires live validation against Grail API. See `docs/validation.md` for the 6-tier validation strategy.
- **nrql-engine parity** — the TS sibling at `/Users/Shared/GitHub/PROJECTS/nrql-engine/` is kept at parity (53/53 transformer files covered). CI `nrql-engine-parity` job guards drift. See `docs/nrql-engine-sync-audit.md`.
- **Phase gates** — Every phase must have complete tests, documentation, and memory updates before moving to the next phase. All phases (0–26 + 19b + 3rd-pass + 25 + 15) are complete as of v2.0.0.
