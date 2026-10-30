# 客户端适配：OpenCode

本文件是**某一客户端的具体化**，非协议必需。换客户端时按同样形状替换本节即可。

## skill 落点

- 项目级：`<项目>/.opencode/skills/agent-kanban/`（兼容 `<项目>/.agents/skills/agent-kanban/`）
- 全局：`~/.config/opencode/skills/agent-kanban/`
- 取出：`agent-kanban skill --dest <上述父目录>`（例如 `agent-kanban skill --dest ~/.config/opencode/skills`）

## MCP 注册

项目级 `opencode.json`，或全局 `~/.config/opencode/opencode.jsonc`（跨目录派发用全局注册）：

```jsonc
{
  "mcp": {
    "kanban": {
      "type": "local",
      "command": ["/path/to/agent-kanban", "mcp"],
      "environment": { "AGENT_KANBAN_DB": "/home/<user>/.agent-kanban/kanban.db" }
    }
  }
}
```

server 名决定工具前缀（`kanban` -> `kanban_list_tasks`）；名字换成别的，前缀随之变。注册后 `opencode mcp list` 应显示 connected。

## 派发

```sh
agent-kanban dispatch --requirement-id <需求 id> [--model <provider/model>] [--dir <目录>] [--budget <秒|h/m/s>] [--bg]
```

- `--budget`：同步等待的墙钟预算；超时不杀会话，输出带续跑提示。
- `--bg`：投递后立即返回，由后台子进程心跳续租（周期＝环境变量 `AGENT_KANBAN_DISPATCH_HEARTBEAT_SEC`，默认 60s），终态写一条板 note。
- 派发输出含 session id 与 directory 两个顶层字段——**深挖 worker 现场＝`cd <directory>` + `opencode -s <session id>`**（缺一即交接不完整）。

## 续跑

```sh
agent-kanban resume --requirement-id <需求 id 或 ses_req_<8hex>> ["<指令>"] [--model <provider/model>]
```

恢复 / 返工 / 换模型统一入口，不限需求状态，缺省预算 1h。

## 手工恢复会话

```sh
cd <directory>
opencode run -s <session id>                 # 带完整上下文续跑
opencode run -s <session id> -m <provider/model>   # 换模型续跑
```

## 会话 id

- 子会话形如 `ses_req_<8hex>`（派发入口派生）；普通会话形如 `ses_<随机串>`。
- 恢复锚（板 note）里写全：会话 id + 模型 + 恢复命令，三者齐才能续回同一会话。

## 模型继承

派发或续跑都显式带模型（`--model provider/model`，把 provider/model 换成实际值），继承开工时的模型；不显式指定会落回客户端默认模型（默认套餐额度可能见底，产出质量会掉）。

## 本机约定

本机（作者环境）另有目录分区与临时目录政策，见 <skill_dir>/references/project-conventions.md。
