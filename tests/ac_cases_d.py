"""M0-1 结果盲审修复断言：P1-1 id 全链 32-hex 闭合、P2-1 note/update_progress payload 8KB、
P2-3 拆解新增只计 add_subtask 的 decomposition。

oracle：AC15 判据4（payload.subtask_id 字符串精确 join subtasks[].id）；
PRD §6 单事件 payload < 8 KB；plan M0-1.4 拆解新增口径（add_subtask 的 decomposition 事件）。
"""

from __future__ import annotations

from ac_lib import MCP, REST, cli_err, cli_ok, new_db, ok, seed_req

_HEX = set("0123456789abcdef")


def _is_32hex(value: object) -> bool:
    return isinstance(value, str) and len(value) == 32 and all(c in _HEX for c in value)


def p1_id_normalization():
    print("== P1-1: 响应边界 id 全链 32-hex（与写路径/payload 引用一致）")
    db = new_db()
    rid = seed_req(db, "p1-ids")
    m = MCP(db).start()
    c = m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    ok("P1-1: claim_task 写路径 claim_id 32-hex（内存实例）", _is_32hex(c["claim_id"]), c["claim_id"])
    s1 = m.call_ok("add_subtask", {"requirement_id": rid, "title": "s1", "ordinal": 1})
    ms = m.call_ok("add_milestone", {"requirement_id": rid, "title": "M1",
                                     "planned_at": "2030-01-01T00:00:00+00:00"})
    ok("P1-1: add_subtask 写路径 subtask_id 32-hex", _is_32hex(s1["subtask_id"]), s1["subtask_id"])
    ok("P1-1: add_milestone 写路径 milestone_id 32-hex", _is_32hex(ms["milestone_id"]), ms["milestone_id"])

    lt = m.call_ok("list_tasks", {})
    tasks = lt["tasks"]
    bad = [t["requirement_id"] for t in tasks if not _is_32hex(t["requirement_id"])]
    ok("P1-1: list_tasks 全部 requirement_id 32-hex", not bad, str(bad[:3]))
    ok("P1-1: list_tasks 与 seed rid 字符串精确匹配",
       any(t["requirement_id"] == rid for t in tasks), str([t["requirement_id"] for t in tasks][:3]))
    bad_claim = [t["claim"]["claim_id"] for t in tasks if t.get("claim") and not _is_32hex(t["claim"]["claim_id"])]
    ok("P1-1: list_tasks 全部 claim.claim_id 32-hex", not bad_claim, str(bad_claim[:3]))

    d = m.call_ok("get_task_detail", {"requirement_id": rid})
    ok("P1-1: get_task_detail requirement_id 32-hex 且等于 rid", d["requirement_id"] == rid, d["requirement_id"])
    ok("P1-1: get_task_detail claim.claim_id 32-hex",
       d.get("claim") is None or _is_32hex(d["claim"]["claim_id"]), str(d.get("claim")))
    bad_st = [st["subtask_id"] for st in d["subtasks"] if not _is_32hex(st["subtask_id"])]
    ok("P1-1: get_task_detail subtasks 全 32-hex", not bad_st, str(bad_st[:3]))
    bad_ms = [x["milestone_id"] for x in d["milestones"] if not _is_32hex(x["milestone_id"])]
    ok("P1-1: get_task_detail milestones 全 32-hex", not bad_ms, str(bad_ms[:3]))
    bad_ev = [e["claim_id"] for e in d["events"] if e.get("claim_id") and not _is_32hex(e["claim_id"])]
    ok("P1-1: get_task_detail events claim_id 全 32-hex", not bad_ev, str(bad_ev[:3]))
    bad_c = [c2["claim_id"] for c2 in d["claims"] if not _is_32hex(c2["claim_id"])]
    ok("P1-1: get_task_detail claims 时间轴 claim_id 全 32-hex", not bad_c, str(bad_c[:3]))

    rel = cli_ok(db, "release", "--requirement-id", rid, "--reason", "p1-1 check done")
    ok("P1-1: release 响应 claim_id 32-hex", _is_32hex(rel["claim_id"]), rel["claim_id"])
    m.close()

    rest = REST(db).start()
    try:
        code, rd = rest.req("GET", f"/requirements/{rid}")
        ok("P1-1: view.detail events claim_id 全 32-hex",
           code == 200 and all((e.get("claim_id") is None) or _is_32hex(e["claim_id"]) for e in rd["events"]),
           str([e["claim_id"] for e in rd["events"] if e.get("claim_id")][:3]))
        code, exp = rest.req("GET", f"/requirements/{rid}/export?format=json")
        subs = exp["requirement"]["subtasks"]
        mss = exp["requirement"]["milestones"]
        claim_ids = {c2["claim_id"] for c2 in exp["requirement"]["claims"]}
        sub_evs = [e for e in exp["requirement"]["events"] if (e["payload"] or {}).get("subtask_id")]
        ms_evs = [e for e in exp["requirement"]["events"] if (e["payload"] or {}).get("milestone_id")]
        bad_join = [e for e in sub_evs if e["payload"]["subtask_id"] not in {s["subtask_id"] for s in subs}]
        ok("P1-1: export payload.subtask_id 与 subtasks[].id 字符串 join 闭合（AC15 判据4）",
           code == 200 and not bad_join, str([e["payload"]["subtask_id"] for e in bad_join][:3]))
        bad_ms_join = [e for e in ms_evs if e["payload"]["milestone_id"] not in {x["milestone_id"] for x in mss}]
        ok("P1-1: export payload.milestone_id 与 milestones[].id join 闭合", not bad_ms_join,
           str([e["payload"]["milestone_id"] for e in bad_ms_join][:3]))
        bad_ev = [e["claim_id"] for e in exp["requirement"]["events"]
                  if e.get("claim_id") and e["claim_id"] not in claim_ids]
        ok("P1-1: export events claim_id 与 claims[].claim_id join 闭合", not bad_ev, str(bad_ev[:3]))
        ok("P1-1: export subtasks[].id 全 32-hex",
           all(_is_32hex(s["subtask_id"]) for s in subs), str([s["subtask_id"] for s in subs][:3]))
    finally:
        rest.stop()


