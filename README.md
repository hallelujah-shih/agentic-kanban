# Agentic Kanban

AI 时代的看板：不是任务状态跟踪，而是**大黑箱（AI 自动化执行）的关键节点暴露窗口 + 可回溯审计资产**。

## 文档地图

| 路径 | 内容 |
|---|---|
| `docs/PRD.md` | 需求规格 v3.2（当前权威，含反黑箱目标、状态机、MCP 契约、验收判据） |
| `docs/design.md` | 设计理由与决策过程（为何是记录面而非控制面） |
| `docs/mcp-config.md` | MCP 接入配置说明（opencode v2 / Claude Code / 通用客户端） |
| `skills/agent-kanban/` | 协同技能：告诉其他 agent 如何通过 MCP 认领/拆解/记录/交接 |
| `docs/adr/` | 决策与残余登记 |

## 一句话

需求从 Jira/手工进入看板；一个需求 = 一个 agent 认领执行；agent 通过 MCP 把拆解、里程碑、决策、风险、偏离结构化记录到看板；人通过看板的摘要视图判断"是否符合预期、是否偏离、是否有更好方案"，而不被原始输出淹没。

## 状态

草案。PRD v3.2 经双轴对抗审查 APPROVE-WITH-FIXES（剩余 P2 已折入）；候选工具裁决完成（`docs/adr/0001-reuse-vs-build.md`：自研为主 + agent-kanban-pm 移植种子）；Spike 前待验证骨架移植性（G7）。
