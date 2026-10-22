# Agentic Kanban - 产品需求文档 (PRD v3.2)

状态: 草案。v3.1 经双轴复审（需求轴 APPROVE-WITH-FIXES / 契约轴 REJECT 续审），本版折入全部 P1/P2（release 人面独占、approve 按状态判定、写锁先行、AC 错位、覆盖下界语义）
里程碑: M0 完成（2026-10-22，AC10-13/15/17 + Spike AC1-9/16 + 9 码矩阵 + 补充全绿，验证见 docs/ops/m0-verification.md）；M1 未开工
定位: AI 时代的看板——不是任务状态跟踪，而是**大黑箱（AI 自动化执行）的关键节点暴露窗口 + 可回溯审计资产**
读者: 实现者、后续维护者、评审者
关联: docs/design.md（设计理由）、docs/adr/（决策与残余登记）

---

## 0. 定位与目标

AI 执行是黑箱：模型推理不可见、过程不可重放、输出质量不可信其自报。看板的价值不是展示进度条，而是**从黑箱中提炼出人需要知道的少数关键信息**，让人能做三件事：

1. **判断是否符合预期**：需求进入看板时由人写下预期验收标准（expectation anchor）；任务交回时，看板展示"验收对照表"——每项预期 vs 子任务验收项的覆盖与达成状态。人不需要读原始输出流，就能判断完成状态是否偏离自己的预期。
2. **判断是否有偏离**：偏离分两类，都必须在摘要视图可见——agent 显式登记的偏离（偏离了什么、原因、替代方案），以及系统从可观测状态推导出的偏离信号（子任务被放弃/阻塞、拆解范围变化、里程碑延误）。
3. **判断是否有更好的方案**：决策记录必须包含"考虑过什么、选择了什么、为什么拒绝其他"。事后人可以质疑决策，而不是只能接受黑箱结论。

**反淹没约束（最高设计约束）**：人的默认视图只展示关键节点（里程碑、决策、风险、偏离、等待人裁决、覆盖缺口），原始日志、会话内容、过程细节一律不默认展示。

**单一事件源（指引优先）**：完整内容留在其源头（Jira 详情、代码、会话原文），看板只存指针（链接/引用）+ 摘要。登记是 URL+摘要 还是完整详情并不重要，**做好指引更重要**；需要完整内容时由 agent 从源头获取。与反淹没互补：反淹没 = 不默认展示，本原则 = 不留存、只指引。

**报告纪律（agent 侧）**：写给人看的每一段文字（验收自评、decision rationale、deviation 原因、交接说明）必须**简约、大白话、无黑话**，尊重人脑带宽；报告里程碑与关键事件（节点），不报过程流水账。与反淹没互补：反淹没管视图展示什么，本纪律管 agent 写进记录的是什么。

职责边界：看板是记录面 + 协作窗口，不是控制面。它不管理 worktree、不执行合入、不隔离执行。

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
- C7 记录可回溯：5 条回溯判据（见 5.4）在保留窗口内全部可回答。

---

## 2. 对象与数据模型

| 表 | 关键字段 | 状态由谁写 |
|---|---|---|
| requirements | id, source(`jira`/`manual`), source_ref, title, description(摘要), acceptance[]（人写预期验收锚）, state, awaiting_human{reason,evidence,since,kind}, created_at, updated_at | 状态机；acceptance 仅人面可写；DONE 仅人确认；source=`jira` 时 source_ref 存链接（引用登记，无自动导入）；description 存摘要，完整内容留源头（单一事件源） |
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

事件 kind：`decision` / `risk` / `deviation` / `decomposition` / `progress_note` / `state_change` / `review_request` / `approval` / `release` / `note` / `reconcile`（对账事件，系统对账写事件，PRD §6 可观测）。
事件 severity：`info` / `attention` / `critical`。**deviation 的 severity 强制 >= attention**（不允许压级逃逸，见 5.3）。

`awaiting_human` 是 requirements 上的 JSON 列，不是状态：
- 设置：`request_review`（kind=review，不改需求状态）或 `mark_blocked`（kind=blocked，同时转移 CLAIMED -> BLOCKED）。
- 覆盖语义：新设置覆盖旧设置，旧设置对应事件保留（可回溯）。
- 清除（人的操作，与 approval/release/state_change 事件同事务）：approve（按 kind 清除对应标记）、release、reject、cancel、reopen。任何转移到终态或释放认领都会清除标记。

---

