"""B2 dispatch 主链用例（T1 服务发现/状态门/create/prompt/wait/note；T2 复用/resume；
T3 超时契约 + 投递失败/投递后异常留痕 + resume 错误分支）。

oracle 纪律：断言引 plan.md「dispatch 步骤 1-10」+「验证锚」/ BCD b2-dispatch.md
（§3 P-imp1/P-imp2/P-imp4/P-imp6、§4 S1/S4/S5、§5 E7、§7 I1/I2/I3/I4/I6/I7）/
SKILL.md「派发方协议」（派发稿五要素 + 留痕条款）。mock opencode 服务＝测试进程内
threaded http.server（port=0 内核分配 + 读 server_address，无 bind-close 竞态）：
请求全留痕（method/path/body），行为可配置（GET 200/404/401、outcome、wait 阻塞、
prompt_code 可配失败）。超时确定性锚＝mock 侧 _wait_completed 未被记完成（禁墙钟）。
红跑：dispatch 子命令未实现前 argparse invalid choice -> 全红。
"""

from __future__ import annotations

import json
import re
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ac_cases_k import _set_state
from ac_lib import REPO_ROOT, cli, cli_ok, env_for, new_db, ok, query


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
            entry["body"] = json.dumps({"id": m.group(1), "outcome": cfg.get("outcome")})
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
            self._send(200, b"{}")
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
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, lambda: srv.shutdown()


def _workspace(tmp: Path) -> tuple[Path, Path]:
    ws = tmp / "ws"
    ws.mkdir()
    env_card = ws / "AGENTS.md"
    env_card.write_text(
        "## 环境卡\n- workspace: %s\n- 红线: 禁推 main；禁写生产 DB\n" % ws, encoding="utf-8")
    return ws, env_card


def _note_contents(db, rid: str) -> list[str]:
    rows = query(db, "SELECT content FROM events WHERE requirement_id=? AND kind='note'", (rid,))
    return [r["content"] for r in rows if r["content"]]


def _dispatch_env(db, port: int) -> dict:
    return env_for(db, {"AGENT_KANBAN_OPENCODE_URL": f"http://127.0.0.1:{port}",
                        "AGENT_KANBAN_OPENCODE_AUTH": "none"})


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
               (REPO_ROOT / "skills" / "agent-kanban" / "SKILL.md").as_posix() in t)
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
