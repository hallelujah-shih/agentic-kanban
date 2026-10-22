# M0 Plan — 人面 REST + 视图 + 导出 + 对账 + 派生偏离（AC10-13/15/17）

分支: `m0`（worktree `.worktree/m0/`，基分支 main @ 7447950）
档位: M0-1 全六门（D 对外契约/REST API + ①export 工件格式 + ②新信任边界 HTTP + 新测试语义）；M0-2 全六门（③reconcile 周期扫描 + 新测试语义 AC10）
规范锚: docs/PRD.md v3.2（commit 7447950）；Spike 已绿 AC1-9/16（docs/ops/spike-verification.md）
依赖实测: fastapi 0.158.2 / alembic 1.20.0 / uvicorn（本 worktree .venv 已装）；sqlalchemy 2.1.6 / aiosqlite 0.22.1 / mcp 2.3.0 / python 3.14.4
本 plan 为 M0 单一契约，覆盖两个串行子批（M0-1 基础+人面 REST+视图+导出；M0-2 reconcile+AC10+裁决登记）；各子批独立实现派发 + 独立结果盲审，验证后各自 ff 合入 main（user 已授权自合）。

## 契约三锚

1. 规范逐字原文: PRD §4.2（人面 CLI/REST 语义）、§5.1（归属）、§5.3（视图原则：摘要/深潜/反淹没/覆盖下界/派生偏离）、§5.4（回溯 5 判据）、§6（NFR：安全/可观测/可靠性/数据量级）、§7.1-7.3（架构与契约级要点：Alembic sync engine、REST 与 MCP 共用 state_machine、写保护 service 统一）、§8（M0 里程碑）、§9（AC10-13/15/17）、§11（未决：租约参数/心跳模型）。
2. 代码锚点: 现有 src/agent_kanban/（Spike @ main）——identity.py L27 `cli_actor`/L13 `mcp_actor`、operations.py L660 `get_task_detail` L680 `limit(200)`、L752 `export_data`、models.py 6 表（Requirement/Claim/Milestone/Subtask/Event/SeqCounter）、db.py（begin 事件 BEGIN IMMEDIATE、run_op 写重试 3 次 db_busy）。
3. 逐例期望: 下方 AC 判据表（M0 全部）+ REST HTTP 错误映射表。

## 影响面

- M0-1: ① 对外契约命中（REST HTTP 面首次建立、export 工件格式 JSON/Markdown 全量、Alembic 首次迁移）；② 新信任边界命中（HTTP 入口，localhost 默认 + token）。单向门处理：契约源自 PRD 已审规格；本 plan 审 + 各子批结果盲审 + AC oracle 兜底。
- M0-2: ③ 轻触（reconcile 周期扫描 + drift 事件写入）；无新对外契约。

## 并发/并批

- M0-1 与 M0-2 同仓串行：M0-2 的 AC10/对账集成依赖 M0-1 的 view 需要关注区完成。每子批独立实现派发（互斥）+ 独立结果盲审 + 独立验证合入。

## M0-1 原子任务（验证命令列于每项）

