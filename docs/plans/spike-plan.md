# Spike Plan — G7 移植性验证 + 骨架实现（AC1-9/16）

分支: `spike`（worktree: `.worktree/spike/`，基分支 main @ e29106b）
档位: 全六门（C 数据面/SQLite 落盘 + D 对外契约/MCP 工具面 + 新测试语义 AC harness + 影响面①）
规范锚: docs/PRD.md v3.2（commit e29106b）。Spike 只实现 PRD 已审契约，不改业务规则（不触发 Phase 0.5；PRD v3.2 即已审契约文档）
依赖实测: python 3.14.4（.venv）、sqlalchemy 2.1.6、aiosqlite 0.22.1、mcp 2.3.0、pydantic 2.14.1、uv 0.11.12
API 实测: `from mcp.server import MCPServer` 可用（fastmcp 已移除）；`MCPServer.add_tool(fn, name=None, title=None, description=None, ...)` 注册工具；`MCPServer.run(transport='stdio')` 默认 stdio（探针于 .venv 内，已核）

## 契约三锚

1. 规范逐字原文: docs/PRD.md §2（数据模型/DB 约束，L46-71）、§3.1（状态与边，L75-90）、§3.2（认领/租约，L92-106）、§3.3（写保护，L108-114）、§3.4（完成语义，L116-129）、§4.1（MCP 工具面 12 工具，L135-152）、§4.3（错误码 9 码，L166-171）、§7.3（契约级要点，含 #9 ON CONFLICT，L283-291）、§9（AC1-9/16，L310-319）。
2. 代码锚点: 本仓无既有代码；锚点 = 上述 PRD 行号 + mcp 2.3.0 API 探针结论（上节）。
3. 逐例期望: 见「原子任务 T2.8」的 AC 判据表 + 9 码触发矩阵。

## 影响面声明

- ① 对外接口/工件格式/数据迁移: 命中（MCP 工具面 + SQLite schema 首次建立）。单向门处理：契约已过 PRD v3.2 四轮对抗审查；本 plan 审按四层对抗执行；AC oracle + 结果盲审兜底实现偏差。
- ② 新入口/信任边界: 命中（MCP stdio 是 agent 入口）。Spike 单用户本地 stdio、无 token（PRD 6 的 localhost/token 是 M0 安全面）；入口经写保护 service 统一校验。威胁面：agent 面不能置 DONE（AC3）、无认领不能写（AC6）。
- ③ 热路径/资源敏感: 不命中。
- ④ 业务规则变化: 不命中（按 PRD 逐字实现）。

## 并发/并批判据

- G7（T1.x）与骨架（T2.x）改动文件集不相交（_vendor/ + docs/ops/spike-g7.md vs src/ + cli.py + tests/），但 G7 verdict 决定 T2 的借法 → **串行**：先 T1 批（自审通道，A 面观测研究），后 T2 批（全六门）。
- T2.1-2.9 同触 src/ → 同一批、派发内串行（同仓未提交改动互斥）。

## Part 1 — G7：agent-kanban-pm 移植性验证（A 面观测，自审通道）

原子任务：
- T1.1 克隆 kronos3610/agent-kanban-pm 到 `.worktree/spike/_vendor/agent-kanban-pm/`，pin commit sha（写进报告）。
- T1.2 读源码，逐条核 ADR 0001 断言：①认领排他（lease/session uniqueness）②租约/心跳/stale ③角色门控 MCP 工具面（stdio）④append-only 活动日志。每条给 file:line 证据。
- T1.3 实跑其 MCP server，用 MCP stdio 客户端驱动：claim -> 状态推进 -> 第二认领被拒 -> heartbeat/过期信号。记录驱动日志。
- T1.4 产出 `docs/ops/spike-g7.md`（tracked）：每项 pass/partial/fail + 证据 + 对 ADR 0001 移植边界的确认/修正。
  - 偏差大触发清单（任一命中即回 ADR 0001 重议并登记）：①认领排他靠应用层而非 DB 约束；②租约无心跳/activity 口径；③认领非单事务（claim 与状态推进分离提交——直接决定 AC1 崩溃原子性能否照搬其模式）；④角色门控缺口（agent 面可置终态/释放）。
  - 回退分支：G7 偏差大 -> T2 **不停摆**，按 PRD 从零实现，只借 G7 已证实的实现模式；ADR 0001 更新修正后继续。
