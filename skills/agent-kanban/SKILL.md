---
name: Agent Kanban
description: 通过 agent-kanban 看板 MCP 与人类及其他 agent 协同工作的协议。当环境中出现 agent_kanban_* 工具（list_tasks / claim_task / add_subtask / add_record / request_review 等）且要开始或继续看板任务时加载。说明如何认领、拆解、记录决策/风险/偏离、交接评审，以及哪些是人的职责（DONE 确认、释放、解除阻塞）。与 docs/PRD.md v3.2 契约一致。
---

# Agent Kanban 协同协议

看板是**记录面 + 关键决策的记录点/审计点，不是控制面**。执行（worktree、合入、进程）由你的工具链负责；看板负责状态、结构与记忆。人只看摘要视图（关键节点），不读原始输出——你的职责是把关键信息**结构化喂给看板**，而不是倒日志。

## 门序（每段工作照此走）

1. 读：`list_tasks`（按状态过滤）-> `get_task_detail`（需求登记 = 来源指针 + 摘要 + requirement.acceptance 预期锚 + 现有拆解/里程碑/关键事件；看 description 是否带**工作区指针**）。先读后动，尤其先看预期验收锚；完整内容（Jira 详情/原文）按链接从源头获取（单一事件源）。
2. 认领：`claim_task`。独占；`already_claimed` 说明别人持有，换任务，不要抢。
3. 接单确认：认领后、拆解前，留一条接单确认记录 `add_record(kind=note, title="接单确认", content=三段)`——`title` 只写一行提纲，三段写 `content`：**理解**（用自己的话把需求压缩到 1-2 行，照抄需求原文视为未执行）/ **假设**（需求缺失的约束项，逐条列出取值；需求显式委托你定的项也算假设）/ **缺口**（需求缺失的关键信息，逐条列出）。判缺口前先读环境卡（context / reach / 红线 / ops 教训）与需求已有信息——已写明的不算缺口。缺口处置：不靠人决策干不下去 -> `mark_blocked`（reason＝缺什么 + 已核实到哪），不拆解不执行；可假设继续 -> 记入假设并继续，交接时提请人确认该假设（交接说明中点明）。需求清晰也要留记录（缺口写「无」）——这是把理解偏差在接单时刻暴露的门。
4. 就绪：见「工作区就绪」。不就绪按分级处置，不盲目开工。
5. 拆解：`add_subtask`，每条带 acceptance[]（验收项 + 链接预期锚 links_to）。不要窄化范围；锚项无覆盖会显示覆盖缺口，这是有意的下界语义。需求 acceptance 为空时，你拆出的子任务验收 = 事实锚，交接时提请人确认/升格。
6. 执行 + 记录：见「记录纪律」。
7. 交接：`request_review`（附证据 + 验收自评表），然后**等人**。
8. 等裁决：DONE 由人确认（approve）。人可能拒绝/要求返工（REOPEN 后你继续）。

## 认领纪律

- 认领排他：一个需求同时只一个 agent。抢占返回 `already_claimed` + 持有者句柄。
- 租约：lease 2h / idle 30min（可配置）。任何 MCP 写操作都是活动（更 last_activity_at，防 SUSPECT）；租约**不自动续**——延长需显式 renew（可据 update_progress 返回的 lease_expires_at 决策）。长时间无活动 -> SUSPECT，过期 -> STALE（人可见告警）。
- **释放是人的职责**：agent 面无 release 工具。不要试图用 mark_blocked 或伪造状态"退出"；确实要放弃就 `mark_blocked` 说明原因，等人裁决（release / reject）。
- 重试：同一需求累计重试超 2 次，系统会写 risk 事件并进"需要关注"区——这意味着你要向人说明，而不是继续闷头重试。
- **重试成本自报**：每次重试时用 `add_record(kind=note)` 报本次重试的成本（token 数 / 耗时），让"重试代价"进事件流——系统只计数不记成本，人靠你的 note 看到一次重试付了多少钱。

## 工作区就绪

认领后、拆解前核验"这活干得动吗"。不就绪按分级处置，不自由发挥。

