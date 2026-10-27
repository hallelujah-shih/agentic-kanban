# 实施计划：人确认闭环——delegated 受托面 + CLI 零输入

**Goal**: 人面（CLI/REST）6 个写事件操作（approve/release/release_all_stale/renew/note/reopen/abandon）加可选受托参数 -> `actor_surface=delegated` + 事件 `payload.delegated={kind,basis}`（单点派生配对）；CLI approve/release 支持零输入（省 --requirement-id，经 list_awaiting 宁拒不猜）。MCP 面/Web 面零改动，零 schema，零新错误码。

**Architecture**: `parse_delegation` 单点在 `identity.py`（str/dict 两路同函数，非法 -> invalid_record 带参数名+示例）；parse 统一在 handler 层首语句（fail-fast 先于任何 DB 操作），`_invoke`/`_run` 收已 parse 的 dict 并在同一调用点派生 surface+透传 delegated（配对结构耦合点）；op 级 payload merge（`transition` 既有 `event_payload` + `add_event` payload 就地加键，两者签名零改动）；零输入经既有 `list_awaiting` 客户端编排（服务端零新接口）。

**Tech Stack**: Python 3.14.4（worktree `.venv` 需自建：`uv venv .venv && uv pip install -e .`，a1a2 先例已实测该模式 import 指向 worktree src）/ FastAPI / SQLAlchemy 2.0 async / SQLite / 自研 AC harness（非 pytest，禁改 `tests/ac_lib.py`）。

**Spec**: `docs/superpowers/specs/2026-10-27-delegated-confirm-design.md`（v2.1，3 轮对抗审查 APPROVE + user 审阅通过；报告 `-design-review.md` 同目录）。
**BCD**: `docs/business-contracts/delegated-confirm.md`（v2.2，7 节齐）。
**分支/worktree**: `delegated-confirm`（`.worktree/delegated-confirm`，基于 main 5089bfe）。
**批次**: 板上任务 `bcd3a69074b641dba70a08afbce1ac05`（CLAIMED，main-loop）。

## 影响面（分级依据）

- ① 外部接口面：**在**。新 surface 值 `delegated`、CLI 新 flag `--on-behalf` + 零输入、REST 新可选 body（approve/renew 顶层 / 4 端点嵌套字段）、approve 无 body -> 非 conform body 422（登记行为变化）。
- ② 新入口/信任边界：**不在**（delegated 是派生值非入口；调用方不可直传 actor_surface）。
- ③ 热路径：**不在**（零输入仅 approve/release 省参时走一次既有读）。
- ④ 业务规则变化：**在**。delegated 派生规则＝新业务规则；SKILL.md 收尾协议（代执行）新增。
- 结论：**架构级 -> 全六门**（BCD 已完成；spec 3 轮审查共识 APPROVE + user 审阅通过）。

## 验证入口与 oracle（机械预检）

- 工作目录 = worktree 根 `/home/shih/test/AgenticKanban/.worktree/delegated-confirm`；一切 run 带 `TMPDIR=/home/shih/.tmp-ak-m16/delegated-confirm/tmp`（禁 /tmp）。
- **前置（T1 Step 0）**：worktree `.venv` 自建——`uv venv .venv && uv pip install -e .`（实钉版本以 `uv pip list` 为准；主仓记录 python 3.14.4 / mcp 2.3.0 / sqlalchemy 2.1.6）。
- tier-1（合并门槛基础）: `TMPDIR=/home/shih/.tmp-ak-m16/delegated-confirm/tmp .venv/bin/python -u tests/run_ac.py`；新用例单跑 `--only n_parse`（T1 后加 n1-n9,n10,n11,n28 / n19-n24,n26,n27 / n12-n18,n17b）。
- tier-0: `.venv/bin/python -m compileall -q src cli.py tests`。
- 基线: 全量 **624/624**（批首全跑复核一次，红则停）。计数单位＝`ok()` **断言数**：本批新增 68 断言（T1 10 + T2 30 + T3 12 + T4 16）-> 终态 **692/692**（以实际 run 值为准，出入记 ledger）。
- 最高 tier（收尾）: tier-1 全绿 + e2e `TMPDIR=... AK_E2E_DB=/home/shih/.tmp-ak-m16/delegated-confirm/ak-e2e.db npx playwright test`（基线 15/15，撞端口加 `E2E_PORT`）+ docker 双轨（默认轨 build + healthz 200；pypi 轨命令见 `docs/ops/ci-verification.md`）。
- harness 纪律: 断言引 spec/BCD；DB 事后 sqlite3 直查（`query`）；真实子进程（MCP stdio / uvicorn / CLI），禁 mock；**禁改 `tests/ac_lib.py`**（基座冻结——零输入用例用 case-local helper 钉 `stdin=DEVNULL`，`ac_cases_k.py:37-44 _run_cli` 同模式，R1 实证结论）。
- STALE 确定性造法（禁 sleep）：`MCP(db, extra={"AGENT_KANBAN_LEASE_SECONDS": "-1"})`（ac_cases_c.py:496 先例）。
- CLI 错误面契约：stderr 无 `Traceback`（ac_cases_k 先例断言）。

## 全局约束

- 单向门纯 additive：无受托参数路径逐字不变（payload 无 delegated 键、surface=cli/mcp/system 不变、错误码与消息形态不变）；`release --all-stale` 无 on-behalf 逐项 payload 逐字不变。
- MCP 面零改动：`mcp/server.py` 不碰；12 工具不加任何参数（agent 自身动作恒 surface=mcp，结构性门禁）。
- Web 面零改动：`api/web.py` 不碰（待决页推迟至 G3 后，裁决）。
- 零 schema 变更：models.py 表结构不碰（唯一改动＝:136 行尾注释加 delegated，T5）；payload 为既有 JSON 列。
- 错误码零新增：误用 -> `invalid_record` 新触发实例；`REST_ERROR_STATUS` 不碰（invalid_record 已映射 422）。
- 受托参数结构性缺席面：set_expectations / archive / delete / new / export / view / reconcile / prune —— CLI 不加 flag（argparse exit 2）、REST body 模型无字段（体被忽略）。
- parse 单点只在 `identity.py::parse_delegation`；`_invoke`/`_run` 收已 parse 的 dict（两面同构）；**parse 在 handler 首语句，先于任何 DB 操作**（fail-fast：0 待决板不吞非法 flag——R5）；CLI 非法输出＝`{code}: {message}` stderr + exit 1 + 无 Traceback（对齐 k 用例契约）。
- surface 值与 delegated 参数同一调用点同批落值（`_invoke`/`_run` 内 delegated is not None -> surface="delegated" + kwargs["delegated"]）——配对结构耦合点；无参时 kwargs 不含该键（op 调用逐字不变）。
- 零输入仅 approve/release：候选＝list_awaiting（awaiting_human 标记）；0 条＝`无待决项` exit 0 零写；恰 1＝携 32-hex 走既有写路径；多条＋非 tty＝stderr 列表（`<8hex> [STATE] <title>`）+`--requirement-id` 提示 exit 1 零写；多条＋tty＝stdout 列表＋`输入序号: `，非数字/越界/EOF＝`无效选择，未写入` exit 1 零写。release 零输入仍须 `--reason`，检查在 DB 读取**之前**（stderr `invalid_record: release requires a reason`）。
- 零输入用例（n19-n24）一律 case-local helper 钉 `stdin=subprocess.DEVNULL`（非 tty 确定性，本地终端跑套件不阻塞——R1）。
- n25（tty 编号选择）AC 不可测（spec §9 残余 1：不引 pty 注入，共享 ac_lib 改动面超本批档位）：P5 人工核验，规格见收尾清单。
- G11：本批动 cli.py -> 合入后（主仓）`uv sync --reinstall-package agent-kanban` 刷新入口快照。

## 审查重点（spec 暗示但测试最难守住、失败最伤人的 5 处）

1. **配对单边**（surface=delegated 但 payload.delegated 缺失/非法 -> 审计配对断裂，回溯失锚）：pin n1/n2/n4 逐事件双断言（state_change + 操作事件均带）+ n11 正向全表（delegated 行必含有效 payload）。
2. **本地终端跑合并门槛套件阻塞 tty 分支**（R1 实证：ac_lib.cli() 继承父进程 stdin，多条待决走 tty 分支阻塞 readline 30s 超时假红）：pin n19-n24 全部经 case-local DEVNULL helper（tty 分支 AC 不可达、确定性）+ T3 diff 锚（`tests/ac_lib.py` 零改动）。
3. **零输入猜**（多条候选静默取第 1 条执行 -> 写错目标且人以为只有一条）：pin n21（exit 1 零写 + 列表含两候选 + `[CLAIMED]`/`[BLOCKED]` state + `--requirement-id` 提示 + 无 Traceback）。
4. **非法 --on-behalf 被吞**（0 待决板 + 非法 flag -> 静默 exit 0，flag 从未被校验——R5）：pin n6-n8（0/1/2 三形态各拒：invalid_record + 示例 + 零写 + exit 1 + 无 Traceback）。
5. **反向配对过claim**（以 payload.delegated 为检索主键命中 add_record 自由 payload -> 审计误导，R3）：pin n10（mcp 写 surface=mcp + 自由 payload 含 delegated 键例外真实存在）+ n11 反向限定独占 kind {approval,release,renew,state_change}。

