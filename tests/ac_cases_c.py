"""M0 AC 用例（AC11/12/13/15/17 + 安全/读锁/进度派生/payload/REST/CLI M0）。

oracle 纪律：断言逐字引自 PRD §5.3/§9/§4.3；视图断言基于渲染输出（summary dict / 文本 / HTML）。
REST 用真实子进程 uvicorn + urllib（stdlib，禁 TestClient）。
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time

from ac_lib import MCP, REST, VENV_PY, REPO_ROOT, cli, cli_err, cli_ok, env_for, new_db, ok, query, seed_req, _free_port

TIMEOUT = 30


def ac11():
    print("== AC11: 覆盖缺口 + 反向断言（已覆盖锚不显示 uncovered）")
    db = new_db()
    rid = seed_req(db, "ac11")
    cli_ok(db, "set_expectations", "--requirement-id", rid, "--acceptance",
           '[{"item": "A1"}, {"item": "A2"}, {"item": "A3"}]')
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    st1 = m.call_ok("add_subtask", {"requirement_id": rid, "title": "impl1", "ordinal": 1,
                                    "acceptance": [{"item": "x works", "links_to": "a1"}]})
    st2 = m.call_ok("add_subtask", {"requirement_id": rid, "title": "impl2", "ordinal": 2,
                                    "acceptance": [{"item": "y works", "links_to": "a2"}]})
    m.call_ok("request_review", {"requirement_id": rid, "evidence": {"test_summary": "t"},
                                 "assessments": [
                                     {"subtask_id": st1["subtask_id"], "items": [{"item": "x works", "state": "met"}]},
                                     {"subtask_id": st2["subtask_id"], "items": [{"item": "y works", "state": "not_met"}]},
                                 ]})
    m.close()
    rest = REST(db).start()
    try:
        code, s = rest.req("GET", f"/requirements/{rid}/summary")
        ok("ac11: summary 200", code == 200, str(code))
        table = {a["anchor_id"]: a for a in s["acceptance_table"]}
        # 反向断言（审#2）：已覆盖锚不显示 uncovered
        ok("ac11: 已覆盖锚 a1 不显示 uncovered", table["a1"]["uncovered"] is False, str(table["a1"]))
        ok("ac11: 已覆盖锚 a2 不显示 uncovered", table["a2"]["uncovered"] is False, str(table["a2"]))
        # 覆盖锚显示链接项文本+状态（PRD 5.3：非仅聚合缺口）
        ok("ac11: a1 链接项文本+状态可见",
           any(x["item"] == "x works" and x["state"] == "met" for x in table["a1"]["linked"]),
           str(table["a1"]["linked"]))
        ok("ac11: a2 链接项状态可见",
           any(x["item"] == "y works" and x["state"] == "not_met" for x in table["a2"]["linked"]),
           str(table["a2"]["linked"]))
        # 覆盖缺口突出（PRD §9 AC11：无覆盖条目突出显示）
        ok("ac11: 无覆盖锚 a3 uncovered=True", table["a3"]["uncovered"] is True, str(table["a3"]))
        # 文本渲染面也突出
        res = cli(db, "view", "summary", "--requirement-id", rid)
        ok("ac11: CLI 文本覆盖缺口突出", res.returncode == 0 and "覆盖缺口" in res.stdout and "A3" in res.stdout,
           res.stdout[-200:])
    finally:
        rest.stop()


def ac12():
    print("== AC12: 派生偏离可见（blocked/abandoned/里程碑延误，无需 deviation 登记）")
    db = new_db()
    rid = seed_req(db, "ac12")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    s1 = m.call_ok("add_subtask", {"requirement_id": rid, "title": "s1", "ordinal": 1})
    s2 = m.call_ok("add_subtask", {"requirement_id": rid, "title": "s2", "ordinal": 2})
    m.call_ok("add_milestone", {"requirement_id": rid, "title": "M1", "planned_at": "2020-01-01T00:00:00+00:00"})
    m.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": s1["subtask_id"], "state": "blocked"})
    m.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": s2["subtask_id"], "state": "abandoned"})
    m.close()
    rest = REST(db).start()
    try:
        code, s = rest.req("GET", f"/requirements/{rid}/summary")
        ok("ac12: summary 200", code == 200, str(code))
        na = {n["type"]: n for n in s["needs_attention"]}
        ok("ac12: blocked_subtask 派生信号", "blocked_subtask" in na, str(list(na)))
        ok("ac12: abandoned_subtask 派生信号", "abandoned_subtask" in na, str(list(na)))
        ok("ac12: 未解释放弃（无 deviation/note 登记）", "unexplained_abandonment" in na, str(list(na)))
        ok("ac12: 里程碑延误派生信号", "milestone_delay" in na, str(list(na)))
        # 文本渲染面：需要关注区可见
        res = cli(db, "view", "summary", "--requirement-id", rid)
        ok("ac12: CLI 需要关注区含信号", res.returncode == 0 and "需要关注" in res.stdout
           and "blocked_subtask" in res.stdout and "milestone_delay" in res.stdout, res.stdout[-300:])
    finally:
        rest.stop()

    # 反向：已解释放弃（有 deviation）不标 unexplained_abandonment
    rid2 = seed_req(db, "ac12-explained")
    m2 = MCP(db).start()
    m2.call_ok("claim_task", {"requirement_id": rid2, "agent_name": "b"})
    s3 = m2.call_ok("add_subtask", {"requirement_id": rid2, "title": "s3", "ordinal": 1})
    m2.call_ok("update_subtask", {"requirement_id": rid2, "subtask_id": s3["subtask_id"], "state": "abandoned"})
    m2.call_ok("add_record", {"requirement_id": rid2, "kind": "deviation", "title": "gave up",
                              "severity": "attention",
                              "payload": {"subtask_id": s3["subtask_id"], "reason": "blocked by dep"}})
    m2.close()
    rest2 = REST(db).start()
    try:
        code, s = rest2.req("GET", f"/requirements/{rid2}/summary")
        na_types = [n["type"] for n in s["needs_attention"]]
        ok("ac12: 已解释放弃仍显示 abandoned_subtask", "abandoned_subtask" in na_types, str(na_types))
        ok("ac12: 已解释放弃不标 unexplained_abandonment", "unexplained_abandonment" not in na_types, str(na_types))
    finally:
        rest2.stop()

    # 拆解新增派生（CLAIMED 期间 add_subtask 无 decision/deviation 解释）
    rid3 = seed_req(db, "ac12-decomp")
    m3 = MCP(db).start()
    m3.call_ok("claim_task", {"requirement_id": rid3, "agent_name": "c"})
    m3.call_ok("add_subtask", {"requirement_id": rid3, "title": "x", "ordinal": 1})
    m3.call_ok("add_subtask", {"requirement_id": rid3, "title": "y", "ordinal": 2})
    m3.close()
    rest3 = REST(db).start()
    try:
        code, s = rest3.req("GET", f"/requirements/{rid3}/summary")
        na_types = [n["type"] for n in s["needs_attention"]]
        ok("ac12: 拆解新增派生信号（无解释）", "decomposition_added" in na_types, str(na_types))
    finally:
        rest3.stop()

    # 反向：有 decision 解释的拆解不标 decomposition_added
    rid4 = seed_req(db, "ac12-decomp-exp")
    m4 = MCP(db).start()
    m4.call_ok("claim_task", {"requirement_id": rid4, "agent_name": "d"})
    m4.call_ok("add_subtask", {"requirement_id": rid4, "title": "z", "ordinal": 1})
    m4.call_ok("add_record", {"requirement_id": rid4, "kind": "decision", "title": "d",
                              "payload": {"choice": "a", "rationale": "r",
                                          "alternatives": [{"option": "b", "rejected_reason": "w"}]}})
    m4.close()
    rest4 = REST(db).start()
    try:
        code, s = rest4.req("GET", f"/requirements/{rid4}/summary")
        na_types = [n["type"] for n in s["needs_attention"]]
        ok("ac12: 有 decision 解释的拆解不标 decomposition_added", "decomposition_added" not in na_types, str(na_types))
    finally:
        rest4.stop()


def ac13():
    print("== AC13: 反淹没（摘要不含原始输出流；含结构化决策字段）")
    db = new_db()
    rid = seed_req(db, "ac13")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    prog_secret = "PROGRESS_SECRET_" + "x" * 2000
    m.call_ok("update_progress", {"requirement_id": rid, "note": prog_secret})
    long_content = "RISK_LONG_" + "y" * 1500
    m.call_ok("add_record", {"requirement_id": rid, "kind": "risk", "title": "risk1",
                             "severity": "attention", "content": long_content})
    m.call_ok("add_record", {"requirement_id": rid, "kind": "decision", "title": "dec1",
                             "payload": {"choice": "C", "rationale": "R1",
                                         "alternatives": [{"option": "A", "rejected_reason": "slow"},
                                                          {"option": "B", "rejected_reason": "complex"}]}})
    m.close()
    rest = REST(db).start()
    try:
        code, s = rest.req("GET", f"/requirements/{rid}/summary")
        ok("ac13: summary 200", code == 200, str(code))
        blob = json.dumps(s, ensure_ascii=False)
        ok("ac13: 摘要不含 progress_note content 全文", prog_secret not in blob, "leak")
        ok("ac13: 摘要不含事件长 content", long_content not in blob, "leak")
        ok("ac13: 摘要结构不含 run_logs", "run_logs" not in blob, "run_logs")
        decs = [d for d in s["decisions"] if d["title"] == "dec1"]
        ok("ac13: 摘要含结构化决策字段 choice", bool(decs) and decs[0]["choice"] == "C", str(decs))
        ok("ac13: 摘要含 alternatives 全文",
           bool(decs) and any(x["option"] == "A" and x["rejected_reason"] == "slow"
                              for x in decs[0]["alternatives"]), str(decs))
        ok("ac13: 摘要含 rationale", bool(decs) and decs[0]["rationale"] == "R1", str(decs))
        # HTML 结构面（AC13：关键信息可读 + 不含原始输出）
        code, raw = rest.req("GET", f"/requirements/{rid}/summary.html")
        ok("ac13: summary.html 200 且含关键节点",
           code == 200 and isinstance(raw, str) and "ac13" in raw and "需要关注" in raw, f"{code}")
        ok("ac13: html 不含原始输出流", isinstance(raw, str) and prog_secret not in raw and long_content not in raw, "html leak")
        # 关键信息不展开事件流可读（决策 choice 在文本面可见）
        res = cli(db, "view", "summary", "--requirement-id", rid)
        ok("ac13: CLI 文本含决策但无原始输出", res.returncode == 0 and "C" in res.stdout
           and prog_secret not in res.stdout and long_content not in res.stdout, res.stdout[-200:])
    finally:
        rest.stop()


def ac15():
    print("== AC15: 回溯 5 判据 + export JSON/Markdown 完整含 events 全文")
    db = new_db()
    rid = seed_req(db, "ac15")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "ac15-agent"})
    s1 = m.call_ok("add_subtask", {"requirement_id": rid, "title": "s1", "ordinal": 1})
    s2 = m.call_ok("add_subtask", {"requirement_id": rid, "title": "s2", "ordinal": 2})
    ms = m.call_ok("add_milestone", {"requirement_id": rid, "title": "M1", "planned_at": "2020-01-01T00:00:00+00:00"})
    m.call_ok("update_milestone", {"requirement_id": rid, "milestone_id": ms["milestone_id"], "state": "achieved",
                                   "actual_at": "2020-01-02T00:00:00+00:00"})
    m.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": s1["subtask_id"], "state": "done"})
    m.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": s2["subtask_id"], "state": "done"})
    m.call_ok("add_record", {"requirement_id": rid, "kind": "decision", "title": "decision-1",
                             "payload": {"choice": "A", "rationale": "because",
                                         "alternatives": [{"option": "B", "rejected_reason": "why-not"}]}})
    m.call_ok("add_record", {"requirement_id": rid, "kind": "risk", "title": "risk-1",
                             "severity": "attention", "content": "some risk detail"})
    m.call_ok("request_review", {"requirement_id": rid,
                                 "evidence": {"pr_url": "https://github.com/x/pr/1",
                                              "commit_range": "abc123..def456", "test_summary": "all pass"},
                                 "assessments": []})
    m.close()
    cli_ok(db, "approve", "--requirement-id", rid)

    rest = REST(db).start()
    try:
        code, detail = rest.req("GET", f"/requirements/{rid}")
        ok("ac15: detail 200", code == 200, str(code))
        # 判据1（PRD 5.4）：为什么 DONE -> state_change 链 + 人确认 approval 事件
        sc_done = [e for e in detail["events"] if e["kind"] == "state_change"
                   and (e["payload"] or {}).get("to") == "DONE"]
        app = [e for e in detail["events"] if e["kind"] == "approval"]
        ok("ac15: 判据1 state_change->DONE + approval", bool(sc_done) and bool(app), f"sc={len(sc_done)} app={len(app)}")
        ok("ac15: 判据1 approval 时状态 DONE", bool(app) and app[0]["state_at_event"] == "DONE", str(app[0] if app else None))
        # 判据2：decision 当时状态（state_change 链推导）+ conn + ts + alternatives
        dec = [e for e in detail["events"] if e["kind"] == "decision" and e["title"] == "decision-1"]
        ok("ac15: 判据2 decision 当时状态 CLAIMED", bool(dec) and dec[0]["state_at_event"] == "CLAIMED",
           str(dec[0] if dec else None))
        ok("ac15: 判据2 decision 含 conn/ts/alternatives",
           bool(dec) and dec[0]["actor_conn"] and dec[0]["ts"] and (dec[0]["payload"] or {}).get("alternatives"),
           str(dec[0] if dec else None))
        # 判据3：claims 时间轴（含 release_reason）+ 事件归属
        claims = detail["claims"]
        ok("ac15: 判据3 claims 时间轴含 started/ended/reason",
           len(claims) >= 1 and all(c.get("started_at") and (c.get("ended_at") or c.get("release_reason")) for c in claims),
           str(claims))
        ok("ac15: 判据3 事件归属 actor_conn", all(e.get("actor_conn") for e in detail["events"]), "missing conn")
        # 判据4：分解与里程碑演化（subtask/milestone 变更与其事件同事务）
        st_evs = [e for e in detail["events"] if (e["payload"] or {}).get("subtask_id")]
        ms_evs = [e for e in detail["events"] if (e["payload"] or {}).get("milestone_id")]
        ok("ac15: 判据4 子任务变更事件同事务", len(st_evs) >= 2, str(len(st_evs)))
        ok("ac15: 判据4 里程碑变更事件同事务", len(ms_evs) >= 2, str(len(ms_evs)))
        # 判据5：产出物在哪 -> review 证据字段（payload.evidence 嵌套，PRD 5.4）
        rr = [e for e in detail["events"] if e["kind"] == "review_request"]
        ev = (rr[0]["payload"] or {}).get("evidence") if rr else {}
        ok("ac15: 判据5 review 证据字段（pr_url/commit_range/test_summary）",
           bool(rr) and all(ev.get(k) for k in ("pr_url", "commit_range", "test_summary")),
           str(rr[0] if rr else None))
        # export JSON 完整含 events 全文（无 LIMIT）
        code, exp = rest.req("GET", f"/requirements/{rid}/export?format=json")
        ok("ac15: export json 200", code == 200, str(code))
        exp_evs = exp["requirement"]["events"]
        ok("ac15: export json 含全部 events（无 LIMIT）", len(exp_evs) == len(detail["events"]),
           f"{len(exp_evs)} vs {len(detail['events'])}")
        ok("ac15: export json 含事件 content 全文",
           any(e["kind"] == "risk" and "some risk detail" in (e.get("content") or "") for e in exp_evs), "missing content")
        # export markdown 完整含 events 全文
        code, md = rest.req("GET", f"/requirements/{rid}/export?format=markdown")
        ok("ac15: export markdown 200 且含 events 全文",
           code == 200 and isinstance(md, str) and "some risk detail" in md and "all pass" in md, "md missing")
    finally:
        rest.stop()


def ac17():
    print("== AC17: request_review 缺证据被拒（复验）")
    db = new_db()
    m = MCP(db).start()
    r = seed_req(db, "ac17")
    m.call_ok("claim_task", {"requirement_id": r, "agent_name": "a"})
    code, _ = m.call_err("request_review", {"requirement_id": r, "evidence": {}})
    ok("ac17: 缺全部证据 -> invalid_record", code == "invalid_record", code)
    res = m.call_ok("request_review", {"requirement_id": r, "evidence": {"commit_range": "a..b"}})
    ok("ac17: 至少一项证据 -> 成功", (res.get("awaiting_human") or {}).get("kind") == "review", str(res))
    m.close()


def security():
    print("== M0-1.1 安全：localhost 默认 / token 校验 / healthz 豁免 / 非 localhost 无 token 拒绝")
    db = new_db()
    seed_req(db, "sec")

    rest = REST(db, host="127.0.0.1").start()
    try:
        code, _ = rest.req("GET", "/healthz")
        ok("sec: localhost 无 token healthz 200", code == 200, str(code))
        code, _ = rest.req("GET", "/requirements")
        ok("sec: localhost 无 token list 200", code == 200, str(code))
    finally:
        rest.stop()

    rest2 = REST(db, host="127.0.0.1", token="sekret").start()
    try:
        code, _ = rest2.req("GET", "/healthz")
        ok("sec: healthz 豁免 token 200", code == 200, str(code))
        code, _ = rest2.req("GET", "/requirements")
        ok("sec: 无 token 访问 -> 401", code == 401, str(code))
        code, _ = rest2.req("GET", "/requirements", token="wrong")
        ok("sec: 错误 token -> 401", code == 401, str(code))
        code, _ = rest2.req("GET", "/requirements", token="sekret")
        ok("sec: 正确 token header -> 200", code == 200, str(code))
        code, _ = rest2.req("GET", "/requirements", params={"token": "sekret"})
        ok("sec: 正确 token query -> 200", code == 200, str(code))
    finally:
        rest2.stop()

    env = env_for(db, {"AGENT_KANBAN_HOST": "0.0.0.0", "AGENT_KANBAN_PORT": str(_free_port())})
    proc = subprocess.Popen(
        [str(VENV_PY), "-m", "agent_kanban.api"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, cwd=str(REPO_ROOT),
    )
    out, _ = proc.communicate(timeout=20)
    ok("sec: 非 localhost 无 token 启动被拒", proc.returncode != 0, f"rc={proc.returncode}")
    ok("sec: 拒绝含告警日志", b"requires AGENT_KANBAN_TOKEN" in out, out.decode(errors="replace")[-200:])


def readlock():
    print("== M0-1.2/审#4 读锁竞争 + 审#3 进度派生值")
    db = new_db()
    rid = seed_req(db, "readlock")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    s1 = m.call_ok("add_subtask", {"requirement_id": rid, "title": "s1", "ordinal": 1})
    s2 = m.call_ok("add_subtask", {"requirement_id": rid, "title": "s2", "ordinal": 2})
    s3 = m.call_ok("add_subtask", {"requirement_id": rid, "title": "s3", "ordinal": 3})
    m.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": s1["subtask_id"], "state": "done"})
    m.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": s2["subtask_id"], "state": "blocked"})
    m.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": s3["subtask_id"], "state": "abandoned"})
    m.close()

    holder = sqlite3.connect(str(db))
    holder.execute("BEGIN IMMEDIATE")
    tiny = {"AGENT_KANBAN_BUSY_TIMEOUT_MS": "50"}
    try:
        # CLI 读：WAL 快照成功 或 结构化 db_busy，绝不裸 OperationalError
        r = cli(db, "view", "summary", "--requirement-id", rid, extra=tiny)
        structured = r.returncode == 0 or "db_busy" in r.stderr
        ok("readlock: CLI 读返回结构化结果或快照", structured, f"rc={r.returncode} err={r.stderr[:120]}")
        # MCP 读
        m2 = MCP(db, extra=tiny).start()
        try:
            res = m2.call("get_task_detail", {"requirement_id": rid})
            if res.get("isError"):
                code = json.loads(res["content"][0]["text"])["code"]
                ok("readlock: MCP 读结构化 db_busy", code == "db_busy", code)
            else:
                ok("readlock: MCP 读快照成功", json.loads(res["content"][0]["text"])["state"] == "CLAIMED", "snapshot")
        finally:
            m2.close()
        # REST 读
        rest = REST(db, extra=tiny).start()
        try:
            code, body = rest.req("GET", f"/requirements/{rid}/summary")
            ok("readlock: REST 读 200（快照）或 503 db_busy", code in (200, 503), f"{code} {body}")
            if code == 200:
                ok("readlock: REST 读快照含进度派生值",
                   body["progress"]["done"] == 1 and body["progress"]["total"] == 2, str(body["progress"]))
        finally:
            rest.stop()
    finally:
        holder.rollback()
        holder.close()

    # 审#3 进度派生值（无锁）：done/total、blocked=进行中、abandoned 不计分母
    rest2 = REST(db).start()
    try:
        code, s = rest2.req("GET", f"/requirements/{rid}/summary")
        p = s["progress"]
        ok("readlock: done=1 total=2（abandoned 不计分母）", p["done"] == 1 and p["total"] == 2, str(p))
        ok("readlock: blocked 计 total 非 done", p["blocked"] == 1 and p["remaining"] == 1, str(p))
        ok("readlock: abandoned 计数可见", p["abandoned"] == 1, str(p))
    finally:
        rest2.stop()


def payload():
    print("== PRD §6 payload 8KB 写时强制")
    db = new_db()
    m = MCP(db).start()
    r = seed_req(db, "payload")
    m.call_ok("claim_task", {"requirement_id": r, "agent_name": "a"})
    big = "x" * 9000
    code, _ = m.call_err("add_record", {"requirement_id": r, "kind": "note", "title": "n", "content": big})
    ok("payload: add_record content >8KB -> invalid_record", code == "invalid_record", code)
    code, _ = m.call_err("add_record", {"requirement_id": r, "kind": "decision", "title": "d",
                                       "payload": {"choice": "a", "rationale": "r",
                                                   "alternatives": [{"option": "b", "rejected_reason": big}]}})
    ok("payload: add_record payload >8KB -> invalid_record", code == "invalid_record", code)
    code, _ = m.call_err("add_subtask", {"requirement_id": r, "title": "big", "ordinal": 1,
                                         "acceptance": [{"item": big}]})
    ok("payload: add_subtask acceptance >8KB -> invalid_record", code == "invalid_record", code)
    small = "y" * 7000
    res = m.call_ok("add_record", {"requirement_id": r, "kind": "note", "title": "n", "content": small})
    ok("payload: <8KB 内容成功", res["kind"] == "note", str(res))
    m.close()


def rest_api():
    print("== M0-1.3 REST 逐端点 + 错误映射（404/409/422/503）")
    db = new_db()
    rest = REST(db, extra={"AGENT_KANBAN_BUSY_TIMEOUT_MS": "50"}).start()
    try:
        code, body = rest.req("POST", "/requirements", {"title": "rest-new", "acceptance": [{"item": "A1"}]})
        ok("rest: POST /requirements 201", code == 201 and body["state"] == "OPEN", f"{code} {body}")
        rid = body["requirement_id"]
        code, body = rest.req("GET", "/requirements")
        ok("rest: GET /requirements 200", code == 200 and len(body["tasks"]) >= 1, str(code))
        code, body = rest.req("PUT", f"/requirements/{rid}/expectations",
                              {"acceptance": [{"item": "A1"}, {"item": "A2"}]})
        ok("rest: PUT expectations 200", code == 200 and len(body["acceptance"]) == 2, str(code))
        code, s = rest.req("GET", f"/requirements/{rid}/summary")
        ok("rest: GET summary 200", code == 200 and s["state"] == "OPEN", str(code))
        code, d = rest.req("GET", f"/requirements/{rid}")
        ok("rest: GET detail 200", code == 200 and d["state"] == "OPEN", str(code))
        # 错误映射
        code, body = rest.req("POST", f"/requirements/{rid}/approve")
        ok("rest: approve(OPEN) -> 409 illegal_state", code == 409 and body["code"] == "illegal_state", f"{code} {body}")
        code, body = rest.req("POST", "/requirements/deadbeef/release", {"reason": "x"})
        ok("rest: release 不存在 -> 404 not_found", code == 404 and body["code"] == "not_found", f"{code} {body}")
        code, body = rest.req("POST", f"/requirements/{rid}/renew")
        ok("rest: renew 无认领 -> 404 not_found", code == 404 and body["code"] == "not_found", f"{code} {body}")
        code, body = rest.req("POST", f"/requirements/{rid}/release", {"reason": ""})
        ok("rest: release 空 reason -> 422 invalid_record", code == 422 and body["code"] == "invalid_record", f"{code} {body}")
        # db_busy -> 503
        holder = sqlite3.connect(str(db))
        holder.execute("BEGIN IMMEDIATE")
        try:
            code, body = rest.req("POST", "/requirements", {"title": "busy"})
            ok("rest: 写锁竞争 -> 503 db_busy", code == 503 and body["code"] == "db_busy", f"{code} {body}")
        finally:
            holder.rollback()
            holder.close()
    finally:
        rest.stop()

    # reopen/note/abandon 端点 + REST actor 归属（surface=cli, conn=rest:*）
    db2 = new_db()
    m = MCP(db2).start()
    r1 = seed_req(db2, "rest-reopen")
    m.call_ok("claim_task", {"requirement_id": r1, "agent_name": "a"})
    m.call_ok("request_review", {"requirement_id": r1, "evidence": {"test_summary": "t"}})
    m.close()
    rest2 = REST(db2, extra={"AGENT_KANBAN_BUSY_TIMEOUT_MS": "50"}).start()
    try:
        code, body = rest2.req("POST", f"/requirements/{r1}/approve")
        ok("rest: approve(CLAIMED) -> DONE", code == 200 and body["state"] == "DONE", f"{code} {body}")
        code, body = rest2.req("POST", f"/requirements/{r1}/reopen")
        ok("rest: reopen DONE->REOPEN", code == 200 and body["state"] == "REOPEN", f"{code} {body}")
        code, body = rest2.req("POST", f"/requirements/{r1}/reopen", {"continue": True})
        ok("rest: reopen --continue REOPEN->OPEN", code == 200 and body["state"] == "OPEN", f"{code} {body}")
        code, body = rest2.req("POST", f"/requirements/{r1}/note", {"content": "human note"})
        ok("rest: note 200", code == 200, f"{code} {body}")
        code, body = rest2.req("POST", f"/requirements/{r1}/abandon", {"to_state": "CANCELLED"})
        ok("rest: abandon CANCELLED 200", code == 200 and body["state"] == "CANCELLED", f"{code} {body}")
        row = query(db2, "SELECT actor_surface, actor_conn FROM events WHERE kind='note' ORDER BY seq DESC LIMIT 1", ())
        ok("rest: REST 事件归属 surface=cli/conn=rest:*",
           row and row[0]["actor_surface"] == "cli" and (row[0]["actor_conn"] or "").startswith("rest:"),
           str([dict(x) for x in row]))
    finally:
        rest2.stop()


def cli_m0():
    print("== M0-1.5 CLI: reopen / abandon 认领处置 / release --all-stale / export markdown")
    db = new_db()
    m = MCP(db).start()
    r1 = seed_req(db, "reopen1")
    m.call_ok("claim_task", {"requirement_id": r1, "agent_name": "a"})
    m.call_ok("request_review", {"requirement_id": r1, "evidence": {"test_summary": "t"}})
    cli_ok(db, "approve", "--requirement-id", r1)
    res = cli_ok(db, "reopen", "--requirement-id", r1)
    ok("cli: reopen DONE->REOPEN", res["state"] == "REOPEN", str(res))
    res = cli_ok(db, "reopen", "--requirement-id", r1, "--continue")
    ok("cli: reopen --continue REOPEN->OPEN", res["state"] == "OPEN", str(res))
    code, _ = cli_err(db, "reopen", "--requirement-id", r1)
    ok("cli: reopen(OPEN)->illegal_state", code == "illegal_state", code)

    r2 = seed_req(db, "abandon-claimed")
    m.call_ok("claim_task", {"requirement_id": r2, "agent_name": "b"})
    res = cli_ok(db, "abandon", "--requirement-id", r2, "--to-state", "REJECTED")
    ok("cli: abandon CLAIMED->REJECTED", res["state"] == "REJECTED", str(res))
    row = query(db, "SELECT ended_at IS NULL AS active, release_reason FROM claims WHERE requirement_id=?", (r2,))
    ok("cli: abandon 同事务置 claim ended_at + reason",
       row and row[0]["active"] == 0 and row[0]["release_reason"] == "abandon:REJECTED",
       str([dict(x) for x in row]))

    r3 = seed_req(db, "abandon-cancel")
    m.call_ok("claim_task", {"requirement_id": r3, "agent_name": "c"})
    code, _ = cli_err(db, "abandon", "--requirement-id", r3, "--to-state", "CANCELLED")
    ok("cli: abandon CANCELLED(CLAIMED)->illegal_state", code == "illegal_state", code)
    m.close()

    # release --all-stale
    stale_ids = []
    ms = MCP(db, extra={"AGENT_KANBAN_LEASE_SECONDS": "-1"}).start()
    for i in range(2):
        rid = seed_req(db, f"stale{i}")
        ms.call_ok("claim_task", {"requirement_id": rid, "agent_name": "s"})
        stale_ids.append(rid)
    ms.close()
    active_id = seed_req(db, "active-keep")
    ma = MCP(db).start()
    ma.call_ok("claim_task", {"requirement_id": active_id, "agent_name": "k"})
    res = cli_ok(db, "release", "--all-stale")
    released = {x["requirement_id"] for x in res["released"]}
    ok("cli: --all-stale 释放 2 STALE", len(res["released"]) == 2 and all(x["ok"] for x in res["released"]),
       str(res["released"]))
    ok("cli: --all-stale 释放的是 STALE 而非 ACTIVE",
       set(stale_ids) <= released and active_id not in released, f"released={released}")
    for rid in stale_ids:
        row = query(db, "SELECT state FROM requirements WHERE id=?", (rid,))
        ok(f"cli: STALE {rid[:6]} 已回 OPEN", row and row[0]["state"] == "OPEN", str([dict(x) for x in row]))
    row = query(db, "SELECT state FROM requirements WHERE id=?", (active_id,))
    ok("cli: ACTIVE 保持 CLAIMED", row and row[0]["state"] == "CLAIMED", str([dict(x) for x in row]))
    ma.close()

    # export markdown 全量无 LIMIT（>200 events）
    r4 = seed_req(db, "exp-md")
    mm = MCP(db).start()
    mm.call_ok("claim_task", {"requirement_id": r4, "agent_name": "a"})
    for k in range(210):
        mm.call_ok("add_record", {"requirement_id": r4, "kind": "note", "title": f"n{k}"})
    mm.close()
    res = cli(db, "export", "--requirement-id", r4, "--format", "markdown")
    n_events = sum(1 for line in res.stdout.splitlines() if line.startswith("- #"))
    ok("cli: export markdown rc=0", res.returncode == 0, res.stderr)
    ok("cli: export markdown 全量无 LIMIT（>200 events）", n_events >= 210, f"events={n_events}")
