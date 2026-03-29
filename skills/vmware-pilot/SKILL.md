---
name: vmware-pilot
description: >
  VMware workflow orchestration with approval gates. Use when user asks to
  "design a workflow", "create a multi-step operation", "clone and test before applying",
  "run an incident response", or needs cross-skill coordination with human approval.
  For single VM operations use vmware-aiops. For monitoring use vmware-monitor.
installer:
  kind: uv
  package: vmware-pilot
allowed-tools: [Bash]
---

# VMware Pilot

Multi-step workflow orchestration for VMware MCP skills — design, approve, execute, rollback.

**Companion Skills**: [vmware-aiops](../vmware-aiops/SKILL.md) (VM operations) | [vmware-monitor](../vmware-monitor/SKILL.md) (monitoring) | [vmware-nsx](../vmware-nsx/SKILL.md) (networking) | [vmware-aria](../vmware-aria/SKILL.md) (metrics/alerts)

## What This Skill Does

| Capability | Description |
|---|---|
| Workflow Design | Natural language goal → AI designs steps from 7 skills' 156 tools |
| Approval Gates | Pause execution for human review before destructive operations |
| State Persistence | SQLite-backed, survives restarts, supports resume from checkpoint |
| Rollback | Reverse completed steps in order if workflow fails |
| Custom Templates | Save workflows as YAML for reuse, hot-reload without restart |
| Compliance Scans | Read-only health/capacity/anomaly checks across skills |

## Quick Install

```bash
pip install vmware-pilot
# or
uvx --from vmware-pilot vmware-pilot-mcp
```

## When to Use This Skill

| Scenario | Use Pilot? | Why |
|---|---|---|
| "Clone VM, test, then apply to prod" | Yes | Multi-step + approval |
| "Power on a VM" | No, use aiops | Single operation |
| "Set up app network + firewall + VMs" | Yes | Cross-skill orchestration |
| "Check cluster health" | No, use monitor/aria | Single read-only query |
| "Diagnose and fix an alert" | Yes | incident_response template |
| "Run compliance check" | Yes | compliance_scan template |

## Skill Routing

| Need | Skill |
|---|---|
| VM lifecycle (power, clone, deploy) | vmware-aiops |
| Read-only monitoring | vmware-monitor |
| NSX networking | vmware-nsx |
| NSX security (DFW, groups) | vmware-nsx-security |
| Aria metrics/alerts/capacity | vmware-aria |
| Tanzu Kubernetes | vmware-vks |
| Storage (iSCSI, vSAN) | vmware-storage |
| **Multi-step orchestration** | **vmware-pilot** |

## Common Workflows

### 1. Design a Custom Workflow (Interactive)

```
User: "I need to set up a new app environment with networking and VMs"

AI calls: get_skill_catalog()          → see available tools
AI calls: design_workflow(goal="...")   → create draft
AI calls: update_draft(id, steps=[...]) → fill in steps
User reviews and confirms
AI calls: confirm_draft(id, save_as_template=True)
AI calls: run_workflow(id)             → execute with approval gates
```

### 2. Clone-and-Test (Built-in Template)

```
AI calls: plan_workflow("clone_and_test", {
    target_vm: "db01",
    change_spec: {memory_mb: 32768},
    target: "vcenter-prod"
})
AI calls: run_workflow(workflow_id)
→ Clone → Apply → Monitor → [Approval Gate] → Commit → Cleanup
```

### 3. Batch Operations with Approval

```
AI calls: plan_workflow("plan_and_approve", {
    operations: [
        {action: "power_off", vm_name: "db01"},
        {action: "revert_snapshot", vm_name: "db01", snapshot_name: "baseline"},
        {action: "power_on", vm_name: "db01"}
    ]
})
→ Create Plan → [Approval Gate] → Execute Plan (with auto-rollback on failure)
```

## MCP Tools (11)

| Category | Tool | Risk | Description |
|---|---|---|---|
| **Discovery** | `get_skill_catalog` | low | Available skills and tools for design |
| | `list_workflows` | low | Built-in + custom templates |
| **Design** | `design_workflow` | low | Natural language → draft |
| | `update_draft` | medium | Edit draft steps |
| | `confirm_draft` | medium | Finalize draft → ready to execute |
| **Execute** | `plan_workflow` | medium | Create from template |
| | `create_workflow` | medium | One-step custom creation |
| | `run_workflow` | medium | Execute (pauses at approval) |
| **Control** | `approve` | high | Human approval to continue |
| | `rollback` | high | Reverse completed steps |
| | `get_workflow_status` | low | State + audit log |

## Built-in Templates (4)

| Template | Steps | Approval | Skills Used |
|---|---|---|---|
| `clone_and_test` | 6 | Yes | aiops + monitor |
| `incident_response` | 4 | Yes | monitor + aiops |
| `plan_and_approve` | 3 | Yes | aiops |
| `compliance_scan` | 3 | No | monitor + aria |

## Custom Templates

Drop YAML files in `~/.vmware/workflows/` — pilot auto-loads them.

```yaml
# ~/.vmware/workflows/restart_cluster.yaml
name: restart_cluster
description: Rolling restart of database cluster
steps:
  - action: check_health
    skill: monitor
    tool: get_alarms
    params:
      target: "{{target}}"
  - action: stop_replica
    skill: aiops
    tool: vm_power_off
    params:
      vm_name: "{{replica_vm}}"
    rollback_tool: vm_power_on
    rollback_params:
      vm_name: "{{replica_vm}}"
  - action: require_approval
    skill: pilot
    tool: approve
    params:
      message: "Replica stopped. Proceed?"
  - action: restart_primary
    skill: aiops
    tool: vm_power_off
    params:
      vm_name: "{{primary_vm}}"
```

## Setup

No vCenter credentials needed — pilot orchestrates other skills that handle connections.

```json
{
  "mcpServers": {
    "vmware-pilot": {
      "command": "uvx",
      "args": ["--from", "vmware-pilot", "vmware-pilot-mcp"]
    }
  }
}
```

## License

MIT