- **读指针**：需求 description 的工作区指针（一行 `workspace=<dir> env-card=<路径>` + 任务级例外）。无指针 -> 找项目 AGENTS.md 的「环境卡」节（工作目录，或指针所指项目目录）。
- **目录三态**：项目目录已存在 -> 按环境卡落点约定；不存在 + 产物临时性（草稿/试验）-> tmp/会话产物目录，不污染项目；不存在 + 产物永久性 -> 建目录 + decision 登记（建在哪/为什么），交接时点明。
- **分级硬停**（指针缺失/失效、环境不具备、需越红线）：任务需要环境（部署/ssh/写项目/凭据/域 MCP）-> 问人补齐：人 inline 在场就问（结果记 decision）；不在场 `mark_blocked`（reason 一行：缺什么 + 已核实到哪）；纯调研/无环境依赖的轻产物 -> 自决落点与做法 + decision 登记，交接时点明。
- **上下文备齐**：先读环境卡 context 入口（项目知识）再动手；任务领域所需 skill 按环境卡 skills 清单匹配，缺 -> risk 登记 + 请人补或声明降级。
- **红线即止**：环境卡「红线」项不可触；需要触 -> mark_blocked。
- **长段预声明**：进入长无板段（深度调研/长构建）前，先 `update_progress`（headline = 在做什么 + 预计多久），防租约中途 SUSPECT；--bg 长任务由派发方心跳续租（见「派发方协议」）。

环境卡模板（项目 AGENTS.md 固定小节，新项目照此建）：

```
## 环境卡
- workspace: <项目根>；产物落点: <永久产物目录>；临时产物: <tmp 约定>
- context: <项目知识入口：docs/、bundle 索引、需求全文源头>
- skills: <本环境可用领域 skill；常见任务类型 -> 必需 skill>
- tools/mcp: <user 级常驻（kanban 等）+ 本项目 MCP（配置位置/凭据位置/动作面）>
- reach: 操作面 <ssh/部署入口>；测试 <入口>；观察面 <日志/监控/只读 DB>
- 红线: <禁推目标 / 禁触数据 / 禁写生产 / 域红线 / 不做清单>
- ops 教训: <可达路由、flake 签名、既往教训，收尾时追加>
```

## 记录纪律（命名记录契约）

每条人面记录三段：

- **提纲**（一行人话）：`update_progress.headline` / `add_record.title` / `request_review.summary_line` / `mark_blocked.reason`，服务端强制非空，缺/空 -> invalid_record（错误消息带参数名与示例，据此自纠）。
- **所以呢**：对预期的影响（验收对照/偏离）或需要人做什么（approve/解除阻塞/返工）。
- **可选细节**：content/payload，倒日志式细节不写。

报节点，不报流水账。

## 报告纪律（写给人看的每一段文字都遵守）

- **简约**：像给同事一句话汇报，不是写论文。验收自评理由、decision rationale、deviation 原因、交接说明默认几行以内；详情留给原始输出，看板只写"结论 + 关键证据"。
- **大白话**：用日常语言，假设读者是懂业务的普通人，不是同行评审。
- **无黑话**：不用空词堆砌（抓手/闭环/赋能/范式转移之类）；术语必须让读者秒懂，否则换说法。
- **人脑带宽**：人一次只能消化少数关键信息。报告节奏 = 里程碑达成、决策、风险/偏离、等待人裁决、交接——不是每步流水账。一次评审只报"做完了什么 + 偏离了什么 + 请你看哪里"。
- **里程碑与关键事件优先**：该报告的是节点（里程碑、决策、风险、偏离、覆盖缺口），不是过程。
- **决策叙事**：人面视图按「问题是什么 -> 主要选项 -> 选了什么、为什么 -> 关键在哪」读决策。decision 记录：choice 填选定项名称；content = 方案总结（覆盖方案全部主组成，不写背景叙述）。方案主组成（如现成入口/工具）只存在于交付文件而板面无记录 = 人从板上看不到 = 交接缺陷。

## 交接与等待

