"""B3.2 交接自评不静默丢弃（BCD b3.2-self-assessment.md v2 §4/§5/§7，I6-I9/I11）。

oracle 纪律：断言引 BCD 场景/不变量；DB 事后 sqlite3 直查（query）；真实 MCP stdio
子进程，禁 mock。错误消息断言用 _call_err2（ac_cases_m 同模式，ac_lib.call_err 不返
message）。v2 增量：S15 省略不豁免 / S16 deviation_reason 双向 / S17 重复拒写 /
S18 字符串归一 / S19 8KB 门 / I11 计数不变式。
"""

from __future__ import annotations

import json

from ac_lib import MCP, new_db, ok, query, seed_req


def _call_err2(m: MCP, name: str, args: dict) -> tuple[str, str]:
    """call + 解错误 payload 返回 (code, message)（ac_cases_m 同模式）。"""
    res = m.call(name, args)
    if not res.get("isError"):
        raise AssertionError(f"{name} unexpectedly succeeded: {res}")
    payload = json.loads(res["content"][0]["text"])
    return payload["code"], payload.get("message", "")


def _snapshot(db, rid: str) -> tuple:
    """拒写零写入观测面（BCD I8）：subtasks.acceptance / awaiting_human / 事件链。"""
    acc = [(r["id"], r["acceptance"]) for r in query(
        db, "SELECT id, acceptance FROM subtasks WHERE requirement_id=? ORDER BY ordinal", (rid,))]
    ah = query(db, "SELECT awaiting_human FROM requirements WHERE id=?", (rid,))[0]["awaiting_human"]
    evs = [(r["seq"], r["kind"], r["payload"]) for r in query(
        db, "SELECT seq, kind, payload FROM events WHERE requirement_id=? ORDER BY seq", (rid,))]
    return (tuple(acc), ah, tuple(evs))


def _rr_payload(db, rid: str) -> dict:
    row = query(db, "SELECT payload FROM events WHERE requirement_id=? "
                    "AND kind='review_request' ORDER BY seq DESC LIMIT 1", (rid,))[0]
    return json.loads(row["payload"])


def _i11(tag: str, asm: dict) -> None:
    """I11 计数不变式：成功路径 covered<=required 且 covered+added==received_items。"""
    ok(f"{tag}: I11 covered<=required 且 covered+added==received_items",
       asm["covered"] <= asm["required"] and asm["covered"] + asm["added"] == asm["received_items"],
       json.dumps(asm))


def _mk_claimed(db, title: str, subs: list[dict]) -> tuple[str, MCP, list[dict]]:
    """CLAIMED 需求 + 子任务（subs: [{title, ordinal, acceptance?}]）。返回 (rid, m, st 列表)。"""
    rid = seed_req(db, title)
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    sts = [m.call_ok("add_subtask", {"requirement_id": rid, **s}) for s in subs]
    return rid, m, sts


