"""ORM 模型与 DB 约束（PRD §2 逐字；partial unique index 用 sqlite_where；
UUID 存 32 位无连字符 hex；ts/seq 服务端签发）。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

UUIDHex = sa.Uuid(as_uuid=False)


def new_id() -> str:
    return uuid.uuid4().hex


class UTCDateTime(sa.TypeDecorator[datetime]):
    """SQLite DateTime 往返丢 tzinfo（实测）——存储 UTC naive，读回附 tz。"""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: Any, dialect) -> Any:
        if isinstance(value, datetime):
            if value.tzinfo is not None:
                return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value: Any, dialect) -> Any:
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class Base(DeclarativeBase):
    pass


class Requirement(Base):
    __tablename__ = "requirements"

    id: Mapped[str] = mapped_column(UUIDHex, primary_key=True, default=new_id)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")  # jira | manual
    source_ref: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    acceptance: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # 人写预期验收锚
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    awaiting_human: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)  # {reason, evidence, since, kind}
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(UUIDHex, primary_key=True, default=new_id)
    requirement_id: Mapped[str] = mapped_column(
        UUIDHex, ForeignKey("requirements.id"), nullable=False
    )
    agent_name: Mapped[str] = mapped_column(String(255), nullable=False)  # 声明
    agent_conn: Mapped[str | None] = mapped_column(String(255))  # 观测
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    release_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        # 认领排他（PRD 7.3 #9：partial unique index 用 sqlite_where）
        Index("uq_claims_active_requirement", "requirement_id", unique=True, sqlite_where=text("ended_at IS NULL")),
        Index("ix_claims_requirement", "requirement_id"),
    )


class Milestone(Base):
    __tablename__ = "milestones"

    id: Mapped[str] = mapped_column(UUIDHex, primary_key=True, default=new_id)
    requirement_id: Mapped[str] = mapped_column(
        UUIDHex, ForeignKey("requirements.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    planned_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    actual_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="planned")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    __table_args__ = (Index("ix_milestones_requirement", "requirement_id"),)


class Subtask(Base):
    __tablename__ = "subtasks"

    id: Mapped[str] = mapped_column(UUIDHex, primary_key=True, default=new_id)
    requirement_id: Mapped[str] = mapped_column(
        UUIDHex, ForeignKey("requirements.id"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)  # 归一后存储（trim+casefold+空白折叠）
    acceptance: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="todo")
    milestone_id: Mapped[str | None] = mapped_column(
        UUIDHex, ForeignKey("milestones.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("requirement_id", "title", name="uq_subtasks_requirement_title"),
        UniqueConstraint("requirement_id", "ordinal", name="uq_subtasks_requirement_ordinal"),
        Index("ix_subtasks_requirement", "requirement_id"),
    )


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(UUIDHex, primary_key=True, default=new_id)
    requirement_id: Mapped[str] = mapped_column(
        UUIDHex, ForeignKey("requirements.id"), nullable=False
    )
    claim_id: Mapped[str | None] = mapped_column(UUIDHex, ForeignKey("claims.id"), nullable=True)
    subtask_id: Mapped[str | None] = mapped_column(UUIDHex, ForeignKey("subtasks.id"), nullable=True)
    milestone_id: Mapped[str | None] = mapped_column(UUIDHex, ForeignKey("milestones.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    actor_surface: Mapped[str] = mapped_column(String(16), nullable=False)  # mcp | cli | system
    actor_conn: Mapped[str | None] = mapped_column(String(255))
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    __table_args__ = (
        # seq 全局单调服务端签发；UNIQUE(requirement_id, seq) 作每需求排序索引（冗余无害）
        UniqueConstraint("requirement_id", "seq", name="uq_events_requirement_seq"),
        Index("ix_events_requirement", "requirement_id"),
    )


class SeqCounter(Base):
    __tablename__ = "seq_counter"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
