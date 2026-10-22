# M0 Plan — 人面 REST + 视图 + 导出 + 对账 + 派生偏离（AC10-13/15/17）

分支: `m0`（worktree `.worktree/m0/`，基分支 main @ 7447950）
档位: M0-1 全六门（D 对外契约/REST API + ①export 工件格式 + ②新信任边界 HTTP + 新测试语义）；M0-2 全六门（③reconcile 周期扫描 + 新测试语义 AC10）
规范锚: docs/PRD.md v3.2（commit 7447950）；Spike 已绿 AC1-9/16（docs/ops/spike-verification.md）
依赖实测: fastapi 0.158.2 / alembic 1.20.0 / uvicorn（本 worktree .venv 已装）；sqlalchemy 2.1.6 / aiosqlite 0.22.1 / mcp 2.3.0 / python 3.14.4
本 plan 为 M0 单一契约，覆盖两个串行子批（M0-1 基础+人面 REST+视图+导出；M0-2 reconcile+AC10+裁决登记）；各子批独立实现派发 + 独立结果盲审，验证后各自 ff 合入 main（user 已授权自合）。盲审 P1-1/2/3/4 已折入（见正文标注「审#n」）。

## 契约三锚

1. 规范逐字原文: PRD §4.2（人面 CLI/REST 语义）、§5.1（归属）、§5.3（视图原则：摘要/深潜/反淹没/覆盖下界/派生偏离）、§5.4（回溯 5 判据）、§6（NFR：安全/可观测/可靠性/数据量级）、§7.1-7.3（架构与契约级要点：Alembic sync engine、REST 与 MCP 共用 state_machine、写保护 service 统一）、§8（M0 里程碑）、§9（AC10-13/15/17）、§11（未决：租约参数/心跳模型）。
2. 代码锚点: 现有 src/agent_kanban/（Spike @ main）——identity.py L27 `cli_actor`/L13 `mcp_actor`、operations.py L660 `get_task_detail` L680 `limit(200)`、L752 `export_data`、models.py 6 表、db.py（begin 事件 BEGIN IMMEDIATE、run_op 写重试 3 次 db_busy、ensure_schema 的 seq_counter INSERT OR IGNORE）。
3. 逐例期望: 下方 AC 判据表（M0 全部）+ REST HTTP 错误映射表。

## 影响面

- M0-1: ① 对外契约命中（REST HTTP 面首次建立、export 工件格式 JSON/Markdown 全量、Alembic 首次迁移）；② 新信任边界命中（HTTP 入口，localhost 默认 + token）。单向门处理：契约源自 PRD 已审规格；本 plan 审 + 各子批结果盲审 + AC oracle 兜底。
- M0-2: ③ 轻触（reconcile 扫描 + drift 事件写入）；无新对外契约。

## 并发/并批

- M0-1 与 M0-2 同仓串行：M0-2 的 AC10/对账集成依赖 M0-1 的 view 需要关注区完成。每子批独立实现派发（互斥）+ 独立结果盲审 + 独立验证合入。

## M0-1 原子任务

