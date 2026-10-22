"""M0-2 AC 用例：AC10 反黑箱判别力 + M0-2.1 reconcile（ORPHANED/等待中优先/
drift 双场景/BLOCKED 合法/MCP 不触发/视图集成）。

oracle 纪律：AC10 断言基于渲染输出（summary dict / CLI 文本），非实现内部；
reconcile 断言基于 reconcile 事件与报告（read DB 直查 events 表）。
"""

from __future__ import annotations

import json
import sqlite3

from ac_lib import MCP, REST, cli, cli_ok, new_db, ok, query, seed_req


def _update(db, sql: str, params: tuple = ()) -> None:
    conn = sqlite3.connect(str(db))
    conn.execute(sql, params)
    conn.commit()
    conn.close()


def _backdate_last_activity(db, minutes: int) -> None:
    _update(db, "UPDATE claims SET last_activity_at = datetime('now', ?) WHERE ended_at IS NULL",
            (f"-{minutes} minutes",))


def _count_events(db, rid: str, kind: str) -> int:
    return query(db, "SELECT COUNT(*) AS n FROM events WHERE requirement_id=? AND kind=?",
                 (rid, kind))[0]["n"]


def _reconcile_signal(db, rid: str) -> str | None:
    rows = query(db, "SELECT payload FROM events WHERE requirement_id=? AND kind='reconcile'"
                     " ORDER BY seq DESC LIMIT 1", (rid,))
    if not rows:
        return None
    findings = json.loads(rows[0]["payload"]).get("findings") or []
    return findings[0].get("signal") if findings else None


def ac10():
    print("== AC10: 反黑箱判别力（压级风险+窄化验收+虚假覆盖+未登记放弃+决策备选）")
    db = new_db()
    rid = seed_req(db, "ac10")
    cli_ok(db, "set_expectations", "--requirement-id", rid, "--acceptance",
           '[{"item": "粗锚 X：完整功能验收（含导入导出/权限/日志）"}, {"item": "A2：数据持久化"}]')
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "agent"})
    # 窄化验收 + 虚假覆盖：agent 将窄验收项 Y links_to 粗锚 X（a1）以消缺口
    st = m.call_ok("add_subtask", {"requirement_id": rid, "title": "实现登录页", "ordinal": 1,
                                   "acceptance": [{"item": "窄验收项 Y：登录按钮可点击", "links_to": "a1"}]})
    # 未登记 abandoned 子任务（无 deviation/note）
    st2 = m.call_ok("add_subtask", {"requirement_id": rid, "title": "被放弃的子任务", "ordinal": 2})
    m.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": st2["subtask_id"], "state": "abandoned"})
    # 决策含备选
    m.call_ok("add_record", {"requirement_id": rid, "kind": "decision", "title": "实现方案选型",
                             "payload": {"choice": "方案 A", "rationale": "成本最低",
                                         "alternatives": [{"option": "方案 B", "rejected_reason": "成本高"},
                                                          {"option": "方案 C", "rejected_reason": "复杂度高"}]}})
    # 压级风险：severity=info（PRD 5.3 过滤不可见）
    m.call_ok("add_record", {"requirement_id": rid, "kind": "risk", "title": "压级风险：性能不足",
                             "severity": "info", "content": "风险被压级，不应出现在摘要风险列表"})
    # 验收自评：Y 状态可见
    m.call_ok("request_review", {"requirement_id": rid, "evidence": {"test_summary": "t"},
                                 "assessments": [{"subtask_id": st["subtask_id"],
                                                  "items": [{"item": "窄验收项 Y：登录按钮可点击", "state": "met"}]}]})
    m.close()
    rest = REST(db).start()
    try:
        code, s = rest.req("GET", f"/requirements/{rid}/summary")
        ok("ac10: summary 200", code == 200, str(code))
        table = {a["anchor_id"]: a for a in s["acceptance_table"]}
        # ① 粗锚 X（a1）下显示窄验收项 Y 文本及状态（非仅存在映射）
        linked_x = table.get("a1", {}).get("linked", [])
        ok("ac10: ① 粗锚 X 下显示窄验收项 Y 文本及状态",
           any(x.get("item") == "窄验收项 Y：登录按钮可点击" and x.get("state") == "met" for x in linked_x),
           str(table.get("a1")))
        # ② 反向断言：虚假覆盖锚 X 不显示 uncovered（排除靠缺口高亮作答路线）
        ok("ac10: ② 虚假覆盖锚 X 不显示 uncovered",
           table.get("a1", {}).get("uncovered") is False, str(table.get("a1")))
        # ③ 需要关注区有 abandoned 派生信号（未登记 deviation 仍出现）
        na_types = [n["type"] for n in s["needs_attention"]]
        ok("ac10: ③ abandoned 派生信号在需要关注区（无 deviation 登记）",
           "abandoned_subtask" in na_types, str(na_types))
        # ④ decision 含 alternatives 文本
        decs = [d for d in s["decisions"] if d["title"] == "实现方案选型"]
        alts = [a.get("option") for a in (decs[0]["alternatives"] if decs else [])]
        ok("ac10: ④ decision 含 alternatives 文本",
           bool(decs) and "方案 B" in alts and "方案 C" in alts, str(decs))
        # ⑤ risk severity=info 不在决策/风险/偏离列表（压级不可见但其余信号足够作答）
        blob = json.dumps(s["risks"], ensure_ascii=False) + json.dumps(s["decisions"], ensure_ascii=False) \
            + json.dumps(s["deviations"], ensure_ascii=False)
        ok("ac10: ⑤ info 压级风险不在风险/决策/偏离列表",
           "压级风险：性能不足" not in blob, f"risks={s['risks']}")
        # 文本渲染面（PRD 5.3 视图）同源可读：Y 文本+状态可见、压级风险不可见
        res = cli(db, "view", "summary", "--requirement-id", rid)
        ok("ac10: 文本面对照表显示 Y 且压级风险不可见",
           res.returncode == 0 and "窄验收项 Y" in res.stdout and "压级风险" not in res.stdout,
           res.stdout[-300:])
    finally:
        rest.stop()


