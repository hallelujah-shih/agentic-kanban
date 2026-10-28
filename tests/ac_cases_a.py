"""AC1-5 用例。断言逐字引自 PRD §9 判据表。"""

from __future__ import annotations

import json
import sqlite3
import threading
import time

from ac_lib import MCP, cli_err, cli_ok, new_db, ok, query, seed_reopen, seed_req

TIMEOUT = 30


def ac1():
    print("== AC1: 并发认领排他 + kill 崩溃原子性")
    db = new_db()
    req = seed_req(db, "ac1-target")
    procs = [MCP(db).start() for _ in range(10)]
    results: dict[int, tuple[str, str]] = {}

    def worker(i: int):
        try:
            res = procs[i].call("claim_task", {"requirement_id": req, "agent_name": f"agent-{i}"})
            if res.get("isError"):
                results[i] = ("err", json.loads(res["content"][0]["text"])["code"])
            else:
                results[i] = ("ok", json.loads(res["content"][0]["text"])["claim_id"])
        except Exception as exc:
            results[i] = ("exc", f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=TIMEOUT + 10)
    for p in procs:
        p.close()

    oks = [r for r in results.values() if r[0] == "ok"]
    errs = [r[1] for r in results.values() if r[0] == "err"]
    excs = [r for r in results.values() if r[0] == "exc"]
    ok("ac1: 10 并发恰 1 成功", len(oks) == 1 and not excs, f"ok={len(oks)} err={errs} exc={excs}")
    ok("ac1: 其余 9 already_claimed", errs.count("already_claimed") == 9, str(errs))
    rows = query(db, "SELECT state FROM requirements WHERE id=?", (req,))
    ok("ac1: 需求 CLAIMED", rows and rows[0]["state"] == "CLAIMED", str([dict(r) for r in rows]))
    n = query(db, "SELECT COUNT(*) c FROM claims WHERE requirement_id=? AND ended_at IS NULL", (req,))
    ok("ac1: 恰一未结束认领", n[0]["c"] == 1, str(n[0]["c"]))

    # kill 锚：INSERT 后 UPDATE 前阻塞 -> SIGKILL -> 事务回滚无孤儿
    req2 = seed_req(db, "ac1-kill-target")
    marker = db.parent / "claim-marker"
    killer = MCP(db, hook="block_after_insert", marker=marker).start()
    def _killer_claim() -> None:
        # kill 锚刻意 SIGKILL server，reader 侧 EOFError 是确定性设计副产品（G15）；
        # 只吞 EOFError，其他异常照抛（禁掩盖真失败）
        try:
            killer.call("claim_task", {"requirement_id": req2, "agent_name": "killer"})
        except EOFError:
            pass

    kill_thread = threading.Thread(target=_killer_claim)
    kill_thread.start()
    seen = False
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if marker.exists():
            seen = True
            break
        time.sleep(0.05)
    ok("ac1: kill 锚 marker 出现", seen)
    killer.kill()
    kill_thread.join(timeout=5)
    rows = query(db, "SELECT state FROM requirements WHERE id=?", (req2,))
    ok("ac1: 被 kill 需求仍 OPEN", rows and rows[0]["state"] == "OPEN", str([dict(r) for r in rows]))
    n = query(db, "SELECT COUNT(*) c FROM claims WHERE requirement_id=? AND ended_at IS NULL", (req2,))
    ok("ac1: 无孤儿 claim（事务回滚）", n[0]["c"] == 0, str(n[0]["c"]))
    bad = query(db, """
        SELECT r.id, r.state,
               (SELECT COUNT(*) FROM claims c WHERE c.requirement_id=r.id AND c.ended_at IS NULL) n
        FROM requirements r
    """)
    inconsistent = [dict(b) for b in bad if (b["state"] == "CLAIMED") != (b["n"] == 1)]
    ok("ac1: CLAIMED <=> 恰一未结束 claim 全局一致", not inconsistent, str(inconsistent))


