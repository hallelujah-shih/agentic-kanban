# ADR 0003 - M0 决策裁决登记（租约/心跳/reconcile/ORPHANED/activity 口径 + G8 闭合 + G9/G10 登记）

状态: 已裁决（2026-10-22，M0-2；PRD §11 未决项死期折入 + 审#1/审#8/审#9/审#10 折入）
关联: docs/PRD.md §3.2（认领与租约）/§5.1（归属）/§6（可靠性/可观测）/§11（未决项）；docs/adr/0000-known-gaps.md G8/G9/G10；docs/plans/m0-plan.md（审#1/#8/#9/#10 折入）
问题: PRD §11 未决项（心跳模型/租约参数/MCP HTTP 形态）在 M0 内裁决；reconcile 观测源与 ORPHANED 语义钉死；activity 口径既有偏差登记；REST 归属与 HTTP 错误映射表契约化；G8 闭合、G9/G10 登记

## 裁决

- **心跳模型（§11 死期 M0 开工前）**: 默认 = 外部进程（心跳 = MCP 活动频率）。`last_activity_at` 由 agent 面写操作在写事务内更新（lease.touch_activity）；无独立心跳进程，不与进程存活挂钩。与 reconcile 观测源（claims 表 last_activity_at）同源一致。
- **租约参数（§11 死期 M0 内）**: lease 时长 2h / idle 阈值 30min，env 可覆盖（`AGENT_KANBAN_LEASE_SECONDS` / `AGENT_KANBAN_IDLE_SECONDS`）。M0-1 已实现，本 ADR 确认。
- **MCP HTTP 形态（§11 死期 M1 开工前）**: 不做（M1 未决默认）。
- **REST 归属（PRD 5.1 枚举无 rest）**: REST 面 `surface='cli'`（人面语义）+ `conn='rest:<短随机>'`（服务端派生，用 conn 区分传输，不接受调用方传入）。
- **ORPHANED 语义（审#8）**: 只属 reconcile 产物（报告 + 事件）。`claim_view.signal` 保持 PRD 推导序（ended/waiting/stale/suspect/active），view.py 现状不动。ORPHANED = 连接失活（last_activity_at 超 idle）且租约未过期且无 awaiting_human —— 即 SUSPECT 区间在 reconcile 时点的显式化；**等待中优先于 ORPHANED**（不因连接失活盖过「等待人裁决」）。drift/ORPHANED 入摘要「需要关注区」。
- **reconcile 观测源（审#1）**: claims 表（agent_conn + last_activity_at，共享 DB），**无进程内 conn registry**（跨进程各自 registry 会互相误标 ORPHANED）。agent_conn 为观测/审计记录，存活判定 = last_activity_at 超 idle。
- **触发（审#10）**: CLI `agent-kanban reconcile` 命令 + FastAPI lifespan（api/main.py 启动对账）；**MCP server 启动不跑**（避免多进程事件噪音）。
- **reconcile 写入**: append-only `kind='reconcile'` 事件（actor=system/reconcile），payload 含 findings（claim_id/requirement_id/signal）与 drift 明细；只标记不删除。**时点观测语义（结果盲审 P2-1）**: reconcile 事件是派生量（STALE/ORPHANED/drift）在扫描时点的快照标注，**无 ACTIVE 闭合事件（设计如此）**；当前状态以 claims 时间轴 + 视图时点重推导为准（view 展示前以当前事实重判，陈旧事件不可能产生陈旧显示）；**未来埋点禁用 reconcile 事件作状态源**（须用活推导）。M1 可选项：同一 claim 观测到非 active -> active 转移时写闭合事件（有前次非 active 观测才写，限噪），属契约变更待 M1 裁决。
- **activity 口径（G10 声明）**: `last_activity_at` 仅写调用更新（现状，lease.touch_activity 挂 agent 面写路径）；PRD 3.2「读写任一计活动」为既有偏差 -> 登记 G10（M1 定读计活动的连接级模型），本批不改；reconcile 用 last_activity_at 作观测源与 SUSPECT 同源一致。

## REST HTTP 错误映射表（契约，审#7 注明不可达码）

| 错误码 | HTTP | REST 触发端点 | 备注 |
|---|---|---|---|
| not_found | 404 | 不存在 requirement/claim 的读写端点 | - |
| illegal_state | 409 | 状态非法（如 OPEN 上 approve） | - |
| lease_expired | 409 | renew 已过期租约 | - |
| invalid_record | 422 | 载荷校验（缺 alternatives/空 reason/超 8KB 等） | - |
| db_busy | 503 | 写失败重试 3 次后 | - |
| already_claimed | 409 | 无（REST 无 claim 端点） | agent 面（MCP）专用码，保留作契约完整性 |
| no_active_claim | 409 | 无 | 同上 |
| duplicate_subtask | 409 | 无 | 同上 |
| queue_full | 409 | 无 | 同上 |

REST 错误 body 与 MCP 一致为 `{code, message, task_id}`；MCP 面保持 is_error 无 HTTP 码（PRD 4.3）。`/healthz` 豁免 token（探活）。

## G8 闭合（P2-2/3/4/5 均在 M0-1 完成）

Spike 结果盲审登记的 M0 缺口（docs/ops/spike-verification.md「结果盲审 P2 处置」）：

- P2-1 set_expectations links_to 删除保护 —— Spike 已实现。
- P2-2 REOPEN 边无接口可达 —— **M0-1 闭合**：CLI `reopen`（DONE->REOPEN / `--continue` REOPEN->OPEN，审#2-reopen 形状）+ REST 端点。
- P2-3 abandon 于 CLAIMED 的认领处置 —— **M0-1 闭合**：REJECTED/CANCELLED 同事务置 claim ended_at + 清 marker + 事件。
- P2-4 export LIMIT 200 截断 —— **M0-1 闭合**：export JSON/Markdown 独立全量查询，无 LIMIT。
- P2-5 读事务 BEGIN IMMEDIATE 锁竞争下非结构化读错 —— **M0-1 闭合**：读写 sessionmaker 拆分（读 deferred WAL 快照），读失败映射 db_busy 不裸抛。
- P2-6 代码卫生 —— 已删 rand_id 死代码；`_claim_hook` 保持 env 门控测试钩子（登记不修）。

G8 状态更新：docs/adr/0000-known-gaps.md 标注已闭合。

## G9 登记（M1）

- 数据保留清理命令（PRD 6：events 保留 12 个月，清理由显式命令执行，清理前必须导出）—— M0 不做，登记 M1。
- 重试成本超限判定（PRD 3.2「同一需求累计重试超 2 次进入'等你决策'清单」）—— 语义需 M1 澄清，登记 M1。

## G10 登记（activity 口径偏差，M1 定）

PRD 3.2「该 claim 的 agent 面任何写操作 + MCP 调用」计活动 vs 实现仅写操作更新 `last_activity_at`（读工具 list_tasks/get_task_detail 不 touch）。读计活动需连接级模型（连接建立/存活判定），M1 裁决；本批以写口径 + reconcile 显式化（ORPHANED/SUSPECT）覆盖观测需求，不引入读计活动。

## 生效与后续

- 生效点: 本 ADR 登记即 G8 闭合标注 + G9/G10 登记（docs/adr/0000-known-gaps.md 同步）。
- 后续: G9 两项在 M1 裁决；G10 读计活动的连接级模型在 M1 定；MCP HTTP 若 M1 推翻默认需回本 ADR 增补传输小节。
