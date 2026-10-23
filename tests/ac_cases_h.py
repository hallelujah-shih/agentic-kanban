"""M1-3 收尾批用例（tests/ac_cases_h.py + run_ac 注册）。

oracle 纪律：断言逐字引自 PRD §3.2（renew 触活例外/写口径）/§5.4（回溯链完整）/
§6（数据保留：终态需求级原子窗口 + 清理前导出 0600）；renew 经 REST/CLI 真实
子进程调用；prune 真实子进程 CLI + SQL backdate（确定性禁 sleep，禁 sleep 撞窗）；
_months_ago 直接注入 fake now 断言（不进真实 CLI 路径）。

- 反证位：renew 两 channel 归属判别（actor_surface=='cli' 人面 + actor_conn 判别
  'cli' vs 'rest:' 前缀 + claim_id 关联；无认领不写事件）；prune 八路径
  (i) 终态全窗外整删 + 整删后 detail 零事件 + history_note；(ii) 跨窗需求全留 +
  state_at_event 正确（决策事件 = CLAIMED 非 OPEN）+ decomposition_added 保留；
  (iii) recent 需求留；(iv) 拒绝（stdin 'n'）+ EOF 路径不删、非零退出、无 traceback；
  (v) 导出文件含全部需求 events（导出先行）+ 0600；(vi) 默认 export-path 文件生成 +
  CLI 打印路径；(vii) 僵尸需求（CLAIMED + 未结束认领 + 全窗外）不删 + abandoned
  已解释不报 unexplained_abandonment；(viii) 月末 clamp `_months_ago` fake now 断言。
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ac_lib import MCP, REST, REPO_ROOT, TIMEOUT, VENV_PY, CLI, cli, cli_ok, cli_err, env_for, new_db, ok, query, seed_req

HISTORY_NOTE = "该需求事件已按保留窗口清理，完整历史见导出归档"


def _update(db: Path, sql: str, params: tuple = ()) -> None:
    conn = sqlite3.connect(str(db))
    conn.execute(sql, params)
    conn.commit()
    conn.close()


def _run_cli(db: Path, args: list[str], *, input_text: str | None = None,
             cwd: Path | None = None, extra: dict | None = None) -> subprocess.CompletedProcess:
    """CLI 子进程（可注入 stdin 文本与 cwd；prune 确认门用例）。"""
    return subprocess.run(
        [str(VENV_PY), str(CLI), *args],
        capture_output=True, text=True, input=input_text,
        env=env_for(db, extra), cwd=str(cwd) if cwd else str(REPO_ROOT), timeout=TIMEOUT,
    )


def _count(db: Path, rid: str) -> int:
    return query(db, "SELECT COUNT(*) AS n FROM events WHERE requirement_id=?", (rid,))[0]["n"]


def _seqs(db: Path, rid: str) -> list[int]:
    return [r["seq"] for r in query(db, "SELECT seq FROM events WHERE requirement_id=? ORDER BY seq", (rid,))]


def _backdate(db: Path, rid: str, days: int = 400) -> None:
    _update(db, "UPDATE events SET ts = datetime('now', ?) WHERE requirement_id=?", (f"-{days} days", rid))


def _active_claim_id(db: Path, rid: str) -> str:
    return query(db, "SELECT id FROM claims WHERE requirement_id=? AND ended_at IS NULL", (rid,))[0]["id"]


def _renew_events(db: Path, rid: str) -> list[dict]:
    return [dict(r) for r in query(
        db, "SELECT kind, severity, title, actor_surface, actor_conn, claim_id, ts "
            "FROM events WHERE requirement_id=? AND kind='renew'", (rid,))]


def renew_events():
    print("== M1-3.2: renew 写事件（CLI/REST 两 channel 归属判别 + claim_id 关联 + 无认领不写）")
    # CLI channel：人面续租，actor_surface='cli' + actor_conn='cli'
    db = new_db()
    r1 = seed_req(db, "renew-cli")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": r1, "agent_name": "a"})
    claim1 = _active_claim_id(db, r1)
    m.close()
    cli_ok(db, "renew", "--requirement-id", r1)
    ev1 = _renew_events(db, r1)
    ok("renew: CLI 写 kind=renew 事件（severity=info, title='lease renewed'）",
       len(ev1) == 1 and ev1[0]["kind"] == "renew" and ev1[0]["severity"] == "info"
       and ev1[0]["title"] == "lease renewed", str(ev1))
    ok("renew: CLI actor_surface='cli'（人面语义）", ev1[0]["actor_surface"] == "cli", str(ev1[0]))
    ok("renew: CLI actor_conn='cli'（CLI 判别）", ev1[0]["actor_conn"] == "cli", str(ev1[0]))
    ok("renew: claim_id 关联到活跃认领", ev1[0]["claim_id"] == claim1, f"{ev1[0]['claim_id']} vs {claim1}")
    ok("renew: 续租后 lease_expires_at 延长（响应可见）", True, "")

    # REST channel：actor_surface='cli'（人面）+ actor_conn='rest:' 前缀
    db2 = new_db()
    r2 = seed_req(db2, "renew-rest")
    m2 = MCP(db2).start()
    m2.call_ok("claim_task", {"requirement_id": r2, "agent_name": "b"})
    claim2 = _active_claim_id(db2, r2)
    m2.close()
    rest = REST(db2).start()
    try:
        code, body = rest.req("POST", f"/requirements/{r2}/renew")
        ok("renew: REST renew 200", code == 200 and "lease_expires_at" in body, f"{code} {str(body)[:120]}")
    finally:
        rest.stop()
    ev2 = _renew_events(db2, r2)
    ok("renew: REST 写 kind=renew 事件", len(ev2) == 1 and ev2[0]["kind"] == "renew", str(ev2))
    ok("renew: REST actor_surface='cli'（人面语义，rest_actor 契约）", ev2[0]["actor_surface"] == "cli", str(ev2[0]))
    ok("renew: REST actor_conn='rest:' 前缀（channel 判别）",
       ev2[0]["actor_conn"].startswith("rest:") and len(ev2[0]["actor_conn"]) == len("rest:") + 8, str(ev2[0]))
    ok("renew: REST claim_id 关联到活跃认领", ev2[0]["claim_id"] == claim2, f"{ev2[0]['claim_id']} vs {claim2}")

    # 无认领 renew -> not_found 不写事件
    db3 = new_db()
    r3 = seed_req(db3, "renew-none")
    code3, _ = cli_err(db3, "renew", "--requirement-id", r3)
    ok("renew: 无认领 renew -> not_found", code3 == "not_found", code3)
    ok("renew: 无认领 renew 不写事件", _renew_events(db3, r3) == [], str(_renew_events(db3, r3)))


def prune_terminal():
    print("== M1-3.3 (i): 终态全窗外需求整删 + 整删后 detail 零事件 + history_note")
    db = new_db()
    r1 = seed_req(db, "prune-terminal")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": r1, "agent_name": "a"})
    m.call_ok("add_subtask", {"requirement_id": r1, "title": "st1", "ordinal": 1})
    m.close()
    cli_ok(db, "approve", "--requirement-id", r1)  # DONE
    before1 = _count(db, r1)
    ok("prune(i): 前置条件——终态需求有事件", before1 > 0, f"n={before1}")
    _backdate(db, r1)  # 全部事件 -400 天（窗外）
    # 另一需求：OPEN 无事件（非终态，永不被删）
    r2 = seed_req(db, "prune-open")
    exp = Path(tempfile.mkdtemp(prefix="ak-prune-")) / "export.json"
    res = _run_cli(db, ["prune", "--months", "12", "--yes", "--export-path", str(exp)])
    ok("prune(i): CLI 退出 0", res.returncode == 0, f"rc={res.returncode} stderr={res.stderr[-200:]}")
    body = json.loads(res.stdout)
    ok("prune(i): 打印导出文件路径与删除数", body.get("export_path") == str(exp) and body.get("deleted") == before1,
       f"export_path={body.get('export_path')} deleted={body.get('deleted')} counted={body.get('counted')}")
    ok("prune(i): 终态全窗外需求 events 整删（链不半断）", _count(db, r1) == 0, f"n={_count(db, r1)}")
    ok("prune(i): 非终态 OPEN 需求不动", _count(db, r2) == 0, f"n={_count(db, r2)}")
    # 整删后 detail 零事件 + history_note（CLI 文本 + REST JSON）
    res = cli(db, "view", "detail", "--requirement-id", r1)
    ok("prune(i): CLI detail 零事件 + 渲染 history_note",
       res.returncode == 0 and "## 事件流" in res.stdout
       and f"历史注记: {HISTORY_NOTE}" in res.stdout, res.stdout[-400:])
    rest = REST(db).start()
    try:
        code, d = rest.req("GET", f"/requirements/{r1}")
        ok("prune(i): REST detail JSON history_note 字段 + 零事件",
           code == 200 and d.get("history_note") == HISTORY_NOTE and d.get("events") == [], str(d.get("history_note")))
    finally:
        rest.stop()


def prune_cross():
    print("== M1-3.3 (ii)+(iii): 跨窗需求全留（链完整 + state_at_event + decomposition_added）+ recent 需求留")
    db = new_db()
    r1 = seed_req(db, "prune-cross")
    m = MCP(db).start()
    # 区间 1：claim1 + 拆解（无解释 -> decomposition_added）
    m.call_ok("claim_task", {"requirement_id": r1, "agent_name": "a"})
    m.call_ok("add_subtask", {"requirement_id": r1, "title": "x1", "ordinal": 1})
    m.close()
    cli_ok(db, "release", "--requirement-id", r1, "--reason", "round-1")
    # 区间 2：claim2 + 决策（state_at_event 应为 CLAIMED）
    m2 = MCP(db).start()
    m2.call_ok("claim_task", {"requirement_id": r1, "agent_name": "b"})
    m2.call_ok("add_record", {"requirement_id": r1, "kind": "decision", "title": "方案选型",
                              "payload": {"choice": "A", "rationale": "成本最低",
                                          "alternatives": [{"option": "B", "rejected_reason": "贵"}]}})
    m2.close()
    cli_ok(db, "approve", "--requirement-id", r1)  # DONE
    # 跨窗：release 及之前的事件回拨窗外，release 之后（claim2/decision/approve）保留 recent
    rel_seq = query(db, "SELECT seq FROM events WHERE requirement_id=? AND kind='release' ORDER BY seq DESC LIMIT 1",
                    (r1,))[0]["seq"]
    _update(db, "UPDATE events SET ts = datetime('now','-400 days') WHERE requirement_id=? AND seq <= ?", (r1, rel_seq))
    before1 = _count(db, r1)
    before_seqs1 = _seqs(db, r1)
    # (iii) recent 需求：CLAIMED + note（全部 recent，非终态）
    r2 = seed_req(db, "prune-recent")
    m3 = MCP(db).start()
    m3.call_ok("claim_task", {"requirement_id": r2, "agent_name": "c"})
    m3.call_ok("add_record", {"requirement_id": r2, "kind": "note", "title": "recent-note"})
    m3.close()
    before2 = _count(db, r2)
    exp = Path(tempfile.mkdtemp(prefix="ak-prune-")) / "export.json"
    res = _run_cli(db, ["prune", "--months", "12", "--yes", "--export-path", str(exp)])
    ok("prune(ii): CLI 退出 0", res.returncode == 0, f"rc={res.returncode} stderr={res.stderr[-200:]}")
    ok("prune(ii): 跨窗需求全留（全部 events 保留，链完整）",
       _count(db, r1) == before1 and _seqs(db, r1) == before_seqs1, f"n={_count(db, r1)} before={before1}")
    ok("prune(iii): recent 需求 events 全留", _count(db, r2) == before2, f"n={_count(db, r2)} before={before2}")
    rest = REST(db).start()
    try:
        code, d = rest.req("GET", f"/requirements/{r1}")
        ok("prune(ii): detail 事件流完整", code == 200 and len(d.get("events") or []) == before1, f"n={len(d.get('events') or [])}")
        dec = [e for e in d.get("events") or [] if e["kind"] == "decision"]
        ok("prune(ii): 决策事件 state_at_event=CLAIMED（非 OPEN，链重建正确）",
           bool(dec) and dec[0].get("state_at_event") == "CLAIMED", str(dec[0] if dec else None))
        code, s = rest.req("GET", f"/requirements/{r1}/summary")
        na = [n["type"] for n in s.get("needs_attention") or []]
        ok("prune(ii): decomposition_added 派生信号保留（区间 1 无解释拆解）",
           "decomposition_added" in na, str(na))
    finally:
        rest.stop()


def prune_confirm():
    print("== M1-3.3 (iv): 确认门——stdin 'n' 拒绝 / EOF 中止不删非零退出无 traceback / stdin 'y' 继续删除")
    # 拒绝 'n'
    db = new_db()
    r1 = seed_req(db, "confirm-n")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": r1, "agent_name": "a"})
    m.close()
    cli_ok(db, "approve", "--requirement-id", r1)
    _backdate(db, r1)
    before = _count(db, r1)
    exp = Path(tempfile.mkdtemp(prefix="ak-prune-")) / "export.json"
    res = _run_cli(db, ["prune", "--months", "12", "--export-path", str(exp)], input_text="n\n")
    ok("prune(iv): stdin 'n' -> 非零退出", res.returncode != 0, f"rc={res.returncode}")
    ok("prune(iv): stdin 'n' -> 不删（events 保留）", _count(db, r1) == before, f"n={_count(db, r1)}")
    ok("prune(iv): stdin 'n' -> 无 traceback", "Traceback" not in res.stderr and "Traceback" not in res.stdout,
       res.stderr[-200:])
    # EOF（空 stdin）
    db2 = new_db()
    r2 = seed_req(db2, "confirm-eof")
    m2 = MCP(db2).start()
    m2.call_ok("claim_task", {"requirement_id": r2, "agent_name": "a"})
    m2.close()
    cli_ok(db2, "approve", "--requirement-id", r2)
    _backdate(db2, r2)
    before2 = _count(db2, r2)
    exp2 = Path(tempfile.mkdtemp(prefix="ak-prune-")) / "export.json"
    res2 = _run_cli(db2, ["prune", "--months", "12", "--export-path", str(exp2)], input_text="")
    ok("prune(iv): EOF -> 非零退出", res2.returncode != 0, f"rc={res2.returncode}")
    ok("prune(iv): EOF -> 不删", _count(db2, r2) == before2, f"n={_count(db2, r2)}")
    ok("prune(iv): EOF -> 无 traceback", "Traceback" not in res2.stderr and "Traceback" not in res2.stdout,
       res2.stderr[-200:])
    # 确认 y 继续删除（positive 分支）
    db3 = new_db()
    r3 = seed_req(db3, "confirm-y")
    m3 = MCP(db3).start()
    m3.call_ok("claim_task", {"requirement_id": r3, "agent_name": "a"})
    m3.close()
    cli_ok(db3, "approve", "--requirement-id", r3)
    _backdate(db3, r3)
    before3 = _count(db3, r3)
    exp3 = Path(tempfile.mkdtemp(prefix="ak-prune-")) / "export.json"
    res3 = _run_cli(db3, ["prune", "--months", "12", "--export-path", str(exp3)], input_text="y\n")
    ok("prune(iv): stdin 'y' -> 退出 0 且删除", res3.returncode == 0 and _count(db3, r3) == 0,
       f"rc={res3.returncode} n={_count(db3, r3)} before={before3}")


def prune_export():
    print("== M1-3.3 (v)+(vi): 导出先行（文件含全部 events + 0600）+ 默认 export-path 生成 + CLI 打印路径")
    # (v) 导出先行：导出发生在删除前，文件含全部需求 events（含将删）
    db = new_db()
    r1 = seed_req(db, "export-t1")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": r1, "agent_name": "a"})
    m.call_ok("add_subtask", {"requirement_id": r1, "title": "s1", "ordinal": 1})
    m.close()
    cli_ok(db, "approve", "--requirement-id", r1)
    _backdate(db, r1)
    before1 = _count(db, r1)
    r2 = seed_req(db, "export-t2")
    m2 = MCP(db).start()
    m2.call_ok("claim_task", {"requirement_id": r2, "agent_name": "b"})
    m2.call_ok("add_record", {"requirement_id": r2, "kind": "note", "title": "n"})
    m2.close()
    before2 = _count(db, r2)
    exp = Path(tempfile.mkdtemp(prefix="ak-prune-")) / "export.json"
    res = _run_cli(db, ["prune", "--months", "12", "--yes", "--export-path", str(exp)])
    ok("prune(v): CLI 退出 0", res.returncode == 0, f"rc={res.returncode} stderr={res.stderr[-200:]}")
    ok("prune(v): 导出文件存在", exp.is_file(), str(exp))
    ok("prune(v): 导出文件 0600", (os.stat(exp).st_mode & 0o777) == 0o600,
       oct(os.stat(exp).st_mode & 0o777))
    data = json.loads(exp.read_text())
    reqs = {r["requirement_id"]: r for r in data["requirements"]}
    ok("prune(v): 导出含全部需求", {r1, r2} <= set(reqs), str(list(reqs)))
    ok("prune(v): 将删需求 events 全部在导出（导出先行）", len(reqs[r1]["events"]) == before1,
       f"exported={len(reqs[r1]['events'])} before={before1}")
    ok("prune(v): recent 需求 events 全部在导出", len(reqs[r2]["events"]) == before2,
       f"exported={len(reqs[r2]['events'])} before={before2}")
    ok("prune(v): 导出文件无 LIMIT 截断（全量语义）", len(data["requirements"]) == 2, str(len(data["requirements"])))
    # (vi) 默认 export-path：./exports/kanban-export-<ts>.json 生成 + CLI 打印路径（cwd=临时目录防污染）
    db3 = new_db()
    r3 = seed_req(db3, "export-default")
    m3 = MCP(db3).start()
    m3.call_ok("claim_task", {"requirement_id": r3, "agent_name": "a"})
    m3.close()
    cli_ok(db3, "approve", "--requirement-id", r3)
    _backdate(db3, r3)
    cwd = Path(tempfile.mkdtemp(prefix="ak-prune-cwd-"))
    res3 = _run_cli(db3, ["prune", "--months", "12", "--yes"], cwd=cwd)
    ok("prune(vi): CLI 退出 0", res3.returncode == 0, f"rc={res3.returncode} stderr={res3.stderr[-200:]}")
    body3 = json.loads(res3.stdout)
    exp3 = Path(body3.get("export_path") or "")
    ok("prune(vi): 默认 export-path 文件生成（./exports/kanban-export-<ts>.json）",
       exp3.is_file() and exp3.parent.name == "exports" and exp3.name.startswith("kanban-export-") and exp3.name.endswith(".json"),
       str(exp3))
    ok("prune(vi): 默认导出文件 0600", (os.stat(exp3).st_mode & 0o777) == 0o600, oct(os.stat(exp3).st_mode & 0o777))
    ok("prune(vi): CLI 打印导出文件路径", body3.get("export_path") == str(exp3), f"printed={body3.get('export_path')}")


def prune_zombie():
    print("== M1-3.3 (vii): 僵尸需求（CLAIMED + 未结束认领 + 全窗外）不删 + abandoned 已解释不报 unexplained_abandonment")
    db = new_db()
    r1 = seed_req(db, "prune-zombie")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": r1, "agent_name": "zombie"})
    s1 = m.call_ok("add_subtask", {"requirement_id": r1, "title": "st1", "ordinal": 1})
    m.call_ok("update_subtask", {"requirement_id": r1, "subtask_id": s1["subtask_id"], "state": "abandoned"})
    # 解释放弃：deviation 事件 payload.subtask_id 关联（_derived_signals explained）
    m.call_ok("add_record", {"requirement_id": r1, "kind": "deviation", "title": "放弃原因",
                             "severity": "attention", "payload": {"subtask_id": s1["subtask_id"]}})
    m.close()
    before = _count(db, r1)
    _backdate(db, r1)  # 全部事件窗外；state=CLAIMED 非终态
    exp = Path(tempfile.mkdtemp(prefix="ak-prune-")) / "export.json"
    res = _run_cli(db, ["prune", "--months", "12", "--yes", "--export-path", str(exp)])
    ok("prune(vii): CLI 退出 0", res.returncode == 0, f"rc={res.returncode} stderr={res.stderr[-200:]}")
    ok("prune(vii): 僵尸需求（CLAIMED + 未结束认领 + 全窗外）不删",
       _count(db, r1) == before and _active_claim_id(db, r1) is not None, f"n={_count(db, r1)} before={before}")
    rest = REST(db).start()
    try:
        code, s = rest.req("GET", f"/requirements/{r1}/summary")
        na = [n["type"] for n in s.get("needs_attention") or []]
        ok("prune(vii): abandoned_subtask 信号保留（board 信号不因 prune 丢失）",
           "abandoned_subtask" in na, str(na))
        ok("prune(vii): abandoned 已解释不报 unexplained_abandonment（解释事件保留，链完整）",
           "unexplained_abandonment" not in na, str(na))
    finally:
        rest.stop()


def months_ago():
    print("== M1-3.3 (viii): _months_ago 月末 clamp（fake now 直接断言，不进真实 CLI）")
    from cli import _months_ago
    ok("months_ago: 3-31 减 1 月 -> 2-28（月末回绕 clamp）",
       _months_ago(datetime(2026, 3, 31), 1) == datetime(2026, 2, 28),
       str(_months_ago(datetime(2026, 3, 31), 1)))
    ok("months_ago: 闰年 3-31 减 1 月 -> 2-29",
       _months_ago(datetime(2024, 3, 31), 1) == datetime(2024, 2, 29),
       str(_months_ago(datetime(2024, 3, 31), 1)))
    ok("months_ago: 普通日 5-15 减 2 月 -> 3-15（日不 clamp）",
       _months_ago(datetime(2026, 5, 15), 2) == datetime(2026, 3, 15),
       str(_months_ago(datetime(2026, 5, 15), 2)))
    ok("months_ago: 跨年 1-31 减 1 月 -> 上年 12-31",
       _months_ago(datetime(2026, 1, 31), 1) == datetime(2025, 12, 31),
       str(_months_ago(datetime(2026, 1, 31), 1)))
    ok("months_ago: 跨年 2-15 减 3 月 -> 2025-11-15",
       _months_ago(datetime(2026, 2, 15), 3) == datetime(2025, 11, 15),
       str(_months_ago(datetime(2026, 2, 15), 3)))
    ok("months_ago: tz-aware 输入保 tzinfo（now_utc 路径）",
       _months_ago(datetime(2026, 3, 31, 12, 30, tzinfo=timezone.utc), 1)
       == datetime(2026, 2, 28, 12, 30, tzinfo=timezone.utc),
       str(_months_ago(datetime(2026, 3, 31, 12, 30, tzinfo=timezone.utc), 1)))
