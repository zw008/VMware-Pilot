# VMware Pilot

> **作者**: Wei Zhou, VMware by Broadcom — wei-wz.zhou@broadcom.com
> 本项目由 VMware 工程师维护的社区项目，非 VMware 官方产品。
> VMware 官方开发者工具请访问 [developer.broadcom.com](https://developer.broadcom.com)。

[English](README.md) | 中文

多步骤工作流编排 — 跨 VMware MCP 技能的状态机、审批门控、审计日志。

> **配套技能**负责其他领域：
>
> | 技能 | 范围 | 安装 |
> |------|------|------|
> | **[vmware-aiops](https://github.com/zw008/VMware-AIops)** | VM 生命周期、部署、Guest Ops、集群 | `uv tool install vmware-aiops` |
> | **[vmware-monitor](https://github.com/zw008/VMware-Monitor)** | 只读：资源清单、健康检查、告警、事件 | `uv tool install vmware-monitor` |
> | **[vmware-storage](https://github.com/zw008/VMware-Storage)** | 数据存储、iSCSI、vSAN 管理 | `uv tool install vmware-storage` |
> | **[vmware-vks](https://github.com/zw008/VMware-VKS)** | Tanzu 命名空间、TKC 集群生命周期 | `uv tool install vmware-vks` |
> | **[vmware-nsx](https://github.com/zw008/VMware-NSX)** | NSX 网络：Segment、网关、NAT | `uv tool install vmware-nsx-mgmt` |
> | **[vmware-nsx-security](https://github.com/zw008/VMware-NSX-Security)** | DFW 防火墙规则、安全组 | `uv tool install vmware-nsx-security` |
> | **[vmware-aria](https://github.com/zw008/VMware-Aria)** | Aria Ops：指标、告警、容量 | `uv tool install vmware-aria` |
> | **[vmware-avi](https://github.com/zw008/VMware-AVI)** | AVI 负载均衡、Pool 管理、AKO K8s 运维 | `uv tool install vmware-avi` |

## 安装

```bash
uv tool install vmware-pilot
vmware-pilot mcp          # 启动 MCP server（stdio）
```

## MCP 工具（13 个 — 4 读 / 9 写）

| 工具 | 说明 |
|------|------|
| `get_skill_catalog` | 获取所有可用技能和工具（用于工作流设计） |
| `list_workflows` | 列出内置模板和自定义模板 |
| `review_workflow` | 执行前对已规划的工作流做合理性检查 |
| `design_workflow` | 自然语言目标 → 草稿工作流 |
| `update_draft` | 编辑草稿工作流的步骤 |
| `confirm_draft` | 确认草稿 → 可执行状态 |
| `plan_workflow` | 从模板创建执行计划，返回 workflow_id |
| `create_workflow` | 从步骤列表直接创建自定义工作流 |
| `run_workflow` | 执行工作流，在审批门控处暂停 |
| `get_workflow_status` | 查询状态 + 差异报告 + 审计日志 |
| `approve` | 人工审批，继续执行 |
| `rollback` | 中止并按逆序回滚已完成的步骤 |
| `cancel_workflow` | 取消工作流，置为终态 CANCELLED |

- **只读模式**（v1.8.0）—— 一个环境变量即可从 MCP 注册表移除全部 9 个编排类写工具（设计/编辑草稿/确认草稿、规划/创建、执行、审批、回滚、取消），只保留 4 个查询工具；本仓没有配置文件，环境变量是唯一开关，详见[只读模式](#只读模式)

## 内置模板（14 个）

| 模板 | 步骤数 | 审批 | 使用的技能 |
|------|:------:|:----:|-----------|
| `clone_and_test` | 6 | 是 | aiops, monitor |
| `incident_response` | 4 | 是 | monitor, aiops |
| `plan_and_approve` | 3 | 是 | aiops |
| `compliance_scan` | 3 | 否 | monitor, aria |
| `network_segment_setup` | 2-6 | 是 | nsx, nsx-security |
| `vks_cluster_deploy` | 4 | 是 | vks |
| `rolling_restart` | 2+3n | 是 | aiops, monitor |
| `capacity_expansion` | 5 | 是 | aria, aiops, monitor |
| `disaster_recovery` | 5 | 是 | aiops, monitor, nsx |
| `patch_deployment` | 1+3n | 是 | aiops, monitor |
| `storage_expansion` | 6 | 是 | storage |
| `baseline_capture` | 1-5 | 否 | monitor, nsx, storage |
| `baseline_audit` | 2-5 | 否 | monitor, nsx, storage, aria |
| `baseline_remediate` | 3+n | 是 | 按需 |

## MCP 配置

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

> 备用方式：`{"command": "uvx", "args": ["--from", "vmware-pilot", "vmware-pilot-mcp"]}` 同样可用，
> 但 `uvx` 每次启动都会重新到 PyPI 解析包，在有 TLS 中间人代理的企业网络下会失败
> （`invalid peer certificate: UnknownIssuer`）。上面的入口点走 PATH，完全不联网；
> 若必须用 `uvx`，请设置 `UV_NATIVE_TLS=true`。

## 只读模式

提示词约束只是建议——模型可以无视它。只读模式是结构性的：开启后，所有写工具会在启动时从 MCP 注册表中移除，`list_tools()` 根本不会列出它们——模型看不见的工具就无法调用。默认关闭；且为 fail-closed 设计：请求了只读模式但无法保证时，服务器直接拒绝启动。

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

**在本仓启用前请先读这一段。** vmware-pilot 是编排器，**编排本身就是它的写操作面**。13 个工具中有 9 个是写工具，且会被全部移除：

`plan_workflow`、`run_workflow`、`approve`、`rollback`、`cancel_workflow`、`create_workflow`、`design_workflow`、`update_draft`、`confirm_draft`

只剩 4 个读工具可用：

| 工具 | 只读模式下仍可用于 |
|------|-------------------|
| `list_workflows` | 浏览内置模板和自定义模板 |
| `get_skill_catalog` | 查看工作流可以调用哪些技能和工具 |
| `get_workflow_status` | 查询已有工作流的状态、差异报告和审计日志 |
| `review_workflow` | 在任何人执行之前对工作流定义做静态审查 |

也就是说，只读模式下的 pilot **无法创建、规划、执行、审批、回滚或取消任何工作流**，只能查看已经存在的工作流。需要说明的是：pilot 的写操作落在它自己的工作流数据库（`~/.vmware/workflows.db`）里，并不直接作用于 VMware 环境——它自身没有 vCenter 连接。之所以仍被归类为写工具，是因为 `run_workflow` 是工作流的派发点、`approve` 是放行它的闸门；真正的基础设施变更发生在下游，在目标技能自己的进程中，受该技能自己的只读开关约束。

因此，如果你开启家族级开关是为了保护 VMware 环境、同时仍想使用编排能力，那就让 pilot 保持可写、由下游技能来落实这道锁——按 skill 的变量优先于家族级变量：

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

优先级：按 skill 环境变量（`VMWARE_PILOT_READ_ONLY`）→ 家族环境变量（`VMWARE_READ_ONLY`）→ 默认关闭。与家族其他成员不同，vmware-pilot 不读取任何配置文件，**环境变量是唯一的开关**——不存在 `read_only:` 配置项。启动日志会列出被移除工具的完整清单。

## 审计与安全

所有操作通过 vmware-policy（`@vmware_tool` 装饰器）自动审计：
- 每个工具调用记录到 `~/.vmware/audit.db`（SQLite, WAL 模式）
- 策略规则通过 `~/.vmware/rules.yaml` 执行（拒绝规则、维护窗口、风险等级）
- 查看最近操作：`vmware-audit log --last 20`
- 查看被拒绝的操作：`vmware-audit log --status denied`

## 许可证

MIT
