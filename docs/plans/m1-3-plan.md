# M1-3 Plan — 收尾批（G10 裁决 / 归档加密 / renew 事件 / G9-a prune / G5 基准）

分支: `m1-3`（worktree `.worktree/m1-3/`，基 main @ c179200）
档位: 全六门（① 新对外契约：prune CLI 命令 + renew 事件新 kind；无 ④——G10/归档/reconcile 是裁决与决定、renew 事件是审计补充、prune 是数据维护命令、G5 是测量）
规范锚: docs/adr/0000-known-gaps.md G5/G9/G10；docs/adr/0003-m0-decisions.md「G9 登记」「G10 登记」「reconcile ACTIVE 无闭合事件」；PRD §3.2（activity 口径/重试）、§4.2（CLI 人面）、§5.4（回溯）、§6（数据保留/性能/可观测）
G9-b 不在本批：属 ④（基于规则的派生状态系统 + 用户可见行为变化），拆 M1-4 走 Phase 0.5 BCD（判定源已由 user 裁决：系统派生计数）
盲审: REJECT（P1-1 renew actor_surface、P1-2 prune 链断裂选方案 (b) 需求级原子保留 + P2-1..7），已全部折入（标注「审#」）；复审待原审者 consensus

## 契约三锚

1. 规范逐字原文: PRD §3.2「activity 口径：该 claim 的 agent 面任何写操作 + MCP 调用；last_activity_at 在写事务内更新」；§6 数据保留「events 保留 12 个月；清理由显式命令执行，清理前必须导出；导出文件为审计资产最终载体」；§6 性能「摘要视图 < 200 ms（5k 需求）；状态/记录写 < 50 ms」；ADR 0003 G10 登记 + reconcile 时点观测无闭合事件。
2. 代码锚点: operations.py（renew 不写事件 / export_data / add_event / RECORD_KINDS）、identity.py rest_actor（**审#P1-1 返回 ("cli", "rest:<hex>")**）、cli.py、view.py（reconstruct_states 初始 OPEN 假设已核成立 / _claimed_intervals）、db.py（run_op）。
3. 逐例期望: renew 后 detail 事件流含 kind='renew' + actor_surface='cli'（人面）且 actor_conn 判别 CLI('cli') vs REST('rest:' 前缀)；`agent-kanban prune --months 12` 先强制导出（文件 0600）再按**需求级原子窗口**删 events（全部 events 早于 cutoff 的需求整删，否则全留——链永不半断），确认门（非 --yes 读 stdin，EOF/拒绝 abort 不删），导出失败不删；bench 脚本 5k 库测 summary/write/board 三面并记录；board 若超自定预算则批查询优化（同一 DB 优化前后 board dict 全等）。

## 影响面

- ① 新对外契约命中（prune CLI 命令；renew 事件新 kind）。
- ② ③ ④ 不命中（G10/归档/加密/reconcile ACTIVE = 裁决；renew 事件 = 审计补充；prune = 数据维护；G5 = 测量）。
单向门：契约源自 PRD §3.2/§6 + ADR 0003 登记；本 plan 审 + 结果盲审 + AC oracle 兜底。

## 关键设计决策（审#折入）

