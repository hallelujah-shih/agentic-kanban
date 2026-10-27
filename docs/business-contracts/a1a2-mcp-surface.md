# Business Contract: 批 2 A1 短 id 前缀匹配 + A2 update_progress 返回租约态

**作者**: 主循环（a1a2-mcp 批）
**日期**: 2026-10-27
**关联**: docs/PRD.md §4.1（MCP 工具面）§4.3（错误码）§3.2（租约）；ADR 0006（activity 口径）；skills/agent-kanban/SKILL.md（agent 侧协议）；跨批次改进清单裁决（skill-revise 批 spec-improvement-list.md:47「第二批 A1+A2 做、A3 砍」）
**状态**: v1 设计草稿已全批（2026-10-27 user，四决策点均按建议值）；待对抗审查
**板上任务**: 396f583730514ab5a3963dd58563bdcd（CLAIMED，main-loop）

---

## 1. 客户原话语义分析

### 客户原话（未解读，2026-10-27 裁决原文）

> 「按照建议，先落文档，然后 review，过了开始实施」＝组合建议全采纳：第一批 B1+B2+B3+D1+C1 全做，第二批 A1+A2 做、A3 砍；C2 留提醒。
>
> 下批（第二批）：A1 短 id 前缀匹配 + A2 update_progress 返回加租约态（MCP 产品面，新代码批，新板上任务）。

（诚实标注：调研交付的详细条目原文未落盘——跨批次改进调研（2026-10-27，M1-6/CI/G12 三批复盘）的 A1/A2 建议细节只存在于 skill-revise 批对话中，档案仅存名称 + 裁决。本 BCD 的「客户期望」重建自：项名称、裁决原文、现状代码痛点取证、user 对设计草稿的全批（四决策点）。）

### 可能的解读（互斥，业务目标分歧）

| 解读 | 客户真实期望 | 证据 | 证据强度 |
|---|---|---|---|
| A1-a. agent 侧输入人体工学 | agent 抄写/传递 32 位 id 易错且笨重，凡带 requirement_id 的操作允许唯一短前缀，降低 id 误用 | 项名称「短 id 前缀匹配」；MCP 产品面定位（agent 是主调用方） | 项名称 |
| A1-b. 展示/交接侧短 id | 板面/交接简报应显示短 id（人读得动），解析侧顺带支持 | 「MCP 产品面」未点名展示层；web.md 无短 id 诉求 | 弱（无原话支撑） |
| A1-c. 全 id 体系人体工学 | 系统内所有 id（requirement/subtask/milestone/claim）一律支持前缀 | 项名称未限定 id 类型 | 弱（扩大解释） |
| A2-a. 返回自足 | update_progress 返回让 agent 无需再调 list_tasks 就知道租约何时到期 | 项名称「返回加租约态」；痛点＝agent 长任务反复写 progress 却不知何时 renew | 项名称 + 痛点 |
| A2-b. 隐式续租 | 「写 progress＝活跃证明」，所以 update_progress 应顺带延长租约，返回延长后的到期时间 | 常见直觉：activity 该续命 | 无（与 ADR 0006 activity 口径冲突） |
| A2-c. 完整租约视图 | 返回完整 claim_view（agent_name/started_at/signal 全套） | 「租约态」字面 | 弱（YAGNI） |

**互斥对**：A1-a vs A1-b（交付面：仅输入解析 vs 含展示短化——本批做 a 则 b 的板面改动完全不发生）；A1-a vs A1-c（范围：requirement_id only vs 全 id 体系——c 的实施面是 a 的超集且动 subtask/milestone 二级引用面）；A2-a vs A2-b（**根本性分歧**：返回是「通知」还是「续租证明」——b 改变租约模型，a 不碰写路径）。

### 我的解读

