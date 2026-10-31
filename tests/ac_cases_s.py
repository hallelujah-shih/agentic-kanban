"""协议 conformance 判据（G36：SKILL 文本与服务端行为的双向漂移机器判据；板上 92a25b20）。

oracle 纪律：断言来源是 SKILL/PRD 文本（协议 spec）与 CLI 子命令表 / MCP 注册表（真值取自
仓库事实：cli.py add_parser 序列、`build_server()._tool_manager._tools`），不是实现代码行为
的镜像。真实 MCP stdio 子进程 + 人面 CLI + 事后 sqlite3 直查，禁 mock。

边界（BCD F4）：本判据测「SKILL prescribed 动作服务端是否可执行 + 板面结果是否符合文本
描述」，不测 agent 自觉性（接单确认/落点规则/收尾蒸馏的残余归 G27(a)）。

三例 36 断言（逐例编号 1-36，与 plan rev3 一致）：
- s_surface_bidirectional（1-8 静态双向核对）：SKILL「工具命名」节与 MCP 注册表双向 + 计数；
  corpus 内工具计数；corpus 内每个 agent-kanban 引用可分类（子命令/flag/路径/散文），
  不可分类即红；判别力自检（注入假引用必红 + 删除真实引用必红，防空集 vacuous 绿）。
  断言 1 与既有 p3_skill_text(5)（全文单向覆盖）的关系：断言 1 把同一方向收窄到「工具命名」
  节（节内提取而非全文子串），是增强不是重复——全文子串命中不构成命名节声明，收窄后
  注入/删除只作用于该节即可定向红。
- s_journey（9-25 canonical 剧本走查）：按 SKILL 门序 1-8 逐步执行真实 MCP stdio + 人面 CLI
  （临时板），断言每步可执行且板面结果与 SKILL 描述一致（含 reject 转 REOPEN + round、
  REOPEN 直接 claim 必 illegal_state、reopen --continue 重认领 round=2）。
- s_journey_shapes（26-36 负例腿）：SKILL 声称的 invalid 形态确实被拒（decision 三要素、
  acceptance 条目 item 文本），拒写零写入；纯字符串形态不退化；legacy 空白条目兜底
  （直插 SQL 种子，先例 ac_cases_m._seed）保留。

静态判据 corpus（明确排除面，登记 known-gaps 残余）：skill 树（skills/agent-kanban/**.md，
SKILL.md 命名节为 oracle）+ docs/PRD.md + docs/design.md + docs/mcp-config.md + docs/web.md
+ AGENTS.md + README.md。排除：docs/adr（gap 登记引用坏命令作证据）、docs/ops（历史验证记录）、
docs/plans、docs/superpowers、docs/business-contracts。规则盲区（不咬，G40）：flag 名/单
dash/大写 token/JSON 数组形态的命令引用（"args": ["run","agent-kanban","mcp"]）、基线数字
vs 套件实跑数、payload 形态未从 SKILL 文本派生、注册表 oracle 依赖 SDK 私有 _tool_manager。
"""

from __future__ import annotations

import json
import re
import sqlite3

from ac_lib import MCP, REPO_ROOT, cli, cli_ok, new_db, ok, query

SKILL_ROOT = REPO_ROOT / "skills" / "agent-kanban"
CORPUS_DOCS = ("docs/PRD.md", "docs/design.md", "docs/mcp-config.md", "docs/web.md",
               "AGENTS.md", "README.md")
_NAMING_RE = re.compile(r"(\d+)\s*个工具的原名固定[：:]\s*(.+)")
_COUNT_RE = re.compile(r"(\d+)\s*个\s*工具|工具(面|原名|集|清单)[^0-9\n]{0,15}(\d+)\s*个")
_TRAIL_PUNCT = "`\"' )]} ,;:.（）「」『』，；：。"
_TOK_SPLIT = re.compile(r"[\s（）「」『』，；：。]+")


# ---------------------------------------------------------------- 静态判据工具

