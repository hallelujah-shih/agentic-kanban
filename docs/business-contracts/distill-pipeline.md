# Business Contract: distill-pipeline 记录管线蒸馏重构

**作者**: 主循环（distill-pipeline 批）
**日期**: 2026-10-27
**关联**: docs/PRD.md §0（定位/反淹没/报告纪律）§4.1（MCP 工具面）§4.3（错误码）§5.3（视图原则）§5.4（回溯判据）；docs/web.md（前端契约）；skills/agent-kanban/SKILL.md（agent 侧协议）；系统级全量审查结论（2026-10-26，本批起点）
**状态**: v1 五项已裁决（2026-10-27 user 均按推荐）；P1 plan 可开工

---

## 1. 客户原话语义分析

### 客户原话（未解读，2026-10-26/27 对话原文）

> 前端展示面向人、经深思熟虑，「要有好的前端设计语言、好的信息展示哲学」，「要有优秀的审美，而不是简单堆砌」。
>
> 「人每天的时间、精力、大脑带宽极其宝贵、有限——从数据的产生、存储、展示各个层面考虑，面向的是人，不是机器」。
>
> 「从新 review 整个系统，看哪些需要深度重构，包括 mcp 和 skill，特别是 skill，会严重影响质量」。

（本批起因的第一 bug：agent 经 `update_progress` 写的进度备注在板上看不到可读形态——事件 title 恒为常量 "progress"、note 内容只落在 payload 且被摘要排除，深潜页只渲染 title 行。）

### 可能的解读（互斥，业务目标分歧）

| 解读 | 客户真实期望 | 证据 | 证据强度 |
|---|---|---|---|
| A. 展示层美化 | 主要不满在 web 深潜页「平铺同级盒子、零层级」——只修人看到的页面（R4） | 「优秀的审美，而不是简单堆砌」指向页面观感 | 客户原话 |
| B. 写侧契约重构 | 主要不满在「agent 写的记录质量低、不可读」——修契约与 skill（R1+R2），展示顺带 | 「从新 review 整个系统，包括 mcp 和 skill，特别是 skill，会严重影响质量」 | 客户原话 |
| C. 全管线蒸馏架构 | 蒸馏恰好发生一次、在生成点（成本最低质量最高），存储/展示「忠实不聪明」；契约/skill/存储/展示是一个设计贯穿三层（R1-R4） | 「从数据的产生、存储、展示各个层面考虑」逐层点名；「看板价值＝替人蒸馏，直接看代码仓库更好」反复强调 | 客户原话 + 审查佐证 |

**互斥对**：A vs C（根因归因：展示 bug vs 管线架构缺陷；A 的交付是 C 的子集，只修展示则生成端继续倾倒低质量记录，展示层无米下锅）；B vs C（是否动存储层 R3：B 不改 audience 分类/severity 当真/最新优先，展示层分级拿不到数据支撑）。

### 我的解读

**C**。理由：(1) 客户原话逐层点名「产生、存储、展示」，不是单指页面；(2) 系统级全量审查证明展示层平铺是症状、根因在生成点（写契约把提纲通道焊死：update_progress title 常量 operations.py:717、skill :33 把 agent 引向 update_progress 而绕过唯一可自写提纲的 add_record.title）——只修展示，「关键信息」不存在；(3) 客户反复强调「看板价值＝替人蒸馏」，这是管线级原则而非页面级诉求。

### 待澄清项（已裁决，2026-10-27 user 五项均按推荐）

