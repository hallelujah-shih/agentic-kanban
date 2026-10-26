# 实施计划：Task 生命周期操作（create/archive/delete）与看板定位重述

**Goal**: 人获得 task 级生命周期管理权（Web 创建/归档/删除），新增 ARCHIVED 终态，看板 Web 瘦身为"只读 + 生命周期"，决策操作 Web 移除、REST/CLI 保留（语义零改动）。
**Architecture**: ARCHIVED = 新终态 + 唯一人面边 `(任一 -> ARCHIVED)`；archive 复用 abandon 的"同事务结束认领"模式；delete = 整需求五表原子硬删（不写事件）；终态集合收敛为 `operations_util.TERMINAL_STATES` 单一事实源（board/list_tasks/prune 三处引用）；Web 壳移除决策按钮、加生命周期操作区与新建表单。
**Tech Stack**: Python 3.12 / FastAPI / SQLAlchemy 2.0 async / SQLite / 自研 AC harness（非 pytest）。
**Spec**: `docs/superpowers/specs/2026-10-26-task-lifecycle-positioning-design.md`（对抗审查 APPROVE-WITH-FIXES 已折入，报告 `-review.md` 同目录）。
**BCD**: `docs/business-contracts/task-lifecycle-positioning.md`（user 裁决 Q1=A / Q2=方案1 / Q3=from=None 沿用 REJECTED 先例）。
**分支/worktree**: `task-lifecycle`（`.worktree/task-lifecycle`，基于 main 8767385）。

## 全局约束

- 无新增错误码；MCP 工具面 12 工具零改动；C6 保持（DONE 仅人面）；事件链永不半断（删除一律整需求为单位）。
- 创建不写事件、不加事件 kind；无 unarchive；不开放 sub task 人面编辑。
- 壳契约保持：board-root / detail-root / EventSource / 零数据嵌入（无原始输出）。
- harness oracle 纪律：断言引 PRD 语义；DB 事后 sqlite3 直查；确定性（禁 sleep 撞窗，backdate 用 SQL 改 ts）；真实子进程（MCP stdio / uvicorn / CLI），禁 mock。
- 所有命令在 worktree 根 `/home/shih/test/AgenticKanban/.worktree/task-lifecycle` 执行。
- 每任务一个独立审查门：本任务全绿 + 全量回归绿才提交；提交信息引用任务号。

## 审查重点（spec 暗示但测试最难守住、失败最伤人的 5 处）

1. 人误删错任务 -> 预期：CLI 确认门（y/N + 展示 title/状态/事件数 + 导出建议）/ Web 标题输入确认。测试 pin 在 T3（CLI 确认门 n/EOF/y/--yes 四路径）。
2. 任务被删后 agent 继续工作 -> 预期：MCP 读写拿结构化 not_found（非崩溃/挂起），list_tasks 不再返回。测试 pin 在 T3 (ii)(iii)。
3. 已归档任务静默回到 agent 工作列表 -> 预期：list_tasks / board / GET /requirements 默认过滤均排除 ARCHIVED。测试 pin 在 T1 (i)（审 P1-1 的直接防线）。
4. awaiting 出现后人无路可走 -> 预期：深潜页/看板卡片横幅静态 CLI 提示。测试 pin 在 T4（壳含提示文案）+ web.md 冒烟清单（人工）。
5. prune 误删归档未出窗数据或活任务 -> 预期：仅终态且全事件出窗；需求行保留（prune 只删事件）。测试 pin 在 T1 (iv) 三任务场景 + "需求行仍在"显式断言（审 P2-7）。

## 文件结构

| 文件 | 责任 | 任务 |
|---|---|---|
| `src/agent_kanban/services/operations_util.py` | 叶子模块：TERMINAL_STATES 单一事实源 | T1 |
| `src/agent_kanban/services/state_machine.py` | 状态机边表：+(None, ARCHIVED) | T1 |
| `src/agent_kanban/services/view.py` | board 默认过滤引用常量（删本地定义） | T1 |
| `src/agent_kanban/services/operations.py` | list_tasks 过滤 + PRUNE 别名（T1）；archive_requirement（T2）；delete_preview + delete_requirement（T3） | T1/T2/T3 |
| `src/agent_kanban/api/requirements.py` | archive / delete REST 端点 | T2/T3 |
| `cli.py` | archive / delete 子命令（delete 含确认门）；prune 确认文案补 ARCHIVED | T2/T3/T5 |
| `src/agent_kanban/api/web.py` | 壳：_THEME/_JS_COMMON + board 壳 + detail 壳 | T4 |
| `tests/ac_cases_k.py` | 新建 harness 用例文件（k_state/k_archive/k_delete/k_web） | T1-T4 |
| `tests/run_ac.py` | 注册新用例 | T1-T4 |
| `docs/PRD.md` `docs/design.md` `docs/web.md` `docs/adr/0000-known-gaps.md` `README.md` | 文档同步 + 残余登记 | T5 |

---

## Task 1: ARCHIVED 状态值 + 终态集合单一事实源 + 状态机边

**Files:**
- Modify: `src/agent_kanban/services/operations_util.py`
- Modify: `src/agent_kanban/services/state_machine.py`
- Modify: `src/agent_kanban/services/view.py`
- Modify: `src/agent_kanban/services/operations.py`
- Create: `tests/ac_cases_k.py`
- Modify: `tests/run_ac.py`

**Interfaces:**
- Produces: `operations_util.TERMINAL_STATES: tuple[str, ...]`（("DONE","REJECTED","CANCELLED","ARCHIVED")）；state 值 "ARCHIVED" 全链路可识别；三处默认过滤（board / list_tasks / prune）排除 ARCHIVED；`claim/approve/reopen on ARCHIVED -> illegal_state` 且零副作用。`archive_requirement` 本任务**不提供**（T2）。
- 测试基建既有签名（ac_lib.py，勿改动）：`ok(name, cond, detail)`、`new_db() -> Path`、`seed_req(db, title) -> rid`、`seed_reopen(db, rid)`、`query(db, sql, params) -> list[sqlite3.Row]`、`cli_ok(db, *args) -> dict`、`cli_err(db, *args) -> (code, message)`、`MCP(db).start()`、`m.call_ok(tool, args) -> dict`、`m.call_err(tool, args) -> (code, task_id)`、`REST(db, extra=...).start()`、`rest.req(method, path, body=None, params=None, token=None, headers=None) -> (status, body)`。

**Steps:**

- [ ] **Step 1: 建 `tests/ac_cases_k.py`（文件头 + helpers + k_state）**

```python
"""M1-4 task 生命周期用例（tests/ac_cases_k.py + run_ac 注册）。

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

HISTORY_NOTE = "该需求事件已按保留窗口清理，完整历史见导出归档"


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
    print("== M1-4.1: ARCHIVED 状态值 + 终态集合单一事实源（三默认列表/claim/approve/reopen/prune）")
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
```

- [ ] **Step 2: 注册进 `tests/run_ac.py`**

import 区加（`from ac_cases_j import export_csv` 之后）：
```python
from ac_cases_k import k_state
```
TESTS 字典 `}` 前加：
```python
    "k_state": k_state,
```

- [ ] **Step 3: 红跑**

