# 审查报告：Task 生命周期操作（create/archive/delete）与看板定位重述 spec

**审查对象**: `docs/superpowers/specs/2026-10-26-task-lifecycle-positioning-design.md`（13 节）
**配套 BCD**: `docs/business-contracts/task-lifecycle-positioning.md`（7 节）
**参照代码**: 本仓 main 8767385 基线（state_machine.py / operations.py / view.py / api/requirements.py / api/web.py / cli.py / mcp/server.py / models.py / db.py / reconcile.py / tests/）
**审查方式**: adversarial-review，路由 = 设计/架构 spec（线面主轴 + 四层 + 约束审计 + 威胁模型），主 reference = design-review，追加 requirements-review（spec 含能力语义重述 + 非目标边界）。BCD 前置检查已通过（7 节齐，质量抽查见下）。独立 subagent 首审，与编写过程零上下文。
**日期**: 2026-10-26

---

## verdict: APPROVE-WITH-FIXES

方向层、架构层结论：设计落在根因层（新终态 + 硬删 + surface 重划），不是绕行案；7 条业务不变量（I1-I7）除 I3 的完整保证依赖 P1-3 裁决外，spec 均给出实现保证；"零改动/既有模式复用"声明逐条核实后 21 条属实、3 条不实（即下述 P1-1/P1-2/P2-1）。修复清单全部可折入 spec 文本，不复审。

---

## 问题清单

### P1-1: `list_tasks` 默认过滤与 REST `GET /requirements` 将被 ARCHIVED 静默改变，spec 完全未触碰该受影响面

**位置**: spec §2/§5/§7（沉默）+ §2/§7 "MCP 零改动" 声明；代码 `src/agent_kanban/services/operations.py:781`、`src/agent_kanban/api/requirements.py:116-118`

**理由**: `list_tasks` 默认（无 status）过滤是硬编码 `Requirement.state.not_in(["DONE", "REJECTED", "CANCELLED"])`（operations.py:781），与 spec §5 要改的 `board()` 过滤（view.py:227）是**两份独立的硬编码列表**。spec 只改了后者。后果：ARCHIVED 行不满足排除谓词，`list_tasks` 默认输出与 REST `GET /requirements` 将**开始返回已归档任务**。失败序列：任务 CLAIMED -> 人 archive -> agent 会话 `list_tasks`（默认）-> 归档任务出现在工作列表（state=ARCHIVED）-> agent 视其为可工作候选 -> `claim_task` -> illegal_state（claim 行回滚）或 `update_progress` -> no_active_claim -> agent 误判系统故障（恰是 BCD F2 要防的混淆类，只是换了触发源）。这直接违背 PRD §4.1 对 `list_tasks` 的契约"status 过滤，**获取未完成任务**"（PRD.md:148），也与"ARCHIVED = 冷存储、不可回到活跃流"（BCD P1）矛盾——同产品两个"活跃集"（board 排除、list_tasks 包含）漂移。spec §2/§7 的"MCP 工具面零改动（12 工具不变）"在**工具注册**层面为真，但工具**行为**变了，零改动声明在此处不成立。

**建议**: spec §5 增一行：`list_tasks` 默认过滤与 `board()` 同源改 `not_in(TERMINAL_STATES)`（operations.py:781 同 view.py:227 一并常量派生），并显式写 REST `GET /requirements` 同口径；harness 新增断言（ARCHIVED 任务不在 `list_tasks` 默认输出、不在 `GET /requirements` 默认输出、`list_tasks(status="ARCHIVED")` 包含之）；PRD §4.1 list_tasks 行与 web.md 同步。若 user 裁决"agent 应能在默认列表看到 ARCHIVED"，则必须反过来显式声明该行为并改 PRD §4.1 措辞——二选一，不许沉默。

### P1-2: "SSE 推送使看板自动刷新（OPEN 列 +1）"是假机制——create 不写事件，SSE 只由事件帧驱动，spec 内部自相矛盾

**位置**: spec §4.1 第 3 条 + §10 AC1 语境 + BCD S1 Then 子句（"SSE 推送使看板自动刷新"）

