# M1-2 验证记录（Web 窗口）

位置: docs/ops/m1-2-verification.md（tracked，m1-2 分支）
批次: M1-2（M1-2.1 spec 补记 + M1-2.2 board service + M1-2.3 SSE + M1-2.4 Web 页面 + M1-2.5 harness + M1-2.6 docs），全六门
规范锚: docs/PRD.md §4.2（Web 窗口 surface 表）/§5.3（看板口径 + SSE 语义）/§0（反淹没）/§6（token）；docs/adr/0005-m1-direction.md 决策 2；docs/plans/m1-2-plan.md（本批次契约，审#P1-1/P1-2/P1-3/P1-4/P2-1..8/P2-A/P2-B/P2-C 折入）

## oracle 版本（机械预检）

- python 3.14.4（.venv）；httpx2 2.16.0（`[dependency-groups] test` 显式钉，防 mcp 传递依赖漂移）；fastapi 0.158.2；uvicorn；sqlalchemy 2.1.6
- harness argv: `uv run python tests/run_ac.py`（工作目录 = worktree 根）
- tier-0: `uv run python -m compileall -q src cli.py`
- SSE 轮询 env `AGENT_KANBAN_SSE_POLL_MS`（harness 设小值；默认 2000）

## 判据（逐字引自 PRD，oracle 独立于实现）

- M1-2.2（看板，§5.3/§4.2）: `/board` 非终态默认过滤（DONE/REJECTED/CANCELLED 不在板）+ `?status=` 精确过滤；每需求 `needs_attention` 为 `_derived_signals` **全口径**（与摘要视图同源，零假阴性，审#P1-2），返回 `{tasks, attention_ids}`；risk 计数 severity>=attention（同摘要，审#P2-1）；progress/milestone delay/coverage 与摘要同源（共享 helper，审#P2-2）；**board==summary 口径一致性断言**（4 形态：正常/blocked+delay+awaiting/覆盖缺口/拆解新增无解释）。
- M1-2.3（SSE，§5.3）: 全局 seq 游标（`WHERE seq > last_seq ORDER BY seq`，审#P1-1）；游标初始化 = 连接时刻，**无历史回填**、无 `id:` 帧、忽略 Last-Event-ID（审#P1-4）；每轮询新读事务（WAL 快照不跨轮询，跨进程写入可见，审#P1-3）；is_disconnected 停轮询 + finally 关 session（审#P2-4）；纯触发器字段 `{seq, requirement_id, kind, severity, ts, actor_surface, actor_conn}` 无 title/payload（审#P2-5）；keepalive `: ping`；读 events 行自带 requirement_id 无死 join（审#P2-A）；token 中间件覆盖（401）。
- M1-2.4（Web 页面，§4.2/§5.3/审#P2-7/P2-3）: `/` 看板壳（内联 JS fetch `/board` + EventSource 重拉，onopen 重拉审#P1-4）；内容协商 `"text/html" in Accept` -> 深潜壳，缺省/`*/*` -> JSON 形状不变（回归）；反淹没：壳与渲染无原始输出（progress note/事件 content 不进壳）；操作失败内联展示 body `{code,message}`；`/summary.html` 保留 200。
- M1-2.6: docs/web.md + m1-2-verification.md tracked；pyproject `[dependency-groups] test = ["httpx2>=2.16,<3"]` + uv sync 成功。

## 结果（主循环复验 2026-10-23）

- tier-0: `compileall` 退出 0。
- tier-1: `uv run python tests/run_ac.py` -> **279/279 PASS**（既有 248 零回归 + g-case 31 新增）。
- g-case 逐段（green-5.log）: board 18（4 形态 board==summary 一致 + status 过滤 + 401 + 覆盖缺口不入 attention 但 summary uncovered=True 无回归）；sse 6（首帧 keepalive 无回填 + 跨进程 seq=游标+1 + 纯触发器字段 + 401）；web 7（/ 壳 + 反淹没无原始输出 + 内容协商 + 缺省 JSON 形状回归 + /summary.html 保留 + 401）。

## 红绿证据

| 阶段 | 红 | 绿 | 说明 |
|---|---|---|---|
| M1-2 g-case | tests/red-5.log 6/13（src 未实现：/board 404、SSE connect 404、壳缺失的诚实红） | tests/green-5.log 31/31 | 同源（同一 harness 结构）：red 证明 oracle 能抓住缺实现，green 证明实现到位 |
| 全量 | tests/red-5.log | tests/green-full.log 279/279 | tier-1 全量（既有 248 零回归 + g-case 31） |

