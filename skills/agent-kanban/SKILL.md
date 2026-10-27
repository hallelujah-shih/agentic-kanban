---
name: Agent Kanban
description: 通过 agent-kanban 看板 MCP 与人类及其他 agent 协同工作的协议。当环境中出现 agent_kanban_* 工具（list_tasks / claim_task / add_subtask / add_record / request_review 等）且要开始或继续看板任务时加载。说明如何认领、拆解、记录决策/风险/偏离、交接评审，以及哪些是人的职责（DONE 确认、释放、解除阻塞）。与 docs/PRD.md v3.2 契约一致。
---

# Agent Kanban 协同协议

看板是**记录面 + 关键决策的记录点/审计点，不是控制面**。执行（worktree、合入、进程）由你的工具链负责；看板负责状态、结构与记忆。人只看摘要视图（关键节点），不读原始输出——你的职责是把关键信息**结构化喂给看板**，而不是倒日志。

## 门序（每段工作照此走）

1. 读：`list_tasks`（按状态过滤）-> `get_task_detail`（需求登记 = 来源指针 + 摘要 + requirement.acceptance 预期锚 + 现有拆解/里程碑/关键事件）。先读后动，尤其先看预期验收锚；完整内容（Jira 详情/原文）按链接从源头获取（单一事件源）。
2. 认领：`claim_task`。独占；`already_claimed` 说明别人持有，换任务，不要抢。
3. 拆解：`add_subtask`，每条带 acceptance[]（验收项 + 链接预期锚 links_to）。不要窄化范围；锚项无覆盖会显示覆盖缺口，这是有意的下界语义。
4. 执行 + 记录：见「记录纪律」。
5. 交接：`request_review`（附证据 + 验收自评表），然后**等人**。
6. 等裁决：DONE 由人确认（approve）。人可能拒绝/要求返工（REOPEN 后你继续）。

## 认领纪律

- 认领排他：一个需求同时只一个 agent。抢占返回 `already_claimed` + 持有者句柄。
- 租约：lease 2h / idle 30min（可配置）。任何 MCP 写操作都是活动（更 last_activity_at，防 SUSPECT）；租约**不自动续**——延长需显式 renew（可据 update_progress 返回的 lease_expires_at 决策）。长时间无活动 -> SUSPECT，过期 -> STALE（人可见告警）。
- **释放是人的职责**：agent 面无 release 工具。不要试图用 mark_blocked 或伪造状态"退出"；确实要放弃就 `mark_blocked` 说明原因，等人裁决（release / reject）。
- 重试：同一需求累计重试超 2 次，系统会写 risk 事件并进"需要关注"区——这意味着你要向人说明，而不是继续闷头重试。
- **重试成本自报**：每次重试时用 `add_record(kind=note)` 报本次重试的成本（token 数 / 耗时），让"重试代价"进事件流——系统只计数不记成本，人靠你的 note 看到一次重试付了多少钱。

## 记录纪律（命名记录契约）

每条人面记录三段：

- **提纲**（一行人话）：`update_progress.headline` / `add_record.title` / `request_review.summary_line` / `mark_blocked.reason`，服务端强制非空，缺/空 -> invalid_record（错误消息带参数名与示例，据此自纠）。
- **所以呢**：对预期的影响（验收对照/偏离）或需要人做什么（approve/解除阻塞/返工）。
- **可选细节**：content/payload，倒日志式细节不写。

报节点，不报流水账。

## 报告纪律（写给人看的每一段文字都遵守）

- **简约**：像给同事一句话汇报，不是写论文。验收自评理由、decision rationale、deviation 原因、交接说明默认几行以内；详情留给原始输出，看板只写"结论 + 关键证据"。
- **大白话**：用日常语言，假设读者是懂业务的普通人，不是同行评审。
- **无黑话**：不用空词堆砌（抓手/闭环/赋能/范式转移之类）；术语必须让读者秒懂，否则换说法。
- **人脑带宽**：人一次只能消化少数关键信息。报告节奏 = 里程碑达成、决策、风险/偏离、等待人裁决、交接——不是每步流水账。一次评审只报"做完了什么 + 偏离了什么 + 请你看哪里"。
- **里程碑与关键事件优先**：该报告的是节点（里程碑、决策、风险、偏离、覆盖缺口），不是过程。

## 交接与等待

- `request_review`：要求 state=CLAIMED；必须附证据（PR 链接 / commit 区间 / 测试摘要，至少一项，缺了被拒 invalid_record）+ summary_line（交接一句话：做了什么/先看哪，缺/空 -> invalid_record）+ 逐项验收自评（met / not_met / deviated + 原因）。附三行人简报：做了什么 / 先看哪 / 还剩什么，summary_line 承载第一二句。它**不改状态**，只设 awaiting_human(kind=review)。
- `mark_blocked`：只有真需要人决策才用（需求转 BLOCKED + awaiting_human(kind=blocked)）。reason 必写一行人话原因（报节点不报流水账），进事件链可回溯。
- 人与你 inline 交互（会话内当场问答）**不经看板**：结果记一条 decision 事件即可，不设标记，流程零中断。只有交接在会话之外（session 结束、人不在场）才需要 request_review / mark_blocked。
- **永不声称 DONE**：DONE 只能人确认。你的 request_review 是"交回请审核"，不是完成。

## 错误码速查

| 码 | 含义 | 你的动作 |
|---|---|---|
| already_claimed | 已被其他 agent 认领 | 换任务 |
| not_found | 任务不存在 | 查 list_tasks |
| ambiguous_id | 前缀命中多条需求 | 加长前缀重试 |
| illegal_state | 状态不对（如非 CLAIMED 时 request_review） | 按状态机纠正 |
| no_active_claim | 认领已结束/被释放 | 重新 claim_task |
| lease_expired | 对过期租约 renew | 无法续，等人处理 |
| duplicate_subtask | 拆解重复 | 复用已有子任务 |
| invalid_record | 记录结构缺字段（decision 缺 alternatives / 缺证据 / 缺 headline / 缺 summary_line / title 或 reason 为空） | 补全字段 |
| queue_full | 并发认领超上限 16 | 等一个释放再认领 |
| db_busy | SQLite 忙（重试 3 次后） | 稍后重试 |

## 诚实与归属

- actor（conn id、seq、ts）由服务端从传输会话派生，不接受你传入。你的 OpenCode session id（ses_...）会作为外部引用进审计链——不要伪造身份。
- 你报告的结构（子任务/里程碑状态、验收自评）标注 `reported by <agent>`，是声明不是事实；需求级 DONE 只有人确认才是事实。
- 决策/风险/偏离不可编辑，只能追加更正。

## 参考

完整契约：`docs/PRD.md`（v3.2）第 3（状态机/租约/写保护）、4（工具面/错误码）、5（视图/回溯）节。安装与配置：`docs/mcp-config.md`。