**理由**: 失败序列（每次 Web 新建必现）：表单提交 -> `new_requirement` 只写 requirements 行、**不写任何事件**（operations.py:87-112；spec §2 非目标自己也写明"创建不写事件、不加新事件 kind"，BCD P-C）-> SSE 流（api/requirements.py:131-165）只轮询 events 表新行发帧 -> **无帧可发** -> 看板不刷新，用户刚建的任务不见于 OPEN 列，直到手动刷新或恰好有其他事件触发重拉。即：spec §2 非目标（create 不写事件）与 §4.1 承诺（SSE 自动刷新）在机制上互斥，spec 内部矛盾。实施者只有两条路，都是坏的：加 create 事件（违反 P-C 非目标与"事件 kind 契约稳定"）或留 stale board（BCD S1 验收不成立）。

**建议**: spec §4.1 改为"提交成功后**前端主动重拉 board**（深潜页 `handleOpResult` 成功后 `load()` 同款模式，board 壳内联同款）"；BCD S1 Then 同步改措辞（"表单提交成功后看板重拉，OPEN 列 +1"）。harness case 7 / AC1 的"board OPEN 列 +1"按 REST `/board` 重拉断言即可成立，无需改。

### P1-3: BCD S2/E2 承诺"事件记录实际 from 状态"，spec §3 设计为 `from=None -> "? -> ARCHIVED"`——BCD × spec 正典冲突，须 user 裁决，harness 将按其一断言

**位置**: BCD §4 S2（"事件链尾为 state_change(CLAIMED -> ARCHIVED, actor=人面)"）+ §5 E2（"events 尾行 state_change **\"CLAIMED -> ARCHIVED\"（实际 from 记录）**"） vs spec §3（"写 state_change 事件（`from_state=None` 传参，事件 title **\"? -> ARCHIVED\"**，payload `{\"from\": None, \"to\": \"ARCHIVED\"}`——与 REJECTED 既有事件形态一致）"）+ §4.2 步骤 3

**理由**: 这是可直接复现的断言冲突：harness 实施者照 BCD E2 写"事件 title == 'CLAIMED -> ARCHIVED'" -> 按 spec §3 实现（`transition(from_state=None)`，state_machine.py:72 `f"{from_state or '?'} -> {to_state}"`）得到 "? -> ARCHIVED" -> 红。spec 选 None-from 的理由是"与 REJECTED 既有事件形态一致"（precedent 复用，机制核实属实：(None, REJECTED) 边，state_machine.py:29）；BCD 写的是"实际 from 记录"。两者在审计字段（回溯判据 2"决策当时在什么状态下做出"对 archive 的对应问法 = 从哪个状态归档）上给出互斥承诺。spec 未察觉冲突，BCD 未察觉机制约束（若记录实际 from，`transition` 需扩展或 archive 在 operations 层改写事件语义，与 spec "transition() 零改动"声明冲突）。**不自行择一**，列为正典冲突交 user：

- 案 A：BCD S2/E2 修订为接受 REJECTED 先例（title "? -> ARCHIVED"、payload.from=None、from 状态经事件链回放恢复——`reconstruct_states` 可恢复，非审计死角）；spec 不动。
- 案 B：spec 修订为记录实际 from（archive 已 `require_requirement` 拿到 `req.state`，可在 operations 层以实际 from 写事件或扩展 transition），同时改掉 §3 "transition() 零改动"与"与 REJECTED 形态一致"两条声明，并评估 REJECTED 先例是否同步对齐（不同步 = 同类边两种事件形态，新的方言分裂）。

裁决后 harness case 1 必须按裁决断言事件 title/from 字段。

### P2-1: §10 声称"移除既有 harness 的 7 个决策按钮 + set_expectations 断言"，既有 harness 中不存在这些断言

**位置**: spec §10 首条；tests/ 全目录（`ac_cases_a..j`）

