# Business Contract: G9-b 重试成本超限判定

**作者**: 主循环（M1-4）
**日期**: 2026-10-23
**关联**: PRD §3.2（不自动重试/累计重试超 2 次等你决策）；docs/adr/0000-known-gaps.md G9-b；docs/adr/0003-m0-decisions.md「G9 登记」；判定源已由 user 裁决（2026-10-23）：**系统派生计数**（非 agent 显式登记）

---

## 1. 客户原话语义分析

### 客户原话（未解读，PRD §3.2 逐字）

> 不自动重试：重试对象是子任务（agent 侧），每次重试记录成本（token/时长），同一需求累计重试超 2 次进入"等你决策"清单（实现：系统判定超限后写一条 risk(severity=attention) 事件，入摘要"需要关注"区）

### 可能的解读（互斥，业务目标分歧）

| 解读 | 客户真实期望 | 证据 | 证据强度 |
|---|---|---|---|
| A. 系统派生 + 需求级累计 | 系统从子任务状态迁移自动推导"重试"，跨子任务对同一需求累计，超限后**系统自己**写风险事件，不依赖 agent 诚实 | "系统判定超限后写"（明确系统行为）；威胁模型 B（agent 内容不可信） | 客户原话 |
| B. 系统派生 + 子任务级独立 | 每个子任务各自计数，某子任务超 2 次才触发——重试是子任务行为，"同一需求累计"只是措辞 | "重试对象是子任务" + "同一需求累计"两处措辞可读作任一范围 | 客户原话（歧义） |
| C. agent 显式登记 | agent 每次重试主动写成本记录，系统按记录计数——成本（token/时长）只有 agent 自己知道 | "每次重试记录成本"（成本是 agent 侧事实） | 客户原话 |
| D. 阈值边界：≥2 vs >2 | "超 2 次"是"超过 2 次"（第 3 次触发）还是"达到 2 次"（第 2 次触发） | "超"字面 = 严格大于 | 推断 |

**互斥对**：A vs B（计数范围：需求级跨子任务累计 vs 子任务级独立，触发点不同，业务语义不同——需求级会在"整体反复折腾"时告警，子任务级只在单任务反复失败时告警）；A vs C（判定来源：系统推导 vs agent 自报，威胁模型 B 下 A 才可信）；A vs D（阈值边界）。

### 我的解读

**A + D**：系统从 `update_subtask` 状态迁移推导——子任务**重新进入 in_progress**（首入除外）计一次重试；对同一需求**跨子任务累计**；累计**严格超过 2 次（即第 3 次重入 in_progress）**时写一条 risk(attention) 事件（幂等，只写一次），入摘要需要关注区。成本（token/时长）不建结构化字段，留给 agent 侧 note 自报 + SKILL 指引（威胁模型 B 下 agent 自报本就不可审计，降级为展示性信息）。

user 已于 2026-10-23 裁决：系统派生计数（A），选项描述含"blocked/abandoned 后再开工，每子任务首次除外 + 需求级累计达到第 3 次 + 幂等 + 成本留 agent note + 不建 retry_cost 字段"。D（严格超 2）为字面直读。

### 待澄清项（已裁决，2026-10-23 user 三项均按推荐）

1. **重试判定范围**：**任何非 in_progress 状态重入 in_progress 都计一次重试**——含 done 重开（子任务重开）与 todo 退回再进。统一规则最简单，且最贴合反黑箱目标（防任何形式的重开/折腾 churn）；信号是提示非阻断，误标可由 agent 用 deviation/note 解释。
2. **幂等永久性**：超限触发后**只写一次** risk 事件，信号保持；人决策（note/approve）后 agent 继续重试不再二次告警（历史记录可查，note 时间线承载决策上下文）。二次告警 = M2 增强（已记录）。
3. **双展示位**：risk(attention) 事件进 risks 列表（决策/风险/偏离列表）+ 派生信号 `retry_limit` 进 needs_attention（摘要"需要关注"区，板徽标 + 详情区）——双展示，忠实 PRD 逐字"入摘要需要关注区" + §0 反淹没"风险"也是关键节点。

