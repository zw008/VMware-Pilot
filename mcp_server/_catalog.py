"""Static catalog of skills + tools used for custom workflow design.

Building-block reference surfaced by ``get_skill_catalog`` and ``design_workflow``.
"""

from __future__ import annotations

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