| # | 任务 | 验证 | 期望 |
|---|---|---|---|
| M0-1.0 | Alembic 基建：alembic init + env.py（sync engine，PRD 7.3 #8）+ baseline migration（autogenerate 自 models）+ alembic.ini。**审#5**：baseline 迁移内显式 seed seq_counter(id=1,value=0)（纯 alembic 路径下 next_seq 空 UPDATE 会 NoResultFound）；ensure_schema 的 INSERT OR IGNORE 兜底保留（双轨兼容）。**审#5**：等价性验证 = 空库 `alembic upgrade head` 后 sqlite_master 逐项 diff（表/索引/含 sqlite_where 的 partial unique index/FK）与 models 声明一致，非一次人工比对 | 空库 upgrade -> 表集合+全部索引约束与 models 一致；downgrade base 清空（版本表驱动）；既有 AC harness 全绿（create_all 与迁移等价） | upgrade/downgrade 幂等；sqlite_where partial index 渲染正确 |
| M0-1.1 | config/安全（PRD 6）：config.py（HOST/TOKEN/DB env）；默认绑定 127.0.0.1；非 localhost 绑定无 token -> 启动拒绝+告警日志；有 token -> 请求校验（`X-Agent-Kanban-Token` header 或 `?token=`）；**审#6**：`/healthz` 豁免 token（探活） | harness：非 localhost 无 token 启动被拒；token 错误 401；localhost 无 token 可访问；token 正确通过；healthz 无 token 200 | PRD 6 威胁模型 A/C 闭合 |
| M0-1.2 | 读/写 sessionmaker 拆分（G8 P2-5）：写 BEGIN IMMEDIATE（现有 begin 事件），读 deferred（WAL 快照，不抢写锁） | 见 M0-1.7 读锁竞争断言 | G8 P2-5 闭合 |
| M0-1.3 | REST 人面 API（FastAPI）：POST /requirements(new)、PUT /requirements/{id}/expectations、POST /requirements/{id}/approve|release|renew|note|abandon|reopen、GET /requirements(list)、GET /requirements/{id}(深潜)、GET /requirements/{id}/summary(摘要 dict)、GET /requirements/{id}/export?format=json|markdown、GET /healthz。actor：REST -> surface='cli'（人面语义）、conn='rest:<短随机>'（服务端派生，PRD 5.1 枚举无 rest，用 conn 区分传输）。**审#3**：harness 用真实子进程 uvicorn + HTTP 客户端（httpx/urllib），与 CLI/MCP harness 同隔离模式（env_for 注入 HOST/TOKEN/DB）；禁用 TestClient（父进程 _Runtime 单例共享破坏隔离）。错误映射表（契约，**审#7** 注明不可达码）: not_found=404、illegal_state=409、lease_expired=409、invalid_record=422、db_busy=503；already_claimed/no_active_claim/duplicate_subtask/queue_full 为 agent 面（MCP）专用码，REST 面无触发端点（保留作契约完整性，body 仍 `{code,message,task_id}`） | harness 真实子进程逐端点 + 逐码映射 | 与 PRD 4.3 语义一致（REST 用 HTTP 码 + 同 body，MCP 保持 is_error 无 HTTP 码） |
| M0-1.4 | view service（PRD 5.3/5.4）: `view.summary()` 摘要 dict + `view.detail()` 深潜 dict + CLI 文本 + HTML 渲染。摘要含：里程碑时间线（延误：planned_at 未达成超期 / achieved 且 actual_at>planned_at）、决策/风险/偏离（risk>=attention、deviation 无条件）、验收对照表（per 锚：链接的子任务验收项文本+状态可见；无覆盖 -> 覆盖缺口突出）、子任务清单（含 blocked/abandoned）、派生偏离信号（blocked/abandoned、拆解新增、里程碑延误 -> 需要关注区）、认领+awaiting_human、进度派生值（done/total；blocked=进行中；abandoned 不计分母）。**口径钉死**：拆解新增 = 需求进入 CLAIMED 后存在 add_subtask（decomposition 事件）且该 CLAIMED 期间无 decision/deviation 记录解释；未解释放弃 = abandoned subtask 无同 subtask_id 的 deviation 或 note 事件（按事件 payload.subtask_id 关联）。深潜：完整事件流（kind/severity 过滤）+ 状态重建（**算法钉死**：按 seq 回放 state_change 链到目标 ts）。**审#2**：AC13 禁止面 = 摘要不含原始输出流（progress_note content 全文、事件 content 长文本、run_logs）；显式允许结构化决策字段（choice/alternatives/rationale 提取）。**payload 8KB 强制**（PRD 6，写时 add_record/add_subtask 校验） | 见 AC11/12/13 + 深潜状态重建断言 | 反黑箱三问可答 |
| M0-1.5 | CLI 扩展（PRD 4.2）：**审#2-reopen**：`reopen <id>` = DONE->REOPEN；`reopen <id> --continue` = REOPEN->OPEN；REOPEN->CANCELLED 由 abandon 覆盖（不重复）。abandon 认领处置裁决（G8 P2-3）：REJECTED/CANCELLED 同事务置 claim ended_at + 清 marker + 事件（与 DONE 一致）。`release --all-stale`（逐项单释放语义、部分失败逐项返回）。`export --format markdown` + 全量无 LIMIT（G8 P2-4）。`view summary|detail` 子命令（文本） | harness 逐子命令 | G8 P2-2/3/4 闭合 |
| M0-1.6 | 静态 HTML 摘要页：GET /requirements/{id}/summary.html（极简渲染 summary dict，反淹没结构；非 Web 窗口） | 200 + 含关键节点 + 不含原始输出 | AC13 结构面 |
| M0-1.7 | harness 扩展（红绿留档）：AC11（覆盖缺口突出 + **审#2 反向断言**：已覆盖锚不显示 uncovered）、AC12（派生偏离可见：blocked/abandoned/里程碑延误，无需 deviation 登记；abandoned 分支含未解释放弃正反向）、AC13（反淹没：摘要不含 progress_note content 全文/长 content/run_logs，但含结构化决策字段）、AC15（回溯 5 判据真实数据 + export JSON/Markdown 完整含 events 全文）、AC17 复验 + **审#4 读锁竞争断言**（真实子进程持 BEGIN IMMEDIATE + 极小 busy_timeout，CLI/MCP/REST 读返回结构化结果或快照，不抛裸 OperationalError；读失败映射码并入 db_busy）+ **审#3 进度派生值断言**（done/total、blocked=进行中、abandoned 不计分母）+ payload 8KB 超限断言 + REST 逐端点/错误映射 + reopen/abandon 处置/--all-stale/export markdown | `uv run python tests/run_ac.py` | 全绿；红 0 -> 绿留档 |

