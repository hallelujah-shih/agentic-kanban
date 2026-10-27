"""写保护（PRD 3.3）：agent 面写操作要求未结束认领（ended_at IS NULL），
校验与写入同事务（BEGIN IMMEDIATE 已保证写锁先行）。

requirement_id 解析单点（PRD 4.3；spec 2026-10-27-a1a2-mcp-surface §2.2）：
输入统一归一（strip / 大小写 / 连字符）；32 位 hex 精确匹配优先；
8~31 位 hex 唯一前缀可解析（>=2 命中 -> ambiguous_id）；<8 位或非 hex -> not_found。
MCP/REST/CLI 三面同源；前缀逻辑全仓仅存于本文件。"""

from __future__ import annotations

from sqlalchemy import String, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import BusinessError
from ..models import Claim, Requirement
from .ids import norm_id

_HEX = frozenset("0123456789abcdef")


def _not_found(raw: str) -> BusinessError:
    return BusinessError("not_found", f"requirement not found: {raw}", raw)


async def require_requirement(session: AsyncSession, requirement_id: str) -> Requirement:
    s = str(requirement_id).strip().lower().replace("-", "")
    is_hex = bool(s) and all(c in _HEX for c in s)
    if is_hex and len(s) == 32:
        req = await session.get(Requirement, s)
        if req is None:
            raise _not_found(requirement_id)
        return req
    if is_hex and 8 <= len(s) <= 31:
        # cast(String) 避 Uuid 列 .like 的 SADeprecationWarning（sqlalchemy 2.1.6 实测；
        # 未来版本将硬错 InvalidRequestError，盲审 P2-3）；SQLite 下 id 即 TEXT，CAST 无行为变化
        rows = (
            await session.scalars(
                select(Requirement.id)
                .where(Requirement.id.cast(String).like(f"{s}%"))
                .order_by(Requirement.id)
                .limit(6)
            )
        ).all()
        if not rows:
            raise _not_found(requirement_id)
        if len(rows) == 1:
            req = await session.get(Requirement, norm_id(rows[0]))
            if req is None:
                raise _not_found(requirement_id)
            return req
        total = (
            await session.scalar(
                select(func.count()).select_from(Requirement)
                .where(Requirement.id.cast(String).like(f"{s}%"))
            )
            or 0
        )
        cands = sorted(norm_id(r) for r in rows)
        shown = ", ".join(cands[:5]) + (" …" if len(cands) > 5 else "")
        raise BusinessError(
            "ambiguous_id",
            f"ambiguous requirement_id prefix '{s}': {shown}, 共 {total} 个候选; use a longer prefix",
            requirement_id,
        )
    raise _not_found(requirement_id)


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
