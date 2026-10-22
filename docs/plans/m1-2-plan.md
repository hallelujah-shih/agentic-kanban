# M1-2 Plan — Web 窗口（看板列表 + 需求深潜 + SSE 事件推送）

分支: `m1-2`（worktree `.worktree/m1-2/`，基 main @ 02970e3）
档位: 全六门（D 对外契约：新端点 /board、/events/stream、/ 与内容协商 HTML 壳 + ②信任边界延伸）
规范锚: docs/adr/0005-m1-direction.md 决策 2（Web 窗口必须：反淹没默认列表 + 深潜 + 人面操作 + SSE，无原始输出）+ PRD §0 反淹没/报告纪律 + §5.3 视图原则 + §6 安全 + §4.2 人面
既有面（复用，不动语义）: REST 13 端点（人面操作全有）+ view.summary/detail + list_tasks + token 中间件（默认覆盖全部路径，除 /healthz）+ config.host()/port()
盲审: REJECT（P1-1/2/3/4 + P2-1..8 + 疑点 httpx2 依赖），已全部折入（标注「审#」）；复审待原审者 consensus

## 契约三锚

1. 规范逐字原文: ADR 0005 决策 2；PRD §0 反淹没（默认视图只展示关键节点，原始日志/过程细节不默认展示）；§5.3（摘要视图内容清单、深潜视图按需展开、反淹没结构保证）；§6（localhost 默认 + token；威胁模型 C）；§4.2 人面。
2. 代码锚点: src/agent_kanban/services/view.py（summary/detail/_derived_signals/渲染）、operations.py list_tasks、api/requirements.py、api/main.py（token 中间件 + /healthz）、models.py、db.py next_seq（seq_counter 全局表）。
3. 逐例期望: GET / 返回看板 HTML 壳（反淹没，无原始输出）；GET /requirements/{id}（Accept: text/html）返回深潜 HTML 壳，默认 JSON 不变；GET /board 返回非终态任务 + 每需求 `_derived_signals` 口径 attention（同 view.summary）；GET /events/stream 全局 seq 游标跨进程推送新事件（纯触发器字段）；人面操作经页面按钮调既有 REST；无 token 访问新端点 401。

## 影响面

- ① 新对外契约命中（/board、/events/stream SSE、/ 看板壳、内容协商深潜壳）。
- ② 信任边界延伸命中（新端点入 token 中间件；SSE 长连接；localhost 默认）。
- ④ 不命中（board 口径 = 既有 `_derived_signals` 同源；SSE = 事件推送，无新业务规则）。
- ③ 不命中。
单向门：契约源自 ADR 0005（user 裁决 Web 必须）+ PRD 已审规格；本 plan 审 + 结果盲审 + AC oracle 兜底。

## 关键设计决策（审#P1/P2 已折入）

