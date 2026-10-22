# M0 验证记录（M0-1 + M0-2）

位置: docs/ops/m0-verification.md（tracked，m0 分支）
批次: M0 全量（M0-1 基础+人面 REST+视图+导出+派生偏离；M0-2 reconcile+AC10+裁决登记），全六门
规范锚: docs/PRD.md v3.2 §3/§4/§5/§6/§8/§9；docs/plans/m0-plan.md（本批次契约，M0-1/M0-2 两子批）

## oracle 版本（机械预检）

- python 3.14.4（.venv）；fastapi 0.158.2；alembic 1.20.0；uvicorn；sqlalchemy 2.1.6；aiosqlite 0.22.1；mcp 2.3.0
- harness argv: `uv run python tests/run_ac.py`（工作目录 = worktree 根）
- tier-0: `uv run python -m compileall -q src cli.py`

## 判据（逐字引自 PRD §9/§4.3/§5.3/§3.2，oracle 独立于实现）

M0 AC 判据表全文见 docs/plans/m0-plan.md「AC 判据表 / REST 错误映射表」。覆盖：AC10（反黑箱判别力，审#2 五断言钉死）、AC11（覆盖缺口 + 反向断言）、AC12（派生偏离，blocked/abandoned/里程碑延误/拆解新增，无需 deviation 登记）、AC13（反淹没，AC13 禁止面 = 不含 progress_note content 全文/事件长 content/run_logs）、AC15（回溯 5 判据 + export 完整含 events 全文）、AC17（request_review 证据强制复验）+ Spike AC1-9/16 + 9 码矩阵 + 补充断言（marker 覆盖/自评持久化/links_to 删除保护）+ P1/P2 盲审断言（id 归一/payload 8KB/拆解新增口径）。

## 结果（主循环复验 2026-10-22）

- tier-0: `compileall` 退出 0。
- tier-1: `uv run python tests/run_ac.py` -> **203/203 PASS**（M0-1 最终 184 + M0-2 新增 AC10 7 断言 + reconcile 12 断言）。
- 关键对抗变体均绿：AC1 并发 10 真实多进程 MCP + SIGKILL 崩溃原子性；AC6 释放+写竞争（seq 主 oracle）；AC8 第 17 认领；AC2/9 租约 env 加速；AC10 四合一判别力场景（压级风险+窄化验收+虚假覆盖+未登记放弃+决策备选）；readlock 读锁竞争（REST lifespan 对账在锁竞争下 no-op 不抢写锁）；reconcile ORPHANED/等待中优先/drift 双场景；REST 逐端点 + 逐码错误映射；payload 8KB 写时强制。

## 基线

- M0-1 commit: 0345efb（alembic 基建）、472392f（config/读锁拆分）、b56dd3d（REST+view+HTML）、fd304a4（CLI 扩展）、015eef1（AC harness）、f02df97（盲审修复 P1-1/P2-1/P2-3）。
- M0-2 commit: 本批逻辑分段提交（reconcile service / AC10+reconcile harness / ADR 0003+G9+G10 / 验证文档），commit 清单见合入说明。

## 红绿证据

| 阶段 | 红 | 绿 | 说明 |
|---|---|---|---|
| M0-1 首发 | tests/red-1.log 0/10（空实现 stub 全红） | tests/green-1.log 160/160 | 视图/REST/CLI M0 首批断言 |
| M0-1 盲审修复 | tests/red-2.log 5/21（修复未落时针对 P1-1/P2-1/P2-3 定向红） | tests/green-2.log 184/184 | id 归一全链闭合、note/update_progress 8KB、拆解新增口径 |
| M0-2 新增 | tests/red-3.log 8/9（reconcile 命令缺失 -> 对账断言全红；AC10 验证 M0-1 判别力结构 7 断言即绿） | tests/green-3.log 19/19 | AC10 7 断言 + reconcile 12 断言 |

- 每 AC 断言逐字引自 PRD，未读实现私有成员；AC10 断言基于渲染输出（summary dict / CLI 文本）；reconcile 断言基于 reconcile 事件与报告（直查 events 表）；并发场景真实多进程，未 mock。

## 重跑规格

```
cd .worktree/m0
uv run python -m compileall -q src cli.py          # tier-0
uv run python tests/run_ac.py                      # tier-1（全 AC，需 ~3-4 分钟）
```