- `request_review`：要求 state=CLAIMED；必须附证据（PR 链接 / commit 区间 / 测试摘要，至少一项，缺了被拒 invalid_record）+ summary_line（交接一句话：做了什么/先看哪，缺/空 -> invalid_record）+ 逐项验收自评（met / not_met / deviated + 原因）。附三行人简报：做了什么 / 先看哪 / 还剩什么，summary_line 承载第一二句。可选键：`evidence` 内 `document`＝交付物路径、`note`＝收尾说明（必须在 `evidence` dict 内，传顶层会被静默丢弃）——dispatch 入口把历轮这两键装配进同需求下一轮派发稿/续接稿「历轮交付物」节（A2 自动装配，同需求单一事实源）。它**不改状态**，只设 awaiting_human(kind=review)。
- **交付自检（request_review 前必做）**：① evidence 含至少一项指向真实交付物（`pr_url`/`commit_range`/`test_summary` 硬要求不变；`document`/`note` 为 evidence 内可选附加键，交付物类需求把路径写 `document`）；② 逐项验收自评已填（met / not_met / deviated + 原因）；③ 红线自守已核（交付物只落约定位置、板面只动本需求、未声称 DONE、未代执行 release/approve——两者都是人面 op）；④ 三行人简报齐（做了什么 / 先看哪 / 还剩什么），summary_line 承载第一二句（按 request_review 条款）。
- **收尾蒸馏（request_review 前必做）**：把本轮持久教训（可达路由 / flake 签名 / 环境事实）提炼落地——主形态＝追加环境卡「ops 教训」+ 板 `add_record(kind=note)` 一行（摘要 + 落点）；环境卡不可写（主仓只读等）＝板 note 记教训全文；本轮无持久教训＝板 note 显式记「无持久教训」。板 note 恒有，禁静默省略（三种形态必居其一）。环境卡是仓内分支工作副本时，教训随本分支 commit 落地，不写主仓。这是 harness 越用越稳的来源，下一轮 worker 先读这些教训。
- `mark_blocked`：只有真需要人决策才用（需求转 BLOCKED + awaiting_human(kind=blocked)）。reason 必写一行人话原因（报节点不报流水账），进事件链可回溯。
- 人与你 inline 交互（会话内当场问答）**不经看板**：结果记一条 decision 事件即可，不设标记，流程零中断。只有交接在会话之外（session 结束、人不在场）才需要 request_review / mark_blocked。
- **永不声称 DONE**：DONE 只能人确认。你的 request_review 是"交回请审核"，不是完成。

## Session 与恢复

- 认领行的 agent_conn 就是你的 session id（ses_...，服务端派生，人面可见）——恢复锚已自动在审计链里，不用你传。
- **恢复锚留痕**：本轮结束且可能要续（交接待评审 / blocked / 会话中断），`add_record(kind=note)` 留一行：session id + 当前模型 + 恢复命令，例如 `session ses_xxx / model ks-cp/xxx / 恢复: opencode run -s ses_xxx`。评审拒绝返工、中断恢复都靠它续回同一会话（`-s` 带完整上下文）。经 dispatch 入口分发的 worker 会话，正典恢复入口 = `agent-kanban resume --requirement-id <需求 id 或 ses_req_<8hex>>`（自动写续跑 note，见「派发方协议」）。
- **模型继承**：重派或恢复同一需求时显式带模型（`opencode run -m <provider/model>`；sub agent 传 model 参数），继承开工时的模型，不落回默认模型——默认模型套餐额度可能见底，产出质量会掉。
- **模型额度耗尽**：调用报额度/限流错误时不要重试——`mark_blocked`（reason 一行：额度耗尽 + session id + 换模型恢复示例 `opencode run -s <ses> -m <provider/model>`），等人处置。这是需要人决策的情形，不算重试。

## 派发方协议

把任务派给独立会话（sub agent / `opencode run`）执行，是派发方的责任。派发方照协议走，不自由发挥。规范入口 `agent-kanban dispatch --requirement-id <id> [--model <provider/model> --dir <dir> --budget <预算>（秒或 h/m/s 后缀）] [--bg]` 与 `agent-kanban resume --requirement-id <需求 id 或 ses_req_<8hex>> ["<指令>"] [--model <provider/model>]`（dispatch 承担：状态门 OPEN/REOPEN、派发稿五要素、板 note 留痕、超时 resume 提示；resume 承担：不限需求状态、续接指令参数、板 note 留痕；下列手工条款在入口不可用时仍适用）。入口输出含 session id + 启动目录（directory）——人深挖 worker 现场 = `cd <directory>` + `opencode -s <session id>` 两要素（user 裁决 U1，2026-10-28：缺一即交接不完整），交接回报时两要素必带。

