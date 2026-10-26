# M1-5 验证记录（task 生命周期操作 create/archive/delete + 看板定位重述，④ 业务规则变化 + ① 外部接口面 + ② 新破坏性端点，BCD 前置）

位置: docs/ops/m1-5-verification.md（tracked，task-lifecycle 分支）
批次: M1-5（T1 ARCHIVED 状态值/终态常量 + T2 archive + T3 delete + T4 Web 壳 + T5 文档同步），全六门
规范锚: docs/superpowers/specs/2026-10-26-task-lifecycle-positioning-design.md（13 节，对抗审查 12 条全折入）；docs/PRD.md §0/§3.1/§3.4/§4.2/§6（本批修订后）；docs/adr/0000-known-gaps.md R1/R3/R4/G12
BCD: docs/business-contracts/task-lifecycle-positioning.md（7 节齐，user 裁决 Q1=A / Q2=方案 1 / Q3=from=None 沿用 REJECTED 先例；S1/S5 修订记录在案）
计划: docs/superpowers/plans/2026-10-26-task-lifecycle.md（T1-T5，计划盲审 APPROVE-WITH-FIXES 4 P2 + 7 勘误 + BCD S1 陈旧子句全折入，b75a60e；P1 扩展字段：影响面/五元组映射/验证入口）

## oracle 版本（机械预检）

- python 3.14.4（.venv）；mcp 2.3.0 / httpx2 2.16.0 / fastapi 0.158.2 / sqlalchemy 2.1.6 / uvicorn 0.54.0
- harness argv: `uv run python tests/run_ac.py`（工作目录 = worktree 根）；新用例 k_state / k_archive / k_delete / k_web 经 `--only` 单跑
- tier-0: `uv run python -m compileall -q src cli.py tests`
- tier-1: 全量 run_ac.py；tier-2（合并门槛）: tier-1 全绿 + 本文档 + git ls-files 全 tracked
- 基线: main 8767385（worktree 切出点）首跑全量 416/416 PASS（baseline-full.log）

## 判据（逐字引自 spec + BCD，oracle 独立于实现）

- 终态单一事实源（spec §5/§8，I7）: `operations_util.TERMINAL_STATES = ("DONE","REJECTED","CANCELLED","ARCHIVED")`；board / list_tasks / GET /requirements 三默认列表与 prune 窗口集合统一引用该常量（审 P1-1 单点收敛）。
- archive 语义（spec §4.2，BCD P1/P2 + 隐含 B，S2/S3）: 任意状态（含终态）可达，无 unarchive；claim 同事务结束（ended_at + release_reason="archive"）；awaiting_human 清除（可见面）；事件形态 = Q3 裁决 REJECTED 先例（state_change，title "? -> ARCHIVED"，payload {"from": None, "to": "ARCHIVED"}，claim_id = 活跃认领 id）；finished_at = archive 事件 ts。
- delete 语义（spec §4.3/§4.4，BCD P3/P4，S4/S6）: 单事务五表硬删，FK 序 events -> subtasks -> milestones -> claims -> requirement，不写事件；任意状态；仅人面（MCP 面无工具，I4）；CLI 确认门（展示 title/state/事件数 + 导出建议，y/N，EOF/拒绝中止不删非零退出 "aborted: nothing deleted"，--yes 跳过，确认期不持写事务）；REST 200 / 404 not_found / 503 db_busy。
- create 语义（spec §4.1，S1/E1）: 不写事件；acceptance 一行一条 -> normalize_anchors 自动编号 a1/a2；Jira 链接 -> source=jira + source_ref；创建后前端主动重拉（create 不写事件，无 SSE 触发器，审 P1-2）。
- 人面收窄（spec §6，I3/I4）: Web 壳移除全部决策操作（approve/release/renew/reopen/abandon/note/set_expectations）；REST/CLI 决策端点语义零改动；C6 保持（approve 函数零改动，DONE 仅人面）。
- 定位重述（spec §1）: "AI 与人对称交换关键信息的场所 + 关键决策的记录点/审计点"落 PRD §0 / README / design.md §0 / web.md / skills/agent-kanban/SKILL.md / 包 docstring 六处；旧措辞"记录面 + 协作窗口"全仓清零（BCD §1 客户原话解读选项 B 为正当历史引用）。

## 结果（主循环复验）

