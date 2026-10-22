# M1-3 Plan — 收尾批（G10 裁决 / 归档加密 / renew 事件 / G9-a prune / G5 基准）

分支: `m1-3`（worktree `.worktree/m1-3/`，基 main @ c179200）
档位: 全六门（① 新对外契约：prune CLI 命令 + renew 事件新 kind；无 ④——G10/归档/reconcile 是裁决与决定、renew 事件是审计补充、prune 是数据维护命令、G5 是测量）
规范锚: docs/adr/0000-known-gaps.md G5/G9/G10；docs/adr/0003-m0-decisions.md「G9 登记」「G10 登记」「reconcile ACTIVE 无闭合事件」；PRD §3.2（activity 口径/重试）、§4.2（CLI 人面）、§5.4（回溯）、§6（数据保留/性能/可观测）
G9-b 不在本批：属 ④（基于规则的派生状态系统 + 用户可见行为变化），拆 M1-4 走 Phase 0.5 BCD（判定源已由 user 裁决：系统派生计数）

## 契约三锚

1. 规范逐字原文: PRD §3.2「activity 口径：该 claim 的 agent 面任何写操作 + MCP 调用；last_activity_at 在写事务内更新」；§6 数据保留「events 保留 12 个月；清理由显式命令执行，清理前必须导出；导出文件为审计资产最终载体」；§6 性能「摘要视图 < 200 ms（5k 需求）；状态/记录写 < 50 ms」；ADR 0003 G10 登记「读计活动需连接级模型（连接建立/存活判定），M1 裁决」；ADR 0003「reconcile 事件为时点观测无闭合事件（设计如此）」。
2. 代码锚点: operations.py（renew 不写事件 / export_data 全量导出 / update_subtask 状态迁移）、cli.py（命令面：export/view/reconcile 等，无 prune）、view.py（reconstruct_states/_derived_signals 依赖 events 链）、db.py（get_session_factory/run_op）。
3. 逐例期望: renew 后 detail 事件流含 kind=renew 且归属人面 actor；`agent-kanban prune --months 12` 先强制导出（文件 0600）再删 >12 个月 events，确认门（无 --yes 需确认），导出失败不删；bench 脚本 5k 库测 summary/write/board 三面并记录；board 若超目标则批查询优化（输出/口径不变）。

## 影响面

- ① 新对外契约命中（prune CLI 命令；renew 事件新 kind 入事件流）。
- ② ③ ④ 不命中。G10/归档/加密/reconcile ACTIVE = 裁决与决定（规格澄清，无行为变化）。
单向门：契约源自 PRD §3.2/§6（已审规格）+ ADR 0003 登记（M1 裁决约定）；本 plan 审 + 结果盲审 + AC oracle 兜底。

## 原子任务

