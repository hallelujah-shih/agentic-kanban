"""M1-2 Web 窗口用例（tests/ac_cases_g.py + run_ac 注册）。

oracle 纪律：断言逐字引自 PRD §4.2（Web 窗口 surface 表）/§5.3（看板口径与 SSE 语义）/
§6（token）；SSE 用真实 uvicorn 子进程 + httpx2 流式读取（非 mock/TestClient）；
wait-for-event deadline helper 禁 sleep 撞窗；跨进程写经 MCP stdio 子进程
（同一 SQLite，跨进程可靠信号，P2-B 先等 keepalive 再写）。

- 反证位：SSE 跨进程（MCP stdio 子进程写 -> HTTP SSE 收）+ 无回填（连接后首轮询
  窗口零历史）+ board==summary needs_attention 口径一致性（4 形态，含覆盖缺口与
  拆解新增无解释）+ 内容协商壳无原始输出 + 缺省 Accept JSON 形状回归 + 401 覆盖新端点。
- 时点无歧义（P2-C）：里程碑 planned_at 远过去（overdue 确定）、租约正常（active 确定），
  now 依赖断言与口径一致性断言正交。
"""

from __future__ import annotations

import asyncio
import json
import time

import httpx2

from ac_lib import MCP, REST, cli_ok, new_db, ok, query, seed_req