## 文件结构

| 文件 | 责任 | 任务 |
|---|---|---|
| `src/agent_kanban/services/identity.py` | `parse_delegation` 单点 + `DELEGATION_KINDS`/`DELEGATION_EXAMPLE` | T1 |
| `tests/ac_cases_n.py` | 新建：n_parse + n1-n28（T1-T4 分批追加） | T1-T4 |
| `tests/run_ac.py` | 注册新用例 | T1-T4 |
| `src/agent_kanban/services/operations.py` | 6 op 加 `delegated` 参数 + payload merge | T2 |
| `cli.py` | `_invoke` 收 dict + 6 handler 首语句 parse + argparse `--on-behalf` | T2 |
| `cli.py` | approve `--requirement-id` 改可选 + 零输入编排（`_zero_input_candidates`/`_pick_zero_input`） | T3 |
| `src/agent_kanban/api/requirements.py` | `DelegatedIn` + `_run` 收 dict + 6 端点 | T4 |
| `docs/PRD.md` | §4.2 两命令句 / §4.3:201 实例 / §5.1:217 枚举+派生 | T5 |
| `skills/agent-kanban/SKILL.md` | 「收尾协议（代执行）」节 | T5 |
| `AGENTS.md` | 人面 CLI 行 + 基线 592/592 -> 624/624（两处） | T5 |
| `src/agent_kanban/models.py:136` | 行尾注释加 delegated | T5 |

---

### Task T1: parse_delegation 单点（identity.py）

**Files:**
- Modify: `src/agent_kanban/services/identity.py`（文件尾追加）
- Create: `tests/ac_cases_n.py`（T1 部分：docstring + imports + n_parse）
- Modify: `tests/run_ac.py`（import + TESTS 注册）

**Interfaces:**
- Produces: `parse_delegation(raw: str | dict | None) -> dict | None`；模块常量 `DELEGATION_KINDS: tuple[str, ...]`、`DELEGATION_EXAMPLE: str`。非法 -> 抛 `BusinessError("invalid_record", <msg>)`，msg 含参数名 `delegated (CLI --on-behalf)` 与正确示例（agent 一次自纠）。T2 起 CLI/REST handler 均只调它。

- [ ] **Step 0: worktree .venv 自建（首次）**

```bash
cd /home/shih/test/AgenticKanban/.worktree/delegated-confirm
uv venv .venv && uv pip install -e .
.venv/bin/python -c "import agent_kanban, agent_kanban.services.identity as i; print(i.__file__)"
# 期望路径含 .worktree/delegated-confirm/src（import 指向 worktree src，非主仓）
```

- [ ] **Step 1: 建 `tests/ac_cases_n.py`（T1 部分）+ 注册 run_ac.py，跑红留档**

`tests/ac_cases_n.py`：

```python
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
```

`tests/run_ac.py`：import 行尾追加（ac_cases_m import 之后）：

```python
from ac_cases_n import n_parse
```

TESTS dict 末行 `"m_lease_return": m_lease_return, "m_lease_seq": m_lease_seq,` 之后加：

```python
    "n_parse": n_parse,
```

- [ ] **Step 2: 跑红留档**

```bash
cd /home/shih/test/AgenticKanban/.worktree/delegated-confirm
TMPDIR=/home/shih/.tmp-ak-m16/delegated-confirm/tmp .venv/bin/python tests/run_ac.py --only n_parse | tee /home/shih/.tmp-ak-m16/delegated-confirm/red-T1.log
# 期望: n_parse FAIL（exception: ImportError，parse_delegation 未定义）；日志留档
```

- [ ] **Step 3: identity.py 追加 parse_delegation（文件尾，rest_actor 之后）**

```python
DELEGATION_KINDS = ("statement", "action")
DELEGATION_EXAMPLE = "statement:user said PR merged in session"


def parse_delegation(raw: str | dict | None) -> dict | None:
    """受托参数单点校验（spec §2.1）：CLI 传 raw string（"kind:basis"），REST 传
    dict（{kind,basis}）。None -> None（无参现行为）。结构非法 -> invalid_record，
    消息含参数名（括注 CLI flag 供两面自纠）+ 正确示例（agent 一次自纠）。"""
    if raw is None:
        return None
    if isinstance(raw, str):
        if ":" not in raw:
            raise BusinessError(
                "invalid_record",
                f'delegated (CLI --on-behalf) must be "kind:basis" '
                f"(kind in statement|action), e.g. \"{DELEGATION_EXAMPLE}\"",
            )
        kind_raw, _, basis_raw = raw.partition(":")
    else:  # dict（REST：pydantic 已保证 kind/basis 为 str 或键缺失）
        kind_raw = raw.get("kind")
        basis_raw = raw.get("basis")
        if not isinstance(kind_raw, str) or not isinstance(basis_raw, str):
            raise BusinessError(
                "invalid_record",
                f'delegated (CLI --on-behalf) must be "kind:basis" '
                f"(kind in statement|action), e.g. \"{DELEGATION_EXAMPLE}\"",
            )
    kind = kind_raw.strip().lower()
    basis = basis_raw.strip()
    if kind not in DELEGATION_KINDS:
        raise BusinessError(
            "invalid_record",
            f'delegated kind must be statement|action, got "{kind_raw}", '
            f'e.g. "{DELEGATION_EXAMPLE}"',
        )
    if not basis:
        raise BusinessError(
            "invalid_record",
            f'delegated basis must be non-empty, e.g. "{DELEGATION_EXAMPLE}"',
        )
    return {"kind": kind, "basis": basis}
```

- [ ] **Step 4: 绿 + 全量回归 + 编译**

```bash
TMPDIR=/home/shih/.tmp-ak-m16/delegated-confirm/tmp .venv/bin/python tests/run_ac.py --only n_parse
# 期望: 10/10 PASS
TMPDIR=/home/shih/.tmp-ak-m16/delegated-confirm/tmp .venv/bin/python -u tests/run_ac.py | tail -3
# 期望: 634/634 PASS（624 基线 + 10）
.venv/bin/python -m compileall -q src cli.py tests
```

- [ ] **Step 5: diff 自检 + 提交**

```bash
git diff --stat   # 仅 3 文件：identity.py / ac_cases_n.py / run_ac.py
git add src/agent_kanban/services/identity.py tests/ac_cases_n.py tests/run_ac.py
git commit -m "T1: parse_delegation 受托参数单点校验（invalid_record 带参数名+示例）"
```

---

### Task T2: delegated 受托面（CLI + 6 op）

**Files:**
- Modify: `src/agent_kanban/services/operations.py`（6 op 签名 + payload merge）
- Modify: `cli.py`（`_invoke` 收 dict、6 handler 首语句 parse、argparse `--on-behalf` ×6）
- Test: `tests/ac_cases_n.py`（追加 n1-n9、n10、n11、n28）
- Modify: `tests/run_ac.py`（注册）

**Interfaces:**
- Consumes: `parse_delegation`（T1）。
- Produces: 6 op（approve/release/release_all_stale/renew/note/reopen/abandon）签名尾部加 `delegated: dict | None = None`（keyword，默认 None，无参调用逐字不变）；`_invoke(op_name, *, is_write=True, delegated=None, **kwargs)`；6 命令 `--on-behalf "<kind:basis>"`。T3 零输入与 T4 REST 依赖此形态。

- [ ] **Step 1: 追加 n1-n9、n10、n11、n28 用例 + 注册，跑红留档**

`tests/ac_cases_n.py` 追加（n_parse 之后）：

（事件断言一律用 `query` 返回的原始行：state_change 事件需同时拿 kind 与 payload，payload 里 to 状态键名是 `"to"`。）

