# M1-1 验证记录（MCP HTTP）

位置: docs/ops/m1-verification.md（tracked，m1-1 分支）
批次: M1-1（M1-1.1 api 挂载 /mcp + M1-1.2 HTTP 归因 + M1-1.3 真实 HTTP 客户端 harness + M1-1.4 docs），全六门
规范锚: docs/PRD.md §4.1（双 transport）/§4.3（is_error + {code,message,task_id}）/§5.1（actor 服务端派生，HTTP conn = 服务端铸币 session id）/§6（token）；docs/plans/m1-1-plan.md（本批次契约，审#P1-1/P1-2/P2-1/P2-2/P2-3/P2-4 折入）

## oracle 版本（机械预检）

- python 3.14.4（.venv）；mcp 2.3.0（streamable_http_app / streamable_http_client / create_mcp_http_client）；httpx2 2.16.0；fastapi 0.158.2；uvicorn；sqlalchemy 2.1.6
- harness argv: `uv run python tests/run_ac.py`（工作目录 = worktree 根）
- tier-0: `uv run python -m compileall -q src cli.py`

## 判据（逐字引自 PRD，oracle 独立于实现）

- M1-1.1: 无 token 访问 /mcp -> 401 且响应体 `code=='unauthorized'`（排除偶发 404/421 混同，审#P2-2）；有 token 真实客户端 initialize + 全流程通过；token 中间件覆盖 mount 的 Starlette 子 app。
- M1-1.2（归因，审#P1-1 钉死）: HTTP 写事件 `conn == http:<sid>`（initialize 响应 Mcp-Session-Id 头捕获的服务端铸币值）且 `!=` 任何客户端注入头值 / 注入 sessionID meta；两 HTTP 客户端（两 session）conn 可分；stdio conn 仍为 `conn-*` 不混。
- M1-1.3（错误面逐码，审#P1-2/P2-3）: 同一场景 stdio 与 HTTP 同 DB 各跑一次，`(code, message, task_id)` 三元组严格一致（失败调用全部非变异）；每个码在 HTTP 面 code 正确（no_active_claim / invalid_record / already_claimed / illegal_state / not_found / duplicate_subtask / queue_full）。`lease_expired` 仅人面 renew 非 MCP 可达（缺得对）。
- M1-1.4: docs/mcp-config.md 补 HTTP transport 段（URL /mcp、token 头、与 stdio 选择场景、客户端示例），tracked。

## 结果（主循环复验 2026-10-22）

- tier-0: `compileall` 退出 0。
- tier-1: `uv run python tests/run_ac.py` -> **248/248 PASS**（既有 203 零回归 + f-case 45 新增）。
- f-case 逐段: http_mcp 22（12 工具注册 + 工具面无 release/renew + 12 工具 happy path 逐条 + is_error 两代表码 + 归因五断言 + stdio conn 不混）；http_mcp_sec 5（401 x2 + 错 token + 有 token 全流程 + 归因仍 http:<sid>）；http_mcp_equiv 18（8 场景逐码等价 x2 + 双会话可辨 x2）。

## 红绿证据

| 阶段 | 红 | 绿 | 说明 |
|---|---|---|---|
| M1-1 f-case | tests/red-4.log 0/3（stash src 后全 MCPError: Not Found = 无 /mcp 的诚实红） | tests/green-4.log 45/45 | 同源（同一 harness 结构）：red 证明 oracle 能抓住缺实现，green 证明实现到位 |
| 全量 | tests/red-4.log | tests/green-full.log 248/248 | tier-1 全量（既有 203 零回归 + f-case 45） |

- harness 修复史（红绿同源前修正，均属 harness 自身 bug 非实现缺陷）：seed 未 await（coroutine 传入 JSON）、CallToolResult 客户端字段为 `is_error` 非 `isError`、update_progress 断言字段、等价 runner 结构（setup 一次 + 失败调用双 transport 同 DB）。

## 重跑规格

```
cd .worktree/m1-1
uv run python -m compileall -q src cli.py          # tier-0
uv run python tests/run_ac.py                      # tier-1（全 AC，需 ~5-6 分钟）
```

- 确定性: 无 sleep 撞窗；queue_full 经 `AGENT_KANBAN_LEASE_SECONDS=-1`（16 认领全 STALE）确定性构造；租约/过期经 env 覆盖；等价场景 setup 一次（stdio）后失败调用 stdio 与 HTTP 同 DB 各跑一次（失败调用非变异 -> task_id 严格一致）。
- 隔离: 每次运行临时 DB 目录；HTTP 面真实 uvicorn 子进程 + streamable_http_client（禁 TestClient/禁 mock）；stdio 面真实子进程 newline JSON-RPC。

