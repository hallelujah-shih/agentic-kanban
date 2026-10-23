# M1-3 验证记录（收尾批：G10 裁决 docs / renew 写事件 / G9-a prune CLI / G5 基准）

位置: docs/ops/m1-3-verification.md（tracked，m1-3 分支）
批次: M1-3（M1-3.1 docs 裁决 + M1-3.2 renew 写事件 + M1-3.3 prune CLI + M1-3.4 G5 基准 + M1-3.4b board 4b 优化 + M1-3.5 harness + M1-3.6 docs），全六门
规范锚: docs/PRD.md §3.2（activity 写口径 + renew 触活例外）/§4.2（prune 命令 + history_note 渲染）/§5.4（回溯链完整）/§6（数据保留终态需求级原子窗口 + 清理前导出 0600 + 性能目标）；docs/adr/0006-m1-3-decisions.md（G10/renew/prune 裁决）；docs/plans/m1-3-plan.md（本批次契约，审#P1-1/P1-2/P1-A + P2-1..7 + P2-A..I 折入）

## oracle 版本（机械预检）

- python 3.14.4（.venv）；sqlalchemy 2.1.6 / sqlite 3.50.4（IN() 上限 32766 参数，4b rids=5000 远低于）
- harness argv: `uv run python tests/run_ac.py`（工作目录 = worktree 根）
- tier-0: `uv run python -m compileall -q src cli.py tests`
- tier-2（合并门槛）: tier-1 全绿 + bench-results.md + m1-3-verification.md + git ls-files 全 tracked

## 判据（逐字引自 PRD，oracle 独立于实现）

- M1-3.2（renew，§3.2 写口径 + renew 触活例外，ADR 0006 决策 1）: 续租触活 -> 写 kind='renew' 事件（severity=info, title='lease renewed', claim_id 关联活跃认领）；actor_surface='cli'（人面语义）+ actor_conn 归属判别（CLI='cli' / REST='rest:' 前缀，两 channel 各自断言）；无认领/过期路径不写。
- M1-3.3（prune，§6 终态需求级原子窗口 + §4.2 命令 + §5.4 链完整）:
  - (i) 终态（DONE/REJECTED/CANCELLED，PRUNE_TERMINAL_STATES）且 MAX(ts) < cutoff（12 日历月，--months 默认 12，月末 clamp）-> 需求级整删（链永不半断，审#P1-A：终态且全窗才删，board 无假阴/假阳）；整删后 detail 零事件 + history_note 渲染（state!=OPEN，CLI 与 REST 双通道）。
  - (ii) 跨窗需求全留（链完整 + 决策事件 state_at_event=CLAIMED 非 OPEN 证明链重建正确 + decomposition_added 派生信号保留，审#P2-F 链完整断言钉死）；(iii) recent 需求全留。
  - (iv) 确认门：stdin 'n' / EOF -> 不删、非零退出、无 traceback（aborted: nothing deleted）；'y' -> 删除。确认期间不持写事务（审#P2-7）。
  - (v)+(vi) 导出先行：导出文件含全部需求 events（全量无 LIMIT 截断）+ 0600；默认 export-path ./exports/kanban-export-<ts>.json 生成（相对 cwd 解析）+ CLI 打印路径。
  - (vii) 僵尸需求（CLAIMED + 未结束认领 + 全窗外）不删 + abandoned 已解释不报 unexplained_abandonment。
  - (viii) `_months_ago` 月末 clamp（fake now 直接断言，不进真实 CLI）。
- M1-3.4（G5 基准，审#P2-4/P2-C/P2-D/P2-5）: 5000 需求库（形状对齐：payload 结构/ts 绑定参数/seq_counter 同步）；summary < 200 ms / add_record 写 < 50 ms（PRD §6）；board 自定预算 < 1 s（记录制）；审#P2-C 单库重序（最坏 board 5k 非终态 -> UPDATE 4900 DONE -> 混合 board）；4b 条件触发 + 审#P2-5 同一 DB 优化前后 board dict 全等。

## 结果（主循环复验 2026-10-23）

