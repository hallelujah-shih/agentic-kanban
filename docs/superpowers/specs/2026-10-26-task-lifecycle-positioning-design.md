# Spec: Task 生命周期操作（create/archive/delete）与看板定位重述

**日期**: 2026-10-26
**状态**: 设计定稿（待对抗审查 + user 审阅）
**分支/worktree**: task-lifecycle（基于 main 8767385）
**BCD**: `docs/business-contracts/task-lifecycle-positioning.md`（7 节齐；user 裁决 2026-10-26：Q1=A UI 瘦身 + 决策操作 CLI-only；Q2=方案 1 archive 新终态 + delete 硬删 + 三层齐）
**关联**: PRD §0/§3.1/§3.4/§4.2/§5.4/§6；docs/web.md；`state_machine.py`（ALLOWED_EDGES）；`operations.py`（abandon/prune 模式）；`view.py`（TERMINAL_STATES/board）

---

## 1. 背景与定位（修订）

PRD §0 定位语在既有基础上修订为：

> 看板 = **AI 与人对称交换关键信息的场所 + 关键决策的记录点/审计点**。看板不承担共识达成逻辑：子任务/里程碑的共识在 AI 会话内（in-band）达成，看板只展现结果；决策记录两类来源——人在 AI 中做出的决策（agent 以既有 decision/note 事件记录，带 actor provenance）与 AI 自主的决策（decision 事件）。

Web 窗口 surface 划分（PRD §4.2 修订）：

- **Web = 只读视图 + task 生命周期操作（create / archive / delete）**
- 人面决策操作（approve / release / renew / reopen / note / abandon / set_expectations）**保留但降为 CLI-only**：语义、状态机、错误码零改动；C6（终态可信）与威胁模型 B 原样
- "记录人在 AI 中做的决策"不是新机制：agent 侧既有 `add_record`（kind=decision/note，actor provenance）承载，本轮把它从"可选行为"确立为**预期模式**，写进 PRD §0 报告纪律

## 2. 范围与非目标

**范围内**：
- 状态机新增 ARCHIVED 终态 + 人面边
- `operations.archive_requirement` / `operations.delete_requirement`
- 视图：TERMINAL_STATES 扩展、board 过滤、"已归档"tab、awaiting 横幅 CLI 提示
- Web 壳：决策按钮移除、生命周期操作区、新建表单
- REST：`POST /requirements/{id}/archive`、`DELETE /requirements/{id}`
- CLI：`kanban archive`、`kanban delete`
- 数据保留：ARCHIVED 入 prune 终态集合
- 文档同步（§9）+ harness（§10）

**非目标（显式）**：
- 不做 unarchive（BCD §1 待澄清项 2；日后加一条人面边即可，零迁移）
- 不开放 sub task 人面编辑（user 明确：当前不开放；现状即 agent 面写入）
- 创建不写事件、不加新事件 kind（BCD P-C：回溯判据 5 条不要求"谁创建"；行上 created_at/source/source_ref 导出可见；事件 kind 契约保持稳定）
- MCP 工具面零改动（12 工具不变；agent 无 delete/archive 工具 = I4 结构保证）
- 不重命名"已完成"tab（含 DONE/REJECTED/CANCELLED 是既有口径，终态徽章已显示精确状态）
- 不引入 delete undo/回收站（BCD F4 残余接受）
- 不做"归档比例 vs 取消比例"的自动化告警（BCD F1 预防 = 措辞 + 人工观察，单用户规模下自动化是过度设计）

## 3. 状态机变更

`state_machine.py` `ALLOWED_EDGES` 增加一条：

```python
(None, "ARCHIVED"): HUMAN,   # 任一状态 -> ARCHIVED，人面（模式同 (None, "REJECTED")）
```

- `transition()` 零改动即适用：`to_state != BLOCKED` 通规清除 `awaiting_human`；写 state_change 事件（`from_state=None` 传参，事件 title `"? -> ARCHIVED"`，payload `{"from": None, "to": "ARCHIVED"}`——与 REJECTED 既有事件形态一致）
- 派生行为（零改动）：
  - approve on ARCHIVED -> `illegal_state`（§3.4 判定表无 ARCHIVED 边，`edge not in ALLOWED_EDGES` 自然拦截）
  - reopen from ARCHIVED -> `illegal_state`（无 ARCHIVED 出边 = 无 unarchive，I6）
  - release/renew on ARCHIVED -> `not_found`（无活跃认领，既有语义）
  - claim on ARCHIVED -> `transition(OPEN->CLAIMED)` 条件更新不命中 -> `illegal_state`，同事务回滚已 INSERT 的 claim 行（净效果：无副作用，不可认领，I6；已核实 operations.py:400-428 路径）
