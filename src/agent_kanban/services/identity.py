"""actor 派生：接口面 -> (surface, conn)。不接受调用方传入（PRD 5.1/ADR 0002/P1-1）。"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from ..errors import BusinessError

if TYPE_CHECKING:
    from mcp.server.mcpserver.context import Context

CLI_CONN = "cli"


def _http_sid(ctx: "Context") -> str | None:
    """HTTP transport 服务端铸币 MCP session id（PRD 5.1 系统观测）。
    SDK 自述 ctx.headers 是 client-supplied input（P1-1：不作 actor_conn），
    sid 取服务端连接对象（connection.session_id），非客户端头。"""
    try:
        connection = ctx.session._connection
        return getattr(connection, "session_id", None)
    except Exception:
        return None


def mcp_actor(ctx: "Context | None", fallback_conn: str) -> tuple[str, str]:
    """mcp 面：HTTP transport -> actor_conn = 服务端铸币 session id（http:<sid> 前缀，
    与 stdio conn-* 区分）；无 session 拒绝（不落进程级 CONN_ID）。
    stdio -> 优先 opencode 会话 id（外部引用），否则进程级 conn id。"""
    surface = "mcp"
    if ctx is None:
        return surface, fallback_conn
    # HTTP 判定：ctx.headers 仅 HTTP transport 填充（stdio 的 request 为 None）
    try:
        headers = getattr(ctx.request_context.request, "headers", None)
    except Exception:
        headers = None
    if headers is not None:
        sid = _http_sid(ctx)
        if not sid:
            raise BusinessError(
                "illegal_state", "http mcp request without server-minted session id"
            )
        return surface, f"http:{sid}"
    conn = None
    try:
        meta = ctx.request_context.meta
    except Exception:
        meta = None
    if isinstance(meta, dict):
        conn = meta.get("ai.opencode/sessionID")
    return surface, conn or fallback_conn


def cli_actor() -> tuple[str, str]:
    return "cli", CLI_CONN


def rest_actor() -> tuple[str, str]:
    """REST 面（PRD 5.1 枚举无 rest，用 conn 区分传输）：surface='cli'（人面语义），
    conn='rest:<短随机>'（服务端派生）。"""
    return "cli", f"rest:{uuid.uuid4().hex[:8]}"
