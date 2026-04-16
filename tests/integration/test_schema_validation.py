"""Phase 26 Tier 1 — static schema validation.

Validates every transformer's emitted Settings 2.0 envelopes against
the cached DT JSON schemas in `tests/fixtures/dt-schemas/`.

Gated on `RUN_SCHEMA_VALIDATION=1` because the fixtures must be
populated first via `scripts/fetch_dt_schemas.py`.

If the fixtures are empty, every test is skipped with a message.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "dt-schemas"
INDEX_FILE = FIXTURE_DIR / "index.json"

skip_reason = "RUN_SCHEMA_VALIDATION=1 not set or schema fixtures missing"
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_SCHEMA_VALIDATION") or not INDEX_FILE.exists(),
    reason=skip_reason,
)


@pytest.fixture(scope="session")
def schemas() -> Dict[str, Any]:
    if not INDEX_FILE.exists():
        pytest.skip("No index.json — run scripts/fetch_dt_schemas.py first")
    index = json.loads(INDEX_FILE.read_text())
    out: Dict[str, Any] = {}
    for schema_id, fname in index.items():
        path = FIXTURE_DIR / fname
        if path.exists():
            out[schema_id] = json.loads(path.read_text())
    return out


def _validate_envelope(envelope: Dict[str, Any], schemas: Dict[str, Any]):
    """Validate a single {schemaId, scope, value} envelope."""
    import jsonschema

    schema_id = envelope.get("schemaId", "")
    if schema_id not in schemas:
        pytest.skip(f"Schema {schema_id} not cached — fetch it first")
    dt_schema = schemas[schema_id]
    # DT schema API returns the full schema definition under various keys;
    # try `properties` top-level, or the raw JSON schema under `schema`/`schemaConstraints`.
    json_schema = dt_schema.get("schema") or dt_schema
    try:
        jsonschema.validate(instance=envelope.get("value", {}), schema=json_schema)
    except jsonschema.ValidationError as e:
        pytest.fail(f"Schema validation failed for {schema_id}:\n{e.message}")


# One test per transformer that emits Settings 2.0 envelopes.

def test_alert_transformer_schema(schemas):
    from transformers.alert_transformer import AlertTransformer
    r = AlertTransformer().transform({
        "name": "p", "id": 1,
        "conditions": [{"conditionType": "NRQL", "name": "c", "enabled": True,
                         "nrql": {"query": "SELECT count(*) FROM Transaction"},
                         "terms": [{"priority": "critical", "operator": "ABOVE", "threshold": 1}]}],
        "notificationChannels": [],
    })
    for det in r.anomaly_detectors:
        _validate_envelope(det, schemas)


def test_workload_transformer_schema(schemas):
    from transformers.workload_transformer import WorkloadTransformer
    r = WorkloadTransformer().transform({
        "name": "prod", "collection": [{"type": "HOST", "name": "h1"}],
    })
    _validate_envelope(r.segment, schemas)
    _validate_envelope(r.iam_policy, schemas)


def test_slo_transformer_schema(schemas):
    from transformers.slo_transformer import SLOTransformer
    r = SLOTransformer().transform({
        "name": "svc-slo",
        "objectives": [{"target": 99.9, "timeWindow": {"rolling": {"count": 7, "unit": "DAY"}}}],
        "events": {"validEvents": {"where": "status = 200"}},
    })
    _validate_envelope(r.slo, schemas)


def test_tag_transformer_schema(schemas):
    from transformers.tag_transformer import TagTransformer
    r = TagTransformer().transform({
        "name": "svc", "type": "APM_APPLICATION",
        "tags": [{"key": "env", "values": ["prod"]}],
    })
    for proc in r.enrichment_processors:
        _validate_envelope(proc, schemas)
