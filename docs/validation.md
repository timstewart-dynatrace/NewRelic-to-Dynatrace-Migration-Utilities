# Validation Strategy

> **Last updated:** 2026-04-15 (post-Phase-24 + 3rd-pass parity)
> **Companion:** `docs/COVERAGE.md`, `docs/architecture.md`

This project ships **1201 unit + 8 integration tests** that pin
*structural correctness* — every transformer's output matches a
hand-authored expected shape. That proves the code emits what we
believe is correct; it does **not** prove the emitted artifacts are
**actually accepted** by Dynatrace, that the DQL **executes**, or
that the Terraform / Monaco output **applies cleanly**.

This document catalogs six validation tiers, each closing a different
class of correctness gap. Tiers can run independently; pick the ones
that match your risk tolerance + available budget.

## Tier 1 — Static schema validation against published DT schemas

**Closes:** drift between our hand-authored envelopes and the live
Settings 2.0 schema definitions (which evolve).

**How:** Pull every `builtin:*` schema we emit from a DT tenant at
`/api/v2/settings/schemas/<schemaId>`, cache them under
`tests/fixtures/dt-schemas/`, and validate every transformer's
envelope `value` against the cached JSON schema using `jsonschema`.

**Implementation sketch:**

```python
# tests/integration/test_schema_validation.py
import json, jsonschema
from pathlib import Path
from transformers import AlertTransformer, KubernetesTransformer, ...

SCHEMAS = json.loads(Path("tests/fixtures/dt-schemas/index.json").read_text())

def _validate(envelope):
    schema = SCHEMAS[envelope["schemaId"]]
    jsonschema.validate(instance=envelope["value"], schema=schema)

def test_alert_transformer_passes_schema():
    r = AlertTransformer().transform({...})
    for det in r.anomaly_detectors:
        _validate(det)
```

**Cost:** ~4h to write the harness + cache the ~25 schemas we touch.
Runs in CI behind `RUN_SCHEMA_VALIDATION=1`.

**Caveat:** Schemas vary by DT version. Cache from production-stable
tenants only; record the version next to each schema.

## Tier 2 — Compiler differential testing vs `nrql-engine`

**Closes:** silent drift between the Python compiler and the TS
sibling. Phase 19b pins shorthand expansion + K8s overrides + fixer
method coverage, but doesn't compare actual NRQL→DQL output.

**How:** A test runner that:
1. Reads each NRQL pattern from the 292-pattern fixture.
2. Compiles via Python `NRQLCompiler.compile(nrql)`.
3. Compiles via TS `NRQLCompiler.compile(nrql)` through
   `subprocess.run(["npx", "tsx", "scripts/run-ts-compiler.ts", nrql])`.
4. Asserts the two DQL strings are equal (or at least confidence-band
   equal — exact equality is aspirational; semantic equivalence via
   tokenization may be the realistic target).

**Implementation sketch:**

```python
# tests/integration/test_compiler_differential.py
import subprocess, json, pytest

@pytest.fixture(scope="session")
def ts_compile():
    def _run(nrql):
        out = subprocess.run(
            ["npx", "tsx",
             "/Users/Shared/GitHub/PROJECTS/nrql-engine/scripts/compile-one.ts"],
            input=nrql, capture_output=True, text=True, check=True,
        )
        return json.loads(out.stdout)
    return _run

@pytest.mark.parametrize("nrql", load_corpus())
def test_python_ts_compiler_agree(nrql, ts_compile):
    py = NRQLCompiler().compile(nrql)
    ts = ts_compile(nrql)
    assert py.dql.strip() == ts["dql"].strip(), (
        f"NRQL: {nrql}\nPY:  {py.dql}\nTS:  {ts['dql']}"
    )
```

**Cost:** ~6h to write `compile-one.ts` in the sibling repo + the
runner here. **Requires the sibling repo + node toolchain.**

**Caveat:** Whitespace / variable-name differences are common; start
with semantic comparison (parse both DQLs into ASTs and compare).

## Tier 3 — Terraform & Monaco dry-run on emitted output

**Closes:** generated IaC that parses but won't apply.

**How:** A test that:
1. Runs every transformer on a fixture export.
2. Pipes the result through `exporters/terraform.py` and `exporters/monaco.py`.
3. Shells out to `terraform validate` and `monaco deploy --dry-run` against the temp directory.

**Implementation sketch:**

```python
# tests/integration/test_iac_validates.py
import subprocess, tempfile
from pathlib import Path
from exporters import TerraformExporter, MonacoExporter

def test_terraform_validates(tmp_path, gen3_fixture):
    TerraformExporter().export(gen3_fixture, tmp_path)
    subprocess.run(["terraform", "init", "-backend=false"], cwd=tmp_path, check=True)
    subprocess.run(["terraform", "validate"], cwd=tmp_path, check=True)

def test_monaco_dry_run(tmp_path, gen3_fixture):
    MonacoExporter().export(gen3_fixture, tmp_path)
    subprocess.run(["monaco", "deploy", "--dry-run", "--manifest", tmp_path / "manifest.yaml"], check=True)
```

**Cost:** ~3h. **Requires** `terraform` and `monaco` CLIs installed
in CI.

**Caveat:** `terraform validate` needs the provider plugin; cache it
in the GHA runner.

## Tier 4 — Live DQL execution against a real tenant

**Closes:** DQL that's syntactically valid but references metrics /
attributes that don't exist on the target tenant, or uses a function
combination DT rejects at runtime.

