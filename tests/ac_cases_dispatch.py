"""B2 dispatch 主链用例（T1 服务发现/状态门/create/prompt/wait/note；T2 复用/resume；
T3 超时契约 + 投递失败/投递后异常留痕 + resume 错误分支；T4 --bg 心跳续租 + U1 深挖锚
directory 字段 + R6 resume 目标接受面归一）。

oracle 纪律：断言引 plan.md「dispatch 步骤 1-10」+「心跳（--bg）」+「验证锚」/
BCD b2-dispatch.md（§3 P-imp1/P-imp2/P-imp3/P-imp4/P-imp6、§4 S1/S4/S5/S7/S8、
§5 E7、§7 I1-I7）/ SKILL.md「派发方协议」（派发稿五要素 + 留痕条款）。
mock opencode 服务＝测试进程内 threaded http.server（port=0 内核分配 + 读
server_address，无 bind-close 竞态）：请求全留痕（method/path/body），行为可配置
（GET 200/404/401、outcome 运行中可翻转（测试线程改 srv._cfg["outcome"]）、
wait 阻塞、prompt_code 可配失败）。超时确定性锚＝mock 侧 _wait_completed 未被记完成
（禁墙钟）；bg 用例确定性锚＝mock 探测 GET 事件/DB 计数/renew 事件（有界 deadline
仅用于等事件，超期即红）。
红跑：dispatch 子命令未实现前 argparse invalid choice -> 全红。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import tempfile
import threading
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ac_cases_k import _set_state, _update
from ac_cases_l import _ak_dispose, _ak_import, _ak_restore
from ac_lib import MCP, REPO_ROOT, cli, cli_err, cli_ok, env_for, new_db, ok, query

from agent_kanban import skillpack


class _MockOpencode(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 静音
        pass

    def _send(self, code, body=b""):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n).decode() if n else ""

    def do_GET(self):
        log = self.server._log
        parsed = urllib.parse.urlparse(self.path)
        entry = {"method": "GET", "path": self.path, "body": "",
                 "auth": self.headers.get("Authorization")}
        m = re.fullmatch(r"/api/session/([^/]+)", parsed.path)
        if m:
            cfg = self.server._cfg
            # 真服务 2.1.4 形态（dogfood 探针实锤）：GET /api/session/{id} 200 body 为
            # {"data": {...}} 包装；裸形态会使 bg 终态判据 outcome 恒 None（T5 审 D4）
            entry["body"] = json.dumps({"data": {"id": m.group(1),
                                                 "outcome": cfg.get("outcome")}})
            code = int(cfg.get("get_code", 404))
            # 状态化（T2 幂等复用）：未收到该 id 的 create POST 前 404，收到后 200；
            # get_code=401/200 保持静态语义（T1 夹具契约不动）
            if code == 404 and m.group(1) in self.server._exists:
                code = 200
        else:
            code = 404
        log.append(entry)
        self._send(code, entry["body"].encode())

    def do_POST(self):
        log = self.server._log
        body = self._body()
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        log.append({"method": "POST", "path": self.path, "body": body,
                    "auth": self.headers.get("Authorization")})
        if path == "/api/session":
            try:
                self.server._exists[json.loads(body)["id"]] = True
            except (ValueError, KeyError):
                pass
            self._send(200, body.encode())
        elif re.fullmatch(r"/api/session/[^/]+/prompt", path):
            code = int(self.server._cfg.get("prompt_code", 200))
            self._send(code, b"{}")
        elif re.fullmatch(r"/api/session/[^/]+/model", path):
            # 真服务 switchModel 返回 204 No Content（非 200）；对齐真实行为，禁镜像实现假设
            code = int(self.server._cfg.get("model_code", 204))
            self.server._model_codes.append(code)
            self._send(code, b"" if code == 204 else b"{}")
        elif re.fullmatch(r"/api/experimental/session/[^/]+/wait", path):
            delay = float(self.server._cfg.get("wait_delay", 0))
            if delay:
                time.sleep(delay)
            self.server._wait_completed = True
            try:
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
            except OSError:
                # 客户端已断开（超时放弃）：写响应抛错，handler 线程异常噪声禁入测试进程
                pass
        else:
            self._send(404)

    def do_DELETE(self):
        # T3 盲审 P1-1：无 do_DELETE 时 DELETE 走 501 不入 log，I4「无 delete」断言为空断言；
        # 记 entry 后回 204（真服务语义），断言 method 判据对「超时后杀 session」错实现必红
        log = self.server._log
        log.append({"method": "DELETE", "path": self.path, "body": "",
                    "auth": self.headers.get("Authorization")})
        self._send(204, b"")


def _mock_start(cfg: dict):
    # port=0 内核分配 + 读 server_address：无 bind-close 竞态（T2 盲审 P2-1 确定性锚）
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _MockOpencode)
    srv._cfg = cfg
    srv._log = []
    srv._wait_completed = False
    srv._exists = {}  # T2 状态化：已收到 create POST 的 session id 集合
    srv._model_codes = []  # switchModel 端点实际回码记录（断言 mock 对齐真实 204）
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, lambda: srv.shutdown()


def _workspace(tmp: Path) -> tuple[Path, Path]:
    ws = tmp / "ws"
    ws.mkdir()
    env_card = ws / "AGENTS.md"
    env_card.write_text(
        "## 环境卡\n- workspace: %s\n- 红线: 禁推 main；禁写生产 DB\n" % ws, encoding="utf-8")
    return ws, env_card


def _pid_alive(pid: int) -> bool:
    """bg 子进程存活判定（非测试进程子进程，不能 waitpid；pid 未回收则 kill(pid,0) 成功）。"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _note_contents(db, rid: str) -> list[str]:
    rows = query(db, "SELECT content FROM events WHERE requirement_id=? AND kind='note'", (rid,))
    return [r["content"] for r in rows if r["content"]]


def _dispatch_env(db, port: int) -> dict:
    # a4 预检注入：假 `opencode mcp list`（kanban connected）。tmp 工作区无项目级
    # opencode.json，真命令只列全局服务器（无 kanban）会误拒所有用例；既有用例经
    # 预检通过路径，预检行为本身由 k_mcp_precheck_* 用例各自构造状态化 fake 覆盖。
    fd, fake = tempfile.mkstemp(prefix="ak-mcp-pass-", suffix=".sh")
    with os.fdopen(fd, "w") as f:
        f.write("#!/bin/sh\nprintf '\u2713 kanban  connected\\n'\n")
    os.chmod(fake, 0o755)
    return env_for(db, {"AGENT_KANBAN_OPENCODE_URL": f"http://127.0.0.1:{port}",
                        "AGENT_KANBAN_OPENCODE_AUTH": "none",
                        "AGENT_KANBAN_DISPATCH_MCP_LIST_CMD": fake})


