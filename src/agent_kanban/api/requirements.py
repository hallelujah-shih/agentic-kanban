"""REST 人面路由（PRD 4.2/4.3 + plan M0-1.3）。actor 服务端派生（rest_actor）。

错误映射（契约，审#7）：not_found=404、illegal_state=409、lease_expired=409、
invalid_record=422、db_busy=503；already_claimed/no_active_claim/duplicate_subtask/
queue_full 为 agent 面（MCP）专用码，REST 无触发端点（保留作契约完整性，body 仍
{code,message,task_id}）。MCP 保持 is_error 无 HTTP 码（PRD 4.3）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from ..db import get_session_factory, run_op
from ..services import operations as ops
from ..services import view
from ..services.identity import rest_actor

router = APIRouter()


class NewIn(BaseModel):
    title: str
    description: str | None = None
    source: str = "manual"
    source_ref: str | None = None
    acceptance: list | None = None


class ExpectationsIn(BaseModel):
    acceptance: list


class ReleaseIn(BaseModel):
    reason: str


class NoteIn(BaseModel):
    content: str


class AbandonIn(BaseModel):
    to_state: str


class ReopenIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    continue_: bool = Field(default=False, alias="continue")


async def _run(op_name: str, *, is_write: bool = True, **kwargs: Any) -> Any:
    surface, conn = rest_actor()
    return await run_op(
        get_session_factory(), getattr(ops, op_name), is_write=is_write,
        actor_surface=surface, actor_conn=conn, **kwargs,
    )


@router.post("/requirements", status_code=201)
async def create_requirement(body: NewIn) -> dict:
    return await _run("new_requirement", title=body.title, description=body.description,
                      source=body.source, source_ref=body.source_ref, acceptance=body.acceptance)


@router.put("/requirements/{requirement_id}/expectations")
async def set_expectations(requirement_id: str, body: ExpectationsIn) -> dict:
    return await _run("set_expectations", requirement_id=requirement_id, acceptance=body.acceptance)


@router.post("/requirements/{requirement_id}/approve")
async def approve(requirement_id: str) -> dict:
    return await _run("approve", requirement_id=requirement_id)


@router.post("/requirements/{requirement_id}/release")
async def release(requirement_id: str, body: ReleaseIn) -> dict:
    return await _run("release", requirement_id=requirement_id, reason=body.reason)


@router.post("/requirements/{requirement_id}/renew")
async def renew(requirement_id: str) -> dict:
    return await _run("renew", requirement_id=requirement_id)


@router.post("/requirements/{requirement_id}/note")
async def note(requirement_id: str, body: NoteIn) -> dict:
    return await _run("note", requirement_id=requirement_id, content=body.content)


@router.post("/requirements/{requirement_id}/abandon")
async def abandon(requirement_id: str, body: AbandonIn) -> dict:
    return await _run("abandon", requirement_id=requirement_id, to_state=body.to_state)


@router.post("/requirements/{requirement_id}/reopen")
async def reopen(requirement_id: str, body: ReopenIn | None = None) -> dict:
    body = body or ReopenIn()
    return await _run("reopen", requirement_id=requirement_id, continue_=body.continue_)


@router.get("/requirements")
async def list_requirements() -> dict:
    return await _run("list_tasks", is_write=False)


@router.get("/board")
async def get_board(status: str | None = None) -> dict:
    """看板默认列表（PRD §4.2/§5.3）：非终态 + status 过滤；每需求派生需要关注信号。"""
    surface, conn = rest_actor()
    return await run_op(
        get_session_factory(), view.board, is_write=False,
        status=status, actor_surface=surface, actor_conn=conn,
    )


@router.get("/requirements/{requirement_id}")
async def get_requirement(requirement_id: str) -> dict:
    """深潜（view.detail，含状态重建与完整事件流）。"""
    surface, conn = rest_actor()
    return await run_op(
        get_session_factory(), view.detail, is_write=False,
        requirement_id=requirement_id, actor_surface=surface, actor_conn=conn,
    )


@router.get("/requirements/{requirement_id}/summary")
async def get_summary(requirement_id: str) -> dict:
    surface, conn = rest_actor()
    return await run_op(
        get_session_factory(), view.summary, is_write=False,
        requirement_id=requirement_id, actor_surface=surface, actor_conn=conn,
    )


@router.get("/requirements/{requirement_id}/summary.html", response_class=HTMLResponse)
async def get_summary_html(requirement_id: str) -> HTMLResponse:
    surface, conn = rest_actor()
    data = await run_op(
        get_session_factory(), view.summary, is_write=False,
        requirement_id=requirement_id, actor_surface=surface, actor_conn=conn,
    )
    return HTMLResponse(content=view.render_summary_html(data))


@router.get("/requirements/{requirement_id}/export")
async def export(requirement_id: str, format: str = "json") -> Any:
    res = await _run("export_data", is_write=False, requirement_id=requirement_id, fmt=format)
    if format == "markdown":
        return PlainTextResponse(res)
    return res
