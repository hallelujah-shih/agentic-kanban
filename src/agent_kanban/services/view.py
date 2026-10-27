"""视图服务（PRD 5.3/5.4）：摘要 dict + 深潜 dict + 文本/HTML 渲染 + 导出 Markdown。

口径钉死：
- 里程碑延误：planned_at 未达成且超期（overdue）/ achieved 且 actual_at>planned_at（late）。
- 决策/风险/偏离：deviation 无条件；risk severity>=attention；decision 全展示（结构化字段，无 content）。
- 验收对照表（下界语义）：per 锚 -> 链接子任务验收项文本+状态；无链接 -> uncovered。
- 进度派生值：done/total；blocked=进行中（计分母不计 done）；abandoned 不计分母。
- 拆解新增：进入 CLAIMED 后有 add_subtask（decomposition）且该 CLAIMED 期间无 decision/deviation 解释。
- 未解释放弃：abandoned 子任务无同 subtask_id 的 deviation/note 事件（payload.subtask_id 关联）。
- retry_limit：G9-b 系统 marker（kind=risk + severity>=attention + payload.retry_limit + actor_surface=system，
  幂等/信号谓词同一，BCD g9b-retry-limit）-> {"type": "retry_limit", "count": N} 入需要关注区。
- 深潜状态重建：按 seq 回放 state_change 链到目标 ts。
- AC13 禁止面：摘要不含 progress_note content 全文/事件长 content/run_logs。
"""

from __future__ import annotations

import csv
import html
import io
import json
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import idle_seconds, now_utc
from ..models import Claim, Event, Milestone, Requirement, Subtask
from . import lease as lease_svc
from .ids import norm_id as _nid
from .retry_limit import is_retry_limit_event
from .write_guard import require_requirement
from .operations_util import TERMINAL_STATES

# 审#P2-A：整删需求（零事件且非 OPEN）深潜视图的历史注记——链已被保留窗口清理，
# 完整历史见导出归档（PRD §6 回溯承诺限于保留窗口 + C7 措辞对齐）。
HISTORY_NOTE = "该需求事件已按保留窗口清理，完整历史见导出归档"

# R3（BCD distill-pipeline §3 Policy 4）：人/机分类单点派生——所有读点同源，
# 禁各读点字符串匹配 kind + payload 形状。未登记 kind -> "human"（保守：宁可人面
# 多显示，不把人面记录藏进簿记，防未来 kind 漂移时静默藏记录）。
BOOKKEEPING_KINDS = {"state_change", "decomposition", "reconcile", "release", "renew"}


def event_audience(kind: str) -> str:
    """kind -> audience 分类单点（"bookkeeping" / "human"，BCD §3 Policy 4）。"""
    return "bookkeeping" if kind in BOOKKEEPING_KINDS else "human"