def sa_happy():
    """S10/E1+E10：全覆盖落库 + payload.assessment 计数；返工以最新自评为准。"""
    print("== sa_happy: 全覆盖自评落库 + 覆盖摘要留痕 + 返工覆写")
    db = new_db()
    rid, m, (s1, s2) = _mk_claimed(db, "sa-happy", [
        {"title": "impl1", "ordinal": 1, "acceptance": [{"item": "Y1"}]},
        {"title": "impl2", "ordinal": 2, "acceptance": [{"item": "Y2"}]},
    ])
    m.call_ok("request_review", {"requirement_id": rid, "evidence": {"test_summary": "t"},
                                 "summary_line": "sa 交接",
                                 "assessments": [
                                     {"subtask_id": s1["subtask_id"],
                                      "items": [{"item": "Y1", "state": "met"}]},
                                     {"subtask_id": s2["subtask_id"],
                                      "items": [{"item": "Y2", "state": "not_met",
                                                 "deviation_reason": "只跑了单测"}]},
                                 ]})
    d = m.call_ok("get_task_detail", {"requirement_id": rid})
    acc = {st["subtask_id"]: st["acceptance"] for st in d["subtasks"]}
    ok("sa_happy: Y1 state=met 落库",
       any(a.get("item") == "Y1" and a.get("state") == "met" for a in acc[s1["subtask_id"]]),
       json.dumps(acc[s1["subtask_id"]]))
    ok("sa_happy: Y2 state=not_met + deviation_reason 落库",
       any(a.get("item") == "Y2" and a.get("state") == "not_met"
           and a.get("deviation_reason") == "只跑了单测" for a in acc[s2["subtask_id"]]),
       json.dumps(acc[s2["subtask_id"]]))
    asm = _rr_payload(db, rid).get("assessment")
    ok("sa_happy: payload.assessment == {required:2,covered:2,added:0,received_subtasks:2,received_items:2}",
       asm == {"required": 2, "covered": 2, "added": 0, "received_subtasks": 2, "received_items": 2},
       json.dumps(asm))
    _i11("sa_happy", asm)
    # E10：返工再次交接，以最新自评为准，计数随之更新
    m.call_ok("request_review", {"requirement_id": rid, "evidence": {"test_summary": "t2"},
                                 "summary_line": "sa 返工交接",
                                 "assessments": [
                                     {"subtask_id": s1["subtask_id"],
                                      "items": [{"item": "Y1", "state": "met"}]},
                                     {"subtask_id": s2["subtask_id"],
                                      "items": [{"item": "Y2", "state": "deviated",
                                                 "deviation_reason": "补了 e2e"}]},
                                 ]})
    d = m.call_ok("get_task_detail", {"requirement_id": rid})
    acc2 = {st["subtask_id"]: st["acceptance"] for st in d["subtasks"]}
    ok("sa_happy: 返工后 Y2 以最新自评 deviated 为准",
       any(a.get("item") == "Y2" and a.get("state") == "deviated" for a in acc2[s2["subtask_id"]]),
       json.dumps(acc2[s2["subtask_id"]]))
    asm2 = _rr_payload(db, rid).get("assessment")
    ok("sa_happy: 返工 payload.assessment 计数更新（仍 required:2 covered:2）",
       asm2 == {"required": 2, "covered": 2, "added": 0, "received_subtasks": 2, "received_items": 2},
       json.dumps(asm2))
    m.close()


def sa_form():
    """S11/E2/E5+E9：形态不合法整单拒写 + 可自纠消息 + 零写入。"""
    print("== sa_form: 形态不合法 -> invalid_record + 正典形态示例 + 可用清单 + 零写入")
    db = new_db()
    rid, m, (s1,) = _mk_claimed(db, "sa-form", [
        {"title": "impl1", "ordinal": 1, "acceptance": [{"item": "Y1"}]},
    ])
    before = _snapshot(db, rid)
    # E2：扁平形态（缺 subtask_id/items）
    code, msg = _call_err2(m, "request_review", {
        "requirement_id": rid, "evidence": {"test_summary": "t"}, "summary_line": "x",
        "assessments": [{"item": "Y1", "state": "met"}]})
    ok("sa_form: 扁平形态 -> invalid_record", code == "invalid_record", code)
    ok("sa_form: 消息含第几项定位（assessments[0]）", "assessments[0]" in msg, msg[:200])
    ok("sa_form: 消息含正典形态示例（可照抄 JSON 片段）",
       '"subtask_id"' in msg and '"items"' in msg and '"state"' in msg, msg[:200])
    ok("sa_form: 消息含本需求可用 subtask_id + 验收条目清单",
       s1["subtask_id"] in msg and "Y1" in msg, msg[:300])
    # E5：state 枚举外
    code, msg = _call_err2(m, "request_review", {
        "requirement_id": rid, "evidence": {"test_summary": "t"}, "summary_line": "x",
        "assessments": [{"subtask_id": s1["subtask_id"], "items": [{"item": "Y1", "state": "pass"}]}]})
    ok("sa_form: state=pass（枚举外）-> invalid_record", code == "invalid_record", code)
    ok("sa_form: 消息含合法枚举 met/not_met/deviated",
       "met" in msg and "not_met" in msg and "deviated" in msg, msg[:200])
    # 缺 subtask_id
    code, msg = _call_err2(m, "request_review", {
        "requirement_id": rid, "evidence": {"test_summary": "t"}, "summary_line": "x",
        "assessments": [{"items": [{"item": "Y1", "state": "met"}]}]})
    ok("sa_form: 缺 subtask_id -> invalid_record", code == "invalid_record", code)
    # E9：零写入（subtasks.acceptance / awaiting_human / 事件链逐字不变）
    after = _snapshot(db, rid)
    ok("sa_form: 三次拒写后零写入（acceptance/awaiting_human/事件链逐字相同）",
       before == after, f"before={before} after={after}")
    m.close()


