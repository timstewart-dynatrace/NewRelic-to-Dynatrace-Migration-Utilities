# Phase 07 — Validation, Retry & Diff
Status: DONE

## Goal
Production-harden the migration pipeline with pre-import DQL validation, dry-run preview, partial retry, and diff/preview against live environment.

## Tasks
- [ ] Pre-import DQL validation during transform phase
- [ ] Dry-run preview with JSON output + summary table
- [ ] Partial retry (save failed entities, --retry flag)
- [ ] Diff/preview before import (--diff flag, CREATE/UPDATE/CONFLICT)
- [ ] Tests for all new features
- [ ] Phase gate: docs, memories, commit/push, v1.1.0

## Acceptance Criteria
- DQL validation runs on every converted query when registry available
- Dry-run shows entity count summary + saves preview JSON
- Failed entities saved to JSON, retryable via --retry
- --diff shows what would be created vs updated vs conflicting
- All new code has tests

## Decisions Made This Phase
(append as you go)
