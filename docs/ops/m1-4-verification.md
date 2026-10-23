# M1-4 验证记录（G9-b 重试成本超限判定，④ 业务规则变化，BCD 前置）

位置: docs/ops/m1-4-verification.md（tracked，m1-4 分支）
批次: M1-4（M1-4.1 docs + M1-4.3 harness 冻结红 + M1-4.2 实现 + M1-4.4 docs），全六门
规范锚: docs/PRD.md §3.2（不自动重试/累计重试超 2 次等你决策 + M1-4 实现注记）；docs/adr/0000-known-gaps.md G9-b；docs/adr/0003-m0-decisions.md「G9 登记」
BCD: docs/business-contracts/g9b-retry-limit.md（7 节齐，判定源 user 裁决 = 系统派生计数，审#P1-1..3/P2-1..4 折入）
计划: docs/plans/m1-4-plan.md（M1-4.1..4.4，P1-1..3 + P2-1 边缘 4 判别力 + P3-1..4 折入）

## oracle 版本（机械预检）

- python 3.14.4（.venv）；mcp 2.3.0 / httpx2 2.16.0 / fastapi 0.158.2 / sqlalchemy 2.1.6
- harness argv: `uv run python tests/run_ac.py`（工作目录 = worktree 根）；新用例经 `--only` 单跑
- tier-0: `uv run python -m compileall -q src cli.py tests`
- tier-2（合并门槛）: tier-1 全绿 + m1-4-verification.md + git ls-files 全 tracked

## 判据（逐字引自 PRD §3.2 + BCD §4/§5/§7，oracle 独立于实现）

- 判定源 = 系统从 `update_subtask` 状态迁移推导（PRD 实现注记/BCD §1 裁决：非 agent 显式登记，威胁模型 B 下 agent 自报不可审计）。
- 重试计数（BCD §3 Policy 3，审#P1-3）：subtask 作用域 state_change（payload.subtask_id 非空 + payload.milestone_id 空 + to==in_progress + from!=in_progress）；per-subtask n 次重入 -> max(0, n-1)（首入除外），sum 跨子任务；任何非 in_progress 重入都计（done 重开/todo 退回再进/blocked 再开工，user 裁决）；里程碑迁移不计。
- 触发（BCD §4 S1/S2 + §5 例 1/例 2，严格超 2）：累计重试 >= 3（第 3 次重入 in_progress）-> 同事务写 kind=risk severity=attention 事件，title=「累计重试超 2 次，需要人决策」，payload={retry_limit: true, count: N}（count=触发时点快照），marker actor_surface=system + actor_conn=system + claim_id=活跃认领。
- 幂等 + 反伪造（BCD §7 强不变量 3，审#P1-1/P3-4）：幂等/信号谓词同一 = kind=risk AND severity>=attention AND payload.retry_limit==true AND actor_surface==system（单一匹配器 `is_retry_limit_event` 两处共用）；同一需求只写一次；agent 经 add_record 伪造 marker（actor_surface=mcp）不抑制告警、不进信号。
- 只标记不干预（BCD §7 强不变量 1）：超限只写事件 + 信号，无状态迁移/无自动释放。
- 信号（BCD §2 What 2 + PRD §3.2「入摘要需要关注区」）：view._derived_signals 追加 `{"type": "retry_limit", "count": N}` 入 needs_attention（summary/board/详情同源）；risk 事件入 risks 列表（severity>=attention，PRD 5.3 口径）。

## 结果（主循环复验）

- tier-0: `compileall` 退出 0。
- tier-1: `uv run python tests/run_ac.py` -> **382/382 PASS**（345 既有零回归 + 37 新增）。
- 37 新增分解（tests/green-7.log）: retry_s1 8 / retry_s2 2 / retry_s3 2 / retry_edge1 4 / retry_edge2 3 / retry_edge3 2 / retry_edge4 3 / retry_edge5 6 / retry_ex5 3 / retry_board 4。

## 红绿证据

| 阶段 | 红 | 绿 | 说明 |
|---|---|---|---|
| M1-4 harness | tests/red-7.log 17/37（20 FAIL） | tests/green-7.log 37/37 | 同源同一 harness 结构；red 证明 oracle 能抓住缺实现：系统 marker 缺失（risk 事件空）、retry_limit 信号缺失、伪造不抑制缺失、跨周期累计缺失；S2/边缘 2/边缘 4 负例等前置与保真断言 red 时即 PASS |
| 全量 | tests/red-7.log | tests/green-full-7.log 382/382 | tier-1 全量（345 既有零回归 + 37 新增） |

