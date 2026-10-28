"""B2 dispatch 主链用例（T1：服务发现 + 状态门 + 存在检查/create + prompt + 同步 wait + 板 note）。

oracle 纪律：断言引 plan.md「dispatch 步骤 1-10」+「验证锚」/ BCD b2-dispatch.md
（§3 P-imp1/P-imp4/P-imp6、§4 S1/S4、§7 I1/I2/I3/I6/I7）/ SKILL.md「派发方协议」
（派发稿五要素 + 留痕条款）。mock opencode 服务＝测试进程内 threaded http.server：
请求全留痕（method/path/body），行为可配置（GET 200/404/401、outcome、wait 阻塞）。
红跑：dispatch 子命令未实现前 argparse invalid choice -> 全红。
"""

from __future__ import annotations

import json
import re
import socket
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
            self._send(200, body.encode())
        elif re.fullmatch(r"/api/session/[^/]+/prompt", path):
            self._send(200, b"{}")
        elif re.fullmatch(r"/api/session/[^/]+/model", path):
            self._send(200, b"{}")
        elif re.fullmatch(r"/api/experimental/session/[^/]+/wait", path):
            delay = float(self.server._cfg.get("wait_delay", 0))
            if delay:
                time.sleep(delay)
            self.server._wait_completed = True
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self._send(404)


def _find_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _mock_start(port: int, cfg: dict):
    srv = ThreadingHTTPServer(("127.0.0.1", port), _MockOpencode)
    srv._cfg = cfg
    srv._log = []
    srv._wait_completed = False
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
    srv, stop = _mock_start(_find_port(), {"get_code": 404})
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
        ok("mock 无 delete 调用", not any("delete" in r["path"].lower() for r in log))
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
    srv, stop = _mock_start(_find_port(), {"get_code": 404})
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
    srv, stop = _mock_start(_find_port(), {"get_code": 401})
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
