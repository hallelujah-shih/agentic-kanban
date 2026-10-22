"""M1-1 MCP HTTP 用例（tests/ac_cases_f.py + run_ac 注册）。

oracle 纪律：真实 uvicorn 子进程（复用 REST 进程管理，env_for HOST/TOKEN/DB）+
streamable_http_client（mcp 2.3.0 真实 HTTP MCP 客户端）+ httpx2。断言逐字引自
PRD §4.1（双 transport）/§4.3（is_error + {code,message,task_id}）/§5.1（actor 服务端派生，
HTTP conn = 服务端铸币 session id http:<sid>）/§6（token）。

- 错误面逐码：no_active_claim / invalid_record / already_claimed / illegal_state /
  not_found（claim 不存在 req、update_subtask 不存在 subtask）/ duplicate_subtask /
  queue_full（第 17 次 claim，AC8 同场景）。lease_expired 仅人面 renew 非 MCP 可达（缺得对）；
  db_busy 不可确定性触发 -> 显式登记盲区（docs/ops/m1-verification.md，不在本 harness 断言）。
- 逐码等价（审#P2-3）：同一场景 stdio 与 HTTP 各跑一次，断言 (code, message, task_id) 三元组一致。
- 归因（审#P1-1）：HTTP conn == 服务端铸币值（initialize 响应 Mcp-Session-Id 头对照）且 != 客户端
  注入头值/注入 sessionID meta；两 HTTP 客户端 conn 可分；stdio conn 仍为 conn-* 不混。
- 401（审#P2-2）：无 token 访问 /mcp 401 且响应体 code=='unauthorized'（排除偶发 404/421 混同）。
"""

from __future__ import annotations

import asyncio
import json
from typing import Callable

import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from ac_lib import MCP, REST, new_db, ok, query, seed_req


# ---------------------------------------------------------------- HTTP MCP 会话 harness

class HttpSession:
    """一个已连接的 HTTP MCP session（streamable_http_client 真实客户端）。

    sid = 服务端握手铸币的 MCP session id（initialize 响应 Mcp-Session-Id 头，事件钩子捕获）。
    inject 为客户端自加 header（测试注入：证明 client-supplied 不作 actor_conn，P1-1）。
    """

    def __init__(self, url: str, *, token: str | None = None, inject: dict | None = None):
        self.url = url
        self.headers: dict[str, str] = {}
        if token:
            self.headers["x-agent-kanban-token"] = token
        self.headers.update(inject or {})
        self.sid: str | None = None
        self._client: httpx2.AsyncClient | None = None
        self._cm = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> "HttpSession":
        captured: dict[str, str] = {}

        async def _capture(resp: httpx2.Response) -> None:
            sid = resp.headers.get("mcp-session-id")
            if sid:
                captured["sid"] = sid

        self._client = create_mcp_http_client(headers=self.headers)
        self._client.event_hooks["response"] = [_capture]
        self._cm = streamable_http_client(self.url, http_client=self._client)
        read, write = await self._cm.__aenter__()
        self._session = ClientSession(read, write)
        await self._session.__aenter__()
        await self._session.initialize()
        self.sid = captured.get("sid")
        return self

    async def __aexit__(self, *exc) -> None:
        err = None
        for closer in (
            lambda: self._session.__aexit__(None, None, None) if self._session else _noop(),
            lambda: self._cm.__aexit__(None, None, None) if self._cm else _noop(),
            lambda: self._client.aclose() if self._client else _noop(),
        ):
            try:
                await closer()
            except Exception as e:  # pragma: no cover
                err = err or e
        if err is not None:
            raise err  # pragma: no cover

    async def list_tools(self) -> list[str]:
        assert self._session is not None
        res = await self._session.list_tools()
        return [t.name for t in res.tools]

    async def call(self, name: str, args: dict, meta: dict | None = None) -> dict:
        assert self._session is not None
        res = await self._session.call_tool(name, args, meta=meta)
        text = res.content[0].text if res.content else ""
        return {"isError": bool(getattr(res, "is_error", False)), "content": [{"text": text}]}

    async def call_ok(self, name: str, args: dict, meta: dict | None = None) -> dict:
        res = await self.call(name, args, meta=meta)
        if res["isError"]:
            raise AssertionError(f"{name} failed: {res}")
        return json.loads(res["content"][0]["text"])

    async def call_err3(self, name: str, args: dict, meta: dict | None = None) -> tuple:
        """返回 (code, message, task_id)，断言 isError（PRD 4.3 三元组）。"""
        res = await self.call(name, args, meta=meta)
        if not res["isError"]:
            raise AssertionError(f"{name} unexpectedly succeeded: {res}")
        payload = json.loads(res["content"][0]["text"])
        return payload["code"], payload["message"], payload.get("task_id")