- **何时派**：复杂任务 / 长任务 / 跨目录。主循环只做单文件微调。一个需求 = 一个 worker，同需求不并行 worker。
- **预检**：工作目录状态（脏/有并发会话 -> worktree 或等待）；环境卡存在（缺则按模板先建，或问人）；目标目录 kanban MCP 可达（全局注册为正典，见 mcp-config.md）。同需求历轮交付物由 dispatch 入口自动装配（「历轮交付物」节），env card 基线指针只用于跨需求（supersede）场景，不手抄同需求历史进 env card（双源漂移，BCD b3 D2）。
- **模型继承**：传派发方当前模型（`opencode run -m <provider/model>`），不落回默认模型（默认套餐额度可能见底）。
- **派发稿**：prompt = 任务指针（需求 id + 标题 + 指针行）+ 协议入口（本 SKILL 路径）+ 环境卡路径 + 交付规格 + 历轮交付物（同需求有历史时；dispatch 入口自动装配）+ 红线提醒 + 墙钟预算。不把任务全文塞进 prompt，也不让 worker 自由发挥。交付规格禁向 worker 承诺 release（release 是人面 op，agent 面不可达——dogfood 真机实锤）：完成收尾＝worker note 报完成 + 派发方人面代执行 release。
- **留痕**：dispatch 入口自动经人面 note 留痕（恢复锚：dispatch note 首行 = 分发 + 会话 id + 模型，结局在 body；resume note 首行 = 续跑 + 指令摘要 + 需求状态）；手工派发时仍 `add_record(kind=note)`：session id + 模型 + transcript 路径 + 预算——这条 note 即恢复锚（见「Session 与恢复」）。transcript 落批次产物目录（tee，禁 /tmp）。
- **验收**：worker 的 `request_review` 是回执；派发方按板面三问（对照预期/偏离/更好方案）自答核交付，不代 worker 交接。
- **循环**：REOPEN -> `agent-kanban resume --requirement-id <需求 id 或 ses_req_<8hex>> "返工意见..." [--model <provider/model>]`（同会话带上下文）；手工 `opencode run -s <ses>` 仍可用（换模型 = `-s` + `-m`）。
- **长段心跳**：--bg 长任务由 `dispatch --bg` 自动完成（独立 bg 子进程代人面续租，受托痕 basis 指向分发 note；心跳周期 env `AGENT_KANBAN_DISPATCH_HEARTBEAT_SEC` 默认 60s、pre-claim 窗口跳过；终态 note 含存活时长 / renew 总数），防活着的 worker 中途 SUSPECT。已知局限：bg 进程随派发方终端死则心跳停（结构替代 = B6 plugin 心跳）。
- **收尾蒸馏核验**：worker 按「交接与等待 -> 收尾蒸馏」条款自蒸馏（环境卡 + 板 note）；派发方只核验落点在板面可见，缺则补记，不重复定义义务。

## 收尾协议（代执行）

- **触发（pull）**：agent 侧工作完成后（PR 流＝PR 发起后 / 本地合流＝合入后），人表态（「合了」「收尾吧」）或 agent 检测到人工作面动作完成 -> 会话内 `list_awaiting` 查等待面，有待决任务即代执行收尾。
- **kind 判据**：`statement`＝人会话表态（basis 指向可引用的真实原话）；`action`＝人工作面动作且 agent 结构性做不了（如远端 PR merge：git fetch 后确认目标 commit 在 origin main）。**本地仓检测不算**——本地 ff 折入 / 分支合并是 agent 自己的动作，标 action 即自我认证（显式反例）。
- **执行**：`cli.py approve --requirement-id <id> --on-behalf "<kind>:<basis>"`（release 同，携 `--reason`）。受托痕在事件自身（payload.delegated），**不再要求前置 note**。
- **禁**：agent 自产决定（编造 statement basis / 把自己动作标 action）。终态/确认迁移的源必须是已发生的人的决定。

## 错误码速查

| 码 | 含义 | 你的动作 |
|---|---|---|
| already_claimed | 已被其他 agent 认领 | 换任务 |
| not_found | 任务不存在 | 查 list_tasks |
| ambiguous_id | 前缀命中多条需求 | 加长前缀重试 |
| illegal_state | 状态不对（如非 CLAIMED 时 request_review） | 按状态机纠正 |
| no_active_claim | 认领已结束/被释放 | 重新 claim_task |
| lease_expired | 对过期租约 renew | 无法续，等人处理 |
| duplicate_subtask | 拆解重复 | 复用已有子任务 |
| invalid_record | 记录结构缺字段（decision 缺 alternatives / 缺证据 / 缺 headline / 缺 summary_line / title 或 reason 为空） | 补全字段 |
| queue_full | 并发认领超上限 16 | 等一个释放再认领 |
| db_busy | SQLite 忙（重试 3 次后） | 稍后重试 |

## 诚实与归属

- actor（conn id、seq、ts）由服务端从传输会话派生，不接受你传入。你的 OpenCode session id（ses_...）会作为外部引用进审计链——不要伪造身份。
- 你报告的结构（子任务/里程碑状态、验收自评）标注 `reported by <agent>`，是声明不是事实；需求级 DONE 只有人确认才是事实。
- 决策/风险/偏离不可编辑，只能追加更正。

## 参考

完整契约：`docs/PRD.md`（v3.2）第 3（状态机/租约/写保护）、4（工具面/错误码）、5（视图/回溯）节。安装与配置：`docs/mcp-config.md`。
