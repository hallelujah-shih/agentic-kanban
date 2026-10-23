"""G5 基准（tests/bench.py，独立脚本，不进 run_ac）。

5k 需求库直接 SQL 批量种子（审#P2-4 形状对齐：seq_counter 同步到 max(seed seq)、
payload 形状对齐真实 ops（state_change 含 from/to、decomposition 含 subtask_id）、
ts 经 SQLAlchemy 绑定参数写 datetime（UTCDateTime 往返，禁裸 SQL 字符串）、最坏 =
5k 非终态且 <=16 认领）。测序（审#P2-C 单库重序）：summary 单需求 -> add_record 写
-> 最坏 board（5k 非终态）-> UPDATE 4900 需求为 DONE 测混合 board。board 自定预算
<1s（记录制，审#P2-5）。结果写入 docs/ops/bench-results.md。
"""

from __future__ import annotations

import asyncio
import os
import platform
import sys
import tempfile
import time
import uuid
from datetime import timedelta
from pathlib import Path

import sqlalchemy
import sqlite3

REPO_ROOT = Path(__file__).resolve().parent.parent

DB_PATH = Path(tempfile.mkdtemp(prefix="ak-bench-")) / "kanban.db"
os.environ["AGENT_KANBAN_DB"] = str(DB_PATH)

from agent_kanban.db import ensure_schema, get_session_factory, now_utc, run_op  # noqa: E402（env 先置）
from agent_kanban.models import Claim, Event, Milestone, Requirement, Subtask  # noqa: E402
from agent_kanban.services import operations as ops  # noqa: E402
from agent_kanban.services import view  # noqa: E402

N = 5000
N_CLAIMED = 16
CHUNK = 500


async def _insert_chunks(session, table, rows, chunk=CHUNK) -> None:
    for i in range(0, len(rows), chunk):
        await session.execute(sqlalchemy.insert(table), rows[i:i + chunk])


async def _seed(session) -> tuple[int, list[str], str]:
    """直接 SQL 批量种子（审#P2-4 形状对齐）。返回 (max_seq, rids, 单需求样例 rid)。"""
    t0 = time.perf_counter()
    now = now_utc()
    rids = [uuid.uuid4().hex for _ in range(N)]
    claimed_rids = set(rids[:N_CLAIMED])

    req_rows = [{
        "id": rids[i], "source": "manual", "source_ref": None,
        "title": f"bench-req-{i}", "description": None, "acceptance": [],
        "state": "CLAIMED" if rids[i] in claimed_rids else "OPEN",
        "awaiting_human": None, "created_at": now, "updated_at": now,
    } for i in range(N)]

    subtask_rows = []
    sub_ids: dict[str, list[str]] = {}
    for i, rid in enumerate(rids):
        sid = uuid.uuid4().hex
        sub_ids[rid] = [sid]
        subtask_rows.append({
            "id": sid, "requirement_id": rid, "ordinal": 1,
            "title": f"sub-{i}", "acceptance": [], "state": "todo",
            "milestone_id": None, "created_at": now, "updated_at": now,
        })
        if rid in claimed_rids:  # CLAIMED 需求多一条 blocked 子任务（_derived_signals blocked 路径）
            sid2 = uuid.uuid4().hex
            sub_ids[rid].append(sid2)
            subtask_rows.append({
                "id": sid2, "requirement_id": rid, "ordinal": 2,
                "title": f"sub-{i}-blocked", "acceptance": [], "state": "blocked",
                "milestone_id": None, "created_at": now, "updated_at": now,
            })

    milestone_rows = []
    mile_ids: dict[str, str] = {}
    for i, rid in enumerate(claimed_rids):
        mid = uuid.uuid4().hex
        mile_ids[rid] = mid
        milestone_rows.append({
            "id": mid, "requirement_id": rid, "title": f"ms-{i}",
            "planned_at": now - timedelta(days=30), "actual_at": None, "state": "planned",
            "created_at": now, "updated_at": now,
        })

    claim_rows = []
    for i, rid in enumerate(claimed_rids):
        claim_rows.append({
            "id": uuid.uuid4().hex, "requirement_id": rid, "agent_name": f"bench-agent-{i}",
            "agent_conn": f"conn-bench-{i}", "started_at": now,
            "lease_expires_at": now + timedelta(hours=2), "last_activity_at": now,
            "ended_at": None, "release_reason": None,
        })

    event_rows = []
    seq = 0
    for i, rid in enumerate(rids):
        if rid in claimed_rids:
            # 真实 ops 形状（审#P2-4c）：state_change 含 from/to、decomposition 含 subtask_id/milestone_id、decision 结构化
            evs = [
                {"kind": "state_change", "severity": "info", "title": "OPEN -> CLAIMED",
                 "payload": {"from": "OPEN", "to": "CLAIMED"}},
                {"kind": "decomposition", "severity": "info", "title": "add_subtask",
                 "payload": {"subtask_id": sub_ids[rid][0], "ordinal": 1, "title": f"sub-{i}"}},
                {"kind": "decomposition", "severity": "info", "title": "add_milestone",
                 "payload": {"milestone_id": mile_ids[rid], "title": f"ms-{i}"}},
                {"kind": "decision", "severity": "info", "title": "选型",
                 "payload": {"choice": "A", "rationale": "r",
                             "alternatives": [{"option": "B", "rejected_reason": "x"}]}},
            ]
        else:
            evs = [
                {"kind": "state_change", "severity": "info", "title": "OPEN -> CLAIMED",
                 "payload": {"from": "OPEN", "to": "CLAIMED"}},
                {"kind": "decomposition", "severity": "info", "title": "add_subtask",
                 "payload": {"subtask_id": sub_ids[rid][0], "ordinal": 1, "title": f"sub-{i}"}},
                {"kind": "state_change", "severity": "info", "title": "CLAIMED -> OPEN",
                 "payload": {"from": "CLAIMED", "to": "OPEN"}},
            ]
        for ev in evs:
            seq += 1
            event_rows.append({
                "id": uuid.uuid4().hex, "requirement_id": rid, "claim_id": None,
                "subtask_id": sub_ids[rid][0] if ev["kind"] == "decomposition" and ev["payload"].get("subtask_id") else None,
                "milestone_id": ev["payload"].get("milestone_id") if ev["kind"] == "decomposition" else None,
                "kind": ev["kind"], "severity": ev["severity"], "title": ev["title"],
                "content": None, "payload": ev["payload"],
                "actor_surface": "mcp", "actor_conn": f"conn-bench-{i}",
                "seq": seq, "ts": now,
            })

    await _insert_chunks(session, Requirement, req_rows)
    await _insert_chunks(session, Subtask, subtask_rows)
    await _insert_chunks(session, Milestone, milestone_rows)
    await _insert_chunks(session, Claim, claim_rows)
    await _insert_chunks(session, Event, event_rows)
    # 审#P2-4a：seq 同步 seq_counter 到 max(seed seq)
    await session.execute(
        sqlalchemy.text("UPDATE seq_counter SET value = :max WHERE id = 1"), {"max": seq}
    )
    await session.commit()
    elapsed = time.perf_counter() - t0
    return seq, rids, claimed_rids, elapsed


