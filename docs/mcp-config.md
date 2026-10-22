# Agent Kanban - MCP 配置说明

让其他 agent（opencode v2 / Claude Code 等 MCP 客户端）通过 MCP 接入看板、协同工作的安装与配置说明。与 `docs/PRD.md` v3.2 第 4 节（工具面）一致。

## 概览

| 项 | 值 |
|---|---|
| 传输 | stdio（M0 起）；HTTP/SSE 形态 M1 前不做 |
| 工具面 | 12 个（见 PRD 4.1：list_tasks / get_task_detail / claim_task / add_subtask / update_subtask / add_milestone / update_milestone / add_record / update_progress / request_review / mark_blocked / list_awaiting） |
| 数据 | 本地 SQLite（默认 127.0.0.1 绑定；非 localhost 绑定必须带 token） |
| 角色 | 单用户、无 RBAC；agent 面与人面（CLI/REST）分离 |

## 1. 服务启动命令（契约级）

实现后以 `pyproject.toml` 的 console entry point 为准（Spike 内定稿），目标形态：

```sh
uv run agent-kanban mcp          # 启动 MCP server（stdio）
uv run agent-kanban serve        # 启动 REST/人面 API（M0）
```

MCP stdio 模式由客户端拉起进程，无需常驻。默认数据库路径与端口在 `AGENT_KANBAN_DB` / 配置文件中声明。

## 2. opencode v2

### 2.1 手工配置（推荐，可保留注释）

`opencode.jsonc`（项目级）或 `~/.config/opencode/opencode.jsonc`（全局）：

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "agent-kanban": {
        "type": "local",
        "command": ["uv", "run", "agent-kanban", "mcp"],
        "cwd": "/path/to/agentic-kanban",
        "environment": {
          "AGENT_KANBAN_DB": "/path/to/kanban.db"
        }
      }
    }
  }
}
```

字段说明（opencode v2）：`type` 必须 `"local"`（stdio）；`command` = 可执行文件 + 参数；`cwd` = 进程工作目录；`environment` = 追加的环境变量；`disabled: true` 可保留配置但不连接。Code Mode 默认开启，工具出现在 Code Mode 工具集内。

### 2.2 CLI 方式

```sh
opencode mcp add agent-kanban -- uv run agent-kanban mcp
opencode mcp add agent-kanban --env AGENT_KANBAN_DB=/path/to/kanban.db -- uv run agent-kanban mcp
opencode mcp list     # 应显示 connected
```

### 2.3 工具命名与权限

opencode 把工具命名为 `<server>_<tool>`，即 `agent_kanban_claim_task`、`agent_kanban_request_review` 等。可按需用权限隐藏/禁用：

```jsonc
{
  "permissions": [
    { "action": "agent_kanban_*", "resource": "*", "effect": "allow" }
  ]
}
```

### 2.4 会话标识（外部引用）

opencode 在每次工具调用经 `CallToolRequest.params._meta["ai.opencode/sessionID"]` 传入当前会话 id（如 `ses_...`）。服务端将其作为**外部引用**归入审计链（PRD 5.1 中可信档），与系统观测的 conn id 区分。该 id 是请求元数据，不是工具参数，不用于鉴权。

## 3. Claude Code

`.mcp.json`（项目根）：

```json
{
  "mcpServers": {
    "agent-kanban": {
      "command": "uv",
      "args": ["run", "agent-kanban", "mcp"],
      "env": {
        "AGENT_KANBAN_DB": "/path/to/kanban.db"
      }
    }
  }
}
```

## 4. 其他通用 MCP 客户端

凡支持 stdio 的 MCP 客户端，等价配置为：

```json
{
  "mcpServers": {
    "agent-kanban": {
      "command": "uv",
      "args": ["run", "agent-kanban", "mcp"],
      "env": { "AGENT_KANBAN_DB": "/path/to/kanban.db" }
    }
  }
}
```

## 5. 环境变量

| 变量 | 默认 | 用途 |
|---|---|---|
| `AGENT_KANBAN_DB` | `~/.agent-kanban/kanban.db` | SQLite 文件路径（0600） |
| `AGENT_KANBAN_TOKEN` | 空 | 非 localhost 绑定时的访问令牌（绑定 localhost 时不需要） |

安全：默认只绑 127.0.0.1；改为非 localhost 绑定必须带 token，且服务启动告警（PRD 6）。

## 6. 验证

```sh
opencode mcp list                    # agent-kanban 显示 connected
# opencode 内 /mcps 查看连接状态
# 自检：让 agent 依次调 claim_task -> add_subtask -> request_review，看返回与错误码符合 PRD 4.3
```

## 7. 安装协同技能

仓库内 `skills/agent-kanban/` 是给 agent 的协同协议（认领/拆解/记录/交接纪律）。安装方式任选其一：

- 项目级：复制到 `.opencode/skills/agent-kanban/`（或 `.claude/skills/`、`.agents/skills/`）；
- 全局：复制到 `~/.config/opencode/skills/`；
- 或通过 opencode 配置声明额外技能目录：

```jsonc
{
  "skills": ["./skills"]
}
```

技能 id = 目录名 `agent-kanban`。模型在遇到 `agent_kanban_*` 工具或看板任务时自动发现并加载（SKILL.md 的 description 触发）。

## 8. 设计注记（实现时）

- MCP server 应在 initialize 时返回 instructions（如「认领前先 get_task_detail；request_review 必须附证据」），opencode 会注入到系统提示（见其 mcp-servers 文档 "Server instructions"）。
- 服务端从传输会话派生 actor（conn id），不接受工具参数传入；opencode 的 sessionID 只作外部引用（2.4）。
