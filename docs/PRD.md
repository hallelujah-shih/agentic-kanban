# Agentic Kanban - 产品需求文档 (PRD v3.3)

状态: 草案。v3.1 经双轴复审（需求轴 APPROVE-WITH-FIXES / 契约轴 REJECT 续审），本版折入全部 P1/P2（release 人面独占、approve 按状态判定、写锁先行、AC 错位、覆盖下界语义）；M1-3 折入：G10 裁决（ADR 0006——维持写口径 + 静默读意图内 + 连接级模型不引入）、§2 事件 kind 补 renew、§3.2 activity 行澄清（写口径 + renew 例外）、§4.2 prune 命令、§6 数据保留改终态需求级原子窗口；v3.3 折入：评审拒绝（review 拒绝边 CLAIMED->REOPEN + 人面 reject op + review_reject 事件，拒因/指向/轮次可观测可计数）、request_review 轮次（marker 与事件 payload 带 round）、§4.2 dispatch 条目与 REOPEN 派发自动折回 OPEN 语义、租约口径（拒结束认领不续租，返工新认领新窗口），契约版本 3.2 -> 3.3
里程碑: M0 完成（2026-10-22，AC10-13/15/17 + Spike AC1-9/16 + 9 码矩阵 + 补充全绿，验证见 docs/ops/m0-verification.md）；M1 未开工
定位: AI 时代的看板——不是任务状态跟踪，而是**大黑箱（AI 自动化执行）的关键节点暴露窗口 + 可回溯审计资产 + AI 与人对称交换关键信息的场所 + 关键决策的记录点/审计点**。看板不承担共识达成逻辑：子任务/里程碑的共识在 AI 会话内（in-band）达成，看板只展现结果；决策记录两类来源——人在 AI 中做出的决策（agent 以既有 decision/note 事件记录，带 actor provenance）与 AI 自主的决策（decision 事件）
读者: 实现者、后续维护者、评审者
关联: docs/design.md（设计理由）、docs/adr/（决策与残余登记）
BCD 引用: docs/business-contracts/g9b-retry-limit.md（G9-b 重试成本超限判定，判定源 user 裁决 = 系统派生计数，M1-4 前置产出）
BCD 引用: docs/business-contracts/distill-pipeline.md（记录管线蒸馏重构：提纲契约 + queue_full=16 + 关键事件最新优先有界 + 管线原则入 §0 + 深潜提纲优先，2026-10-27 五项裁决）

---

## 0. 定位与目标

AI 执行是黑箱：模型推理不可见、过程不可重放、输出质量不可信其自报。看板的价值不是展示进度条，而是**从黑箱中提炼出人需要知道的少数关键信息**，让人能做三件事：

1. **判断是否符合预期**：需求进入看板时由人写下预期验收标准（expectation anchor）；任务交回时，看板展示"验收对照表"——每项预期 vs 子任务验收项的覆盖与达成状态。人不需要读原始输出流，就能判断完成状态是否偏离自己的预期。
2. **判断是否有偏离**：偏离分两类，都必须在摘要视图可见——agent 显式登记的偏离（偏离了什么、原因、替代方案），以及系统从可观测状态推导出的偏离信号（子任务被放弃/阻塞、拆解范围变化、里程碑延误）。
3. **判断是否有更好的方案**：决策记录必须包含"考虑过什么、选择了什么、为什么拒绝其他"。事后人可以质疑决策，而不是只能接受黑箱结论。

**反淹没约束（最高设计约束）**：人的默认视图只展示关键节点（里程碑、决策、风险、偏离、等待人裁决、覆盖缺口），原始日志、会话内容、过程细节一律不默认展示。

**单一事件源（指引优先）**：完整内容留在其源头（Jira 详情、代码、会话原文），看板只存指针（链接/引用）+ 摘要。登记是 URL+摘要 还是完整详情并不重要，**做好指引更重要**；需要完整内容时由 agent 从源头获取。与反淹没互补：反淹没 = 不默认展示，本原则 = 不留存、只指引。

**报告纪律（agent 侧）**：写给人看的每一段文字（验收自评、decision rationale、deviation 原因、交接说明）必须**简约、大白话、无黑话**，尊重人脑带宽；报告里程碑与关键事件（节点），不报过程流水账。与反淹没互补：反淹没管视图展示什么，本纪律管 agent 写进记录的是什么。in-band 人的决策（人在 AI 会话中做出的决策）由 agent 以 decision/note 事件记录（带 actor provenance）= 预期模式，非可选行为。

**管线原则（蒸馏恰好一次，在生成点）**：蒸馏恰好一次，在生成点——写契约强制一行人话提纲（服务端只校验结构：非空；长度上限未强制——8KB 单事件 payload 上限作用于 note/content/payload；语义质量是写侧责任，服务端不生成人面文字）；存储/展示层忠实不聪明——不二次摘要、不做读侧语义挑选（读侧挑选 = 第二个蒸馏点，违反本原则）；人面记录必带提纲。与报告纪律互补：报告纪律管写什么，本段管蒸馏位置。

职责边界：看板是记录面 + 关键决策的记录点/审计点，不是控制面，不是共识达成场所。它不管理 worktree、不执行合入、不隔离执行。人面 surface 划分：Web = 只读视图 + task 生命周期（create/archive/delete）；决策操作（approve/release/renew/reopen/note/abandon/set_expectations）= CLI/REST-only（Web 无入口）。

### 0.1 全局不做清单

- 不做多 agent 同需求并行（一个需求 = 一个认领）。
- 不做多用户、RBAC、OAuth；不做外网部署；不做云端 SaaS。
- 不做 worktree 编排、合入执行、进程隔离（执行由 agent 工具链承担）。
- 不做模型推理或 prompt 编排。
- 不做移动端；不做 Web 之外的第二界面（M1 起）。
- 不做 PostgreSQL（SQLite 足够，双方言 CI 是纯成本）。
- 不做 Jira 自动导入/回写与任何内容搬运（单一事件源原则：完整内容留在源头，看板只存指针 + 摘要——Jira 需求、代码/PR、会话原文同理，由 agent 自行获取；AI 已能做好的事不重复造）。

