"""业务操作层：MCP 工具与 CLI 共用的写/读原语。全部在单事务内执行
（run_op + BEGIN IMMEDIATE），seq/ts 服务端同事务签发。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import MAX_ACTIVE_CLAIMS, idle_seconds, lease_seconds, now_utc
from ..errors import BusinessError
from ..models import Claim, Event, Milestone, Requirement, Subtask, new_id
from . import lease as lease_svc
from .ids import norm_id
from .operations_util import TERMINAL_STATES, add_event, normalize_anchors, normalize_title
from .retry_limit import (
    RETRY_LIMIT_CONN,
    RETRY_LIMIT_SURFACE,
    RETRY_LIMIT_THRESHOLD,
    RETRY_LIMIT_TITLE,
    count_retries,
    is_retry_limit_event,
)
from .state_machine import transition
from .write_guard import count_active_claims, get_active_claim, require_requirement

RECORD_KINDS = {"decision", "risk", "deviation", "decomposition", "note"}
SEVERITIES = {"info", "attention", "critical"}
SUBTASK_STATES = {"todo", "in_progress", "done", "blocked", "abandoned"}
MILESTONE_STATES = {"planned", "in_progress", "achieved"}
EVIDENCE_FIELDS = ("pr_url", "commit_range", "test_summary")
ASSESSMENT_STATES = {"met", "not_met", "deviated"}
ASSESSMENT_FORM_EXAMPLE = (
    '[{"subtask_id": "<子任务 id>", "items": [{"item": "<该子任务验收文本逐字>", '
    '"state": "met"|"not_met"|"deviated", "deviation_reason": "<仅 not_met/deviated 需要>"}]}]'
)
MAX_PAYLOAD_BYTES = 8192  # PRD §6：单事件 payload < 8 KB（写时强制）


def _check_payload_size(requirement_id: str, *objects: Any) -> None:
    for obj in objects:
        if obj is None:
            continue
        size = len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))
        if size > MAX_PAYLOAD_BYTES:
            raise BusinessError(
                "invalid_record", f"payload exceeds {MAX_PAYLOAD_BYTES} bytes", requirement_id
            )


def _claim_view(claim: Claim | None, awaiting_human: dict | None, now: datetime) -> dict | None:
    """认领视图（响应边界）：claim_id 归一 32-hex（与 view._claim_view 同口径）。"""
    v = lease_svc.claim_view(claim, awaiting_human, now)
    if v is not None:
        v["claim_id"] = norm_id(v["claim_id"])
    return v


def _validate_decision_payload(payload: Any) -> None:
    """decision 结构钉死：{choice, rationale, alternatives:[{option, rejected_reason}]}。"""
    if not isinstance(payload, dict):
        raise BusinessError("invalid_record", "decision requires a structured payload", None)
    rationale = payload.get("rationale")
    if not rationale or not str(rationale).strip():
        raise BusinessError("invalid_record", "decision requires rationale", None)
    alternatives = payload.get("alternatives")
    if not isinstance(alternatives, list) or not alternatives:
        raise BusinessError("invalid_record", "decision requires alternatives[] (>=1)", None)
    for alt in alternatives:
        if not isinstance(alt, dict):
            raise BusinessError("invalid_record", "alternative must be an object", None)
        if not str(alt.get("option", "")).strip():
            raise BusinessError("invalid_record", "alternative requires option", None)
        if not str(alt.get("rejected_reason", "")).strip():
            raise BusinessError("invalid_record", "alternative requires rejected_reason", None)


def _parse_iso(value: Any, field: str) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        raise BusinessError("invalid_record", f"{field} must be ISO-8601 datetime", None)


# ---------------------------------------------------------------- 人面（CLI）
async def new_requirement(
    session: AsyncSession,
    *,
    title: str,
    description: str | None = None,
    source: str = "manual",
    source_ref: str | None = None,
    acceptance: Any = None,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
) -> dict:
    now = now or now_utc()
    req = Requirement(
        id=new_id(),
        source=source,
        source_ref=source_ref,
        title=title,
        description=description,
        acceptance=normalize_anchors(acceptance),
        state="OPEN",
        created_at=now,
        updated_at=now,
    )
    session.add(req)
    return {"requirement_id": req.id, "state": "OPEN"}


async def set_expectations(
    session: AsyncSession,
    *,
    requirement_id: str,
    acceptance: Any,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
) -> dict:
    now = now or now_utc()
    req = await require_requirement(session, requirement_id)
    requirement_id = norm_id(req.id)
    old = req.acceptance or []
    new = normalize_anchors(acceptance, old)
    removed = {a.get("id") for a in old if isinstance(a, dict) and a.get("id")} - {
        a.get("id") for a in new if isinstance(a, dict) and a.get("id")
    }
    if removed:
        # PRD 4.2：删除被 subtasks.acceptance[].links_to 引用的锚项被拒绝
        sts = (
            await session.scalars(
                select(Subtask).where(Subtask.requirement_id == requirement_id)
            )
        ).all()
        for st in sts:
            for acc in (st.acceptance or []):
                if not isinstance(acc, dict):
                    continue
                refs = acc.get("links_to") or []
                if isinstance(refs, str):
                    refs = [refs]
                hit = removed & set(refs)
                if hit:
                    raise BusinessError(
                        "invalid_record",
                        f"acceptance anchor {sorted(hit)} still referenced by subtask {st.title}",
                        requirement_id,
                    )
    req.acceptance = new
    req.updated_at = now
    return {"requirement_id": requirement_id, "acceptance": new}


async def approve(
    session: AsyncSession,
    *,
    requirement_id: str,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
    delegated: dict | None = None,
) -> dict:
    now = now or now_utc()
    req = await require_requirement(session, requirement_id)
    requirement_id = norm_id(req.id)
    if req.state == "CLAIMED":
        # CLAIMED -> DONE：人确认终态 + claim ended_at 同事务 + 清 marker
        await transition(
            session, requirement_id=requirement_id, from_state="CLAIMED", to_state="DONE",
            actor_surface=actor_surface, actor_conn=actor_conn, now=now,
            event_payload={"delegated": delegated} if delegated else None,
        )
        await session.execute(
            update(Claim).where(Claim.requirement_id == requirement_id, Claim.ended_at.is_(None)).values(ended_at=now)
        )
        await add_event(
            session, requirement_id=requirement_id, kind="approval", severity="info",
            title="approved", payload={"state": "DONE", **({"delegated": delegated} if delegated else {})},
            actor_surface=actor_surface, actor_conn=actor_conn, now=now,
        )
        return {"requirement_id": requirement_id, "state": "DONE"}
    if req.state == "BLOCKED":
        await transition(
            session, requirement_id=requirement_id, from_state="BLOCKED", to_state="CLAIMED",
            actor_surface=actor_surface, actor_conn=actor_conn, now=now,
            event_payload={"delegated": delegated} if delegated else None,
        )
        return {"requirement_id": requirement_id, "state": "CLAIMED"}
    raise BusinessError("illegal_state", f"approve not allowed from state {req.state}", requirement_id)


async def release(
    session: AsyncSession,
    *,
    requirement_id: str,
    reason: str,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
    delegated: dict | None = None,
) -> dict:
    now = now or now_utc()
    if not reason or not str(reason).strip():
        raise BusinessError("invalid_record", "release requires a reason", requirement_id)
    req = await require_requirement(session, requirement_id)
    requirement_id = norm_id(req.id)
    claim = await session.scalar(
        select(Claim).where(Claim.requirement_id == requirement_id, Claim.ended_at.is_(None))
    )
    if claim is None:
        raise BusinessError("not_found", f"no active claim to release for {requirement_id}", requirement_id)
    await transition(
        session, requirement_id=requirement_id, from_state="CLAIMED", to_state="OPEN",
        actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim.id, now=now,
        event_payload={"delegated": delegated} if delegated else None,
    )
    await session.execute(
        update(Claim).where(Claim.id == claim.id).values(ended_at=now, release_reason=reason)
    )
    await add_event(
        session, requirement_id=requirement_id, kind="release", severity="info",
        title="released", payload={"reason": reason, "agent_name": claim.agent_name, **({"delegated": delegated} if delegated else {})},
        actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim.id, now=now,
    )
    return {"requirement_id": requirement_id, "state": "OPEN", "claim_id": norm_id(claim.id)}


async def release_all_stale(
    session: AsyncSession,
    *,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
    delegated: dict | None = None,
) -> dict:
    """`release --all-stale`（PRD 4.2）：批量释放全部 STALE 认领（仅覆盖 CLAIMED 需求；
    逐项单释放语义，部分失败逐项返回，非全有全无）。"""
    now = now or now_utc()
    claimed = (
        await session.scalars(select(Requirement).where(Requirement.state == "CLAIMED"))
    ).all()
    results: list[dict] = []
    for r in claimed:
        claim = await session.scalar(
            select(Claim).where(Claim.requirement_id == r.id, Claim.ended_at.is_(None))
        )
        if claim is None:
            continue
        if lease_svc.derive_signal(claim, now, r.awaiting_human) != "stale":
            continue
        try:
            await transition(
                session, requirement_id=r.id, from_state="CLAIMED", to_state="OPEN",
                actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim.id, now=now,
                event_payload={"delegated": delegated} if delegated else None,
            )
            await session.execute(
                update(Claim).where(Claim.id == claim.id).values(ended_at=now, release_reason="stale")
            )
            await add_event(
                session, requirement_id=r.id, kind="release", severity="info",
                title="released", payload={"reason": "stale", "agent_name": claim.agent_name, **({"delegated": delegated} if delegated else {})},
                actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim.id, now=now,
            )
            results.append({"requirement_id": r.id.replace("-", ""), "ok": True, "state": "OPEN"})
        except BusinessError as exc:
            results.append({"requirement_id": r.id.replace("-", ""), "ok": False, "error": exc.code})
    return {"released": results}


async def renew(
    session: AsyncSession,
    *,
    requirement_id: str,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
    delegated: dict | None = None,
) -> dict:
    now = now or now_utc()
    req = await require_requirement(session, requirement_id)
    requirement_id = norm_id(req.id)
    claim = await session.scalar(
        select(Claim).where(Claim.requirement_id == requirement_id, Claim.ended_at.is_(None))
    )
    if claim is None:
        raise BusinessError("not_found", f"no active claim to renew for {requirement_id}", requirement_id)
    if now > claim.lease_expires_at:
        raise BusinessError("lease_expired", "lease already expired", requirement_id)
    new_expiry = now + timedelta(seconds=lease_seconds())
    await session.execute(
        update(Claim).where(Claim.id == claim.id).values(lease_expires_at=new_expiry, last_activity_at=now)
    )
    # M1-3.2：renew 写事件（PRD §2 kind 全集 + §3.2 人续租证明；可回溯谁续了租约）。
    # 无认领/已过期路径在上方已 raise，不写事件。
    await add_event(
        session, requirement_id=requirement_id, kind="renew", severity="info",
        title="lease renewed",
        payload={"delegated": delegated} if delegated else None,
        actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim.id, now=now,
    )
    return {"requirement_id": requirement_id, "lease_expires_at": new_expiry.isoformat()}


async def note(
    session: AsyncSession,
    *,
    requirement_id: str,
    content: str,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
    delegated: dict | None = None,
) -> dict:
    now = now or now_utc()
    req = await require_requirement(session, requirement_id)
    requirement_id = norm_id(req.id)
    _check_payload_size(requirement_id, {"content": content}, content)  # PRD §6：单事件 payload < 8KB
    await add_event(
        session, requirement_id=requirement_id, kind="note", severity="info",
        title="note", content=content, payload={"content": content, **({"delegated": delegated} if delegated else {})},
        actor_surface=actor_surface, actor_conn=actor_conn, now=now,
    )
    return {"requirement_id": requirement_id}


async def reopen(
    session: AsyncSession,
    *,
    requirement_id: str,
    continue_: bool = False,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
    delegated: dict | None = None,
) -> dict:
    """PRD 4.2（审#2-reopen）：`reopen` = DONE->REOPEN（避免死端）；
    `--continue` = REOPEN->OPEN（回到可认领）。REOPEN->CANCELLED 由 abandon 覆盖。"""
    now = now or now_utc()
    req = await require_requirement(session, requirement_id)
    requirement_id = norm_id(req.id)
    if continue_:
        await transition(
            session, requirement_id=requirement_id, from_state="REOPEN", to_state="OPEN",
            actor_surface=actor_surface, actor_conn=actor_conn, now=now,
            event_payload={"delegated": delegated} if delegated else None,
        )
        return {"requirement_id": requirement_id, "state": "OPEN"}
    await transition(
        session, requirement_id=requirement_id, from_state="DONE", to_state="REOPEN",
        actor_surface=actor_surface, actor_conn=actor_conn, now=now,
        event_payload={"delegated": delegated} if delegated else None,
    )
    return {"requirement_id": requirement_id, "state": "REOPEN"}


async def abandon(
    session: AsyncSession,
    *,
    requirement_id: str,
    to_state: str,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
    delegated: dict | None = None,
) -> dict:
    now = now or now_utc()
    req = await require_requirement(session, requirement_id)
    requirement_id = norm_id(req.id)
    claim = await session.scalar(
        select(Claim).where(Claim.requirement_id == requirement_id, Claim.ended_at.is_(None))
    )
    claim_id = claim.id if claim is not None else None
    if to_state == "REJECTED":
        await transition(
            session, requirement_id=requirement_id, from_state=None, to_state="REJECTED",
            actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim_id, now=now,
            event_payload={"delegated": delegated} if delegated else None,
        )
    elif to_state == "CANCELLED":
        if req.state not in ("OPEN", "REOPEN"):
            raise BusinessError("illegal_state", f"cannot cancel from state {req.state}", requirement_id)
        await transition(
            session, requirement_id=requirement_id, from_state=req.state, to_state="CANCELLED",
            actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim_id, now=now,
            event_payload={"delegated": delegated} if delegated else None,
        )
    else:
        raise BusinessError("invalid_record", f"invalid abandon state: {to_state}", requirement_id)
    # G8 P2-3：REJECTED/CANCELLED 同事务置 claim ended_at（+清 marker 由 transition 完成 + 事件同事务）
    if claim is not None:
        await session.execute(
            update(Claim).where(Claim.id == claim.id).values(ended_at=now, release_reason=f"abandon:{to_state}")
        )
    return {"requirement_id": requirement_id, "state": to_state}


async def archive_requirement(
    session: AsyncSession,
    *,
    requirement_id: str,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
) -> dict:
    now = now or now_utc()
    req = await require_requirement(session, requirement_id)
    requirement_id = norm_id(req.id)
    claim = await session.scalar(
        select(Claim).where(Claim.requirement_id == requirement_id, Claim.ended_at.is_(None))
    )
    claim_id = claim.id if claim is not None else None
    await transition(
        session, requirement_id=requirement_id, from_state=None, to_state="ARCHIVED",
        actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim_id, now=now,
    )
    # 同事务结束未结束认领（abandon 模式，operations.py:371-375）；清 marker 由 transition 通规完成
    if claim is not None:
        await session.execute(
            update(Claim).where(Claim.id == claim.id).values(ended_at=now, release_reason="archive")
        )
    return {"requirement_id": requirement_id, "state": "ARCHIVED"}


async def delete_preview(
    session: AsyncSession,
    *,
    requirement_id: str,
    actor_surface: str,
    actor_conn: str,
) -> dict:
    req = await require_requirement(session, requirement_id)
    requirement_id = norm_id(req.id)
    count = await session.scalar(
        select(func.count()).select_from(Event).where(Event.requirement_id == requirement_id)
    )
    return {"requirement_id": requirement_id, "title": req.title, "state": req.state,
            "event_count": count or 0}


async def delete_requirement(
    session: AsyncSession,
    *,
    requirement_id: str,
    actor_surface: str,
    actor_conn: str,
) -> dict:
    req = await require_requirement(session, requirement_id)
    requirement_id = norm_id(req.id)
    # FK 序：events（FK 指向 claims/subtasks/milestones）-> subtasks/milestones/claims -> requirement；
    # 不写事件（整链随属主消失，I2：链永不半断的推广形态）
    await session.execute(delete(Event).where(Event.requirement_id == requirement_id))
    await session.execute(delete(Subtask).where(Subtask.requirement_id == requirement_id))
    await session.execute(delete(Milestone).where(Milestone.requirement_id == requirement_id))
    await session.execute(delete(Claim).where(Claim.requirement_id == requirement_id))
    await session.execute(delete(Requirement).where(Requirement.id == requirement_id))
    return {"requirement_id": requirement_id, "deleted": True}


# ---------------------------------------------------------------- agent 面（MCP）
async def claim_task(
    session: AsyncSession,
    *,
    requirement_id: str,
    agent_name: str,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
) -> dict:
    now = now or now_utc()
    req = await require_requirement(session, requirement_id)
    requirement_id = norm_id(req.id)
    active = await count_active_claims(session)
    if active >= MAX_ACTIVE_CLAIMS:
        raise BusinessError(
            "queue_full",
            f"active claims at capacity ({MAX_ACTIVE_CLAIMS})",
            requirement_id,
        )
    lease_secs = lease_seconds()
    claim_id = new_id()
    res = await session.execute(
        sqlite_insert(Claim)
        .values(
            id=claim_id,
            requirement_id=requirement_id,
            agent_name=agent_name,
            agent_conn=actor_conn,
            started_at=now,
            lease_expires_at=now + timedelta(seconds=lease_secs),
            last_activity_at=now,
            ended_at=None,
            release_reason=None,
        )
        .on_conflict_do_nothing()  # 裸 DO NOTHING（PRD 7.3 #9，partial index 不能带显式目标）
    )
    if res.rowcount == 0:
        holder = await session.scalar(
            select(Claim.agent_name).where(Claim.requirement_id == requirement_id, Claim.ended_at.is_(None))
        )
        raise BusinessError(
            "already_claimed",
            f"requirement already claimed by {holder or 'unknown'}",
            requirement_id,
        )
    _claim_hook()
    await transition(
        session, requirement_id=requirement_id, from_state="OPEN", to_state="CLAIMED",
        actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim_id, now=now,
    )
    return {
        "requirement_id": requirement_id,
        "claim_id": claim_id,
        "agent_name": agent_name,
        "lease_expires_at": (now + timedelta(seconds=lease_secs)).isoformat(),
        "lease_seconds": lease_secs,
    }


def _claim_hook() -> None:
    """AC1 kill 锚：INSERT claims 后、UPDATE requirements 前阻塞（仅测试钩子）。"""
    import os
    import time
    from pathlib import Path

    if os.environ.get("AGENT_KANBAN_TEST_CLAIM_HOOK") == "block_after_insert":
        marker = os.environ.get("AGENT_KANBAN_TEST_CLAIM_HOOK_MARKER")
        if marker:
            Path(marker).touch()
        time.sleep(60)


async def add_subtask(
    session: AsyncSession,
    *,
    requirement_id: str,
    title: str,
    ordinal: int,
    acceptance: Any = None,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
) -> dict:
    now = now or now_utc()
    req = await require_requirement(session, requirement_id)
    requirement_id = norm_id(req.id)
    claim = await get_active_claim(session, requirement_id)
    norm_title = normalize_title(title)
    dup = await session.scalar(
        select(func.count()).select_from(Subtask).where(
            Subtask.requirement_id == requirement_id, Subtask.title == norm_title
        )
    )
    if dup:
        raise BusinessError("duplicate_subtask", f"subtask title already exists: {norm_title}", requirement_id)
    ord_dup = await session.scalar(
        select(func.count()).select_from(Subtask).where(
            Subtask.requirement_id == requirement_id, Subtask.ordinal == ordinal
        )
    )
    if ord_dup:
        raise BusinessError("invalid_record", f"ordinal {ordinal} already used", requirement_id)
    st = Subtask(
        id=new_id(), requirement_id=requirement_id, ordinal=ordinal, title=norm_title,
        acceptance=list(acceptance or []), state="todo", created_at=now, updated_at=now,
    )
    _check_payload_size(requirement_id, st.acceptance)  # PRD §6：acceptance 拆解载荷 < 8KB
    session.add(st)
    await add_event(
        session, requirement_id=requirement_id, kind="decomposition", severity="info",
        title="add_subtask", payload={"subtask_id": st.id, "ordinal": ordinal, "title": norm_title},
        actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim.id, subtask_id=st.id, now=now,
    )
    await lease_svc.touch_activity(session, requirement_id, now)
    return {"requirement_id": requirement_id, "subtask_id": st.id, "ordinal": ordinal, "title": norm_title}


async def update_subtask(
    session: AsyncSession,
    *,
    requirement_id: str,
    subtask_id: str,
    state: str,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
) -> dict:
    now = now or now_utc()
    req = await require_requirement(session, requirement_id)
    requirement_id = norm_id(req.id)
    claim = await get_active_claim(session, requirement_id)
    if state not in SUBTASK_STATES:
        raise BusinessError("invalid_record", f"invalid subtask state: {state}", requirement_id)
    st = await session.scalar(
        select(Subtask).where(Subtask.id == subtask_id, Subtask.requirement_id == requirement_id)
    )
    if st is None:
        raise BusinessError("not_found", f"subtask not found: {subtask_id}", requirement_id)
    old = st.state
    st.state = state
    st.updated_at = now
    await add_event(
        session, requirement_id=requirement_id, kind="state_change", severity="info",
        title=f"subtask {old} -> {state}", payload={"subtask_id": subtask_id, "from": old, "to": state},
        actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim.id, subtask_id=subtask_id, now=now,
    )
    if state == "in_progress" and old != "in_progress":
        await _maybe_write_retry_limit(session, requirement_id=requirement_id, claim_id=claim.id, now=now)
    await lease_svc.touch_activity(session, requirement_id, now)
    return {"requirement_id": requirement_id, "subtask_id": subtask_id, "state": state}


async def _maybe_write_retry_limit(
    session: AsyncSession, *, requirement_id: str, claim_id: str, now: datetime,
) -> None:
    """G9-b（BCD §4 S1/边缘 1/§7 强不变量 1,3）：子任务重入 in_progress 时评估需求级
    累计重试（含本次，事件链单一事件源）；累计严格超 2 且无既有 marker -> 同事务写
    risk(attention) 事件，幂等只写一次，count=触发时点快照。只标记不干预（无状态迁移）。"""
    events = (await session.scalars(
        select(Event).where(Event.requirement_id == requirement_id).order_by(Event.seq)
    )).all()
    retries = count_retries(events)
    if retries < RETRY_LIMIT_THRESHOLD:
        return
    if any(is_retry_limit_event(e) for e in events):
        return
    await add_event(
        session, requirement_id=requirement_id, kind="risk", severity="attention",
        title=RETRY_LIMIT_TITLE, payload={"retry_limit": True, "count": retries},
        actor_surface=RETRY_LIMIT_SURFACE, actor_conn=RETRY_LIMIT_CONN, claim_id=claim_id, now=now,
    )


async def add_milestone(
    session: AsyncSession,
    *,
    requirement_id: str,
    title: str,
    planned_at: Any = None,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
) -> dict:
    now = now or now_utc()
    req = await require_requirement(session, requirement_id)
    requirement_id = norm_id(req.id)
    claim = await get_active_claim(session, requirement_id)
    planned = _parse_iso(planned_at, "planned_at")
    ms = Milestone(
        id=new_id(), requirement_id=requirement_id, title=title, planned_at=planned,
        actual_at=None, state="planned", created_at=now, updated_at=now,
    )
    session.add(ms)
    await add_event(
        session, requirement_id=requirement_id, kind="decomposition", severity="info",
        title="add_milestone", payload={"milestone_id": ms.id, "title": title},
        actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim.id, milestone_id=ms.id, now=now,
    )
    await lease_svc.touch_activity(session, requirement_id, now)
    return {"requirement_id": requirement_id, "milestone_id": ms.id, "title": title}


async def update_milestone(
    session: AsyncSession,
    *,
    requirement_id: str,
    milestone_id: str,
    state: str,
    actual_at: Any = None,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
) -> dict:
    now = now or now_utc()
    req = await require_requirement(session, requirement_id)
    requirement_id = norm_id(req.id)
    claim = await get_active_claim(session, requirement_id)
    if state not in MILESTONE_STATES:
        raise BusinessError("invalid_record", f"invalid milestone state: {state}", requirement_id)
    ms = await session.scalar(
        select(Milestone).where(Milestone.id == milestone_id, Milestone.requirement_id == requirement_id)
    )
    if ms is None:
        raise BusinessError("not_found", f"milestone not found: {milestone_id}", requirement_id)
    old = ms.state
    ms.state = state
    if actual_at not in (None, ""):
        ms.actual_at = _parse_iso(actual_at, "actual_at")
    ms.updated_at = now
    await add_event(
        session, requirement_id=requirement_id, kind="state_change", severity="info",
        title=f"milestone {old} -> {state}", payload={"milestone_id": milestone_id, "from": old, "to": state},
        actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim.id, milestone_id=milestone_id, now=now,
    )
    await lease_svc.touch_activity(session, requirement_id, now)
    return {"requirement_id": requirement_id, "milestone_id": milestone_id, "state": state}


async def add_record(
    session: AsyncSession,
    *,
    requirement_id: str,
    kind: str,
    title: str,
    content: str | None = None,
    severity: str | None = None,
    payload: Any = None,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
) -> dict:
    now = now or now_utc()
    req = await require_requirement(session, requirement_id)
    requirement_id = norm_id(req.id)
    claim = await get_active_claim(session, requirement_id)
    if kind not in RECORD_KINDS:
        raise BusinessError("invalid_record", f"invalid record kind: {kind}", requirement_id)
    if title is None or not str(title).strip():
        raise BusinessError(
            "invalid_record",
            'add_record requires title: one-line human outline. '
            'e.g. title="选型 SQLite WAL 而非 busy 重试"',
            requirement_id,
        )
    severity = severity or "info"
    if severity not in SEVERITIES:
        raise BusinessError("invalid_record", f"invalid severity: {severity}", requirement_id)
    if kind == "deviation" and severity not in {"attention", "critical"}:
        raise BusinessError("invalid_record", "deviation severity must be >= attention", requirement_id)
    if kind == "decision":
        _validate_decision_payload(payload)
    payload = payload or {}
    _check_payload_size(requirement_id, payload, content)  # PRD §6：payload/content < 8KB
    await add_event(
        session, requirement_id=requirement_id, kind=kind, severity=severity,
        title=title, content=content, payload=payload,
        actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim.id, now=now,
    )
    await lease_svc.touch_activity(session, requirement_id, now)
    return {"requirement_id": requirement_id, "kind": kind}


async def update_progress(
    session: AsyncSession,
    *,
    requirement_id: str,
    note: str,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
    headline: str | None = None,
) -> dict:
    now = now or now_utc()
    req = await require_requirement(session, requirement_id)
    requirement_id = norm_id(req.id)
    claim = await get_active_claim(session, requirement_id)
    if headline is None or not str(headline).strip():
        raise BusinessError(
            "invalid_record",
            'update_progress requires headline: one-line human outline. '
            'e.g. headline="修了 test_view 竞态"',
            requirement_id,
        )
    _check_payload_size(requirement_id, {"note": note}, note)  # PRD §6：单事件 payload < 8KB
    await add_event(
        session, requirement_id=requirement_id, kind="progress_note", severity="info",
        title=str(headline).strip(), content=note, payload={"note": note},
        actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim.id, now=now,
    )
    await lease_svc.touch_activity(session, requirement_id, now)
    return {"requirement_id": requirement_id, "lease_expires_at": claim.lease_expires_at.isoformat()}


async def request_review(
    session: AsyncSession,
    *,
    requirement_id: str,
    evidence: Any = None,
    assessments: Any = None,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
    summary_line: str | None = None,
) -> dict:
    now = now or now_utc()
    req = await require_requirement(session, requirement_id)
    requirement_id = norm_id(req.id)
    if req.state != "CLAIMED":
        raise BusinessError("illegal_state", f"request_review requires state=CLAIMED, got {req.state}", requirement_id)
    claim = await get_active_claim(session, requirement_id, requirement=req)
    evidence = evidence or {}
    if not any(bool(evidence.get(k)) for k in EVIDENCE_FIELDS):
        raise BusinessError(
            "invalid_record",
            "request_review requires at least one evidence item (pr_url/commit_range/test_summary)",
            requirement_id,
        )
    if summary_line is None or not str(summary_line).strip():
        raise BusinessError(
            "invalid_record",
            'request_review requires summary_line: one line of what was done / where to look first. '
            'e.g. summary_line="重做了记录管线，先看事件流"',
            requirement_id,
        )
    subtasks = (await session.scalars(
        select(Subtask).where(Subtask.requirement_id == requirement_id).order_by(Subtask.ordinal)
    )).all()
    validated = _validate_assessments(requirement_id, assessments, subtasks)
    assessment = _persist_self_assessment(validated, subtasks, now)
    req.awaiting_human = {
        "reason": "review requested",
        "evidence": evidence,
        "since": now.isoformat(),
        "kind": "review",
        "summary_line": str(summary_line).strip(),
    }
    await add_event(
        session, requirement_id=requirement_id, kind="review_request", severity="attention",
        title="review requested",
        payload={"evidence": evidence, "summary_line": str(summary_line).strip(),
                 "assessment": assessment},
        actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim.id, now=now,
    )
    await lease_svc.touch_activity(session, requirement_id, now)
    return {"requirement_id": requirement_id, "awaiting_human": req.awaiting_human}


def _assessment_available(subtasks: list) -> str:
    """本需求可用 subtask_id 与验收条目清单（错误消息自纠用，BCD b3.2 S11）。"""
    lines = []
    for st in subtasks:
        items = [str(a.get("item")) for a in (st.acceptance or []) if isinstance(a, dict)]
        lines.append(f"subtask_id={norm_id(st.id)} (state={st.state}): acceptance={items}")
    return "\n".join(lines) if lines else "（本需求无子任务）"


def _validate_assessments(requirement_id: str, assessments: Any, subtasks: list) -> list[dict]:
    """形态+归属+覆盖全量校验（BCD b3.2 I6/I7/I8）：任何一项不合法整单拒写、零写入。"""
    if assessments is None:
        return []
    if not isinstance(assessments, list):
        raise BusinessError(
            "invalid_record",
            f"assessments 必须是列表；正典形态：{ASSESSMENT_FORM_EXAMPLE}\n"
            f"本需求可用：\n{_assessment_available(subtasks)}",
            requirement_id,
        )
    by_id = {norm_id(st.id): st for st in subtasks}
    out: list[dict] = []
    for i, asm in enumerate(assessments):
        loc = f"assessments[{i}]"
        if not isinstance(asm, dict) or not asm.get("subtask_id"):
            raise BusinessError(
                "invalid_record",
                f"{loc} 缺 subtask_id 或形态不是对象；正典形态：{ASSESSMENT_FORM_EXAMPLE}\n"
                f"本需求可用：\n{_assessment_available(subtasks)}",
                requirement_id,
            )
        sid = norm_id(asm["subtask_id"])
        if sid not in by_id:
            raise BusinessError(
                "invalid_record",
                f"{loc} subtask_id={asm['subtask_id']} 不属于本需求；"
                f"本需求可用：\n{_assessment_available(subtasks)}",
                requirement_id,
            )
        items = asm.get("items")
        if not isinstance(items, list):
            raise BusinessError(
                "invalid_record",
                f"{loc} 缺 items 列表；正典形态：{ASSESSMENT_FORM_EXAMPLE}\n"
                f"本需求可用：\n{_assessment_available(subtasks)}",
                requirement_id,
            )
        norm_items = []
        for j, it in enumerate(items):
            iloc = f"{loc}.items[{j}]"
            if not isinstance(it, dict) or not str(it.get("item") or "").strip():
                raise BusinessError(
                    "invalid_record",
                    f"{iloc} 缺 item（验收文本逐字）；正典形态：{ASSESSMENT_FORM_EXAMPLE}\n"
                    f"本需求可用：\n{_assessment_available(subtasks)}",
                    requirement_id,
                )
            state = it.get("state")
            if state not in ASSESSMENT_STATES:
                raise BusinessError(
                    "invalid_record",
                    f"{iloc} state={state!r} 非法，合法枚举：met/not_met/deviated；"
                    f"正典形态：{ASSESSMENT_FORM_EXAMPLE}",
                    requirement_id,
                )
            entry = {"item": str(it["item"]), "state": state}
            if it.get("deviation_reason"):
                entry["deviation_reason"] = str(it["deviation_reason"])
            norm_items.append(entry)
        out.append({"subtask": by_id[sid], "items": norm_items})
    assessed = {(norm_id(v["subtask"].id), it["item"]) for v in out for it in v["items"]}
    missing = []
    for st in subtasks:
        if st.state == "abandoned":
            continue
        for a in (st.acceptance or []):
            if isinstance(a, dict) and (norm_id(st.id), str(a.get("item"))) not in assessed:
                missing.append(f"subtask_id={norm_id(st.id)} 条目「{a.get('item')}」")
    if missing:
        raise BusinessError(
            "invalid_record",
            "assessments 漏评：" + "；".join(missing) +
            "。出路：① 补评漏项后重交；② 若该子任务不再需要，"
            "先 update_subtask(state=abandoned) 将其移出覆盖分母。",
            requirement_id,
        )
    return out


def _persist_self_assessment(validated: list[dict], subtasks: list, now: datetime) -> dict:
    """验收自评持久化到 subtasks.acceptance[].state（按 item 文本精确匹配）。

    只在全量校验通过后调用（BCD b3.2 I8）；返回 payload.assessment 计数
    {required, covered, added, received_subtasks, received_items}（§3）。
    """
    required = sum(
        1 for st in subtasks if st.state != "abandoned"
        for a in (st.acceptance or []) if isinstance(a, dict)
    )
    covered = 0
    added = 0
    for v in validated:
        st = v["subtask"]
        current = list(st.acceptance or [])
        by_item = {str(a.get("item")): a for a in current if isinstance(a, dict)}
        seen: set[str] = set()
        new_acc = []
        for item in v["items"]:
            key = item["item"]
            seen.add(key)
            if key in by_item:
                entry = dict(by_item[key])
                entry["state"] = item["state"]
                if item.get("deviation_reason"):
                    entry["deviation_reason"] = item["deviation_reason"]
                covered += 1
            else:
                entry = dict(item)
                added += 1
            new_acc.append(entry)
        for a in current:
            if not (isinstance(a, dict) and str(a.get("item")) in seen):
                new_acc.append(a)
        st.acceptance = new_acc
        st.updated_at = now
    return {
        "required": required,
        "covered": covered,
        "added": added,
        "received_subtasks": len(validated),
        "received_items": sum(len(v["items"]) for v in validated),
    }


async def mark_blocked(
    session: AsyncSession,
    *,
    requirement_id: str,
    reason: str,
    evidence: str | None = None,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
) -> dict:
    now = now or now_utc()
    req = await require_requirement(session, requirement_id)
    requirement_id = norm_id(req.id)
    if req.state != "CLAIMED":
        raise BusinessError("illegal_state", f"mark_blocked requires state=CLAIMED, got {req.state}", requirement_id)
    claim = await get_active_claim(session, requirement_id, requirement=req)
    if not str(reason).strip():
        raise BusinessError(
            "invalid_record",
            'mark_blocked requires reason: one-line human-readable reason. '
            'e.g. reason="等 user 裁决"',
            requirement_id,
        )
    await transition(
        session, requirement_id=requirement_id, from_state="CLAIMED", to_state="BLOCKED",
        actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim.id, now=now,
        event_payload={"reason": reason},
    )
    await session.execute(
        update(Requirement).where(Requirement.id == requirement_id).values(
            awaiting_human={"reason": reason, "evidence": evidence or "", "since": now.isoformat(), "kind": "blocked"}
        )
    )
    await lease_svc.touch_activity(session, requirement_id, now)
    return {"requirement_id": requirement_id, "state": "BLOCKED"}


# ---------------------------------------------------------------- 读
async def list_tasks(
    session: AsyncSession,
    *,
    status: str | None = None,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
) -> dict:
    now = now or now_utc()
    stmt = select(Requirement)
    if status:
        stmt = stmt.where(Requirement.state == status)
    else:
        stmt = stmt.where(Requirement.state.not_in(TERMINAL_STATES))
    rows = (await session.scalars(stmt.order_by(Requirement.created_at))).all()
    tasks = []
    for r in rows:
        claim = await session.scalar(
            select(Claim).where(Claim.requirement_id == r.id, Claim.ended_at.is_(None))
        )
        tasks.append(
            {
                "requirement_id": norm_id(r.id),
                "title": r.title,
                "state": r.state,
                "awaiting_human": r.awaiting_human,
                "claim": _claim_view(claim, r.awaiting_human, now),
            }
        )
    return {"tasks": tasks}


async def get_task_detail(
    session: AsyncSession,
    *,
    requirement_id: str,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
) -> dict:
    """需求深潜数据（委托 view.detail 单一源）：关键事件 = 最新 200（event_limit=200，
    先 limit 后 filter，输出 seq 升序；R3，BCD distill-pipeline 裁决 3）。"""
    from .view import detail as _view_detail

    now = now or now_utc()
    return await _view_detail(
        session, requirement_id=requirement_id, event_limit=200,
        actor_surface=actor_surface, actor_conn=actor_conn, now=now,
    )


async def list_awaiting(
    session: AsyncSession,
    *,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
) -> dict:
    now = now or now_utc()
    rows = (await session.scalars(
        select(Requirement).where(Requirement.awaiting_human.isnot(None)).order_by(Requirement.updated_at)
    )).all()
    out = []
    for r in rows:
        claim = await session.scalar(
            select(Claim).where(Claim.requirement_id == r.id, Claim.ended_at.is_(None))
        )
        since = _parse_iso((r.awaiting_human or {}).get("since"), "since")
        waiting = (now - since).total_seconds() if since else None
        out.append(
            {
                "requirement_id": norm_id(r.id),
                "title": r.title,
                "state": r.state,
                "awaiting_human": r.awaiting_human,
                "waiting_seconds": waiting,
                "claim": _claim_view(claim, r.awaiting_human, now),
            }
        )
    return {"awaiting": out}


# ---------------------------------------------------------------- 导出（JSON/Markdown/CSV 全量，无 LIMIT）
async def export_data(
    session: AsyncSession,
    *,
    requirement_id: str | None = None,
    fmt: str = "json",
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
) -> dict | str:
    """PRD 4.2 export：JSON / Markdown / CSV 全量导出（G8 P2-4：独立全量查询，无 LIMIT）。"""
    from .view import detail as _view_detail

    now = now or now_utc()
    if fmt not in ("json", "markdown", "csv"):
        raise BusinessError("invalid_record", f"invalid export format: {fmt}", None)
    if requirement_id:
        data = {
            "requirement": await _view_detail(
                session, requirement_id=requirement_id, event_limit=None,
                actor_surface=actor_surface, actor_conn=actor_conn, now=now,
            )
        }
    else:
        rows = (await session.scalars(select(Requirement).order_by(Requirement.created_at))).all()
        data = {
            "requirements": [
                await _view_detail(
                    session, requirement_id=r.id, event_limit=None,
                    actor_surface=actor_surface, actor_conn=actor_conn, now=now,
                ) for r in rows
            ]
        }
    if fmt == "markdown":
        from .view import render_export_markdown

        return render_export_markdown(data)
    if fmt == "csv":
        from .view import render_export_csv

        return render_export_csv(data)
    return data


# ---------------------------------------------------------------- 数据保留（PRD §6，G9-a 闭合）
PRUNE_TERMINAL_STATES = TERMINAL_STATES


def _prune_targets(cutoff: datetime):
    """终态需求级原子窗口（审#P1-2/P1-A）：终态且全部事件早于 cutoff 的需求整删，
    非终态（含僵尸/STALE）全留 = 活审计主体。COUNT 与 DELETE 共享同一谓词表达式（审#P2-6）。"""
    return (
        select(Event.requirement_id)
        .join(Requirement, Requirement.id == Event.requirement_id)
        .where(Requirement.state.in_(PRUNE_TERMINAL_STATES))
        .group_by(Event.requirement_id)
        .having(func.max(Event.ts) < cutoff)
    )


async def count_prunable_events(session: AsyncSession, *, cutoff: datetime) -> int:
    """将删事件数（读，与 prune_events 共享同一谓词表达式）。"""
    subq = _prune_targets(cutoff)
    return await session.scalar(
        select(func.count()).select_from(Event).where(Event.requirement_id.in_(subq))
    ) or 0


async def prune_events(session: AsyncSession, *, cutoff: datetime) -> int:
    """单事务按终态需求级原子谓词删除并返回删除数（PRD §6 数据保留；清理前导出由 CLI 保证）。"""
    subq = _prune_targets(cutoff)
    res = await session.execute(delete(Event).where(Event.requirement_id.in_(subq)))
    return res.rowcount or 0
