"""
Centralized URLs and canonical references for this project and its siblings.

The point of this module is that when an external URL changes (notably
the planned `nrql-engine` → `dynatrace-dma` relocation), exactly one
file needs editing. Tests, footer templates, CHANGELOG helpers, and
generated artifact attribution all import from here.

HISTORY.md tracks the breadcrumbs for past / future relocations.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectLinks:
    """Single source of truth for external URLs.

    Update when a canonical URL changes; never hardcode URLs elsewhere in
    the codebase. Add a HISTORY.md entry alongside every change.
    """

    # This repo.
    dynatrace_newrelic_repo: str = (
        "https://github.com/timstewart-dynatrace/Dynatrace-NewRelic"
    )

    # TypeScript sibling. Planned relocation: `timstewart-dynatrace` -> `dynatrace-dma`.
    # When the move happens:
    #   1. Change `nrql_engine_repo` to the new canonical URL.
    #   2. Flip `nrql_engine_relocation_pending` to False.
    #   3. Log the change in HISTORY.md.
    nrql_engine_repo: str = "https://github.com/timstewart-dynatrace/nrql-engine"
    nrql_engine_relocation_pending: bool = True
    nrql_engine_future_org: str = "dynatrace-dma"

    # Notebook series (read-only reference).
    notebook_series_repo: str = (
        "https://github.com/timstewart-dynatrace/Best-Practice-Notebooks-Generator"
    )

    # Dynatrace-DMA umbrella (may host both once relocation completes).
    dma_org: str = "https://github.com/dynatrace-dma"


LINKS = ProjectLinks()


def nrql_engine_attribution() -> str:
    """Attribution string for artifact footers (Monaco / Terraform)."""
    if LINKS.nrql_engine_relocation_pending:
        return (
            f"Compiler parity maintained with {LINKS.nrql_engine_repo} "
            f"(planned future home: {LINKS.nrql_engine_future_org})."
        )
    return f"Compiler parity maintained with {LINKS.nrql_engine_repo}."
