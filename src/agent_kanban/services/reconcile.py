"""重启对账（PRD 3.2 服务重启对账 / §6 可靠性）：遍历未结束 claim，有序判定
stale/waiting/orphaned/active；claim-state 失配 -> drift；写 reconcile 事件
（append-only，只标记不删除）。

观测源 = claims 表（agent_conn + last_activity_at，共享 DB），无进程内 conn
registry（审#1，跨进程各自 registry 会互相误标 ORPHANED）。ORPHANED/drift
只属 reconcile 产物（审#8），claim_view.signal 保持 PRD 推导序，view.py 现状不动；
reconcile 结果入摘要「需要关注区」由 view 集成完成。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session_factory, idle_seconds, now_utc
from ..models import Claim, Requirement
from .ids import norm_id
from .operations_util import add_event

RECONCILE_SURFACE = "system"
RECONCILE_CONN = "reconcile"


def _signal(claim: Claim, req: Requirement, now: datetime, idle: int) -> str:
    """有序判定：awaiting_human -> waiting（优先于 ORPHANED，连接失活不盖过
    「等待人裁决」）；租约过期 -> stale；last_activity 超 idle -> orphaned（=
    SUSPECT 区间在 reconcile 时点的显式化）；否则 active。"""
    if req.awaiting_human:
        return "waiting"
    if now > claim.lease_expires_at:
        return "stale"
    if (now - claim.last_activity_at).total_seconds() > idle:
        return "orphaned"
    return "active"


async def reconcile(session: AsyncSession, *, now: datetime | None = None) -> dict:
    """对账：读扫描（WAL 快照，不抢写锁）+ 仅在有非 active finding 或 drift 时
    开写事务写 reconcile 事件。返回报告（响应边界 id 归一 32-hex）。"""
    now = now or now_utc()
    idle = idle_seconds()

    claims = (await session.scalars(
        select(Claim).where(Claim.ended_at.is_(None))
    )).all()
    req_ids = {c.requirement_id for c in claims}
    reqs: dict[str, Requirement] = {}
    if req_ids:
        reqs = {
            r.id: r for r in (await session.scalars(
                select(Requirement).where(Requirement.id.in_(req_ids))
            )).all()
        }

    findings = []
    for c in claims:
        req = reqs.get(c.requirement_id)
        if req is None:  # claim 指向不存在的需求：跳过信号判定（不写事件）
            continue
        findings.append({
            "claim_id": c.id,
            "requirement_id": c.requirement_id,
            "signal": _signal(c, req, now, idle),
        })

    # claim-state 失配（PRD 3.2/§6 可靠性）：有 claim 无 CLAIMED（BLOCKED 合法）；
    # 反之 state==CLAIMED 无未结束 claim
    drift: list[dict] = []
    for f in findings:
        req = reqs[f["requirement_id"]]
        if req.state not in ("CLAIMED", "BLOCKED"):
            drift.append({
                "type": "claim_without_claimed", "requirement_id": f["requirement_id"],
                "claim_id": f["claim_id"], "state": req.state,
            })
    for r in (await session.scalars(
        select(Requirement).where(Requirement.state == "CLAIMED")
    )).all():
        if r.id not in req_ids:
            drift.append({"type": "claimed_without_claim", "requirement_id": r.id, "state": "CLAIMED"})

    # 每受影响 requirement 一条 reconcile 事件（非 active finding 或 drift）
    by_req: dict[str, dict] = {}
    for f in findings:
        if f["signal"] != "active":
            by_req.setdefault(f["requirement_id"], {"findings": [], "drift": []})["findings"].append(f)
    for d in drift:
        by_req.setdefault(d["requirement_id"], {"findings": [], "drift": []})["drift"].append(d)

    events_written: list[str] = []
    if by_req:
        async with get_session_factory()() as ws:
            for rid, payload in by_req.items():
                await add_event(
                    ws, requirement_id=rid, kind="reconcile", severity="info", title="reconcile",
                    payload=payload, actor_surface=RECONCILE_SURFACE, actor_conn=RECONCILE_CONN, now=now,
                )
                events_written.append(rid)
            await ws.commit()

    return {
        "scanned": len(claims),
        "findings": [
            {"claim_id": norm_id(f["claim_id"]), "requirement_id": norm_id(f["requirement_id"]),
             "signal": f["signal"]}
            for f in findings
        ],
        "drift": [
            {
                "type": d["type"], "requirement_id": norm_id(d["requirement_id"]),
                **({"claim_id": norm_id(d["claim_id"])} if d.get("claim_id") else {}),
                "state": d.get("state"),
            }
            for d in drift
        ],
        "events_written": [norm_id(r) for r in events_written],
    }
