"""R1 写侧契约 + 工具自描述用例（tests/ac_cases_l.py + run_ac 注册）。

oracle 纪律：断言引 BCD distill-pipeline §1 裁决 1/§3 Commands 1-4/§4 Scenario 1-3/
边缘 2（无半态）；DB 事后 sqlite3 直查（读数据非读实现）。

覆盖（五元组）：
- 裁决 1(a) update_progress 必填 headline -> l_headline
- 强不变量 3 人面记录必带提纲 -> l_headline / l_summary_line / l_record_title
- 裁决 5/Scenario 2 交接一句话 -> l_summary_line
- Scenario 3 阻塞原因进追加链 -> l_blocked_reason_chain
- Premortem 1 带内兜底 -> l_tool_self_desc

无半态断言（BCD 边缘 2 Then，审 r1 P2-1）：三个错误路径用例的每个错误分支
写前后 events 计数相等 + 需求行 awaiting_human/state 未变，防「先写事件再抛错」
的实现使错误码绿而留半态。
"""

from __future__ import annotations

import json
from pathlib import Path

from ac_lib import MCP, REPO_ROOT, cli_ok, new_db, ok, query, seed_req

EXPECTED_TOOLS = {
    "list_tasks", "get_task_detail", "claim_task", "add_subtask", "update_subtask",
    "add_milestone", "update_milestone", "add_record", "update_progress",
    "request_review", "mark_blocked", "list_awaiting",
}


def _count(db: Path, rid: str) -> int:
    return query(db, "SELECT COUNT(*) AS n FROM events WHERE requirement_id=?", (rid,))[0]["n"]


def _req_snap(db: Path, rid: str) -> tuple:
    """需求行 (state, awaiting_human 原始存储) 快照，无半态对照用。"""
    row = query(db, "SELECT state, awaiting_human FROM requirements WHERE id=?", (rid,))[0]
    return (row["state"], row["awaiting_human"])


def _call_err2(m: MCP, name: str, args: dict) -> tuple[str, str]:
    """call + 解错误 payload，返回 (code, message)（ac_lib.call_err 不返 message，不改 ac_lib）。"""
    res = m.call(name, args)
    if not res.get("isError"):
        raise AssertionError(f"{name} unexpectedly succeeded: {res}")
    payload = json.loads(res["content"][0]["text"])
    return payload["code"], payload.get("message", "")


def l_headline():
    print("== R1.1: update_progress 必填 headline（invalid_record 带修法）+ 提纲落 title + 错误无半态")
    db = new_db()
    rid = seed_req(db, "l-headline")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    # (i) 缺 headline -> invalid_record，message 含 headline（修法）；无半态
    n0 = _count(db, rid)
    snap0 = _req_snap(db, rid)
    code, msg = _call_err2(m, "update_progress", {"requirement_id": rid, "note": "n1"})
    ok("l_headline(i): 缺 headline -> invalid_record", code == "invalid_record", code)
    ok("l_headline(i): message 含 headline（指明修法）", "headline" in msg, msg)
    ok("l_headline(i): 无半态——events 计数不变", _count(db, rid) == n0, f"{n0}->{_count(db, rid)}")
    ok("l_headline(i): 无半态——需求行未变", _req_snap(db, rid) == snap0, str(_req_snap(db, rid)))
    # (ii) 仅空白 headline -> invalid_record；无半态
    n1 = _count(db, rid)
    snap1 = _req_snap(db, rid)
    code, msg = _call_err2(m, "update_progress", {"requirement_id": rid, "note": "n2", "headline": "   "})
    ok("l_headline(ii): 仅空白 headline -> invalid_record", code == "invalid_record", code)
    ok("l_headline(ii): message 含 headline", "headline" in msg, msg)
    ok("l_headline(ii): 无半态——events 计数不变", _count(db, rid) == n1, f"{n1}->{_count(db, rid)}")
    ok("l_headline(ii): 无半态——需求行未变", _req_snap(db, rid) == snap1, str(_req_snap(db, rid)))
    # (iii) 正常 -> title==headline.strip()、content==note、severity==info、payload.note==note
    m.call_ok("update_progress",
              {"requirement_id": rid, "note": "修了 tests/test_view.py 的竞态，加了锁",
               "headline": "  修了 test_view 竞态  "})
    ev = query(db, "SELECT title, content, severity, payload FROM events WHERE requirement_id=? "
                   "AND kind='progress_note' ORDER BY seq DESC LIMIT 1", (rid,))[0]
    pl = json.loads(ev["payload"])
    ok("l_headline(iii): title == headline.strip()", ev["title"] == "修了 test_view 竞态", ev["title"])
    ok("l_headline(iii): content == note", ev["content"] == "修了 tests/test_view.py 的竞态，加了锁",
       str(ev["content"]))
    ok("l_headline(iii): severity == info", ev["severity"] == "info", ev["severity"])
    ok("l_headline(iii): payload.note == note（双写保留）",
       pl.get("note") == "修了 tests/test_view.py 的竞态，加了锁", str(pl))
    m.close()


