# Phase 01 — Compiler Enhancements
Status: PENDING

## Goal
Close compiler gaps by pulling proven patterns from the sibling repos, expanding NRQL coverage from 282 to 300+ tested patterns.

## Tasks
- [ ] NR shorthand expansion (from Migrator): `averageDuration → average(duration)`, `errorRate → percentage(...)`, `throughput → rate(...)`, `maxDuration`, `minDuration`, `medianDuration`, `apdexScore`, `apdexPerfZone` (8 magic fields)
- [ ] COMPARE WITH → `append` subquery (from nrql-translator): generate proper day-over-day DQL using `append [fetch ... from:shifted_time]` instead of just a warning comment
- [ ] `cdfPercentage()` decomposition (from nrql-translator): expand to multiple `countIf()` expressions per threshold instead of "not available" comment
- [ ] `FACET CASES(...)` support: conditional grouping in FACET clause
- [ ] `SLIDE BY` detection and warning: recognize sliding window aggregation, emit note
- [ ] `WITH TIMEZONE` handling: detect and lower confidence
- [ ] `IS TRUE` / `IS FALSE` condition handling: convert to `== true` / `== false`
- [ ] `capture()` function: regex field extraction → DQL `parse` with DPL pattern
- [ ] `eventType()` function: metadata query handling
- [ ] Nested `filter()` inside aggregations: `count(*, filter(WHERE ...))` → `countIf(...)`
- [ ] Add regression tests for every new pattern

## Acceptance Criteria
- All 8 NR shorthands expand correctly before lexing
- COMPARE WITH produces valid `append` subquery DQL (not just a comment)
- cdfPercentage produces multiple countIf expressions
- FACET CASES produces conditional by-clause
- SLIDE BY, WITH TIMEZONE detected without crashing
- IS TRUE/IS FALSE emit correct DQL
- 300+ compiler tests pass
- All existing 649 tests still pass

## Decisions Made This Phase
(append as you go)