- PRD §3.1 状态表新增行：`任一 | ARCHIVED | 人 | -（终态，无出边）`
- PRD §3.4 approve 判定表新增行：`ARCHIVED | 任意 | 拒绝 | 无 | 无 | illegal_state`

## 4. 操作语义与实现锚点

### 4.1 create（端点/命令既有，Web 表单新增）

- `ops.new_requirement` / `POST /requirements` / `kanban new` **零改动**
- Web 新建表单（board 壳顶栏"新建"按钮触发表单区）：
  | 字段 | 必填 | 映射 |
  |---|---|---|
  | title | 是 | `title` |
  | description | 否 | `description` |
  | acceptance（textarea，一行一条锚） | 否 | 每行 -> `{"item": line}`（`normalize_anchors` 自动编号 a1/a2/...；空行忽略） |
  | Jira 链接 | 否 | 非空时 `source="jira"` + `source_ref=<url>`；空则 `source="manual"` |
- 提交 -> `POST /requirements` -> 成功后关闭表单；SSE 推送使看板自动刷新（OPEN 列 +1）
- 失败展示：内联 `body {code,message}`（复用深潜页 `handleOpResult` 同款模式）

### 4.2 archive（新）

`ops.archive_requirement(session, *, requirement_id, actor_surface, actor_conn, now)`：

1. `require_requirement`（不存在 -> `not_found`）
2. 读未结束认领（`Claim.ended_at IS NULL`）
3. `transition(from_state=None, to_state="ARCHIVED")`（state_change 事件 + marker 清除，同事务）
4. 有认领则 `UPDATE claims SET ended_at=now, release_reason="archive"`（**abandon 模式逐字复用**，operations.py:371-375）
5. 返回 `{"requirement_id", "state": "ARCHIVED"}`

- 人面操作无写保护前置（与 abandon/approve 一致：人面不要求活跃认领）
- 经 `run_op(is_write=True)` 单事务（BEGIN IMMEDIATE，既有写路径）
- ARCHIVED 上再 archive：允许（`(None, ARCHIVED)` 边不拒绝自身，**与 REJECTED -> REJECTED 既有口径一致**）；UI 在 state==ARCHIVED 时禁用 archive 按钮，CLI/REST 不特判
- claim `release_reason="archive"` 进入回溯判据 3 的 claims 时间轴（"谁在什么时候做了什么"可答）

### 4.3 delete（新）

`ops.delete_requirement(session, *, requirement_id, actor_surface, actor_conn)`：

1. `require_requirement`（不存在 -> `not_found`）
2. 单事务（`run_op(is_write=True)`）按 FK 顺序删除：
   `delete(Event) where requirement_id` -> `delete(Subtask)` / `delete(Milestone)` / `delete(Claim) where requirement_id` -> `delete(Requirement) where id`
3. **不写事件**（事件链随属主消失——I2 的推广：整链随属主一起走，链永不半断）
4. 返回 `{"requirement_id", "deleted": true}`

- 无业务前置（任意状态可删，含活跃认领；认领行被直接删除而非"结束"——与 archive 的"结束认领"是两种机制，BCD P3）
- 不受数据保留窗口约束（BCD P4：显式意图覆盖保留策略）
- 并发：SQLite 写串行化。agent 写事务与 delete 竞争时，要么 agent 先提交随后被整删，要么 agent 拿锁超时走既有 db_busy 重试、随后 `not_found`/`no_active_claim`（BCD S6）
- 删除后 agent 面感知（BCD S8）：所有 MCP 读/写拿既有 `not_found`；`list_tasks` 不再返回该任务——agent 可判定"任务不存在/已被人删除"，非系统故障（README/docs 写明此语义，BCD F2）

### 4.4 三层 surface

| 操作 | REST | CLI | Web |
|---|---|---|---|
| create | `POST /requirements`（既有） | `kanban new`（既有） | 新建表单（新增） |
| archive | `POST /requirements/{id}/archive`（新增） | `kanban archive <id>`（新增） | 深潜页按钮（新增） |
| delete | `DELETE /requirements/{id}`（新增） | `kanban delete <id>`（新增，确认提示） | 深潜页按钮 + 标题确认（新增） |