- 定量验证: spike-g7.md 含每断言证据行号 + 驱动日志关键行；无断言的 pass 不算数。

## Part 2 — 骨架实现（全六门）

原子任务（每任务含验证命令与期望）：

| # | 任务 | 验证命令 | 期望 |
|---|---|---|---|
| T2.0 | **前置：登记 ADR 0002**（mcp>=2.3,<3 锁定、stdio 传输、MCPServer 替代 fastmcp、stdio 无 token 鉴权模型）——闭合 G4 单向门 | `git ls-files docs/adr/0002-mcp-sdk.md` | 文件 tracked、内容四要素齐 |
| T2.1 | pyproject entry points（`agent-kanban mcp` / `agent-kanban cli`）+ 目录 | `uv run agent-kanban --help` | 退出 0，列出子命令 |
| T2.2 | models + schema + connect 事件（FK/WAL/busy_timeout）+ DB 约束 + **DB 文件创建后 chmod 0600**（闭合 mcp-config.md 承诺） | harness 探针 + `stat -c %a <db>` | FK=ON 实测；partial unique index 存在；seq 全局单调服务端同事务签发、ts 服务端签发；ON CONFLICT 用裸 DO NOTHING（PRD 7.3 #9）；文件权限 0600 |
| T2.3 | state_machine service（唯一转移点、单事务+rowcount、BEGIN IMMEDIATE） | T2.8 AC3/AC2 | 按 PRD 3.1 边集；非法边 illegal_state |
| T2.4 | identity/写保护（actor 派生自传输会话、写保护同事务 ended_at IS NULL） | T2.8 AC6 | 无认领写 -> no_active_claim；并发释放不产孤儿 |
| T2.5 | lease service（STALE/等待中/SUSPECT/ACTIVE 推导 + activity 口径） | T2.8 AC2 | 过期无标记=STALE；有标记=等待中；idle 超无标记=SUSPECT；不自动释放 |
| T2.6 | MCP server（**12 工具，含 list_awaiting**，错误码 is_error + structured content；decision 字段钉死见下） | T2.8 AC1/4/5/7/8/9 + 9 码矩阵 | 逐码触发条件与 PRD 4.3 一致 |
| T2.7 | CLI（new/set_expectations/approve/release/renew/note/abandon/export 最小面） | T2.8 AC3/16 | approve 置 DONE（CLAIMED）/解 BLOCKED/非法状态 illegal_state；release 回 OPEN、无认领 not_found |
| T2.8 | AC harness `tests/run_ac.py`（红→绿，oracle 独立） | `uv run python tests/run_ac.py` | AC1-9/16 + 9 码矩阵逐条 PASS；先红后绿留档 |
| T2.9 | `docs/ops/spike-verification.md`（tracked: harness 判据/基线/重跑规格/AC verdicts + 每轮红绿证据路径） | git ls-files 校验 tracked | 文件 tracked；判据逐条可复跑 |

**decision 字段钉死**（T2.6/add_record）：`{ choice, rationale, alternatives: [{option, rejected_reason}] }`。缺 alternatives[]（>=1）/ 缺 rationale / 某 alternative 缺 rejected_reason -> invalid_record（AC4 断言边界）。

**seq/ts 口径钉死**（T2.2）：seq = 全局单调计数（跨库唯一），服务端在写事务内同事务签发（BEGIN IMMEDIATE 单写者保证唯一）；保留 PRD 声明的 `UNIQUE(requirement_id, seq)` 作每需求排序索引（冗余但无害）。ts 由服务端同事务签发，不接受调用方传入。

