"""
Legacy Error-Inbox Transformer (Gen2-only fallback).

Ported from nrql-engine `src/transformers/legacy-error-inbox.transformer.ts`.

NR Errors Inbox exposes per-occurrence state that has no Gen3 equivalent
— status (resolved / ignored / work-in-progress), threaded comments,
and assignees. Classic DT Problems expose comments and acknowledgement
endpoints, so this transformer emits a list of API **actions** (not a
single payload) the operator's CLI can batch-POST.

Reached only via `--legacy`. Gen3 tenants should skip this transformer
entirely; error-inbox state is considered non-migratable in the default
(Gen3) flow — see `docs/out-of-scope.md` §13.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


_NR_STATUS_TO_DT_ACTION = {
    "UNRESOLVED": None,  # no action on DT side
    "RESOLVED": "close",
    "IGNORED": "close",
    "WORK_IN_PROGRESS": "acknowledge",
}


@dataclass
class ErrorInboxResult:
    success: bool
    api_actions: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class LegacyErrorInboxTransformer:
    """NR Errors Inbox -> DT Problems API actions (Gen2 fallback)."""

    def transform(self, nr_record: Dict[str, Any]) -> ErrorInboxResult:
        warnings: List[str] = []
        errors: List[str] = []
        try:
            group_id = nr_record.get("errorGroupId", "")
            status = str(nr_record.get("status", "UNRESOLVED")).upper()
            comments = nr_record.get("comments") or []
            assignee = nr_record.get("assignee", "")
            problem_selector = nr_record.get(
                "dtProblemIdMatcher",
                f'problemFilter~"{group_id}"',
            )

            actions: List[Dict[str, Any]] = []

            # Comments — one POST per comment.
            for comment in comments:
                body = comment.get("body", "")
                author = comment.get("author", "migration")
                actions.append(
                    {
                        "method": "POST",
                        "endpoint": "/api/v2/problems/{problemId}/comments",
                        "problem_selector": problem_selector,
                        "body": {
                            "message": f"[Migrated from NR Errors Inbox by {author}] {body}",
                        },
                    }
                )

            # Status translation — DT problem close / ack.
            dt_action = _NR_STATUS_TO_DT_ACTION.get(status)
            if dt_action == "close":
                actions.append(
                    {
                        "method": "POST",
                        "endpoint": "/api/v2/problems/{problemId}/close",
                        "problem_selector": problem_selector,
                        "body": {"message": f"Closed during NR migration (status={status})"},
                    }
                )
            elif dt_action == "acknowledge":
                actions.append(
                    {
                        "method": "POST",
                        "endpoint": "/api/v2/problems/{problemId}/acknowledge",
                        "problem_selector": problem_selector,
                        "body": {"message": "WIP carried over from NR"},
                    }
                )

            # Assignee — DT has no problem assignee API; emit a warning.
            if assignee:
                warnings.append(
                    f"Assignee '{assignee}' for error group {group_id} cannot "
                    "migrate — DT problems have no assignee field. Tag the "
                    "problem's owning service via the workload IAM policy instead."
                )

            logger.info(
                "Transformed error-inbox record (legacy)",
                group_id=group_id,
                status=status,
                comment_count=len(comments),
            )
            return ErrorInboxResult(
                success=True, api_actions=actions, warnings=warnings
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Error-inbox transformation failed", error=str(exc))
            return ErrorInboxResult(
                success=False, errors=[f"Transformation error: {exc}"]
            )

    def transform_all(
        self, records: List[Dict[str, Any]]
    ) -> List[ErrorInboxResult]:
        return [self.transform(r) for r in records]
