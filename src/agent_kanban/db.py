"""DB 基础设施：engine、connect 事件（FK/WAL/busy_timeout）、BEGIN IMMEDIATE、
0600 权限、seq 计数器、事务执行器（写失败重试 3 次 -> db_busy）。

读写拆分（G8 P2-5）：写引擎保留 begin 事件 BEGIN IMMEDIATE（PRD 3.3 写锁先行）；
读引擎 deferred 事务（WAL 快照，不抢写锁）。run_op 按 is_write 选工厂。
"""

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


def _make_engine(db_path: Path, *, immediate: bool) -> AsyncEngine:
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

    if immediate:
        @event.listens_for(engine.sync_engine, "begin")
        def _begin_immediate(conn):
            # 写锁先行（PRD 3.3）：写事务以 BEGIN IMMEDIATE 开启，单写者保证
            # 校验与写入同提交点、seq 签发唯一。读引擎不挂此事件（WAL 快照）。
            conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


class _Runtime:
    write_engine: AsyncEngine | None = None
    read_engine: AsyncEngine | None = None
    factory: async_sessionmaker[AsyncSession] | None = None
    read_factory: async_sessionmaker[AsyncSession] | None = None
    schema_ready: bool = False


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """写工厂（BEGIN IMMEDIATE）。进程级单例（读 AGENT_KANBAN_DB）。"""
    if _Runtime.factory is None:
        _Runtime.write_engine = _make_engine(Path(DEFAULT_DB), immediate=True)
        _Runtime.factory = async_sessionmaker(_Runtime.write_engine, expire_on_commit=False)
    assert _Runtime.factory is not None
    return _Runtime.factory


def get_read_session_factory() -> async_sessionmaker[AsyncSession]:
    """读工厂（deferred 事务，WAL 快照不抢写锁）。"""
    if _Runtime.read_factory is None:
        _Runtime.read_engine = _make_engine(Path(DEFAULT_DB), immediate=False)
        _Runtime.read_factory = async_sessionmaker(_Runtime.read_engine, expire_on_commit=False)
    assert _Runtime.read_factory is not None
    return _Runtime.read_factory


async def ensure_schema() -> None:
    """幂等建表 + seq 计数器种子。并发安全：先查 sqlite_master 再 create_all；
    仅缺失时才写（读路径在持锁场景下不触发写）。只读检查走读引擎（deferred，
    不抢写锁），建表/种子走写引擎。"""
    if _Runtime.schema_ready:
        return
    from .models import Base

    read_eng = _Runtime.read_engine
    if read_eng is None:
        get_read_session_factory()
        read_eng = _Runtime.read_engine
    assert read_eng is not None
    async with read_eng.connect() as conn:
        names = set(
            (await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))).scalars().all()
        )
    if not {"requirements", "seq_counter"}.issubset(names):
        write_eng = _Runtime.write_engine
        if write_eng is None:
            get_session_factory()
            write_eng = _Runtime.write_engine
        assert write_eng is not None
        async with write_eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    async with read_eng.connect() as conn:
        has_seq = (await conn.execute(text("SELECT COUNT(*) FROM seq_counter WHERE id=1"))).scalar_one()
    if not has_seq:
        async with get_session_factory()() as session:
            await session.execute(text("INSERT OR IGNORE INTO seq_counter (id, value) VALUES (1, 0)"))
            await session.commit()
    await heal_null_text_markers()
    _Runtime.schema_ready = True


async def heal_null_text_markers() -> int:
    # 真实 marker 恒为 JSON 对象文本，4 字节 `null` 只可能来自旧编码清除
    async with get_read_session_factory()() as session:
        n = (await session.execute(
            text("SELECT COUNT(*) FROM requirements WHERE awaiting_human = 'null'")
        )).scalar_one()
    if not n:
        return 0
    async with get_session_factory()() as session:
        res = await session.execute(
            text("UPDATE requirements SET awaiting_human = NULL WHERE awaiting_human = 'null'")
        )
        await session.commit()
        return res.rowcount


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
    """单事务执行 op(session, ...)。写：BEGIN IMMEDIATE（写锁先行）；读：deferred（WAL 快照）。
    失败（locked/busy）重试 3 次后抛 db_busy（PRD 7.3 #4；读路径同样映射，不裸抛）。"""
    await ensure_schema()
    target = factory if is_write else get_read_session_factory()
    for attempt in range(WRITE_RETRIES + 1):
        try:
            async with target() as session:
                result = await op(session, *args, **kwargs)
                await session.commit()
                return result
        except OperationalError as exc:
            if _is_locked(exc) and attempt < WRITE_RETRIES:
                continue
            if _is_locked(exc):
                raise BusinessError("db_busy", "sqlite database is locked after retries", None) from exc
            raise