def ac2():
    print("== AC2: 租约推导 STALE/等待中/SUSPECT + 不自动释放")
    db = new_db()
    lease_neg = {"AGENT_KANBAN_LEASE_SECONDS": "-1"}
    idle_neg = {"AGENT_KANBAN_IDLE_SECONDS": "-1"}
    ra = seed_req(db, "ac2-stale")
    ma = MCP(db, extra=lease_neg).start()
    ma.call_ok("claim_task", {"requirement_id": ra, "agent_name": "agent-a"})
    sig_a = ma.call_ok("get_task_detail", {"requirement_id": ra})["claim"]["signal"]
    ok("ac2: 过期无标记=STALE", sig_a == "stale", sig_a)
    ma.call_ok("request_review", {"requirement_id": ra, "evidence": {"test_summary": "s"},
                                   "summary_line": "ac2 交接"})
    sig_a2 = ma.call_ok("get_task_detail", {"requirement_id": ra})["claim"]["signal"]
    ok("ac2: 过期有标记=等待中", sig_a2 == "waiting", sig_a2)
    ok("ac2: STALE != 等待中", sig_a != sig_a2)
    row = query(db, """
        SELECT c.ended_at IS NULL AS active, r.state FROM claims c
        JOIN requirements r ON r.id = c.requirement_id WHERE r.id=?
    """, (ra,))
    ok("ac2: 过期不自动释放（claim 仍在）", row and row[0]["active"] == 1, str([dict(r) for r in row]))
    ok("ac2: 过期不自动重开（state 仍 CLAIMED）", row and row[0]["state"] == "CLAIMED", str([dict(r) for r in row]))
    ma.close()

    rb = seed_req(db, "ac2-suspect")
    mb = MCP(db, extra=idle_neg).start()
    mb.call_ok("claim_task", {"requirement_id": rb, "agent_name": "agent-b"})
    sig_b = mb.call_ok("get_task_detail", {"requirement_id": rb})["claim"]["signal"]
    ok("ac2: idle 超无标记=SUSPECT", sig_b == "suspect", sig_b)
    mb.close()


def ac3():
    print("== AC3: agent 面无法置 DONE；approve 决策表")
    db = new_db()
    m = MCP(db).start()
    tools = m.list_tools()
    expected = {
        "list_tasks", "get_task_detail", "claim_task", "add_subtask", "update_subtask",
        "add_milestone", "update_milestone", "add_record", "update_progress",
        "request_review", "mark_blocked", "list_awaiting",
    }
    ok("ac3: 12 工具清单精确", set(tools) == expected, str(sorted(tools)))
    ok("ac3: 工具面无 release/approve/new/set_expectations",
       not ({"release", "approve", "new", "set_expectations"} & set(tools)))

    r1 = seed_req(db, "ac3-claimed")
    m.call_ok("claim_task", {"requirement_id": r1, "agent_name": "a"})
    m.call_ok("request_review", {"requirement_id": r1, "evidence": {"test_summary": "t"},
                                  "summary_line": "ac3 交接"})
    res = cli_ok(db, "approve", "--requirement-id", r1)
    ok("ac3: approve(CLAIMED)->DONE", res["state"] == "DONE", json.dumps(res))
    d = m.call_ok("get_task_detail", {"requirement_id": r1})
    ok("ac3: approve 清 marker（同事务）", d["awaiting_human"] is None)
    row = query(db, "SELECT ended_at IS NULL AS active FROM claims WHERE requirement_id=?", (r1,))
    ok("ac3: claim ended_at 同事务", row and row[0]["active"] == 0, str([dict(r) for r in row]))
    kinds = [e["kind"] for e in query(db, "SELECT kind FROM events WHERE requirement_id=? ORDER BY seq", (r1,))]
    ok("ac3: approval 事件写入", "approval" in kinds and "state_change" in kinds, str(kinds))

    code, _ = cli_err(db, "approve", "--requirement-id", r1)
    ok("ac3: approve(DONE)->illegal_state", code == "illegal_state", code)
    r2 = seed_req(db, "ac3-open")
    code, _ = cli_err(db, "approve", "--requirement-id", r2)
    ok("ac3: approve(OPEN)->illegal_state", code == "illegal_state", code)
    r3 = seed_req(db, "ac3-reopen")
    seed_reopen(db, r3)
    code, _ = cli_err(db, "approve", "--requirement-id", r3)
    ok("ac3: approve(REOPEN)->illegal_state", code == "illegal_state", code)
    r4 = seed_req(db, "ac3-rejected")
    cli_ok(db, "abandon", "--requirement-id", r4, "--to-state", "REJECTED")
    code, _ = cli_err(db, "approve", "--requirement-id", r4)
    ok("ac3: approve(REJECTED)->illegal_state", code == "illegal_state", code)
    r5 = seed_req(db, "ac3-cancelled")
    cli_ok(db, "abandon", "--requirement-id", r5, "--to-state", "CANCELLED")
    code, _ = cli_err(db, "approve", "--requirement-id", r5)
    ok("ac3: approve(CANCELLED)->illegal_state", code == "illegal_state", code)

    r6 = seed_req(db, "ac3-blocked")
    m.call_ok("claim_task", {"requirement_id": r6, "agent_name": "a"})
    m.call_ok("mark_blocked", {"requirement_id": r6, "reason": "waiting input"})
    res = cli_ok(db, "approve", "--requirement-id", r6)
    ok("ac3: approve(BLOCKED)->CLAIMED 解阻塞", res["state"] == "CLAIMED", json.dumps(res))
    d = m.call_ok("get_task_detail", {"requirement_id": r6})
    ok("ac3: 解阻塞清 marker", d["awaiting_human"] is None)

    r7 = seed_req(db, "ac3-blocked-review")
    m.call_ok("claim_task", {"requirement_id": r7, "agent_name": "a"})
    m.call_ok("mark_blocked", {"requirement_id": r7, "reason": "x"})
    code, _ = m.call_err("request_review",
                         {"requirement_id": r7, "evidence": {"test_summary": "t"},
                          "summary_line": "ac3 交接"})
    ok("ac3: BLOCKED 上 request_review->illegal_state", code == "illegal_state", code)
    code, _ = m.call_err("mark_blocked", {"requirement_id": r2, "reason": "x"})
    ok("ac3: mark_blocked(OPEN)->illegal_state", code == "illegal_state", code)
    m.close()