def l_summary_line():
    print("== R1.2: request_review 必填 summary_line + severity=attention + 交接一句话 + 错误无半态")
    # (i) 缺 summary_line -> invalid_record，message 含 summary_line；无半态
    db = new_db()
    rid = seed_req(db, "l-summary")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    n0 = _count(db, rid)
    snap0 = _req_snap(db, rid)
    code, msg = _call_err2(m, "request_review",
                           {"requirement_id": rid, "evidence": {"test_summary": "s"}})
    ok("l_summary_line(i): 缺 summary_line -> invalid_record", code == "invalid_record", code)
    ok("l_summary_line(i): message 含 summary_line", "summary_line" in msg, msg)
    ok("l_summary_line(i): 无半态——events 计数不变", _count(db, rid) == n0, f"{n0}->{_count(db, rid)}")
    ok("l_summary_line(i): 无半态——需求行未变", _req_snap(db, rid) == snap0, str(_req_snap(db, rid)))
    # (ii) BLOCKED 上 request_review 仍 -> illegal_state（校验顺序 state 在前，不回归）
    db2 = new_db()
    rid2 = seed_req(db2, "l-summary-blocked")
    m2 = MCP(db2).start()
    m2.call_ok("claim_task", {"requirement_id": rid2, "agent_name": "a"})
    m2.call_ok("mark_blocked", {"requirement_id": rid2, "reason": "waiting"})
    code2, _ = m2.call_err("request_review",
                           {"requirement_id": rid2, "evidence": {"test_summary": "s"},
                            "summary_line": "x"})
    ok("l_summary_line(ii): BLOCKED 上 request_review -> illegal_state（顺序不回归）",
       code2 == "illegal_state", code2)
    m2.close()
    # (iii) 正常 -> awaiting_human.summary_line == 传入值；review_request 事件 severity=attention
    #       且 payload.summary_line 在场
    m.call_ok("request_review",
              {"requirement_id": rid, "evidence": {"test_summary": "s"},
               "summary_line": "重做了记录管线，先看事件流"})
    row = query(db, "SELECT awaiting_human FROM requirements WHERE id=?", (rid,))[0]
    ah = json.loads(row["awaiting_human"])
    ok("l_summary_line(iii): awaiting_human.summary_line == 传入值",
       ah.get("summary_line") == "重做了记录管线，先看事件流", str(ah))
    ok("l_summary_line(iii): awaiting_human.kind == review", ah.get("kind") == "review", str(ah))
    ev = query(db, "SELECT severity, payload FROM events WHERE requirement_id=? "
                   "AND kind='review_request' ORDER BY seq DESC LIMIT 1", (rid,))[0]
    pl = json.loads(ev["payload"])
    ok("l_summary_line(iii): review_request severity == attention", ev["severity"] == "attention",
       ev["severity"])
    ok("l_summary_line(iii): payload.summary_line 在场（与 evidence 平级）",
       pl.get("summary_line") == "重做了记录管线，先看事件流", str(pl))
    m.close()


