"""AC6-9/16 + 9 码矩阵 + 补充断言。断言逐字引自 PRD §9 判据表。"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta

from ac_lib import MCP, cli, cli_err, cli_ok, new_db, ok, query, seed_req

TIMEOUT = 30
margin_dt = timedelta(seconds=2.0)  # 跨进程时钟边界容差


def dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def ac6():
    print("== AC6: 无认领写保护 + 释放/写并发不产孤儿")
    db = new_db()
    m = MCP(db).start()
    r1 = seed_req(db, "ac6-noclaim")
    for tool, args in [
        ("add_subtask", {"requirement_id": r1, "title": "s", "ordinal": 1}),
        ("update_progress", {"requirement_id": r1, "note": "n"}),
        ("add_record", {"requirement_id": r1, "kind": "note", "title": "n"}),
    ]:
        code, _ = m.call_err(tool, args)
        ok(f"ac6: 无认领 {tool} -> no_active_claim", code == "no_active_claim", code)

    # 释放（CLI 子进程）与 agent 写（3 个真实进程）并发竞争
    r2 = seed_req(db, "ac6-race")
    m.call_ok("claim_task", {"requirement_id": r2, "agent_name": "racer"})
    writers = [MCP(db).start() for _ in range(3)]
    barrier = threading.Barrier(4)
    outcomes: list[str] = []
    release_rc: list[int] = []

    def write_worker(i: int):
        barrier.wait()
        for k in range(25):
            res = writers[i].call("update_progress",
                                  {"requirement_id": r2, "note": f"w{i}-{k}",
                                   "headline": f"h{i}-{k}"})
            if res.get("isError"):
                outcomes.append(json.loads(res["content"][0]["text"])["code"])
            else:
                outcomes.append("ok")
            time.sleep(0.03)

    def release_worker():
        barrier.wait()
        release_rc.append(cli(db, "release", "--requirement-id", r2, "--reason", "handoff").returncode)

    t1 = threading.Thread(target=release_worker)
    threads = [threading.Thread(target=write_worker, args=(i,)) for i in range(3)]
    t1.start()
    for t in threads:
        t.start()
    t1.join(timeout=TIMEOUT + 10)
    for t in threads:
        t.join(timeout=TIMEOUT + 10)
    for p in writers:
        p.close()
    m.close()

    ok("ac6: release 成功", release_rc == [0], str(release_rc))
    n_ok = outcomes.count("ok")
    n_no = outcomes.count("no_active_claim")
    ok("ac6: 竞争产生 ok 与 no_active_claim 混合", n_ok >= 1 and n_no >= 1,
       f"ok={n_ok} no_active_claim={n_no} other={outcomes}")

    # 孤儿 oracle 双通道：
    # 1) seq 排序（BEGIN IMMEDIATE 串行化，seq=提交序，无时钟依赖）：
    #    全部 agent 事件 seq < release 事件 seq => 无 release 提交后的 agent 记录
    # 2) ts 窗口（PRD 字面口径）：落在 [started_at, ended_at]，跨进程边界留 2s 容差
    evs = query(db, """
        SELECT e.seq, e.ts, c.started_at, c.ended_at, e.kind FROM events e
        JOIN claims c ON c.id = e.claim_id
        WHERE e.requirement_id=? AND e.actor_surface='mcp'
    """, (r2,))
    rel_seq = query(db, "SELECT seq FROM events WHERE requirement_id=? AND kind='release'", (r2,))
    seq_ok = bool(rel_seq) and all(r["seq"] < rel_seq[0]["seq"] for r in evs)
    max_mcp = max((r["seq"] for r in evs), default=None)
    ok("ac6: 全部 agent 事件 seq < release 事件 seq（无孤儿）", seq_ok,
       f"max_mcp_seq={max_mcp} release_seq={rel_seq[0]['seq'] if rel_seq else None}")
    margin = 2.0
    in_window = all(
        (dt(r["started_at"]) - margin_dt <= dt(r["ts"]) <= dt(r["ended_at"]) + margin_dt)
        for r in evs if r["ended_at"] is not None
    ) and all(dt(r["started_at"]) - margin_dt <= dt(r["ts"]) for r in evs if r["ended_at"] is None)
    ok("ac6: 全部 agent 事件 ts 落在 [started_at, ended_at]（2s 容差）", in_window,
       f"{len(evs)} events" + ("" if in_window else f" {[dict(r) for r in evs]}"))
    row = query(db, "SELECT state FROM requirements WHERE id=?", (r2,))
    ok("ac6: 竞争后 state=OPEN", row and row[0]["state"] == "OPEN", str([dict(r) for r in row]))
    n = query(db, "SELECT COUNT(*) c FROM claims WHERE requirement_id=? AND ended_at IS NULL", (r2,))
    ok("ac6: 无未结束认领残留", n[0]["c"] == 0, str(n[0]["c"]))


def ac7():
    print("== AC7: 归一后同 title -> duplicate_subtask")
    db = new_db()
    m = MCP(db).start()
    r = seed_req(db, "ac7")
    m.call_ok("claim_task", {"requirement_id": r, "agent_name": "a"})
    m.call_ok("add_subtask", {"requirement_id": r, "title": "Alpha Task", "ordinal": 1})
    code, _ = m.call_err("add_subtask", {"requirement_id": r, "title": "  ALPHA   task ", "ordinal": 2})
    ok("ac7: 大小写/空白归一重复 -> duplicate_subtask", code == "duplicate_subtask", code)
    m.close()


def ac8():
    print("== AC8: 第 17 认领 -> queue_full（含 STALE/等待中）")
    db = new_db()
    reqs = [seed_req(db, f"ac8-r{i}") for i in range(16)]
    r17 = seed_req(db, "ac8-r17")
    m = MCP(db, extra={"AGENT_KANBAN_LEASE_SECONDS": "-1"}).start()
    for i, r in enumerate(reqs):
        m.call_ok("claim_task", {"requirement_id": r, "agent_name": f"a{i}"})
    m.call_ok("request_review", {"requirement_id": reqs[0], "evidence": {"test_summary": "s"},
                                  "summary_line": "ac8 交接"})
    code, _ = m.call_err("claim_task", {"requirement_id": r17, "agent_name": "b"})
    ok("ac8: 第 17 认领 -> queue_full（含 STALE/等待中）", code == "queue_full", code)
    n = query(db, "SELECT COUNT(*) c FROM claims WHERE ended_at IS NULL", ())
    ok("ac8: 恰好 16 未结束认领", n[0]["c"] == 16, str(n[0]["c"]))
    m.close()


def ac9():
    print("== AC9: renew 已过期租约 -> lease_expired")
    db = new_db()
    r = seed_req(db, "ac9")
    m = MCP(db, extra={"AGENT_KANBAN_LEASE_SECONDS": "-1"}).start()
    m.call_ok("claim_task", {"requirement_id": r, "agent_name": "a"})
    code, _ = cli_err(db, "renew", "--requirement-id", r)
    ok("ac9: 过期 renew -> lease_expired", code == "lease_expired", code)
    r2 = seed_req(db, "ac9-valid")
    m2 = MCP(db).start()
    before = m2.call_ok("claim_task", {"requirement_id": r2, "agent_name": "b"})["lease_expires_at"]
    res = cli_ok(db, "renew", "--requirement-id", r2)
    ok("ac9: 有效 renew 续租成功", res["lease_expires_at"] > before, f"{before} -> {res['lease_expires_at']}")
    m.close()
    m2.close()


def ac16():
    print("== AC16: MCP 面无 release；CLI release 语义")
    db = new_db()
    m = MCP(db).start()
    ok("ac16: 工具面无 release", "release" not in m.list_tools())
    r1 = seed_req(db, "ac16")
    m.call_ok("claim_task", {"requirement_id": r1, "agent_name": "a"})
    m.call_ok("request_review", {"requirement_id": r1, "evidence": {"test_summary": "t"},
                                  "summary_line": "ac16 交接"})
    res = cli_ok(db, "release", "--requirement-id", r1, "--reason", "handoff")
    ok("ac16: release 回 OPEN", res["state"] == "OPEN", json.dumps(res))
    rel = [e for e in query(db, "SELECT kind, payload FROM events WHERE requirement_id=? ORDER BY seq", (r1,))
           if e["kind"] == "release"]
    ok("ac16: release 事件写入", len(rel) == 1, str([dict(e) for e in rel]))
    ok("ac16: release 事件含 reason", json.loads(rel[0]["payload"] or "{}").get("reason") == "handoff")
    row = query(db, "SELECT ended_at IS NULL AS active, release_reason FROM claims WHERE requirement_id=?", (r1,))
    ok("ac16: claim 已结束 + reason 落库",
       row and row[0]["active"] == 0 and row[0]["release_reason"] == "handoff",
       str([dict(r) for r in row]))
    d = m.call_ok("get_task_detail", {"requirement_id": r1})
    ok("ac16: release 清 marker", d["awaiting_human"] is None)
    r2 = seed_req(db, "ac16-noclaim")
    code, _ = cli_err(db, "release", "--requirement-id", r2, "--reason", "x")
    ok("ac16: 无认领 release -> not_found", code == "not_found", code)
    m.close()


def matrix():
    print("== 9 码矩阵")
    db = new_db()
    m = MCP(db).start()
    code, _ = m.call_err("claim_task", {"requirement_id": "deadbeef", "agent_name": "x"})
    ok("m: claim 不存在 -> not_found", code == "not_found", code)
    code, _ = cli_err(db, "renew", "--requirement-id", "deadbeef")
    ok("m: renew 不存在 -> not_found", code == "not_found", code)
    code, _ = m.call_err("get_task_detail", {"requirement_id": "deadbeef"})
    ok("m: get_task_detail 不存在 -> not_found", code == "not_found", code)
    code, _ = cli_err(db, "approve", "--requirement-id", "deadbeef")
    ok("m: approve 不存在 -> not_found", code == "not_found", code)
    r = seed_req(db, "m-invalid")
    m.call_ok("claim_task", {"requirement_id": r, "agent_name": "a"})
    code, _ = m.call_err("request_review", {"requirement_id": r, "evidence": {},
                                             "summary_line": "m 交接"})
    ok("m: request_review 缺证据 -> invalid_record（死期 M0 唯一例外）", code == "invalid_record", code)

    # db_busy：第二连接持锁 + 极小 busy_timeout -> 写重试 3 次后
    r2 = seed_req(db, "m-busy")
    r3 = seed_req(db, "m-busy2")
    mb = MCP(db, extra={"AGENT_KANBAN_BUSY_TIMEOUT_MS": "50"}).start()
    mb.call_ok("claim_task", {"requirement_id": r2, "agent_name": "warm"})  # 同进程预热 schema
    holder = sqlite3.connect(str(db))
    holder.execute("BEGIN IMMEDIATE")
    try:
        code, _ = mb.call_err("claim_task", {"requirement_id": r3, "agent_name": "blocked"})
    finally:
        holder.rollback()
        holder.close()
    ok("m: 写重试 3 次后 -> db_busy", code == "db_busy", code)
    mb.close()
    m.close()


def extras():
    print("== 补充断言: marker 覆盖 + 验收自评持久化")
    db = new_db()
    m = MCP(db).start()
    r = seed_req(db, "extras")
    m.call_ok("claim_task", {"requirement_id": r, "agent_name": "a"})
    st = m.call_ok("add_subtask", {"requirement_id": r, "title": "impl", "ordinal": 1,
                                   "acceptance": [{"item": "works"}]})
    m.call_ok("request_review", {"requirement_id": r, "evidence": {"test_summary": "t"},
                                  "summary_line": "e 交接",
                                 "assessments": [{"subtask_id": st["subtask_id"],
                                                  "items": [{"item": "works", "state": "met"}]}]})
    d = m.call_ok("get_task_detail", {"requirement_id": r})
    acc = d["subtasks"][0]["acceptance"]
    ok("e: 自评持久化到 subtasks.acceptance[].state",
       acc and any(str(a.get("item")) == "works" and a.get("state") == "met" for a in acc),
       json.dumps(acc))
    m.call_ok("mark_blocked", {"requirement_id": r, "reason": "needs decision"})
    d = m.call_ok("get_task_detail", {"requirement_id": r})
    ah = d["awaiting_human"] or {}
    ok("e: mark_blocked 覆盖旧 marker(kind=blocked)", ah.get("kind") == "blocked", json.dumps(ah))

    # links_to 删除保护（PRD 4.2：删除被 links_to 引用的锚项被拒绝）
    r2 = seed_req(db, "extras-links")
    cli_ok(db, "set_expectations", "--requirement-id", r2,
           "--acceptance", '[{"item": "A1"}, {"item": "A2"}]')
    m.call_ok("claim_task", {"requirement_id": r2, "agent_name": "a"})
    m.call_ok("add_subtask", {"requirement_id": r2, "title": "impl2", "ordinal": 2,
                              "acceptance": [{"item": "x", "links_to": "a1"}]})
    code, _ = cli_err(db, "set_expectations", "--requirement-id", r2,
                      "--acceptance", '[{"item": "A2"}]')
    ok("e: 删除被 links_to 引用的锚项 -> invalid_record", code == "invalid_record", code)
    cli_ok(db, "set_expectations", "--requirement-id", r2,
           "--acceptance", '[{"item": "A1"}, {"item": "A2"}]')
    ok("e: 保留被引用锚项 -> set_expectations 成功", True, "ok")
    m.close()