def sa_foreign():
    """S13/E4：引用他需求 subtask_id -> invalid_record（P2-1：本需求无验收条目，
    唯一可能的错误来源就是归属校验，覆盖门不可能顶替报错——M3 变异判别锚）。"""
    print("== sa_foreign: 子任务归属错 -> invalid_record（不得静默跳过）")
    db = new_db()
    rid, m, (s1,) = _mk_claimed(db, "sa-foreign", [{"title": "impl1", "ordinal": 1}])
    rid_b = seed_req(db, "sa-foreign-b")
    m.call_ok("claim_task", {"requirement_id": rid_b, "agent_name": "b"})
    st_b = m.call_ok("add_subtask", {"requirement_id": rid_b, "title": "other", "ordinal": 1,
                                     "acceptance": [{"item": "Z1"}]})
    before = _snapshot(db, rid)
    code, msg = _call_err2(m, "request_review", {
        "requirement_id": rid, "evidence": {"test_summary": "t"}, "summary_line": "x",
        "assessments": [{"subtask_id": st_b["subtask_id"], "items": [{"item": "Z1", "state": "met"}]}]})
    ok("sa_foreign: 引用他需求 subtask_id -> invalid_record", code == "invalid_record", code)
    ok("sa_foreign: 消息指明不属于本需求（判别归属校验本身，非覆盖门顶替）",
       "不属于本需求" in msg, msg[:200])
    ok("sa_foreign: 消息含本需求可用清单（subtask_id）", s1["subtask_id"] in msg, msg[:300])
    after = _snapshot(db, rid)
    ok("sa_foreign: 零写入", before == after, f"before={before} after={after}")
    m.close()


def sa_coverage():
    """S12/E3+E8+P2-7：漏评拒写点名漏项 + 两条出路 + 期望/提交对照；abandoned 出分母。"""
    print("== sa_coverage: 漏评 -> invalid_record 点名漏项 + 出路；abandoned 出分母")
    db = new_db()
    rid, m, (s1, s2) = _mk_claimed(db, "sa-coverage", [
        {"title": "impl1", "ordinal": 1, "acceptance": [{"item": "Y1", "links_to": "a1"}]},
        {"title": "impl2", "ordinal": 2, "acceptance": [{"item": "Y2"}]},
    ])
    before = _snapshot(db, rid)
    code, msg = _call_err2(m, "request_review", {
        "requirement_id": rid, "evidence": {"test_summary": "t"}, "summary_line": "x",
        "assessments": [{"subtask_id": s1["subtask_id"], "items": [{"item": "Y1", "state": "met"}]}]})
    ok("sa_coverage: 漏评 -> invalid_record", code == "invalid_record", code)
    ok("sa_coverage: 消息点名漏项（subtask_id + 条目文本）",
       s2["subtask_id"] in msg and "Y2" in msg, msg[:300])
    ok("sa_coverage: 消息给两条出路（补评 / update_subtask state=abandoned）",
       "补评" in msg and "abandoned" in msg, msg[:300])
    after = _snapshot(db, rid)
    ok("sa_coverage: 零写入", before == after, f"before={before} after={after}")
    # P2-7：逐字不匹配（多空格）-> 消息给期望逐字/你提交的对照 + 逐字说明
    before = _snapshot(db, rid)
    code, msg = _call_err2(m, "request_review", {
        "requirement_id": rid, "evidence": {"test_summary": "t"}, "summary_line": "x",
        "assessments": [
            {"subtask_id": s1["subtask_id"], "items": [{"item": " Y1 ", "state": "met"}]},
            {"subtask_id": s2["subtask_id"], "items": [{"item": "Y2", "state": "met"}]}]})
    ok("sa_coverage: 逐字不匹配（\" Y1 \" 多空格）-> invalid_record", code == "invalid_record", code)
    ok("sa_coverage: 消息给期望逐字与你提交的对照", "「Y1」" in msg and " Y1 " in msg, msg[:300])
    ok("sa_coverage: 消息声明按逐字匹配（不做 trim/大小写归一）", "逐字匹配" in msg, msg[:300])
    after = _snapshot(db, rid)
    ok("sa_coverage: 逐字不匹配拒写零写入", before == after, f"before={before} after={after}")
    # E8：把 s2 置 abandoned 后出分母，只评 Y1 即成功
    m.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": s2["subtask_id"],
                                 "state": "abandoned"})
    m.call_ok("request_review", {"requirement_id": rid, "evidence": {"test_summary": "t"},
                                 "summary_line": "sa 交接",
                                 "assessments": [{"subtask_id": s1["subtask_id"],
                                                  "items": [{"item": "Y1", "state": "met"}]}]})
    asm = _rr_payload(db, rid).get("assessment")
    ok("sa_coverage: abandoned 不计 required（required:1 covered:1）",
       asm == {"required": 1, "covered": 1, "added": 0, "received_subtasks": 1, "received_items": 1},
       json.dumps(asm))
    _i11("sa_coverage", asm)
    m.close()


