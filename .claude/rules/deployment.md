# Deployment & Release Checklist

## Pre-Release Checklist

- [ ] All tests passing (`pytest tests/ -v`)
- [ ] Code coverage meets threshold (`pytest --cov=. --cov-fail-under=80`)
- [ ] Linting clean (`ruff check .`)
- [ ] Type checking clean (`mypy compiler/ migration/ validators/ config/`)
- [ ] Documentation complete and reviewed
- [ ] CHANGELOG.md updated with new version section
- [ ] Version incremented in both `pyproject.toml` and `_version.py` (must match)
- [ ] No uncommitted changes (`git status` clean)
- [ ] No hardcoded credentials or secrets
- [ ] `.env.example` updated if new env vars added

## Release Steps

1. **Verify quality gates**
   ```bash
   ruff check . && ruff format --check . && pytest tests/ -v --cov=. --cov-fail-under=80
   ```

2. **Bump version** (update both locations)
   ```bash
   # _version.py
   __version__ = "X.Y.Z"

   # pyproject.toml [project] section
   version = "X.Y.Z"
   ```

3. **Update CHANGELOG.md**
   - Move items from `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD`

4. **Commit version bump**
   ```bash
   git add _version.py pyproject.toml CHANGELOG.md
   git commit -m "chore: bump version to X.Y.Z"
   ```

5. **Tag release**
   ```bash
   git tag -a vX.Y.Z -m "Release vX.Y.Z: brief description"
   git push origin main --tags
   ```

6. **Build distribution** (if publishing to PyPI)
   ```bash
   python -m build
   twine check dist/*
   twine upload dist/*
   ```

## Post-Release

- [ ] Verify tag exists on remote (`git ls-remote --tags origin`)
- [ ] Create GitHub release from tag (include CHANGELOG section)
- [ ] Test install from fresh environment: `pip install .`
- [ ] Run smoke test: `python migrate.py --version` matches release
- [ ] Document any production insights in DECISIONS.md

## Rollback Procedure

If issues are found after release:

1. **Revert the problematic commit(s)**
   ```bash
   git revert <commit-sha>
   ```

2. **Bump patch version** (e.g., 1.3.1)
   ```bash
   # Update _version.py and pyproject.toml
   # Add fix entry to CHANGELOG.md
   ```

3. **Tag and release the fix**
   ```bash
   git tag -a vX.Y.Z -m "Hotfix: description"
   git push origin main --tags
   ```

4. **If published to PyPI**, upload the fixed version

## Version Locations

Both must always match:

| File | Field |
|------|-------|
| `_version.py` | `__version__ = "X.Y.Z"` |
| `pyproject.toml` | `version = "X.Y.Z"` |

## Release Notes Template

```markdown
# Release vX.Y.Z

**Release Date:** YYYY-MM-DD

## What's New

[2-3 line summary of major features/fixes]

## Migration Guide

[Any breaking changes, new env vars, or workflow changes]

## Changelog

[Link to or paste CHANGELOG section for this version]
```