- **SSE 数据源 = DB 轮询**（非进程内 pub/sub）：MCP stdio 独立子进程直写同一 SQLite，唯一跨进程可靠信号是 DB。轮询间隔 env `AGENT_KANBAN_SSE_POLL_MS`（默认 2000，测试设小值）。
- **审#P1-1 SSE 游标 = 全局 seq**：Event.seq 为全局单调（db.py next_seq/seq_counter，PRD §2 行 65），`WHERE seq > last_seq ORDER BY seq`，零 schema 变更，严格全序无 uuid/时钟回拨漏窗。游标初始化 = 连接时刻（**审#P1-4 无历史回填**）；帧不发 `id:`、忽略 Last-Event-ID（保持无回填确定性）。
- **审#P1-3 SSE 读新鲜度**：每轮询新建读连接/显式事务边界（WAL 快照不跨轮询复用，否则 stdio 子进程写入永不可见）；生成器 finally 关 session + **审#P2-4 is_disconnected 停轮询**。
- **审#P2-5 推送字段纯触发器**（反淹没）：{seq, requirement_id, kind, severity, ts, actor_surface, actor_conn}——无 title join、无 payload，客户端收到 = "变了，重拉结构"；防过程细节入面。
- **审#P1-2 board attention = 每需求 `_derived_signals`**（同 view.py 口径，非子集）：事件已按 requirement 分组，回放/匹配是内存操作，零 N+1；口径与 detail needs_attention 天然一致，无假阴性。**审#P2-2 抽共享 helper**（milestone delay/progress/coverage 口径单一来源，board 与 summary 共用）。**审#P2-1 risk 计数 severity>=attention 过滤**（同 summary）。
- **DOM 单一渲染源 = 客户端 JS**（薄 HTML 壳 + fetch REST + EventSource）；浏览器 E2E 无自动化 -> 盲区登记（人工冒烟）。无新依赖（不引 jinja2/前端框架/build；SSE 用 StreamingResponse）。
- **token 传播**：页面 URL `?token=`（EventSource 不能设 header）-> sessionStorage -> 全部 fetch/EventSource 附 token。localhost 默认无 token 不生效；非 localhost 单用户可接受 URL 可见 token（威胁模型 C，文档注明）。
- **审#P2-7 内容协商钉死**：`"text/html" in Accept` -> HTML 壳；缺省/`*/*` -> JSON（已核 harness 全部 Accept 缺省，无回归）；`/summary.html` 静态端点保留不冲突。

## 原子任务

| # | 任务 | 验证 | 期望 |
|---|---|---|---|
| M1-2.1 | spec 补记（docs 批先于实现）：**审#P2-8** PRD §4.2 加 Web 窗口 surface 表行（/board、/events/stream、/ 壳、内容协商壳、token 传播）；§5.3 加 board 口径（每需求 `_derived_signals` 同源）与 SSE 语义（全局 seq 游标、连接时刻初始化、无回填、纯触发器字段） | git ls-files tracked | 规格先行 |
| M1-2.2 | board service（view.board）：非终态默认过滤 + status 过滤；**审#P1-2** 每需求调 `_derived_signals` 得 attention（含 decomposition_added/unexplained/orphaned/drift 全口径）；**审#P2-2** 抽共享 helper（progress/milestone delay/coverage 与 summary 同源）；**审#P2-1** risk 计数 severity>=attention；返回 {tasks: [{requirement_id,title,state,awaiting_human,claim,progress,needs_attention:[{type,...}]}], attention_ids} | harness: 4 需求（正常/blocked+delay+awaiting/覆盖缺口/**审#P1-2 拆解新增无解释**）断言行与 attention == detail needs_attention 一致（口径一致性断言） | 反淹没看板数据正确 + 与详情零假阴性 |
| M1-2.3 | SSE endpoint（GET /events/stream，StreamingResponse text/event-stream）：**审#P1-1** 全局 seq 游标轮询 join requirements 取 requirement_id（不取 title）；**审#P1-3/P2-4** 每轮询新事务 + is_disconnected + finally 关 session；**审#P1-4** 游标=连接时刻无回填、无 id: 帧；**审#P2-5** 纯触发器字段；keepalive `: ping`；poll env AGENT_KANBAN_SSE_POLL_MS；token 中间件覆盖 | harness: 真实 uvicorn 子进程 + httpx2 流式 + wait-for-event deadline helper（禁 sleep）；**审#P1-4** 断言连接后首轮询窗口无历史重放（条件锚）；跨进程（MCP stdio 子进程写 -> SSE 收） | 跨进程实时推送 + 无回填 |
| M1-2.4 | Web 页面：/ 看板壳（HTML + 内联 JS：fetch /board 渲染需要关注区置顶 + 紧凑行，EventSource -> 重拉，**审#P1-4 onopen 重拉**）；/requirements/{id} 内容协商壳（JS fetch detail+summary 渲染验收对照/子任务/里程碑/决策风险偏离/事件流过滤/需要关注/认领租约/awaiting_human + 人面操作 approve/release(reason)/renew/note(content)/abandon(to_state)/reopen(continue)/set_expectations(JSON textarea)；**审#P2-3** 操作失败内联展示 body {code,message}）；反淹没：壳与渲染无原始输出；token 传播 sessionStorage | harness: GET / 200 + 壳标记（无原始输出/事件 content 不进壳）；GET /requirements/{id} Accept text/html 200 + 壳标记，缺省 Accept JSON 形状不变（回归） | Web 窗口可用（后端/壳面自动化；JS 渲染盲区登记） |
| M1-2.5 | harness 集成（tests/ac_cases_g.py + run_ac 注册）：2.2/2.3/2.4 全部用例红绿留档（red-5 -> green-5）；401 覆盖新端点；回归既有 248 | `uv run python tests/run_ac.py` 全绿 | 全绿 + 盲区登记 |
| M1-2.6 | docs：**审#P2-3** docs/web.md（URL/token 传播/页面/操作/冒烟 checklist：操作失败展示 code+message、SSE 断连重连行为）；m1-2-verification.md（判据/红绿/盲区：浏览器 JS 渲染无自动化、SSE 无回填）；**审#疑点** pyproject 补 `[dependency-groups] test = ["httpx2>=2.16,<3"]`（显式钉测试依赖，防 mcp 传递依赖漂移）+ uv sync | git ls-files tracked + uv sync 成功 | 文档对齐 + 测试依赖显式 |

