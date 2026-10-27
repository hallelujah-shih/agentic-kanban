#!/usr/bin/env python3
"""e2e 种子（plan T3）：服务启动前直写 DB（无并发）。

用法: .venv/bin/python tests/e2e/seed.py <db_path>

复用 tests/ac_lib（CLI + MCP stdio）。7 种子（预探针触发后备则 8）：
  s1 OPEN+description（对抗内容：<img onerror> + 引号 + 换行，真浏览器 XSS 探针）
  s2 OPEN+acceptance 2 锚 0 子任务（覆盖缺口标红对象）
  s3 claim+mark_blocked+update_progress（事件链=恰好 3：state_change×2+progress_note×1；
     awaiting_human 与 E5/E3c 双对象）
  s4 claim（CLAIMED；archive 对象）  s5 OPEN（delete 对象）
  s6 claim（CLAIMED；status 过滤对象）  s7 claim+approve（DONE；已完成 tab 对象）
预探针：seed 首跑后核 s3 awaiting_human 仍非空（update_progress 预期不清 marker，
代码裁决 state_machine.py 转移处唯一清点位）；若被清 -> 后备种子 s8（仅 claim+
mark_blocked，E5 改用 s8）。两路径写死。
产物：<db>.seeds.json 清单（spec 读 id/title/预探针结论）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # tests/

import ac_lib  # noqa: E402

S1_DESC = (
    'line1 <img src=x onerror=alert(1)> "double" \'single\'\n'
    'line2 换行保留'
)
S2_ANCHORS = [{"item": "e2e 锚A"}, {"item": "e2e 锚B"}]
S3_REASON = "e2e 阻塞原因"
S3_NOTE = "e2e 进度注记"
S3_HEADLINE = "e2e 进度提纲"
AGENT = "e2e-agent"

TITLES = {
    "s1": "e2e-s1-open-xss-desc",
    "s2": "e2e-s2-open-acc-gap",
    "s3": "e2e-s3-blocked-progress",
    "s4": "e2e-s4-claimed-archive",
    "s5": "e2e-s5-open-delete",
    "s6": "e2e-s6-claimed-filter",
    "s7": "e2e-s7-claimed-done",
    "s8": "e2e-s8-blocked-fallback",
}


def _claim(mcp: ac_lib.MCP, rid: str) -> None:
    mcp.call_ok("claim_task", {"requirement_id": rid, "agent_name": AGENT})


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: seed.py <db_path>", file=sys.stderr)
        return 2
    db = Path(sys.argv[1])

    ids: dict[str, str | None] = {}
    # s1-s7 按序创建（created_at 序 = 看板列内行序，确定性前提）
    ids["s1"] = ac_lib.cli_ok(db, "new", "--title", TITLES["s1"],
                              "--description", S1_DESC)["requirement_id"]
    ids["s2"] = ac_lib.cli_ok(db, "new", "--title", TITLES["s2"],
                              "--acceptance", json.dumps(S2_ANCHORS, ensure_ascii=False))["requirement_id"]
    ids["s3"] = ac_lib.seed_req(db, TITLES["s3"])
    ids["s4"] = ac_lib.seed_req(db, TITLES["s4"])
    ids["s5"] = ac_lib.seed_req(db, TITLES["s5"])
    ids["s6"] = ac_lib.seed_req(db, TITLES["s6"])
    ids["s7"] = ac_lib.seed_req(db, TITLES["s7"])
    for k, v in ids.items():
        print(f"seed {k} = {v}  {TITLES[k]}", flush=True)

    # MCP 动作（单实例串行）
    mcp = ac_lib.MCP(db).start()
    try:
        _claim(mcp, ids["s3"])
        mcp.call_ok("mark_blocked", {"requirement_id": ids["s3"], "reason": S3_REASON})
        mcp.call_ok("update_progress", {"requirement_id": ids["s3"], "note": S3_NOTE,
                                         "headline": S3_HEADLINE})
        _claim(mcp, ids["s4"])
        _claim(mcp, ids["s6"])
        _claim(mcp, ids["s7"])
    finally:
        mcp.close()
    print("mcp: s3 claim+blocked+progress / s4 claim / s6 claim / s7 claim", flush=True)
    ac_lib.cli_ok(db, "approve", "--requirement-id", ids["s7"])
    print("cli: s7 approve -> DONE", flush=True)

    # 预探针：s3 awaiting_human 仍非空？（update_progress 预期不清 marker）
    rows = ac_lib.query(db, "SELECT awaiting_human FROM requirements WHERE id=?", (ids["s3"],))
    s3_marker = rows[0][0] if rows else None
    if s3_marker:
        ids["s8"] = None
        e5_target = "s3"
        print("pre-probe: s3 awaiting_human 非空（预期内，update_progress 不清 marker）", flush=True)
    else:
        # 后备路径：s8 = 仅 claim+mark_blocked，E5 改用 s8（两路径写死）
        ids["s8"] = ac_lib.seed_req(db, TITLES["s8"])
        mcp = ac_lib.MCP(db).start()
        try:
            _claim(mcp, ids["s8"])
            mcp.call_ok("mark_blocked", {"requirement_id": ids["s8"], "reason": S3_REASON})
        finally:
            mcp.close()
        e5_target = "s8"
        print(f"pre-probe: s3 marker 被清（非预期）-> 启用后备 s8 = {ids['s8']}", flush=True)

    s3_kinds = [r[0] for r in ac_lib.query(
        db, "SELECT kind FROM events WHERE requirement_id=? ORDER BY seq", (ids["s3"],))]
    manifest = {
        **{k: v for k, v in ids.items() if k != "s8"},
        "s8": ids["s8"],
        "titles": TITLES,
        "s3_awaiting_human": s3_marker,
        "s3_event_kinds": s3_kinds,
        "e5_target": e5_target,
    }
    out = Path(str(db) + ".seeds.json")
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"manifest -> {out}", flush=True)
    print(f"s3 event kinds = {s3_kinds}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
