# Development Setup & Workflow

## Prerequisites

- Python 3.9+ (verify with `python3 --version`)
- pip (included with Python)

## Initial Setup

```bash
# Clone repository
git clone https://github.com/timstewart-dynatrace/NewRelic-to-Dynatrace-Migration-Utilities.git
cd NewRelic-to-Dynatrace-Migration-Utilities

# Create virtual environment
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate        # macOS/Linux
# OR
.venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requirements.txt

# Install dev dependencies
pip install -e ".[dev]"

# Verify installation
python migrate.py --version

# Set up environment
cp .env.example .env
# Edit .env with your NR/DT credentials
```

## Development Workflow

### Common Tasks

| Task | Command |
|------|---------|
| Run all tests | `pytest tests/ -v` |
| Run with coverage | `pytest --cov=. --cov-fail-under=80` |
| Run single test file | `pytest tests/unit/test_compiler.py -v` |
| Debug specific test | `pytest -vv tests/unit/test_compiler.py::TestClass::test_method` |
| Integration tests | `RUN_INTEGRATION_TESTS=1 pytest tests/integration/ -v` |
| Lint code | `ruff check .` |
| Format code | `ruff format .` |
| Type checking | `mypy compiler/ migration/ validators/ config/` |
| Compile a query | `python migrate.py compile "SELECT count(*) FROM Transaction"` |
| Interactive REPL | `python migrate.py compile --interactive` |
| Batch compile | `python migrate.py compile --file examples/example_queries.nrql` |
| CSV/Excel batch | `python migrate.py batch --file queries.csv --output results.csv` |
| Dry-run migration | `python migrate.py migrate --dry-run` |
| Full migration | `python migrate.py migrate --full` |
| Diff against live DT | `python migrate.py migrate --diff` |
| Monaco export | `python migrate.py export-monaco --input ./output --output ./monaco-out` |
| Terraform export | `python migrate.py export-terraform --input ./output --output ./tf-out` |
| SLO audit | `python migrate.py audit-slos` |
| Reference table | `python migrate.py reference` |
| Check outdated pkgs | `pip list --outdated` |
| Clean pycache | `find . -type d -name __pycache__ -exec rm -r {} +` |
| Profile performance | `python -m cProfile -s cumtime migrate.py compile "SELECT 1"` |

### Adding New Dependencies

```bash
# Install package
pip install package_name

# Update requirements.txt
pip freeze > requirements.txt

# Also add to pyproject.toml [project.dependencies] for install support
```

### Quality Gates (run before committing)

```bash
# All three must pass
ruff check . && ruff format --check . && pytest tests/ -v
```

## Dependency Files

| File | Purpose | Commit? |
|------|---------|---------|
| `requirements.txt` | Production + dev dependencies | Yes |
| `pyproject.toml` | Project metadata, build config, tool settings | Yes |
| `.venv/` | Virtual environment | No (.gitignore) |
| `.env` | Credentials and runtime config | No (.gitignore) |
| `.env.example` | Environment template | Yes |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `NEW_RELIC_API_KEY` | For migration | NerdGraph API key (`NRAK-...`) |
| `NEW_RELIC_ACCOUNT_ID` | For migration | NR account ID |
| `NEW_RELIC_REGION` | No | `US` (default) or `EU` |
| `DYNATRACE_API_TOKEN` | For migration | DT API token (`dt0c01....`) |
| `DYNATRACE_ENVIRONMENT_URL` | For migration | DT environment URL |
| `MIGRATION_DRY_RUN` | No | `true`/`false` (default: `false`) |
| `MIGRATION_OUTPUT_DIR` | No | Output directory (default: `./output`) |
| `MIGRATION_BATCH_SIZE` | No | Batch size (default: `50`) |
| `MIGRATION_RATE_LIMIT` | No | Requests/sec (default: `5.0`) |
| `LOG_LEVEL` | No | `DEBUG`/`INFO`/`WARNING`/`ERROR` |

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError` | Activate venv; reinstall: `pip install -r requirements.txt` |
| Tests can't find modules | Ensure venv activated; run from project root |
| Import errors after git pull | Delete venv and recreate: `rm -rf .venv && python3 -m venv .venv && pip install -r requirements.txt` |
| Integration tests skipped | Set `RUN_INTEGRATION_TESTS=1` and ensure `.env` has valid credentials |
| mypy errors on new code | Add module to mypy overrides in `pyproject.toml` if needed |
| ruff format conflicts | Run `ruff format .` then re-stage changes |
