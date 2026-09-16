# Copilot Instructions - NewRelic-to-Dynatrace Migration Utilities

## Project Overview

**v2.0.0** — Universal migration framework for converting New Relic monitoring configurations to Dynatrace. AST-based NRQL-to-DQL compiler with 309 compiler tests and 1,355 total tests (Gen3 default, Gen2 via `--legacy`).

## Architecture

```
Export (NR NerdGraph) → Transform (40 Gen3 transformers) → Import (DT Gen3 APIs) / Monaco / Terraform

NRQL Compiler: NRQL string → Shorthands → Lexer → Parser → AST → DQLEmitter → DQL string
```

**Key modules:**
- `compiler/` — AST-based NRQL→DQL compiler (lexer, parser, emitter)
- `transformers/` — 40 Gen3 entity transformers (see `docs/COVERAGE.md`); Gen2 `*_v1` under `transformers/legacy/` (`--legacy` only)
- `validators/` — DQL syntax validator + 25-rule auto-fixer
- `registry/` — DTEnvironmentRegistry for live validation + SLOAuditor
- `migration/` — Rollback, checkpointing, incremental state, conversion reports, retry, diff, canary, audit
- `clients/` — NR NerdGraph + DT Gen3 facade (Settings 2.0, Document API v1 multipart, Automation API v1); Config v1 under `clients/legacy/`. Gen3 request rules: `.claude/rules/gen3-apis.md`
- `migrate.py` — Click CLI (migrate, compile, convert, reference, batch, extract-nrql, preflight, audit, audit-slos, export-monaco, export-terraform, agents, scan-instrumentation, archive)
- `exporters/` — Gen3 Monaco YAML + Terraform HCL exporters (Gen2 under `exporters/legacy/`)
- `agents/`, `tools/` — per-language APM agent orchestrators; NRDB archive

## Transformer Pattern

All transformers follow this interface:
```python
@dataclass
class {Entity}TransformResult:
    success: bool
    {payload}: Optional[...] = None  # entity-specific
    warnings: List[str] = None
    errors: List[str] = None

class {Entity}Transformer:
    def transform(self, nr_entity: Dict) -> {Entity}TransformResult: ...
    def transform_all(self, items: List[Dict]) -> List[{Entity}TransformResult]: ...
```

## CLI Commands

```bash
python migrate.py compile "SELECT count(*) FROM Transaction"  # Single query
python migrate.py compile --interactive                        # REPL
python migrate.py compile --file queries.nrql                  # Batch
python migrate.py compile --validate "SELECT ..."              # Live DT validation
python migrate.py convert "SELECT ..."                         # Compile + auto-fix
python migrate.py reference                                    # NRQL→DQL table
python migrate.py reference --mappings                         # Full mapping tables
python migrate.py batch --file queries.csv                     # CSV batch
python migrate.py audit-slos                                   # SLO metric audit
python migrate.py preflight                                    # Gen3 API access + token scope check
python migrate.py migrate --dry-run                            # Validate
python migrate.py migrate --full                               # Execute
python migrate.py migrate --list-components                    # Show components
python migrate.py migrate --diff                               # Compare vs live DT
python migrate.py migrate --retry failed.json                  # Retry failures
python migrate.py export-monaco --input ./output               # Monaco export
python migrate.py export-terraform --input ./output            # Terraform export
python migrate.py --version                                    # Show version
```

## Testing

```bash
pytest tests/ -v                    # 1194 unit + 158 legacy + 14 gated integration
pytest tests/unit/test_compiler.py  # 309 compiler tests
pytest -x --tb=short               # Stop on first failure
```

## Code Conventions

1. **Logging:** `structlog` (not `logging`)
2. **Config:** Pydantic BaseSettings from `.env`
3. **Results:** Dataclass result types, never raw dicts
4. **Imports:** stdlib → third-party → local
5. **CLI:** Click decorators + Rich output
6. **HTTP mocking:** `unittest.mock.patch` on session methods

## Adding a New Transformer

1. Create `transformers/{name}_transformer.py` with `{Name}TransformResult` + `{Name}Transformer`
2. Register in `transformers/__init__.py`
3. Add to `AVAILABLE_COMPONENTS` in `config/settings.py`
4. Add to `MigrationOrchestrator.__init__` and `_transform_phase` in `migrate.py`
5. Create `tests/unit/test_{name}_transformer.py`

## Entity Mapping

| New Relic | Dynatrace | Transformer |
|-----------|-----------|-------------|
| Dashboard | Dashboard | DashboardTransformer |
| Alert Policy | Alerting Profile | AlertTransformer |
| NRQL Condition | Metric Event | AlertTransformer |
| Notification | Problem Notification | NotificationTransformer |
| Synthetic Monitor | HTTP/Browser Monitor | SyntheticTransformer |
| SLO | SLO | SLOTransformer |
| Workload | Management Zone | WorkloadTransformer |
| Infra Condition | Metric Event | InfrastructureTransformer |
| Log Rule | Processing Rule | LogParsingTransformer |
| Tags | Auto-Tag Rules | TagTransformer |
| Drop Rules | Ingest Rules | DropRuleTransformer |