## 3. 状态机与认领

### 3.1 状态与边

OPEN -> CLAIMED -> DONE；侧向 BLOCKED / REJECTED / CANCELLED / REOPEN。

| from | to | 触发者 | 前置 |
|---|---|---|---|
| OPEN | CLAIMED | agent | 无未结束认领（DB 强制：ended_at IS NULL 谓词） |
| OPEN | CANCELLED | 人 | - |
| CLAIMED | DONE | 人 | 人确认（唯一终态来源） |
| CLAIMED | BLOCKED | agent | 附原因；同时设 awaiting_human(kind=blocked) |
| BLOCKED | CLAIMED | 人 | 解除阻塞，清除标记 |
| CLAIMED | OPEN | 人 | 释放认领（唯一释放路径，无自动释放） |
| DONE | REOPEN | 人 | - |
| REOPEN | OPEN | 人 | 重开回到可认领（避免死端） |
| REOPEN | CANCELLED | 人 | - |
| 任一 | REJECTED | 人 | 转移时清除 awaiting_human |

### 3.2 认领与租约

- 认领 = `INSERT claims` + 条件 `UPDATE requirements SET state=CLAIMED WHERE state=OPEN`，**单事务**，rowcount 校验；任一失败整体回滚。
- 释放（人面 CLI `release`，唯一释放路径）= 单事务（置 ended_at + 条件更新需求 CLAIMED -> OPEN + 写 release 事件），`release_reason` 必填。
- 租约推导（不存状态字段）：
  - `ended_at 非空 -> 结束`
  - `now > lease_expires_at 且无 awaiting_human -> STALE`
  - `now > lease_expires_at 且有 awaiting_human -> 等待中`（不标 STALE）
  - `now - last_activity_at > idle 且无 awaiting_human -> SUSPECT`
  - 否则 `ACTIVE`
- **租约过期不自动释放、不自动重开**。过期只改变信号。释放的唯一路径是人的操作。
- activity 口径：该 claim 的 agent 面任何写操作 + MCP 调用；`last_activity_at` 在写事务内更新。
- 参数：lease 时长默认 2h，idle 阈值默认 30min，均可配置；默认值入 11 未决表 M0 内裁决。
- 不自动重试：重试对象是子任务（agent 侧），每次重试记录成本（token/时长），同一需求累计重试超 2 次进入"等你决策"清单（实现：系统判定超限后写一条 risk(severity=attention) 事件，入摘要"需要关注"区）。
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

  BLOCKED + kind=review 组合不可达：request_review 前置要求 state=CLAIMED（4.1）。
- DONE 后追加更正：写保护要求未结束认领，因此更正需人面操作（CLI `note`）或 REOPEN 后由 agent 继续——两条路径都明确，不冲突。

---

## 4. 记录渠道（MCP 工具面 + 人面）

### 4.1 MCP 工具面

transport：**stdio**（本地 agent 默认，opencode/Claude Code 直连）+ **streamable-http**（挂载 FastAPI /mcp，ADR 0005；与 stdio 共用同一工具注册表；localhost 默认 + token 一致）。agent 面无 release 工具，写保护语义两 transport 相同。

| 工具 | 语义 | 前置 |
|---|---|---|
| list_tasks | status 过滤，获取未完成任务 | 读 |
| get_task_detail | 需求 + 子任务树（含验收自评与覆盖对照）+ 里程碑 + 关键事件 + 认领 + awaiting_human | 读 |
| claim_task | 独占认领（单事务） | 无未结束认领 |
| add_subtask | 拆解：title + acceptance[]（含 links_to 预期锚）+ ordinal | 未结束认领 |
| update_subtask | state: todo/in_progress/done/blocked/abandoned | 未结束认领 |
| add_milestone | title + planned_at | 未结束认领 |
| update_milestone | state: planned/in_progress/achieved + actual_at | 未结束认领 |
| add_record | kind = decision / risk / deviation / decomposition / note；decision 必含 alternatives[] + rationale + 拒绝理由；deviation severity 强制 >= attention | 未结束认领 |
| update_progress | 进度备注（不覆盖派生值） | 未结束认领 |
| request_review | 设 awaiting_human(kind=review)，持久化验收自评到 subtasks.acceptance[].state，附证据（PR / commit 区间 / 测试摘要，至少一项，缺证据拒绝）；不改状态 | 未结束认领 且 state=CLAIMED（否则 illegal_state） |
| mark_blocked | 转移 CLAIMED -> BLOCKED + 设 awaiting_human(kind=blocked)，附原因 | 未结束认领 且 state=CLAIMED（否则 illegal_state） |
| list_awaiting | 全部"等你决策"条目，含等待时长 | 读（人面） |

