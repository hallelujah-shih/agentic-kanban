FROM python:3.14-slim

WORKDIR /app

COPY pyproject.toml uv.lock cli.py alembic.ini README.md ./
COPY src ./src
COPY alembic ./alembic

# 双轨镜像源：默认国内轨（aliyun + 锁内 URL frozen sync，办公网零改动）；
# 海外 CI 传 --build-arg UV_DEPS_MODE=pip --build-arg UV_PIP_INDEX=https://pypi.org/simple/
COPY uv.toml /root/.config/uv/uv.toml

ARG UV_PIP_INDEX=https://mirrors.aliyun.com/pypi/simple/
ARG UV_PIP_TRUSTED_HOST=mirrors.aliyun.com
RUN pip install --no-cache-dir uv --index-url ${UV_PIP_INDEX} ${UV_PIP_TRUSTED_HOST:+--trusted-host ${UV_PIP_TRUSTED_HOST}}
ARG UV_DEPS_MODE=frozen
RUN if [ "$UV_DEPS_MODE" = "frozen" ]; then \
      uv sync --frozen; \
    else \
      uv export --locked --all-groups -o /deps-ci.txt \
      && uv venv \
      && UV_INDEX_URL=${UV_PIP_INDEX} uv pip install -r /deps-ci.txt; \
    fi

ENV AGENT_KANBAN_HOST=127.0.0.1
ENV AGENT_KANBAN_DB=/data/kanban.db

EXPOSE 8765

CMD ["/app/.venv/bin/python", "-m", "agent_kanban.api"]