---

## 1. 核心能力（可测）

- C1 反黑箱摘要：任一需求的默认视图可回答三问（对照预期验收 / 是否偏离 / 是否有更好方案），无需展开原始输出。
- C2 偏离显式化：登记偏离与推导偏离（见 5.3）都进入摘要视图；deviation 记录的结构与展示不依赖 severity 压级逃逸。
- C3 决策可追溯：每个 decision 记录含"备选方案 + 拒绝理由"，事后可质疑。
- C4 认领可排他：一个需求同时只被一个 agent 认领，抢占被拒并返回持有者。
- C5 状态不占死：任何占用有租约与到期信号；等待人裁决的任务与死掉的 agent 在视图上可区分。
- C6 终态可信：DONE 只能由人确认，不来自 agent 声明。
- C7 记录可回溯：5 条回溯判据（见 5.4）对未清理的完整事件链全部可回答；清理（prune，见 6）按终态需求级原子窗口整删，整删需求的历史以导出归档为准。

---

## 2. 对象与数据模型

| 表 | 关键字段 | 状态由谁写 |
|---|---|---|
| requirements | id, source(`jira`/`manual`), source_ref, title, description(摘要+工作区指针行), acceptance[]（人写预期验收锚）, state, awaiting_human{reason,evidence,since,kind,summary_line,round（kind=review 时：第几轮交接）}, created_at, updated_at | 状态机；acceptance 仅人面可写；DONE 仅人确认；source=`jira` 时 source_ref 存链接（引用登记，无自动导入）；description 存摘要，完整内容留源头（单一事件源）；工作区指针行（`workspace=<dir> env-card=<路径>`，约定见 SKILL「工作区就绪」，结构化字段后置）；summary_line 由 request_review 设置（评审交接一句话），mark_blocked 不设（blocked 用 reason） |
| claims | id, requirement_id, agent_name(声明), agent_conn(观测), started_at, lease_expires_at, last_activity_at, ended_at, release_reason | 系统推导（租约） |
| subtasks | id, requirement_id, ordinal, title, acceptance[{item, criteria, state: met|not_met|deviated, deviation_reason?, links_to[]}], state, milestone_id?, created_at, updated_at | agent 报告，带 provenance |
| milestones | id, requirement_id, title, planned_at?, actual_at?, state, created_at, updated_at | agent 报告，带 provenance |
| events | id, requirement_id, claim_id?, subtask_id?, milestone_id?, kind, severity, title, content, payload, actor_surface, actor_conn, seq, ts | 系统 append |

索引与约束（全部由 DB 强制）：
- `UNIQUE (requirement_id) WHERE ended_at IS NULL` on claims（认领排他）
- `UNIQUE (requirement_id, title)` on subtasks（归一：trim + casefold）
- `UNIQUE (requirement_id, ordinal)` on subtasks
- `UNIQUE (requirement_id, seq)` on events；seq 全局单调递增，服务端签发
- `ts` 由服务端在写入时签发，不接受调用方传入

事件 kind：`decision` / `risk` / `deviation` / `decomposition` / `progress_note` / `state_change` / `review_request` / `review_reject`（评审拒绝，人面 reject 写事件：payload={reason 拒因必填, target 子任务/锚 id 可空, round 被拒交接轮次}，severity=attention）/ `approval` / `release` / `renew`（人面续租写事件，可回溯谁续了租约）/ `note` / `reconcile`（对账事件，系统对账写事件，PRD §6 可观测）。
事件 severity：`info` / `attention` / `critical`。**deviation 的 severity 强制 >= attention**（不允许压级逃逸，见 5.3）。

`awaiting_human` 是 requirements 上的 JSON 列，不是状态：
- 设置：`request_review`（kind=review，不改需求状态）或 `mark_blocked`（kind=blocked，同时转移 CLAIMED -> BLOCKED）。
- 覆盖语义：新设置覆盖旧设置，旧设置对应事件保留（可回溯）。
- 清除（人的操作，与 approval/release/state_change 事件同事务）：approve（按 kind 清除对应标记）、release、reject、cancel、reopen。任何转移到终态或释放认领都会清除标记。

---

## 3. 状态机与认领

### 3.1 状态与边

OPEN -> CLAIMED -> DONE；侧向 BLOCKED / REJECTED / CANCELLED / REOPEN；终态 DONE / REJECTED / CANCELLED / ARCHIVED。

| from | to | 触发者 | 前置 |
|---|---|---|---|
| OPEN | CLAIMED | agent | 无未结束认领（DB 强制：ended_at IS NULL 谓词） |
| OPEN | CANCELLED | 人 | - |
| CLAIMED | DONE | 人 | 人确认（唯一终态来源） |
| CLAIMED | BLOCKED | agent | 附原因；同时设 awaiting_human(kind=blocked) |
| BLOCKED | CLAIMED | 人 | 解除阻塞，清除标记 |
| CLAIMED | OPEN | 人 | 释放认领（唯一释放路径，无自动释放） |
| CLAIMED | REOPEN | 人 | 评审拒绝（reject，见 3.5）：写 review_reject 事件（拒因/指向/轮次），同事务结束认领（release_reason=review_rejected）+ 清 marker；重入走 REOPEN->OPEN |
| DONE | REOPEN | 人 | 事后拒绝（reopen，与评审拒绝区分见事件链：本边无 review_reject 事件） |
| REOPEN | OPEN | 人 | 重开回到可认领（避免死端）；dispatch 遇 REOPEN 复派亦经本边自动折回（见 4.2 dispatch 条目） |
| REOPEN | CANCELLED | 人 | - |
| 任一 | REJECTED | 人 | 转移时清除 awaiting_human |
| 任一 | ARCHIVED | 人 | 终态，无出边（无 unarchive）；转移时清除 awaiting_human；同事务结束未结束认领（release_reason=archive） |

### 3.2 认领与租约

