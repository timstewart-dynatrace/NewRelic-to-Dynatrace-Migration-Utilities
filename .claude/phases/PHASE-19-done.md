# Phase 19 — Data Fidelity, Dashboard Parity, Confidence Uplift
Status: PENDING

## Goal
Close remaining dashboard/widget and compiler-confidence gaps so migrations require less manual review.

## Tasks
- [ ] Funnel widget → DT multi-stage chart composite (no single equivalent; generate composite tile)
- [ ] Heatmap widget → DT honeycomb tile (real visualization, not table fallback)
- [ ] Event-feed widget → DT events table with canonical sort key
- [ ] Cascading dashboard variables: fully honor NR variable dependencies
- [ ] Permissions mapping: NR dashboard permissions → Document sharing settings (concrete mapping, not just conceptual)
- [ ] Saved filter sets → Document saved views
- [ ] Compiler: Apdex translation uplift from LOW → HIGH confidence (add bucketing patterns)
- [ ] Compiler: COMPARE WITH → DT overlay tile (replace markdown placeholder)
- [ ] Compiler: `rate()` interval preservation → emit per-second DQL rate expression
- [ ] Compiler: `percentage()` decomposition → inline `fieldsAdd` division

## Acceptance Criteria
- Compiler confidence scores: ≥ 95% of fixtures return HIGH (current baseline: ~85%)
- Every widget type in the NR inventory has at least a 🟡 entry in `migration-coverage.md` (no 🔴 dashboard widgets remain)
- Full suite + 50 new widget/compiler tests pass

## Decisions Made This Phase
(append as you go)