- REST actor：`rest_actor` 服务端派生（既有模式）；错误映射既有（not_found=404）
- CLI delete 确认：展示 title/state/事件数 + "建议先 `kanban export` 留档" + y/N（EOF/非 y 中止，模式同 prune 确认门）
- Web delete 确认：确认框显示 title + 事件数 + 当前状态 + "删除不可逆，建议先导出"，**要求输入 task 标题**，不匹配拒绝（BCD 隐含 Policy B、F4）

## 5. 视图变更

- `view.py` `TERMINAL_STATES = ("DONE", "REJECTED", "CANCELLED", "ARCHIVED")`（line 191）
- `board()` 默认过滤（line 227）由硬编码列表改为 `Requirement.state.not_in(TERMINAL_STATES)`——常量派生，消灭与 line 191 的漂移隐患（本轮本来就要动这行）
- `finished_at`（`_terminal_entry_ts`）零改动：判别口径 = 需求级 state_change 且 `to in TERMINAL_STATES`，ARCHIVED 自然覆盖（归档 tab 的完成时间 = archive 事件 ts）
- 深潜页/导出/事件流/验收对照/子任务/里程碑/决策风险偏离：**零改动**
- `list_awaiting`：ARCHIVED 任务 marker 已被 archive 清除（transition 通规），自然不出现（BCD S5）

## 6. Web UI 变更

### 6.1 board 壳

- 顶栏加"新建"按钮 -> 顶栏正下方内联展开新建表单（§4.1 字段，不用 modal），提交成功后收起
- tabs：`在板 / 已完成 / 已归档`（第三 tab `data-tab="archived"`，fetch `/board?status=ARCHIVED` 单请求）
- 已归档 tab 行渲染复用 done-row 结构：终态徽章（`ARCHIVED` -> "已归档"）+ finished_at + 决策/偏离计数 + reviewed 标记

### 6.2 detail 壳（瘦身）

- **移除**：approve / release(reason) / renew / reopen / reopen --continue / abandon 按钮、abandon-state 选择器、note 输入区、set_expectations 输入区（对应 JS：`doOp`/`doRelease`/`doReopen`/`doAbandon`/`doNote`/`doExpectations` 中决策类函数）
- **保留**：awaiting 横幅（+ 新增静态 CLI 提示：kind=review -> "人面确认: kanban approve <id>"；kind=blocked -> "解除阻塞: kanban approve <id>"——静态文字，非交互，BCD 隐含 Policy A、F3）、全部只读区、事件流（kind 过滤选项保留 renew——CLI 仍写 renew 事件）
- **新增"task 生命周期"操作区**：archive 按钮（state==ARCHIVED 时禁用）+ delete 按钮（标题确认流程，§4.4）；两按钮视觉分离（BCD F4）
- 壳契约保持：board-root/detail-root/EventSource/零数据嵌入不变；token 传播不变

## 7. REST/CLI surface

- `POST /requirements/{id}/archive` -> 200 `{"requirement_id", "state": "ARCHIVED"}`；404 not_found
- `DELETE /requirements/{id}` -> 200 `{"requirement_id", "deleted": true}`；404 not_found
- CLI 新命令 `archive` / `delete`（argparse 子命令，JSON 输出，`_invoke` 既有模式）
- 既有 CLI 命令（new/approve/release/renew/reopen/note/abandon/set_expectations/export/prune/reconcile/view）零改动
- MCP server 零改动（12 工具；I4）

## 8. 数据保留

- `operations.py` `PRUNE_TERMINAL_STATES = ("DONE", "REJECTED", "CANCELLED", "ARCHIVED")`（line 953）
- prune CLI 确认文案更新："终态（DONE/REJECTED/CANCELLED/ARCHIVED）"
- delete 与 prune 的关系（PRD §6 措辞）：prune = 窗口化批量（仅终态、强制导出）；delete = 定点即时（任意状态、不强制导出、确认提示含导出建议）。两者都以"整个需求"为单位（I2）
- ARCHIVED 任务在 prune 窗口内整删（BCD S7/E4）

## 9. 文档同步清单

| 文档 | 变更 |
|---|---|
| PRD §0 | 定位语修订（§1 引文）；报告纪律补"in-band 人的决策由 agent 以 decision/note 事件记录 = 预期模式" |
| PRD §3.1 | 状态表 + ARCHIVED 行（§3） |
| PRD §3.4 | approve 判定表 + ARCHIVED 行（illegal_state） |
| PRD §4.2 | Web 窗口 surface 表重写（只读 + 生命周期；决策操作 CLI-only 明示） |
| PRD §6 | 数据保留行：ARCHIVED 入终态集合；delete 语义（显式即时、不受窗口、不强制导出） |
| docs/web.md | surface 表 + 人面操作节重写（生命周期操作 + CLI 速查节） |
| README | 若文档地图/功能描述提及人面操作，同步（实施时核对） |

