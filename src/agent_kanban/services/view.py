"""视图服务（PRD 5.3/5.4）：摘要 dict + 深潜 dict + 文本/HTML 渲染 + 导出 Markdown。

口径钉死：
- 里程碑延误：planned_at 未达成且超期（overdue）/ achieved 且 actual_at>planned_at（late）。
- 决策/风险/偏离：deviation 无条件；risk severity>=attention；decision 全展示（结构化字段，无 content）。
- 验收对照表（下界语义）：per 锚 -> 链接子任务验收项文本+状态；无链接 -> uncovered。
- 进度派生值：done/total；blocked=进行中（计分母不计 done）；abandoned 不计分母。
- 拆解新增：进入 CLAIMED 后有 add_subtask（decomposition）且该 CLAIMED 期间无 decision/deviation 解释。
- 未解释放弃：abandoned 子任务无同 subtask_id 的 deviation/note 事件（payload.subtask_id 关联）。
- 深潜状态重建：按 seq 回放 state_change 链到目标 ts。
- AC13 禁止面：摘要不含 progress_note content 全文/事件长 content/run_logs。
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import now_utc
from ..models import Claim, Event, Milestone, Requirement, Subtask
from . import lease as lease_svc
from .write_guard import require_requirement


def _nid(value: Any) -> str:
    """id 归一为 32-hex 无连字符（与 create 响应/DB 存储一致；Uuid(as_uuid=False)
    读回 36-char 带连字符，API 面归一避免与 payload 引用（32-hex）失配）。"""
    return str(value).replace("-", "")


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

    milestone_rows = []
    for m in milestones:
        delay = None
        if m.state != "achieved" and m.planned_at is not None and now > m.planned_at:
            delay = "overdue"
        elif m.state == "achieved" and m.actual_at is not None and m.planned_at is not None and m.actual_at > m.planned_at:
            delay = "late"
        milestone_rows.append({
            "milestone_id": _nid(m.id), "title": m.title, "state": m.state,
            "planned_at": m.planned_at.isoformat() if m.planned_at else None,
            "actual_at": m.actual_at.isoformat() if m.actual_at else None,
            "delay": delay,
        })

    decisions: list[dict] = []
    risks: list[dict] = []
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
        elif e.kind == "risk" and e.severity in ("attention", "critical"):
            risks.append({
                "seq": e.seq, "ts": e.ts.isoformat(), "title": e.title,
                "severity": e.severity, "actor_conn": e.actor_conn,
            })
        elif e.kind == "deviation":
            deviations.append({
                "seq": e.seq, "ts": e.ts.isoformat(), "title": e.title,
                "severity": e.severity, "payload": e.payload,
                "actor_conn": e.actor_conn,
            })

    # 验收对照表（下界语义：只保证未链接锚项必然显示缺口）
    anchors = list(req.acceptance or [])
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

    # 进度派生值：done/total；blocked=进行中；abandoned 不计分母
    states = [s.state for s in subtasks]
    total = sum(1 for s in states if s != "abandoned")
    done = sum(1 for s in states if s == "done")
    progress = {
        "done": done,
        "total": total,
        "remaining": total - done,
        "blocked": sum(1 for s in states if s == "blocked"),
        "abandoned": sum(1 for s in states if s == "abandoned"),
    }

    needs_attention = _derived_signals(subtasks, milestones, events, milestone_rows)

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
) -> list[dict]:
    """派生偏离信号（系统推导，不依赖 agent 自愿登记，PRD 5.3）。"""
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
    return out


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
                if e.kind == "decomposition":
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
) -> dict:
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
    all_events = (await session.scalars(
        select(Event).where(Event.requirement_id == requirement_id).order_by(Event.seq)
    )).all()
    states = reconstruct_states(all_events, as_of=as_of)

    events: list[Event] = []
    for e in all_events:
        if as_of is not None and e.ts > as_of:
            continue
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
        "acceptance": req.acceptance,
        "awaiting_human": req.awaiting_human,
        "claim": _claim_view(claim, req.awaiting_human, now),
        "claims": _claim_timeline(session, requirement_id, now),
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
                "seq": e.seq, "kind": e.kind, "severity": e.severity, "title": e.title,
                "content": e.content, "payload": e.payload,
                "actor_surface": e.actor_surface, "actor_conn": e.actor_conn,
                "claim_id": e.claim_id, "ts": e.ts.isoformat(),
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
