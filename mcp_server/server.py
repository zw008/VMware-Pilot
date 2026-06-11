"""MCP server for VMware Pilot — workflow orchestration.

Exposes 5 tools for AI agents to manage multi-step VMware workflows:
  plan_workflow   — create execution plan
  run_workflow    — execute (pauses at approval gates)
  get_workflow_status — query state + diff + audit log
  approve         — human approval, continue
  rollback        — abort and reverse
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from vmware_policy import vmware_tool

from vmware_pilot.executor import WorkflowExecutor
from vmware_pilot.models import WorkflowState, WorkflowStore
from vmware_pilot.review import review as _review_workflow_impl
from vmware_pilot.templates import get_all_templates

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "vmware-pilot",
    instructions=(
        "VMware workflow orchestration. Plan and execute multi-step operations "
        "(clone-test-approve-commit, incident response) with state persistence, "
        "approval gates, and automatic rollback. "
        "Use plan_workflow to create a plan, run_workflow to execute, "
        "approve to continue past gates, rollback to abort."
    ),
)

_store: WorkflowStore | None = None
_executor: WorkflowExecutor | None = None


def _get_store() -> WorkflowStore:
    global _store
    if _store is None:
        _store = WorkflowStore()
    return _store


def _get_executor() -> WorkflowExecutor:
    global _executor
    if _executor is None:
        _executor = WorkflowExecutor(_get_store())
    return _executor


# ── MCP Tools ─────────────────────────────────────────────────────────


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
@vmware_tool(risk_level="medium")
def plan_workflow(
    workflow_type: str,
    params: dict[str, Any],
) -> dict:
    """[WRITE] Create an execution plan for a multi-step workflow.

    Available workflow types:
      - clone_and_test: Clone VM → apply changes → monitor → approve → commit
      - incident_response: Diagnose alert → collect info → approve → remediate
      - plan_and_approve: Wrap aiops batch operations with approval gate
      - compliance_scan: Read-only health/capacity/anomaly check (no approval)

    Args:
        workflow_type: One of the available workflow types.
        params: Workflow-specific parameters.
            clone_and_test: target_vm (str), change_spec (dict), monitor_minutes (int), target (str).
            incident_response: alert_entity (str), alert_name (str), target (str).
            plan_and_approve: operations (list[dict]), target (str), description (str).
            compliance_scan: target (str), check_alarms (bool), check_capacity (bool).

    Returns:
        dict with workflow_id, steps summary, and plan details.
    """
    try:
        templates = get_all_templates()
        template_fn = templates.get(workflow_type)
        if not template_fn:
            return {"error": f"Unknown workflow type: {workflow_type}. Available: {list(templates.keys())}"}

        wf = template_fn(**params)
        _get_store().save(wf)

        return {
            "workflow_id": wf.id,
            "workflow_type": wf.workflow_type,
            "state": wf.state.value,
            "steps": [
                {"index": s.index, "action": s.action, "skill": s.skill, "tool": s.tool}
                for s in wf.steps
            ],
            "params": wf.params,
            "message": f"Plan created. Call run_workflow('{wf.id}') to execute.",
        }
    except Exception as e:
        return {"error": str(e), "hint": "Check workflow_type and params. Use list_workflows() to see available templates."}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
@vmware_tool(risk_level="medium")
def run_workflow(workflow_id: str, force: bool = False) -> dict:
    """[WRITE] Advance a planned workflow. Pauses at approval gates.

    IMPORTANT — this MCP server has no dispatcher and cannot call other
    skills' MCP tools itself. Steps are recorded as 'not_executed' and the
    run finishes with outcome='dispatch_required' (NOT 'completed'),
    returning each pending step's skill/tool/params. YOU (the calling
    agent) must then perform those skill/tool calls in order. A workflow
    only reaches 'completed' when every step genuinely executed via a
    real dispatcher (embedders supplying one to WorkflowExecutor).

    Safety: the workflow is structurally reviewed before each run. Runs
    are REFUSED if review finds ungated destructive steps or destructive
    steps inside a parallel group, unless force=True (forced runs are
    written to the workflow audit log).

    When an approval gate is reached, the workflow pauses with state
    'awaiting_approval'. Call approve() to continue.

    Args:
        workflow_id: The workflow ID from plan_workflow.
        force: Bypass blocking review findings (ungated_destructive,
            destructive_in_parallel_group). Use only with explicit human
            consent; the bypass is audited.

    Returns:
        Current workflow state with 'outcome' (completed | awaiting_approval
        | dispatch_required | failed) and, when dispatch is required, a
        'pending_dispatch' list of steps for the agent to perform.
    """
    wf = _get_store().load(workflow_id)
    if not wf:
        return {"error": f"Workflow '{workflow_id}' not found"}

    if wf.state not in (WorkflowState.PENDING, WorkflowState.RUNNING):
        return {"error": f"Workflow '{workflow_id}' cannot be run (state: {wf.state.value})"}

    try:
        # ── Approval-gate enforcement (not just advisory) ─────────────
        review_result = _review_workflow_impl(wf)
        blocking = [
            f for f in review_result.get("findings", [])
            if f.get("kind") in ("ungated_destructive", "destructive_in_parallel_group")
        ]
        if blocking:
            if not force:
                return {
                    "error": (
                        f"Refusing to run workflow '{workflow_id}': review found "
                        f"{len(blocking)} blocking safety finding(s) — destructive "
                        "steps without a preceding require_approval gate and/or "
                        "destructive steps inside a parallel group."
                    ),
                    "blocking_findings": blocking,
                    "hint": (
                        "Fix the workflow (add a require_approval step before "
                        "destructive operations, or remove them from parallel "
                        "groups) via update_draft/create_workflow, or re-run "
                        "with force=True after explicit human confirmation "
                        "(forced runs are audited)."
                    ),
                }
            wf.log(
                "forced_run",
                f"force=True bypassed {len(blocking)} blocking review finding(s): "
                + ", ".join(f"{f['kind']}@step{f['step_index']}" for f in blocking),
            )
            logger.warning(
                "Workflow %s forced past %d blocking review findings",
                workflow_id, len(blocking),
            )
            _get_store().save(wf)

        return _get_executor().run_until_checkpoint(wf)
    except Exception as e:
        return {"error": str(e), "hint": f"Workflow '{workflow_id}' execution failed. Use get_workflow_status() to check state, or rollback()."}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
@vmware_tool(risk_level="low")
def review_workflow(workflow_id: str) -> dict:
    """[READ] Sanity-check a planned workflow before execution.

    Performs structural validation only — does NOT call into other skills.
    Catches the common authoring errors before they hit production:

      - Delete-then-use: a step deletes resource X, a later step references X
      - Missing required params: a step has empty params or placeholder values
      - Cross-skill order issues: surfacing the cross-skill dispatch sequence
      - Risk profile: count of destructive vs. read-only steps
      - Approval coverage: are all destructive ops gated behind a require_approval?

    Args:
        workflow_id: The workflow ID returned by ``plan_workflow``.

    Returns:
        Dict with keys:
          - ``verdict``: ``"approved"`` if no structural issues, otherwise ``"needs_revision"``
          - ``findings``: list of {severity, kind, message, step_index}
          - ``summary``: counts (steps, gather/destructive/approval), groups, est_duration_min
    """
    try:
        wf = _get_store().load(workflow_id)
        if not wf:
            return {"error": f"Workflow '{workflow_id}' not found"}
        return _review_workflow_impl(wf)
    except Exception as e:
        return {"error": str(e), "hint": f"Review failed for '{workflow_id}'. Use get_workflow_status() to inspect raw state."}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
@vmware_tool(risk_level="low")
def get_workflow_status(workflow_id: str) -> dict:
    """[READ] Get current workflow state, diff report, and audit log.

    Args:
        workflow_id: The workflow ID to query.

    Returns:
        Full workflow state including steps, audit log, and diff report.
    """
    try:
        wf = _get_store().load(workflow_id)
        if not wf:
            return {"error": f"Workflow '{workflow_id}' not found"}
        return wf.to_dict()
    except Exception as e:
        return {"error": str(e), "hint": "Use list_workflows() to see active workflow IDs."}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
@vmware_tool(risk_level="high")
def approve(workflow_id: str, approver: str = "") -> dict:
    """[WRITE] Approve a workflow that is waiting for human confirmation.

    Only works when workflow state is 'awaiting_approval'.
    After approval, execution continues to the next steps.

    Args:
        workflow_id: The workflow ID to approve.
        approver: Name of the person approving (for audit trail).

    Note: this server has no dispatcher — after approval, remaining steps
    are recorded as 'not_executed' and the result carries
    outcome='dispatch_required' with a 'pending_dispatch' list for the
    calling agent to perform (see run_workflow).

    Returns:
        Updated workflow state after resuming.
    """
    try:
        wf = _get_store().load(workflow_id)
        if not wf:
            return {"error": f"Workflow '{workflow_id}' not found"}

        # Non-empty approver enforcement lives in the executor so embedders
        # cannot bypass the audit-trail requirement.
        return _get_executor().resume_after_approval(wf, approver=approver)
    except Exception as e:
        return {"error": str(e), "hint": f"Approval failed for '{workflow_id}'. Use get_workflow_status() to check state."}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True})
@vmware_tool(risk_level="high")
def rollback(workflow_id: str) -> dict:
    """[WRITE] Abort a workflow and rollback completed steps in reverse order.

    Works in any state except 'completed'. Irreversible steps are skipped.
    The workflow state is set to 'failed' after rollback.

    Args:
        workflow_id: The workflow ID to rollback.

    Returns:
        Rollback results for each step.
    """
    try:
        wf = _get_store().load(workflow_id)
        if not wf:
            return {"error": f"Workflow '{workflow_id}' not found"}

        if wf.state == WorkflowState.COMPLETED:
            return {"error": f"Workflow '{workflow_id}' is already completed, cannot rollback"}

        return _get_executor().rollback(wf)
    except Exception as e:
        return {"error": str(e), "hint": f"Rollback failed for '{workflow_id}'. Use get_workflow_status() to check state."}


# ── Discovery & Dynamic Creation ──────────────────────────────────────


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
@vmware_tool(risk_level="low")
def list_workflows() -> dict:
    """[READ] List all available workflow templates (built-in + custom).

    Built-in templates are always available. Custom templates are loaded
    from ~/.vmware/workflows/*.yaml — drop a YAML file there to add
    your own workflows.

    Returns:
        dict with builtin and custom workflow lists, each with name, description, steps count.
    """
    try:
        from vmware_pilot.custom_loader import list_custom_workflows
        from vmware_pilot.templates import BUILTIN_TEMPLATES

        builtin = [
            {"name": name, "type": "builtin", "description": (fn.__doc__ or "").split("\n")[0].strip()}
            for name, fn in BUILTIN_TEMPLATES.items()
        ]
        custom = [
            {**c, "type": "custom"}
            for c in list_custom_workflows()
        ]

        active = _get_store().list_active()

        return {
            "templates": builtin + custom,
            "active_workflows": active,
        }
    except Exception as e:
        return {"error": str(e), "hint": "Failed to list workflows."}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
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
                return {"error": name_error, "hint": "Choose a simple name like 'network_segment_setup'."}

        now = datetime.now(tz=timezone.utc).isoformat()
        wf_steps = []
        for i, s in enumerate(steps):
            wf_steps.append(WorkflowStep(
                index=i,
                action=s.get("action", f"step_{i}"),
                skill=s.get("skill", "unknown"),
                tool=s.get("tool", "unknown"),
                params=s.get("params", {}),
                rollback_tool=s.get("rollback_tool", ""),
                rollback_params=s.get("rollback_params", {}),
            ))

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
        return {"error": str(e), "hint": "Failed to create workflow. Check step definitions."}


def _validate_template_name(name: str) -> str | None:
    """Return an error message if ``name`` is unsafe as a template filename.

    ``name`` is user-supplied and becomes a filename — reject traversal so a
    template cannot be written outside the workflows dir.
    """
    if not name or "/" in name or "\\" in name or name.startswith(".") or "\x00" in name:
        return (
            f"Invalid workflow name {name!r}: must be non-empty with no path "
            "separators, leading dots, or null bytes"
        )
    return None


def _save_as_yaml(name: str, description: str, steps: list[dict[str, Any]]) -> None:
    """Save a dynamic workflow as YAML for future reuse."""
    import os
    import yaml
    from pathlib import Path

    name_error = _validate_template_name(name)
    if name_error:
        raise ValueError(name_error)

    workflows_dir = Path("~/.vmware/workflows").expanduser()
    workflows_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(workflows_dir, 0o700)
    except OSError:
        pass

    spec = {
        "name": name,
        "description": description,
        "steps": [
            {k: v for k, v in s.items() if v}  # strip empty values
            for s in steps
        ],
    }

    path = workflows_dir / f"{name}.yaml"
    with open(path, "w") as fh:
        yaml.dump(spec, fh, default_flow_style=False, allow_unicode=True)

    logger.info("Saved custom workflow template: %s", path)


# ── Skill Catalog & Design Mode ──────────────────────────────────────

SKILL_CATALOG = {
    "aiops": {
        "description": "VM lifecycle, deployment, clusters, guest operations, alarm management",
        "tools": {
            "vm_power_on": {"risk": "medium", "desc": "Power on a VM"},
            "vm_power_off": {"risk": "medium", "desc": "Power off a VM (graceful/force)"},
            "deploy_linked_clone": {"risk": "medium", "desc": "Instant clone from snapshot"},
            "deploy_vm_from_template": {"risk": "medium", "desc": "Clone from vSphere template"},
            "deploy_vm_from_ova": {"risk": "medium", "desc": "Deploy from OVA file"},
            "batch_clone_vms": {"risk": "medium", "desc": "Batch clone multiple VMs"},
            "vm_guest_exec": {"risk": "medium", "desc": "Execute command inside VM"},
            "vm_guest_exec_output": {"risk": "medium", "desc": "Execute and capture stdout"},
            "vm_guest_upload": {"risk": "medium", "desc": "Upload file to VM"},
            "vm_guest_provision": {"risk": "medium", "desc": "Multi-step VM provisioning"},
            "vm_create_plan": {"risk": "medium", "desc": "Create multi-step execution plan"},
            "vm_apply_plan": {"risk": "medium", "desc": "Execute a created plan"},
            "vm_rollback_plan": {"risk": "medium", "desc": "Rollback a failed plan"},
            "vm_clean_slate": {"risk": "high", "desc": "Revert VM to baseline snapshot"},
            "cluster_create": {"risk": "medium", "desc": "Create cluster with HA/DRS"},
            "cluster_delete": {"risk": "high", "desc": "Delete empty cluster"},
            "acknowledge_vcenter_alarm": {"risk": "medium", "desc": "Acknowledge alarm"},
            "reset_vcenter_alarm": {"risk": "medium", "desc": "Clear alarm"},
        },
    },
    "monitor": {
        "description": "Read-only monitoring: inventory, alarms, events, VM info",
        "tools": {
            "list_virtual_machines": {"risk": "low", "desc": "List all VMs"},
            "list_esxi_hosts": {"risk": "low", "desc": "List ESXi hosts"},
            "get_alarms": {"risk": "low", "desc": "Get active alarms with remediation hints"},
            "get_events": {"risk": "low", "desc": "Recent events by severity"},
            "vm_info": {"risk": "low", "desc": "Detailed VM info (CPU/mem/disk/NIC)"},
        },
    },
    "nsx": {
        "description": "NSX networking: segments, gateways, NAT, routing, IP pools",
        "tools": {
            "list_segments": {"risk": "low", "desc": "List network segments"},
            "create_segment": {"risk": "medium", "desc": "Create network segment"},
            "delete_segment": {"risk": "high", "desc": "Delete network segment"},
            "create_tier1_gateway": {"risk": "medium", "desc": "Create Tier-1 gateway"},
            "delete_tier1_gateway": {"risk": "high", "desc": "Delete Tier-1 gateway"},
            "create_nat_rule": {"risk": "medium", "desc": "Create NAT rule on Tier-1"},
            "delete_nat_rule": {"risk": "high", "desc": "Delete NAT rule"},
            "create_static_route": {"risk": "medium", "desc": "Create static route"},
        },
    },
    "nsx-security": {
        "description": "NSX security: DFW policies/rules, security groups, traceflow, IDPS",
        "tools": {
            "list_dfw_policies": {"risk": "low", "desc": "List firewall policies"},
            "create_dfw_policy": {"risk": "medium", "desc": "Create firewall policy"},
            "delete_dfw_policy": {"risk": "high", "desc": "Delete firewall policy"},
            "create_dfw_rule": {"risk": "medium", "desc": "Create firewall rule"},
            "delete_dfw_rule": {"risk": "high", "desc": "Delete firewall rule"},
            "create_group": {"risk": "medium", "desc": "Create security group"},
            "run_traceflow": {"risk": "medium", "desc": "Network path trace"},
        },
    },
    "aria": {
        "description": "Aria Operations: metrics, alerts, capacity planning, anomaly detection",
        "tools": {
            "list_alerts": {"risk": "low", "desc": "List alerts with filters"},
            "acknowledge_alert": {"risk": "medium", "desc": "Acknowledge alert"},
            "get_capacity_overview": {"risk": "low", "desc": "Capacity recommendations"},
            "get_remaining_capacity": {"risk": "low", "desc": "CPU/mem/disk remaining"},
            "get_time_remaining": {"risk": "low", "desc": "Days until capacity exhaustion"},
            "list_anomalies": {"risk": "low", "desc": "ML-detected metric anomalies"},
            "list_rightsizing_recommendations": {"risk": "low", "desc": "Over/under-provisioned VMs"},
        },
    },
    "vks": {
        "description": "Tanzu Kubernetes: Supervisor, Namespaces, TKC clusters",
        "tools": {
            "create_namespace": {"risk": "medium", "desc": "Create vSphere Namespace"},
            "delete_namespace": {"risk": "high", "desc": "Delete vSphere Namespace"},
            "create_tkc_cluster": {"risk": "medium", "desc": "Create TKC cluster"},
            "scale_tkc_cluster": {"risk": "medium", "desc": "Scale worker nodes"},
            "upgrade_tkc_cluster": {"risk": "medium", "desc": "Upgrade K8s version"},
            "delete_tkc_cluster": {"risk": "high", "desc": "Delete TKC cluster"},
        },
    },
    "storage": {
        "description": "Storage management: datastores, iSCSI, vSAN",
        "tools": {
            "storage_iscsi_enable": {"risk": "medium", "desc": "Enable iSCSI adapter"},
            "storage_iscsi_add_target": {"risk": "medium", "desc": "Add iSCSI target"},
            "storage_rescan": {"risk": "medium", "desc": "Rescan all HBAs"},
            "vsan_health": {"risk": "low", "desc": "vSAN cluster health"},
            "vsan_capacity": {"risk": "low", "desc": "vSAN capacity overview"},
        },
    },
}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
@vmware_tool(risk_level="low")
def get_skill_catalog() -> dict:
    """[READ] Get the complete catalog of available skills and tools for workflow design.

    Use this to understand what building blocks are available when designing
    a custom workflow. Each skill lists its key tools with risk level and description.

    Returns:
        dict mapping skill name → {description, tools: {tool_name: {risk, desc}}}.
    """
    return SKILL_CATALOG


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
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


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
@vmware_tool(risk_level="medium")
def update_draft(
    workflow_id: str,
    name: str = "",
    description: str = "",
    steps: list[dict[str, Any]] | None = None,
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
    from vmware_pilot.models import WorkflowStep

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
            {"index": s.index, "action": s.action, "skill": s.skill, "tool": s.tool,
             "has_rollback": bool(s.rollback_tool)}
            for s in wf.steps
        ],
        "message": "Draft updated. Show to user for review. Call confirm_draft() when approved.",
    }


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
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
                return {"error": name_error, "hint": "Rename the draft via update_draft(name=...) first."}

        wf.state = WorkflowState.PENDING
        wf.log("draft_confirmed", f"Confirmed with {len(wf.steps)} steps")
        _get_store().save(wf)

        if will_save_template:
            steps_for_yaml = [
                {
                    "action": s.action, "skill": s.skill, "tool": s.tool,
                    "params": s.params,
                    **({"rollback_tool": s.rollback_tool, "rollback_params": s.rollback_params}
                       if s.rollback_tool else {}),
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
        return {"error": str(e), "hint": f"Failed to confirm draft '{workflow_id}'. Use get_workflow_status() to inspect it."}


# ── Entry point ───────────────────────────────────────────────────────


def main() -> None:
    """Run the MCP server over stdio."""
    logging.basicConfig(level=logging.INFO)
    mcp.run(transport="stdio")