def _corpus_files() -> dict[str, str]:
    files = {
        f"skills/agent-kanban/{p.relative_to(SKILL_ROOT).as_posix()}": p.read_text(encoding="utf-8")
        for p in sorted(SKILL_ROOT.rglob("*.md"))
    }
    for rel in CORPUS_DOCS:
        files[rel] = (REPO_ROOT / rel).read_text(encoding="utf-8")
    return files


def _section(text: str, heading: str) -> str:
    start = text.find(heading)
    if start < 0:
        return ""
    rest = text[start + len(heading):]
    nxt = rest.find("\n## ")
    return rest if nxt < 0 else rest[:nxt]


def _naming_names(section: str) -> tuple[int | None, set[str] | None]:
    """「N 个工具的原名固定：a / b / …」行 -> (声明计数, 工具名集合)；节缺失 -> (None, None)。"""
    m = _NAMING_RE.search(section or "")
    if not m:
        return None, None
    seg = m.group(2).split("。", 1)[0]
    names = {t.strip() for t in seg.split("/")
             if t.strip() and re.fullmatch(r"[a-z_]+", t.strip())}
    return int(m.group(1)), names


def _cli_subcommands() -> set[str]:
    text = (REPO_ROOT / "cli.py").read_text(encoding="utf-8")
    return set(re.findall(r'add_parser\("([a-z_]+)"', text))


def _naming_variant(section: str, mode: str) -> set[str] | None:
    """token 级注入（禁整段字面 replace）：add＝命名列表末尾追加探针 token renew_tool；
    del＝删除末位 token list_awaiting。返回变换后的工具名集合；注入失败（命名行缺失或
    行未变化）返回 None，断言侧显式红。"""
    lines = (section or "").splitlines()
    for i, ln in enumerate(lines):
        if not _NAMING_RE.search(ln):
            continue
        if mode == "add":
            new = re.sub(r"(list_awaiting)(。)", r"\1 / renew_tool\2", ln, count=1)
        else:
            new = re.sub(r" / list_awaiting(。)", r"\1", ln, count=1)
        if new == ln:
            return None
        lines[i] = new
        return _naming_names("\n".join(lines))[1]
    return None


def _cli_ref_reds(line: str, subcommands: set[str]) -> list[str]:
    """行内每个 agent-kanban 出现按 plan rev3 修正版规则分类；返回不可分类（红）的上下文。

    规则（逐字）：前紧邻字符 ∈ {/ - _ . ASCII 字母数字} -> identifier/path 合法；后无 token
    （行尾）合法；后随首块（按空白 + 全角标点（）「」『』，；：。切分）以 -- 开头＝flag 合法；
    首块剥尾随标点 ` " ' ) ] } , ; : . （）「」『』，；：。 后为空或非 [a-z_]+
    ＝散文/版本/标点合法；剥后为 [a-z_]+ 必须 ∈ CLI 子命令集合，否则红。匹配按行内 token 边界，
    禁跨行。
    """
    reds = []
    for m in re.finditer(r"agent-kanban", line):
        start = m.start()
        prev = line[start - 1] if start else ""
        if prev and (prev in "/-_." or (prev.isascii() and prev.isalnum())):
            continue
        blocks = [b for b in _TOK_SPLIT.split(line[m.end():]) if b]
        if not blocks:
            continue
        nxt = blocks[0]
        if nxt.startswith("--"):
            continue
        stripped = nxt.rstrip(_TRAIL_PUNCT)
        if not stripped or not re.fullmatch(r"[a-z_]+", stripped):
            continue
        if stripped not in subcommands:
            reds.append(line.strip()[:100])
    return reds