def k_dispatch_main():
    print("== B2-T1: dispatch 主链（OPEN + 指针行 + create + 派发稿五要素 + wait + 板 note）")
    tmp = Path(tempfile.mkdtemp(prefix="ak-dispatch-main-"))
    db = new_db()
    ws, env_card = _workspace(tmp)
    rid = cli_ok(db, "new", "--title", "dispatch 主链需求",
                 "--description", f"workspace={ws} env-card={env_card}")["requirement_id"]
    sid = f"ses_req_{rid[:8]}"
    srv, stop = _mock_start({"get_code": 404})
    port = srv.server_address[1]
    extra = _dispatch_env(db, port)
    try:
        res = cli(db, "dispatch", "--requirement-id", rid,
                  "--model", "ks-cp/glm-5-3-flash", "--budget", "10m", extra=extra)
        ok("dispatch rc=0", res.returncode == 0, f"rc={res.returncode} stderr={res.stderr}")
        out = json.loads(res.stdout)
        # U1 深挖锚（user 裁决 2026-10-28）：stdout 结果必含 session id + 启动目录两顶层字段
        ok("stdout 结果顶层 directory＝workspace 指针值（深挖锚 cd <dir>）",
           out.get("directory") == str(ws), out)
        ok("stdout 结果顶层 session id＝派生 id", out.get("session_id") == sid, out)
        log = list(srv._log)
        creates = [r for r in log if r["method"] == "POST" and r["path"] == "/api/session"]
        ok("create 恰 1 次", len(creates) == 1, f"n={len(creates)}")
        if creates:
            b = json.loads(creates[0]["body"])
            ok("id=ses_req_<前8hex>", b.get("id") == sid, b.get("id"))
            ok("title 含 ak-<id8> 与需求标题",
               isinstance(b.get("title"), str) and b["title"].startswith(f"ak-{rid[:8]}")
               and "dispatch 主链需求" in b["title"], b.get("title"))
            ok("model 拆分", b.get("model") == {"id": "glm-5-3-flash", "providerID": "ks-cp"},
               b.get("model"))
            ok("location.directory=workspace 指针值",
               b.get("location", {}).get("directory") == str(ws), b.get("location"))
        prompts = [r for r in log if r["method"] == "POST"
                   and r["path"] == f"/api/session/{sid}/prompt"]
        ok("prompt 投给派生 session", len(prompts) == 1, f"n={len(prompts)}")
        if prompts:
            t = json.loads(prompts[0]["body"])["text"]
            ok("要素1 任务指针=req id 完整", rid in t)
            ok("要素1 指针行原文", f"workspace={ws}" in t)
            ok("要素2 协议入口=SKILL 绝对路径",
               skillpack.skill_file().as_posix() in t)
            ok("要素3 环境卡路径=指针值逐字", str(env_card) in t)
            ok("要素4 交付规格", "交付规格" in t and "事实锚" in t)
            ok("要素5 红线节原文", "禁推 main；禁写生产 DB" in t)
            ok("墙钟预算", "预算" in t)
        ok("wait 被调", any(r["method"] == "POST" and r["path"] == f"/api/experimental/session/{sid}/wait"
                            for r in log))
        contents = _note_contents(db, rid)
        ok("板 note 恰 1 条", len(contents) == 1, f"n={len(contents)}")
        if contents:
            c = contents[0]
            first, *rest = c.splitlines()
            ok("note 首行人话（分发+session id）",
               "分发" in first and sid in first, first)
            tail = "\n".join(rest)
            ok("note 结构化=模型/目录/结局",
               "ks-cp/glm-5-3-flash" in tail and str(ws) in tail and "完成" in tail, tail)
        ok("mock 无 delete 调用",
           not any(r["method"] == "DELETE" or "delete" in r["path"].lower() for r in log))
        # 勘误 3：AUTH=none 时所有请求不带 auth 头（防生产覆盖误关鉴权的确定性锚）
        ok("AUTH=none 全部请求 auth 头为 None",
           log and all(r.get("auth") is None for r in log),
           f"auths={[(r['path'], r['auth']) for r in log]}")
    finally:
        stop()


def k_dispatch_badstate():
    print("== B2-T1: 状态门（DONE -> 拒绝，HTTP 零调用，无 note）")
    tmp = Path(tempfile.mkdtemp(prefix="ak-dispatch-bad-"))
    db = new_db()
    ws, env_card = _workspace(tmp)
    rid = cli_ok(db, "new", "--title", "done 需求",
                 "--description", f"workspace={ws} env-card={env_card}")["requirement_id"]
    _set_state(db, rid, "DONE")
    srv, stop = _mock_start({"get_code": 404})
    port = srv.server_address[1]
    extra = _dispatch_env(db, port)
    try:
        res = cli(db, "dispatch", "--requirement-id", rid,
                  "--model", "ks-cp/glm-5-3-flash", "--budget", "10m", extra=extra)
        ok("非零退出", res.returncode != 0, f"rc={res.returncode}")
        ok("stderr 含当前 state", "DONE" in res.stderr, res.stderr)
        ok("mock 零调用", len(srv._log) == 0, f"n={len(srv._log)}")
        ok("无 note 事件", len(_note_contents(db, rid)) == 0)
    finally:
        stop()


def k_dispatch_authfail():
    print("== B2-T1: 存在检查 401 -> 鉴权中止（P-imp1 类：不误判创建，无 create 调用）")
    tmp = Path(tempfile.mkdtemp(prefix="ak-dispatch-auth-"))
    db = new_db()
    ws, env_card = _workspace(tmp)
    rid = cli_ok(db, "new", "--title", "auth 需求",
                 "--description", f"workspace={ws} env-card={env_card}")["requirement_id"]
    srv, stop = _mock_start({"get_code": 401})
    port = srv.server_address[1]
    extra = _dispatch_env(db, port)
    try:
        res = cli(db, "dispatch", "--requirement-id", rid,
                  "--model", "ks-cp/glm-5-3-flash", "--budget", "10m", extra=extra)
        ok("非零退出", res.returncode != 0, f"rc={res.returncode}")
        low = res.stderr.lower()
        ok("错误含鉴权语义（auth/401）", "auth" in low or "401" in low, res.stderr)
        ok("无 create 调用", not any(r["method"] == "POST" and r["path"] == "/api/session"
                                     for r in srv._log), f"log={srv._log}")
    finally:
        stop()


def k_dispatch_reuse():
    print("== B2-T2: 幂等复用（req 保持 OPEN，dispatch 两次 -> create 恰 1 次 + 第二次投续接稿）")
    tmp = Path(tempfile.mkdtemp(prefix="ak-dispatch-reuse-"))
    db = new_db()
    ws, env_card = _workspace(tmp)
    rid = cli_ok(db, "new", "--title", "幂等复用需求",
                 "--description", f"workspace={ws} env-card={env_card}")["requirement_id"]
    sid = f"ses_req_{rid[:8]}"
    srv, stop = _mock_start({"get_code": 404})
    port = srv.server_address[1]
    extra = _dispatch_env(db, port)
    try:
        res1 = cli(db, "dispatch", "--requirement-id", rid,
                   "--model", "ks-cp/glm-5-3-flash", "--budget", "10m", extra=extra)
        ok("第一次 dispatch rc=0", res1.returncode == 0,
           f"rc={res1.returncode} stderr={res1.stderr}")
        res2 = cli(db, "dispatch", "--requirement-id", rid,
                   "--model", "ks-cp/glm-5-3-flash", "--budget", "10m", extra=extra)
        ok("第二次 dispatch rc=0", res2.returncode == 0,
           f"rc={res2.returncode} stderr={res2.stderr}")
        log = list(srv._log)
        creates = [r for r in log if r["method"] == "POST" and r["path"] == "/api/session"]
        ok("create 计数=1（第二次不新 create）", len(creates) == 1, f"n={len(creates)}")
        prompts = [r for r in log if r["method"] == "POST" and r["path"] == f"/api/session/{sid}/prompt"]
        ok("同 session 收到 2 次 prompt", len(prompts) == 2, f"n={len(prompts)}")
        if len(prompts) == 2:
            t1 = json.loads(prompts[0]["body"])["text"]
            t2 = json.loads(prompts[1]["body"])["text"]
            ok("第一次是新建稿", "派发稿" in t1 and "会话已存在" not in t1, t1[:120])
            ok("第二次是续接稿（会话已存在）", "会话已存在" in t2 and "派发稿" not in t2, t2[:120])
            ok("续接稿 state=OPEN", "state: OPEN" in t2, t2)
            ok("续接稿 awaiting 摘要（无）", "awaiting: 无" in t2, t2)
            ok("续接稿子任务进度逐字 0/0", "0/0" in t2, t2)
        contents = _note_contents(db, rid)
        ok("板 note 共 2 条", len(contents) == 2, f"n={len(contents)}")
        if len(contents) == 2:
            first = contents[1].splitlines()[0]
            ok("第二条 note 首行人话含会话 id", "分发" in first and sid in first, first)
    finally:
        stop()


