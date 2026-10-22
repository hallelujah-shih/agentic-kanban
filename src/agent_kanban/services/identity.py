"""actor 派生：接口面 -> (surface, conn)。不接受调用方传入（PRD 5.1/ADR 0002）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.mcpserver.context import Context

CLI_CONN = "cli"


def mcp_actor(ctx: "Context | None", fallback_conn: str) -> tuple[str, str]:
    """mcp 面：conn 优先取 opencode 会话 id（外部引用），否则进程级 conn id。"""
    surface = "mcp"
    conn = None
    if ctx is not None:
        try:
            meta = ctx.request_context.meta
        except Exception:
            meta = None
        if isinstance(meta, dict):
            conn = meta.get("ai.opencode/sessionID")
    return surface, conn or fallback_conn


def cli_actor() -> tuple[str, str]:
    return "cli", CLI_CONN
