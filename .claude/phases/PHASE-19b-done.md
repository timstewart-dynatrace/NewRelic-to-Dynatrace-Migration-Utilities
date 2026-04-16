# Phase 19b — Compiler Parity with nrql-engine
Status: ACTIVE

## Goal
Port the three compiler-level items from `docs/nrql-engine-sync-audit.md` where the TS sibling is ahead:

1. Phase 0 shorthand expansion (centralized pre-lex)
2. K8s metric overrides + entity-field map (correctness)
3. DQL fixer rules 7–20 (quality)

The transformer additions from the audit (KeyTransactionTransformer, OTel/StatsD/CWMS) stay in Phase 23.

## Tasks
- [ ] `compiler/shorthands.py` — `expand_nr_shorthands(nrql)` covering 9 patterns; wired into `NRQLCompiler.compile()`
- [ ] `compiler/emitter.py` — `K8S_METRIC_OVERRIDES` + `K8S_ENTITY_FIELDS`; route K8s queries through overrides
- [ ] `validators/dql_fixer.py` — port fixer rules 7–20 from TS `dql-fixer.ts`
- [ ] Tests: shorthand suite, K8s override suite, new fixer rule cases
- [ ] Coverage matrix refresh