def s_surface_bidirectional():
    """静态双向核对（1-8）：工具命名节 vs MCP 注册表 + 计数 + CLI 引用分类 + 判别力自检。"""
    print("== s_surface_bidirectional: SKILL/文档 与 MCP 注册表/CLI 子命令表双向核对")
    from agent_kanban.mcp.server import build_server

    registry = set(build_server()._tool_manager._tools)
    files = _corpus_files()
    section = _section(files["skills/agent-kanban/SKILL.md"], "## 工具命名")
    count, names = _naming_names(section)

    ok("s_surface(1): SKILL 命名节集合 ⊇ MCP 注册表（文本缺工具名 -> 红）",
       names is not None and registry <= names,
       f"missing={sorted(registry - (names or set()))}")
    ok("s_surface(2): SKILL 命名节集合 ⊆ MCP 注册表（文本引用不存在工具 -> 红）",
       names is not None and names <= registry,
       f"ghosts={sorted((names or set()) - registry)}")
    ok("s_surface(3): SKILL 命名节「N 个工具」计数 == len(registry)",
       count is not None and count == len(registry),
       f"declared={count} registry={len(registry)}")

    count_hits = []
    count_reds = []
    n = len(registry)
    for rel, body in files.items():
        for i, line in enumerate(body.splitlines(), 1):
            for m in _COUNT_RE.finditer(line):
                count_hits.append(f"{rel}:{i}")
                if int(m.group(1) or m.group(3)) != n:
                    count_reds.append(f"{rel}:{i} {m.group(0)}")
    probes = ["本工具提供 3 个选项", "该工具 12 个参数中只有 2 个必填",
              "工具命名节有 14 个条目，其中 3 个是交接类"]
    probe_hits = [p for p in probes if _COUNT_RE.search(p)]
    ok("s_surface(4): corpus 内工具计数行（收窄正则）== 注册表大小（探针不假红 + 命中下界防过窄）",
       not count_reds and not probe_hits and len(count_hits) >= 4,
       "; ".join(count_reds[:6]) or f"hits={len(count_hits)} probes={probe_hits}")

    subs = _cli_subcommands()
    ref_reds = []
    for rel, body in files.items():
        for i, line in enumerate(body.splitlines(), 1):
            if "agent-kanban" not in line:
                continue
            ref_reds += [f"{rel}:{i}: {ctx}" for ctx in _cli_ref_reds(line, subs)]
    n_skill = sum(1 for _ in SKILL_ROOT.rglob("*.md"))
    total_refs = sum(body.count("agent-kanban") for body in files.values())
    ok("s_surface(5): corpus 内每个 agent-kanban 引用可分类（输入面守卫：文件集齐 + 引用数下界）",
       not ref_reds and len(CORPUS_DOCS) == 6 and len(files) == n_skill + len(CORPUS_DOCS)
       and total_refs >= 20,
       "; ".join(ref_reds[:6]) or f"files={len(files)} skill={n_skill} docs={len(CORPUS_DOCS)} refs={total_refs}")

    red_inj = _cli_ref_reds("详见 `agent-kanban serve` 用法", subs)
    red_fw = _cli_ref_reds("跑 agent-kanban serve，然后看板", subs)
    g_eol = _cli_ref_reds("入口是 agent-kanban", subs)
    g_path = _cli_ref_reds("落到 <父目录>/agent-kanban/ 下", subs)
    g_cmd = _cli_ref_reds("uv run agent-kanban mcp", subs)
    ok("s_surface(6): 断言 5 判别力自检（注入假子命令 serve 必红含全角逗号连写形；行尾裸写/路径尾斜杠/真子命令必绿）",
       bool(red_inj) and bool(red_fw) and not g_eol and not g_path and not g_cmd,
       f"red_inj={len(red_inj)} red_fw={len(red_fw)} g_eol={g_eol} g_path={g_path} g_cmd={g_cmd}")

    n_inj = _naming_variant(section, "add")
    ok("s_surface(7): 断言 2 判别力自检（token 级注入 renew_tool -> ⊄ 注册表必红；注入失败必红）",
       n_inj is not None and "renew_tool" in n_inj and not n_inj <= registry,
       f"n_inj={sorted(n_inj) if n_inj else None} ghosts={sorted((n_inj or set()) - registry)}")

    n_del = _naming_variant(section, "del")
    ok("s_surface(8): 断言 1 判别力自检（token 级删 list_awaiting -> ⊉ 注册表必红，防空集 vacuous 绿；删除失败必红）",
       n_del is not None and "list_awaiting" not in n_del and not registry <= n_del,
       f"n_del={sorted(n_del) if n_del else None} missing={sorted(registry - (n_del or set()))}")


# ---------------------------------------------------------------- 剧本走查工具

