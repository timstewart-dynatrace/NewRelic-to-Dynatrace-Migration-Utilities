# Phase 21 — Cross-Repo Alignment + Dynatrace-DMA Relocation
Status: PENDING

## Goal
Finalize cross-repo references: the `nrql-engine` repo will relocate to `dynatrace-dma`. Update every internal URL, footer, and docstring, and mirror the changes the NRLC series expects.

## Tasks
- [ ] Replace `https://github.com/timstewart-dynatrace/nrql-engine` with the new canonical URL across README.md, docs/, CHANGELOG.md, and code comments
- [ ] Move "planned future home: dynatrace-dma" language to "canonical home" once the move is complete
- [ ] Preserve a historical note in HISTORY.md (this repo) pointing to the old URL
- [ ] Replicate NRLC/NR2DT notebook footer updates into this repo's generated artifact footers (Monaco exports, Terraform comments)
- [ ] Update `transformers/mapping_rules.py` docstrings that cite NR→DT terminology to remove Gen2 nostalgia
- [ ] Verify `docs/migration-research.md` and `docs/migration-guide.md` point to the updated notebook series

## Acceptance Criteria
- `grep -r timstewart-dynatrace/nrql-engine` returns zero matches
- `grep -r dynatrace-dma` finds the updated canonical URL in every place where the old URL used to live
- README still renders cleanly; Monaco/Terraform export footers carry the new attribution

## Decisions Made This Phase
(append as you go)
