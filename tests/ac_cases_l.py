"""R1 写侧契约 + 工具自描述 + R3 读侧用例（tests/ac_cases_l.py + run_ac 注册）。

oracle 纪律：断言引 BCD distill-pipeline §1 裁决 1/§3 Commands 1-4/§4 Scenario 1-3/
边缘 2（无半态）；DB 事后 sqlite3 直查（读数据非读实现）。

覆盖（五元组）：
- 裁决 1(a) update_progress 必填 headline -> l_headline
- 强不变量 3 人面记录必带提纲 -> l_headline / l_summary_line / l_record_title / l_blocked_reason_empty
- 裁决 5/Scenario 2 交接一句话 -> l_summary_line
- Scenario 3 阻塞原因进追加链 -> l_blocked_reason_chain
- Premortem 1 带内兜底 -> l_tool_self_desc

R3 读侧（T2，plan distill-pipeline T2 节）：
- 裁决 3 最新 200（seq 升序）+ 先 limit 后 filter + 无读侧 severity 过滤
  （Premortem 4 反向判别）+ export 全量 -> l_latest_first
- Policy 4 人/机分类单点同源 -> l_audience
- 强不变量 1 蒸馏不破坏 export 全量 -> l_export_stable（回归 oracle）

无半态断言（BCD 边缘 2 Then，审 r1 P2-1）：四个错误路径用例的每个错误分支
写前后 events 计数相等 + 需求行 awaiting_human/state 未变，防「先写事件再抛错」
的实现使错误码绿而留半态。

l_export_stable 冻结常量由批次目录 export-baseline/{md,csv,json} 机械生成
（T1 态 471f158 冻结，重跑规格见该目录 README.txt）；一经冻结即契约，绿步禁
反向修改去迁就合并后输出。测试不读批次目录（本仓无 committed-fixture 约定，
oracle 自包含保 CI 可跑）。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ac_lib import MCP, REPO_ROOT, cli, cli_ok, new_db, ok, query, seed_req

EXPECTED_TOOLS = {
    "new_requirement", "set_expectations",
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


def l_blocked_reason_empty():
    print("== R1.6: mark_blocked reason 必填一行人话（空/纯空白 -> invalid_record）+ 错误无半态")
    db = new_db()
    rid = seed_req(db, "l-blocked-empty")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    # (i) reason="" -> invalid_record，message 含 reason（指明修法）；无半态
    n0 = _count(db, rid)
    snap0 = _req_snap(db, rid)
    code, msg = _call_err2(m, "mark_blocked", {"requirement_id": rid, "reason": ""})
    ok("l_blocked_empty(i): reason='' -> invalid_record", code == "invalid_record", code)
    ok("l_blocked_empty(i): message 含 reason（指明修法）", "reason" in msg, msg)
    ok("l_blocked_empty(i): 无半态——events 计数不变", _count(db, rid) == n0, f"{n0}->{_count(db, rid)}")
    ok("l_blocked_empty(i): 无半态——需求行未变（state 仍 CLAIMED、awaiting_human 未设）",
       _req_snap(db, rid) == snap0, str(_req_snap(db, rid)))
    # (ii) reason 仅空白 -> invalid_record；无半态
    n1 = _count(db, rid)
    snap1 = _req_snap(db, rid)
    code, msg = _call_err2(m, "mark_blocked", {"requirement_id": rid, "reason": "   "})
    ok("l_blocked_empty(ii): reason 仅空白 -> invalid_record", code == "invalid_record", code)
    ok("l_blocked_empty(ii): message 含 reason", "reason" in msg, msg)
    ok("l_blocked_empty(ii): 无半态——events 计数不变", _count(db, rid) == n1, f"{n1}->{_count(db, rid)}")
    ok("l_blocked_empty(ii): 无半态——需求行未变（state 仍 CLAIMED、awaiting_human 未设）",
       _req_snap(db, rid) == snap1, str(_req_snap(db, rid)))
    # (iii) 正常 reason 不误伤（CLAIMED -> BLOCKED 照旧）
    m.call_ok("mark_blocked", {"requirement_id": rid, "reason": "等 user 裁决 X"})
    row = query(db, "SELECT state FROM requirements WHERE id=?", (rid,))[0]
    ok("l_blocked_empty(iii): 正常 reason -> BLOCKED", row["state"] == "BLOCKED", row["state"])
    m.close()


def l_tool_self_desc():
    print("== R1.5: 工具自描述——14 工具 description + server instructions（带内兜底）")
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
    ok("l_tool_self_desc: 14 工具名集合 == 预期", names == EXPECTED_TOOLS, str(sorted(names)))
    missing = [t.name for t in tools if not (t.description and t.description.strip())]
    ok("l_tool_self_desc: 14 工具 description 全部非空", not missing, str(missing))


# ==================================================================== R3 读侧（T2）
# oracle：plan distill-pipeline T2 节——最新 200（seq 升序）/ 先 limit 后 filter /
# 无读侧 severity 过滤（Premortem 4 反向判别）/ audience 单点 / export 回归 oracle。
# 判别力声明：红步（T1 态）l_latest_first 红于「最旧 200 seq[1,200]」与 audience 键缺失；
# l_audience 红于 event_audience 不存在；l_export_stable 红步平凡绿是设计使然
# （回归 oracle，判别力在绿步：合并后 md/csv byte-identical 若破即抓出合并破坏）。


def _ak_import(db: Path | None):
    """进程内 agent_kanban import：AGENT_KANBAN_DB 先置（db.DEFAULT_DB 在 import 时求值，
    序错＝打错库）、worktree src 置顶 + purge 旧模块（l_tool_self_desc 可能已导入）。
    返回 (prev_env, akdb, models, ops, view)。"""
    prev = os.environ.get("AGENT_KANBAN_DB")
    if db is not None:
        os.environ["AGENT_KANBAN_DB"] = str(db)
    sys.path.insert(0, str(REPO_ROOT / "src"))
    for mod in [m for m in sys.modules if m == "agent_kanban" or m.startswith("agent_kanban.")]:
        del sys.modules[mod]
    import agent_kanban.db as akdb
    from agent_kanban.models import Claim, Event, Milestone, Requirement, Subtask
    from agent_kanban.services import operations as ops
    from agent_kanban.services import view

    return prev, akdb, (Requirement, Claim, Subtask, Milestone, Event), ops, view


def _ak_restore(prev) -> None:
    """还原 env + purge 进程内 agent_kanban，不给后续用例留状态。"""
    if prev is None:
        os.environ.pop("AGENT_KANBAN_DB", None)
    else:
        os.environ["AGENT_KANBAN_DB"] = prev
    for mod in [m for m in sys.modules if m == "agent_kanban" or m.startswith("agent_kanban.")]:
        del sys.modules[mod]


async def _ak_dispose(akdb) -> None:
    """dispose 引擎（aiosqlite 线程防泄漏阻塞进程退出）。"""
    if akdb._Runtime.write_engine is not None:
        await akdb._Runtime.write_engine.dispose()
    if akdb._Runtime.read_engine is not None:
        await akdb._Runtime.read_engine.dispose()


# ---------------------------------------------------------------- fixture（固定常量）
RID = "a1" * 16
CLAIM_ID = "b2" * 16
SUB_ID = "c3" * 16
MS_ID = "d4" * 16


def _ts(m: int) -> datetime:
    return datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=m)


def _ev_id(i: int) -> str:
    return f"0f{i:02d}" * 8


def _export_fixture_rows() -> dict:
    return {
        "requirement": {
            "id": RID, "source": "manual", "source_ref": "AKT-42",
            "title": "distill 蒸馏夹具", "description": "冻结基线夹具",
            "acceptance": [{"id": "a1", "item": "锚 A"}],
            "state": "OPEN", "awaiting_human": None,
            "created_at": _ts(0), "updated_at": _ts(10),
        },
        "claim": {
            "id": CLAIM_ID, "requirement_id": RID, "agent_name": "fixture-agent",
            "agent_conn": "fixture-conn", "started_at": _ts(0),
            "lease_expires_at": _ts(120), "last_activity_at": _ts(9),
            "ended_at": _ts(10), "release_reason": "manual",
        },
        "milestone": {
            "id": MS_ID, "requirement_id": RID, "title": "ms one",
            "planned_at": _ts(1440), "actual_at": _ts(2880),
            "state": "achieved", "created_at": _ts(1), "updated_at": _ts(2880),
        },
        "subtask": {
            "id": SUB_ID, "requirement_id": RID, "ordinal": 1, "title": "sub one",
            "acceptance": [{"item": "x1", "state": "done"}], "state": "done",
            "milestone_id": MS_ID, "created_at": _ts(1), "updated_at": _ts(9),
        },
        # 旧形状锚点：seq4 progress_note(title="progress", payload.note)；
        # seq6 review_request severity=info（T1 前旧值，直 SQL 绕 T1 写校验）。
        "events": [
            {"id": _ev_id(1), "requirement_id": RID, "claim_id": CLAIM_ID,
             "subtask_id": None, "milestone_id": None,
             "kind": "state_change", "severity": "info", "title": "OPEN -> CLAIMED",
             "content": None, "payload": {"from": "OPEN", "to": "CLAIMED"},
             "actor_surface": "mcp", "actor_conn": "fixture-conn", "seq": 1, "ts": _ts(1)},
            {"id": _ev_id(2), "requirement_id": RID, "claim_id": CLAIM_ID,
             "subtask_id": SUB_ID, "milestone_id": None,
             "kind": "decomposition", "severity": "info", "title": "add_subtask",
             "content": None, "payload": {"subtask_id": SUB_ID, "ordinal": 1, "title": "sub one"},
             "actor_surface": "mcp", "actor_conn": "fixture-conn", "seq": 2, "ts": _ts(2)},
            {"id": _ev_id(3), "requirement_id": RID, "claim_id": CLAIM_ID,
             "subtask_id": None, "milestone_id": MS_ID,
             "kind": "decomposition", "severity": "info", "title": "add_milestone",
             "content": None, "payload": {"milestone_id": MS_ID, "title": "ms one"},
             "actor_surface": "mcp", "actor_conn": "fixture-conn", "seq": 3, "ts": _ts(2)},
            {"id": _ev_id(4), "requirement_id": RID, "claim_id": CLAIM_ID,
             "subtask_id": None, "milestone_id": None,
             "kind": "progress_note", "severity": "info", "title": "progress",
             "content": "开始重构", "payload": {"note": "开始重构"},
             "actor_surface": "mcp", "actor_conn": "fixture-conn", "seq": 4, "ts": _ts(3)},
            {"id": _ev_id(5), "requirement_id": RID, "claim_id": CLAIM_ID,
             "subtask_id": None, "milestone_id": None,
             "kind": "decision", "severity": "info", "title": "选型 SQLite WAL",
             "content": None,
             "payload": {"choice": "sqlite", "rationale": "简单可靠",
                         "alternatives": [{"option": "postgres", "rejected_reason": "运维成本"}]},
             "actor_surface": "mcp", "actor_conn": "fixture-conn", "seq": 5, "ts": _ts(4)},
            {"id": _ev_id(6), "requirement_id": RID, "claim_id": CLAIM_ID,
             "subtask_id": None, "milestone_id": None,
             "kind": "review_request", "severity": "info", "title": "review requested",
             "content": None, "payload": {"evidence": {"test_summary": "521/521"}},
             "actor_surface": "mcp", "actor_conn": "fixture-conn", "seq": 6, "ts": _ts(6)},
            {"id": _ev_id(7), "requirement_id": RID, "claim_id": CLAIM_ID,
             "subtask_id": None, "milestone_id": None,
             "kind": "state_change", "severity": "info", "title": "CLAIMED -> BLOCKED",
             "content": None,
             "payload": {"from": "CLAIMED", "to": "BLOCKED", "reason": "等 user 裁决"},
             "actor_surface": "mcp", "actor_conn": "fixture-conn", "seq": 7, "ts": _ts(7)},
            {"id": _ev_id(8), "requirement_id": RID, "claim_id": CLAIM_ID,
             "subtask_id": None, "milestone_id": None,
             "kind": "state_change", "severity": "info", "title": "BLOCKED -> CLAIMED",
             "content": None, "payload": {"from": "BLOCKED", "to": "CLAIMED"},
             "actor_surface": "mcp", "actor_conn": "fixture-conn", "seq": 8, "ts": _ts(8)},
            {"id": _ev_id(9), "requirement_id": RID, "claim_id": CLAIM_ID,
             "subtask_id": None, "milestone_id": None,
             "kind": "state_change", "severity": "info", "title": "CLAIMED -> OPEN",
             "content": None, "payload": {"from": "CLAIMED", "to": "OPEN"},
             "actor_surface": "mcp", "actor_conn": "fixture-conn", "seq": 9, "ts": _ts(9)},
            {"id": _ev_id(10), "requirement_id": RID, "claim_id": CLAIM_ID,
             "subtask_id": None, "milestone_id": None,
             "kind": "release", "severity": "info", "title": "released",
             "content": None, "payload": {"reason": "manual", "agent_name": "fixture-agent"},
             "actor_surface": "mcp", "actor_conn": "fixture-conn", "seq": 10, "ts": _ts(10)},
        ],
    }


async def _seed_fixture(session, models) -> None:
    import sqlalchemy

    rows = _export_fixture_rows()
    Requirement, Claim, Subtask, Milestone, Event = models
    await session.execute(sqlalchemy.insert(Requirement), [rows["requirement"]])
    await session.execute(sqlalchemy.insert(Milestone), [rows["milestone"]])
    await session.execute(sqlalchemy.insert(Claim), [rows["claim"]])
    await session.execute(sqlalchemy.insert(Subtask), [rows["subtask"]])
    await session.execute(sqlalchemy.insert(Event), rows["events"])
    await session.execute(
        sqlalchemy.text("UPDATE seq_counter SET value = :v WHERE id = 1"), {"v": 10}
    )
    await session.commit()

# ---- 机械生成：export-baseline/{export.md,export.csv,export.json} ----
MD_FROZEN = '''# distill 蒸馏夹具  [OPEN]
- id: a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1
- source: manual AKT-42
- description: 冻结基线夹具

## acceptance
- [a1] 锚 A

## subtasks
- (1) sub one [done]

## milestones
- ms one [achieved] planned=2026-10-02T00:00:00+00:00 actual=2026-10-03T00:00:00+00:00

## claim

## events
- #1 2026-10-01T00:01:00+00:00 state_change/info by mcp:fixture-conn OPEN -> CLAIMED
  payload: {"from": "OPEN", "to": "CLAIMED"}
- #2 2026-10-01T00:02:00+00:00 decomposition/info by mcp:fixture-conn add_subtask
  payload: {"subtask_id": "c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3", "ordinal": 1, "title": "sub one"}
- #3 2026-10-01T00:02:00+00:00 decomposition/info by mcp:fixture-conn add_milestone
  payload: {"milestone_id": "d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4", "title": "ms one"}
- #4 2026-10-01T00:03:00+00:00 progress_note/info by mcp:fixture-conn progress
  content: 开始重构
  payload: {"note": "开始重构"}
- #5 2026-10-01T00:04:00+00:00 decision/info by mcp:fixture-conn 选型 SQLite WAL
  payload: {"choice": "sqlite", "rationale": "简单可靠", "alternatives": [{"option": "postgres", "rejected_reason": "运维成本"}]}
- #6 2026-10-01T00:06:00+00:00 review_request/info by mcp:fixture-conn review requested
  payload: {"evidence": {"test_summary": "521/521"}}
- #7 2026-10-01T00:07:00+00:00 state_change/info by mcp:fixture-conn CLAIMED -> BLOCKED
  payload: {"from": "CLAIMED", "to": "BLOCKED", "reason": "等 user 裁决"}
- #8 2026-10-01T00:08:00+00:00 state_change/info by mcp:fixture-conn BLOCKED -> CLAIMED
  payload: {"from": "BLOCKED", "to": "CLAIMED"}
- #9 2026-10-01T00:09:00+00:00 state_change/info by mcp:fixture-conn CLAIMED -> OPEN
  payload: {"from": "CLAIMED", "to": "OPEN"}
- #10 2026-10-01T00:10:00+00:00 release/info by mcp:fixture-conn released
  payload: {"reason": "manual", "agent_name": "fixture-agent"}
'''
CSV_FROZEN = '''record_type,requirement_id,title,description,source,source_ref,state,acceptance,awaiting_human,claim,claims,subtask_id,ordinal,milestone_id,created_at,updated_at,planned_at,actual_at,seq,kind,severity,content,payload,actor_surface,actor_conn,claim_id,ts
requirement,a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1,distill 蒸馏夹具,冻结基线夹具,manual,AKT-42,OPEN,"[{""id"": ""a1"", ""item"": ""锚 A""}]",,,"[{""claim_id"": ""b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2"", ""agent_name"": ""fixture-agent"", ""agent_conn"": ""fixture-conn"", ""started_at"": ""2026-10-01T00:00:00+00:00"", ""lease_expires_at"": ""2026-10-01T02:00:00+00:00"", ""last_activity_at"": ""2026-10-01T00:09:00+00:00"", ""ended_at"": ""2026-10-01T00:10:00+00:00"", ""release_reason"": ""manual"", ""signal"": ""ended""}]",,,,,,,,,,,,,,,,
subtask,,sub one,,,,done,"[{""item"": ""x1"", ""state"": ""done""}]",,,,c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3,1,d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4,2026-10-01T00:01:00+00:00,2026-10-01T00:09:00+00:00,,,,,,,,,,,
milestone,,ms one,,,,achieved,,,,,,,d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4,,,2026-10-02T00:00:00+00:00,2026-10-03T00:00:00+00:00,,,,,,,,,
event,,OPEN -> CLAIMED,,,,,,,,,,,,,,,,1,state_change,info,,"{""from"": ""OPEN"", ""to"": ""CLAIMED""}",mcp,fixture-conn,b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2,2026-10-01T00:01:00+00:00
event,,add_subtask,,,,,,,,,,,,,,,,2,decomposition,info,,"{""subtask_id"": ""c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3"", ""ordinal"": 1, ""title"": ""sub one""}",mcp,fixture-conn,b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2,2026-10-01T00:02:00+00:00
event,,add_milestone,,,,,,,,,,,,,,,,3,decomposition,info,,"{""milestone_id"": ""d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4"", ""title"": ""ms one""}",mcp,fixture-conn,b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2,2026-10-01T00:02:00+00:00
event,,progress,,,,,,,,,,,,,,,,4,progress_note,info,开始重构,"{""note"": ""开始重构""}",mcp,fixture-conn,b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2,2026-10-01T00:03:00+00:00
event,,选型 SQLite WAL,,,,,,,,,,,,,,,,5,decision,info,,"{""choice"": ""sqlite"", ""rationale"": ""简单可靠"", ""alternatives"": [{""option"": ""postgres"", ""rejected_reason"": ""运维成本""}]}",mcp,fixture-conn,b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2,2026-10-01T00:04:00+00:00
event,,review requested,,,,,,,,,,,,,,,,6,review_request,info,,"{""evidence"": {""test_summary"": ""521/521""}}",mcp,fixture-conn,b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2,2026-10-01T00:06:00+00:00
event,,CLAIMED -> BLOCKED,,,,,,,,,,,,,,,,7,state_change,info,,"{""from"": ""CLAIMED"", ""to"": ""BLOCKED"", ""reason"": ""等 user 裁决""}",mcp,fixture-conn,b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2,2026-10-01T00:07:00+00:00
event,,BLOCKED -> CLAIMED,,,,,,,,,,,,,,,,8,state_change,info,,"{""from"": ""BLOCKED"", ""to"": ""CLAIMED""}",mcp,fixture-conn,b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2,2026-10-01T00:08:00+00:00
event,,CLAIMED -> OPEN,,,,,,,,,,,,,,,,9,state_change,info,,"{""from"": ""CLAIMED"", ""to"": ""OPEN""}",mcp,fixture-conn,b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2,2026-10-01T00:09:00+00:00
event,,released,,,,,,,,,,,,,,,,10,release,info,,"{""reason"": ""manual"", ""agent_name"": ""fixture-agent""}",mcp,fixture-conn,b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2,2026-10-01T00:10:00+00:00
'''
JSON_FROZEN = {'requirement': {'requirement_id': 'a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1',
                 'title': 'distill 蒸馏夹具',
                 'description': '冻结基线夹具',
                 'source': 'manual',
                 'source_ref': 'AKT-42',
                 'state': 'OPEN',
                 'acceptance': [{'id': 'a1', 'item': '锚 A'}],
                 'awaiting_human': None,
                 'claim': None,
                 'claims': [{'claim_id': 'b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2',
                             'agent_name': 'fixture-agent',
                             'agent_conn': 'fixture-conn',
                             'started_at': '2026-10-01T00:00:00+00:00',
                             'lease_expires_at': '2026-10-01T02:00:00+00:00',
                             'last_activity_at': '2026-10-01T00:09:00+00:00',
                             'ended_at': '2026-10-01T00:10:00+00:00',
                             'release_reason': 'manual',
                             'signal': 'ended'}],
                 'subtasks': [{'subtask_id': 'c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3',
                               'ordinal': 1,
                               'title': 'sub one',
                               'state': 'done',
                               'acceptance': [{'item': 'x1', 'state': 'done'}],
                               'milestone_id': 'd4d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4',
                               'created_at': '2026-10-01T00:01:00+00:00',
                               'updated_at': '2026-10-01T00:09:00+00:00'}],
                 'milestones': [{'milestone_id': 'd4d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4',
                                 'title': 'ms one',
                                 'state': 'achieved',
                                 'planned_at': '2026-10-02T00:00:00+00:00',
                                 'actual_at': '2026-10-03T00:00:00+00:00'}],
                 'events': [{'seq': 1,
                             'kind': 'state_change',
                             'severity': 'info',
                             'title': 'OPEN -> CLAIMED',
                             'content': None,
                             'payload': {'from': 'OPEN', 'to': 'CLAIMED'},
                             'actor_surface': 'mcp',
                             'actor_conn': 'fixture-conn',
                             'claim_id': 'b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2',
                             'ts': '2026-10-01T00:01:00+00:00'},
                            {'seq': 2,
                             'kind': 'decomposition',
                             'severity': 'info',
                             'title': 'add_subtask',
                             'content': None,
                             'payload': {'subtask_id': 'c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3',
                                         'ordinal': 1,
                                         'title': 'sub one'},
                             'actor_surface': 'mcp',
                             'actor_conn': 'fixture-conn',
                             'claim_id': 'b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2',
                             'ts': '2026-10-01T00:02:00+00:00'},
                            {'seq': 3,
                             'kind': 'decomposition',
                             'severity': 'info',
                             'title': 'add_milestone',
                             'content': None,
                             'payload': {'milestone_id': 'd4d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4',
                                         'title': 'ms one'},
                             'actor_surface': 'mcp',
                             'actor_conn': 'fixture-conn',
                             'claim_id': 'b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2',
                             'ts': '2026-10-01T00:02:00+00:00'},
                            {'seq': 4,
                             'kind': 'progress_note',
                             'severity': 'info',
                             'title': 'progress',
                             'content': '开始重构',
                             'payload': {'note': '开始重构'},
                             'actor_surface': 'mcp',
                             'actor_conn': 'fixture-conn',
                             'claim_id': 'b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2',
                             'ts': '2026-10-01T00:03:00+00:00'},
                            {'seq': 5,
                             'kind': 'decision',
                             'severity': 'info',
                             'title': '选型 SQLite WAL',
                             'content': None,
                             'payload': {'choice': 'sqlite',
                                         'rationale': '简单可靠',
                                         'alternatives': [{'option': 'postgres', 'rejected_reason': '运维成本'}]},
                             'actor_surface': 'mcp',
                             'actor_conn': 'fixture-conn',
                             'claim_id': 'b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2',
                             'ts': '2026-10-01T00:04:00+00:00'},
                            {'seq': 6,
                             'kind': 'review_request',
                             'severity': 'info',
                             'title': 'review requested',
                             'content': None,
                             'payload': {'evidence': {'test_summary': '521/521'}},
                             'actor_surface': 'mcp',
                             'actor_conn': 'fixture-conn',
                             'claim_id': 'b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2',
                             'ts': '2026-10-01T00:06:00+00:00'},
                            {'seq': 7,
                             'kind': 'state_change',
                             'severity': 'info',
                             'title': 'CLAIMED -> BLOCKED',
                             'content': None,
                             'payload': {'from': 'CLAIMED', 'to': 'BLOCKED', 'reason': '等 user 裁决'},
                             'actor_surface': 'mcp',
                             'actor_conn': 'fixture-conn',
                             'claim_id': 'b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2',
                             'ts': '2026-10-01T00:07:00+00:00'},
                            {'seq': 8,
                             'kind': 'state_change',
                             'severity': 'info',
                             'title': 'BLOCKED -> CLAIMED',
                             'content': None,
                             'payload': {'from': 'BLOCKED', 'to': 'CLAIMED'},
                             'actor_surface': 'mcp',
                             'actor_conn': 'fixture-conn',
                             'claim_id': 'b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2',
                             'ts': '2026-10-01T00:08:00+00:00'},
                            {'seq': 9,
                             'kind': 'state_change',
                             'severity': 'info',
                             'title': 'CLAIMED -> OPEN',
                             'content': None,
                             'payload': {'from': 'CLAIMED', 'to': 'OPEN'},
                             'actor_surface': 'mcp',
                             'actor_conn': 'fixture-conn',
                             'claim_id': 'b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2',
                             'ts': '2026-10-01T00:09:00+00:00'},
                            {'seq': 10,
                             'kind': 'release',
                             'severity': 'info',
                             'title': 'released',
                             'content': None,
                             'payload': {'reason': 'manual', 'agent_name': 'fixture-agent'},
                             'actor_surface': 'mcp',
                             'actor_conn': 'fixture-conn',
                             'claim_id': 'b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2',
                             'ts': '2026-10-01T00:10:00+00:00'}]}}

_JSON_MISSING = object()
_NEW_KEY_WHITELIST = {"history_note", "state_at_event", "audience"}


def _diff_detail(a: str, b: str, n: int = 80) -> str:
    if a == b:
        return ""
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return f"first diff @ {i}: {a[max(0, i - 30):i + n]!r} vs {b[max(0, i - 30):i + n]!r}"
    return f"prefix equal, len {len(a)} vs {len(b)}"


def _json_old_compat(actual, frozen, path: str = "") -> tuple[bool, str]:
    """冻结（旧）键值逐一相等 + 新键 ⊆ 白名单（强不变量 1：蒸馏不破坏 export 全量）。"""
    if isinstance(frozen, dict):
        if not isinstance(actual, dict):
            return False, f"{path or 'root'}: {type(actual).__name__} != dict"
        for k, v in frozen.items():
            good, why = _json_old_compat(actual.get(k, _JSON_MISSING), v, f"{path}.{k}")
            if not good:
                return False, why
        extra = set(actual) - set(frozen)
        if not extra <= _NEW_KEY_WHITELIST:
            return False, f"{path}: 白名单外新键 {sorted(extra - _NEW_KEY_WHITELIST)}"
        return True, ""
    if isinstance(frozen, list):
        if not isinstance(actual, list) or len(actual) != len(frozen):
            la = len(actual) if isinstance(actual, list) else "?"
            return False, f"{path}: list len {la} != {len(frozen)}"
        for i, (a, f) in enumerate(zip(actual, frozen)):
            good, why = _json_old_compat(a, f, f"{path}[{i}]")
            if not good:
                return False, why
        return True, ""
    if actual is _JSON_MISSING:
        return False, f"{path}: 键缺失（frozen={frozen!r}）"
    if actual != frozen:
        return False, f"{path}: {actual!r} != {frozen!r}"
    return True, ""


_LATEST_BASE = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
_LATEST_RID = "e5" * 16
_LATEST_CLAIM = "f6" * 16


def _latest_rows() -> tuple[dict, dict, list[dict]]:
    """250 种子组成钉死（plan 审 r1 P2-2，改组成＝改判别力）：全 kind=note；
    severity 按 seq 奇偶交替（偶=info、奇=attention）；边界 title 固定
    seq50="e50"(info) / seq51="e51"(attention) / seq250="e250"(info)；
    低 severity 负判别 seq52/54（info）须在结果内。"""
    req = {
        "id": _LATEST_RID, "source": "manual", "source_ref": None,
        "title": "l-latest-250", "description": None, "acceptance": [],
        "state": "CLAIMED", "awaiting_human": None,
        "created_at": _LATEST_BASE, "updated_at": _LATEST_BASE + timedelta(minutes=250),
    }
    claim = {
        "id": _LATEST_CLAIM, "requirement_id": _LATEST_RID, "agent_name": "l-latest-agent",
        "agent_conn": "l-latest-conn", "started_at": _LATEST_BASE,
        "lease_expires_at": _LATEST_BASE + timedelta(days=365),
        "last_activity_at": _LATEST_BASE + timedelta(minutes=250),
        "ended_at": None, "release_reason": None,
    }
    boundary = {50: "e50", 51: "e51", 250: "e250"}
    events = []
    for seq in range(1, 251):
        events.append({
            "id": f"0e{seq:03d}" + "0" * 27,
            "requirement_id": _LATEST_RID, "claim_id": _LATEST_CLAIM,
            "subtask_id": None, "milestone_id": None,
            "kind": "note", "severity": "info" if seq % 2 == 0 else "attention",
            "title": boundary.get(seq, f"n{seq}"), "content": None, "payload": None,
            "actor_surface": "mcp", "actor_conn": "l-latest-conn",
            "seq": seq, "ts": _LATEST_BASE + timedelta(minutes=seq),
        })
    return req, claim, events


def l_latest_first():
    print("== R3.1: get_task_detail 最新 200（seq 升序）+ 先 limit 后 filter + 无读侧 severity 过滤 + export 全量 250")
    db = new_db()
    # (A) 进程内直 SQL 种子（bench.py 模式：seq 同步 seq_counter、datetime 绑定参数）
    prev, akdb, models, _ops, _view = _ak_import(db)
    try:
        req, claim, events = _latest_rows()

        async def _seed():
            import sqlalchemy

            await akdb.ensure_schema()
            Requirement, Claim, _Sub, _Ms, Event = models
            factory = akdb.get_session_factory()
            try:
                async with factory() as s:
                    await s.execute(sqlalchemy.insert(Requirement), [req])
                    await s.execute(sqlalchemy.insert(Claim), [claim])
                    await s.execute(sqlalchemy.insert(Event), events)
                    await s.execute(
                        sqlalchemy.text("UPDATE seq_counter SET value = :v WHERE id = 1"), {"v": 250}
                    )
                    await s.commit()
            finally:
                await _ak_dispose(akdb)

        asyncio.run(_seed())
    finally:
        _ak_restore(prev)
    # (B) MCP get_task_detail：最新 200
    m = MCP(db).start()
    try:
        res = m.call_ok("get_task_detail", {"requirement_id": _LATEST_RID})
        evs = res["events"]
        seqs = [e["seq"] for e in evs]
        ok("l_latest(i): 恰好 200 条", len(evs) == 200, f"len={len(evs)}")
        ok("l_latest(ii): seq 区间 [51,250] 且升序（最新 200）",
           seqs == list(range(51, 251)),
           f"min={seqs[0] if seqs else '-'} max={seqs[-1] if seqs else '-'} n={len(seqs)}")
        titles = {e["title"] for e in evs}
        ok("l_latest(iii): 边界 e51/e250 在场、e50 不在场",
           "e51" in titles and "e250" in titles and "e50" not in titles,
           f"e-边界在场={sorted(t for t in titles if t.startswith('e'))}")
        ok("l_latest(iv): 低 severity 负判别 seq52/54 在场（读侧不按 severity 过滤）",
           52 in seqs and 54 in seqs, f"52 in={52 in seqs} 54 in={54 in seqs}")
        bad_kind = [e["seq"] for e in evs if e["kind"] != "note"]
        ok("l_latest(v): 200 条全 kind=note（先 limit 后 filter，全命中）",
           not bad_kind, f"非 note seqs={bad_kind[:5]}")
        bad_aud = [e["seq"] for e in evs if e.get("audience") != "human"]
        ok("l_latest(vi): 事件行带 audience（全 note -> human）",
           not bad_aud, f"非 human seqs={bad_aud[:5]}")
    finally:
        m.close()
    # (C) 进程内 view.detail：kinds 过滤与 event_limit 并存（先 limit 后 filter 口径）
    prev2, akdb2, _models2, _ops2, view2 = _ak_import(db)
    try:

        async def _filter():
            factory = akdb2.get_session_factory()
            try:
                return await akdb2.run_op(
                    factory, view2.detail, is_write=False,
                    requirement_id=_LATEST_RID, kinds=["note"], event_limit=200,
                    actor_surface="test", actor_conn="test",
                )
            finally:
                await _ak_dispose(akdb2)

        detail = asyncio.run(_filter())
    finally:
        _ak_restore(prev2)
    ok("l_latest(vii): kinds=['note'] 过滤后仍 200（先 limit 后 filter）",
       len(detail["events"]) == 200, f"len={len(detail['events'])}")
    # (D) CLI export json 全量
    res = cli(db, "export", "--requirement-id", _LATEST_RID, "--format", "json")
    ok("l_latest(viii): export json rc=0", res.returncode == 0, res.stderr[-200:])
    data = json.loads(res.stdout) if res.returncode == 0 else {}
    n_ev = len((data.get("requirement") or {}).get("events") or [])
    ok("l_latest(viii): export 全量 250（无 limit）", n_ev == 250, f"n={n_ev}")


def l_audience():
    print("== R3.2: audience 单点派生 event_audience（5 簿记 / 7 人面 / 未知 kind 保守人面）")
    prev, _akdb, _models, _ops, view = _ak_import(None)
    try:
        ea = view.event_audience
        for k in ("state_change", "decomposition", "reconcile", "release", "renew"):
            ok(f"l_audience: {k} -> bookkeeping", ea(k) == "bookkeeping", repr(ea(k)))
        for k in ("progress_note", "decision", "deviation", "review_request", "approval", "note", "risk"):
            ok(f"l_audience: {k} -> human", ea(k) == "human", repr(ea(k)))
        ok("l_audience: 未知 kind future_x -> human（保守：宁可人面多显示）",
           ea("future_x") == "human", repr(ea("future_x")))
    finally:
        _ak_restore(prev)


def l_export_stable():
    print("== R3.3: export 回归 oracle——md/csv byte-identical + json 旧键相等、新键白名单")
    db = new_db()
    prev, akdb, models, ops, _view = _ak_import(db)
    try:

        async def _all():
            await akdb.ensure_schema()
            factory = akdb.get_session_factory()
            async with factory() as s:
                await _seed_fixture(s, models)
            try:
                md = await akdb.run_op(factory, ops.export_data, is_write=False,
                                       requirement_id=RID, fmt="markdown",
                                       actor_surface="test", actor_conn="test")
                csv_ = await akdb.run_op(factory, ops.export_data, is_write=False,
                                         requirement_id=RID, fmt="csv",
                                         actor_surface="test", actor_conn="test")
                data = await akdb.run_op(factory, ops.export_data, is_write=False,
                                         requirement_id=RID, fmt="json",
                                         actor_surface="test", actor_conn="test")
            finally:
                await _ak_dispose(akdb)
            return md, csv_, data

        md, csv_, data = asyncio.run(_all())
        ok("l_export_stable(i): markdown 与冻结基线 byte-identical",
           md == MD_FROZEN, _diff_detail(md, MD_FROZEN))
        ok("l_export_stable(ii): csv 与冻结基线 byte-identical",
           csv_ == CSV_FROZEN, _diff_detail(csv_, CSV_FROZEN))
        good, why = _json_old_compat(data, JSON_FROZEN)
        ok("l_export_stable(iii): json 旧键值逐一相等 + 新键 ⊆ {history_note, state_at_event, audience}",
           good, why)
    finally:
        _ak_restore(prev)
