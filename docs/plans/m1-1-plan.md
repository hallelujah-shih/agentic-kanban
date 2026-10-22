# M1-1 Plan — MCP HTTP（streamable-http 挂载 FastAPI /mcp）

分支: `m1-1`（worktree `.worktree/m1-1/`，基 main @ ca5aeff）
档位: 全六门（D 对外契约：MCP HTTP 新 transport + ①归因语义 + ②信任边界延伸 /mcp）
规范锚: docs/adr/0005-m1-direction.md（MCP HTTP 做）+ PRD §4.1（双 transport）+ §4.3（错误码语义两 transport 一致）+ §5.1（归属）+ §6（安全 localhost+token）
依赖实测（主循环已探）: mcp 2.3.0 `MCPServer.streamable_http_app(*, streamable_http_path='/mcp', ...) -> Starlette`；客户端 `streamable_http_client(url, http_client=..., ...)`（httpx2 2.16.0）；stdio 路径不变
盲审: APPROVE-WITH-FIXES（P1-1/P1-2 + P2-1/2/3/4 已折入，见标注「审#」）

## 契约三锚

1. 规范逐字原文: ADR 0005；PRD §4.1 transport 注；§4.3（is_error + {code,message,task_id}，无 HTTP 码语义）；§5.1（actor 服务端派生，**不接受调用方传入**）；§6（localhost 默认 + token header/query 双通道）。
2. 代码锚点: mcp/server.py（12 工具 + mcp_actor 从 ctx meta 取 ai.opencode/sessionID，fallback 进程级 CONN_ID）；api/main.py（FastAPI + token 中间件 + lifespan + config.host()/port()）。
3. 逐例期望: 真实 HTTP MCP 客户端经 /mcp 调用全部 12 工具；错误 is_error 语义与 stdio 逐码等价；写事件归属 actor_surface='mcp' + conn = 服务端铸币 HTTP 会话 id；无 token 访问 /mcp 401；有 token 通过。

## 影响面

- ① 新对外契约（/mcp 端点 + 归因语义）。
- ② 信任边界延伸（/mcp 入 token 中间件；localhost 默认）。
- ③ 不命中。
单向门：契约源自 ADR 0005（user 裁决）+ PRD 已审规格；本 plan 审 + 结果盲审 + AC oracle 兜底。

## 原子任务