Run: `uv run python tests/run_ac.py --only k_state`
Expected: FAIL（`k_state(i)` 三条默认列表断言——当前过滤列表无 ARCHIVED，任务会出现在列表里；`k_state(iv)` "ARCHIVED 出窗 -> events 整删"——当前 `PRUNE_TERMINAL_STATES` 无 ARCHIVED）。(ii)(iii) 应已 PASS（既有行为），若 (ii)(iii) 也 FAIL 说明对既有机制理解有误，停下核对 `state_machine.py` / `operations.py`。

- [ ] **Step 4: 实现**

(1) `operations_util.py` 文件尾追加：
```python
# 终态集合单一事实源（spec 5 / 审 P1-1）：view.board / operations.list_tasks /
# operations.PRUNE_TERMINAL_STATES 三处引用此常量，不再各持硬编码列表
TERMINAL_STATES = ("DONE", "REJECTED", "CANCELLED", "ARCHIVED")
```

(2) `state_machine.py` `ALLOWED_EDGES` 中 `(None, "REJECTED"): HUMAN,` 之后加：
```python
    (None, "ARCHIVED"): HUMAN,
```

(3) `view.py`：
- import 区（`from .write_guard import require_requirement` 之后）加：
```python
from .operations_util import TERMINAL_STATES
```
- 删除本地定义行 `TERMINAL_STATES = ("DONE", "REJECTED", "CANCELLED")`（约 line 191，验收对照表 helper 之后；注意 HISTORY_NOTE 在文件头部 import 区之后，不要混淆位置）
- `board()` 默认过滤（约 line 227）：
```python
        stmt = stmt.where(Requirement.state.not_in(["DONE", "REJECTED", "CANCELLED"]))
```
改为：
```python
        stmt = stmt.where(Requirement.state.not_in(TERMINAL_STATES))
```

(4) `operations.py`：
- line 19 import 改为：
```python
from .operations_util import TERMINAL_STATES, add_event, normalize_anchors, normalize_title
```
- `list_tasks()` 默认过滤（约 line 780，与 view.board 同形）：
```python
        stmt = stmt.where(Requirement.state.not_in(["DONE", "REJECTED", "CANCELLED"]))
```
改为：
```python
        stmt = stmt.where(Requirement.state.not_in(TERMINAL_STATES))
```
- 约 line 953：
```python
PRUNE_TERMINAL_STATES = ("DONE", "REJECTED", "CANCELLED")
```
改为（保留原名别名，既有引用不破坏）：
```python
PRUNE_TERMINAL_STATES = TERMINAL_STATES
```

- [ ] **Step 5: 绿跑 + 全量回归**

Run: `uv run python tests/run_ac.py --only k_state` -> 全 PASS。
Run: `uv run python tests/run_ac.py` -> 全绿（既有 400+ 断言零回归；特别注意 `prune_terminal`/`prune_cross`/`prune_zombie`/`board`/`board_term`/`web`）。

- [ ] **Step 6: 提交**

```bash
git add src/agent_kanban/services/operations_util.py src/agent_kanban/services/state_machine.py \
  src/agent_kanban/services/view.py src/agent_kanban/services/operations.py \
  tests/ac_cases_k.py tests/run_ac.py
git commit -m "T1: ARCHIVED 状态值 + 终态集合单一事实源 operations_util.TERMINAL_STATES（board/list_tasks/prune 三处引用，审 P1-1）+ 状态机边 (None, ARCHIVED): HUMAN；harness k_state（三默认列表排除/claim 零副作用/approve+reopen illegal_state/prune 覆盖含需求行保留断言）"
```

---

## Task 2: archive 操作（ops + CLI + REST + harness 七状态矩阵）

**Files:**
- Modify: `src/agent_kanban/services/operations.py`（`archive_requirement`，放 `abandon` 函数之后、"agent 面（MCP）"注释之前，约 line 377）
- Modify: `src/agent_kanban/api/requirements.py`（archive 端点）
- Modify: `cli.py`（`_cmd_archive` + parser 条目）
- Modify: `tests/ac_cases_k.py`（`k_archive`）
- Modify: `tests/run_ac.py`（注册 `k_archive`）

**Interfaces:**
- Produces: `ops.archive_requirement(session, *, requirement_id, actor_surface, actor_conn, now=None) -> {"requirement_id", "state": "ARCHIVED"}`（经 `run_op(is_write=True)`）；CLI `kanban archive --requirement-id <id>`；REST `POST /requirements/{id}/archive`（200 / 404 not_found）。
- 事件形态（Q3 裁决，REJECTED 先例）：`state_change`，title `"? -> ARCHIVED"`，payload `{"from": None, "to": "ARCHIVED"}`，claim_id = 活跃认领 id（有则）。claim 处置：`ended_at` + `release_reason="archive"`（同事务）。

**Steps:**

- [ ] **Step 1: `tests/ac_cases_k.py` 追加 `k_archive`；`run_ac.py` 注册**

import 行补 `seed_reopen`（若 Step 1 已含则不重复）：
```python
from ac_cases_k import k_state, k_archive   # run_ac.py 侧
    "k_archive": k_archive,                 # TESTS
```