**A1-a（requirement_id only，仅输入解析面）+ A2-a（仅通知，不改租约语义）**。理由：(1) A1 的痛点在 agent 输入侧（MCP 调用参数），展示侧无原话诉求且 web 面已定稿（distill-pipeline 批）不动；(2) subtask/milestone id 是二级引用（update_subtask 的 subtask_id 来自 add_subtask 返回，agent 通常原样透传，前缀需求弱）；(3) A2-b 与 ADR 0006 裁决冲突（activity 口径＝last_activity_at 观测值，lease_expires_at 固定、显式 renew 延长）——若「写 progress 就续租」成立，renew 工具与 lease 信号推导全部失效，这不在本批授权内；(4) 四决策点（8 hex 最小长度 / requirement_id only / 409 映射 / 仅 lease_expires_at）user 已全批。

### 待澄清项（已裁决，2026-10-27 user 设计草稿全批）

1. **A1 最小前缀长度**：**8 hex**（git 惯例；歧义由 ambiguous_id 兜底，阈值只影响便利面）。
2. **A1 适用范围**：**仅 requirement_id**（subtask/milestone/claim id 维持精确匹配；日后需要单开）。
3. **ambiguous_id 的 REST 映射**：**409**（匹配多资源＝conflict）。
4. **A2 返回粒度**：**仅 `lease_expires_at`**（iso 字符串，与 renew 返回口径逐字一致；不给完整 claim_view）。
5. **A2 不延租（隐含 Policy 显性化）**：A2 返回是通知，touch_activity 维持现语义（只更 last_activity_at，不动 lease_expires_at）。设计草稿范围即「纯 additive、写路径零改动」，user 全批＝认可；本节显式登记防实施期误读为 A2-b。

---

## 2. Impact Mapping

### Why（业务目标）

目标＝agent 经 MCP/CLI 操作看板时 id 误用率与往返次数下降：短前缀消除「抄 32 位 id 抄错/抄累」，update_progress 返回自足消除「写完 progress 再拉 list_tasks 看租约」的额外往返。**不是**通用 id 体系改造（A1-c），**不是**展示层短化（A1-b），**不是**租约模型变更（A2-b）。

### Who（受影响方）

1. **agent（MCP 工具面主调用方）**：12 工具中凡带 requirement_id 的参数均可用 8+ 位前缀；update_progress 返回多一个租约到期字段。
2. **人（CLI/REST 面）**：CLI 命令与 REST 路由同 choke point 生效（三面同源）；ambiguous_id 错误信息含候选集，人面排障可读。
3. **未来调用方（契约稳定面）**：MCP 单向门只增——新错误码、新返回字段、更宽的解析输入；既有行为（全 id 精确匹配、not_found 语义）逐字不变。

### How（影响路径）

1. A1：id 解析从「精确主键匹配」放宽为「精确优先 + 唯一前缀兜底」，实现单点＝`write_guard.require_requirement`（MCP/REST/CLI 三面必经）；歧义拒绝用新错误码 `ambiguous_id`（错误面只增一码）。
2. A2：`operations.update_progress` 返回加 `lease_expires_at`（claim 对象本事务内已加载，零额外查询；口径对齐 `renew`）。
3. 契约同步：PRD §4.3 错误码表 + 新「id 解析口径」；api/main.py REST_ERROR_STATUS；MCP docstring（update_progress 返回行 + 带 id 工具错误行）。

### What（具体交付物）

1. `write_guard.py`：requirement_id 前缀解析（含 ambiguous_id）。
2. `operations.py`：update_progress 返回加 lease_expires_at。
3. 契约文档：PRD §4.3 + id 解析口径 + §4.1 update_progress 返回行；api/main.py 映射；server.py docstring。
4. 测试：前缀解析/歧义/短输入/非 hex/全 id 回归的 AC 用例；update_progress 返回面 AC 用例。
5. 本 BCD + spec（docs/superpowers/specs/2026-10-27-a1a2-mcp-surface-design.md）。

---

## 3. Domain Event 流

### Domain Events（按时间顺序）

**零新事件 kind、零事件形状变更**。A1 的解析发生在任何写入之前（requirement 定位失败即拒绝，同事务无半态）；A2 的 progress_note 事件形状不变（distill-pipeline 批的 headline 契约原样），只改**命令返回面**。

### Commands