class SSE:
    """httpx2 流式 SSE 客户端：帧解析（空行分帧）+ wait-for deadline helper。

    服务端以 keepalive（`: ping`）/data 帧驱动读取，客户端零 sleep；deadline 超时即失败。
    """

    def __init__(self, url: str, *, token: str | None = None):
        self.url = url
        self.headers: dict[str, str] = {}
        if token:
            self.headers["x-agent-kanban-token"] = token
        self.client: httpx2.AsyncClient | None = None
        self._ctx = None
        self._lines = None

    async def connect(self):
        self.client = httpx2.AsyncClient(
            timeout=httpx2.Timeout(connect=10, read=None, write=10, pool=10)
        )
        self._ctx = self.client.stream("GET", self.url, headers=self.headers)
        resp = await self._ctx.__aenter__()
        if resp.status_code != 200:
            raise AssertionError(f"SSE connect status {resp.status_code}")
        self._lines = resp.aiter_lines()

    @staticmethod
    def _parse_frame(lines: list[str]) -> dict:
        out: dict = {}
        data: list[str] = []
        for line in lines:
            if line.startswith(":"):
                out.setdefault("comments", []).append(line[1:].strip())
            elif line.startswith("data:"):
                data.append(line[5:].strip())
            elif line.startswith("event:"):
                out["event"] = line[6:].strip()
        if data:
            out["data"] = "\n".join(data)
        return out

    async def _next_frame(self) -> dict | None:
        assert self._lines is not None
        lines: list[str] = []
        async for line in self._lines:
            if line == "":
                if lines:
                    return self._parse_frame(lines)
                continue
            lines.append(line)
        return None

    async def wait_for(self, predicate, *, deadline_s: float = 10.0) -> tuple[list[dict], dict]:
        """读帧直到 predicate(frame)；deadline 内未满足 -> TimeoutError。
        返回 (已见帧列表, 满足帧)。禁 sleep 撞窗：读取由服务端轮询驱动。"""
        deadline = time.monotonic() + deadline_s
        seen: list[dict] = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                frame = await asyncio.wait_for(self._next_frame(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            if frame is None:
                break
            seen.append(frame)
            if predicate(frame):
                return seen, frame
        raise TimeoutError(f"predicate not satisfied within {deadline_s}s; seen={seen}")

    async def close(self):
        if self._ctx is not None:
            try:
                await self._ctx.__aexit__(None, None, None)
            except Exception:
                pass
        if self.client is not None:
            await self.client.aclose()


def sse_stream():
    print("== M1-2.3: SSE 跨进程实时推送 + 无回填 + 纯触发器字段 + keepalive + 401")

    async def run():
        db = new_db()
        rid = seed_req(db, "sse")
        m = MCP(db).start()
        m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
        m.call_ok("add_record", {"requirement_id": rid, "kind": "note", "title": "hist-note"})
        max_before = query(db, "SELECT MAX(seq) AS s FROM events")[0]["s"]
        ok("sse: 连接前已有历史事件（游标基线非零）", bool(max_before) and max_before > 0, f"max={max_before}")
        server = REST(db, token="sekret",
                      extra={"AGENT_KANBAN_SSE_POLL_MS": "200"}).start()
        try:
            # 401（PRD §6 token 中间件覆盖全部路径，除 /healthz）
            code, body = server.req("GET", "/events/stream")
            ok("sse: 无 token /events/stream -> 401", code == 401 and body["code"] == "unauthorized",
               f"{code} {str(body)[:120]}")

            sse = SSE(f"http://{server.host}:{server.port}/events/stream", token="sekret")
            await sse.connect()
            try:
                # P2-B 时序锚：先等首个 keepalive（证明轮询已启动、游标已初始化）再跨进程写
                seen, first = await sse.wait_for(lambda f: "data" not in f)
                ok("sse: 首帧为 keepalive（连接后首轮询零历史，无回填）",
                   first.get("comments") == ["ping"] and not any("data" in f for f in seen), str(seen))
                # 跨进程写：MCP stdio 子进程写新事件 -> SSE 收到（seq=连接时游标+1）
                new_seq = max_before + 1
                m.call_ok("add_record", {"requirement_id": rid, "kind": "note", "title": "live-note"})
                seen2, frame = await sse.wait_for(lambda f: "data" in f)
                data = json.loads(frame["data"])
                ok("sse: 跨进程事件到达且 seq=游标+1（无历史重放）",
                   data.get("seq") == new_seq, f"seq={data.get('seq')} expect={new_seq} frame={frame}")
                ok("sse: 纯触发器字段（无 title/payload，反淹没）",
                   set(data.keys()) == {"seq", "requirement_id", "kind", "severity", "ts",
                                        "actor_surface", "actor_conn"},
                   f"keys={sorted(data.keys())}")
                ok("sse: kind/requirement_id 正确",
                   data.get("kind") == "note" and data.get("requirement_id") == rid, str(data))
            finally:
                await sse.close()
        finally:
            server.stop()
        m.close()

    asyncio.run(run())


def board_view():
    print("== M1-2.2: board 4 形态 + board==summary 口径一致性 + status 过滤 + 401")

    db = new_db()
    m = MCP(db).start()
    r1 = seed_req(db, "board-normal")   # 正常：无子任务 -> 无 attention
    r2 = seed_req(db, "board-blocked")  # blocked 子任务 + 里程碑延误 + awaiting
    m.call_ok("claim_task", {"requirement_id": r2, "agent_name": "a"})
    s1 = m.call_ok("add_subtask", {"requirement_id": r2, "title": "st1", "ordinal": 1})
    m.call_ok("update_subtask", {"requirement_id": r2, "subtask_id": s1["subtask_id"], "state": "blocked"})
    m.call_ok("add_milestone", {"requirement_id": r2, "title": "M2", "planned_at": "2020-01-01T00:00:00+00:00"})
    m.call_ok("mark_blocked", {"requirement_id": r2, "reason": "need decision"})
    r3 = seed_req(db, "board-gap")      # 覆盖缺口：acceptance 锚无子任务链接
    cli_ok(db, "set_expectations", "--requirement-id", r3, "--acceptance", '[{"item": "G1"}]')
    r4 = seed_req(db, "board-decomp")   # 拆解新增无解释：CLAIMED 期间 add_subtask 无 decision/deviation
    m.call_ok("claim_task", {"requirement_id": r4, "agent_name": "b"})
    m.call_ok("add_subtask", {"requirement_id": r4, "title": "x1", "ordinal": 1})
    m.call_ok("add_subtask", {"requirement_id": r4, "title": "x2", "ordinal": 2})
    m.close()

    rest = REST(db, token="sekret").start()
    try:
        code, body = rest.req("GET", "/board")
        ok("board: 无 token /board -> 401", code == 401 and body["code"] == "unauthorized", f"{code} {str(body)[:120]}")
        code, data = rest.req("GET", "/board", token="sekret")
        ok("board: 有 token /board 200", code == 200, str(code))
        tasks = {t["requirement_id"]: t for t in data["tasks"]}
        ok("board: 4 需求在板（非终态默认过滤）", {r1, r2, r3, r4} <= set(tasks), str(list(tasks)))
        # 口径一致性（审#P1-2）：每需求 board needs_attention == summary needs_attention
        for rid in (r1, r2, r3, r4):
            code, s = rest.req("GET", f"/requirements/{rid}/summary", token="sekret")
            b_na = sorted(n["type"] for n in tasks[rid]["needs_attention"])
            s_na = sorted(n["type"] for n in s["needs_attention"])
            ok(f"board: {rid[:6]} board==summary needs_attention 一致", b_na == s_na,
               f"board={b_na} summary={s_na}")
        na2 = sorted(n["type"] for n in tasks[r2]["needs_attention"])
        ok("board: R2 blocked_subtask 信号", "blocked_subtask" in na2, str(na2))
        ok("board: R2 milestone_delay 信号（planned_at 远过去 -> overdue 无歧义）",
           "milestone_delay" in na2, str(na2))
        ok("board: R2 awaiting_human 标记可见", (tasks[r2]["awaiting_human"] or {}).get("kind") == "blocked",
           str(tasks[r2]["awaiting_human"]))
        ok("board: R2 claim signal=active（租约远未来，无歧义时点）",
           (tasks[r2]["claim"] or {}).get("signal") == "active", str(tasks[r2]["claim"]))
        na4 = sorted(n["type"] for n in tasks[r4]["needs_attention"])
        ok("board: R4 decomposition_added 信号", "decomposition_added" in na4, str(na4))
        ok("board: R1 正常无 attention", tasks[r1]["needs_attention"] == [], str(tasks[r1]["needs_attention"]))
        ok("board: R3 覆盖缺口不入 attention（非派生信号，与 summary 同源）",
           tasks[r3]["needs_attention"] == [], str(tasks[r3]["needs_attention"]))
        code, s3 = rest.req("GET", f"/requirements/{r3}/summary", token="sekret")
        ok("board: R3 summary 覆盖缺口 uncovered=True（共享 helper 无回归）",
           any(a["uncovered"] for a in s3["acceptance_table"]), str(s3["acceptance_table"]))
        ok("board: attention_ids = {R2, R4}", set(data["attention_ids"]) == {r2, r4}, str(data["attention_ids"]))
        code, d = rest.req("GET", "/board", params={"status": "OPEN"}, token="sekret")
        ok("board: status=OPEN 过滤只留 OPEN", {t["requirement_id"] for t in d["tasks"]} == {r1, r3},
           str([t["state"] for t in d["tasks"]]))
        code, d = rest.req("GET", "/board", params={"status": "CLAIMED"}, token="sekret")
        ok("board: status=CLAIMED 过滤只留 CLAIMED", {t["requirement_id"] for t in d["tasks"]} == {r4},
           str([t["state"] for t in d["tasks"]]))
    finally:
        rest.stop()


def web_shell():
    print("== M1-2.4: / 看板壳 + 内容协商壳 + 反淹没无原始输出 + 缺省 Accept JSON 回归 + 401")

    db = new_db()
    rid = seed_req(db, "web")
    m = MCP(db).start()
    m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
    prog_secret = "WEB_PROGRESS_SECRET_xyz"
    long_content = "WEB_LONG_CONTENT_abc"
    m.call_ok("update_progress", {"requirement_id": rid, "note": prog_secret})
    m.call_ok("add_record", {"requirement_id": rid, "kind": "risk", "title": "risk",
                             "severity": "attention", "content": long_content})
    m.close()

    rest = REST(db, token="sekret").start()
    try:
        code, body = rest.req("GET", "/")
        ok("web: 无 token / -> 401", code == 401 and body["code"] == "unauthorized", f"{code} {str(body)[:120]}")
        code, raw = rest.req("GET", "/", token="sekret")
        ok("web: / 200 且为看板壳（shell 标记 + EventSource）",
           code == 200 and isinstance(raw, str) and 'id="board-root"' in raw and "EventSource" in raw, str(code))
        ok("web: / 壳无原始输出（progress note/事件 content 不进壳）",
           isinstance(raw, str) and prog_secret not in raw and long_content not in raw, "shell leak")
        code, raw = rest.req("GET", f"/requirements/{rid}", token="sekret",
                             headers={"Accept": "text/html"})
        ok("web: detail Accept text/html -> 200 HTML 壳",
           code == 200 and isinstance(raw, str) and 'id="detail-root"' in raw, str(code))
        ok("web: 深潜壳无原始输出",
           isinstance(raw, str) and prog_secret not in raw and long_content not in raw, "shell leak")
        code, d = rest.req("GET", f"/requirements/{rid}", token="sekret")
        ok("web: detail 缺省 Accept -> JSON 形状回归（state/subtasks/events）",
           code == 200 and isinstance(d, dict) and d["state"] == "CLAIMED"
           and isinstance(d["subtasks"], list) and isinstance(d["events"], list), str(code))
        code, raw = rest.req("GET", f"/requirements/{rid}/summary.html", token="sekret")
        ok("web: /summary.html 保留 200", code == 200 and isinstance(raw, str) and "需要关注" in raw, str(code))
    finally:
        rest.stop()