```python
def k_archive():
    print("== M1-4.2: archive 七状态矩阵 + claim 同事务结束（release_reason=archive）+ marker 清除 + 事件形态 + channel 归属")
    def _seed_state(db, title, state, need_claim=False, need_blocked=False):
        rid = seed_req(db, title)
        if need_claim or state == "DONE":
            m = MCP(db).start()
            m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
            if need_blocked:
                m.call_ok("mark_blocked", {"requirement_id": rid, "reason": "waiting input"})
            m.close()
        if state == "DONE":
            cli_ok(db, "approve", "--requirement-id", rid)  # CLAIMED -> DONE（无 marker 亦合法，PRD 3.4）
        elif state == "REOPEN":
            seed_reopen(db, rid)
        elif state in ("REJECTED", "CANCELLED"):
            cli_ok(db, "abandon", "--requirement-id", rid, "--to-state", state)
        return rid

    # (i) 七状态矩阵（CLI channel：actor_surface=cli / actor_conn=cli）
    for state, need_claim, need_blocked in [
        ("OPEN", False, False), ("CLAIMED", True, False), ("BLOCKED", True, True),
        ("REOPEN", False, False), ("DONE", False, False), ("REJECTED", False, False),
        ("CANCELLED", False, False)]:
        db = new_db()
        rid = _seed_state(db, f"k-arch-{state}", state, need_claim, need_blocked)
        resp = cli_ok(db, "archive", "--requirement-id", rid)
        ok(f"k_archive({state}): CLI archive -> ARCHIVED", resp.get("state") == "ARCHIVED", str(resp))
        row = query(db, "SELECT state, awaiting_human FROM requirements WHERE id=?", (rid,))[0]
        ok(f"k_archive({state}): requirements.state=ARCHIVED", row["state"] == "ARCHIVED", str(dict(row)))
        ev = query(db, "SELECT title, payload, actor_surface, actor_conn, claim_id "
                       "FROM events WHERE requirement_id=? ORDER BY seq DESC LIMIT 1", (rid,))[0]
        pl = json.loads(ev["payload"])
        ok(f"k_archive({state}): 事件链尾 state_change from=None to=ARCHIVED（Q3 裁决形态）",
           ev["title"] == "? -> ARCHIVED" and pl == {"from": None, "to": "ARCHIVED"}, str(dict(ev)))
        ok(f"k_archive({state}): CLI 归属 surface=cli conn=cli",
           ev["actor_surface"] == "cli" and ev["actor_conn"] == "cli", f"{ev['actor_surface']}/{ev['actor_conn']}")
        if need_claim:
            c = query(db, "SELECT ended_at, release_reason FROM claims WHERE requirement_id=? AND ended_at IS NOT NULL", (rid,))[0]
            ok(f"k_archive({state}): claim 同事务 ended（release_reason=archive）",
               c["ended_at"] is not None and c["release_reason"] == "archive", str(dict(c)))
            cid = query(db, "SELECT id FROM claims WHERE requirement_id=?", (rid,))[0]["id"]
            ok(f"k_archive({state}): 事件 claim_id 归属到认领", ev["claim_id"] == cid, f"{ev['claim_id']} vs {cid}")
        if need_blocked:
            ok("k_archive(BLOCKED): awaiting_human 清除", row["awaiting_human"] is None, str(row["awaiting_human"]))
    # (ii) REST channel（surface=cli / conn=rest:* 前缀）+ 再 archive 允许 + 404
    db2 = new_db()
    rid2 = seed_req(db2, "k-arch-rest")
    rest = REST(db2).start()
    try:
        code, body = rest.req("POST", f"/requirements/{rid2}/archive")
        ok("k_archive: REST archive 200", code == 200 and body["state"] == "ARCHIVED", f"{code} {body}")
        # 视图（spec case 2 / AC3）：board 默认排除 + status 过滤包含 + finished_at = archive 事件 ts
        code, body = rest.req("GET", "/board")
        ok("k_archive: board 默认响应不含 ARCHIVED",
           code == 200 and rid2 not in [t["requirement_id"] for t in body["tasks"]], str([t["requirement_id"] for t in body["tasks"]]))
        code, body = rest.req("GET", "/board", params={"status": "ARCHIVED"})
        row_t = [t for t in body["tasks"] if t["requirement_id"] == rid2]
        ok("k_archive: /board?status=ARCHIVED 包含", len(row_t) == 1, str(body.get("tasks")))
        code, d = rest.req("GET", f"/requirements/{rid2}")
        last_sc = [e for e in d["events"] if e["kind"] == "state_change"][-1]
        ok("k_archive: finished_at = archive 事件 ts（_terminal_entry_ts 派生，零改动验证）",
           row_t and row_t[0]["finished_at"] == last_sc["ts"],
           f"{row_t[0]['finished_at'] if row_t else 'missing'} vs {last_sc['ts']}")
        code, body = rest.req("POST", f"/requirements/{rid2}/archive")
        ok("k_archive: ARCHIVED 上再 archive 允许（与 REJECTED->REJECTED 既有口径一致）",
           code == 200 and body["state"] == "ARCHIVED", f"{code} {body}")
        code, body = rest.req("POST", "/requirements/deadbeef/archive")
        ok("k_archive: archive 不存在 -> 404 not_found", code == 404 and body["code"] == "not_found", f"{code} {body}")
    finally:
        rest.stop()
    ev2 = query(db2, "SELECT actor_surface, actor_conn FROM events WHERE requirement_id=? "
                      "AND kind='state_change' ORDER BY seq DESC LIMIT 1", (rid2,))[0]
    ok("k_archive: REST 归属 surface=cli conn=rest:*",
       ev2["actor_surface"] == "cli" and ev2["actor_conn"].startswith("rest:"),
       f"{ev2['actor_surface']}/{ev2['actor_conn']}")
    db3 = new_db()
    code3, _ = cli_err(db3, "archive", "--requirement-id", "deadbeef")
    ok("k_archive: CLI archive 不存在 -> not_found", code3 == "not_found", code3)
```

- [ ] **Step 2: 红跑**

Run: `uv run python tests/run_ac.py --only k_archive`
Expected: FAIL（CLI `archive` 子命令不存在 -> `cli_ok` 抛 "cli ... failed"；REST 404/405）。

- [ ] **Step 3: 实现**

(1) `operations.py`，`abandon` 之后插入（逐字对照 abandon 的认领处置模式）：
```python
async def archive_requirement(
    session: AsyncSession,
    *,
    requirement_id: str,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
) -> dict:
    now = now or now_utc()
    await require_requirement(session, requirement_id)
    claim = await session.scalar(
        select(Claim).where(Claim.requirement_id == requirement_id, Claim.ended_at.is_(None))
    )
    claim_id = claim.id if claim is not None else None
    await transition(
        session, requirement_id=requirement_id, from_state=None, to_state="ARCHIVED",
        actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim_id, now=now,
    )
    # 同事务结束未结束认领（abandon 模式，operations.py:371-375）；清 marker 由 transition 通规完成
    if claim is not None:
        await session.execute(
            update(Claim).where(Claim.id == claim.id).values(ended_at=now, release_reason="archive")
        )
    return {"requirement_id": requirement_id, "state": "ARCHIVED"}
```

(2) `requirements.py`，人面端点区（`reopen` 端点之后）加：
```python
@router.post("/requirements/{requirement_id}/archive")
async def archive_requirement(requirement_id: str) -> dict:
    return await _run("archive_requirement", requirement_id=requirement_id)
```

(3) `cli.py`：
- parser（`abandon` parser 块之后）：
```python
    p = sub.add_parser("archive", help="归档（任一状态 -> ARCHIVED 终态；同事务结束未结束认领）")
    p.add_argument("--requirement-id", required=True)
    p.set_defaults(handler=_cmd_archive)
```
- handler（`_cmd_abandon` 之后；确认 `_cmd_abandon` 的实际位置后紧随其后）：
```python
def _cmd_archive(args: argparse.Namespace) -> int:
    return _invoke("archive_requirement", requirement_id=args.requirement_id)
```

- [ ] **Step 4: 绿跑 + 全量回归**

Run: `uv run python tests/run_ac.py --only k_archive` -> 全 PASS。
Run: `uv run python tests/run_ac.py` -> 全绿。

- [ ] **Step 5: 提交**

```bash
git add -A && git commit -m "T2: archive 操作——ops.archive_requirement（(None->ARCHIVED) + claim 同事务结束 release_reason=archive，abandon 模式）+ CLI kanban archive + REST POST /requirements/{id}/archive；harness k_archive（七状态矩阵/事件形态 Q3/claim 归属/channel 判别/再归档/404）"
```

---

## Task 3: delete 操作（ops + CLI 确认门 + REST DELETE + harness 原子性/并发/agent 面）

**Files:**
- Modify: `src/agent_kanban/services/operations.py`（`delete_preview` + `delete_requirement`，紧随 `archive_requirement`）
- Modify: `src/agent_kanban/api/requirements.py`（DELETE 端点）
- Modify: `cli.py`（`_cmd_delete` + parser 条目）
- Modify: `tests/ac_cases_k.py`（`k_delete`）
- Modify: `tests/run_ac.py`（注册 `k_delete`）

**Interfaces:**
- Produces: `ops.delete_requirement(session, *, requirement_id, actor_surface, actor_conn) -> {"requirement_id", "deleted": True}`（单事务五表删除，不写事件）；`ops.delete_preview(...)`（读：title/state/event_count，CLI 确认门用）；CLI `kanban delete --requirement-id <id> [--yes]`（确认门 y/N，EOF/拒绝中止非零退出）；REST `DELETE /requirements/{id}`（200 / 404 not_found / 503 db_busy）。

