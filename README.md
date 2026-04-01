# VMware Pilot

English | [中文](README-CN.md)

Multi-step workflow orchestration for VMware MCP skills — state machine, approval gates, audit trail.

> **Companion skills** handle everything else:
>
> | Skill | Scope | Install |
> |-------|-------|---------|
> | **[vmware-aiops](https://github.com/zw008/VMware-AIops)** | VM lifecycle, deployment, guest ops, cluster | `uv tool install vmware-aiops` |
> | **[vmware-monitor](https://github.com/zw008/VMware-Monitor)** | Read-only: inventory, health, alarms, events | `uv tool install vmware-monitor` |
> | **[vmware-storage](https://github.com/zw008/VMware-Storage)** | Datastores, iSCSI, vSAN management | `uv tool install vmware-storage` |
> | **[vmware-vks](https://github.com/zw008/VMware-VKS)** | Tanzu Namespaces, TKC cluster lifecycle | `uv tool install vmware-vks` |
> | **[vmware-nsx](https://github.com/zw008/VMware-NSX)** | NSX networking: segments, gateways, NAT | `uv tool install vmware-nsx-mgmt` |
> | **[vmware-nsx-security](https://github.com/zw008/VMware-NSX-Security)** | DFW firewall rules, security groups | `uv tool install vmware-nsx-security` |
> | **[vmware-aria](https://github.com/zw008/VMware-Aria)** | Aria Ops: metrics, alerts, capacity | `uv tool install vmware-aria` |
> | **[vmware-avi](https://github.com/zw008/VMware-AVI)** | AVI load balancing, pool management, AKO K8s ops | `uv tool install vmware-avi` |

## Install

```bash
pip install vmware-pilot
```

## MCP Tools (11)

| Tool | Description |
|------|-------------|
| `get_skill_catalog` | List all available skills and tools for workflow design |
| `list_workflows` | List built-in and custom templates |
| `design_workflow` | Natural language goal → draft workflow |
| `update_draft` | Edit draft workflow steps |
| `confirm_draft` | Finalize draft → ready to execute |
| `plan_workflow` | Generate execution plan from template, returns workflow_id |
| `create_workflow` | Create custom workflow from step list |
| `run_workflow` | Execute workflow, pauses at approval gates |
| `get_workflow_status` | Query state + diff report + audit log |
| `approve` | Human approval, continue execution |
| `rollback` | Abort and rollback at any stage |

## MCP Configuration

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