释放不属于 agent 面：MCP 工具面无 release 工具，唯一释放路径为人面 CLI `release`（见 4.2）。

### 4.2 人面（CLI/REST，非 MCP）

- `new`：创建需求（手工导入），可写入 acceptance 预期锚。
- `new --source jira --source-ref <链接>`：以链接引用登记 Jira 需求（description 贴摘要，完整详情留在 Jira——单一事件源，由 agent 自行获取）；不做自动导入（AI 已能做好的事不重复造，ADR 0004）。
- `set_expectations`：设置/修改 requirement.acceptance（唯一入口，agent 面无此工具）。锚项可修改文本；删除被 links_to 引用的锚项被拒绝（需 agent 先解除链接）。
- `approve`：按**当前状态**确认（决策表见 3.4）——CLAIMED 上确认 DONE、BLOCKED 上解除阻塞；按 awaiting_human.kind 清除标记，写 approval/state_change 事件（同事务）。
- `release`：释放认领（唯一释放路径，人面）；要求存在未结束认领，无则 `not_found`；写 release 事件 + 清除 awaiting_human。`release --all-stale`：批量释放全部 STALE 认领（仅覆盖 CLAIMED 需求；逐项执行单释放语义，部分失败逐项返回，非全有全无）。
- `renew`：续租（对已过期租约返回 `lease_expired`）。
- `note`：人追加更正/质疑（写入 note 事件）。
- `export`：JSON / Markdown 全量导出。
- `abandon`：REJECTED / CANCELLED。

### 4.3 错误码

MCP `is_error` + structured content（`{code, message, task_id}`），无 HTTP 码：
`not_found | illegal_state | already_claimed | no_active_claim | lease_expired | duplicate_subtask | invalid_record | queue_full | db_busy`

每个码有唯一触发条件：`lease_expired` = 对已过期租约 renew；`db_busy` = SQLite 写失败重试 3 次后（7.3）；`queue_full` = claim_task 计数超上限（6）；`invalid_record` = decision 缺 alternatives 或 request_review 缺证据；其余见工具表。

---

## 5. 归属、视图与回溯

### 5.1 三类归属

| 类别 | 例子 | 可伪造性 | 用途 |
|---|---|---|---|
| 系统观测 | MCP 握手签发的 conn id、服务签发的 seq/ts、租约 | 低 | 审计链锚 |
| 外部引用 | OpenCode session id（`ses_...`）、Jira key、分支名 | 中 | 重放与定位 |
| 自报声明 | "我是 deepseek harness"、"测试通过" | 高 | 存 payload，标注声明，不作为事实 |

`actor_surface`（`mcp`/`cli`/`system`）与 `actor_conn` 由服务端派生，不接受调用方传入。决策/风险/偏离不可编辑，只能追加更正（人面 `note` 或 REOPEN 后 agent 追加）。

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

深潜视图（按需展开）：完整事件流（按 kind/severity 过滤），支持重建事件发生时需求的状态（由 state_change 链 + 该时点事件推导）。

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
| 数据保留 | events 保留 12 个月；清理由显式命令执行，清理前必须导出；导出文件为审计资产最终载体 | 无限保留 -> 隐私与备份风险；回溯承诺（C7）限于保留窗口 |
| 可观测 | 每次转移/交接/对账写事件；`/healthz`；埋点：等你决策清单等待时长（ts(清除) - ts(设置)）、STALE 率、偏离登记率、覆盖缺口数 | 反黑箱目标无法度量 |
| 可靠性 | 重启后未结束认领与真实连接对账 + claim-state 失配检测；不一致标 drift，不自动删除 | 静默丢失占用状态 |
| 退役 | 6 个月内 events < 100 则归档并说明替代方案 | 僵尸项目 |

威胁模型：
- A: 本机任意进程通过接口写记录污染审计链 -> 默认 localhost + token（非 localhost）+ 写保护（3.3）。残余：直接写 SQLite 文件不可防（G1）。
- B: agent 内容不可信（偏离不登记、自评造假）-> 结构强制（decision 必含 alternatives、验收自评表、deviation 强制 attention）+ 派生偏离信号（不依赖自愿登记）+ 人抽查（G2）。
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