**Steps:**

- [ ] **Step 1: `tests/ac_cases_k.py` 追加 `k_delete`；`run_ac.py` 注册**

```python
def k_delete():
    print("== M1-4.3: delete 五表原子零残留 + REST 404/MCP not_found + agent 写 not_found + 确认门 + 写锁竞争 503")
    def _rich(db, title):
        """富需求：claim（已结束）+ 子任务 + 里程碑 + note 事件。"""
        rid = seed_req(db, title)
        m = MCP(db).start()
        m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
        m.call_ok("add_subtask", {"requirement_id": rid, "title": "st1", "ordinal": 1})
        m.call_ok("add_milestone", {"requirement_id": rid, "title": "ms1", "planned_at": "2026-12-31T00:00:00Z"})
        m.call_ok("add_record", {"requirement_id": rid, "kind": "note", "title": "n1"})
        m.close()
        cli_ok(db, "release", "--requirement-id", rid, "--reason", "test release")
        return rid

    # (i) CLI --yes：五表零残留（含需求行本身）
    db = new_db()
    rid = _rich(db, "k-del-rich")
    res = _run_cli(db, ["delete", "--requirement-id", rid, "--yes"])
    ok("k_delete(i): CLI delete --yes 退出 0", res.returncode == 0, f"rc={res.returncode} stderr={res.stderr[-200:]}")
    body = json.loads(res.stdout)
    ok("k_delete(i): 响应 deleted=true", body.get("deleted") is True, str(body))
    rows = {t: query(db, f"SELECT COUNT(*) AS n FROM {t} WHERE requirement_id=?", (rid,))[0]["n"]
            for t in ("events", "subtasks", "milestones", "claims")}
    req_n = query(db, "SELECT COUNT(*) AS n FROM requirements WHERE id=?", (rid,))[0]["n"]
    ok("k_delete(i): 五表零残留（需求行本身不存在，与 prune 语义区分，审 P2-7）",
       all(v == 0 for v in rows.values()) and req_n == 0, f"{rows} req={req_n}")
    # (ii) REST 200 -> 404 + MCP not_found + list_tasks 排除
    db2 = new_db()
    rid2 = _rich(db2, "k-del-rest")
    rest = REST(db2).start()
    try:
        m = MCP(db2).start()
        code, b = rest.req("GET", f"/requirements/{rid2}")
        ok("k_delete(ii): 删前 GET detail 200", code == 200, str(code))
        code, b = rest.req("DELETE", f"/requirements/{rid2}")
        ok("k_delete(ii): REST DELETE 200 deleted=true", code == 200 and b.get("deleted") is True, f"{code} {b}")
        code, b = rest.req("GET", f"/requirements/{rid2}")
        ok("k_delete(ii): 删后 GET detail -> 404 not_found", code == 404 and b["code"] == "not_found", f"{code} {b}")
        code2, _ = m.call_err("get_task_detail", {"requirement_id": rid2})
        ok("k_delete(ii): MCP get_task_detail -> not_found", code2 == "not_found", code2)
        ids = [t["requirement_id"] for t in m.call_ok("list_tasks", {})["tasks"]]
        ok("k_delete(ii): list_tasks 不含已删任务", rid2 not in ids, str(ids))
        # (iii) agent 写操作 -> 结构化 not_found（非崩溃/挂起，BCD S8）
        code3, _ = m.call_err("add_record", {"requirement_id": rid2, "kind": "note", "title": "x"})
        ok("k_delete(iii): agent add_record 已删任务 -> not_found", code3 == "not_found", code3)
        m.close()
    finally:
        rest.stop()
    # (iv) 确认门：n / EOF / y（+--yes 已在 (i) 覆盖）
    for label, text, expect_del in (("n", "n\n", False), ("EOF", "", False), ("y", "y\n", True)):
        db3 = new_db()
        rid3 = _rich(db3, f"k-del-{label}")
        res3 = _run_cli(db3, ["delete", "--requirement-id", rid3], input_text=text)
        req_n3 = query(db3, "SELECT COUNT(*) AS n FROM requirements WHERE id=?", (rid3,))[0]["n"]
        ok(f"k_delete(iv): stdin '{label}' -> {'已删+退出0' if expect_del else '不删+非零退出+无traceback'}",
           (req_n3 == 0) == expect_del and (res3.returncode == 0) == expect_del
           and "Traceback" not in res3.stderr and "Traceback" not in res3.stdout,
           f"rc={res3.returncode} req={req_n3}")
        if not expect_del:
            ok(f"k_delete(iv): stdin '{label}' -> aborted 消息（prune 确认门同口径）",
               "aborted: nothing deleted" in res3.stderr, res3.stderr[-200:])
    # (v) 写锁竞争 -> 503 db_busy（结构化，非 500）
    db4 = new_db()
    rid4 = _rich(db4, "k-del-busy")
    rest2 = REST(db4, extra={"AGENT_KANBAN_BUSY_TIMEOUT_MS": "50"}).start()
    holder = sqlite3.connect(str(db4))
    holder.execute("BEGIN IMMEDIATE")
    try:
        code, b = rest2.req("DELETE", f"/requirements/{rid4}")
        ok("k_delete(v): 写锁竞争 -> 503 db_busy", code == 503 and b["code"] == "db_busy", f"{code} {b}")
        ok("k_delete(v): 竞争失败未删", query(db4, "SELECT COUNT(*) AS n FROM requirements WHERE id=?", (rid4,))[0]["n"] == 1, "deleted?")
    finally:
        holder.rollback()
        holder.close()
        rest2.stop()
```

- [ ] **Step 2: 红跑**

Run: `uv run python tests/run_ac.py --only k_delete`
Expected: FAIL（CLI `delete` 不存在；REST DELETE 405）。

- [ ] **Step 3: 实现**

(1) `operations.py`，`archive_requirement` 之后插入：
```python
async def delete_preview(
    session: AsyncSession,
    *,
    requirement_id: str,
    actor_surface: str,
    actor_conn: str,
) -> dict:
    req = await require_requirement(session, requirement_id)
    count = await session.scalar(
        select(func.count()).select_from(Event).where(Event.requirement_id == requirement_id)
    )
    return {"requirement_id": requirement_id, "title": req.title, "state": req.state,
            "event_count": count or 0}


async def delete_requirement(
    session: AsyncSession,
    *,
    requirement_id: str,
    actor_surface: str,
    actor_conn: str,
) -> dict:
    await require_requirement(session, requirement_id)
    # FK 序：events（FK 指向 claims/subtasks/milestones）-> subtasks/milestones/claims -> requirement；
    # 不写事件（整链随属主消失，I2：链永不半断的推广形态）
    await session.execute(delete(Event).where(Event.requirement_id == requirement_id))
    await session.execute(delete(Subtask).where(Subtask.requirement_id == requirement_id))
    await session.execute(delete(Milestone).where(Milestone.requirement_id == requirement_id))
    await session.execute(delete(Claim).where(Claim.requirement_id == requirement_id))
    await session.execute(delete(Requirement).where(Requirement.id == requirement_id))
    return {"requirement_id": requirement_id, "deleted": True}
```

