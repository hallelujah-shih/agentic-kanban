# ADR 0005 - M1 方向裁决：MCP HTTP 做、Web 窗口必须、报告纪律

状态: 已定（user 裁决）
日期: 2026-10-22
关联: PRD §0 / §4.1 / §8 / §11；design.md §7；ADR 0003（M0 决策，其中「MCP HTTP = 不做」本 ADR 反转）；ADR 0004（单一事件源）

## 背景

user 三项裁决：1) HTTP 的 MCP 一起实现；2) Web 窗口是必须的——AI 与人之间最重要的信息沟通渠道；3) SKILL 明确报告纪律——详情要简约、不要像写论文、大白话、无黑话、考虑人脑带宽极限、合理的报告里程碑和关键事件很重要。

## 决策

1. **MCP HTTP 做**（反转 ADR 0003「MCP HTTP 形态: 不做」）：mcp 2.3.0 支持 `MCPServer.streamable_http_app()`（返回 Starlette app），挂载进现有 FastAPI（路径 `/mcp`），与 stdio 并存（stdio = 本地 agent 默认，HTTP = 网络/远程场景）；同一套 12 工具注册表；安全与 REST 一致（localhost 默认 + token 中间件覆盖）。测试用真实 streamable-http 客户端。
2. **Web 窗口必须**：AI 与人之间最重要的信息沟通渠道。M1 主交付，范围：反淹没默认列表视图（看板）+ 需求深潜视图 + 人面操作（approve/release/renew/note/abandon/reopen/set_expectations）+ 事件推送（SSE，agent 动作实时可见）；无原始输出（反淹没结构）。
3. **报告纪律（agent 侧）**：写给人看的每一段文字必须简约、大白话、无黑话，尊重人脑带宽；报告里程碑与关键事件（节点），不报过程流水账。写入 SKILL.md「报告纪律」节 + PRD §0 原则。

## 理由

- MCP HTTP：stdio 只覆盖本地进程；HTTP 使 agent 面在单机网络可达，且 Web 窗口（决策 2）与远程 agent 场景共用同一 HTTP 面，收敛端口/中间件。
- Web 必须：反黑箱的落点是「人看什么」——终端/静态 HTML 不是合格的沟通渠道；Web 窗口是人与 agent 协作的默认界面。
- 报告纪律：反淹没管视图展示什么，本纪律管 agent 写进记录的是什么——两者互补，缺后者则记录面仍会被论文式文本淹没。

## 影响

- PRD：§0 新增「报告纪律」原则、§4.1 双 transport 说明、§8 M1 行（Web 窗口 + MCP HTTP）、§11 未决表（MCP HTTP 已裁决）。
- SKILL.md：新增「报告纪律」节。
- 实现批次：M1-1 = HTTP MCP（全六门）；M1-2 = Web 窗口（全六门）。G3 基线采集仍为 AC14 硬前置（user 侧）。