# ---------------------------------------------------------------- 摘要
async def summary(
    session: AsyncSession,
    *,
    requirement_id: str,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
) -> dict:
    now = now or now_utc()
    req = await require_requirement(session, requirement_id)
    requirement_id = _nid(req.id)
    claim = await session.scalar(
        select(Claim).where(Claim.requirement_id == requirement_id, Claim.ended_at.is_(None))
    )
    subtasks = (await session.scalars(
        select(Subtask).where(Subtask.requirement_id == requirement_id).order_by(Subtask.ordinal)
    )).all()
    milestones = (await session.scalars(
        select(Milestone).where(Milestone.requirement_id == requirement_id).order_by(Milestone.created_at)
    )).all()
    events = (await session.scalars(
        select(Event).where(Event.requirement_id == requirement_id).order_by(Event.seq)
    )).all()

    milestone_rows = [_milestone_row(m, now) for m in milestones]

    decisions: list[dict] = []
    deviations: list[dict] = []
    for e in events:
        if e.kind == "decision":
            payload = e.payload or {}
            decisions.append({
                "seq": e.seq, "ts": e.ts.isoformat(), "title": e.title,
                "choice": payload.get("choice"),
                "rationale": payload.get("rationale"),
                "alternatives": payload.get("alternatives") or [],
                "actor_surface": e.actor_surface, "actor_conn": e.actor_conn,
            })
        elif e.kind == "deviation":
            deviations.append({
                "seq": e.seq, "ts": e.ts.isoformat(), "title": e.title,
                "severity": e.severity, "payload": e.payload,
                "actor_conn": e.actor_conn,
            })
    risks = _risk_rows(events)

    # 验收对照表（下界语义：只保证未链接锚项必然显示缺口）
    table = _acceptance_table(list(req.acceptance or []), subtasks)

    # 进度派生值：done/total；blocked=进行中；abandoned 不计分母
    progress = _progress_dict([s.state for s in subtasks])

    needs_attention = _derived_signals(
        subtasks, milestones, events, milestone_rows,
        claim=claim, state=req.state, awaiting_human=req.awaiting_human, now=now,
    )

    return {
        "requirement_id": _nid(req.id),
        "title": req.title,
        "description": req.description,
        "source": req.source,
        "source_ref": req.source_ref,
        "state": req.state,
        "awaiting_human": req.awaiting_human,
        "claim": _claim_view(claim, req.awaiting_human, now),
        "milestones": milestone_rows,
        "decisions": decisions,
        "risks": risks,
        "deviations": deviations,
        "acceptance_table": table,
        "subtasks": [
            {
                "subtask_id": _nid(s.id), "ordinal": s.ordinal, "title": s.title,
                "state": s.state, "milestone_id": _nid(s.milestone_id) if s.milestone_id else None,
            }
            for s in subtasks
        ],
        "progress": progress,
        "needs_attention": needs_attention,
        "created_at": req.created_at.isoformat(),
        "updated_at": req.updated_at.isoformat(),
    }


def _milestone_row(m: Milestone, now: datetime) -> dict:
    """里程碑行（审#P2-2 共享 helper，summary 与 board 同口径）：
    planned_at 未达成且超期 -> overdue；achieved 且 actual_at>planned_at -> late。"""
    delay = None
    if m.state != "achieved" and m.planned_at is not None and now > m.planned_at:
        delay = "overdue"
    elif m.state == "achieved" and m.actual_at is not None and m.planned_at is not None and m.actual_at > m.planned_at:
        delay = "late"
    return {
        "milestone_id": _nid(m.id), "title": m.title, "state": m.state,
        "planned_at": m.planned_at.isoformat() if m.planned_at else None,
        "actual_at": m.actual_at.isoformat() if m.actual_at else None,
        "delay": delay,
    }


def _progress_dict(states: list[str]) -> dict:
    """进度派生值（审#P2-2 共享 helper）：done/total；blocked=进行中；abandoned 不计分母。"""
    total = sum(1 for s in states if s != "abandoned")
    done = sum(1 for s in states if s == "done")
    return {
        "done": done,
        "total": total,
        "remaining": total - done,
        "blocked": sum(1 for s in states if s == "blocked"),
        "abandoned": sum(1 for s in states if s == "abandoned"),
    }


def _risk_rows(events: list[Event]) -> list[dict]:
    """risk 计数口径（审#P2-1 共享 helper）：severity>=attention 才展示（PRD 5.3）。"""
    return [
        {
            "seq": e.seq, "ts": e.ts.isoformat(), "title": e.title,
            "severity": e.severity, "actor_conn": e.actor_conn,
        }
        for e in events if e.kind == "risk" and e.severity in ("attention", "critical")
    ]


def _acceptance_table(anchors: list, subtasks: list[Subtask]) -> list[dict]:
    """验收对照表（审#P2-2 共享 helper，下界语义：只保证未链接锚项必然显示缺口）。"""
    table = []
    for a in anchors:
        aid = str(a.get("id") or a.get("item"))
        linked = []
        for st in subtasks:
            for acc in (st.acceptance or []):
                if not isinstance(acc, dict):
                    continue
                refs = acc.get("links_to") or []
                if isinstance(refs, str):
                    refs = [refs]
                if aid in {str(x) for x in refs}:
                    linked.append({
                        "subtask_id": _nid(st.id), "subtask_title": st.title,
                        "item": acc.get("item"), "state": acc.get("state"),
                        "criteria": acc.get("criteria"),
                    })
        table.append({
            "anchor_id": aid, "item": a.get("item"),
            "linked": linked, "uncovered": len(linked) == 0,
        })
    return table