def l_record_title():
    print("== R1.3: add_record 必填 title（一行人话提纲）+ 错误无半态")
    db = new_db()
    rid = seed_req(db, "l-title")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    # (i) title="" -> invalid_record，message 指明 title；无半态
    n0 = _count(db, rid)
    snap0 = _req_snap(db, rid)
    code, msg = _call_err2(m, "add_record", {"requirement_id": rid, "kind": "note", "title": ""})
    ok("l_record_title(i): title='' -> invalid_record", code == "invalid_record", code)
    ok("l_record_title(i): message 指明 title", "title" in msg, msg)
    ok("l_record_title(i): 无半态——events 计数不变", _count(db, rid) == n0, f"{n0}->{_count(db, rid)}")
    ok("l_record_title(i): 无半态——需求行未变", _req_snap(db, rid) == snap0, str(_req_snap(db, rid)))
    # (ii) title="   " -> invalid_record；无半态
    n1 = _count(db, rid)
    snap1 = _req_snap(db, rid)
    code, msg = _call_err2(m, "add_record", {"requirement_id": rid, "kind": "note", "title": "   "})
    ok("l_record_title(ii): title 仅空白 -> invalid_record", code == "invalid_record", code)
    ok("l_record_title(ii): message 指明 title", "title" in msg, msg)
    ok("l_record_title(ii): 无半态——events 计数不变", _count(db, rid) == n1, f"{n1}->{_count(db, rid)}")
    ok("l_record_title(ii): 无半态——需求行未变", _req_snap(db, rid) == snap1, str(_req_snap(db, rid)))
    # (iii) 正常 title 成功落事件
    m.call_ok("add_record", {"requirement_id": rid, "kind": "note", "title": "选型 SQLite WAL"})
    ev = query(db, "SELECT title FROM events WHERE requirement_id=? AND kind='note' "
                   "ORDER BY seq DESC LIMIT 1", (rid,))[0]
    ok("l_record_title(iii): 正常 title 落事件", ev["title"] == "选型 SQLite WAL", ev["title"])
    m.close()


def l_blocked_reason_chain():
    print("== R1.4: mark_blocked reason 进追加链（state_change payload.reason）+ approve 清 marker 后链仍存")
    db = new_db()
    rid = seed_req(db, "l-blocked")
    reason = "等 user 裁决 X"
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.call_ok("mark_blocked", {"requirement_id": rid, "reason": reason})
    # (i) state_change(CLAIMED->BLOCKED) payload 含 reason
    ev = query(db, "SELECT title, payload FROM events WHERE requirement_id=? AND kind='state_change' "
                   "AND title='CLAIMED -> BLOCKED' ORDER BY seq DESC LIMIT 1", (rid,))
    ok("l_blocked(i): state_change CLAIMED->BLOCKED 在场", len(ev) == 1, f"n={len(ev)}")
    pl = json.loads(ev[0]["payload"])
    ok("l_blocked(i): payload.reason == 传入值", pl.get("reason") == reason, str(pl))
    m.close()
    # (ii) CLI approve -> awaiting_human 清除
    cli_ok(db, "approve", "--requirement-id", rid)
    row = query(db, "SELECT awaiting_human FROM requirements WHERE id=?", (rid,))[0]
    ok("l_blocked(ii): approve 清 awaiting_human", row["awaiting_human"] in (None, "null"),
       str(row["awaiting_human"]))
    # (iii) 事件链 reason 仍在（追加链不可抹，审计可回溯）
    ev2 = query(db, "SELECT payload FROM events WHERE requirement_id=? AND kind='state_change' "
                    "AND title='CLAIMED -> BLOCKED'", (rid,))
    pl2 = json.loads(ev2[0]["payload"])
    ok("l_blocked(iii): approve 后事件链 reason 仍在（追加链不抹）", pl2.get("reason") == reason, str(pl2))


def l_tool_self_desc():
    print("== R1.5: 工具自描述——12 工具 description + server instructions（带内兜底）")
    # in-process import：worktree src 优先（.venv editable 指向主仓 src，显式置顶防漂移）
    import asyncio
    import sys
    # .venv editable 指向主仓 src：裸 import 会影子主仓（T0 同类），故置顶 worktree
    # src；purge 为防御——当前套件无其他用例 in-process 载入 agent_kanban（已核，
    # insert 单独即够），但任一未来 in-process import 都会把本用例静默打回主仓，
    # 清缓存防该漂移
    sys.path.insert(0, str(REPO_ROOT / "src"))
    for mod in [m for m in sys.modules if m == "agent_kanban" or m.startswith("agent_kanban.")]:
        del sys.modules[mod]
    from agent_kanban.mcp.server import build_server
    server = build_server()
    ok("l_tool_self_desc: server.instructions 非空",
       bool(server.instructions and server.instructions.strip()),
       repr((server.instructions or "")[:80]))
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    ok("l_tool_self_desc: 12 工具名集合 == 预期", names == EXPECTED_TOOLS, str(sorted(names)))
    missing = [t.name for t in tools if not (t.description and t.description.strip())]
    ok("l_tool_self_desc: 12 工具 description 全部非空", not missing, str(missing))