- 认领 = `INSERT claims` + 条件 `UPDATE requirements SET state=CLAIMED WHERE state=OPEN`，**单事务**，rowcount 校验；任一失败整体回滚。
- 释放（人面 CLI `release`，唯一释放路径）= 单事务（置 ended_at + 条件更新需求 CLAIMED -> OPEN + 写 release 事件），`release_reason` 必填。
- 评审拒绝（人面 CLI `reject`）同样结束认领（release_reason=review_rejected）且**不续租**（lease_expires_at 不改写）；拒后返工 = 新认领周期（REOPEN -> OPEN 后重新 claim，全新 lease 2h / idle 30min）——租约口径 = 重置（见 3.5）。
- 租约推导（不存状态字段）：
  - `ended_at 非空 -> 结束`
  - `now > lease_expires_at 且无 awaiting_human -> STALE`
  - `now > lease_expires_at 且有 awaiting_human -> 等待中`（不标 STALE）
  - `now - last_activity_at > idle 且无 awaiting_human -> SUSPECT`
  - 否则 `ACTIVE`
- **租约过期不自动释放、不自动重开**。过期只改变信号。释放的唯一路径是人的操作。
- activity 口径（写口径，ADR 0006 裁决）：`last_activity_at` = claim 最近活跃时间戳，agent 面写操作在写事务内更新；读操作（list_tasks/get_task_detail 等）不 touch——agent 只读不写被标 SUSPECT 属意图内（无写 = 无进展证据），等待场景由 awaiting_human 豁免；例外：人面 renew 同事务更新 `last_activity_at`（人续租证明）。
- 参数：lease 时长默认 2h，idle 阈值默认 30min，均可配置；默认值入 11 未决表 M0 内裁决。
- 不自动重试：重试对象是子任务（agent 侧），每次重试记录成本（token/时长），同一需求累计重试超 2 次进入"等你决策"清单（实现：系统判定超限后写一条 risk(severity=attention) 事件，入摘要"需要关注"区）。
  - 实现注记（M1-4，G9-b，判定源 user 裁决 = 系统派生计数）：判定源 = 系统从 `update_subtask` 状态迁移推导（非 agent 显式登记，威胁模型 B 下 agent 自报不可审计）；重试 = 子任务从**任何非 in_progress 状态重入 in_progress**（首入除外；from==in_progress 的 no-op 不计；含 done 重开、todo 退回再进、blocked/abandoned 再开工）；同一需求**跨子任务累计**（跨认领周期延续）；累计**严格超 2 次**（第 3 次重入）时写一条 risk(severity=attention) 事件，**幂等只写一次**（payload={retry_limit: true, count: N}，count = 触发时点快照，不随后续重试更新；marker 事件 actor_surface=system，幂等/信号谓词同一，agent 伪造 marker 不抑制告警不进信号）；计数来源 = events 链（state_change 重入推导，不建独立计数器表）；重试成本（token/时长）不建结构化字段，由 agent 在重试时用 note 自报（SKILL 指引），人读 note 感知代价。
- 服务重启对账：遍历未结束 claim，agent 连接不在 -> 标 STALE/ORPHANED，只标记不删除；并检测 claim-state 失配（有 claim 无 CLAIMED 或反之），报告 drift。

### 3.3 写保护

- 任何对 requirement 及其子项（subtasks/milestones/events）的写操作，要求存在未结束认领（agent 面）或交互面（人）。
- 校验与写入在**同一事务**内完成；该事务以写锁开启（BEGIN IMMEDIATE），重读/COUNT 与写入同提交点，否则读快照被并发提交失效（实测：deferred 事务存在读-写滞后窗）。避免校验后、写入前被并发释放的 TOCTOU。
- 校验只查 `ended_at IS NULL`，不校验租约有效性——租约只影响信号，不影响写权限（避免过期后需求卡死）。即 BLOCKED 期间持有未结束认领的 agent 仍可写（补充证据/记录），属意图内。
- 释放不属于 agent 面操作，不受写保护前置约束，由 4.2 人面执行。
- 违反返回 `no_active_claim`。

### 3.4 完成语义

- agent 的 `request_review` 是交接（设标记 + 持久化验收自评），不是状态变更。
- DONE 只能人确认。人确认与 approval 事件同事务。人确认 DONE 时，认领 `ended_at` 同步置位（同一事务）。
- `approve` 动作按**当前状态**判定，marker kind 只决定清除内容与事件：

| 状态 | kind | approve 行为 | 转移 | claim | 事件（同事务） |
|---|---|---|---|---|---|
| CLAIMED | review（或无 marker） | 确认 DONE | CLAIMED -> DONE | ended_at 置位 | approval + state_change，清 marker |
| BLOCKED | blocked | 解除阻塞 | BLOCKED -> CLAIMED | 不变（仍活跃） | state_change，清 marker |
| OPEN/DONE/REOPEN/REJECTED/CANCELLED | 任意 | 拒绝 | 无 | 无 | illegal_state |
| ARCHIVED | 任意 | 拒绝 | 无 | 无 | illegal_state |

  BLOCKED + kind=review 组合不可达：request_review 前置要求 state=CLAIMED（4.1）。
- DONE 后追加更正：写保护要求未结束认领，因此更正需人面操作（CLI `note`）或 REOPEN 后由 agent 继续——两条路径都明确，不冲突。

### 3.5 评审拒绝与返工轮次

- `reject` 前置：state=CLAIMED 且 awaiting_human.kind=review（语义对象是「待审交接」）。CLAIMED 无待审标记的退回走既有 `release --reason`（CLAIMED->OPEN），两路不混用。
- 拒绝可观测：reject 单事务 = 状态转移（CLAIMED->REOPEN）+ 结束认领（release_reason=review_rejected，不续租）+ `review_reject` 事件（severity=attention，payload={reason 拒因必填, target 子任务 id 或验收锚 id 可空, round}）+ 清 marker。谁拒＝事件 actor 归属；一次真实返工在板面可读出第几轮、谁拒、拒因。
- **round 两口径（单计数源，结构上无漂移）**：
  - 交接轮次：request_review 的 round = 1 + 本需求此前 `review_request` 事件数；marker 与事件 payload 同值。
  - 拒事件 round：读自被拒交接的 marker.round（被拒的是哪一轮交接就是几；legacy 标记无 round 键按 1）。
