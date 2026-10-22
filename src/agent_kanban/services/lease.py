"""租约推导（PRD 3.2）：不存状态字段，按序判定；
不自动释放/重开；activity 在写事务内更新。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import idle_seconds
from ..models import Claim


def derive_signal(
    claim: Claim, now: datetime, awaiting_human: dict | None, idle: int | None = None
) -> str:
    """有序判定：ended -> 结束；租约过期+标记 -> 等待中；租约过期无标记 -> STALE；
    无活动超 idle 无标记 -> SUSPECT；否则 ACTIVE。"""
    if claim.ended_at is not None:
        return "ended"
    if now > claim.lease_expires_at:
        return "waiting" if awaiting_human else "stale"
    idle = idle_seconds() if idle is None else idle
    if not awaiting_human and (now - claim.last_activity_at).total_seconds() > idle:
        return "suspect"
    return "active"


async def touch_activity(session: AsyncSession, requirement_id: str, now: datetime) -> None:
    """agent 面写操作在同一事务内更新 last_activity_at（PRD 3.2 activity 口径）。"""
    await session.execute(
        update(Claim)
        .where(Claim.requirement_id == requirement_id, Claim.ended_at.is_(None))
        .values(last_activity_at=now)
    )


def claim_view(claim: Claim | None, awaiting_human: dict | None, now: datetime) -> dict | None:
    if claim is None:
        return None
    return {
        "claim_id": claim.id,
        "agent_name": claim.agent_name,
        "agent_conn": claim.agent_conn,
        "started_at": claim.started_at.isoformat(),
        "lease_expires_at": claim.lease_expires_at.isoformat(),
        "last_activity_at": claim.last_activity_at.isoformat(),
        "ended_at": claim.ended_at.isoformat() if claim.ended_at else None,
        "release_reason": claim.release_reason,
        "signal": derive_signal(claim, now, awaiting_human),
    }
