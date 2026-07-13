"""Structural review of a planned workflow.

Pure-function implementation so it is trivially testable. The MCP tool wrapper
in ``mcp_server/server.py`` just loads the workflow and calls ``review()``.
"""

from __future__ import annotations

from typing import Any

from vmware_pilot.models import Workflow

# Heuristic: any tool name containing one of these is "destructive".
# Aligns with the L3+ tier in capabilities.md across the family.
_DESTRUCTIVE_HINTS = (
    "delete",
    "remove",
    "destroy",
    "force_power_off",
    "shutdown",
    "drop",
    "rollback",
)

# Heuristic: tools that are read-only (L1/L2). Used for risk profile only.
_READONLY_HINTS = (
    "list",
    "get",
    "show",
    "browse",
    "scan",
    "status",
    "health",
    "fetch",
    "describe",
    "inspect",
)

# Common identifier-like param-name fragments — used to detect delete-then-use.
_ID_FRAGMENTS = ("name", "id", "vm", "segment", "rule", "policy")


def review(wf: Workflow) -> dict[str, Any]:
    """Sanity-check a planned workflow and return findings + summary.

    See docstring of ``mcp_server.server.review_workflow`` for behavior contract.
    """
    findings: list[dict[str, Any]] = []
    destructive_indices: list[int] = []
    readonly_indices: list[int] = []
    approval_indices: list[int] = []

    # resource_id -> earliest step index that deletes it
    deleted_resources: dict[str, int] = {}

    for step in wf.steps:
        tool_lc = step.tool.lower()
        action_lc = step.action.lower()

        if step.action == "require_approval":
            approval_indices.append(step.index)
            continue

        is_destructive = any(h in tool_lc or h in action_lc for h in _DESTRUCTIVE_HINTS)
        is_readonly = any(h in tool_lc for h in _READONLY_HINTS) and not is_destructive

        if is_destructive:
            destructive_indices.append(step.index)
            for k, v in step.params.items():
                if isinstance(v, str) and any(t in k.lower() for t in _ID_FRAGMENTS):
                    deleted_resources.setdefault(v, step.index)
        elif is_readonly:
            readonly_indices.append(step.index)

        for k, v in step.params.items():
            if v in ("", None) and k not in ("target", "description"):
                findings.append(
                    {
                        "severity": "low",
                        "kind": "empty_param",
                        "step_index": step.index,
                        "message": (
                            f"Step {step.index} ({step.tool}) has empty value for "
                            f"required-looking param '{k}'"
                        ),
                    }
                )
            if isinstance(v, str) and v.upper() in ("REVIEW", "TODO", "FIXME"):
                findings.append(
                    {
                        "severity": "high",
                        "kind": "placeholder_param",
                        "step_index": step.index,
                        "message": (
                            f"Step {step.index} ({step.tool}) has placeholder value "
                            f"'{v}' for param '{k}'"
                        ),
                    }
                )

        if not is_destructive:
            for k, v in step.params.items():
                if (
                    isinstance(v, str)
                    and v in deleted_resources
                    and deleted_resources[v] < step.index
                ):
                    findings.append(
                        {
                            "severity": "high",
                            "kind": "delete_then_use",
                            "step_index": step.index,
                            "message": (
                                f"Step {step.index} references resource '{v}' which "
                                f"step {deleted_resources[v]} deletes — operation will "
                                "fail at dispatch"
                            ),
                        }
                    )

    # Approval coverage check.
    for d_idx in destructive_indices:
        if not any(a < d_idx for a in approval_indices):
            findings.append(
                {
                    "severity": "high",
                    "kind": "ungated_destructive",
                    "step_index": d_idx,
                    "message": (
                        f"Step {d_idx} is destructive but has no preceding "
                        "require_approval gate — add an approval step or document "
                        "why this is safe"
                    ),
                }
            )

    # Group integrity
    groups: dict[str, list[int]] = {}
    for s in wf.steps:
        if s.group_id:
            groups.setdefault(s.group_id, []).append(s.index)
    for gid, indices in groups.items():
        indices.sort()
        if indices != list(range(min(indices), max(indices) + 1)):
            findings.append(
                {
                    "severity": "medium",
                    "kind": "non_contiguous_group",
                    "step_index": indices[0],
                    "message": f"Parallel group '{gid}' has non-contiguous steps {indices}",
                }
            )
        for i in indices:
            if i in destructive_indices:
                findings.append(
                    {
                        "severity": "high",
                        "kind": "destructive_in_parallel_group",
                        "step_index": i,
                        "message": (
                            f"Step {i} is destructive but belongs to parallel group "
                            f"'{gid}' — concurrent destructive ops bypass approval ordering"
                        ),
                    }
                )

    est_duration_min = (
        len(readonly_indices) * 0.2
        + len(destructive_indices) * 1.5
        + len(approval_indices) * 5.0
        + len(groups) * (-0.5)
    )
    est_duration_min = max(0.5, est_duration_min)

    verdict = "needs_revision" if any(f["severity"] == "high" for f in findings) else "approved"

    return {
        "workflow_id": wf.id,
        "verdict": verdict,
        "findings": findings,
        "summary": {
            "total_steps": len(wf.steps),
            "destructive_steps": len(destructive_indices),
            "read_only_steps": len(readonly_indices),
            "approval_gates": len(approval_indices),
            "parallel_groups": len(groups),
            "est_duration_min": round(est_duration_min, 1),
        },
    }