- 重复拒 = `illegal_state`：每个交接轮次至多一次 reject（第一次拒后 state=REOPEN，第二次前置不满足）；再次拒绝必须经由新一轮交接。
- REOPEN 双来源（事件链区分）：交接被拒（本节约，入边 from=CLAIMED + review_reject 事件）vs 完成被拒（既有，入边 from=DONE，无 review_reject 事件）。
- 返工重入路径：REOPEN -> OPEN（人面 `reopen --continue`，或 dispatch 复派时自动折回，见 4.2）-> 返工方首个动作 = `claim_task` 重认领（新认领行、全新租约）-> 返工 -> 再次 request_review（round 自动 +1，第几轮交接板面可区分）。

---

## 4. 记录渠道（MCP 工具面 + 人面）

### 4.1 MCP 工具面

transport：**stdio**（本地 agent 默认，opencode/Claude Code 直连）+ **streamable-http**（挂载 FastAPI /mcp，ADR 0005；与 stdio 共用同一工具注册表；localhost 默认 + token 一致）。agent 面无 release/approve/delete 工具，写保护语义两 transport 相同。

| 工具 | 语义 | 前置 |
|---|---|---|
| new_requirement | 建需求（规划入口，与人面 `new` 同 service 层、参数对齐）：title + description（长文本免 argv 转义）+ source/source_ref + acceptance[]（字符串或 {item,id} 形态，id 缺省自动分配 a1..；条目 item 文本非空，缺/空 -> invalid_record）；不写事件（规划通道，非执行证据） | 无（规划通道） |
| set_expectations | 设置/修改验收锚（与人面 `set_expectations` 同 service 层、唯一入口语义两面一致）；删除被 subtask links_to 引用的锚项被拒（invalid_record）；acceptance 条目 item 文本非空（缺/空 -> invalid_record） | 无（规划通道，无需未结束认领） |
| list_tasks | status 过滤，获取未完成任务 | 读 |
| get_task_detail | 需求 + 子任务树（含验收自评与覆盖对照）+ 里程碑 + 关键事件（最新优先，有界 200，输出 seq 升序；事件自带提纲——生成点写，无读侧语义挑选）+ 认领 + awaiting_human | 读 |
| claim_task | 独占认领（单事务） | 无未结束认领 |
| add_subtask | 拆解：title + acceptance[]（含 links_to 预期锚）+ ordinal；acceptance 条目 item 文本非空（缺/空 -> invalid_record），落库形态逐字保留（不归一） | 未结束认领 |
| update_subtask | state: todo/in_progress/done/blocked/abandoned | 未结束认领 |
| add_milestone | title + planned_at | 未结束认领 |
| update_milestone | state: planned/in_progress/achieved + actual_at | 未结束认领 |
| add_record | title 必填（一行人话提纲，空 -> invalid_record）；kind = decision / risk / deviation / decomposition / note；decision 必含 choice + rationale + alternatives[] + 拒绝理由（choice 缺/空 -> invalid_record）；deviation severity 强制 >= attention | 未结束认领 |
| update_progress | 进度备注（不覆盖派生值）；headline 必填（一行人话提纲，缺/空 -> invalid_record）；返回 lease_expires_at（租约到期时间，仅通知不延长租约——延长用 renew） | 未结束认领 |
| request_review | 设 awaiting_human(kind=review)，持久化验收自评到 subtasks.acceptance[].state，附证据（PR / commit 区间 / 测试摘要，至少一项，缺证据拒绝）+ summary_line 必填（交接一句话，缺/空 -> invalid_record）；review_request 事件 severity=attention；不改状态 | 未结束认领 且 state=CLAIMED（否则 illegal_state） |
| mark_blocked | 转移 CLAIMED -> BLOCKED + 设 awaiting_human(kind=blocked)，附原因（一行人话，为空 -> invalid_record） | 未结束认领 且 state=CLAIMED（否则 illegal_state） |
| list_awaiting | 全部"等你决策"条目，含等待时长 | 读（人面） |

释放不属于 agent 面：MCP 工具面无 release 工具，唯一释放路径为人面 CLI `release`（见 4.2）。

工具面自描述：各工具 description + server instructions 带内承载工具语义与记录契约（带内兜底，不依赖带外 skill 加载，威胁模型 B）。

### 4.2 人面（CLI/REST，非 MCP）