1. **update_progress 处置**（与挂账 A2 交叉）：
   - (a) **推荐**：保留工具 + 加**必填** `headline` 参数（人面一句话提纲）。缺 headline 的旧式调用返回 `invalid_record`，错误消息指明修法。progress_note kind 保留，展示层归类「过程备注」（事件流默认显示提纲行，点开全文；不进摘要关键节点区）。
   - (b) 保留工具 + headline 可选（缺省取 note 首行——服务端做结构截断，不生成语义）。
   - (c) 退役工具并入 `add_record(kind=note, title=提纲)`（单向门：移除工具，现成调用报错）。
   - 分歧：(a) 一次性跨单向门把「人面记录必带提纲」焊死，agent 无法退回旧形状；(b) 留了退路，第一 bug 可能复发；(c) 契约破坏成本最高，且丢失 progress_note 独立 kind（展示层无法再区分「进度备注」与「一般笔记」）。
   - **user 裁决（2026-10-27）：(a) 保留工具 + 加必填 headline 参数**。缺 headline -> invalid_record（错误消息带新参数名与示例）；progress_note kind 保留，展示层归类「过程备注」。
2. **queue_full 上限 6 vs 16**（正典冲突 1）：PRD §4.3:196 写「(6)」，PRD §6:258 写 16，AC8:346 写「第 17 个 claim_task -> queue_full」（即 16），代码 db.py:22 `MAX_ACTIVE_CLAIMS = 16`，SKILL.md:63 写 16。推荐：16（四源一致，§4.3 为笔误），本批改 §4.3，上限本身不变。**user 裁决（2026-10-27）：16 定案；PRD §4.3 笔误本批修正，上限不变。**
3. **get_task_detail「关键事件」口径**（正典冲突 2）：PRD §4.1:151 声明返回「关键事件」，实现取**最旧** 200 条（operations.py:878-881 `order_by(Event.seq)` ASC + `limit(200)`，:938 `event_limit=200`）——超过 200 条事件的需求丢最新。推荐：按文档意图实现为「事件自带提纲（生成点写）+ **最新优先**（有界）」，不做读侧语义挑选（读侧挑选＝第二个蒸馏点，违反「蒸馏恰好一次」）。**user 裁决（2026-10-27）：此口径定案。**
4. **反淹没原则缺三层管线框架**（正典冲突 3）：PRD §0 有反淹没 + 报告纪律，但无「蒸馏恰好一次在生成点、存储/展示忠实不聪明」的框架表述。推荐：本批在 PRD §0 补入该管线原则（本次重构的北极星，不写进正典则后续批次无依据可依）。**user 裁决（2026-10-27）：本批写入 PRD §0。**
5. **web.md:29「事件流只渲染标题行」**（正典冲突 4）：文档把 title-only 渲染固化为意图，与新设计「提纲优先、点开看全文」冲突。推荐：本批改为「提纲优先（title=提纲），点开展开 content，默认收起；原始输出（run_logs/会话原文）仍不默认展示」——与反淹没一致（展开的是 agent 写侧已蒸馏的文字，非原始输出；数据模型仍无 run_logs 表）。**user 裁决（2026-10-27）：本批改新设计。**

---

## 2. Impact Mapping

### Why（业务目标）

目标＝人分钟级看板即可答出三问（对照预期验收 / 是否有偏离 / 是否有更好方案），且只在需要人时打扰人；看板价值＝替人蒸馏。**不是**全量日志查看器（要全量直接看代码仓库/会话原文），**不是**展示层美化工程（美化无米下锅）。

### Who（受影响方）

1. **人（需求持有者）**：日常注意力消费者——默认只见关键节点（决策/风险/偏离/验收对照/等人裁决），事件流提纲优先、点开看全文。
2. **agent（写侧）**：MCP 工具面契约变化（提纲必填、工具自描述、交接一句话），所有写此看板的 agent 须按新记录契约；skill（R2）是主载体，MCP description + server instructions 是带内兜底（威胁模型 B：不依赖带外 skill 被加载）。
3. **未来审计者**：审计链必须完整——蒸馏是展示层挑选而非存储层删改；export 全量不变；blocked 原因/交接一句话进追加链（可回溯）。

### How（影响路径）