def _terminal_entry_ts(events: list[Event]) -> str | None:
    """最近一次需求级进入终态的 ts（判别口径与 reconstruct_states 一致：
    state_change 且 payload 无 subtask_id/milestone_id）；未入终态为 None。"""
    ts = None
    for e in events:
        p = e.payload or {}
        if e.kind == "state_change" and not p.get("subtask_id") and not p.get("milestone_id") \
                and p.get("to") in TERMINAL_STATES:
            ts = e.ts
    return ts.isoformat() if ts is not None else None


async def board(
    session: AsyncSession,
    *,
    status: str | None = None,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
) -> dict:
    """看板默认列表（PRD 5.3 + 审#P1-2）：非终态默认过滤 + status 过滤；
    每需求 needs_attention = _derived_signals 全口径（与 summary 同源，零假阴性）；
    progress/milestone delay/coverage/risk 口径与 summary 同源（审#P2-1/P2-2）。

    M1-3.4b（G5）：claims/subtasks/milestones/events 按 rids 分组批量查询 + Python
    内存分组（order_by 与逐需求查询相同，逐需求相对顺序/过滤/排序不变），替代 N+1
    逐需求查询。审#P2-5：同一 DB 优化前后 board dict 全等已用确定性种子验证
    （docs/ops/m1-3-verification.md）。"""
    now = now or now_utc()
    stmt = select(Requirement)
    if status:
        stmt = stmt.where(Requirement.state == status)
    else:
        stmt = stmt.where(Requirement.state.not_in(TERMINAL_STATES))
    rows = (await session.scalars(stmt.order_by(Requirement.created_at))).all()
    if not rows:
        return {"tasks": [], "attention_ids": []}
    rids = [r.id for r in rows]
    active_claims = (await session.scalars(
        select(Claim).where(Claim.requirement_id.in_(rids), Claim.ended_at.is_(None))
    )).all()
    subtasks = (await session.scalars(
        select(Subtask).where(Subtask.requirement_id.in_(rids)).order_by(Subtask.ordinal)
    )).all()
    milestones = (await session.scalars(
        select(Milestone).where(Milestone.requirement_id.in_(rids)).order_by(Milestone.created_at)
    )).all()
    events = (await session.scalars(
        select(Event).where(Event.requirement_id.in_(rids)).order_by(Event.seq)
    )).all()
    claim_by_rid = {c.requirement_id: c for c in active_claims}
    subtasks_by_rid: dict[str, list[Subtask]] = defaultdict(list)
    for s in subtasks:
        subtasks_by_rid[s.requirement_id].append(s)
    milestones_by_rid: dict[str, list[Milestone]] = defaultdict(list)
    for m in milestones:
        milestones_by_rid[m.requirement_id].append(m)
    events_by_rid: dict[str, list[Event]] = defaultdict(list)
    for e in events:
        events_by_rid[e.requirement_id].append(e)
    tasks = []
    for r in rows:
        r_claim = claim_by_rid.get(r.id)
        r_subtasks = subtasks_by_rid.get(r.id, [])
        r_milestones = milestones_by_rid.get(r.id, [])
        r_events = events_by_rid.get(r.id, [])
        milestone_rows = [_milestone_row(m, now) for m in r_milestones]
        needs_attention = _derived_signals(
            r_subtasks, r_milestones, r_events, milestone_rows,
            claim=r_claim, state=r.state, awaiting_human=r.awaiting_human, now=now,
        )
        tasks.append({
            "requirement_id": _nid(r.id),
            "title": r.title,
            "state": r.state,
            "awaiting_human": r.awaiting_human,
            "claim": _claim_view(r_claim, r.awaiting_human, now),
            "progress": _progress_dict([s.state for s in r_subtasks]),
            "needs_attention": needs_attention,
            "risks": _risk_rows(r_events),
            # 回溯要点（已完成视图用）：全部从既有事件流派生
            "decision_count": sum(1 for e in r_events if e.kind == "decision"),
            "deviation_count": sum(1 for e in r_events if e.kind == "deviation"),
            "reviewed": any(e.kind == "review_request" for e in r_events),
            "finished_at": _terminal_entry_ts(r_events),
        })
    attention_ids = [t["requirement_id"] for t in tasks if t["needs_attention"]]
    return {"tasks": tasks, "attention_ids": attention_ids}