## Verdicts

- 12 工具逐条（HTTP happy path 全走通，含租约字段/认领可见/子任务/里程碑/记录/进度/评审 marker/BLOCKED/等待列表）。
- 错误面逐码: 8 场景 (code,message,task_id) 三元组 stdio == HTTP（同一 DB、同一 task_id），且 HTTP 面 code 与 PRD 4.3/§9 一致。
- 归因断言（最强对抗变体）: conn == 服务端铸币值且 != 客户端注入头值 / 注入 opencode sessionID meta；双会话（两 sid）conn 可分；stdio conn-* 前缀不混。
- stdio 回归: 既有 203 断言全绿（stdio/MCP/CLI/REST 零回归），`build_server()` 工厂单点注册无漂移。

## 盲区登记（db_busy）

- 判据（PRD 7.3 #4）: SQLite 写路径 BEGIN IMMEDIATE 在持续锁竞争下重试 3 次后抛 `db_busy`（REST 映射 503）。MCP 面同经 `_call` 包转 is_error 返回。
- 盲区: 触发依赖真实锁竞争时序（并发写事务同时 BEGIN IMMEDIATE），确定性 harness 无法在不引入人为 sleep/锁持有协程的情况下稳定触发；与 AC1 并发场景（seq 主 oracle）在 `busy_timeout` 内可被重试吸收，属不可确定性事件。
- 处理: 不写入本批 harness 断言（避免脆弱性）；db_busy 的既有覆盖 = 单元层/人面映射契约（REST 503 映射表，m0 已有），MCP 面语义经同一 `run_op` 路径派生（代码同源）。重跑规格: 如需验证，以真机并发写压测（多进程同时 claim 同一批）观察 503/`db_busy` 响应，属人工观测项，不入自动化门。

## 不做清单（本批显式不做，见 docs/plans/m1-1-plan.md「不修清单」）

MCP transport_security（JWT，走统一 token 中间件 PRD 6）；SSE 旧 transport（用 streamable-http）；会话持久化/多机（SDK 内存会话管理，idle 1800s 默认）；HTTP 面 conn 的外部引用档复用展示（P1-1 判定 client header 仅外部引用，本批不实现展示）。

## 域外发现（单列，修复裁决归主循环）

1. **CallToolResult 客户端字段名事实（非 bug）**: mcp SDK 客户端 `CallToolResult` 字段为 `is_error`（非协议层 `isError`），harness 断言已按客户端字段修正；属 SDK 命名事实，非实现缺陷。
2. **mounted Starlette 子 app lifespan 不执行（实现说明）**: 已读 starlette 1.9.0 Mount 源码确认，`mcp_server.session_manager.run()` 必须在 FastAPI lifespan 内显式执行（session 内存管理与 idle 回收），否则挂载的 /mcp 无会话管理。
3. **MCP 面 db_busy 语义同源（见盲区登记）**: 与 m0 既有 503 映射同一 `run_op` 路径，无需新增代码。
4. **协议版本协商（信息性，结果盲审 P2-1）**: mcp 2.3.0 SDK 对客户端协商降级到 2025-11-25（双 era 协商）；若客户端硬编码发送 modern `MCP-Protocol-Version: 2026-07-28` 会走 SDK 单交换路径（无 session id），工具调用命中 identity 的「无 session 拒绝」illegal_state——与服务端一贯协商降级的现实客户端行为不冲突，符合 plan「无 session 时拒绝」语义；不修，登记留档。
5. **`_http_sid` 依赖 SDK 私有属性（结果盲审 P2-2）**: identity.py `_http_sid` 读取 `ctx.session._connection.session_id`（mcp 2.3.0 服务端铸币值，harness 已钉住 = initialize 响应 Mcp-Session-Id）。mcpserver Context 无公开等价访问器，属 SDK 私有 API 依赖——mcp 升级时回归风险点，登记留档。
6. **无 session 拒绝分支不可达性（结果盲审 P2-3）**: stateful 模式下 SDK 会话管理器在 handler 前即 404 拒绝未知/缺失 session id，identity 的「无 session 拒绝」为防御性（关键不变量「HTTP 永不落 stdio 进程级 CONN_ID」由结构保证）；无独立用例，登记留档。