def p2_payload_8kb():
    print("== P2-1: note/update_progress 单事件 payload < 8KB 写时强制（PRD 6）")
    db = new_db()
    m = MCP(db).start()
    r = seed_req(db, "p2-1")
    m.call_ok("claim_task", {"requirement_id": r, "agent_name": "a"})
    big = "x" * 9000
    code, _ = cli_err(db, "note", "--requirement-id", r, "--content", big)
    ok("P2-1: note content >8KB -> invalid_record", code == "invalid_record", code)
    code, _ = m.call_err("update_progress", {"requirement_id": r, "note": big})
    ok("P2-1: update_progress note >8KB -> invalid_record", code == "invalid_record", code)
    small = "y" * 7000
    res = m.call_ok("update_progress", {"requirement_id": r, "note": small})
    ok("P2-1: update_progress <8KB 成功", res["requirement_id"] == r, str(res))
    res = cli_ok(db, "note", "--requirement-id", r, "--content", small)
    ok("P2-1: note <8KB 成功", res["requirement_id"] == r, str(res))
    m.close()


def p2_decomposition_signal():
    print("== P2-3: 拆解新增信号只计 add_subtask 的 decomposition（排除 add_milestone）")
    db = new_db()
    rid = seed_req(db, "p2-3-ms")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.call_ok("add_milestone", {"requirement_id": rid, "title": "M1",
                                "planned_at": "2030-01-01T00:00:00+00:00"})
    m.close()
    rest = REST(db).start()
    try:
        code, s = rest.req("GET", f"/requirements/{rid}/summary")
        na_types = [n["type"] for n in s["needs_attention"]]
        ok("P2-3: CLAIMED 内仅 add_milestone 不触发拆解新增信号",
           "decomposition_added" not in na_types, str(na_types))
    finally:
        rest.stop()

    rid2 = seed_req(db, "p2-3-sub")
    m2 = MCP(db).start()
    m2.call_ok("claim_task", {"requirement_id": rid2, "agent_name": "b"})
    m2.call_ok("add_subtask", {"requirement_id": rid2, "title": "x", "ordinal": 1})
    m2.close()
    rest2 = REST(db).start()
    try:
        code, s = rest2.req("GET", f"/requirements/{rid2}/summary")
        na_types = [n["type"] for n in s["needs_attention"]]
        ok("P2-3: CLAIMED 内 add_subtask 触发拆解新增信号（正对照）",
           "decomposition_added" in na_types, str(na_types))
    finally:
        rest2.stop()
