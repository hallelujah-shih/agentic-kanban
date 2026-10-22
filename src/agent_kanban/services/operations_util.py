"""共享写原语：事件追加（seq/ts 服务端签发）、归一化、锚 id 分配。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..db import next_seq, now_utc
from ..models import Event, new_id


async def add_event(
    session: AsyncSession,
    *,
    requirement_id: str,
    kind: str,
    severity: str = "info",
    title: str,
    content: str | None = None,
    payload: dict | None = None,
    actor_surface: str,
    actor_conn: str,
    claim_id: str | None = None,
    subtask_id: str | None = None,
    milestone_id: str | None = None,
    now: datetime | None = None,
) -> Event:
    now = now or now_utc()
    seq = await next_seq(session)
    ev = Event(
        id=new_id(),
        requirement_id=requirement_id,
        claim_id=claim_id,
        subtask_id=subtask_id,
        milestone_id=milestone_id,
        kind=kind,
        severity=severity,
        title=title,
        content=content,
        payload=payload,
        actor_surface=actor_surface,
        actor_conn=actor_conn,
        seq=seq,
        ts=now,
    )
    session.add(ev)
    return ev


def normalize_title(title: str) -> str:
    """子任务 title 归一：trim + 空白折叠 + casefold（PRD §2 UNIQUE 语义）。"""
    return " ".join(str(title).split()).casefold()


def normalize_anchors(acceptance: Any, existing: list | None = None) -> list:
    """预期验收锚：按 item 文本保留既有 id，其余按序分配 a{i+1}。"""
    existing = existing or []
    by_item = {str(a.get("item")): a.get("id") for a in existing if isinstance(a, dict)}
    out: list = []
    for i, a in enumerate(acceptance or []):
        item = dict(a) if isinstance(a, dict) else {"item": str(a)}
        if not item.get("id"):
            item["id"] = by_item.get(str(item.get("item"))) or f"a{i + 1}"
        out.append(item)
    return out


def rand_id() -> str:
    return uuid.uuid4().hex