## oracle 纪律

- 断言逐字引自 PRD §0/§5.3/§6/§4.2；真实 uvicorn 子进程 + httpx2 流式（SSE 非 mock/TestClient）；wait-for-event 条件锚（禁 sleep 撞窗）。
- 反证位：SSE 跨进程（MCP stdio 子进程写 -> HTTP SSE 收）+ 无回填（首轮询窗口零历史）+ board==detail 口径一致性（4 形态含拆解新增无解释）。
- 既有 248 不回归（含 GET /requirements/{id} 默认 JSON 形状、/summary.html 保留）。

## 验证入口与 tier

- tier-0: `uv run python -m compileall -q src cli.py`
- tier-1: `uv run python tests/run_ac.py` 全绿
- tier-2（合并门槛）: tier-1 全绿 + web.md/m1-2-verification.md 更新 + git ls-files 全 tracked

## 不修清单

1. 不做浏览器 E2E 自动化（无 JS 引擎依赖；盲区登记 + 人工冒烟）。
2. 不做实时编辑/拖拽看板（读+操作按钮已够；拖拽=控制面倾向，PRD 看板非控制面）。
3. 不做 SSE 历史补发/Last-Event-ID 续传（客户端 onopen 重拉结构自愈；无回填确定性保持）。
4. 不做 set_expectations 可视化编辑（JSON textarea 即可；复杂列表编辑器 M2+）。
5. 不引前端框架/jinja2/build（薄壳 + 原生 JS，最小改动）。
6. **审#P1-1** 不新增 Event 表字段——全局 seq 已存在（db.next_seq/seq_counter），直接作游标。
7. **审#P2-6** 不做 ts 索引（游标改 seq 后不需要；<100k events 可接受）。

## 机械预检

- 登记位置 tracked: docs/plans/m1-2-plan.md、docs/web.md、docs/ops/m1-2-verification.md、pyproject.toml（dependency-groups）。
- oracle 版本: mcp 2.3.0 / httpx2 2.16.0 / fastapi 0.158.2 / uvicorn / sqlalchemy 2.1.6。
- 产物清单: src/agent_kanban/services/view.py（board + 共享 helper）、api（/board、/events/stream、/ 壳、内容协商壳）、tests/ac_cases_g.py、tests/run_ac.py（注册）、tests/red-5.log/green-5.log、docs/web.md、docs/ops/m1-2-verification.md、docs/PRD.md（§4.2/§5.3 补记）、pyproject.toml（test 组）。

## 域外发现处置

执行/审查中一切非本批引入的问题 -> 回报单列 + 登记 + 主循环裁决，禁静默修。
