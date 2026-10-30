#!/usr/bin/env bash
# a6 空目录验收：只靠 pip 包 + 取出的 skill 树，在与本仓无关的空目录里部署并连上看板。
#
# 用法: bash tests/manual/a6-empty-dir.sh <工作目录> <wheel 路径>
# 产物与 DB 全在 <工作目录> 下；需要 uv 与 Python 3.14（可离线用本机 uv 缓存）。
set -euo pipefail

WORK=${1:?工作目录}
WHEEL=${2:?wheel 路径}

rm -rf "$WORK"
mkdir -p "$WORK"
cd "$WORK"

echo "== 0. 空目录（与本仓无关）: $WORK（现有条目 $(ls -A | wc -l) 个）"

echo "== 1. 装包 + 建 DB（首次命令自动建表）"
uv venv --python 3.14 .venv >/dev/null
uv pip install --python .venv/bin/python --offline "$WHEEL" >/dev/null
.venv/bin/agent-kanban --version
export AGENT_KANBAN_DB="$WORK/kanban.db"
.venv/bin/agent-kanban new --title "a6 空目录验收" --description "workspace=$WORK" >/dev/null
stat -c 'DB %a %n' "$AGENT_KANBAN_DB"

echo "== 2. 落 skill 树并自检"
.venv/bin/agent-kanban skill --dest .opencode/skills
find .opencode/skills/agent-kanban -type f | sort
.venv/bin/agent-kanban skill --check .opencode/skills

echo "== 3. 连上看板（MCP stdio list_tasks）"
AGENT_KANBAN_DB="$AGENT_KANBAN_DB" .venv/bin/python - <<'PY'
import json, os, subprocess, sys

proc = subprocess.Popen(
    ["./.venv/bin/agent-kanban", "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    stderr=subprocess.PIPE, text=True, bufsize=1, env=dict(os.environ),
)

def send(msg):
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()

def recv(want_id):
    while True:
        line = proc.stdout.readline()
        if not line:
            sys.exit(f"server closed: {proc.stderr.read()}")
        msg = json.loads(line)
        if msg.get("id") == want_id:
            return msg

send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
      "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                 "clientInfo": {"name": "a6", "version": "0"}}})
recv(1)
send({"jsonrpc": "2.0", "method": "notifications/initialized"})
send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
      "params": {"name": "list_tasks", "arguments": {}}})
res = recv(2)
proc.stdin.close()
proc.wait(timeout=10)
text = res["result"]["content"][0]["text"]
tasks = json.loads(text)["tasks"]
print(f"list_tasks -> {len(tasks)} 条: {tasks[0]['title']} / {tasks[0]['state']}")
PY

echo "== 4. 全程未读本仓"
git -C "$WORK" status --porcelain 2>/dev/null || echo "（空目录不是 git 仓，符合预期）"