def _rr_payload(db, rid: str) -> dict:
    row = query(db, "SELECT payload FROM events WHERE requirement_id=? "
                     "AND kind='review_request' ORDER BY seq DESC LIMIT 1", (rid,))[0]
    return json.loads(row["payload"])


def _ev_count(db, rid: str) -> int:
    return query(db, "SELECT COUNT(*) AS n FROM events WHERE requirement_id=?", (rid,))[0]["n"]


def _snap_global(db) -> tuple:
    """全局写入指纹（events 数, claims 数, 各需求 state）——零写入对照（ac_cases_m._snap 同模式）。"""
    ev = query(db, "SELECT COUNT(*) AS n FROM events")[0]["n"]
    cl = query(db, "SELECT COUNT(*) AS n FROM claims")[0]["n"]
    states = [(r["id"], r["state"]) for r in query(db, "SELECT id, state FROM requirements ORDER BY id")]
    return (ev, cl, tuple(states))


def _snap_reqs(db) -> tuple:
    rq = query(db, "SELECT COUNT(*) AS n FROM requirements")[0]["n"]
    ev = query(db, "SELECT COUNT(*) AS n FROM events")[0]["n"]
    return (rq, ev)


def _state(db, rid: str) -> str:
    return query(db, "SELECT state FROM requirements WHERE id=?", (rid,))[0]["state"]


def _err_code(m: MCP, name: str, args: dict) -> str:
    """call 解错误码；成功返回 'OK'（负例腿用，禁 raise——红阶段成功也算可观测结果）。"""
    res = m.call(name, args)
    if res.get("isError"):
        return json.loads(res["content"][0]["text"])["code"]
    return "OK"