- tier-0: `compileall` 退出 0。
- tier-1: `uv run python tests/run_ac.py` -> **337/337 PASS**（284 既有零回归 + 53 新增）。
- 337 分解: 284 既有 = 279（m1-2.5 归档 green-full.log）+ 5（m1-2.7 P2-2 折入：board==summary 一致性扩至 5 需求 + risks 直接断言，m1-2.2 节断言 18->23）；53 = M1-3 新增（renew 12 / prune_i 7 / prune_ii 6 / prune_iv 7 / prune_v 11 / prune_vii 4 / months_ago 6）。
- G5: bench 数字与结论见 docs/ops/bench-results.md；4b 触发与优化前后对比见下节。

## G5 基准与 4b（M1-3.4 + M1-3.4b）

- 种子: 5000 需求（15016 events / 5002 subtasks / 16 active claims / 16 milestones），种子 3.4 s；最坏 = 5k 非终态（16 CLAIMED + 4984 OPEN）。
- 首跑（未优化实现）: summary median 3.7 ms（<200 ms 达标）；add_record 写 median 3.8 ms（<50 ms 达标）；**board 最坏 median 11542 ms（>1 s 预算 -> 触发 4b）**；board 混合 median 225 ms。
- 4b 优化（view.board）: claims/subtasks/milestones/events 按 rids `in_()` 批量查询 + Python defaultdict 内存分组；order_by 与逐需求查询相同（subtask ordinal / milestone created_at / event seq），逐需求相对顺序不变；DB 层 partial unique index `uq_claims_active_requirement`（requirement_id WHERE ended_at IS NULL）保证单活跃认领，dict 语义与旧 scalar() 等价。
- 等价断言（审#P2-5）: /tmp 一次性工具 board_equiv.py——确定性种子（2000 reqs 固定 uuid + 固定 now）+ 同一 DB（先旧实现 dump 683KB，后新实现同库重跑）；default 与 status=CLAIMED 两面 board dict `json.dumps(sort_keys=True)` **全等**（顺序/过滤/排序不变）。
- 复测（优化后）: board 最坏 median 11542 -> **538.7 ms（<1 s 达标）**；board 混合 225 -> **15.5 ms**；summary 3.7 ms / write 3.6 ms 保持达标；green-full-6.log 337/337 零回归。

## 红绿证据

| 阶段 | 红 | 绿 | 说明 |
|---|---|---|---|
| M1-3 harness | tests/red-6.log 15/26 | tests/green-6.log 53/53 | 同源同一 harness 结构；red 证明 oracle 能抓住缺实现：renew 事件缺失（[]）、prune 子命令缺失（rc=2 argparse usage）、months_ago 缺失（ImportError）、导出文件缺失；CLI 退出 0 / 导出 0600 等门断言全红，其余为前置/保真断言（renew 本体可用、无认领 not_found、前置 n=4 等） |
| 全量 | tests/red-6.log | tests/green-full-6.log 337/337 | tier-1 全量（284 既有零回归 + 53 新增） |

- 批内修正史（harness 侧 3 处，实现侧未动；harness 冻结于 red 后仅修正 harness 自身缺陷，红绿同源证据保留）:
  ① `_months_ago` 导入路径——site-packages 持有安装时旧 wheel 副本 cli.py（无该函数，red 时 ImportError），months_ago 用例改 `sys.path.insert(0, REPO_ROOT)` 从源码导入；
  ② prune_export (vi) 默认 export-path 断言——默认路径相对子进程 cwd 解析，harness 显式传临时 cwd（ak-prune-cwd-）再以 `Path(cwd)/export_path` 断言生成与打印；
  ③ renew_events 删除一个 trivially-true 断言（red 后自检发现不判别，按 oracle 纪律剔除）。

## 重跑规格

```
cd .worktree/m1-3
uv run python -m compileall -q src cli.py tests      # tier-0
uv run python tests/run_ac.py                        # tier-1（全 AC，需 ~5-6 分钟）
uv run python tests/bench.py                         # G5 基准（覆写 docs/ops/bench-results.md，~1 分钟）
```