- `new`：创建需求（手工导入），可写入 acceptance 预期锚。agent 面等价入口＝MCP `new_requirement`（4.1，同 service 层，长文本免 argv 转义）。
- `new --source jira --source-ref <链接>`：以链接引用登记 Jira 需求（description 贴摘要，完整详情留在 Jira——单一事件源，由 agent 自行获取）；不做自动导入（AI 已能做好的事不重复造，ADR 0004）。
- `set_expectations`：设置/修改 requirement.acceptance（唯一入口；agent 面经 MCP `set_expectations` 同名可达（4.1），两面同 service 层语义一致）。锚项可修改文本；删除被 links_to 引用的锚项被拒绝（需 agent 先解除链接）；acceptance 条目 item 文本非空（缺/空 -> invalid_record）。
- `approve`：按**当前状态**确认（决策表见 3.4）——CLAIMED 上确认 DONE、BLOCKED 上解除阻塞；按 awaiting_human.kind 清除标记，写 approval/state_change 事件（同事务）。 `--on-behalf "<kind>:<basis>"` 受托代执行（kind ∈ statement|action，basis 一行指向依据；surface 服务端派生为 delegated，派生规则见 5.1）。`--requirement-id` 可省（零输入）：awaiting_human 恰 1 条直接执行 / 0 条提示「无待决项」零写 / 多条非交互通道拒绝（列候选含状态 + 提示携 --requirement-id；tty 编号列选，无效选择零写）；`--on-behalf` 结构非法 -> invalid_record（先于候选读取拒绝）。
- `release`：释放认领（唯一释放路径，人面）；要求存在未结束认领，无则 `not_found`；写 release 事件 + 清除 awaiting_human。`release --all-stale`：批量释放全部 STALE 认领（仅覆盖 CLAIMED 需求；逐项执行单释放语义，部分失败逐项返回，非全有全无）。 `--on-behalf` 与 `--requirement-id` 可省语义同 approve；零输入仍须 `--reason`（语义字段不免输，先于候选读取拒绝）。
- `reject`：评审拒绝（3.5）——前置 CLAIMED + 待审（awaiting_human.kind=review），缺任一 -> `illegal_state`；`--reason` 拒因必填（空 -> `invalid_record`，先于状态校验拒绝），`--target` 可选（子任务 id 或验收锚 id；非法值 -> `invalid_record`，消息含本需求可用清单）；单事务写 state_change（CLAIMED->REOPEN）+ `review_reject` 事件（拒因/指向/轮次）+ 结束认领（release_reason=review_rejected，不续租）+ 清 marker。`--on-behalf` 与 `--requirement-id` 可省语义同 approve；零输入候选仅含 kind=review 待审项（blocked 待决不混入），0 条提示「无待审项」零写。
- `renew`：续租（对已过期租约返回 `lease_expired`）。
- `note`：人追加更正/质疑（写入 note 事件）。
- `export`：JSON / Markdown 全量导出。
- `abandon`：REJECTED / CANCELLED。
- `archive`：归档（任一状态 -> ARCHIVED 终态，同事务结束未结束认领 release_reason=archive）；语义 = 移出活跃视野，**无工作判断**（区别于 abandon 的 REJECTED/CANCELLED）；无 unarchive。
- `delete`：整需求硬删（requirement + subtasks/milestones/claims/events 单事务原子，不写事件）；任意状态可删（含活跃认领）；不受数据保留窗口约束；删除后该需求的回溯承诺作废，建议先 `export` 留档（提示不强制）；Web 上需输入标题确认。
- `prune`：数据保留清理（§6）——`--months N`（默认 12，日历月 + 月末回绕 clamp）、`--export-path`（默认 `./exports/kanban-export-<ts>.json`）、`--yes` 跳过确认；流程 = 强制全量导出（timestamped JSON 0600，导出失败中止清理）-> 确认门（stdin `y/N`，EOF/拒绝/非 y 中止不删、非零退出）-> 按终态需求级原子窗口删除 events（仅 DONE/REJECTED/CANCELLED/ARCHIVED 且全部事件早于窗口的需求整删，链永不半断）。
- `dispatch`：worker 派发（worker 派发协议细节归 skill 树 dispatch reference，此处只登记状态面语义）：状态门 OPEN/REOPEN，其余状态 -> `illegal_state`；**遇 REOPEN 派发前自动折回 OPEN**——经既有 REOPEN->OPEN 边（人面 actor + 受托痕）、板 note 留痕、派发稿/续接稿注明；折回发生在 MCP 预检之后（预检拒派零写）、服务发现/会话创建之前；折回后派发失败不折回滚（需求已 OPEN，可认领或再派，幂等）。折回闭合的断点：claim 硬写 from_state=OPEN，REOPEN 下不折回则 worker 首个动作认领必失败。

**Web 窗口（M1，人面）**：

| surface | 语义 |
|---|---|
| `GET /board` | 看板默认列表（反淹没）：非终态需求 + 每需求派生需要关注信号（口径同 §5.3 摘要 `_derived_signals`，全口径含 decomposition_added/unexplained/orphaned/drift），返回 `{tasks, attention_ids}` |
| `GET /events/stream` | SSE 事件推送：全局 seq 游标、连接时刻初始化、无回填、纯触发器字段（语义见 §5.3） |
| `GET /` | 看板 HTML 壳：内联 JS fetch `/board` 渲染（在板/已完成/已归档 三 tab）+ 新建表单 + EventSource 重拉，无原始输出 |
| `GET /requirements/{id}` | 内容协商：Accept 含 `text/html` -> 深潜 HTML 壳（JS 渲染 + task 生命周期操作 archive/delete；决策操作 CLI/REST-only），缺省/`*/*` -> JSON（形状不变） |
| `GET /requirements/{id}/summary.html` | M0 静态摘要 HTML（保留，不冲突） |
| token 传播 | EventSource 无法设 header：页面从 URL `?token=` 读 token 存入 sessionStorage，全部 fetch/EventSource 附 token（localhost 默认无 token 不生效；非 localhost 单用户可接受 URL 可见 token，威胁模型 C） |

### 4.3 错误码

MCP `is_error` + structured content（`{code, message, task_id}`），无 HTTP 码：
`not_found | illegal_state | already_claimed | no_active_claim | lease_expired | duplicate_subtask | invalid_record | queue_full | db_busy | ambiguous_id`

每个码有唯一触发条件：`ambiguous_id` = requirement_id 短前缀（8~31 hex）命中 >=2 条需求（0 命中 -> not_found）；`lease_expired` = 对已过期租约 renew；`db_busy` = SQLite 写失败重试 3 次后（7.3）；`queue_full` = claim_task 计数超上限（16）；`invalid_record` = 记录结构缺字段（decision 缺 choice / 缺 alternatives / request_review 缺证据 / 缺 headline / 缺 summary_line / acceptance 条目缺 item 文本 / title 或 reason 为空 / delegated 结构非法（字符串形缺冒号 / kind 越 statement|action 枚举 / basis 空））；其余见工具表。

requirement_id 输入统一归一（strip + 大小写不敏感 + 连字符去除）；8~31 位 hex 唯一前缀可解析（>=2 命中 -> ambiguous_id）；32 位全 id 精确匹配优先；<8 位或非 hex -> not_found；MCP/REST/CLI 三面同源；响应的 requirement_id 与 ambiguous_id 错误候选列表为 32-hex 形态，not_found 消息与错误 task_id 保留原始输入。

---

## 5. 归属、视图与回溯

### 5.1 三类归属

