"""FastAPI app（M0-1.1 安全 + M0-1.3 错误映射 + /healthz 豁免 token + M1-1.1 MCP HTTP 挂载 /mcp）。

M1-1.1：Starlette Mount 剥前缀，streamable_http_app(streamable_http_path="/") 内层 Route 在 "/"
（审#P2-1）；host 传 config.host()（非 localhost 时 SDK DNS rebinding 保护自动关闭，token 为门，
不传则默认 127.0.0.1 保护在非 localhost 绑定下静默 421，审#P2-2）。
Mount 子 app 的 lifespan 不被 Starlette 执行，故 lifespan 显式跑 mcp_server.session_manager.run()。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .. import config
from ..db import ensure_schema, get_session_factory, run_op
from ..errors import BusinessError
from ..mcp.server import build_server
from ..services import reconcile as reconcile_svc
from .requirements import router

logger = logging.getLogger("agent_kanban.api")

# 错误映射（契约，审#7）：agent 面专用码无 REST 触发端点，保留作契约完整性
REST_ERROR_STATUS = {
    "not_found": 404,
    "illegal_state": 409,
    "lease_expired": 409,
    "invalid_record": 422,
    "db_busy": 503,
    "already_claimed": 409,
    "no_active_claim": 409,
    "duplicate_subtask": 409,
    "queue_full": 409,
}


def create_app() -> FastAPI:
    mcp_server = build_server()
    mcp_app = mcp_server.streamable_http_app(streamable_http_path="/", host=config.host())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # PRD §6 威胁模型 A/C：非 localhost 绑定必须带 token，否则启动拒绝+告警日志
        bind = config.host()
        if not config.is_localhost(bind) and not config.token():
            logger.warning("refusing to start: non-localhost bind (%s) requires AGENT_KANBAN_TOKEN", bind)
            raise RuntimeError(f"non-localhost bind ({bind}) requires AGENT_KANBAN_TOKEN")
        await ensure_schema()
        # 审#10：FastAPI lifespan 触发对账（重启对账，PRD 3.2/§6）；MCP server 启动不跑
        # （避免多进程事件噪音）。读扫描（WAL 快照）不抢写锁；有 finding/drift 才写事件。
        await run_op(get_session_factory(), reconcile_svc.reconcile, is_write=False)
        # Mount 子 app 的 lifespan 不执行：显式跑 MCP 会话管理器（session 内存管理与 idle 回收）
        async with mcp_server.session_manager.run():
            yield

    app = FastAPI(title="agent-kanban", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    app.mount("/mcp", mcp_app)

    @app.middleware("http")
    async def token_middleware(request: Request, call_next):
        if request.url.path == "/healthz":
            return await call_next(request)
        tok = config.token()
        if tok:
            header = request.headers.get("x-agent-kanban-token")
            query = request.query_params.get("token")
            if header != tok and query != tok:
                return JSONResponse(
                    status_code=401,
                    content={"code": "unauthorized", "message": "invalid or missing token", "task_id": None},
                )
        return await call_next(request)

    @app.exception_handler(BusinessError)
    async def business_error_handler(request: Request, exc: BusinessError):
        status = REST_ERROR_STATUS.get(exc.code, 500)
        return JSONResponse(status_code=status, content=exc.as_dict())

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"code": "invalid_record", "message": "request validation error", "task_id": None},
        )

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