- 确定性: 无 sleep 撞窗——prune 用 SQL backdate（`datetime('now', '-N days')`）把事件移到窗外/窗内，禁 sleep；renew/prune 均真实子进程（MCP stdio / CLI）调用；_months_ago 直接注入 fake now（不进真实 CLI 路径）。
- 隔离: 每次运行临时 DB 目录；CLI 子进程注入 stdin 文本（确认门 n/y/EOF）；默认 export-path 用例以临时 cwd 隔离，防污染 worktree。
- 4b 等价: /tmp/opencode/board_equiv.py（确定性种子 + 固定 now），前后 dump 对比 `json.dumps(sort_keys=True)` 全等；工具不入库（一次性证据，结果记入本文件）。

## Verdicts

- renew: CLI 与 REST 两 channel 均写 kind='renew' 事件（severity=info, title='lease renewed'），actor_surface='cli'（人面语义）+ actor_conn 判别（'cli' vs 'rest:' 前缀），claim_id 关联活跃认领；无认领 renew -> not_found 且不写事件。
- prune: 八路径全过——终态全窗外整删（链不半断）且 detail 零事件 + history_note（CLI/REST）；跨窗/recent 全留（state_at_event=CLAIMED 链重建正确 + decomposition_added 保留）；确认门 'n'/EOF 不删非零退出无 traceback、'y' 删；导出先行（全量 events + 0600）+ 默认 export-path 生成与打印；僵尸需求（非终态）不删。
- G5/4b: summary/write 达标 PRD §6；board 最坏 11542 ms 触发 4b，批查询优化后 538.7 ms 达标，同一 DB 优化前后 board dict 全等（口径不变）；green-full-6.log 337/337 零回归。

## 结果盲审 P2 折入（2026-10-23，verdict APPROVE）

- P2-2 CLI --months 校验: `--months < 1` 干净报错返回 1（非 traceback）；`_months_ago` 极端溢出（year 越界）catch ValueError 干净报错。
- P2-3 过期路径无 renew 事件断言: 负租约 env（AGENT_KANBAN_LEASE_SECONDS=-1）下 renew -> lease_expired 且 events 表无 kind='renew' 行。
- P2-4 导出失败 (ix) 用例: --export-path 指向目录 -> open 抛 IsADirectoryError -> 非零退出、不删（清理前必须导出）、stderr 含 export write failed、无 traceback。
- P2-5 stderr 断言: 确认门 'n'/EOF 路径断言 stderr 含 "aborted: nothing deleted"（判据原文）。
- P2-6 known-gaps G5 行闭合标注（2026-10-23，bench 落地）。
- P2-1/P2-7 证据措辞（不涉代码）: bench 数字以 docs/ops/bench-results.md 为准（commit message 为早期运行值，run-to-run 方差）；board 等价断言实际为「确定性种子重建的等同 DB」字节全等（一次性工具，未入库，已由盲审独立复核）。

## 盲区登记

1. **bench 为测量非断言门**（plan 明示）：bench-results.md 是记录制证据，不参与 run_ac 门禁；数字依赖本机环境（python/sqlalchemy/sqlite/磁盘），换机重跑可能漂移；4b 等价断言依赖 /tmp 一次性工具，结果已固化于本文件。
2. **stdin 交互子进程覆盖**：确认门经真实子进程注入 stdin 文本（'n'/'y'/EOF）断言，但 TTY 交互（信号中断、SIGINT 半途、管道关闭时序）无自动化，靠人工冒烟。
3. **浏览器 JS 渲染无自动化**（沿 m1-2 盲区 1）：Web 侧 history_note 渲染经 REST JSON 断言，浏览器实际渲染效果依赖人工冒烟。
4. **4b 条件批为一次性触发**：plan 的 4b 是条件步骤，本次已触发并落地；后续 board 再超预算属新问题，不在本批自动门内（bench 盲区 1 同源）。

## 不做清单（本批显式不做，见 docs/plans/m1-3-plan.md「不修清单」）

G9-b（导出/导入双 CLI）拆 M1-4（BCD）；导出文件加密（ADR 0006 裁决：强制导出不加密）；reconcile 行为变更（ADR 0006 裁决：ACTIVE 维持 ADR 0003）；连接级模型（ADR 0006 裁决：不引入）。

## 域外发现（单列，修复裁决归主循环）

本批无域外发现。批内修正史（harness 3 处）均属 harness 自身缺陷，非既有面问题；4b 等价断言与优化均为本批新代码验证。
