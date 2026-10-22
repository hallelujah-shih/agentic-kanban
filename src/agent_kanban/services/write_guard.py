"""写保护（PRD 3.3）：agent 面写操作要求未结束认领（ended_at IS NULL），
校验与写入同事务（BEGIN IMMEDIATE 已保证写锁先行）。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import BusinessError
from ..models import Claim, Requirement


async def require_requirement(session: AsyncSession, requirement_id: str) -> Requirement:
    req = await session.get(Requirement, requirement_id)
    if req is None:
        raise BusinessError("not_found", f"requirement not found: {requirement_id}", requirement_id)
    return req


async def get_active_claim(session: AsyncSession, requirement_id: str, requirement: Requirement | None = None) -> Claim:
    """同事务校验只查 ended_at IS NULL，不校验租约有效性（BLOCKED 期间仍可写）。"""
    if requirement is None:
        await require_requirement(session, requirement_id)
    claim = await session.scalar(
        select(Claim).where(Claim.requirement_id == requirement_id, Claim.ended_at.is_(None))
    )
    if claim is None:
        raise BusinessError("no_active_claim", f"no active claim for requirement {requirement_id}", requirement_id)
    return claim


async def count_active_claims(session: AsyncSession) -> int:
    return await session.scalar(
        select(func.count()).select_from(Claim).where(Claim.ended_at.is_(None))
    ) or 0
