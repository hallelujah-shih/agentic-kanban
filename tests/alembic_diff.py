"""M0-1.0 验证：空库 alembic upgrade head 后的 sqlite_master 与 models (create_all) 逐项一致。

对比双轨（alembic 迁移 vs create_all 同源 models）：
- 表集合（name + sql，排除 alembic_version）
- 索引集合（name + tbl_name + sql，含 sqlite_where partial unique index）
- FK 集合（name + 列 + 引用表/列）

退出码 0 = 一致；否则打印逐项 diff。
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_PY = REPO_ROOT / ".venv" / "bin" / "python"


def sqlite_master(db: Path) -> dict:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _split_top(body: str) -> list[str]:
    """按顶层逗号切分 CREATE TABLE 子句（跟踪括号深度，UNIQUE(...)/FK(...) 不切裂）。"""
    parts: list[str] = []
    cur: list[str] = []
    depth = 0
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur).strip())
    return [c for c in parts if c]


def _canonical_table_sql(sql: str) -> str:
    """CREATE TABLE DDL 规范化：子句排序（FK/UNIQUE 顺序差异为同语义，排序后可比）。"""
    if not sql or not sql.startswith("CREATE TABLE"):
        return sql
    start = sql.index("(")
    end = sql.rindex(")")
    head = sql[:start].strip()
    clauses = sorted(_split_top(sql[start + 1 : end]))
    return head + "(" + ", ".join(clauses) + ")"


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ak-alembic-"))
    alembic_db = tmp / "alembic.db"
    create_db = tmp / "create_all.db"

    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")

    # 轨 A：空库 alembic upgrade head
    env["AGENT_KANBAN_DB"] = str(alembic_db)
    up = subprocess.run(
        [str(VENV_PY), "-m", "alembic", "upgrade", "head"],
        capture_output=True, text=True, env=env, cwd=str(REPO_ROOT),
    )
    if up.returncode != 0:
        print("alembic upgrade failed:\n", up.stdout, up.stderr)
        return 1

    # 轨 B：create_all（app 双轨兼容路径）
    create_script = (
        "import asyncio\n"
        "from pathlib import Path\n"
        "from agent_kanban.db import make_engine\n"
        "from agent_kanban.models import Base\n"
        "async def main():\n"
        f"    eng = make_engine(Path('{create_db}'))\n"
        "    async with eng.begin() as conn:\n"
        "        await conn.run_sync(Base.metadata.create_all)\n"
        "asyncio.run(main())\n"
    )
    env["AGENT_KANBAN_DB"] = str(create_db)
    cr = subprocess.run(
        [str(VENV_PY), "-c", create_script],
        capture_output=True, text=True, env=env, cwd=str(REPO_ROOT),
    )
    if cr.returncode != 0:
        print("create_all failed:\n", cr.stdout, cr.stderr)
        return 1

    a = sqlite_master(alembic_db)
    b = sqlite_master(create_db)
    a_biz = [r for r in a if r["name"] != "alembic_version"]
    b_biz = [r for r in b if r["name"] != "alembic_version"]

    def norm(rows: list[dict]) -> dict[str, dict]:
        out = {}
        for r in rows:
            key = (r["type"], r["name"])
            sql = r["sql"] or ""
            if key[0] == "table":
                sql = _canonical_table_sql(sql)
            else:  # index：只归一空白（无子句顺序问题）
                sql = " ".join(sql.split())
            out[key] = {"tbl": r["tbl_name"], "sql": sql}
        return out

    na, nb = norm(a_biz), norm(b_biz)
    ok = True
    for key in sorted(set(na) | set(nb)):
        if key not in na:
            print(f"MISSING in alembic: {key}")
            ok = False
        elif key not in nb:
            print(f"EXTRA in alembic: {key}")
            ok = False
        elif na[key]["tbl"] != nb[key]["tbl"]:
            print(f"TABLE MISMATCH {key}: {na[key]['tbl']} != {nb[key]['tbl']}")
            ok = False
        elif na[key]["sql"] != nb[key]["sql"]:
            print(f"SQL MISMATCH {key}:\n  alembic:    {na[key]['sql']}\n  create_all: {nb[key]['sql']}")
            ok = False

    # FK 对照（PRAGMA 逐行，双轨）
    def fks(path: Path) -> list[tuple[str, str, str]]:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        out = []
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            t = row["name"]
            for r in conn.execute(f"PRAGMA foreign_key_list('{t}')").fetchall():
                out.append((t, r["from"], r["to"]))
        conn.close()
        return sorted(out)

    a_fk, b_fk = fks(alembic_db), fks(create_db)
    if a_fk != b_fk:
        print(f"FK MISMATCH:\n  alembic: {a_fk}\n  create_all: {b_fk}")
        ok = False

    # 种子检查：seq_counter(id=1, value=0)
    conn = sqlite3.connect(str(alembic_db))
    row = conn.execute("SELECT id, value FROM seq_counter WHERE id=1").fetchone()
    conn.close()
    if row != (1, 0):
        print(f"seq_counter seed mismatch: {row}")
        ok = False

    # 索引数 & partial unique index 的 WHERE 子句
    partial = [r for r in a_biz if r["type"] == "index" and "WHERE" in (r["sql"] or "")]
    print(f"alembic: {len(a_biz)} objects, {len([r for r in a_biz if r['type'] == 'index'])} indexes, "
          f"{len(partial)} partial unique index(es): {[r['name'] for r in partial]}")

    if ok:
        print(f"OK: alembic upgrade head == create_all 同源 models（{len(a_biz)} 项逐条一致，含 sqlite_where partial index 与 FK）")
        return 0
    print("MISMATCH found")
    return 1


if __name__ == "__main__":
    sys.exit(main())
