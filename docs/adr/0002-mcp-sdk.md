# ADR 0002 - MCP SDK 选型（G4 登记）

状态: 已登记（2026-10-22，Spike T2.0；实测 mcp 2.3.0）
关联: docs/PRD.md §7.3 契约级要点、§11 未决项；docs/adr/0000-known-gaps.md G4
问题: MCP SDK 版本与接入形态（版本锁定、传输、鉴权模型）

## 裁决

- 版本: 锁定 `mcp>=2.3,<3`（pyproject 依赖约束）。
- 服务端 API: 用 `mcp.server.MCPServer`（`from mcp.server import MCPServer`）；`mcp.server.fastmcp.FastMCP` 在 2.x 已移除改名，禁用。工具注册 `server.add_tool(fn, name=..., title=..., description=...)`，启动 `server.run(transport='stdio')`。
- 传输: M0 仅 stdio（agent 面入口）；streamable-http 属 M1 未决（PRD §11，默认不做）。
- 鉴权模型: stdio 单机信任边界 = 发起进程；无 token/无网络面（PRD §6 的 token/localhost 绑定归 M0 安全面，MCP 侧不承担）。agent 身份经会话上下文（opencode `CallToolRequest.params._meta["ai.opencode/sessionID"]`）作为外部引用传递，服务端仅记录、不鉴权。
- 错误面: 业务错误经 `is_error` + structured content 返回，不依赖 HTTP 状态码（PRD §4.3）。

## 实测证据（mcp 2.3.0，本仓 .venv）

- `from mcp.server import MCPServer` 成功；`MCPServer.__init__(name, title, description, instructions, website_url, icons, version)`。
- `from mcp.server.fastmcp import FastMCP` 抛 ImportError（PRD 断言成立）。
- `MCPServer.add_tool(fn, name=None, title=None, description=None, ...)`；`MCPServer.run(transport='stdio', ...)` 默认 stdio。

## 生效与后续

- 生效点: 本 ADR 登记即闭合 G4（docs/adr/0000-known-gaps.md）。
- 后续: M1 若做 HTTP 传输（未决默认不做）需回本 ADR 增补传输与鉴权小节；MCP SDK 跨 2.x 破坏性升级（fastmcp 移除类）需先行回归 AC harness。