## 10. 契约涟漪与 harness

**壳契约断言更新**（既有 harness 的 web 壳部分）：
- 深潜页：7 个决策按钮 + set_expectations 的断言移除；新增 archive/delete 操作区断言
- board 壳：tabs 数量 2 -> 3（在板/已完成/已归档）；新增"新建"入口断言
- 保持：board-root/detail-root/EventSource/零数据嵌入断言不变

**新增 harness 用例**：
1. archive 全状态矩阵：OPEN/CLAIMED/BLOCKED(带 marker)/DONE/REJECTED/CANCELLED -> ARCHIVED 均成功；事件链尾 state_change；CLAIMED 的 claim 同事务 ended_at（release_reason="archive"）；BLOCKED 的 marker 清除
2. archive 视图：board 默认响应不含 ARCHIVED；`/board?status=ARCHIVED` 含之；finished_at = archive 事件 ts
3. delete 原子性：requirement/subtasks/milestones/claims/events 五表零残留；随后 REST 404、MCP get_task_detail not_found、list_tasks 不含
4. delete 并发：与 agent 写事务竞争，无 FK 悬空（串行验证：delete 后全表扫描无 requirement_id 残留）
5. prune 覆盖 ARCHIVED：出窗整删 / 未出窗保留 / 非终态保留（三任务场景，同 BCD E4）
6. C6 回归：CLI approve 仍是 DONE 唯一来源；MCP 全工具面无法产生 DONE/archive/delete
7. Web 表单：create 带/不带 acceptance、带 jira 链接（source=jira 映射）
8. awaiting 横幅 CLI 提示渲染（kind=review / kind=blocked 两形态）

**既有断言**：除壳契约同步项外零回归（实施后全量跑通）。

## 11. 错误码

**无新增错误码**。触发面映射（全为既有码）：

| 场景 | 码 |
|---|---|
| archive/delete 不存在的 id | not_found（REST 404） |
| agent 写已归档任务（无活跃认领） | no_active_claim |
| agent 认领已归档任务 | illegal_state（claim 行随事务回滚） |
| agent/人访问已删除任务 | not_found |
| approve/reopen on ARCHIVED | illegal_state |
| 并发锁竞争 | db_busy（既有重试） |

## 12. 验收标准（可测）

- AC1：Web 新建表单提交（title + 两行 acceptance）-> 201；board OPEN 列 +1；深潜页锚 a1/a2
- AC2：archive 六个状态（OPEN/CLAIMED/BLOCKED/DONE/REJECTED/CANCELLED）均成功；CLAIMED 的 claim ended_at 同事务置位（release_reason="archive"）；BLOCKED 的 awaiting_human 清除
- AC3：ARCHIVED 任务不在 board 默认响应；`/board?status=ARCHIVED` 包含；finished_at = archive 事件 ts
- AC4：delete 后五表（requirements/subtasks/milestones/claims/events）零残留；REST GET 404；MCP not_found
- AC5：delete 后 agent 写操作拿 not_found 或 no_active_claim；list_tasks 不含该任务
- AC6：prune --months 12：ARCHIVED 出窗整删、ARCHIVED 未出窗保留、非终态保留
- AC7：MCP 工具面 12 工具不变；agent 无法经任何 MCP 工具触发 archive/delete/DONE
- AC8：detail 壳无决策按钮（壳契约断言）；CLI approve 路径回归绿（C6）
- AC9：CLI `kanban archive` / `kanban delete` 可用（JSON 输出 / 确认门语义同 prune）

## 13. 风险与残余

| # | 风险 | 处置 |
|---|---|---|
| R1 | agent harness 对 delete 后 not_found 的处理在本仓之外（BCD F2） | 错误码语义 + 文档写明；harness 断言 agent 面 not_found。残余登记 |
| R2 | delete 误删不可恢复（BCD F4） | 标题输入确认 + 展示事件数/状态 + 导出建议；残余接受（单用户） |
| R3 | archive/abandon 语义区分靠使用纪律，非结构强制（BCD F1） | agent 面无 archive 工具（结构性半边）；人面靠 UI 语义 + PRD 措辞；人工观察比例。残余登记 |
| R4 | 决策操作移 CLI 后 awaiting 堆积（BCD F3） | awaiting 横幅静态 CLI 提示 + 命令速查文档。残余：习惯迁移 |