- tier-0: compileall 退出 0。
- tier-1: `uv run python tests/run_ac.py` -> **509/509 PASS**（416 既有零回归 + 93 新增）。
- 93 新增分解: k_state 14 / k_archive 42 / k_delete 16 / k_web 21（计数链 416 -> 430 -> 472 -> 488 -> 509 与各 green/full 日志结果行一致）。
- P5 复验: 全量重跑 509/509（p5-full-rerun.log，TMPDIR 重定向，见重跑规格）。

## 红绿证据

| 阶段 | 红 | 绿 | 说明 |
|---|---|---|---|
| T1 | t1-red 4 条预期 FAIL（i 三默认列表 + iv prune 出窗整删；ii/iii 前置 PASS） | t1-green 14/14，t1-full 430/430 | 红 = 三处默认过滤缺失 + prune 集合漏 ARCHIVED |
| T2 | t2-red（CLI archive 子命令不存在 rc=2） | t2-green 42/42，t2-full 472/472 | 首跑 41/42 中断：BLOCKED 裸 DB 锚 vs JSON 列 "null" 文本存储（none_as_null=False，main 既有形态，approve/abandon 同形）-> 裁决改双空锚 in (None, "null")（b8b09f5），业务契约"无存活 marker"不变；域外发现 = G12（list_awaiting 过滤层泄漏，主循环活体复验坐实，登记 known-gaps） |
| T3 | t3-red（CLI delete 子命令不存在 argparse invalid choice） | t3-green 16/16，t3-full 488/488 | 五表零残留/404+not_found/确认门四路径/写锁 503 全钉 |
| T4 | t4-red 15 FAIL（14 壳断言 + AC1 401）-> 裁决补 token（fd65013，零断言变更）-> t4-red2 14 壳断言 FAIL + AC1 三前置 PASS | t4-green 21/21，t4-full 509/509 | 401 = 计划测试代码缺陷（REST token 中间件全路径强制），非产品面；既有 web 壳契约用例零回归 |
| T5 | 无新测试（文档同步 + prune 文案，无字面断言，已核实） | t5-full 509/509（prune_confirm 9 断言绿） | 文档锚点逐字对照计划 |

- 日志位置: /tmp/opencode/m1-5/logs/（工作产物不入库：baseline-full / t1-red / t1-green / t1-full / t2-red / t2-green / t2-full / t3-red / t3-green / t3-full / t4-red / t4-red2 / t4-green / t4-full / t5-full / p5-full-rerun 共 16 份；关键行与计数已记入本表）。
- 批内裁决史（3 次计划级，均带活体探针/复验证据，裁决先落计划后实现，零断言弱化）: T2 双空锚（b8b09f5）/ T4 测试 token（fd65013）/ T5 Files 清单漏列两文件 -> 主循环补漏（d673029）。

## BCD 映射（S1-S8 / I1-I7 逐场景）

- S1（create）: k_web AC1 数据路径（201 OPEN + a1/a2 锚编号 + jira source 映射）+ 壳表单锚在场；JS 交互（提交->主动 loadBoard）= 手测（盲区 1）。
- S2（archive 活跃任务）: k_archive 七状态矩阵 OPEN/CLAIMED/BLOCKED/REOPEN 行（state=ARCHIVED + 三默认列表排除 + claim ended/release_reason=archive + 事件形态 from=None/"? -> ARCHIVED"/claim_id/actor 归属 cli 与 rest:* 双 channel）+ (iii) archive 后 agent 写 no_active_claim 端到端。
- S3（archive 终态任务）: k_archive DONE/REJECTED/CANCELLED 行（含终态再归档允许，P1 幂等口径）。
- S4（delete happy）: k_delete(i) CLI --yes 五表扫描零残留（含需求行）+ (ii) REST 200 -> 404。
- S5（archive 带 marker）: k_archive BLOCKED 行无存活 marker（双空锚）；list_awaiting 过滤层 = G12 既有缺陷，本批 pin 可见面（BCD S5 修订记录在案）。
- S6（并发 delete）: k_delete(v) 写锁竞争 503 db_busy + 竞争失败未删（不半删）。
- S7（prune 覆盖）: k_state(iv) 三任务场景（ARCHIVED 出窗 events 整删 + 需求行保留 + 未出窗保留 + 非终态保留）。
- S8（agent 面感知）: k_delete(iii) MCP 读 not_found + agent 写 not_found（非半删数据的错误）。
- I1（C6）: approve 函数零改动 + 既有套件（agent 置 DONE 路径 illegal_state 等）416 条零回归。
- I2（事件链永不半断）: delete 整需求五表同事务 + prune 语义零改动（k_state(iv) 需求行保留断言）。
- I3（archive/abandon 语义区分）: archive 事件形态断言（from=None/to=ARCHIVED/release_reason=archive）与 abandon 事件（-> REJECTED/CANCELLED）结构可区分。
- I4（仅人面）: MCP 12 工具零改动（既有 ac3 精确集断言回归）+ Web 决策标记 9 处缺席（k_web）+ mcp/server.py 本批零 diff。
- I5（单事务原子）: k_delete(i) FK 序零残留 + (v) 写锁竞争不半删；崩溃面（事务中进程崩溃）无直接测试 = SQLite 单事务机制保证（P4 重推确认，盲区 4）。
- I6（ARCHIVED 不可认领/不可写）: k_state(ii) claim illegal_state 且 claim 行零残留（事务回滚钉）+ k_archive(iii) no_active_claim。
- I7（保留分工）: k_state(iv) prune 覆盖 ARCHIVED + 非终态不受 prune + T5 prune 确认文案补 ARCHIVED。