1. R1（契约，单向门，最先定）：MCP 工具面自描述（12 工具 description 现全空 + 无 server instructions，server.py:136-154）；headline 作人面提纲原语（update_progress.headline 必填 + add_record.title 写侧强制）；request_review 加「做了什么/先看哪」一句话（现只有 3 固定证据字段，operations.py:724-759）；mark_blocked 原因进追加链（现只存可变 `awaiting_human.reason`，转移即抹，operations.py:817-820）。
2. R2（skill，与 R1 共同设计）：命名记录契约（提纲 -> 所以呢 -> 可选细节）；每条人面记录必写提纲；交接/阻塞重述为「三行人简报」；砍操作机制篇幅（机制由 MCP description 承载，skill 不再重复）。
3. R3（存储）：kind -> audience 分类单点派生（纯派生函数，不加列；现状各读点字符串匹配 kind + payload 形状）；severity 当真用（review_request 现恒 info，operations.py:754，应 >= attention）；title 变 agent 写的提纲（全量审查计数：15 个事件写点 12 个 title 为常量/函数名）；两个 detail 组装器合并（view.py detail 与 operations.py `_requirement_detail` 双源）；get_task_detail 最旧 200 -> 最新优先（有界）。
4. R4（展示，基于 R3 数据）：深潜页三层结构＝蒸馏先行（决策/风险/偏离/验收对照主线）-> 叙事（事件流，提纲优先、点开全文）-> 簿记退背景（state_change/decomposition/reconcile/租约类）；真字阶层级 + 按「此刻需不需要人」分级；杀掉平铺同级盒子；保留既有配色/token（不重造视觉语言）。

### What（具体交付物）

1. R1：server.py 12 工具 description + server instructions；operations.py update_progress / request_review / mark_blocked 契约变更；PRD §4.1 同步 + §4.3 笔误修正（6->16）。
2. R2：skills/agent-kanban/SKILL.md 记录纪律节改写（提纲契约 + 三行人简报 + 篇幅削减）。
3. R3：operations.py（title 通道 + severity + audience 派生函数 + detail 组装器合并 + 最新优先）；view.py 同源；PRD §5.3 同步。
4. R4：web.py 深潜壳（三层结构 + 提纲优先展开 + 层级）；docs/web.md 同步（:29 改 + 冒烟 checklist 更新）。
5. 测试：e2e 深潜页断言按新契约扩展（基线 12/12 不回退）；audience 分类/severity/最新优先单测；旧数据兼容 harness（旧形状事件不崩新展示）。
6. 正典同步：PRD §0 补管线原则（正典冲突 3）、PRD §4.1 关键事件口径（冲突 2）、PRD §4.3 笔误（冲突 1）、web.md :29（冲突 4）。
7. 本 BCD + 5 项裁决记录（修订记录节）。

---

## 3. Domain Event 流

### Domain Events（按时间顺序）

事件 kind（12 个）不变：progress_note / decision / deviation / review_request / approval / note / risk（人面）+ state_change / decomposition / reconcile / release / renew（簿记）。本重构改三个事件的**语义**（payload 形状只增不改）：

1. `progress_note`：title = agent 写的 headline（一句话提纲），content = 详情全文（旧形状：title 常量 "progress"，note 双写 content + payload.note）。
2. `review_request`：payload 增「做了什么/先看哪」一句话（人面简报），evidence 三字段（pr_url/commit_range/test_summary）不变；severity 从恒 info 改为 >= attention（它正是「需要人」的信号）。
3. `mark_blocked` 转移：reason 写入事件链（追加、不可抹；现只落可变 `awaiting_human.reason`，approve/release 清 marker 即无痕）。

其余 9 个 kind 的 payload 形状不动（范围纪律）。

### Commands