```python
def _ev_rows(db: Path, rid: str):
    return query(db, "SELECT kind, actor_surface, actor_conn, payload FROM events WHERE requirement_id=?", (rid,))


def _pl(r):
    return json.loads(r["payload"]) if r["payload"] else {}


def n1():
    """delegated approve（CLAIMED->DONE 两条事件均带 payload.delegated）。"""
    db = new_db()
    rid = seed_req(db, "delegated approve")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.close()
    res = cli_ok(db, "approve", "--requirement-id", rid, "--on-behalf", "statement:测试表态")
    ok("n1: approve --on-behalf exit0 + DONE", res.get("state") == "DONE", str(res))
    rows = _ev_rows(db, rid)
    ap = [r for r in rows if r["kind"] == "approval"]
    want = {"kind": "statement", "basis": "测试表态"}
    ok("n1: approval 事件 delegated+cli+payload",
       len(ap) == 1 and ap[0]["actor_surface"] == "delegated" and ap[0]["actor_conn"] == "cli"
       and _pl(ap[0]).get("delegated") == want and _pl(ap[0]).get("state") == "DONE", str([dict(x) for x in ap]))
    sc = [r for r in rows if r["kind"] == "state_change" and _pl(r).get("to") == "DONE"]
    ok("n1: state_change(CLAIMED->DONE) delegated+payload",
       len(sc) == 1 and sc[0]["actor_surface"] == "delegated" and _pl(sc[0]).get("delegated") == want,
       str([dict(x) for x in sc]))


def n2():
    db = new_db()
    rid = seed_req(db, "delegated release")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.close()
    res = cli_ok(db, "release", "--requirement-id", rid, "--reason", "x",
                 "--on-behalf", "action:PR merged (abc123)")
    ok("n2: release --on-behalf OPEN", res.get("state") == "OPEN", str(res))
    rows = _ev_rows(db, rid)
    rel = [r for r in rows if r["kind"] == "release"]
    want = {"kind": "action", "basis": "PR merged (abc123)"}
    ok("n2: release 事件 delegated(action)+reason",
       len(rel) == 1 and rel[0]["actor_surface"] == "delegated" and _pl(rel[0]).get("delegated") == want
       and _pl(rel[0]).get("reason") == "x", str([dict(x) for x in rel]))
    sc = [r for r in rows if r["kind"] == "state_change" and _pl(r).get("to") == "OPEN"]
    ok("n2: state_change(CLAIMED->OPEN) delegated",
       len(sc) == 1 and sc[0]["actor_surface"] == "delegated" and _pl(sc[0]).get("delegated") == want,
       str([dict(x) for x in sc]))
    row = query(db, "SELECT release_reason FROM claims WHERE requirement_id=?", (rid,))[0]
    ok("n2: release_reason 不变", row["release_reason"] == "x", str(dict(row)))


def n3():
    db = new_db()
    rid = seed_req(db, "delegated note/renew")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.close()
    cli_ok(db, "note", "--requirement-id", rid, "--content", "note 内容", "--on-behalf", "statement:user 指示")
    r1 = query(db, "SELECT actor_surface, payload FROM events WHERE kind='note' AND requirement_id=?", (rid,))[0]
    ok("n3: note 事件 delegated + content 共存",
       r1["actor_surface"] == "delegated" and json.loads(r1["payload"]) == {
           "content": "note 内容", "delegated": {"kind": "statement", "basis": "user 指示"}}, str(dict(r1)))
    cli_ok(db, "renew", "--requirement-id", rid, "--on-behalf", "action:user 工作面操作")
    r2 = query(db, "SELECT actor_surface, payload FROM events WHERE kind='renew' AND requirement_id=?", (rid,))[0]
    ok("n3: renew 事件 delegated（新增 payload）",
       r2["actor_surface"] == "delegated" and json.loads(r2["payload"]) == {
           "delegated": {"kind": "action", "basis": "user 工作面操作"}}, str(dict(r2)))


def n4():
    db = new_db()
    rid = seed_req(db, "delegated reopen/abandon")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.call_ok("request_review", {"requirement_id": rid, "evidence": {"test_summary": "s"}, "summary_line": "交接"})
    m.close()
    cli_ok(db, "approve", "--requirement-id", rid)  # CLAIMED->DONE（无受托）
    cli_ok(db, "reopen", "--requirement-id", rid, "--on-behalf", "statement:user 说重做")
    sc1 = [r for r in _ev_rows(db, rid) if r["kind"] == "state_change" and _pl(r).get("to") == "REOPEN"]
    ok("n4: reopen state_change delegated",
       len(sc1) == 1 and sc1[0]["actor_surface"] == "delegated"
       and _pl(sc1[0]).get("delegated") == {"kind": "statement", "basis": "user 说重做"}, str([dict(x) for x in sc1]))
    cli_ok(db, "abandon", "--requirement-id", rid, "--to-state", "REJECTED", "--on-behalf", "statement:user 拒绝")
    sc2 = [r for r in _ev_rows(db, rid) if r["kind"] == "state_change" and _pl(r).get("to") == "REJECTED"]
    ok("n4: abandon state_change delegated",
       len(sc2) == 1 and sc2[0]["actor_surface"] == "delegated"
       and _pl(sc2[0]).get("delegated") == {"kind": "statement", "basis": "user 拒绝"}, str([dict(x) for x in sc2]))


def n5():
    db = new_db()
    ms = MCP(db, extra={"AGENT_KANBAN_LEASE_SECONDS": "-1"}).start()  # STALE 确定性（ac_cases_c 先例）
    stale = []
    for i in range(2):
        r = seed_req(db, f"stale-delegated-{i}")
        ms.call_ok("claim_task", {"requirement_id": r, "agent_name": "s"})
        stale.append(r)
    ms.close()
    res = cli_ok(db, "release", "--all-stale", "--on-behalf", "action:批量代执行")
    ok("n5: 2 STALE 全 ok（部分失败语义不变）",
       len(res["released"]) == 2 and all(x["ok"] for x in res["released"]), str(res))
    for r in stale:
        row = query(db, "SELECT actor_surface, payload FROM events WHERE kind='release' AND requirement_id=?", (r,))[0]
        ok(f"n5[{r[:8]}]: release 事件 delegated(action)",
           row["actor_surface"] == "delegated"
           and json.loads(row["payload"]).get("delegated") == {"kind": "action", "basis": "批量代执行"},
           str(dict(row)))


def _bad_flag_case(flag: str, label: str):
    """n6-n8 共用：0/1/2 待决三形态下非法 flag 均先拒（parse 先于读候选，R5）。
    断言用 DELEGATION_EXAMPLE（spec §2.1 三种非法消息均含该示例；kind/basis 形态
    消息逐字为 'delegated kind must be ...' / 'delegated basis must be ...'，
    不含 on-behalf 字样，勿按它断言）。"""
    from agent_kanban.services.identity import DELEGATION_EXAMPLE
    for n in (0, 1, 2):
        db = new_db()
        _mk_awaiting(db, n)
        before = query(db, "SELECT COUNT(*) AS n FROM events")[0]["n"]
        res = cli(db, "approve", "--on-behalf", flag)
        after = query(db, "SELECT COUNT(*) AS n FROM events")[0]["n"]
        ok(f"{label}[{n}待决]: {flag!r} -> invalid_record 零写 exit1 无Traceback",
           res.returncode == 1 and res.stderr.strip().startswith("invalid_record")
           and DELEGATION_EXAMPLE in res.stderr and "Traceback" not in res.stderr
           and before == after,
           f"rc={res.returncode} stderr={res.stderr[:200]}")


def n6():
    _bad_flag_case("foo", "n6")  # 无冒号


def n7():
    _bad_flag_case("badkind:x", "n7")  # kind 越枚举


def n8():
    _bad_flag_case("statement:", "n8")  # basis 空


def n9():
    db = new_db()
    rid = seed_req(db, "regress no-flag")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.close()
    cli_ok(db, "approve", "--requirement-id", rid)  # 无 --on-behalf
    row = query(db, "SELECT actor_surface, payload FROM events WHERE kind='approval' AND requirement_id=?", (rid,))[0]
    p = json.loads(row["payload"])
    ok("n9: 无 on-behalf 回归 surface=cli + payload 逐字 {state:DONE}",
       row["actor_surface"] == "cli" and p == {"state": "DONE"}, str(dict(row)))


def n10():
    """MCP 结构性门禁：12 工具 schema 无受托字段 + mcp 写恒 surface=mcp。"""
    db = new_db()
    m = MCP(db).start()
    tools = m.rpc("tools/list", {}).get("tools", [])
    ok("n10: 12 工具", len(tools) == 12, str(len(tools)))
    bad = [t["name"] for t in tools if "delegated" in json.dumps(t.get("inputSchema", {}))
           or "on_behalf" in json.dumps(t.get("inputSchema", {}))]
    ok("n10: inputSchema 无 on_behalf/delegated 字段", not bad, str(bad))
    rid = seed_req(db, "mcp gate")
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.call_ok("add_record", {"requirement_id": rid, "kind": "note", "title": "委托讨论",
                             "payload": {"delegated": {"kind": "statement", "basis": "讨论引用"}}})
    m.close()
    row = query(db, "SELECT actor_surface, payload FROM events WHERE kind='note' AND requirement_id=?", (rid,))[0]
    ok("n10: mcp 写 surface=mcp；add_record 自由 payload 例外真实存在（R3 登记）",
       row["actor_surface"] == "mcp" and json.loads(row["payload"]).get("delegated") is not None, str(dict(row)))


def n11():
    """配对不变量：正向全表 + 反向限定独占 kind（spec §2.3，R3 收窄）。"""
    REVERSE_KINDS = ("approval", "release", "renew", "state_change")
    db = new_db()
    m = MCP(db).start()
    r1 = seed_req(db, "pair delegated")
    m.call_ok("claim_task", {"requirement_id": r1, "agent_name": "a"})
    m.close()
    cli_ok(db, "approve", "--requirement-id", r1, "--on-behalf", "statement:pair 表态")
    r2 = seed_req(db, "pair plain")
    m2 = MCP(db).start()
    m2.call_ok("claim_task", {"requirement_id": r2, "agent_name": "b"})
    m2.close()
    cli_ok(db, "approve", "--requirement-id", r2)
    r3 = seed_req(db, "pair mcp free payload")
    m3 = MCP(db).start()
    m3.call_ok("claim_task", {"requirement_id": r3, "agent_name": "c"})
    m3.call_ok("add_record", {"requirement_id": r3, "kind": "note", "title": "委托讨论",
                              "payload": {"delegated": {"kind": "statement", "basis": "x"}}})
    m3.close()
    rows = query(db, "SELECT kind, actor_surface, payload FROM events")

    def valid_d(r):
        d = (json.loads(r["payload"]) if r["payload"] else {}).get("delegated")
        return isinstance(d, dict) and d.get("kind") in ("statement", "action") \
            and bool(str(d.get("basis", "")).strip())

    fwd = [dict(r) for r in rows if r["actor_surface"] == "delegated" and not valid_d(r)]
    ok("n11: 正向全表（delegated -> 有效 payload.delegated）", not fwd, str(fwd))
    rev = [dict(r) for r in rows if r["kind"] in REVERSE_KINDS
           and bool((json.loads(r["payload"]) if r["payload"] else {}).get("delegated"))
           and r["actor_surface"] != "delegated"]
    ok("n11: 反向（独占 kind 含 delegated 键 -> surface=delegated；kind=note 共享不在限定内）",
       not rev, str(rev))


def n28():
    """受托参数结构性缺席面（CLI：argparse exit 2）。"""
    db = new_db()
    rid = seed_req(db, "structural gate")
    res1 = cli(db, "delete", "--requirement-id", rid, "--on-behalf", "x")
    ok("n28: delete --on-behalf -> exit2 unrecognized arguments",
       res1.returncode == 2 and "unrecognized arguments" in res1.stderr,
       f"rc={res1.returncode} stderr={res1.stderr[:200]}")
    res2 = cli(db, "set_expectations", "--requirement-id", rid, "--acceptance", "[]",
               "--on-behalf", "x")
    ok("n28: set_expectations --on-behalf -> exit2（D1 结构性缺席）",
       res2.returncode == 2 and "unrecognized arguments" in res2.stderr,
       f"rc={res2.returncode} stderr={res2.stderr[:200]}")
```

