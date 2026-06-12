"""Tanzu Kubernetes (VKS) workflow templates — namespace + TKC cluster deploy."""

from __future__ import annotations

from vmware_pilot.templates._common import (
    Workflow,
    WorkflowState,
    WorkflowStep,
    datetime,
    new_workflow_id,
    timezone,
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
