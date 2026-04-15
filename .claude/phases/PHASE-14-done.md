# Phase 14 — `--legacy` Flag for Gen2 (Classic Tenant) Support
Status: PENDING

## Goal
Users on classic (Gen2) Dynatrace tenants without Gen3 features (Workflows, OpenPipeline, Segments, Document API) can opt into the old code paths via a single flag. Default remains Gen3.

## Rationale
Some customer tenants do not yet have Gen3 platform features provisioned. Removing Gen2 entirely would break those migrations. The `--legacy` flag is a stop-gap until those tenants upgrade.

## Tasks
- [ ] Add `--legacy` flag to `migrate.py` subcommands: `migrate`, `export-monaco`, `export-terraform`, `audit-slos`
- [ ] Add `MIGRATION_LEGACY_MODE: bool = False` to `config/settings.py` (Pydantic); CLI flag overrides env var
- [ ] Route legacy mode through `transformers/legacy/`, `clients/legacy/config_v1_client.py`, `exporters/legacy/`
- [ ] Emit a `WARNING` log at startup when legacy mode is active: "Running in Gen2 compatibility mode. Gen3 features (Workflows, OpenPipeline, Segments) will not be used."
- [ ] README + `.env.example` document the flag as "classic tenant support only"
- [ ] Add `--legacy` coverage to integration test matrix (dry-run)
- [ ] Add a `migrate.py preflight` check that detects whether the target tenant supports Gen3 (probe Document API + Automation API) and suggests `--legacy` if not

## Acceptance Criteria
- `python migrate.py migrate --legacy --dry-run` completes and produces Gen2 payloads
- `python migrate.py migrate --dry-run` (no flag) produces Gen3 payloads
- Preflight check correctly identifies Gen2-only tenants (unit-tested with mocked responses)
- README has a "Gen2 compatibility" section explaining the flag
- CHANGELOG notes the flag as a deprecation runway (removal planned in a future major)

## Decisions Made This Phase
(append as you go)