def sa_omit():
    """S15/E11：有验收条目时省略 assessments 不构成豁免；不传/None/[] 三者一致。"""
    print("== sa_omit: 有验收条目 + 省略 assessments -> invalid_record（三种输入一致）")
    db = new_db()
    rid, m, (s1,) = _mk_claimed(db, "sa-omit", [
        {"title": "impl1", "ordinal": 1, "acceptance": [{"item": "Y1"}]},
    ])
    for label, kw in (("不传", {}), ("显式 None", {"assessments": None}),
                      ("空列表 []", {"assessments": []})):
        before = _snapshot(db, rid)
        args = {"requirement_id": rid, "evidence": {"test_summary": "t"}, "summary_line": "x"}
        args.update(kw)
        code, msg = _call_err2(m, "request_review", args)
        ok(f"sa_omit: {label} -> invalid_record（省略不构成豁免）", code == "invalid_record", code)
        ok(f"sa_omit: {label} 消息点名漏评 Y1 + 出路", "Y1" in msg and "abandoned" in msg, msg[:200])
        after = _snapshot(db, rid)
        ok(f"sa_omit: {label} 零写入", before == after, f"{label}")
    m.close()


def sa_dup():
    """S17/E14：重复引用 subtask_id / 重复条目 / 引用已 abandoned 子任务 -> 拒写。"""
    print("== sa_dup: 重复引用 / 重复条目 / 引用 abandoned -> invalid_record")
    db = new_db()
    rid, m, (s1, s2) = _mk_claimed(db, "sa-dup", [
        {"title": "impl1", "ordinal": 1, "acceptance": [{"item": "Y1"}]},
        {"title": "impl2", "ordinal": 2},
    ])
    # 同一 subtask_id 出现两次
    before = _snapshot(db, rid)
    code, msg = _call_err2(m, "request_review", {
        "requirement_id": rid, "evidence": {"test_summary": "t"}, "summary_line": "x",
        "assessments": [
            {"subtask_id": s1["subtask_id"], "items": [{"item": "Y1", "state": "met"}]},
            {"subtask_id": s1["subtask_id"], "items": [{"item": "Y1", "state": "met"}]}]})
    ok("sa_dup: 同一 subtask_id 两次 -> invalid_record", code == "invalid_record", code)
    ok("sa_dup: 消息含定位 assessments[1] + 重复引用",
       "assessments[1]" in msg and "重复引用" in msg, msg[:200])
    after = _snapshot(db, rid)
    ok("sa_dup: 重复引用零写入", before == after, f"before={before} after={after}")
    # 同一子任务 items 内同一文本两次
    before = _snapshot(db, rid)
    code, msg = _call_err2(m, "request_review", {
        "requirement_id": rid, "evidence": {"test_summary": "t"}, "summary_line": "x",
        "assessments": [{"subtask_id": s1["subtask_id"], "items": [
            {"item": "Y1", "state": "met"},
            {"item": "Y1", "state": "not_met", "deviation_reason": "x"}]}]})
    ok("sa_dup: 同子任务同文本两次 -> invalid_record", code == "invalid_record", code)
    ok("sa_dup: 消息含定位 assessments[0].items[1] + 重复条目",
       "assessments[0].items[1]" in msg and "重复条目" in msg, msg[:200])
    after = _snapshot(db, rid)
    ok("sa_dup: 重复条目零写入", before == after, f"before={before} after={after}")
    # 引用已 abandoned 子任务
    m.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": s2["subtask_id"],
                                 "state": "abandoned"})
    before = _snapshot(db, rid)
    code, msg = _call_err2(m, "request_review", {
        "requirement_id": rid, "evidence": {"test_summary": "t"}, "summary_line": "x",
        "assessments": [
            {"subtask_id": s1["subtask_id"], "items": [{"item": "Y1", "state": "met"}]},
            {"subtask_id": s2["subtask_id"], "items": [{"item": "X", "state": "met"}]}]})
    ok("sa_dup: 引用 abandoned 子任务 -> invalid_record", code == "invalid_record", code)
    ok("sa_dup: 消息说明已放弃+不计入分母+改回出路",
       "已放弃" in msg and s2["subtask_id"] in msg and "update_subtask" in msg, msg[:300])
    after = _snapshot(db, rid)
    ok("sa_dup: 引用 abandoned 零写入", before == after, f"before={before} after={after}")
    m.close()


