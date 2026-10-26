"""REST 人面路由（PRD 4.2/4.3 + plan M0-1.3）。actor 服务端派生（rest_actor）。

错误映射（契约，审#7）：not_found=404、illegal_state=409、lease_expired=409、
invalid_record=422、db_busy=503；already_claimed/no_active_claim/duplicate_subtask/
queue_full 为 agent 面（MCP）专用码，REST 无触发端点（保留作契约完整性，body 仍
{code,message,task_id}）。MCP 保持 is_error 无 HTTP 码（PRD 4.3）。
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ..db import get_read_session_factory, get_session_factory, run_op
from ..models import Event
from ..services import operations as ops
from ..services import view
from ..services.identity import rest_actor
from ..services.ids import norm_id
from ..services.write_guard import require_requirement
from .web import board_shell, detail_shell

router = APIRouter()


def _sse_poll_seconds() -> float:
    return int(os.environ.get("AGENT_KANBAN_SSE_POLL_MS", "2000")) / 1000


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


@router.post("/requirements/{requirement_id}/archive")
async def archive_requirement(requirement_id: str) -> dict:
    return await _run("archive_requirement", requirement_id=requirement_id)


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


@router.get("/events/stream")
async def events_stream(request: Request) -> StreamingResponse:
    """SSE 事件推送（PRD §5.3）：全局 seq 游标轮询（WHERE seq > last_seq ORDER BY seq）；
    游标初始化 = 连接时刻（无历史回填，无 id: 帧、忽略 Last-Event-ID）；每轮询显式
    事务边界（WAL 快照不跨轮询，跨进程写入可见）；is_disconnected 停轮询 + finally 关
    session；纯触发器字段（无 title/payload，反淹没）；keepalive `: ping`。"""
    async def gen():
        session = get_read_session_factory()()
        try:
            cursor = (await session.execute(select(Event.seq).order_by(Event.seq.desc()).limit(1))).scalar() or 0
            await session.commit()
            while True:
                if await request.is_disconnected():
                    break
                rows = (await session.execute(
                    select(Event.seq, Event.requirement_id, Event.kind, Event.severity,
                           Event.ts, Event.actor_surface, Event.actor_conn)
                    .where(Event.seq > cursor).order_by(Event.seq)
                )).all()
                await session.commit()  # 显式事务边界：释放快照，下轮询新读事务
                if rows:
                    for r in rows:
                        yield "data: " + json.dumps({
                            "seq": r.seq, "requirement_id": norm_id(r.requirement_id), "kind": r.kind,
                            "severity": r.severity, "ts": r.ts.isoformat(),
                            "actor_surface": r.actor_surface, "actor_conn": r.actor_conn,
                        }, ensure_ascii=False) + "\n\n"
                    cursor = rows[-1].seq
                else:
                    yield ": ping\n\n"
                await asyncio.sleep(_sse_poll_seconds())
        finally:
            await session.close()

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/", response_class=HTMLResponse)
async def board_page() -> HTMLResponse:
    """看板 HTML 壳（反淹没：壳无数据嵌入，JS fetch /board 渲染 + EventSource 重拉）。"""
    return HTMLResponse(content=board_shell())


@router.get("/requirements/{requirement_id}")
async def get_requirement(requirement_id: str, request: Request) -> Any:
    """深潜（view.detail，含状态重建与完整事件流）。内容协商（审#P2-7 + 审#P2-1）：
    Accept 含 text/html -> HTML 壳（只做存在性校验，不跑完整 detail 的无谓 DB 工作）；
    缺省/* -> JSON（形状不变）。"""
    accept = request.headers.get("accept") or ""
    if "text/html" in accept:
        await run_op(
            get_session_factory(), require_requirement, is_write=False, requirement_id=requirement_id,
        )
        return HTMLResponse(content=detail_shell())
    surface, conn = rest_actor()
    data = await run_op(
        get_session_factory(), view.detail, is_write=False,
        requirement_id=requirement_id, actor_surface=surface, actor_conn=conn,
    )
    return data


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