1. `update_progress(requirement_id, note, headline)`（R1，headline 必填——已裁决 (a)）：写 progress_note（title=headline，content=note）。
2. `add_record(requirement_id, kind, title, ...)`：title = agent 写的提纲（现有参数；本批变为写侧强制纪律 + 服务端非空结构校验）。
3. `request_review(requirement_id, evidence, assessments, summary_line)`：summary_line = 「做了什么/先看哪」一句话，进 payload + awaiting_human 展示。
4. `mark_blocked(requirement_id, reason, ...)`：reason 进追加链（事件）+ awaiting_human（现行设置）。
5. 其余 8 工具：签名不变，仅补 description（自描述带内兜底）。

### Aggregates（业务边界）

**Requirement**（事件链＝append-only 事实链）是唯一聚合，不变。新增派生视图：kind -> audience 分类（人面/簿记）为纯派生函数（单点定义，所有读点同源），不加列、不加表。

### Policies（含隐含 Policy）

1. **蒸馏恰好一次，在生成点**：写契约强制提纲（服务端校验结构——非空、长度上限；语义质量是写侧责任，服务端不生成人面文字）；存储/展示层忠实不聪明——不二次摘要、不做读侧语义挑选。
2. **追加链不被蒸馏破坏**：蒸馏＝展示层挑选（排序/收起/层级），不是存储层删改；export 全量不变；PRD §5.4 回溯 5 判据全部仍可回答。
3. **severity 当真用**：review_request / risk / deviation = 需要人（>= attention）；progress_note / note / 簿记类 = info。摘要关键节点区只呈现 >= attention 的人面 kind（deviation 强制 >= attention 既有规则保留，5.3）。
4. **人/机分类单点同源**：audience = 派生函数(kind)，唯一定义；读点（board/摘要/深潜/SSE/export）共用；禁止现状「各读点字符串匹配 kind + payload 形状」。
5. **隐含 Policy：旧数据容忍**——存量事件（title="progress"、note 在 payload、review_request severity=info 无简报）不得使新读面崩溃；展示按形状降级（无提纲 -> 显示 kind 标签 + content 或占位）。不迁移存量数据。
6. **隐含 Policy：工具面兼容边界**——MCP 工具面是单向门：本批「只增不删」（加参数、加 description、加 payload 字段），不删工具（待裁决 1 的 (c) 不推荐正因此）；单向门跨过之后，「人面记录必带提纲」是长期契约，skill / MCP description / PRD 三处表述必须一致（防止带内外漂移复发）。
7. **隐含 Policy：展示分级＝「此刻需不需要人」**——必看（等人裁决/风险/偏离）> 应看（决策/里程碑/验收对照）> 深潜才看（进度备注/簿记）。分级由 kind + severity 派生（同源、可审计），不做内容判断。

---

## 4. BDD Given-When-Then 场景

### Scenario 1（happy path：带提纲的进度）
- Given: 需求 CLAIMED，agent 执行中
- When: agent 调 `update_progress(note="修了 test_view.py 的竞态，加了锁", headline="修了 test_view 竞态")`
- Then: 事件链新增 progress_note（title="修了 test_view 竞态"，content=全文，severity=info）；深潜页事件流默认显示提纲行、点开看全文；摘要关键节点区不出现该项（进度备注不进摘要）

### Scenario 2（happy path：交接简报）
- Given: 需求 CLAIMED，工作完成
- When: agent 调 `request_review(evidence={pr_url:...}, assessments=[...], summary_line="重做了记录管线，先看你熟悉的事件流新 title 字段")`
- Then: awaiting_human(kind=review) 设置；事件链 review_request payload 含一句话且 severity>=attention；板等待卡片/深潜等待横幅显示该一句话（人不用进深潜就知道「做了什么/先看哪」）

### Scenario 3（happy path：阻塞原因可回溯）
- Given: 需求 CLAIMED
- When: agent 调 `mark_blocked(reason="等 user 裁决 queue_full 上限")` -> 后 human approve 回 CLAIMED（清 marker）
- Then: 事件链存在含 reason 的事件（追加、不可抹）；marker 清除后，人/审计者仍可由事件链回答「当时为什么阻塞」（回溯判据 3）