| 类别 | 例子 | 可伪造性 | 用途 |
|---|---|---|---|
| 系统观测 | MCP 握手签发的 conn id、服务签发的 seq/ts、租约 | 低 | 审计链锚 |
| 外部引用 | OpenCode session id（`ses_...`）、Jira key、分支名 | 中 | 重放与定位 |
| 自报声明 | "我是 deepseek harness"、"测试通过" | 高 | 存 payload，标注声明，不作为事实 |

`actor_surface`（`mcp`/`cli`/`system`/`delegated`）与 `actor_conn` 由服务端派生，不接受调用方传入。`delegated`＝人面上代执行：人面入口（CLI `--on-behalf` / REST 受托 body）+ 结构有效受托参数 -> 服务端派生落此值，且该命令写出的每条事件必带 `payload.delegated={kind,basis}`（单点派生，配对；MCP `add_record` 自由 payload 可含同名键为登记例外，审计检索代执行面主键＝`actor_surface=delegated`）。delegated 的源必须是已发生的人的决定（statement＝人会话表态 / action＝人工作面动作中 agent 结构性做不了的），agent 只翻译不产生；MCP 面无受托参数入口，恒 mcp。决策/风险/偏离不可编辑，只能追加更正（人面 `note` 或 REOPEN 后 agent 追加）。

### 5.2 结构与声明的诚实区分

| 信息 | 来源 | 可否信 |
|---|---|---|
| 子任务/里程碑状态、验收自评 | agent 报告（标注 `reported by <agent> at <ts>`） | 声明，可更新 |
| requirement.acceptance（预期锚） | 人面写入 | 人确认 |
| 需求级 DONE | 人确认 | 唯一可信终态 |
| 认领、租约、seq、ts、conn | 系统观测 | 事实 |
| 决策/风险/偏离内容 | 写入即记录 | 记录，不可编辑 |

进度用派生值：done / (总数)，其中 blocked 计为"进行中"，abandoned 不计入分母；缺对应 deviation/note 记录的 abandoned 由视图标"未解释的放弃"入"需要关注"区（视图告警，不作写时拒绝）。

### 5.3 视图原则（反淹没 + 偏离可见）

摘要视图（默认）包含：
- 里程碑时间线（含延误：planned_at 未达成且超期，或 achieved 但 actual_at > planned_at 的迟达 -> 延误标记）
- 决策 / 风险 / 偏离列表（deviation 无条件展示，不随 severity 过滤；risk severity >= attention 展示）
- **验收对照表**：requirement.acceptance 每项 -> 逐锚显示链接它的子任务验收项文本及状态（非仅聚合缺口）；无覆盖的预期项 -> 覆盖缺口，突出显示。覆盖判定为**下界语义**：links_to 由 agent 填写，只保证未链接的锚项必然显示缺口；已链接锚项的覆盖质量（如窄标准链接粗锚）由人按对照表的锚项-链接项对账目视判断，不自动判定
- 子任务状态清单（state 含 blocked/abandoned）
- **派生偏离信号**（系统推导，不依赖 agent 自愿登记）：子任务进入 blocked/abandoned、拆解后子任务数新增、里程碑延误。这些进入"需要关注"区。范围减少路径由 abandoned 承担（拆解无删除工具，见 4.1）
- 认领信息（谁、何时、租约信号）与 awaiting_human 标记

深潜视图（按需展开，M1 Web 壳），三层结构（蒸馏先行，BCD distill-pipeline）：
- 层 0 决策线：标题 + state + 描述 + 等待人横幅（awaiting_human.summary_line 在场显该一句话——评审交接"做了什么/先看哪"；缺失降级显 reason——blocked/旧数据）+ 认领/租约 + 进度 + 需要关注区。
- 层 1 蒸馏：验收对照表（覆盖缺口标红）+ 决策/风险/偏离（决策展开备选与拒绝理由）。
- 层 2 次要：子任务清单、里程碑。
- 事件流提纲优先（按 kind/severity 过滤）：人面事件逐条默认收起，提纲位 = title（空则降级显 kind 标签），点开看 content/payload 全文；簿记事件折入单一"簿记 N"组默认收起。
- audience 单点派生：kind -> human/bookkeeping（服务端单点派生，读面禁止按 kind 重分类；未登记 kind 归人面）。
- 支持重建事件发生时需求的状态（由 state_change 链 + 该时点事件推导）。

看板视图（Web 默认列表，M1）：每需求一行紧凑行（title/state/awaiting_human/claim/progress/needs_attention），需要关注需求置顶；`needs_attention` 口径与摘要视图同源——每需求以 `_derived_signals` 全口径派生（blocked/abandoned/未解释放弃/里程碑延误/拆解新增无解释/orphaned/drift），返回 `attention_ids` 供置顶；risk 计数 severity>=attention 过滤同摘要；覆盖缺口经摘要验收对照表展示（口径同源，board 不默认展示缺口明细）。

事件推送（SSE，M1）：`GET /events/stream` 以全局单调 seq 为游标（`WHERE seq > last_seq ORDER BY seq`）；游标初始化 = 连接时刻（无历史回填）；帧只含纯触发器字段 `{seq, requirement_id, kind, severity, ts, actor_surface, actor_conn}`（无 title/payload——客户端收到"变了"即重拉结构，反淹没）；无 `id:` 帧、忽略 Last-Event-ID；keepalive `: ping`；每轮询新读事务（WAL 快照不跨轮询，跨进程写入可见）。

**反淹没结构保证**：原始输出流不在数据模型内（无 run_logs 表，payload 上限 8 KB，深潜视图只存外部会话引用），摘要视图结构上不可能包含原始输出。

### 5.4 回溯判据

1. 为什么 DONE -> state_change 链 + 人确认的 approval 事件。
2. 这个决策当时在什么状态下做出 -> decision 事件 + 需求当时状态（state_change 链推导）+ conn + ts + alternatives。
3. 谁在什么时候做了什么 -> claims 时间轴（含 release_reason）+ 事件归属。
4. 分解与里程碑如何演化 -> subtasks/milestones 每次变更与其事件**同事务**写入，可重建时间线。
5. 产出物在哪 -> review 证据字段（PR / commit 区间）。