### AC 判据表（harness 逐条断言，全部来自 PRD §9 逐字 + 上表钉死）

| AC | 断言 |
|---|---|
| 1 | 并发 10 claim_task 同需求：1 成功 + 9 already_claimed。**kill 锚**：env 钩子 `AGENT_KANBAN_TEST_CLAIM_HOOK=block_after_insert` 使 claim 事务在 INSERT claims 后、UPDATE requirements 前阻塞；harness 触发后 SIGKILL 进程。**事后 oracle** = 重开后只读直查 SQLite 文件：无 `ended_at IS NULL` 孤儿 claim，且 claim-state 一致（CLAIMED <=> 恰一未结束 claim）。禁 sleep 撞窗（陷阱 #1） |
| 2 | 租约过期无 awaiting_human -> STALE；有标记 -> 等待中；两者不同；过期不自动释放/不自动重开。**加速机制**：env 覆盖 `AGENT_KANBAN_LEASE_SECONDS`（可负值/短秒，创建即过期），确定性造过期，禁 sleep 撞窗。SUSPECT：env 覆盖 `AGENT_KANBAN_IDLE_SECONDS` 短秒 + 无标记 -> SUSPECT |
| 3 | agent 面（MCP 12 工具）无法置 DONE；人面 approve 在 CLAIMED 置 DONE + claim ended_at + 清 marker；在 BLOCKED 解阻塞；在 OPEN/DONE/REOPEN/REJECTED/CANCELLED -> illegal_state；BLOCKED+kind=review 不可达（request_review 前置 state=CLAIMED） |
| 4 | add_record(kind=decision) 缺 alternatives[] / 缺 rationale / alternative 缺 rejected_reason -> invalid_record |
| 5 | add_record(kind=deviation, severity=info) 被拒或强制升 attention |
| 6 | 无未结束认领的写 -> no_active_claim；并发释放+写入竞争不产孤儿（DB 直读：agent 面记录 ts 落在 [started_at, ended_at] 内）。**并发架构**：真实多进程 MCP stdio 客户端（N 个子进程共享同一 SQLite 文件，WAL 跨进程语义），非单进程 async |
| 7 | 同需求同 title（大小写/空白归一后）第二次 add_subtask -> duplicate_subtask |
| 8 | 第 17 个 claim_task -> queue_full（计数含 STALE/等待中；STALE 用 env 短 lease 造） |
| 9 | 对已过期租约 renew -> lease_expired |
| 16 | MCP 面无释放工具（12 工具清单无 release）；CLI release 在 CLAIMED 释放成功写 release 事件且回 OPEN；无认领 not_found |

### 9 码触发矩阵（T2.8 补充断言，全部 PRD-literal 字符串）

| 码 | 触发 | 断言 |
|---|---|---|
| already_claimed | 第二 agent 认领 | AC1 |
| not_found | 对不存在需求 claim/renew/approve/get_task_detail | 返回 not_found |
| illegal_state | approve 于 OPEN/DONE/REOPEN/REJECTED/CANCELLED；mark_blocked 于非 CLAIMED | AC3 扩展 |
| no_active_claim | 无未结束认领的写 | AC6 |
| lease_expired | 对已过期租约 renew | AC9 |
| duplicate_subtask | 归一后同 title | AC7 |
| invalid_record | decision 缺字段（AC4）；request_review 缺证据分支（死期 M0，PRD §11，标注唯一例外） | AC4 |
| queue_full | 第 17 认领 | AC8 |
| db_busy | 第二连接 BEGIN IMMEDIATE 持锁 + 极小 busy_timeout -> 写重试 3 次后（PRD 7.3 #4） | 返回 db_busy |

### awaiting_human / 自评补充断言（T2.8）