1. 全部带 requirement_id 的命令（MCP 12 工具 + REST + CLI）：参数 id 的**解析**放宽（8+ 位 hex 唯一前缀）；签名、参数名、写入语义零改动。
2. `update_progress(requirement_id, note, headline)`：返回 `{"requirement_id", "lease_expires_at"}`（现仅 `{"requirement_id"}`）；写路径零改动。

### Aggregates（业务边界）

Requirement / Claim 聚合不变。无新表、无新列、无索引变更（前缀匹配走 requirements 主键索引，`id LIKE '<prefix>%'` 可命中）。

### Policies（含隐含 Policy）

1. **宁拒不猜**：前缀命中 ≥2 条必须拒绝（ambiguous_id），永不静默挑选——写错最坏后果＝事件落进错误需求（审计链污染）。
2. **精确优先**：32 位 hex 输入走精确匹配（session.get），不进入前缀扫描；前缀扫描只服务 8~31 位输入。
3. **单向门纯 additive**：新错误码 + 新返回字段 + 更宽解析输入；既有错误码语义、not_found 行为、全 id 行为逐字不变。
4. **三面同源（隐含）**：解析实现单点在 require_requirement choke point，MCP/REST/CLI 天然一致——禁止各面自行实现前缀逻辑（漂移源）。
5. **activity 不延租（隐含，ADR 0006）**：agent 面写操作只更 last_activity_at；lease_expires_at 固定、显式 renew 延长。A2 返回是通知该规则，不是改变该规则。
6. **展示面不变（隐含）**：板面/web/export 仍显示 32 位全 id；本批只放宽输入侧。

---

## 4. BDD Given-When-Then 场景

### Scenario 1（happy path：唯一前缀解析）
- Given: 板上存在需求 `396f583730514ab5a3963dd58563bdcd`（CLAIMED），无其他需求以 `396f` 开头
- When: agent 调 `update_progress(requirement_id="396f5837", note="...", headline="...")`
- Then: 解析到该需求，progress_note 写入成功；返回 `{"requirement_id": "<32位全id>", "lease_expires_at": "<iso>"}`（返回用解析后的全 id，不回填短前缀）

### Scenario 2（happy path：全 id 回归）
- Given: 同 Scenario 1
- When: agent 以 32 位全 id 调任意带 id 工具
- Then: 行为与现实现逐字一致（精确匹配路径，不进前缀扫描）

### Scenario 3（happy path：A2 返回自足）
- Given: 需求 CLAIMED（租约 7200s，lease_expires_at 已定）
- When: agent 调 `update_progress`（headline 必填契约照旧）
- Then: 返回含 `lease_expires_at`（与同事务 renew 会返回的值一致口径）；agent 由此可决定何时 renew，无需再调 list_tasks

### 边缘场景 1（歧义拒绝）
- Given: 两个需求 id 均以 `ab12cd34` 开头
- When: agent 以 `ab12cd34` 调任一写操作
- Then: 返回 `ambiguous_id`，信息含候选 id 集与「加长前缀」提示；**零写入**（无事件、无 claim 变更、无状态变更）

### 边缘场景 2（短/非 hex 输入兼容）
- Given: 任意板面
- When: agent 以 `396f`（4 位）、`xyz12345`（非 hex）、空串调工具
- Then: 均 `not_found`（与现行为一致，不引入新错误码）

### 边缘场景 3（配置变更时场景）
- Given: 本批不引入配置项——最小前缀长度 8 是代码常量（非配置面）
- When: （无配置变更面）
- Then: 记录为「无配置变更面」；若未来阈值可配置化，存量调用方依赖的短输入语义（<8 位＝not_found）变更需单独评审

### 跨时段场景（唯一性漂移）
- Given: agent 曾用 8 位前缀 `a1b2c3d4` 唯一命中需求 X（当时板上无其他 `a1b2c3d4*` 需求）
- When: 新需求 Y（id 以 `a1b2c3d4` 开头）创建后，agent 再以 `a1b2c3d4` 调用
- Then: 从「解析成功」变为 `ambiguous_id`——前缀唯一性随板面增长**只收紧不放松**；agent 收到 ambiguous_id 的既定行为＝加长前缀重试（docstring/错误信息明示）

