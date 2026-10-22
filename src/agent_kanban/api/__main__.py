"""`python -m agent_kanban.api` 入口：真实 uvicorn 子进程（harness 用，PRD 7.1 FastAPI）。"""

from __future__ import annotations

import uvicorn

from .. import config
from .main import app


def main() -> None:
    uvicorn.run(app, host=config.host(), port=config.port(), access_log=False)


if __name__ == "__main__":
    main()