---

## 2. Impact Mapping

### Why（业务目标）

目标是让**人及时看到"重试失控"的需求并决策**（反黑箱：agent 反复折腾却不产出，人不能只靠翻事件流发现）；**不是**自动阻断 agent 重试（"不自动重试"已钉死，系统只标记不干预）。

### Who（受影响方）

1. **人（需求持有者）**：在摘要/看板需要关注区看到 retry_limit 信号，决策继续/终止/改道（note/approve/release 记录决策）。
2. **agent（被标记对象）**：重试行为被系统推导计数；超限后需要关注区有信号（提示而非阻断，自主性不受损）。
3. **未来审计者**：重试失控的历史（风险事件 + note 决策上下文）入回溯链（判据 3 谁在什么时候做了什么）。

### How（影响路径）

1. agent 每次 `update_subtask` 使子任务重入 in_progress（首入除外）-> 系统在同一事务推导需求级累计重试数。
2. 累计 > 2（第 3 次重入）-> 写 risk(attention) 事件（幂等，payload 标 retry_limit + count）。
3. 视图层：risk 事件入 risks 列表；派生信号 `retry_limit` 入 needs_attention（摘要/看板/详情）。
4. 人看到信号 -> 决策并记录（既有 note/approve/release 路径）。

### What（具体交付物）

1. 重试推导逻辑（operations.update_subtask 重入 in_progress 时计数 + 幂等写事件）。
2. `retry_limit` 派生信号（view._derived_signals，同源）。
3. SKILL.md 报告纪律补 agent 侧重试成本自报指引。
4. PRD §3.2 实现注记（判定源语义钉死）+ known-gaps G9-b 闭合。
5. harness（判定源/阈值/幂等/累计/边界全断言）+ BCD 落地。

---

## 3. Domain Event 流

### Domain Events（按时间顺序）

1. `subtask_entered_in_progress`（state_change 事件，payload.from/to；首入 = 初始尝试）
2. `subtask_re_entered_in_progress`（第 2+ 次重入 = 一次重试；同一 state_change 事件，语义由计数逻辑派生，不另写事件）
3. `retry_limit_exceeded`（kind=risk, severity=attention, payload={retry_limit: true, count: N}；幂等一次）
4. 人决策（note / approve / release——既有事件）

### Commands

1. `update_subtask(state="in_progress")`：agent 触发；系统在同一事务做重试计数 + 超限写事件。
2. `note / approve / release / abandon / renew`：人/既有路径，记录决策上下文（不改计数）。

### Aggregates（业务边界）

**Requirement** 为重试计数的业务边界（跨子任务累计、幂等判定、事件写入都在需求级）。

### Policies（含隐含 Policy）

1. 计数时点 = 子任务重入 in_progress 的迁移事件（只在该时点评估，不扫描全表定时跑）。
2. 首入除外（每子任务第一次 in_progress 是初始尝试，非重试）。
3. **计数作用域 = 子任务（审#P1-3）**：只计 `kind=state_change` 且 `payload.subtask_id` 非空、`payload.milestone_id` 为空、`to=="in_progress"`、`from!="in_progress"` 的事件——里程碑进入 in_progress（MILESTONE_STATES 含 in_progress，payload 是 milestone_id）不污染计数。
4. **隐含 Policy：幂等 + 反伪造（审#P1-1）**——marker 事件 `actor_surface="system"`（先例：reconcile 产物 RECONCILE_SURFACE="system"）；幂等谓词与信号谓词**同一**，钉死为 `kind=risk AND severity>=attention AND payload.retry_limit=true AND actor_surface=system`。agent 经 add_record 伪造 payload.retry_limit 的 risk 事件（actor_surface=mcp）不抑制告警、不进信号（威胁模型 B：agent 内容不可信，可伪造 marker 恰好刺穿系统派生的信任根基）。触发 agent 的审计轨迹留在同事务相邻的 state_change 事件（actor 服务端派生不可伪造），不丢回溯判据 3。
5. **隐含 Policy：计数来源 = events 链，不建独立计数器表**——避免双写漂移（PRD 单一事件源原则）。
6. **隐含 Policy：活动需求链完整性由 M1-3 prune 终态需求级原子窗口保障**——只有终态全窗外需求整删，活动需求 state_change 链完整，计数可靠。
7. **隐含 Policy：阈值常量钉死 2**——本批不配置化（PRD 未要求可配）。

