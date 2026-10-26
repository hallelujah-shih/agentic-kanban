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
