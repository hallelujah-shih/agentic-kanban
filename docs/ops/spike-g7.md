# Spike G7 — agent-kanban-pm 移植性验证报告（A 面观测，T1.1-T1.4）

- 日期: 2026-10-22（A 面观测研究，自审通道）
- 分支: `spike`（worktree: `.worktree/spike/`，基分支 main @ e29106b）
- 规范锚: docs/PRD.md v3.2（只读，未改）；判据: docs/adr/0001-reuse-vs-build.md 四断言 + docs/plans/spike-plan.md Part 1 偏差触发清单
- 对象: kronos3610/agent-kanban-pm（MIT，记录面），**pin `e29d288e4f454254c4f276a4cc25b64581b1ddf5`**（feat: purge rows orphaned before foreign keys were enforced）
- 复跑路径: `.worktree/spike/_vendor/agent-kanban-pm/`（venv: `.venv`，python 3.12.13，mcp 2.3.0）；T1.3 驱动脚本与日志在 `/tmp/opencode/g7/`（driver.py / driver.stdout.log / kanban.db）

## DEVIATION 登记

偏差触发清单（spike-plan L34）命中 **①③④ 共 3 项**，② 未命中。命中即 T2 按回退分支执行（spike-plan L35）：**不照搬 vendor 语义，按 PRD 从零实现，只借本报告已证实的实现模式**。按任务规则（命中 DEVIATION 禁止改写 ADR 0001），本报告仅登记，ADR 0001 保持原文；移植边界修正见 T1.4 节。

| 触发（spike-plan L34 原文） | 判定 | 一句话证据 |
|---|---|---|
| ① 认领排他靠应用层而非 DB 约束 | 命中 | DB partial unique 索引粒度是 `(task_id, agent_id)`，非 per-task（models.py L393-400）；per-task 排他靠无锁 check-then-insert（coordination.py L70-80） |
| ② 租约无心跳/activity 口径 | 未命中 | AgentHeartbeat + report_status + 心跳 stale sweeper 存在（agents.py L115-156 / app.py L71-183），stale 可推导 |
| ③ 认领非单事务（claim 与状态推进分离提交） | 命中 | MCP claim_task 单事务只建 lease，不碰 task 状态（coordination.py L64-118）；状态推进是独立 move_task 事务（tasks.py L169-197）——PRD AC1 的 claim+state 单事务崩溃原子性 vendor MCP 面无 |
| ④ 角色门控缺口（agent 面可置终态/释放） | 命中 | MCP 面有 release_task（tool_schemas.py L304），agent 可释放自己租约（coordination.py L126-127）；move_task 可达 completed（tool_schemas.py L101），OWNER/MANAGER agent 可绕过 orchestrator-move 闸（review_gate.py L37-40） |

## T1.1 克隆与 pin

- 克隆 `kronos3610/agent-kanban-pm` 到 `.worktree/spike/_vendor/agent-kanban-pm/`。
- pin: `e29d288e4f454254c4f276a4cc25b64581b1ddf5`（`git log -1` 实测一致）。
- venv: `_vendor/agent-kanban-pm/.venv`（uv 创建，python 3.12.13，含 `kanban-mcp` 入口 + mcp 2.3.0）。启动 env: `KANBAN_AGENT_NAME=<entities 表 is_active 名称>`、`KANBAN_AGENT_ROLE=<role>`、`DATABASE_URL=sqlite+aiosqlite:///<db>`。

## T1.2 源码核验（四断言）

### 断言 A 认领排他（ADR「认领=通过(lease)」）-> **partial**

- DB 约束存在但粒度不符：`task_leases` 的 partial unique index `uq_task_leases_active_assignment` 覆盖 `(task_id, agent_id)` WHERE `status='ACTIVE'`（models.py L392-401）——只防同一 agent 对同一 task 持多个 ACTIVE lease，**不防两个不同 agent 同时 ACTIVE**（per-task 排他无 DB 约束）。
- per-task 排他纯应用层：claim_task 内 `SELECT TaskLease WHERE task_id=? AND status=ACTIVE AND expires_at>now AND agent_id!=?`（coordination.py L70-77）-> 命中即拒（L79-80）-> 否则 INSERT（L94-101）。check 与 insert 在同一事务（L116 commit），但为无锁 read-then-write：并发两 agent 各自事务均看不到对方 ACTIVE lease 时双双通过，索引不拦（不同 agent）。
- PRD 对照：PRD L57 要求 claims 上 `UNIQUE (requirement_id) WHERE ended_at IS NULL`（per-requirement 排他，DB 强制）——vendor 无此约束。
- 实测佐证：同一 task 出现两个 ACTIVE lease（lease2+lease3，见 T1.3）。