---

## 4. BDD Given-When-Then 场景

### Scenario 1（happy path：阈值触发）
- Given: 需求 CLAIMED，有 1 个 in_progress 子任务（已首入），已重试 2 次（两次 blocked->in_progress）
- When: agent 第 3 次 update_subtask 使该子任务重入 in_progress
- Then: 同事务写一条 risk(severity=attention) 事件（payload.retry_limit=true, count=3）；摘要 needs_attention 含 retry_limit；risks 列表含该风险事件

### Scenario 2（happy path：未超限不触发）
- Given: 需求有 1 个子任务，已重试 2 次
- When: agent 重入 in_progress（第 3 次进入 in_progress，重试计 2——未超）
- Then: 不写 risk 事件，needs_attention 无 retry_limit

### Scenario 3（happy path：跨子任务累计）
- Given: 需求有子任务 A（已重入 1 次 = 重试 1）、子任务 B（已重入 1 次 = 重试 1），合计 2
- When: agent 使 A 再次重入 in_progress（需求累计重试 3）
- Then: 触发写风险事件（需求级累计语义成立）

### 边缘场景 1（幂等）
- Given: 需求已触发过 retry_limit（存在 marker 风险事件）
- When: agent 继续重入 in_progress 多次（第 4、5、6 次）
- Then: 不再写新风险事件（事件数保持 1）；retry_limit 信号保持；payload.count 保持 3（触发时点快照，不随后续重试更新，P3-1）

### 边缘场景 2（首入不计 + no-op 不计）
- Given: 需求有子任务刚 add（todo）
- When: agent 首次 update_subtask 到 in_progress；随后连续两次 in_progress->in_progress no-op
- Then: 重试计 0，永不触发（首入 + no-op 均不计数）

### 边缘场景 3（done 重开 / todo 退回再进计重试——user 已裁决"任何非 in_progress 重入都计"）
- Given: 需求子任务已 done（首入已发生）；另一子任务已退回 todo（ip->todo）
- When: agent 使 done 子任务 done -> in_progress（重开）；使 todo 子任务 todo -> in_progress（退回再进）
- Then: 两者各计一次重试（"任何非 in_progress 状态重入 in_progress"均计，BCD §1 待澄清 1 已裁决）

### 边缘场景 4（里程碑 in_progress 不计——审#P1-3 subtask 作用域）
- Given: 需求有一个里程碑，状态进入 in_progress（payload.milestone_id 非空，无 subtask_id）
- When: 里程碑反复在 milestone_states 间迁移（含 in_progress 进出）
- Then: 重试计 0（计数只认 payload.subtask_id 非空 + milestone_id 空的 state_change 事件），不污染计数

### 边缘场景 5（agent 伪造 marker 不抑制告警——审#P1-1 反伪造）
- Given: agent 用 add_record(kind=risk, severity=attention, payload={"retry_limit": true, "count": 0}) 预写伪造 marker
- When: 真实重入达到第 3 次（重试 3）
- Then: 系统仍写真实 risk 事件（actor_surface=system，幂等谓词排除伪造 marker）；伪造事件不进 needs_attention 的 retry_limit 信号（信号谓词含 actor_surface=system）；伪造事件仍作为普通 risk 记录显示在 risks 列表（agent 自报风险，允许）

### 配置变更时场景（必写）
- Given: 阈值钉死为常量 2（本批无配置项），存量需求状态各异
- When: （本批不引入配置变更——无阈值配置）
- Then: 变更瞬间语义不适用；记录为"阈值常量钉死，无配置变更面"；若未来 M2 配置化，需单独评审存量已触发 vs 新阈值的再触发语义

