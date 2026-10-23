# M1-4 Plan — G9-b 重试成本超限判定（④ 业务规则变化，BCD 前置）

分支: `m1-4`（worktree `.worktree/m1-4/`，基 main @ 84f02e6）
档位: 全六门（④ 业务规则变化命中：新派生信号 retry_limit + 系统自动写 risk 事件；Phase 0.5 BCD 已产出并前置）
规范锚: PRD §3.2（不自动重试/累计重试超 2 次等你决策/实现注记）；docs/adr/0000-known-gaps.md G9-b；docs/adr/0003-m0-decisions.md「G9 登记」
BCD: docs/business-contracts/g9b-retry-limit.md（7 节齐；判定源 user 裁决 = 系统派生计数）
任务映射 BCD 节: §4 BDD 场景 -> harness 断言（S1 阈值/S2 未超/S3 跨子任务累计/边缘 1 幂等/边缘 2 首入+no-op/边缘 3 done 重开/跨时段 prune-reopen）；§5 Spec by Example 例 1-5 -> harness；§7 不变量 1-5 -> 实现约束（只标记不干预/来源 events 链/幂等/首入不计/需求级累计）

## 契约三锚

1. 规范逐字原文: PRD §3.2「不自动重试：重试对象是子任务（agent 侧），每次重试记录成本（token/时长），同一需求累计重试超 2 次进入"等你决策"清单（实现：系统判定超限后写一条 risk(severity=attention) 事件，入摘要"需要关注"区）」。BCD §1 解读 A+D（系统派生 + 需求级累计 + 严格超 2）+ user 裁决（2026-10-23 系统派生计数，幂等一次，成本留 agent note + SKILL 指引，不建 retry_cost 字段）。
2. 代码锚点: operations.py update_subtask（state_change 事件 payload={subtask_id, from, to}，无迁移守卫，SUBTASK_STATES 全集）；view.py _derived_signals（派生信号列表）+ summary/board 同源；models.py Event（kind/severity/payload/claim_id）。
3. 逐例期望: 子任务第 3 次重入 in_progress（首入除外）-> 同事务写 risk(attention) 事件（payload.retry_limit=true, count=3, actor_surface=system）+ needs_attention 含 retry_limit + risks 列表含该事件；2 次重试不触发；跨子任务累计；幂等（只写一次，信号保持）；首入与 no-op 不计；任何非 in_progress 重入都计（done 重开 + todo 退回再进，user 裁决）；里程碑 in_progress 不计；agent 伪造 marker 不抑制告警；跨 claim 周期累计延续。

## 影响面

- ④ 业务规则变化命中（新派生信号 + 系统自动事件）。BCD 前置完成（7 节齐，user 已裁决判定源）。
- ① 轻微：新事件 kind 复用既有 kind=risk（无新 kind），新派生信号类型 retry_limit（视图字段新增）。
- ② ③ 不命中。
单向门：BCD（user 裁决）+ PRD §3.2 已审规格；本 plan 审 + 结果盲审 + AC oracle 兜底。

## 关键设计决策（已钉）

- **计数来源 = events 链**（单一事件源，BCD §3 Policy 5 + §7 强不变量 2）：不建独立计数器表。判定只在 update_subtask 使子任务**重入 in_progress**（new=="in_progress" 且 old!="in_progress"）时评估。
- **计数谓词（subtask 作用域，审#P1-3）**：加载该需求 state_change 事件，只计 `payload.subtask_id` 非空且 `payload.milestone_id` 为空且 `to=="in_progress"` 且 `from!="in_progress"` 的重入；per-subtask 计 n 次重入，retries = sum(max(0, n-1))（首入除外）。里程碑 in_progress 迁移（payload.milestone_id）不污染计数。
- **重试范围（user 裁决，审#P1-2）**：**任何非 in_progress 状态重入 in_progress 都计**——含 done 重开、todo 退回再进、blocked/abandoned 再开工；首入除外；from==in_progress 的 no-op 不计。
- **幂等 + 反伪造（审#P1-1）**：retries >= 3 且无既有 marker -> 写一次；marker 事件 `actor_surface="system"`（先例 reconcile RECONCILE_SURFACE）；幂等谓词与信号谓词**同一** = `kind=risk AND severity>=attention AND payload.retry_limit=true AND actor_surface=system`。agent 经 add_record 伪造 marker（actor_surface=mcp）不抑制告警、不进信号。
- **风险事件**：kind="risk", severity="attention", title="累计重试超 2 次，需要人决策", payload={"retry_limit": true, "count": N}, actor_surface="system", actor_conn="system"（对齐 reconcile RECONCILE_CONN 先例，risks 列表可区分系统判定 vs agent 自报，P3-3）, claim_id=活跃认领。同事务。count = 触发时点快照（后续重试不更新，P2-1 记录制）。
- **派生信号**（BCD §2 What 2）：view._derived_signals 按统一谓词检查（含 actor_surface=system）-> append {"type": "retry_limit", "count": N}——入摘要需要关注区（PRD 逐字）+ board 徽标 + 详情（同源）。
- **只标记不干预**（BCD §7 强不变量 1）：不自动重试/释放/阻断，无状态迁移。
- **成本**（BCD §1 待澄清/§5 差异表）：不建 retry_cost 字段；SKILL.md 报告纪律补 agent 重试成本自报指引（note 报 token/时长）。
- **阈值钉死 2**（BCD §3 Policy 7）：常量，不配置化。

## 原子任务