- **审#P1-2 prune 窗口 = 需求级原子保留**（方案 (b)）：删 events 的谓词 = `requirement_id IN (SELECT requirement_id FROM events GROUP BY requirement_id HAVING MAX(ts) < :cutoff)`——该需求全部 events 早于窗口才整删，否则全留（链永不半断，reconstruct_states/_claimed_intervals 不产生错值或假阴性）。代价：活动需求的部分 events 超 12 个月保留——产品语义为「活动需求 = 活审计主体，保留完整链；终态且全窗外需求整删，归档文件为最终载体」，PRD §6 数据保留行改写（窗口语义）+ §1 C7 措辞对齐（回溯保证 = 未清理的完整链；整删需求以归档为准）。**「12 个月」语义 = 日历月**（--months N，now 减 N 个自然月，纯算术无新依赖）。
- **审#P1-1 renew 归属**：REST 与 CLI renew 的 actor_surface 恒为 'cli'（人面语义，rest_actor 契约），两 channel 判别靠 actor_conn（CLI='cli'、REST='rest:<hex>' 前缀）。
- **审#P2-6 prune 事务边界**：确认门（读 stdin）期间不持写事务——先导出（读）+ COUNT 将删（读），确认后再开写事务 DELETE；stdin EOF/拒绝 -> abort 不删、非零退出、不 traceback；y/N 大小写均可；打印将删数 = COUNT 快照，prune 返回实际删除数（注明关系）；CLI 打印导出文件路径。
- **审#P2-2 renew 触活口径**：renew（人面）更新 last_activity_at 为既有行为，裁决语义 = 「last_activity_at = claim 最近活跃时间戳」，来源可为 agent 写（MCP）或 renew（人续租证明）——ADR 0006 记录该例外，PRD §3.2 activity 行澄清。
- **审#P2-1 G10 静默读声明**：ADR 0006 显式声明「agent 只读不写被标 SUSPECT 是意图内——看板是记录面，无写 = 无进展证据；等待场景由 awaiting_human 豁免（既有）」。
- **审#P2-4 bench 种子形状**：直接 SQL 批量种子必须 (a) seq 同步 seq_counter 到 max(seed seq)（否则 add_record 撞 UNIQUE(requirement_id, seq)）；(b) ts 经 SQLAlchemy 绑定参数写 datetime（UTCDateTime 往返，禁裸 SQL 字符串）；(c) payload 形状对齐真实 ops（state_change 含 from/to、decomposition 含 subtask_id）；(d) 最坏场景 = 5k 非终态（≤16 认领，MAX_ACTIVE_CLAIMS 上限，非「5k 活动」）。
- **审#P2-5 4b 触发与等价**：board 自定预算 <1s（记录制，PRD §6 无 board 目标行）；优化前后**同一 DB** board dict 全等（顺序/过滤/排序）才算口径不变，非「数字对比」。

## 原子任务

| # | 任务 | 验证 | 期望 |
|---|---|---|---|
| M1-3.1 | docs 裁决批（docs 先）：ADR 0006——(a) G10 维持写口径 + **审#P2-1 静默读意图内声明** + 连接级模型不引入（与 ADR 0003 一致）；(b) **审#P2-2 renew 触活例外语义**；(c) 归档=prune 强制导出文件（timestamped JSON 0600）；加密不做（单用户本地 + 0600 + 威胁模型 A 残余 G1 不可防）；(d) reconcile ACTIVE 闭合事件维持 ADR 0003 不实现。PRD：§3.2 activity 行澄清（写口径 + renew 例外）、§6 数据保留行改写（**审#P1-2 需求级原子窗口** + 命令名）、§1 C7 措辞对齐、§2 事件 kind 全集补 'renew'（**审#P2-3**）、§4.2 prune 命令行；known-gaps G9/G10 闭合标注 + PRD 状态行 | git ls-files tracked | 裁决入档 + 规格澄清 |
| M1-3.2 | renew 写事件：operations.renew 同事务 add_event(kind="renew", severity="info", title="lease renewed", actor_surface/conn, claim_id)；**审#P1-1** harness 期望：actor_surface=='cli'（人面）+ actor_conn 判别（'cli' vs 'rest:' 前缀）+ claim_id 关联；无认领 renew -> not_found 不写事件 | harness: REST renew + CLI renew -> detail events 含 kind='renew' + 归属判别 + claim_id | 谁续了租约可回溯（判据 3） |
| M1-3.3 | G9-a prune CLI：operations.prune_events(session, cutoff) 单事务按**审#P1-2 需求级原子谓词**删并返回删除数；CLI `prune`：--months N（默认 12，日历月）、--export-path（默认 ./exports/kanban-export-<ts>.json）、--yes；流程=全量导出（export_data json 无 LIMIT）-> 写文件（0600，mkdir）-> COUNT 将删（读）-> 确认门（**审#P2-6** EOF/拒绝 abort 不删非零退出；y/N；确认期间不持写事务）-> prune_events；导出失败中止 | harness: (i) 全窗外需求（SQL backdate 整需求 -400 天）整删；(ii) 跨窗需求（1 条 recent event）全留（链完整）；(iii) recent 需求留；(iv) 拒绝路径（stdin 'n'）与 EOF 路径不删；(v) 导出文件含全部需求 events（导出先行）+ 0600；(vi) 无 --export-path 默认文件生成 + CLI 打印路径 | 强制导出 + 需求级原子窗口 + 确认门 |
| M1-3.4 | G5 基准：tests/bench.py（独立脚本，不进 run_ac）——5k 需求库（直接 SQL 批量种子，**审#P2-4** 形状对齐：seq_counter 同步/payload 形状/ts 绑定参数/最坏=5k 非终态≤16 认领），测三面：view.summary 单需求（PRD 目标 <200ms）、add_record 写（<50ms）、board（混合 4900 终态+100 非终态 + 最坏 5k 非终态；**审#P2-5** board 自定预算 <1s 记录制）；结果记录 docs/ops/bench-results.md | `uv run python tests/bench.py` 跑通 + bench-results.md | 基准跑完 + G5 闭合 |
| M1-3.4b | （条件，仅当 bench 显示 board 超预算）board 批查询优化：claims/subtasks/milestones/events 分组查询 + Python 内存分组，逐需求调 _derived_signals/_milestone_row/_risk_rows；**审#P2-5** 等价断言 = 同一 DB 优化前后 board dict 全等；复测 bench | bench 前后 + dict 全等断言 | 口径不变 + 延迟下降 |
| M1-3.5 | harness 集成（tests/ac_cases_h.py + run_ac 注册）：M1-3.2/3.3 用例红绿留档（red-6 -> green-6）；回归既有（tier-1 全绿为基准数） | `uv run python tests/run_ac.py` 全绿 | 全绿 + 回归零 |
| M1-3.6 | docs：m1-3-verification.md（判据/红绿/prune 需求级原子窗口/bench 结果/盲区：bench 为测量非断言门、stdin 交互子进程覆盖、4b 条件批）；PRD §4.2 prune 命令行 + §6 数据保留行（M1-3.1 已改） | git ls-files tracked | 文档对齐 |

