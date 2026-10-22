"""DB 基础设施：engine、connect 事件（FK/WAL/busy_timeout）、BEGIN IMMEDIATE、
0600 权限、seq 计数器、事务执行器（写失败重试 3 次 -> db_busy）。"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .errors import BusinessError

DEFAULT_DB = Path(os.environ.get("AGENT_KANBAN_DB") or (Path.home() / ".agent-kanban" / "kanban.db"))
MAX_ACTIVE_CLAIMS = 16
WRITE_RETRIES = 3


def lease_seconds() -> int:
    return int(os.environ.get("AGENT_KANBAN_LEASE_SECONDS", "7200"))


def idle_seconds() -> int:
    return int(os.environ.get("AGENT_KANBAN_IDLE_SECONDS", "1800"))


def busy_timeout_ms() -> int:
    return int(os.environ.get("AGENT_KANBAN_BUSY_TIMEOUT_MS", "5000"))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _chmod_0600(db_path: Path) -> None:
    for p in (db_path, Path(str(db_path) + "-wal"), Path(str(db_path) + "-shm")):
        try:
            if p.exists():
                os.chmod(p, 0o600)
        except OSError:
            pass


def make_engine(db_path: Path) -> AsyncEngine:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"timeout": busy_timeout_ms() / 1000},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={busy_timeout_ms()}")
        cursor.fetchall()
        cursor.close()
        _chmod_0600(db_path)

    @event.listens_for(engine.sync_engine, "begin")
    def _begin_immediate(conn):
        # 写锁先行（PRD 3.3）：所有事务以 BEGIN IMMEDIATE 开启，单写者保证
        # 校验与写入同提交点、seq 签发唯一。
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


class _Runtime:
    engine: AsyncEngine | None = None
    factory: async_sessionmaker[AsyncSession] | None = None
    schema_ready: bool = False


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """进程级单例 session factory（读 AGENT_KANBAN_DB）。"""
    if _Runtime.factory is None:
        _Runtime.engine = make_engine(Path(DEFAULT_DB))
        _Runtime.factory = async_sessionmaker(_Runtime.engine, expire_on_commit=False)
    assert _Runtime.factory is not None
    return _Runtime.factory


async def ensure_schema(factory: async_sessionmaker[AsyncSession]) -> None:
    """幂等建表 + seq 计数器种子。并发安全：先查 sqlite_master 再 create_all。"""
    if _Runtime.schema_ready:
        return
    from .models import Base

    engine = _Runtime.engine
    assert engine is not None
    async with engine.connect() as conn:
        names = set(
            (await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))).scalars().all()
        )
    if not {"requirements", "seq_counter"}.issubset(names):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        await session.execute(text("INSERT OR IGNORE INTO seq_counter (id, value) VALUES (1, 0)"))
        await session.commit()
    _Runtime.schema_ready = True


async def next_seq(session: AsyncSession) -> int:
    """全局单调 seq，同事务签发（BEGIN IMMEDIATE 单写者保证唯一）。"""
    res = await session.execute(text("UPDATE seq_counter SET value = value + 1 WHERE id = 1 RETURNING value"))
    return res.scalar_one()


def _is_locked(exc: OperationalError) -> bool:
    msg = str(exc).lower()
    return "database is locked" in msg or "database is busy" in msg


async def run_op(
    factory: async_sessionmaker[AsyncSession],
    op: Callable,
    *args: Any,
    is_write: bool = True,
    **kwargs: Any,
) -> Any:
    """单事务执行 op(session, ...)，BEGIN IMMEDIATE 自动生效；
    写失败（locked/busy）重试 3 次后抛 db_busy（PRD 7.3 #4）。"""
    await ensure_schema(factory)
    for attempt in range(WRITE_RETRIES + 1):
        try:
            async with factory() as session:
                result = await op(session, *args, **kwargs)
                await session.commit()
                return result
        except OperationalError as exc:
            if _is_locked(exc) and attempt < WRITE_RETRIES:
                continue
            if is_write and _is_locked(exc):
                raise BusinessError("db_busy", "sqlite write failed after 3 retries", None) from exc
            raise