### 边缘场景 1（旧形状数据容忍）
- Given: 存量事件含旧 progress_note（title="progress"，note 在 payload）与旧 review_request（severity=info，无一句话）
- When: 人打开看板/深潜页/export
- Then: 不崩溃、不白屏；旧形状事件降级展示（提纲位显 content 或 kind 标签）；export 全量不缺

### 边缘场景 2（提纲契约强制）
- Given: 需求 CLAIMED
- When: agent 调 `update_progress` 不传 headline；或 `add_record(kind=note, title="")`
- Then: 均返回 `invalid_record`，消息指明「人面记录需一句话提纲」（带新参数/字段名与示例）；不写任何事件（同事务，无半态）

### 边缘场景 3（最新优先有界）
- Given: 需求有 500 条事件
- When: `get_task_detail`（event_limit=200）
- Then: 返回**最新** 200 条（含最新一条；排序方向口径由 plan 钉死）；export / event_limit=None 仍返回全量 500 条

### 边缘场景 4（配置变更时场景）
- Given: 本批不引入配置项（audience 分类为派生函数非配置；并发上限 16 不变）
- When: （无配置变更面）
- Then: 记录为「无配置变更面」；若未来 audience 分类可配，存量事件重分类语义需单独评审

### 跨时段场景（存量审计链）
- Given: 生产 DB 已有完整事件链（既有审计资产，只读侦察确认存在）
- When: 新版代码读旧链（看板/深潜/export/回溯 5 判据）
- Then: 全可读、不缺失（强不变量 1/5）；旧链「关键事件」无提纲、展示降级但链完整——重构不断审计连续性

---

## 5. Spec by Example

### 例 1（进度备注：旧 vs 新）
- 输入: `update_progress(note="修了 tests/test_view.py 的竞态，加了锁", headline="修了 test_view 竞态")`
- 操作: agent 报进度
- 预期: 旧行为（第一 bug）：事件 title="progress"，摘要排除，深潜页只渲染 "progress" 一行，note 在 payload 不可见；新行为：事件流显示「修了 test_view 竞态」，点开看全文

### 例 2（decision：title 从常量到提纲）
- 输入: `add_record(kind=decision, title="选型 SQLite WAL 而非 busy 重试", content="...备选与拒绝理由...", payload={alternatives:[...], rationale:...})`
- 操作: agent 记决策
- 预期: 旧：title 为服务端常量，人看到一行常量；新：人看到 agent 写的「选型 SQLite WAL 而非 busy 重试」，点开看 rationale 全文

### 例 3（交接：一句话）
- 输入: `request_review(evidence={pr_url:"..."}, assessments=[...], summary_line="重做了记录管线，先看你熟悉的事件流新 title 字段")`
- 操作: 交接评审
- 预期: 等待卡片头 = summary_line；evidence 三字段照旧（PR/commit/测试摘要，至少一项，缺了 invalid_record 不变）

### 例 4（阻塞：原因进追加链）
- 输入: `mark_blocked(reason="等 user 裁决 queue_full 上限，6 还是 16")`
- 操作: 阻塞 + 等待
- 预期: 事件链有 reason（state 转移后不抹）；awaiting_human.reason 同文本（现行设置 + 事件双写，事件侧为审计侧）

### 例 5（旧数据：重构前的进度事件）
- 输入: 存量事件 `{kind: progress_note, title: "progress", content: "开始重构", payload: {note: "开始重构"}, severity: info}`
- 操作: 人打开新版深潜页
- 预期: 不崩溃；提纲位降级（显 content 或 kind 标签），点开仍见全文

### 客户期望 vs 系统行为差异表

