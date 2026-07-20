"""Dynamic workflow authoring tools: create + draft design/update/confirm."""

from __future__ import annotations

import logging
from typing import Any, Optional

from vmware_policy import vmware_tool

from vmware_pilot.mcp_server._catalog import SKILL_CATALOG
from vmware_pilot.mcp_server._shared import (
    _get_store,
    _safe_error,
    _save_as_yaml,
    _validate_template_name,
    mcp,
)

logger = logging.getLogger(__name__)


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
@vmware_tool(risk_level="medium")
def create_workflow(
    name: str,
    description: str,
    steps: list[dict[str, Any]],
    save_as_template: bool = False,
) -> dict:
    """[WRITE] Create a custom workflow dynamically from a step list.

    Use this when none of the built-in templates match. Describe what you need
    and the AI will design the steps using available skills.

    Available skills and their key tools:
      - aiops: vm_power_on, vm_power_off, deploy_linked_clone, vm_create_plan,
               vm_apply_plan, vm_rollback_plan, vm_guest_exec, batch_clone_vms
      - monitor: get_alarms, get_events, list_virtual_machines, vm_info
      - nsx: create_segment, delete_segment, create_tier1_gateway, list_segments
      - nsx-security: create_dfw_rule, delete_dfw_rule, create_group
      - aria: get_capacity_overview, list_anomalies, list_alerts, get_remaining_capacity
      - vks: create_tkc_cluster, scale_tkc_cluster, delete_tkc_cluster
      - storage: storage_iscsi_enable, storage_iscsi_add_target, vsan_health

    Special step actions:
      - require_approval: Pauses workflow for human confirmation

    Each step dict must have: action, skill, tool, params.
    Optional: rollback_tool, rollback_params.

    Args:
        name: Workflow name (used as workflow_type).
        description: Human-readable description.
        steps: List of step dicts, each with action/skill/tool/params.
        save_as_template: If True, save as YAML to ~/.vmware/workflows/ for reuse.

    Returns:
        dict with workflow_id and plan summary. Call run_workflow to execute.

    Example:
        create_workflow(
            name="network_segment_setup",
            description="Create segment with NAT and verify",
            steps=[
                {"action": "create_segment", "skill": "nsx", "tool": "create_segment",
                 "params": {"segment_id": "app-seg", "display_name": "App Segment", ...}},
                {"action": "create_nat", "skill": "nsx", "tool": "create_nat_rule",
                 "params": {"tier1_id": "app-t1", "rule_id": "snat-1", ...}},
                {"action": "verify", "skill": "nsx", "tool": "list_segments",
                 "params": {}},
            ]
        )
    """
    from datetime import datetime, timezone

    from vmware_pilot.models import Workflow, WorkflowState, WorkflowStep, new_workflow_id

    try:
        # Validate BEFORE persisting anything: an invalid template name must
        # not leave a half-created workflow behind.
        if save_as_template:
            name_error = _validate_template_name(name)
            if name_error:
                return {
                    "error": name_error,
                    "hint": "Choose a simple name like 'network_segment_setup'.",
                }

        now = datetime.now(tz=timezone.utc).isoformat()
        wf_steps = []
        for i, s in enumerate(steps):
            wf_steps.append(
                WorkflowStep(
                    index=i,
                    action=s.get("action", f"step_{i}"),
                    skill=s.get("skill", "unknown"),
                    tool=s.get("tool", "unknown"),
                    params=s.get("params", {}),
                    rollback_tool=s.get("rollback_tool", ""),
                    rollback_params=s.get("rollback_params", {}),
                )
            )

        wf = Workflow(
            id=new_workflow_id(),
            workflow_type=name,
            state=WorkflowState.PENDING,
            steps=wf_steps,
            params={"description": description, "custom": True},
            created_at=now,
            updated_at=now,
        )
        _get_store().save(wf)

        # Optionally save as YAML template for reuse
        if save_as_template:
            _save_as_yaml(name, description, steps)

        return {
            "workflow_id": wf.id,
            "workflow_type": name,
            "state": wf.state.value,
            "steps": [
                {"index": s.index, "action": s.action, "skill": s.skill, "tool": s.tool}
                for s in wf.steps
            ],
            "saved_as_template": save_as_template,
            "message": f"Custom workflow created. Call run_workflow('{wf.id}') to execute.",
        }
    except Exception as e:
        return {
            "error": _safe_error(e, "create_workflow"),
            "hint": "Every step needs action, skill, tool and params. Run "
            "get_skill_catalog to confirm the skill and tool names are ones "
            "pilot can drive, then call create_workflow again.",
        }


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
@vmware_tool(risk_level="low")
def design_workflow(
    goal: str,
    constraints: str = "",
) -> dict:
    """[WRITE] Start designing a workflow from a natural language description.

    Call this when the user describes a complex operation and you need to
    design a multi-step workflow. Returns a DRAFT workflow with proposed steps
    for the user to review and edit before execution.

    Design flow:
      1. AI calls design_workflow(goal="...") → returns draft with proposed steps
      2. User reviews: "step 3 should use vm_power_off instead" or "add an approval before step 4"
      3. AI calls update_draft(workflow_id, ...) to modify
      4. User confirms: "looks good"
      5. AI calls confirm_draft(workflow_id) → state changes to PENDING
      6. AI calls run_workflow(workflow_id) → execute

    The AI should use get_skill_catalog() first to understand available tools,
    then propose steps based on the user's goal.

    Args:
        goal: Natural language description of what the user wants to accomplish.
        constraints: Optional constraints (e.g. "must have approval before any destructive step",
                     "use NSX for networking", "target is vcenter-prod").

    Returns:
        dict with workflow_id (state=DRAFT), proposed steps placeholder,
        and instructions for the AI to fill in steps via update_draft.
    """
    from datetime import datetime, timezone

    from vmware_pilot.models import Workflow, WorkflowState, new_workflow_id

    now = datetime.now(tz=timezone.utc).isoformat()
    wf = Workflow(
        id=new_workflow_id(),
        workflow_type="custom_draft",
        state=WorkflowState.DRAFT,
        steps=[],
        params={"goal": goal, "constraints": constraints, "custom": True},
        created_at=now,
        updated_at=now,
    )
    wf.log("draft_created", f"Goal: {goal}")
    _get_store().save(wf)

    return {
        "workflow_id": wf.id,
        "state": "draft",
        "goal": goal,
        "constraints": constraints,
        "available_skills": list(SKILL_CATALOG.keys()),
        "next_step": (
            "Now design the workflow steps. Use get_skill_catalog() to see available tools, "
            "then call update_draft() to add steps. When done, call confirm_draft() to finalize."
        ),
    }


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
@vmware_tool(risk_level="medium")
def update_draft(
    workflow_id: str,
    name: str = "",
    description: str = "",
    steps: Optional[list[dict[str, Any]]] = None,  # noqa: UP045 — Optional, not PEP 604, in reflected MCP signature (踩坑 #33)
) -> dict:
    """[WRITE] Update a DRAFT workflow's name, description, or steps.

    Call this after design_workflow() to fill in the actual steps,
    or to modify steps based on user feedback.

    Each step dict: {action, skill, tool, params, rollback_tool?, rollback_params?}
    Use action="require_approval" for approval gates.

    Args:
        workflow_id: The draft workflow ID.
        name: Workflow name (optional, updates workflow_type).
        description: Human-readable description.
        steps: Complete list of steps (replaces all existing steps).

    Returns:
        Updated workflow summary for user review.
    """
    from vmware_pilot.models import WorkflowState, WorkflowStep

    wf = _get_store().load(workflow_id)
    if not wf:
        return {"error": f"Workflow '{workflow_id}' not found"}
    if wf.state != WorkflowState.DRAFT:
        return {"error": f"Workflow '{workflow_id}' is not a draft (state: {wf.state.value})"}

    if name:
        wf.workflow_type = name
    if description:
        wf.params["description"] = description

    if steps is not None:
        wf.steps = [
            WorkflowStep(
                index=i,
                action=s.get("action", f"step_{i}"),
                skill=s.get("skill", "unknown"),
                tool=s.get("tool", "unknown"),
                params=s.get("params", {}),
                rollback_tool=s.get("rollback_tool", ""),
                rollback_params=s.get("rollback_params", {}),
            )
            for i, s in enumerate(steps)
        ]
        wf.log("steps_updated", f"{len(steps)} steps")

    _get_store().save(wf)

    return {
        "workflow_id": wf.id,
        "workflow_type": wf.workflow_type,
        "state": "draft",
        "steps": [
            {
                "index": s.index,
                "action": s.action,
                "skill": s.skill,
                "tool": s.tool,
                "has_rollback": bool(s.rollback_tool),
            }
            for s in wf.steps
        ],
        "message": "Draft updated. Show to user for review. Call confirm_draft() when approved.",
    }


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
@vmware_tool(risk_level="medium")
def confirm_draft(
    workflow_id: str,
    save_as_template: bool = False,
) -> dict:
    """[WRITE] Confirm a draft workflow — changes state from DRAFT to PENDING.

    After confirmation, the workflow can be executed via run_workflow().
    Optionally saves as a YAML template for future reuse.

    Args:
        workflow_id: The draft workflow ID to confirm.
        save_as_template: If True, save to ~/.vmware/workflows/ for reuse.

    Returns:
        Confirmed workflow summary. Call run_workflow() to execute.
    """
    from vmware_pilot.models import WorkflowState

    try:
        wf = _get_store().load(workflow_id)
        if not wf:
            return {"error": f"Workflow '{workflow_id}' not found"}
        if wf.state != WorkflowState.DRAFT:
            return {"error": f"Workflow '{workflow_id}' is not a draft (state: {wf.state.value})"}
        if not wf.steps:
            return {"error": "Cannot confirm a draft with no steps. Call update_draft() first."}

        # Validate the template name BEFORE flipping state to PENDING, so an
        # invalid name cannot leave a confirmed-but-unsaved-template state.
        will_save_template = save_as_template and wf.workflow_type != "custom_draft"
        if will_save_template:
            name_error = _validate_template_name(wf.workflow_type)
            if name_error:
                return {
                    "error": name_error,
                    "hint": "Rename the draft via update_draft(name=...) first.",
                }

        wf.state = WorkflowState.PENDING
        wf.log("draft_confirmed", f"Confirmed with {len(wf.steps)} steps")
        _get_store().save(wf)

        if will_save_template:
            steps_for_yaml = [
                {
                    "action": s.action,
                    "skill": s.skill,
                    "tool": s.tool,
                    "params": s.params,
                    **(
                        {"rollback_tool": s.rollback_tool, "rollback_params": s.rollback_params}
                        if s.rollback_tool
                        else {}
                    ),
                }
                for s in wf.steps
            ]
            _save_as_yaml(wf.workflow_type, wf.params.get("description", ""), steps_for_yaml)

        return {
            "workflow_id": wf.id,
            "workflow_type": wf.workflow_type,
            "state": "pending",
            "steps_count": len(wf.steps),
            "saved_as_template": save_as_template,
            "message": f"Workflow confirmed. Call run_workflow('{wf.id}') to execute.",
        }
    except Exception as e:
        return {
            "error": _safe_error(e, "confirm_draft"),
            "hint": f"Failed to confirm draft '{workflow_id}'. "
            f"Use get_workflow_status() to inspect it.",
        }