**理由**: 全 tests/ grep `data-op` / 按钮 / `data-tab` / 7 按钮相关断言 = 零命中。既有 web 壳契约断言只有：board-root/detail-root 壳标记、EventSource、壳无原始输出（ac_cases_g.py:295-302）。spec 把"不存在的移除"写成"存在的更新"，属"既有模式复用"式不实声明（无行为后果，但实施者按清单找断言会落空，且掩盖了真实事实：壳契约目前**没有**按钮级 pin，本次是新增而非更新）。

**建议**: §10 改为"board 壳：tabs 2 -> 3、新增新建入口断言、新增 archive/delete 操作区断言（**新增**，非移除）；深潜页：壳契约基线维持 board-root/detail-root/EventSource/零数据嵌入，新增生命周期操作区断言 + 决策按钮缺席断言（assert detail 壳 HTML 不含 approve/release/... 按钮）"。注意"决策按钮缺席"这条新断言是 C6/UI 瘦身的判别力所在，应显式列入。

### P2-2: BCD F3 预防措施第 2 项（板面"等待人"区展示命令）未落入 spec

**位置**: BCD §6 F3 预防（"awaiting 横幅加静态 CLI 提示；**板面'等待人'区同样展示命令**；README/web.md 加命令速查"）vs spec §6.1（board 壳变更仅列新建按钮/tabs/归档 tab）+ §10 case 8（只测深潜页横幅两形态）

**理由**: Premortem F3（awaiting 堆积）的预防是三条的，spec 只落了两条（深潜页横幅 CLI 提示、文档速查）。board 卡片 `.wait` 行（web.py:166，"等待人: <reason>"）是 agent 交接后人在**板面**首先看到的落点，恰是 F3 失败序列的第一步（"板上看板横幅等待人 -> 没有按钮 -> 不知道去终端"）。预防半覆盖 = 残余风险 R4 比 spec 声称的大。

**建议**: §6.1 增"board 卡片等待人行追加静态命令（kind=review/blocked -> `kanban approve <id>`）"，harness case 8 扩板面形态；或显式修订 BCD F3 预防为"仅深潜页横幅"并同步 R4 残余描述。

### P2-3: 残余登记无落点——§13 三条"残余登记"，§9 文档同步清单不含登记惯例文件

**位置**: spec §13 R1/R3/R4（"残余登记"字样）+ §9 文档同步清单（PRD §0/§3.1/§3.4/§4.2/§6、web.md、README，无 ADR）

**理由**: 本仓残余登记惯例 = `docs/adr/0000-known-gaps.md`（G1-G10 全在此）。§13 说"残余登记"但没写登记到哪，§9 清单不含 ADR 0000——只留在 spec 风险表里 = 未登记（审查报告/对话里的登记不构成可追溯登记）。R1（agent harness 仓外处理 not_found）、R3（archive/abandon 语义靠使用纪律）、R4（习惯迁移）三条都要求持久可见。

**建议**: §9 增一行"`docs/adr/0000-known-gaps.md`：新增 G11（R1）/G12（R3）/G13（R4）行，含档位与升级路径"。

### P2-4: 文档同步清单漏掉与新定位直接冲突的既有正典措辞（两处定位语 + web.md 冒烟项）

**位置**: spec §9；`docs/PRD.md:26`（"看板是记录面 + **协作窗口**，不是控制面"）、`docs/design.md:11`（"看板是**记录面 + 协作窗口**，不是控制面"）、`docs/web.md:45-52` 冒烟 checklist 第 4 条（"人面操作：approve/renew/note 成功并重拉"）

**理由**: spec §1 把定位重述为"看板不承担共识达成逻辑……只展现结果"，BCD §5 明确旧语义是"根本性业务冲突"、裁决为"看板降为展示面"。但 PRD §0 职责边界行与 design.md §0 的"记录面 + 协作窗口"措辞不在 §9 同步清单（§9 的 PRD §0 项只写"定位语修订（§1 引文）+ 报告纪律"，§1 引文未覆盖职责边界行；design.md 整份不在清单）。实施后正典内并存两句互斥定位语 = 正典自我冲突，后续审查者无法判定哪句为现行。web.md 冒烟第 4 条在 UI 瘦身后失效（按钮已不存在），§9 "人面操作节重写"未点名冒烟 checklist。

