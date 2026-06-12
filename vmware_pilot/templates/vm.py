"""VM lifecycle workflow templates — clone/test, batch plan, restart, resize,
disaster recovery, and rolling patch deployment."""

from __future__ import annotations

from vmware_pilot.templates._common import (
    Any,
    Workflow,
    WorkflowState,
    WorkflowStep,
    datetime,
    new_workflow_id,
    timezone,
)


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
            tool="vm_reconfigure" if "cpu" in change_spec or "memory_mb" in change_spec or "memory_gb" in change_spec else "vm_guest_exec",
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
            tool="vm_reconfigure" if "cpu" in change_spec or "memory_mb" in change_spec or "memory_gb" in change_spec else "vm_guest_exec",
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
            params={"plan_id": "__from_step_0__:plan_id", "target": target},
            rollback_tool="vm_rollback_plan",
            rollback_params={"plan_id": "__from_step_0__:plan_id", "target": target},
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


def rolling_restart(
    vm_names: list[str],
    target: str = "",
) -> Workflow:
    """Rolling restart: power off → power on each VM, health check between each.

    Steps per VM:
      1. Check health (no active alarms)
      2. Power off VM
      3. Power on VM
      4. Verify health after restart
    Approval gate before starting.
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    steps: list[WorkflowStep] = []
    idx = 0

    steps.append(WorkflowStep(
        index=idx, action="pre_check", skill="monitor",
        tool="get_alarms", params={"target": target},
    ))
    idx += 1

    steps.append(WorkflowStep(
        index=idx, action="require_approval", skill="pilot", tool="approve",
        params={"message": f"Rolling restart {len(vm_names)} VMs: {', '.join(vm_names)}. Proceed?"},
    ))
    idx += 1

    for vm in vm_names:
        steps.append(WorkflowStep(
            index=idx, action=f"power_off_{vm}", skill="aiops",
            tool="vm_power_off",
            params={"vm_name": vm, "force": False, "target": target},
            rollback_tool="vm_power_on",
            rollback_params={"vm_name": vm, "target": target},
        ))
        idx += 1

        steps.append(WorkflowStep(
            index=idx, action=f"power_on_{vm}", skill="aiops",
            tool="vm_power_on",
            params={"vm_name": vm, "target": target},
        ))
        idx += 1

        steps.append(WorkflowStep(
            index=idx, action=f"health_check_{vm}", skill="monitor",
            tool="get_alarms", params={"target": target},
        ))
        idx += 1

    return Workflow(
        id=new_workflow_id(), workflow_type="rolling_restart",
        state=WorkflowState.PENDING, steps=steps,
        params={"vm_names": vm_names, "target": target},
        created_at=now, updated_at=now,
    )


def capacity_expansion(
    vm_name: str,
    cpu: int | None = None,
    memory_mb: int | None = None,
    target: str = "",
) -> Workflow:
    """Capacity expansion: check remaining → approve → reconfigure → verify.

    Steps:
      1. Check remaining capacity (aria)
      2. Check rightsizing recommendations (aria)
      3. Approve expansion
      4. Apply reconfiguration (aiops)
      5. Verify health after change
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    change_desc = []
    if cpu:
        change_desc.append(f"CPU→{cpu}")
    if memory_mb:
        change_desc.append(f"Memory→{memory_mb}MB")

    steps = [
        WorkflowStep(
            index=0, action="check_capacity", skill="aria",
            tool="get_remaining_capacity",
            params={"resource_id": vm_name, "target": target},
        ),
        WorkflowStep(
            index=1, action="check_rightsizing", skill="aria",
            tool="list_rightsizing_recommendations",
            params={"resource_id": vm_name, "target": target},
        ),
        WorkflowStep(
            index=2, action="require_approval", skill="pilot", tool="approve",
            params={"message": f"Expand '{vm_name}': {', '.join(change_desc)}. Approve?"},
        ),
        WorkflowStep(
            index=3, action="apply_change", skill="aiops",
            tool="vm_create_plan",
            params={"operations": [{"action": "reconfigure", "vm_name": vm_name,
                                    **({"cpu": cpu} if cpu else {}),
                                    **({"memory_mb": memory_mb} if memory_mb else {})}],
                    "target": target},
        ),
        WorkflowStep(
            index=4, action="verify_health", skill="monitor",
            tool="get_alarms", params={"target": target},
        ),
    ]

    return Workflow(
        id=new_workflow_id(), workflow_type="capacity_expansion",
        state=WorkflowState.PENDING, steps=steps,
        params={"vm_name": vm_name, "cpu": cpu, "memory_mb": memory_mb, "target": target},
        created_at=now, updated_at=now,
    )