def _claim_view(claim: Claim | None, awaiting_human: dict | None, now: datetime) -> dict | None:
    v = lease_svc.claim_view(claim, awaiting_human, now)
    if v is not None:
        v["claim_id"] = _nid(v["claim_id"])
    return v


async def _claim_timeline(session: AsyncSession, requirement_id: str, now: datetime) -> list[dict]:
    """claims 时间轴（回溯判据 3：谁在什么时候做了什么，含 release_reason）。"""
    claims = (await session.scalars(
        select(Claim).where(Claim.requirement_id == requirement_id).order_by(Claim.started_at)
    )).all()
    out = []
    for c in claims:
        v = _claim_view(c, None, now)
        if v is not None:
            out.append(v)
    return out


def _derived_signals(
    subtasks: list[Subtask],
    milestones: list[Milestone],
    events: list[Event],
    milestone_rows: list[dict],
    *,
    claim: Claim | None = None,
    state: str | None = None,
    awaiting_human: dict | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """派生偏离信号（系统推导，不依赖 agent 自愿登记，PRD 5.3）+ reconcile 产物
    （审#8：ORPHANED/drift 入需要关注区，观测在视图时点仍成立才显示）。"""
    out: list[dict] = []
    subtask_ids = {_nid(s.id) for s in subtasks}
    explained: set[str] = set()
    for e in events:
        if e.kind in ("deviation", "note"):
            pid = (e.payload or {}).get("subtask_id")
            if pid and _nid(pid) in subtask_ids:
                explained.add(_nid(pid))
    for s in subtasks:
        sid = _nid(s.id)
        if s.state == "blocked":
            out.append({"type": "blocked_subtask", "subtask_id": sid, "title": s.title})
        elif s.state == "abandoned":
            out.append({"type": "abandoned_subtask", "subtask_id": sid, "title": s.title})
            if sid not in explained:
                out.append({"type": "unexplained_abandonment", "subtask_id": sid, "title": s.title})
    for m, row in zip(milestones, milestone_rows):
        if row["delay"]:
            out.append({
                "type": "milestone_delay", "milestone_id": _nid(m.id), "title": m.title, "delay": row["delay"],
            })
    for iv in _claimed_intervals(events):
        if iv["decompositions"] > 0 and iv["explanations"] == 0:
            out.append({"type": "decomposition_added", "count": iv["decompositions"]})
    _append_retry_limit_signal(out, events)
    _append_reconcile_signals(out, events, claim, state, awaiting_human, now)
    return out


def _append_retry_limit_signal(out: list[dict], events: list[Event]) -> None:
    """G9-b retry_limit 派生信号（BCD §2/§5）：与幂等谓词同一（含 actor_surface=system，
    审#P1-1/P3-4）检查 marker；幂等只出一次，count=marker 触发时点快照。入 needs_attention
    （摘要/看板/详情同源，PRD §3.2「入摘要需要关注区」）。"""
    for e in events:
        if is_retry_limit_event(e):
            out.append({"type": "retry_limit", "count": (e.payload or {}).get("count")})
            return


def _append_reconcile_signals(
    out: list[dict], events: list[Event], claim: Claim | None, state: str | None,
    awaiting_human: dict | None, now: datetime | None,
) -> None:
    """reconcile 产物入需要关注区：ORPHANED + claim-state drift。只读最新一条
    reconcile 事件；观测在视图时点仍成立才显示（claim 释放/恢复活动/状态修复后
    自愈，不残留陈旧信号）。"""
    now = now or now_utc()
    rec = [e for e in events if e.kind == "reconcile"]
    if not rec:
        return
    payload = rec[-1].payload or {}
    findings = payload.get("findings") or []
    if findings and findings[0].get("signal") == "orphaned":
        cid = findings[0].get("claim_id")
        if claim is not None and claim.id == cid and not awaiting_human \
                and now <= claim.lease_expires_at \
                and (now - claim.last_activity_at).total_seconds() > idle_seconds():
            out.append({"type": "orphaned_claim", "claim_id": _nid(cid), "title": claim.agent_name})
    for d in payload.get("drift") or []:
        if _drift_holds(d, claim, state):
            out.append({
                "type": "claim_state_drift", "title": d.get("type"), "state": d.get("state"),
                "claim_id": _nid(d["claim_id"]) if d.get("claim_id") else None,
            })


def _drift_holds(d: dict, claim: Claim | None, state: str | None) -> bool:
    """drift 在视图时点是否仍成立（BLOCKED 有 claim 合法，不报 claim_without_claimed）。"""
    t = d.get("type")
    if t == "claim_without_claimed":
        return claim is not None and state not in ("CLAIMED", "BLOCKED")
    if t == "claimed_without_claim":
        return claim is None and state == "CLAIMED"
    return False


def _requirement_state_changes(events: list[Event]) -> list[Event]:
    """需求级 state_change（state_machine.transition 写，payload 无 subtask_id/milestone_id）；
    子任务/里程碑级 state_change（update_subtask/update_milestone 写）不参与需求状态重建。"""
    return [e for e in events if e.kind == "state_change"
            and not (e.payload or {}).get("subtask_id")
            and not (e.payload or {}).get("milestone_id")]


def _claimed_intervals(events: list[Event]) -> list[dict]:
    """按 seq 回放需求级 state_change 链，找全部 CLAIMED 期间；统计期间内
    decomposition（拆解新增）与 decision/deviation（解释）事件数。"""
    intervals: list[dict] = []
    cur: str | None = None
    for e in _requirement_state_changes(events):
        to = (e.payload or {}).get("to")
        if to == "CLAIMED" and cur != "CLAIMED":
            cur = "CLAIMED"
            intervals.append({"start": e.seq, "end": None, "decompositions": 0, "explanations": 0})
        elif cur == "CLAIMED" and to != "CLAIMED":
            intervals[-1]["end"] = e.seq
            cur = to
    for e in events:
        for iv in intervals:
            if iv["start"] <= e.seq and (iv["end"] is None or e.seq <= iv["end"]):
                # 拆解新增只计 add_subtask 的 decomposition（payload 含 subtask_id）；
                # add_milestone 也写 decomposition（payload 仅 milestone_id），不构成拆解新增
                if e.kind == "decomposition" and (e.payload or {}).get("subtask_id"):
                    iv["decompositions"] += 1
                elif e.kind in ("decision", "deviation"):
                    iv["explanations"] += 1
                break
    return intervals


# ---------------------------------------------------------------- 深潜
def reconstruct_states(events: list[Event], as_of: datetime | None = None) -> dict[int, str]:
    """算法钉死（PRD 5.4）：按 seq 回放需求级 state_change 链，重建每事件时点需求状态。
    初始 OPEN（new_requirement 唯一创建路径）；as_of 截断到目标 ts。"""
    cur = "OPEN"
    out: dict[int, str] = {}
    for e in sorted(events, key=lambda x: x.seq):
        if as_of is not None and e.ts > as_of:
            continue
        if e.kind == "state_change" and not (e.payload or {}).get("subtask_id") \
                and not (e.payload or {}).get("milestone_id"):
            cur = (e.payload or {}).get("to") or cur
        out[e.seq] = cur
    return out


async def detail(
    session: AsyncSession,
    *,
    requirement_id: str,
    kinds: list[str] | None = None,
    severities: list[str] | None = None,
    as_of: datetime | None = None,
    actor_surface: str,
    actor_conn: str,
    now: datetime | None = None,
    event_limit: int | None = None,
) -> dict:
    """深潜数据（web 深潜/REST 与 MCP get_task_detail、export 单一源）。

    事件选取口径：reconstruct_states 永远用全链 -> as_of 过滤 -> 若 event_limit 非空：
    取最新 N（all_events 已 seq 升序，filtered[-event_limit:]；守卫 event_limit>0，
    防 [-0:] 切片陷阱）-> 再套 kinds/severities 过滤（先 limit 后 filter，结果可 < N）
    -> 输出保持 seq 升序。event_limit=None 全量（export 口径，无 LIMIT）。
    """
    now = now or now_utc()
    req = await require_requirement(session, requirement_id)
    requirement_id = _nid(req.id)
    claim = await session.scalar(
        select(Claim).where(Claim.requirement_id == requirement_id, Claim.ended_at.is_(None))
    )
    subtasks = (await session.scalars(
        select(Subtask).where(Subtask.requirement_id == requirement_id).order_by(Subtask.ordinal)
    )).all()
    milestones = (await session.scalars(
        select(Milestone).where(Milestone.requirement_id == requirement_id).order_by(Milestone.created_at)
    )).all()
    all_events = (await session.scalars(
        select(Event).where(Event.requirement_id == requirement_id).order_by(Event.seq)
    )).all()
    states = reconstruct_states(all_events, as_of=as_of)

    as_of_events: list[Event] = []
    for e in all_events:
        if as_of is not None and e.ts > as_of:
            continue
        as_of_events.append(e)
    if event_limit and event_limit > 0:
        as_of_events = as_of_events[-event_limit:]
    events: list[Event] = []
    for e in as_of_events:
        if kinds is not None and e.kind not in kinds:
            continue
        if severities is not None and e.severity not in severities:
            continue
        events.append(e)

    return {
        "requirement_id": _nid(req.id),
        "title": req.title,
        "description": req.description,
        "source": req.source,
        "source_ref": req.source_ref,
        "state": req.state,
        "history_note": HISTORY_NOTE if not all_events and req.state != "OPEN" else None,
        "acceptance": req.acceptance,
        "awaiting_human": req.awaiting_human,
        "claim": _claim_view(claim, req.awaiting_human, now),
        "claims": await _claim_timeline(session, requirement_id, now),
        "subtasks": [
            {
                "subtask_id": _nid(s.id), "ordinal": s.ordinal, "title": s.title, "state": s.state,
                "acceptance": s.acceptance, "milestone_id": _nid(s.milestone_id) if s.milestone_id else None,
                "created_at": s.created_at.isoformat(), "updated_at": s.updated_at.isoformat(),
            }
            for s in subtasks
        ],
        "milestones": [
            {
                "milestone_id": _nid(m.id), "title": m.title, "state": m.state,
                "planned_at": m.planned_at.isoformat() if m.planned_at else None,
                "actual_at": m.actual_at.isoformat() if m.actual_at else None,
            }
            for m in milestones
        ],
        "events": [
            {
                "seq": e.seq, "kind": e.kind, "severity": e.severity, "audience": event_audience(e.kind),
                "title": e.title, "content": e.content, "payload": e.payload,
                "actor_surface": e.actor_surface, "actor_conn": e.actor_conn,
                "claim_id": _nid(e.claim_id) if e.claim_id else None, "ts": e.ts.isoformat(),
                "state_at_event": states.get(e.seq),
            }
            for e in events
        ],
    }


# ---------------------------------------------------------------- 渲染
def render_summary_text(summary_dict: dict) -> str:
    L: list[str] = []
    L.append(f"# {summary_dict['title']}  [{summary_dict['state']}]")
    L.append(f"id: {summary_dict['requirement_id']}")
    p = summary_dict["progress"]
    L.append(f"进度: {p['done']}/{p['total']} 完成（blocked={p['blocked']} 进行中、abandoned={p['abandoned']} 不计分母）")
    c = summary_dict["claim"]
    if c:
        L.append(f"认领: {c['agent_name']} conn={c['agent_conn']} signal={c['signal']} 到期={c['lease_expires_at']}")
    ah = summary_dict["awaiting_human"]
    if ah:
        L.append(f"等待人: kind={ah.get('kind')} reason={ah.get('reason')} since={ah.get('since')}")
    L.append("")
    L.append("## 里程碑")
    for m in summary_dict["milestones"]:
        delay = f" [延误:{m['delay']}]" if m["delay"] else ""
        L.append(f"- {m['title']} ({m['state']}){delay}")
    L.append("")
    L.append("## 验收对照")
    for a in summary_dict["acceptance_table"]:
        if a["uncovered"]:
            L.append(f"- [覆盖缺口] {a['item']} ({a['anchor_id']})")
        else:
            linked = ", ".join(f"{x['item']}({x['state']})@{x['subtask_title']}" for x in a["linked"])
            L.append(f"- {a['item']} ({a['anchor_id']}) -> {linked}")
    L.append("")
    L.append("## 子任务")
    for s in summary_dict["subtasks"]:
        L.append(f"- ({s['ordinal']}) {s['title']} [{s['state']}]")
    if summary_dict["decisions"]:
        L.append("")
        L.append("## 决策")
        for d in summary_dict["decisions"]:
            L.append(f"- {d['title']} -> {d['choice']} (备选 {len(d['alternatives'])})")
    if summary_dict["risks"]:
        L.append("")
        L.append("## 风险")
        for r in summary_dict["risks"]:
            L.append(f"- [{r['severity']}] {r['title']}")
    if summary_dict["deviations"]:
        L.append("")
        L.append("## 偏离")
        for v in summary_dict["deviations"]:
            L.append(f"- [{v['severity']}] {v['title']}")
    L.append("")
    L.append("## 需要关注")
    if summary_dict["needs_attention"]:
        for n in summary_dict["needs_attention"]:
            L.append(f"- {n['type']}: {n.get('title', '')}")
    else:
        L.append("- 无")
    return "\n".join(L)


def render_detail_text(detail_dict: dict) -> str:
    L: list[str] = []
    L.append(f"# {detail_dict['title']}  [{detail_dict['state']}]")
    L.append(f"id: {detail_dict['requirement_id']}")
    if detail_dict.get("history_note"):
        L.append(f"历史注记: {detail_dict['history_note']}")
    L.append("")
    L.append("## 子任务")
    for s in detail_dict["subtasks"]:
        L.append(f"- ({s['ordinal']}) {s['title']} [{s['state']}]")
    L.append("")
    L.append("## 里程碑")
    for m in detail_dict["milestones"]:
        L.append(f"- {m['title']} ({m['state']}) planned={m['planned_at']} actual={m['actual_at']}")
    L.append("")
    L.append("## 事件流")
    for e in detail_dict["events"]:
        L.append(f"- #{e['seq']} [{e['state_at_event']}] {e['ts']} {e['kind']}/{e['severity']} by {e['actor_surface']}:{e['actor_conn']} {e['title']}")
        if e.get("content"):
            L.append(f"  content: {e['content']}")
        if e.get("payload"):
            L.append(f"  payload: {json.dumps(e['payload'], ensure_ascii=False)}")
    return "\n".join(L)


def render_summary_html(summary_dict: dict) -> str:
    """极简静态 HTML（PRD 8：M0 不做 Web 窗口，仅反淹没结构渲染）。"""
    e = html.escape
    L: list[str] = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'><title>",
        e(str(summary_dict["title"])),
        "</title></head><body>",
        f"<h1>{e(str(summary_dict['title']))} <span>[{e(str(summary_dict['state']))}]</span></h1>",
        f"<p>id: {e(str(summary_dict['requirement_id']))}</p>",
    ]
    p = summary_dict["progress"]
    L.append(f"<p>进度: {p['done']}/{p['total']} 完成</p>")
    c = summary_dict["claim"]
    if c:
        L.append(f"<p>认领: {e(str(c['agent_name']))} signal={e(str(c['signal']))}</p>")
    ah = summary_dict["awaiting_human"]
    if ah:
        L.append(f"<p>等待人: {e(str(ah.get('kind')))} {e(str(ah.get('reason')))}</p>")
    L.append("<h2>里程碑</h2><ul>")
    for m in summary_dict["milestones"]:
        delay = f" [延误:{e(str(m['delay']))}]" if m["delay"] else ""
        L.append(f"<li>{e(str(m['title']))} ({e(str(m['state']))}){delay}</li>")
    L.append("</ul><h2>验收对照</h2><ul>")
    for a in summary_dict["acceptance_table"]:
        if a["uncovered"]:
            L.append(f"<li><strong>[覆盖缺口]</strong> {e(str(a['item']))}</li>")
        else:
            linked = ", ".join(f"{e(str(x['item']))}({e(str(x['state']))})" for x in a["linked"])
            L.append(f"<li>{e(str(a['item']))} -&gt; {linked}</li>")
    L.append("</ul><h2>子任务</h2><ul>")
    for s in summary_dict["subtasks"]:
        L.append(f"<li>{e(str(s['title']))} [{e(str(s['state']))}]</li>")
    L.append("</ul><h2>需要关注</h2><ul>")
    if summary_dict["needs_attention"]:
        for n in summary_dict["needs_attention"]:
            L.append(f"<li>{e(str(n['type']))}: {e(str(n.get('title', '')))}</li>")
    else:
        L.append("<li>无</li>")
    L.append("</ul></body></html>")
    return "\n".join(L)


