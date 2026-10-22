"""MCP stdio server（PRD 4.1）：12 工具；错误返回 is_error + {code,message,task_id}（PRD 4.3）。
actor 经 Context 派生（identity.mcp_actor），不接受调用方传入（ADR 0002）。"""

from __future__ import annotations

import json
import uuid
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context
from mcp_types import CallToolResult, TextContent

from ..db import get_session_factory, run_op
from ..errors import BusinessError
from ..services import operations as ops
from ..services.identity import mcp_actor

CONN_ID = f"conn-{uuid.uuid4().hex[:8]}"


def _error(exc: BusinessError) -> CallToolResult:
    return CallToolResult(
        isError=True, content=[TextContent(type="text", text=json.dumps(exc.as_dict()))]
    )


def _ok(data: dict) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data))])


async def _call(
    ctx: Context | None, op_name: str, *, is_write: bool = True, **kwargs: Any
) -> CallToolResult:
    surface, conn = mcp_actor(ctx, CONN_ID)
    try:
        result = await run_op(
            get_session_factory(), getattr(ops, op_name), is_write=is_write,
            actor_surface=surface, actor_conn=conn, **kwargs,
        )
    except BusinessError as exc:
        return _error(exc)
    return _ok(result)


async def list_tasks(status: str | None = None, ctx: Context | None = None) -> CallToolResult:
    return await _call(ctx, "list_tasks", is_write=False, status=status)


async def get_task_detail(requirement_id: str, ctx: Context | None = None) -> CallToolResult:
    return await _call(ctx, "get_task_detail", is_write=False, requirement_id=requirement_id)


async def claim_task(requirement_id: str, agent_name: str, ctx: Context | None = None) -> CallToolResult:
    return await _call(ctx, "claim_task", requirement_id=requirement_id, agent_name=agent_name)


async def add_subtask(
    requirement_id: str, title: str, ordinal: int, acceptance: Any = None,
    ctx: Context | None = None,
) -> CallToolResult:
    return await _call(
        ctx, "add_subtask", requirement_id=requirement_id, title=title, ordinal=ordinal,
        acceptance=acceptance,
    )


async def update_subtask(
    requirement_id: str, subtask_id: str, state: str, ctx: Context | None = None
) -> CallToolResult:
    return await _call(
        ctx, "update_subtask", requirement_id=requirement_id, subtask_id=subtask_id, state=state
    )


async def add_milestone(
    requirement_id: str, title: str, planned_at: Any = None, ctx: Context | None = None
) -> CallToolResult:
    return await _call(
        ctx, "add_milestone", requirement_id=requirement_id, title=title, planned_at=planned_at
    )


async def update_milestone(
    requirement_id: str, milestone_id: str, state: str, actual_at: Any = None,
    ctx: Context | None = None,
) -> CallToolResult:
    return await _call(
        ctx, "update_milestone", requirement_id=requirement_id, milestone_id=milestone_id,
        state=state, actual_at=actual_at,
    )


async def add_record(
    requirement_id: str, kind: str, title: str, content: str | None = None,
    severity: str | None = None, payload: Any = None, ctx: Context | None = None,
) -> CallToolResult:
    return await _call(
        ctx, "add_record", requirement_id=requirement_id, kind=kind, title=title,
        content=content, severity=severity, payload=payload,
    )


async def update_progress(requirement_id: str, note: str, ctx: Context | None = None) -> CallToolResult:
    return await _call(ctx, "update_progress", requirement_id=requirement_id, note=note)


async def request_review(
    requirement_id: str, evidence: Any = None, assessments: Any = None,
    ctx: Context | None = None,
) -> CallToolResult:
    return await _call(
        ctx, "request_review", requirement_id=requirement_id, evidence=evidence,
        assessments=assessments,
    )


async def mark_blocked(
    requirement_id: str, reason: str, evidence: str | None = None,
    ctx: Context | None = None,
) -> CallToolResult:
    return await _call(
        ctx, "mark_blocked", requirement_id=requirement_id, reason=reason, evidence=evidence
    )


async def list_awaiting(ctx: Context | None = None) -> CallToolResult:
    return await _call(ctx, "list_awaiting", is_write=False)


server = MCPServer(name="agent-kanban", version="0.1.0")
for tool in (
    list_tasks,
    get_task_detail,
    claim_task,
    add_subtask,
    update_subtask,
    add_milestone,
    update_milestone,
    add_record,
    update_progress,
    request_review,
    mark_blocked,
    list_awaiting,
):
    server.add_tool(tool)


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