| # | 任务 | 验证 | 期望 |
|---|---|---|---|
| M0-1.0 | Alembic 基建：alembic init + env.py（sync engine，PRD 7.3 #8）+ baseline migration（autogenerate 自 models）+ alembic.ini | 空库 `alembic upgrade head` -> 表集合与 models 一致；`downgrade base` 清空；既有 AC harness 全绿（create_all 与迁移等价） | upgrade 建 6 表 + 全部索引约束（partial unique index/FK/seq_counter）；downgrade 幂等 |
| M0-1.1 | config/安全（PRD 6）：config.py（HOST/TOKEN/DB env）；默认绑定 127.0.0.1；非 localhost 绑定无 token -> 启动拒绝+告警日志；有 token -> 请求校验（`X-Agent-Kanban-Token` header 或 `?token=`）；DB 0600（Spike 已有，保留） | harness：非 localhost 无 token 启动被拒；token 错误 401；localhost 无 token 可访问；token 正确通过 | PRD 6 威胁模型 A/C 闭合 |
| M0-1.2 | 读/写 sessionmaker 拆分（G8 P2-5）：写 BEGIN IMMEDIATE（现有 begin 事件），读 deferred（WAL 快照，不抢写锁） | 读在写锁竞争下不抛裸 OperationalError（返回结构化错误或快照）；既有 AC 全绿 | G8 P2-5 闭合 |
| M0-1.3 | REST 人面 API（FastAPI）：POST /requirements(new)、PUT /requirements/{id}/expectations、POST /requirements/{id}/approve|release|renew|note|abandon|reopen、GET /requirements(list)、GET /requirements/{id}(深潜)、GET /requirements/{id}/summary(摘要 dict)、GET /requirements/{id}/export?format=json|markdown、GET /healthz。actor：REST -> surface='cli'（人面语义）、conn='rest:<短随机>'（服务端派生，PRD 5.1 枚举无 rest，用 conn 区分传输）。错误映射表（契约）：not_found=404、illegal_state/already_claimed/no_active_claim/lease_expired/duplicate_subtask=409、invalid_record=422、queue_full=429、db_busy=503；body `{code,message,task_id}` | harness REST 客户端逐端点 + 逐码映射 | 与 PRD 4.3 语义一致（REST 用 HTTP 码 + 同 body，MCP 保持 is_error 无 HTTP 码） |
| M0-1.4 | view service（PRD 5.3/5.4）: `view.summary()` 摘要 dict + `view.detail()` 深潜 dict + CLI 文本格式化 + HTML 渲染。摘要含：里程碑时间线（延误：planned_at 未达成超期 / achieved 且 actual_at>planned_at）、决策/风险/偏离（risk>=attention 展示、deviation 无条件）、验收对照表（per 锚：链接的子任务验收项文本+状态可见；无覆盖 -> 覆盖缺口突出）、子任务清单（含 blocked/abandoned）、派生偏离信号（blocked/abandoned、拆解新增、里程碑延误 -> 需要关注区）、认领+awaiting_human、进度派生值（done/total；blocked=进行中；abandoned 不计分母；缺 deviation/note 记录的 abandoned -> "未解释的放弃"告警）。深潜含：完整事件流（kind/severity 过滤）+ 需求状态重建（state_change 链 + 该时点事件）。反淹没结构保证：无 run_logs；payload <=8KB 强制（NFR） | 见 AC11/12/13 判据 + 深潜状态重建断言 | 反黑箱三问可答 |
| M0-1.5 | CLI 扩展（PRD 4.2）：`reopen`（DONE->REOPEN/REOPEN->OPEN/CANCELLED，闭合 G8 P2-2）、abandon 认领处置裁决（REJECTED/CANCELLED 同事务置 claim ended_at + 清 marker + 事件，与 DONE 一致，闭合 G8 P2-3）、`release --all-stale`（逐项单释放语义、部分失败逐项返回，非全有全无）、`export --format markdown` + 全量无 LIMIT（闭合 G8 P2-4）、`view summary|detail` 子命令（文本） | harness 逐子命令 | G8 P2-2/3/4 闭合 |
| M0-1.6 | 静态 HTML 摘要页：GET /requirements/{id}/summary.html（极简渲染 summary dict，反淹没结构；非 Web 窗口） | 200 + 含关键节点 + 不含原始输出 | AC13 结构面 |
| M0-1.7 | harness 扩展：AC11（覆盖缺口突出）、AC12（派生偏离可见，无需 deviation 登记）、AC13（反淹没：摘要输出不含原始内容）、AC15（回溯 5 判据真实数据 + export JSON/Markdown 完整含 events 全文）+ REST 逐端点/错误映射 + reopen/abandon 处置/--all-stale/export markdown 断言；红绿留档 | `uv run python tests/run_ac.py` | 全绿；红 0 -> 绿留档 |

AC 判据表（M0，harness 逐条断言，PRD §9 逐字）：
- AC10（M0-2 实现）：见下。
- AC11 覆盖缺口：requirement.acceptance 中无子任务验收项覆盖的条目在摘要视图突出显示（结构断言：summary dict 含该锚标记 uncovered）。
- AC12 派生偏离可见：子任务 blocked/abandoned 或里程碑延误后，无任何 deviation 登记，摘要"需要关注区"出现对应信号。
- AC13 反淹没：摘要视图不含原始输出流内容（无 run_logs + 断言 summary 不含场景原始长文本/事件 payload）；关键信息不展开事件流可读。
- AC15 回溯：5 条判据逐条用真实数据回答（state_change 链重建、decision+当时状态、claims 时间轴+事件归属、subtask/milestone 变更+事件同事务重建、review 证据字段）；export JSON/Markdown 完整且含 events 全文。
- AC17 证据强制：request_review 缺证据（PR/commit 区间/测试摘要全缺）被拒（Spike matrix 已实现，M0 复验）。

## M0-2 原子任务