---

## 5. Spec by Example

### 例 1（唯一前缀 -> 成功）
- 输入: `note(requirement_id="c53a151a", content="人面更正")`，板上仅一条 `c53a151a...` 需求
- 操作: 人面 CLI note
- 预期: 解析到该需求，note 事件写入（与全 id 调用同效果）

### 例 2（歧义 -> 拒绝 + 候选）
- 输入: 板上 `7f00aaaa...` 与 `7f00bbbb...` 两需求；`claim_task(requirement_id="7f00", agent_name="x")`
- 操作: agent 认领
- 预期: `ambiguous_id`，信息列出 `7f00aaaa...` 与 `7f00bbbb...` 两候选 + 加长前缀提示；无 claim 行创建

### 例 3（4 位 -> not_found）
- 输入: `claim_task(requirement_id="7f00aa", ...)`（<8 位）
- 操作: 同上
- 预期: `not_found`（消息形态与现行为一致）

### 例 4（全 id 不存在 -> not_found 不变）
- 输入: 32 位 hex 但板上不存在
- 操作: 任意带 id 工具
- 预期: `not_found`（精确匹配路径，语义不变）

### 例 5（A2 返回面）
- 输入: `update_progress(requirement_id="<全id>", note="跑了全量", headline="全量 592 绿")`，当前 claim lease_expires_at=2026-10-27T14:00:00+00:00
- 操作: agent 报进度
- 预期: 返回 `{"requirement_id": "<全id>", "lease_expires_at": "2026-10-27T14:00:00+00:00"}`；事件链 progress_note 形状不变（title=headline）

### 客户期望 vs 系统行为差异表

| 场景 | 客户期望 | 系统行为（现实现） | 冲突性质 | 差距 |
|---|---|---|---|---|
| 短 id 操作 | agent/人用 8+ 位唯一前缀即可操作（抄全 id 易错笨重） | require_requirement 仅精确主键匹配（write_guard.py:15 session.get），短输入一律 not_found | 能力缺口（本批填平） | A1 前缀解析 |
| 写完知道租约 | update_progress 返回自足，agent 知道何时 renew | 仅返 `{"requirement_id"}`（operations.py:737），租约态须另调 list_tasks/get_task_detail | 能力缺口（本批填平） | A2 返回加 lease_expires_at |
| 「写 progress＝活跃＝租约续命」 | 直觉：写操作即活跃证明，到期时间应随写顺延 | ADR 0006 裁决：activity 口径＝last_activity_at（观测），lease_expires_at 固定、显式 renew 才延长 | **根本性业务冲突** | 本批不改变租约模型（A2-b 不在授权内）；A2 把隐藏规则显性化（返回到期时间），agent 依返回决定 renew——冲突以「规则显性化 + 模型不动」收口 |
| 三面一致 | 同一 id 输入在 MCP/REST/CLI 行为一致 | 现三面共用 choke point（天然一致） | 无缺口，防回归 | Policy 4 单点实现 + 回归测试 |

---

## 6. Premortem（假设 6 个月后失败）

### 失败原因 1（业务规则维度）：歧义兜底失守——某处解析「猜了一个」
- 失败序列: 前缀扫描实现漏了 >=2 候选的拒绝分支（或后人图省事改成「取第一条」）-> agent 短前缀写进错误需求 -> 事件/claim/状态变更落进无关需求 -> 人发现「两个需求的事件串了」，审计链（回溯判据 2/3）对该需求不可信，看板核心资产受损。
- 预防: 强不变量 1（宁拒不猜）入 spec；AC 含歧义判别用例（两同前缀需求必拒 + 零写入断言）；审查锚点＝前缀扫描函数的候选计数分支。
- 残余: 无（该分支可测试可断言）。