机制保证：所有写路径"变更 + 事件"同事务（含 approval 与 DONE 转移、子任务变更与 state_change）。回溯保证限于保留窗口（12 个月），清理前必须导出（见 6）。

---

## 6. 非功能需求

| 维度 | 目标 | 不写时的默认风险 |
|---|---|---|
| 并发 | 未结束认领上限 16；`claim_task` 在事务内以写锁（BEGIN IMMEDIATE）COUNT + INSERT 校验，超限返回 `queue_full`；计数含 STALE 与等待中（占位都算）；STALE 占满上限时恢复路径为人面批量释放（`release --all-stale`） | 无上限 -> 大量 STALE 堆积 |
| 数据量级 | < 5k 需求、< 100k events、单事件 payload < 8 KB | 事件无上限 -> SQLite 膨胀 |
| 性能 | 摘要视图 < 200 ms（5k 需求）；状态/记录写 < 50 ms | 无界 -> 窗口不可用 |
| 安全 | 默认绑定 127.0.0.1；非 localhost 绑定必须带 token 并启动告警；DB 文件 0600 | 本机任意进程可污染审计链 |
| 数据保留 | events 保留 12 个月；清理由显式命令 `prune` 执行（--months N 默认 12，日历月）；**终态需求级原子窗口**：仅 DONE/REJECTED/CANCELLED/ARCHIVED 且全部事件早于窗口的需求整删（链永不半断），非终态（含僵尸/STALE）全留 = 活审计主体；清理前强制导出（timestamped JSON 0600，导出失败中止清理），导出文件为审计资产最终载体；另有人面定点即时删除（4.2 delete）：任意状态、不强制导出、不受窗口约束、删需求行（prune 只删事件留需求行）；数据量级主要由活跃需求数决定（prune 只释放终态/僵尸） | 无限保留 -> 隐私与备份风险；回溯承诺（C7）限于保留窗口，整删需求以导出归档为准 |
| 可观测 | 每次转移/交接/对账写事件；`/healthz`；埋点：等你决策清单等待时长（ts(清除) - ts(设置)）、STALE 率、偏离登记率、覆盖缺口数 | 反黑箱目标无法度量 |
| 可靠性 | 重启后未结束认领与真实连接对账 + claim-state 失配检测；不一致标 drift，不自动删除 | 静默丢失占用状态 |
| 退役 | 6 个月内 events < 100 则归档并说明替代方案 | 僵尸项目 |

威胁模型：
- A: 本机任意进程通过接口写记录污染审计链 -> 默认 localhost + token（非 localhost）+ 写保护（3.3）。残余：直接写 SQLite 文件不可防（G1）。
- B: agent 内容不可信（偏离不登记、自评造假）-> 结构强制（decision 必含 choice + alternatives、验收自评表、deviation 强制 attention）+ 派生偏离信号（不依赖自愿登记）+ 人抽查（G2）。
- C: 无鉴权 API 暴露任务内容 -> 默认 localhost 绑定。

---

## 7. 技术架构

### 7.1 选型

- Python 3.12+；uv（`[dependency-groups]`，不用已废弃的 `[tool.uv] dev-dependencies`）。
- FastAPI + Pydantic v2；SQLAlchemy 2.0 async + Alembic（sync engine）；SQLite，不做 PostgreSQL。
- MCP：`mcp>=2.3,<3`，stdio（M0）。mcp 2.x：`mcp.server.fastmcp` 已移除（改名 `MCPServer`），单向门，开工前登记 ADR。
- 前端：M0 终端视图 + 按需静态 HTML；M1 Web 窗口。

### 7.2 目录

```
agentic-kanban/
  pyproject.toml
  alembic.ini
  Dockerfile
  docker-compose.yml
  src/
    main.py
    config.py
    database.py            # connect 事件: PRAGMA foreign_keys=ON, journal_mode=WAL, busy_timeout
    models/                requirement.py, claim.py, subtask.py, milestone.py, event.py
    schemas/               requirement.py, claim.py, record.py
    services/
      state_machine.py     # 唯一转移执行点（含单事务与 rowcount 校验）
      identity.py          # 接口面 -> 可执行动作的派生
      lease.py             # 租约推导 + activity 口径
      reconcile.py         # 重启对账 + claim-state 失配检测
      view.py              # 摘要视图 / 深潜视图组装（覆盖对照、派生偏离）
    api/v1/requirements.py
    mcp/server.py
    cli.py                 # 人面：new(--source jira --source-ref <链接>) / set_expectations / approve / release(--all-stale) / renew / note / abandon / export
  tests/
  docs/adr/
```

### 7.3 契约级要点

1. 状态转移唯一执行点 `state_machine.transition(...)`；REST 与 MCP 都调用它；转移与事件同事务。
2. 认领/释放为单事务（INSERT claim + 条件 UPDATE，rowcount 校验），见 3.2。
3. 写保护在 service 层统一校验，与写入同事务（3.3）。
4. SQLite：`PRAGMA foreign_keys` 默认 0（实测），connect 事件开启；WAL + busy_timeout；写失败重试 3 次后 `db_busy`。
5. UUID 用通用 `sqlalchemy.UUID`；所有写入走 ORM 类型绑定，禁止 raw SQL 传 UUID 字符串（混合格式破坏查询与 FK 校验，实测）。
6. 时间存 UTC，`TypeDecorator` attach tz（SQLite `DateTime(timezone=True)` 往返丢 tzinfo，实测）；禁用 `datetime.utcnow`（3.12 起废弃，3.14 仍存在仅警告；用 lint + `-W error` 拦截）。
7. 状态转移读-改-写用条件更新 + rowcount 校验。
8. Alembic 走 sync engine（async 需 `run_sync` 包装）。
9. partial unique index（认领排他、子任务去重）在 SQLite 用 `CREATE UNIQUE INDEX ... WHERE ...`；ORM upsert 必须用裸 `ON CONFLICT DO NOTHING`（带显式目标的 `ON CONFLICT(col)` 与 partial index 不匹配会报错，实测）。

---

## 8. 里程碑

