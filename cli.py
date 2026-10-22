"""agent-kanban CLI（人面，PRD 4.2）。子命令：mcp / new / set_expectations / approve /
release / renew / note / abandon / reopen / export / view。agent 面工具仅经 MCP 暴露，
CLI 不提供（PRD 4.1）。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from agent_kanban.db import get_session_factory, run_op
from agent_kanban.errors import BusinessError
from agent_kanban.services import operations as ops
from agent_kanban.services import view
from agent_kanban.services.identity import cli_actor


def _invoke(op_name: str, *, is_write: bool = True, **kwargs: object) -> int:
    surface, conn = cli_actor()
    try:
        result = asyncio.run(
            run_op(
                get_session_factory(), getattr(ops, op_name), is_write=is_write,
                actor_surface=surface, actor_conn=conn, **kwargs,
            )
        )
    except BusinessError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _load_json(raw: str | None) -> object:
    return json.loads(raw) if raw else None


def _cmd_mcp(args: argparse.Namespace) -> int:
    from agent_kanban.mcp.server import main as mcp_main

    mcp_main()
    return 0


def _cmd_new(args: argparse.Namespace) -> int:
    return _invoke(
        "new_requirement", title=args.title, description=args.description,
        acceptance=_load_json(args.acceptance),
    )


def _cmd_set_expectations(args: argparse.Namespace) -> int:
    return _invoke(
        "set_expectations", requirement_id=args.requirement_id,
        acceptance=_load_json(args.acceptance),
    )


def _cmd_approve(args: argparse.Namespace) -> int:
    return _invoke("approve", requirement_id=args.requirement_id)


def _cmd_release(args: argparse.Namespace) -> int:
    if args.all_stale:
        return _invoke("release_all_stale")
    return _invoke("release", requirement_id=args.requirement_id, reason=args.reason)


def _cmd_renew(args: argparse.Namespace) -> int:
    return _invoke("renew", requirement_id=args.requirement_id)


def _cmd_note(args: argparse.Namespace) -> int:
    return _invoke("note", requirement_id=args.requirement_id, content=args.content)


def _cmd_abandon(args: argparse.Namespace) -> int:
    return _invoke("abandon", requirement_id=args.requirement_id, to_state=args.to_state)


def _cmd_reopen(args: argparse.Namespace) -> int:
    return _invoke("reopen", requirement_id=args.requirement_id, continue_=args.continue_)


def _cmd_export(args: argparse.Namespace) -> int:
    if args.format == "markdown":
        surface, conn = cli_actor()
        try:
            result = asyncio.run(
                run_op(
                    get_session_factory(), ops.export_data, is_write=False,
                    requirement_id=args.requirement_id, fmt="markdown",
                    actor_surface=surface, actor_conn=conn,
                )
            )
        except BusinessError as exc:
            print(f"{exc.code}: {exc.message}", file=sys.stderr)
            return 1
        print(result)
        return 0
    return _invoke("export_data", is_write=False, requirement_id=args.requirement_id, fmt="json")


def _cmd_view(args: argparse.Namespace) -> int:
    surface, conn = cli_actor()
    try:
        if args.mode == "summary":
            result = asyncio.run(
                run_op(
                    get_session_factory(), view.summary, is_write=False,
                    requirement_id=args.requirement_id, actor_surface=surface, actor_conn=conn,
                )
            )
            print(view.render_summary_text(result))
        else:
            result = asyncio.run(
                run_op(
                    get_session_factory(), view.detail, is_write=False,
                    requirement_id=args.requirement_id, actor_surface=surface, actor_conn=conn,
                )
            )
            print(view.render_detail_text(result))
    except BusinessError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-kanban",
        description="AI 时代看板：黑箱关键节点暴露窗口 + 可回溯审计资产",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

    p = sub.add_parser("mcp", help="运行 MCP stdio server（agent 面，12 工具）")
    p.set_defaults(handler=_cmd_mcp)

    p = sub.add_parser("new", help="创建需求（手工导入）")
    p.add_argument("--title", required=True)
    p.add_argument("--description")
    p.add_argument("--acceptance", help="JSON 数组，如 '[{\"item\": \"...\"}]'")
    p.set_defaults(handler=_cmd_new)

    p = sub.add_parser("set_expectations", help="设置/修改 acceptance 预期锚（唯一入口）")
    p.add_argument("--requirement-id", required=True)
    p.add_argument("--acceptance", required=True)
    p.set_defaults(handler=_cmd_set_expectations)

    p = sub.add_parser("approve", help="按当前状态确认（CLAIMED->DONE / BLOCKED->CLAIMED）")
    p.add_argument("--requirement-id", required=True)
    p.set_defaults(handler=_cmd_approve)

    p = sub.add_parser("release", help="释放认领（唯一释放路径，人面）；--all-stale 批量释放 STALE")
    p.add_argument("--requirement-id")
    p.add_argument("--reason")
    p.add_argument("--all-stale", action="store_true")
    p.set_defaults(handler=_cmd_release)

    p = sub.add_parser("renew", help="续租")
    p.add_argument("--requirement-id", required=True)
    p.set_defaults(handler=_cmd_renew)

    p = sub.add_parser("note", help="人追加更正/质疑（note 事件）")
    p.add_argument("--requirement-id", required=True)
    p.add_argument("--content", required=True)
    p.set_defaults(handler=_cmd_note)

    p = sub.add_parser("abandon", help="REJECTED / CANCELLED（同事务处置认领）")
    p.add_argument("--requirement-id", required=True)
    p.add_argument("--to-state", required=True, choices=["REJECTED", "CANCELLED"])
    p.set_defaults(handler=_cmd_abandon)

    p = sub.add_parser("reopen", help="DONE->REOPEN；--continue REOPEN->OPEN（回到可认领）")
    p.add_argument("--requirement-id", required=True)
    p.add_argument("--continue", dest="continue_", action="store_true")
    p.set_defaults(handler=_cmd_reopen)

    p = sub.add_parser("export", help="全量导出（JSON/Markdown，无 LIMIT）")
    p.add_argument("--requirement-id")
    p.add_argument("--format", choices=["json", "markdown"], default="json")
    p.set_defaults(handler=_cmd_export)

    p = sub.add_parser("view", help="视图：summary（摘要）/ detail（深潜）")
    p.add_argument("mode", choices=["summary", "detail"])
    p.add_argument("--requirement-id", required=True)
    p.set_defaults(handler=_cmd_view)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 0
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