async def _noop() -> None:
    return None


class HTTPMCP:
    """一个 uvicorn 子进程 + 一个 HTTP MCP session（async ctx manager，自带清理）。"""

    def __init__(self, db, *, host: str = "127.0.0.1", token: str | None = None,
                 extra: dict | None = None, inject: dict | None = None):
        self.server = REST(db, host=host, token=token, extra=extra)
        self.token = token
        self.inject = inject or {}
        self.session: HttpSession | None = None

    async def __aenter__(self) -> "HTTPMCP":
        self.server.start()
        self.session = HttpSession(
            f"http://{self.server.host}:{self.server.port}/mcp", token=self.token, inject=self.inject
        )
        await self.session.__aenter__()
        return self

    async def __aexit__(self, *exc) -> None:
        if self.session is not None:
            await self.session.__aexit__(*exc)
        self.server.stop()

    @property
    def sid(self) -> str | None:
        return self.session.sid if self.session else None

    async def call(self, *a, **k):
        assert self.session is not None
        return await self.session.call(*a, **k)

    async def call_ok(self, *a, **k):
        assert self.session is not None
        return await self.session.call_ok(*a, **k)

    async def call_err3(self, *a, **k):
        assert self.session is not None
        return await self.session.call_err3(*a, **k)

    async def list_tools(self):
        assert self.session is not None
        return await self.session.list_tools()


# ---------------------------------------------------------------- 错误场景（审#P2-3 场景数据单点）

# 每个场景拆 setup（一次，stdio 跑，产生 ctx）+ fail（双 transport 同 DB 各跑一次）。
# 全部失败调用非变异（无写发生），故 stdio 与 HTTP 先后同 DB 跑失败调用，task_id 严格一致。
SCENARIOS: list[tuple[str, Callable]] = []


def _register(name):
    def deco(fn):
        SCENARIOS.append((name, fn))
        return fn
    return deco


# ctx 复用：_run_equiv 中 setup 一次（stdio）后，HTTP 侧以 ctx 跳过 setup 只跑失败调用（全部非变异 -> task_id 一致）。
@_register("no_active_claim")
async def no_active_claim(t, ctx=None):
    if ctx is None:
        ctx = {"rid": await t.seed("no_active_claim")}
    return ctx, await _fail(t, ctx, "add_subtask",
                            lambda c: {"requirement_id": c["rid"], "title": "s", "ordinal": 1})


@_register("invalid_record")
async def invalid_record(t, ctx=None):
    if ctx is None:
        rid = await t.seed("invalid_record")
        await t.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
        ctx = {"rid": rid}
    return ctx, await _fail(t, ctx, "request_review", lambda c: {"requirement_id": c["rid"], "evidence": {}})


@_register("already_claimed")
async def already_claimed(t, ctx=None):
    if ctx is None:
        rid = await t.seed("already_claimed")
        await t.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
        ctx = {"rid": rid}
    return ctx, await _fail(t, ctx, "claim_task",
                            lambda c: {"requirement_id": c["rid"], "agent_name": "b"})


@_register("illegal_state")
async def illegal_state(t, ctx=None):
    if ctx is None:
        rid = await t.seed("illegal_state")
        await t.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
        await t.call_ok("mark_blocked", {"requirement_id": rid, "reason": "dep"})
        ctx = {"rid": rid}
    return ctx, await _fail(t, ctx, "request_review",
                            lambda c: {"requirement_id": c["rid"], "evidence": {"test_summary": "t"}})


@_register("not_found_claim")
async def not_found_claim(t, ctx=None):
    if ctx is None:
        ctx = {}
    return ctx, await _fail(t, ctx, "claim_task",
                            lambda c: {"requirement_id": "deadbeef", "agent_name": "x"})


@_register("not_found_subtask")
async def not_found_subtask(t, ctx=None):
    if ctx is None:
        rid = await t.seed("not_found_subtask")
        await t.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
        ctx = {"rid": rid}
    return ctx, await _fail(t, ctx, "update_subtask",
                            lambda c: {"requirement_id": c["rid"], "subtask_id": "nope", "state": "done"})


@_register("duplicate_subtask")
async def duplicate_subtask(t, ctx=None):
    if ctx is None:
        rid = await t.seed("duplicate_subtask")
        await t.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
        await t.call_ok("add_subtask", {"requirement_id": rid, "title": "Alpha Task", "ordinal": 1})
        ctx = {"rid": rid}
    return ctx, await _fail(t, ctx, "add_subtask",
                            lambda c: {"requirement_id": c["rid"], "title": "  ALPHA   task ", "ordinal": 2})


