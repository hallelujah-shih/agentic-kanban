# ADR 0001 - 自研 vs 复用/改造候选工具（G6 裁决）

状态: 已裁决（2026-10-22，桌面调研 + 源码级取证，非 2h 实操）
关联: docs/PRD.md 第 8 节 Spike 前置、第 10 节 G6；docs/adr/0000-known-gaps.md
问题: 是否复用/改造现成 AI agent 看板工具，还是自研

## 判据矩阵（9 项）

合取目标 = 三问（Q1 预期锚 / Q2 偏离 / Q3 备选）+ 反淹没 + 认领排他 + 占用恢复 + DONE 人确认 + 审计资产 + MCP stdio + 本地单用户。

| 候选 | 谱线 | License | 活跃 | MCP stdio | Q1 | Q2 | Q3 | 反淹没 | 认领 | 占用恢复 | DONE人确认 | 审计 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| kander | 控制面 | MIT | 158★ v0.9.10 | 无 | 通过(ACCEPTANCE_CRITERIA) | 通过(hash-bound findings) | 通过(basis+决策引用) | 部分 | 通过(pins/CAS/epochs) | 通过(2PC/进程探针) | 通过(5-check 闸) | 通过(git 卡) |
| Traycer | 控制面 | MIT | 1628★ 活跃 | 仅 client | 部分(ticket 人审批) | 部分(drift gate 停跑) | 部分(/debate + A/B fork) | 通过 | 部分(assign) | 通过 | 部分(无硬闸) | 通过(工件版本) |
| kandev | 控制面 | AGPL-3.0 | 988★ 活跃 | 无(HTTP/SSE) | 部分(草稿) | 部分(escalation) | 无 | 无 | 无(advisory) | 部分(stall + waiting-vs-dead) | 部分(工作流驱动) | 部分 |
| agent-kanban-pm | 记录面 | MIT | 8★ 2026-09 | 有(stdio) | 部分(无 DoD 结构) | 部分(无 findings) | 部分(无 alternatives) | 通过(Focused view) | 通过(lease) | 通过(heartbeat/stale) | 部分(机器转) | 通过(append-only) |
| graywrk/agent-kanban | 记录面 | MIT | 4★ 沉寂 | HTTP+SSE | 无 | 部分(typed events) | 无 | 无 | 通过(MVCC atomic) | 无 | 无(agent 自标) | 部分 |
| Vibe Kanban | 记录面 | Apache-2.0 | 28k★ 已 sunset | 有(--mcp) | 部分 | 部分(派生 PR 状态) | 无 | 部分 | 部分 | 部分 | 通过(Done=PR merged) | 部分 |
| Agetor | 记录面 | MIT | 92★ macOS-only | 无 | 部分 | 部分(Blocked+原因) | 无 | 通过 | 部分 | 通过(session-gone->Ready) | 通过(human move) | 部分 |
| Cline Kanban | 记录面 | Apache-2.0 | 1.4k★ | 无(已移除) | 无 | 无 | 无 | 通过(hooks) | 部分 | 无(crash-resume 未闭合) | 通过(人清卡=完成) | 部分 |
| Nimbalyst | 记录面 | MIT | 1.9k★ | 仅 client | 部分 | 无 | 部分(@decision) | 通过 | 无 | 部分 | 无(agent 自移) | 部分 |
| openkanban | 记录面 | AGPL-3.0 | 152★ 沉寂 | 无 | 无 | 无 | 无 | 无 | 部分 | 部分 | 部分 | 无 |
| VS Code Agent Kanban | 记录面 | ELv2/SaaS | 60★ 沉寂 | HTTP only | 无 | 无 | 无 | 部分 | 部分 | 无 | 无(agent 自移) | 部分 |

## 关键洞察

1. **合取无解**：没有任何单一候选同时满足 9 项。满足「三问 + 人确认 DONE」的是控制面（kander 最强）；满足「MCP stdio + 本地单用户 + 记录面 + 租约 + 审计」的只有 agent-kanban-pm。
2. **谱线冲突**：控制面候选（kander/Traycer/kandev）正是 PRD v1->v3 已推翻的「看板控制执行」方向（它们自带 worktree 编排、跑 agent、闸门停跑）。以其为底座 = 推翻既定裁决。
3. **意外重合**：agent-kanban-pm（kronos3610，MIT）与我们选型完全同构——FastAPI + SQLite + stdio MCP（角色门控）+ 租约/心跳 + append-only 活动日志 + Alembic + 本地单用户。其缺口正是我们的差异化核心：无验收对照（Q1）、无结构化偏离（Q2）、决策无备选字段（Q3）、DONE 机器转移、无导出、无关键节点摘要。
4. **设计参照可白嫖**（不引入依赖）：kandev 的 stall 分类（waiting-vs-dead 判定逻辑）、Traycer 的 drift gate（产品偏离停跑并回到人）、kander 的 hash-bound findings。