def sa_reason():
    """S16/E12/E13：deviation_reason 双向一致（not_met/deviated 必填；met 清旧值）。"""
    print("== sa_reason: deviation_reason 必填 + met 清旧值")
    db = new_db()
    rid, m, (s1,) = _mk_claimed(db, "sa-reason", [
        {"title": "impl1", "ordinal": 1, "acceptance": [{"item": "Y2"}]},
    ])
    # E12：not_met 无原因 -> invalid_record
    before = _snapshot(db, rid)
    code, msg = _call_err2(m, "request_review", {
        "requirement_id": rid, "evidence": {"test_summary": "t"}, "summary_line": "x",
        "assessments": [{"subtask_id": s1["subtask_id"],
                         "items": [{"item": "Y2", "state": "not_met"}]}]})
    ok("sa_reason: not_met 无 deviation_reason -> invalid_record", code == "invalid_record", code)
    ok("sa_reason: 消息含定位 + 必填说明",
       "assessments[0].items[0]" in msg and "deviation_reason" in msg, msg[:200])
    # deviated 纯空白原因 -> invalid_record
    code, msg = _call_err2(m, "request_review", {
        "requirement_id": rid, "evidence": {"test_summary": "t"}, "summary_line": "x",
        "assessments": [{"subtask_id": s1["subtask_id"],
                         "items": [{"item": "Y2", "state": "deviated", "deviation_reason": "  "}]}]})
    ok("sa_reason: deviated 纯空白原因 -> invalid_record", code == "invalid_record", code)
    after = _snapshot(db, rid)
    ok("sa_reason: 两次拒写零写入", before == after, f"before={before} after={after}")
    # 正常：not_met + 原因 -> 成功落库
    m.call_ok("request_review", {"requirement_id": rid, "evidence": {"test_summary": "t"},
                                 "summary_line": "sa 交接",
                                 "assessments": [{"subtask_id": s1["subtask_id"], "items": [
                                     {"item": "Y2", "state": "not_met",
                                      "deviation_reason": "只跑了单测"}]}]})
    # E13：返工 met 不给原因 -> 旧 deviation_reason 清除（以最新自评为准）
    m.call_ok("request_review", {"requirement_id": rid, "evidence": {"test_summary": "t2"},
                                 "summary_line": "sa 返工交接",
                                 "assessments": [{"subtask_id": s1["subtask_id"],
                                                  "items": [{"item": "Y2", "state": "met"}]}]})
    d = m.call_ok("get_task_detail", {"requirement_id": rid})
    acc = d["subtasks"][0]["acceptance"]
    ok("sa_reason: met 后旧 deviation_reason 清除（条目只剩 item+state）",
       acc == [{"item": "Y2", "state": "met"}], json.dumps(acc))
    m.close()