`tests/run_ac.py`：import 行 `from ac_cases_n import n_parse` 改为：

```python
from ac_cases_n import (n1, n10, n11, n2, n28, n3, n4, n5, n6, n7, n8, n9, n_parse)
```

TESTS dict `"n_parse": n_parse,` 之后加：

```python
    "n1": n1, "n2": n2, "n3": n3, "n4": n4, "n5": n5, "n6": n6, "n7": n7, "n8": n8,
    "n9": n9, "n10": n10, "n11": n11, "n28": n28,
```

- [ ] **Step 2: 跑红留档**

```bash
TMPDIR=/home/shih/.tmp-ak-m16/delegated-confirm/tmp .venv/bin/python tests/run_ac.py \
  --only n1,n2,n3,n4,n5,n6,n7,n8,n9,n28 | tee /home/shih/.tmp-ak-m16/delegated-confirm/red-T2.log
# 期望: n1-n8 FAIL（unrecognized arguments: --on-behalf，rc=2）；n9/n10/n11/n28 PASS
# （变更前即成立的锚：n9 无 flag 回归 / n10 MCP 结构门禁 / n11 配对空表 /
# n28 argparse 已拒）；日志留档
```

- [ ] **Step 3: operations.py 6 op 加 delegated 参数 + payload merge**

签名（6 处同形，`now: datetime | None = None,` 行尾后插入 `delegated: dict | None = None,`）：

- `approve`（:158-165）/ `release`（:193-201）/ `release_all_stale`（:227-233）/ `renew`（:268-275）/ `note`（:300-308）/ `reopen`（:321-329）/ `abandon`（:348-356）——**共 7 个 op 函数**（release_all_stale 在 6 个人面操作内）。

payload merge（逐点）：

1. `approve` CLAIMED 分支 transition（:171-174）加尾参 `event_payload={"delegated": delegated} if delegated else None,`；同分支 add_event（:178-182）`payload={"state": "DONE"}` 改 `payload={"state": "DONE", **({"delegated": delegated} if delegated else {})}`。
2. `approve` BLOCKED 分支 transition（:185-188）加尾参 `event_payload={"delegated": delegated} if delegated else None,`。
3. `release` transition（:212-215）加尾参 event_payload 同形；add_event（:219-223）`payload={"reason": reason, "agent_name": claim.agent_name}` 改 `payload={"reason": reason, "agent_name": claim.agent_name, **({"delegated": delegated} if delegated else {})}`。
4. `release_all_stale` 循环内 transition（:250-253）加尾参 event_payload 同形；add_event（:257-261）`payload={"reason": "stale", "agent_name": claim.agent_name}` 改 `payload={"reason": "stale", "agent_name": claim.agent_name, **({"delegated": delegated} if delegated else {})}`。
5. `renew` add_event（:292-296）加参 `payload={"delegated": delegated} if delegated else None,`（现无 payload 参数）。
6. `note` add_event（:313-317）`payload={"content": content}` 改 `payload={"content": content, **({"delegated": delegated} if delegated else {})}`。
7. `reopen` continue_ 分支 transition（:336-339）与 DONE->REOPEN transition（:341-344）各加尾参 event_payload 同形。
8. `abandon` REJECTED transition（:365-368）与 CANCELLED transition（:372-375）各加尾参 event_payload 同形。

（行号仅供定位；每点先 `grep -c` 核 oldString 全文件唯一再改。`add_event`/`transition` 签名零改动。）

- [ ] **Step 4: cli.py（_invoke 收 dict + 6 handler 首语句 parse + argparse）**

import（:19）改：

```python
from agent_kanban.services.identity import cli_actor, parse_delegation
```

`_invoke`（:22-35）改：

```python
def _invoke(op_name: str, *, is_write: bool = True, delegated: dict | None = None,
            **kwargs: object) -> int:
    surface, conn = cli_actor()
    if delegated is not None:
        surface = "delegated"
        kwargs["delegated"] = delegated
    try:
        result = asyncio.run(
            run_op(
                get_session_factory(), getattr(ops, op_name), is_write=is_write,
                actor_surface=surface, actor_conn=conn, **kwargs,
            )
        )
    except BusinessError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
```

6 handler（parse 首语句，fail-fast 先于任何 DB 操作——R5；T3 会再扩 approve/release，本步先给无零输入形态）：

```python
def _cmd_approve(args: argparse.Namespace) -> int:
    try:
        delegated = parse_delegation(args.on_behalf)
    except BusinessError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1
    return _invoke("approve", requirement_id=args.requirement_id, delegated=delegated)


def _cmd_release(args: argparse.Namespace) -> int:
    try:
        delegated = parse_delegation(args.on_behalf)
    except BusinessError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1
    if args.all_stale:
        return _invoke("release_all_stale", delegated=delegated)
    return _invoke("release", requirement_id=args.requirement_id, reason=args.reason,
                   delegated=delegated)


def _cmd_renew(args: argparse.Namespace) -> int:
    try:
        delegated = parse_delegation(args.on_behalf)
    except BusinessError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1
    return _invoke("renew", requirement_id=args.requirement_id, delegated=delegated)


def _cmd_note(args: argparse.Namespace) -> int:
    try:
        delegated = parse_delegation(args.on_behalf)
    except BusinessError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1
    return _invoke("note", requirement_id=args.requirement_id, content=args.content,
                   delegated=delegated)


def _cmd_abandon(args: argparse.Namespace) -> int:
    try:
        delegated = parse_delegation(args.on_behalf)
    except BusinessError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1
    return _invoke("abandon", requirement_id=args.requirement_id, to_state=args.to_state,
                   delegated=delegated)


def _cmd_reopen(args: argparse.Namespace) -> int:
    try:
        delegated = parse_delegation(args.on_behalf)
    except BusinessError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1
    return _invoke("reopen", requirement_id=args.requirement_id, continue_=args.continue_,
                   delegated=delegated)
```

argparse（6 个子 parser 各加一行，加在该 parser 既有 add_argument 之后、`set_defaults` 之前；**set_expectations/archive/delete/new/export/view/reconcile/prune 不加**——结构性缺席，n28 锚）：

```python
    p.add_argument("--on-behalf", metavar='"kind:basis"',
                   help="受托代执行（kind: statement|action，basis 一行指向依据）")
```

涉及：approve（:279-281）、release（:283-287）、renew（:289-291）、note（:293-296）、abandon（:298-301）、reopen（:312-315）。

- [ ] **Step 5: 绿 + 全量回归 + 编译**

