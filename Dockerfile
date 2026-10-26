FROM python:3.14-slim

WORKDIR /app

COPY pyproject.toml uv.lock cli.py alembic.ini README.md ./
COPY src ./src
COPY alembic ./alembic

# 与宿主 uv.toml 同源：内网 PyPI 镜像（mirrors.aliyun.com 解析到 internal-proxy 代理，
# internal CA 签发证书），uv/pip 对该 host 跳过证书校验（allow-insecure-host）
ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

RUN pip install --no-cache-dir uv --index-url https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
RUN uv sync --frozen --allow-insecure-host mirrors.aliyun.com

ENV AGENT_KANBAN_HOST=0.0.0.0
ENV AGENT_KANBAN_DB=/data/kanban.db

EXPOSE 8765

CMD ["/app/.venv/bin/python", "-m", "agent_kanban.api"]