AC 判据表（M0，harness 逐条断言，PRD §9 逐字）：
- AC11 覆盖缺口：无子任务验收项覆盖的 acceptance 条目在摘要突出显示（结构断言：summary dict 该锚 uncovered 标记）；已覆盖锚不显示 uncovered（反向断言）。
- AC12 派生偏离可见：子任务 blocked/abandoned 或里程碑延误后，无 deviation 登记，摘要"需要关注区"出现对应信号。
- AC13 反淹没：摘要不含原始输出流内容（progress_note content 全文/长 content/run_logs）；关键信息不展开事件流可读；结构化决策字段可见（与 AC10 同库互证，**审#2**）。
- AC15 回溯：5 条判据逐条真实数据回答（state_change 链重建、decision+当时状态、claims 时间轴+事件归属、subtask/milestone 变更+事件同事务、review 证据字段）；export JSON/Markdown 完整含 events 全文。
- AC17 证据强制：request_review 缺证据被拒（Spike 已实现，M0 复验）。

## M0-2 原子任务

| # | 任务 | 验证 | 期望 |
|---|---|---|---|
| M0-2.1 | reconcile service（PRD 3.2 重启对账 / §6 可靠性）。**审#1 折入**：观测源 = claims 表（agent_conn + last_activity_at，共享 DB），**不做进程内 conn registry**（跨进程各自 registry 会互相误标 ORPHANED）。`reconcile()`：遍历未结束 claim -> 租约过期? awaiting_human? 连接失活（last_activity_at 超 idle）? -> 有序判定（租约优先，等待中优先于 ORPHANED）；ORPHANED = 连接失活且租约未过期且无 awaiting_human（对 SUSPECT 区间在 reconcile 时点的显式化）；claim-state 失配检测（有 claim 无 CLAIMED [BLOCKED 合法] / 反之）-> drift 报告；写 reconcile 事件（append-only，只标记不删除）。**审#10**：触发 = CLI `reconcile` 命令 + FastAPI lifespan；MCP server 启动不跑全量 reconcile（避免多进程事件噪音）。**审#8**：ORPHANED 只属 reconcile 产物（报告+事件），claim_view.signal 保持 PRD 推导序（ended/waiting/stale/suspect/active），drift/ORPHANED 入摘要"需要关注区" | harness 造连接失活（last_activity_at 旧）+ 等待中优先级 + drift 双场景（claim 无 CLAIMED / CLAIMED 无 claim），断言 reconcile 事件与报告 | §6 可靠性闭合；C5 可区分等待裁决 vs 死 agent |
| M0-2.2 | AC10 判别力测试（**审#2 断言钉死**）：场景 = 压级风险（risk severity=info，5.3 过滤不可见）+ 窄化验收 + 虚假覆盖（agent 将窄验收项 Y links_to 粗锚 X）+ 未登记 abandoned 子任务 + 决策含备选。断言：①对照表显示"粗锚 X 下显示窄验收项 Y 文本及状态"（非仅存在映射）；②反向断言：虚假覆盖锚 X 不显示 uncovered 标记（排除靠缺口高亮作答路线）；③需要关注区有 abandoned 派生信号；④decision 含 alternatives 文本；⑤risk=info 不在决策/风险/偏离列表（压级不可见但其余信号足够作答） | harness AC10 | 判别力结构成立（"符合预期"凭链接映射可判不达标） |
| M0-2.3 | ADR 裁决登记：**审#9 扩范围** ADR 0003（租约参数 2h/30min 确认 + 心跳模型=外部进程确认 + MCP HTTP=不做确认 + REST 归属 surface='cli'/conn='rest:' 设计 + REST HTTP 错误映射表 + ORPHANED 语义 + reconcile 观测源=claims 表无进程内 registry）；G8 闭合（P2-2/3/4/5 均完成）；G9 登记（数据保留清理命令 + 重试成本超限判定，M1） | git ls-files tracked | ADR 0003 全要素；G8 闭合、G9 登记 |
| M0-2.4 | 全量验证 + 文档：全部 AC（Spike AC1-9/16 + M0 AC10-13/15/17 + 9 码矩阵 + 补充）harness 全绿；docs/ops/m0-verification.md（tracked：判据/基线/重跑规格/verdicts/红绿证据/域外发现）；PRD 状态行标注 M0 完成 | tier-1/2 | 全绿 + 文档对齐 |

