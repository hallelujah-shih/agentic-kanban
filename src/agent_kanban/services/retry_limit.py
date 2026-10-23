"""G9-b 重试成本超限判定（BCD docs/business-contracts/g9b-retry-limit.md）。

计数来源 = events 链（单一事件源，BCD §3 Policy 5 / §7 强不变量 2）；判定只在
update_subtask 使子任务重入 in_progress 时评估（Policy 1）；幂等/信号谓词同一
（审#P1-1/P3-4）：单一匹配器供 _maybe_write_retry_limit 与 view._derived_signals 两处共用。
"""

from __future__ import annotations

from ..models import Event

# 阈值钉死常量（BCD §3 Policy 7：累计重试 > 2 即第 3 次重入 in_progress 触发；不配置化）
RETRY_LIMIT_THRESHOLD = 3
RETRY_LIMIT_TITLE = "累计重试超 2 次，需要人决策"
# marker 归属（对齐 reconcile 先例 RECONCILE_SURFACE/RECONCILE_CONN，risks 列表可区分系统判定 vs agent 自报）
RETRY_LIMIT_SURFACE = "system"
RETRY_LIMIT_CONN = "system"


def is_retry_limit_event(e: Event) -> bool:
    """幂等/信号谓词同一（审#P1-1/P3-4）：kind=risk AND severity>=attention AND
    payload.retry_limit==true AND actor_surface==system。agent 伪造（actor_surface=mcp）
    不抑制告警、不进信号（威胁模型 B：agent 内容不可信）。"""
    if e.kind != "risk":
        return False
    if e.severity not in ("attention", "critical"):
        return False
    if not (e.payload or {}).get("retry_limit"):
        return False
    return e.actor_surface == RETRY_LIMIT_SURFACE


def count_retries(events: list[Event]) -> int:
    """需求级跨子任务累计重试数（BCD §3 Policy 3，审#P1-3）：只计 subtask 作用域
    state_change（payload.subtask_id 非空 + payload.milestone_id 空 + to==in_progress +
    from!=in_progress）；per-subtask n 次重入 -> max(0, n-1)（首入除外），sum 跨子任务。
    done 重开 / todo 退回再进 / blocked 再开工均计（user 裁决：任何非 in_progress 重入都计）。"""
    per: dict[str, int] = {}
    for e in events:
        if e.kind != "state_change":
            continue
        p = e.payload or {}
        if not p.get("subtask_id") or p.get("milestone_id"):
            continue
        if p.get("to") == "in_progress" and p.get("from") != "in_progress":
            per[str(p["subtask_id"])] = per.get(str(p["subtask_id"]), 0) + 1
    return sum(max(0, n - 1) for n in per.values())
