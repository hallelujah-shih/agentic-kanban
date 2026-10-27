# 设计文档 v3 — 人机共享状态 + 审计记录层（承载结构化深度）

关联: docs/PRD.md（v3.2，含反黑箱目标）；本文件说明设计理由与决策过程
状态: 建议，随 PRD v3.2 生效
历史: v1（控制面方向，被推翻）-> v2（记录面 + 窗口）-> v3（结构化深度 + 反黑箱目标）

---

## 0. 定位

看板是**记录面 + 关键决策的记录点/审计点**，不是控制面，不是共识达成场所（定位修订 2026-10-26，spec: docs/superpowers/specs/2026-10-26-task-lifecycle-positioning-design.md）。

- 需求手工登记进入看板（Jira 需求以链接引用登记，不做自动导入）。
- 一个原始需求 = 一个 agent 认领并执行（并行发生在跨需求）。
- 调度、分解、里程碑设定是 agent（你的 harness + opencode v2）做的，但**这些信息必须通过 MCP 渠道结构化记录到看板**——看板不只是进度跟踪，它承载：需求登记（来源指针 + 摘要）、子任务拆解树、里程碑时间线、决策/风险、事件流与归属。
- 看板不控制执行，它记录"发生了什么"，供人介入与回溯分析。

对传统看板的升级点：列（状态机）只是骨架；卡片内部承载结构化深度，且每个字段都标注来源（agent 报告 / 人确认 / 系统观测）。

---

## 1. 核心对象：5 个

| 表 | 关键字段 | 状态由谁写 |
|---|---|---|
| requirements | id, source(`jira`/`manual`), source_ref, title, description(摘要), acceptance[]（人写预期验收锚）, state, awaiting_human{reason,evidence,since,kind}, created_at, updated_at | 状态机（见 2），DONE 仅人确认；acceptance 仅人面可写；source=`jira` 时 source_ref 存链接 |
| claims | id, requirement_id, agent_name(声明), agent_conn(观测), started_at, lease_expires_at, last_activity_at, ended_at, release_reason | 系统推导（租约） |
| subtasks | id, requirement_id, ordinal, title, acceptance[{item, criteria, state: met|not_met|deviated, deviation_reason?, links_to[]}], state, milestone_id?, created_at, updated_at | agent 报告，带 provenance |
| milestones | id, requirement_id, title, planned_at?, actual_at?, state, created_at, updated_at | agent 报告，带 provenance |
| events | id, requirement_id, claim_id?, subtask_id?, milestone_id?, kind, severity, title, content, payload, actor_surface, actor_conn, seq, ts | 系统 append |

需求 -> 子任务 1:N；需求 -> 里程碑 1:N；需求 -> 事件 1:N。子任务与里程碑不是生命周期单元，是**记录项**：看板只存它们被报告的状态，不驱动它们流转。

事件 kind：`decision` / `risk` / `deviation` / `decomposition` / `progress_note` / `state_change` / `review_request` / `approval` / `release` / `note`。
`deviation` 的 severity 强制 >= attention（不允许压级逃逸高亮）。

---

## 2. 状态机（需求级，最小集）

状态：OPEN -> CLAIMED -> DONE；侧向 BLOCKED / REJECTED / CANCELLED / REOPEN。

| from | to | 触发者 | 前置 |
|---|---|---|---|
| OPEN | CLAIMED | agent | 无未结束认领（DB 强制：ended_at IS NULL 谓词） |
| OPEN | CANCELLED | 人 | - |
| CLAIMED | DONE | 人 | 人确认（唯一终态来源，不是 agent 声明） |
| CLAIMED | BLOCKED | agent（声明） | 附原因；同时设 awaiting_human(kind=blocked) |
| BLOCKED | CLAIMED | 人 | 解除 |
| CLAIMED | OPEN | 人 | 释放认领（唯一释放路径，无自动释放） |
| DONE | REOPEN | 人 | - |
| REOPEN | OPEN | 人 | 重开回到可认领（避免死端） |
| REOPEN | CANCELLED | 人 | - |
| 任一 | REJECTED | 人 | 转移时清除 awaiting_human |

**不设"等待人审核"状态，设标记**：

```
awaiting_human: { reason, evidence, since, kind: review|blocked }
```

