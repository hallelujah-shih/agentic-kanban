# Web 窗口（M1，人面）

位置: docs/web.md（tracked）
规范锚: docs/PRD.md §4.2（Web 窗口 surface 表）/§5.3（看板口径 + SSE 语义）/§6（token，威胁模型 C）；docs/adr/0005-m1-direction.md 决策 2（Web 必须）
批次: M1-2（plan m1-2-plan.md，审#P1-2/P2-1/P2-2/P2-3/P2-5/P2-7/P1-4 折入）

## URL

| 路径 | 说明 |
|---|---|
| `GET /` | 看板壳（HTML）：JS fetch `/board` 渲染，需要关注区置顶 + 紧凑行；EventSource 订阅 `/events/stream`，收到事件或重连（onopen）即重拉 |
| `GET /board` | 看板数据（JSON）：`{tasks: [{requirement_id,title,state,awaiting_human,claim,progress,needs_attention,risks}], attention_ids}`。`awaiting_human` 形状 `{kind,reason,evidence?,since,summary_line?}`，`summary_line` additive（request_review 设置的评审交接一句话；缺失时卡片等待行降级显 reason）。默认只含非终态需求（DONE/REJECTED/CANCELLED/ARCHIVED 过滤掉）；`?status=` 精确过滤状态 |
| `GET /events/stream` | SSE：全局 seq 游标轮询，连接时刻初始化、无历史回填；帧只含纯触发器字段 `{seq, requirement_id, kind, severity, ts, actor_surface, actor_conn}`；keepalive `: ping`（默认 2s，env `AGENT_KANBAN_SSE_POLL_MS`） |
| `GET /requirements/{id}` | 内容协商：Accept 含 `text/html` 返回深潜 HTML 壳（JS 渲染 + task 生命周期操作 archive/delete；决策操作 CLI/REST-only）；缺省/`*/*` 返回 JSON（与 M0 形状一致；`events[]` 增 `audience`（"human"/"bookkeeping"，additive，服务端单点派生，读面禁止按 kind 重分类）） |
| `GET /requirements/{id}/summary.html` | M0 静态摘要 HTML（保留，与深潜壳不冲突） |

服务地址默认 `http://localhost:{config.port()}`（config.host()，PRD §6 localhost 默认）。

## token 传播

- EventSource 无法设置 header：页面从 URL `?token=` 读 token 存入 `sessionStorage`（键 `kanban_token`），此后全部 `fetch` 经 header `x-agent-kanban-token` 携带，`EventSource` 经 query `?token=` 携带。
- localhost 默认无 token 不生效（PRD §6：localhost 请求豁免，以 Connection 对端判定）；非 localhost 需带 token，否则 401 `{code:'unauthorized', ...}`。
- 非 localhost 场景 token 会出现在 URL（威胁模型 C 单用户可接受，见 PRD §6 注明）；不建议在多用户/可被他人观察的网络直接暴露 URL。

## 页面

看板页（`/`）：每需求一行紧凑行 = title(链接到深潜壳) + state 标签 + 需要关注信号标签（blocked_subtask/abandoned/milestone_delay/decomposition_added/unexplained/orphaned/drift 等，来自 `_derived_signals` 全口径）+ 风险标签（severity>=attention）+ 进度 done/total + 认领(agent/signal) + awaiting_human。需要关注需求置顶（attention_ids）。顶部 tabs：在板 / 已完成（DONE/REJECTED/CANCELLED）/ 已归档（ARCHIVED）；顶栏「新建」按钮展开内联表单（title 必填 / description / acceptance 一行一条锚 / Jira 链接可选 -> source=jira）；等待人卡片含 CLI 提示（kanban approve <id>）。

深潜页（`/requirements/{id}`，Accept text/html），三层结构（蒸馏先行，BCD distill-pipeline 裁决 5；CSS 沿用既有 token，不新增视觉语言）：

