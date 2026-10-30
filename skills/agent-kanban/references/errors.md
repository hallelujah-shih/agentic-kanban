# 错误码全表与处置

看板返回的业务失败都带一个码。处置按「你的动作」列做，**不要重试同一动作期待不同结果**。

| 码 | 含义 | 你的动作 |
|---|---|---|
| `already_claimed` | 需求已被其他 agent 认领（附持有者句柄） | 换任务，不要抢 |
| `not_found` | 需求不存在（id 短于 8 位 / 非 hex / 无此记录） | 用 `list_tasks` 确认 id |
| `ambiguous_id` | 前缀命中多条需求 | 加长前缀重试（或用完整 32 位 id） |
| `illegal_state` | 当前状态不允许该操作（如非 CLAIMED 时 request_review、重复 approve） | 读状态机边（<skill_dir>/references/contract.md）后纠正动作，不要重试 |
| `no_active_claim` | 本需求没有未结束的认领（已释放 / 已过期回收） | 重新 `claim_task`；若刚被释放，先看清是否人要求返工 |
| `lease_expired` | 认领租约过期（人面 renew 已失效） | agent 面无续租工具：转 `mark_blocked` 请人续租或重派 |
| `duplicate_subtask` | 子任务重复（同标题已存在） | 复用已有子任务，或改名表达差异 |
| `invalid_record` | 记录结构缺字段：decision 缺 alternatives / 缺证据 / 缺 headline / 缺 summary_line / title 或 reason 为空 / 验收自评漏项或形态错 | 按错误消息里的参数名、示例与可用清单补全后重发；不会静默丢弃 |
| `queue_full` | 并发认领超上限（16） | 等一个认领结束/释放后再认领 |
| `db_busy` | SQLite 忙（内部已重试 3 次） | 稍后重试一次；连续出现说明有并发写户在长事务里 |

补充：

- `claim_changed`（派发心跳内部的合成码）：心跳绑定的认领已变更，心跳自行退场；你不需要处理。
- `invalid_record` 消息里带「期望逐字 / 你提交的对照」时，说明是验收文本匹配失败——照抄子任务验收原文，不要改写。
- 所有码都是**可判定的失败**：先读码再动作，不要把它当成瞬时故障重试。
