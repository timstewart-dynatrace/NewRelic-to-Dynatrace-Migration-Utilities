# Dynatrace-NewRelic Migration Tools

**Last Updated:** 2026-04-09

## Project Overview

Repository containing the New Relic to Dynatrace migration framework. All tools are consolidated under `newrelic-to-dynatrace-migration/` — see its `.claude/CLAUDE.md` for detailed instructions.

## Quick Reference

```bash
cd newrelic-to-dynatrace-migration

# Run tests (863 total)
pytest tests/ -v

# Compile single query
python migrate.py compile "SELECT count(*) FROM Transaction"

# Interactive REPL
python migrate.py compile --interactive

# Batch compile from file
python migrate.py compile --file examples/example_queries.nrql

# Reference table
python migrate.py reference

# Full migration (dry run)
python migrate.py migrate --dry-run
```

## Key Constraints

- **No hardcoded credentials** — all secrets via .env / environment variables
- **Community project** — not officially supported by Dynatrace
- **Feature branches** — never commit features directly to main

## Active Development

See `newrelic-to-dynatrace-migration/.claude/phases/` for the 7-phase roadmap:
0. ~~Consolidate nrql-converter into Migration Tool~~ (done)
1. ~~Compiler Enhancements~~ (done)
2. ~~Test Coverage Completion~~ (done)
3. ~~Environment Registry & Live Validation~~ (done)
4. ~~New Entity Transformers~~ (done)
5. ~~Migration Infrastructure~~ (done)
6. API Modernization & CI/CD

## Sub-project Instructions

@newrelic-to-dynatrace-migration/.claude/CLAUDE.md
