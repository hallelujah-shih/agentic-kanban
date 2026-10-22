"""业务操作层：MCP 工具与 CLI 共用的写/读原语。全部在单事务内执行
（run_op + BEGIN IMMEDIATE），seq/ts 服务端同事务签发。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import MAX_ACTIVE_CLAIMS, idle_seconds, lease_seconds, now_utc
from ..errors import BusinessError
from ..models import Claim, Event, Milestone, Requirement, Subtask, new_id
from . import lease as lease_svc
from .operations_util import add_event, normalize_anchors, normalize_title
from .state_machine import transition
from .write_guard import count_active_claims, get_active_claim, require_requirement

RECORD_KINDS = {"decision", "risk", "deviation", "decomposition", "note"}
SEVERITIES = {"info", "attention", "critical"}
SUBTASK_STATES = {"todo", "in_progress", "done", "blocked", "abandoned"}
MILESTONE_STATES = {"planned", "in_progress", "achieved"}
EVIDENCE_FIELDS = ("pr_url", "commit_range", "test_summary")
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
) -> dict:
    now = now or now_utc()
    req = await require_requirement(session, requirement_id)
    if req.state == "CLAIMED":
        # CLAIMED -> DONE：人确认终态 + claim ended_at 同事务 + 清 marker
        await transition(
            session, requirement_id=requirement_id, from_state="CLAIMED", to_state="DONE",
            actor_surface=actor_surface, actor_conn=actor_conn, now=now,
        )
        await session.execute(
            update(Claim).where(Claim.requirement_id == requirement_id, Claim.ended_at.is_(None)).values(ended_at=now)
        )
        await add_event(
            session, requirement_id=requirement_id, kind="approval", severity="info",
            title="approved", payload={"state": "DONE"},
            actor_surface=actor_surface, actor_conn=actor_conn, now=now,
        )
        return {"requirement_id": requirement_id, "state": "DONE"}
    if req.state == "BLOCKED":
        await transition(
            session, requirement_id=requirement_id, from_state="BLOCKED", to_state="CLAIMED",
            actor_surface=actor_surface, actor_conn=actor_conn, now=now,
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
) -> dict:
    now = now or now_utc()
    if not reason or not str(reason).strip():
        raise BusinessError("invalid_record", "release requires a reason", requirement_id)
    claim = await session.scalar(
        select(Claim).where(Claim.requirement_id == requirement_id, Claim.ended_at.is_(None))
    )
    if claim is None:
        await require_requirement(session, requirement_id)
        raise BusinessError("not_found", f"no active claim to release for {requirement_id}", requirement_id)
    await transition(
        session, requirement_id=requirement_id, from_state="CLAIMED", to_state="OPEN",
        actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim.id, now=now,
    )
    await session.execute(
        update(Claim).where(Claim.id == claim.id).values(ended_at=now, release_reason=reason)
    )
    await add_event(
        session, requirement_id=requirement_id, kind="release", severity="info",
        title="released", payload={"reason": reason, "agent_name": claim.agent_name},
        actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim.id, now=now,
    )
    return {"requirement_id": requirement_id, "state": "OPEN", "claim_id": claim.id}


async def release_all_stale(
    session: AsyncSession,
    *,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
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
            )
            await session.execute(
                update(Claim).where(Claim.id == claim.id).values(ended_at=now, release_reason="stale")
            )
            await add_event(
                session, requirement_id=r.id, kind="release", severity="info",
                title="released", payload={"reason": "stale", "agent_name": claim.agent_name},
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
) -> dict:
    now = now or now_utc()
    await require_requirement(session, requirement_id)
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
    return {"requirement_id": requirement_id, "lease_expires_at": new_expiry.isoformat()}


async def note(
    session: AsyncSession,
    *,
    requirement_id: str,
    content: str,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
) -> dict:
    now = now or now_utc()
    await require_requirement(session, requirement_id)
    await add_event(
        session, requirement_id=requirement_id, kind="note", severity="info",
        title="note", content=content, payload={"content": content},
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
) -> dict:
    """PRD 4.2（审#2-reopen）：`reopen` = DONE->REOPEN（避免死端）；
    `--continue` = REOPEN->OPEN（回到可认领）。REOPEN->CANCELLED 由 abandon 覆盖。"""
    now = now or now_utc()
    await require_requirement(session, requirement_id)
    if continue_:
        await transition(
            session, requirement_id=requirement_id, from_state="REOPEN", to_state="OPEN",
            actor_surface=actor_surface, actor_conn=actor_conn, now=now,
        )
        return {"requirement_id": requirement_id, "state": "OPEN"}
    await transition(
        session, requirement_id=requirement_id, from_state="DONE", to_state="REOPEN",
        actor_surface=actor_surface, actor_conn=actor_conn, now=now,
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
) -> dict:
    now = now or now_utc()
    req = await require_requirement(session, requirement_id)
    claim = await session.scalar(
        select(Claim).where(Claim.requirement_id == requirement_id, Claim.ended_at.is_(None))
    )
    claim_id = claim.id if claim is not None else None
    if to_state == "REJECTED":
        await transition(
            session, requirement_id=requirement_id, from_state=None, to_state="REJECTED",
            actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim_id, now=now,
        )
    elif to_state == "CANCELLED":
        if req.state not in ("OPEN", "REOPEN"):
            raise BusinessError("illegal_state", f"cannot cancel from state {req.state}", requirement_id)
        await transition(
            session, requirement_id=requirement_id, from_state=req.state, to_state="CANCELLED",
            actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim_id, now=now,
        )
    else:
        raise BusinessError("invalid_record", f"invalid abandon state: {to_state}", requirement_id)
    # G8 P2-3：REJECTED/CANCELLED 同事务置 claim ended_at（+清 marker 由 transition 完成 + 事件同事务）
    if claim is not None:
        await session.execute(
            update(Claim).where(Claim.id == claim.id).values(ended_at=now, release_reason=f"abandon:{to_state}")
        )
    return {"requirement_id": requirement_id, "state": to_state}


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
    await require_requirement(session, requirement_id)
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
    await lease_svc.touch_activity(session, requirement_id, now)
    return {"requirement_id": requirement_id, "subtask_id": subtask_id, "state": state}


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
    claim = await get_active_claim(session, requirement_id)
    if kind not in RECORD_KINDS:
        raise BusinessError("invalid_record", f"invalid record kind: {kind}", requirement_id)
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
) -> dict:
    now = now or now_utc()
    claim = await get_active_claim(session, requirement_id)
    await add_event(
        session, requirement_id=requirement_id, kind="progress_note", severity="info",
        title="progress", content=note, payload={"note": note},
        actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim.id, now=now,
    )
    await lease_svc.touch_activity(session, requirement_id, now)
    return {"requirement_id": requirement_id}


async def request_review(
    session: AsyncSession,
    *,
    requirement_id: str,
    evidence: Any = None,
    assessments: Any = None,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
) -> dict:
    now = now or now_utc()
    req = await require_requirement(session, requirement_id)
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
    await _persist_self_assessment(session, requirement_id, assessments or [], now)
    req.awaiting_human = {
        "reason": "review requested",
        "evidence": evidence,
        "since": now.isoformat(),
        "kind": "review",
    }
    await add_event(
        session, requirement_id=requirement_id, kind="review_request", severity="info",
        title="review requested", payload={"evidence": evidence},
        actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim.id, now=now,
    )
    await lease_svc.touch_activity(session, requirement_id, now)
    return {"requirement_id": requirement_id, "awaiting_human": req.awaiting_human}


async def _persist_self_assessment(session: AsyncSession, requirement_id: str, assessments: list, now: datetime) -> None:
    """验收自评持久化到 subtasks.acceptance[].state（按 item 文本精确匹配）。"""
    for asm in assessments:
        if not isinstance(asm, dict):
            continue
        sid = asm.get("subtask_id")
        if not sid:
            continue
        st = await session.scalar(
            select(Subtask).where(Subtask.id == sid, Subtask.requirement_id == requirement_id)
        )
        if st is None:
            continue
        current = list(st.acceptance or [])
        by_item = {str(a.get("item")): a for a in current if isinstance(a, dict)}
        new_acc = []
        for item in asm.get("items", []):
            if not isinstance(item, dict):
                continue
            key = str(item.get("item"))
            if key in by_item:
                entry = dict(by_item[key])
                entry["state"] = item.get("state", "met")
                if item.get("deviation_reason"):
                    entry["deviation_reason"] = item["deviation_reason"]
                new_acc.append(entry)
            else:
                new_acc.append(dict(item))
        covered = {str(i.get("item")) for i in asm.get("items", []) if isinstance(i, dict)}
        for a in current:
            if str(a.get("item")) not in covered:
                new_acc.append(a)
        st.acceptance = new_acc
        st.updated_at = now


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
    if req.state != "CLAIMED":
        raise BusinessError("illegal_state", f"mark_blocked requires state=CLAIMED, got {req.state}", requirement_id)
    claim = await get_active_claim(session, requirement_id, requirement=req)
    await transition(
        session, requirement_id=requirement_id, from_state="CLAIMED", to_state="BLOCKED",
        actor_surface=actor_surface, actor_conn=actor_conn, claim_id=claim.id, now=now,
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
        stmt = stmt.where(Requirement.state.not_in(["DONE", "REJECTED", "CANCELLED"]))
    rows = (await session.scalars(stmt.order_by(Requirement.created_at))).all()
    tasks = []
    for r in rows:
        claim = await session.scalar(
            select(Claim).where(Claim.requirement_id == r.id, Claim.ended_at.is_(None))
        )
        tasks.append(
            {
                "requirement_id": r.id,
                "title": r.title,
                "state": r.state,
                "awaiting_human": r.awaiting_human,
                "claim": lease_svc.claim_view(claim, r.awaiting_human, now),
            }
        )
    return {"tasks": tasks}


async def _requirement_detail(
    session: AsyncSession,
    requirement_id: str,
    *,
    event_limit: int | None,
    now: datetime | None = None,
) -> dict:
    """需求深潜数据组装（MCP get_task_detail 与 export 共用）。event_limit=None 全量（G8 P2-4）。"""
    now = now or now_utc()
    req = await require_requirement(session, requirement_id)
    claim = await session.scalar(
        select(Claim).where(Claim.requirement_id == requirement_id, Claim.ended_at.is_(None))
    )
    subtasks = (await session.scalars(
        select(Subtask).where(Subtask.requirement_id == requirement_id).order_by(Subtask.ordinal)
    )).all()
    milestones = (await session.scalars(
        select(Milestone).where(Milestone.requirement_id == requirement_id).order_by(Milestone.created_at)
    )).all()
    stmt = select(Event).where(Event.requirement_id == requirement_id).order_by(Event.seq)
    if event_limit is not None:
        stmt = stmt.limit(event_limit)
    events = (await session.scalars(stmt)).all()
    return {
        "requirement_id": req.id,
        "title": req.title,
        "description": req.description,
        "source": req.source,
        "source_ref": req.source_ref,
        "state": req.state,
        "acceptance": req.acceptance,
        "awaiting_human": req.awaiting_human,
        "claim": lease_svc.claim_view(claim, req.awaiting_human, now),
        "claims": [
            {k: v for k, v in (lease_svc.claim_view(c, None, now) or {}).items()}
            for c in (
                await session.scalars(
                    select(Claim).where(Claim.requirement_id == requirement_id).order_by(Claim.started_at)
                )
            ).all()
        ],
        "subtasks": [
            {
                "subtask_id": s.id, "ordinal": s.ordinal, "title": s.title, "state": s.state,
                "acceptance": s.acceptance, "milestone_id": s.milestone_id,
                "created_at": s.created_at.isoformat(), "updated_at": s.updated_at.isoformat(),
            }
            for s in subtasks
        ],
        "milestones": [
            {
                "milestone_id": m.id, "title": m.title, "state": m.state,
                "planned_at": m.planned_at.isoformat() if m.planned_at else None,
                "actual_at": m.actual_at.isoformat() if m.actual_at else None,
            }
            for m in milestones
        ],
        "events": [
            {
                "seq": e.seq, "kind": e.kind, "severity": e.severity, "title": e.title,
                "content": e.content, "payload": e.payload,
                "actor_surface": e.actor_surface, "actor_conn": e.actor_conn,
                "claim_id": e.claim_id, "ts": e.ts.isoformat(),
            }
            for e in events
        ],
    }


async def get_task_detail(
    session: AsyncSession,
    *,
    requirement_id: str,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
) -> dict:
    now = now or now_utc()
    return await _requirement_detail(
        session, requirement_id, event_limit=200, now=now,
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
                "requirement_id": r.id,
                "title": r.title,
                "state": r.state,
                "awaiting_human": r.awaiting_human,
                "waiting_seconds": waiting,
                "claim": lease_svc.claim_view(claim, r.awaiting_human, now),
            }
        )
    return {"awaiting": out}


# ---------------------------------------------------------------- 导出（JSON/Markdown 全量，无 LIMIT）
async def export_data(
    session: AsyncSession,
    *,
    requirement_id: str | None = None,
    fmt: str = "json",
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
) -> dict | str:
    """PRD 4.2 export：JSON / Markdown 全量导出（G8 P2-4：独立全量查询，无 LIMIT）。"""
    now = now or now_utc()
    if fmt not in ("json", "markdown"):
        raise BusinessError("invalid_record", f"invalid export format: {fmt}", None)
    if requirement_id:
        data = {
            "requirement": await _requirement_detail(
                session, requirement_id, event_limit=None, now=now,
            )
        }
    else:
        rows = (await session.scalars(select(Requirement).order_by(Requirement.created_at))).all()
        data = {
            "requirements": [
                await _requirement_detail(session, r.id, event_limit=None, now=now) for r in rows
            ]
        }
    if fmt == "markdown":
        from .view import render_export_markdown

        return render_export_markdown(data)
    return data