def k_resume():
    print("== B2-T2: resume（需求 id + 指令逐字 + note 记当前 state；--model 先 switchModel 后 prompt）")
    tmp = Path(tempfile.mkdtemp(prefix="ak-resume-"))
    db = new_db()
    ws, env_card = _workspace(tmp)
    rid = cli_ok(db, "new", "--title", "resume 需求",
                 "--description", f"workspace={ws} env-card={env_card}")["requirement_id"]
    _set_state(db, rid, "REOPEN")
    sid = f"ses_req_{rid[:8]}"
    srv, stop = _mock_start({"get_code": 404})
    srv._exists[sid] = True  # given：worker session 已存在（此前 dispatch 创建）
    port = srv.server_address[1]
    extra = _dispatch_env(db, port)
    try:
        # (a) 需求 id + 指令逐字
        res = cli(db, "resume", "--requirement-id", rid, "落点改 tmp 目录", extra=extra)
        ok("resume rc=0", res.returncode == 0, f"rc={res.returncode} stderr={res.stderr}")
        out = json.loads(res.stdout)
        # U1 深挖锚（user 裁决 2026-10-28）：stdout 结果必含 session id + 启动目录两顶层字段
        ok("stdout 结果顶层 directory＝workspace 指针值（深挖锚 cd <dir>）",
           out.get("directory") == str(ws), out)
        log = list(srv._log)
        prompts = [r for r in log if r["method"] == "POST" and r["path"] == f"/api/session/{sid}/prompt"]
        ok("prompt 投同派生 session", len(prompts) == 1, f"n={len(prompts)}")
        if prompts:
            t = json.loads(prompts[0]["body"])["text"]
            ok("text 逐字＝指令", t == "落点改 tmp 目录", t)
        ok("无 --model 时不调 switchModel",
           not any(r["method"] == "POST" and r["path"].endswith("/model") for r in log),
           f"log={[r['path'] for r in log]}")
        ok("resume 不 create session",
           not any(r["method"] == "POST" and r["path"] == "/api/session" for r in log),
           f"log={[r['path'] for r in log]}")
        ok("同步 wait 被调",
           any(r["method"] == "POST" and r["path"] == f"/api/experimental/session/{sid}/wait"
               for r in log))
        contents = _note_contents(db, rid)
        ok("板 note 1 条", len(contents) == 1, f"n={len(contents)}")
        if contents:
            first, *rest = contents[0].splitlines()
            ok("note 首行含 续跑 + 需求当前 state",
               "续跑" in first and "REOPEN" in first, first)
            tail = "\n".join(rest)
            ok("note 结构化含 session id", sid in tail, tail)
            ok("note 含目录行（U1 深挖锚，逐字）", f"目录: {ws}" in contents[0], contents[0])
        # (b) ses 派生形态直给 + --model：先 switchModel 后 prompt
        res2 = cli(db, "resume", "--requirement-id", sid, "继续",
                   "--model", "other/model", extra=extra)
        ok("resume --model rc=0", res2.returncode == 0,
           f"rc={res2.returncode} stderr={res2.stderr}")
        log = list(srv._log)
        model_idx = [i for i, r in enumerate(log)
                     if r["method"] == "POST" and r["path"] == f"/api/session/{sid}/model"]
        prompt_idx = [i for i, r in enumerate(log)
                      if r["method"] == "POST" and r["path"] == f"/api/session/{sid}/prompt"]
        ok("switchModel 恰 1 次", len(model_idx) == 1, f"log={[r['path'] for r in log]}")
        ok("顺序：model 在 prompt 之前",
           len(model_idx) == 1 and len(prompt_idx) == 2 and model_idx[0] < prompt_idx[1],
           f"model={model_idx} prompt={prompt_idx}")
        if model_idx:
            b = json.loads(log[model_idx[0]]["body"])
            ok("switchModel body {model:{id,providerID}}",
               b == {"model": {"id": "model", "providerID": "other"}}, b)
        if len(prompt_idx) == 2:
            t2 = json.loads(log[prompt_idx[1]]["body"])["text"]
            ok("第二次 prompt text＝继续", t2 == "继续", t2)
        contents = _note_contents(db, rid)
        ok("板 note 共 2 条", len(contents) == 2, f"n={len(contents)}")
        if len(contents) == 2:
            first, *rest = contents[1].splitlines()
            ok("第二条 note 首行含 续跑 + state", "续跑" in first and "REOPEN" in first, first)
            ok("note 模型记新模型", "other/model" in "\n".join(rest), rest)
        # (c) R6 resume 目标接受面对齐 dispatch（T3 盲审 P2-2 裁决）：
        # 超时契约行回显的 dispatch 原样输入（8-hex 前缀/大写 32hex）resume 恒可执行
        res3 = cli(db, "resume", "--requirement-id", rid[:8], "继续", extra=extra)
        ok("8-hex 前缀形态目标 resume 成功", res3.returncode == 0,
           f"rc={res3.returncode} stderr={res3.stderr}")
        out3 = json.loads(res3.stdout)
        ok("8-hex 前缀与 32hex 同 session id", out3.get("session_id") == sid, out3)
        res4 = cli(db, "resume", "--requirement-id", rid.upper(), "继续", extra=extra)
        ok("大写 32hex 形态目标 resume 成功（归一后）", res4.returncode == 0,
           f"rc={res4.returncode} stderr={res4.stderr}")
        out4 = json.loads(res4.stdout)
        ok("大写 32hex 归一后同 session id", out4.get("session_id") == sid, out4)
    finally:
        stop()


def k_dispatch_timeout():
    print("== B2-T3: 超时契约（budget 2s / wait 阻塞 10s -> rc=1 + stdout timeout/resume 提示"
          " + note 记超时 + 不杀 session + wait 未被记完成）")
    tmp = Path(tempfile.mkdtemp(prefix="ak-dispatch-timeout-"))
    db = new_db()
    ws, env_card = _workspace(tmp)
    rid = cli_ok(db, "new", "--title", "超时需求",
                 "--description", f"workspace={ws} env-card={env_card}")["requirement_id"]
    sid = f"ses_req_{rid[:8]}"
    srv, stop = _mock_start({"get_code": 404, "wait_delay": 10})
    port = srv.server_address[1]
    extra = _dispatch_env(db, port)
    try:
        res = cli(db, "dispatch", "--requirement-id", rid, "--budget", "2s", extra=extra)
        ok("rc=1（超时≠硬失败但命令未完成）", res.returncode == 1,
           f"rc={res.returncode} stderr={res.stderr}")
        ok("stdout 契约行含 timeout 与 resume 提示（禁墙钟）",
           "timeout" in res.stdout and f"agent-kanban resume {rid}" in res.stdout,
           f"stdout={res.stdout!r}")
        ok("错误照旧进 stderr", "timeout" in res.stderr, res.stderr)
        contents = _note_contents(db, rid)
        ok("板 note 恰 1 条", len(contents) == 1, f"n={len(contents)}")
        if contents:
            ok("note 记超时", "超时" in contents[0], contents[0])
        ok("mock 无 delete 调用（I4 超时不杀 session）",
           not any(r["method"] == "DELETE" or "delete" in r["path"].lower() for r in srv._log),
           f"log={[(r['method'], r['path']) for r in srv._log]}")
        ok("mock wait 未被记完成（确定性锚：超时真发生）", srv._wait_completed is False)
    finally:
        stop()


def k_dispatch_failnote():
    print("== B2-T3: 投递失败留痕（P-imp2：prompt 500 -> 非零退出 + note 记失败事实+错误码，无 wait 调用）")
    tmp = Path(tempfile.mkdtemp(prefix="ak-dispatch-failnote-"))
    db = new_db()
    ws, env_card = _workspace(tmp)
    rid = cli_ok(db, "new", "--title", "投递失败需求",
                 "--description", f"workspace={ws} env-card={env_card}")["requirement_id"]
    srv, stop = _mock_start({"get_code": 404, "prompt_code": 500})
    port = srv.server_address[1]
    extra = _dispatch_env(db, port)
    try:
        res = cli(db, "dispatch", "--requirement-id", rid, "--budget", "10m", extra=extra)
        ok("非零退出", res.returncode != 0, f"rc={res.returncode}")
        contents = _note_contents(db, rid)
        ok("板 note 恰 1 条（失败也留痕）", len(contents) == 1, f"n={len(contents)}")
        if contents:
            first = contents[0].splitlines()[0]
            ok("note 首行人话含「分发失败」", "分发失败" in first, first)
            ok("note content 含失败语义 + 错误码", "失败" in contents[0] and "500" in contents[0],
               contents[0])
        ok("无 wait 调用（投递失败不进入同步）",
           not any("wait" in r["path"] for r in srv._log),
           f"log={[r['path'] for r in srv._log]}")
    finally:
        stop()


