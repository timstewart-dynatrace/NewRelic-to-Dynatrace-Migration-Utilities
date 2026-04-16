"""Legacy Dynatrace client — reached only via the `--legacy` CLI flag."""

from .config_v1_client import (
    DynatraceResponse,
    ImportResult,
    LegacyDynatraceV1Client,
)

__all__ = ["LegacyDynatraceV1Client", "DynatraceResponse", "ImportResult"]