def sa_stracc():
    """S18：字符串形态既有验收条目归一——不出现同文本双份，计数归位。"""
    print("== sa_stracc: 字符串 acceptance 归一（normalize_anchors 同口径）")
    db = new_db()
    rid, m, (s1,) = _mk_claimed(db, "sa-stracc", [
        {"title": "impl1", "ordinal": 1, "acceptance": ["实现可回滚"]},
    ])
    m.call_ok("request_review", {"requirement_id": rid, "evidence": {"test_summary": "t"},
                                 "summary_line": "sa 交接",
                                 "assessments": [{"subtask_id": s1["subtask_id"], "items": [
                                     {"item": "实现可回滚", "state": "met"}]}]})
    d = m.call_ok("get_task_detail", {"requirement_id": rid})
    acc = d["subtasks"][0]["acceptance"]
    ok("sa_stracc: 落库单份且归一为 {item,state}（无同文本双份）",
       acc == [{"item": "实现可回滚", "state": "met"}], json.dumps(acc))
    asm = _rr_payload(db, rid).get("assessment")
    ok("sa_stracc: payload.assessment required=1 covered=1 added=0（计数归位）",
       asm == {"required": 1, "covered": 1, "added": 0, "received_subtasks": 1, "received_items": 1},
       json.dumps(asm))
    _i11("sa_stracc", asm)
    m.close()


def sa_size():
    """S19/E15：8KB 双门——事件 payload 超限 / 落库后 acceptance 超限 -> 拒写零写入。"""
    print("== sa_size: 8KB 体积门（summary_line 过长 + 自拟条目过多）")
    db = new_db()
    rid, m, (s1,) = _mk_claimed(db, "sa-size", [
        {"title": "impl1", "ordinal": 1, "acceptance": [{"item": "Y1"}]},
    ])
    # E15：超长 summary_line -> 事件 payload > 8KB
    before = _snapshot(db, rid)
    code, _ = _call_err2(m, "request_review", {
        "requirement_id": rid, "evidence": {"test_summary": "t"},
        "summary_line": "长" * 9000,
        "assessments": [{"subtask_id": s1["subtask_id"], "items": [{"item": "Y1", "state": "met"}]}]})
    ok("sa_size: summary_line 9000 字（payload>8KB）-> invalid_record", code == "invalid_record", code)
    after = _snapshot(db, rid)
    ok("sa_size: 事件 payload 超限零写入", before == after, f"before={before} after={after}")
    # 自拟条目过多 -> 落库后 acceptance > 8KB（与 add_subtask 同口径）
    rid2 = seed_req(db, "sa-size-added")
    m.call_ok("claim_task", {"requirement_id": rid2, "agent_name": "b"})
    st2 = m.call_ok("add_subtask", {"requirement_id": rid2, "title": "impl", "ordinal": 1})
    before2 = _snapshot(db, rid2)
    items = [{"item": f"自拟条目 {i} 等等等等等等等等", "state": "met"} for i in range(600)]
    code, msg = _call_err2(m, "request_review", {
        "requirement_id": rid2, "evidence": {"test_summary": "t"}, "summary_line": "x",
        "assessments": [{"subtask_id": st2["subtask_id"], "items": items}]})
    ok("sa_size: 自拟 600 条（acceptance>8KB）-> invalid_record", code == "invalid_record", code)
    ok("sa_size: acceptance 超限消息点名 subtask_id + 字节数（可自纠）",
       st2["subtask_id"] in msg and "8192" in msg, msg[:240])
    after2 = _snapshot(db, rid2)
    ok("sa_size: acceptance 超限零写入（落库前拒）", before2 == after2,
       f"before={before2} after={after2}")
    m.close()