(2) `requirements.py` 加：
```python
@router.delete("/requirements/{requirement_id}")
async def delete_requirement(requirement_id: str) -> dict:
    return await _run("delete_requirement", requirement_id=requirement_id)
```

(3) `cli.py`：
- parser（`archive` parser 之后）：
```python
    p = sub.add_parser("delete", help="整需求硬删（全部子行原子删除、不写事件；--yes 跳过确认门）")
    p.add_argument("--requirement-id", required=True)
    p.add_argument("--yes", action="store_true", help="跳过确认门（非交互场景）")
    p.set_defaults(handler=_cmd_delete)
```
- handler（`_cmd_archive` 之后）：
```python
def _cmd_delete(args: argparse.Namespace) -> int:
    """整需求硬删（spec 4.3）：读 preview（title/state/事件数）-> 确认门（stdin y/N，
    EOF/拒绝/非 y 中止不删、非零退出，确认期间不持写事务；--yes 跳过）->
    delete_requirement 单事务原子删除（不写事件）。"""
    surface, conn = cli_actor()
    try:
        info = asyncio.run(run_op(
            get_session_factory(), ops.delete_preview, is_write=False,
            requirement_id=args.requirement_id, actor_surface=surface, actor_conn=conn,
        ))
        if not args.yes:
            sys.stdout.write(
                f"将硬删整个需求: {info['title']}（state={info['state']}，{info['event_count']} 条事件）。"
                f"删除不可逆，建议先 `kanban export` 留档。继续？[y/N] "
            )
            sys.stdout.flush()
            if sys.stdin.readline().strip().lower() != "y":
                print("aborted: nothing deleted", file=sys.stderr)
                return 1
        result = asyncio.run(run_op(
            get_session_factory(), ops.delete_requirement, is_write=True,
            requirement_id=args.requirement_id, actor_surface=surface, actor_conn=conn,
        ))
    except BusinessError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
```

- [ ] **Step 4: 绿跑 + 全量回归**

Run: `uv run python tests/run_ac.py --only k_delete` -> 全 PASS。
Run: `uv run python tests/run_ac.py` -> 全绿。

- [ ] **Step 5: 提交**

```bash
git add -A && git commit -m "T3: delete 操作——ops.delete_requirement（单事务五表 FK 序硬删、不写事件）+ delete_preview（确认门读）+ CLI kanban delete（y/N 确认门 + --yes，prune 先例）+ REST DELETE /requirements/{id}；harness k_delete（五表零残留/404+not_found/agent 写 not_found/确认门四路径/写锁 503）"
```

---

## Task 4: Web 壳（board 新建表单 + 3 tab + 卡片等待人提示 / detail 瘦身 + 生命周期操作 + 标题确认）

**Files:**
- Modify: `src/agent_kanban/api/web.py`（`_THEME`、`_JS_COMMON`、`board_shell`、`detail_shell`）
- Modify: `tests/ac_cases_k.py`（`k_web`）
- Modify: `tests/run_ac.py`（注册 `k_web`）

**Interfaces:**
- Produces: 壳契约——board 壳含 3 tab（`data-tab="active|done|archived"`）、新建表单（`#new-btn` + `#nf-title/#nf-desc/#nf-acc/#nf-jira`）、卡片等待人横幅含 `kanban approve <id>` 提示；detail 壳决策操作缺席（approve/release/renew/reopen/abandon/note/set_expectations 相关标记与函数全不在）、生命周期操作在场（`data-op='archive'` + `doDelete`）、等待人横幅含 kind 级 CLI 提示（"人面确认: kanban approve" / "解除阻塞: kanban approve"）。行为契约（JS，浏览器侧，harness 不执行 JS）：新建提交后主动 `loadBoard()`（不依赖 SSE，审 P1-2）；delete 标题不匹配拒绝。
- 现有壳契约保持：`board-root` / `detail-root` / `EventSource` / 零数据嵌入（`web` 用例回归零改动）。

**Steps:**

- [ ] **Step 1: `tests/ac_cases_k.py` 追加 `k_web`；`run_ac.py` 注册**

```python
def k_web():
    print("== M1-4.4: Web 壳契约——board 3 tab + 新建表单 + 卡片等待人提示 / 深潜决策按钮缺席 + 生命周期操作 + kind 级 CLI 提示")
    db = new_db()
    rid = seed_req(db, "k-web")
    secret = "K_WEB_SECRET_xyz"
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.call_ok("update_progress", {"requirement_id": rid, "note": secret})
    m.close()
    rest = REST(db, token="sekret").start()
    try:
        code, raw = rest.req("GET", "/", token="sekret")
        ok("k_web: board 壳 200 + board-root/EventSource（既有契约保持）",
           code == 200 and isinstance(raw, str) and 'id="board-root"' in raw and "EventSource" in raw, str(code))
        ok("k_web: board 3 tab（在板/已完成/已归档）",
           'data-tab="active"' in raw and 'data-tab="done"' in raw and 'data-tab="archived"' in raw, "tab 缺失")
        ok("k_web: 新建表单入口 + 字段锚",
           'id="new-btn"' in raw and 'id="nf-title"' in raw and 'id="nf-acc"' in raw and 'id="nf-jira"' in raw, "表单缺失")
        ok("k_web: 卡片等待人横幅含 CLI 提示（BCD F3 预防）", "kanban approve" in raw, "提示缺失")
        ok("k_web: board 壳无原始输出（既有契约保持）", secret not in raw, "shell leak")
        code, raw2 = rest.req("GET", f"/requirements/{rid}", token="sekret",
                              headers={"Accept": "text/html"})
        ok("k_web: 深潜壳 200 + detail-root（既有契约保持）",
           code == 200 and isinstance(raw2, str) and 'id="detail-root"' in raw2, str(code))
        for gone in ("data-op='approve'", "doRelease", "doReopen", "doAbandon", "doNote",
                     "doExpectations", "abandon-state", "note-input", "acc-input"):
            ok(f"k_web: 深潜壳决策操作缺席（{gone}）", gone not in raw2, "仍在壳内")
        ok("k_web: 生命周期操作在场（archive/delete）",
           "data-op='archive'" in raw2 and "doDelete" in raw2, "生命周期缺失")
        ok("k_web: 深潜等待人横幅 kind 级 CLI 提示",
           "人面确认: kanban approve" in raw2 and "解除阻塞: kanban approve" in raw2, "提示缺失")
        ok("k_web: 深潜壳无原始输出（既有契约保持）", secret not in raw2, "shell leak")
        # AC1 数据路径：Web 表单映射的 payload（一行一条 -> {item}）+ jira 映射（spec case 7）
        code, body = rest.req("POST", "/requirements", {"title": "k-create",
                                                        "acceptance": [{"item": "吞吐 >= 5000"}, {"item": "p99 < 200ms"}]})
        ok("k_web(AC1): 两行锚 create 201 OPEN", code == 201 and body["state"] == "OPEN", f"{code} {body}")
        ridc = body["requirement_id"]
        code, s = rest.req("GET", f"/requirements/{ridc}/summary")
        a_ids = [a["anchor_id"] for a in s["acceptance_table"]]
        ok("k_web(AC1): 锚自动编号 a1/a2（normalize_anchors）", a_ids == ["a1", "a2"], str(a_ids))
        code, body = rest.req("POST", "/requirements",
                              {"title": "k-create-jira", "source": "jira", "source_ref": "https://jira.example/X-1"})
        row_c = query(db, "SELECT source, source_ref FROM requirements WHERE id=?", (body["requirement_id"],))[0]
        ok("k_web(AC1): jira 链接 -> source=jira + source_ref 映射",
           row_c["source"] == "jira" and row_c["source_ref"] == "https://jira.example/X-1", str(dict(row_c)))
    finally:
        rest.stop()
```