```bash
TMPDIR=/home/shih/.tmp-ak-m16/delegated-confirm/tmp .venv/bin/python tests/run_ac.py \
  --only n1,n2,n3,n4,n5,n6,n7,n8,n9,n10,n11,n28
# 期望: 30/30 PASS
TMPDIR=/home/shih/.tmp-ak-m16/delegated-confirm/tmp .venv/bin/python -u tests/run_ac.py | tail -3
# 期望: 664/664 PASS（634 + 30）
.venv/bin/python -m compileall -q src cli.py tests
```

- [ ] **Step 6: diff 自检 + 提交**

```bash
git diff --stat   # 仅 4 文件：operations.py / cli.py / ac_cases_n.py / run_ac.py
git diff src/agent_kanban/mcp/server.py   # 期望空（MCP 零改动锚）
git diff src/agent_kanban/api/web.py      # 期望空（Web 零改动锚）
git add src/agent_kanban/services/operations.py cli.py tests/ac_cases_n.py tests/run_ac.py
git commit -m "T2: delegated 受托面——6 op 写事件落 payload.delegated + CLI --on-behalf（handler 首语句 parse，surface 单点派生）"
```

---

### Task T3: CLI 零输入（approve/release 省 --requirement-id）

**Files:**
- Modify: `cli.py`（approve parser `--requirement-id` 改可选；`_zero_input_candidates` / `_print_awaiting_list` / `_pick_zero_input` 新增；`_cmd_approve` / `_cmd_release` 扩零输入分支）
- Test: `tests/ac_cases_n.py`（追加 `_run_cli_nul` + n19-n24、n26、n27）
- Modify: `tests/run_ac.py`（注册）

**Interfaces:**
- Consumes: T2 的 `_cmd_approve`/`_cmd_release`（parse 首语句已就位）+ 既有 `ops.list_awaiting`（operations.py:936，外层 `{"awaiting": [...]}`，条目含 requirement_id 32-hex / title / state / awaiting_human / waiting_seconds / claim，updated_at 序）。
- Produces: 零输入行为契约（spec §3.2：0 条 `无待决项` exit 0；恰 1 直执；多条非 tty stderr 列表拒；多条 tty 编号选，无效 `无效选择，未写入`；release 零输入 reason fail-fast 于 DB 读取前）。T5 契约同步引用。
- Excludes: n25（tty 编号选择/越界）AC 测不到（spec §9 残余 1）——本任务不写其 AC 用例；人工核验规格在收尾清单。

- [ ] **Step 1: 追加零输入用例 + 注册，跑红留档**

`tests/ac_cases_n.py` 追加：

```python
def _run_cli_nul(db: Path, args: list[str]) -> subprocess.CompletedProcess:
    """CLI 子进程钉 stdin=DEVNULL（零输入非 tty 确定性，R1；ac_cases_k._run_cli 同模式）。"""
    return subprocess.run(
        [str(VENV_PY), str(CLI), *args],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
        env=env_for(db), cwd=str(REPO_ROOT), timeout=TIMEOUT,
    )


def n19():
    db = new_db()
    res = _run_cli_nul(db, ["approve"])
    ok("n19: 0 待决 -> exit0 + 无待决项 + 零写",
       res.returncode == 0 and "无待决项" in res.stdout
       and query(db, "SELECT COUNT(*) AS n FROM events")[0]["n"] == 0,
       f"rc={res.returncode} stdout={res.stdout[:100]}")


def n20():
    db = new_db()
    [rid] = _mk_awaiting(db, 1)
    res = _run_cli_nul(db, ["approve"])
    ok("n20: 恰1 -> 直执 DONE", res.returncode == 0
       and json.loads(res.stdout).get("state") == "DONE",
       f"rc={res.returncode} stdout={res.stdout[:200]}")
    row = query(db, "SELECT actor_surface FROM events WHERE kind='approval'")[0]
    ok("n20: 无 on-behalf -> surface=cli（等价显式 id）", row["actor_surface"] == "cli", str(dict(row)))


def n21():
    db = new_db()
    m = MCP(db).start()
    r1 = seed_req(db, "z21-blocked")
    m.call_ok("claim_task", {"requirement_id": r1, "agent_name": "a"})
    m.call_ok("mark_blocked", {"requirement_id": r1, "reason": "等人裁决"})
    m.close()
    m2 = MCP(db).start()
    r2 = seed_req(db, "z21-claimed")
    m2.call_ok("claim_task", {"requirement_id": r2, "agent_name": "b"})
    m2.call_ok("request_review",
               {"requirement_id": r2, "evidence": {"test_summary": "s"}, "summary_line": "交接"})
    m2.close()
    before = query(db, "SELECT COUNT(*) AS n FROM events")[0]["n"]
    res = _run_cli_nul(db, ["approve"])
    after = query(db, "SELECT COUNT(*) AS n FROM events")[0]["n"]
    ok("n21: 多条非tty -> exit1 拒绝零写", res.returncode == 1 and before == after,
       f"rc={res.returncode} stderr={res.stderr[:300]}")
    ok("n21: 列表含两候选 + [STATE] + --requirement-id 提示 + 无Traceback",
       r1[:8] in res.stderr and "[BLOCKED]" in res.stderr
       and r2[:8] in res.stderr and "[CLAIMED]" in res.stderr
       and "--requirement-id" in res.stderr and "Traceback" not in res.stderr,
       res.stderr[:400])


def n22():
    db = new_db()
    _mk_awaiting(db, 1)
    before = query(db, "SELECT COUNT(*) AS n FROM events")[0]["n"]
    res = _run_cli_nul(db, ["release"])
    after = query(db, "SELECT COUNT(*) AS n FROM events")[0]["n"]
    ok("n22: 零输入 release 无 --reason -> invalid_record 零写（DB 读取前 fail-fast）",
       res.returncode == 1 and "release requires a reason" in res.stderr and before == after,
       f"rc={res.returncode} stderr={res.stderr[:200]}")


def n23():
    db = new_db()
    [rid] = _mk_awaiting(db, 1)
    res = _run_cli_nul(db, ["release", "--reason", "方向不对"])
    ok("n23: 零输入 release --reason -> OPEN",
       res.returncode == 0 and json.loads(res.stdout).get("state") == "OPEN",
       f"rc={res.returncode} stdout={res.stdout[:200]}")
    row = query(db, "SELECT release_reason FROM claims WHERE requirement_id=?", (rid,))[0]
    ok("n23: release_reason 落值", row["release_reason"] == "方向不对", str(dict(row)))


def n24():
    """零输入 + 受托组合（agent 主流程）。"""
    db = new_db()
    _mk_awaiting(db, 1)
    res = _run_cli_nul(db, ["approve", "--on-behalf", "statement:user 表态收尾"])
    ok("n24: 零输入+受托 -> DONE", res.returncode == 0
       and json.loads(res.stdout).get("state") == "DONE",
       f"rc={res.returncode} stdout={res.stdout[:200]}")
    row = query(db, "SELECT actor_surface, payload FROM events WHERE kind='approval'")[0]
    ok("n24: approval 事件 delegated+basis",
       row["actor_surface"] == "delegated"
       and json.loads(row["payload"]).get("delegated") == {"kind": "statement", "basis": "user 表态收尾"},
       str(dict(row)))


def n26():
    db = new_db()
    [rid] = _mk_awaiting(db, 1)
    _run_cli_nul(db, ["approve", "--on-behalf", "statement:展示面"])
    res = cli(db, "view", "detail", "--requirement-id", rid)  # 文本渲染，非 JSON
    ok("n26: view detail 事件行 by delegated:cli（既有通用渲染透传，零改动）",
       res.returncode == 0 and "by delegated:cli" in res.stdout, res.stdout[-500:])


def n27():
    db = new_db()
    [rid] = _mk_awaiting(db, 1)
    _run_cli_nul(db, ["approve", "--on-behalf", "action:export 面"])
    res = cli_ok(db, "export", "--format", "json")
    reqs = [q for q in res["requirements"] if q["requirement_id"] == rid]
    evs = [e for e in reqs[0]["events"] if e["kind"] == "approval"]
    ok("n27: export json approval 行 actor_surface=delegated + payload.delegated",
       len(evs) == 1 and evs[0]["actor_surface"] == "delegated"
       and evs[0]["payload"].get("delegated") == {"kind": "action", "basis": "export 面"},
       str(evs))
```

`tests/run_ac.py`：import 行追加 `n19, n20, n21, n22, n23, n24, n26, n27`（同 import 行合并）；TESTS dict 加：

```python
    "n19": n19, "n20": n20, "n21": n21, "n22": n22, "n23": n23, "n24": n24,
    "n26": n26, "n27": n27,
```

- [ ] **Step 2: 跑红留档**

