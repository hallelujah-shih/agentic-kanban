# M1-1 Plan — MCP HTTP（streamable-http 挂载 FastAPI /mcp）

分支: `m1-1`（worktree `.worktree/m1-1/`，基 main @ ca5aeff）
档位: 全六门（D 对外契约：MCP HTTP 新 transport + ①归因语义 + ②信任边界延伸 /mcp）
规范锚: docs/adr/0005-m1-direction.md（MCP HTTP 做）+ PRD §4.1（双 transport）+ §4.3（错误码语义两 transport 一致）+ §5.1（归属）+ §6（安全 localhost+token）
依赖实测（主循环已探）: mcp 2.3.0 `MCPServer.streamable_http_app(*, streamable_http_path='/mcp', ...) -> Starlette`；客户端 `streamable_http_client(url, http_client=..., ...)`（mcp.client.streamable_http，需 httpx2，已装 2.16.0）；stdio 路径不变（cli.py mcp / MCP 工具面既有）

## 契约三锚

1. 规范逐字原文: ADR 0005（MCP HTTP 做，与 stdio 并存，同一 12 工具注册表，localhost 默认 + token 一致）；PRD §4.1 transport 注；PRD §4.3（错误返回 is_error + {code,message,task_id}，无 HTTP 码语义）；PRD §5.1（actor 服务端派生，不接受调用方传入）；PRD §6（非 localhost 需 token；token 校验 header/query 双通道）。
2. 代码锚点: src/agent_kanban/mcp/server.py（12 工具函数 + `_call` + `mcp_actor(ctx, CONN_ID)` 从 ctx.request_context.meta 取 `ai.opencode/sessionID`，无则 fallback 进程级 CONN_ID）；api/main.py（FastAPI + token 中间件 + lifespan + config.host()/port()）；services/identity.py `mcp_actor`。
3. 逐例期望: 真实 HTTP MCP 客户端经 /mcp 调用全部 12 工具可达；错误 is_error 语义与 stdio 逐码等价；写事件归属 actor_surface='mcp' + conn 服务端派生（HTTP 会话级，非进程级混同）；无 token 访问 /mcp 401；有 token 通过。

## 影响面

- ① 新对外契约命中（MCP HTTP transport 首次建立，/mcp 端点 + 归因语义）。
- ② 信任边界延伸命中（/mcp 入 token 中间件覆盖；localhost 默认）。
- ③ 不命中（无新增周期扫描）。
单向门处理：契约源自 ADR 0005（user 裁决）+ PRD 已审规格；本 plan 审 + 结果盲审 + AC oracle 兜底。

## 原子任务

| # | 任务 | 验证 | 期望 |
|---|---|---|---|
| M1-1.1 | api 集成：复用 mcp/server.py 的工具注册表，新建 MCPServer 实例挂载 `streamable_http_app` 到 /mcp（探明 FastAPI `app.mount` vs inner path 的正确组合；token 中间件须覆盖 mount 的 Starlette app）；`cli.py` 与既有 stdio MCP 不动 | harness: 无 token 访问 /mcp 401；有 token 200 | PRD 6 安全延伸；stdio 回归零 |
| M1-1.2 | 归因（HTTP transport）：actor conn 服务端派生——优先 client header（如 `X-Agent-Kanban-Conn`，客户端经 ClientMessageMetadata/httpx 头注入）或 MCP session id；mcp_actor 扩展 HTTP 场景；**不接受调用方传入 requirement 内字段**（PRD 5.1）；HTTP 与 stdio 的 conn 不得混同（进程级 CONN_ID 仅 stdio 用） | harness: HTTP 调用写事件，断言 events.actor_surface='mcp' + actor_conn 为该 HTTP 会话派生值（非 stdio CONN_ID）；两个不同 HTTP 客户端 conn 可区分 | 5.1 归属 + 判据3 可答 |
| M1-1.3 | harness（tests/ac_cases_f.py + run_ac 注册）：真实 uvicorn 子进程（复用 ac_lib REST harness 模式：env_for HOST/TOKEN/DB）+ `streamable_http_client` 真实调用全部 12 工具；错误路径逐条：无认领写 -> no_active_claim、request_review 缺证据 -> invalid_record、claim 排他 -> already_claimed、approve 非 CLAIMED -> illegal_state、缺 token -> 401（HTTP 层）；is_error 语义与 stdio 等价断言；红绿留档（red-4 -> green-4） | `uv run python tests/run_ac.py` 全绿 | 12 工具全可达 + 错误语义与 stdio 一致 |
| M1-1.4 | docs：docs/mcp-config.md 补 HTTP transport 配置段（URL /mcp、token 头、与 stdio 的选择场景、客户端示例）；ADR 0005 已含方向 | git ls-files tracked | 文档对齐 |

## oracle 纪律

- 断言逐字引自 PRD §4.3/§5.1/§6；HTTP 客户端真实（streamable_http_client + httpx2，非 mock/TestClient）；错误语义与 stdio 同库逐码对比。
- 反证位：每 AC 先红后绿留档；最强对抗变体 = 错误路径逐码 + 归因区分性（两客户端 conn 可分）。
- 既有 203 不回归（stdio/MCP/CLI/REST 全保绿）。

## 验证入口与 tier

- tier-0: `uv run python -m compileall -q src cli.py`
- tier-1: `uv run python tests/run_ac.py` 全绿
- tier-2（合并门槛）: tier-1 全绿 + mcp-config.md 更新 + git ls-files 全 tracked

## 不修清单

1. 不用 mcp 的 transport_security（JWT 模型）——走统一 token 中间件（PRD 6）。
2. 不做 SSE 旧 transport（MCP 已 deprecated；用 streamable-http）。
3. 不做会话持久化/多机部署（SDK 内存会话管理满足单机；会话超时 1800s 默认）。

## 机械预检

- 登记位置 tracked: docs/plans/m1-1-plan.md（本 plan）、docs/mcp-config.md（M1-1.4）。
- oracle 版本: mcp 2.3.0 / httpx2 2.16.0 / fastapi 0.158.2 / uvicorn / sqlalchemy 2.1.6。
- 产物清单: src/agent_kanban/api/main.py（+mcp 挂载）、services/identity.py（mcp_actor HTTP 场景）、tests/ac_cases_f.py、tests/red-4.log/green-4.log、docs/mcp-config.md。

## 域外发现处置

执行/审查中一切非本批引入的问题 -> 回报单列 + 登记 + 主循环裁决，禁静默修。