async def _measure(n: int, op, *, is_write: bool, **kwargs) -> list[float]:
    out = []
    for _ in range(n):
        t0 = time.perf_counter()
        await run_op(get_session_factory(), op, is_write=is_write, **kwargs)
        out.append((time.perf_counter() - t0) * 1000)
    return out


def _sum(ts: list[float]) -> dict:
    return {"min": round(min(ts), 1), "median": round(sorted(ts)[len(ts) // 2], 1), "max": round(max(ts), 1)}


async def _run() -> dict:
    await ensure_schema()
    session = get_session_factory()()
    try:
        max_seq, rids, claimed_rids, seed_s = await _seed(session)
    finally:
        await session.close()

    sample = list(claimed_rids)[0]
    summary = await _measure(3, view.summary, is_write=False, requirement_id=sample,
                             actor_surface="cli", actor_conn="cli")
    write = await _measure(3, ops.add_record, is_write=True, requirement_id=sample,
                           kind="note", title="bench-note", actor_surface="cli", actor_conn="cli")
    board_worst = await _measure(3, view.board, is_write=False, actor_surface="cli", actor_conn="cli")
    # 审#P2-C：UPDATE 4900 需求为 DONE 测混合 board（100 非终态 = 16 CLAIMED + 84 OPEN）
    session = get_session_factory()()
    try:
        await session.execute(
            sqlalchemy.update(Requirement).where(Requirement.id.in_(rids[100:])).values(state="DONE")
        )
        await session.commit()
    finally:
        await session.close()
    board_mixed = await _measure(3, view.board, is_write=False, actor_surface="cli", actor_conn="cli")

    return {
        "seed_s": round(seed_s, 1), "max_seq": max_seq, "n_events": max_seq,
        "summary": _sum(summary), "write": _sum(write),
        "board_worst": _sum(board_worst), "board_mixed": _sum(board_mixed),
    }


def _env() -> dict:
    return {
        "python": platform.python_version(), "platform": platform.platform(),
        "sqlalchemy": sqlalchemy.__version__, "sqlite": sqlite3.sqlite_version,
        "db_path": str(DB_PATH), "db_size_mb": round(DB_PATH.stat().st_size / 1024 / 1024, 1),
    }


def _write_md(res: dict, env: dict, trigger_4b: bool) -> Path:
    md = REPO_ROOT / "docs" / "ops" / "bench-results.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# G5 基准结果（M1-3.4，tests/bench.py 生成）",
        "",
        "位置: docs/ops/bench-results.md（tracked；重跑 `uv run python tests/bench.py` 覆写）",
        "规范锚: PRD §6 性能（摘要视图 < 200 ms @ 5k 需求；状态/记录写 < 50 ms）；docs/plans/m1-3-plan.md M1-3.4（审#P2-4 种子形状 / 审#P2-C 单库重序 / 审#P2-5 board 自定预算 <1s 记录制）",
        "",
        "## 环境",
        "",
        f"- python {env['python']} / platform {env['platform']}",
        f"- sqlalchemy {env['sqlalchemy']} / sqlite {env['sqlite']}",
        f"- DB: {env['db_path']}（{env['db_size_mb']} MB，临时目录每次新建）",
        "",
        "## 种子（审#P2-4 形状对齐）",
        "",
        f"- 5000 需求（{res['max_seq']} events / 5002 subtasks / 16 active claims / 16 milestones）；种子耗时 {res['seed_s']} s",
        "- 形状对齐：state_change payload 含 from/to；decomposition 含 subtask_id/milestone_id；decision 结构化（choice/rationale/alternatives）；ts 经 SQLAlchemy 绑定参数写 datetime（UTCDateTime 往返）；seq_counter 同步到 max(seed seq)（审#P2-4a）",
        "- 最坏 = 5000 非终态（16 CLAIMED + 4984 OPEN）且 <=16 认领（MAX_ACTIVE_CLAIMS 上限）",
        "",
        "## 测量（审#P2-C 单库重序：summary -> write -> 最坏 board -> UPDATE 4900 DONE -> 混合 board）",
        "",
        "| 面 | 目标 | min | median | max | 达标 |",
        "|---|---|---|---|---|---|",
        f"| summary 单需求（CLAIMED 全数据） | < 200 ms | {res['summary']['min']} | {res['summary']['median']} | {res['summary']['max']} | {'是' if res['summary']['median'] < 200 else '否'} |",
        f"| add_record 写 | < 50 ms | {res['write']['min']} | {res['write']['median']} | {res['write']['max']} | {'是' if res['write']['median'] < 50 else '否'} |",
        f"| board 最坏（5k 非终态） | < 1 s（自定预算记录制，审#P2-5） | {res['board_worst']['min']} | {res['board_worst']['median']} | {res['board_worst']['max']} | {'是' if res['board_worst']['median'] < 1000 else '否'} |",
        f"| board 混合（100 非终态，4900 DONE） | -（记录） | {res['board_mixed']['min']} | {res['board_mixed']['median']} | {res['board_mixed']['max']} | - |",
        "",
        "## 结论",
        "",
        f"- summary / 写面：{'达标' if res['summary']['median'] < 200 and res['write']['median'] < 50 else '未达标，见下'}（PRD §6 目标）。",
        f"- board 最坏面：{'达标（<1s）' if not trigger_4b else '超自定预算（>=1s），触发 M1-3.4b 批查询优化（claims/subtasks/milestones/events 分组查询 + Python 内存分组，审#P2-5 同一 DB 优化前后 board dict 全等）'}。4b 触发与优化前后对比见 m1-3-verification.md。",
        f"- 量级注记（审#P2-D）：数据量级主要由活跃需求数决定——混合 board（4900 DONE）median {res['board_mixed']['median']} ms vs 最坏（5k 非终态）median {res['board_worst']['median']} ms。",
        "",
        "## 盲区",
        "",
        "1. bench 为测量非断言门（M1-3.6 盲区 1）：本文件是记录制证据，不参与 run_ac 门禁；种子/测量数字依赖本机环境。",
        "2. summary/write 面若超 PRD 目标仅记录上报，不自动触发重构（plan 仅 4b 对 board 有条件触发）。",
    ]
    md.write_text("\n".join(lines), encoding="utf-8")
    return md


def main() -> int:
    res = asyncio.run(_run())
    env = _env()
    trigger_4b = res["board_worst"]["median"] >= 1000
    md = _write_md(res, env, trigger_4b)
    print(json_dumps := __import__("json").dumps({"seed_s": res["seed_s"], "summary": res["summary"],
                                                  "write": res["write"], "board_worst": res["board_worst"],
                                                  "board_mixed": res["board_mixed"], "trigger_4b": trigger_4b},
                                                 ensure_ascii=False, indent=2))
    print(f"bench-results written: {md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