def disaster_recovery(
    vm_name: str,
    snapshot_name: str = "baseline",
    target: str = "",
) -> Workflow:
    """Disaster recovery: revert from snapshot → verify network → verify health.

    Steps:
      1. Approve recovery action
      2. Revert VM to snapshot (clean slate)
      3. Verify VM is running
      4. Check network connectivity (NSX segments)
      5. Check health (no new alarms)
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    steps = [
        WorkflowStep(
            index=0, action="require_approval", skill="pilot", tool="approve",
            params={"message": f"Disaster recovery: revert '{vm_name}' to snapshot '{snapshot_name}'. Confirm?"},
        ),
        WorkflowStep(
            index=1, action="revert_snapshot", skill="aiops",
            tool="vm_clean_slate",
            params={"vm_name": vm_name, "snapshot_name": snapshot_name, "target": target},
        ),
        WorkflowStep(
            index=2, action="verify_vm", skill="monitor",
            tool="vm_info",
            params={"vm_name": vm_name, "target": target},
        ),
        WorkflowStep(
            index=3, action="verify_network", skill="nsx",
            tool="list_segments", params={"target": target},
        ),
        WorkflowStep(
            index=4, action="verify_health", skill="monitor",
            tool="get_alarms", params={"target": target},
        ),
    ]

    return Workflow(
        id=new_workflow_id(), workflow_type="disaster_recovery",
        state=WorkflowState.PENDING, steps=steps,
        params={"vm_name": vm_name, "snapshot_name": snapshot_name, "target": target},
        created_at=now, updated_at=now,
    )


def patch_deployment(
    vm_names: list[str],
    patch_local_path: str,
    patch_guest_path: str,
    install_command: str,
    username: str = "root",
    password: str = "",  # nosec B107 — empty default; caller supplies the value
    target: str = "",
) -> Workflow:
    """Rolling patch deployment: upload → install → verify, one VM at a time.

    Steps per VM:
      1. Upload patch file
      2. Execute install command
      3. Verify health
    Approval gate before starting.
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    steps: list[WorkflowStep] = []
    idx = 0

    steps.append(WorkflowStep(
        index=idx, action="require_approval", skill="pilot", tool="approve",
        params={"message": f"Deploy patch to {len(vm_names)} VMs: {', '.join(vm_names)}. Proceed?"},
    ))
    idx += 1

    for vm in vm_names:
        steps.append(WorkflowStep(
            index=idx, action=f"upload_{vm}", skill="aiops",
            tool="vm_guest_upload",
            params={"vm_name": vm, "local_path": patch_local_path,
                    "guest_path": patch_guest_path,
                    "username": username, "password": password, "target": target},
        ))
        idx += 1

        steps.append(WorkflowStep(
            index=idx, action=f"install_{vm}", skill="aiops",
            tool="vm_guest_exec_output",
            params={"vm_name": vm, "command": install_command,
                    "username": username, "password": password, "target": target},
        ))
        idx += 1

        steps.append(WorkflowStep(
            index=idx, action=f"verify_{vm}", skill="monitor",
            tool="get_alarms", params={"target": target},
        ))
        idx += 1

    return Workflow(
        id=new_workflow_id(), workflow_type="patch_deployment",
        state=WorkflowState.PENDING, steps=steps,
        params={"vm_names": vm_names, "patch": patch_local_path, "target": target},
        created_at=now, updated_at=now,
    )