```bash
TMPDIR=/home/shih/.tmp-ak-m16/delegated-confirm/tmp .venv/bin/python tests/run_ac.py \
  --only n19,n20,n21,n22,n23,n24,n26,n27 | tee /home/shih/.tmp-ak-m16/delegated-confirm/red-T3.log
# 期望: n19/n20/n22/n23/n24 FAIL（approve 无参 -> argparse "the following arguments are
# required: --requirement-id" rc=2；n21 同样 rc=2 非 1；n26/n27 因零输入不可达连带 FAIL）
```

- [ ] **Step 3: cli.py 零输入编排**

argparse approve parser（:279-281）：`p.add_argument("--requirement-id", required=True)` 改 `p.add_argument("--requirement-id")`（release parser 的 `--requirement-id` 现已可选，不动）。

`_build_parser` 之前（`main` 之前）新增 3 个 helper：

```python
def _zero_input_candidates() -> list[dict] | None:
    """零输入候选读（spec §3.2）：list_awaiting（awaiting_human 标记，板唯一等待面；
    operations.py:936 既有读路径，is_write=False）。失败已按 _invoke 形态输出 -> None。"""
    surface, conn = cli_actor()
    try:
        result = asyncio.run(
            run_op(
                get_session_factory(), ops.list_awaiting, is_write=False,
                actor_surface=surface, actor_conn=conn,
            )
        )
    except BusinessError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return None
    return result.get("awaiting") or []


def _print_awaiting_list(cands: list[dict], *, file) -> None:
    print("多条待决项，请用 --requirement-id 指定目标:", file=file)
    for i, c in enumerate(cands, 1):
        print(f"  {i}. {c['requirement_id'][:8]} [{c['state']}] {c['title']}", file=file)


def _pick_zero_input(cands: list[dict]) -> str | None:
    """多条候选分支（宁拒不猜，BCD 强 5）：非 tty -> stderr 列表拒；tty -> 编号选择
    （非数字/越界/EOF -> 拒）。拒绝返回 None。行含 state（BLOCKED 被 approve 是解阻
    而非 DONE，列表必须可区分——R6）。"""
    if not sys.stdin.isatty():
        _print_awaiting_list(cands, file=sys.stderr)
        return None
    _print_awaiting_list(cands, file=sys.stdout)
    sys.stdout.write("输入序号: ")
    sys.stdout.flush()
    line = sys.stdin.readline()
    try:
        idx = int(line.strip())
    except ValueError:
        print("无效选择，未写入", file=sys.stderr)
        return None
    if not (1 <= idx <= len(cands)):
        print("无效选择，未写入", file=sys.stderr)
        return None
    return cands[idx - 1]["requirement_id"]
```

`_cmd_approve` 改为（T2 的 parse 首语句保留，其后插零输入分支）：

```python
def _cmd_approve(args: argparse.Namespace) -> int:
    try:
        delegated = parse_delegation(args.on_behalf)
    except BusinessError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1
    if args.requirement_id is None:
        cands = _zero_input_candidates()
        if cands is None:
            return 1
        if not cands:
            print("无待决项")
            return 0
        if len(cands) == 1:
            args.requirement_id = cands[0]["requirement_id"]
        else:
            rid = _pick_zero_input(cands)
            if rid is None:
                return 1
            args.requirement_id = rid
    return _invoke("approve", requirement_id=args.requirement_id, delegated=delegated)
```

`_cmd_release` 改为（reason fail-fast 在 DB 读取**之前**，spec §3.2 第 3 条）：

```python
def _cmd_release(args: argparse.Namespace) -> int:
    try:
        delegated = parse_delegation(args.on_behalf)
    except BusinessError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1
    if args.all_stale:
        return _invoke("release_all_stale", delegated=delegated)
    if args.requirement_id is None:
        if not args.reason or not str(args.reason).strip():
            print("invalid_record: release requires a reason", file=sys.stderr)
            return 1
        cands = _zero_input_candidates()
        if cands is None:
            return 1
        if not cands:
            print("无待决项")
            return 0
        if len(cands) == 1:
            args.requirement_id = cands[0]["requirement_id"]
        else:
            rid = _pick_zero_input(cands)
            if rid is None:
                return 1
            args.requirement_id = rid
    return _invoke("release", requirement_id=args.requirement_id, reason=args.reason,
                   delegated=delegated)
```

（显式 --requirement-id + 无 reason 的既有 op 层校验路径不变——零输入分支不触碰它。）

- [ ] **Step 4: 绿 + 全量回归 + 编译**

```bash
TMPDIR=/home/shih/.tmp-ak-m16/delegated-confirm/tmp .venv/bin/python tests/run_ac.py \
  --only n19,n20,n21,n22,n23,n24,n26,n27
# 期望: 12/12 PASS
TMPDIR=/home/shih/.tmp-ak-m16/delegated-confirm/tmp .venv/bin/python -u tests/run_ac.py | tail -3
# 期望: 676/676 PASS（664 + 12）
.venv/bin/python -m compileall -q src cli.py tests
```

- [ ] **Step 5: diff 自检 + 提交**

```bash
git diff --stat   # 仅 3 文件：cli.py / ac_cases_n.py / run_ac.py
git diff tests/ac_lib.py   # 期望空（基座冻结锚，R1 修法的边界）
git add cli.py tests/ac_cases_n.py tests/run_ac.py
git commit -m "T3: CLI 零输入——approve/release 省 --requirement-id（list_awaiting 宁拒不猜；release reason 先于 DB 读取 fail-fast；候选行含 state）"
```

---

### Task T4: REST delegated（DelegatedIn + 6 端点）

**Files:**
- Modify: `src/agent_kanban/api/requirements.py`（`DelegatedIn` 模型 + `ReleaseIn`/`NoteIn`/`AbandonIn`/`ReopenIn` 加嵌套可选字段 + `_run` 收 dict + approve/renew 加顶层 body + 6 端点 handler parse）
- Test: `tests/ac_cases_n.py`（追加 n12-n18、n17b）
- Modify: `tests/run_ac.py`（注册）

**Interfaces:**
- Consumes: `parse_delegation`（T1；REST 传 dict）；T2 的 6 op `delegated` 参数。
- Produces: `DelegatedIn(BaseModel){kind: str, basis: str}`；approve/renew body 整体即顶层 `{kind,basis}`（无 wrapper）；release/note/abandon/reopen 既有 body 加嵌套可选 `delegated`；set_expectations/archive/delete body 无字段（结构门禁）。非法 -> `invalid_record` -> 422（既有映射）；非 conform 非 body 200 -> 422（登记行为变化）。

- [ ] **Step 1: 追加 n12-n18、n17b 用例 + 注册，跑红留档**

`tests/ac_cases_n.py` 追加：

