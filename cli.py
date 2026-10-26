"""agent-kanban CLI（人面，PRD 4.2）。子命令：mcp / new / set_expectations / approve /
release / renew / note / abandon / reopen / export / view。agent 面工具仅经 MCP 暴露，
CLI 不提供（PRD 4.1）。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from agent_kanban.db import get_session_factory, now_utc, run_op
from agent_kanban.errors import BusinessError
from agent_kanban.services import operations as ops
from agent_kanban.services import reconcile, view
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
        source=args.source, source_ref=args.source_ref,
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


def _cmd_archive(args: argparse.Namespace) -> int:
    return _invoke("archive_requirement", requirement_id=args.requirement_id)


def _cmd_delete(args: argparse.Namespace) -> int:
    """整需求硬删（spec 4.3）：读 preview（title/state/事件数）-> 确认门（stdin y/N，
    EOF/拒绝/非 y 中止不删、非零退出，确认期间不持写事务；--yes 跳过）->
    delete_requirement 单事务原子删除（不写事件）。"""
    surface, conn = cli_actor()
    try:
        info = asyncio.run(run_op(
            get_session_factory(), ops.delete_preview, is_write=False,
            requirement_id=args.requirement_id, actor_surface=surface, actor_conn=conn,
        ))
        if not args.yes:
            sys.stdout.write(
                f"将硬删整个需求: {info['title']}（state={info['state']}，{info['event_count']} 条事件）。"
                f"删除不可逆，建议先 `kanban export` 留档。继续？[y/N] "
            )
            sys.stdout.flush()
            if sys.stdin.readline().strip().lower() != "y":
                print("aborted: nothing deleted", file=sys.stderr)
                return 1
        result = asyncio.run(run_op(
            get_session_factory(), ops.delete_requirement, is_write=True,
            requirement_id=args.requirement_id, actor_surface=surface, actor_conn=conn,
        ))
    except BusinessError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_reopen(args: argparse.Namespace) -> int:
    return _invoke("reopen", requirement_id=args.requirement_id, continue_=args.continue_)


def _cmd_export(args: argparse.Namespace) -> int:
    if args.format in ("markdown", "csv"):
        surface, conn = cli_actor()
        try:
            result = asyncio.run(
                run_op(
                    get_session_factory(), ops.export_data, is_write=False,
                    requirement_id=args.requirement_id, fmt=args.format,
                    actor_surface=surface, actor_conn=conn,
                )
            )
        except BusinessError as exc:
            print(f"{exc.code}: {exc.message}", file=sys.stderr)
            return 1
        if args.format == "csv":
            # render 产物自带末行换行，print 会多追加一个导致末尾空行
            sys.stdout.write(result)
        else:
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


def _months_ago(now: datetime, n: int) -> datetime:
    """now 减 n 自然月（审#P2-B/G）：月末日回绕 clamp 到目标月最后一天（3-31 减 1 月 ->
    2-28/29），纯算术无新依赖；tzinfo 随输入保留（CLI 用 now_utc()，harness 注入 fake now）。"""
    month_index = now.year * 12 + (now.month - 1) - n
    year, month_1based = divmod(month_index, 12)
    month = month_1based + 1
    next_first = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    last_day = (next_first - timedelta(days=1)).day
    return datetime(year, month, min(now.day, last_day), now.hour, now.minute, now.second,
                    now.microsecond, tzinfo=now.tzinfo)


def _cmd_prune(args: argparse.Namespace) -> int:
    """数据保留清理（PRD §6 + G9-a，审#P1-2/P1-A/P2-6）：强制导出（0600，导出失败中止）
    -> COUNT 将删（读，与 DELETE 共享谓词）-> 确认门（stdin y/N，EOF/拒绝/非 y abort 不删
    非零退出，确认期间不持写事务）-> prune_events 单事务删除。"""
    surface, conn = cli_actor()
    now = now_utc()
    if args.months < 1:
        print("--months must be >= 1", file=sys.stderr)
        return 1
    try:
        cutoff = _months_ago(now, args.months)
    except ValueError as exc:  # 极端月数溢出日历范围（审#P2-2）
        print(f"invalid --months: {exc}", file=sys.stderr)
        return 1
    export_path = Path(args.export_path) if args.export_path else \
        Path("exports") / f"kanban-export-{now.strftime('%Y%m%dT%H%M%S%f')}.json"
    try:
        # 1. 全量导出（读，无 LIMIT；G8 P2-4 全量语义）
        data = asyncio.run(run_op(
            get_session_factory(), ops.export_data, is_write=False,
            fmt="json", actor_surface=surface, actor_conn=conn,
        ))
        # 2. 写文件 0600（mkdir）；导出失败中止（清理前必须导出）
        try:
            export_path.parent.mkdir(parents=True, exist_ok=True)
            with export_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.chmod(export_path, 0o600)
        except OSError as exc:
            print(f"export write failed: {exc}", file=sys.stderr)
            return 1
        # 3. COUNT 将删（读）
        count = asyncio.run(run_op(
            get_session_factory(), ops.count_prunable_events, is_write=False, cutoff=cutoff,
        ))
        # 4. 确认门（不持写事务）
        if not args.yes:
            sys.stdout.write(
                f"将删除 {count} 条事件（终态需求级原子窗口：仅 DONE/REJECTED/CANCELLED "
                f"且全部事件早于 {cutoff.isoformat()} 的需求整删）。继续？[y/N] "
            )
            sys.stdout.flush()
            if sys.stdin.readline().strip().lower() != "y":
                print("aborted: nothing deleted", file=sys.stderr)
                return 1
        # 5. 单事务删除（写）
        deleted = asyncio.run(run_op(
            get_session_factory(), ops.prune_events, is_write=True, cutoff=cutoff,
        ))
    except BusinessError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1
    print(json.dumps(
        {"export_path": str(export_path), "counted": count, "deleted": deleted},
        ensure_ascii=False, indent=2,
    ))
    return 0


def _cmd_reconcile(args: argparse.Namespace) -> int:
    """对账（PRD 3.2 服务重启对账 / §6 可靠性）：只标记不删除；事件 actor=system。"""
    try:
        result = asyncio.run(
            run_op(get_session_factory(), reconcile.reconcile, is_write=False)
        )
    except BusinessError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-kanban",
        description="AI 时代看板：黑箱关键节点暴露窗口 + 可回溯审计资产",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

    p = sub.add_parser("mcp", help="运行 MCP stdio server（agent 面，12 工具）")
    p.set_defaults(handler=_cmd_mcp)

    p = sub.add_parser("new", help="创建需求（手工登记；jira 以链接引用）")
    p.add_argument("--title", required=True)
    p.add_argument("--description")
    p.add_argument("--source", help="来源：manual（默认）| jira")
    p.add_argument("--source-ref", help="外部引用（jira 时为链接）")
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

    p = sub.add_parser("archive", help="归档（任一状态 -> ARCHIVED 终态；同事务结束未结束认领）")
    p.add_argument("--requirement-id", required=True)
    p.set_defaults(handler=_cmd_archive)

    p = sub.add_parser("delete", help="整需求硬删（全部子行原子删除、不写事件；--yes 跳过确认门）")
    p.add_argument("--requirement-id", required=True)
    p.add_argument("--yes", action="store_true", help="跳过确认门（非交互场景）")
    p.set_defaults(handler=_cmd_delete)

    p = sub.add_parser("reopen", help="DONE->REOPEN；--continue REOPEN->OPEN（回到可认领）")
    p.add_argument("--requirement-id", required=True)
    p.add_argument("--continue", dest="continue_", action="store_true")
    p.set_defaults(handler=_cmd_reopen)

    p = sub.add_parser("export", help="全量导出（JSON/Markdown/CSV，无 LIMIT）")
    p.add_argument("--requirement-id")
    p.add_argument("--format", choices=["json", "markdown", "csv"], default="json")
    p.set_defaults(handler=_cmd_export)

    p = sub.add_parser("view", help="视图：summary（摘要）/ detail（深潜）")
    p.add_argument("mode", choices=["summary", "detail"])
    p.add_argument("--requirement-id", required=True)
    p.set_defaults(handler=_cmd_view)

    p = sub.add_parser("reconcile", help="对账：扫描未结束认领 + claim-state drift（只标记不删除）")
    p.set_defaults(handler=_cmd_reconcile)

    p = sub.add_parser("prune", help="数据保留清理（§6）：强制导出 -> 确认门 -> 终态需求级原子窗口删除 events")
    p.add_argument("--months", type=int, default=12, help="保留月数（默认 12，日历月 + 月末 clamp）")
    p.add_argument("--export-path", help="导出文件路径（默认 ./exports/kanban-export-<ts>.json）")
    p.add_argument("--yes", action="store_true", help="跳过确认门")
    p.set_defaults(handler=_cmd_prune)

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