## 重跑规格

```
cd /home/shih/test/AgenticKanban/.worktree/task-lifecycle
uv run python -m compileall -q src cli.py tests    # tier-0
uv run python tests/run_ac.py                      # tier-1（全 AC，需 ~5-6 分钟）
```

- 环境约束: 全量回归对 /tmp tmpfs usrquota 敏感（T5 首跑实测 EDQUOT 中断，dd 100MB 仅落 717KB 坐实配额满）；配额不足时以 `TMPDIR=/home/shih/.tmp-ak-m15 uv run python tests/run_ac.py` 执行（T5 先例；P4 裁决核验：new_db 走 tempfile.mkdtemp 跟随 TMPDIR，无硬编码 /tmp 路径、无路径断言，TMPDIR 不改变任何断言语义）。
- 确定性: 无 sleep——状态迁移经真实 MCP stdio 子进程，视图经真实 REST 子进程，写锁竞争 = 持锁方全程持锁（非撞窗），backdate 用 SQL 直写；DB 事后 sqlite3 直查。
- 隔离: 每用例独立临时 DB（new_db）；红绿同源（冻结红后仅修 harness/计划自身缺陷）。

## Verdicts

- 终态单一事实源: 三默认列表 + prune 统一引用 operations_util.TERMINAL_STATES（审 P1-1 单点收敛，防三处漂移）。
- archive: 七状态矩阵全通（含终态再归档）；claim 同事务结束 release_reason=archive + marker 可见面清除；事件形态逐字 Q3 裁决；finished_at=archive 事件 ts；无 unarchive（k_state(iii) approve/reopen on ARCHIVED -> illegal_state）。
- delete: 五表零残留含需求行（与 prune"删事件留需求行"语义区分钉死）；agent 面 not_found；确认门 fail-closed（仅 y/Y 继续，EOF/非 y 中止不删非零退出）；写锁竞争 503 且不半删。
- Web 壳: 决策操作 9 标记缺席 + 生命周期操作在场 + 壳契约（board-root/EventSource/零原始输出）保持 + AC1 数据路径钉。
- 回归: 416 既有零回归（509/509）；MCP 12 工具零改动；approve/release/renew/reopen/abandon/note/set_expectations REST/CLI 语义零改动。
- 文档: 新定位措辞六处落位一致，旧措辞全仓清零（正当历史引用例外在 BCD §1）。

## 结果盲审（2026-10-26，两段式，verdict APPROVE）

- 阶段一（盲，diff+契约+产物目录+陷阱库，无 report 注入）: 0 P0 / 0 P1 / 0 P2。断言力重推逐用例点名（最弱断言 k_web 无独立、k_state /board?status=ARCHIVED 仅值卫生；archive 按钮 disabled 三元式未锚——服务端允许幂等再归档，行为后果为零，计划已划手测面，均不占问题位）；非目标零偷渡；威胁模型各面有钉（token 中间件 app 级全路径 / MCP 面无 delete / 确认门 fail-closed / 503 映射）；红证据 15 份模式自洽无"复跑变绿"结案；计数链自洽；既有断言零改动。
- 阶段二（对账，释放全部 report）: 零矛盾。T5 三偏差均核实为忠实执行/环境处置（backtick 保留 = 计划排版限制的忠实处理；EDQUOT 残片不掩盖问题，t5-full.log 完整性实证；TMPDIR 不改变语义）。
- 审者合入前待办: ① 本文档（已落）；② user 浏览器冒烟（web.md checklist 第 4/5 条）。

