# M1-2 Plan — Web 窗口（看板列表 + 需求深潜 + SSE 事件推送）

分支: `m1-2`（worktree `.worktree/m1-2/`，基 main @ 02970e3）
档位: 全六门（D 对外契约：新端点 /board、/events/stream、/ 与内容协商 HTML 壳 + ②信任边界延伸）
规范锚: docs/adr/0005-m1-direction.md 决策 2（Web 窗口必须：反淹没默认列表 + 深潜 + 人面操作 + SSE，无原始输出）+ PRD §0 反淹没/报告纪律 + §5.3 视图原则 + §6 安全 + §4.2 人面
既有面（复用，不动语义）: REST 13 端点（人面操作全有）+ view.summary/detail + list_tasks + token 中间件（默认覆盖全部路径，除 /healthz）+ config.host()/port()

## 契约三锚

1. 规范逐字原文: ADR 0005 决策 2；PRD §0 反淹没（默认视图只展示关键节点，原始日志/过程细节不默认展示）；§5.3（摘要视图内容清单、深潜视图按需展开、反淹没结构保证——无 run_logs 表，payload 8KB 上限）；§6（localhost 默认 + token；威胁模型 C）；§4.2 人面（approve/release/renew/note/abandon/reopen/set_expectations）。
2. 代码锚点: src/agent_kanban/services/view.py（summary/detail/_derived_signals/渲染）、operations.py list_tasks、api/requirements.py（REST 路由 + rest_actor + _run）、api/main.py（create_app + token 中间件 + /healthz）、models.py（Event: kind/severity/content/payload/ts/id；Requirement/Claim/Subtask/Milestone）。
3. 逐例期望: GET / 返回看板 HTML 壳（反淹没结构，无原始输出）；GET /requirements/{id}（Accept: text/html）返回深潜 HTML 壳，默认 JSON 不变（既有 248 不回归）；GET /board 返回非终态任务 + 单次聚合信号（progress/attention 标志）；GET /events/stream 跨进程推送新事件（游标 (ts,id)，反淹没事件字段）；人面操作经页面按钮调既有 REST；无 token 访问新端点 401。

## 影响面

- ① 新对外契约命中（/board JSON、/events/stream SSE、/ 看板壳、内容协商深潜壳）。
- ② 信任边界延伸命中（新端点入 token 中间件覆盖；SSE 长连接；localhost 默认）。
- ④ 不命中（board 聚合信号 = 既有 derived 信号子集，SSE = 事件推送，无新业务规则）。
- ③ 不命中。
单向门：契约源自 ADR 0005（user 裁决 Web 必须）+ PRD 已审规格；本 plan 审 + 结果盲审 + AC oracle 兜底。

## 关键设计决策（已钉，理由入 plan 审）

- **SSE 数据源 = DB 轮询**（非进程内 pub/sub）：MCP stdio 是独立子进程直写同一 SQLite，唯一跨进程可靠信号是 DB 本身。服务端轮询间隔 env `AGENT_KANBAN_SSE_POLL_MS`（默认 2000，测试设小值）。
- **SSE 游标 = (ts, id)**：Event.seq 是需求级序号，非全局；无 schema 变更，`WHERE (ts, id) > (last_ts, last_id) ORDER BY ts, id`。首次连接不补发历史（客户端先 fetch /board）。
- **推送字段反淹没**：{seq, requirement_id, requirement_title, kind, severity, ts, actor_surface, actor_conn, title}（紧凑；客户端收到 = "变了，重新拉结构"）。
- **DOM 单一渲染源 = 客户端 JS**（薄 HTML 壳 + fetch REST + EventSource → 重渲染）。不做 Python+JS 双渲染（镜像实现漂移风险）；浏览器 E2E 无自动化 -> 盲区登记（人工冒烟）。
- **无新依赖**：不引 jinja2/前端框架/build；SSE 用 StreamingResponse。
- **token 传播**：页面 URL `?token=`（EventSource 不能设 header）-> sessionStorage -> 全部 fetch/EventSource 附 token（header 或 query）。localhost 默认无 token 时不生效；非 localhost 单用户可接受 URL 可见 token（威胁模型 C，文档注明）。

## 原子任务

