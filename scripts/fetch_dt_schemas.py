#!/usr/bin/env python3
"""Fetch DT Settings 2.0 schemas for offline validation.

Usage:
    DT_URL=https://abc.live.dynatrace.com DT_API_TOKEN=dt0c01.xxx \\
        python scripts/fetch_dt_schemas.py

Caches every `builtin:*` schema this project emits into
`tests/fixtures/dt-schemas/` as `<schema-id>.json`. Creates an
`index.json` mapping schema-id → filename for the test harness.

Run once per DT version you want to pin against; commit the cached
files so CI can validate without a live tenant.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

SCHEMAS_WE_EMIT = [
    "builtin:davis.anomaly-detectors",
    "builtin:segment",
    "builtin:iam.policy",
    "builtin:monitoring.slo",
    "builtin:synthetic_test",
    "builtin:openpipeline.logs.pipelines",
    "builtin:openpipeline.events.pipelines",
    "builtin:openpipeline.metrics.pipelines",
    "builtin:cloud.aws",
    "builtin:cloud.azure",
    "builtin:cloud.gcp",
    "builtin:rum.web.app-config",
    "builtin:mobile-application",
    "builtin:deployment.maintenance",
    "builtin:appsec.vulnerability-alerting",
    "builtin:appsec.vulnerability-muting",
    "builtin:appsec.security-signals",
    "builtin:network.snmp-device",
    "builtin:network.netflow",
    "builtin:ai.observability.model",
    "builtin:statsd.metrics",
    "builtin:otel.ingest.metrics",
    "builtin:otel.ingest-mappings",
    "builtin:aws.metric-streams",
    "builtin:logmonitoring.log-storage-settings",
    "builtin:request-naming.request-naming-rules",
    "builtin:prometheus.exporter",
    "builtin:identity.saml",
    "builtin:iam.users",
    "builtin:iam.groups",
]

OUT = Path("tests/fixtures/dt-schemas")


def main():
    url = os.environ.get("DT_URL", "").rstrip("/")
    token = os.environ.get("DT_API_TOKEN", "")
    if not url or not token:
        print("Set DT_URL and DT_API_TOKEN", file=sys.stderr)
        sys.exit(1)

    OUT.mkdir(parents=True, exist_ok=True)
    index: dict[str, str] = {}
    errors = 0

    for schema_id in SCHEMAS_WE_EMIT:
        api = f"{url}/api/v2/settings/schemas/{schema_id}"
        resp = requests.get(
            api, headers={"Authorization": f"Api-Token {token}"}, timeout=30
        )
        if resp.status_code != 200:
            print(f"  SKIP {schema_id} ({resp.status_code})")
            errors += 1
            continue
        safe = schema_id.replace(":", "_").replace(".", "_")
        fname = f"{safe}.json"
        (OUT / fname).write_text(json.dumps(resp.json(), indent=2))
        index[schema_id] = fname
        print(f"  OK   {schema_id} -> {fname}")

    (OUT / "index.json").write_text(json.dumps(index, indent=2))
    (OUT / "README.md").write_text(
        f"# Cached DT Settings 2.0 schemas\n\n"
        f"Fetched from `{url}` via `scripts/fetch_dt_schemas.py`.\n"
        f"Count: {len(index)} / {len(SCHEMAS_WE_EMIT)} "
        f"({errors} errors).\n\n"
        "Re-run the script when pinning against a new DT version.\n"
    )
    print(f"\n{len(index)}/{len(SCHEMAS_WE_EMIT)} schemas cached; index at {OUT / 'index.json'}")


if __name__ == "__main__":
    main()