- [ ] **Step 2: 红跑**

Run: `uv run python tests/run_ac.py --only k_web`
Expected: FAIL（3 tab / 表单 / 提示缺失；决策标记仍在；生命周期缺失）。

- [ ] **Step 3: 实现（web.py，七处）**

(1) `_THEME` 的 `.pill.CANCELLED{...}` 行之后加：
```
.pill.ARCHIVED{background:rgba(91,102,114,.25);color:var(--muted)}
```

(2) `_JS_COMMON` 的 STATE_ZH 改为：
```js
var STATE_ZH = {OPEN:"待认领", CLAIMED:"进行中", BLOCKED:"阻塞", REOPEN:"返工", DONE:"已完成", REJECTED:"已拒绝", CANCELLED:"已取消", ARCHIVED:"已归档"};
```

(3) `board_shell`：
- `<style>` 内（`.done-row .grow{flex:1}` 之后）加：
```
input{background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:7px;
  padding:6px 8px;font-size:.82rem}
#nf-msg.err{color:var(--red)}
#nf-msg.ok{color:var(--green)}
```
- topbar（line 136-140）改为（新建按钮 + 内联表单，不用 modal——spec 6.1）：
```html
<div class="topbar">
  <span class="title">agent-kanban</span>
  <span class="meta" id="top-count"></span>
  <button id="new-btn" style="margin-left:auto">新建</button>
  <div class="live" id="live"><div class="dot"></div><span>连接中</span></div>
</div>
<div id="new-form" style="display:none;padding:10px 20px 0;max-width:720px">
  <div style="display:flex;flex-direction:column;gap:6px">
    <input id="nf-title" placeholder="标题（必填）" style="width:100%;box-sizing:border-box">
    <textarea id="nf-desc" rows="2" placeholder="描述（可选）"></textarea>
    <textarea id="nf-acc" rows="3" placeholder="预期验收（可选，一行一条锚）"></textarea>
    <input id="nf-jira" placeholder="Jira 链接（可选，非空则 source=jira）" style="width:100%;box-sizing:border-box">
    <div style="display:flex;gap:8px;align-items:center">
      <button class="primary" onclick="submitNew()">创建</button>
      <button onclick="document.getElementById('new-form').style.display='none'">取消</button>
      <span id="nf-msg" style="font-size:.8rem"></span>
    </div>
  </div>
</div>
```
- tabs（line 141-144）加第三 tab：
```html
<button class="tab" data-tab="archived">已归档</button>
```
- `cardHTML` 的 wait 行（line 166）改为：
```js
  var wait = t.awaiting_human ? "<div class='wait'>等待人: " + esc(t.awaiting_human.reason || t.awaiting_human.kind || "")
    + " <span class='meta'>kanban approve " + esc(t.requirement_id) + "</span></div>" : "";
```
- `DONE_ZH`（line 188）加 ARCHIVED：
```js
var DONE_ZH = {DONE:"已完成", CANCELLED:"已取消", REJECTED:"已拒绝", ARCHIVED:"已归档"};
```
- `renderDone(tasks)` 参数化（label/empty 文案）：
```js
function renderDone(tasks, label, empty){
  tasks.sort(function(a, b){
    var fa = a.finished_at || "", fb = b.finished_at || "";
    return fa < fb ? 1 : (fa > fb ? -1 : 0);
  });
  var rows = tasks.map(function(t){
    var flag = t.reviewed ? "" : "<span class='badge attn'>无评审交接</span>";
    return "<a class='done-row' href='/requirements/" + encodeURIComponent(t.requirement_id) + "'>"
      + "<span class='pill " + esc(t.state) + "'>" + esc(DONE_ZH[t.state] || t.state) + "</span>"
      + "<span class='dt'>" + esc(t.title) + "</span><span class='grow'></span>"
      + "<span class='meta'>完成 " + (esc(fmtTs(t.finished_at)) || "-") + "</span>"
      + "<span class='meta'>决策 " + (t.decision_count || 0) + " · 偏离 " + (t.deviation_count || 0) + "</span>"
      + flag + "</a>";
  }).join("");
  document.getElementById("board-root").innerHTML = "<div class='done-list'>"
    + (rows || "<div class='empty'>" + empty + "</div>") + "</div>";
  document.getElementById("top-count").textContent = tasks.length + " " + label;
}
```
- `loadBoard` 的 else 分支改为（archived 单请求；done 三请求保持）：
```js
    } else {
      var sts = TAB === "archived" ? ["ARCHIVED"] : ["DONE", "CANCELLED", "REJECTED"];
      var resps = [];
      for (var i = 0; i < sts.length; i++) {
        resps.push(await fetch("/board?status=" + sts[i], {headers: hdr()}));
      }
      for (var j = 0; j < resps.length; j++) {
        if (!resps[j].ok) { fail("加载失败: " + resps[j].status); return; }
      }
      var all = [];
      for (var k = 0; k < resps.length; k++) {
        (await resps[k].json()).tasks.forEach(function(t){ all.push(t); });
      }
      if (TAB === "archived") renderDone(all, "个已归档", "（无已归档需求）");
      else renderDone(all, "个已完成", "（无已完成需求）");
    }
```
- `loadBoard()` 调用之前（tab 绑定代码之后）加新建表单 JS：
```js
document.getElementById("new-btn").onclick = function(){
  var f = document.getElementById("new-form");
  f.style.display = f.style.display === "none" ? "block" : "none";
};
function nfMsg(m, isErr){
  var el = document.getElementById("nf-msg");
  el.textContent = m; el.className = isErr ? "err" : "ok";
}
async function submitNew(){
  var title = document.getElementById("nf-title").value.trim();
  if (!title) { nfMsg("标题必填", true); return; }
  var body = {title: title};
  var desc = document.getElementById("nf-desc").value.trim();
  if (desc) body.description = desc;
  var acc = document.getElementById("nf-acc").value.split("\n")
    .map(function(s){ return s.trim(); }).filter(Boolean);
  if (acc.length) body.acceptance = acc.map(function(s){ return {item: s}; });
  var jira = document.getElementById("nf-jira").value.trim();
  if (jira) { body.source = "jira"; body.source_ref = jira; }
  var resp = await fetch("/requirements", {method: "POST",
    headers: Object.assign(hdr(), {"Content-Type": "application/json"}), body: JSON.stringify(body)});
  var txt = await resp.text(); var b = null;
  try { b = JSON.parse(txt); } catch (e) {}
  if (!resp.ok) { nfMsg("创建失败: " + (b && b.code ? b.code + ": " + (b.message || "") : txt), true); return; }
  ["nf-title", "nf-desc", "nf-acc", "nf-jira"].forEach(function(id){ document.getElementById(id).value = ""; });
  document.getElementById("new-form").style.display = "none";
  nfMsg("已创建", false);
  loadBoard();  // create 不写事件，SSE 无触发器——主动重拉（spec 4.1 / 审 P1-2）
}
```