### 跨时段场景（prune / reopen 交互）
- Given: 需求长期活动，事件链跨 12 个月窗口；prune 只整删终态全窗外需求（M1-3 裁决）
- When: 活动需求发生重入 in_progress（第 N 次，N>2）
- Then: 计数基于完整链（活动需求不被 prune），触发正确；极端 reopen 场景（曾终态整删后 reopen）计数从零开始（已知限制，M1-3 已文档化）

---

## 5. Spec by Example

### 例 1（单子任务多轮）
- 输入: 子任务 S 状态序列：todo->ip, ip->blocked, blocked->ip, ip->blocked, blocked->ip, ip->blocked, blocked->ip
- 操作: 每次 blocked->ip 计一次重入
- 预期: 重入次数 = 4，重试 = 3（首入除外）-> 第 4 次重入（重试 3）时触发写事件

### 例 2（与例 1 差异：跨子任务）
- 输入: 子任务 A（重入 1）+ 子任务 B（重入 2）= 需求级 3
- 操作: 按时间顺序重入
- 预期: B 第 2 次重入（需求累计第 3 次）时触发

### 例 3（差异：零重试）
- 输入: 单子任务 todo->ip->done
- 操作: 无重入
- 预期: 永不触发，无风险事件，needs_attention 无 retry_limit

### 例 4（差异：幂等）
- 输入: 触发后继续重入 3 次
- 操作: 继续 blocked->ip
- 预期: risk 事件数保持 1（不重复写）

### 例 5（差异：多 claim 周期）
- 输入: 周期 1 重试 2（release 后重新 claim），周期 2 重试 1
- 操作: 跨周期继续重入
- 预期: 需求级累计 3 -> 周期 2 第 1 次重入时触发（累计语义跨周期延续，不因 claim 周期重置）

### 客户期望 vs 系统行为差异表

| 场景 | 客户期望（PRD 字面） | 系统行为（本 BCD） | 冲突性质 | 差距 |
|---|---|---|---|---|
| 成本记录 | "每次重试记录成本（token/时长）"——结构化可统计 | 无 retry_cost 字段；成本只进 agent note 自由文本（SKILL 指引自报） | **根本性业务** | PRD 期望"成本可记录"，系统给"成本不可结构化"——agent 自报在威胁模型 B 下本就不可审计，user 已裁决降级为展示性信息；差距 = 成本无法系统统计/聚合，只能人读 note |
| 触发点 | "累计重试超 2 次" | 第 3 次重入触发，幂等一次 | 技术/语义澄清 | 阈值边界（>2）已按字面直读；幂等性为系统新增（PRD 未言明是否重复触发） |
| 展示位 | "入摘要'需要关注'区" | risk 事件入 risks 列表 + retry_limit 派生信号入 needs_attention（双展示） | 语义澄清 | PRD 只提一个区；双展示为忠实解读（§0 风险也是关键节点），见 §1 待澄清 3 |

---

## 6. Premortem（假设 6 个月后失败）

### 失败原因 1：计数语义把"正常小步重试"误标为失控（业务规则维度）
- 失败序列: 某些 agent 采用"频繁尝试-快速失败"策略（blocked->ip 多次是正常探索），需求被标 retry_limit，人频繁看到误报，开始忽略信号 -> 真失控时没人看。
- 预防: 信号是提示非阻断（人决策，不自动干预）；agent 可用既有 deviation/note 登记重试策略与原因（偏离显式化机制）；SKILL 指引 agent 在重试前/时解释；阈值钉死 2 是保守起点，误报率由 SKILL 侧降低。

### 失败原因 2：幂等导致"人决策后又失控"静默
- 失败序列: 人决策"继续"，agent 又重试 20 次，无任何新信号（幂等只写一次），人以为已解决。
- 预防: 信号保持 + note 时间线承载决策上下文（人可回查）；若"二次告警"成为真实需求，M2 增强（记录于 BCD §1 待澄清 2，当前显式不做）。