def reconcile_ac():
    print("== M0-2.1 reconcile: ORPHANED / 等待中优先 / drift 双场景 / BLOCKED 合法 / MCP 不触发 / 视图集成")
    db = new_db()

    # MCP server 启动不跑对账（审#10）
    r0 = seed_req(db, "mcp-no-reconcile")
    m0 = MCP(db).start()
    m0.call_ok("claim_task", {"requirement_id": r0, "agent_name": "a"})
    m0.call_ok("request_review", {"requirement_id": r0, "evidence": {"test_summary": "t"}})
    m0.close()
    ok("reconcile: MCP server 启动不写 reconcile 事件（审#10）",
       _count_events(db, r0, "reconcile") == 0, "")

    # 场景1: 连接失活（last_activity 旧、租约未过、无等待标记）-> ORPHANED
    r1 = seed_req(db, "orphan-1")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": r1, "agent_name": "dead"})
    m.close()
    _backdate_last_activity(db, 40)  # idle 默认 30min
    rep = cli_ok(db, "reconcile")
    sig = {f["requirement_id"]: f["signal"] for f in rep["findings"]}
    ok("reconcile: 连接失活租约未过 -> ORPHANED", sig.get(r1) == "orphaned", str(sig))
    ok("reconcile: ORPHANED 事件写入", _reconcile_signal(db, r1) == "orphaned", "")

    # 场景2: 等待中优先（awaiting_human 存在 -> waiting 而非 orphaned）
    r2 = seed_req(db, "awaiting-2")
    m2 = MCP(db).start()
    m2.call_ok("claim_task", {"requirement_id": r2, "agent_name": "waiting-agent"})
    m2.call_ok("request_review", {"requirement_id": r2, "evidence": {"test_summary": "t"}})
    m2.close()
    _backdate_last_activity(db, 40)
    rep2 = cli_ok(db, "reconcile")
    sig2 = {f["requirement_id"]: f["signal"] for f in rep2["findings"]}
    ok("reconcile: 等待中优先于 ORPHANED（连接失活不盖过等待人裁决）",
       sig2.get(r2) == "waiting", str(sig2))
    ok("reconcile: waiting 事件不含 orphaned", _reconcile_signal(db, r2) == "waiting", "")

    # 场景3a: claim 无 CLAIMED -> drift（OPEN 非法，BLOCKED 合法）
    r3 = seed_req(db, "drift-open")
    m3 = MCP(db).start()
    m3.call_ok("claim_task", {"requirement_id": r3, "agent_name": "a"})
    m3.close()
    _update(db, "UPDATE requirements SET state='OPEN' WHERE id=?", (r3,))
    rep3 = cli_ok(db, "reconcile")
    drift3 = [d for d in rep3["drift"] if d["requirement_id"] == r3]
    ok("reconcile: claim 无 CLAIMED -> drift(claim_without_claimed)",
       any(d["type"] == "claim_without_claimed" for d in drift3), str(drift3))

    # 场景3b: CLAIMED 无 claim -> drift
    r4 = seed_req(db, "drift-claimed")
    _update(db, "UPDATE requirements SET state='CLAIMED' WHERE id=?", (r4,))
    rep4 = cli_ok(db, "reconcile")
    drift4 = [d for d in rep4["drift"] if d["requirement_id"] == r4]
    ok("reconcile: CLAIMED 无 claim -> drift(claimed_without_claim)",
       any(d["type"] == "claimed_without_claim" for d in drift4), str(drift4))

    # BLOCKED 有 claim 合法（不报 drift）
    r5 = seed_req(db, "blocked-legal")
    m5 = MCP(db).start()
    m5.call_ok("claim_task", {"requirement_id": r5, "agent_name": "a"})
    m5.call_ok("mark_blocked", {"requirement_id": r5, "reason": "dep"})
    m5.close()
    rep5 = cli_ok(db, "reconcile")
    drift5 = [d for d in rep5["drift"] if d["requirement_id"] == r5]
    ok("reconcile: BLOCKED 有 claim 不报 drift", not drift5, str(drift5))

    # ACTIVE claim 不写事件
    r6 = seed_req(db, "active-6")
    m6 = MCP(db).start()
    m6.call_ok("claim_task", {"requirement_id": r6, "agent_name": "a"})
    m6.close()
    rep6 = cli_ok(db, "reconcile")
    ok("reconcile: ACTIVE claim 不写 reconcile 事件",
       _count_events(db, r6, "reconcile") == 0 and r6 not in rep6["events_written"],
       str(rep6["events_written"]))

    # 视图集成：ORPHANED/drift 入摘要需要关注区（REST lifespan 触发对账）
    rest = REST(db).start()
    try:
        code, s1 = rest.req("GET", f"/requirements/{r1}/summary")
        na1 = [n["type"] for n in s1["needs_attention"]]
        ok("reconcile: 摘要需要关注区含 orphaned_claim（REST lifespan 对账）",
           code == 200 and "orphaned_claim" in na1, str(na1))
        code, s3 = rest.req("GET", f"/requirements/{r3}/summary")
        na3 = [n["type"] for n in s3["needs_attention"]]
        ok("reconcile: 摘要需要关注区含 claim_state_drift",
           code == 200 and "claim_state_drift" in na3, str(na3))
        code, s5 = rest.req("GET", f"/requirements/{r5}/summary")
        na5 = [n["type"] for n in s5["needs_attention"]]
        ok("reconcile: BLOCKED 需求摘要无 drift 信号", "claim_state_drift" not in na5, str(na5))
    finally:
        rest.stop()