| # | 任务 | 验证 | 期望 |
|---|---|---|---|
| M1-1.1 | api 集成。**审#2/P2-1**：Starlette Mount 剥前缀，`streamable_http_app(streamable_http_path="/", host=config.host())` + `app.mount("/mcp", mcp_app)`（内层 Route 在 "/" 才不会 404）。**审#P2-2**：host 必须传 `config.host()`（非 localhost 时 SDK 的 DNS rebinding 保护自动关闭，token 为门；不传则默认 127.0.0.1 保护在非 localhost 绑定下静默 421）。token 中间件确认覆盖 mount 的 Starlette app。**审#P2-4**：抽 `build_server()` 工厂（12 工具注册单点），stdio（cli.py mcp）与 HTTP 共用，防注册表手工复制漂移；stdio 路径回归零 | harness: 无 token 访问 /mcp 401（含响应体 code=='unauthorized'）；有 token 真实客户端 initialize 全流程通过 | PRD 6 安全延伸；stdio 回归零 |
| M1-1.2 | 归因（HTTP transport）。**审#P1-1 钉死**：HTTP actor_conn = 服务端握手铸币的 MCP session id（`http:<sid>` 前缀，与 stdio `conn-*` 区分）；**client header 不作 actor_conn**（可任意伪造 = 调用方传入，违反 PRD 5.1 与 SDK Context.headers 自述「client-supplied input, never an identity assertion」）；client header 至多作外部引用档（PRD 5.1 可伪造性=中），不进 actor_conn。mcp_actor 扩展 HTTP 场景：从 ctx.headers 的 `mcp-session-id` 或 connection session 取值（实现时确认 SDK 取法），无则拒绝（不落进程级 CONN_ID） | harness 归因区分性断言（**审#P1-1**）：HTTP 写事件 conn == 服务端铸币值（initialize 响应 Mcp-Session-Id 头对照）且 != 任何客户端注入头值；两 HTTP 客户端 conn 可分（两 session）；stdio conn 仍为 conn-* 不混 | 5.1 归属 + 判据3 可答；审计链不可伪冒 |
| M1-1.3 | harness（tests/ac_cases_f.py + run_ac 注册）：真实 uvicorn 子进程（复用 ac_lib env_for HOST/TOKEN/DB）+ `streamable_http_client` 真实调用全部 12 工具；**审#P1-2 错误面补全**：no_active_claim / invalid_record（request_review 缺证据）/ already_claimed / illegal_state / not_found（claim 不存在 req、update_subtask 不存在 subtask）/ duplicate_subtask（add_subtask 同 title）/ queue_full（第 17 次 claim_task，AC8 同场景）；`lease_expired` 仅人面 renew 非 MCP 可达（缺得对）；**db_busy 不可确定性触发 -> 显式登记盲区**（判据/盲区/重跑规格入 m1-verification 关联档）。**审#P2-3 逐码等价机制**：同一场景 stdio 与 HTTP 各跑一次，断言 (code, message, task_id) 三元组一致（helper 复用场景数据）。**审#P2-2**：401 断言同时校验响应体 code=='unauthorized'，排除偶发 404/421 混同。红绿留档（red-4 -> green-4） | `uv run python tests/run_ac.py` 全绿 | 12 工具全可达 + 错误语义与 stdio 逐码一致 |
| M1-1.4 | docs：docs/mcp-config.md 补 HTTP transport 配置段（URL /mcp、token 头、与 stdio 选择场景、客户端示例） | git ls-files tracked | 文档对齐 |

## oracle 纪律

- 断言逐字引自 PRD §4.3/§5.1/§6；HTTP 客户端真实（streamable_http_client + httpx2）；错误语义与 stdio 同库逐码对比（同场景双 transport 跑）。
- 反证位：每 AC 先红后绿留档；最强对抗变体 = 错误路径逐码 + 归因区分性（conn==铸币值 且 != 注入头值）。
- 既有 203 不回归（stdio/MCP/CLI/REST 全保绿）。

## 验证入口与 tier

- tier-0: `uv run python -m compileall -q src cli.py`
- tier-1: `uv run python tests/run_ac.py` 全绿
- tier-2（合并门槛）: tier-1 全绿 + mcp-config.md 更新 + git ls-files 全 tracked

## 不修清单

1. 不用 mcp 的 transport_security（JWT）——走统一 token 中间件（PRD 6）。
2. 不做 SSE 旧 transport（deprecated；用 streamable-http）。
3. 不做会话持久化/多机（SDK 内存会话管理；session 超时 1800s 默认）。
4. 不做 HTTP 面 conn 的外部引用档复用（P1-1 判定 client header 仅外部引用；本批不实现其展示）。

## 机械预检

- 登记位置 tracked: docs/plans/m1-1-plan.md（本 plan）、docs/mcp-config.md（M1-1.4）。
- oracle 版本: mcp 2.3.0 / httpx2 2.16.0 / fastapi 0.158.2 / uvicorn / sqlalchemy 2.1.6。
- 产物清单: src/agent_kanban/api/main.py（+mcp 挂载）、src/agent_kanban/mcp/server.py（build_server 工厂重构）、services/identity.py（mcp_actor HTTP 场景）、tests/ac_cases_f.py、tests/run_ac.py（注册）、tests/red-4.log/green-4.log、docs/mcp-config.md。

## 域外发现处置

执行/审查中一切非本批引入的问题 -> 回报单列 + 登记 + 主循环裁决，禁静默修。