- 批内修正史（harness 侧 3 处，实现侧修正 1 处；harness 冻结于 red 后仅修 harness 自身缺陷，red-green 同源）:
  ① 边缘 4 里程碑迁移序列数错（11 步含 6 次 in_progress，改 9 步恰 5 次，与「>= 5 次不计」一致）；
  ② evs[0] 在 red 失败时抛 IndexError 污染日志，改 `_first()` 安全访问；
  ③ s1 空 dict 取值 KeyError，改 `.get()`。
  ④ 实现侧：`_maybe_write_retry_limit(session, requirement_id, claim.id, now)` 位置实参撞关键字-only 签名抛 TypeError，改关键字实参（首次 green 复现定位，非 oracle 缺陷）。

## BCD 映射（S1-S3 / 边缘 1-5 / 例 5 判定）

- S1（阈值触发）: 第 3 次重入（重试 3）-> 1 条系统 marker（count=3、actor_surface=system、actor_conn=system、claim_id=活跃认领）+ 摘要 needs_attention 含 retry_limit(count=3) + risks 列表含该事件。通过。
- S2（未超限不触发）: 重试 2（第 3 次进入 in_progress）不写事件、无信号。通过。
- S3（跨子任务累计）: A 重入 1 + B 重入 2 = 需求级 3 -> B 第 2 次重入触发（例 2 语义）。通过。
- 边缘 1（幂等 + count 快照）: 触发后 3 次重入事件数保持 1 + 信号保持 + payload.count 仍 = 3（P3-1 记录制，不随后续重试更新）。通过。
- 边缘 2（首入 + no-op 不计）: 1 首入 + 2 no-op（in_progress->in_progress）重试 0，永不触发。通过。
- 边缘 3（done 重开 + todo 退回再进）: 两者各计一次（累计 2 未触发），第 3 次重入（done 重开路径）触发。通过。
- 边缘 4（里程碑不计，负例判别力）: 里程碑 in_progress 迁移 5 次（误计将达 retries 4 >= 3 触发）-> 无 risk 事件 + 无信号 + 里程碑事件已落库（非零判别）。通过。
- 边缘 5（agent 伪造 marker 反伪造）: add_record(kind=risk, severity=attention, payload.retry_limit=true, count=0) 伪造 marker -> 仅伪造时无 retry_limit 信号（伪造不进信号）；第 3 次重入仍写真实 system 事件（伪造不抑制告警，count=3）；伪造仍显示 risks 列表（_risk_rows 既有口径，severity>=attention）。通过。
- 例 5（跨 claim 周期累计延续）: 周期 1 重试 2（release）-> 周期 2 第 1 次重入触发（不重置），marker claim_id 关联周期 2 活跃认领。通过。
- board==summary 同源: board needs_attention == summary needs_attention（retry_limit 一致）+ attention_ids 含触发需求 + board risks == summary risks。通过。

## 重跑规格

```
cd .worktree/m1-4
uv run python -m compileall -q src cli.py tests      # tier-0
uv run python tests/run_ac.py                        # tier-1（全 AC，需 ~5-6 分钟）
```

- 确定性: 无 sleep——全部状态迁移经真实 MCP stdio 子进程调用；视图经真实 REST 子进程；DB 事后 sqlite3 直查（读数据非读实现代码）。
- 隔离: 每用例独立临时 DB 目录（new_db）；REST/MCP 各为独立子进程共享同库（WAL 并发读，跨进程可靠信号）。
- 红绿同源: red-7.log 与 green-7.log 来自同一 harness 结构（冻结 red 后仅修 harness 自身缺陷）。

## Verdicts

- 判定正确: 阈值边界（重试 2 不触发 / 第 3 次重入触发）逐字 PRD「严格超 2」；首入与 no-op 不计；done 重开 + todo 退回再进各计；里程碑迁移不计（subtask 作用域）；跨子任务与跨 claim 周期累计延续。
- 幂等 + 反伪造: 同一需求超限只写一次（事件数钉死 1）+ payload.count 触发时点快照（不随后续重试更新）；agent 伪造 marker（actor_surface=mcp）不抑制告警不进信号但显示 risks 列表。
- 归属: marker actor_surface=system + actor_conn=system + claim_id=活跃认领（对齐 reconcile 先例，risks 列表可区分系统判定 vs agent 自报）。
- 视图同源: retry_limit 信号入 needs_attention（摘要/看板/详情同一 _derived_signals + 同一谓词），board==summary 全口径一致 + risks 同源。
- 回归: green-full-7.log 382/382（345 既有零回归 + 37 新增）。