(4) `detail_shell` docstring 改为：`人面操作 = task 生命周期（archive / delete 标题确认）；决策操作 CLI/REST-only（PRD §4.2 修订）；操作失败内联展示 body {code,message}。`

(5) `detail_shell` render() 内 wait-banner（line 335-336）改为：
```js
  if (s.awaiting_human) {
    var hint = s.awaiting_human.kind === "blocked" ? "解除阻塞: kanban approve " : "人面确认: kanban approve ";
    html += "<div class='wait-banner'>等待人决策: kind=" + esc(s.awaiting_human.kind)
      + " reason=" + esc(s.awaiting_human.reason || "")
      + " <span class='meta'>（" + hint + esc(s.requirement_id) + "）</span></div>";
  }
```

(6) 人面操作区（line 396-409 整块）替换为生命周期操作区（archive 与 delete 分行视觉分离，BCD F4；state=ARCHIVED 时 archive 禁用，spec 4.2）：
```js
  html += "<div class='sec wide'><h2>Task 生命周期</h2><div id='op-msg'></div>"
    + "<div class='ops'>"
    + "<button class='primary' data-op='archive'" + (s.state === "ARCHIVED" ? " disabled" : "") + ">archive</button>"
    + "</div>"
    + "<div class='op-row' style='margin-top:14px'>"
    + "<button onclick='doDelete()'>delete</button>"
    + "<span class='meta'>整需求硬删（不可逆，建议先 kanban export；输入标题确认）</span></div></div>";
```

(7) JS 函数区：
- `var _D = null;` 旁加 `var _S = null;`；render() 开头 `_D = d;` 后加 `_S = s;`
- load() 的失败分支（line 321）改为：
```js
    if (!dr.ok || !sr.ok) {
      var msg = dr.status === 404 ? "任务不存在（可能已被人删除）" : "加载失败: " + dr.status + " / " + sr.status;
      root.innerHTML = "<p class='meta'>" + msg + "</p>"; return;
    }
```
- 删除 `doRelease` / `doReopen` / `doAbandon` / `doNote` / `doExpectations` 五个函数（line 442-474 整段）；保留 `doOp`（archive 经 data-op 走 `POST /requirements/{id}/archive`）与 `handleOpResult` / `flash`；新增：
```js
async function doDelete(){
  if (!_S) return;
  var t = prompt("删除不可逆（建议先 kanban export）。当前状态: " + stateZh(_S.state)
    + "，事件 " + _D.events.length + " 条。输入任务标题确认删除:");
  if (t === null) return;
  if (t.trim() !== _S.title) { flash("标题不匹配，已取消删除", true); return; }
  var resp = await fetch("/requirements/" + encodeURIComponent(RID), {method: "DELETE", headers: hdr()});
  handleOpResult(resp);
}
```

- [ ] **Step 4: 绿跑 + 全量回归**

Run: `uv run python tests/run_ac.py --only k_web` -> 全 PASS。
Run: `uv run python tests/run_ac.py` -> 全绿（特别确认 `web`（既有壳契约用例）零回归——board-root/detail-root/EventSource/零原始输出断言不受影响）。

- [ ] **Step 5: 提交**

```bash
git add -A && git commit -m "T4: Web 壳——board 新建表单（一行一条锚/jira 映射）+ 已归档 tab + 卡片等待人 CLI 提示；detail 决策按钮全移除 + Task 生命周期区（archive 终态禁用 / delete 标题确认）+ kind 级 CLI 提示 + 404 友好文案；harness k_web（壳契约在场/缺席断言）"
```

---

## Task 5: 文档同步 + 残余登记 + prune 确认文案

**Files:**
- Modify: `cli.py`（prune 确认文案，line 188）
- Modify: `docs/PRD.md`（§0 定位语 + 职责边界行、§3.1、§3.4、§4.2、§6）
- Modify: `docs/design.md`（§0 旧措辞）
- Modify: `docs/web.md`（surface 行 + 人面操作节重写 + 冒烟第 4 条 + CLI 速查）
- Modify: `docs/adr/0000-known-gaps.md`（登记 R1/R3/R4）
- Modify: `README.md`（line 3 定位行）

**Interfaces:** 无代码行为变更（除 prune 确认文案，harness 无字面断言，已核实）。

**Steps:**

- [ ] **Step 1: `cli.py` prune 确认文案**

line 188：
```python
                f"将删除 {count} 条事件（终态需求级原子窗口：仅 DONE/REJECTED/CANCELLED "
```
改为：
```python
                f"将删除 {count} 条事件（终态需求级原子窗口：仅 DONE/REJECTED/CANCELLED/ARCHIVED "
```

- [ ] **Step 2: `docs/PRD.md` 五处**

(1) §0 定位语（line 7）：
```
定位: AI 时代的看板——不是任务状态跟踪，而是**大黑箱（AI 自动化执行）的关键节点暴露窗口 + 可回溯审计资产**
```
改为：
```
定位: AI 时代的看板——不是任务状态跟踪，而是**大黑箱（AI 自动化执行）的关键节点暴露窗口 + 可回溯审计资产 + AI 与人对称交换关键信息的场所**。看板不承担共识达成逻辑：子任务/里程碑共识在 AI 会话内（in-band）达成，看板只展现结果；决策记录两类来源——人在 AI 中做出的决策（agent 以 decision/note 事件记录，带 actor provenance）与 AI 自主的决策（decision 事件）
```

(2) §0 职责边界行（line 25）：
```
职责边界：看板是记录面 + 协作窗口，不是控制面。它不管理 worktree、不执行合入、不隔离执行。
```
改为：
```
职责边界：看板是记录面 + 关键决策的记录点/审计点，不是控制面，不是共识达成场所。它不管理 worktree、不执行合入、不隔离执行。人面 surface 划分：Web = 只读视图 + task 生命周期（create/archive/delete）；决策操作（approve/release/renew/reopen/note/abandon/set_expectations）= CLI/REST-only（Web 无入口）。
```

(3) §3.1 表格（line 96 行后）加：
```
| 任一 | ARCHIVED | 人 | 终态，无出边（无 unarchive）；转移时清除 awaiting_human；同事务结束未结束认领（release_reason=archive） |
```
并把 line 83 的 `OPEN -> CLAIMED -> DONE；侧向 BLOCKED / REJECTED / CANCELLED / REOPEN。` 改为 `OPEN -> CLAIMED -> DONE；侧向 BLOCKED / REJECTED / CANCELLED / REOPEN；终态 DONE / REJECTED / CANCELLED / ARCHIVED。`

(4) §3.4 approve 判定表（line 133）：
```
| OPEN/DONE/REOPEN/REJECTED/CANCELLED | 任意 | 拒绝 | 无 | 无 | illegal_state |
```
改为：
```
| OPEN/DONE/REOPEN/REJECTED/CANCELLED/ARCHIVED | 任意 | 拒绝 | 无 | 无 | illegal_state |
```

