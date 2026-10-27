"""批 2 A1 前缀解析 + A2 租约态返回用例（tests/ac_cases_m.py + run_ac 注册）。

oracle 纪律：断言逐字引 spec 2026-10-27-a1a2-mcp-surface §2（解析算法/传播规则/
ambiguous_id 钉死模板）/§4（兼容矩阵）/§5.1（PRD id 解析口径）；DB 事后 sqlite3 直查
（读数据非读实现）；需求行 SQL 直插指定 32-hex id（seed_req 走 CLI new，无法控前缀）。

覆盖（spec §6 十一用例，m1-m9 属 T1、m10-m11 属 T2）：
- m1 传播规则判别：唯一 8 位前缀认领成功 + 事件 requirement_id 落 32-hex 全 id
- m2 歧义：两同前缀 -> ambiguous_id + 两候选入消息 + 零写入
- m3 >5 候选：消息逐字匹配钉死模板（共 6 个候选，前 5 + …）
- m4 0 命中前缀 -> not_found（消息含原始输入）
- m5 <8 位 / 非 hex / 空串 -> not_found
- m6 全 id 回归（精确路径）：小写存在命中 / 不存在 not_found
- m7 归一面：大写全 id / 大写前缀 / 首尾空白 / 36 连字符全 id
- m8 跨面：MCP 与 REST 同前缀同结果（同目标 / 同 409）
- m9 返回 echo：claim_task 前缀输入 -> 32-hex 全 id
- m10 A2 返回：lease_expires_at（aware UTC iso）+ 前缀输入返回全 id
- m11 口径：renew -> update_progress 两返回 lease_expires_at 相等
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from ac_lib import MCP, REST, cli_ok, new_db, ok, query, seed_req

PFX = "aabbccdd"
_BOOTSTRAPPED: set[Path] = set()


def _seed(db: Path, rid: str, title: str = "m-req") -> None:
    """需求行直插（指定 32-hex id）；created_at 存 naive UTC 字符串（UTCDateTime 口径）。
    new_db 是空文件无 schema：首个 _seed 先经 CLI `new`（子进程 ensure_schema）建表，
    bootstrap 行为随机 uuid4 需求，与本文件断言不冲突（前缀碰撞概率 2^-32）。"""
    if db not in _BOOTSTRAPPED:
        seed_req(db, "m-bootstrap")
        _BOOTSTRAPPED.add(db)
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO requirements (id, source, title, acceptance, state, created_at, updated_at) "
        "VALUES (?, 'manual', ?, '[]', 'OPEN', '2026-01-01 00:00:00', '2026-01-01 00:00:00')",
        (rid, title),
    )
    conn.commit()
    conn.close()


def _snap(db: Path) -> tuple:
    """全局写入指纹（events 数, claims 数, 各需求 state）——零写入对照。"""
    ev = query(db, "SELECT COUNT(*) AS n FROM events")[0]["n"]
    cl = query(db, "SELECT COUNT(*) AS n FROM claims")[0]["n"]
    states = [(r["id"], r["state"]) for r in query(db, "SELECT id, state FROM requirements ORDER BY id")]
    return (ev, cl, tuple(states))


def _call_err2(m: MCP, name: str, args: dict) -> tuple[str, str]:
    """call + 解错误 payload 返回 (code, message)（ac_lib.call_err 不返 message，ac_cases_l 同模式）。"""
    res = m.call(name, args)
    if not res.get("isError"):
        raise AssertionError(f"{name} unexpectedly succeeded: {res}")
    payload = json.loads(res["content"][0]["text"])
    return payload["code"], payload.get("message", "")


def m_prefix_unique():
    print("== m1: 唯一 8 位前缀 -> 目标需求，事件落 32-hex（传播规则判别）")
    db = new_db()
    rid = "a1b2c3d4" + "f" * 24
    _seed(db, rid)
    m = MCP(db).start()
    try:
        m.call_ok("claim_task", {"requirement_id": rid[:8], "agent_name": "a"})
        ok("m1: 前缀 claim 成功", True, "")
        m.call_ok("add_record", {"requirement_id": rid[:8], "kind": "note", "title": "t"})
        ids = {r["requirement_id"] for r in query(db, "SELECT requirement_id FROM events")}
        ok("m1: 全部事件 requirement_id = 32-hex 全 id（传播到下游）", ids == {rid}, str(ids))
    finally:
        m.close()


def m_prefix_ambiguous():
    print("== m2: 前缀命中 2 -> ambiguous_id + 两候选入消息 + 零写入")
    db = new_db()
    a = PFX + "0" * 23 + "1"
    b = PFX + "0" * 23 + "2"
    _seed(db, a)
    _seed(db, b)
    m = MCP(db).start()
    try:
        snap0 = _snap(db)
        code, msg = _call_err2(m, "claim_task", {"requirement_id": PFX, "agent_name": "x"})
        ok("m2: ambiguous_id", code == "ambiguous_id", code)
        ok("m2: 消息含两候选", a in msg and b in msg, msg)
        ok("m2: 消息含加长前缀提示", "longer prefix" in msg, msg)
        ok("m2: 零写入（events/claims/state 不变）", _snap(db) == snap0, str(_snap(db)))
    finally:
        m.close()


def m_prefix_trunc():
    print("== m3: >5 候选 -> 消息逐字匹配钉死模板（共 6 个候选，前 5 + …）")
    db = new_db()
    cands = sorted("deadbeef" + "0" * 23 + str(i) for i in range(1, 7))
    for c in cands:
        _seed(db, c)
    m = MCP(db).start()
    try:
        code, msg = _call_err2(m, "get_task_detail", {"requirement_id": "deadbeef"})
        expected = (
            "ambiguous requirement_id prefix 'deadbeef': "
            f"{', '.join(cands[:5])} …, 共 6 个候选; use a longer prefix"
        )
        ok("m3: ambiguous_id", code == "ambiguous_id", code)
        ok("m3: 消息逐字匹配钉死模板", msg == expected, msg)
    finally:
        m.close()


def m_prefix_zero():
    print("== m4: 0 命中前缀 -> not_found（消息含原始输入）")
    db = new_db()
    _seed(db, "a1b2c3d4" + "f" * 24)
    m = MCP(db).start()
    try:
        code, msg = _call_err2(m, "get_task_detail", {"requirement_id": "ffff0000"})
        ok("m4: not_found", code == "not_found", code)
        ok("m4: 消息含原始输入", "ffff0000" in msg, msg)
    finally:
        m.close()


def m_prefix_invalid():
    print("== m5: <8 位 / 非 hex / 空串 -> not_found")
    db = new_db()
    _seed(db, "a1b2c3d4" + "f" * 24)
    m = MCP(db).start()
    try:
        for raw in ("abcd", "1234567", "1234567g", ""):
            code, _ = _call_err2(m, "get_task_detail", {"requirement_id": raw})
            ok(f"m5: {raw!r} -> not_found", code == "not_found", code)
    finally:
        m.close()


def m_full_id():
    print("== m6: 全 id 回归（精确路径）")
    db = new_db()
    rid = "a1b2c3d4" + "f" * 24
    _seed(db, rid)
    m = MCP(db).start()
    try:
        res = m.call_ok("get_task_detail", {"requirement_id": rid})
        ok("m6: 小写全 id 存在 -> 命中", res["requirement_id"] == rid, str(res["requirement_id"]))
        code, _ = _call_err2(m, "get_task_detail", {"requirement_id": "0" * 32})
        ok("m6: 全 id 不存在 -> not_found", code == "not_found", code)
    finally:
        m.close()


def m_normalization():
    print("== m7: 归一面（大写 / 空白 / 36 连字符）")
    db = new_db()
    rid = "a1b2c3d4" + "f" * 24
    _seed(db, rid)
    hyphenated = f"{rid[:8]}-{rid[8:12]}-{rid[12:16]}-{rid[16:20]}-{rid[20:]}"
    m = MCP(db).start()
    try:
        res = m.call_ok("get_task_detail", {"requirement_id": rid.upper()})
        ok("m7: 大写全 id -> 命中（新行为）", res["requirement_id"] == rid, str(res["requirement_id"]))
        res = m.call_ok("get_task_detail", {"requirement_id": rid[:8].upper()})
        ok("m7: 大写前缀 -> 命中", res["requirement_id"] == rid, str(res["requirement_id"]))
        res = m.call_ok("get_task_detail", {"requirement_id": f"  {rid[:8]}  "})
        ok("m7: 首尾空白前缀 -> 命中", res["requirement_id"] == rid, str(res["requirement_id"]))
        res = m.call_ok("get_task_detail", {"requirement_id": hyphenated})
        ok("m7: 36 连字符全 id -> 命中", res["requirement_id"] == rid, str(res["requirement_id"]))
        ok(
            "m7: echo 为 32-hex（无连字符，读回形态归一）",
            len(res["requirement_id"]) == 32 and "-" not in res["requirement_id"],
            res["requirement_id"],
        )
    finally:
        m.close()


def m_cross_surface():
    print("== m8: 跨面一致性（MCP 与 REST 同前缀同结果）")
    db = new_db()
    r1 = "cafe1234" + "e" * 24
    r2 = "cafe1234" + "d" * 24
    _seed(db, r1)
    _seed(db, r2)
    m = MCP(db).start()
    rest = REST(db).start()
    try:
        got = m.call_ok("get_task_detail", {"requirement_id": "cafe1234e"})
        status, body = rest.req("GET", "/requirements/cafe1234e/summary")
        ok("m8: 唯一前缀 MCP 命中目标", got["requirement_id"] == r1, str(got["requirement_id"]))
        ok(
            "m8: 唯一前缀 REST 命中同目标",
            status == 200 and isinstance(body, dict) and body.get("requirement_id") == r1,
            f"{status} {body if status != 200 else 'ok'}",
        )
        code, _ = _call_err2(m, "get_task_detail", {"requirement_id": "cafe1234"})
        status, body = rest.req("GET", "/requirements/cafe1234/summary")
        ok("m8: 歧义前缀 MCP -> ambiguous_id", code == "ambiguous_id", code)
        ok(
            "m8: 歧义前缀 REST -> 409 + ambiguous_id",
            status == 409 and isinstance(body, dict) and body.get("code") == "ambiguous_id",
            f"{status} {body}",
        )
    finally:
        m.close()
        rest.stop()


def m_echo():
    print("== m9: 返回 echo（claim_task 前缀输入 -> 32-hex 全 id；全 id 恒等回归）")
    db = new_db()
    rid = "ec0c1234" + "a" * 24
    _seed(db, rid)
    m = MCP(db).start()
    try:
        res = m.call_ok("claim_task", {"requirement_id": rid[:9], "agent_name": "a"})
        ok(
            "m9: 前缀输入返回 32-hex 全 id",
            res["requirement_id"] == rid and len(res["requirement_id"]) == 32,
            str(res["requirement_id"]),
        )
        db2 = new_db()
        rid2 = "ec0c1234" + "b" * 24
        _seed(db2, rid2)
        m2 = MCP(db2).start()
        try:
            res2 = m2.call_ok("claim_task", {"requirement_id": rid2, "agent_name": "a"})
            ok("m9: 全 id 输入返回恒等（回归）", res2["requirement_id"] == rid2, str(res2["requirement_id"]))
        finally:
            m2.close()
    finally:
        m.close()


def m_lease_return():
    print("== m10: A2 返回（lease_expires_at aware UTC iso + 前缀输入返回全 id）")
    db = new_db()
    rid = "0f0e0d0c" + "b" * 24
    _seed(db, rid)
    m = MCP(db).start()
    try:
        m.call_ok("claim_task", {"requirement_id": rid[:8], "agent_name": "a"})
        res = m.call_ok("update_progress", {"requirement_id": rid[:8], "note": "n", "headline": "h"})
        ok("m10: 前缀输入 requirement_id = 32-hex 全 id", res["requirement_id"] == rid, str(res["requirement_id"]))
        ok("m10: 含 lease_expires_at", "lease_expires_at" in res, str(res))
        v = res.get("lease_expires_at", "")
        dt = datetime.fromisoformat(v)
        ok(
            "m10: aware UTC iso（…+00:00，全仓 UTCDateTime 口径）",
            dt.utcoffset() is not None and v.endswith("+00:00"),
            v,
        )
    finally:
        m.close()


def m_lease_seq():
    print("== m11: 口径（顺序钉死 renew -> update_progress，两返回 lease_expires_at 相等）")
    db = new_db()
    rid = "11223344" + "c" * 24
    _seed(db, rid)
    m = MCP(db).start()
    try:
        m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
        r1 = cli_ok(db, "renew", "--requirement-id", rid)  # renew 是人面 CLI/REST（MCP 12 工具无 renew，v1.3 裁决）
        r2 = m.call_ok("update_progress", {"requirement_id": rid, "note": "n", "headline": "h"})
        ok(
            "m11: renew 与 update_progress 返回 lease_expires_at 相等",
            r1.get("lease_expires_at") == r2.get("lease_expires_at"),
            f"{r1.get('lease_expires_at')} vs {r2.get('lease_expires_at')}",
        )
    finally:
        m.close()
