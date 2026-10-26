# ADR 0000 - 已知残余登记

位置: docs/adr/0000-known-gaps.md
关联: docs/PRD.md 第 10 节
声明三档: ①测试背书 ②登记残余 + 升级路径 ③纯预期

| 编号 | 残余 | 档位 | 升级路径 | 生效点 |
|---|---|---|---|---|
| G1 | 本机 shell 可直接写 SQLite，污染审计链 | ② | 文档声明边界；未来 DB 文件只读 + 单写进程 | 文档生效起 |
| G2 | 偏离/验收自评的真实性不可完全验证（agent 造假） | ② | 结构强制（decision 必含 alternatives、验收自评表）+ 派生偏离信号（不依赖自愿登记）+ 人抽查 | PRD v3.2 生效起 |
| G3 | 痛点基线未采集 | ③ | 试用包已备好（docs/ops/g3-trial/：协议 + 基线周日志模板 + 试用周记分卡 + 周中检查点）；待 user 跑第 0 周（基线）+ 第 1 周（N>=5 真实需求三问打分），基线回来定反淹没阈值 + AC14 判定 | 采集完成起 |
| G4 | MCP SDK 2.x 选型（版本锁定、stdio、鉴权模型）未登记 ADR | ② | 已闭合：登记 docs/adr/0002-mcp-sdk.md（mcp>=2.3,<3、MCPServer 替代 fastmcp、stdio、无 token 鉴权模型） | 2026-10-22 闭合 |
| G5 | 性能目标无基准 | ③ | 已闭合：tests/bench.py 基准落地（5k 库测 summary/write/board，PRD §6 summary<200ms/write<50ms 达标；board 超预算后批查询优化 ~20x 达标），结果 docs/ops/bench-results.md | 2026-10-23 闭合 |
| G6 | 候选工具未调研，自研依据未闭合 | ② | 已裁决：无候选满足合取，自研为主 + agent-kanban-pm 为移植种子（docs/adr/0001-reuse-vs-build.md） | ADR 0001 生效起（已闭合） |
| G7 | agent-kanban-pm 骨架（认领/租约/角色门控 MCP/append-only）移植性未经真机验证 | ② | 已闭合：Spike 真机验证（2026-10-22），命中 3/4 偏差触发（认领非 DB 排他 / claim 非单事务 / agent 面可释放置终态）；移植边界收窄并登记于 docs/adr/0001-reuse-vs-build.md「G7 Spike 验证」，证据 docs/ops/spike-g7.md | 2026-10-22 闭合 |

| G8 | Spike 结果盲审登记的 M0 缺口：REOPEN 边无接口可达（PRD 3.1 vs 4.2）；abandon 于 CLAIMED 的认领处置未规定；读事务 BEGIN IMMEDIATE 锁竞争下非结构化读错；export LIMIT 200 截断 | ② | 已闭合：P2-2 reopen 命令+端点、P2-3 abandon 同事务置 ended_at、P2-4 export 全量无 LIMIT、P2-5 读写 sessionmaker 拆分，均在 M0-1 完成（裁决登记 docs/adr/0003-m0-decisions.md「G8 闭合」） | 2026-10-22 闭合 |
| G9 | 数据保留清理命令（12 个月窗口 + 清理前导出）+ 重试成本超限判定（PRD 3.2「累计重试超 2 次等你决策」语义需澄清） | ② | G9-a（清理命令）已闭合：M1-3.3 prune CLI（终态需求级原子窗口，docs/adr/0006-m1-3-decisions.md）；G9-b（重试超限判定）已闭合：M1-4 实现（系统派生计数 + 需求级跨子任务累计 + 幂等 risk 事件 + retry_limit 派生信号，判定源 user 裁决，BCD docs/business-contracts/g9b-retry-limit.md，验证 docs/ops/m1-4-verification.md） | G9-a 2026-10-23 闭合；G9-b 2026-10-23 闭合（M1-4） |
| G10 | activity 口径既有偏差：PRD 3.2「读写任一计活动」vs 实现仅写操作更新 last_activity_at（读工具不 touch） | ② | 已裁决：维持写口径 + 静默读意图内声明 + 连接级模型不引入（docs/adr/0006-m1-3-decisions.md；PRD §3.2 activity 行澄清 + renew 触活例外） | 2026-10-23 闭合 |
| G11 | `agent-kanban` 入口快照陈旧：cli.py 经 force-include 以快照复制进 site-packages（editable 只覆盖 agent_kanban 包），改 cli.py 后 `uv sync` 不刷新快照，入口脚本继续跑旧代码（harness 走 `python cli.py` 文件直跑，结构性测不到） | ② | 2026-10-23 dogfood 验收命中并当场处置（`uv sync --reinstall-package agent-kanban` 刷新，411/411 复验）；纪律：凡合并涉及 cli.py 的变更，合入后必须跑该命令刷新；升级路径：harness 增加入口脚本冒烟用例，或打包改为 cli 可编辑 | 2026-10-23 登记 |
| R1 | agent harness 对 delete 后 not_found 的处理在本仓之外（opencode 会话层）：可能误判系统故障重试/上报 | ② | 错误码语义（not_found 含 requirement id）+ README/docs 写明"任务被删除属人面操作结果"；harness k_delete 断言 agent 面 not_found；残余接受 | 2026-10-26 登记（task-lifecycle spec §13） |
| R3 | archive/abandon 语义区分靠使用纪律（人可能用 archive 替代 abandon 让任务消失），非结构强制 | ② | agent 面无 archive 工具（结构性半边）；PRD §0/§4.2 措辞 + UI 语义提示；人工定期观察 archive/abandon 比例（单用户规模不做自动化告警） | 2026-10-26 登记（BCD F1） |
| R4 | 决策操作移 CLI 后 awaiting 堆积风险（人习惯点按钮，发现无入口） | ② | 深潜页/卡片等待人横幅静态 CLI 提示 + web.md 人面 surface 速查；残余：习惯迁移靠使用 | 2026-10-26 登记（BCD F3） |
| G12 | list_awaiting 放行已清 marker 任务（**既有缺陷，非 M1-5 引入**）：`awaiting_human` JSON 列 none_as_null=False，清 marker 存文本 "null"，SQL 谓词 `IS NOT NULL`（operations.py:918）匹配该文本 -> approve/abandon/archive on BLOCKED 后任务仍出现在 list_awaiting（awaiting_human=null）；detail/board 可见面不受影响（反序列化归一 None）。复现: claim -> mark_blocked -> approve -> MCP list_awaiting。修复选项（未裁决，单独立项）: ① JSON(none_as_null=True) + 存量 "null" 行迁移；② 谓词补 `isnot("null")`（无迁移但 pin 编码） | ② | 已修复（2026-10-26，g12-list-awaiting 分支；根治=none_as_null=True+启动自愈回填，user 裁决） | 2026-10-26 登记（M1-5 T2 域外发现，主循环复验坐实） |

登记规则：新增残余必须同时写明档位与生效点；档位 ③ 冒充 ① 或 ② 视为虚标，审查照报。