def k_resume_errcase():
    print("== B2-T3: resume 错误分支（T2 盲审 P2-1 折入：非派生形态 invalid_target；"
          "派生形态无映射 session_unmapped，无 prompt 调用）")
    db = new_db()
    srv, stop = _mock_start({"get_code": 404})
    port = srv.server_address[1]
    extra = _dispatch_env(db, port)
    try:
        res = cli(db, "resume", "--requirement-id", "ses_handmade1", "继续", extra=extra)
        ok("非派生形态 ses id 非零退出", res.returncode != 0, f"rc={res.returncode}")
        ok("报错含 invalid_target 语义", "invalid_target" in res.stderr, res.stderr)
        res2 = cli(db, "resume", "--requirement-id", "ses_req_ffff9999", "继续", extra=extra)
        ok("派生形态无映射非零退出", res2.returncode != 0, f"rc={res2.returncode}")
        ok("报错含「无法映射」语义（session_unmapped）",
           "session_unmapped" in res2.stderr and "无法映射" in res2.stderr, res2.stderr)
        ok("无 prompt 调用",
           not any(r["method"] == "POST" and "prompt" in r["path"] for r in srv._log),
           f"log={[r['path'] for r in srv._log]}")
    finally:
        stop()


def k_bg_heartbeat():
    print("== B2-T4: --bg 心跳（pre-claim 跳过 -> claim 后周期 renew(delegated 受托痕) "
          "-> outcome 翻转终态 note + bg 退出；断言全计数/事件，有界 deadline 仅等事件）")
    tmp = Path(tempfile.mkdtemp(prefix="ak-dispatch-bg-"))
    db = new_db()
    ws, env_card = _workspace(tmp)
    rid = cli_ok(db, "new", "--title", "bg 心跳需求",
                 "--description", f"workspace={ws} env-card={env_card}")["requirement_id"]
    sid = f"ses_req_{rid[:8]}"
    # mock 长活 session：GET 404（状态化：create POST 后 200）+ outcome=None 运行中可翻转
    srv, stop = _mock_start({"get_code": 404})
    port = srv.server_address[1]
    extra = _dispatch_env(db, port)
    extra["AGENT_KANBAN_DISPATCH_HEARTBEAT_SEC"] = "1"
    proc_pid = None
    try:
        res = cli(db, "dispatch", "--requirement-id", rid, "--bg", extra=extra)
        ok("dispatch --bg 投递后立即返回 rc=0", res.returncode == 0,
           f"rc={res.returncode} stderr={res.stderr}")
        out = json.loads(res.stdout)
        proc_pid = out.get("bg_pid")
        ok("stdout JSON 含 bg_pid", isinstance(proc_pid, int), out)
        ok("stdout 顶层 directory（U1 深挖锚）", out.get("directory") == str(ws), out)
        ok("结局=bg（未进同步 wait）", out.get("outcome") == "bg", out)
        # (a) pre-claim 窗口先行：等第 2 个探测 GET（create POST 之后）再建 claim——
        # 首探测结构上先于 claim，pre-claim 跳过 >=1 确定性成立（T4 审 P1-2：只等第 1 个
        # 探测时，子进程被挂起可致跳过计数 0，(c) 段假红＝测试锚调度竞态非产品缺陷）；
        # 建 claim 前无 renew 调用、无板事件（除分发 note）
        deadline = time.monotonic() + 15
        probed = False
        while time.monotonic() < deadline:
            log = list(srv._log)
            post_idx = [i for i, r in enumerate(log)
                        if r["method"] == "POST" and r["path"] == "/api/session"]
            get_idx = [i for i, r in enumerate(log)
                       if r["method"] == "GET" and r["path"] == f"/api/session/{sid}"]
            if post_idx and len([i for i in get_idx if i > post_idx[0]]) >= 2:
                probed = True
                break
            time.sleep(0.05)
        ok("心跳跑过至少两个周期（bg 探测 GET >=2 次，create 后，pre-claim 窗口实证）",
           probed, f"paths={[(r['method'], r['path']) for r in srv._log]}")
        evs = query(db, "SELECT kind FROM events WHERE requirement_id=?", (rid,))
        ok("pre-claim 窗口无 renew 调用",
           not any(r["kind"] == "renew" for r in evs), f"events={[r['kind'] for r in evs]}")
        ok("pre-claim 窗口无板事件（除分发 note）",
           len(evs) == 1 and evs[0]["kind"] == "note", f"events={[r['kind'] for r in evs]}")
        note_seq = query(db, "SELECT seq FROM events WHERE requirement_id=? AND kind='note'",
                         (rid,))[0]["seq"]
        # (b) 测试经 service 层建 active claim -> 周期 renew（计数/事件断言）
        m = MCP(db, extra=extra).start()
        m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "bg-heartbeat"})
        la_before = query(
            db, "SELECT last_activity_at FROM claims WHERE requirement_id=? AND ended_at IS NULL",
            (rid,))[0]["last_activity_at"]
        m.close()
        deadline = time.monotonic() + 15
        renews = []
        while time.monotonic() < deadline:
            renews = query(
                db, "SELECT seq, payload FROM events WHERE requirement_id=? AND kind='renew' "
                    "ORDER BY seq", (rid,))
            if len(renews) >= 2:
                break
            time.sleep(0.05)
        ok("renew 调用次数 >=2（claim active 后周期续租）", len(renews) >= 2, f"n={len(renews)}")
        if renews:
            p = json.loads(renews[0]["payload"])
            d = p.get("delegated") or {}
            ok("renew 事件 payload 带 delegated（kind=statement，P-imp3 受托痕）",
               d.get("kind") == "statement", p)
            ok("delegated basis 指向分发 note seq + session id",
               str(note_seq) in d.get("basis", "") and sid in d.get("basis", ""), d)
        la_after = query(
            db, "SELECT last_activity_at FROM claims WHERE requirement_id=? AND ended_at IS NULL",
            (rid,))[0]["last_activity_at"]
        ok("claim.last_activity_at 递增（renew 触活）",
           datetime.fromisoformat(str(la_after).replace(" ", "T"))
           > datetime.fromisoformat(str(la_before).replace(" ", "T")),
           f"before={la_before} after={la_after}")
        # (c) mock 翻转 outcome=succeeded -> 有界等待（钉死 deadline=15s：心跳 1s 下
        # 翻转后 2 周期内必达，超期＝真失败非 flake）终态 note + bg 进程退出
        srv._cfg["outcome"] = "succeeded"
        deadline = time.monotonic() + 15
        final = []
        while time.monotonic() < deadline:
            final = [c for c in _note_contents(db, rid) if "bg 存活时长" in c]
            if final and not _pid_alive(proc_pid):
                break
            time.sleep(0.05)
        ok("终态 note 存在（含 bg 存活时长语义）", bool(final),
           f"notes={_note_contents(db, rid)}")
        if final:
            c = final[0]
            n_renew = len(query(
                db, "SELECT seq FROM events WHERE requirement_id=? AND kind='renew'", (rid,)))
            ok("终态 note 含 renew 总数（与 DB 事件计数一致）", f"renew 总数: {n_renew}" in c, c)
            ok("终态 note 含 pre-claim 跳过次数（>=1）",
               re.search(r"pre-claim 跳过: [1-9]\d*", c) is not None, c)
            first = c.splitlines()[0]
            ok("终态 note 首行人话（bg 心跳结束 + session id）",
               "bg 心跳结束" in first and sid in first, first)
            ok("终态 note 原因记 session 终态（outcome=succeeded）", "succeeded" in c, c)
        ok("bg 进程退出（用例自清理）",
           proc_pid is not None and not _pid_alive(proc_pid), f"pid={proc_pid}")
    finally:
        # 兜底：deadline 后仍未退出的子进程 kill 再停 mock，禁留孤儿
        if proc_pid is not None and _pid_alive(proc_pid):
            try:
                os.kill(proc_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        stop()


def k_bg_claim_binding():
    print("== B3.1-G28: bg 心跳认领绑定（S9：watcher 绑定启动后首个 active claim；认领结束/变更 "
          "-> 终态 note 记原因后退出；复派新 claim 后旧 watcher 无新增 renew）")
    tmp = Path(tempfile.mkdtemp(prefix="ak-dispatch-bgbind-"))
    db = new_db()
    ws, env_card = _workspace(tmp)
    rid = cli_ok(db, "new", "--title", "bg 认领绑定需求",
                 "--description", f"workspace={ws} env-card={env_card}")["requirement_id"]
    srv, stop = _mock_start({"get_code": 404})
    port = srv.server_address[1]
    extra = _dispatch_env(db, port)
    extra["AGENT_KANBAN_DISPATCH_HEARTBEAT_SEC"] = "1"
    proc_pid = None
    try:
        res = cli(db, "dispatch", "--requirement-id", rid, "--bg", extra=extra)
        ok("dispatch --bg rc=0", res.returncode == 0, f"rc={res.returncode} stderr={res.stderr}")
        proc_pid = json.loads(res.stdout).get("bg_pid")
        # (a) claim A 建立 -> watcher 绑定并周期续租（>=1 条 renew 事件锚定「已绑定」）
        m = MCP(db, extra=extra).start()
        claim_a = m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "worker-a"})["claim_id"]
        deadline = time.monotonic() + 15
        renews_a = []
        while time.monotonic() < deadline:
            renews_a = query(db, "SELECT claim_id FROM events WHERE requirement_id=? AND kind='renew'",
                             (rid,))
            if renews_a:
                break
            time.sleep(0.05)
        ok("claim A active 后 watcher 续租（绑定成立，renew >=1）", bool(renews_a),
           f"n={len(renews_a)}")
        # (b) G28 实锤序列：人面释放（claim A 结束 + 需求回 OPEN）+ 复派产生 claim B。
        # 释放与新认领间 >watcher 读->写间隙（MCP 往返 >> 单次读间隙），无 TOCTOU 窗
        _update(db, "UPDATE claims SET ended_at=? WHERE id=?",
                (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f"), claim_a))
        _set_state(db, rid, "OPEN")
        claim_b = m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "worker-b"})["claim_id"]
        m.close()
        # (c) 旧 watcher 下一探测周期观测到认领变更/消失 -> 终态 note（记原因）+ 进程退出
        deadline = time.monotonic() + 15
        final = []
        while time.monotonic() < deadline:
            final = [c for c in _note_contents(db, rid) if "bg 存活时长" in c]
            if final and not _pid_alive(proc_pid):
                break
            time.sleep(0.05)
        ok("旧 watcher 终态 note 存在（认领结束后退场，S9）", bool(final),
           f"notes={_note_contents(db, rid)}")
        ok("终态 note 恰 1 条（G28 重复终态 note 不复现）", len(final) == 1, f"n={len(final)}")
        if final:
            ok("终态 note 记结束原因（认领变更/需求释放）",
               "认领变更" in final[0] or "需求释放" in final[0], final[0].splitlines()[-1])
        ok("bg 进程退出（旧 watcher 不再存活）",
           proc_pid is not None and not _pid_alive(proc_pid), f"pid={proc_pid}")
        # (d) 越权续租判别：renew 事件 claim_id 恒为 A；claim B 零 renew（BCD I8/S9 核心）
        renews = query(db, "SELECT claim_id FROM events WHERE requirement_id=? AND kind='renew'",
                       (rid,))
        ok("renew 全部锚 claim A（复派后旧 watcher 未续租新 claim）",
           bool(renews) and all(r["claim_id"] == claim_a for r in renews),
           f"claim_ids={[r['claim_id'] for r in renews]} A={claim_a} B={claim_b}")
        ok("claim B 零 renew（旧 watcher 未按需求 id 越权续租）",
           not any(r["claim_id"] == claim_b for r in renews),
           f"B_renews={sum(1 for r in renews if r['claim_id'] == claim_b)}")
        # (f) S9 另一支：绑定认领结束且不复派 -> 「需求释放」退场（确定性：无新 claim 竞态）
        rid2 = cli_ok(db, "new", "--title", "bg 需求释放需求",
                      "--description", f"workspace={ws} env-card={env_card}")["requirement_id"]
        res2 = cli(db, "dispatch", "--requirement-id", rid2, "--bg", extra=extra)
        ok("需求释放支 dispatch --bg rc=0", res2.returncode == 0,
           f"rc={res2.returncode} stderr={res2.stderr}")
        proc_pid2 = json.loads(res2.stdout).get("bg_pid")
        m2 = MCP(db, extra=extra).start()
        claim_c = m2.call_ok("claim_task", {"requirement_id": rid2, "agent_name": "worker-c"})["claim_id"]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if query(db, "SELECT seq FROM events WHERE requirement_id=? AND kind='renew'", (rid2,)):
                break
            time.sleep(0.05)
        _update(db, "UPDATE claims SET ended_at=? WHERE id=?",
                (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f"), claim_c))
        _set_state(db, rid2, "OPEN")
        m2.close()
        deadline = time.monotonic() + 15
        final2 = []
        while time.monotonic() < deadline:
            final2 = [c for c in _note_contents(db, rid2) if "bg 存活时长" in c]
            if final2 and not _pid_alive(proc_pid2):
                break
            time.sleep(0.05)
        ok("不复派时旧 watcher 终态 note 存在", bool(final2),
           f"notes={_note_contents(db, rid2)}")
        if final2:
            ok("终态 note 原因记需求释放（绑定认领已结束）",
               "需求释放" in final2[0], final2[0].splitlines()[-1])
        ok("需求释放支 bg 进程退出",
           proc_pid2 is not None and not _pid_alive(proc_pid2), f"pid={proc_pid2}")
    finally:
        # 兜底：deadline 后仍未退出的子进程 kill 再停 mock，禁留孤儿
        for pid in (proc_pid, locals().get("proc_pid2")):
            if pid is not None and _pid_alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        stop()


def k_bg_renew_binding():
    print("== B3.1-G28-P1: _bg_renew 写边界原子校验（expected_claim_id 与 active claim 同一"
          "写事务内比对；不等 -> 拒写 renew 事件且不延长新 claim 租约，check-then-act 窗口清零）")
    db = new_db()
    rid = cli_ok(db, "new", "--title", "renew 绑定需求")["requirement_id"]
    sid = f"ses_req_{rid[:8]}"
    m = MCP(db).start()
    claim_a = m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "worker-a"})["claim_id"]
    # P1 窗口终态的确定性重演：claim A 已结束、claim B active（绕开心跳时序，直打写边界）
    _update(db, "UPDATE claims SET ended_at=? WHERE id=?",
            (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f"), claim_a))
    _set_state(db, rid, "OPEN")
    claim_b = m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "worker-b"})["claim_id"]
    m.close()
    lease_b = query(db, "SELECT lease_expires_at FROM claims WHERE id=?", (claim_b,))[0]["lease_expires_at"]
    prev, akdb, _, _, _ = _ak_import(db)
    try:
        from agent_kanban import dispatch as disp
        # (a) 旧 watcher 语义：绑定 A 但 active=B -> 拒写（I8：心跳只续它绑定的认领）
        rejected = False
        try:
            disp._bg_renew(rid, sid, None, expected_claim_id=claim_a)
        except disp.BusinessError:
            rejected = True
        ok("expected_claim_id != active claim -> 拒绝（BusinessError）", rejected, "")
        renews = query(db, "SELECT claim_id FROM events WHERE requirement_id=? AND kind='renew'",
                       (rid,))
        ok("拒写路径零 renew 事件（claim B 不被越权续租）", not renews, f"n={len(renews)}")
        lease_b2 = query(db, "SELECT lease_expires_at FROM claims WHERE id=?",
                         (claim_b,))[0]["lease_expires_at"]
        ok("拒写路径 claim B lease_expires_at 不变（租约未被不可见第三方延长）",
           lease_b2 == lease_b, f"{lease_b} -> {lease_b2}")
        # (b) 本 watcher 语义：绑定 B 且 active=B -> 正常写一条
        disp._bg_renew(rid, sid, None, expected_claim_id=claim_b)
        renews = query(db, "SELECT claim_id FROM events WHERE requirement_id=? AND kind='renew'",
                       (rid,))
        ok("expected == active claim -> 正常写一条 renew", len(renews) == 1, f"n={len(renews)}")
        if renews:
            ok("renew 事件锚 claim B", renews[0]["claim_id"] == claim_b, renews[0]["claim_id"])
    finally:
        asyncio.run(_ak_dispose(akdb))
        _ak_restore(prev)


