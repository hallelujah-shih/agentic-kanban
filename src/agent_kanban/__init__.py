"""Agentic Kanban — 记录面 + 关键决策的记录点/审计点。"""

__version__ = "0.1.0"

# 契约版本：与 docs/PRD.md 首行版本、skills/agent-kanban/SKILL.md frontmatter
# contract-version 同一值（一致性由 AC p3_skill_text 断言）。skill 与 MCP 是否漂移
# 靠比较已装 skill 文件的该字段与 `agent-kanban --version` 输出判断。
CONTRACT_VERSION = "3.2"
