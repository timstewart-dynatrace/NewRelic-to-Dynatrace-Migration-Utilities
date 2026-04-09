# Phase 06 — API Modernization & CI/CD
Status: PENDING

## Goal
Modernize API integrations to use Dynatrace's latest APIs, add CI pipeline, and align with production deployment patterns from the sibling repos.

## Tasks
- [ ] **Documents API for dashboards**
  - Replace Config API v1 dashboard creation with Platform Documents API (`/platform/document/v1/documents`)
  - Support dashboard schema version discovery
  - Support create and update operations
  - Maintain backwards compatibility with Config API v1 as fallback
- [ ] **GitHub Actions CI pipeline**
  - Port `.github/workflows/ci.yml` from Migrator repo
  - Run pytest on push/PR
  - Run ruff linter
  - Run mypy type checking
  - Upload coverage report
  - Matrix test on Python 3.9, 3.10, 3.11, 3.12
- [ ] **Package as installable pip package**
  - Complete `pyproject.toml` with full metadata (name, version, description, authors, classifiers)
  - Add `[project.scripts]` entry point for CLI: `nrql-migrate = "migrate:cli"`
  - Build and verify: `pip install -e .`
  - Add `py.typed` marker for type checking consumers
- [ ] **Excel batch processing** (from nrql-translator)
  - Accept Excel file with NRQL column
  - Translate all queries, write DQL + confidence + status back to Excel
  - Support row/sheet filtering
  - Add `batch` CLI subcommand
- [ ] **Dynatrace MCP Server integration**
  - Add optional MCP server configuration for Claude Code integration
  - Enable live DQL query execution via MCP
  - Document setup in README
- [ ] **Incident Workflows transformer** (stretch goal)
  - NR Applied Intelligence workflows → DT AutomationEngine workflows
  - Map triggers, conditions, and actions
  - This is high-complexity; may require multiple sessions
- [ ] Tests for Documents API client, CI validation, batch processing

## Acceptance Criteria
- Dashboards created via Documents API when available, Config API v1 fallback works
- CI pipeline passes on all supported Python versions
- Package installs cleanly with `pip install -e .`
- Excel batch mode processes 100+ queries in a single run
- MCP integration documented and functional
- All new code has tests

## Decisions Made This Phase
(append as you go)