| 阶段 | 交付 | 完成判据（编号见 9） | 不做 |
|---|---|---|---|
| Spike（2 天） | CLI + SQLite + MCP stdio：requirements(acceptance) + claims(租约) + subtasks + milestones + events + 工具面；agent 协同技能（skills/agent-kanban/）+ MCP 配置说明（docs/mcp-config.md） | AC1-9、AC16 | Web、Jira、对账、视图 |
| M0 | 摘要/深潜视图（CLI + 静态 HTML）、交接/标记语义完整、导出、对账、派生偏离 | AC10-13、AC15、AC17 | Web 窗口 |
| M1 | Web 窗口（AI-人沟通渠道，必须）、MCP HTTP | AC14（一周试用协议，G3 基线采集完成为硬前置） | 控制面任何能力；Jira 导入/回写（已裁决不做，ADR 0004） |

Spike 前置任务（不可跳过）：候选工具调研与裁决已完成（docs/adr/0001-reuse-vs-build.md，无候选满足合取，自研为主 + agent-kanban-pm 为移植种子）。Spike 内实操验证收窄为：对 agent-kanban-pm 骨架做 2h 移植性验证（MCP 面能否推进状态，对应 AC1/2/3 场景，G7）。

---

## 9. 验收判据（对抗性，按里程碑标注）

Spike：
1. 认领排他：并发 10 次 `claim_task` 同一需求，1 成功 + 9 `already_claimed`；且认领事务崩溃（进程 kill 于 INSERT 与 UPDATE 之间）不留半态。
2. 租约信号：租约过期且无 awaiting_human -> STALE；有标记 -> 等待中；两者不同；过期后不自动释放、不自动重开。
3. 终态可信：agent 通过任何接口面无法把需求置为 DONE；只有人面 approve 可。approve 在 CLAIMED 上确认 DONE、在 BLOCKED 上解除阻塞，二者均可测；BLOCKED + kind=review 组合经 request_review 前置（state=CLAIMED）拦截。
4. 决策结构强制：`add_record(kind=decision)` 缺 alternatives 或拒绝理由 -> `invalid_record`。
5. 偏离压级防护：`add_record(kind=deviation, severity=info)` 被拒绝或强制升为 attention。
6. 写保护：无未结束认领的写 -> `no_active_claim`；并发释放与写入竞争时（释放与写入并发）不产生孤儿记录。
7. 子任务冲突：同 requirement 同 title（含大小写/空白差异归一后）第二次 `add_subtask` -> `duplicate_subtask`。
8. 并发上限：第 17 个 `claim_task` -> `queue_full`（计数含 STALE 与等待中）。
9. 租约续租：对已过期租约 renew -> `lease_expired`。
16. 释放仅人面：agent 面无任何释放工具；CLI `release` 在 CLAIMED 上释放成功并写 release 事件（含 reason）且需求回 OPEN，无认领时返回 not_found。

M0：
10. 反黑箱判别力测试：构造含"压级风险（risk severity=info，摘要按 5.3 过滤不可见）+ 窄化验收 + 虚假覆盖（agent 将窄验收项链接到粗锚项以消缺口）+ 未登记的结构偏离（abandoned 子任务）+ 备选方案"的需求，受测者仅凭摘要视图能答出三问（符合预期 / 偏离 / 更好方案），其中"符合预期"须判为不达标——依赖对照表可见的链接映射而非缺口高亮；压级风险不可见时，其余信号仍须足够作答，答不出即失败。
11. 覆盖缺口：requirement.acceptance 中无子任务验收项覆盖的条目在摘要视图突出显示。
12. 派生偏离可见：子任务进入 blocked/abandoned 或里程碑延误后，无需 agent 登记任何 deviation，摘要视图"需要关注"区出现对应信号。
13. 反淹没：摘要视图不含原始输出流内容（结构保证：数据模型中无 run_logs 表）；关键信息可在不展开事件流的情况下读取。
15. 回溯：5 条判据逐条用真实数据回答，导出 JSON/Markdown 完整且含 events 全文。
17. 证据强制：`request_review` 缺证据（PR / commit 区间 / 测试摘要全缺）被拒绝。

M1：
14. 一周试用协议：真实需求 N >= 5；每个需求逐项回答三问并打分；"无法回答"计数为 0 且反淹没主观评分 >= 阈值（阈值 M0 后按基线定）；G3 基线采集完成是前置条件。

---

## 10. 残留登记（详见 docs/adr/0000-known-gaps.md）

| 编号 | 残留 | 档位 | 升级路径 |
|---|---|---|---|
| G1 | 本机 shell 可直接写 SQLite，污染审计链 | ② | 文档声明边界；未来 DB 文件只读 + 单写进程 |
| G2 | 偏离/验收自评的真实性不可完全验证（agent 造假） | ② | 结构强制 + 派生偏离信号 + 人抽查 |
| G3 | 痛点基线未采集 | ③ | M0 前一周手工日志；M1 试用协议的硬前置 |
| G4 | MCP SDK 2.x 选型未登记 ADR | ② | 开工前登记 |
| G5 | 性能目标无基准 | ③ | M1 跑基准 |
| G6 | 候选工具未调研，自研依据未闭合 | ② | 已裁决（docs/adr/0001-reuse-vs-build.md） |

---

## 11. 未决事项与死期

| 事项 | 死期 | 未裁决时的默认 |
|---|---|---|
| 心跳模型：harness 外部进程（心跳 = MCP 活动）vs 看板拉起（心跳 = 进程存活） | M0 开工前 | 外部进程 |
| 租约参数：lease 时长 / idle 阈值 | M0 内 | 2h / 30min |
| Jira 导入/回写 | 已裁决（ADR 0004） | 不做（Jira 需求以链接引用登记） |
| request_review 证据强制 | M0 内 | 已定：至少一项，缺证据拒绝（PRD 4.1 + AC17；design.md §4 同步） |
| MCP HTTP 形态 | 已裁决（ADR 0005） | 做（streamable-http 挂载 FastAPI /mcp，与 stdio 并存；localhost 默认 + token 一致） |
| 候选工具裁决 | Spike 前 | 已裁决：自研 + agent-kanban-pm 移植种子（ADR 0001） |