- 批内修正史（实现侧，harness 冻结于 red 后未动）: ① SSE 曾用 raw `text()` 读行致 `ts` 为 str（`AttributeError: 'str' object has no attribute 'isoformat'`）-> 改 ORM `select(Event...)` 让 UTCDateTime TypeDecorator 生效；② SSE `requirement_id` 经 `norm_id()` 归一化（ORM 读回 36 位带横线 id，对齐 API/CLI 无横线约定）。两处均属本批新代码缺陷，非既有面，红绿同源证据保留。

## 重跑规格

```
cd .worktree/m1-2
uv run python -m compileall -q src cli.py          # tier-0
uv run python tests/run_ac.py                      # tier-1（全 AC，需 ~5-6 分钟）
```

- 确定性: 无 sleep 撞窗——SSE 用 wait-for-event deadline helper（条件锚，非固定等待）；跨进程写时序钉死（审#P2-B）：连接建立后先等首个 keepalive（证明轮询已启动、游标已初始化）再经 MCP stdio 子进程写，断言收到；board 时点无歧义（审#P2-C）：planned_at 远过去、lease 远未来，now 依赖断言与口径一致性断言正交。
- 隔离: 每次运行临时 DB 目录；HTTP 面真实 uvicorn 子进程 + httpx2 流式客户端（禁 TestClient/禁 mock）；SSE 跨进程写 = MCP stdio 子进程直写同一 SQLite。

## Verdicts

- 看板: 5 形态需求 board 与 detail `needs_attention` 逐项一致（含 blocked_subtask/decomposition_added/milestone_delay/unexplained_abandonment 全口径；覆盖缺口不入 attention 与 summary 同源且 summary 的 uncovered=True 无回归）；board risks 与 summary risks 同源（审#P2-3：默认视图展示风险，PRD §0）；attention_ids 置顶正确；status 过滤正确；无 token 401。
- SSE: 连接前历史事件存在（游标基线非零）但连接后首轮询零历史（无回填）；MCP stdio 子进程写入的跨进程事件以 seq=游标+1 到达；帧字段纯触发器无 title/payload；keepalive `: ping`；无 token 401。
- Web: `/` 壳含 EventSource 且无原始输出泄漏；`Accept: text/html` 深潜壳；缺省 Accept JSON 形状不变（既有 248 零回归）；`/summary.html` 保留。

## 结果盲审 P2 折入（2026-10-23，verdict APPROVE）

- P2-1 壳请求效率: GET /requirements/{id} 先判 Accept，HTML 分支只做 `require_requirement` 存在性校验（404 保真），不再跑完整 detail 的无谓 DB 工作；缺省 JSON 路径不变。
- P2-2 全口径覆盖: harness 补第 5 形态「未解释放弃」（abandoned 子任务无 deviation/note 解释 -> unexplained_abandonment），board==summary 一致性断言扩至 5 需求；同时补 board risks 直接断言（critical risk 事件 -> board 行 risks 与 summary risks 逐项相等）。
- P2-3 看板行风险信号: board 行补 `risks` 字段（`_risk_rows` 共享 helper，severity>=attention）；/ 壳 JS 渲染风险徽标。闭合 PRD §0「默认视图只展示关键节点（…风险…）」的产品解读张力。

## 盲区登记

1. **浏览器 JS 渲染无自动化**（plan 不修清单 1）: 壳面（后端返回静态 HTML + JS 源）已自动化断言，但 JS 实际渲染效果、按钮交互、sessionStorage token 行为依赖浏览器——仅人工冒烟（docs/web.md 冒烟 checklist），不入自动化门。
2. **SSE 无回填为条件锚**（审#P1-4）: 断言的是「连接后首轮询窗口零历史事件」（keepalive 帧证明），不能断言「连接后永不出现旧事件」——因为连接建立后新写入的事件本就应推送；游标=连接时刻这一语义由「首帧非历史」+「跨进程事件 seq=游标+1（非重放）」（审#P2-B 时序钉死）联合证明。
3. **SSE 断连重连行为**（EventSource 自动重连 + onopen 重拉）属浏览器侧，人工冒烟（web.md checklist 第 5 条）。

## 不做清单（本批显式不做，见 docs/plans/m1-2-plan.md「不修清单」）

浏览器 E2E 自动化；实时编辑/拖拽看板；SSE 历史补发/Last-Event-ID 续传；set_expectations 可视化编辑；前端框架/jinja2/build；Event 表新增字段（全局 seq 已够）；ts 索引。

## 域外发现（单列，修复裁决归主循环）

本批无域外发现。批内修正（SSE ts TypeDecorator、norm_id 归一化）均属本批新代码缺陷，已入批内修正史，非既有面问题。