**建议**: §9 PRD §0 项扩为"定位语 + 职责边界行（'协作窗口'措辞按新定位改写）"；清单增 design.md §0 行；web.md 项扩为"surface 表 + 人面操作节 + 冒烟 checklist 第 4 条（改 create/archive/delete + CLI 提示冒烟）"。

### P2-5: archive 全状态矩阵漏 REOPEN——"任一状态可达"未全 pin

**位置**: spec §10 case 1 + AC2（均列 OPEN/CLAIMED/BLOCKED/DONE/REJECTED/CANCELLED 六态）

**理由**: 状态机全集含 REOPEN（state_machine.py:26-28 三条 REOPEN 边可达）。矩阵漏它，"任一状态"声明的判别力不完整：若实施时误把 archive 实现成"六态白名单"而非 (None, ARCHIVED) 边，现有用例全绿、REOPEN 任务归档失败。REOPEN 不是边角态——它是 DONE 的必经返工通道。

**建议**: case 1 / AC2 矩阵补 REOPEN 行（含断言 REOPEN -> ARCHIVED 成功 + 事件链尾正确）。

### P2-6: 两处实施锚点欠定义（archive 事件 claim 关联、CLI delete --yes）

**位置**: spec §4.2 步骤 3（`transition(...)` 未写 claim_id 参数）、§4.4/AC9（CLI delete "确认提示，模式同 prune 确认门"未写 --yes）

**理由**: (a) abandon 先例把活跃 claim id 传入 transition，使 state_change 事件带 claim_id 归属（operations.py:356-361，回溯判据 3"谁在什么时候做了什么"的事件-认领关联）。spec 的 archive 步骤 2 已读 claim、步骤 4 用 claim 置 ended_at，唯独步骤 3 未说明是否传 claim_id——实施者两种实现都"符合 spec"，事件链形态却不同（claim_id 有/无）。(b) prune 确认门的完整形态含 `--yes` 跳过（cli.py:186-194，ac_cases_h.py:144 实际用 `--yes` 驱动非交互）；"模式同 prune"是否含 --yes 未言明，harness 非交互测 delete 依赖它。

**建议**: §4.2 步骤 3 补"有活跃认领时 claim_id 传入 transition（abandon 先例）"；§4.4 补"CLI delete 支持 --yes 跳过确认（prune 同形）"。

### P2-7: "整删"措辞与既有 prune 实现语义（只删 events、需求行保留）未对齐，harness case 5 判别口径不定

**位置**: spec §8（"ARCHIVED 任务在 prune 窗口内整删"）+ BCD S7（"该任务被终态需求级窗口整删"）+ §10 case 5（"出窗整删"）；代码 `prune_events` 只 `delete(Event)`（operations.py:976-980），既有 harness 已钉死"events 整删 + 需求行保留 + detail 零事件 + history_note"（ac_cases_h.py:149-160）

**理由**: 既有 prune 的"整删"= 需求的事件链整删，requirements 行保留（view.HISTORY_NOTE 即为此设计，C7"整删需求的历史以导出归档为准"）。spec/BCD 的"任务被整删"字面可读出"需求行也消失"。实施者若按字面写 case 5 断言（requirement 行 == 0）-> 红 -> 进而可能把 prune 扩成删行（推翻 HISTORY_NOTE/C7 既有设计，且 §8 自己又声明 prune 仅改 PRUNE_TERMINAL_STATES 一行）。既有 harness 先例可救，但 spec 文本不应把判别口径留给读者推断。

**建议**: §8 与 BCD S7 措辞改"事件链整删（需求行保留，detail 显 history_note，既有口径）"；case 5 显式写可观测断言：events 计数 0 + requirement 行 state=ARCHIVED 仍在 + detail history_note 命中（同 ac_cases_h prune(i) 口径）。

---

## 事实勘误附注（不占问题位、不改 verdict）