def sa_blankacc():
    """b11 写侧拒（G36 配套行为变更）：add_subtask 空白 item 条目拒写；存量空白条目兜底见 ac_cases_s 断言 36。

    写侧不再产生空白条目（validate_anchor_entries 拒，消息点名 item 文本）；读侧分母兜底
    （空白条目不计分母、不卡死交接）保留，其 oracle 移到 ac_cases_s s_journey_shapes(36)
    （SQL 直插 legacy 种子，先例 ac_cases_m._seed）。
    """
    print("== sa_blankacc: 写侧拒空白 item 条目 + 零写入；正常条目不受影响")
    db = new_db()
    rid, m, (s1,) = _mk_claimed(db, "sa-blankacc", [
        {"title": "impl1", "ordinal": 1, "acceptance": [{"item": "Y1"}]},
    ])
    before = _snapshot(db, rid)
    code, msg = _call_err2(m, "add_subtask", {
        "requirement_id": rid, "title": "impl2", "ordinal": 2,
        "acceptance": [{"item": "   "}, {"item": "Y2"}]})
    after = _snapshot(db, rid)
    ok("sa_blankacc: add_subtask 空白 item 条目 -> invalid_record（消息点名 item 文本）且零写入",
       code == "invalid_record" and "item text" in msg and before == after,
       f"{code} {msg[:100]} changed={before != after}")
    m.call_ok("request_review", {"requirement_id": rid, "evidence": {"test_summary": "t"},
                                 "summary_line": "sa 交接",
                                 "assessments": [{"subtask_id": s1["subtask_id"],
                                                  "items": [{"item": "Y1", "state": "met"}]}]})
    d = m.call_ok("get_task_detail", {"requirement_id": rid})
    acc = d["subtasks"][0]["acceptance"]
    ok("sa_blankacc: 正常条目 Y1 落库 + 自评 state=met（其余键不丢）",
       [a for a in acc if a.get("item") == "Y1"] == [{"item": "Y1", "state": "met"}], json.dumps(acc))
    _i11("sa_blankacc", _rr_payload(db, rid).get("assessment"))
    m.close()


def sa_added():
    """S13/E6：子任务无验收条目可自拟，追加进 acceptance，计 added。"""
    print("== sa_added: 自拟条目追加 + added 计数（既有语义保留）")
    db = new_db()
    rid, m, (s1,) = _mk_claimed(db, "sa-added", [{"title": "impl1", "ordinal": 1}])
    m.call_ok("request_review", {"requirement_id": rid, "evidence": {"test_summary": "t"},
                                 "summary_line": "sa 交接",
                                 "assessments": [{"subtask_id": s1["subtask_id"],
                                                  "items": [{"item": "自拟：实现可回滚", "state": "met"}]}]})
    d = m.call_ok("get_task_detail", {"requirement_id": rid})
    acc = d["subtasks"][0]["acceptance"]
    ok("sa_added: 自拟条目追加为子任务验收条目（带 state）",
       any(a.get("item") == "自拟：实现可回滚" and a.get("state") == "met" for a in acc),
       json.dumps(acc))
    asm = _rr_payload(db, rid).get("assessment")
    ok("sa_added: payload.assessment added=1 required=0",
       asm == {"required": 0, "covered": 0, "added": 1, "received_subtasks": 1, "received_items": 1},
       json.dumps(asm))
    _i11("sa_added", asm)
    m.close()


def sa_empty():
    """S14/E7：无验收条目且未传 assessments -> 成功，payload.assessment 恒在全 0。"""
    print("== sa_empty: 无验收条目才可省略 assessments -> payload.assessment 字段恒在（全 0）")
    db = new_db()
    rid, m, _ = _mk_claimed(db, "sa-empty", [{"title": "impl1", "ordinal": 1}])
    m.call_ok("request_review", {"requirement_id": rid, "evidence": {"test_summary": "t"},
                                 "summary_line": "sa 交接"})
    asm = _rr_payload(db, rid).get("assessment")
    ok("sa_empty: 不传 assessments，assessment 字段恒在且全 0",
       asm == {"required": 0, "covered": 0, "added": 0, "received_subtasks": 0, "received_items": 0},
       json.dumps(asm))
    m.close()