## 结果盲审 P2 折入（2026-10-23，verdict APPROVE-WITH-FIXES）

- P2-1 跨时段 prune-reopen harness 缺失（plan:7 任务映射承诺未兑现，M1-4.3 原子任务行漏列致 plan 内部不一致）：按审者修法选项 (a) 补用例——tests/ac_cases_i.py 新增 `retry_cross_window`（6 断言：backdate 生效（全事件早于窗口下限）-> prune rc=0 + deleted=0（活动需求非终态不被整删，M1-3 谓词）+ 事件链完整（before==after）-> 第 3 次重入触发且 payload.count=3（跨窗链累计：旧链 2 次 + 新 1 次）+ needs_attention retry_limit 信号 count=3）。判别力：若链被 prune 截断则新入为 n=1 不触发，count=3 断言必红——prune 谓词与计数的交互路径直接断言，非组合覆盖论证。plan M1-4.3 任务行补列边缘 6（消除内部不一致）。
- 盲审独立验证面（记录）：red 重跑（base src 解包 + 新 harness，17/37 逐断言 diff 与 red-7.log 一致）；全量绿重跑 382/382 序列一致；基线纯净（plan commits 仅 2 docs 文件，实现 diff 12 文件全在批内）；actor_surface 不可伪造面（全仓 system 面仅 reconcile + retry marker 两个服务端点）；计数公式六场景代码级推导（含 no-op 守卫、里程碑/需求级 state_change 无 subtask_id 不入谓词）。
- P3 簿记项（不阻塞，记录）：plan M1-4.2「单一谓词常量 RETRY_LIMIT_EVENT」实现为函数 `is_retry_limit_event`（意图满足，operations + view 两处消费）；plan 产物清单漏列新模块 src/agent_kanban/services/retry_limit.py（本节补记）；edge4 plan 写「>= 3 次」实际 5 次（满足且判别力更强，口径一致为 5）；「345 既有」基线溯源属 M1-3 侧留档习惯（green-full-6.log 337/337 为 m1-3.7 前快照，345 出自 m1-3.7 commit 消息），域外不影响本批。
- 折入后复验: tier-0 compileall 退出 0；tier-1 `uv run python tests/run_ac.py` -> 388/388（382 既有零回归 + 6 新增 retry_cross_window）。

## 盲区登记

1. **阈值常量钉死，无配置变更面**（BCD §3 Policy 7 / §4 配置变更时场景）: 阈值 2 为常量（RETRY_LIMIT_THRESHOLD=3），本批无配置项；若未来 M2 配置化，需单独评审「存量已触发 vs 新阈值」的再触发语义（BCD 已记录）。
2. **幂等后二次告警为 M2 增强**（BCD §1 待澄清 2 已裁决）: 人决策后 agent 继续重试不再二次告警（信号保持 + note 时间线承载决策上下文）；「人决策后又失控」静默属已知设计取舍，二次告警 = M2 记录不做。
3. **reopen 极端计数归零为已知限制**（BCD §6 失败原因 3 / §4 跨时段场景）: prune 只整删终态全窗外需求，活动需求链完整（主流路径无此问题）；曾终态整删后 reopen 的需求计数从零开始，归档文件为权威（M1-3 裁决语义）。
4. **count 为触发时点快照**（P3-1）: 触发后继续重试不更新 count 与信号；需要「当前累计数」的读者应查事件链推导（单一事件源可重建），非读 marker。
5. **浏览器 JS 无自动化**（沿 m1-2/m1-3 盲区 1）: retry_limit 信号的 Web 渲染（看板徽标/详情区）经 REST JSON（board/summary）断言，浏览器实际 JS 渲染效果依赖人工冒烟。

## 不做清单（本批显式不做，见 docs/plans/m1-4-plan.md「不修清单」）

retry_cost 字段/独立计数器表（BCD §7 强不变量 2，成本留 agent note + SKILL 指引）；阈值配置化（差异阈值 = M2 业务决策，BCD §6 记录）；幂等后二次告警（M2 增强）；自动干预（只标记，BCD §7 强不变量 1）；计数重置（跨 claim 周期/跨时段延续；reopen 极端归零为已知限制）。

## 域外发现（单列，修复裁决归主循环）

本批无域外发现。批内修正史（harness 3 处 + 实现 1 处签名实参）均属本批新代码自身的缺陷，非既有面问题；其中实现侧 TypeError 为首次 green 复现定位（red 阶段该断言同样红，判定面未被遮蔽）。