def ac4():
    print("== AC4: decision payload 校验")
    db = new_db()
    m = MCP(db).start()
    r = seed_req(db, "ac4")
    m.call_ok("claim_task", {"requirement_id": r, "agent_name": "a"})
    cases = [
        ("缺 alternatives", {"choice": "a", "rationale": "r"}),
        ("缺 rationale", {"choice": "a", "alternatives": [{"option": "b", "rejected_reason": "why"}]}),
        ("alternative 缺 rejected_reason", {"choice": "a", "rationale": "r", "alternatives": [{"option": "b"}]}),
        ("alternatives 空", {"choice": "a", "rationale": "r", "alternatives": []}),
        ("payload 非对象", "not-a-dict"),
    ]
    for name, payload in cases:
        code, _ = m.call_err("add_record", {"requirement_id": r, "kind": "decision",
                                            "title": "d", "payload": payload})
        ok(f"ac4: {name} -> invalid_record", code == "invalid_record", code)
    res = m.call_ok("add_record", {"requirement_id": r, "kind": "decision", "title": "d",
                                   "payload": {"choice": "a", "rationale": "r",
                                               "alternatives": [{"option": "b", "rejected_reason": "why"}]}})
    ok("ac4: 合法 decision 成功", res["kind"] == "decision")
    m.close()


def ac5():
    print("== AC5: deviation severity 强制 >= attention")
    db = new_db()
    m = MCP(db).start()
    r = seed_req(db, "ac5")
    m.call_ok("claim_task", {"requirement_id": r, "agent_name": "a"})
    code, _ = m.call_err("add_record", {"requirement_id": r, "kind": "deviation",
                                        "title": "dev", "severity": "info"})
    ok("ac5: deviation+info 被拒 invalid_record", code == "invalid_record", code)
    res = m.call_ok("add_record", {"requirement_id": r, "kind": "deviation",
                                   "title": "dev", "severity": "attention"})
    ok("ac5: deviation+attention 成功", res["kind"] == "deviation")
    m.close()