- 确定性: 租约/过期/空闲经 env 覆盖（AGENT_KANBAN_LEASE_SECONDS / AGENT_KANBAN_IDLE_SECONDS / AGENT_KANBAN_BUSY_TIMEOUT_MS）；reconcile 失活场景经 harness 直改 DB `last_activity_at`（datetime('now','-40 minutes')）确定性加速，禁 sleep 撞窗。
- 隔离: 每次运行临时 DB 目录，互不污染；REST 真实子进程 uvicorn + urllib（禁 TestClient，父进程 _Runtime 单例共享破坏隔离）。

## Verdicts

- AC10 五断言逐条（审#2 钉死）：① 摘要对照表粗锚 X（a1）下显示窄验收项 Y 文本及状态（`linked[].item` 精确匹配 + `state=met`，非仅映射存在）；② 反向断言：虚假覆盖锚 X `uncovered=False`（排除靠缺口高亮作答）；③ 需要关注区有 `abandoned_subtask` 派生信号（未登记 deviation 仍出现）；④ decision 含 `alternatives` 文本（方案 B/C 可见）；⑤ risk severity=info 不在决策/风险/偏离列表（压级不可见但 ③④ 信号足够作答）。
- reconcile：连接失活（last_activity 旧、租约未过、无等待标记）-> ORPHANED 事件+报告；awaiting_human 存在 -> waiting（优先于 ORPHANED）；claim 无 CLAIMED -> drift(claim_without_claimed)，BLOCKED 有 claim 合法不报；CLAIMED 无 claim -> drift(claimed_without_claim)；ACTIVE 不写事件；MCP 启动不触发（审#10）；ORPHANED/drift 入摘要需要关注区（REST lifespan 触发，视图时点再校验自愈）。

## 不做清单（本批显式不做，见 docs/plans/m0-plan.md「不修清单」）

Web 窗口（M1）、Jira 导入/回写（M1）、G3 痛点基线采集（M1 硬前置）、G5 性能基准（M1）、MCP HTTP（M1 默认不做）、数据保留清理命令（G9，M1）、重试成本超限判定（G9，M1）、多用户/RBAC/外网部署（全局不做）、导出文件归档/加密（M1 定）。

## 域外发现（单列，修复裁决归主循环）

1. **UUID 格式不对称（M0-1，已修复，m0-1.8 P1-1）**：`Uuid(as_uuid=False)` 读回 36-char 带连字符，写路径内存实例/响应为 32-hex -> 响应边界不对称（list_tasks/get_task_detail/list_awaiting/release/view.detail events 混 36-char）。修复：抽共享 `ids.norm_id`（原 view._nid），应用于全部响应边界；写路径与事件 payload 引用不动（payload 与响应 join 需字符串一致）。断言 p1_ids 留档 red-2 -> green-2。
2. **activity 口径偏差（M0-1，登记 G10）**：PRD 3.2「agent 面任何写操作 + MCP 调用」计活动 vs 实现仅写操作 touch_activity（读工具不更新 last_activity_at）。读计活动需连接级模型（连接建立/存活判定），M1 定；本批以写口径 + reconcile 显式化（ORPHANED/SUSPECT 同源）覆盖观测需求。登记 docs/adr/0003-m0-decisions.md「G10 登记」。
3. **结果盲审 REJECT -> 修复闭环（M0-1）**：M0-1 结果盲审 REJECT（P1-1 id 归一、P2-1 note/update_progress 8KB 漏强制、P2-3 拆解新增误计 add_milestone）-> m0-1.8 修复 + 定向红绿留档（red-2 5/21 -> green-2 184/184）后全量复验。
4. **reconcile 事件无 ACTIVE 闭合记录（M0-2，待裁决）**：reconcile 只写非 active finding 事件；ORPHANED 认领恢复活动后无对应「active」闭合事件，原始事件流的对账状态停留在 ORPHANED（视图层以时点再校验自愈，显示正确）。裁决：M1 是否加信号转移闭合事件（事件流审计连续性 vs 噪音）。
5. **reconcile 两段式设计（M0-2，实现说明）**：REST lifespan 对账为「读扫描（WAL 快照）+ 仅在有非 active finding/drift 时才开写事务」，避免 no-op 对账在锁竞争下以 BEGIN IMMEDIATE 拖垮启动（readlock AC 保绿）；有 finding 时写事务在锁竞争下会 db_busy -> REST 启动失败（fail-fast，与安全启动检查同策略）。
