# ADR 0000 - 已知残余登记

位置: docs/adr/0000-known-gaps.md
关联: docs/PRD.md 第 10 节
声明三档: ①测试背书 ②登记残余 + 升级路径 ③纯预期

| 编号 | 残余 | 档位 | 升级路径 | 生效点 |
|---|---|---|---|---|
| G1 | 本机 shell 可直接写 SQLite，污染审计链 | ② | 文档声明边界；未来 DB 文件只读 + 单写进程 | 文档生效起 |
| G2 | 偏离/验收自评的真实性不可完全验证（agent 造假） | ② | 结构强制（decision 必含 alternatives、验收自评表）+ 派生偏离信号（不依赖自愿登记）+ 人抽查 | PRD v3.2 生效起 |
| G3 | 痛点基线未采集 | ③ | M0 前一周手工日志；M1 试用协议硬前置 | 采集完成起 |
| G4 | MCP SDK 2.x 选型（版本锁定、stdio、鉴权模型）未登记 ADR | ② | 已闭合：登记 docs/adr/0002-mcp-sdk.md（mcp>=2.3,<3、MCPServer 替代 fastmcp、stdio、无 token 鉴权模型） | 2026-10-22 闭合 |
| G5 | 性能目标无基准 | ③ | 已闭合：tests/bench.py 基准落地（5k 库测 summary/write/board，PRD §6 summary<200ms/write<50ms 达标；board 超预算后批查询优化 ~20x 达标），结果 docs/ops/bench-results.md | 2026-10-23 闭合 |
| G6 | 候选工具未调研，自研依据未闭合 | ② | 已裁决：无候选满足合取，自研为主 + agent-kanban-pm 为移植种子（docs/adr/0001-reuse-vs-build.md） | ADR 0001 生效起（已闭合） |
| G7 | agent-kanban-pm 骨架（认领/租约/角色门控 MCP/append-only）移植性未经真机验证 | ② | 已闭合：Spike 真机验证（2026-10-22），命中 3/4 偏差触发（认领非 DB 排他 / claim 非单事务 / agent 面可释放置终态）；移植边界收窄并登记于 docs/adr/0001-reuse-vs-build.md「G7 Spike 验证」，证据 docs/ops/spike-g7.md | 2026-10-22 闭合 |

| G8 | Spike 结果盲审登记的 M0 缺口：REOPEN 边无接口可达（PRD 3.1 vs 4.2）；abandon 于 CLAIMED 的认领处置未规定；读事务 BEGIN IMMEDIATE 锁竞争下非结构化读错；export LIMIT 200 截断 | ② | 已闭合：P2-2 reopen 命令+端点、P2-3 abandon 同事务置 ended_at、P2-4 export 全量无 LIMIT、P2-5 读写 sessionmaker 拆分，均在 M0-1 完成（裁决登记 docs/adr/0003-m0-decisions.md「G8 闭合」） | 2026-10-22 闭合 |
| G9 | 数据保留清理命令（12 个月窗口 + 清理前导出）+ 重试成本超限判定（PRD 3.2「累计重试超 2 次等你决策」语义需澄清） | ② | G9-a（清理命令）已闭合：M1-3.3 prune CLI（终态需求级原子窗口，docs/adr/0006-m1-3-decisions.md）；G9-b（重试超限判定）拆 M1-4 BCD（基于规则的派生状态系统，判定源已由 user 裁决：系统派生计数） | G9-a 2026-10-23 闭合；G9-b M1-4 |
| G10 | activity 口径既有偏差：PRD 3.2「读写任一计活动」vs 实现仅写操作更新 last_activity_at（读工具不 touch） | ② | 已裁决：维持写口径 + 静默读意图内声明 + 连接级模型不引入（docs/adr/0006-m1-3-decisions.md；PRD §3.2 activity 行澄清 + renew 触活例外） | 2026-10-23 闭合 |

登记规则：新增残余必须同时写明档位与生效点；档位 ③ 冒充 ① 或 ② 视为虚标，审查照报。
