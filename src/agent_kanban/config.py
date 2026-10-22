"""运行配置（PRD §6 安全）：HOST/TOKEN/DB 全走 env，默认 localhost 绑定。

- 默认绑定 127.0.0.1（威胁模型 A/C 闭合）；非 localhost 绑定必须带 token（启动拒绝见 api/main.py lifespan）。
- DB 与 db.py 的 AGENT_KANBAN_DB 同源。
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def host() -> str:
    return os.environ.get("AGENT_KANBAN_HOST", DEFAULT_HOST)


def port() -> int:
    return int(os.environ.get("AGENT_KANBAN_PORT", str(DEFAULT_PORT)))


def token() -> str | None:
    t = os.environ.get("AGENT_KANBAN_TOKEN")
    return t if t else None


def db_path() -> Path:
    return Path(os.environ.get("AGENT_KANBAN_DB") or (Path.home() / ".agent-kanban" / "kanban.db"))


def is_localhost(hostname: str) -> bool:
    return hostname in ("127.0.0.1", "localhost", "::1")
