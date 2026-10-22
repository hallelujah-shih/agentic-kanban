"""AC harness 基础设施：raw MCP stdio 客户端、CLI/DB 助手、oracle 直查。

oracle 纪律：断言逐字引自 PRD；DB 事后用 sqlite3 直查文件（读数据非读实现代码）。
并发架构：真实多进程 MCP stdio 客户端（newline-delimited JSON-RPC，每实例一子进程）。
红跑：AGENT_KANBAN_SRC 指向空目录可对"空实现"全红留档。
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_PY = REPO_ROOT / ".venv" / "bin" / "python"
SRC = Path(os.environ.get("AGENT_KANBAN_SRC", REPO_ROOT / "src"))
CLI = REPO_ROOT / "cli.py"
TIMEOUT = 30
PROTOCOL = "2025-11-25"

RESULTS: list[tuple[str, bool, str]] = []


def ok(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))
    print(f"    {'PASS' if cond else 'FAIL'}  {name}  {detail}")


def new_db() -> Path:
    return Path(tempfile.mkdtemp(prefix="ak-ac-")) / "kanban.db"


def env_for(db: Path, extra: dict | None = None) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env["AGENT_KANBAN_DB"] = str(db)
    if extra:
        env.update(extra)
    return env


def cli(db: Path, *args: str, extra: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(VENV_PY), str(CLI), *args],
        capture_output=True, text=True, env=env_for(db, extra),
        cwd=str(REPO_ROOT), timeout=TIMEOUT,
    )


def cli_ok(db: Path, *args: str, extra: dict | None = None) -> dict:
    res = cli(db, *args, extra=extra)
    if res.returncode != 0:
        raise AssertionError(f"cli {args} failed: rc={res.returncode} stderr={res.stderr}")
    return json.loads(res.stdout)


def cli_err(db: Path, *args: str, extra: dict | None = None) -> tuple[str, str]:
    res = cli(db, *args, extra=extra)
    if res.returncode == 0:
        raise AssertionError(f"cli {args} unexpectedly succeeded: {res.stdout}")
    code, _, message = res.stderr.strip().partition(":")
    return code.strip(), message.strip()


def seed_req(db: Path, title: str = "requirement") -> str:
    return cli_ok(db, "new", "--title", title)["requirement_id"]


def seed_reopen(db: Path, req_id: str) -> None:
    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE requirements SET state='REOPEN' WHERE id=?", (req_id,))
    conn.commit()
    conn.close()


def query(db: Path, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


class MCP:
    """raw newline-delimited JSON-RPC MCP stdio 客户端（每实例一子进程）。"""

    def __init__(self, db: Path, *, extra: dict | None = None, hook: str | None = None,
                 marker: Path | None = None):
        self.db = db
        self.extra = extra or {}
        self.hook = hook
        self.marker = marker
        self.proc: subprocess.Popen | None = None
        self._id = 0
        self._alive = False

    def start(self) -> "MCP":
        env = env_for(self.db, self.extra)
        if self.hook:
            env["AGENT_KANBAN_TEST_CLAIM_HOOK"] = self.hook
        if self.marker:
            env["AGENT_KANBAN_TEST_CLAIM_HOOK_MARKER"] = str(self.marker)
        self.proc = subprocess.Popen(
            [str(VENV_PY), "-m", "agent_kanban.mcp"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, cwd=str(REPO_ROOT),
        )
        self._alive = True
        rid = self._send("initialize", {
            "protocolVersion": PROTOCOL,
            "capabilities": {},
            "clientInfo": {"name": "ac-harness", "version": "0.1.0"},
        })
        init = self._read_until(rid)
        if "result" not in init:
            self.close()
            raise RuntimeError(f"initialize failed: {init}")
        self._send("notifications/initialized", None)
        return self

    def _send(self, method: str, params: dict | None) -> int:
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            msg["params"] = params
        assert self.proc and self.proc.stdin
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        self.proc.stdin.flush()
        return self._id

    def _read_until(self, req_id: int, timeout: float = TIMEOUT) -> dict:
        assert self.proc and self.proc.stdout
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                raise EOFError("server stdout closed")
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == req_id:
                return msg
            if "method" in msg and "id" in msg:  # server 发起的请求（ping 等）
                if msg["method"] == "ping":
                    reply = {"jsonrpc": "2.0", "id": msg["id"], "result": {}}
                else:
                    reply = {"jsonrpc": "2.0", "id": msg["id"],
                             "error": {"code": -32601, "message": "method not found"}}
                self.proc.stdin.write((json.dumps(reply) + "\n").encode())
                self.proc.stdin.flush()
        raise TimeoutError(f"no response for id {req_id}")

    def rpc(self, method: str, params: dict) -> dict:
        rid = self._send(method, params)
        resp = self._read_until(rid)
        if "error" in resp:
            raise RuntimeError(f"jsonrpc error: {resp['error']}")
        return resp["result"]

    def call(self, name: str, args: dict, meta: dict | None = None) -> dict:
        params = {"name": name, "arguments": args}
        if meta:
            params["_meta"] = meta
        return self.rpc("tools/call", params)

    def call_ok(self, name: str, args: dict, meta: dict | None = None) -> dict:
        res = self.call(name, args, meta=meta)
        if res.get("isError"):
            raise AssertionError(f"{name} failed: {res}")
        return json.loads(res["content"][0]["text"])

    def call_err(self, name: str, args: dict, meta: dict | None = None) -> tuple[str, str]:
        res = self.call(name, args, meta=meta)
        if not res.get("isError"):
            raise AssertionError(f"{name} unexpectedly succeeded: {res}")
        payload = json.loads(res["content"][0]["text"])
        return payload["code"], payload.get("task_id") or ""

    def list_tools(self) -> list[str]:
        result = self.rpc("tools/list", {})
        return [t["name"] for t in result.get("tools", [])]

    def kill(self) -> None:
        if self._alive and self.proc:
            self.proc.kill()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            self._alive = False

    def close(self) -> None:
        if self._alive and self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
            self._alive = False
