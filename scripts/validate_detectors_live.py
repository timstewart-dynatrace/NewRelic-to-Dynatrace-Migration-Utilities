"""Validate every detector emitter's output against a live tenant — without creating anything.

Runs each transformer on representative NR inputs and submits the resulting
builtin:davis.anomaly-detectors value to `dtctl create settings --validate-only`.
Requires `dtctl` logged in to the target tenant and DYNATRACE_DETECTOR_ACTOR set to a
service-user UUID on that tenant. Exit code 1 if any payload is rejected.

    DYNATRACE_DETECTOR_ACTOR=<uuid> PYTHONPATH=. python scripts/validate_detectors_live.py

See docs/live-validation-2026-09.md.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

from clients._detector_actor import with_detector_actor
from transformers.aiops_transformer import AIOpsTransformer
from transformers.alert_transformer import AlertTransformer
from transformers.baseline_alert_transformer import BaselineAlertTransformer
from transformers.infrastructure_transformer import InfrastructureTransformer
from transformers.non_nrql_alert_transformer import _CONDITION_METRIC_MAP, NonNRQLAlertTransformer


def main() -> int:
    actor = os.environ.get("DYNATRACE_DETECTOR_ACTOR")
    if not actor:
        print("DYNATRACE_DETECTOR_ACTOR must be set to a service-user UUID", file=sys.stderr)
        return 2
    dets = []
    dets += [("alert", d) for d in AlertTransformer().transform({"name":"[nr-migration-test] p","conditions":[{"name":"err","nrql":{"query":"SELECT percentage(count(*), WHERE error IS true) FROM Transaction WHERE appName='frontend'"}}]}).anomaly_detectors]
    dets += [("alert:terms", d) for d in AlertTransformer().transform({"name":"[nr-migration-test] p2","conditions":[{"name":"lat","nrql":{"query":"SELECT average(duration) FROM Transaction FACET appName"},"terms":[{"threshold":2,"operator":"ABOVE","priority":"critical","thresholdDuration":600,"thresholdOccurrences":"AT_LEAST_ONCE"}]}]}).anomaly_detectors]
    for ct in _CONDITION_METRIC_MAP: dets += [(f"nonnrql:{ct}", d) for d in NonNRQLAlertTransformer().transform({"type":ct,"name":f"[nr-migration-test] {ct}"}).anomaly_detectors]
    for c in ({"type":"host_not_reporting","name":"[nr-migration-test] h"},{"type":"process_not_running","name":"[nr-migration-test] p"},{"type":"infra_metric","name":"[nr-migration-test] m","select_value":"diskUsedPercent","criticalThreshold":{"value":90,"durationMinutes":2}}):
        dets += [(f"infra:{c['type']}", d) for d in InfrastructureTransformer().transform(c).anomaly_detectors]
    dets += [("baseline", d) for d in BaselineAlertTransformer().transform({"name":"[nr-migration-test] b","conditionType":"baseline","nrql":{"query":"SELECT average(duration) FROM Transaction"}}).anomaly_detectors]
    dets += [("outlier", d) for d in BaselineAlertTransformer().transform({"name":"[nr-migration-test] o","conditionType":"outlier","nrql":{"query":"SELECT average(duration) FROM Transaction FACET appName"},"facet":"dt.service.name"}).anomaly_detectors]
    dets += [("aiops", d) for d in (AIOpsTransformer().transform({"anomalyDetectionSettings":[{"name":"[nr-migration-test] a","metricKey":"builtin:host.cpu.usage"}]}).anomaly_detectors or [])]
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        for label, det in dets:
            env = with_detector_actor(det, actor)
            env["value"]["enabled"] = False
            path = os.path.join(tmp, f"{label.replace(':', '_')}.json")
            with open(path, "w") as fh:
                json.dump(env["value"], fh)
            out = subprocess.run(
                ["dtctl", "create", "settings", "-f", path, "--schema", "builtin:davis.anomaly-detectors",
                 "--scope", "environment", "--validate-only", "-o", "json", "--plain", "--no-agent"],
                capture_output=True, text=True,
            )
            text = (out.stdout + out.stderr).strip()
            ok = "Validation passed" in text
            bad += not ok
            msgs = re.findall(r'\\"path\\":\\"([^\\]+)\\",\\"message\\":\\"([^\\]+)', text)
            print(f"{label:34s}", "VALID" if ok else f"INVALID {msgs or text[:200]}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