## oracle 纪律

- 独立于实现：断言逐字引自 PRD §5.3/§9/§4.3；视图断言基于渲染输出（summary dict / 文本 / HTML）。
- 反证位：每 AC 先红后绿留档（tests/red-*.log）。
- 最强对抗变体：AC10 四合一场景；REST 错误映射逐码；reconcile drift/ORPHANED 双场景；读锁竞争。
- 不可测性分支：无（HTTP 用真实子进程 uvicorn，本仓可测）。

## 验证入口与 tier（本机=构建机）

- tier-0: `uv run python -m compileall -q src cli.py`
- tier-1: `uv run python tests/run_ac.py`（全 AC 全绿）
- tier-2（合并门槛）: tier-1 全绿 + 对账 docs/ops/m0-verification.md 逐条与当轮产物一致 + git ls-files 全 tracked + 空库 `alembic upgrade head` 验证
- 折入只重跑受影响 AC 的 tier-1；合并前 tier-2。

## 不修清单（M0，含位置/理由/登记处）

1. 不做 Web 窗口（M1，PRD 8）；静态 HTML 摘要页仅极简渲染，不作交互面。
2. 不做 Jira 导入/回写（M1）。
3. 不做 G3 痛点基线采集（user 侧手工日志，M1 硬前置）。
4. 不做 G5 性能基准（M1）。
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