### 断言 B 租约/心跳/stale（ADR「占用恢复=通过(heartbeat/stale)」）-> **pass（带注意项）**

- 租约: `TaskLease.expires_at` TTL 制（models.py L408）；claim 时 `now + ttl_seconds`（coordination.py L99）。
- 心跳: `report_status` upsert `AgentHeartbeat`（按 agent_id 唯一行，handlers/agents.py L115-156，commit L153）。
- stale 推导: `_heartbeat_sweeper`（app.py L71-183）按 per-adapter `heartbeat_interval` 阈值把过期心跳置 IDLE/清 task_id（L173-176）、活跃会话补写（L153-156）；`_orphaned_session_sweeper`（app.py L226-278）把消失的 AgentSession 置 ERROR。
- 注意项（不翻转判定，但 T2 需按 PRD 语义自研）:
  - lease 自身无心跳/activity 耦合：心跳是独立 per-agent 表，不刷新 lease；lease stale 纯 TTL。
  - lease 过期**不自动释放、不置 EXPIRED**（实测：lease2 过期后仍 ACTIVE，见 T1.3）——PRD L86 亦为「唯一释放路径=人，无自动释放」，此处语义吻合；但 PRD 要求 STALE/等待中推导与 activity 口径（L103），vendor 无 claim 级 activity 字段。
  - `AGENT_STALE` 事件类型已定义（events.py L52）但从无 emit（全 src 检索仅 events.py 定义处命中，死代码）。

### 断言 C 角色门控 MCP 工具面（ADR「DONE人确认=部分(机器转)」+ MCP stdio）-> **partial**

- MCP stdio 工具面成立：`claim_task`（tool_schemas.py L290）、`release_task`（L304）、`move_task`（L94，status enum 含 `completed` L101），真机 stdio 驱动成功（T1.3）。
- 门控缺口:
  - `release_task` 存在（PRD AC16 要求 agent 面无任何释放工具）：coordination.py L120-138，lease 属己时不查角色（L126-127），仅释放他人 lease 才要求 MANAGER（L128）——agent（WORKER）可经 MCP 释放自己租约（实测成功，T1.3）。
  - 终态可达: `move_task` 要求 WORKER 角色（tasks.py L171），worker 置 completed 被 review 前置闸挡住（review_gate.py L45-46「Complete review before marking the task Done」，实测命中）；但 `completion_blocker` 的 orchestrator 判定 `actor.role in (OWNER, MANAGER)`（review_gate.py L37-40）——OWNER/MANAGER 角色 agent 可绕过 orchestrator-move 闸，DONE 非人独有。
- 门控存在部分: worker 面 move-to-completed 确有证据闸（review_gate.py L29-116），非全裸。

### 断言 D append-only 活动日志（ADR「审计=通过(append-only)」）-> **pass**

- 审计表只增: `agent_activities`（models.py L459）、`task_logs`（L162）、`orchestration_decisions`（L373）、`outbox_events`（L657，payload 只增）。
- 删除仅在非审计处:
  - `pending_events` 是轮询队列，sweeper 按 TTL `DELETE`（app.py L186-223，delete 于 L204）——非审计表。
  - `task_leases` 行可被 UPDATE 成 RELEASED（coordination.py L129，状态非审计）。
  - 真删除仅 REST/UI 路由（agent_connections.py L182/L197、entities.py L138/L154、projects.py L162/L176、stages.py L82/L97、tasks.py L196/L219/L336、ui/projects.py L62/L81、ui/tasks.py L457/L478）；MCP 工具面无删除工具。
- PRD 对照: events append-only + 清除/释放事件与状态变更同事务（PRD L69）——vendor 侧 release 事件与状态翻转确在同一事务（coordination.py L129-137）。

## T1.3 实跑驱动（真机 MCP stdio，serial sessions）

