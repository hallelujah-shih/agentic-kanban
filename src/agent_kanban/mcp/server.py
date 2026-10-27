"""MCP server（PRD 4.1）：12 工具；错误返回 is_error + {code,message,task_id}（PRD 4.3）。
actor 经 Context 派生（identity.mcp_actor），不接受调用方传入（ADR 0002/P1-1）。
build_server() 为 12 工具注册单点，stdio（cli.py mcp）与 HTTP（api /mcp）共用（审#P2-4）。"""

from __future__ import annotations

import json
import uuid
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context
from mcp_types import CallToolResult, TextContent

from ..db import get_session_factory, run_op
from ..errors import BusinessError
from ..services import operations as ops
from ..services.identity import mcp_actor

# stdio 进程级 conn id（HTTP 不用，HTTP 用服务端铸币 session id）
CONN_ID = f"conn-{uuid.uuid4().hex[:8]}"


def _error(exc: BusinessError) -> CallToolResult:
    return CallToolResult(
        isError=True, content=[TextContent(type="text", text=json.dumps(exc.as_dict()))]
    )


def _ok(data: dict) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data))])


async def _call(
    ctx: Context | None, op_name: str, *, is_write: bool = True, **kwargs: Any
) -> CallToolResult:
    try:
        surface, conn = mcp_actor(ctx, CONN_ID)
    except BusinessError as exc:
        return _error(exc)
    try:
        result = await run_op(
            get_session_factory(), getattr(ops, op_name), is_write=is_write,
            actor_surface=surface, actor_conn=conn, **kwargs,
        )
    except BusinessError as exc:
        return _error(exc)
    return _ok(result)


async def list_tasks(status: str | None = None, ctx: Context | None = None) -> CallToolResult:
    """列出看板未完成任务（OPEN/CLAIMED/BLOCKED/REOPEN），返回 title/state/awaiting_human/claim。
    参数: status=按状态过滤（可选）。
    等待面只认 awaiting_human（需要人的任务）。
    """
    return await _call(ctx, "list_tasks", is_write=False, status=status)


async def get_task_detail(requirement_id: str, ctx: Context | None = None) -> CallToolResult:
    """读取单需求深潜数据：子任务/里程碑/事件链（最新 200 条，输出 seq 升序）/验收对照。
    参数: requirement_id（32 位全 id 或 8~31 位唯一前缀，空白/大小写/连字符不敏感）。
    错误: not_found（需求不存在）/ ambiguous_id（前缀命中多条，错误信息含候选，加长前缀重试）。
    """
    return await _call(ctx, "get_task_detail", is_write=False, requirement_id=requirement_id)


async def claim_task(requirement_id: str, agent_name: str, ctx: Context | None = None) -> CallToolResult:
    """认领一个 OPEN 需求（状态 -> CLAIMED）；同一 agent 最多并发持有 16 个。
    参数: requirement_id（32 位全 id 或 8~31 位唯一前缀，空白/大小写/连字符不敏感）, agent_name。
    错误: no_active_claim（已被认领）/ illegal_state（非 OPEN）/ queue_full（超 16）/ ambiguous_id（前缀命中多条，错误信息含候选，加长前缀重试）。
    """
    return await _call(ctx, "claim_task", requirement_id=requirement_id, agent_name=agent_name)


async def add_subtask(
    requirement_id: str, title: str, ordinal: int, acceptance: Any = None,
    ctx: Context | None = None,
) -> CallToolResult:
    """拆解子任务（写 decomposition 事件）。
    参数: requirement_id（32 位全 id 或 8~31 位唯一前缀，空白/大小写/连字符不敏感）, title, ordinal, acceptance（可选，验收项列表）。
    错误: no_active_claim / duplicate_subtask（title 重复）/ ambiguous_id（前缀命中多条，错误信息含候选，加长前缀重试）。
    """
    return await _call(
        ctx, "add_subtask", requirement_id=requirement_id, title=title, ordinal=ordinal,
        acceptance=acceptance,
    )


async def update_subtask(
    requirement_id: str, subtask_id: str, state: str, ctx: Context | None = None
) -> CallToolResult:
    """更新子任务状态（todo/in_progress/done/blocked/abandoned）。
    参数: requirement_id（32 位全 id 或 8~31 位唯一前缀，空白/大小写/连字符不敏感）, subtask_id, state。
    错误: no_active_claim / not_found / ambiguous_id（前缀命中多条，错误信息含候选，加长前缀重试）/ invalid_record（非法 state）。
    """
    return await _call(
        ctx, "update_subtask", requirement_id=requirement_id, subtask_id=subtask_id, state=state
    )


async def add_milestone(
    requirement_id: str, title: str, planned_at: Any = None, ctx: Context | None = None
) -> CallToolResult:
    """新增里程碑（写 decomposition 事件）。
    参数: requirement_id（32 位全 id 或 8~31 位唯一前缀，空白/大小写/连字符不敏感）, title, planned_at（可选，ISO-8601）。
    错误: no_active_claim / invalid_record / ambiguous_id（前缀命中多条，错误信息含候选，加长前缀重试）。
    """
    return await _call(
        ctx, "add_milestone", requirement_id=requirement_id, title=title, planned_at=planned_at
    )