| # | 任务 | 验证 | 期望 |
|---|---|---|---|
| M1-4.1 | docs（先于代码）：PRD §3.2 实现注记（判定源语义钉死：系统派生/需求级累计/严格超 2/幂等/成本留 agent note）+ spec 元数据追加 BCD 路径（docs/business-contracts/g9b-retry-limit.md）；known-gaps G9-b 行闭合标注；SKILL.md 认领纪律补重试成本自报指引（重试时 note 报 token/时长，让人看到重试代价） | git ls-files tracked | 规格先行 + BCD 引用 |
| M1-4.2 | 实现：operations.update_subtask 重入 in_progress 计数（_count_retries(events) helper，subtask 作用域谓词）+ 幂等写 risk 事件（_maybe_write_retry_limit，同事务，marker actor_surface=system/actor_conn=system，幂等/信号谓词同一且提取单一谓词常量 RETRY_LIMIT_EVENT 匹配器两处共用，P3-4 纵深防御）；view._derived_signals 加 retry_limit 信号（同一谓词常量，同源 summary/board） | tier-0 + harness 绿 | 判定/幂等/信号正确 |
| M1-4.3 | harness（tests/ac_cases_i.py + run_ac 注册）：BCD §4/§5 全场景——S1 阈值触发（第 3 次重入 -> risk 事件 + needs_attention retry_limit + risks 列表）；S2 2 次重试不触发；S3 跨子任务累计（A 1 + B 2 = 3 -> B 第 2 次重入时触发）；边缘 1 幂等（触发后 3 次重入事件数保持 1 + 信号保持 + payload.count 仍 = 3 快照断言，P3-1）；边缘 2 首入与 no-op 不计；边缘 3 done 重开 + todo 退回再进各计重试；边缘 4 里程碑 in_progress 迁移**>= 3 次**不计（负例判别力：误计将达 retries>=3 触发，断言"无 risk 事件 + 无信号 + 事件数 0"，新 P2-1）；边缘 5 agent 伪造 marker（add_record kind=risk payload.retry_limit=true）不抑制告警（第 3 次重入仍写真实 system 事件）+ 伪造事件不进信号；例 5 跨 claim 周期累计延续（release 后重新 claim，周期 2 第 1 次重入时触发）；边缘 6 跨窗 prune 交互（backdate 重入长链全事件至 12 个月窗外 -> prune 不删活动需求（deleted=0）+ 事件链完整 -> 第 3 次重入触发且 count=3 跨窗链累计正确，审#结果盲审 P2-1）；board==summary 一致（retry_limit 同源）；事件归属（marker actor_surface=system + actor_conn=system + claim_id 关联）。红绿留档（red-7 -> green-7）；回归全绿 | `uv run python tests/run_ac.py` 全绿 | 全绿 + 回归零 |
| M1-4.4 | docs：m1-4-verification.md（判据/红绿/BCD 映射/盲区：阈值常量钉死无配置变更面、幂等二次告警为 M2 记录、reopen 极端计数归零为已知限制、count 为触发时点快照不随后续重试更新 P3-1） | git ls-files tracked | 文档对齐 |

## oracle 纪律

- 断言逐字引自 PRD §3.2 + BCD §4/§5/§7；真实 MCP 调用链（update_subtask 经 MCP stdio 客户端）；禁 mock/禁 sleep。
- 反证位：阈值边界（2 不触发 3 触发）、幂等（事件数钉死 1）、首入/no-op 不计、跨子任务与跨周期累计、board==summary 同源。
- 回归全绿（tier-1 为基准数，不预设）。

## 验证入口与 tier

- tier-0: `uv run python -m compileall -q src cli.py`
- tier-1: `uv run python tests/run_ac.py` 全绿
- tier-2（合并门槛）: tier-1 全绿 + m1-4-verification.md + git ls-files 全 tracked

## 不修清单

1. 不建 retry_cost 字段/计数器表（BCD §7 强不变量 2；成本留 note + SKILL 指引）。
2. 阈值不配置化（BCD §3 Policy 7 钉死常量 2；差异化阈值 = M2 业务决策，BCD §6 记录）。
3. 不做幂等后二次告警（BCD §1 待澄清 2 默认一次；M2 增强记录）。
4. 不做自动干预（只标记，BCD §7 强不变量 1）。
5. 不重置计数（跨 claim 周期/跨时段延续；reopen 极端归零为已知限制，M1-3 已文档化）。

## 机械预检

- 登记位置 tracked: docs/plans/m1-4-plan.md、docs/business-contracts/g9b-retry-limit.md、docs/ops/m1-4-verification.md、skills/agent-kanban/SKILL.md。
- oracle 版本: mcp 2.3.0 / httpx2 2.16.0 / fastapi 0.158.2 / sqlalchemy 2.1.6。
- 产物清单: src/agent_kanban/services/operations.py（计数 + 幂等写事件）、src/agent_kanban/services/view.py（retry_limit 信号）、tests/ac_cases_i.py、tests/run_ac.py、tests/red-7.log/green-7.log、docs/business-contracts/g9b-retry-limit.md、docs/ops/m1-4-verification.md、docs/PRD.md（§3.2 注记 + §1 BCD 元数据）、docs/adr/0000-known-gaps.md（G9-b 闭合）、skills/agent-kanban/SKILL.md（重试成本自报指引）。

## 域外发现处置

执行/审查中一切非本批引入的问题 -> 回报单列 + 登记 + 主循环裁决，禁静默修。