def _seed_note(db: Path, rid: str, seq: int, content: str) -> None:
    """note 事件种子（I8 basis 锚用例：直插 content 可控的 note，不耦合 op 层）。"""
    _update(db,
            "INSERT INTO events (id, requirement_id, kind, severity, title, content, "
            "actor_surface, seq, ts) VALUES (?, ?, 'note', 'info', 'note', ?, 'cli', ?, "
            "'2026-10-29 00:00:00')",
            (uuid.uuid4().hex, rid, content, seq))


def k_bg_note_basis():
    print("== B3.1-G28: renew delegated basis 锚分发 note（I8：_bg_note_seq 只取 content 前缀 "
          "「分发：」的最新 note；worker 认领后写的接单确认 note 不夺锚；无分发 note -> None）")
    db = new_db()
    rid = cli_ok(db, "new", "--title", "basis 锚需求")["requirement_id"]
    _seed_note(db, rid, 101, "分发：basis 锚需求，会话 ses_req_x，模型 m\nsession id: ses_req_x")
    _seed_note(db, rid, 102, "接单确认\n理解：...（worker 认领后写，不得夺锚）")
    _seed_note(db, rid, 103, "进度：做到一半")
    rid2 = cli_ok(db, "new", "--title", "无分发 note 需求")["requirement_id"]
    _seed_note(db, rid2, 101, "接单确认\n理解：...")
    prev, akdb, _, _, _ = _ak_import(db)
    try:
        from agent_kanban import dispatch as disp
        got = disp._bg_note_seq(rid)
        ok("basis 锚最新「分发：」note（seq 101），后续非分发 note 不夺锚",
           got == 101, f"got={got}")
        got2 = disp._bg_note_seq(rid2)
        ok("无分发 note -> None（basis 记缺失，不误锚接单确认类 note）",
           got2 is None, f"got={got2}")
    finally:
        asyncio.run(_ak_dispose(akdb))
        _ak_restore(prev)


