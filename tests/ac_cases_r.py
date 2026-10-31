"""B10 审查拒绝的状态路径（BCD b10-review-reject.md v1，S1-S11 / E1-E11）：
CLAIMED+待审(kind=review) -> REOPEN（拒因/指向/轮次可观测、可计数；同事务结束认领、
不续租、清 marker）+ 零输入 reject（候选仅 kind=review）+ REST 对等 + agent 面边界。

oracle 纪律：断言逐字引 BCD 场景号；DB 事后 sqlite3 直查（query）；真实子进程
（MCP stdio / uvicorn / CLI），禁 mock。零输入用例用 case-local helper 钉
stdin=subprocess.DEVNULL（先例：ac_cases_n.py 头 docstring + _run_cli_nul——父进程
stdin 继承会在本地终端多条待决时误走 tty 分支阻塞）。
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ac_lib import (CLI, MCP, REST, REPO_ROOT, TIMEOUT, VENV_PY, cli, cli_ok, cli_err,
                    env_for, new_db, ok, query, seed_req)


def _run_cli_nul(db: Path, args: list[str]) -> subprocess.CompletedProcess:
    """CLI 子进程钉 stdin=DEVNULL（零输入非 tty 确定性；ac_cases_n._run_cli_nul 同模式）。"""
    return subprocess.run(
        [str(VENV_PY), str(CLI), *args],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
        env=env_for(db), cwd=str(REPO_ROOT), timeout=TIMEOUT,
    )


def _seed_review(db: Path, label: str, *, with_subtask: bool = False,
                 anchors: str | None = None) -> tuple[str, str | None]:
    """S1 前置：seed + claim + request_review（awaiting_human kind=review，round=1）。
    返回 (requirement_id, subtask_id 或 None)。"""
    if anchors is not None:
        rid = cli_ok(db, "new", "--title", label, "--acceptance", anchors)["requirement_id"]
    else:
        rid = seed_req(db, label)
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    st_id = None
    if with_subtask:
        st = m.call_ok("add_subtask", {"requirement_id": rid, "title": "impl", "ordinal": 1,
                                       "acceptance": [{"item": "works"}]})
        st_id = st["subtask_id"]
        m.call_ok("request_review", {
            "requirement_id": rid, "evidence": {"test_summary": "t"}, "summary_line": "r 交接",
            "assessments": [{"subtask_id": st_id, "items": [{"item": "works", "state": "met"}]}]})
    else:
        m.call_ok("request_review", {"requirement_id": rid, "evidence": {"test_summary": "t"},
                                     "summary_line": "r 交接"})
    m.close()
    return rid, st_id


def _ev(db: Path, rid: str) -> list:
    return query(db, "SELECT kind, severity, actor_surface, actor_conn, payload FROM events "
               "WHERE requirement_id=? ORDER BY seq", (rid,))


def _pl(r) -> dict:
    return json.loads(r["payload"]) if r["payload"] else {}


def _marker(db: Path, rid: str) -> dict | None:
    row = query(db, "SELECT awaiting_human FROM requirements WHERE id=?", (rid,))[0]
    return json.loads(row["awaiting_human"]) if row["awaiting_human"] else None


def r_happy():
    """S1/E1：评审拒绝可观测——REOPEN + 两事件 + 认领结束（review_rejected）+ marker 清除。"""
    db = new_db()
    rid, _ = _seed_review(db, "r-happy", with_subtask=True)
    m = MCP(db).start()
    res = cli_ok(db, "reject", "--requirement-id", rid, "--reason", "复验发现缺陷：X")
    ok("r_happy: reject rc0 + REOPEN + round=1",
       res.get("state") == "REOPEN" and res.get("round") == 1, str(res))
    row = query(db, "SELECT state FROM requirements WHERE id=?", (rid,))[0]
    ok("r_happy: state=REOPEN", row["state"] == "REOPEN", str(dict(row)))
    rows = _ev(db, rid)
    sc = [r for r in rows if r["kind"] == "state_change" and _pl(r).get("to") == "REOPEN"]
    ok("r_happy: state_change(CLAIMED->REOPEN) payload 含 reason",
       len(sc) == 1 and _pl(sc[0]).get("from") == "CLAIMED"
       and _pl(sc[0]).get("reason") == "复验发现缺陷：X",
       str([dict(r) for r in sc]))
    rj = [r for r in rows if r["kind"] == "review_reject"]
    ok("r_happy: review_reject(attention) payload={reason,target:null,round:1}",
       len(rj) == 1 and rj[0]["severity"] == "attention"
       and _pl(rj[0]) == {"reason": "复验发现缺陷：X", "target": None, "round": 1},
       str([dict(r) for r in rj]))
    claim = query(db, "SELECT ended_at IS NULL AS active, release_reason "
                       "FROM claims WHERE requirement_id=?", (rid,))[0]
    ok("r_happy: claim ended + release_reason=review_rejected",
       claim["active"] == 0 and claim["release_reason"] == "review_rejected", str(dict(claim)))
    d = m.call_ok("get_task_detail", {"requirement_id": rid})
    ok("r_happy: get_task_detail awaiting_human 已清除", d["awaiting_human"] is None)
    m.close()


def r_target():
    """S6/E6：指向校验——子任务 id（归一）/锚 id 成功；垃圾 -> invalid_record + 可用清单 + 零写。"""
    db = new_db()
    # 垃圾 target：零写入（state 仍 CLAIMED、无 review_reject 事件、marker 仍在）
    r1, st1 = _seed_review(db, "r-tgt-garbage", with_subtask=True, anchors='[{"item": "A1"}]')
    before = query(db, "SELECT COUNT(*) AS n FROM events WHERE requirement_id=?", (r1,))[0]["n"]
    code, msg = cli_err(db, "reject", "--requirement-id", r1, "--reason", "x",
                        "--target", "no-such-id")
    ok("r_target: 垃圾 target -> invalid_record", code == "invalid_record", code)
    ok("r_target: 错误消息含可用清单（子任务 id + 锚 id）", st1 in msg and "a1" in msg, msg[:300])
    after = query(db, "SELECT COUNT(*) AS n FROM events WHERE requirement_id=?", (r1,))[0]["n"]
    state = query(db, "SELECT state FROM requirements WHERE id=?", (r1,))[0]["state"]
    ok("r_target: 垃圾 target 零写入（state 仍 CLAIMED、marker 仍在）",
       before == after and state == "CLAIMED" and _marker(db, r1) is not None,
       f"{before}->{after} state={state}")

    r2, st2 = _seed_review(db, "r-tgt-subtask", with_subtask=True)
    cli_ok(db, "reject", "--requirement-id", r2, "--reason", "x", "--target", st2)
    p = _pl([r for r in _ev(db, r2) if r["kind"] == "review_reject"][0])
    ok("r_target: --target 子任务 id -> payload.target=归一 id", p.get("target") == st2, str(p))

    r3, _ = _seed_review(db, "r-tgt-anchor", anchors='[{"item": "A1"}]')
    cli_ok(db, "reject", "--requirement-id", r3, "--reason", "x", "--target", "a1")
    p = _pl([r for r in _ev(db, r3) if r["kind"] == "review_reject"][0])
    ok("r_target: --target a1（验收锚）-> payload.target=\"a1\"", p.get("target") == "a1", str(p))


def r_no_reason():
    """S2/E2：拒因必填——缺/空 reason -> invalid_record 零写入。"""
    for i, reason_args in enumerate(((), ("--reason", "   "))):
        db = new_db()
        rid, _ = _seed_review(db, f"r-noreason-{i}")
        before = query(db, "SELECT COUNT(*) AS n FROM events WHERE requirement_id=?", (rid,))[0]["n"]
        res = cli(db, "reject", "--requirement-id", rid, *reason_args)
        after = query(db, "SELECT COUNT(*) AS n FROM events WHERE requirement_id=?", (rid,))[0]["n"]
        state = query(db, "SELECT state FROM requirements WHERE id=?", (rid,))[0]["state"]
        ok(f"r_no_reason[{i}]: {'缺' if not reason_args else '空'} reason -> rc1 invalid_record 零写入",
           res.returncode == 1 and res.stderr.strip().startswith("invalid_record")
           and before == after and state == "CLAIMED" and _marker(db, rid) is not None,
           f"rc={res.returncode} stderr={res.stderr[:120]} {before}->{after} state={state}")


def r_illegal_states():
    """S3/S4/S5（E3/E4/E5）：状态前置 + 无待审标记 + 重复拒 -> illegal_state 零写入。"""
    db = new_db()
    # OPEN 未认领
    r_open = seed_req(db, "r-illegal-open")
    code, _ = cli_err(db, "reject", "--requirement-id", r_open, "--reason", "x")
    ok("r_illegal: OPEN 未认领 -> illegal_state", code == "illegal_state", code)
    # OPEN + 空白 reason（P4 P1-1：语义必填先于状态校验，PRD §4.2 口径，与 release 同惯例）
    r_blank = seed_req(db, "r-illegal-blankreason")
    before = _ev(db, r_blank)
    res = cli(db, "reject", "--requirement-id", r_blank, "--reason", "  ")
    after = _ev(db, r_blank)
    state = query(db, "SELECT state FROM requirements WHERE id=?", (r_blank,))[0]["state"]
    ok("r_illegal: OPEN + 空白 reason -> invalid_record（先于状态校验，PRD §4.2 口径）",
       res.returncode == 1 and res.stderr.strip().startswith("invalid_record")
       and "illegal_state" not in res.stderr,
       f"rc={res.returncode} stderr={res.stderr[:120]}")
    ok("r_illegal: OPEN + 空白 reason 零写入（state/事件链逐字不变）",
       before == after and state == "OPEN" and _marker(db, r_blank) is None,
       f"state={state} marker={_marker(db, r_blank)} events {len(before)}->{len(after)}")
    # BLOCKED（claim 后 mark_blocked）
    r_blk = seed_req(db, "r-illegal-blocked")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": r_blk, "agent_name": "a"})
    m.call_ok("mark_blocked", {"requirement_id": r_blk, "reason": "等人裁决"})
    m.close()
    before = _ev(db, r_blk)
    code, _ = cli_err(db, "reject", "--requirement-id", r_blk, "--reason", "x")
    after = _ev(db, r_blk)
    state = query(db, "SELECT state FROM requirements WHERE id=?", (r_blk,))[0]["state"]
    ok("r_illegal: BLOCKED -> illegal_state 零写入",
       code == "illegal_state" and len(before) == len(after) and state == "BLOCKED"
       and not any(e["kind"] == "review_reject" for e in after),
       f"{code} events {len(before)}->{len(after)} state={state}")
    # CLAIMED 无标记（从未 request_review）
    r_nm = seed_req(db, "r-illegal-nomarker")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": r_nm, "agent_name": "a"})
    m.close()
    before = _ev(db, r_nm)
    code, _ = cli_err(db, "reject", "--requirement-id", r_nm, "--reason", "x")
    after = _ev(db, r_nm)
    ok("r_illegal: CLAIMED 无待审标记 -> illegal_state 零写入",
       code == "illegal_state" and len(before) == len(after), f"{code} {len(before)}->{len(after)}")
    # DONE（先 approve）
    r_done, _ = _seed_review(db, "r-illegal-done")
    cli_ok(db, "approve", "--requirement-id", r_done)
    code, _ = cli_err(db, "reject", "--requirement-id", r_done, "--reason", "x")
    ok("r_illegal: DONE -> illegal_state", code == "illegal_state", code)
    # 重复拒（S1 已发生，state=REOPEN，同 S5）
    r_re, _ = _seed_review(db, "r-illegal-reopen")
    cli_ok(db, "reject", "--requirement-id", r_re, "--reason", "第一次拒")
    n1 = len([e for e in _ev(db, r_re) if e["kind"] == "review_reject"])
    code, _ = cli_err(db, "reject", "--requirement-id", r_re, "--reason", "第二次拒")
    n2 = len([e for e in _ev(db, r_re) if e["kind"] == "review_reject"])
    ok("r_illegal: 重复拒（REOPEN）-> illegal_state 且不新增 review_reject（轮次计数不污染）",
       code == "illegal_state" and n1 == 1 and n2 == 1, f"{code} review_reject {n1}->{n2}")


def r_rounds():
    """S7/E7：轮次可区分——交接 1/2/3 的 marker 与事件均带 round=1/2/3；拒事件 round 读被拒交接标记。"""
    db = new_db()
    rid, _ = _seed_review(db, "r-rounds")
    m = MCP(db).start()
    ok("r_rounds: 交接#1 marker.round=1 + 事件 payload.round=1",
       (_marker(db, rid) or {}).get("round") == 1
       and _pl([e for e in _ev(db, rid) if e["kind"] == "review_request"][0]).get("round") == 1,
       str(_marker(db, rid)))
    res = cli_ok(db, "reject", "--requirement-id", rid, "--reason", "拒#1")
    p = _pl([e for e in _ev(db, rid) if e["kind"] == "review_reject"][-1])
    ok("r_rounds: reject#1 payload.round=1", res.get("round") == 1 and p.get("round") == 1, str(p))
    cli_ok(db, "reopen", "--requirement-id", rid, "--continue")
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a2"})
    m.call_ok("request_review", {"requirement_id": rid, "evidence": {"test_summary": "t"},
                                 "summary_line": "第 2 轮交接"})
    ok("r_rounds: 交接#2 marker.round=2 + 事件 payload.round=2",
       (_marker(db, rid) or {}).get("round") == 2
       and _pl([e for e in _ev(db, rid) if e["kind"] == "review_request"][-1]).get("round") == 2,
       str(_marker(db, rid)))
    cli_ok(db, "reject", "--requirement-id", rid, "--reason", "拒#2")
    p = _pl([e for e in _ev(db, rid) if e["kind"] == "review_reject"][-1])
    ok("r_rounds: reject#2 payload.round=2", p.get("round") == 2, str(p))
    cli_ok(db, "reopen", "--requirement-id", rid, "--continue")
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a3"})
    m.call_ok("request_review", {"requirement_id": rid, "evidence": {"test_summary": "t"},
                                 "summary_line": "第 3 轮交接"})
    ok("r_rounds: 交接#3 round=3（标记与事件同值）",
       (_marker(db, rid) or {}).get("round") == 3
       and _pl([e for e in _ev(db, rid) if e["kind"] == "review_request"][-1]).get("round") == 3,
       str(_marker(db, rid)))
    m.close()


def r_delegated():
    """S8/E8：受托代执行——两事件 actor_surface=delegated + payload.delegated{kind,basis}。"""
    db = new_db()
    rid, _ = _seed_review(db, "r-delegated")
    cli_ok(db, "reject", "--requirement-id", rid, "--reason", "复验不达标",
           "--on-behalf", "statement:复验不达标")
    want = {"kind": "statement", "basis": "复验不达标"}
    rows = _ev(db, rid)
    sc = [r for r in rows if r["kind"] == "state_change" and _pl(r).get("to") == "REOPEN"]
    ok("r_delegated: state_change(CLAIMED->REOPEN) delegated + payload.delegated",
       len(sc) == 1 and sc[0]["actor_surface"] == "delegated" and _pl(sc[0]).get("delegated") == want,
       str([dict(r) for r in sc]))
    rj = [r for r in rows if r["kind"] == "review_reject"]
    ok("r_delegated: review_reject delegated + payload.delegated",
       len(rj) == 1 and rj[0]["actor_surface"] == "delegated" and _pl(rj[0]).get("delegated") == want,
       str([dict(r) for r in rj]))


def r_lease():
    """S9/E9：拒后返工=新认领周期——旧认领 lease_expires_at 未被改写（不续租）；新认领全新 2h 窗口。"""
    db = new_db()
    rid, _ = _seed_review(db, "r-lease")
    old = query(db, "SELECT id, lease_expires_at FROM claims WHERE requirement_id=?", (rid,))[0]
    t_reject = datetime.now(timezone.utc)
    cli_ok(db, "reject", "--requirement-id", rid, "--reason", "x")
    row = query(db, "SELECT ended_at IS NULL AS active, lease_expires_at, release_reason "
                      "FROM claims WHERE requirement_id=?", (rid,))[0]
    ok("r_lease: 旧认领 ended + lease_expires_at 未被 reject 改写（不续租）",
       row["active"] == 0 and row["lease_expires_at"] == old["lease_expires_at"]
       and row["release_reason"] == "review_rejected",
       f"old={old['lease_expires_at']} after={row['lease_expires_at']}")
    cli_ok(db, "reopen", "--requirement-id", rid, "--continue")
    m = MCP(db).start()
    res = m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "again"})
    m.close()
    new_exp = datetime.fromisoformat(res["lease_expires_at"])
    ok("r_lease: 新认领全新 2h 窗口（lease > 拒时刻 + 7190s）",
       new_exp > t_reject + timedelta(seconds=7190),
       f"new={new_exp.isoformat()} reject_at={t_reject.isoformat()}")


def r_mcp_surface():
    """S10/E10：agent 面边界——MCP 14 工具集不含 reject/reject_review（与 ac3 同口径）。"""
    db = new_db()
    m = MCP(db).start()
    tools = m.list_tools()
    expected = {
        "new_requirement", "set_expectations",
        "list_tasks", "get_task_detail", "claim_task", "add_subtask", "update_subtask",
        "add_milestone", "update_milestone", "add_record", "update_progress",
        "request_review", "mark_blocked", "list_awaiting",
    }
    ok("r_mcp: 14 工具精确集（ac3 同口径，I4 回归锚）", set(tools) == expected, str(sorted(tools)))
    ok("r_mcp: 工具面无 reject/reject_review（人面 op 不进 agent 面）",
       not ({"reject", "reject_review"} & set(tools)), str(sorted(tools)))
    m.close()


def r_rest():
    """S11：REST 对等——POST /requirements/{id}/reject 与 CLI 同 service 层语义；错误映射 409/422/404。"""
    db = new_db()
    rid, _ = _seed_review(db, "r-rest")
    rest = REST(db).start()
    try:
        code, body = rest.req("POST", f"/requirements/{rid}/reject", body={"reason": "REST 复验不通过"})
        ok("r_rest: reject 200 REOPEN", code == 200 and body.get("state") == "REOPEN", f"{code} {body}")
    finally:
        rest.stop()
    p = _pl([e for e in _ev(db, rid) if e["kind"] == "review_reject"][0])
    ok("r_rest: review_reject 事件 payload round=1 target=null",
       p.get("round") == 1 and p.get("target") is None, str(p))

    db2 = new_db()
    r_open = seed_req(db2, "r-rest-open")
    rest2 = REST(db2).start()
    try:
        code, body = rest2.req("POST", f"/requirements/{r_open}/reject", body={"reason": "x"})
        ok("r_rest: reject(OPEN) -> 409 illegal_state",
           code == 409 and body.get("code") == "illegal_state", f"{code} {body}")
        r2, _ = _seed_review(db2, "r-rest-empty")
        code, body = rest2.req("POST", f"/requirements/{r2}/reject", body={"reason": "  "})
        ok("r_rest: 空 reason -> 422 invalid_record",
           code == 422 and body.get("code") == "invalid_record", f"{code} {body}")
        missing = "deadbeef" + "0" * 24
        code, body = rest2.req("POST", f"/requirements/{missing}/reject", body={"reason": "x"})
        ok("r_rest: 不存在 id -> 404 not_found",
           code == 404 and body.get("code") == "not_found", f"{code} {body}")
    finally:
        rest2.stop()


def r_zero_input():
    """E11：零输入 reject——候选仅 kind=review 待审（blocked 不混入）；文案「无待审项」
    区别于 approve/release 的「无待决项」。"""
    # 0 条待审（库内另有 blocked 待决）-> 无待审项 rc0 零写
    db = new_db()
    rb = seed_req(db, "z0-blocked")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rb, "agent_name": "a"})
    m.call_ok("mark_blocked", {"requirement_id": rb, "reason": "等人裁决"})
    m.close()
    before = query(db, "SELECT COUNT(*) AS n FROM events")[0]["n"]
    res = _run_cli_nul(db, ["reject", "--reason", "x"])
    after = query(db, "SELECT COUNT(*) AS n FROM events")[0]["n"]
    ok("z0: 0 条待审（blocked 在库）-> 无待审项 rc0 零写",
       res.returncode == 0 and "无待审项" in res.stdout and before == after,
       f"rc={res.returncode} stdout={res.stdout[:100]}")

    # 1 条 review 待审 + 1 条 blocked 待审同库 -> 零输入命中 review 条（blocked 不进候选）
    db2 = new_db()
    rr, _ = _seed_review(db2, "z1-review")
    rb2 = seed_req(db2, "z1-blocked")
    m = MCP(db2).start()
    m.call_ok("claim_task", {"requirement_id": rb2, "agent_name": "b"})
    m.call_ok("mark_blocked", {"requirement_id": rb2, "reason": "等人裁决"})
    m.close()
    res = _run_cli_nul(db2, ["reject", "--reason", "复验发现缺陷"])
    state_r = query(db2, "SELECT state FROM requirements WHERE id=?", (rr,))[0]["state"]
    state_b = query(db2, "SELECT state FROM requirements WHERE id=?", (rb2,))[0]["state"]
    ok("z1: 1 条待审+1 条 blocked 同库 -> 零输入命中 review（blocked 不进候选）",
       res.returncode == 0 and state_r == "REOPEN" and state_b == "BLOCKED",
       f"rc={res.returncode} review={state_r} blocked={state_b} stderr={res.stderr[:120]}")

    # 2 条 review 待审 + 非交互 stdin -> rc1 列候选拒（零写）
    db3 = new_db()
    r_a, _ = _seed_review(db3, "z2-a")
    r_b, _ = _seed_review(db3, "z2-b")
    before = query(db3, "SELECT COUNT(*) AS n FROM events")[0]["n"]
    res = _run_cli_nul(db3, ["reject", "--reason", "x"])
    after = query(db3, "SELECT COUNT(*) AS n FROM events")[0]["n"]
    ok("z2: 2 条待审非交互 -> rc1 列候选拒零写（头部「多条待审项」，I8 过滤口径）",
       res.returncode == 1 and before == after
       and r_a[:8] in res.stderr and r_b[:8] in res.stderr
       and "多条待审项" in res.stderr and "Traceback" not in res.stderr,
       f"rc={res.returncode} {before}->{after} stderr={res.stderr[:300]}")