async def update_milestone(
    requirement_id: str, milestone_id: str, state: str, actual_at: Any = None,
    ctx: Context | None = None,
) -> CallToolResult:
    """更新里程碑状态（planned/in_progress/achieved）。
    参数: requirement_id（32 位全 id 或 8~31 位唯一前缀，空白/大小写/连字符不敏感）, milestone_id, state, actual_at（可选）。
    错误: no_active_claim / not_found / ambiguous_id（前缀命中多条，错误信息含候选，加长前缀重试）/ invalid_record。
    """
    return await _call(
        ctx, "update_milestone", requirement_id=requirement_id, milestone_id=milestone_id,
        state=state, actual_at=actual_at,
    )


async def add_record(
    requirement_id: str, kind: str, title: str, content: str | None = None,
    severity: str | None = None, payload: Any = None, ctx: Context | None = None,
) -> CallToolResult:
    """记录一条人面事件（decision/risk/deviation/note/decomposition）。
    参数: requirement_id（32 位全 id 或 8~31 位唯一前缀，空白/大小写/连字符不敏感）, kind, title（一行人话提纲）, content, severity, payload。
    错误: no_active_claim / invalid_record（kind 非法或 title 为空）/ ambiguous_id（前缀命中多条，错误信息含候选，加长前缀重试）。
    记录契约: title 必写一行人话提纲（报节点不报流水账），缺/空 -> invalid_record。
    """
    return await _call(
        ctx, "add_record", requirement_id=requirement_id, kind=kind, title=title,
        content=content, severity=severity, payload=payload,
    )


async def update_progress(
    requirement_id: str, note: str, headline: str | None = None, ctx: Context | None = None
) -> CallToolResult:
    """记一条进度备注（progress_note 事件）。
    参数: requirement_id（32 位全 id 或 8~31 位唯一前缀，空白/大小写/连字符不敏感）, note, headline（一行人话提纲）。
    错误: no_active_claim / invalid_record（缺 headline）/ ambiguous_id（前缀命中多条，错误信息含候选，加长前缀重试）。
    记录契约: headline 必写一行人话提纲（报节点不报流水账），缺/空 -> invalid_record。
    返回: requirement_id（32 位全 id）+ lease_expires_at（租约到期时间；本操作不延长租约，续租用 renew）。
    """
    return await _call(
        ctx, "update_progress", requirement_id=requirement_id, note=note, headline=headline
    )


async def request_review(
    requirement_id: str, evidence: Any = None, assessments: Any = None,
    summary_line: str | None = None, ctx: Context | None = None,
) -> CallToolResult:
    """交接评审：置 awaiting_human(kind=review)，写 review_request 事件（severity=attention）。
    参数: requirement_id（32 位全 id 或 8~31 位唯一前缀，空白/大小写/连字符不敏感）, evidence（pr_url/commit_range/test_summary 至少一项）,
          assessments, summary_line（交接一句话：做了什么/先看哪）。
    错误: illegal_state（非 CLAIMED）/ invalid_record（缺 evidence 或 summary_line）/ ambiguous_id（前缀命中多条，错误信息含候选，加长前缀重试）。
    记录契约: summary_line 必写「做了什么/先看哪」一句话，缺/空 -> invalid_record。
    """
    return await _call(
        ctx, "request_review", requirement_id=requirement_id, evidence=evidence,
        assessments=assessments, summary_line=summary_line,
    )


async def mark_blocked(
    requirement_id: str, reason: str, evidence: str | None = None,
    ctx: Context | None = None,
) -> CallToolResult:
    """标记阻塞：CLAIMED -> BLOCKED；reason 进追加链（state_change 事件）+ awaiting_human(kind=blocked)。
    参数: requirement_id（32 位全 id 或 8~31 位唯一前缀，空白/大小写/连字符不敏感）, reason（一行人话阻塞原因）, evidence（可选）。
    错误: illegal_state（非 CLAIMED）/ no_active_claim / invalid_record（空 reason）/ ambiguous_id（前缀命中多条，错误信息含候选，加长前缀重试）。
    记录契约: reason 必写一行人话原因（报节点不报流水账），进事件链可回溯。
    """
    return await _call(
        ctx, "mark_blocked", requirement_id=requirement_id, reason=reason, evidence=evidence
    )


async def list_awaiting(ctx: Context | None = None) -> CallToolResult:
    """列出所有 awaiting_human（需要人裁决/评审）的任务——唯一等待面。
    无需参数。
    """
    return await _call(ctx, "list_awaiting", is_write=False)


SERVER_INSTRUCTIONS = (
    "agent-kanban = 记录面，不是控制面。每条人面记录必带一行人话提纲：\n"
    "update_progress.headline / add_record.title / request_review.summary_line / mark_blocked.reason，\n"
    "服务端强制非空，缺/空 -> invalid_record（错误消息带参数名与示例，据此自纠）。\n"
    "交接（request_review）附三行人简报：做了什么 / 先看哪 / 还剩什么，summary_line 承载第一二句。\n"
    "等待面只认 awaiting_human（list_awaiting）。报节点，不报流水账。"
)


def build_server() -> MCPServer:
    """12 工具注册单点（审#P2-4）：stdio 与 HTTP transport 共用，防注册表手工复制漂移。"""
    server = MCPServer(name="agent-kanban", version="0.1.0", instructions=SERVER_INSTRUCTIONS)
    for tool in (
        list_tasks,
        get_task_detail,
        claim_task,
        add_subtask,
        update_subtask,
        add_milestone,
        update_milestone,
        add_record,
        update_progress,
        request_review,
        mark_blocked,
        list_awaiting,
    ):
        server.add_tool(tool)
    return server


def main() -> None:
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