- **e1**: spec §3 "approve on ARCHIVED -> illegal_state（§3.4 判定表无 ARCHIVED 边，`edge not in ALLOWED_EDGES` 自然拦截）"——实际拦截点在 `approve` 操作内部的状态判定（operations.py:167-188，state 非 CLAIMED/BLOCKED 直接 raise），请求根本不到边表。行为结论（illegal_state）正确，PRD §3.4 新增行（ARCHIVED | 任意 | 拒绝 | illegal_state）与行为一致。
- **e2**: spec §1 "决策操作……保留但降为 **CLI-only**"——本 spec 未删除 REST 决策端点（approve/release/renew/reopen/note/abandon/expectations 均零改动保留），准确措辞为"Web UI 移除入口，REST/CLI 保留"。行为无变化（REST 决策端点为既有面），但"CLI-only"若被实施者读成"删 REST 端点"会扩大改动面，建议措辞修正。

---

## 正典老化 / 冲突（单列节）

1. **正典冲突（P1-3）**：BCD S2/E2 "实际 from 记录" × spec §3 "from=None（REJECTED 先例）"。交 user 裁决案 A/B（见 P1-3），裁决前该条不视为已审定的契约字段。
2. **老化（spec 自身引入，P2-4 覆盖）**：PRD §0 职责边界行与 design.md §0 "记录面 + 协作窗口" 将被本 spec 的新定位超越；spec 未列同步计划。不得以"PRD 原文如此"作为 UI 仍承载决策面的证据（代码现状的 7 按钮才是当前事实，spec 移除之）。
3. **老化（既有，登记不占问题位）**：PRD.md:4 状态行 "M1 未开工" vs 代码事实（Web 壳已实现并过 harness，ac_cases_g）；PRD §4.2 Web surface 表无人面操作行 vs 代码 web.py:396-409 有 7 决策按钮。前一条 spec 未触碰（建议 §9 顺手修订状态行）；后一条 spec §9 重写 §4.2 时自然收口，重写稿须以"只读 + 生命周期"为唯一现行口径，不得保留旧表。
4. **ADR 无冲突**：ADR 0005（M1 方向、Web 必须）与 UI 瘦身不冲突（Web 保留、操作搬家）；ADR 0000 残余惯例被 P2-3 引用；(None, REJECTED) 先例（state_machine.py:29）spec 引用属实。

---

## 分层覆盖说明