| # | 任务 | 验证 | 期望 |
|---|---|---|---|
| M1-2.1 | spec 补记（docs 批，先于实现 commit）：PRD §4.2 加 Web 窗口 surface 表行（/board、/events/stream、/ 壳、内容协商壳、token 传播）；§5.3 加 SSE 实时更新一句 | git ls-files tracked | 规格先行 |
| M1-2.2 | board service（view.board）：非终态默认过滤（list_tasks 同）+ status 过滤；**单次聚合 pass**（无 N+1）：subtasks 按 requirement 分组 -> progress（done/total，blocked=进行中，abandoned 不计分母）+ blocked/abandoned 标志；milestones 分组 -> delay（overdue/late，同 view.summary 口径）；events 分组 -> decision/deviation/risk 计数；awaiting_human + claim 信号（claim_view，同 list_tasks）；coverage gap 计数（acceptance 锚无链接，下界语义）；返回 {tasks: [{requirement_id,title,state,awaiting_human,claim,progress,attention:{blocked_subtasks,abandoned_subtasks,milestone_delay,decisions,deviations,risks,coverage_gaps}}], attention_ids: [...]}；**board 的 attention = 单次聚合信号，完整 derived 信号（decomposition_added/unexplained/orphaned/drift）留深潜 view**（不同粒度不矛盾：board 徽标 = "去看详情"） | harness: 造 3 需求（1 正常、1 有 blocked 子任务 + 里程碑延误 + awaiting_human、1 有覆盖缺口）断言 board 行与 attention 标志、状态过滤、非终态排除 | 反淹没看板数据正确 |
| M1-2.3 | SSE endpoint（GET /events/stream，StreamingResponse text/event-stream）：每轮询间隔查新事件（游标 (ts,id)），join requirements 取 title；反淹没字段；每间隔 keepalive `: ping`；poll 间隔 env AGENT_KANBAN_SSE_POLL_MS（默认 2000）；token 中间件覆盖（无 token 401）；SSE 读用独立 session（无 actor 属性，纯系统读不写事件） | harness: 真实 uvicorn 子进程 + httpx2 流式 GET，REST 写事件后 **wait-for-event deadline helper**（asyncio.wait_for，非 sleep）断言推送字段（req_id/kind/ts/actor 与落库一致）；跨进程验证（MCP stdio 子进程写 -> SSE 收到） | 跨进程实时推送 |
| M1-2.4 | Web 页面：/ 看板壳（HTML + 内联 JS：fetch /board 渲染"需要关注"区置顶 + 全列表紧凑行，EventSource /events/stream -> 重拉 /board）；/requirements/{id} 内容协商壳（Accept: text/html -> HTML 壳，默认 JSON；JS fetch detail+summary 渲染验收对照/子任务/里程碑/决策风险偏离/事件流（kind/severity 过滤控件）/需要关注/认领租约/awaiting_human + 人面操作按钮 approve/release(reason)/renew/note(content)/abandon(to_state)/reopen(continue)/set_expectations(JSON textarea)）；反淹没：壳与渲染均无原始输出；token 传播 sessionStorage | harness: GET / 200 + 壳标记断言（无原始输出/事件 content 不进壳）；GET /requirements/{id} Accept text/html 200 + 壳标记，默认 Accept JSON 形状不变（回归） | Web 窗口可用（后端/壳面自动化；JS 渲染盲区登记） |
| M1-2.5 | harness 集成（tests/ac_cases_g.py + run_ac 注册）：M1-2.2/2.3/2.4 全部用例红绿留档（red-5 -> green-5）；401 覆盖新端点；回归既有 248 | `uv run python tests/run_ac.py` 全绿 | 全绿 + 盲区登记 |
| M1-2.6 | docs：docs/web.md（Web 窗口使用说明：URL/token 传播/页面/操作/与 CLI 关系）；m1-2-verification.md（判据/红绿/盲区：浏览器 JS 渲染无自动化、SSE 首次连接不补发历史） | git ls-files tracked | 文档对齐 |

## oracle 纪律

- 断言逐字引自 PRD §0/§5.3/§6/§4.2；真实 uvicorn 子进程 + httpx2 流式（SSE 非 mock/TestClient）；wait-for-event 条件锚（禁 sleep 撞窗）。
- 反证位：SSE 跨进程（MCP stdio 子进程写 -> HTTP SSE 收）+ board 聚合区分性（三需求三种 attention 形态互不串）。
- 既有 248 不回归（含 GET /requirements/{id} 默认 JSON 形状）。

## 验证入口与 tier

- tier-0: `uv run python -m compileall -q src cli.py`
- tier-1: `uv run python tests/run_ac.py` 全绿
- tier-2（合并门槛）: tier-1 全绿 + web.md/m1-2-verification.md 更新 + git ls-files 全 tracked

## 不修清单

1. 不做浏览器 E2E 自动化（无 JS 引擎依赖；盲区登记 + 人工冒烟）。
2. 不做实时编辑/拖拽看板（读+操作按钮已够；拖拽=控制面倾向，PRD 看板非控制面）。
3. 不做 SSE 历史补发/断线重连缓存（客户端重拉结构自愈）。
4. 不做 set_expectations 的可视化编辑（JSON textarea 即可；复杂列表编辑器 M2+）。
5. 不引前端框架/jinja2/build（薄壳 + 原生 JS，最小改动）。
6. 不改 Event 表加全局 seq（(ts,id) 游标够用）。

## 机械预检

- 登记位置 tracked: docs/plans/m1-2-plan.md、docs/web.md、docs/ops/m1-2-verification.md。
- oracle 版本: mcp 2.3.0 / httpx2 2.16.0 / fastapi 0.158.2 / uvicorn / sqlalchemy 2.1.6。
- 产物清单: src/agent_kanban/services/view.py（board）、api/requirements.py 或 api/web.py（/board、/events/stream、/ 壳、内容协商壳）、tests/ac_cases_g.py、tests/run_ac.py（注册）、tests/red-5.log/green-5.log、docs/web.md、docs/ops/m1-2-verification.md、docs/PRD.md（§4.2/§5.3 补记）。

## 域外发现处置

执行/审查中一切非本批引入的问题 -> 回报单列 + 登记 + 主循环裁决，禁静默修。