## 盲区登记

1. **浏览器 JS 无自动化**（沿 m1-4 盲区 5）: 表单提交 -> 主动 loadBoard 重拉、delete 标题不匹配拒绝、tab 切换、404 友好文案——壳字符串层有锚（k_web），JS 行为 = web.md 冒烟 checklist 第 4/5 条手测。
2. **G12（既有缺陷，非 M1-5 引入）**: list_awaiting 谓词 `IS NOT NULL`（operations.py 登记时点 :918）匹配 JSON 列 "null" 文本，清 marker 后任务仍出现于 list_awaiting（awaiting_human=null）；approve/abandon/archive on BLOCKED 全路径同形；detail/board 可见面不受影响（反序列化归一 None）。修复选项未裁决，单独立项（known-gaps G12，含复现命令）。
3. **R1 / R3 / R4 残余**（known-gaps 登记）: agent harness 对 delete 后 not_found 的处理在本仓之外 / archive-abandon 语义区分靠使用纪律 / 决策操作移 CLI 后 awaiting 堆积风险。
4. **delete 崩溃面原子性无直接测试**: 机制保证 = SQLite 单事务（BEGIN IMMEDIATE + 单 commit）；P4 重推确认无缺口。
5. **再归档幂等允许（P1）+ create 不写事件（隐含 C）**: CLI/REST 层已钉；Web archive 按钮 disabled 仅视觉提示（服务端允许再归档，无行为契约依赖该禁用）。

## 不做清单（spec §2 非目标，本批显式不做）

无 unarchive；无 subtask 人面编辑；无新事件 kind；MCP 12 工具零改动；无回收站；REST 层无交互确认（G1 残余，人面可信 surface）；G12 不修（单独立项）；Jira 自动导入/回写不做（ADR 0004 裁决保持）。

## 域外发现（单列，修复裁决归主循环/user）

1. **G12** list_awaiting "null" 文本泄漏——T2 实现者发现，主循环活体复验坐实（approve on BLOCKED 既有路径后任务仍在 list_awaiting、字段 null），登记 known-gaps，修复单独立项归 user 裁决（选项: ① JSON(none_as_null=True) + 存量行迁移；② 谓词补 isnot("null")）。
2. **环境（非产品）**: /tmp tmpfs usrquota 接近满 + RAM 30G 已用 20G + swap 14/15G——T5 首跑全量 EDQUOT 中断，处置 = 清理 52 个陈旧 harness 临时库（~93MB）+ TMPDIR 重定向重跑（P4 对账确认无产品面后果，重跑规格已记环境约束）。

## 流程审计（六门）

- G1 worktree 隔离: .worktree/task-lifecycle（base main 8767385），开工时干净。
- G2 计划盲审: 独立 subagent APPROVE-WITH-FIXES（0 P0/0 P1/4 P2 + 7 勘误 + BCD S1 陈旧子句），全部折入（b75a60e）不复审。
- G3 SDD 派发: T1-T5 同仓串行，TDD 红绿同源，红证据 16 份在位；3 次中断/缺陷裁决（T2 断言锚 / T4 测试 token / T5 Files 清单漏列）均带探针证据、裁决先落计划后实现。
- G4 结果盲审: 两段式 APPROVE + 对账零矛盾。
- G5 全绿复验: 509/509（P5 独立重跑，TMPDIR 重定向）+ tier-0 退出 0。
- G6 流程事故记录: ① 主循环 `git add -A` 扫入 subagent 未提交的 T2 代码（混合 commit db8fc15，含旧红断言）-> reset --mixed 后计划单独成 commit b8b09f5（教训: subagent 中断留未提交改动时主循环禁 `git add -A`，只 add 明确文件）；② provider 回报生成阶段 3 次 "content after finish reason"（工作产物均完整，以现场状态验收，不重派）；③ T5 首跑环境 EDQUOT 中断（非产品，重跑规格已记）。
- 主循环 ledger: /tmp/opencode/m1-5-ledger.md（工作产物不入库，门序/派发/裁决/事故全记录）。