def _seed_review(db: Path, rid: str, seq: int, evidence, kind: str = "review_request") -> None:
    """直插事件种子（读路径测试不耦合状态机；evidence=None 模拟缺键，str 模拟非 dict）。"""
    payload = ({"evidence": evidence, "summary_line": f"seed r{seq}"}
               if evidence is not None else {"summary_line": "no evidence key"})
    _update(db,
            "INSERT INTO events (id, requirement_id, kind, severity, title, payload, actor_surface, seq, ts) "
            "VALUES (?, ?, ?, 'attention', 'seeded', ?, 'mcp', ?, '2026-10-28 00:00:00')",
            (f"{seq:032x}", rid, kind, json.dumps(payload), seq))


def k_history_assembly():
    print("== B3-T2: A2 历轮交付物装配（续接稿/派发稿双点 + 无历史零差异 + evidence 可选键形态 + 畸形 payload + 无存在检查）")
    tmp = Path(tempfile.mkdtemp(prefix="ak-dispatch-history-"))
    db = new_db()
    ws, env_card = _workspace(tmp)
    doc1 = ws / "deliverables" / "v1.md"
    doc1.parent.mkdir()
    doc1.write_text("v1", encoding="utf-8")
    rid = cli_ok(db, "new", "--title", "A2 装配需求",
                 "--description", f"workspace={ws} env-card={env_card}")["requirement_id"]
    sid = f"ses_req_{rid[:8]}"
    # 六种轮次形态（BCD §5 E1/E3 + P-imp2）：9001=doc+note；9002=仅 note；9003=doc/note 皆缺（跳过）；
    # 9004=缺 evidence 键（跳过）；9005=doc 指不存在路径（字面输出，无存在检查）；9006=evidence 非 dict（跳过不崩）；
    # 9007=非 review_request 事件但含 evidence（跳过）。插入序 != seq 序：9005 先入（删 order_by 必乱序）。
    _seed_review(db, rid, 9005, {"document": "/nonexistent/b3-nonexistent.md", "test_summary": "s5"})
    _seed_review(db, rid, 9001, {"document": str(doc1), "note": "遗留：X 待核", "test_summary": "s1"})
    _seed_review(db, rid, 9002, {"note": "第 2 轮无交付物路径", "test_summary": "s2"})
    _seed_review(db, rid, 9003, {"test_summary": "s3"})
    _seed_review(db, rid, 9004, None)
    _seed_review(db, rid, 9006, "oops-not-a-dict")
    _seed_review(db, rid, 9007, {"document": "/note-event-should-not-appear.md"}, kind="note")
    _set_state(db, rid, "REOPEN")
    srv, stop = _mock_start({"get_code": 404})
    srv._exists[sid] = True  # 预置 session 存在 -> 复用路径（续接稿），BCD Q2 主命中场景
    port = srv.server_address[1]
    extra = _dispatch_env(db, port)
    try:
        res = cli(db, "dispatch", "--requirement-id", rid,
                  "--model", "ks-cp/glm-5-3-flash", "--budget", "10m", extra=extra)
        ok("REOPEN 复派 rc=0", res.returncode == 0, f"rc={res.returncode} stderr={res.stderr}")
        prompts = [r for r in srv._log
                   if r["method"] == "POST" and r["path"] == f"/api/session/{sid}/prompt"]
        ok("续接稿已投递", len(prompts) == 1, f"n={len(prompts)}")
        if prompts:
            t = json.loads(prompts[0]["body"])["text"]
            ok("续接稿含历史节标题（BCD E1 字面）",
               "## 历轮交付物（本需求历史 request_review，seq 升序）" in t, t)
            ok("轮 1 交付物字面", f"- 第 1 轮（seq 9001）: 交付物 {doc1}" in t, t)
            ok("轮 1 note 字面", "- note: 遗留：X 待核" in t, t)
            ok("轮 2 无 doc 只出 note 行（BCD E3）",
               "- 第 2 轮（seq 9002）" not in t and "- note: 第 2 轮无交付物路径" in t, t)
            ok("轮 3 doc/note 皆缺跳过", "seq 9003" not in t, t)
            ok("缺 evidence 键跳过不崩", "seq 9004" not in t, t)
            ok("不存在路径按字面输出且无警示（P-imp2 无存在检查）",
               "- 第 3 轮（seq 9005）: 交付物 /nonexistent/b3-nonexistent.md" in t and "警示" not in t, t)
            ok("非 dict evidence 跳过不崩", "seq 9006" not in t, t)
            ok("非 review_request 事件不入节（历史源边界）",
               "note-event-should-not-appear" not in t and "seq 9007" not in t, t)
            anchors = ("seq 9001", "- note: 遗留：X 待核",
                       "- note: 第 2 轮无交付物路径", "seq 9005")
            present = all(a in t for a in anchors)
            ok("升序锚点齐（先验存在，缺锚不裸抛）", present,
               str([a for a in anchors if a not in t]))
            ok("轮次序升序（插入序与 seq 序相反）",
               present and t.index(anchors[0]) < t.index(anchors[1])
               < t.index(anchors[2]) < t.index(anchors[3]), "")
            ok("节位置在摘要之后（续接稿）",
               "## 历轮交付物" in t
               and t.index("## 历轮交付物") > t.index("- 子任务进度: 0/0"), "")
            ok("既有摘要行不变（回归）", "- state: REOPEN" in t and "子任务进度: 0/0" in t, t)
        # 无历史需求 -> 新建派发稿零差异（BCD S2/E2）
        rid2 = cli_ok(db, "new", "--title", "A2 无历史需求",
                      "--description", f"workspace={ws} env-card={env_card}")["requirement_id"]
        res2 = cli(db, "dispatch", "--requirement-id", rid2,
                   "--model", "ks-cp/glm-5-3-flash", "--budget", "10m", extra=extra)
        ok("无历史 dispatch rc=0", res2.returncode == 0, f"rc={res2.returncode} stderr={res2.stderr}")
        p2 = [r for r in srv._log
              if r["method"] == "POST" and r["path"] == f"/api/session/ses_req_{rid2[:8]}/prompt"]
        ok("新需求派发稿已投递", len(p2) == 1, f"n={len(p2)}")
        if p2:
            t2 = json.loads(p2[0]["body"])["text"]
            ok("无历史无历史节（无占位，BCD I2）", "历轮交付物" not in t2, t2)
            ok("五要素逐字回归", "## 任务指针" in t2 and "## 交付规格" in t2 and "## 红线提醒" in t2, t2)
        # 有历史但 session 不存在 -> create 分支仍装历史节，位置在交付规格与红线提醒之间
        rid3 = cli_ok(db, "new", "--title", "A2 建链有历史需求",
                      "--description", f"workspace={ws} env-card={env_card}")["requirement_id"]
        _seed_review(db, rid3, 9101, {"document": "/create-branch-v1.md"})
        res3 = cli(db, "dispatch", "--requirement-id", rid3,
                   "--model", "ks-cp/glm-5-3-flash", "--budget", "10m", extra=extra)
        ok("建链有历史 dispatch rc=0", res3.returncode == 0, f"rc={res3.returncode} stderr={res3.stderr}")
        p3 = [r for r in srv._log
              if r["method"] == "POST" and r["path"] == f"/api/session/ses_req_{rid3[:8]}/prompt"]
        ok("建链派发稿已投递", len(p3) == 1, f"n={len(p3)}")
        if p3:
            t3 = json.loads(p3[0]["body"])["text"]
            ok("建链派发稿含历史节", "- 第 1 轮（seq 9101）: 交付物 /create-branch-v1.md" in t3, t3)
            ok("历史节位于交付规格与红线提醒之间",
               "## 历轮交付物" in t3 and "## 交付规格" in t3 and "## 红线提醒" in t3
               and t3.index("## 交付规格") < t3.index("## 历轮交付物") < t3.index("## 红线提醒"), t3)
    finally:
        stop()