| 场景 | 客户期望（PRD/原话） | 系统行为（现实现） | 冲突性质 | 差距 |
|---|---|---|---|---|
| 默认视图关键节点 | §0 反淹没：默认视图只展示关键节点（里程碑/决策/风险/偏离/等待/覆盖缺口） | 深潜页平铺同级盒子零层级；事件流垫底且 title-only；「关键信息」本身质量差（title 常量） | **根本性业务冲突** | PRD 说「看板替人提炼」，系统实现「全量倾倒+截断」——方向相反：不是展示太多，而是该展示的关键信息不存在/不可读 |
| 提纲通道 | SKILL.md:8「把关键信息结构化喂给看板，而不是倒日志」；§0 报告纪律「报节点不报流水账」 | update_progress title 常量 "progress"（operations.py:717）；15 写点 12 个 title 常量/函数名；skill :33 把 agent 引向 update_progress（唯一可自写提纲的 add_record.title 被绕过） | **根本性业务冲突** | 客户期望「每条人面记录有一行人话」，系统契约把该通道焊死——第一 bug 的根因 |
| 关键事件 | PRD §4.1:151 get_task_detail 返回「关键事件」 | operations.py:878-881 取最旧 200（丢最新） | 语义冲突（文档声明未实现） | 「关键」由生成点提纲 + 最新优先表达，不做读侧挑选（已裁决） |
| 工具自描述 | agent 应带内知道工具语义/记录怎么写（威胁模型 B：不押带外） | server.py:136-154 12 工具 description 全空、无 server instructions；唯一载体是带外 SKILL.md（不加载/换 harness -> 零契约） | 业务规则冲突（质量押在带外） | MCP description + server instructions 自描述（R1） |
| 阻塞原因回溯 | §5.4 回溯判据 3「谁在什么时候做了什么」 | mark_blocked 原因只在可变 awaiting_human（operations.py:817-820），转移即抹，事件链无痕 | 业务规则冲突 | reason 进追加链（R1） |

---

## 6. Premortem（假设 6 个月后失败）

### 失败原因 1（业务规则维度）：skill 纪律改变不了 agent 行为，提纲契约在写侧失守
- 失败序列: skill 是带外载体——agent 环境没加载新 skill（新 harness / 旧安装 / skill 未触发）-> agent 仍写旧形状（或不写 headline）-> 人面视图新旧混杂，「提纲」契约对相当比例写侧无约束力 -> 人觉得「还是乱」，弃用看板。
- 预防: R1 的 MCP 工具 description + server instructions = 带内兜底（工具面自己告诉 agent 怎么记录，不依赖 skill 加载）；服务端结构校验（headline/title 非空）让旧形状直接报错（agent 被迫纠正，错误消息带修法）；skill 只承载深度协议（三行人简报/报告节奏）。
- 残余: 提纲的语义质量（简约/大白话/无黑话）仍依赖写侧自觉——结构有保证、语义无（威胁模型 B 既有边界，known-gaps G2，不假装解决）。

### 失败原因 2（跨边界语义维度）：单向门跨错一步——现成调用断裂或新契约漏风
- 失败序列: update_progress headline 必填（已裁决 (a)）-> 现成 agent 调用（旧 skill 版本 / 其他 harness 的 prompt 硬编码旧签名）报错 -> agent 流程中断且不知如何修 -> 看板变负资产；或反向：可选 + 兜底留了退路，旧 bug 复发，契约形同虚设。
- 预防: 错误消息指明修法（新参数名 + 示例）；skill 与 MCP description 同批同 PR 发布（两处载体一致，防带内外漂移）；旧形状容忍（强不变量 5）保证已写旧数据可读；裁决先于实现（本批已执行：BCD 五项裁决后才进 plan）。
- 残余: 真正的第三方（非本 user 环境）调用方不可见——单用户系统，接受（PRD §0.1 不做多用户）。