def s_journey():
    """canonical 剧本走查（9-25）：SKILL 门序 1-8 全步可执行 + 板面结果与 SKILL 描述一致。"""
    print("== s_journey: 门序 1-8 全步走查（真实 MCP stdio + 人面 CLI，临时板）")
    db = new_db()
    m = MCP(db).start()
    try:
        # 门 1 读/登记：new_requirement（带 2 条 acceptance 锚）
        res = m.call_ok("new_requirement", {
            "title": "s-journey", "acceptance": [{"item": "锚一"}, {"item": "锚二"}]})
        rid = res["requirement_id"]
        ok("s_journey(9): new_requirement（2 条 acceptance 锚）-> state OPEN",
           res.get("state") == "OPEN" and _state(db, rid) == "OPEN",
           f"res={res.get('state')} db={_state(db, rid)}")

        m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "journey"})
        ok("s_journey(10): claim_task -> CLAIMED", _state(db, rid) == "CLAIMED", _state(db, rid))

        m.call_ok("add_record", {"requirement_id": rid, "kind": "note", "title": "接单确认",
                                 "content": "理解：协议 conformance 剧本走查。\n假设：无。\n缺口：无。"})
        note = query(db, "SELECT kind, title FROM events WHERE requirement_id=? "
                               "AND kind='note' ORDER BY seq", (rid,))
        ok("s_journey(11): 接单确认 add_record(kind=note, title 逐字「接单确认」) 落库",
           len(note) == 1 and note[0]["title"] == "接单确认", str([dict(r) for r in note]))

        st = m.call_ok("add_subtask", {"requirement_id": rid, "title": "子一", "ordinal": 1,
                                       "acceptance": [{"item": "验收项一", "links_to": "a1"}]})
        sstate = query(db, "SELECT state FROM subtasks WHERE id=?", (st["subtask_id"],))[0]["state"]
        ok("s_journey(12): add_subtask（acceptance + links_to 指需求锚）-> 子任务起始 todo",
           sstate == "todo", sstate)

        acc = json.loads(query(db, "SELECT acceptance FROM subtasks WHERE id=?",
                               (st["subtask_id"],))[0]["acceptance"])
        ok("s_journey(13): add_subtask 落库 acceptance 逐字（不归一、不合成 id，ac_cases_j 同口径）",
           acc == [{"item": "验收项一", "links_to": "a1"}], json.dumps(acc, ensure_ascii=False))

        m.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": st["subtask_id"],
                                     "state": "in_progress"})
        m.call_ok("update_subtask", {"requirement_id": rid, "subtask_id": st["subtask_id"],
                                     "state": "done"})
        sstate = query(db, "SELECT state FROM subtasks WHERE id=?", (st["subtask_id"],))[0]["state"]
        ok("s_journey(14): update_subtask in_progress -> done（状态迁移是进度唯一来源）",
           sstate == "done", sstate)

        out = cli(db, "view", "summary", "--requirement-id", rid)
        det = m.call_ok("get_task_detail", {"requirement_id": rid})
        ok("s_journey(15): 人面 CLI view summary 板面进度 1/1（progress 派生，get_task_detail 返回键不含 progress）",
           out.returncode == 0 and "进度: 1/1 完成" in out.stdout and "progress" not in det,
           f"rc={out.returncode} keys={sorted(det)} "
           + (out.stdout[:120] if out.returncode == 0 else out.stderr[:120]))

        dec_payload = {"choice": "选 SQLite", "rationale": "零依赖",
                       "alternatives": [{"option": "Postgres", "rejected_reason": "运维成本高"}]}
        m.call_ok("add_record", {"requirement_id": rid, "kind": "decision", "title": "选型",
                                 "content": "方案总结", "payload": dec_payload})
        pl = json.loads(query(db, "SELECT payload FROM events WHERE requirement_id=? "
                                  "AND kind='decision' ORDER BY seq DESC LIMIT 1", (rid,))[0]["payload"])
        ok("s_journey(16): decision 三要素齐备 -> 落库 payload 含 choice/rationale/alternatives",
           pl.get("choice") == "选 SQLite" and pl.get("rationale") == "零依赖"
           and pl.get("alternatives") == [{"option": "Postgres", "rejected_reason": "运维成本高"}],
           json.dumps(pl, ensure_ascii=False)[:200])

        m.call_ok("update_progress", {"requirement_id": rid, "note": "n", "headline": "h1"})
        pn = query(db, "SELECT title FROM events WHERE requirement_id=? "
                            "AND kind='progress_note' ORDER BY seq DESC LIMIT 1", (rid,))
        ok("s_journey(17): update_progress(headline 非空) -> progress_note 事件",
           len(pn) == 1 and pn[0]["title"] == "h1", str([dict(r) for r in pn]))

        m.call_ok("request_review", {
            "requirement_id": rid, "evidence": {"test_summary": "t"}, "summary_line": "交接：完成",
            "assessments": [{"subtask_id": st["subtask_id"],
                             "items": [{"item": "验收项一", "state": "met"}]}]})
        ah = json.loads(query(db, "SELECT awaiting_human FROM requirements WHERE id=?",
                              (rid,))[0]["awaiting_human"])
        ok("s_journey(18): request_review -> awaiting_human kind=review",
           ah.get("kind") == "review", json.dumps(ah, ensure_ascii=False)[:160])

        asm = _rr_payload(db, rid).get("assessment")
        ok("s_journey(19): payload.assessment required == covered",
           asm is not None and asm["required"] == asm["covered"] == 1, json.dumps(asm))

        lw = m.call_ok("list_awaiting", {})
        ok("s_journey(20): list_awaiting 命中该需求（唯一等待面）",
           any(row.get("requirement_id") == rid for row in lw.get("awaiting", [])),
           json.dumps(lw, ensure_ascii=False)[:160])

        resj = cli_ok(db, "reject", "--requirement-id", rid, "--reason", "评审拒绝：示例拒因")
        rj = query(db, "SELECT payload FROM events WHERE requirement_id=? "
                            "AND kind='review_reject' ORDER BY seq DESC LIMIT 1", (rid,))
        ok("s_journey(21): 人面 CLI reject -> REOPEN + review_reject 事件 round=1",
           resj.get("state") == "REOPEN" and _state(db, rid) == "REOPEN"
           and len(rj) == 1 and json.loads(rj[0]["payload"]).get("round") == 1,
           f"cli={resj.get('state')} db={_state(db, rid)} round={json.loads(rj[0]['payload']) if rj else None}")

        snap = _snap_global(db)
        code = _err_code(m, "claim_task", {"requirement_id": rid, "agent_name": "journey"})
        ok("s_journey(22): REOPEN 直接 claim_task -> illegal_state（claim 起点写死 OPEN + transition rowcount 守卫，零写入）",
           code == "illegal_state" and _snap_global(db) == snap, f"{code} snap_changed={_snap_global(db) != snap}")

        cli_ok(db, "reopen", "--requirement-id", rid, "--continue")
        ok("s_journey(23): 人面 CLI reopen --continue -> OPEN", _state(db, rid) == "OPEN", _state(db, rid))

        m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "journey2"})
        ok("s_journey(24): 重认领 claim_task -> CLAIMED", _state(db, rid) == "CLAIMED", _state(db, rid))

        m.call_ok("request_review", {
            "requirement_id": rid, "evidence": {"test_summary": "t2"}, "summary_line": "第 2 轮交接",
            "assessments": [{"subtask_id": st["subtask_id"],
                             "items": [{"item": "验收项一", "state": "met"}]}]})
        rnd = json.loads(query(db, "SELECT payload FROM events WHERE requirement_id=? "
                                    "AND kind='review_request' ORDER BY seq DESC LIMIT 1",
                               (rid,))[0]["payload"]).get("round")
        ok("s_journey(25): 再次交接 -> round=2（第几轮交接板面可区分）", rnd == 2, str(rnd))
    finally:
        m.close()