@_register("queue_full")
async def queue_full(t, ctx=None):
    # AC8 同场景：16 认领（LEASE=-1 -> 全 STALE）+ request_review 等待中 + 第 17 认领
    if ctx is None:
        reqs = [await t.seed(f"qf-{i}") for i in range(16)]
        r17 = await t.seed("qf-17")
        for i, r in enumerate(reqs):
            await t.call_ok("claim_task", {"requirement_id": r, "agent_name": f"a{i}"})
        await t.call_ok("request_review", {"requirement_id": reqs[0], "evidence": {"test_summary": "s"}})
        ctx = {"r17": r17}
    return ctx, await _fail(t, ctx, "claim_task",
                            lambda c: {"requirement_id": c["r17"], "agent_name": "b"})


async def _fail(t, ctx: dict, name: str, args_fn) -> tuple:
    return await t.call_err3(name, args_fn(ctx))


class _StdioAdapter:
    """stdio 适配器：ac_lib.MCP（真实子进程 newline JSON-RPC），to_thread 桥接 async。"""

    def __init__(self, db, m):
        self.db = db
        self.m = m

    async def seed(self, title):
        return await asyncio.to_thread(seed_req, self.db, title)

    async def call_ok(self, name, args):
        return await asyncio.to_thread(self.m.call_ok, name, args)

    async def call_err3(self, name, args):
        return await asyncio.to_thread(self._err3, name, args)

    def _err3(self, name, args):
        res = self.m.call(name, args)
        if not res.get("isError"):
            raise AssertionError(f"{name} unexpectedly succeeded: {res}")
        payload = json.loads(res["content"][0]["text"])
        return payload["code"], payload["message"], payload.get("task_id")


class _HttpAdapter:
    """HTTP 适配器：HTTPMCP 会话；seed 走 CLI 子进程（transport 无关）。"""

    def __init__(self, db, h):
        self.db = db
        self.h = h

    async def seed(self, title):
        return seed_req(self.db, title)

    async def call_ok(self, name, args):
        return await self.h.call_ok(name, args)

    async def call_err3(self, name, args):
        return await self.h.call_err3(name, args)


async def _run_equiv(name: str, fn) -> tuple:
    """setup 一次（stdio 跑）-> 失败调用 stdio 与 HTTP 同 DB 各跑一次（失败调用非变异 -> task_id 一致）。"""
    db = new_db()
    m = MCP(db, extra={"AGENT_KANBAN_LEASE_SECONDS": "-1"}).start()
    try:
        ctx, triple_s = await fn(_StdioAdapter(db, m))
    finally:
        m.close()
    async with HTTPMCP(db, extra={"AGENT_KANBAN_LEASE_SECONDS": "-1"}) as h:
        _ctx, triple_h = await fn(_HttpAdapter(db, h), ctx)
    return triple_s, triple_h


# ---------------------------------------------------------------- 用例

