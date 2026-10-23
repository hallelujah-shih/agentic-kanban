# G5 基准结果（M1-3.4，tests/bench.py 生成）

位置: docs/ops/bench-results.md（tracked；重跑 `uv run python tests/bench.py` 覆写）
规范锚: PRD §6 性能（摘要视图 < 200 ms @ 5k 需求；状态/记录写 < 50 ms）；docs/plans/m1-3-plan.md M1-3.4（审#P2-4 种子形状 / 审#P2-C 单库重序 / 审#P2-5 board 自定预算 <1s 记录制）

## 环境

- python 3.14.4 / platform Linux-7.2.11-200.fc44.x86_64-x86_64-with-glibc2.43
- sqlalchemy 2.1.6 / sqlite 3.50.4
- DB: /tmp/ak-bench-28npo2_b/kanban.db（7.8 MB，临时目录每次新建）

## 种子（审#P2-4 形状对齐）

- 5000 需求（15016 events / 5002 subtasks / 16 active claims / 16 milestones）；种子耗时 3.4 s
- 形状对齐：state_change payload 含 from/to；decomposition 含 subtask_id/milestone_id；decision 结构化（choice/rationale/alternatives）；ts 经 SQLAlchemy 绑定参数写 datetime（UTCDateTime 往返）；seq_counter 同步到 max(seed seq)（审#P2-4a）
- 最坏 = 5000 非终态（16 CLAIMED + 4984 OPEN）且 <=16 认领（MAX_ACTIVE_CLAIMS 上限）

## 测量（审#P2-C 单库重序：summary -> write -> 最坏 board -> UPDATE 4900 DONE -> 混合 board）

| 面 | 目标 | min | median | max | 达标 |
|---|---|---|---|---|---|
| summary 单需求（CLAIMED 全数据） | < 200 ms | 3.2 | 3.7 | 12.5 | 是 |
| add_record 写 | < 50 ms | 3.5 | 3.6 | 6.6 | 是 |
| board 最坏（5k 非终态） | < 1 s（自定预算记录制，审#P2-5） | 536.9 | 538.7 | 619.6 | 是 |
| board 混合（100 非终态，4900 DONE） | -（记录） | 15.3 | 15.5 | 17.0 | - |

## 结论

- summary / 写面：达标（PRD §6 目标）。
- board 最坏面：达标（<1s）。4b 触发与优化前后对比见 m1-3-verification.md。
- 量级注记（审#P2-D）：数据量级主要由活跃需求数决定——混合 board（4900 DONE）median 15.5 ms vs 最坏（5k 非终态）median 538.7 ms。

## 盲区

1. bench 为测量非断言门（M1-3.6 盲区 1）：本文件是记录制证据，不参与 run_ac 门禁；种子/测量数字依赖本机环境。
2. summary/write 面若超 PRD 目标仅记录上报，不自动触发重构（plan 仅 4b 对 board 有条件触发）。