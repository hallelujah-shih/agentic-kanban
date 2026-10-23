"""M1-4 用例（tests/ac_cases_i.py + run_ac 注册）：G9-b 重试成本超限判定（BCD g9b-retry-limit）。

oracle 纪律：断言逐字引自 PRD §3.2（不自动重试/累计重试超 2 次等你决策/实现注记）+
BCD §4/§5/§7（S1-S3/边缘 1-5/例 5/跨时段；强不变量 1-5）；update_subtask 经真实
MCP stdio 客户端调用；view 经真实 REST 子进程（summary/board 同源）；DB 事后
sqlite3 直查（读数据非读实现代码）。禁 sleep。

- 反证位：阈值边界（重试 2 不触发 / 第 3 次重入触发）；幂等（事件数钉死 1 + count
  触发时点快照）；首入与 no-op 不计；done 重开 + todo 退回再进各计重试；里程碑
  in_progress 迁移 >= 5 次不计（误计将达 retries>=4 触发，负例判别力）；agent 伪造
  marker（actor_surface=mcp）不抑制告警不进信号但显示 risks；跨 claim 周期累计延续；
  board==summary 同源 + marker 归属（actor_surface=system/actor_conn=system/claim_id）。
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ac_lib import MCP, REST, cli, cli_ok, new_db, ok, query, seed_req

RETRY_LIMIT_TITLE = "累计重试超 2 次，需要人决策"


def _active_claim(db, rid: str) -> str | None:
    rows = query(db, "SELECT id FROM claims WHERE requirement_id=? AND ended_at IS NULL", (rid,))
    return rows[0]["id"] if rows else None


def _risk_events(db, rid: str) -> list[dict]:
    """全部 kind='risk' 事件（含 agent 伪造），payload 已解析，按 seq 升序。"""
    rows = query(
        db, "SELECT seq, kind, severity, title, payload, actor_surface, actor_conn, claim_id "
            "FROM events WHERE requirement_id=? AND kind='risk' ORDER BY seq", (rid,))
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = json.loads(d["payload"]) if d["payload"] else None
        out.append(d)
    return out


def _retry_events(db, rid: str) -> list[dict]:
    """payload.retry_limit 为真的 risk 事件（含伪造——反伪造判别靠 actor_surface）。"""
    return [e for e in _risk_events(db, rid) if (e["payload"] or {}).get("retry_limit")]


def _system_retry_events(db, rid: str) -> list[dict]:
    """系统 marker（幂等谓词口径：retry_limit + actor_surface=system）。"""
    return [e for e in _retry_events(db, rid) if e["actor_surface"] == "system"]


def _state_change_payloads(db, rid: str) -> list[dict]:
    rows = query(db, "SELECT payload FROM events WHERE requirement_id=? AND kind='state_change' ORDER BY seq", (rid,))
    return [json.loads(r["payload"]) if r["payload"] else {} for r in rows]


def _retry_signal(na: list | None) -> dict | None:
    return next((n for n in (na or []) if n.get("type") == "retry_limit"), None)


def _first(evs: list[dict]) -> dict:
    return evs[0] if evs else {}


def _cycle_in_progress(m: MCP, rid: str, sid: str, n: int) -> None:
    """子任务 ip->blocked->ip 循环 n 次 = 重入 in_progress n 次（每次计一次重试）。"""
    for _ in range(n):
        m.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": sid, "state": "blocked"})
        m.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": sid, "state": "in_progress"})


def _to_ip(m: MCP, rid: str, sid: str) -> None:
    m.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": sid, "state": "in_progress"})


def retry_s1():
    print("== M1-4 S1: 阈值触发（第 3 次重入 -> 同事务 risk 事件 + needs_attention retry_limit + risks 列表 + 归属）")
    db = new_db()
    rid = seed_req(db, "s1")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    claim_id = _active_claim(db, rid)
    st = m.call_ok("add_subtask", {"requirement_id": rid, "title": "s1", "ordinal": 1})["subtask_id"]
    _to_ip(m, rid, st)          # 首入（不计）
    _cycle_in_progress(m, rid, st, 2)  # 重试 1、2（未超）
    ok("s1: 重试 2 未触发（无 risk 事件）", _retry_events(db, rid) == [], str(_retry_events(db, rid)))
    _cycle_in_progress(m, rid, st, 1)  # 重试 3 -> 触发
    m.close()
    evs = _system_retry_events(db, rid)
    ok("s1: 触发写一条 risk 事件（系统 marker 数 = 1）", len(evs) == 1, str(evs))
    ev = _first(evs)
    ok("s1: kind=risk + severity=attention + title=累计重试超 2 次，需要人决策",
       ev.get("kind") == "risk" and ev.get("severity") == "attention" and ev.get("title") == RETRY_LIMIT_TITLE, str(ev))
    ok("s1: payload={retry_limit:true, count:3}（触发时点快照）",
       (ev.get("payload") or {}).get("retry_limit") is True and (ev.get("payload") or {}).get("count") == 3,
       str(ev.get("payload")))
    ok("s1: marker actor_surface=system + actor_conn=system（系统派生，先例 reconcile）",
       ev.get("actor_surface") == "system" and ev.get("actor_conn") == "system",
       f"{ev.get('actor_surface')}:{ev.get('actor_conn')}")
    ok("s1: marker claim_id 关联到活跃认领", ev.get("claim_id") == claim_id,
       f"{ev.get('claim_id')} vs {claim_id}")
    rest = REST(db).start()
    try:
        code, s = rest.req("GET", f"/requirements/{rid}/summary")
        sig = _retry_signal(s.get("needs_attention"))
        ok("s1: 摘要 needs_attention 含 retry_limit（count=3）",
           code == 200 and sig is not None and sig.get("count") == 3, str(sig))
        ok("s1: risks 列表含该风险事件（severity>=attention，PRD 5.3 口径）",
           any(r.get("title") == RETRY_LIMIT_TITLE and r.get("severity") == "attention" for r in s.get("risks")),
           str(s.get("risks")))
    finally:
        rest.stop()


def retry_s2():
    print("== M1-4 S2: 重试 2 次不触发（严格超 2：第 3 次进入 in_progress 重试计 2 未超）")
    db = new_db()
    rid = seed_req(db, "s2")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    st = m.call_ok("add_subtask", {"requirement_id": rid, "title": "s2", "ordinal": 1})["subtask_id"]
    _to_ip(m, rid, st)              # 首入
    _cycle_in_progress(m, rid, st, 2)  # 重试 1、2
    m.close()
    ok("s2: 重试 2 无 risk 事件（无系统 marker）", _system_retry_events(db, rid) == [], str(_system_retry_events(db, rid)))
    rest = REST(db).start()
    try:
        code, s = rest.req("GET", f"/requirements/{rid}/summary")
        ok("s2: needs_attention 无 retry_limit 信号",
           code == 200 and _retry_signal(s.get("needs_attention")) is None, str(s.get("needs_attention")))
    finally:
        rest.stop()


def retry_s3():
    print("== M1-4 S3: 跨子任务累计（BCD §4 S3 + 例 2：A 重入 1 + B 重入 2 = 需求级 3 -> B 第 2 次重入触发）")
    db = new_db()
    rid = seed_req(db, "s3")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    a = m.call_ok("add_subtask", {"requirement_id": rid, "title": "A", "ordinal": 1})["subtask_id"]
    b = m.call_ok("add_subtask", {"requirement_id": rid, "title": "B", "ordinal": 2})["subtask_id"]
    _to_ip(m, rid, a)  # A 首入
    _to_ip(m, rid, b)  # B 首入
    _cycle_in_progress(m, rid, a, 1)  # A 重试 1（需求累计 1）
    _cycle_in_progress(m, rid, b, 1)  # B 重试 1（需求累计 2）
    ok("s3: 跨子任务累计 2 未触发", _system_retry_events(db, rid) == [], str(_system_retry_events(db, rid)))
    _cycle_in_progress(m, rid, b, 1)  # B 重试 2（需求累计 3）-> 触发
    m.close()
    evs = _system_retry_events(db, rid)
    ok("s3: 需求累计 3 触发（B 第 2 次重入时，需求级累计语义成立）",
       len(evs) == 1 and (evs[0]["payload"] or {}).get("count") == 3, str(evs))


def retry_edge1():
    print("== M1-4 边缘 1: 幂等（触发后 3 次重入事件数保持 1 + 信号保持 + payload.count 仍 = 3 快照）")
    db = new_db()
    rid = seed_req(db, "e1")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    st = m.call_ok("add_subtask", {"requirement_id": rid, "title": "e1", "ordinal": 1})["subtask_id"]
    _to_ip(m, rid, st)
    _cycle_in_progress(m, rid, st, 3)  # 重试 1、2、3 -> 第 3 次触发
    ok("edge1: 触发时 marker 数 = 1", len(_system_retry_events(db, rid)) == 1, str(_system_retry_events(db, rid)))
    _cycle_in_progress(m, rid, st, 3)  # 重试 4、5、6（幂等：不再写）
    m.close()
    evs = _system_retry_events(db, rid)
    ok("edge1: 触发后 3 次重入事件数保持 1（幂等只写一次，PRD 实现注记）", len(evs) == 1, str(evs))
    ok("edge1: payload.count 仍 = 3（触发时点快照，不随后续重试更新）",
       (_first(evs).get("payload") or {}).get("count") == 3, str(_first(evs).get("payload")))
    rest = REST(db).start()
    try:
        code, s = rest.req("GET", f"/requirements/{rid}/summary")
        sig = _retry_signal(s.get("needs_attention"))
        ok("edge1: retry_limit 信号保持（count=3，不更新）",
           code == 200 and sig is not None and sig.get("count") == 3, str(sig))
    finally:
        rest.stop()


def retry_edge2():
    print("== M1-4 边缘 2: 首入不计 + no-op（in_progress->in_progress）不计")
    db = new_db()
    rid = seed_req(db, "e2")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    st = m.call_ok("add_subtask", {"requirement_id": rid, "title": "e2", "ordinal": 1})["subtask_id"]
    _to_ip(m, rid, st)              # 首入
    _to_ip(m, rid, st)              # no-op 1
    _to_ip(m, rid, st)              # no-op 2
    m.close()
    sc = _state_change_payloads(db, rid)
    ip_entries = [p for p in sc if p.get("subtask_id") and p.get("to") == "in_progress"]
    no_ops = [p for p in ip_entries if p.get("from") == "in_progress"]
    ok("edge2: 3 条 in_progress state_change 事件落库（1 首入 + 2 no-op）",
       len(ip_entries) == 3 and len(no_ops) == 2, str(ip_entries))
    ok("edge2: 重试 0 无 risk 事件（永不触发）", _system_retry_events(db, rid) == [], str(_system_retry_events(db, rid)))
    rest = REST(db).start()
    try:
        code, s = rest.req("GET", f"/requirements/{rid}/summary")
        ok("edge2: needs_attention 无 retry_limit 信号",
           code == 200 and _retry_signal(s.get("needs_attention")) is None, str(s.get("needs_attention")))
    finally:
        rest.stop()


def retry_edge3():
    print("== M1-4 边缘 3: done 重开 + todo 退回再进各计重试（user 裁决：任何非 in_progress 重入都计）")
    db = new_db()
    rid = seed_req(db, "e3")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    a = m.call_ok("add_subtask", {"requirement_id": rid, "title": "A", "ordinal": 1})["subtask_id"]
    b = m.call_ok("add_subtask", {"requirement_id": rid, "title": "B", "ordinal": 2})["subtask_id"]
    _to_ip(m, rid, a)
    m.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": a, "state": "done"})
    _to_ip(m, rid, b)
    m.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": b, "state": "todo"})
    # done 重开（A done -> in_progress）计重试 1；todo 退回再进（B todo -> in_progress）计重试 2
    m.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": a, "state": "in_progress"})
    m.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": b, "state": "in_progress"})
    ok("edge3: done 重开 + todo 退回再进各计一次（累计 2 未触发）",
       _system_retry_events(db, rid) == [], str(_system_retry_events(db, rid)))
    # 第 3 次重入（A 重开再计 1）-> 触发
    m.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": a, "state": "done"})
    m.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": a, "state": "in_progress"})
    m.close()
    evs = _system_retry_events(db, rid)
    ok("edge3: 累计重试 3 触发（done 重开路径同样计重试）",
       len(evs) == 1 and (_first(evs).get("payload") or {}).get("count") == 3, str(evs))


def retry_edge4():
    print("== M1-4 边缘 4: 里程碑 in_progress 迁移 >= 5 次不计（负例判别力：误计将达 retries>=4 触发）")
    db = new_db()
    rid = seed_req(db, "e4")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    ms = m.call_ok("add_milestone", {"requirement_id": rid, "title": "M"})["milestone_id"]
    # 5 次进入 in_progress（每次 from!=in_progress）；若被误计，5 次进入 -> 重试 4 >= 3 会触发
    for state in ("in_progress", "achieved", "in_progress", "planned", "in_progress",
                  "achieved", "in_progress", "planned", "in_progress"):
        m.call_ok("update_milestone", {"requirement_id": rid, "milestone_id": ms, "state": state})
    m.close()
    sc = _state_change_payloads(db, rid)
    ms_ip = [p for p in sc if p.get("milestone_id") and not p.get("subtask_id")
             and p.get("to") == "in_progress" and p.get("from") != "in_progress"]
    ok("edge4: 里程碑 5 次 in_progress 迁移已落库（事件真实存在，非零判别）", len(ms_ip) == 5, str(ms_ip))
    ok("edge4: 里程碑迁移不计入重试（无 risk 事件）", _system_retry_events(db, rid) == [], str(_system_retry_events(db, rid)))
    rest = REST(db).start()
    try:
        code, s = rest.req("GET", f"/requirements/{rid}/summary")
        ok("edge4: needs_attention 无 retry_limit 信号",
           code == 200 and _retry_signal(s.get("needs_attention")) is None, str(s.get("needs_attention")))
    finally:
        rest.stop()


def retry_edge5():
    print("== M1-4 边缘 5: agent 伪造 marker 不抑制告警（第 3 次重入仍写真实 system 事件）+ 伪造不进信号 + 仍显示 risks")
    db = new_db()
    rid = seed_req(db, "e5")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    st = m.call_ok("add_subtask", {"requirement_id": rid, "title": "e5", "ordinal": 1})["subtask_id"]
    # 伪造 marker：add_record kind=risk severity=attention payload.retry_limit=true count=0
    m.call_ok("add_record", {"requirement_id": rid, "kind": "risk", "title": "fake-marker",
                             "severity": "attention", "payload": {"retry_limit": True, "count": 0}})
    rest = REST(db).start()
    try:
        code, s0 = rest.req("GET", f"/requirements/{rid}/summary")
        ok("edge5: 仅伪造 marker 时 needs_attention 无 retry_limit（伪造不进信号，威胁模型 B）",
           code == 200 and _retry_signal(s0.get("needs_attention")) is None, str(s0.get("needs_attention")))
        ok("edge5: 伪造事件作为普通 risk 显示在 risks 列表（agent 自报风险，_risk_rows 口径）",
           any(r.get("title") == "fake-marker" and r.get("severity") == "attention" for r in s0.get("risks")),
           str(s0.get("risks")))
        _to_ip(m, rid, st)               # 首入
        _cycle_in_progress(m, rid, st, 3)  # 重试 1、2、3 -> 真实触发
        m.close()
        evs = _risk_events(db, rid)
        ok("edge5: 真实重试 3 仍写真实 system 事件（伪造不抑制告警）",
           len(_system_retry_events(db, rid)) == 1, str(evs))
        real = [e for e in evs if e["actor_surface"] == "system"]
        fake = [e for e in evs if e["actor_surface"] != "system"]
        ok("edge5: 真实事件 actor_surface=system + count=3（伪造 actor_surface=mcp 排除）",
           len(real) == 1 and (real[0]["payload"] or {}).get("count") == 3
           and len(fake) == 1 and fake[0]["title"] == "fake-marker", str(evs))
        code, s1 = rest.req("GET", f"/requirements/{rid}/summary")
        sig = _retry_signal(s1.get("needs_attention"))
        ok("edge5: 触发后 retry_limit 信号 count=3（来自真实系统事件）",
           code == 200 and sig is not None and sig.get("count") == 3, str(sig))
        titles = [r.get("title") for r in s1.get("risks")]
        ok("edge5: risks 列表含伪造与真实两条（伪造仍显示）",
           "fake-marker" in titles and RETRY_LIMIT_TITLE in titles, str(titles))
    finally:
        rest.stop()


def retry_ex5():
    print("== M1-4 例 5: 跨 claim 周期累计延续（release 后重新 claim，周期 2 第 1 次重入时触发，claim_id 关联周期 2）")
    db = new_db()
    rid = seed_req(db, "ex5")
    m1 = MCP(db).start()
    m1.call_ok("claim_task", {"requirement_id": rid, "agent_name": "p1"})
    st = m1.call_ok("add_subtask", {"requirement_id": rid, "title": "S", "ordinal": 1})["subtask_id"]
    _to_ip(m1, rid, st)                 # 周期 1 首入
    _cycle_in_progress(m1, rid, st, 2)  # 周期 1 重试 1、2
    ok("ex5: 周期 1 重试 2 未触发", _system_retry_events(db, rid) == [], str(_system_retry_events(db, rid)))
    m1.close()
    cli_ok(db, "release", "--requirement-id", rid, "--reason", "round-1")
    m2 = MCP(db).start()
    m2.call_ok("claim_task", {"requirement_id": rid, "agent_name": "p2"})
    claim2 = _active_claim(db, rid)
    m2.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": st, "state": "blocked"})
    m2.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": st, "state": "in_progress"})  # 周期 2 第 1 次重入
    m2.close()
    evs = _system_retry_events(db, rid)
    ok("ex5: 周期 2 第 1 次重入触发（需求级累计跨 claim 周期延续，不重置）",
       len(evs) == 1 and (_first(evs).get("payload") or {}).get("count") == 3, str(evs))
    ok("ex5: 真实 marker claim_id 关联周期 2 活跃认领",
       _first(evs).get("claim_id") == claim2, f"{_first(evs).get('claim_id')} vs {claim2}")


def _backdate(db, rid: str, days: int = 400) -> None:
    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE events SET ts = datetime('now', ?) WHERE requirement_id=?", (f"-{days} days", rid))
    conn.commit()
    conn.close()


def retry_cross_window():
    print("== M1-4 边缘 6: 跨窗 prune 交互（BCD §4 跨时段场景 + plan 任务映射：backdate 重入长链 -> prune 不删活动需求 -> 链累计计数仍正确）")
    db = new_db()
    rid = seed_req(db, "cross-window")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    st = m.call_ok("add_subtask", {"requirement_id": rid, "title": "cw", "ordinal": 1})["subtask_id"]
    _to_ip(m, rid, st)                # 首入（不计）
    _cycle_in_progress(m, rid, st, 2)  # 重试 1、2（未超）
    m.close()
    before = query(db, "SELECT COUNT(*) AS n FROM events WHERE requirement_id=?", (rid,))[0]["n"]
    _backdate(db, rid)
    old_max = query(db, "SELECT MAX(ts) AS t FROM events WHERE requirement_id=?", (rid,))[0]["t"]
    floor = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d %H:%M:%S")
    ok("cw: backdate 生效（全部事件早于 12 个月窗口下限）", old_max is not None and old_max < floor, f"old_max={old_max} floor={floor}")
    exp = Path(tempfile.mkdtemp(prefix="ak-cw-")) / "cw-export.json"
    res = cli(db, "prune", "--months", "12", "--yes", "--export-path", str(exp))
    out = json.loads(res.stdout) if res.returncode == 0 else {}
    ok("cw: prune 退出 0（确认门 --yes 跳过）", res.returncode == 0, f"rc={res.returncode} stderr={res.stderr[-200:]}")
    ok("cw: 活动需求（CLAIMED 非终态）未被整删（deleted=0，M1-3 终态需求级原子谓词）",
       out.get("deleted") == 0, str(out))
    after = query(db, "SELECT COUNT(*) AS n FROM events WHERE requirement_id=?", (rid,))[0]["n"]
    ok("cw: 事件链完整未截断（backdate 长链全留）", after == before, f"before={before} after={after}")
    m2 = MCP(db).start()
    m2.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": st, "state": "blocked"})
    m2.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": st, "state": "in_progress"})  # 第 3 次重入（新 ts）
    m2.close()
    evs = _system_retry_events(db, rid)
    ok("cw: 跨窗链累计计数正确——第 3 次重入触发且 count=3（旧链 2 次 + 新 1 次，若链被截断则 n=1 不触发）",
       len(evs) == 1 and (_first(evs).get("payload") or {}).get("count") == 3, str(evs))
    rest = REST(db).start()
    try:
        code, s = rest.req("GET", f"/requirements/{rid}/summary")
        sig = _retry_signal(s.get("needs_attention"))
        ok("cw: needs_attention retry_limit 信号 count=3（跨窗链同源）",
           code == 200 and sig is not None and sig.get("count") == 3, str(sig))
    finally:
        rest.stop()


def retry_board():
    print("== M1-4: board==summary 一致（retry_limit 信号同源，_derived_signals 同一谓词）+ attention_ids + risks 同源")
    db = new_db()
    rid = seed_req(db, "board")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    st = m.call_ok("add_subtask", {"requirement_id": rid, "title": "st", "ordinal": 1})["subtask_id"]
    _to_ip(m, rid, st)
    _cycle_in_progress(m, rid, st, 3)  # 重试 3 -> 触发
    m.close()
    rest = REST(db).start()
    try:
        code, b = rest.req("GET", "/board")
        tasks = {t["requirement_id"]: t for t in b.get("tasks", [])}
        ok("board: 触发需求在板（非终态）且 attention_ids 含之",
           code == 200 and rid in tasks and rid in b.get("attention_ids", []), str(b.get("attention_ids")))
        code, s = rest.req("GET", f"/requirements/{rid}/summary")
        b_na = tasks[rid].get("needs_attention")
        s_na = s.get("needs_attention")
        b_sig = _retry_signal(b_na)
        s_sig = _retry_signal(s_na)
        ok("board: board 与 summary 均含 retry_limit 且 count 一致（同源）",
           b_sig is not None and b_sig == s_sig and (b_sig or {}).get("count") == 3,
           f"board={b_sig} summary={s_sig}")
        ok("board: board needs_attention == summary needs_attention（_derived_signals 全口径同源）",
           b_na == s_na, f"board={b_na} summary={s_na}")
        ok("board: board risks == summary risks（_risk_rows 共享口径，含系统 marker）",
           tasks[rid].get("risks") == s.get("risks"), f"board={tasks[rid].get('risks')} summary={s.get('risks')}")
    finally:
        rest.stop()