def http_mcp():
    print("== M1-1.3: HTTP MCP 全 12 工具 + is_error 机制 + 归因（P1-1）")

    async def run():
        db = new_db()
        async with HTTPMCP(db, inject={"x-actor-inject": "forged-header"}) as h:
            ok("http: 服务端铸币 session id 已捕获", bool(h.sid), f"sid={h.sid!r}")

            names = await h.list_tools()
            ok("http: 12 工具注册", len(names) == 12, str(names))
            ok("http: 工具面无 release/renew（lease_expired 仅人面可达，缺得对）",
               "release" not in names and "renew" not in names, str(names))

            # 12 工具 happy path（PRD 4.1 全表）
            await h.call_ok("list_tasks", {})
            ok("http: list_tasks", True, "")
            rid = seed_req(db, "http-happy")
            claim = await h.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
            ok("http: claim_task 含租约", "lease_expires_at" in claim and "claim_id" in claim, str(claim)[:100])
            detail = await h.call_ok("get_task_detail", {"requirement_id": rid})
            ok("http: get_task_detail 认领可见",
               (detail.get("claim") or {}).get("agent_name") == "a", str(detail.get("claim"))[:100])
            st = await h.call_ok("add_subtask", {"requirement_id": rid, "title": "impl", "ordinal": 1})
            ok("http: add_subtask 返回 subtask_id", bool(st.get("subtask_id")), str(st)[:100])
            up = await h.call_ok("update_subtask", {"requirement_id": rid,
                                                    "subtask_id": st["subtask_id"], "state": "done"})
            ok("http: update_subtask state=done", up.get("state") == "done", str(up)[:100])
            ms = await h.call_ok("add_milestone", {"requirement_id": rid, "title": "m1",
                                                   "planned_at": "2026-11-01T00:00:00Z"})
            ok("http: add_milestone 返回 milestone_id", bool(ms.get("milestone_id")), str(ms)[:100])
            um = await h.call_ok("update_milestone", {"requirement_id": rid,
                                                      "milestone_id": ms["milestone_id"],
                                                      "state": "achieved",
                                                      "actual_at": "2026-11-02T00:00:00Z"})
            ok("http: update_milestone achieved", um.get("state") == "achieved", str(um)[:100])
            rec = await h.call_ok("add_record", {"requirement_id": rid, "kind": "note", "title": "n"})
            ok("http: add_record note", rec.get("kind") == "note", str(rec)[:100])
            pr = await h.call_ok("update_progress", {"requirement_id": rid, "note": "progress"})
            ok("http: update_progress", pr.get("requirement_id") == rid, str(pr)[:100])
            rv = await h.call_ok("request_review", {"requirement_id": rid,
                                                    "evidence": {"test_summary": "t"}})
            ok("http: request_review 设 marker", (rv.get("awaiting_human") or {}).get("kind") == "review",
               str(rv)[:100])
            mb = await h.call_ok("mark_blocked", {"requirement_id": rid, "reason": "need decision"})
            ok("http: mark_blocked -> BLOCKED", mb.get("state") == "BLOCKED", str(mb)[:100])
            await h.call_ok("list_awaiting", {})
            ok("http: list_awaiting", True, "")

            # 归因（P1-1）：写事件 conn == 服务端铸币 http:<sid> 且 != 客户端注入头值
            conns = query(db, "SELECT DISTINCT actor_conn c FROM events "
                              "WHERE actor_surface='mcp' AND requirement_id=?", (rid,))
            vals = [r["c"] for r in conns]
            ok("http: 归因 conn == http:<sid> 铸币值",
               bool(vals) and all(v == f"http:{h.sid}" for v in vals), str(vals))
            ok("http: 归因 != 客户端注入头值", all(v != "forged-header" for v in vals), str(vals))
            detail2 = await h.call_ok("get_task_detail", {"requirement_id": rid})
            ok("http: claim.agent_conn 同铸币值",
               (detail2.get("claim") or {}).get("agent_conn") == f"http:{h.sid}",
               str(detail2.get("claim"))[:100])

            # 最强变体：注入 opencode sessionID meta（stdio 的 conn 来源）-> 仍取 http:<sid>
            rid2 = seed_req(db, "http-meta")
            await h.call_ok("claim_task", {"requirement_id": rid2, "agent_name": "a"},
                            meta={"ai.opencode/sessionID": "ses_forged"})
            conns2 = query(db, "SELECT actor_conn c FROM events "
                               "WHERE actor_surface='mcp' AND requirement_id=?", (rid2,))
            vals2 = [r["c"] for r in conns2]
            ok("http: 注入 sessionID meta 不作 actor_conn",
               bool(vals2) and all(v == f"http:{h.sid}" and v != "ses_forged" for v in vals2), str(vals2))

            # is_error 机制（HTTP 代表码：no_active_claim / invalid_record）
            rid3 = seed_req(db, "http-noactive")
            code, msg, tid = await h.call_err3("add_subtask",
                                               {"requirement_id": rid3, "title": "s", "ordinal": 1})
            ok("http: is_error no_active_claim + task_id", code == "no_active_claim" and tid == rid3,
               f"{code} | {msg} | {tid}")
            rid4 = seed_req(db, "http-invrec")
            await h.call_ok("claim_task", {"requirement_id": rid4, "agent_name": "a"})
            code, msg, tid = await h.call_err3("request_review", {"requirement_id": rid4, "evidence": {}})
            ok("http: is_error invalid_record + task_id", code == "invalid_record" and tid == rid4,
               f"{code} | {msg} | {tid}")

        # stdio conn 仍为 conn-*（不混）：独立 DB + stdio 写事件
        db2 = new_db()
        m = MCP(db2).start()
        try:
            rid_s = seed_req(db2, "stdio-conn")
            m.call_ok("claim_task", {"requirement_id": rid_s, "agent_name": "a"})
            sconns = query(db2, "SELECT DISTINCT actor_conn c FROM events WHERE actor_surface='mcp' "
                                "AND requirement_id=?", (rid_s,))
            svals = [r["c"] for r in sconns]
            ok("stdio: conn 仍为 conn-*（与 http: 前缀不混）",
               bool(svals) and all(v.startswith("conn-") for v in svals), str(svals))
        finally:
            m.close()

    asyncio.run(run())