- **BCD 前置检查**：7 节齐。质量抽查：§1 三解读真互斥（A/B 决策按钮去留、A/C UI 生命周期面）；§7 强/软分类有真实后果支撑（I6 软 = 边可后加零迁移，成立）；§5 差异表"根本性业务冲突"（C6 审计 surface）成立；§6 四个失败原因均可推出具体序列。实质缺口两处 = P1-3（S2/E2 × spec）、P2-2（F3 预防项 2 未承接），已列。
- **第 1 层（不变量）**：I1（C6）——DONE 唯一来源仍为 approve，MCP 12 工具无 DONE 路径，AC8 回归 pin；保持。I2（链永不半断）——delete 单事务全聚合行删除（FK 序 events -> subtasks/milestones/claims -> requirement，与 models.py 外键方向一致，foreign_keys=ON 已开 db.py:62）；prune 全链谓词既有。I3（archive/abandon 可区分）——release_reason="archive" + state=ARCHIVED 与 REJECTED/CANCELLED 结构可分；事件 from 字段完整保证依赖 P1-3。I4（销毁仅人面）——12 工具核实无 delete/archive。I5（delete 原子）——run_op 单事务（BEGIN IMMEDIATE + 3 重试），kill -9 于事务中 -> 全回滚。I6/I7（软）——claim on ARCHIVED 回滚路径逐行核实（operations.py:400-428：insert 成功 -> transition OPEN->CLAIMED rowcount=0 -> illegal_state -> 事务回滚，净零副作用）；prune 终态集合扩展。
- **第 2 层（契约/消费者）**：新输出逐一问"谁消费"——ARCHIVED 状态值（board 归档 tab、list_tasks 默认 [P1-1]）、release_reason="archive"（claims 时间轴/回溯判据 3）、REST 200 body（Web 壳/CLI JSON）、"? -> ARCHIVED" 事件（深潜回放/P1-3）。声明分级：P1-2 属"纯预期冒充既有机制"（SSE 自动刷新无机制支撑），已按虚标处理。
- **第 3 层（反例构造）**：崩溃时序——archive/delete 事务内各插 kill -9，均全回滚，无半态（单事务，SQLite 原子提交）；双主角并发——delete × agent 写：BEGIN IMMEDIATE 单写者串行化，两序（agent 先提交被整删 / delete 先提交 agent 重试后 not_found）均无 FK 悬空，spec §4.3 声明核实成立；archive × claim_task 同两序验证（archive 先 -> agent claim 回滚；agent 先 -> archive 同事务结束 claim）；残留——新代码读旧库无 ARCHIVED 行无影响；旧代码读新库 ARCHIVED 行仅视图退化（old board 计数含、无列渲染）不损坏数据，单用户 localhost 无发版形态，登记为注；生命周期闭环——marker 清除与 claim 结束均在 archive 同事务（transition 通规 to!=BLOCKED 清 marker，state_machine.py:63-66），无孤儿资源；双重失败——无中间态可叠加。
- **主轴·线**：问题定位 = task 生命周期归属 + 看板定位漂移（客户原话语义），设计落在根因层（状态机终态 + 聚合硬删 + surface 重划），无裱糊信号（无同构问题复发、无多调用方重复补丁）。
- **主轴·面**：①消费方——list_tasks/REST list（P1-1）、SSE（P1-2）、board/detail/export/reconcile/prune 逐一核过（export 全量含 ARCHIVED 无行为变化；reconcile drift 谓词对 ARCHIVED 无新触发——claim 同事务结束，claim_without_claimed 不可持续）；②部署/迁移——无 schema 变更（state String(16) 无 CHECK 约束，alembic baseline 核实），无迁移；③失败邻座——delete × agent 写已核；④退役——未引入 shim/双路径/兼容层；⑤既有约束触碰——C6/I2/I4 保持、错误码零新增（九码全集核实，新场景全部落入既有码）、事件 kind 稳定（12 kind 无新增）。
- **威胁模型**：无新信任边界。新端点 POST /{id}/archive、DELETE /{id} 被 path-agnostic token 中间件覆盖（api/main.py:64-77，仅 /healthz 豁免）；失败方向 = 默认 localhost 绑定、非 localhost 强制 token（lifespan 启动拒绝）；delete 为新增销毁路径但仅人面（I4）+ 标题确认门；无新凭据面。设计期通过。
- **约束审计**：铁律一（证据）——(None, REJECTED) 边、abandon 同事务置 ended_at、prune 确认门、run_op 写路径均有代码证据（引用属实）；铁律二（退役）——无过渡层；unarchive 非目标登记了零迁移后路（BCD §1 待澄清项 2）；铁律三（先例）——spec 引用的先例均为仓内既有实现，引用核实属实。

---

## 疑点待核

无。所有构造的反例要么成立（已列问题）要么被机制排除（已核代码），无停留在直觉层未闭合的怀疑。

## 残留（本审查新增登记）

无新增。spec §13 已登记 R1-R4（其中 R1/R3/R4 的落点问题见 P2-3）；BCD F4 误删残余为 user 已接受项。

## 未核区

