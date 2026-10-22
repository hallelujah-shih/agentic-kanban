"""Alembic 环境（PRD 7.3 #8：sync engine，async 需 run_sync 包装，故直用 sync）。

URL 优先取 AGENT_KANBAN_DB（与应用同源），否则 ~/.agent-kanban/kanban.db。
target_metadata = models.Base.metadata（autogenerate 源）。
"""

from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

from agent_kanban.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

db_env = os.environ.get("AGENT_KANBAN_DB") or str(Path.home() / ".agent-kanban" / "kanban.db")
config.set_main_option("sqlalchemy.url", f"sqlite:///{db_env}")

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
