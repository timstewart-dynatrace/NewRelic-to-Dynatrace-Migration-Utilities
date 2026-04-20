"""
Alert Transformer — Gen3 target.

Converts New Relic alert policies + conditions to Dynatrace Gen3 objects:

  NR Alert Policy       -> DT Automation Workflow (one per policy)
  NR NRQL Condition     -> DT Davis Anomaly Detector (builtin:davis.anomaly-detectors)
                           + Workflow trigger on the detector's Davis event
  NR Notification Ch.   -> Workflow action task (email / slack / webhook /
                           pagerduty via dynatrace.pagerduty connector)

The workflow's `trigger.event.config.davis_event` block filters Davis events
emitted by the anomaly detectors produced from the policy's conditions. All
routing happens through Workflow task nodes — no Alerting Profile, no Problem
Notification, no Config-v1 Metric Event.

Legacy (Gen2) behavior is preserved in
`transformers/legacy/alert_transformer_v1.py` and reached via `--legacy`.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

from ._workflow_utils import tasks_list_to_dict
from .mapping_rules import OPERATOR_MAP, EntityMapper

logger = structlog.get_logger()


@dataclass
class AlertTransformResult:
    """Result of alert transformation (Gen3)."""

    success: bool
    workflow: Optional[Dict[str, Any]] = None
    anomaly_detectors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class AlertTransformer:
    """Transforms NR alert policies/conditions to DT Workflows + Davis Anomaly Detectors."""

    def __init__(self) -> None:
        self.mapper = EntityMapper()

    def transform(self, nr_policy: Dict[str, Any]) -> AlertTransformResult:
        """Transform a single NR alert policy into Gen3 payloads."""
        warnings: List[str] = []
        errors: List[str] = []

        try:
            policy_name = nr_policy.get("name", "Unnamed Policy")
            policy_id = str(nr_policy.get("id", ""))
            conditions = nr_policy.get("conditions", []) or []

            anomaly_detectors: List[Dict[str, Any]] = []
            detector_ids: List[str] = []

            for condition in conditions:
                det = self._build_anomaly_detector(condition, policy_name, warnings)
                if det is None:
                    continue
                anomaly_detectors.append(det)
                detector_ids.append(det["detectorId"])

            # Phase 25: detect severity-ladder delays → fan out Workflows.
            severity_rules = nr_policy.get("severityRules", []) or []
            workflows = self._build_workflows(
                policy_name=policy_name,
                policy_id=policy_id,
                detector_ids=detector_ids,
                notifications=nr_policy.get("notificationChannels", []) or [],
                severity_rules=severity_rules,
                warnings=warnings,
            )
            # Backward compat: `.workflow` is the first (or only) Workflow;
            # `.all_workflows` carries the full list when fanout occurred.
            workflow = workflows[0]

            logger.info(
                "Transformed alert policy to Gen3",
                policy=policy_name,
                detectors=len(anomaly_detectors),
                workflows=len(workflows),
            )

            return AlertTransformResult(
                success=True,
                workflow=workflow,
                anomaly_detectors=anomaly_detectors,
                warnings=warnings,
                errors=errors,
            )

        except Exception as exc:  # noqa: BLE001 — surfaced via result
            logger.error("Alert policy transformation failed", error=str(exc))
            return AlertTransformResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    # ------------------------------------------------------------------
    # Davis Anomaly Detector (builtin:davis.anomaly-detectors)
    # ------------------------------------------------------------------

    def _build_anomaly_detector(
        self,
        condition: Dict[str, Any],
        policy_name: str,
        warnings: List[str],
    ) -> Optional[Dict[str, Any]]:
        condition_type = condition.get("conditionType", "NRQL")
        condition_name = condition.get("name", "Unnamed Condition")
        description = condition.get("description", "")
        enabled = bool(condition.get("enabled", True))

        if condition_type != "NRQL":
            warnings.append(
                f"Condition type '{condition_type}' for '{condition_name}' "
                "requires manual review; emitted a disabled detector skeleton."
            )
            enabled = False

        nrql = condition.get("nrql", {}) or {}
        query = nrql.get("query", "")
        terms = condition.get("terms", []) or []
        signal = condition.get("signal", {}) or {}
        aggregation_window = int(signal.get("aggregationWindow", 60))

        threshold, operator_dt, samples, violating = self._resolve_threshold(terms)

        detector_id = f"davis-detector-{policy_name}-{condition_name}".lower().replace(
            " ", "-"
        )[:180]

        detector: Dict[str, Any] = {
            "schemaId": "builtin:davis.anomaly-detectors",
            "scope": "environment",
            "detectorId": detector_id,
            "value": {
                "name": f"[Migrated] {condition_name}",
                "description": description
                or f"Migrated from New Relic policy '{policy_name}'. Original NRQL: {query[:200]}",
                "enabled": enabled,
                "source": {
                    "type": "DQL",
                    # Post-processing (NRQLtoDQLConverter) fills this when invoked
                    # from the orchestrator; we keep the raw NRQL as a reference field.
                    "query": "",
                    "originalNRQL": query,
                    "evaluationWindow": f"{aggregation_window}s",
                },
                "strategy": {
                    "type": "STATIC_THRESHOLD",
                    "threshold": threshold,
                    "alertCondition": operator_dt,
                    "samples": samples,
                    "violatingSamples": violating,
                    "dealingWithGapsStrategy": "DROP_DATA",
                    "alertOnNoData": False,
                },
                "eventTemplate": {
                    "title": f"[Migrated] {condition_name}",
                    "description": description or condition_name,
                    "eventType": "CUSTOM_ALERT",
                    "davisMerge": True,
                    "properties": [
                        {"key": "source.policy", "value": policy_name},
                        {"key": "source.condition", "value": condition_name},
                        {"key": "migrated.from", "value": "newrelic"},
                    ],
                },
            },
        }

        runbook_url = condition.get("runbookUrl")
        if runbook_url:
            detector["value"]["eventTemplate"]["properties"].append(
                {"key": "runbook.url", "value": runbook_url}
            )

        return detector

    @staticmethod
    def _resolve_threshold(terms: List[Dict[str, Any]]):
        """Pick the critical term (fallback: warning) and translate to DT fields."""
        operator_dt = "ABOVE"
        threshold = 0.0
        samples = 3
        violating = 3

        if not terms:
            return threshold, operator_dt, samples, violating

        critical = next(
            (t for t in terms if str(t.get("priority", "")).lower() == "critical"),
            None,
        )
        warning = next(
            (t for t in terms if str(t.get("priority", "")).lower() == "warning"),
            None,
        )
        active = critical or warning or terms[0]

        operator_dt = OPERATOR_MAP.get(active.get("operator", "ABOVE"), "ABOVE")
        threshold = float(active.get("threshold", 0))
        duration_seconds = int(active.get("thresholdDuration", 300))
        samples = max(1, duration_seconds // 60)
        violating = samples
        if active.get("thresholdOccurrences") == "AT_LEAST_ONCE":
            violating = 1
        return threshold, operator_dt, samples, violating

    # ------------------------------------------------------------------
    # Automation Workflow (platform/automation/v1/workflows)
    # ------------------------------------------------------------------

    # Phase 25 — per-severity delay-ladder detection. NR policies
    # sometimes carry explicit severityRules with different delays:
    #   [{"severity":"AVAILABILITY","delayMinutes":0},
    #    {"severity":"ERROR","delayMinutes":5}, ...]
    # When the delays are non-uniform, fan out one Workflow per severity
    # so each can carry its own delay (via a pre-step sleep node). When
    # all delays are the same (the common case), emit a single Workflow.
    _SEVERITY_LEVELS = [
        "AVAILABILITY", "ERROR", "PERFORMANCE",
        "RESOURCE_CONTENTION", "CUSTOM_ALERT",
    ]

    def _build_workflows(
        self,
        policy_name: str,
        policy_id: str,
        detector_ids: List[str],
        notifications: List[Dict[str, Any]],
        severity_rules: List[Dict[str, Any]],
        warnings: List[str],
    ) -> List[Dict[str, Any]]:
        """Build one or more Workflows for a policy.

        Phase 25: when severity_rules carry non-uniform delays, emit
        one Workflow per severity level. Otherwise, emit a single Workflow.
        """
        delays = {
            str(r.get("severity", r.get("severityLevel", ""))).upper():
            int(r.get("delayMinutes", r.get("delayInMinutes", 0)))
            for r in severity_rules
        }
        unique_delays = set(delays.values())
        if len(unique_delays) <= 1 or not severity_rules:
            return [self._build_single_workflow(
                policy_name, policy_id, detector_ids, notifications,
                None, warnings,
            )]

        workflows: List[Dict[str, Any]] = []
        for severity, delay in delays.items():
            wf = self._build_single_workflow(
                policy_name=f"{policy_name} [{severity}]",
                policy_id=policy_id,
                detector_ids=detector_ids,
                notifications=notifications,
                severity_filter=severity,
                warnings=warnings,
                delay_minutes=delay,
            )
            wf["migratedFrom"] = {
                "type": "newrelic.severity_ladder",
                "severity": severity,
                "delayMinutes": delay,
            }
            workflows.append(wf)
        warnings.append(
            f"Policy '{policy_name}' has non-uniform severity delays "
            f"({delays}). Emitting {len(workflows)} Workflows "
            "(one per severity) — Phase 25 severity-ladder fanout."
        )
        return workflows

    def _build_single_workflow(
        self,
        policy_name: str,
        policy_id: str,
        detector_ids: List[str],
        notifications: List[Dict[str, Any]],
        severity_filter: Optional[str],
        warnings: List[str],
        delay_minutes: int = 0,
    ) -> Dict[str, Any]:
        tasks = self._build_notification_tasks(notifications, warnings)

        if delay_minutes > 0:
            tasks.insert(0, {
                "name": f"delay_{delay_minutes}m",
                "action": "dynatrace.automations:run-javascript",
                "active": True,
                "description": f"Pre-notification delay of {delay_minutes} minutes (migrated from NR severity ladder).",
                "input": {
                    "script": f"export default async () => {{ await new Promise(r => setTimeout(r, {delay_minutes * 60_000})); return {{ ok: true }}; }};",
                },
                "position": {"x": 0, "y": 0},
            })

        if not tasks:
            tasks.append(
                {
                    "name": "placeholder_action",
                    "action": "dynatrace.automations:run-javascript",
                    "active": False,
                    "description": "No NR notification channels attached to the policy — add an action.",
                    "input": {"script": "export default () => ({ ok: true });"},
                    "position": {"x": 0, "y": 1},
                }
            )

        trigger_config: Dict[str, Any] = {
            "eventType": "CUSTOM_ALERT",
            "detectorIds": detector_ids,
            "anyEventMatches": True,
        }
        if severity_filter:
            trigger_config["eventProperties"] = {
                "event.severity": severity_filter,
            }

        return {
            "title": f"[Migrated] {policy_name}",
            "description": (
                f"Migrated from New Relic alert policy '{policy_name}' (id={policy_id})."
            ),
            "private": False,
            "isPrivate": False,
            "trigger": {
                "event": {
                    "active": True,
                    "config": {"davis_event": trigger_config},
                }
            },
            # Gen3 Automation API requires `tasks` as a dict keyed by task id.
            "tasks": tasks_list_to_dict(tasks),
        }

    def _build_notification_tasks(
        self, channels: List[Dict[str, Any]], warnings: List[str]
    ) -> List[Dict[str, Any]]:
        nt = NotificationTransformer()
        tasks: List[Dict[str, Any]] = []
        for idx, channel in enumerate(channels):
            result = nt.transform(channel)
            if not result.success or result.task is None:
                warnings.extend(result.errors or result.warnings or [])
                continue
            task = dict(result.task)
            task["position"] = {"x": 0, "y": idx + 1}
            tasks.append(task)
            warnings.extend(result.warnings or [])
        return tasks

    # ------------------------------------------------------------------
    # Batch
    # ------------------------------------------------------------------

    def transform_all(
        self, policies: List[Dict[str, Any]]
    ) -> List[AlertTransformResult]:
        results = [self.transform(p) for p in policies]
        successful = sum(1 for r in results if r.success)
        detectors = sum(len(r.anomaly_detectors) for r in results)
        logger.info(
            f"Transformed {successful}/{len(results)} policies to Gen3; "
            f"{detectors} anomaly detectors created"
        )
        return results


# ---------------------------------------------------------------------------
# NotificationTransformer — emits Workflow action tasks (Gen3)
# ---------------------------------------------------------------------------


@dataclass
class NotificationTransformResult:
    """Result of notification channel -> Workflow task translation."""

    success: bool
    task: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class NotificationTransformer:
    """Translate NR notification channels into Workflow action task definitions.

    Each channel becomes a single task node inside the parent Workflow. The
    Workflow's Davis-event trigger fires the task when a detector alerts.
    """

    _TITLE = "[Migrated] Davis event: {{ event()['event.name'] }}"
    _BODY = (
        "Policy: {{ event()['source.policy'] }}\n"
        "Condition: {{ event()['source.condition'] }}\n"
        "Severity: {{ event()['event.severity'] }}\n"
        "Status: {{ event()['event.status'] }}\n"
        "URL: {{ event()['event.url'] }}"
    )

    def transform(self, nr_channel: Dict[str, Any]) -> NotificationTransformResult:
        channel_type = str(nr_channel.get("type", "")).upper()
        channel_name = nr_channel.get("name", "Unknown Channel")
        properties = {
            p["key"]: p["value"] for p in nr_channel.get("properties", []) or []
        }

        if channel_type == "EMAIL":
            return self._email(nr_channel, channel_name, properties)
        if channel_type == "SLACK":
            return self._slack(nr_channel, channel_name, properties)
        if channel_type == "PAGERDUTY":
            return self._pagerduty(nr_channel, channel_name, properties)
        if channel_type == "WEBHOOK":
            return self._webhook(nr_channel, channel_name, properties)

        return NotificationTransformResult(
            success=False,
            errors=[
                f"Notification type '{channel_type}' for '{channel_name}' "
                "has no Gen3 Workflow mapping — add a custom action task."
            ],
        )

    def _email(self, channel, name, props) -> NotificationTransformResult:
        recipients = [r.strip() for r in str(props.get("recipients", "")).split(",") if r.strip()]
        return NotificationTransformResult(
            success=True,
            task={
                "name": f"email_{self._slug(name)}",
                "action": "dynatrace.email:email-action",
                "active": bool(channel.get("active", True)),
                "description": f"Migrated email channel: {name}",
                "input": {
                    "to": recipients,
                    "subject": self._TITLE,
                    "body": self._BODY,
                },
            },
        )

    def _slack(self, channel, name, props) -> NotificationTransformResult:
        return NotificationTransformResult(
            success=True,
            task={
                "name": f"slack_{self._slug(name)}",
                "action": "dynatrace.slack:slack-send-message",
                "active": bool(channel.get("active", True)),
                "description": f"Migrated Slack channel: {name}",
                "input": {
                    "channel": props.get("channel", ""),
                    "message": self._BODY,
                    "connectionId": "",
                },
            },
            warnings=[
                "Slack connector requires a Dynatrace Slack connection ID — "
                "replace the empty connectionId after import."
            ],
        )

    def _pagerduty(self, channel, name, props) -> NotificationTransformResult:
        return NotificationTransformResult(
            success=True,
            task={
                "name": f"pagerduty_{self._slug(name)}",
                "action": "dynatrace.pagerduty:trigger-incident",
                "active": bool(channel.get("active", True)),
                "description": f"Migrated PagerDuty channel: {name}",
                "input": {
                    "integrationKey": props.get("service_key", ""),
                    "summary": self._TITLE,
                    "severity": "critical",
                },
            },
            warnings=[
                "PagerDuty integration key may need to be regenerated in Dynatrace."
            ],
        )

    def _webhook(self, channel, name, props) -> NotificationTransformResult:
        return NotificationTransformResult(
            success=True,
            task={
                "name": f"webhook_{self._slug(name)}",
                "action": "dynatrace.automations:http-function",
                "active": bool(channel.get("active", True)),
                "description": f"Migrated webhook channel: {name}",
                "input": {
                    "method": "POST",
                    "url": props.get("base_url", ""),
                    "headers": [{"key": "Content-Type", "value": "application/json"}],
                    "body": (
                        '{"title":"{{ event()["event.name"] }}",'
                        '"severity":"{{ event()["event.severity"] }}",'
                        '"policy":"{{ event()["source.policy"] }}"}'
                    ),
                },
            },
            warnings=[
                "Webhook payload/headers may need adjustment for the receiver's schema."
            ],
        )

    @staticmethod
    def _slug(text: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")[:60]
