"""export CSV 用例（CLI --format csv）：列名 = JSON 导出字段名并集 + record_type 类型列，
每条记录一行，嵌套结构 JSON 序列化进同名单列；覆盖全量/单项导出、含逗号引号换行的
content 转义、json/markdown 回归。

oracle：列名集合直接从 JSON 导出自身字段名派生（独立于 CSV 实现）；数据值与 JSON
导出对照；id 用 JSON 导出的归一 32-hex 口径（create 响应为 36-char 带连字符，不直比）。
"""

from __future__ import annotations

import csv
import io
import json

from ac_lib import MCP, cli, new_db, ok, seed_req

ESCAPE_CONTENT = '逗号, 引号"换行\n第二行'


def export_csv():
    print("== export CSV: 列名=JSON 字段名并集、每条记录一行、嵌套 JSON 单列、全量/单项")
    db = new_db()
    r1 = seed_req(db, "csv-req")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": r1, "agent_name": "csv-agent"})
    s1 = m.call_ok("add_subtask", {
        "requirement_id": r1, "title": "st1", "ordinal": 1,
        "acceptance": [{"item": "acc-1", "links_to": []}],
    })
    s2 = m.call_ok("add_subtask", {"requirement_id": r1, "title": "st2", "ordinal": 2})
    m.call_ok("update_subtask", {"requirement_id": r1, "subtask_id": s2["subtask_id"], "state": "done"})
    ms = m.call_ok("add_milestone", {"requirement_id": r1, "title": "ms1",
                                     "planned_at": "2026-10-24T00:00:00+00:00"})
    m.call_ok("update_milestone", {"requirement_id": r1, "milestone_id": ms["milestone_id"],
                                   "state": "achieved", "actual_at": "2026-10-23T12:00:00+00:00"})
    m.call_ok("add_record", {"requirement_id": r1, "kind": "decision", "title": "选型",
                             "payload": {"choice": "A", "rationale": "便宜",
                                         "alternatives": [{"option": "B", "rejected_reason": "贵"}]}})
    m.call_ok("add_record", {"requirement_id": r1, "kind": "risk", "title": "风险",
                             "severity": "attention"})
    m.call_ok("add_record", {"requirement_id": r1, "kind": "deviation", "title": "偏离",
                             "severity": "attention"})
    m.call_ok("update_progress", {"requirement_id": r1, "note": "p1",
                                   "headline": "j 进度提纲"})
    m.call_ok("add_record", {"requirement_id": r1, "kind": "note", "title": "csv-escape",
                             "content": ESCAPE_CONTENT})
    m.close()
    # JSON 导出 = oracle 基准（列名派生 + 值对照）
    jres = cli(db, "export", "--requirement-id", r1, "--format", "json")
    ok("export_csv: json 导出回归 rc=0", jres.returncode == 0, jres.stderr[-200:])
    jdata = json.loads(jres.stdout)["requirement"]
    # CSV 不携 additive 视图键：T2 合并后 JSON/深潜 detail 才带的读侧计算键
    # （plan T2 钉死 CSV byte-identical，强不变量 1 导出稳定）；
    # oracle 仍独立从 JSON 派生，仅排除这 3 个文档化视图键
    _VIEW_KEYS = {"history_note", "state_at_event", "audience"}
    expected_cols = ({"record_type"}
                     | {k for k in jdata if k not in ("subtasks", "milestones", "events")}
                     | set((jdata["subtasks"] or [{}])[0])
                     | set((jdata["milestones"] or [{}])[0])
                     | set((jdata["events"] or [{}])[0])) - _VIEW_KEYS
    res = cli(db, "export", "--requirement-id", r1, "--format", "csv")
    ok("export_csv: CLI rc=0", res.returncode == 0, res.stderr[-200:])
    rows = list(csv.reader(io.StringIO(res.stdout)))
    header, body = rows[0], rows[1:]
    idx = {name: i for i, name in enumerate(header)}
    ok("export_csv: 列名与 JSON 导出字段名一致（并集 + record_type，排除文档化视图键，无多余无遗漏）",
       set(header) == expected_cols, str(sorted(set(header) ^ expected_cols)))
    types = [row[idx["record_type"]] for row in body]
    ok("export_csv: 记录类型齐全（requirement/subtask/milestone/event）",
       set(types) == {"requirement", "subtask", "milestone", "event"}, str(sorted(set(types))))
    kinds = [row[idx["kind"]] for row in body if row[idx["record_type"]] == "event"]
    ok("export_csv: 事件类型覆盖 decision/risk/deviation/progress_note",
       {"decision", "risk", "deviation", "progress_note"} <= set(kinds), str(sorted(set(kinds))))
    req_rows = [row for row in body if row[idx["record_type"]] == "requirement"]
    ok("export_csv: 单项导出仅一个需求行", len(req_rows) == 1, str(len(req_rows)))
    rq = req_rows[0]
    ok("export_csv: 需求行关键列正确（id 归一 32-hex / title / state）",
       rq[idx["requirement_id"]] == jdata["requirement_id"] and rq[idx["title"]] == "csv-req"
       and rq[idx["state"]] == "CLAIMED",
       f"id={rq[idx['requirement_id']]} state={rq[idx['state']]}")
    claim = json.loads(rq[idx["claim"]])
    ok("export_csv: 嵌套 claim 列为合法 JSON 且 agent_name 正确", claim.get("agent_name") == "csv-agent",
       str(claim)[:120])
    st_rows = [row for row in body if row[idx["record_type"]] == "subtask"]
    ok("export_csv: 子任务行数与 JSON 一致", len(st_rows) == 2, str(len(st_rows)))
    ok("export_csv: 子任务 id 与 JSON 导出一致",
       {row[idx["subtask_id"]] for row in st_rows} == {s["subtask_id"] for s in jdata["subtasks"]},
       str({row[idx["subtask_id"]] for row in st_rows}))
    acc = json.loads([row for row in st_rows if row[idx["subtask_id"]] == s1["subtask_id"].replace("-", "")][0][idx["acceptance"]])
    ok("export_csv: 子任务 acceptance 嵌套列为合法 JSON 且内容正确",
       acc == [{"item": "acc-1", "links_to": []}], str(acc))
    ok("export_csv: 子任务 state 与 JSON 一致（done/todo 各一）",
       sorted(row[idx["state"]] for row in st_rows)
       == sorted(s["state"] for s in jdata["subtasks"]),
       str(sorted(row[idx["state"]] for row in st_rows)))
    ms_rows = [row for row in body if row[idx["record_type"]] == "milestone"]
    ok("export_csv: 里程碑行 planned_at/actual_at 与 JSON 导出一致",
       len(ms_rows) == 1
       and ms_rows[0][idx["planned_at"]] == jdata["milestones"][0]["planned_at"]
       and ms_rows[0][idx["actual_at"]] == jdata["milestones"][0]["actual_at"],
       str(ms_rows[0] if ms_rows else None))
    jdec = [e for e in jdata["events"] if e["kind"] == "decision"][0]
    dec = [row for row in body if row[idx["record_type"]] == "event" and row[idx["kind"]] == "decision"][0]
    ok("export_csv: 事件 payload 嵌套列为合法 JSON 且与 JSON 导出一致",
       json.loads(dec[idx["payload"]]) == jdec["payload"], str(jdec["payload"]))
    ok("export_csv: 事件 seq/ts 与 JSON 导出一致",
       dec[idx["seq"]] == str(jdec["seq"]) and dec[idx["ts"]] == jdec["ts"],
       f"seq={dec[idx['seq']]} ts={dec[idx['ts']]}")
    esc = [row for row in body if row[idx["record_type"]] == "event" and row[idx["title"]] == "csv-escape"][0]
    ok("export_csv: 含逗号/引号/换行的 content 经 CSV 转义后原样还原",
       esc[idx["content"]] == ESCAPE_CONTENT, repr(esc[idx["content"]]))
    ok("export_csv: 跨类型空列留空（需求行 seq 空 / 事件行 description 空）",
       rq[idx["seq"]] == "" and esc[idx["description"]] == "", f"req.seq={rq[idx['seq']]!r}")
    # 全量导出
    r2 = seed_req(db, "csv-req2")
    m2 = MCP(db).start()
    m2.call_ok("claim_task", {"requirement_id": r2, "agent_name": "a2"})
    m2.call_ok("add_subtask", {"requirement_id": r2, "title": "st3", "ordinal": 1})
    m2.close()
    res2 = cli(db, "export", "--format", "csv")
    ok("export_csv: 全量导出 CLI rc=0", res2.returncode == 0, res2.stderr[-200:])
    rows2 = list(csv.reader(io.StringIO(res2.stdout)))
    header2, body2 = rows2[0], rows2[1:]
    idx2 = {n: i for i, n in enumerate(header2)}
    jfull = json.loads(cli(db, "export", "--format", "json").stdout)["requirements"]
    ok("export_csv: 全量导出含全部需求（id 与 JSON 一致）",
       {row[idx2["requirement_id"]] for row in body2 if row[idx2["record_type"]] == "requirement"}
       == {q["requirement_id"] for q in jfull},
       str({row[idx2["requirement_id"]] for row in body2 if row[idx2["record_type"]] == "requirement"}))
    ok("export_csv: 全量导出子任务总数与 JSON 一致",
       sum(1 for row in body2 if row[idx2["record_type"]] == "subtask")
       == sum(len(q["subtasks"]) for q in jfull),
       str(sum(1 for row in body2 if row[idx2["record_type"]] == "subtask")))
    ok("export_csv: 全量导出事件总数与 JSON 一致",
       sum(1 for row in body2 if row[idx2["record_type"]] == "event")
       == sum(len(q["events"]) for q in jfull),
       str(sum(1 for row in body2 if row[idx2["record_type"]] == "event")))
    mres = cli(db, "export", "--requirement-id", r1, "--format", "markdown")
    ok("export_csv: markdown 导出回归（标题 + events 节）",
       mres.returncode == 0 and mres.stdout.startswith("# csv-req") and "## events" in mres.stdout,
       mres.stdout[:80])
    res3 = cli(db, "export", "--requirement-id", r1, "--format", "xml")
    ok("export_csv: 非法 format 被拒绝（argparse choices）",
       res3.returncode != 0 and "invalid choice" in res3.stderr, res3.stderr[-120:])