def http_mcp_sec():
    print("== M1-1.1/M1-1.3: token 覆盖 /mcp（401 + code=='unauthorized'）+ 有 token 全流程")

    async def run():
        db = new_db()
        async with HTTPMCP(db, token="sekret") as h:
            # 401 断言（审#P2-2）：无 token / 错 token -> 401 且 body code=='unauthorized'
            code, body = h.server.req("GET", "/mcp")
            ok("sec: 无 token /mcp -> 401", code == 401, str(code))
            ok("sec: 401 响应体 code=='unauthorized'（排除 404/421 混同）",
               isinstance(body, dict) and body.get("code") == "unauthorized", str(body)[:120])
            code, body = h.server.req("GET", "/mcp", token="wrong")
            ok("sec: 错 token /mcp -> 401 + code=='unauthorized'",
               code == 401 and isinstance(body, dict) and body.get("code") == "unauthorized",
               f"{code} {str(body)[:120]}")

            # 有 token 真实客户端 initialize + 写全流程通过（M1-1.1 验证）
            rid = seed_req(db, "sec-http")
            claim = await h.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
            await h.call_ok("update_progress", {"requirement_id": rid, "note": "secured"})
            ok("sec: 有 token HTTP MCP initialize+写 通过", bool(claim.get("claim_id")), str(claim)[:100])
            conns = query(db, "SELECT DISTINCT actor_conn c FROM events WHERE actor_surface='mcp' "
                              "AND requirement_id=?", (rid,))
            ok("sec: 有 token 归因仍 http:<sid>",
               bool(conns) and all(r["c"] == f"http:{h.sid}" for r in conns), str([r["c"] for r in conns]))

    asyncio.run(run())


def http_mcp_equiv():
    print("== M1-1.3: 错误面 stdio vs HTTP 逐码等价（(code,message,task_id) 三元组）+ 双会话可辨")

    # 期望码（断言逐字引自 PRD 4.3/§9）
    EXPECTED = {
        "no_active_claim": "no_active_claim",
        "invalid_record": "invalid_record",
        "already_claimed": "already_claimed",
        "illegal_state": "illegal_state",
        "not_found_claim": "not_found",
        "not_found_subtask": "not_found",
        "duplicate_subtask": "duplicate_subtask",
        "queue_full": "queue_full",
    }

    async def run():
        for name, fn in SCENARIOS:
            triple_s, triple_h = await _run_equiv(name, fn)
            ok(f"equiv: {name} (code,message,task_id) 逐码一致",
               triple_s == triple_h, f"stdio={triple_s} http={triple_h}")
            ok(f"equiv: {name} code=={EXPECTED[name]}", triple_h[0] == EXPECTED[name], str(triple_h))

        # 双 HTTP 会话可辨（两个 session -> 两个铸币 sid -> conn 可分）
        db = new_db()
        async with HTTPMCP(db) as h1:
            h2 = HttpSession(f"http://{h1.server.host}:{h1.server.port}/mcp",
                             inject={"x-actor-inject": "second-client"})
            await h2.__aenter__()
            try:
                ok("http2: 双会话 sid 各自铸币", bool(h1.sid) and bool(h2.sid) and h1.sid != h2.sid,
                   f"{h1.sid} vs {h2.sid}")
                r1 = seed_req(db, "two-s1")
                r2 = seed_req(db, "two-s2")
                await h1.call_ok("claim_task", {"requirement_id": r1, "agent_name": "a"})
                await h2.call_ok("claim_task", {"requirement_id": r2, "agent_name": "b"})
                c1 = query(db, "SELECT actor_conn c FROM events WHERE actor_surface='mcp' "
                               "AND requirement_id=?", (r1,))
                c2 = query(db, "SELECT actor_conn c FROM events WHERE actor_surface='mcp' "
                               "AND requirement_id=?", (r2,))
                ok("http: 双会话 conn 可分辨",
                   c1 and c2 and c1[0]["c"] == f"http:{h1.sid}" and c2[0]["c"] == f"http:{h2.sid}"
                   and c1[0]["c"] != c2[0]["c"],
                   f"{[r['c'] for r in c1]} vs {[r['c'] for r in c2]}")
            finally:
                await h2.__aexit__(None, None, None)

    asyncio.run(run())
