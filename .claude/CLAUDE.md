# Dynatrace-NewRelic Migration Tools

**Last Updated:** 2026-04-08

## Project Overview

Repository containing tools for migrating New Relic monitoring configurations to Dynatrace. Two components:

| Tool | Location | Purpose |
|------|----------|---------|
| **NRQL to DQL Converter** | `nrql-converter/` | Standalone query converter (lightweight) |
| **Migration Framework** | `newrelic-to-dynatrace-migration/` | Full migration pipeline (export→transform→import) |

The migration framework is the primary active project — see its `.claude/CLAUDE.md` for detailed instructions.

## Quick Reference

```bash
cd newrelic-to-dynatrace-migration

# Run tests (649 total)
pytest tests/ -v

# Compile single query
python migrate.py compile "SELECT count(*) FROM Transaction"

# Full migration (dry run)
python migrate.py migrate --dry-run
```

## Key Constraints

- **No hardcoded credentials** — all secrets via .env / environment variables
- **Community project** — not officially supported by Dynatrace
- **Feature branches** — never commit features directly to main

## Active Development

See `newrelic-to-dynatrace-migration/.claude/phases/` for the 6-phase roadmap:
1. Compiler Enhancements
2. Test Coverage Completion
3. Environment Registry & Live Validation
4. New Entity Transformers
5. Migration Infrastructure
6. API Modernization & CI/CD

## Sub-project Instructions

@newrelic-to-dynatrace-migration/.claude/CLAUDE.md