### 失败原因 3：reopen 极端场景计数归零制造审计盲区
- 失败序列: 需求曾终态整删（prune）后 reopen，旧重试链丢失，计数从零开始，人误以为"没重试过"。
- 预防: M1-3 已文档化（prune 只整删终态全窗外）；活动需求链完整（主流路径无此问题）；极端 reopen 属已知限制，归档文件为权威（M1-3 裁决）。

### 失败原因 4（业务规则维度）：一刀切阈值不适配 agent 工作模式差异
- 失败序列: 重试阈值对"长推理型 agent"（重试成本高，2 次就该停）与"探索型 agent"（重试频繁是常态）同价，探索型被长期误标，人免疫。
- 预防: 阈值常量是 PRD 钉死（2），本批不做配置化（§3 Policy 7）；agent 用 deviation/note 解释策略（偏离机制）是设计内缓解；若需要按 agent/需求差异化是 M2 业务决策（记录）。

---

## 7. 业务不变量

### 强不变量（违反即业务失败）

1. **系统只标记不干预**——重试超限只写风险事件 + 信号，绝不自动重试/自动释放/自动阻断 agent（PRD 3.2「不自动重试」核心语义）。违反后果：agent 自主性被破坏，看板从记录面变控制面（PRD 明确定位）。
2. **计数来源 = events 链（state_change 重入推导），不建独立计数器表**（单一事件源原则）。违反后果：双写漂移，审计链与计数不一致，回溯判据失真。
3. **幂等 + 反伪造：同一需求超限只写一次 risk 事件，marker 事件 actor_surface=system，幂等/信号谓词同一（kind=risk AND severity>=attention AND payload.retry_limit=true AND actor_surface=system）**（审#P1-1）。违反后果：重复骚扰人 / agent 伪造 marker 抑制告警，威胁模型 B 的信任根基被刺穿（系统派生的唯一依据是 agent 内容不可信）。
4. **首次 in_progress 永不计数；from==in_progress 的 no-op 永不计数；计数只认 subtask 作用域（milestone_id 空）**（重试 = 重入，非进入；审#P1-3）。违反后果：初始尝试/无操作/里程碑迁移被误标，误报破坏信号可信度。
5. **重试计数按需求级跨子任务累计**（非子任务级独立）。违反后果：单子任务反复失败被漏报（若子任务级）或整体折腾被漏报（若需求级口径漂移），"等你决策"清单失真。

### 软约束（违反可容忍）

1. **成本记录不结构化**（无 retry_cost 字段，note 自由文本）——违反后果：成本无法系统聚合，只能人读 note；威胁模型 B 下 agent 自报本就不可审计，容忍。
2. **reopen 极端场景计数从零开始**（prune 整删后）——违反后果：历史重试盲区，归档文件可补；活动需求主流路径链完整，容忍。
3. **双展示位（risks 列表 + needs_attention）**——违反后果：轻微信息冗余；§0 反淹没两者都是关键节点，容忍（若 user 认为冗余可单选，见 §1 待澄清 3）。

---

## 修订记录

- 2026-10-23 创建（主循环）。判定源裁决来源：user 选项「系统派生计数（推荐）」。
- 2026-10-23 审#1 折入（plan 盲审 APPROVE-WITH-FIXES，3 P1 + 4 P2）：P1-1 marker 反伪造（actor_surface=system + 幂等/信号谓词统一）；P1-2 待澄清 1 重试范围 user 裁决 = 任何非 in_progress 重入都计（含 done 重开 + todo 退回再进）；P1-3 计数 subtask 作用域（milestone 不计）；P2-1 count 为触发时点快照（后续重试不更新，信号保持，记录制）；P2-2 ip->todo->ip 语义并入裁决（退回再进计重试）+ harness 补例；P2-3 待澄清 2/3 user 裁决 = 幂等只写一次 + 双展示；P2-4 措辞（SUBTASK_STATES 拼写、reopen 归零引用以 M1-3 prune 语义为准）。
