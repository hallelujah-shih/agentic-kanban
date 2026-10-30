"""skill 树解析与自引用断链检查的单点（cli 与 dispatch 共用）。

`dispatch` 顶层不能 import `cli`（`cli.py` 顶层已 import dispatch，必成环），故解析逻辑放这里。
解析顺序：wheel 包内资源 `agent_kanban/data/skill/SKILL.md` -> 源码树回退（限 3 层祖先，
editable 安装不携带 data/ 目录）-> FileNotFoundError。
"""

from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path

SOURCE_FALLBACK_DEPTH = 3
SKILL_PKG_NAME = "agent-kanban"

# 引用形态：<skill_dir>/references/x.md、references/a/b.md、带 #anchor、通配（通配必判缺，
# 逼作者写实名）；前导 / 与 anchor 在归一化时剥掉。大小写不敏感（REFERENCES/ 也算）。
REF_RE = re.compile(
    r"(?:(?:<skill_dir>)?/)?(?:references|templates)/[A-Za-z0-9_./*-]+\.md"
    r"(?:#[^\s，。；：、」』)>`|]*)?",
    re.IGNORECASE,
)
_TRAILING = "，。；：、」』)>`|"


def skill_dir() -> Path:
    """skill 树根目录（含 SKILL.md / references/ / templates/）。"""
    packaged = files("agent_kanban") / "data" / "skill" / "SKILL.md"
    if packaged.is_file():
        return Path(str(packaged)).parent
    import agent_kanban

    anchor = Path(agent_kanban.__file__).resolve()
    for depth, parent in enumerate(anchor.parents):
        if depth > SOURCE_FALLBACK_DEPTH:
            break
        candidate = parent / "skills" / SKILL_PKG_NAME / "SKILL.md"
        if candidate.is_file():
            return candidate.parent
    raise FileNotFoundError(
        "找不到 skill 树（editable 安装不携带它）：改用 `python cli.py skill ...`，或安装构建好的 wheel"
    )


def skill_file() -> Path:
    """SKILL.md 路径（`skill --print` 与派发稿协议入口共用）。"""
    return skill_dir() / "SKILL.md"


def resolve_check_root(base: Path) -> Path:
    """`skill --check <目录>` 的根：既接受 `--dest` 的父目录，也接受取出的 skill 目录本身。"""
    if (base / SKILL_PKG_NAME).is_dir():
        return base / SKILL_PKG_NAME
    if (base / "SKILL.md").is_file():
        return base
    return base / SKILL_PKG_NAME


def normalize_ref(matched: str) -> str:
    cand = matched.replace("<skill_dir>", "").lstrip("/")
    return re.split(r"#", cand, 1)[0].rstrip(_TRAILING)


def refs_in(text: str) -> set[str]:
    return {normalize_ref(m.group(0)) for m in REF_RE.finditer(text)}


def check_links(root: Path) -> tuple[int, list[str]]:
    """扫 root 下全部 .md，逐个判 `references/` `templates/` 引用是否存在。

    返回（引用总数，问题清单）。问题清单同时承载断链与非 UTF-8 读不动的文件
    （后者不能静默跳过：跳过等于让 `--check` 空转绿）。
    """
    total, problems = 0, []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            problems.append(f"{rel} -> 不是 UTF-8 文本，无法解析引用")
            continue
        for ref in refs_in(text):
            total += 1
            if not (root / ref).is_file():
                problems.append(f"{rel} -> {ref}")
    return total, problems