- approve 后 marker 清除（get_task_detail 观测，且清 marker 与 approval/state_change 同事务）。
- release 后 marker 清除。
- mark_blocked 覆盖旧 marker（新设置覆盖旧，旧事件保留）。
- request_review 持久化验收自评到 subtasks.acceptance[].state（get_task_detail 可读回）。

## oracle 纪律

- 独立于实现: harness 断言全部逐字引自 PRD §9/§4.3/§2（规范原文）；事后 oracle 用 DB 文件只读直查（读数据非读实现代码）。
- 反证位 load-bearing: 每 AC 先红——harness 对未实现/故意破坏的功能先跑出红，留档（tests/red-*.log），再实现至绿。
- 最强对抗变体: AC1 并发 10 真实多进程、AC6 释放与写并发竞争、AC8 第 17 认领（含 STALE 计数）、kill 崩溃原子性。
- 不可测性分支: 无（全部本仓实现，SQLite/MCP 均为本仓可测）。

## 验证入口与 tier（本机=构建机）

- tier-0: `uv run python -m compileall -q src cli.py`（语法）。
- tier-1: `uv run python tests/run_ac.py`（AC1-9/16 + 9 码矩阵全绿）。
- tier-2（最高/合并门槛）: tier-1 全绿 + 对账 `docs/ops/spike-verification.md` 逐条断言与当轮产物（红绿日志）一致 + `git ls-files docs/ops/ docs/adr/0002-mcp-sdk.md` 全 tracked。
- 折入只重跑受影响 AC 的 tier-1；合并前必须 tier-2。

## 不修清单（每条含位置/理由/登记处）

1. 不做 FastAPI/REST 人面 API —— M0（PRD 8），Spike 人面=CLI。登记: docs/ops/spike-verification.md「不做清单」。
2. 不做 Alembic 迁移 —— M0；Spike 用 `metadata.create_all`。登记: 同上。
3. 不做 reconcile 重启对账 —— M0（PRD 8）。登记: 同上。
4. 不做 token/非 localhost 绑定 —— M0 安全面（PRD 6）。Spike stdio 单机无网络面；DB 0600 已实现（T2.2），闭合 mcp-config.md 承诺。登记: 同上。
5. 不做摘要/深潜视图、导出 JSON/Markdown 之外 —— M0。Spike 的 export 仅 CLI 占位（AC 不测导出）。
6. 不做 payload 8KB 上限、数据保留清理 —— NFR M0。登记: 同上。
7. 不做重试/成本记录/心跳模型 —— 未决项 M0 裁决（PRD 11）。Spike 租约参数经 env 可覆盖（`AGENT_KANBAN_LEASE_SECONDS` / `AGENT_KANBAN_IDLE_SECONDS`）以便确定性测试。
8. **不做 `release --all-stale`**（PRD 4.2 L160 的 STALE 占满唯一恢复路径）—— M0 实现；AC16 只测单释放。显式登记，非静默遗漏。登记: 同上。

## 机械预检（派发前主循环已跑）

- 登记位置 tracked: docs/ops/spike-g7.md、docs/ops/spike-verification.md、docs/adr/0002-mcp-sdk.md 在 spike 分支新增并 tracked（派发后 git ls-files 验证）。
- 代码锚点: PRD 行号以上方 grep 实测为准；mcp API 探针在本 worktree .venv 实跑。
- oracle 版本: python 3.14.4 / sqlalchemy 2.1.6 / aiosqlite 0.22.1 / mcp 2.3.0 / uv 0.11.12；harness argv = `uv run python tests/run_ac.py`。
- 产物清单: src/agent_kanban/{__init__,db,models}.py、services/{state_machine,identity,lease,write_guard}.py、mcp/server.py、cli.py、tests/run_ac.py、pyproject.toml、docs/adr/0002-mcp-sdk.md、docs/ops/*.md。

## 域外发现处置

执行/审查中一切非本批引入的问题（环境缺口、基码缺陷、文档失实）→ 回报单列节 + 登记 docs/ops/spike-verification.md「域外发现」+ 修复裁决归主循环，禁静默修。
