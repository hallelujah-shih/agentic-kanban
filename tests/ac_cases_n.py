"""delegated 受托面 + CLI 零输入用例（spec 2026-10-27-delegated-confirm-design.md §7，n1-n28 + n_parse）。

oracle 纪律：断言引 spec/BCD；DB 事后 sqlite3 直查（query）；真实子进程（MCP stdio /
uvicorn / CLI），禁 mock。零输入用例（n19-n24）用 case-local helper 钉
stdin=subprocess.DEVNULL（非 tty 确定性，R1 实证：ac_lib.cli() 继承父进程 stdin，
本地终端跑套件多条待决会阻塞 tty 分支）；禁改 tests/ac_lib.py。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ac_lib import (CLI, MCP, REST, REPO_ROOT, TIMEOUT, VENV_PY, cli, cli_ok,
                    env_for, new_db, ok, query, seed_req)


def _mk_awaiting(db: Path, n: int, prefix: str = "z") -> list[str]:
    """造 n 条 awaiting（CLAIMED + request_review(kind=review)）。返回 32-hex id 列表。"""
    m = MCP(db).start()
    ids = []
    for i in range(n):
        r = seed_req(db, f"{prefix}-awaiting-{i}")
        m.call_ok("claim_task", {"requirement_id": r, "agent_name": "a"})
        m.call_ok("request_review",
                  {"requirement_id": r, "evidence": {"test_summary": "s"}, "summary_line": "交接"})
        ids.append(r)
    m.close()
    return ids


def n_parse():
    """parse_delegation 单点（直接 import，ac_cases_h _months_ago 先例；无 DB）。"""
    from agent_kanban.errors import BusinessError
    from agent_kanban.services.identity import DELEGATION_EXAMPLE, parse_delegation

    def _err(fn, *a):
        try:
            fn(*a)
            return None
        except BusinessError as e:
            return e

    ok("n_parse(1): None -> None（无参现行为）", parse_delegation(None) is None)
    ok("n_parse(2): 合法 str", parse_delegation("statement:user said PR merged in session")
       == {"kind": "statement", "basis": "user said PR merged in session"})
    ok("n_parse(3): basis 可含冒号（首个 : partition）", parse_delegation("statement:a:b")
       == {"kind": "statement", "basis": "a:b"})
    ok("n_parse(4): kind 大小写/空白归一", parse_delegation("  ACTION : x ")
       == {"kind": "action", "basis": "x"})
    e = _err(parse_delegation, "foo")
    ok("n_parse(5): 无冒号 -> invalid_record + 参数名 + 示例",
       e is not None and e.code == "invalid_record" and "on-behalf" in e.message
       and DELEGATION_EXAMPLE in e.message, str(getattr(e, "message", e)))
    e = _err(parse_delegation, "badkind:x")
    ok("n_parse(6): kind 越枚举 -> invalid_record + got 原值",
       e is not None and e.code == "invalid_record" and "badkind" in e.message
       and DELEGATION_EXAMPLE in e.message, str(getattr(e, "message", e)))
    e = _err(parse_delegation, "statement:")
    ok("n_parse(7): basis 空 -> invalid_record non-empty",
       e is not None and e.code == "invalid_record" and "non-empty" in e.message
       and DELEGATION_EXAMPLE in e.message, str(getattr(e, "message", e)))
    ok("n_parse(8): dict 合法", parse_delegation({"kind": "action", "basis": "PR #8 merged (5089bfe)"})
       == {"kind": "action", "basis": "PR #8 merged (5089bfe)"})
    e = _err(parse_delegation, {"kind": "foo", "basis": "x"})
    ok("n_parse(9): dict kind 越枚举 -> invalid_record",
       e is not None and e.code == "invalid_record", str(getattr(e, "message", e)))
    e = _err(parse_delegation, {"kind": "statement"})
    ok("n_parse(10): dict 缺 basis -> invalid_record",
       e is not None and e.code == "invalid_record", str(getattr(e, "message", e)))


def _ev_rows(db: Path, rid: str):
    return query(db, "SELECT kind, actor_surface, actor_conn, payload FROM events WHERE requirement_id=?", (rid,))


def _pl(r):
    return json.loads(r["payload"]) if r["payload"] else {}


def n1():
    """delegated approve（CLAIMED->DONE 两条事件均带 payload.delegated）。"""
    db = new_db()
    rid = seed_req(db, "delegated approve")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.close()
    res = cli_ok(db, "approve", "--requirement-id", rid, "--on-behalf", "statement:测试表态")
    ok("n1: approve --on-behalf exit0 + DONE", res.get("state") == "DONE", str(res))
    rows = _ev_rows(db, rid)
    ap = [r for r in rows if r["kind"] == "approval"]
    want = {"kind": "statement", "basis": "测试表态"}
    ok("n1: approval 事件 delegated+cli+payload",
       len(ap) == 1 and ap[0]["actor_surface"] == "delegated" and ap[0]["actor_conn"] == "cli"
       and _pl(ap[0]).get("delegated") == want and _pl(ap[0]).get("state") == "DONE", str([dict(x) for x in ap]))
    sc = [r for r in rows if r["kind"] == "state_change" and _pl(r).get("to") == "DONE"]
    ok("n1: state_change(CLAIMED->DONE) delegated+payload",
       len(sc) == 1 and sc[0]["actor_surface"] == "delegated" and _pl(sc[0]).get("delegated") == want,
       str([dict(x) for x in sc]))


def n2():
    db = new_db()
    rid = seed_req(db, "delegated release")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.close()
    res = cli_ok(db, "release", "--requirement-id", rid, "--reason", "x",
                 "--on-behalf", "action:PR merged (abc123)")
    ok("n2: release --on-behalf OPEN", res.get("state") == "OPEN", str(res))
    rows = _ev_rows(db, rid)
    rel = [r for r in rows if r["kind"] == "release"]
    want = {"kind": "action", "basis": "PR merged (abc123)"}
    ok("n2: release 事件 delegated(action)+reason",
       len(rel) == 1 and rel[0]["actor_surface"] == "delegated" and _pl(rel[0]).get("delegated") == want
       and _pl(rel[0]).get("reason") == "x", str([dict(x) for x in rel]))
    sc = [r for r in rows if r["kind"] == "state_change" and _pl(r).get("to") == "OPEN"]
    ok("n2: state_change(CLAIMED->OPEN) delegated",
       len(sc) == 1 and sc[0]["actor_surface"] == "delegated" and _pl(sc[0]).get("delegated") == want,
       str([dict(x) for x in sc]))
    row = query(db, "SELECT release_reason FROM claims WHERE requirement_id=?", (rid,))[0]
    ok("n2: release_reason 不变", row["release_reason"] == "x", str(dict(row)))


def n3():
    db = new_db()
    rid = seed_req(db, "delegated note/renew")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.close()
    cli_ok(db, "note", "--requirement-id", rid, "--content", "note 内容", "--on-behalf", "statement:user 指示")
    r1 = query(db, "SELECT actor_surface, payload FROM events WHERE kind='note' AND requirement_id=?", (rid,))[0]
    ok("n3: note 事件 delegated + content 共存",
       r1["actor_surface"] == "delegated" and json.loads(r1["payload"]) == {
           "content": "note 内容", "delegated": {"kind": "statement", "basis": "user 指示"}}, str(dict(r1)))
    cli_ok(db, "renew", "--requirement-id", rid, "--on-behalf", "action:user 工作面操作")
    r2 = query(db, "SELECT actor_surface, payload FROM events WHERE kind='renew' AND requirement_id=?", (rid,))[0]
    ok("n3: renew 事件 delegated（新增 payload）",
       r2["actor_surface"] == "delegated" and json.loads(r2["payload"]) == {
           "delegated": {"kind": "action", "basis": "user 工作面操作"}}, str(dict(r2)))


def n4():
    db = new_db()
    rid = seed_req(db, "delegated reopen/abandon")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.call_ok("request_review", {"requirement_id": rid, "evidence": {"test_summary": "s"}, "summary_line": "交接"})
    m.close()
    cli_ok(db, "approve", "--requirement-id", rid)  # CLAIMED->DONE（无受托）
    cli_ok(db, "reopen", "--requirement-id", rid, "--on-behalf", "statement:user 说重做")
    sc1 = [r for r in _ev_rows(db, rid) if r["kind"] == "state_change" and _pl(r).get("to") == "REOPEN"]
    ok("n4: reopen state_change delegated",
       len(sc1) == 1 and sc1[0]["actor_surface"] == "delegated"
       and _pl(sc1[0]).get("delegated") == {"kind": "statement", "basis": "user 说重做"}, str([dict(x) for x in sc1]))
    cli_ok(db, "abandon", "--requirement-id", rid, "--to-state", "REJECTED", "--on-behalf", "statement:user 拒绝")
    sc2 = [r for r in _ev_rows(db, rid) if r["kind"] == "state_change" and _pl(r).get("to") == "REJECTED"]
    ok("n4: abandon state_change delegated",
       len(sc2) == 1 and sc2[0]["actor_surface"] == "delegated"
       and _pl(sc2[0]).get("delegated") == {"kind": "statement", "basis": "user 拒绝"}, str([dict(x) for x in sc2]))


def n5():
    db = new_db()
    ms = MCP(db, extra={"AGENT_KANBAN_LEASE_SECONDS": "-1"}).start()  # STALE 确定性（ac_cases_c 先例）
    stale = []
    for i in range(2):
        r = seed_req(db, f"stale-delegated-{i}")
        ms.call_ok("claim_task", {"requirement_id": r, "agent_name": "s"})
        stale.append(r)
    ms.close()
    res = cli_ok(db, "release", "--all-stale", "--on-behalf", "action:批量代执行")
    ok("n5: 2 STALE 全 ok（部分失败语义不变）",
       len(res["released"]) == 2 and all(x["ok"] for x in res["released"]), str(res))
    for r in stale:
        row = query(db, "SELECT actor_surface, payload FROM events WHERE kind='release' AND requirement_id=?", (r,))[0]
        ok(f"n5[{r[:8]}]: release 事件 delegated(action)",
           row["actor_surface"] == "delegated"
           and json.loads(row["payload"]).get("delegated") == {"kind": "action", "basis": "批量代执行"},
           str(dict(row)))


def _bad_flag_case(flag: str, label: str):
    """n6-n8 共用：0/1/2 待决三形态下非法 flag 均先拒（parse 先于读候选，R5）。
    断言用 DELEGATION_EXAMPLE（spec §2.1 三种非法消息均含该示例；kind/basis 形态
    消息逐字为 'delegated kind must be ...' / 'delegated basis must be ...'，
    不含 on-behalf 字样，勿按它断言）。"""
    from agent_kanban.services.identity import DELEGATION_EXAMPLE
    for n in (0, 1, 2):
        db = new_db()
        _mk_awaiting(db, n)
        # T2 阶段 approve --requirement-id 仍 required（T3 才改可选）：携真实 id，
        # id 不参与解析（parse 是 handler 首语句，先于任何 DB 操作）。
        rid = seed_req(db, f"{label}-rid")
        before = query(db, "SELECT COUNT(*) AS n FROM events")[0]["n"]
        res = cli(db, "approve", "--requirement-id", rid, "--on-behalf", flag)
        after = query(db, "SELECT COUNT(*) AS n FROM events")[0]["n"]
        ok(f"{label}[{n}待决]: {flag!r} -> invalid_record 零写 exit1 无Traceback",
           res.returncode == 1 and res.stderr.strip().startswith("invalid_record")
           and DELEGATION_EXAMPLE in res.stderr and "Traceback" not in res.stderr
           and before == after,
           f"rc={res.returncode} stderr={res.stderr[:200]}")


def n6():
    _bad_flag_case("foo", "n6")  # 无冒号


def n7():
    _bad_flag_case("badkind:x", "n7")  # kind 越枚举


def n8():
    _bad_flag_case("statement:", "n8")  # basis 空


def n9():
    db = new_db()
    rid = seed_req(db, "regress no-flag")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.close()
    cli_ok(db, "approve", "--requirement-id", rid)  # 无 --on-behalf
    row = query(db, "SELECT actor_surface, payload FROM events WHERE kind='approval' AND requirement_id=?", (rid,))[0]
    p = json.loads(row["payload"])
    ok("n9: 无 on-behalf 回归 surface=cli + payload 逐字 {state:DONE}",
       row["actor_surface"] == "cli" and p == {"state": "DONE"}, str(dict(row)))


def n10():
    """MCP 结构性门禁：14 工具 schema 无受托字段 + mcp 写恒 surface=mcp。"""
    db = new_db()
    m = MCP(db).start()
    tools = m.rpc("tools/list", {}).get("tools", [])
    ok("n10: 14 工具", len(tools) == 14, str(len(tools)))
    bad = [t["name"] for t in tools if "delegated" in json.dumps(t.get("inputSchema", {}))
           or "on_behalf" in json.dumps(t.get("inputSchema", {}))]
    ok("n10: inputSchema 无 on_behalf/delegated 字段", not bad, str(bad))
    rid = seed_req(db, "mcp gate")
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.call_ok("add_record", {"requirement_id": rid, "kind": "note", "title": "委托讨论",
                             "payload": {"delegated": {"kind": "statement", "basis": "讨论引用"}}})
    m.close()
    row = query(db, "SELECT actor_surface, payload FROM events WHERE kind='note' AND requirement_id=?", (rid,))[0]
    ok("n10: mcp 写 surface=mcp；add_record 自由 payload 例外真实存在（R3 登记）",
       row["actor_surface"] == "mcp" and json.loads(row["payload"]).get("delegated") is not None, str(dict(row)))


def n11():
    """配对不变量：正向全表 + 反向限定独占 kind（spec §2.3，R3 收窄）。"""
    REVERSE_KINDS = ("approval", "release", "renew", "state_change")
    db = new_db()
    m = MCP(db).start()
    r1 = seed_req(db, "pair delegated")
    m.call_ok("claim_task", {"requirement_id": r1, "agent_name": "a"})
    m.close()
    cli_ok(db, "approve", "--requirement-id", r1, "--on-behalf", "statement:pair 表态")
    r2 = seed_req(db, "pair plain")
    m2 = MCP(db).start()
    m2.call_ok("claim_task", {"requirement_id": r2, "agent_name": "b"})
    m2.close()
    cli_ok(db, "approve", "--requirement-id", r2)
    r3 = seed_req(db, "pair mcp free payload")
    m3 = MCP(db).start()
    m3.call_ok("claim_task", {"requirement_id": r3, "agent_name": "c"})
    m3.call_ok("add_record", {"requirement_id": r3, "kind": "note", "title": "委托讨论",
                              "payload": {"delegated": {"kind": "statement", "basis": "x"}}})
    m3.close()
    rows = query(db, "SELECT kind, actor_surface, payload FROM events")

    def valid_d(r):
        d = (json.loads(r["payload"]) if r["payload"] else {}).get("delegated")
        return isinstance(d, dict) and d.get("kind") in ("statement", "action") \
            and bool(str(d.get("basis", "")).strip())

    fwd = [dict(r) for r in rows if r["actor_surface"] == "delegated" and not valid_d(r)]
    ok("n11: 正向全表（delegated -> 有效 payload.delegated）", not fwd, str(fwd))
    rev = [dict(r) for r in rows if r["kind"] in REVERSE_KINDS
           and bool((json.loads(r["payload"]) if r["payload"] else {}).get("delegated"))
           and r["actor_surface"] != "delegated"]
    ok("n11: 反向（独占 kind 含 delegated 键 -> surface=delegated；kind=note 共享不在限定内）",
       not rev, str(rev))


def n28():
    """受托参数结构性缺席面（CLI：argparse exit 2）。"""
    db = new_db()
    rid = seed_req(db, "structural gate")
    res1 = cli(db, "delete", "--requirement-id", rid, "--on-behalf", "x")
    ok("n28: delete --on-behalf -> exit2 unrecognized arguments",
       res1.returncode == 2 and "unrecognized arguments" in res1.stderr,
       f"rc={res1.returncode} stderr={res1.stderr[:200]}")
    res2 = cli(db, "set_expectations", "--requirement-id", rid, "--acceptance", "[]",
               "--on-behalf", "x")
    ok("n28: set_expectations --on-behalf -> exit2（D1 结构性缺席）",
       res2.returncode == 2 and "unrecognized arguments" in res2.stderr,
       f"rc={res2.returncode} stderr={res2.stderr[:200]}")


def _run_cli_nul(db: Path, args: list[str]) -> subprocess.CompletedProcess:
    """CLI 子进程钉 stdin=DEVNULL（零输入非 tty 确定性，R1；ac_cases_k._run_cli 同模式）。"""
    return subprocess.run(
        [str(VENV_PY), str(CLI), *args],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
        env=env_for(db), cwd=str(REPO_ROOT), timeout=TIMEOUT,
    )


def n19():
    db = new_db()
    res = _run_cli_nul(db, ["approve"])
    ok("n19: 0 待决 -> exit0 + 无待决项 + 零写",
       res.returncode == 0 and "无待决项" in res.stdout
       and query(db, "SELECT COUNT(*) AS n FROM events")[0]["n"] == 0,
       f"rc={res.returncode} stdout={res.stdout[:100]}")


def n20():
    db = new_db()
    [rid] = _mk_awaiting(db, 1)
    res = _run_cli_nul(db, ["approve"])
    ok("n20: 恰1 -> 直执 DONE", res.returncode == 0
       and json.loads(res.stdout).get("state") == "DONE",
       f"rc={res.returncode} stdout={res.stdout[:200]}")
    row = query(db, "SELECT actor_surface FROM events WHERE kind='approval'")[0]
    ok("n20: 无 on-behalf -> surface=cli（等价显式 id）", row["actor_surface"] == "cli", str(dict(row)))


def n21():
    db = new_db()
    m = MCP(db).start()
    r1 = seed_req(db, "z21-blocked")
    m.call_ok("claim_task", {"requirement_id": r1, "agent_name": "a"})
    m.call_ok("mark_blocked", {"requirement_id": r1, "reason": "等人裁决"})
    m.close()
    m2 = MCP(db).start()
    r2 = seed_req(db, "z21-claimed")
    m2.call_ok("claim_task", {"requirement_id": r2, "agent_name": "b"})
    m2.call_ok("request_review",
               {"requirement_id": r2, "evidence": {"test_summary": "s"}, "summary_line": "交接"})
    m2.close()
    before = query(db, "SELECT COUNT(*) AS n FROM events")[0]["n"]
    res = _run_cli_nul(db, ["approve"])
    after = query(db, "SELECT COUNT(*) AS n FROM events")[0]["n"]
    ok("n21: 多条非tty -> exit1 拒绝零写", res.returncode == 1 and before == after,
       f"rc={res.returncode} stderr={res.stderr[:300]}")
    ok("n21: 列表含两候选 + [STATE] + --requirement-id 提示 + 无Traceback",
       r1[:8] in res.stderr and "[BLOCKED]" in res.stderr
       and r2[:8] in res.stderr and "[CLAIMED]" in res.stderr
       and "--requirement-id" in res.stderr and "Traceback" not in res.stderr,
       res.stderr[:400])


def n22():
    db = new_db()
    _mk_awaiting(db, 1)
    before = query(db, "SELECT COUNT(*) AS n FROM events")[0]["n"]
    res = _run_cli_nul(db, ["release"])
    after = query(db, "SELECT COUNT(*) AS n FROM events")[0]["n"]
    ok("n22: 零输入 release 无 --reason -> invalid_record 零写（DB 读取前 fail-fast）",
       res.returncode == 1 and "release requires a reason" in res.stderr and before == after,
       f"rc={res.returncode} stderr={res.stderr[:200]}")


def n23():
    db = new_db()
    [rid] = _mk_awaiting(db, 1)
    res = _run_cli_nul(db, ["release", "--reason", "方向不对"])
    ok("n23: 零输入 release --reason -> OPEN",
       res.returncode == 0 and json.loads(res.stdout).get("state") == "OPEN",
       f"rc={res.returncode} stdout={res.stdout[:200]}")
    row = query(db, "SELECT release_reason FROM claims WHERE requirement_id=?", (rid,))[0]
    ok("n23: release_reason 落值", row["release_reason"] == "方向不对", str(dict(row)))


def n24():
    """零输入 + 受托组合（agent 主流程）。"""
    db = new_db()
    _mk_awaiting(db, 1)
    res = _run_cli_nul(db, ["approve", "--on-behalf", "statement:user 表态收尾"])
    ok("n24: 零输入+受托 -> DONE", res.returncode == 0
       and json.loads(res.stdout).get("state") == "DONE",
       f"rc={res.returncode} stdout={res.stdout[:200]}")
    row = query(db, "SELECT actor_surface, payload FROM events WHERE kind='approval'")[0]
    ok("n24: approval 事件 delegated+basis",
       row["actor_surface"] == "delegated"
       and json.loads(row["payload"]).get("delegated") == {"kind": "statement", "basis": "user 表态收尾"},
       str(dict(row)))


def n26():
    db = new_db()
    [rid] = _mk_awaiting(db, 1)
    _run_cli_nul(db, ["approve", "--on-behalf", "statement:展示面"])
    res = cli(db, "view", "detail", "--requirement-id", rid)  # 文本渲染，非 JSON
    ok("n26: view detail 事件行 by delegated:cli（既有通用渲染透传，零改动）",
       res.returncode == 0 and "by delegated:cli" in res.stdout, res.stdout[-500:])


def n27():
    db = new_db()
    [rid] = _mk_awaiting(db, 1)
    _run_cli_nul(db, ["approve", "--on-behalf", "action:export 面"])
    res = cli_ok(db, "export", "--format", "json")
    reqs = [q for q in res["requirements"] if q["requirement_id"] == rid]
    evs = [e for e in reqs[0]["events"] if e["kind"] == "approval"]
    ok("n27: export json approval 行 actor_surface=delegated + payload.delegated",
       len(evs) == 1 and evs[0]["actor_surface"] == "delegated"
       and evs[0]["payload"].get("delegated") == {"kind": "action", "basis": "export 面"},
       str(evs))


def n12():
    db = new_db()
    rid = seed_req(db, "rest approve")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.close()
    rest = REST(db).start()
    try:
        code, body = rest.req("POST", f"/requirements/{rid}/approve",
                              body={"kind": "statement", "basis": "user 会话原话"})
        ok("n12: 顶层 body -> 200", code == 200, f"{code} {body}")
    finally:
        rest.stop()
    row = query(db, "SELECT actor_surface, actor_conn, payload FROM events WHERE kind='approval' AND requirement_id=?", (rid,))[0]
    ok("n12: delegated + rest: 前缀 + payload 落值",
       row["actor_surface"] == "delegated" and str(row["actor_conn"]).startswith("rest:")
       and json.loads(row["payload"]).get("delegated") == {"kind": "statement", "basis": "user 会话原话"},
       str(dict(row)))


def n13():
    db = new_db()
    rid = seed_req(db, "rest regress")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.close()
    rest = REST(db).start()
    try:
        code, body = rest.req("POST", f"/requirements/{rid}/approve")
        ok("n13: 无 body -> 200（回归）", code == 200, f"{code} {body}")
    finally:
        rest.stop()
    row = query(db, "SELECT actor_surface, payload FROM events WHERE kind='approval' AND requirement_id=?", (rid,))[0]
    ok("n13: surface=cli + payload 无 delegated",
       row["actor_surface"] == "cli" and "delegated" not in json.loads(row["payload"]), str(dict(row)))


def n14():
    db = new_db()
    rid = seed_req(db, "rest release")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.close()
    rest = REST(db).start()
    try:
        code, body = rest.req("POST", f"/requirements/{rid}/release",
                              body={"reason": "方向不对",
                                    "delegated": {"kind": "action", "basis": "user 自行关闭 PR"}})
        ok("n14: 嵌套 delegated -> 200 OPEN", code == 200 and body.get("state") == "OPEN", f"{code} {body}")
    finally:
        rest.stop()
    row = query(db, "SELECT actor_surface, payload FROM events WHERE kind='release' AND requirement_id=?", (rid,))[0]
    ok("n14: release 事件 delegated",
       row["actor_surface"] == "delegated"
       and json.loads(row["payload"]).get("delegated") == {"kind": "action", "basis": "user 自行关闭 PR"},
       str(dict(row)))


def n15():
    db = new_db()
    rid = seed_req(db, "rest note")
    rest = REST(db).start()
    try:
        code, body = rest.req("POST", f"/requirements/{rid}/note",
                              body={"content": "REST 更正",
                                    "delegated": {"kind": "statement", "basis": "user 指正"}})
        ok("n15: 嵌套 delegated -> 200", code == 200, f"{code} {body}")
    finally:
        rest.stop()
    row = query(db, "SELECT actor_surface, payload FROM events WHERE kind='note' AND requirement_id=?", (rid,))[0]
    ok("n15: note 事件 delegated + content 共存",
       row["actor_surface"] == "delegated" and json.loads(row["payload"]) == {
           "content": "REST 更正", "delegated": {"kind": "statement", "basis": "user 指正"}}, str(dict(row)))


def n16():
    db = new_db()
    rid = seed_req(db, "rest reopen")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.call_ok("request_review", {"requirement_id": rid, "evidence": {"test_summary": "s"}, "summary_line": "交接"})
    m.close()
    cli_ok(db, "approve", "--requirement-id", rid)  # -> DONE
    rest = REST(db).start()
    try:
        code, body = rest.req("POST", f"/requirements/{rid}/reopen",
                              body={"delegated": {"kind": "statement", "basis": "user 要重做"}})
        ok("n16: reopen 嵌套 delegated -> 200 REOPEN",
           code == 200 and body.get("state") == "REOPEN", f"{code} {body}")
    finally:
        rest.stop()
    sc = [r for r in query(db, "SELECT actor_surface, payload FROM events WHERE kind='state_change' AND requirement_id=?", (rid,))
          if json.loads(r["payload"]).get("to") == "REOPEN"]
    ok("n16: state_change->REOPEN delegated",
       len(sc) == 1 and sc[0]["actor_surface"] == "delegated"
       and json.loads(sc[0]["payload"]).get("delegated") == {"kind": "statement", "basis": "user 要重做"},
       str([dict(x) for x in sc]))


def n17():
    db = new_db()
    rid = seed_req(db, "rest invalid kind")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.close()
    before = query(db, "SELECT COUNT(*) AS n FROM events WHERE requirement_id=?", (rid,))[0]["n"]
    rest = REST(db).start()
    try:
        code, body = rest.req("POST", f"/requirements/{rid}/approve",
                              body={"kind": "foo", "basis": "x"})
        ok("n17: kind 越枚举 -> 422 invalid_record",
           code == 422 and (isinstance(body, dict) and body.get("code") == "invalid_record"), f"{code} {body}")
    finally:
        rest.stop()
    after = query(db, "SELECT COUNT(*) AS n FROM events WHERE requirement_id=?", (rid,))[0]["n"]
    ok("n17: 零写", before == after, f"{before} -> {after}")


def n17b():
    db = new_db()
    rid = seed_req(db, "rest nonconform body")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.close()
    before = query(db, "SELECT COUNT(*) AS n FROM events WHERE requirement_id=?", (rid,))[0]["n"]
    rest = REST(db).start()
    try:
        code, body = rest.req("POST", f"/requirements/{rid}/approve", body={"foo": 1})
        ok("n17b: 非 conform body -> 422（登记行为变化，R4）", code == 422, f"{code} {body}")
    finally:
        rest.stop()
    after = query(db, "SELECT COUNT(*) AS n FROM events WHERE requirement_id=?", (rid,))[0]["n"]
    ok("n17b: 零写", before == after, f"{before} -> {after}")


def n18():
    db = new_db()
    rid = seed_req(db, "rest structural gate")
    rest = REST(db).start()
    try:
        code, body = rest.req("POST", f"/requirements/{rid}/archive",
                              body={"delegated": {"kind": "statement", "basis": "x"}})
        ok("n18: archive 携 delegated 体 -> 200（体被忽略）", code == 200, f"{code} {body}")
    finally:
        rest.stop()
    row = query(db, "SELECT actor_surface, payload FROM events WHERE kind='state_change' AND requirement_id=?", (rid,))[0]
    ok("n18: state_change surface=cli + payload 无 delegated（结构门禁）",
       row["actor_surface"] == "cli" and "delegated" not in json.loads(row["payload"]), str(dict(row)))


def n29():
    """delegated approve 解阻（BLOCKED->CLAIMED 单条 state_change 带 delegated，无 approval 事件）。"""
    db = new_db()
    rid = seed_req(db, "delegated unblock")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.call_ok("mark_blocked", {"requirement_id": rid, "reason": "待人裁决"})
    m.close()
    res = cli_ok(db, "approve", "--requirement-id", rid, "--on-behalf", "statement:人会话说继续")
    want = {"kind": "statement", "basis": "人会话说继续"}
    ok("n29: approve 解阻 exit0 + CLAIMED（非 DONE）", res.get("state") == "CLAIMED", str(res))
    rows = _ev_rows(db, rid)
    # claim_task 的 OPEN->CLAIMED 也是 to=CLAIMED，必须从 from 限定解阻那条（payload
    # 键 {"from","to"} 见 state_machine.transition）
    sc = [r for r in rows if r["kind"] == "state_change"
          and _pl(r).get("to") == "CLAIMED" and _pl(r).get("from") == "BLOCKED"]
    ok("n29: state_change(BLOCKED->CLAIMED) delegated+payload",
       len(sc) == 1 and sc[0]["actor_surface"] == "delegated" and _pl(sc[0]).get("delegated") == want,
       str([dict(x) for x in sc]))
    ap = [r for r in rows if r["kind"] == "approval"]
    ok("n29: 解阻分支无 approval 事件（分支判别锚）", len(ap) == 0, str([dict(x) for x in ap]))