- **层 0 决策线**（唯一「花力气」区）：标题 + state + 描述（description 全文，esc 转义 + 保留换行，空则不显示该节）+ 等待人横幅（`awaiting_human.summary_line` 在场显该一句话——评审交接「做了什么/先看哪」；缺失显 `reason`——blocked/旧数据降级；静态 CLI 提示保留：kind=review -> 人面确认: kanban approve <id>，kind=blocked -> 解除阻塞: kanban approve <id>）+ 认领/租约 + 进度 + 需要关注区。
- **层 1 蒸馏**：验收对照表（覆盖缺口标红）+ 决策/风险/偏离区（决策行 `<details>`：提纲=title，展开=choice / rationale / alternatives 逐条 option + rejected_reason 可读列表——拒绝理由可见；风险/偏离行平铺）。
- **层 2 次要**：子任务清单、里程碑（planned/actual）（内容不变，节标题视觉层级低于层 1）。
- **事件流（提纲优先，audience 分组；JS 无分类表——只信服务端 `events[].audience` 字段）**：人面事件（audience=="human"）逐条 `<details>`——提纲位（summary）= title（title 空/纯空白 -> 降级显 kind 标签；旧 title="progress" 原样显示，不做特殊识别），展开 = content + payload（JSON 缩进），默认收起；簿记事件（audience=="bookkeeping"）折入单一 `<details>`「簿记 N」（N=计数）默认收起，展开为平铺行（空 title 同样降级显 kind 标签）；kind/severity 过滤选中时按过滤结果平铺渲染（覆盖分组，负方向排除仍有效）；原始输出仍不默认展示（无 run_logs，展开的是写侧已蒸馏文字；全部动态串 esc 转义）。
- Task 生命周期区（archive/delete）。

## 人面 surface（修订 2026-10-26）

**Web 深潜页 = Task 生命周期（全走 REST）**：

| 按钮 | 请求 | 备注 |
|---|---|---|
| archive | POST `/requirements/{id}/archive` | state=ARCHIVED 时按钮禁用 |
| delete | DELETE `/requirements/{id}` | prompt 输入任务标题确认；不可逆，提示先 export |

**决策操作 = CLI/REST-only（Web 无入口）**：approve / release(reason) / renew / reopen(--continue) / note(content) / abandon(to_state) / set_expectations——语义与端点不变（PRD §4.2），Web 壳已移除对应按钮。深潜页等待人横幅含静态 CLI 提示（kind=review -> 人面确认: kanban approve <id>；kind=blocked -> 解除阻塞: kanban approve <id>）。

操作结果：成功 -> 回看板（`location.href = "/"`，看板即反馈；archive/delete 均为终态操作，user 裁决 2026-10-26 不再停留深潜页）；失败 -> 内联展示响应体 `{code, message}`（如 `illegal_state: ...`、`not_found: ...`），停留页面。

## 冒烟 checklist（浏览器人工）

1. `GET /?token=<t>` 打开看板页：需 token 或 localhost；任务行按需要关注置顶；无任务时显示「（无任务）」。
2. 数据与 `/board` JSON 一致（核对 title/state/进度/信号标签）。
3. 点深潜链接进深潜壳：三层结构（层0 决策线/层1 蒸馏/层2 次要）；验收对照缺口标红；事件流提纲优先（人面事件 `<details>` 默认收起，点开见 content 全文 + payload JSON；簿记事件折入「簿记 N」组默认收起）；kind/severity 过滤选中后按过滤结果平铺（覆盖分组，E3c/E11 口径）。
4. 生命周期操作：新建表单提交（带/不带 acceptance 两行锚、带 Jira 链接）成功且看板重拉出现新任务；对 CLAIMED 需求 archive 成功（回看板，任务出现在已归档 tab）；delete 输入错误标题被拒、正确标题删成功（回看板，任务消失）。深链直接访问不存在的任务 -> 友好文案“任务不存在（可能已被人删除）”。
5. 等待人提示：对 awaiting_human 任务确认深潜页与卡片横幅显示 `kanban approve <id>` 提示（静态文字，非按钮）；横幅/卡片文本按 `summary_line` 优先（评审交接一句话），缺失降级显 `reason`——渲染级断言覆盖四腿：E1（卡片：s10 显 summary_line、s3 显 reason）、E5（深潜横幅：blocked 显 reason）、E12（深潜横幅：review 显 summary_line 且不显 generic reason）。`kind` 兜底腿经 canonical API 不可达（mark_blocked 强制 reason 非空、request_review 强制 summary_line 非空），无渲染级断言，盲区登记见 docs/adr/0000-known-gaps.md G13。
6. SSE 断连重连行为：断网/服务重启后 EventSource 自动重连，onopen 触发重拉，页面结构自愈（无历史回填，数据以重拉结果为准）；页面打开状态下另一进程（如 MCP stdio agent）推进状态 -> 页面 2s 内自动刷新（`AGENT_KANBAN_SSE_POLL_MS`）。
7. `GET /board?status=CLAIMED` 等过滤有效。
8. 非 localhost 无 token 访问 -> 401，页面显示加载失败。
9. XSS 提纲中和（E9）：progress headline 含 `<img onerror=...>` 时，提纲位渲染为转义文本（页面文本含转义形态），页面无 img 元素注入、无 alert dialog；点开 details 见 content 全文。
10. 旧数据容忍（E10）：空 title 事件提纲位显 kind 标签；旧形状 `title="progress"` 原样显示；深潜页不崩。
11. 簿记折叠（E11）：簿记组标题「簿记 N」默认收起（closed），展开后平铺行 = N。