- 方法: 每 agent 一个独立短生命周期 `kanban-mcp` stdio 子进程（driver.py，`StdioServerParameters` + `ClientSession` 显式 `initialize()`）；DB 直读快照（`sqlite3 ... mode=ro`）作事后 oracle。
- fixture: owner=1(human OWNER)、probe_agent1=2、probe_agent2=3（agent WORKER）、project=1(APPROVED)、task=1(PENDING, stage To Do=2)。
- 关键日志行（driver.stdout.log，行号即文件行号）:
  - L2-6 `[claim] claim_task: {"success": true, "lease_id": 1, ...}` —— agent1 认领成功。
  - L7-12 `[advance] move_task: {"success": true, ..., "status": "in_progress"}` —— 状态推进是第二次独立调用/独立事务（claim 未推进状态，佐证 ③）。
  - L17-20 `[claim2] claim_task: {"error": "Task is already leased by agent 2", "lease_id": 1}` —— 第二 agent 认领被拒（应用层拒绝，佐证 ①）。
  - L25-29 `[hb] report_status: {"success": true, ...}` + L33 heartbeat 行 —— 心跳写入（佐证 ②）。
  - L35-39 `[release] release_task: {"success": true, "lease_id": 1, "status": "released"}` —— agent 经 MCP 释放自己 lease 成功（佐证 ④）。
  - L56-60 62s 后快照: lease2 仍 `ACTIVE`、`expires_at` 已过、`released_at=None` —— 过期不自动释放/不置 EXPIRED（佐证 ② 注意项）。
  - L62-72 过期后 agent2 认领成功: lease3 ACTIVE 与 lease2(ACTIVE 过期) 共存同一 task —— 同 task 两个 ACTIVE lease（佐证 ① per-task 排他靠 expires_at 过滤的应用层）。
  - L74-77 `[done-attempt] move_task: {"error": "Complete review before marking the task Done", "transition_blocked": true}` —— worker 置 completed 被 review 闸挡（佐证 ④ 部分门控）。

## T1.4 结论：ADR 0001 移植边界确认/修正

ADR 0001（L38）「移植 = 借用其认领/租约/角色门控 MCP/append-only 的实现模式与表结构，不引入其代码为运行依赖」——**方向确认，粒度修正**:

- 可借（实测证实）: `task_leases`/`agent_sessions` 表结构 + partial unique index 写法、claim 拒绝语义（返回持有者）、心跳 upsert + stale sweeper 模式、append-only 事件表 + outbox、MCP stdio 工具面骨架。
- 不可照搬（DEVIATION ①③④，PRD 已规定而 vendor 不具备，须自研——正是 T2 骨架要做的）:
  - per-task 认领排他需自建 `UNIQUE(requirement_id) WHERE ended_at IS NULL`（PRD L57，DB 强制），替代 vendor 的 `(task_id, agent_id)` 应用层 check-then-insert。
  - claim+state 单事务（PRD L94）：认领 = INSERT claims + 条件 UPDATE requirements，rowcount 校验，任一失败整体回滚（AC1 kill 崩溃原子性）。vendor MCP 面 claim 与状态推进分离提交，照搬即继承崩溃半态缺陷。
  - agent 面无 release（PRD AC16）：MCP 12 工具清单不含 release，释放仅 CLI 人面。
  - DONE 仅人面（PRD AC3/L119）：vendor `completed` 走 agent move_task（OWNER/MANAGER 可绕过 orchestrator 闸），须改为唯一转移点 state_machine + 人面 approve 同事务（T2.3/T2.7）。
  - claim 级 activity 口径（PRD L103）：`last_activity_at` 写事务内更新、STALE/等待中/SUSPECT 推导（T2.5），vendor 无 claim 级 activity 字段。
- ② 未命中但注意项要落实: lease 过期不自动释放语义与 PRD L86 一致；STALE 推导与 AGENT_STALE 死代码属 vendor 未完成项，T2.5 按 PRD 从零实现（env 覆盖 `AGENT_KANBAN_LEASE_SECONDS`/`AGENT_KANBAN_IDLE_SECONDS` 加速）。

## 域外发现

1. mcp 2.3.0 SDK `ClientSession` 不再 auto-initialize，必须显式 `await session.initialize()`；此前 -32602「Invalid request parameters」为客户端用法错误，非 vendor bug（与 spike 自身 mcp 2.3.0 同版，T2.6 需按此写法）。
2. `AGENT_STALE` 事件类型死代码（events.py L52 定义、全仓无 emit）——vendor 未完成项，T2.5 不借鉴。
3. vendor launcher 路径（assignment_launcher.py L906-1034）确有 session+lease+`_mark_task_started` 单事务（L1034 commit），但那是运行时编排路径（tmux/进程探针），**MCP agent 面 claim_task 不经过它**；PRD AC1 对应的是 agent 面 MCP claim，故 ③ 判定不受影响。
