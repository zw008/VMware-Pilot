<!-- mcp-name: io.github.zw008/vmware-pilot -->

# VMware Pilot

> **Author**: Wei Zhou, VMware by Broadcom — wei-wz.zhou@broadcom.com
> This is a community-driven project by a VMware engineer, not an official VMware product.
> For official VMware developer tools see [developer.broadcom.com](https://developer.broadcom.com).

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
uv tool install vmware-pilot
vmware-pilot mcp          # start the MCP server (stdio)
```

## MCP Tools (13 — 4 read, 9 write)

| Tool | Description |
|------|-------------|
| `get_skill_catalog` | List all available skills and tools for workflow design |
| `list_workflows` | List built-in and custom templates |
| `review_workflow` | Sanity-check a planned workflow before execution |
| `design_workflow` | Natural language goal → draft workflow |
| `update_draft` | Edit draft workflow steps |
| `confirm_draft` | Finalize draft → ready to execute |
| `plan_workflow` | Generate execution plan from template, returns workflow_id |
| `create_workflow` | Create custom workflow from step list |
| `run_workflow` | Execute workflow, pauses at approval gates |
| `get_workflow_status` | Query state + diff report + audit log |
| `approve` | Human approval, continue execution |
| `rollback` | Abort and rollback at any stage |
| `cancel_workflow` | Cancel a workflow — move it to the terminal CANCELLED state |

- **Read-only mode** (v1.8.0) — one env var strips all 9 orchestration write tools (design/update/confirm draft, plan/create, run, approve, rollback, cancel) from the MCP registry, leaving the 4 query tools; env vars are the only switch here, pilot has no config file — see [Read-Only Mode](#read-only-mode)

## MCP Configuration

```json
{
  "mcpServers": {
    "vmware-pilot": {
      "command": "vmware-pilot",
      "args": ["mcp"]
    }
  }
}
```

> Fallback: `{"command": "uvx", "args": ["--from", "vmware-pilot", "vmware-pilot-mcp"]}` still
> works, but `uvx` re-resolves against PyPI on every start and fails behind a TLS-inspecting
> corporate proxy (`invalid peer certificate: UnknownIssuer`). The installed entry point above
> touches the network zero times; set `UV_NATIVE_TLS=true` if you must use `uvx`.

## Read-Only Mode

A prompt instruction is advisory — a model can ignore it. Read-only mode is structural: turn it on and every write tool is removed from the MCP registry at startup, so `list_tools()` never offers them and the model cannot call what it cannot see. Off by default, and fail-closed: if the mode is requested but cannot be guaranteed, the server refuses to start.

```json
{
  "mcpServers": {
    "vmware-pilot": {
      "command": "vmware-pilot",
      "args": ["mcp"],
      "env": { "VMWARE_PILOT_READ_ONLY": "true" }
    }
  }
}
```

**Read this before enabling it here.** vmware-pilot is an orchestrator, so orchestration *is* its write surface. 9 of its 13 tools are writes, and all 9 are withheld:

`plan_workflow`, `run_workflow`, `approve`, `rollback`, `cancel_workflow`, `create_workflow`, `design_workflow`, `update_draft`, `confirm_draft`

Only the 4 read tools survive:

| Tool | Still available for |
|------|---------------------|
| `list_workflows` | Browsing built-in and custom templates |
| `get_skill_catalog` | Seeing which skills and tools a workflow could call |
| `get_workflow_status` | State, diff report and audit log of an existing workflow |
| `review_workflow` | Static review of a workflow definition before anyone runs it |

A read-only pilot therefore cannot author, plan, run, approve, roll back or cancel anything — it can only inspect workflows that already exist. Note that pilot's writes land in its own workflow database (`~/.vmware/workflows.db`), not on a VMware estate; it has no vCenter connection of its own. They are classified as writes because `run_workflow` is where a workflow is dispatched and `approve` is the gate that releases it — the infrastructure change happens downstream, in the target skill's process, under that skill's own read-only setting.

So if you set the family-wide switch to protect your estate but still want orchestration, keep pilot writable and let the downstream skills enforce the lock — the per-skill variable wins over the family one:

```json
{
  "mcpServers": {
    "vmware-pilot": {
      "command": "vmware-pilot",
      "args": ["mcp"],
      "env": { "VMWARE_READ_ONLY": "true", "VMWARE_PILOT_READ_ONLY": "false" }
    }
  }
}
```

Precedence: per-skill env (`VMWARE_PILOT_READ_ONLY`) → family env (`VMWARE_READ_ONLY`) → off. Unlike the other family members, vmware-pilot reads no config file, so the environment variables are the only switch — there is no `read_only:` config key. Startup logs list exactly which tools were withheld.

## License

MIT