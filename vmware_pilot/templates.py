"""Built-in workflow templates — predefined multi-step operations.

Each template function returns a Workflow with pre-configured steps.
The executor runs them; the AI agent only calls plan/run/approve/rollback.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from vmware_pilot.models import Workflow, WorkflowState, WorkflowStep, new_workflow_id


def clone_and_test(
    target_vm: str,
    change_spec: dict[str, Any],
    monitor_minutes: int = 5,
    target: str = "",
) -> Workflow:
    """Clone a VM, apply changes in staging, monitor, then await approval.

    Steps:
      1. Clone target VM → staging
      2. Apply change_spec to staging
      3. Monitor staging for N minutes
      4. Await human approval
      5. Apply change_spec to production (original VM)
      6. Delete staging VM

    Args:
        target_vm: Production VM name to clone.
        change_spec: Changes to apply (e.g. {"memory_gb": 32, "cpu": 4}).
        monitor_minutes: How long to monitor staging (default 5).
        target: vCenter target name.
    """
    staging_name = f"{target_vm}-staging"
    now = datetime.now(tz=timezone.utc).isoformat()

    steps = [
        WorkflowStep(
            index=0,
            action="clone",
            skill="aiops",
            tool="deploy_linked_clone",
            params={
                "source_vm_name": target_vm,
                "snapshot_name": "current",
                "new_name": staging_name,
                "power_on": True,
                "target": target,
            },
            rollback_tool="vm_power_off",
            rollback_params={"vm_name": staging_name, "force": True, "target": target},
        ),
        WorkflowStep(
            index=1,
            action="apply_changes",
            skill="aiops",
            tool="vm_reconfigure" if "cpu" in change_spec or "memory_mb" in change_spec else "vm_guest_exec",
            params={"vm_name": staging_name, **change_spec, "target": target},
        ),
        WorkflowStep(
            index=2,
            action="monitor",
            skill="monitor",
            tool="get_alarms",
            params={"target": target},
        ),
        WorkflowStep(
            index=3,
            action="require_approval",
            skill="pilot",
            tool="approve",
            params={"message": f"Staging VM '{staging_name}' tested. Apply to production?"},
        ),
        WorkflowStep(
            index=4,
            action="apply_to_production",
            skill="aiops",
            tool="vm_reconfigure" if "cpu" in change_spec or "memory_mb" in change_spec else "vm_guest_exec",
            params={"vm_name": target_vm, **change_spec, "target": target},
        ),
        WorkflowStep(
            index=5,
            action="cleanup",
            skill="aiops",
            tool="vm_power_off",
            params={"vm_name": staging_name, "force": True, "target": target},
        ),
    ]

    return Workflow(
        id=new_workflow_id(),
        workflow_type="clone_and_test",
        state=WorkflowState.PENDING,
        steps=steps,
        params={
            "target_vm": target_vm,
            "change_spec": change_spec,
            "staging_vm": staging_name,
            "monitor_minutes": monitor_minutes,
            "target": target,
        },
        created_at=now,
        updated_at=now,
    )


def incident_response(
    alert_entity: str,
    alert_name: str,
    target: str = "",
) -> Workflow:
    """Auto-diagnose and remediate an alert.

    Steps:
      1. Get alarm details
      2. Collect diagnostics (events, VM info)
      3. Await approval for remediation
      4. Execute remediation (acknowledge alarm)
    """
    now = datetime.now(tz=timezone.utc).isoformat()

    steps = [
        WorkflowStep(
            index=0,
            action="get_alarms",
            skill="monitor",
            tool="get_alarms",
            params={"target": target},
        ),
        WorkflowStep(
            index=1,
            action="get_events",
            skill="monitor",
            tool="get_events",
            params={"hours": 1, "severity": "critical", "target": target},
        ),
        WorkflowStep(
            index=2,
            action="require_approval",
            skill="pilot",
            tool="approve",
            params={"message": f"Alert '{alert_name}' on '{alert_entity}'. Acknowledge and clear?"},
        ),
        WorkflowStep(
            index=3,
            action="acknowledge",
            skill="aiops",
            tool="acknowledge_vcenter_alarm",
            params={"entity_name": alert_entity, "alarm_name": alert_name, "target": target},
        ),
    ]

    return Workflow(
        id=new_workflow_id(),
        workflow_type="incident_response",
        state=WorkflowState.PENDING,
        steps=steps,
        params={
            "alert_entity": alert_entity,
            "alert_name": alert_name,
            "target": target,
        },
        created_at=now,
        updated_at=now,
    )


def plan_and_approve(
    operations: list[dict[str, Any]],
    target: str = "",
    description: str = "",
) -> Workflow:
    """Wrap aiops Plan→Apply with an approval gate.

    Uses aiops's existing vm_create_plan / vm_apply_plan / vm_rollback_plan
    but inserts a human approval step between plan creation and execution.

    This is the bridge between aiops's single-skill batch operations and
    pilot's approval-gated workflows.

    Steps:
      1. Create plan via aiops (validates operations, generates rollback mapping)
      2. Await human approval (show plan summary)
      3. Apply plan via aiops (execute step-by-step)

    On failure at step 3, the workflow exposes aiops's rollback capability.

    Args:
        operations: List of operation dicts for vm_create_plan. Each has
            "action" key plus action-specific params. Allowed actions:
            power_on, power_off, reset, clone, deploy_ova, deploy_template,
            linked_clone, create_snapshot, delete_snapshot, revert_snapshot, etc.
        target: vCenter target name.
        description: Human-readable description of what this batch does.

    Example:
        operations=[
            {"action": "power_off", "vm_name": "db01"},
            {"action": "revert_snapshot", "vm_name": "db01", "snapshot_name": "baseline"},
            {"action": "power_on", "vm_name": "db01"},
        ]
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    vm_names = list({op.get("vm_name", "?") for op in operations if "vm_name" in op})
    desc = description or f"Batch operation on {', '.join(vm_names)} ({len(operations)} steps)"

    steps = [
        WorkflowStep(
            index=0,
            action="create_plan",
            skill="aiops",
            tool="vm_create_plan",
            params={"operations": operations, "target": target},
        ),
        WorkflowStep(
            index=1,
            action="require_approval",
            skill="pilot",
            tool="approve",
            params={"message": f"Plan ready: {desc}. Review and approve?"},
        ),
        WorkflowStep(
            index=2,
            action="apply_plan",
            skill="aiops",
            tool="vm_apply_plan",
            params={"plan_id": "__from_step_0__", "target": target},
            rollback_tool="vm_rollback_plan",
            rollback_params={"plan_id": "__from_step_0__", "target": target},
        ),
    ]

    return Workflow(
        id=new_workflow_id(),
        workflow_type="plan_and_approve",
        state=WorkflowState.PENDING,
        steps=steps,
        params={
            "operations": operations,
            "description": desc,
            "vm_names": vm_names,
            "target": target,
        },
        created_at=now,
        updated_at=now,
    )