(5) §4.2：
- `abandon` 行后加两行：
```
- `archive`：归档（任一状态 -> ARCHIVED 终态，同事务结束未结束认领 release_reason=archive）；语义 = 移出活跃视野，**无工作判断**（区别于 abandon 的 REJECTED/CANCELLED）；无 unarchive。
- `delete`：整需求硬删（requirement + subtasks/milestones/claims/events 单事务原子，不写事件）；任意状态可删（含活跃认领）；不受数据保留窗口约束；删除后该需求的回溯承诺作废，建议先 `export` 留档（提示不强制）；Web 上需输入标题确认。
```
- `prune` 行（line 174）：`仅 DONE/REJECTED/CANCELLED 且全部事件早于窗口` 改为 `仅 DONE/REJECTED/CANCELLED/ARCHIVED 且全部事件早于窗口`。
- Web 窗口表（line 180-185）：`GET /` 行改为 `看板 HTML 壳：内联 JS fetch /board 渲染（在板/已完成/已归档 三 tab）+ 新建表单 + EventSource 重拉，无原始输出`；`GET /requirements/{id}` 行的 `（JS 渲染 + 人面操作）` 改为 `（JS 渲染 + task 生命周期操作 archive/delete；决策操作 CLI/REST-only）`。

(6) §6 数据保留行（line 258）：`仅 DONE/REJECTED/CANCELLED 且全部事件早于窗口的需求整删` 改为 `仅 DONE/REJECTED/CANCELLED/ARCHIVED 且全部事件早于窗口的需求整删`；并在该行"目标"单元格末尾（"导出文件为审计资产最终载体"之后）加：`；另有人面定点即时删除（4.2 delete）：任意状态、不强制导出、不受窗口约束、删需求行（prune 只删事件留需求行）`。

- [ ] **Step 3: `docs/design.md` §0**

line 11：
```
看板是**记录面 + 协作窗口**，不是控制面。
```
改为：
```
看板是**记录面 + 关键决策的记录点/审计点**，不是控制面，不是共识达成场所（定位修订 2026-10-26，spec: docs/superpowers/specs/2026-10-26-task-lifecycle-positioning-design.md）。
```

- [ ] **Step 4: `docs/web.md`**

(1) line 14 surface 行：`（JS 渲染 + 人面操作按钮）` 改为 `（JS 渲染 + task 生命周期操作 archive/delete；决策操作 CLI/REST-only）`。
(2) line 27 看板页描述末尾补：`顶部 tabs：在板 / 已完成（DONE/REJECTED/CANCELLED）/ 已归档（ARCHIVED）；顶栏「新建」按钮展开内联表单（title 必填 / description / acceptance 一行一条锚 / Jira 链接可选 -> source=jira）；等待人卡片含 CLI 提示（kanban approve <id>）。`
(3) line 29 深潜页描述末尾 `、人面操作区` 改为 `、Task 生命周期区（archive/delete）`。
(4) 「## 人面操作（深潜页按钮，全走既有 REST）」整节（line 31-42）替换为：
```
## 人面 surface（修订 2026-10-26）

**Web 深潜页 = Task 生命周期（全走 REST）**：

| 按钮 | 请求 | 备注 |
|---|---|---|
| archive | POST `/requirements/{id}/archive` | state=ARCHIVED 时按钮禁用 |
| delete | DELETE `/requirements/{id}` | prompt 输入任务标题确认；不可逆，提示先 export |

**决策操作 = CLI/REST-only（Web 无入口）**：approve / release(reason) / renew / reopen(--continue) / note(content) / abandon(to_state) / set_expectations——语义与端点不变（PRD §4.2），Web 壳已移除对应按钮。深潜页等待人横幅含静态 CLI 提示（kind=review -> 人面确认: kanban approve <id>；kind=blocked -> 解除阻塞: kanban approve <id>）。

操作结果：成功 -> 提示后 `load()` 重拉页面数据；失败 -> 内联展示响应体 `{code, message}`（如 `illegal_state: ...`、`not_found: ...`）。
```
(5) 冒烟 checklist 第 4 条（line 50）替换为：
```
4. 生命周期操作：新建表单提交（带/不带 acceptance 两行锚、带 Jira 链接）成功且看板重拉出现新任务；对 CLAIMED 需求 archive 成功（移入已归档 tab）；delete 输入错误标题被拒、正确标题删成功（页面转"任务不存在"）。
5. 等待人提示：对 awaiting_human 任务确认深潜页与卡片横幅显示 `kanban approve <id>` 提示（静态文字，非按钮）。
```
（原 5/6 条顺延为 6/7。）

- [ ] **Step 5: `docs/adr/0000-known-gaps.md` 登记残余**

表格尾（G11 之后）加三行：
```
| R1 | agent harness 对 delete 后 not_found 的处理在本仓之外（opencode 会话层）：可能误判系统故障重试/上报 | ② | 错误码语义（not_found 含 requirement id）+ README/docs 写明"任务被删除属人面操作结果"；harness k_delete 断言 agent 面 not_found；残余接受 | 2026-10-26 登记（task-lifecycle spec §13） |
| R3 | archive/abandon 语义区分靠使用纪律（人可能用 archive 替代 abandon 让任务消失），非结构强制 | ② | agent 面无 archive 工具（结构性半边）；PRD §0/§4.2 措辞 + UI 语义提示；人工定期观察 archive/abandon 比例（单用户规模不做自动化告警） | 2026-10-26 登记（BCD F1） |
| R4 | 决策操作移 CLI 后 awaiting 堆积风险（人习惯点按钮，发现无入口） | ② | 深潜页/卡片等待人横幅静态 CLI 提示 + web.md 人面 surface 速查；残余：习惯迁移靠使用 | 2026-10-26 登记（BCD F3） |
```

- [ ] **Step 6: `README.md` line 3 定位行**

```
AI 时代的看板：不是任务状态跟踪，而是**大黑箱（AI 自动化执行）的关键节点暴露窗口 + 可回溯审计资产**。
```
改为：
```
AI 时代的看板：不是任务状态跟踪，而是**大黑箱（AI 自动化执行）的关键节点暴露窗口 + 可回溯审计资产 + AI 与人对称交换关键信息的场所**（看板只记录/展现，不承载共识达成；人面 = Web 只读 + task 生命周期，决策操作 CLI/REST）。
```

- [ ] **Step 7: 全量回归 + 提交**

Run: `uv run python tests/run_ac.py` -> 全绿（prune 文案改动无断言影响，确认 `prune_confirm` 绿）。
```bash
git add -A && git commit -m "T5: 文档同步（PRD §0/§3.1/§3.4/§4.2/§6 定位与生命周期面、design.md §0 旧措辞、web.md surface 重写 + 冒烟清单、README 定位行）+ prune 确认文案补 ARCHIVED + known-gaps 登记 R1/R3/R4 残余"
```

---

## 收尾（全部任务后）

- [ ] 全量回归：`uv run python tests/run_ac.py` 全绿。
- [ ] 核对 spec §9 文档同步清单逐项打勾（PRD 五节 / design.md / web.md / known-gaps / README / prune 文案）。
- [ ] 核对 spec §2 非目标未被偷渡（无 unarchive / 无 subtask 编辑 / 无新事件 kind / MCP 12 工具不变 / 无回收站）。
- [ ] 向 user 汇报：测试结果 + 手工冒烟建议（web.md 冒烟 checklist 1-7 浏览器过一遍）+ MR 建议（分支 task-lifecycle -> main，user 裁决合入）。

</content>
</invoke>