- 设置：`request_review`（kind=review，不改需求状态）或 `mark_blocked`（kind=blocked，同时转移 CLAIMED -> BLOCKED）；覆盖语义：新设置覆盖旧设置，旧设置对应事件保留（可回溯）。
- 清除：人的一次操作（approve 按 kind、release、reject、cancel、reopen），清除动作记 `approval` 事件；任何转移到终态或释放认领都会清除标记。
- 标记只改变信号，不阻塞：标记存在时租约过期不标 STALE，标"等待中"；无标记且无活动才标 STALE。这让"等你的任务"与"死掉的 agent"在窗口上可区分。
- agent 与人 inline 交互（会话内问答）不经看板，结果记一条 decision 事件。看板存结果，不存过程；只有交接才设标记。

**没有强制闸门。** 方案批准、中途纠偏都是 inline 交互，看板不充当裁判。唯一硬规则：DONE 只能人确认——这是审计语义，不是闸门。

---

## 3. 认领与异常（需求级租约）

- 独占认领：`UNIQUE (requirement_id) WHERE ended_at IS NULL`。第二认领返回 `already_claimed` + 持有者句柄。
- 租约推导状态（有序判定）：`ended_at 非空 -> 结束`；`租约过期且无 awaiting_human -> STALE`；`租约过期且有 awaiting_human -> 等待中`（不标 STALE）；`无活动超 idle 且无 awaiting_human -> SUSPECT`；否则 `ACTIVE`。
- 租约过期不自动释放、不自动重开，只改变信号；释放的唯一路径是人的操作。activity 口径 = 该 claim 的 agent 面任何写操作 + MCP 调用；参数默认 lease 2h / idle 30min。
- 不自动重试（最多 2 次，记录成本，超阈值进入"等你决策"清单）。
- 服务重启对账：未结束 claim 的 agent 连接不在了 -> 标 `stale`/`orphaned`，只标记不删除；并检测 claim-state 失配（有 claim 无 CLAIMED 或反之），报告 drift。
- 写保护：对 requirement 及其子项的任何写操作，要求存在未结束认领（agent 面）或交互面（人）。校验与写入同事务、以写锁开启（BEGIN IMMEDIATE），避免 TOCTOU；只查 `ended_at IS NULL`，租约只影响信号不影响写权限。释放不属于 agent 面操作，不受写保护前置约束（唯一释放路径为人面 CLI `release`）。

---

## 4. 完成语义（结构与声明诚实分开）

看板里有两类信息，视图必须视觉区分：

| 信息 | 来源 | 可否信 |
|---|---|---|
| 子任务/里程碑状态 | agent 报告（`reported by <agent> at <ts>` 标注） | 声明，可被 agent 更新 |
| 需求级 DONE | 人确认 | 唯一可信终态 |
| 认领、事件 seq、租约 | 系统观测 | 事实 |
| 决策/风险内容 | agent 或人写入 | 记录（不可编辑，可追加更正） |

progress 推导而非上报：需求级进度 = 子任务 state 的派生值（done/total），agent 的 `update_progress` 只作为进度备注事件，不覆盖派生值。

`request_review` 附证据（PR 链接 / commit 区间 / 测试摘要，至少一项）；缺证据的请求被拒绝。证据字段是回溯判据 5 的来源。

`approve` 按**当前状态**判定：CLAIMED 上确认 DONE（claim 置 ended_at），BLOCKED 上解除阻塞回 CLAIMED；marker kind 只决定清除内容与事件。BLOCKED + kind=review 组合不可达（request_review 前置 state=CLAIMED）。

agent 与人 inline 交互的结果（批准方案、纠偏、解答问题）由 agent 或人在会话内记一条 `decision` 事件；这类交互不设 awaiting_human 标记，流程零中断。只有当交接发生在会话之外（session 结束、人不在场、决策太大），才设标记进入"等你决策"清单。

---

## 5. 归属与回溯

三类归属（观测 / 外部引用 / 自报声明），只有观测是审计事实（沿用 v2，不重复）。

回溯判据（需求级）：
1. 为什么 DONE -> state_change 链 + 人确认的 approval 事件
2. 这个决策当时在什么状态下做出 -> decision 事件 + 需求当时状态 + conn + ts
3. 谁在什么时候做了什么 -> claims 时间轴 + 事件归属
4. 分解与里程碑的演化 -> subtasks/milestones 的每次状态变更都有事件，可重建时间线
5. 产出物在哪 -> review 证据字段（PR / commit 区间）

导出：JSON / Markdown（含事件流全文），供外部分析。

---

## 6. MCP 工具面（记录渠道，约 12 个）