```python
def n12():
    db = new_db()
    rid = seed_req(db, "rest approve")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.close()
    rest = REST(db).start()
    try:
        code, body = rest.req("POST", f"/requirements/{rid}/approve",
                              body={"kind": "statement", "basis": "user 会话原话"})
        ok("n12: 顶层 body -> 200", code == 200, f"{code} {body}")
    finally:
        rest.stop()
    row = query(db, "SELECT actor_surface, actor_conn, payload FROM events WHERE kind='approval' AND requirement_id=?", (rid,))[0]
    ok("n12: delegated + rest: 前缀 + payload 落值",
       row["actor_surface"] == "delegated" and str(row["actor_conn"]).startswith("rest:")
       and json.loads(row["payload"]).get("delegated") == {"kind": "statement", "basis": "user 会话原话"},
       str(dict(row)))


def n13():
    db = new_db()
    rid = seed_req(db, "rest regress")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.close()
    rest = REST(db).start()
    try:
        code, body = rest.req("POST", f"/requirements/{rid}/approve")
        ok("n13: 无 body -> 200（回归）", code == 200, f"{code} {body}")
    finally:
        rest.stop()
    row = query(db, "SELECT actor_surface, payload FROM events WHERE kind='approval' AND requirement_id=?", (rid,))[0]
    ok("n13: surface=cli + payload 无 delegated",
       row["actor_surface"] == "cli" and "delegated" not in json.loads(row["payload"]), str(dict(row)))


def n14():
    db = new_db()
    rid = seed_req(db, "rest release")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.close()
    rest = REST(db).start()
    try:
        code, body = rest.req("POST", f"/requirements/{rid}/release",
                              body={"reason": "方向不对",
                                    "delegated": {"kind": "action", "basis": "user 自行关闭 PR"}})
        ok("n14: 嵌套 delegated -> 200 OPEN", code == 200 and body.get("state") == "OPEN", f"{code} {body}")
    finally:
        rest.stop()
    row = query(db, "SELECT actor_surface, payload FROM events WHERE kind='release' AND requirement_id=?", (rid,))[0]
    ok("n14: release 事件 delegated",
       row["actor_surface"] == "delegated"
       and json.loads(row["payload"]).get("delegated") == {"kind": "action", "basis": "user 自行关闭 PR"},
       str(dict(row)))


def n15():
    db = new_db()
    rid = seed_req(db, "rest note")
    rest = REST(db).start()
    try:
        code, body = rest.req("POST", f"/requirements/{rid}/note",
                              body={"content": "REST 更正",
                                    "delegated": {"kind": "statement", "basis": "user 指正"}})
        ok("n15: 嵌套 delegated -> 200", code == 200, f"{code} {body}")
    finally:
        rest.stop()
    row = query(db, "SELECT actor_surface, payload FROM events WHERE kind='note' AND requirement_id=?", (rid,))[0]
    ok("n15: note 事件 delegated + content 共存",
       row["actor_surface"] == "delegated" and json.loads(row["payload"]) == {
           "content": "REST 更正", "delegated": {"kind": "statement", "basis": "user 指正"}}, str(dict(row)))


def n16():
    db = new_db()
    rid = seed_req(db, "rest reopen")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.call_ok("request_review", {"requirement_id": rid, "evidence": {"test_summary": "s"}, "summary_line": "交接"})
    m.close()
    cli_ok(db, "approve", "--requirement-id", rid)  # -> DONE
    rest = REST(db).start()
    try:
        code, body = rest.req("POST", f"/requirements/{rid}/reopen",
                              body={"delegated": {"kind": "statement", "basis": "user 要重做"}})
        ok("n16: reopen 嵌套 delegated -> 200 REOPEN",
           code == 200 and body.get("state") == "REOPEN", f"{code} {body}")
    finally:
        rest.stop()
    sc = [r for r in query(db, "SELECT actor_surface, payload FROM events WHERE kind='state_change' AND requirement_id=?", (rid,))
          if json.loads(r["payload"]).get("to") == "REOPEN"]
    ok("n16: state_change->REOPEN delegated",
       len(sc) == 1 and sc[0]["actor_surface"] == "delegated"
       and json.loads(sc[0]["payload"]).get("delegated") == {"kind": "statement", "basis": "user 要重做"},
       str([dict(x) for x in sc]))


def n17():
    db = new_db()
    rid = seed_req(db, "rest invalid kind")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.close()
    before = query(db, "SELECT COUNT(*) AS n FROM events WHERE requirement_id=?", (rid,))[0]["n"]
    rest = REST(db).start()
    try:
        code, body = rest.req("POST", f"/requirements/{rid}/approve",
                              body={"kind": "foo", "basis": "x"})
        ok("n17: kind 越枚举 -> 422 invalid_record",
           code == 422 and (isinstance(body, dict) and body.get("code") == "invalid_record"), f"{code} {body}")
    finally:
        rest.stop()
    after = query(db, "SELECT COUNT(*) AS n FROM events WHERE requirement_id=?", (rid,))[0]["n"]
    ok("n17: 零写", before == after, f"{before} -> {after}")


def n17b():
    db = new_db()
    rid = seed_req(db, "rest nonconform body")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    m.close()
    before = query(db, "SELECT COUNT(*) AS n FROM events WHERE requirement_id=?", (rid,))[0]["n"]
    rest = REST(db).start()
    try:
        code, body = rest.req("POST", f"/requirements/{rid}/approve", body={"foo": 1})
        ok("n17b: 非 conform body -> 422（登记行为变化，R4）", code == 422, f"{code} {body}")
    finally:
        rest.stop()
    after = query(db, "SELECT COUNT(*) AS n FROM events WHERE requirement_id=?", (rid,))[0]["n"]
    ok("n17b: 零写", before == after, f"{before} -> {after}")


def n18():
    db = new_db()
    rid = seed_req(db, "rest structural gate")
    rest = REST(db).start()
    try:
        code, body = rest.req("POST", f"/requirements/{rid}/archive",
                              body={"delegated": {"kind": "statement", "basis": "x"}})
        ok("n18: archive 携 delegated 体 -> 200（体被忽略）", code == 200, f"{code} {body}")
    finally:
        rest.stop()
    row = query(db, "SELECT actor_surface, payload FROM events WHERE kind='state_change' AND requirement_id=?", (rid,))[0]
    ok("n18: state_change surface=cli + payload 无 delegated（结构门禁）",
       row["actor_surface"] == "cli" and "delegated" not in json.loads(row["payload"]), str(dict(row)))
```

`tests/run_ac.py`：import 行追加 `n12, n13, n14, n15, n16, n17, n17b, n18`；TESTS dict 加：

```python
    "n12": n12, "n13": n13, "n14": n14, "n15": n15, "n16": n16,
    "n17": n17, "n17b": n17b, "n18": n18,
```

- [ ] **Step 2: 跑红留档**

```bash
TMPDIR=/home/shih/.tmp-ak-m16/delegated-confirm/tmp .venv/bin/python tests/run_ac.py \
  --only n12,n14,n15,n16,n17,n17b | tee /home/shih/.tmp-ak-m16/delegated-confirm/red-T4.log
# 期望: n12/n14/n15/n16 FAIL（body 被忽略 -> surface=cli）；n17/n17b FAIL（现 200 非 422）；
# n13/n18 可能 PASS（回归/结构锚）
```

- [ ] **Step 3: api/requirements.py（模型 + _run + 6 端点）**

import（:25）改：`from ..services.identity import rest_actor, parse_delegation`

模型区（`AbandonIn` 之后、`ReopenIn` 之前或之后均可，保持字母序不强制）：

```python
class DelegatedIn(BaseModel):
    kind: str
    basis: str
```

`ReleaseIn` / `NoteIn` / `AbandonIn` / `ReopenIn` 各加一行（`ReopenIn` 保留 `continue_` 行）：

```python
    delegated: DelegatedIn | None = None
```

`_run`（:66-71）改（与 cli `_invoke` 同构）：

```python
async def _run(op_name: str, *, is_write: bool = True, delegated: dict | None = None,
               **kwargs: Any) -> Any:
    surface, conn = rest_actor()
    if delegated is not None:
        surface = "delegated"
        kwargs["delegated"] = delegated
    return await run_op(
        get_session_factory(), getattr(ops, op_name), is_write=is_write,
        actor_surface=surface, actor_conn=conn, **kwargs,
    )
```

6 端点（parse 在端点函数首语句；approve/renew 顶层 body 形态——body 存在即受托意图，无 wrapper；release/note/abandon/reopen 嵌套字段形态；两形态分写，spec §2.2/§4）：

```python
@router.post("/requirements/{requirement_id}/approve")
async def approve(requirement_id: str, body: DelegatedIn | None = None) -> dict:
    delegated = parse_delegation(body.model_dump() if body else None)
    return await _run("approve", requirement_id=requirement_id, delegated=delegated)


@router.post("/requirements/{requirement_id}/release")
async def release(requirement_id: str, body: ReleaseIn) -> dict:
    delegated = parse_delegation(body.delegated.model_dump() if body.delegated else None)
    return await _run("release", requirement_id=requirement_id, reason=body.reason,
                      delegated=delegated)


@router.post("/requirements/{requirement_id}/renew")
async def renew(requirement_id: str, body: DelegatedIn | None = None) -> dict:
    delegated = parse_delegation(body.model_dump() if body else None)
    return await _run("renew", requirement_id=requirement_id, delegated=delegated)


@router.post("/requirements/{requirement_id}/note")
async def note(requirement_id: str, body: NoteIn) -> dict:
    delegated = parse_delegation(body.delegated.model_dump() if body.delegated else None)
    return await _run("note", requirement_id=requirement_id, content=body.content,
                      delegated=delegated)


@router.post("/requirements/{requirement_id}/abandon")
async def abandon(requirement_id: str, body: AbandonIn) -> dict:
    delegated = parse_delegation(body.delegated.model_dump() if body.delegated else None)
    return await _run("abandon", requirement_id=requirement_id, to_state=body.to_state,
                      delegated=delegated)


@router.post("/requirements/{requirement_id}/reopen")
async def reopen(requirement_id: str, body: ReopenIn | None = None) -> dict:
    body = body or ReopenIn()
    delegated = parse_delegation(body.delegated.model_dump() if body.delegated else None)
    return await _run("reopen", requirement_id=requirement_id, continue_=body.continue_,
                      delegated=delegated)
```

（`set_expectations` / `archive` / `delete` 端点零改动——body 模型无 delegated 字段，体被 FastAPI 忽略，n18 锚。）

- [ ] **Step 4: 绿 + 全量回归 + 编译**

```bash
TMPDIR=/home/shih/.tmp-ak-m16/delegated-confirm/tmp .venv/bin/python tests/run_ac.py \
  --only n12,n13,n14,n15,n16,n17,n17b,n18
# 期望: 16/16 PASS
TMPDIR=/home/shih/.tmp-ak-m16/delegated-confirm/tmp .venv/bin/python -u tests/run_ac.py | tail -3
# 期望: 692/692 PASS（676 + 16）
.venv/bin/python -m compileall -q src cli.py tests
```

- [ ] **Step 5: diff 自检 + 提交**

```bash
git diff --stat   # 仅 3 文件：api/requirements.py / ac_cases_n.py / run_ac.py
git diff src/agent_kanban/api/main.py   # 期望空（REST_ERROR_STATUS 零改动锚）
git add src/agent_kanban/api/requirements.py tests/ac_cases_n.py tests/run_ac.py
git commit -m "T4: REST delegated——DelegatedIn + 6 端点（approve/renew 顶层 body / 4 端点嵌套字段；非 conform body 422 登记）"
```

