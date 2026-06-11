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


def network_segment_setup(
    segment_id: str,
    display_name: str,
    subnet: str,
    transport_zone_path: str,
    tier1_id: str = "",
    tier0_path: str = "",
    nat_source: str = "",
    nat_translated: str = "",
    dfw_policy_id: str = "",
    target: str = "",
) -> Workflow:
    """Set up a complete app network: segment + gateway + NAT + firewall.

    Steps:
      1. Create Tier-1 gateway (if tier1_id provided)
      2. Create network segment
      3. Create NAT rule (if nat_source provided)
      4. Create DFW policy (if dfw_policy_id provided)
      5. Approve before finalizing
      6. Verify segment connectivity
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    steps: list[WorkflowStep] = []
    idx = 0

    if tier1_id:
        steps.append(WorkflowStep(
            index=idx, action="create_gateway", skill="nsx",
            tool="create_tier1_gateway",
            params={"tier1_id": tier1_id, "display_name": f"{display_name}-gw",
                    "tier0_path": tier0_path, "target": target},
            rollback_tool="delete_tier1_gateway",
            rollback_params={"tier1_id": tier1_id, "target": target},
        ))
        idx += 1

    steps.append(WorkflowStep(
        index=idx, action="create_segment", skill="nsx",
        tool="create_segment",
        params={"segment_id": segment_id, "display_name": display_name,
                "transport_zone_path": transport_zone_path, "subnet": subnet, "target": target},
        rollback_tool="delete_segment",
        rollback_params={"segment_id": segment_id, "target": target},
    ))
    idx += 1

    if nat_source and nat_translated and tier1_id:
        steps.append(WorkflowStep(
            index=idx, action="create_nat", skill="nsx",
            tool="create_nat_rule",
            params={"tier1_id": tier1_id, "rule_id": f"{segment_id}-snat",
                    "action": "SNAT", "source_network": nat_source,
                    "translated_network": nat_translated, "target": target},
            rollback_tool="delete_nat_rule",
            rollback_params={"tier1_id": tier1_id, "rule_id": f"{segment_id}-snat", "target": target},
        ))
        idx += 1

    if dfw_policy_id:
        steps.append(WorkflowStep(
            index=idx, action="create_firewall", skill="nsx-security",
            tool="create_dfw_policy",
            params={"policy_id": dfw_policy_id, "display_name": f"{display_name}-policy", "target": target},
            rollback_tool="delete_dfw_policy",
            rollback_params={"policy_id": dfw_policy_id, "target": target},
        ))
        idx += 1

    steps.append(WorkflowStep(
        index=idx, action="require_approval", skill="pilot", tool="approve",
        params={"message": f"Network '{display_name}' created. Verify and finalize?"},
    ))
    idx += 1

    steps.append(WorkflowStep(
        index=idx, action="verify", skill="nsx",
        tool="list_segments", params={"target": target},
    ))

    return Workflow(
        id=new_workflow_id(), workflow_type="network_segment_setup",
        state=WorkflowState.PENDING, steps=steps,
        params={"segment_id": segment_id, "display_name": display_name, "target": target},
        created_at=now, updated_at=now,
    )


def vks_cluster_deploy(
    namespace_name: str,
    cluster_id: str,
    storage_policy: str,
    tkc_name: str,
    k8s_version: str,
    vm_class: str = "best-effort-medium",
    worker_count: int = 3,
    target: str = "",
) -> Workflow:
    """Deploy a complete VKS environment: namespace + TKC cluster + verify.

    Steps:
      1. Create vSphere Namespace
      2. Approve before cluster creation
      3. Create TKC cluster
      4. Verify cluster health
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    steps = [
        WorkflowStep(
            index=0, action="create_namespace", skill="vks",
            tool="create_namespace",
            params={"name": namespace_name, "cluster_id": cluster_id,
                    "storage_policy": storage_policy, "dry_run": False, "target": target},
            rollback_tool="delete_namespace",
            rollback_params={"name": namespace_name, "confirmed": True, "dry_run": False, "target": target},
        ),
        WorkflowStep(
            index=1, action="require_approval", skill="pilot", tool="approve",
            params={"message": f"Namespace '{namespace_name}' created. Deploy TKC cluster '{tkc_name}'?"},
        ),
        WorkflowStep(
            index=2, action="create_tkc", skill="vks",
            tool="create_tkc_cluster",
            params={"name": tkc_name, "namespace": namespace_name, "k8s_version": k8s_version,
                    "vm_class": vm_class, "worker_count": worker_count,
                    "dry_run": False, "target": target},
            rollback_tool="delete_tkc_cluster",
            rollback_params={"name": tkc_name, "namespace": namespace_name,
                             "confirmed": True, "dry_run": False, "target": target},
        ),
        WorkflowStep(
            index=3, action="verify_cluster", skill="vks",
            tool="get_tkc_cluster",
            params={"name": tkc_name, "namespace": namespace_name, "target": target},
        ),
    ]

    return Workflow(
        id=new_workflow_id(), workflow_type="vks_cluster_deploy",
        state=WorkflowState.PENDING, steps=steps,
        params={"namespace": namespace_name, "tkc_name": tkc_name, "target": target},
        created_at=now, updated_at=now,
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


def storage_expansion(
    host_name: str,
    iscsi_address: str,
    iscsi_port: int = 3260,
    target: str = "",
) -> Workflow:
    """Storage expansion: add iSCSI target → rescan → verify.

    Steps:
      1. Check current iSCSI status
      2. Enable iSCSI adapter (if not enabled)
      3. Approve before adding target
      4. Add iSCSI target
      5. Rescan storage
      6. Verify new datastores visible
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    steps = [
        WorkflowStep(
            index=0, action="check_iscsi_status", skill="storage",
            tool="storage_iscsi_status",
            params={"host_name": host_name, "target": target},
        ),
        WorkflowStep(
            index=1, action="enable_iscsi", skill="storage",
            tool="storage_iscsi_enable",
            params={"host_name": host_name, "target": target},
        ),
        WorkflowStep(
            index=2, action="require_approval", skill="pilot", tool="approve",
            params={"message": f"Add iSCSI target {iscsi_address}:{iscsi_port} to '{host_name}'. Approve?"},
        ),
        WorkflowStep(
            index=3, action="add_iscsi_target", skill="storage",
            tool="storage_iscsi_add_target",
            params={"host_name": host_name, "address": iscsi_address,
                    "port": iscsi_port, "target": target},
            rollback_tool="storage_iscsi_remove_target",
            rollback_params={"host_name": host_name, "address": iscsi_address,
                             "port": iscsi_port, "target": target},
        ),
        WorkflowStep(
            index=4, action="rescan_storage", skill="storage",
            tool="storage_rescan",
            params={"host_name": host_name, "target": target},
        ),
        WorkflowStep(
            index=5, action="verify_datastores", skill="storage",
            tool="list_all_datastores", params={"target": target},
        ),
    ]

    return Workflow(
        id=new_workflow_id(), workflow_type="storage_expansion",
        state=WorkflowState.PENDING, steps=steps,
        params={"host_name": host_name, "iscsi_address": iscsi_address, "target": target},
        created_at=now, updated_at=now,
    )


def baseline_capture(
    target: str = "",
    include_vms: bool = True,
    include_hosts: bool = True,
    include_network: bool = True,
    include_storage: bool = True,
    include_alarms: bool = True,
    baseline_name: str = "",
) -> Workflow:
    """Capture current infrastructure state as a baseline snapshot.

    Collects configuration from all relevant skills and stores as JSON
    in ~/.vmware/baselines/. Use baseline_audit to compare later.

    Steps:
      1. Collect VM inventory (monitor)
      2. Collect host inventory (monitor)
      3. Collect network segments (nsx)
      4. Collect storage/datastores (storage)
      5. Collect active alarms (monitor)
      6. Save baseline to ~/.vmware/baselines/{name}.json

    Args:
        target: vCenter target name.
        include_vms: Capture VM configurations.
        include_hosts: Capture ESXi host configurations.
        include_network: Capture NSX segment/gateway state.
        include_storage: Capture datastore/vSAN state.
        include_alarms: Capture current alarm state.
        baseline_name: Name for this baseline (default: auto-generated with timestamp).
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    name = baseline_name or f"baseline-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    steps: list[WorkflowStep] = []
    idx = 0

    if include_vms:
        steps.append(WorkflowStep(
            index=idx, action="capture_vms", skill="monitor",
            tool="list_virtual_machines", params={"target": target},
        ))
        idx += 1

    if include_hosts:
        steps.append(WorkflowStep(
            index=idx, action="capture_hosts", skill="monitor",
            tool="list_esxi_hosts", params={"target": target},
        ))
        idx += 1

    if include_network:
        steps.append(WorkflowStep(
            index=idx, action="capture_segments", skill="nsx",
            tool="list_segments", params={"target": target},
        ))
        idx += 1

    if include_storage:
        steps.append(WorkflowStep(
            index=idx, action="capture_datastores", skill="storage",
            tool="list_all_datastores", params={"target": target},
        ))
        idx += 1

    if include_alarms:
        steps.append(WorkflowStep(
            index=idx, action="capture_alarms", skill="monitor",
            tool="get_alarms", params={"target": target},
        ))
        idx += 1

    return Workflow(
        id=new_workflow_id(), workflow_type="baseline_capture",
        state=WorkflowState.PENDING, steps=steps,
        params={
            "baseline_name": name,
            "baseline_path": f"~/.vmware/baselines/{name}.json",
            "target": target,
            "include_vms": include_vms,
            "include_hosts": include_hosts,
            "include_network": include_network,
            "include_storage": include_storage,
            "include_alarms": include_alarms,
        },
        created_at=now, updated_at=now,
    )


def baseline_audit(
    baseline_name: str = "latest",
    target: str = "",
    include_vms: bool = True,
    include_hosts: bool = True,
    include_network: bool = True,
    include_storage: bool = True,
) -> Workflow:
    """Audit current state against a saved baseline — detect configuration drift.

    Collects current state using the same tools as baseline_capture,
    then compares with the saved baseline. Differences are reported as drift items.

    Steps:
      1. Collect current VM inventory
      2. Collect current host inventory
      3. Collect current network state
      4. Collect current storage state
      5. Compare against saved baseline (results in diff_report)

    Args:
        baseline_name: Name of the baseline to compare against (default: "latest").
        target: vCenter target name.
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    steps: list[WorkflowStep] = []
    idx = 0

    if include_vms:
        steps.append(WorkflowStep(
            index=idx, action="current_vms", skill="monitor",
            tool="list_virtual_machines", params={"target": target},
        ))
        idx += 1

    if include_hosts:
        steps.append(WorkflowStep(
            index=idx, action="current_hosts", skill="monitor",
            tool="list_esxi_hosts", params={"target": target},
        ))
        idx += 1

    if include_network:
        steps.append(WorkflowStep(
            index=idx, action="current_segments", skill="nsx",
            tool="list_segments", params={"target": target},
        ))
        idx += 1

    if include_storage:
        steps.append(WorkflowStep(
            index=idx, action="current_datastores", skill="storage",
            tool="list_all_datastores", params={"target": target},
        ))
        idx += 1

    # Capacity check for context
    steps.append(WorkflowStep(
        index=idx, action="check_anomalies", skill="aria",
        tool="list_anomalies", params={"target": target},
    ))

    return Workflow(
        id=new_workflow_id(), workflow_type="baseline_audit",
        state=WorkflowState.PENDING, steps=steps,
        params={
            "baseline_name": baseline_name,
            "baseline_path": f"~/.vmware/baselines/{baseline_name}.json",
            "target": target,
        },
        created_at=now, updated_at=now,
    )


def baseline_remediate(
    drift_items: list[dict[str, Any]],
    target: str = "",
) -> Workflow:
    """Remediate configuration drifts detected by baseline_audit.

    Takes a list of drift items (from audit results) and generates
    remediation steps with approval gates.

    Each drift_item: {type, resource, expected, actual, action, skill, tool, params}

    Steps:
      1. Review drift summary
      2. Approve remediation
      3. Execute remediation steps (one per drift item)
      4. Re-audit to verify fixes

    Args:
        drift_items: List of drift items to remediate. Each must have:
            action (str), skill (str), tool (str), params (dict).
            Optional: resource (str), rollback_tool (str), rollback_params (dict).
        target: vCenter target name.
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    steps: list[WorkflowStep] = []
    idx = 0

    # Pre-check: current alarms
    steps.append(WorkflowStep(
        index=idx, action="pre_check_alarms", skill="monitor",
        tool="get_alarms", params={"target": target},
    ))
    idx += 1

    # Approval before remediation
    resource_names = [d.get("resource", "unknown") for d in drift_items]
    steps.append(WorkflowStep(
        index=idx, action="require_approval", skill="pilot", tool="approve",
        params={"message": f"Remediate {len(drift_items)} drift(s): {', '.join(resource_names[:5])}{'...' if len(resource_names) > 5 else ''}. Proceed?"},
    ))
    idx += 1

    # One step per drift item
    for i, item in enumerate(drift_items):
        steps.append(WorkflowStep(
            index=idx,
            action=f"fix_{item.get('resource', f'item_{i}')}",
            skill=item.get("skill", "aiops"),
            tool=item.get("tool", "vm_create_plan"),
            params=item.get("params", {}),
            rollback_tool=item.get("rollback_tool", ""),
            rollback_params=item.get("rollback_params", {}),
        ))
        idx += 1

    # Post-fix verification
    steps.append(WorkflowStep(
        index=idx, action="post_verify", skill="monitor",
        tool="get_alarms", params={"target": target},
    ))

    return Workflow(
        id=new_workflow_id(), workflow_type="baseline_remediate",
        state=WorkflowState.PENDING, steps=steps,
        params={"drift_count": len(drift_items), "target": target},
        created_at=now, updated_at=now,
    )


def investigate_alert(
    alert_entity: str,
    alert_name: str = "",
    deep_dive: bool = False,
    target: str = "",
) -> Workflow:
    """Causal-chain root-cause investigation per investigation-protocol.md.

    Encodes the four-criteria root cause completeness loop from the Enterprise
    Harness Engineering framework as a pilot workflow.

    Stage 1 — parallel-group "round1-gather":
        Fetch alarms, events, and Aria alerts/metrics for the affected entity
        concurrently. All three are L1/L2 read-only and independent.
    Stage 2 — synthesis checkpoint:
        Pause for the AI agent to apply the four criteria
        (falsifiability / sufficiency / necessity / mechanism) and decide
        whether the root cause is complete.
    Stage 3 (only when ``deep_dive=True``) — parallel-group "round2-gather":
        Broader evidence: anomalies, capacity context, recent alerts in the
        same cluster. Used when round 1 fails the necessity or mechanism check.
    Stage 4 (only when ``deep_dive=True``) — final synthesis checkpoint.

    The agent is responsible for producing the structured report (root cause
    plus four-criteria evidence). Pilot only orchestrates the data gathering
    and the human-approval gates.

    Args:
        alert_entity: Resource that triggered the alert (VM name, host, cluster).
        alert_name: Optional human-readable alert label, surfaced in approval prompts.
        deep_dive: If True, append a second round of broader gathering and a
            second synthesis checkpoint (max three rounds total — a third would
            require a follow-up workflow).
        target: vCenter / Aria target identifier; defaults to the first
            configured target on each skill.
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    label = alert_name or alert_entity

    round1 = [
        WorkflowStep(
            index=0, action="gather_alarms",
            skill="monitor", tool="list_alarms",
            params={"entity_name": alert_entity, "target": target},
        ),
        WorkflowStep(
            index=1, action="gather_events",
            skill="monitor", tool="list_events",
            params={"hours": 2, "entity_name": alert_entity, "target": target},
        ),
        WorkflowStep(
            index=2, action="gather_aria_alerts",
            skill="aria", tool="list_alerts",
            params={"resource_name": alert_entity, "target": target},
        ),
    ]
    parallel_group("round1-gather", round1)

    checkpoint1 = WorkflowStep(
        index=3, action="require_approval",
        skill="pilot", tool="approve",
        params={
            "message": (
                f"Round 1 evidence gathered for '{label}'. "
                "Apply the four-criteria check from references/investigation-protocol.md: "
                "(1) falsifiability, (2) sufficiency, (3) necessity, (4) mechanism. "
                "APPROVE if root cause is complete and you are ready to write the report. "
                "REJECT to escalate or relaunch with deep_dive=True."
            ),
        },
    )

    steps = round1 + [checkpoint1]

    if deep_dive:
        round2 = [
            WorkflowStep(
                index=4, action="gather_anomalies",
                skill="aria", tool="list_anomalies",
                params={"resource_name": alert_entity, "target": target},
            ),
            WorkflowStep(
                index=5, action="gather_capacity",
                skill="aria", tool="capacity_overview",
                params={"resource_name": alert_entity, "target": target},
            ),
            WorkflowStep(
                index=6, action="gather_recent_alerts",
                skill="aria", tool="list_alerts",
                params={"hours": 24, "target": target},
            ),
        ]
        parallel_group("round2-gather", round2)

        checkpoint2 = WorkflowStep(
            index=7, action="require_approval",
            skill="pilot", tool="approve",
            params={
                "message": (
                    f"Round 2 evidence gathered for '{label}'. "
                    "Re-apply the four-criteria check. "
                    "APPROVE if root cause is now complete. "
                    "REJECT and escalate if a third round is needed — "
                    "the protocol caps at three rounds before human handoff."
                ),
            },
        )

        steps += round2 + [checkpoint2]

    return Workflow(
        id=new_workflow_id(),
        workflow_type="investigate_alert",
        state=WorkflowState.PENDING,
        steps=steps,
        params={
            "alert_entity": alert_entity,
            "alert_name": alert_name,
            "deep_dive": deep_dive,
            "target": target,
        },
        created_at=now,
        updated_at=now,
    )


BUILTIN_TEMPLATES = {
    "clone_and_test": clone_and_test,
    "incident_response": incident_response,
    "investigate_alert": investigate_alert,
    "plan_and_approve": plan_and_approve,
    "compliance_scan": compliance_scan,
    "network_segment_setup": network_segment_setup,
    "vks_cluster_deploy": vks_cluster_deploy,
    "rolling_restart": rolling_restart,
    "capacity_expansion": capacity_expansion,
    "disaster_recovery": disaster_recovery,
    "patch_deployment": patch_deployment,
    "storage_expansion": storage_expansion,
    "baseline_capture": baseline_capture,
    "baseline_audit": baseline_audit,
    "baseline_remediate": baseline_remediate,
}


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
        raise ValueError("group_id must be non-empty")
    for s in steps:
        s.group_id = group_id
    return steps


def get_all_templates() -> dict[str, Any]:
    """Return built-in + user-defined custom templates.

    Custom templates from ~/.vmware/workflows/*.yaml are loaded on each call
    (supports hot-reload — drop a YAML, immediately available).
    """
    import logging

    from vmware_pilot.custom_loader import load_custom_templates

    all_templates = dict(BUILTIN_TEMPLATES)
    custom = load_custom_templates()
    # Custom templates can override built-ins (user takes precedence) — but
    # warn loudly so a stray YAML cannot silently replace a vetted built-in.
    shadowed = sorted(set(custom) & set(BUILTIN_TEMPLATES))
    if shadowed:
        logging.getLogger("vmware-pilot.templates").warning(
            "Custom workflow YAML shadows built-in template(s) %s — the "
            "custom version in ~/.vmware/workflows/ takes precedence. "
            "Rename the YAML file(s) if this is unintentional.",
            ", ".join(shadowed),
        )
    all_templates.update(custom)
    return all_templates


# Backward compat — TEMPLATES is still available but prefers get_all_templates()
TEMPLATES = BUILTIN_TEMPLATES
