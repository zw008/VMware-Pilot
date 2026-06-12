"""Storage workflow templates — iSCSI target add + rescan + verify."""

from __future__ import annotations

from vmware_pilot.templates._common import (
    Workflow,
    WorkflowState,
    WorkflowStep,
    datetime,
    new_workflow_id,
    timezone,
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