---

### Task T5: 契约同步 + 全量回归收尾

**Files:**
- Modify: `docs/PRD.md`（§4.2 approve 句 / release 句 / §4.3 :201 实例清单 / §5.1 :217 枚举+派生规则，共 4 处）
- Modify: `skills/agent-kanban/SKILL.md`（「交接与等待」节后新增「收尾协议（代执行）」节）
- Modify: `AGENTS.md`（人面 CLI 行补零输入+on-behalf；基线 592/592 -> 624/624 两处）
- Modify: `src/agent_kanban/models.py:136`（行尾注释加 delegated）
- 无新测试（契约面＝静态检查 + 全量回归）

**Interfaces:**
- Consumes: T1-T4 全部落地行为（契约文字描述的行为均已 AC 锚定）。
- Produces: 契约文档与实现一致（下批/人面读者的唯一事实源）。

- [ ] **Step 1: PRD 4 处**

1. `§4.2` approve 句（:175，现文以「（同事务）。」结尾）句尾追加：

```
 `--on-behalf "<kind>:<basis>"` 受托代执行（kind ∈ statement|action，basis 一行指向依据；surface 服务端派生为 delegated，派生规则见 5.1）。`--requirement-id` 可省（零输入）：awaiting_human 恰 1 条直接执行 / 0 条提示「无待决项」零写 / 多条非交互通道拒绝（列候选含状态 + 提示携 --requirement-id；tty 编号列选，无效选择零写）；`--on-behalf` 结构非法 -> invalid_record（先于候选读取拒绝）。
```

2. `§4.2` release 句（:176，「非全有全无）。」结尾）句尾追加：

```
 `--on-behalf` 与 `--requirement-id` 可省语义同 approve；零输入仍须 `--reason`（语义字段不免输，先于候选读取拒绝）。
```

3. `§4.3`（:201）invalid_record 实例清单：`title 或 reason 为空）` 改 `title 或 reason 为空 / delegated 结构非法（字符串形缺冒号 / kind 越 statement|action 枚举 / basis 空））`。（「每码唯一触发条件」纪律保持：实例清单只增。）

4. `§5.1`（:217）：`actor_surface`（`mcp`/`cli`/`system`）改（`mcp`/`cli`/`system`/`delegated`）；同句尾（「不接受调用方传入。」）后追加新句：

```
`delegated`＝人面上代执行：人面入口（CLI `--on-behalf` / REST 受托 body）+ 结构有效受托参数 -> 服务端派生落此值，且该命令写出的每条事件必带 `payload.delegated={kind,basis}`（单点派生，配对；MCP `add_record` 自由 payload 可含同名键为登记例外，审计检索代执行面主键＝`actor_surface=delegated`）。delegated 的源必须是已发生的人的决定（statement＝人会话表态 / action＝人工作面动作中 agent 结构性做不了的），agent 只翻译不产生；MCP 面无受托参数入口，恒 mcp。
```

- [ ] **Step 2: SKILL.md「收尾协议（代执行）」节**

`skills/agent-kanban/SKILL.md`「交接与等待」节末（「**永不声称 DONE**」行之后、「## 错误码速查」之前）插入：

```markdown
## 收尾协议（代执行）

- **触发（pull）**：agent 侧工作完成后（PR 流＝PR 发起后 / 本地合流＝合入后），人表态（「合了」「收尾吧」）或 agent 检测到人工作面动作完成 -> 会话内 `list_awaiting` 查等待面，有待决任务即代执行收尾。
- **kind 判据**：`statement`＝人会话表态（basis 指向可引用的真实原话）；`action`＝人工作面动作且 agent 结构性做不了（如远端 PR merge：git fetch 后确认目标 commit 在 origin main）。**本地仓检测不算**——本地 ff 折入 / 分支合并是 agent 自己的动作，标 action 即自我认证（显式反例）。
- **执行**：`cli.py approve --requirement-id <id> --on-behalf "<kind>:<basis>"`（release 同，携 `--reason`）。受托痕在事件自身（payload.delegated），**不再要求前置 note**。
- **禁**：agent 自产决定（编造 statement basis / 把自己动作标 action）。终态/确认迁移的源必须是已发生的人的决定。
```

- [ ] **Step 3: AGENTS.md 2 处 + models.py 注释**

1. `AGENTS.md`「任务与看板操作面」人面 CLI 条：`（flag 式参数，非位置参数）。` 改 `（flag 式参数，非位置参数；approve/release 可省 --requirement-id＝零输入，agent 代执行携 `--on-behalf "<kind>:<basis>"`，判据见 SKILL.md 收尾协议）。`
2. `AGENTS.md`「验证入口与 tier 阶梯」：`基线 **592/592**`（tier 2 行）与 `全量 592/592`（tier 5 最高 tier 行）均改 **624/624**（批 2 合入后未同步的存量漂移，v1 审查 N4）。
3. `src/agent_kanban/models.py:136`：`# mcp | cli | system` 改 `# mcp | cli | system | delegated`（纯注释，surface 枚举唯一代码内清单）。

- [ ] **Step 4: 复读 + 全量回归 + e2e + docker 双轨**

```bash
# 非代码资产检查清单（AGENTS.md 仓适配事实）：docs 改动复读变更节 + 核对交叉引用目标存在
# （PRD 4 处复读；SKILL.md 新节复读；AGENTS.md 2 处复读；models.py 行复读）
TMPDIR=/home/shih/.tmp-ak-m16/delegated-confirm/tmp .venv/bin/python -u tests/run_ac.py | tail -3
# 期望: 692/692 PASS（若 T1-T4 实际断言数与本计划 68 有出入，以实际为准并回填本节）
TMPDIR=/home/shih/.tmp-ak-m16/delegated-confirm/tmp AK_E2E_DB=/home/shih/.tmp-ak-m16/delegated-confirm/ak-e2e.db npx playwright test
# 期望: 15/15 PASS（Web 面零改动回归；sqlite disk I/O error 先查 /tmp quota＝环境面）
# docker 双轨（默认轨）：
TMPDIR=/home/shih/.tmp-ak-m16/delegated-confirm/tmp docker compose up -d --build kanban && curl -sf localhost:<port>/healthz
# 期望: build 成功 + healthz 200（端口以 docker-compose.yml 为准）；pypi 轨命令见 docs/ops/ci-verification.md
```

- [ ] **Step 5: 提交**

```bash
git add docs/PRD.md skills/agent-kanban/SKILL.md AGENTS.md src/agent_kanban/models.py
git commit -m "T5: 契约同步——PRD 4 处（§4.2 两命令句/§4.3 实例/§5.1 枚举+派生）+ SKILL.md 收尾协议（代执行）+ AGENTS.md 人面 CLI 行/基线 624 + models.py surface 注释"
```

---

## 收尾（T5 提交后）

- [ ] n25 人工核验（spec §9 残余 1）：临时 DB 造 2 条 awaiting，真终端跑 `cli.py approve`：(a) 输入非数字 `abc` -> stderr 拒绝零写；(b) 输入越界序号 99 -> 拒绝零写；(c) 再跑一次输入 1 -> 执行第 1 条。核验记录入批次 ledger。

- [ ] 最高 tier 全链（worktree 根）：tier-1 全量 692/692 + e2e 15/15 + docker 双轨（Step 4 已跑，留日志入 `/home/shih/.tmp-ak-m16/delegated-confirm/`）。
- [ ] 核对 spec §5 兼容矩阵 12 行逐行「逐字不变/零改动」断言已被用例锚定（n9/n13 无参回归 / n10 MCP / n18 archive / n28 CLI 结构门禁 / release --all-stale 无 on-behalf 既有 cli_m0 覆盖）；核对 §1 非目标未偷渡（Web 零改动 / MCP 零改动 / 零 schema / 错误码零新增 / set_expectations 结构性缺席）。
- [ ] push 分支 `delegated-confirm`（`ssh://git@ssh.github.com:443` 网络口径）-> 发起 PR（user 裁决合入；agent 永不 merge）。
- [ ] 合入后：主仓 `uv sync --reinstall-package agent-kanban`（G11，cli.py 涉改）+ 生产部署 `docker compose up -d --build kanban`（主仓根）+ 核验（healthz 200 + 容器代码态 + list_awaiting）。
- [ ] 板上 `request_review`（evidence 含 pr_url/commit_range/test_summary + 验收自评）——本批落地后即可用新产品化 `--on-behalf`（收尾协议产品化闭环）。
- [ ] AGENTS.md 基线随本批合入再更新一次（624 -> 终态实际值，T5 Step 3 只修存量漂移，本批增量随 PR 描述或合入 commit 更新）。
- [ ] worktree/分支按 git-dev-flow 正典收尾（合入后删 `.worktree/delegated-confirm`）。