**How:** For every dashboard tile / Davis detector / SLO metric
expression, POST the DQL to
`/platform/storage/query/v1/query:execute` and assert the response
`state` is `SUCCEEDED` or `RUNNING` (not `FAILED`). Sample data is
fine — we're testing that the query parses + plans, not that data
exists.

**Implementation sketch:**

```python
# tests/integration/test_dql_executes.py
import os, requests, pytest

@pytest.mark.skipif(not os.getenv("DT_API_TOKEN"), reason="needs token")
@pytest.mark.parametrize("dql", collect_emitted_dqls())
def test_dql_executes_without_failure(dql):
    r = requests.post(
        f"{os.environ['DT_URL']}/platform/storage/query/v1/query:execute",
        headers={"Authorization": f"Api-Token {os.environ['DT_API_TOKEN']}"},
        json={"query": dql, "requestTimeoutMilliseconds": 10000},
        timeout=15,
    )
    assert r.status_code == 200, dql
    assert r.json().get("state") != "FAILED", r.json()
```

**Cost:** ~2h. Token must have `storage:*:read` scopes.

**Caveat:** Throws away rate-limit budget; gate on a label like
`run-live-dql=1`.

## Tier 5 — Throwaway-tenant round-trip

**Closes:** envelopes that schema-validate but reject when actually
POSTed (auth scopes, tenant-feature flags, scope='environment'
restrictions).

**How:** Provision a sandbox DT tenant; for every entity type, run
the full **create → read → delete** cycle; assert each step returns 2xx.
Phase 20's `migration/audit.py` is the read-side of this; the new
test would just exercise it end-to-end.

**Implementation sketch:**

```python
# tests/integration/test_throwaway_round_trip.py
@pytest.mark.skipif(not os.getenv("DT_THROWAWAY_TENANT"), reason="needs sandbox")
def test_anomaly_detector_round_trip():
    env = AlertTransformer().transform(NR_FIXTURE).anomaly_detectors[0]
    create_result = dt_client.create_anomaly_detector(env)
    assert create_result.success

    fetched = dt_client.settings.list_objects(env["schemaId"])
    assert any(o["objectId"] == create_result.dynatrace_id for o in fetched)

    delete_result = dt_client.delete_entity("anomaly_detector", create_result.dynatrace_id)
    assert delete_result.success
```

**Cost:** ~8h harness + ongoing tenant cost (a few $$/month for a
small Grail tenant).

**Caveat:** Tests run sequentially against shared tenant state;
serialize with `pytest-xdist -n 1` or per-test namespace prefixes.

## Tier 6 — Property-based / fuzz testing

**Closes:** unhandled input shapes that no human thought to write a
test for.

**How:** Hypothesis strategies that generate plausible NR exports
(random alert policy with 0–10 conditions, random dashboard with
0–50 widgets, etc.); assert these invariants on every output:

- Never raises an unhandled exception
- Result is JSON-serializable
- Every emitted envelope has `schemaId` + `scope` + `value`
- No emitted envelope's `schemaId` is a Gen2 schema (in default mode)
- All `confidence_score` values are in [0, 100]
- All warning strings are non-empty

**Implementation sketch:**

```python
# tests/unit/test_invariants.py
from hypothesis import given, strategies as st

@given(st.dictionaries(st.sampled_from(["name","conditions","notificationChannels"]), st.text()))
def test_alert_transform_never_raises(nr_policy):
    r = AlertTransformer().transform(nr_policy)
    assert r.success or r.errors
    assert json.dumps(r.workflow) is not None  # serializable
```

**Cost:** ~4h to write strategies for the major transformers.

## Other validation hardenings

### Tighten `mypy` to strict mode

Current `pyproject.toml` has `disallow_untyped_defs = false`. Set to
`true` and fix the resulting errors. Catches a class of bugs unit
tests miss (wrong return type, optional fields not handled).

### Coverage threshold uplift

`--cov-fail-under=80` is enforced today. Generate `--cov-report=html`
and audit the uncovered branches; raise to 90% incrementally as the
gaps close.

### Snapshot testing

For each transformer, store a hand-crafted real NR export under
`tests/fixtures/nr-exports/` and a corresponding expected DT output
under `tests/fixtures/dt-expected/`. Use `syrupy` or similar to assert
exact-string equality. Catches **unexpected output changes** when a
transformer is refactored.

### Real-customer pilot

Pick one consenting customer, run the full migration in dry-run mode
against their NR account → DT sandbox tenant pair, hand-review the
output. The single best validation step there is.

## Recommended execution order

1. **T1 (schema validation)** — biggest confidence ROI for the time
2. **T6 (property-based)** — catches the long tail
3. **mypy --strict** — type safety
4. **T3 (Terraform / Monaco dry-run)** — catches IaC silliness
5. **T4 (live DQL)** — when you have a tenant
6. **T2 (compiler differential)** — when nrql-engine has compatible CLI
7. **T5 (throwaway-tenant round-trip)** — full end-to-end, when budget allows

Phases 16–24 + 19b + 3rd-pass shipped without these tiers; the
existing 1201 unit tests caught regressions during execution. **The
above is the next layer of confidence**, not a precondition for
shipping. Tiers 1, 3, 6 + `mypy --strict` are the minimum for a v2.0.0
production release.

Tracked in `.claude/phases/PHASE-26-pending.md`.