| 工具 | 语义 | 归类 |
|---|---|---|
| list_tasks | status 过滤，获取未完成任务 | 读 |
| get_task_detail | 需求 + 子任务树 + 里程碑 + 事件流 + 认领 | 读 |
| claim_task | 独占认领，返回租约 | 认领 |
| add_subtask | 拆解：title + acceptance + ordinal | 记录（结构） |
| update_subtask | state: todo/in_progress/done/blocked/abandoned | 记录（结构） |
| add_milestone | title + planned_at | 记录（结构） |
| update_milestone | state: planned/in_progress/achieved + actual_at | 记录（结构） |
| add_record | kind = decision / risk / deviation / decomposition / note；decision 必含 alternatives + 拒绝理由；deviation severity 强制 >= attention | 记录（事件） |
| update_progress | progress 备注（不覆盖派生值） | 记录 |
| request_review | 完工交接：设置 awaiting_human(kind=review)，持久化验收自评，附证据（至少一项，缺证据拒绝）；不改状态。前置 state=CLAIMED | 交接 |
| mark_blocked | 声明阻塞：转移 CLAIMED -> BLOCKED + 设置 awaiting_human(kind=blocked)，附原因 | 交接（含状态转移） |
| list_awaiting | 全部"等你决策"条目，含等待时长 | 读（人面） |

错误码：`not_found | illegal_state | already_claimed | no_active_claim | lease_expired | duplicate_subtask | invalid_record | queue_full | db_busy | ambiguous_id`。MCP `is_error` + structured content，无 HTTP 码。

工具面的写操作统一前置校验：`no_active_claim`（agent 面）或交互面（人）。这使每个记录可追溯到一个认领或一次人工操作。

---

## 7. Jira：链接引用登记，不做导入/回写（ADR 0004）

Jira 需求以 `new --source jira --source-ref <链接>` 登记：`source_ref` 存链接，`description` 贴摘要；完整详情留在 Jira（单一事件源），由 agent 自行获取。不做自动导入与回写（AI 已能做好的事不重复造）。

---

## 8. 砍掉什么

| 项 | 理由 |
|---|---|
| worktree 编排、merge executor、进程管理 | 执行不在看板职责内 |
| repo 注册表、Workspace 抽象 | 无此需要 |
| 子任务作为状态机单元 | 子任务是记录项，不是生命周期单元 |
| 9 个状态 | 6-7 个够用 |
| Web UI（M0） | 终端表格 + 按需 HTML；M1 再做窗口 |
| PostgreSQL | SQLite 足够 |
| agent 自报的百分数进度 | 用派生值替代 |

---

## 9. 需要你裁决的点

1. ~~分析闸门~~ 已解决：不设强制闸门，方案批准走 inline 交互，结果记 decision 事件。`request_review` 证据要求已定：至少一项，缺证据拒绝（PRD 11）。
2. **心跳模型**：harness 是看板拉起的还是外部进程？推荐 M0 按外部进程（心跳 = MCP 活动频率），M1 支持看板拉起。
3. **Jira 回写**：不做（PRD §11 默认 + ADR 0004）。

---

## 10. 分期

| 阶段 | 交付 | 判据 |
|---|---|---|
| Spike（2 天） | CLI + SQLite + MCP stdio：requirements + claims + subtasks + milestones + events + 工具面 | AC1-9、AC16（一次真实流程：导入 -> 认领 -> 拆 3 子任务 -> 记 2 决策 + 1 里程碑 -> request_review(证据) -> 人确认 DONE；第二 agent 认领被拒；租约过期不自动释放） |
| M0 | 交接/标记语义、证据校验、导出、终端看板（列 + 卡片展开）、派生偏离 | AC10-13、AC15、AC17（5 条回溯判据可回答 + 判别力测试） |
| M1 | Web 窗口 | AC14（一周试用协议，G3 基线采集为硬前置） |

---

## 11. 为什么这版是对的

职责分离不变：agent 工具链负责能力，看板负责状态与记忆。这版的增量是：**记忆要有结构**。纯事件流能记录一切但查询与分析要靠解析；结构化的子任务树与里程碑时间线直接支撑"回溯分析"——哪个子任务卡住、里程碑延误多久、决策分布如何。

同时守住诚实：结构是 agent 报告的，带 provenance，视图区分"报告"与"确认"；只有 DONE 是人确认的。看板变厚了，但没有假装控制执行。

保留的跨版本原则：状态由事实/确认推导，归属三类只有观测是事实，任何占用有租约与到期信号，自我报告不是终态。
