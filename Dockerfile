FROM python:3.14-slim

WORKDIR /app

COPY pyproject.toml uv.lock cli.py alembic.ini README.md ./
COPY src ./src
COPY alembic ./alembic

# 内网 PyPI 镜像 + allow-insecure-host 与宿主 uv 配置同源（镜像源证书不可验证，uv.toml 已声明）
COPY uv.toml /root/.config/uv/uv.toml

RUN pip install --no-cache-dir uv --index-url https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
RUN uv sync --frozen

ENV AGENT_KANBAN_HOST=127.0.0.1
ENV AGENT_KANBAN_DB=/data/kanban.db

EXPOSE 8765

CMD ["/app/.venv/bin/python", "-m", "agent_kanban.api"]