| # | 任务 | 验证 | 期望 |
|---|---|---|---|
| M1-3.1 | docs 裁决批（docs 先于代码）：ADR 0006（M1-3 裁决）——(a) G10 维持写口径：last_activity_at 在写事务内更新（PRD §3.2 原文），读路径用只读 session（写会污染读路径架构），等待场景由 awaiting_human 豁免（SUSPECT 判定「无 awaiting_human」已覆盖），连接级模型不引入（与 ADR 0003 reconcile 观测源=claims 表无进程内 registry 一致）；PRD §3.2 activity 口径行文字澄清。(b) 归档=prune 强制导出文件（timestamped JSON 0600，审计资产最终载体）；加密不做（单用户本地 + 文件 0600 + 威胁模型 A 残余 G1 直写 SQLite 不可防，加密增益边际，文档化）。(c) reconcile ACTIVE 闭合事件维持 ADR 0003 不实现（时点观测；_append_reconcile_signals 观测仍成立才显示，自愈）。(d) known-gaps G9/G10 行闭合标注 + PRD 状态行。**prune 的已知限制入 PRD §5.4**：删旧 events 后，跨 12 个月窗口的 state_change 链断裂 -> 深潜 state_at_event 与 _derived_signals 对窗口外转移不保证（归档文件为权威），摘要/看板用当前 state 列不受影响 | git ls-files tracked | 裁决入档 + 规格澄清 |
| M1-3.2 | renew 写事件：operations.renew 同事务 add_event(kind="renew", severity="info", title="lease renewed", actor_surface/conn, claim_id)；renew 是人面（CLI/REST）actor 已由 rest_actor 派生。回溯判据 3 覆盖 renew | harness: REST renew + CLI renew -> detail events 含 kind=renew + actor_surface='rest'/'cli' + claim_id 关联；无认领 renew -> not_found 不写事件 | 谁续了租约可回溯 |
| M1-3.3 | G9-a prune CLI：operations.prune_events(session, cutoff) 单事务删 events ts<cutoff 返回删除数；CLI `prune`：--months N（默认 12，cutoff=now-N月）、--export-path（默认 ./exports/kanban-export-<ts>.json）、--yes；流程=全量导出（export_data json，无 LIMIT）-> 写文件（0600，mkdir exports/）-> 打印将删数 -> 确认门（非 --yes 读 stdin y/N）-> prune_events；导出失败中止（清理前必须导出） | harness: 造 2 需求，SQL backdate 一个需求 events -400 天，prune --months 12 --yes --export-path tmp：导出文件含全部需求 events（导出先行）、backdated 删、recent 留、需求行留；拒绝路径（stdin 'n'）不删；无 --export-path 时默认文件生成 | 强制导出 + 12 月窗口 + 确认门 |
| M1-3.4 | G5 基准：tests/bench.py（独立脚本，不进 run_ac）——5k 需求库（直接 SQL 批量种子，形状对齐 ORM：每需求 2-3 subtasks + 1 milestone + 数 events + claims），测三面：view.summary 单需求（PRD 目标 <200ms）、add_record 写（<50ms）、board（混合 4900 终态+100 活动 + 最坏 5k 活动）；结果记录 docs/ops/bench-results.md（日期/环境/数字/结论） | `uv run python tests/bench.py` 跑通 + bench-results.md 记录 | 基准跑完 + G5 闭合 |
| M1-3.4b | （条件，仅当 bench 显示 board 超目标）board 批查询优化：claims/subtasks/milestones/events 分组查询一次取回 + Python 内存分组，逐需求调 _derived_signals/_milestone_row/_risk_rows（输出与口径不变，审#P1-2 零假阴性保持）；复测 bench | bench 前后数字对比 | 口径不变 + 延迟下降 |
| M1-3.5 | harness 集成（tests/ac_cases_h.py + run_ac 注册）：M1-3.2/3.3 用例红绿留档（red-6 -> green-6）；回归既有 284 | `uv run python tests/run_ac.py` 全绿 | 全绿 + 回归零 |
| M1-3.6 | docs：m1-3-verification.md（判据/红绿/prune 已知限制/G5 基准结果/盲区：bench 为测量非断言门、stdin 交互在子进程 harness 覆盖）；PRD §4.2 加 prune 命令行 + §6 数据保留行更新（命令名） | git ls-files tracked | 文档对齐 |

## oracle 纪律

- 断言逐字引自 PRD §3.2/§5.4/§6；renew 事件经 REST/CLI 真实调用断言；prune 用真实子进程 CLI + SQL backdate（确定性，禁 sleep）；bench 用直接 SQL 批量种子（测量 harness，非正确性 oracle）。
- 反证位：prune 导出先行（文件含将删 events）+ 拒绝路径不删 + backdated 删/recent 留；renew 事件归属两 channel。
- 既有 284 不回归。

## 验证入口与 tier

- tier-0: `uv run python -m compileall -q src cli.py`
- tier-1: `uv run python tests/run_ac.py` 全绿
- tier-2（合并门槛）: tier-1 全绿 + bench-results.md + m1-3-verification.md + git ls-files 全 tracked

## 不修清单

1. 不做加密导出（裁决：单用户本地 + 0600 + G1 残余不可防，见 M1-3.1）。
2. 不做 reconcile ACTIVE 闭合事件（维持 ADR 0003，时点观测自愈）。
3. 不做读计活动（G10 裁决：维持写口径，awaiting_human 覆盖等待场景）。
4. 不做退役/僵尸项目归档（PRD §6 退役行，非 G9 登记，M2+）。
5. prune 不删需求/认领/子任务/里程碑行（PRD 仅 events 保留窗口；需求行是板项）。
6. bench 不进 run_ac（5k 种子慢 + 环境依赖；独立脚本 + 记录）。

## 机械预检

- 登记位置 tracked: docs/plans/m1-3-plan.md、docs/adr/0006-m1-3-decisions.md、docs/ops/bench-results.md、docs/ops/m1-3-verification.md、tests/bench.py。
- oracle 版本: mcp 2.3.0 / httpx2 2.16.0 / fastapi 0.158.2 / sqlalchemy 2.1.6。
- 产物清单: src/agent_kanban/services/operations.py（renew 事件 + prune_events）、cli.py（prune 命令）、tests/ac_cases_h.py、tests/run_ac.py、tests/red-6.log/green-6.log、tests/bench.py、docs/adr/0006-m1-3-decisions.md、docs/ops/bench-results.md、docs/ops/m1-3-verification.md、docs/PRD.md（§3.2/§4.2/§5.4/§6）。

## 域外发现处置

执行/审查中一切非本批引入的问题 -> 回报单列 + 登记 + 主循环裁决，禁静默修。
