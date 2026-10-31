"""状态机唯一转移点（PRD 3.1/7.3 #1）：条件更新 + rowcount 校验，
转移与事件同事务；转移到除 BLOCKED 外的状态一律清除 awaiting_human。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import now_utc
from ..errors import BusinessError
from ..models import Requirement
from .operations_util import add_event

# 转移边（from, to）；from=None 表示"任一"（REJECTED）
HUMAN = "human"
AGENT = "agent"
ALLOWED_EDGES: dict[tuple[str | None, str], str] = {
    ("OPEN", "CLAIMED"): AGENT,
    ("OPEN", "CANCELLED"): HUMAN,
    ("CLAIMED", "DONE"): HUMAN,
    ("CLAIMED", "BLOCKED"): AGENT,
    ("BLOCKED", "CLAIMED"): HUMAN,
    ("CLAIMED", "OPEN"): HUMAN,
    ("CLAIMED", "REOPEN"): HUMAN,
    ("DONE", "REOPEN"): HUMAN,
    ("REOPEN", "OPEN"): HUMAN,
    ("REOPEN", "CANCELLED"): HUMAN,
    (None, "REJECTED"): HUMAN,
    (None, "ARCHIVED"): HUMAN,
}


async def transition(
    session: AsyncSession,
    *,
    requirement_id: str,
    from_state: str | None,
    to_state: str,
    actor_surface: str,
    actor_conn: str,
    claim_id: str | None = None,
    now: datetime | None = None,
    event_payload: dict | None = None,
) -> str:
    now = now or now_utc()
    edge = (from_state, to_state)
    if edge not in ALLOWED_EDGES:
        raise BusinessError("illegal_state", f"transition {from_state} -> {to_state} is not allowed", requirement_id)

    stmt = (
        update(Requirement).where(Requirement.id == requirement_id).values(state=to_state, updated_at=now)
        if from_state is None
        else update(Requirement)
        .where(Requirement.id == requirement_id, Requirement.state == from_state)
        .values(state=to_state, updated_at=now)
    )
    res = await session.execute(stmt)
    if res.rowcount == 0:
        cur = await session.scalar(select(Requirement.state).where(Requirement.id == requirement_id))
        if cur is None:
            raise BusinessError("not_found", f"requirement not found: {requirement_id}", requirement_id)
        raise BusinessError("illegal_state", f"cannot transition {cur} -> {to_state}", requirement_id)

    if to_state != "BLOCKED":
        await session.execute(
            update(Requirement).where(Requirement.id == requirement_id).values(awaiting_human=None)
        )
    payload = {"from": from_state, "to": to_state}
    if event_payload:
        payload.update(event_payload)
    await add_event(
        session,
        requirement_id=requirement_id,
        kind="state_change",
        severity="info",
        title=f"{from_state or '?'} -> {to_state}",
        payload=payload,
        actor_surface=actor_surface,
        actor_conn=actor_conn,
        claim_id=claim_id,
        now=now,
    )
    return to_state
