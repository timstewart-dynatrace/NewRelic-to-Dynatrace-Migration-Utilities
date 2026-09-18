"""Shared helpers for Gen3 Platform SLO emission (`/platform/slo/v1/slos`).

Platform SLOs carry a DQL indicator (`customSli.indicator`) that must produce
an `sli` field (array of doubles, percent). Used by `SLOTransformer`,
`KeyTransactionTransformer`, and `NRQLtoDQLConverter` so all three emit the
same shape.

Payload shape verified against the Dynatrace SLO SDK, the Terraform
`dynatrace_platform_slo` resource, and Monaco `slo-v2` test fixtures.
"""

from typing import Any, Dict, List, Optional

DEFAULT_LATENCY_THRESHOLD_MS = 1000


def default_warning(target: float) -> float:
    """Platform SLO warning sits between target and 100 (warning > target)."""
    return round(min(target + (100 - target) / 2, 99.99), 2)


def _service_scope(service_name: Optional[str]) -> str:
    step = "\n| fieldsAdd entityName = getNodeName(dt.smartscape.service)"
    if service_name:
        escaped = service_name.replace('"', '\\"')
        step += f'\n| filter contains(entityName, "{escaped}")'
    return step


def availability_indicator(service_name: Optional[str] = None) -> str:
    """Service success-rate SLI (non-failed requests / all requests)."""
    return (
        "timeseries {\n"
        "  total=sum(dt.service.request.count),\n"
        "  failures=sum(dt.service.request.failure_count)\n"
        f"}}, by: {{ dt.smartscape.service }}{_service_scope(service_name)}\n"
        "| fieldsAdd sli=(((total[]-failures[])/total[])*(100))\n"
        "| fieldsRemove total, failures"
    )


def latency_indicator(
    threshold_ms: int = DEFAULT_LATENCY_THRESHOLD_MS, service_name: Optional[str] = None
) -> str:
    """Share of time buckets whose avg response time is within the threshold.

    `dt.service.request.response_time` is in microseconds.
    """
    threshold_us = int(threshold_ms) * 1000
    return (
        "timeseries total=avg(dt.service.request.response_time), default:0, "
        f"by: {{ dt.smartscape.service }}{_service_scope(service_name)}\n"
        f"| fieldsAdd high=iCollectArray(if(total[] > {threshold_us}, total[]))\n"
        f"| fieldsAdd low=iCollectArray(if(total[] <= {threshold_us}, total[]))\n"
        "| fieldsAdd highRespTimes=iCollectArray(if(isNull(high[]), 0, else: 1))\n"
        "| fieldsAdd lowRespTimes=iCollectArray(if(isNull(low[]), 0, else: 1))\n"
        "| fieldsAdd sli=100*(lowRespTimes[]/(lowRespTimes[]+highRespTimes[]))\n"
        "| fieldsRemove total, high, low, highRespTimes, lowRespTimes"
    )


def build_platform_slo(
    name: str,
    description: str,
    target: float,
    indicator: str,
    timeframe_from: str = "now-7d",
    warning: Optional[float] = None,
    tags: Optional[List[str]] = None,
    external_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Platform SLO API request body."""
    slo: Dict[str, Any] = {
        "name": name,
        "description": description[:1000],
        "criteria": [
            {
                "target": target,
                "warning": default_warning(target) if warning is None else warning,
                "timeframeFrom": timeframe_from,
                "timeframeTo": "now",
            }
        ],
        "customSli": {"indicator": indicator},
        "tags": list(tags or []),
    }
    if external_id:
        slo["externalId"] = external_id
    return slo