def k_dispatch_placement():
    print("== 落点纪律: 交付规格带环境卡产物落点 + 交付物永久位置提醒；无落点给跨项目指路")
    tmp = Path(tempfile.mkdtemp(prefix="ak-dispatch-place-"))
    db = new_db()
    ws1, env1 = _workspace(tmp)
    env1.write_text(
        "## 环境卡\n"
        f"- workspace: {ws1}；产物落点: docs/（文档）/ tests/（用例）；临时产物: /home/x/tmp/\n"
        "- 红线: 禁推 main\n", encoding="utf-8")
    ws2 = tmp / "ws2"
    ws2.mkdir()
    env2 = ws2 / "AGENTS.md"
    env2.write_text(f"## 环境卡\n- workspace: {ws2}\n- 红线: 禁推 main\n", encoding="utf-8")
    rids = [cli_ok(db, "new", "--title", t, "--description", f"workspace={w} env-card={e}")
            ["requirement_id"]
            for t, w, e in (("落点声明需求", ws1, env1), ("落点缺失需求", ws2, env2))]
    srv, stop = _mock_start({})
    extra = _dispatch_env(db, srv.server_address[1])
    try:
        for rid in rids:
            res = cli(db, "dispatch", "--requirement-id", rid, extra=extra)
            ok(f"dispatch rc=0 ({rid[:8]})", res.returncode == 0,
               f"rc={res.returncode} stderr={res.stderr}")

        def prompt_of(rid):
            path = f"/api/session/ses_req_{rid[:8]}/prompt"
            rows = [r for r in srv._log if r["method"] == "POST" and r["path"] == path]
            return json.loads(rows[0]["body"])["text"] if rows else None

        t1, t2 = prompt_of(rids[0]), prompt_of(rids[1])
        ok("两稿均投递", t1 is not None and t2 is not None, f"{t1 is not None}/{t2 is not None}")
        if t1:
            ok("产物落点＝环境卡字段原文（分号分隔字段可抽取）",
               "- 产物落点: docs/（文档）/ tests/（用例）" in t1, t1)
            ok("交付物永久位置提醒在规格内（禁 tmp 作唯一副本）",
               "禁作唯一副本" in t1 and t1.index("## 交付规格") < t1.index("禁作唯一副本"), t1)
            # b6（板上 7226dfd6）：子任务状态迁移提醒须在交付规格节（与落点提醒同位置），散落别节必红
            spec = t1[t1.index("## 交付规格"):t1.index("\n## ", t1.index("## 交付规格") + 1)]
            ok("交付规格含子任务状态迁移提醒（开工置 in_progress + 进度/重试信号唯一来源）",
               "开工置 in_progress" in spec and "唯一来源" in spec, spec)
            ok("状态迁移提醒明说服务端不硬拒（todo->done 也合法）",
               "不硬拒" in spec and "todo->done 也合法" in spec, spec)
        if t2:
            ok("无落点 -> 指路跨项目归属与问人（不静默省略）",
               "- 产物落点: 环境卡未声明" in t2 and "问人" in t2
               and "禁在本仓新建目录" in t2, t2)
            ok("状态迁移提醒为无条件行（无落点需求也带）",
               "开工置 in_progress" in t2, t2)
    finally:
        stop()


def k_resume_model_204():
    print("== B2-T2: resume --model 换模（switchModel 返回 204 亦成功：先 switchModel 后 prompt 后 wait）")
    tmp = Path(tempfile.mkdtemp(prefix="ak-resume-model-"))
    db = new_db()
    ws, env_card = _workspace(tmp)
    rid = cli_ok(db, "new", "--title", "resume 换模需求",
                 "--description", f"workspace={ws} env-card={env_card}")["requirement_id"]
    _set_state(db, rid, "REOPEN")
    sid = f"ses_req_{rid[:8]}"
    srv, stop = _mock_start({"get_code": 404})  # model 端点缺省 204（对齐真服务）
    srv._exists[sid] = True
    port = srv.server_address[1]
    extra = _dispatch_env(db, port)
    try:
        res = cli(db, "resume", "--requirement-id", rid, "继续", "--model", "other/model", extra=extra)
        ok("rc=0（switchModel 204 被接受）", res.returncode == 0,
           f"rc={res.returncode} stderr={res.stderr}")
        ok("mock switchModel 实际回码 204", srv._model_codes == [204],
           f"codes={srv._model_codes}")
        log = list(srv._log)
        model_idx = [i for i, r in enumerate(log)
                     if r["method"] == "POST" and r["path"] == f"/api/session/{sid}/model"]
        prompt_idx = [i for i, r in enumerate(log)
                      if r["method"] == "POST" and r["path"] == f"/api/session/{sid}/prompt"]
        wait_idx = [i for i, r in enumerate(log)
                    if r["method"] == "POST" and r["path"] == f"/api/experimental/session/{sid}/wait"]
        ok("switchModel 后仍投递 prompt 并进入 wait",
           model_idx and prompt_idx and wait_idx and model_idx[0] < prompt_idx[0] < wait_idx[0],
           f"model={model_idx} prompt={prompt_idx} wait={wait_idx}")
        ok("prompt 文本逐字＝继续", prompt_idx and json.loads(log[prompt_idx[0]]["body"])["text"] == "继续",
           log[prompt_idx[0]]["body"] if prompt_idx else "")
    finally:
        stop()


