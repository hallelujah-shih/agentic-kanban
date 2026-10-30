"""批 b4 派发门可执行化 + 规划入口进 MCP。

覆盖需求 4a3ac0e2 验收：
- a2 规划入口进 MCP：new_requirement + set_expectations 经 MCP 可达（复用 service 层）
- a3 长文本建需求不再 argv 转义：长 description 经 MCP 结构化参数逐字回读（含反引号/美元/引号/换行）
- a5 release/approve/delete 仍不在 agent 面；状态机未改（new -> OPEN 可 claim）

oracle 纪律：断言逐字引自需求判据「主循环在会话内完成建需求+派发全链路，全程不经 argv 转义」；
DB 事后 sqlite3 直查（读数据非读实现）。
"""

from __future__ import annotations

import json

from ac_lib import MCP, cli_ok, new_db, ok, query, seed_req

# 会击穿 shell argv 转义的长文本：反引号（会被命令替换）、美元（变量展开）、
# 双/单引号、换行。MCP 参数走 JSON-RPC 结构化体，经 stdin 逐字传输，不经 shell。
LONG_DESCRIPTION = (
    "第一行：含反引号 `_default_transport`（shell 会当命令执行）。\n"
    "第二行：含美元 $HOME 与 $(date)（shell 会展开）。\n"
    "第三行：含双引号 \"quoted\" 与单引号 'sq'。\n"
    "第四行：普通长文本，用于验证多行逐字回读。\n"
)


def _acceptance(rid: str, db) -> list:
    d = query(db, "SELECT acceptance FROM requirements WHERE id=?", (rid,))
    return json.loads(d[0]["acceptance"]) if d[0]["acceptance"] else []


def q_planning_entry():
    print("== b4-q1: 规划入口进 MCP（new_requirement + set_expectations）")
    db = new_db()
    m = MCP(db).start()

    tools = m.list_tools()
    ok("q: new_requirement/set_expectations 在 agent 面",
       {"new_requirement", "set_expectations"} <= set(tools), str(sorted(tools)))
    ok("q: release/approve/delete 仍不在 agent 面",
       not ({"release", "approve", "delete"} & set(tools)),
       str(sorted(t for t in tools if t in {"release", "approve", "delete"})))

    # a2 + a3：长文本 description + 验收锚，一次建需求，全程无 argv 转义
    nr = m.call_ok("new_requirement", {
        "title": "q-planning",
        "description": LONG_DESCRIPTION,
        "source": "manual",
        "acceptance": [{"item": "A1 规划入口"}, {"item": "A2 长文本"}],
    })
    rid = nr["requirement_id"]
    ok("q: new_requirement 返回 requirement_id + OPEN", nr.get("state") == "OPEN" and bool(rid),
       json.dumps(nr))

    d = m.call_ok("get_task_detail", {"requirement_id": rid})
    ok("q: 长 description 经 MCP 逐字回读（无 argv 转义丢失）",
       d.get("description") == LONG_DESCRIPTION,
       repr(d.get("description")[:120]) if d.get("description") != LONG_DESCRIPTION else "ok")
    acc = d.get("acceptance") or []
    ok("q: acceptance 锚随 new 落库（a1/a2 两条）",
       [a.get("item") for a in acc] == ["A1 规划入口", "A2 长文本"], json.dumps(acc))

    # set_expectations：修改/追加锚，唯一入口语义保留 + links_to 删除保护复用
    se = m.call_ok("set_expectations", {
        "requirement_id": rid,
        "acceptance": [{"item": "A1 规划入口"}, {"item": "A2 长文本"}, {"item": "A3 派发"}],
    })
    ok("q: set_expectations 返回 requirement_id", se.get("requirement_id") == rid, json.dumps(se))
    d2 = m.call_ok("get_task_detail", {"requirement_id": rid})
    acc2 = d2.get("acceptance") or []
    ok("q: set_expectations 追加锚后回读",
       [a.get("item") for a in acc2] == ["A1 规划入口", "A2 长文本", "A3 派发"], json.dumps(acc2))

    # a5：状态机未改——新建需求是 OPEN，可被 claim（规划 -> 派发前置链路通）
    c = m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "q-worker"})
    ok("q: 新建需求 OPEN 可 claim（claim 返回 claim_id）", bool(c.get("claim_id")), json.dumps(c))
    row = query(db, "SELECT state FROM requirements WHERE id=?", (rid,))[0]
    ok("q: claim 后 state=CLAIMED（状态机未改）", row["state"] == "CLAIMED", row["state"])
    m.close()


def q_jira_source():
    print("== b4-q2: new_requirement 的 source/source_ref 经 MCP 对齐 CLI")
    db = new_db()
    m = MCP(db).start()
    nr = m.call_ok("new_requirement", {
        "title": "q-jira",
        "description": "Jira 摘要",
        "source": "jira",
        "source_ref": "https://jira.example.com/browse/X-1",
    })
    rid = nr["requirement_id"]
    row = query(db, "SELECT source, source_ref FROM requirements WHERE id=?", (rid,))[0]
    ok("q: source=jira + source_ref 落库",
       row["source"] == "jira" and row["source_ref"] == "https://jira.example.com/browse/X-1",
       str(dict(row)))
    m.close()


def q_no_argv_escape():
    print("== b4-q3: 长文本建需求端到端（无 argv 转义、无删了重建）")
    db = new_db()
    m = MCP(db).start()
    # 模拟主循环现场：会话内一次 MCP 调用建需求（含长 description + 锚），
    # 无 cli.py 切 shell、无 argv 转义、无需先占位后 delete 重建。
    nr = m.call_ok("new_requirement", {
        "title": "q-e2e",
        "description": LONG_DESCRIPTION + "尾追加行，验证整体完整。",
        "acceptance": ["锚一", "锚二", "锚三"],
    })
    rid = nr["requirement_id"]
    d = m.call_ok("get_task_detail", {"requirement_id": rid})
    ok("q: 端到端 description 完整回读",
       d.get("description") == LONG_DESCRIPTION + "尾追加行，验证整体完整。",
       repr(d.get("description")[-40:]) if d.get("description") != LONG_DESCRIPTION + "尾追加行，验证整体完整。" else "ok")
    acc = d.get("acceptance") or []
    ok("q: 字符串锚自动分配 id a1/a2/a3",
       [a.get("id") for a in acc] == ["a1", "a2", "a3"]
       and [a.get("item") for a in acc] == ["锚一", "锚二", "锚三"], json.dumps(acc))
    m.close()


def q_set_expectations_error():
    print("== b4-q4: set_expectations 错误面（唯一入口语义 + 错误码）")
    db = new_db()
    m = MCP(db).start()
    code, _ = m.call_err("set_expectations", {"requirement_id": "deadbeef", "acceptance": [{"item": "X"}]})
    ok("q: 不存在需求 -> not_found", code == "not_found", code)
    # links_to 删除保护复用（CLI 同源）：先建 + 锚 + 子任务引用
    rid = seed_req(db, "q-links")
    m.call_ok("set_expectations", {"requirement_id": rid, "acceptance": [{"item": "A1"}, {"item": "A2"}]})
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.call_ok("add_subtask", {"requirement_id": rid, "title": "impl", "ordinal": 1,
                              "acceptance": [{"item": "x", "links_to": "a1"}]})
    code, _ = m.call_err("set_expectations", {"requirement_id": rid, "acceptance": [{"item": "A2"}]})
    ok("q: 删除被 links_to 引用的锚 -> invalid_record", code == "invalid_record", code)
    m.close()
    # 释放：q4 认领了需求，需人面 release 才回 OPEN（不在此测，走下一用例隔离 DB）