### 失败原因 3（技术但具体）：深潜页 JS 膨胀破坏 e2e 基线/canary
- 失败序列: R4 提纲优先展开 + 三层结构 + 字阶层级增加内联 JS -> 既有 e2e 12/12 断言（绑旧壳 DOM 形状）逐条红 -> 为凑绿改断言镜像新实现（违反 Q1/Q2/Q3 纪律：断言应跟契约不跟实现）-> e2e 退化为自证，canary（f764794^ 历史坏壳）判别力失效。
- 预防: 不加新依赖（内联 JS 壳形态不变）；e2e 断言按新契约（docs/web.md 修订版）与 plan 同写，不在实施期补；canary 用例复验「旧坏壳仍红」（判别力声明入结果审）。

### 失败原因 4（业务规则维度）：「关键事件」做成读侧语义挑选，第二蒸馏点复发
- 失败序列: 为「好看」，get_task_detail/摘要实现「关键事件挑选」算法（按关键词/长度打分）-> 读侧蒸馏与写侧蒸馏漂移（同一条记录写侧判重要、读侧被滤掉）-> 人发现「我写的记录不见了」，审计链信任破裂。
- 预防: 已裁决钉死「提纲 + 最新优先，不做读侧语义挑选」；Policy 1（蒸馏恰好一次）升强不变量；e2e/单测含反向判别用例「低 severity 但真实的事件不被读侧过滤掉」。

---

## 7. 业务不变量

### 强不变量（违反即业务失败）

1. **蒸馏是展示层挑选，不是存储层删改**（追加链不被蒸馏破坏；export 全量不变；回溯 5 判据全部仍可回答）。违反后果：生产审计链损坏，C7 回溯判据失效，看板失去「可回溯审计资产」定位。
2. **蒸馏恰好一次，在生成点；存储/展示层忠实不聪明**（不二次摘要、不做读侧语义挑选、服务端不生成人面文字）。违反后果：两个蒸馏点漂移，质量沿链路衰减，第一 bug 的根因模式复发。
3. **人面记录必带提纲**（update_progress.headline / add_record.title；服务端结构校验非空）。违反后果：「一行人话」通道失守，人面退回常量/流水账，重构目标不达成。
4. **状态机/租约/写保护/单写者 seq/同事务内核不动**（范围纪律）。违反后果：核心正确性受波及，重构爆炸半径失控（本批档位判定以该边界为前提）。
5. **存量数据与现成调用可读**（旧形状事件不崩新读面；工具面只增不删——已裁决 (a)：保留工具加必填 headline，不删工具）。违反后果：生产审计资产不可读，或现成 agent 调用报错。

### 软约束（违反可容忍）

1. **保留既有配色/token**（不重造视觉语言）。违反后果：与看板页视觉一致性破坏、改面扩大；容忍但不值得。
2. **不加新前端依赖**（内联 JS 壳形态不变）。违反后果：构建面/供应链/e2e 面扩大。
3. **不迁移存量数据**（展示层容忍旧形状，旧事件降级展示）。违反后果：迁移脚本引入新风险；旧数据降级展示可接受。
4. **queue_full 上限 = 16 不变**（PRD §4.3 是笔误修正，非容量变更）。违反后果：无（上限语义不变）。

---

## 修订记录

- 2026-10-27 创建（主循环）。来源：user 五轮对话定稿方向（2026-10-26/27）+ 系统级全量审查结论（adversarial-review 法 + 2 explore subagent；正典冲突 4 条 + 三层诊断：产生层写契约焊死 / 存储层人面机面混排 / 展示层平铺零层级）。5 项待裁决。
- 2026-10-27 五项裁决折入（user 均按推荐）：1) update_progress 保留 + 必填 headline（缺 -> invalid_record，消息带修法）；2) queue_full = 16 定案（PRD §4.3 笔误本批修正）；3) 关键事件口径 = 最新优先 + 事件自带提纲，无读侧语义挑选；4) 管线原则（蒸馏恰好一次在生成点）本批写入 PRD §0；5) web.md:29 本批改新设计（提纲优先、点开看全文、默认收起）。§1 转已裁决，§3/§5/§6/§7 引用同步。