| # | 任务 | 验证 | 期望 |
|---|---|---|---|
| M0-2.1 | reconcile service（PRD 3.2 重启对账 / §6 可靠性）：进程内 conn registry（conn_id -> last_seen，每次交互更新）；`reconcile()` 遍历未结束 claim -> conn_live? 租约过期? awaiting_human? -> 信号（STALE/等待中/SUSPECT/ACTIVE + ORPHANED[conn 不在且租约未过期]）；claim-state 失配检测（有 claim 无 CLAIMED [注：BLOCKED 合法] / 反之）-> drift 报告；写 reconcile 事件（append-only，只标记不删除）；触发：FastAPI lifespan + MCP server 启动 + CLI `reconcile` 命令 | harness 造 ORPHANED（conn registry 模拟）与 drift 场景，断言 reconcile 事件与报告 | §6 可靠性闭合；drift 入摘要需要关注区 |
| M0-2.2 | AC10 判别力测试：场景 = 压级风险（risk severity=info，5.3 过滤不可见）+ 窄化验收 + 虚假覆盖（agent 将窄验收项 links_to 粗锚）+ 未登记 abandoned 子任务 + 决策含备选；断言：对照表显示链接映射（锚-链接项文本可见，非仅缺口高亮）使"符合预期"可判不达标；需要关注区有 abandoned 派生信号；decision 含 alternatives；risk=info 不在列表（压级不可见但其余信号足够作答） | harness AC10 | 判别力结构成立 |
| M0-2.3 | ADR 裁决登记：ADR 0003（租约参数 2h/30min 确认 + 心跳模型=外部进程确认 + MCP HTTP=不做确认 + REST 归属 surface='cli'/conn='rest:' 设计钉死）；G8 闭合（P2-2/3/4/5 均在本批完成）；G9 登记（数据保留清理命令 + 重试成本超限判定，M1） | git ls-files tracked | ADR 0003 四要素齐；G8 闭合、G9 登记 |
| M0-2.4 | 全量验证 + 文档：全部 AC（Spike AC1-9/16 + M0 AC10-13/15/17 + 9 码矩阵 + 补充）harness 全绿；docs/ops/m0-verification.md（tracked：判据/基线/重跑规格/verdicts/红绿证据/域外发现）；PRD 状态行标注 M0 完成 | tier-1/2 | 全绿 + 文档对齐 |

## oracle 纪律

- 独立于实现：断言逐字引自 PRD §5.3/§9/§4.3；视图断言基于渲染输出（summary dict / 文本 / HTML），非实现内部成员。
- 反证位：每 AC 先红后绿留档（tests/red-*.log）。
- 最强对抗变体：AC10 场景（虚假覆盖+压级+未登记偏离+备选四合一）；REST 错误映射逐码；reconcile drift/ORPHANED 双场景。
- 不可测性分支：无（全部本仓实现；HTTP 用 uvicorn TestClient/真实子进程均可本仓测）。

## 验证入口与 tier（本机=构建机）

- tier-0: `uv run python -m compileall -q src cli.py`
- tier-1: `uv run python tests/run_ac.py`（全 AC 全绿）
- tier-2（合并门槛）: tier-1 全绿 + 对账 docs/ops/m0-verification.md 逐条与当轮产物一致 + git ls-files 全 tracked + `alembic upgrade head` 于空库验证
- 折入只重跑受影响 AC 的 tier-1；合并前 tier-2。

## 不修清单（M0，含位置/理由/登记处）

1. 不做 Web 窗口（M1，PRD 8）；静态 HTML 摘要页仅极简渲染，不作交互面。
2. 不做 Jira 导入/回写（M1；jira import 属 M1 交付）。
3. 不做 G3 痛点基线采集（user 侧手工日志，M1 硬前置）。
4. 不做 G5 性能基准（M1 跑基准）。
5. 不做 MCP HTTP 形态（M1 未决默认不做）。
6. 不做数据保留清理命令（12 个月窗口 + 清理前导出）——登记 G9，M1。
7. 不做重试成本超限判定（3.2「累计重试超 2 次等你决策」语义需 M1 澄清）——登记 G9。
8. 不做多用户/RBAC/外网部署（全局不做清单）。
9. 不做导出文件的归档/加密（审计资产载体，M1 定）。

## 机械预检（派发前主循环已跑）

- 登记位置 tracked: docs/plans/m0-plan.md（本 plan）、docs/ops/m0-verification.md（M0-2 生成）、docs/adr/0003-*.md（M0-2）。
- 代码锚点: PRD 行号以上方 grep 实测为准；现有实现锚点（identity/operations/models）已列。
- oracle 版本: 实测（fastapi 0.158.2 / alembic 1.20.0 / uvicorn / sqlalchemy 2.1.6 / aiosqlite 0.22.1 / mcp 2.3.0 / python 3.14.4）；harness argv = `uv run python tests/run_ac.py`。
- 产物清单: src/agent_kanban/{config.py, api/__init__.py, api/requirements.py, api/main.py, services/view.py, services/reconcile.py, services/identity.py(增 rest_actor)}、alembic/{env.py, versions/0001_*.py}、alembic.ini、cli.py 扩展、tests/*（ac_cases_c.py 等）、docs/plans/m0-plan.md、docs/ops/m0-verification.md、docs/adr/0003-*.md。

## 域外发现处置

执行/审查中一切非本批引入的问题（PRD 缺口、环境、既有基码缺陷）-> 回报单列 + 登记 m0-verification.md「域外发现」+ 裁决归主循环，禁静默修。
