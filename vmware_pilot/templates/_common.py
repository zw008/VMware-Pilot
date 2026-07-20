"""Shared helpers for built-in workflow templates.

Imports and the ``parallel_group`` tagging helper used across the per-domain
template modules. Kept separate so the domain modules (vm, network, k8s, …)
can import it without a circular dependency on the package ``__init__``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from vmware_pilot.models import Workflow, WorkflowState, WorkflowStep, new_workflow_id

__all__ = [
    "Any",
    "Workflow",
    "WorkflowState",
    "WorkflowStep",
    "datetime",
    "new_workflow_id",
    "parallel_group",
    "timezone",
]


def parallel_group(group_id: str, steps: list[WorkflowStep]) -> list[WorkflowStep]:
    """Tag a list of steps as a parallel group.

    Steps in the same group share a non-empty ``group_id``. The dispatch
    contract treats them as independent — the AI agent may invoke their
    underlying skill+tool calls concurrently. They still preserve their
    declaration order in ``Workflow.steps``; ordering only matters when
    the group exits and subsequent steps reference results.

    Use this for read-only data gathering before reasoning steps:
    fetching alerts, metrics, and events from different skills can fire
    simultaneously, since none modify state.

    Args:
        group_id: A short stable identifier, e.g. ``"gather-symptoms"``.
        steps: The steps to tag. All step.group_id is set in place.

    Returns:
        The same list (for chaining convenience).
    """
    if not group_id:
        raise ValueError(
            f"group_id must be non-empty (got {group_id!r}). It is the tag that "
            "marks these steps as concurrently dispatchable — pass a short stable "
            "id such as 'gather-symptoms', or omit the parallel_group() call to "
            "leave the steps sequential. review_workflow groups steps by this id, "
            "so an empty tag would hide the group from its safety checks."
        )
    for s in steps:
        s.group_id = group_id
    return steps
