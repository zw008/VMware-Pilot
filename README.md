# VMware Pilot

Multi-step workflow orchestration for VMware MCP skills — state machine, approval gates, audit trail.

## Install

```bash
pip install vmware-pilot
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `plan_workflow` | Generate execution plan, returns workflow_id |
| `run_workflow` | Execute workflow, pauses at approval gates |
| `get_workflow_status` | Query state + diff report + audit log |
| `approve` | Human approval, continue execution |
| `rollback` | Abort and rollback at any stage |