def s_journey_shapes():
    """负例腿（26-36）：SKILL 声称的 invalid 形态确实被拒 + 零写入；既有便利形态不退化。"""
    print("== s_journey_shapes: decision 三要素 / acceptance item 文本 负例 + legacy 兜底")
    db = new_db()
    m = MCP(db).start()
    try:
        rid = m.call_ok("new_requirement", {"title": "s-shapes",
                                            "acceptance": [{"item": "原锚"}]})["requirement_id"]
        m.call_ok("claim_task", {"requirement_id": rid, "agent_name": "a"})
        base = {"requirement_id": rid, "kind": "decision", "title": "t"}

        # 26-31：decision 形态（oracle＝SKILL「决策叙事」payload 形态钉死）
        cases = [
            (26, "decision 缺 choice",
             {"rationale": "r", "alternatives": [{"option": "o", "rejected_reason": "rr"}]}),
            (27, "decision choice 纯空白",
             {"choice": "   ", "rationale": "r", "alternatives": [{"option": "o", "rejected_reason": "rr"}]}),
            (28, "decision 缺 rationale（回归锚，既有校验未退化）",
             {"choice": "c", "alternatives": [{"option": "o", "rejected_reason": "rr"}]}),
            (29, "decision alternatives 空",
             {"choice": "c", "rationale": "r", "alternatives": []}),
            (30, "decision alt 缺 rejected_reason",
             {"choice": "c", "rationale": "r", "alternatives": [{"option": "o"}]}),
        ]
        for num, label, payload in cases:
            snap = _ev_count(db, rid)
            code = _err_code(m, "add_record", {**base, "payload": payload})
            ok(f"s_shapes({num}): {label} -> invalid_record 且零写入",
               code == "invalid_record" and _ev_count(db, rid) == snap, code)
        snap = _ev_count(db, rid)
        code = _err_code(m, "add_record", base)  # 无 payload 键
        ok("s_shapes(31): decision 无 payload -> invalid_record 且零写入",
           code == "invalid_record" and _ev_count(db, rid) == snap, code)

        # 32：new_requirement acceptance dict 缺 item 文本
        snap = _snap_reqs(db)
        code = _err_code(m, "new_requirement", {"title": "s-neg32", "acceptance": [{"id": "x1"}]})
        ok("s_shapes(32): new_requirement acceptance dict 缺 item 文本 -> invalid_record 且零写入",
           code == "invalid_record" and _snap_reqs(db) == snap, code)

        # 33：set_expectations acceptance dict 缺 item 文本（原锚不变）
        acc_before = query(db, "SELECT acceptance FROM requirements WHERE id=?", (rid,))[0]["acceptance"]
        code = _err_code(m, "set_expectations", {"requirement_id": rid, "acceptance": [{"id": "x1"}]})
        acc_after = query(db, "SELECT acceptance FROM requirements WHERE id=?", (rid,))[0]["acceptance"]
        ok("s_shapes(33): set_expectations acceptance dict 缺 item 文本 -> invalid_record 且原锚不变",
           code == "invalid_record" and acc_after == acc_before,
           f"{code} acc={acc_before} -> {acc_after}")

        # 34：add_subtask acceptance dict 缺 item 文本（子任务行不存在）
        snap = (query(db, "SELECT COUNT(*) AS n FROM subtasks WHERE requirement_id=?", (rid,))[0]["n"],
                _ev_count(db, rid))
        code = _err_code(m, "add_subtask", {"requirement_id": rid, "title": "s34", "ordinal": 1,
                                            "acceptance": [{"id": "x1"}]})
        after = (query(db, "SELECT COUNT(*) AS n FROM subtasks WHERE requirement_id=?", (rid,))[0]["n"],
                 _ev_count(db, rid))
        ok("s_shapes(34): add_subtask acceptance dict 缺 item 文本 -> invalid_record 且零写入",
           code == "invalid_record" and after == snap, f"{code} {snap} -> {after}")

        # 35：纯字符串形态不退化（需求侧归一 / 子任务侧落库逐字，sa_stracc/ac_cases_j 同口径）
        rid2 = m.call_ok("new_requirement", {"title": "s-str", "acceptance": ["字符串锚"]})["requirement_id"]
        acc2 = json.loads(query(db, "SELECT acceptance FROM requirements WHERE id=?",
                                (rid2,))[0]["acceptance"])
        st2 = m.call_ok("add_subtask", {"requirement_id": rid, "title": "s35", "ordinal": 2,
                                        "acceptance": ["子任务字符串"]})
        acc2s = json.loads(query(db, "SELECT acceptance FROM subtasks WHERE id=?",
                                 (st2["subtask_id"],))[0]["acceptance"])
        ok("s_shapes(35): acceptance 纯字符串——需求侧归一 {item,id} / 子任务侧落库逐字（不退化）",
           acc2 == [{"item": "字符串锚", "id": "a1"}] and acc2s == ["子任务字符串"],
           f"req={json.dumps(acc2, ensure_ascii=False)} sub={json.dumps(acc2s, ensure_ascii=False)}")

        # 36：legacy 空白验收条目（直插 SQL 种子，先例 ac_cases_m._seed）兜底分支保留
        db3 = new_db()
        m3 = MCP(db3).start()
        try:
            rid3 = m3.call_ok("new_requirement", {"title": "s-legacy"})["requirement_id"]
            m3.call_ok("claim_task", {"requirement_id": rid3, "agent_name": "l"})
            sid = "ab" * 16
            conn = sqlite3.connect(str(db3))
            conn.execute(
                "INSERT INTO subtasks (id, requirement_id, ordinal, title, acceptance, state, "
                "created_at, updated_at) VALUES (?, ?, 1, 'legacy', ?, 'todo', "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')",
                (sid, rid3, '[{"item":"   "},{"item":"B1"}]'),
            )
            conn.commit()
            conn.close()
            m3.call_ok("request_review", {
                "requirement_id": rid3, "evidence": {"test_summary": "t"}, "summary_line": "x",
                "assessments": [{"subtask_id": sid, "items": [{"item": "B1", "state": "met"}]}]})
            asm = _rr_payload(db3, rid3).get("assessment")
            acc3 = json.loads(query(db3, "SELECT acceptance FROM subtasks WHERE id=?",
                                    (sid,))[0]["acceptance"])
            ok("s_shapes(36): legacy 空白验收条目（SQL 种子）不计分母且不卡死交接（required==covered），"
               "自评落库后条目逐字保留且不重复",
               asm is not None and asm["required"] == asm["covered"] == 1
               and sorted(str(a.get("item")) for a in acc3) == ["   ", "B1"],
               json.dumps({"asm": asm, "acc": acc3}, ensure_ascii=False))
        finally:
            m3.close()
    finally:
        m.close()
