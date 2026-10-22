# Spike 验证记录（T2.1-T2.9）

位置: docs/ops/spike-verification.md（tracked，spike 分支）
批次: Spike 骨架实现（AC1-9/16 + 9 码矩阵 + 补充断言），全六门
规范锚: docs/PRD.md v3.2 §2/§3/§4/§7.3/§9；docs/plans/spike-plan.md（本批次契约）

## oracle 版本（机械预检）

- python 3.14.4（.venv）；sqlalchemy 2.1.6；aiosqlite 0.22.1；mcp 2.3.0；pydantic 2.14.1；uv 0.11.12
- harness argv: `uv run python tests/run_ac.py`（工作目录 = worktree 根）
- tier-0: `uv run python -m compileall -q src cli.py`

## 判据（逐字引自 PRD §9/§4.3/§2，oracle 独立于实现）

AC1-9/16 + 9 码矩阵（db_busy / not_found / illegal_state / no_active_claim / lease_expired / duplicate_subtask / invalid_record / queue_full / already_claimed）+ awaiting_human 补充断言（approve/release 清 marker 同事务、mark_blocked 覆盖旧 marker、验收自评持久化 subtasks.acceptance[].state）。判据表全文见 docs/plans/spike-plan.md「AC 判据表 / 9 码触发矩阵 / awaiting_human 与自评补充断言」。

## 结果（主循环复验 2026-10-22）

- tier-0: compileall 退出 0。
- tier-1: `uv run python tests/run_ac.py` -> 66/66 PASS（主循环复验一致；sub agent 连续 4 轮复验稳定）。
- 关键对抗变体均绿：AC1 并发 10 真实多进程 MCP 客户端（1 成功 9 already_claimed）+ SIGKILL 崩溃原子性（重开直查 DB：无 ended_at IS NULL 孤儿、claim-state 全局一致）；AC6 释放+3 写进程竞争（seq 提交序主 oracle + ts 窗口 2s 副 oracle，无孤儿）；AC8 第 17 认领（含 STALE/等待中）；AC2/9 租约经 env 确定性加速（AGENT_KANBAN_LEASE_SECONDS=-1/短秒）。

## 红绿证据

- 红: `tests/red-0-all.log` —— 空实现（stub 包 PYTHONPATH 遮蔽）0/12 PASS，全红。
- 绿: `tests/green-0.log` —— 66/66 PASS。
- 每 AC 断言逐字引自 PRD，未读实现私有成员；并发场景真实多进程，未 mock。

## 重跑规格

```
cd .worktree/spike
uv run python -m compileall -q src cli.py          # tier-0
uv run python tests/run_ac.py                      # tier-1（全 AC，需 ~2-3 分钟）
```

- 确定性: 租约/过期/空闲经 env 覆盖（AGENT_KANBAN_LEASE_SECONDS / AGENT_KANBAN_IDLE_SECONDS / AGENT_KANBAN_BUSY_TIMEOUT_MS），禁 sleep 撞窗；AC1 kill 锚经 AGENT_KANBAN_TEST_CLAIM_HOOK=block_after_insert + marker 文件轮询。
- 隔离: harness 每次运行用临时 DB 目录（tests/run_ac.py 内部），互不污染。

## 不做清单（本批显式不做，见 docs/plans/spike-plan.md「不修清单」）

FastAPI/REST（M0）、Alembic（M0，create_all 占位）、reconcile 对账（M0）、token/localhost 绑定（M0 安全面；DB 0600 已实现）、摘要/深潜视图、export 完整实现（CLI 占位）、payload 8KB 上限（NFR）、重试/成本记录/心跳模型（未决 M0）、release --all-stale（M0，AC16 只测单释放）。

## 域外发现（单列，修复裁决归主循环）

1. 跨进程时钟边界：AC6 竞争下 agent 写事件 ts 可比 release ended_at 晚数毫秒（锁竞争期各自捕获 now）。处理：harness 以 seq（提交序，无时钟依赖）为主 oracle、ts 窗口 2s 容差为副；未改业务代码。后续 M0 可评估 ts 改为同事务签发基准（当前 seq 已承担顺序职责，ts 仅作展示）。
2. renew/approve 非 MCP 工具（PRD 4.1/4.2 设计事实）：lease_expired 触发路径为 CLI renew；MCP 调 renew 得 "Unknown tool: renew"。
3. mark_blocked/request_review 前置顺序：实现先查 state 再查认领（OPEN 无认领误回 no_active_claim 的次序问题已修），state=CLAIMED 违反应 illegal_state。
4. uv 将包装入 .venv：红跑空实现改走 PYTHONPATH 遮蔽 stub 包方案（site-packages 优先）。

## 基线

- 本批 commit: 6beb539（T2.1）、fcefb75（T2.2-2.7）、a9dcb21（T2.8+红绿留档）
- 关联: ADR 0001「G7 Spike 验证」节（移植边界收窄）、ADR 0002（MCP SDK，G4 闭合）、ADR 0000 G7/G4 已闭合