- tests/ac_cases_a..e、i、j 未全文读（grep 了断言相关行 + 全文读了 ac_cases_g 壳断言段与 ac_cases_h prune 段）——spec 对它们无代码事实引用（AC8"回归绿"为测试运行声明，非引用）。
- lease.py、config.py、retry_limit.py、bench.py、docs/design.md 全文、ADR 0001-0004 全文、docs/ops/* 验证文档未读——spec 未对其作行为引用。
- "既有断言除壳契约同步项外零回归"（spec §10 末条）按 grep 证据成立，未实际运行全量 harness 验证（实施后由验收跑）。

## 核实过的关键代码事实（审查员侧证据锚）

- state_machine.py:19-30 ALLOWED_EDGES 无 ARCHIVED；:46-61 边校验 + rowcount；:63-66 清 marker 通规；:72 from=None 时 title "?" 形态。
- operations.py:87-112 new_requirement 不写事件；:157-188 approve 状态判定（e1 依据）；:342-376 abandon（claim_id 传入 transition + 同事务置 ended_at，371-375）；:380-435 claim_task（insert -> transition OPEN->CLAIMED -> 失败回滚）；:768-797 list_tasks 默认过滤硬编码 :781（P1-1 依据）；:953 PRUNE_TERMINAL_STATES；:976-980 prune 只删 events（P2-7 依据）。
- view.py:191 TERMINAL_STATES；:194-203 _terminal_entry_ts 用 TERMINAL_STATES 判别（spec"自然覆盖"声明属实）；:227 board 默认过滤硬编码（spec 行号属实）。
- api/requirements.py:116-118 GET /requirements 走 list_tasks（P1-1）；:131-165 SSE 纯事件驱动（P1-2 依据）；:74-75 POST /requirements 201。
- api/web.py:141-144 两 tabs；:396-409 人面操作区 7 按钮 + set_expectations（P2-1 依据：harness 无对应断言）；:438-485 doOp/handleOpResult 模式（spec"同款模式"声明属实）。
- cli.py:150-206 prune 确认门（y/N + --yes，P2-6b 依据）；:222-293 子命令全集（spec §7"既有命令零改动"清单属实，mcp 启动器未列但非操作命令）。
- mcp/server.py:139-153 12 工具注册（I4 结构保证属实；list_tasks 在其中 = P1-1 传播面）。
- db.py:62 foreign_keys=ON（delete FK 序有意义且 spec 序正确）；:150-172 run_op 单事务 + db_busy 重试（spec §4.3 并发声明依据）。
- models.py 无 state CHECK 约束（无迁移需求）；alembic baseline 同。
- tests/ac_cases_g.py:295-302 壳断言现状（board-root/detail-root/EventSource/零原始输出）；ac_cases_h.py:144-160 prune 既有钉死口径（P2-7 依据、delete CLI 非交互先例）。

---

## 折入记录（spec 作者，2026-10-26；非审者 verdict，verdict 以上述 APPROVE-WITH-FIXES 为准）

| 问题 | 状态 | 折入位置 |
|---|---|---|
| P1-1 list_tasks/GET /requirements 漏改 | closed | spec §5 终态集合单一事实源（operations_util.py）+ 连锁修复行 + §10 case 9 + AC3 |
| P1-2 SSE 假机制 | closed | spec §4.1 改"提交成功后主动重拉 loadBoard()" |
| P1-3 BCD×spec from 冲突 | closed（裁决案 A） | BCD Q3 裁决（user 委托主循环代裁，spec 审阅可推翻）+ BCD S2/E2 修订 + 修订记录；spec §3 保持 from=None（REJECTED 先例） |
| P2-1 壳断言勘误 | closed | spec §10 壳契约节重写为"新增缺席断言 + 在场断言" |
| P2-2 板面等待人 CLI 提示 | closed | spec §6.1 卡片横幅 + §10 case 8 双形态 |
| P2-3 残余登记落点 | closed | spec §9 加 docs/adr/0000-known-gaps.md 行（R1/R3/R4） |
| P2-4 旧定位措辞 + 冒烟项 | closed | spec §9 加 PRD §0 职责边界行 / design.md §0 / web.md 冒烟第 4 条 |
| P2-5 REOPEN 漏 | closed | spec §10 case 1 七状态 + AC2 |
| P2-6 claim_id / --yes | closed | spec §4.2 步骤 3 传 claim_id（abandon 先例）+ §4.4 delete --yes（prune 先例） |
| P2-7 整删措辞 | closed | spec §8 prune 语义零改动 + 两语境消歧 + §10 case 3/case 5 可观测断言（需求行在/不在） |
| 勘误 1（approve 拦截点） | closed | spec §3 改"approve 内部状态判定（operations.py:188 起）" |
| 勘误 2（CLI-only 措辞） | closed | spec §1 改"Web UI 移除、REST/CLI 保留" |
