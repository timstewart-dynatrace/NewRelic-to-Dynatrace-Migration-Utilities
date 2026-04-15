# Out of Scope — What This Tool Will Never Migrate

> **Companion to:** `docs/migration-coverage.md` (inventories ✅/🟡/🔴 items)
> **Last updated:** 2026-04-15 (post-Phase-22)

Some New Relic surfaces have no Dynatrace equivalent, are explicit
platform behaviors rather than configuration, or are deliberately
excluded because the cost of migration exceeds the value. This document
makes the exclusions permanent so future phases do not re-litigate them.

## Permanent exclusions

### 1. Historical NRDB data

**Why:** Dynatrace Grail is a live-ingest system. There is no bulk-load
path for past event records. Replaying historical data would not produce
meaningful Davis baselines or span timelines, since timestamps and
causal relationships would be rewritten at ingest time.

**Alternative:** Run both platforms in parallel during the migration
window; use `tools/nrdb_archive.py` for offline JSONL archives if
compliance or forensic retention is required.

### 2. Secrets

**Why:** API keys, webhook URLs, PagerDuty integration keys, Slack
connection IDs, SAML signing certificates, and SCIM bearer tokens are
considered non-portable by design. Any transfer would be a security
regression.

**Alternative:** The tool emits runbook items enumerating what the
operator must re-create on the Dynatrace side. Never commit secrets to
source control.

### 3. Custom Nerdpacks / NR One apps

**Why:** New Relic's Nerdpack ecosystem (React-based NR One apps,
custom visualizations, bespoke GraphQL fragments) has no 1:1 path to
Dynatrace AppEngine. The UI frameworks and data models differ enough
that translation would be a rewrite, not a migration.

**Alternative:** Inventory which Nerdpacks a customer uses; reimplement
the critical ones as DT AppEngine apps after the core data migration.

### 4. Davis-replaced features

**Why:** These NR features are replaced by Dynatrace Davis's automatic
causal engine. Migrating the rules would duplicate work Davis already
does and produce conflicting signals.

- NR AIOps **Decisions** (manual correlation rules)
- NR proactive detection thresholds
- NR anomaly detection **sensitivity presets** that conflict with Davis
  auto-adaptive baselines

**Alternative:** `AIOpsTransformer` (Phase 18) captures the original
logic as decision_notes so operators have a reference; it does not
attempt to recreate the rules.

### 5. DT platform features (not configuration)

These are things Dynatrace does automatically; there is no configuration
to migrate because there is no configuration on the DT side.

- **Smartscape** topology — DT auto-discovers entity relationships
- **Davis** problem detection and RCA
- **Log pattern recognition** (auto-clustering)
- **Error fingerprinting** (span error grouping)
- **Live tail** log view
- **PurePath** trace sampling

Customer expectations for these sometimes collide with migration scope
(e.g., "migrate my NR Service Map annotations"). The answer is that DT
doesn't have an equivalent place to put the annotations — the topology
is the source of truth.

### 6. NRQL features without DQL equivalents

- `COMPARE WITH n hours ago` on span queries (DQL `shift:` only works
  on `timeseries` / `makeTimeseries`, not `fetch spans`). Handled by
  extending the query timeframe instead — documented confidence HIGH
  via Phase 19 uplift.
- `EXTRAPOLATE` full-fidelity extrapolation beyond `countDistinct`.
  DT's `extrapolate:true` flag is more limited.
- Nested aggregations (`sum(average(x))`). Split into two queries.
- `FACET CASES` (SQL-like CASE expression in facet). Must be rewritten
  as `fieldsAdd` + `summarize`.

## Decision log

| Decision | Rationale | Date |
|---|---|---|
| Do not emit Metric Events as Gen3 default | Davis Anomaly Detectors supersede them; Gen2 fallback keeps MEs via `--legacy`. | 2026-04-14 |
| Do not attempt to reconstruct NR Service Map annotations | Smartscape replaces them; user-drawn annotations have no DT slot. | 2026-04-15 |
| `nr1` CLI not in migration scope | Customer-specific rewrite; track as reference work in runbooks. | 2026-04-15 |
| `newrelic.setTransactionName()` does not map to a runtime call | DT uses config-time request-naming rules. Emit LOW confidence. | 2026-04-15 |
| NR Decisions captured as notes, not migrated | Davis causal engine is automatic. | 2026-04-15 |

## What to do when a user asks about an out-of-scope item

1. Confirm it's in this document.
2. Offer the listed alternative (runbook, archive tool, parallel run,
   re-implementation).
3. If the user disagrees, the answer is *not* "we'll add it to the
   tool" — surface the underlying platform constraint.
4. Update this file if a previously-out-of-scope item becomes migratable
   (e.g., DT ships a new API). Add a HISTORY.md entry alongside.