## 裁决

**自研为主，agent-kanban-pm 为移植种子（架构蓝本），kandev/Traycer/kander 机制为设计参照。**

- 采纳: 自研看板（记录面），数据模型与状态机按 PRD v3.2；认领/租约/审计骨架按 agent-kanban-pm 模式移植（MIT 合法）。
- 不采纳: 任何控制面工具作底座（谱线冲突）；kandev 作依赖（AGPL + 编排面不需要）；Vibe Kanban（已 sunset）、Agetor（macOS-only）、VS Code Agent Kanban（SaaS 化）。
- 移植边界: 移植 = 借用其认领/租约/角色门控 MCP/append-only 的实现模式与表结构，不引入其代码为运行依赖（8★ 无社区，单作者，作运行依赖风险高）。

负载论证（为什么不是纯从零也不是整仓 fork）:
- 差异化核心（Q1 锚、Q2 结构偏离、Q3 备选、人确认 DONE、反淹没摘要）在任何候选里都是缺失或草稿，补全成本 ≈ 自建；
- 而认领/租约/审计/角色门控 MCP 这类「基础设施骨架」agent-kanban-pm 已实现且同栈，直接移植省一个 Spike 的推倒重来；
- 组合两半（自建差异面 + 移植骨架）比任一半从零都便宜，且不背 AGPL/编排包袱。

## 生效与后续

- 生效点: 本 ADR 生效即 G6 决策层闭合；PRD §8 Spike 前置措辞随 v3.2 折入更新（候选对照已完成，实操验证收窄为「agent-kanban-pm 骨架可移植性验证」）。
- 残余: 移植性未经真机验证（G7，档位 ③），Spike 内用 2h 实操验证其 MCP 面能否推进状态（对应 PRD AC1/2/3 的场景）。
- 复审: 若 Spike 实操发现骨架与声明的重大偏差，回到本 ADR 重议移植边界。G7 已触发重议，结论见下节「G7 Spike 验证」。

## G7 Spike 验证（2026-10-22，真机 2h 实操）

前置: docs/ops/spike-g7.md（证据报告，pin e29d288e4f454254c4f276a4cc25b64581b1ddf5）

四断言实测 verdict（证据行号见报告）:
- 认领排他: partial——DB 索引为 (task_id, agent_id) WHERE ACTIVE，非 per-task 粒度；per-task 排他靠应用层无锁 check-then-insert（models.py L393-400 / mcp/handlers/coordination.py L70-80）。
- 租约/心跳/stale: pass——expires_at TTL + 心跳 upsert + stale/orphaned sweeper 存在；注意项: 过期不自动释放/不置 EXPIRED、AGENT_STALE 死代码（events.py L52）。
- 认领原子性: fail——MCP claim_task 单事务只建租约、不碰任务状态；状态推进是独立 move_task 事务（mcp/handlers/coordination.py L58-118 / mcp/handlers/tasks.py L169-197）。
- 角色门控 MCP: fail——MCP 面有 release_task + move_task 可达 completed，DONE 非人独有（mcp/tool_schemas.py L94/L304）。

偏差触发: 命中 ① ③ ④（回退分支生效）。重议结论: 方向不变（自研为主、不引入运行依赖），移植边界收窄——只借已证实模式，其余自研（正是 T2 骨架任务）:
- 借: lease 表结构 + partial unique index 写法（按 PRD per-requirement 粒度重建）+ 认领拒绝语义 + 心跳/stale sweeper 推导 + append-only 事件表。
- 不借（自研）: per-task DB 排他约束（PRD UNIQUE(requirement_id) WHERE ended_at IS NULL）、claim+state 单事务原子性（AC1）、agent 面无 release（AC16）、DONE 仅人面（AC3）、claim 级 activity 口径。
- G7 闭合: docs/adr/0000-known-gaps.md G7 更新为已闭合。
