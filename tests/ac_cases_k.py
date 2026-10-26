"""M1-5 task 生命周期用例（tests/ac_cases_k.py + run_ac 注册）。

oracle 纪律：断言引 PRD §0（定位：记录点/审计点）/§3.1（状态机含 ARCHIVED）/§3.4
（approve 判定表）/§4.1（list_tasks 获取未完成任务）/§6（数据保留：终态需求级原子窗口
含 ARCHIVED；prune 只删事件、需求行保留）；ARCHIVED 前置态经 SQL 直设（seed_reopen 同模式）；
prune 真实子进程 CLI + SQL backdate（确定性，禁 sleep 撞窗）。

- 反证位：list_tasks/board/GET /requirements 三默认列表排除 ARCHIVED（审 P1-1）+
  claim on ARCHIVED 零副作用（claim 行回滚）+ approve/reopen illegal_state +
  prune 覆盖 ARCHIVED（出窗事件整删、需求行保留、未出窗/非终态保留，审 P2-7）。
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from ac_lib import (CLI, MCP, REST, REPO_ROOT, TIMEOUT, VENV_PY, cli, cli_ok, cli_err,
                    env_for, new_db, ok, query, seed_req, seed_reopen)


def _update(db: Path, sql: str, params: tuple = ()) -> None:
    conn = sqlite3.connect(str(db))
    conn.execute(sql, params)
    conn.commit()
    conn.close()


def _set_state(db: Path, rid: str, state: str) -> None:
    _update(db, "UPDATE requirements SET state=? WHERE id=?", (state, rid))


def _run_cli(db: Path, args: list[str], *, input_text: str | None = None,
             extra: dict | None = None) -> subprocess.CompletedProcess:
    """CLI 子进程（可注入 stdin；确认门用例，ac_cases_h 同模式）。"""
    return subprocess.run(
        [str(VENV_PY), str(CLI), *args],
        capture_output=True, text=True, input=input_text,
        env=env_for(db, extra), cwd=str(REPO_ROOT), timeout=TIMEOUT,
    )


def _count(db: Path, rid: str) -> int:
    return query(db, "SELECT COUNT(*) AS n FROM events WHERE requirement_id=?", (rid,))[0]["n"]


def _backdate(db: Path, rid: str, days: int = 400) -> None:
    _update(db, "UPDATE events SET ts = datetime('now', ?) WHERE requirement_id=?", (f"-{days} days", rid))


def k_state():
    print("== M1-5.1: ARCHIVED 状态值 + 终态集合单一事实源（三默认列表/claim/approve/reopen/prune）")
    # (i) SQL 置 ARCHIVED：board / list_tasks / GET /requirements 默认列表排除；status 过滤包含
    db = new_db()
    r1 = seed_req(db, "k-archived")
    _set_state(db, r1, "ARCHIVED")
    r2 = seed_req(db, "k-open")
    m = MCP(db).start()
    ids = [t["requirement_id"] for t in m.call_ok("list_tasks", {})["tasks"]]
    ok("k_state(i): list_tasks 默认排除 ARCHIVED（审 P1-1）", r1 not in ids and r2 in ids, str(ids))
    m.close()
    rest = REST(db).start()
    try:
        code, body = rest.req("GET", "/board")
        ok("k_state(i): board 默认排除 ARCHIVED",
           code == 200 and r1 not in [t["requirement_id"] for t in body["tasks"]]
           and r2 in [t["requirement_id"] for t in body["tasks"]], str([t["requirement_id"] for t in body["tasks"]]))
        code, body = rest.req("GET", "/board", params={"status": "ARCHIVED"})
        ok("k_state(i): /board?status=ARCHIVED 包含",
           code == 200 and [t["requirement_id"] for t in body["tasks"]] == [r1], str(body.get("tasks")))
        code, body = rest.req("GET", "/requirements")
        ok("k_state(i): GET /requirements 排除 ARCHIVED（审 P1-1 连锁）",
           code == 200 and r1 not in [t["requirement_id"] for t in body["tasks"]], str([t["requirement_id"] for t in body["tasks"]]))
    finally:
        rest.stop()
    # (ii) claim on ARCHIVED -> illegal_state 且 claim 行零残留（INSERT 随事务回滚）
    m2 = MCP(db).start()
    code2, _ = m2.call_err("claim_task", {"requirement_id": r1, "agent_name": "x"})
    ok("k_state(ii): claim ARCHIVED -> illegal_state", code2 == "illegal_state", code2)
    n_claims = query(db, "SELECT COUNT(*) AS n FROM claims WHERE requirement_id=?", (r1,))[0]["n"]
    ok("k_state(ii): claim 回滚零 claim 行", n_claims == 0, str(n_claims))
    m2.close()
    # (iii) approve / reopen on ARCHIVED -> illegal_state（无 unarchive）
    code3, _ = cli_err(db, "approve", "--requirement-id", r1)
    ok("k_state(iii): approve ARCHIVED -> illegal_state", code3 == "illegal_state", code3)
    code4, _ = cli_err(db, "reopen", "--requirement-id", r1)
    ok("k_state(iii): reopen ARCHIVED -> illegal_state", code4 == "illegal_state", code4)
    # (iv) prune 覆盖 ARCHIVED：出窗事件整删（需求行保留）/ 未出窗保留 / 非终态保留（审 P2-7）
    db2 = new_db()
    a = seed_req(db2, "k-prune-a")  # ARCHIVED 全窗外 -> events 整删、需求行保留
    b = seed_req(db2, "k-prune-b")  # ARCHIVED 有近期事件 -> 保留
    c = seed_req(db2, "k-prune-c")  # CLAIMED 僵尸（非终态）-> 保留
    m3 = MCP(db2).start()
    m3.call_ok("claim_task", {"requirement_id": a, "agent_name": "a"})
    m3.call_ok("claim_task", {"requirement_id": b, "agent_name": "b"})
    m3.call_ok("claim_task", {"requirement_id": c, "agent_name": "c"})
    m3.close()
    _set_state(db2, a, "ARCHIVED")
    _set_state(db2, b, "ARCHIVED")
    _backdate(db2, a)  # 仅 a 的全部事件出窗
    before_a = _count(db2, a)
    ok("k_state(iv): 前置——a 有事件", before_a > 0, f"n={before_a}")
    exp = Path(tempfile.mkdtemp(prefix="ak-k-")) / "export.json"
    res = _run_cli(db2, ["prune", "--months", "12", "--yes", "--export-path", str(exp)])
    ok("k_state(iv): prune CLI 退出 0", res.returncode == 0, f"rc={res.returncode} stderr={res.stderr[-200:]}")
    ok("k_state(iv): ARCHIVED 出窗 -> events 整删", _count(db2, a) == 0, f"n={_count(db2, a)}")
    row_a = query(db2, "SELECT state FROM requirements WHERE id=?", (a,))
    ok("k_state(iv): ARCHIVED 出窗 -> 需求行保留（prune 只删事件，审 P2-7）",
       len(row_a) == 1 and row_a[0]["state"] == "ARCHIVED", str([dict(x) for x in row_a]))
    ok("k_state(iv): ARCHIVED 未出窗保留", _count(db2, b) > 0, f"n={_count(db2, b)}")
    ok("k_state(iv): 非终态保留", _count(db2, c) > 0, f"n={_count(db2, c)}")


def k_archive():
    print("== M1-5.2: archive 七状态矩阵 + claim 同事务结束（release_reason=archive）+ marker 清除 + 事件形态 + channel 归属 + archive 后 agent 写 no_active_claim")
    def _seed_state(db, title, state, need_claim=False, need_blocked=False):
        rid = seed_req(db, title)
        if need_claim or state == "DONE":
            m = MCP(db).start()
            m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
            if need_blocked:
                m.call_ok("mark_blocked", {"requirement_id": rid, "reason": "waiting input"})
            m.close()
        if state == "DONE":
            cli_ok(db, "approve", "--requirement-id", rid)  # CLAIMED -> DONE（无 marker 亦合法，PRD 3.4）
        elif state == "REOPEN":
            seed_reopen(db, rid)
        elif state in ("REJECTED", "CANCELLED"):
            cli_ok(db, "abandon", "--requirement-id", rid, "--to-state", state)
        return rid

    # (i) 七状态矩阵（CLI channel：actor_surface=cli / actor_conn=cli）
    for state, need_claim, need_blocked in [
        ("OPEN", False, False), ("CLAIMED", True, False), ("BLOCKED", True, True),
        ("REOPEN", False, False), ("DONE", False, False), ("REJECTED", False, False),
        ("CANCELLED", False, False)]:
        db = new_db()
        rid = _seed_state(db, f"k-arch-{state}", state, need_claim, need_blocked)
        resp = cli_ok(db, "archive", "--requirement-id", rid)
        ok(f"k_archive({state}): CLI archive -> ARCHIVED", resp.get("state") == "ARCHIVED", str(resp))
        row = query(db, "SELECT state, awaiting_human FROM requirements WHERE id=?", (rid,))[0]
        ok(f"k_archive({state}): requirements.state=ARCHIVED", row["state"] == "ARCHIVED", str(dict(row)))
        ev = query(db, "SELECT title, payload, actor_surface, actor_conn, claim_id "
                       "FROM events WHERE requirement_id=? ORDER BY seq DESC LIMIT 1", (rid,))[0]
        pl = json.loads(ev["payload"])
        ok(f"k_archive({state}): 事件链尾 state_change from=None to=ARCHIVED（Q3 裁决形态）",
           ev["title"] == "? -> ARCHIVED" and pl == {"from": None, "to": "ARCHIVED"}, str(dict(ev)))
        ok(f"k_archive({state}): CLI 归属 surface=cli conn=cli",
           ev["actor_surface"] == "cli" and ev["actor_conn"] == "cli", f"{ev['actor_surface']}/{ev['actor_conn']}")
        if need_claim:
            c = query(db, "SELECT ended_at, release_reason FROM claims WHERE requirement_id=? AND ended_at IS NOT NULL", (rid,))[0]
            ok(f"k_archive({state}): claim 同事务 ended（release_reason=archive）",
               c["ended_at"] is not None and c["release_reason"] == "archive", str(dict(c)))
            cid = query(db, "SELECT id FROM claims WHERE requirement_id=?", (rid,))[0]["id"]
            ok(f"k_archive({state}): 事件 claim_id 归属到认领", ev["claim_id"] == cid, f"{ev['claim_id']} vs {cid}")
        if need_blocked:
            # 裸存储双空形态：SQLAlchemy JSON 列 none_as_null=False，清 marker 存文本 "null"（非 SQL NULL，
            # main 既有行为，approve/abandon 路径同形）；业务契约 = 无存活 marker（存活 = JSON dict 文本，仍红）。
            # list_awaiting 过滤层对该文本的泄漏 = 既有缺陷 G12（登记 known-gaps，非本批引入，不在此 pin）。
            ok("k_archive(BLOCKED): awaiting_human 清除（无存活 marker）",
               row["awaiting_human"] in (None, "null"), str(row["awaiting_human"]))
    # (ii) REST channel（surface=cli / conn=rest:* 前缀）+ 再 archive 允许 + 404
    db2 = new_db()
    rid2 = seed_req(db2, "k-arch-rest")
    rest = REST(db2).start()
    try:
        code, body = rest.req("POST", f"/requirements/{rid2}/archive")
        ok("k_archive: REST archive 200", code == 200 and body["state"] == "ARCHIVED", f"{code} {body}")
        # 视图（spec case 2 / AC3）：board 默认排除 + status 过滤包含 + finished_at = archive 事件 ts
        code, body = rest.req("GET", "/board")
        ok("k_archive: board 默认响应不含 ARCHIVED",
           code == 200 and rid2 not in [t["requirement_id"] for t in body["tasks"]], str([t["requirement_id"] for t in body["tasks"]]))
        code, body = rest.req("GET", "/board", params={"status": "ARCHIVED"})
        row_t = [t for t in body["tasks"] if t["requirement_id"] == rid2]
        ok("k_archive: /board?status=ARCHIVED 包含", len(row_t) == 1, str(body.get("tasks")))
        code, d = rest.req("GET", f"/requirements/{rid2}")
        last_sc = [e for e in d["events"] if e["kind"] == "state_change"][-1]
        ok("k_archive: finished_at = archive 事件 ts（_terminal_entry_ts 派生，零改动验证）",
           row_t and row_t[0]["finished_at"] == last_sc["ts"],
           f"{row_t[0]['finished_at'] if row_t else 'missing'} vs {last_sc['ts']}")
        code, body = rest.req("POST", f"/requirements/{rid2}/archive")
        ok("k_archive: ARCHIVED 上再 archive 允许（与 REJECTED->REJECTED 既有口径一致）",
           code == 200 and body["state"] == "ARCHIVED", f"{code} {body}")
        code, body = rest.req("POST", "/requirements/deadbeef/archive")
        ok("k_archive: archive 不存在 -> 404 not_found", code == 404 and body["code"] == "not_found", f"{code} {body}")
    finally:
        rest.stop()
    ev2 = query(db2, "SELECT actor_surface, actor_conn FROM events WHERE requirement_id=? "
                      "AND kind='state_change' ORDER BY seq DESC LIMIT 1", (rid2,))[0]
    ok("k_archive: REST 归属 surface=cli conn=rest:*",
       ev2["actor_surface"] == "cli" and ev2["actor_conn"].startswith("rest:"),
       f"{ev2['actor_surface']}/{ev2['actor_conn']}")
    db3 = new_db()
    code3, _ = cli_err(db3, "archive", "--requirement-id", "deadbeef")
    ok("k_archive: CLI archive 不存在 -> not_found", code3 == "not_found", code3)
    # (iii) archive 后 agent 写 -> no_active_claim（BCD I6"不可写"端到端，盲审 P2-3：
    # claim 未同事务结束或 write guard 漏新终态，任一坏都会红）
    db4 = new_db()
    rid4 = seed_req(db4, "k-arch-guard")
    m4 = MCP(db4).start()
    m4.call_ok("claim_task", {"requirement_id": rid4, "agent_name": "a"})
    m4.close()
    cli_ok(db4, "archive", "--requirement-id", rid4)
    m5 = MCP(db4).start()
    code4, _ = m5.call_err("add_record", {"requirement_id": rid4, "kind": "note", "title": "post-archive"})
    ok("k_archive(iii): archive 后 agent 写 -> no_active_claim（BCD I6）", code4 == "no_active_claim", code4)
    m5.close()


def k_delete():
    print("== M1-5.3: delete 五表原子零残留 + REST 404/MCP not_found + agent 写 not_found + 确认门 + 写锁竞争 503")
    def _rich(db, title):
        """富需求：claim（已结束）+ 子任务 + 里程碑 + note 事件。"""
        rid = seed_req(db, title)
        m = MCP(db).start()
        m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
        m.call_ok("add_subtask", {"requirement_id": rid, "title": "st1", "ordinal": 1})
        m.call_ok("add_milestone", {"requirement_id": rid, "title": "ms1", "planned_at": "2026-12-31T00:00:00Z"})
        m.call_ok("add_record", {"requirement_id": rid, "kind": "note", "title": "n1"})
        m.close()
        cli_ok(db, "release", "--requirement-id", rid, "--reason", "test release")
        return rid

    # (i) CLI --yes：五表零残留（含需求行本身）
    db = new_db()
    rid = _rich(db, "k-del-rich")
    res = _run_cli(db, ["delete", "--requirement-id", rid, "--yes"])
    ok("k_delete(i): CLI delete --yes 退出 0", res.returncode == 0, f"rc={res.returncode} stderr={res.stderr[-200:]}")
    body = json.loads(res.stdout)
    ok("k_delete(i): 响应 deleted=true", body.get("deleted") is True, str(body))
    rows = {t: query(db, f"SELECT COUNT(*) AS n FROM {t} WHERE requirement_id=?", (rid,))[0]["n"]
            for t in ("events", "subtasks", "milestones", "claims")}
    req_n = query(db, "SELECT COUNT(*) AS n FROM requirements WHERE id=?", (rid,))[0]["n"]
    ok("k_delete(i): 五表零残留（需求行本身不存在，与 prune 语义区分，审 P2-7）",
       all(v == 0 for v in rows.values()) and req_n == 0, f"{rows} req={req_n}")
    # (ii) REST 200 -> 404 + MCP not_found + list_tasks 排除
    db2 = new_db()
    rid2 = _rich(db2, "k-del-rest")
    rest = REST(db2).start()
    try:
        m = MCP(db2).start()
        code, b = rest.req("GET", f"/requirements/{rid2}")
        ok("k_delete(ii): 删前 GET detail 200", code == 200, str(code))
        code, b = rest.req("DELETE", f"/requirements/{rid2}")
        ok("k_delete(ii): REST DELETE 200 deleted=true", code == 200 and b.get("deleted") is True, f"{code} {b}")
        code, b = rest.req("GET", f"/requirements/{rid2}")
        ok("k_delete(ii): 删后 GET detail -> 404 not_found", code == 404 and b["code"] == "not_found", f"{code} {b}")
        code2, _ = m.call_err("get_task_detail", {"requirement_id": rid2})
        ok("k_delete(ii): MCP get_task_detail -> not_found", code2 == "not_found", code2)
        ids = [t["requirement_id"] for t in m.call_ok("list_tasks", {})["tasks"]]
        ok("k_delete(ii): list_tasks 不含已删任务", rid2 not in ids, str(ids))
        # (iii) agent 写操作 -> 结构化 not_found（非崩溃/挂起，BCD S8）
        code3, _ = m.call_err("add_record", {"requirement_id": rid2, "kind": "note", "title": "x"})
        ok("k_delete(iii): agent add_record 已删任务 -> not_found", code3 == "not_found", code3)
        m.close()
    finally:
        rest.stop()
    # (iv) 确认门：n / EOF / y（+--yes 已在 (i) 覆盖）
    for label, text, expect_del in (("n", "n\n", False), ("EOF", "", False), ("y", "y\n", True)):
        db3 = new_db()
        rid3 = _rich(db3, f"k-del-{label}")
        res3 = _run_cli(db3, ["delete", "--requirement-id", rid3], input_text=text)
        req_n3 = query(db3, "SELECT COUNT(*) AS n FROM requirements WHERE id=?", (rid3,))[0]["n"]
        ok(f"k_delete(iv): stdin '{label}' -> {'已删+退出0' if expect_del else '不删+非零退出+无traceback'}",
           (req_n3 == 0) == expect_del and (res3.returncode == 0) == expect_del
           and "Traceback" not in res3.stderr and "Traceback" not in res3.stdout,
           f"rc={res3.returncode} req={req_n3}")
        if not expect_del:
            ok(f"k_delete(iv): stdin '{label}' -> aborted 消息（prune 确认门同口径）",
               "aborted: nothing deleted" in res3.stderr, res3.stderr[-200:])
    # (v) 写锁竞争 -> 503 db_busy（结构化，非 500）
    db4 = new_db()
    rid4 = _rich(db4, "k-del-busy")
    rest2 = REST(db4, extra={"AGENT_KANBAN_BUSY_TIMEOUT_MS": "50"}).start()
    holder = sqlite3.connect(str(db4))
    holder.execute("BEGIN IMMEDIATE")
    try:
        code, b = rest2.req("DELETE", f"/requirements/{rid4}")
        ok("k_delete(v): 写锁竞争 -> 503 db_busy", code == 503 and b["code"] == "db_busy", f"{code} {b}")
        ok("k_delete(v): 竞争失败未删", query(db4, "SELECT COUNT(*) AS n FROM requirements WHERE id=?", (rid4,))[0]["n"] == 1, "deleted?")
    finally:
        holder.rollback()
        holder.close()
        rest2.stop()


def k_web():
    print("== M1-5.4: Web 壳契约——board 3 tab + 新建表单 + 卡片等待人提示 / 深潜决策按钮缺席 + 生命周期操作 + kind 级 CLI 提示")
    db = new_db()
    rid = seed_req(db, "k-web")
    secret = "K_WEB_SECRET_xyz"
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.call_ok("update_progress", {"requirement_id": rid, "note": secret})
    m.close()
    rest = REST(db, token="sekret").start()
    try:
        code, raw = rest.req("GET", "/", token="sekret")
        ok("k_web: board 壳 200 + board-root/EventSource（既有契约保持）",
           code == 200 and isinstance(raw, str) and 'id="board-root"' in raw and "EventSource" in raw, str(code))
        ok("k_web: board 3 tab（在板/已完成/已归档）",
           'data-tab="active"' in raw and 'data-tab="done"' in raw and 'data-tab="archived"' in raw, "tab 缺失")
        ok("k_web: 新建表单入口 + 字段锚",
           'id="new-btn"' in raw and 'id="nf-title"' in raw and 'id="nf-acc"' in raw and 'id="nf-jira"' in raw, "表单缺失")
        ok("k_web: 卡片等待人横幅含 CLI 提示（BCD F3 预防）", "kanban approve" in raw, "提示缺失")
        ok("k_web: board 壳无原始输出（既有契约保持）", secret not in raw, "shell leak")
        code, raw2 = rest.req("GET", f"/requirements/{rid}", token="sekret",
                              headers={"Accept": "text/html"})
        ok("k_web: 深潜壳 200 + detail-root（既有契约保持）",
           code == 200 and isinstance(raw2, str) and 'id="detail-root"' in raw2, str(code))
        for gone in ("data-op='approve'", "doRelease", "doReopen", "doAbandon", "doNote",
                     "doExpectations", "abandon-state", "note-input", "acc-input"):
            ok(f"k_web: 深潜壳决策操作缺席（{gone}）", gone not in raw2, "仍在壳内")
        ok("k_web: 生命周期操作在场（archive/delete）",
           "data-op='archive'" in raw2 and "doDelete" in raw2, "生命周期缺失")
        ok("k_web: 深潜等待人横幅 kind 级 CLI 提示",
           "人面确认: kanban approve" in raw2 and "解除阻塞: kanban approve" in raw2, "提示缺失")
        ok("k_web: 深潜壳无原始输出（既有契约保持）", secret not in raw2, "shell leak")
        # M1-6 T1 壳解析防线：JS 字符串字面量不得被未转义换行截断（P0：web.py 三引号串
        # 把 JS "\n" 转成真换行 -> 整 <script> 块 SyntaxError -> JS 零执行，看板恒"加载中"）
        ok('k_web(M1-6 A1): board 壳 split 换行转义以字面 2 字符 \\n 送达（spec 71 行一条锚）',
           '.value.split("\\n")' in raw and '.value.split("\n")' not in raw, "JS 换行转义被 Python 三引号串损坏")
        # 假阳边界（plan 审 P2 登记）：单引号 JS 字符串/正则字面量/注释内含奇数个双引号
        # 的行会假红；当前两壳零命中，属未来维护面。
        def _js_quote_parity(shell_html: str) -> bool:
            m = re.search(r"<script>(.*)</script>", shell_html, re.S)
            if not m:
                return False
            for line in m.group(1).splitlines():
                if re.sub(r"\\.", "", line.rstrip()).count('"') % 2 == 1:
                    return False
            return True
        ok("k_web(M1-6 A2): board+detail 壳 <script> 块逐行双引号配对（无字符串截断）",
           _js_quote_parity(raw) and _js_quote_parity(raw2), "存在未终止 JS 字符串字面量")
        # M1-6 T2 终态操作导航防线：archive/delete 成功后回看板（user 2026-10-26 第二轮
        # 原话：点了 archive 即不再期许看详情）。单根因 = handleOpResult 成功路径
        # flash+load() 重拉（delete->404 死页归因错 / archive->静默成功无反馈）
        # 抽取法（plan 审 P2-1 登记）：至首个列 0 的 `}` 止（lstrip 形态匹配缩进 `}`
        # 会在 if 闭合处截断块 -> 假红）
        _l = raw2.splitlines()
        _s = next(i for i, x in enumerate(_l) if x.startswith("async function handleOpResult"))
        _e = next(i for i in range(_s + 1, len(_l)) if _l[i] == "}")
        _op_block = "\n".join(_l[_s:_e + 1])
        ok("k_web(M1-6 A3): handleOpResult 成功回看板（location.href \"/\"）",
           'location.href = "/"' in _op_block, "缺回看板导航")
        ok("k_web(M1-6 A4): handleOpResult 成功路径无 load() 重拉（杜绝死页/静默成功）",
           "load()" not in _op_block, "残留 load() 重拉")
        # AC1 数据路径：Web 表单映射的 payload（一行一条 -> {item}）+ jira 映射（spec case 7）
        # token 必带（REST 以 token="sekret" 启动，中间件对全路径强制，T4 红跑实证 401）
        code, body = rest.req("POST", "/requirements", {"title": "k-create",
                                                        "acceptance": [{"item": "吞吐 >= 5000"}, {"item": "p99 < 200ms"}]},
                              token="sekret")
        ok("k_web(AC1): 两行锚 create 201 OPEN", code == 201 and body["state"] == "OPEN", f"{code} {body}")
        ridc = body["requirement_id"]
        code, s = rest.req("GET", f"/requirements/{ridc}/summary", token="sekret")
        a_ids = [a["anchor_id"] for a in s["acceptance_table"]]
        ok("k_web(AC1): 锚自动编号 a1/a2（normalize_anchors）", a_ids == ["a1", "a2"], str(a_ids))
        code, body = rest.req("POST", "/requirements",
                              {"title": "k-create-jira", "source": "jira", "source_ref": "https://jira.example/X-1"},
                              token="sekret")
        row_c = query(db, "SELECT source, source_ref FROM requirements WHERE id=?", (body["requirement_id"],))[0]
        ok("k_web(AC1): jira 链接 -> source=jira + source_ref 映射",
           row_c["source"] == "jira" and row_c["source_ref"] == "https://jira.example/X-1", str(dict(row_c)))
    finally:
        rest.stop()