## oracle 纪律

- 断言逐字引自 PRD §3.2/§5.4/§6；renew 经 REST/CLI 真实调用；prune 真实子进程 CLI + SQL backdate（确定性禁 sleep）；bench 直接 SQL 种子（测量 harness）。
- 反证位：prune (i)-(vi) 六路径（含跨窗需求链完整 + 拒绝/EOF）；renew 归属两 channel 判别。
- 既有 284 不回归（tier-1 复验）。

## 验证入口与 tier

- tier-0: `uv run python -m compileall -q src cli.py`
- tier-1: `uv run python tests/run_ac.py` 全绿
- tier-2（合并门槛）: tier-1 全绿 + bench-results.md + m1-3-verification.md + git ls-files 全 tracked

## 不修清单

1. 不做加密导出（裁决见 M1-3.1）。
2. 不做 reconcile ACTIVE 闭合事件（维持 ADR 0003，时点观测自愈）。
3. 不做读计活动/连接级模型（G10 裁决：写口径 + awaiting_human 覆盖 + 静默读意图内）。
4. 不做退役/僵尸项目归档（PRD §6 退役行，M2+）。
5. prune 不删需求/认领/子任务/里程碑行（PRD 仅 events 窗口；需求行是板项）。
6. bench 不进 run_ac（5k 种子慢 + 环境依赖；独立脚本 + 记录）。

## 机械预检

- 登记位置 tracked: docs/plans/m1-3-plan.md、docs/adr/0006-m1-3-decisions.md、docs/ops/bench-results.md、docs/ops/m1-3-verification.md、tests/bench.py。
- oracle 版本: mcp 2.3.0 / httpx2 2.16.0 / fastapi 0.158.2 / sqlalchemy 2.1.6。
- 产物清单: src/agent_kanban/services/operations.py（renew 事件 + prune_events）、cli.py（prune 命令）、tests/ac_cases_h.py、tests/run_ac.py、tests/red-6.log/green-6.log、tests/bench.py、docs/adr/0006-m1-3-decisions.md、docs/ops/bench-results.md、docs/ops/m1-3-verification.md、docs/PRD.md（§1 C7/§2 kind 全集/§3.2/§4.2/§6）。

## 域外发现处置

执行/审查中一切非本批引入的问题 -> 回报单列 + 登记 + 主循环裁决，禁静默修。