def k_resume_model_err():
    print("== B2-T2: resume --model 换模失败（switchModel 4xx/5xx -> 非零退出 + 可操作错误，无 prompt/wait）")
    tmp = Path(tempfile.mkdtemp(prefix="ak-resume-modelerr-"))
    db = new_db()
    ws, env_card = _workspace(tmp)
    rid = cli_ok(db, "new", "--title", "resume 换模失败需求",
                 "--description", f"workspace={ws} env-card={env_card}")["requirement_id"]
    _set_state(db, rid, "REOPEN")
    sid = f"ses_req_{rid[:8]}"
    srv, stop = _mock_start({"get_code": 404, "model_code": 500})
    srv._exists[sid] = True
    port = srv.server_address[1]
    extra = _dispatch_env(db, port)
    try:
        for code in (400, 500):
            srv._cfg["model_code"] = code
            res = cli(db, "resume", "--requirement-id", rid, "继续", "--model", "other/model", extra=extra)
            ok(f"switchModel {code} 非零退出", res.returncode != 0,
               f"rc={res.returncode} stderr={res.stderr}")
            ok(f"switchModel {code} 报可操作错误（失败语义 + 重试/服务版本指引）",
               "switchModel 失败" in res.stderr and "--model" in res.stderr
               and ("重试" in res.stderr or "服务版本" in res.stderr), res.stderr)
        log = list(srv._log)
        ok("换模失败不投 prompt",
           not any(r["method"] == "POST" and "prompt" in r["path"] for r in log),
           f"log={[r['path'] for r in log]}")
        ok("换模失败不进 wait",
           not any("wait" in r["path"] for r in log),
           f"log={[r['path'] for r in log]}")
    finally:
        stop()


def _fake_mcp_list(tmp: Path, name: str, body: str) -> str:
    """写可执行 fake `opencode mcp list` 脚本（状态经 $AK_FAKE_MCP_CALLS 调用计数文件）。"""
    p = tmp / name
    p.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    os.chmod(p, 0o755)
    return str(p)


def k_mcp_precheck_flake_recovers():
    print("== b4-a4: 预检首跑 flake（No MCP servers configured）复跑一次即恢复，派发继续")
    tmp = Path(tempfile.mkdtemp(prefix="ak-mcp-flake-"))
    db = new_db()
    ws, env_card = _workspace(tmp)
    rid = cli_ok(db, "new", "--title", "预检 flake 需求",
                 "--description", f"workspace={ws} env-card={env_card}")["requirement_id"]
    calls = tmp / "mcp-calls"
    # 首次调用回 flake 文本，复跑（第 2 次起）回 kanban connected——钉死 2026-10-30
    # Gmail 批实测的首跑 flake 形态（5defed11 note：配置齐全时首跑仍偶报）
    fake = _fake_mcp_list(tmp, "mcp-list-flake.sh",
                          "if [ -f \"$AK_FAKE_MCP_CALLS\" ]; then\n"
                          "  n=$(wc -l < \"$AK_FAKE_MCP_CALLS\" | tr -d ' ')\n"
                          "else\n  n=0\nfi\n"
                          "echo x >> \"$AK_FAKE_MCP_CALLS\"\n"
                          "if [ \"$n\" -eq 0 ]; then\n"
                          "  echo 'No MCP servers configured'\n"
                          "else\n"
                          "  printf '\u2713 kanban  connected\\n'\n"
                          "fi\n")
    srv, stop = _mock_start({"get_code": 404})
    port = srv.server_address[1]
    extra = _dispatch_env(db, port)
    extra["AGENT_KANBAN_DISPATCH_MCP_LIST_CMD"] = fake
    extra["AK_FAKE_MCP_CALLS"] = str(calls)
    try:
        res = cli(db, "dispatch", "--requirement-id", rid, extra=extra)
        ok("flake 复跑恢复后派发 rc=0", res.returncode == 0,
           f"rc={res.returncode} stderr={res.stderr}")
        ok("fake 恰被调用 2 次（首跑 flake + 复跑）",
           calls.exists() and len(calls.read_text(encoding="utf-8").splitlines()) == 2,
           calls.read_text(encoding="utf-8") if calls.exists() else "未调用")
        log = list(srv._log)
        creates = [r for r in log if r["method"] == "POST" and r["path"] == "/api/session"]
        ok("预检恢复 -> session 正常创建（主链未中断）", len(creates) == 1, f"n={len(creates)}")
        ok("板 note 恰 1 条（正常分发 note，无失败 note）",
           len(_note_contents(db, rid)) == 1, f"n={len(_note_contents(db, rid))}")
    finally:
        stop()


def k_mcp_precheck_unreachable_rejects():
    print("== b4-a4: 预检复跑仍不可达 -> mcp_unreachable 拒派（不建会话、不写板 note、不复跑第三次）")
    tmp = Path(tempfile.mkdtemp(prefix="ak-mcp-unreach-"))
    db = new_db()
    ws, env_card = _workspace(tmp)
    rid = cli_ok(db, "new", "--title", "预检不可达需求",
                 "--description", f"workspace={ws} env-card={env_card}")["requirement_id"]
    calls = tmp / "mcp-calls"
    # 持久不可达（非 flake）：kanban 条目存在但启动失败——真实形态如 opencode.json
    # 注册命令不存在（本批 probe 实测输出形态）
    fake = _fake_mcp_list(tmp, "mcp-list-broken.sh",
                          "echo x >> \"$AK_FAKE_MCP_CALLS\"\n"
                          "printf '\u2717 kanban  failed: NotFound: ChildProcess.spawn (no-such-cmd mcp)\\n'\n")
    srv, stop = _mock_start({"get_code": 404})
    port = srv.server_address[1]
    extra = _dispatch_env(db, port)
    extra["AGENT_KANBAN_DISPATCH_MCP_LIST_CMD"] = fake
    extra["AK_FAKE_MCP_CALLS"] = str(calls)
    try:
        code, msg = cli_err(db, "dispatch", "--requirement-id", rid, extra=extra)
        ok("复跑仍不可达 -> 错误码 mcp_unreachable", code == "mcp_unreachable", code)
        ok("错误消息含目标目录（可操作：去该目录修 opencode.json）", str(ws) in msg, msg)
        log = list(srv._log)
        ok("fail-closed：预检先于服务交互，session 未创建",
           not any(r["method"] == "POST" and r["path"] == "/api/session" for r in log),
           f"log={[r['path'] for r in log]}")
        ok("投递前中止不写板 note（与状态门/服务不可达同契约）",
           len(_note_contents(db, rid)) == 0, f"n={len(_note_contents(db, rid))}")
        ok("fake 恰被调用 2 次（复跑一次，不第三次）",
           calls.exists() and len(calls.read_text(encoding="utf-8").splitlines()) == 2,
           calls.read_text(encoding="utf-8") if calls.exists() else "未调用")
    finally:
        stop()


def k_b5_brief_fallback():
    print("== b5-a3: 派发稿交付规格节含看板兜底指令（停止并报告 / 写板面走 CLI 正典路径 / 不硬写代码不静默继续）")
    tmp = Path(tempfile.mkdtemp(prefix="ak-b5-fallback-"))
    db = new_db()
    ws, env_card = _workspace(tmp)
    rid = cli_ok(db, "new", "--title", "兜底指令需求",
                 "--description", f"workspace={ws} env-card={env_card}")["requirement_id"]
    sid = f"ses_req_{rid[:8]}"
    srv, stop = _mock_start({"get_code": 404})
    port = srv.server_address[1]
    extra = _dispatch_env(db, port)
    try:
        res = cli(db, "dispatch", "--requirement-id", rid, extra=extra)
        ok("dispatch rc=0", res.returncode == 0,
           f"rc={res.returncode} stderr={res.stderr}")
        prompts = [r for r in srv._log if r["method"] == "POST"
                   and r["path"] == f"/api/session/{sid}/prompt"]
        ok("派发稿已投递", len(prompts) == 1, f"n={len(prompts)}")
        if prompts:
            t = json.loads(prompts[0]["body"])["text"]
            # 落点判据：兜底行须在交付规格节（与落点提醒同位置），散落别节必红
            spec_start = t.index("## 交付规格")
            spec = t[spec_start:t.index("\n## ", spec_start + 1)]
            ok("交付规格节含兜底指令（停止并报告 + kanban 工具）",
               "立即停止并报告" in spec and "kanban" in spec, spec)
            ok("兜底指令含触发面（预检跳过或环境漂移）",
               "预检跳过或环境漂移" in spec, spec)
            ok("兜底指令含写板面不可达出路（CLI 正典路径）",
               "CLI 正典路径" in spec, spec)
            ok("兜底指令禁硬写代码/静默继续",
               "不硬写代码" in spec and "不静默继续" in spec, spec)
    finally:
        stop()
