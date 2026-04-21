"""Workflow executor — runs workflow steps, handles approval gates and rollback.

The executor does NOT call VMware APIs directly. It delegates to skill MCP tools
via a pluggable dispatch interface. This keeps pilot decoupled from any specific skill.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from vmware_pilot.models import Workflow, WorkflowState, WorkflowStore

_log = logging.getLogger("vmware-pilot.executor")


# Type for the dispatch function: (skill, tool, params) → result
DispatchFn = Callable[[str, str, dict[str, Any]], Any]


class WorkflowExecutor:
    """Execute workflow steps sequentially, pausing at approval gates."""

    def __init__(self, store: WorkflowStore, dispatch: DispatchFn | None = None) -> None:
        self._store = store
        self._dispatch = dispatch or _noop_dispatch

    def run_until_checkpoint(self, wf: Workflow) -> dict[str, Any]:
        """Execute steps until an approval gate or completion.

        Returns the current workflow state as a dict.
        """
        wf.state = WorkflowState.RUNNING
        wf.log("run_started")
        self._store.save(wf)

        for step in wf.steps:
            if step.status != "pending":
                continue

            # Check if this step requires approval
            if step.action == "require_approval":
                wf.state = WorkflowState.AWAITING_APPROVAL
                wf.log("awaiting_approval", f"Step {step.index}: {step.action}")
                self._store.save(wf)
                return wf.to_dict()

            # Execute the step
            step.status = "running"
            step.started_at = _now()
            self._store.save(wf)

            try:
                resolved_params = self._resolve_step_refs(step.params, wf.steps)
                result = self._dispatch(step.skill, step.tool, resolved_params)
                step.status = "success"
                step.result = result
                step.completed_at = _now()
                wf.log("step_completed", f"Step {step.index}: {step.tool} → success")
            except Exception as exc:
                step.status = "failed"
                step.result = {"error": str(exc)}
                step.completed_at = _now()
                wf.state = WorkflowState.FAILED
                wf.log("step_failed", f"Step {step.index}: {step.tool} → {exc}")

                # Skip remaining steps
                for remaining in wf.steps:
                    if remaining.status == "pending":
                        remaining.status = "skipped"

                self._store.save(wf)
                return wf.to_dict()

        # All steps completed
        wf.state = WorkflowState.COMPLETED
        wf.log("workflow_completed")
        self._store.save(wf)
        return wf.to_dict()

    def resume_after_approval(self, wf: Workflow, approver: str = "") -> dict[str, Any]:
        """Continue execution after human approval."""
        if wf.state != WorkflowState.AWAITING_APPROVAL:
            return {"error": f"Workflow {wf.id} is not awaiting approval (state: {wf.state.value})"}

        wf.approved_by = approver
        wf.log("approved", f"Approved by {approver}")

        # Mark the approval step as done
        for step in wf.steps:
            if step.action == "require_approval" and step.status == "pending":
                step.status = "success"
                step.result = {"approved_by": approver}
                step.completed_at = _now()
                break

        # Continue executing remaining steps
        return self.run_until_checkpoint(wf)

    def rollback(self, wf: Workflow) -> dict[str, Any]:
        """Rollback completed steps in reverse order."""
        wf.state = WorkflowState.ROLLING_BACK
        wf.log("rollback_started")
        self._store.save(wf)

        rollback_results = []
        for step in reversed(wf.completed_steps()):
            if not step.rollback_tool:
                rollback_results.append({
                    "step": step.index,
                    "tool": step.tool,
                    "status": "skipped",
                    "reason": "no rollback defined",
                })
                continue

            try:
                resolved_rb = self._resolve_step_refs(step.rollback_params, wf.steps)
                result = self._dispatch(step.skill, step.rollback_tool, resolved_rb)
                step.status = "rolled_back"
                rollback_results.append({
                    "step": step.index,
                    "tool": step.rollback_tool,
                    "status": "success",
                    "result": result,
                })
                wf.log("rollback_step", f"Step {step.index}: {step.rollback_tool} → success")
            except Exception as exc:
                rollback_results.append({
                    "step": step.index,
                    "tool": step.rollback_tool,
                    "status": "failed",
                    "error": str(exc),
                })
                wf.log("rollback_failed", f"Step {step.index}: {step.rollback_tool} → {exc}")
                # Continue rolling back other steps even if one fails

            self._store.save(wf)

        wf.state = WorkflowState.FAILED
        wf.log("rollback_completed")
        self._store.save(wf)

        result = wf.to_dict()
        result["rollback_results"] = rollback_results
        return result

    def mark_blocked(self, wf: Workflow, reason: str) -> dict[str, Any]:
        """Mark workflow as blocked by policy. Does NOT rollback."""
        wf.state = WorkflowState.BLOCKED_BY_POLICY
        wf.blocked_reason = reason
        wf.log("blocked_by_policy", reason)
        self._store.save(wf)
        return wf.to_dict()


    @staticmethod
    def _resolve_step_refs(
        params: dict[str, Any], steps: list,
    ) -> dict[str, Any]:
        """Replace ``__from_step_N__:key`` references with actual step results.

        Format: ``"__from_step_0__:plan_id"`` → result of step 0, key ``plan_id``.
        If the key part is omitted, the entire step result is used.
        """
        resolved: dict[str, Any] = {}
        for k, v in params.items():
            if isinstance(v, str) and v.startswith("__from_step_") and v.endswith("__"):
                # Legacy format without key: __from_step_0__
                try:
                    idx = int(v[len("__from_step_"):-2])
                    source = steps[idx]
                    resolved[k] = source.result if source.result is not None else v
                except (ValueError, IndexError):
                    resolved[k] = v
            elif isinstance(v, str) and v.startswith("__from_step_"):
                # New format with key: __from_step_0__:plan_id
                try:
                    ref_part, result_key = v.split(":", 1)
                    idx = int(ref_part[len("__from_step_"):-2])
                    source = steps[idx]
                    if isinstance(source.result, dict):
                        resolved[k] = source.result.get(result_key, source.result)
                    else:
                        resolved[k] = source.result if source.result is not None else v
                except (ValueError, IndexError):
                    resolved[k] = v
            else:
                resolved[k] = v
        return resolved


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _noop_dispatch(skill: str, tool: str, params: dict[str, Any]) -> Any:
    """Placeholder dispatch — real implementation calls MCP tools."""
    _log.warning("noop dispatch: %s.%s(%s)", skill, tool, params)
    return {"noop": True, "skill": skill, "tool": tool}