def render_export_markdown(data: dict) -> str:
    """导出 Markdown（PRD 4.2/5.4：完整含 events 全文）。"""
    if "requirement" in data:
        items = [data["requirement"]]
    else:
        items = data.get("requirements") or []
    parts: list[str] = []
    for r in items:
        parts.append(f"# {r['title']}  [{r['state']}]")
        parts.append(f"- id: {r['requirement_id']}")
        parts.append(f"- source: {r['source']} {r.get('source_ref') or ''}")
        parts.append(f"- description: {r.get('description') or ''}")
        parts.append("")
        parts.append("## acceptance")
        for a in (r.get("acceptance") or []):
            parts.append(f"- [{a.get('id')}] {a.get('item')}")
        parts.append("")
        parts.append("## subtasks")
        for s in (r.get("subtasks") or []):
            parts.append(f"- ({s['ordinal']}) {s['title']} [{s['state']}]")
        parts.append("")
        parts.append("## milestones")
        for m in (r.get("milestones") or []):
            parts.append(f"- {m['title']} [{m['state']}] planned={m.get('planned_at')} actual={m.get('actual_at')}")
        parts.append("")
        parts.append("## claim")
        c = r.get("claim")
        if c:
            parts.append(f"- agent: {c['agent_name']} conn={c.get('agent_conn')} started={c['started_at']} "
                         f"ended={c.get('ended_at')} reason={c.get('release_reason')}")
        parts.append("")
        parts.append("## events")
        for e in (r.get("events") or []):
            line = f"- #{e['seq']} {e['ts']} {e['kind']}/{e['severity']} by {e['actor_surface']}:{e['actor_conn']} {e['title']}"
            parts.append(line)
            if e.get("content"):
                parts.append(f"  content: {e['content']}")
            if e.get("payload"):
                parts.append(f"  payload: {json.dumps(e['payload'], ensure_ascii=False)}")
        parts.append("")
    return "\n".join(parts)


