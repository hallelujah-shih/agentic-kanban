# 最小契约（状态机 / 租约 / 写保护 / 视图与回溯）

本文只写执行时判断需要的口径；完整权威文本见文末 URL。视图与工具面语义以服务端实现为准，本文不重复参数逐个说明。

## 状态机边

需求状态：`OPEN` / `CLAIMED` / `BLOCKED` / `DONE` / `REOPEN` / `CANCELLED` / `REJECTED` / `ARCHIVED`。
允许的转移（from -> to，括号内是执行面）：

| 转移 | 执行面 |
|---|---|
| OPEN -> CLAIMED | agent（claim_task） |
| CLAIMED -> BLOCKED | agent（mark_blocked） |
| CLAIMED -> OPEN | 人（release） |
| CLAIMED -> DONE | 人（approve） |
| BLOCKED -> CLAIMED | 人（解除阻塞 / 重派） |
| DONE -> REOPEN | 人（reject 返工） |
| REOPEN -> OPEN | 人（重排队） |
| OPEN -> CANCELLED | 人 |
| REOPEN -> CANCELLED | 人 |
| 任一 -> REJECTED | 人 |
| 任一 -> ARCHIVED | 人 |

不在表内的转移一律 `illegal_state`。转移到除 BLOCKED 外的状态会同时清 `awaiting_human` 标记。**agent 面无 DONE / release / approve 工具**：这些只能由人在人面执行（或 agent 代执行收尾协议，见 SKILL.md）。

## 租约：两个时钟

- **活动时钟** `last_activity_at`：每次 agent 面写操作在同一事务内更新，用于判 SUSPECT（静默失联）。
- **租约时钟** `lease_expires_at`：认领时写死（默认 2h），**写操作不延长**，到点即失效。

派生信号（按序判定，不存状态字段）：认领已结束 -> `ended`；租约过期 + 有等待人标记 -> `waiting`；租约过期无标记 -> `stale`；未过期但静默超 idle（默认 30min）且无标记 -> `suspect`；否则 `active`。

**续租是人面操作**：agent 面无 renew 工具。预计总时长超过租约的任务，开工前请人续租，或改走客户端派发心跳（见 dispatch 协议）。租约过期后 agent 面写操作会被拒（`lease_expired` / 认领已结束）。

## 写保护

- agent 面写操作要求**存在未结束的认领**（ended_at 为空），校验与写入同事务（写锁先行），不存在则 `no_active_claim`。
- 需求 id 解析统一归一（去空白 / 大小写 / 连字符）：32 位 hex 精确匹配优先；8-31 位 hex 唯一前缀可解析，多命中 -> `ambiguous_id`，短于 8 位或非 hex -> `not_found`。三面（MCP / REST / CLI）同源。
- actor（conn id / seq / ts）由服务端从传输会话派生，不接受工具参数传入。

## 视图与回溯

- **卡片视图**（`list_tasks`）：未终态需求 + 状态 + 等待面摘要。
- **深潜视图**（`get_task_detail`）：需求登记、子任务与验收锚、里程碑、事件流（关键事件优先，默认有上限）。
- **等待面**（`list_awaiting`）：只认等待人标记（review / blocked 等），是人查询待裁决事项的唯一入口。
- **导出**（CLI `export`）：JSON / Markdown 含事件全文，供审计与回溯。
- 事件不可编辑，只能追加更正；需求级 DONE 以人的确认为事实。

完整契约（状态机 / 租约 / 工具面 / 错误码的权威文本）：https://github.com/hallelujah-shih/agentic-kanban/blob/main/docs/PRD.md