### 失败原因 2（跨边界语义维度）：agent 把 A2 返回误读为续租证明
- 失败序列: agent 看到 update_progress 返回 lease_expires_at，推断「我每次写 progress 都在续租」-> 长任务中不再调 renew -> 租约到期 -> 派生 signal 转 STALE、后续写操作 lease_expired 报错 -> agent 流程中断，归因「看板租约机制不可靠」。
- 预防: 错误信息与 docstring/PRD 同口径明示「返回仅为通知，不延长租约；续租用 renew」；SKILL.md 协议面如涉租约措辞同批核对；A2 返回字段名与 renew 完全一致（同语义源，防「另一个字段=另一套语义」误读）。
- 残余: agent 的推断行为不可硬约束（带外认知）——语义显性化是上限（与 distill-pipeline 批威胁模型 B 同一边界）。

### 失败原因 3（业务规则维度）：三面一致性被「顺手」破坏
- 失败序列: 某面（如 REST 路由层）为「优化」在 choke point 之外加了本地 id 处理（trim/casefold/前缀）-> 三面语义漂移（同输入 MCP 解析成功、REST not_found）-> 调用方跨面切换时行为不可预测，排障成本反升。
- 预防: Policy 4（单点实现）入 spec 非目标（「禁止各面自行实现前缀逻辑」）；AC 含同输入跨面一致性用例（MCP 与 REST 同前缀同结果）。
- 残余: 代码评审面的约束，测试只覆盖当前两面（CLI 与 MCP 同进程同函数，结构一致）。

### 失败原因 4（技术但具体）：前缀扫描在索引外退化
- 失败序列: 实现写成 `id LIKE '%<suffix>'` 或先取全表再 Python 端过滤（「反正单用户数据量小」）-> 板面长大后每次带前缀操作 O(N) 全表扫 -> 并发写锁窗口拉长，db_busy 率上升。
- 预防: spec 钉死 `id LIKE '<prefix>%'`（前缀锚定，主键索引可用）；实施 diff 审查锚点＝SQL 形态。
- 残余: 单用户规模下即使退化也短期不可见——接受（登记于本 Premortem 即预防的最低形态）。

---

## 7. 业务不变量

### 强不变量（违反即业务失败）

1. **宁拒不猜**：前缀命中 ≥2 条必返 ambiguous_id，任何解析路径不得静默选择候选。违反后果：事件/状态变更落进错误需求，审计链污染（回溯判据失效）。
2. **全 32 位 id 行为逐字不变**：精确匹配路径、not_found 语义、错误信息形态均不回归。违反后果：存量 agent 自动化/CLI 脚本断裂。
3. **单向门纯 additive**：契约变化仅＝新错误码 ambiguous_id + update_progress 新返回字段 + 解析输入放宽；不删不改任何既有码、字段、工具、参数。违反后果：既有调用方断裂，单向门纪律失守。
4. **租约语义零改动**：activity 只更 last_activity_at（ADR 0006）；A2 返回是通知，不延长 lease_expires_at。违反后果：租约模型隐式变更，signal 推导与 renew 工具语义漂移。
5. **三面同源单点**：id 前缀解析唯一实现＝require_requirement choke point，MCP/REST/CLI 同语义。违反后果：同输入跨面行为漂移，排障与契约文档失真。

### 软约束（违反可容忍）

1. **展示面不动**：板面/web/export 仍显 32 位全 id（输入侧放宽、展示侧不短化）。违反后果：输入/展示不对称引发新疑问；但属后续独立需求，不阻塞本批。
2. **最小前缀长度＝8 为代码常量**（非配置）。违反后果：阈值不可按环境调；单用户规模下无此需求。
3. **零 schema 变更**：不加表/列/索引；前缀扫描走既有主键索引。违反后果：部署/迁移面扩大，与本批档位（有界偏轻）不符。

---

## 修订记录

- 2026-10-27 创建（主循环）。来源：skill-revise 批 user 裁决（spec-improvement-list.md:47，A1+A2 做、A3 砍）+ 现状代码取证（write_guard.py choke point / operations.py:737 返回面 / ADR 0006 activity 口径）+ 设计草稿 user 全批（四决策点按建议值）。调研交付原文未落盘，已在 §1 诚实标注重建依据。
