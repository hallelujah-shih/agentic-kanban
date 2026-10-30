"""交付形态自足（需求 ef007e26，验收 a1-a11）：包内携带整棵 skill 树、文本自足、版本对齐、断链可查。

oracle 纪律：真值取自仓库真实配置与代码（pyproject / `build_server()` 注册表 / 代码常量），
不抄被测文本；构建产物用真实 hatchling 构建后开 zip 核对；`skill` 子命令在**解压后的 wheel 树**里跑
（cwd=extract，断言 cli 来源），避免命中的是源码树而空转假绿。

**仓内路径判据（a1/a5）**：对树内每个 `.md` 先切「token」＝非空白连续串，同一 token 内命中仓内路径
形态即红，除非该 token 属于下列放行面：
  - 永久 URL：token 含 `://`（深挖入口）；
  - `<skill_dir>/…`：技能自引用（a11 的正典形态）；
  - 四类装机落点：`.opencode/skills`、`.agents/skills`、`~/.config/opencode/skills`、`~/.claude/skills`；
  - adopter 自己的项目约定（裸 `docs/`、`AGENTS.md`、`README`）不在禁项模式内，故自然放行。

a5 点名的 `AGENTS.md` 形态按**限定词**判（裸文件名本身是 adopter 的合法指路）：另有一层行级扫描
`_repo_qualified_hits`，命中「本仓/仓内/仓库内/本仓库/仓库根」+ 6 字符内 + `AGENTS.md`/`docs/`/`README`
即红——即「见本仓 AGENTS.md 的环境卡」这类回潮会被抓，而「项目根的 AGENTS.md」（adopter 的）放行。
两层判据都做正反对照自检（`p3_skill_text(3)`），防判据死于零命中。
已知边界（不修，登记）：token 规则放行 `file:///x/docs/PRD.md` 这类伪 URL；无边界锚匹配
（`安装见docs/PRD.md第3节` 仍命中，正是要的效果）。

**引用判据（a11）**：`references|templates/**.md` 形态（含嵌套子目录、大小写、通配符）逐个判存在；
引用前只允许 `<skill_dir>/` 前缀，别的前缀（`a/references/x.md`、`../references/x.md`）按断链红处理。
通配符引用判缺（逼作者写实名文件）。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import zipfile
from pathlib import Path

from ac_lib import CLI, REPO_ROOT, SRC, TIMEOUT, VENV_PY, cli, new_db, ok

SKILL_ROOT = REPO_ROOT / "skills" / "agent-kanban"
SKILL = SKILL_ROOT / "SKILL.md"
PACKAGED_DIR = "agent_kanban/data/skill"
TOOL_CALL_NAMES = ("claim_task", "add_record", "request_review", "mark_blocked")
LANDING = (".opencode/skills", ".agents/skills", "~/.config/opencode/skills", "~/.claude/skills")
REPO_PATTERNS = (
    r"docs/(?:PRD|mcp-config|design|web)\.md",
    r"docs/(?:adr|ops|plans|business-contracts|superpowers)/",
    r"(?:PRD|mcp-config|design|web)\.md",
    r"src/agent_kanban",
    r"tests/",
    r"\.venv/",
    r"pyproject\.toml",
    r"uv\.lock",
    r"cli\.py",
    r"skills/agent-kanban/",
)
NOISE = ("__pycache__", ".DS_Store", ".pyc")
# 引用形态：允许嵌套子目录（references/a/b.md）、大小写、通配符（通配必判缺）
REF_RE = re.compile(
    r"(?:(?:<skill_dir>)?/)?(?:references|templates)/[A-Za-z0-9_./*-]+\.md"
    r"(?:#[^\s，。；：、」』)>`|]*)?",
    re.IGNORECASE,
)
# a5 点名的 AGENTS.md / docs 形态：带仓内限定词即红（裸文件名是 adopter 的合法指路）
REPO_QUALIFIED = re.compile(r"(?:本仓|仓内|仓库内|本仓库|仓库根)[^\n]{0,6}?(?:AGENTS\.md|docs/|README)")
BODY_FORBIDDEN = (
    r"opencode\.json", r"opencode run", r"ses_",
    r"(?<![A-Za-z0-9_])OpenCode(?![A-Za-z0-9_])",
    r"~/projects", r"~/test", r"~/src", r"--model provider/model",
    r"/tmp", r"\"mcp\"", r"\"environment\"",
    r"(?<![A-Za-z0-9_])BCD(?![A-Za-z0-9_])", r"(?<![A-Za-z0-9_])B6(?![A-Za-z0-9_])",
)
CLIENT_TOKENS = (
    "opencode.json", "opencode run", "ses_", "OpenCode", "~/projects", "~/test", "~/src",
    "--model provider/model", "/tmp",
)


def _tree_files(root: Path) -> dict[str, bytes]:
    out = {}
    for path in root.rglob("*"):
        if not path.is_file() or any(n in path.name or n in path.parts for n in NOISE):
            continue
        out[path.relative_to(root).as_posix()] = path.read_bytes()
    return out


def _md_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.md") if not any(n in p.parts for n in NOISE))


def _repo_path_hits(text: str) -> list[str]:
    hits = []
    for token in re.findall(r"\S+", text):
        if any(mark in token for mark in ("://", "<skill_dir>", *LANDING)):
            continue
        for pattern in REPO_PATTERNS:
            m = re.search(pattern, token)
            if m:
                hits.append(f"{pattern} -> {token[:80]}")
                break
    return hits


def _repo_qualified_hits(text: str) -> list[str]:
    return [m.group(0)[:80] for m in REPO_QUALIFIED.finditer(text)]


def _bad_ref_prefixes(text: str) -> list[str]:
    """引用前必须是 `<skill_dir>/` 或行内直接可解析的形态；只有路径形态的前缀（以 / 结尾）才算越界。"""
    bad = []
    for token in re.findall(r"\S+", text):
        for m in REF_RE.finditer(token):
            prefix = token[:m.start()]
            if not prefix.endswith("/") or prefix.endswith("<skill_dir>/"):
                continue
            bad.append(f"{prefix}{m.group(0)}")
    return bad


def _refs(text: str) -> set[str]:
    refs = set()
    for m in REF_RE.finditer(text):
        cand = m.group(0).replace("<skill_dir>", "").lstrip("/")
        refs.add(re.split(r"#", cand, 1)[0].rstrip("，。；：、」』)>`|"))
    return refs


def _run_py(code: str, *, cwd: Path, env: dict, args: list[str] | None = None,
            timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(VENV_PY), "-c", code, *(args or [])],
        cwd=str(cwd), env=env, capture_output=True, timeout=timeout,
    )


def _build_wheel(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(
        [str(VENV_PY), "-m", "hatchling", "build", "-t", "wheel", "-d", str(out)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=TIMEOUT * 4,
    )
    if res.returncode != 0:
        raise AssertionError(f"wheel build failed: {res.stderr[-800:]}")
    wheels = sorted(out.glob("*.whl"))
    if len(wheels) != 1:
        raise AssertionError(f"expected exactly 1 wheel, got {wheels}")
    return wheels[0]


def _extract_wheel(wheel: Path, dest: Path) -> Path:
    with zipfile.ZipFile(wheel) as zf:
        zf.extractall(dest)
    return dest


def _wheel_env(extract: Path) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(extract)
    env.pop("AGENT_KANBAN_DB", None)
    return env


def p3_skill():
    """a4：wheel 携带整棵 skill 树、单点来源、取出结构一致、dispatch 协议入口可达。"""
    tmp = Path(tempfile.mkdtemp(prefix="ak-skill-"))
    wheel = _build_wheel(tmp / "dist")
    with zipfile.ZipFile(wheel) as zf:
        packaged = {
            name[len(PACKAGED_DIR) + 1:]: zf.read(name)
            for name in zf.namelist()
            if name.startswith(PACKAGED_DIR + "/") and not any(n in name for n in NOISE)
        }
    source = _tree_files(SKILL_ROOT)
    ok("p3_skill(1): wheel 内 skill 树文件集合与单一来源一致",
       set(packaged) == set(source), f"packaged={sorted(packaged)[:5]} source={sorted(source)[:5]}")
    differing = [rel for rel in source if packaged.get(rel) != source[rel]]
    ok("p3_skill(2): 包内每个文件与源逐字节一致（无第二份副本）", not differing, str(differing[:4]))

    extract = _extract_wheel(wheel, tmp / "extract")
    env = _wheel_env(extract)
    where = _run_py("import cli; print(cli.__file__)", cwd=extract, env=env)
    ok("p3_skill(3): 被测 cli 来自解压后的 wheel 树",
       where.returncode == 0 and str(extract) in where.stdout.decode().strip(),
       where.stdout.decode().strip() or where.stderr.decode()[-300:])

    printed = _run_py("import sys; from cli import main; sys.exit(main(['skill', '--print']))",
                      cwd=extract, env=env)
    ok("p3_skill(4): skill --print 输出与源 SKILL.md 逐字节一致",
       printed.returncode == 0 and printed.stdout == source["SKILL.md"],
       f"rc={printed.returncode} bytes={len(printed.stdout)}")

    dest = tmp / "out"
    dumped = _run_py("import sys; from cli import main; sys.exit(main(['skill', '--dest', sys.argv[1]]))",
                     cwd=extract, env=env, args=[str(dest)])
    ok("p3_skill(5): skill --dest 复制出 <dir>/agent-kanban/ 整棵树且与源一致",
       dumped.returncode == 0 and _tree_files(dest / "agent-kanban") == source,
       f"rc={dumped.returncode} files={sorted(_tree_files(dest / 'agent-kanban'))[:5] if dest.exists() else None}")

    missing = _run_py("import sys; from cli import main; sys.exit(main(['skill']))", cwd=extract, env=env)
    ok("p3_skill(6): skill 缺省选项 -> rc 1 + stderr 用法 + stdout 空",
       missing.returncode == 1 and missing.stdout == b"" and b"skill" in missing.stderr,
       f"rc={missing.returncode} stderr={missing.stderr.decode()[:120]!r}")

    both = _run_py("import sys; from cli import main; sys.exit(main(['skill', '--print', '--dest', sys.argv[1]]))",
                   cwd=extract, env=env, args=[str(tmp / "both")])
    ok("p3_skill(7): --print 与 --dest 同给 -> rc 1 + stderr，且不落文件",
       both.returncode == 1 and both.stdout == b"" and b"skill" in both.stderr
       and not (tmp / "both").exists(),
       f"rc={both.returncode} stderr={both.stderr.decode()[:120]!r}")

    blocker = tmp / "blocker"
    blocker.write_text("x", encoding="utf-8")
    bad_dest = _run_py("import sys; from cli import main; sys.exit(main(['skill', '--dest', sys.argv[1]]))",
                       cwd=extract, env=env, args=[str(blocker)])
    ok("p3_skill(8): --dest 指向普通文件 -> rc 1 + stderr 人话（不裸 traceback）",
       bad_dest.returncode == 1 and bad_dest.stdout == b""
       and b"Traceback" not in bad_dest.stderr and "目录".encode() in bad_dest.stderr,
       f"rc={bad_dest.returncode} stderr={bad_dest.stderr.decode()[:160]!r}")

    entry = _run_py("from agent_kanban.dispatch import _skill_path; print(_skill_path())",
                    cwd=extract, env=env)
    entry_path = Path(entry.stdout.decode().strip()) if entry.returncode == 0 else None
    ok("p3_skill(9): dispatch 派发稿的协议入口在 wheel 安装下真实存在",
       entry_path is not None and entry_path.is_file(),
       f"path={entry_path} rc={entry.returncode} {entry.stderr.decode()[:200]}")


def _frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    block = text.split("\n---\n", 1)[0][4:]
    fields: dict[str, str] = {}
    for line in block.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def _section(text: str, heading: str) -> str:
    start = text.find(heading)
    if start < 0:
        return ""
    rest = text[start + len(heading):]
    nxt = rest.find("\n## ")
    return rest if nxt < 0 else rest[:nxt]


def _pyproject() -> dict:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def p3_skill_text():
    """a1/a2/a3/a8/a9/a10：文本自足、工具命名、契约事实反读、版本链、客户端无关、分层。"""
    files = {p.relative_to(SKILL_ROOT).as_posix(): p.read_text(encoding="utf-8") for p in _md_files(SKILL_ROOT)}
    text = files["SKILL.md"]
    front = _frontmatter(text)

    hits, bad_prefix, qualified = [], [], []
    for rel, body in files.items():
        hits += [f"{rel}: {h}" for h in _repo_path_hits(body)]
        bad_prefix += [f"{rel}: {b}" for b in _bad_ref_prefixes(body)]
        qualified += [f"{rel}: {h}" for h in _repo_qualified_hits(body)]
    ok("p3_skill_text(1): 树内 .md 无仓内相对路径引用（token 判据）", not hits, "; ".join(hits[:4]))
    ok("p3_skill_text(2): AGENTS.md/docs 不带仓内限定词（a5 字面形态）",
       not qualified, "; ".join(qualified[:4]))

    # 判据自检（正反对照）：两层判据都要能咬住回潮、放行 adopter 约定，否则零命中也会绿
    must_red = ("安装见docs/PRD.md第3节", "见本仓 AGENTS.md 的环境卡",
                "细节见 docs/mcp-config.md", "<repo>/docs/PRD.md", "skills/agent-kanban/SKILL.md")
    must_green = ("项目根的 AGENTS.md 里放一节环境卡", "落 .opencode/skills/agent-kanban/",
                  "见 <skill_dir>/references/contract.md",
                  "契约文本 https://github.com/hallelujah-shih/agentic-kanban/blob/main/docs/PRD.md")
    red_missed = [s for s in must_red
                  if not (_repo_path_hits(s) or _repo_qualified_hits(s))]
    green_flagged = [s for s in must_green
                     if _repo_path_hits(s) or _repo_qualified_hits(s)]
    ok("p3_skill_text(3): 仓内路径判据有判别力（回潮必红、adopter 约定必绿）",
       not red_missed and not green_flagged,
       f"missed={red_missed} false_red={green_flagged}")

    ok("p3_skill_text(4): skill 自引用只允许 <skill_dir>/ 或行内裸 references/ 形态",
       not bad_prefix, "; ".join(bad_prefix[:4]))

    from agent_kanban.mcp.server import build_server

    registry = set(build_server()._tool_manager._tools)
    section = _section(text, "## 工具命名")
    desc = front.get("description", "")
    ok("p3_skill_text(5): SKILL.md 覆盖 MCP 真实注册表全部工具名",
       registry and all(name in text for name in registry),
       f"missing={sorted(n for n in registry if n not in text)}")
    ok("p3_skill_text(6): description 与「工具命名」节都说明两种客户端前缀形态",
       all("kanban_<tool>" in chunk and "mcp__<server>__<tool>" in chunk for chunk in (desc, section)),
       f"desc={len(desc)}B section={len(section)}B")
    ok("p3_skill_text(7): 废弃写法 agent_kanban_ 全文不出现",
       not any("agent_kanban_" in body for body in files.values()),
       str([rel for rel, body in files.items() if "agent_kanban_" in body]))
    ok("p3_skill_text(8): description <= 1024 字符", len(desc) <= 1024, str(len(desc)))

    py = _pyproject()
    floor = py["project"]["requires-python"].lstrip(">=")
    entry = next(iter(py["project"]["scripts"]))
    env = {k: v for k, v in os.environ.items() if k != "AGENT_KANBAN_DB"}
    env["PYTHONPATH"] = str(SRC)
    db_probe = subprocess.run(
        [str(VENV_PY), "-c",
         "from pathlib import Path; from agent_kanban.config import db_path;"
         "print(str(db_path()).replace(str(Path.home()), '~'))"],
        capture_output=True, text=True, env=env, cwd=str(REPO_ROOT), timeout=TIMEOUT,
    )
    default_db = db_probe.stdout.strip()
    ok("p3_skill_text(9): 安装事实与代码一致（Python 下界 / 入口 / 默认 DB / 四类落点）",
       floor in text and f"{entry} mcp" in text and default_db in text
       and all(mark in text for mark in LANDING),
       f"floor={floor} db={default_db} landing={[m for m in LANDING if m not in text]}")

    from agent_kanban import CONTRACT_VERSION, __version__

    prd_first = (REPO_ROOT / "docs" / "PRD.md").read_text(encoding="utf-8").splitlines()[0]
    prd_match = re.search(r"PRD v(\d+\.\d+)", prd_first)
    ok("p3_skill_text(10): 版本链一致（代码常量 == frontmatter == PRD 首行 == MCP server）",
       prd_match is not None
       and CONTRACT_VERSION == front.get("contract-version") == prd_match.group(1)
       and build_server().version == __version__ == py["project"]["version"],
       f"code={CONTRACT_VERSION} skill={front.get('contract-version')} "
       f"prd={prd_match.group(1) if prd_match else None} server={build_server().version}")

    version_out = cli(new_db(), "--version")
    ok("p3_skill_text(11): agent-kanban --version 同时给包版本与契约版本",
       version_out.returncode == 0 and __version__ in version_out.stdout
       and CONTRACT_VERSION in version_out.stdout,
       version_out.stdout.strip() or version_out.stderr.strip()[:200])

    leaks = [f"SKILL.md: {p} -> {m.group(0)}"
             for p in BODY_FORBIDDEN for m in re.finditer(p, text)]
    ok("p3_skill_text(12): SKILL.md 不含客户端/本机特有内容（a8）", not leaks, "; ".join(leaks[:4]))
    dropped = [tok for tok in CLIENT_TOKENS
               if not any(tok in body for rel, body in files.items() if rel != "SKILL.md")]
    ok("p3_skill_text(13): 客户端/本机内容下沉到 references（不是被删掉）", not dropped, str(dropped))

    refs = sorted(p.relative_to(SKILL_ROOT).as_posix() for p in (SKILL_ROOT / "references").glob("*.md"))
    tpls = sorted(p.relative_to(SKILL_ROOT).as_posix() for p in (SKILL_ROOT / "templates").glob("*.md"))
    triggers = ("当", "遇到", "涉及", "需要")
    undiscoverable = [rel for rel in refs
                      if not any(Path(rel).name in line and any(t in line for t in triggers)
                                 for line in text.splitlines())]
    err_section = _section(text, "## 高频错误码")
    err_rows = [ln for ln in err_section.splitlines()
                if ln.startswith("|") and not set(ln) <= set("|-: ")]
    err_rows = err_rows[1:] if err_rows else []
    ok("p3_skill_text(14): 分层到位（a10）",
       len(text.splitlines()) <= 500 and len(refs) >= 4 and len(tpls) >= 2 and not undiscoverable
       and not (SKILL_ROOT / "scripts").exists()
       and not [p.name for p in SKILL_ROOT.rglob("*") if p.suffix in (".sh", ".py")]
       and all(_section(text, h).strip() for h in ("## 门序", "## 认领纪律", "## 记录纪律", "## 交接与等待"))
       and all(name in text for name in TOOL_CALL_NAMES)
       and 1 <= len(err_rows) <= 4,
       f"lines={len(text.splitlines())} refs={len(refs)} tpls={len(tpls)} "
       f"undiscoverable={undiscoverable} err_rows={len(err_rows)}")
    env_card = SKILL_ROOT / "templates" / "env-card.md"
    ok("p3_skill_text(15): 环境卡模板下沉到 templates/（正文不再内联）",
       env_card.is_file() and "- workspace: <项目根>" in env_card.read_text(encoding="utf-8")
       and "- workspace: <项目根>" not in text,
       f"exists={env_card.is_file()} inline={'- workspace: <项目根>' in text}")

    from agent_kanban.api.main import REST_ERROR_STATUS

    errors_text = (SKILL_ROOT / "references" / "errors.md").read_text(encoding="utf-8")
    not_listed = sorted(code for code in REST_ERROR_STATUS if code not in errors_text)
    ok("p3_skill_text(16): errors.md 覆盖服务端错误码全表（a10 下沉面）",
       not not_listed, str(not_listed))


def p3_skill_links():
    """a11：<skill_dir>/... 引用逐个存在 + skill --check 有判别力。"""
    refs: dict[str, set[str]] = {}
    for path in _md_files(SKILL_ROOT):
        refs[path.relative_to(SKILL_ROOT).as_posix()] = _refs(path.read_text(encoding="utf-8"))
    missing = [f"{rel} -> {ref}" for rel, want in refs.items() for ref in want
               if not (SKILL_ROOT / ref).is_file()]
    total = sum(len(want) for want in refs.values())
    ok("p3_skill_links(1): 树内 skill 自引用逐个存在（独立判据）",
       total >= 5 and not missing, f"total={total} missing={missing[:4]}")

    ok("p3_skill_links(2): <skill_dir> 语义写明＝加载目录绝对路径（SKILL.md 与 dispatch.md）",
       all(any("<skill_dir>" in line and "绝对路径" in line for line in
               (SKILL_ROOT / rel).read_text(encoding="utf-8").splitlines())
           for rel in ("SKILL.md", "references/dispatch.md")),
       str([rel for rel in ("SKILL.md", "references/dispatch.md")
            if not any("<skill_dir>" in ln and "绝对路径" in ln
                       for ln in (SKILL_ROOT / rel).read_text(encoding="utf-8").splitlines())]))

    tmp = Path(tempfile.mkdtemp(prefix="ak-links-"))
    wheel = _build_wheel(tmp / "dist")
    extract = _extract_wheel(wheel, tmp / "extract")
    env = _wheel_env(extract)

    checked = _run_py("import sys; from cli import main; sys.exit(main(['skill', '--check']))",
                      cwd=extract, env=env)
    ok("p3_skill_links(3): skill --check rc 0 且报出引用数",
       checked.returncode == 0 and re.search(rb"\d+", checked.stdout) is not None,
       f"rc={checked.returncode} out={checked.stdout.decode()[:120]!r} err={checked.stderr.decode()[:160]!r}")

    dest = tmp / "copy"
    _run_py("import sys; from cli import main; sys.exit(main(['skill', '--dest', sys.argv[1]]))",
            cwd=extract, env=env, args=[str(dest)])
    marker = dest / "agent-kanban" / "references" / "contract.md"
    marker.write_text(marker.read_text(encoding="utf-8") + "\n见 <skill_dir>/references/nope.md\n",
                      encoding="utf-8")
    broken = _run_py("import sys; from cli import main; sys.exit(main(['skill', '--check', sys.argv[1]]))",
                     cwd=extract, env=env, args=[str(dest)])
    ok("p3_skill_links(4): --check <dir> 能抓出注入的断链（非空转）",
       broken.returncode == 1 and b"nope.md" in broken.stderr,
       f"rc={broken.returncode} err={broken.stderr.decode()[:200]!r}")

    direct = _run_py("import sys; from cli import main; sys.exit(main(['skill', '--check', sys.argv[1]]))",
                     cwd=extract, env=env, args=[str(dest / "agent-kanban")])
    ok("p3_skill_links(5): --check 也可传 skill 目录本身（父目录与自身两种传法等价）",
       direct.returncode == 1 and b"nope.md" in direct.stderr,
       f"rc={direct.returncode} err={direct.stderr.decode()[:200]!r}")

    non_utf8 = tmp / "latin"
    shutil.copytree(dest / "agent-kanban", non_utf8 / "agent-kanban")
    (non_utf8 / "agent-kanban" / "references" / "errors.md").write_bytes(b"\xff\xfe\x00broken")
    mangled = _run_py("import sys; from cli import main; sys.exit(main(['skill', '--check', sys.argv[1]]))",
                      cwd=extract, env=env, args=[str(non_utf8)])
    ok("p3_skill_links(6): 非 UTF-8 的 .md 不让 --check 裸 traceback（报为问题）",
       mangled.returncode == 1 and b"Traceback" not in mangled.stderr
       and "UTF-8".encode() in mangled.stderr,
       f"rc={mangled.returncode} err={mangled.stderr.decode()[:200]!r}")

    absent = _run_py("import sys; from cli import main; sys.exit(main(['skill', '--check', sys.argv[1]]))",
                     cwd=extract, env=env, args=[str(tmp / "no-such-dir")])
    ok("p3_skill_links(7): --check 指向不存在目录 -> rc 1 + stderr 人话",
       absent.returncode == 1 and absent.stderr.strip() != b"" and b"Traceback" not in absent.stderr,
       f"rc={absent.returncode} err={absent.stderr.decode()[:160]!r}")