def compliance_scan(
    target: str = "",
    check_alarms: bool = True,
    check_capacity: bool = True,
) -> Workflow:
    """Periodic compliance scan — collect health data, report, and flag issues.

    Steps:
      1. Check active alarms (monitor)
      2. Check capacity remaining (aria)
      3. Collect anomalies (aria)
      4. Generate compliance report summary

    All steps are read-only — no approval gate needed.

    Args:
        target: vCenter/Aria target name.
        check_alarms: Include alarm check (default True).
        check_capacity: Include capacity check (default True).
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    steps = []
    idx = 0

    if check_alarms:
        steps.append(WorkflowStep(
            index=idx, action="check_alarms", skill="monitor",
            tool="get_alarms", params={"target": target},
        ))
        idx += 1

    if check_capacity:
        steps.append(WorkflowStep(
            index=idx, action="check_capacity", skill="aria",
            tool="get_capacity_overview", params={"target": target},
        ))
        idx += 1

    steps.append(WorkflowStep(
        index=idx, action="check_anomalies", skill="aria",
        tool="list_anomalies", params={"target": target},
    ))

    return Workflow(
        id=new_workflow_id(),
        workflow_type="compliance_scan",
        state=WorkflowState.PENDING,
        steps=steps,
        params={"target": target, "check_alarms": check_alarms, "check_capacity": check_capacity},
        created_at=now,
        updated_at=now,
    )


BUILTIN_TEMPLATES = {
    "clone_and_test": clone_and_test,
    "incident_response": incident_response,
    "plan_and_approve": plan_and_approve,
    "compliance_scan": compliance_scan,
}


def get_all_templates() -> dict[str, Any]:
    """Return built-in + user-defined custom templates.

    Custom templates from ~/.vmware/workflows/*.yaml are loaded on each call
    (supports hot-reload — drop a YAML, immediately available).
    """
    from vmware_pilot.custom_loader import load_custom_templates

    all_templates = dict(BUILTIN_TEMPLATES)
    custom = load_custom_templates()
    # Custom templates can override built-ins (user takes precedence)
    all_templates.update(custom)
    return all_templates


# Backward compat — TEMPLATES is still available but prefers get_all_templates()
TEMPLATES = BUILTIN_TEMPLATES