CSV_RECORD_FIELDS: dict[str, list[str]] = {
    "requirement": ["requirement_id", "title", "description", "source", "source_ref", "state",
                    "acceptance", "awaiting_human", "claim", "claims"],
    "subtask": ["subtask_id", "ordinal", "title", "state", "acceptance", "milestone_id",
                "created_at", "updated_at"],
    "milestone": ["milestone_id", "title", "state", "planned_at", "actual_at"],
    "event": ["seq", "kind", "severity", "title", "content", "payload", "actor_surface",
              "actor_conn", "claim_id", "ts"],
}


def _csv_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def render_export_csv(data: dict) -> str:
    """导出 CSV：单张宽表，每条记录一行，列 = record_type + JSON 导出字段名并集；
    嵌套结构（acceptance/claim/claims/awaiting_human/payload）JSON 序列化进同名单列。"""
    items = [data["requirement"]] if "requirement" in data else (data.get("requirements") or [])
    header = ["record_type"]
    for fields in CSV_RECORD_FIELDS.values():
        for f in fields:
            if f not in header:
                header.append(f)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    for r in items:
        rows: list[tuple[str, dict]] = [("requirement", r)]
        rows += [("subtask", s) for s in (r.get("subtasks") or [])]
        rows += [("milestone", m) for m in (r.get("milestones") or [])]
        rows += [("event", e) for e in (r.get("events") or [])]
        for rtype, rec in rows:
            vals = {f: _csv_value(rec.get(f)) for f in CSV_RECORD_FIELDS[rtype]}
            writer.writerow([rtype] + [vals.get(f, "") for f in header[1:]])
    return buf.getvalue()
