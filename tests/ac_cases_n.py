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
