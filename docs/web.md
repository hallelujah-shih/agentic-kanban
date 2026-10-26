# Web 窗口（M1，人面）

位置: docs/web.md（tracked）
规范锚: docs/PRD.md §4.2（Web 窗口 surface 表）/§5.3（看板口径 + SSE 语义）/§6（token，威胁模型 C）；docs/adr/0005-m1-direction.md 决策 2（Web 必须）
批次: M1-2（plan m1-2-plan.md，审#P1-2/P2-1/P2-2/P2-3/P2-5/P2-7/P1-4 折入）

## URL

| 路径 | 说明 |
|---|---|
| `GET /` | 看板壳（HTML）：JS fetch `/board` 渲染，需要关注区置顶 + 紧凑行；EventSource 订阅 `/events/stream`，收到事件或重连（onopen）即重拉 |
| `GET /board` | 看板数据（JSON）：`{tasks: [{requirement_id,title,state,awaiting_human,claim,progress,needs_attention,risks}], attention_ids}`。默认只含非终态需求（DONE/REJECTED/CANCELLED/ARCHIVED 过滤掉）；`?status=` 精确过滤状态 |
| `GET /events/stream` | SSE：全局 seq 游标轮询，连接时刻初始化、无历史回填；帧只含纯触发器字段 `{seq, requirement_id, kind, severity, ts, actor_surface, actor_conn}`；keepalive `: ping`（默认 2s，env `AGENT_KANBAN_SSE_POLL_MS`） |
| `GET /requirements/{id}` | 内容协商：Accept 含 `text/html` 返回深潜 HTML 壳（JS 渲染 + task 生命周期操作 archive/delete；决策操作 CLI/REST-only）；缺省/`*/*` 返回 JSON（与 M0 形状一致） |
| `GET /requirements/{id}/summary.html` | M0 静态摘要 HTML（保留，与深潜壳不冲突） |

服务地址默认 `http://localhost:{config.port()}`（config.host()，PRD §6 localhost 默认）。

## token 传播

- EventSource 无法设置 header：页面从 URL `?token=` 读 token 存入 `sessionStorage`（键 `kanban_token`），此后全部 `fetch` 经 header `x-agent-kanban-token` 携带，`EventSource` 经 query `?token=` 携带。
- localhost 默认无 token 不生效（PRD §6：localhost 请求豁免，以 Connection 对端判定）；非 localhost 需带 token，否则 401 `{code:'unauthorized', ...}`。
- 非 localhost 场景 token 会出现在 URL（威胁模型 C 单用户可接受，见 PRD §6 注明）；不建议在多用户/可被他人观察的网络直接暴露 URL。

## 页面

看板页（`/`）：每需求一行紧凑行 = title(链接到深潜壳) + state 标签 + 需要关注信号标签（blocked_subtask/abandoned/milestone_delay/decomposition_added/unexplained/orphaned/drift 等，来自 `_derived_signals` 全口径）+ 风险标签（severity>=attention）+ 进度 done/total + 认领(agent/signal) + awaiting_human。需要关注需求置顶（attention_ids）。顶部 tabs：在板 / 已完成（DONE/REJECTED/CANCELLED）/ 已归档（ARCHIVED）；顶栏「新建」按钮展开内联表单（title 必填 / description / acceptance 一行一条锚 / Jira 链接可选 -> source=jira）；等待人卡片含 CLI 提示（kanban approve <id>）。

深潜页（`/requirements/{id}`，Accept text/html）：标题 + state + 需要关注 + 认领/租约/awaiting_human + 进度、验收对照表（覆盖缺口标红）、子任务清单、里程碑（planned/actual）、决策/风险/偏离列表、需要关注区、事件流（按 kind/severity 过滤，只渲染标题行，无 content/payload 原始输出）、Task 生命周期区（archive/delete）。

## 人面 surface（修订 2026-10-26）

**Web 深潜页 = Task 生命周期（全走 REST）**：

| 按钮 | 请求 | 备注 |
|---|---|---|
| archive | POST `/requirements/{id}/archive` | state=ARCHIVED 时按钮禁用 |
| delete | DELETE `/requirements/{id}` | prompt 输入任务标题确认；不可逆，提示先 export |

**决策操作 = CLI/REST-only（Web 无入口）**：approve / release(reason) / renew / reopen(--continue) / note(content) / abandon(to_state) / set_expectations——语义与端点不变（PRD §4.2），Web 壳已移除对应按钮。深潜页等待人横幅含静态 CLI 提示（kind=review -> 人面确认: kanban approve <id>；kind=blocked -> 解除阻塞: kanban approve <id>）。

操作结果：成功 -> 提示后 `load()` 重拉页面数据；失败 -> 内联展示响应体 `{code, message}`（如 `illegal_state: ...`、`not_found: ...`）。

## 冒烟 checklist（浏览器人工）

1. `GET /?token=<t>` 打开看板页：需 token 或 localhost；任务行按需要关注置顶；无任务时显示「（无任务）」。
2. 数据与 `/board` JSON 一致（核对 title/state/进度/信号标签）。
3. 点深潜链接进深潜壳：验收对照缺口标红、事件流可按 kind/severity 过滤。
4. 生命周期操作：新建表单提交（带/不带 acceptance 两行锚、带 Jira 链接）成功且看板重拉出现新任务；对 CLAIMED 需求 archive 成功（移入已归档 tab）；delete 输入错误标题被拒、正确标题删成功（页面转“任务不存在”）。
5. 等待人提示：对 awaiting_human 任务确认深潜页与卡片横幅显示 `kanban approve <id>` 提示（静态文字，非按钮）。
6. SSE 断连重连行为：断网/服务重启后 EventSource 自动重连，onopen 触发重拉，页面结构自愈（无历史回填，数据以重拉结果为准）；页面打开状态下另一进程（如 MCP stdio agent）推进状态 -> 页面 2s 内自动刷新（`AGENT_KANBAN_SSE_POLL_MS`）。
7. `GET /board?status=CLAIMED` 等过滤有效。
8. 非 localhost 无 token 访问 -> 401，页面显示加载失败。
