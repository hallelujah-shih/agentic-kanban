# Business Contract: 人确认闭环——代执行一等受托面（delegated）+ CLI 零输入 + Web 待决页

**作者**: 主循环（delegated-confirm 批）
**日期**: 2026-10-27
**关联**: docs/PRD.md §29（职责边界）§4.2（Web 窗口）§4.3（错误码）§5.1（actor 模型）§5.2（自报声明）；ADR 0002（服务端派生 actor 先例）；skills/agent-kanban/SKILL.md（agent 收尾协议落点）；docs/adr/0000-known-gaps.md（G11：cli.py 涉改，合入后 `uv sync --reinstall-package agent-kanban`）；docs/business-contracts/a1a2-mcp-surface.md（A1 id 解析语义，本批复用）
**状态**: v1 设计草稿已全批（2026-10-27 user，四决策点 + 整合设计均回「可以」）；待对抗审查
**板上任务**: bcd3a69074b641dba70a08afbce1ac05（CLAIMED，main-loop）

---

## 1. 客户原话语义分析

### 客户原话（未解读，2026-10-27 会话原话）

> 「cli approve 不应该让用户输入……」（零输入痛点）
>
> 「用户告诉你做了，或者你自己检测做了，就应该更新状态」（收尾协议）

（诚实标注：第一句为会话记录引文片段，完整上下文＝「人确认闭环」批的立项讨论；收尾协议为 user 2026-10-27 会话指示，当批即生效——本会话板上三条 DONE（396f5837/5bd38af7/c53a151a）即 agent 依该协议代执行（先 note 留依据、再 approve），属临时权宜流程。四决策点 + 整合设计为主循环据两段原话起草的 v1 设计，user 全批。）

### 可能的解读（互斥，业务目标分歧）

| 解读 | 客户真实期望 | 证据 | 证据强度 |
|---|---|---|---|
| C-a. agent 代执行收尾协议产品化（一等受托面） | 现行权宜流程（前置 note + approve）产品化：受托标记与依据落在事件自身，板面可辨「人做的」与「agent 代做的」 | 收尾协议原话；四决策点 Q1-Q3 全部围绕确认源/委托范围/审计 | 原话 + 裁决原文 |
| C-b. 人面收尾输入人体工学 | `cli.py approve` 不抄 32 位 id 即可用 | 第一句原话 | 原话 |
| C-c. Web 确认入口 | 待决任务在 Web 一键确认（Web 现无决策操作入口） | 无直接原话（整合设计内派生面，随全批成立） | 裁决原文（设计级） |
| C-d. 服务端自动检测人的动作 | 系统自接 GitHub webhook 检测 PR merge 等事件、自动推进状态 | 无 | 无（明确非目标，YAGNI） |

**互斥对**：C-d vs C-a（「action」确认的来源机制：服务端自动检测 vs agent 声明 + 人核——d 是外部系统对接架构，a 是协议 + 审计架构，实现面完全不同）；C-b vs C-c（兜底面：仅 CLI vs CLI + Web，c 为 b 的超集）。

### 我的解读

**C-a + C-b + C-c**（整合设计，user 全批）；C-d 显式非目标。理由：(1) 收尾协议原话的「告诉你 / 检测」对应确认源 statement / action 两种 kind——「检测」指 agent 检测人的工作面动作（远端 PR merge），非服务端检测；(2) 零输入原话只点名 CLI；Web 待决页是同一痛点（人不能在 Web 确认）的派生面，被全批覆盖；(3) C-d 需外部系统对接（GitHub webhook），依赖面与信任边界扩出不符合本批档位（单用户、无外部服务）。

### 待澄清项（已裁决，2026-10-27 user「可以」）

1. **Q1 确认源（kind）**：`statement`（人的会话表态）+ `action`（人的工作面动作中 agent 结构性做不了的，如远端 PR merge；本地仓检测不算——本地仓 ff 折入是 agent 自己的动作，防自我认证）。
2. **Q2 委托范围**：宽松——非破坏人面操作（approve/release/reopen/renew/note/abandon/set_expectations）皆可代执行，两种 kind 均收；delete/archive 等破坏性/非确认操作结构性无受托参数（不可能性即门禁）。
3. **Q3 审计形态**：一等受托面——`actor_surface` 加 `delegated`（服务端派生：人面 + 有效受托参数才落此值，沿用 PRD §5.1/ADR 0002 服务端派生先例）；`payload.delegated={kind,basis}` 结构化（payload JSON 列既有，零 schema 变更）；CLI `--on-behalf "<kind>:<basis>"`；REST body 可选 delegated 字段；板面显「代执行（依据：…）」；MCP 12 工具面零改动（无受托参数，agent 自身动作恒 mcp）；错误码零新增（误用 -> invalid_record 新触发实例）。
4. **Q4 兜底面**：CLI 零输入（approve/release 无 --requirement-id：恰 1 条待决直接执行、多条列号选、0 条提示）+ Web 待决页（PRD §29 定位显式重裁＝只读 + 生命周期 + 待决；复用既有 REST /approve /release 端点，零新端点零新信任边界；按钮＝人亲手，surface 为 cli（rest:）而非 delegated）。

---

## 2. Impact Mapping

### Why（业务目标）

人确认闭环是看板唯一可信终态源（PRD §5.2：需求级 DONE＝人确认，唯一可信终态）。现状痛点三点：(1) agent 代执行收尾（权宜：前置 note 留依据 + approve）的受托标记与依据散落两事件，回溯需人工关联，且 surface=cli 与人亲手不可辨；(2) 人面收尾每次须抄 32 位 id（cli.py:280 required=True）；(3) Web 面无决策操作入口（PRD §29），确认被迫回 CLI。目标＝收尾动作在三面都是最低摩擦操作 + 代执行动作有一等审计。**不是**服务端事件检测（C-d），**不是** MCP 面变更，**不是**状态机/租约变更。

### Who（受影响方）

1. **人（CLI/Web 收尾面）**：`cli.py approve` / `cli.py release` 可零参；Web 待决任务详情页有 approve/release 按钮。
2. **agent（代执行收尾协议）**：SKILL.md 增收尾协议（pull 触发：会话内 list_awaiting；kind 判据；代执行流；不再要求前置 note——受托痕在事件自身）。
3. **审计者（回溯/export 面）**：surface=delegated + basis 板面直读；export 事件行 `by delegated:cli` + payload.delegated。
4. **存量调用方（契约稳定面）**：无受托参数路径逐字不变；MCP 面不变；错误码集不变。

### How（影响路径）

1. 受托面：人面（CLI 进程 / REST conn）+ 结构有效受托参数 -> actor_surface=delegated，且该命令写的事件带 payload.delegated（surface 与 payload 同一函数落值，结构耦合防失配）。
2. CLI：7 命令加 `--on-behalf "<kind>:<basis>"`；approve/release 的 --requirement-id 改可选（零输入＝客户端编排：既有 list_awaiting 读 -> 解析 -> 携全 id 调既有写接口，服务端零新接口）。
3. Web：详情页（既有壳）在 awaiting_human 态渲染 approve/release 按钮 -> 既有 POST 端点。
4. 契约同步：PRD §5.1（surface 枚举 + 派生规则）§4.2 Web 表 §29（职责边界重裁）§4.3（invalid_record 实例清单）；SKILL.md 收尾协议。

### What（具体交付物）

1. `services/identity.py`（或写层单点）：受托参数 -> (delegated, payload) 派生 + 结构校验（kind 枚举 / basis 非空；非法 -> invalid_record，消息带参数名与示例）。
2. `services/operations.py`：7 操作（approve/release/release_all_stale/note/renew/reopen/abandon/set_expectations）加可选受托参数，写事件时落 payload。
3. `cli.py`：--on-behalf（7 命令）+ approve/release 零输入模式（G11：合入后 `uv sync --reinstall-package agent-kanban`）。
4. `api/requirements.py`：7 端点 body 可选 delegated 字段（approve 端点新增可选 body，ReopenIn | None 先例 requirements.py:111）。
5. `api/web.py`：详情页 awaiting 态 -> approve/release 按钮（release 须 reason，既有 invalid_record 语义）。
6. `mcp/server.py`：**零改动**（无受托参数、无新工具）。
7. 契约文档：PRD 四处 + skills/agent-kanban/SKILL.md 收尾协议。
8. 测试：AC（受托派生/配对/零输入三分支 + 非交互拒绝/结构非法拒绝/REST 字段/无参回归）+ e2e（Web 待决按钮）。
9. 本 BCD + spec。

---

## 3. Domain Event 流

### Domain Events

**零新事件 kind**。形状变化仅两个 additive 点：

1. `actor_surface` 枚举新增值 `delegated`（既有 mcp/cli/system 语义不变）。
2. 7 操作写的事件可携带 `payload.delegated = {kind, basis}`（可选字段；无受托参数＝无该字段，逐字不变）。

**配对规则**：任何 actor_surface=delegated 的事件必有结构有效的 payload.delegated，反之亦然（服务端单点派生保证零失配）。

### Commands

1. 7 个人面操作加可选受托参数（签名 additive，既有参数与写语义零改动）。
2. CLI approve/release：--requirement-id 可省（零输入＝客户端编排：list_awaiting 读 -> 恰好 1 条取之 / 多条交互选 / 0 条提示；解析结果携全 id 走既有写路径，服务端零接口变更）。
3. `release --all-stale` 可与 --on-behalf 组合（每个被释放 claim 的 release 事件带 payload）。

### Aggregates

无新表、无新列、无索引（payload 为既有 JSON 列；awaiting_human 为既有列；list_awaiting 为既有读路径 operations.py:936）。

### Policies（含隐含 Policy）

1. **L0（强）**：任何终态/确认迁移必须有**已发生**的人的决定（statement 或 agent 结构性做不了的 action）为源；agent 只翻译、不产生决定。执行面＝协议层（SKILL.md）+ 审计面（delegated + basis 板面可读 + 人回溯权 reopen/note），**非**机器强制——威胁模型 C（单主机、无凭据区分，「人跑 CLI」与「agent 跑 CLI」不可机辨）。
2. **服务端派生单点**：surface 值由服务端判定（人面 + 有效受托参数 -> delegated；无参/非法参 -> 现行为）；调用方不可直传 actor_surface（PRD §5.1/ADR 0002 先例延续）。MCP 面结构性不可能（无参数入口）——agent 自身动作恒 mcp，结构性无法标 delegated。
3. **kind 语义**：statement＝人会话表态（声明）；action＝人的工作面动作且 agent 结构性做不了（远端 PR merge；本地仓检测显式不算）。
4. **basis 声明级**：自由文本，存 payload、标注声明、不作事实（PRD §5.2 自报声明哲学，与 reported by 同边界）；不做机器验证。
5. **不可能性即门禁**：delete/archive/new/reconcile/prune 等无受托参数入口（CLI 不加 flag、REST body 模型无字段、MCP 无参数）——「代执行硬删」结构性不可能。
6. **零输入宁拒不猜**：0 待决＝提示零写；恰 1＝直接执行；多条＝交互列号选（带标题）；多条 + 非交互通道（非 tty）＝拒绝（列候选 + 提示携 --requirement-id）。解析复用既有 id 路径（A1 语义）。
7. **错误码零新增**：误用（格式非法 / kind 越枚举 / basis 空）-> invalid_record 新触发实例（PRD §4.3 清单 additive 更新；「每个码有唯一触发条件」纪律保持：invalid_record＝记录结构字段缺失/非法，实例清单只增）。
8. **Web 待决定位重裁（PRD §29/§4.2）**：Web＝只读视图 + task 生命周期（create/archive/delete）+ **待决操作入口（approve/release，限 awaiting_human 任务详情页）**；按钮＝人亲手，surface=cli + conn=rest:（非 delegated）。
9. **单向门纯 additive**：无受托参数路径、MCP 面、状态机、租约语义、错误码集、REST 无 body 调用、既有 surface 值行为均逐字不变。

---

## 4. BDD Given-When-Then 场景

### Scenario 1（happy path：代执行 approve——statement）
- Given: 任务 awaiting（kind=review），user 会话内说「合了，收尾吧」
- When: agent 跑 `cli.py approve --requirement-id <id> --on-behalf "statement:user 会话表态已合入"`
- Then: state=DONE；approval 事件 actor_surface=delegated、actor_conn=cli、payload={state:"DONE", delegated:{kind:"statement", basis:"..."}}；板面显「代执行（依据：…）」

### Scenario 2（happy path：代执行 approve——action）
- Given: agent 检测到远端 PR merge（git fetch 后目标 commit 在 origin main）
- When: agent 跑 `cli.py approve --requirement-id <id> --on-behalf "action:PR #8 merged (5089bfe)"`
- Then: 同 Scenario 1 但 kind=action；basis 指向 merge commit（人可独立核验）

### Scenario 3（happy path：CLI 零输入，恰 1 条）
- Given: 板上恰 1 条 awaiting（标题「人确认闭环…」）
- When: `cli.py approve`（无参数）
- Then: 直接对其执行（等价于携全 id 调用，事件形态与 Scenario 1/2 的无受托参数版一致）

### Scenario 4（happy path：Web 待决按钮）
- Given: awaiting 任务详情页（HTML）
- When: 人点击 approve
- Then: POST /{id}/approve（surface=cli、conn=rest:<8hex>、非 delegated），state=DONE，页面重拉显 DONE

### 边缘场景 1（零输入，0 条）
- Given: 板无 awaiting
- When: `cli.py approve`
- Then: 提示「无待决项」，零写

### 边缘场景 2（零输入，多条 + 非交互）
- Given: 2 条 awaiting；stdin 非 tty（管道/脚本）
- When: `cli.py approve`
- Then: 拒绝——列编号候选（id + 标题）+「请携 --requirement-id」提示，零写（宁拒不猜）

### 边缘场景 3（on-behalf 结构非法）
- Given: 任意板面
- When: `--on-behalf "foo"`（无冒号）/ `--on-behalf "badkind:x"`（kind 越枚举）/ `--on-behalf "statement:"`（basis 空）
- Then: invalid_record，消息含参数名与正确示例，零写

### 边缘场景 4（无受托参数回归）
- Given: 任意板面
- When: `cli.py approve --requirement-id <id>`（无 --on-behalf）/ 任意 MCP 工具 / REST 无 body 调用
- Then: 与现行为逐字一致（surface=cli 或 mcp，无 payload.delegated，错误码与信息形态不变）

### 边缘场景 5（委托结构拒绝）
- Given: 任意板面
- When: `cli.py delete` 尝试带受托参数 / REST DELETE 体带 delegated / MCP 工具传受托参数
- Then: CLI＝unrecognized arguments；REST＝body 模型无该字段（忽略/422，spec 定）；MCP＝参数不存在——三面结构性不可能

### 跨时段场景（人回溯重裁）
- Given: 某任务经代执行 approve 至 DONE（kind=statement，basis 指向某会话表态）
- When: 人后续发现 basis 与事实不符（人未说过该话）
- Then: 既有重裁路径不变——`reopen` + `note`（人亲手，surface=cli）更正；代执行事件自身不可编辑（append-only），更正链可回溯

---

## 5. Spec by Example

### 例 1（代执行 approve）
- 输入: `cli.py approve --requirement-id bcd3a690… --on-behalf "statement:user 会话表态收尾"`
- 操作: agent 代执行收尾
- 预期: approval 事件行＝`kind=approval, actor_surface=delegated, actor_conn=cli, payload={"state":"DONE","delegated":{"kind":"statement","basis":"user 会话表态收尾"}}`

### 例 2（代执行 release）
- 输入: `cli.py release --requirement-id <id> --reason "方向不对" --on-behalf "action:user 自行关闭 PR"`
- 预期: release 事件 `payload={"reason":"方向不对","agent_name":"...","delegated":{"kind":"action","basis":"user 自行关闭 PR"}}`，actor_surface=delegated，state=OPEN

### 例 3（零输入，恰 1 条）
- 输入: `cli.py approve`；awaiting＝[任务 A]
- 预期: 等价 `approve --requirement-id <A 全id>`，返回 {requirement_id, state}

### 例 4（零输入，多条，交互）
- 输入: `cli.py approve`；awaiting＝[A, B]（tty）
- 预期: 输出 `1. <短id> <标题A>` / `2. <短id> <标题B>` + 选号提示；输入 1 -> 执行 A；输入越界/非法 -> 拒绝零写

### 例 5（REST delegated）
- 输入: `POST /requirements/<id>/approve` body `{"delegated":{"kind":"statement","basis":"user 会话原话"}}`
- 预期: 200，事件 surface=delegated；同 URL 无 body -> surface=cli（回归用例）

### 客户期望 vs 系统行为差异表

| 场景 | 客户期望 | 系统行为（现实现） | 冲突性质 | 差距 |
|---|---|---|---|---|
| agent 代执行收尾 | 受托标记 + 依据在同一条事件，板面直读「代执行（依据：…）」 | surface=cli 与人亲手不可辨；依据散落前置 note 事件（权宜流程） | 能力缺口（本批填平） | 受托面（Q3） |
| 人面收尾零输入 | `cli.py approve` 即执行 | --requirement-id required=True（cli.py:280） | 能力缺口（本批填平） | 零输入（Q4） |
| Web 确认 | 待决任务 Web 一键确认 | 决策操作 CLI/REST-only（PRD §29；web 详情页仅 archive/delete） | 定位重裁 | 待决页（Q4） |
| 审计区分 | 「人做的」vs「agent 代做的」可机辨 | surface 仅 mcp/cli/system 三值（agent 跑 CLI 与人跑 CLI 不可辨） | 能力缺口（本批填平） | delegated 值（Q3） |

---

## 6. Premortem（假设 6 个月后失败）

### 失败原因 1（业务规则维度）：agent 滥用受托面自产决定
- 失败序列: agent 编造 basis，或以本地仓 ff 折入等「自己的动作」标 action 自我认证 -> 终态决定源被污染 -> 人发现「这个 DONE 不是我定的」-> 看板唯一可信终态（PRD §5.2）信用崩塌，回溯资产作废。
- 预防: SKILL.md 协议硬约束（action 限 agent 结构性做不了的动作，本地仓检测显式列反例；statement 必须指向真实会话表态）+ 板面「代执行」显著展示（人一眼可回溯）+ 人重裁权（reopen + note，跨时段场景）。
- 残余: 同主机不可机辨（威胁模型 C）无法机器拦截——L0 在协议层 + 审计面成立，这是系统上限（与 reported by 声明面同边界）；残余风险由人回溯吸收。

### 失败原因 2（跨边界语义维度）：delegated 被误读为「人执行」
- 失败序列: 下游（export/复盘/未来自动化）把 surface=delegated 读作「人亲手动作」-> 归因漂移（agent 代执行动作计入人的直接动作）-> 决策统计与回溯样本失真。
- 预防: PRD §5.1 派生规则措辞钉死「delegated＝人面上代执行，源＝已发生的人的决定」；板面展示措辞＝「代执行（依据：…）」（非「人确认」）；spec 契约同步清单含展示措辞。
- 残余: 无（措辞是可测试契约）。

### 失败原因 3（业务规则维度）：零输入误伤
- 失败序列: 多条待决 + 交互选错（标题看串），或后人把非 tty 路径改成「取第一条」-> 错任务 DONE -> 真正待决任务滞留、错任务终态被污染。
- 预防: 宁拒不猜（非 tty 多条＝拒绝，边缘场景 2）+ 编号列表带标题 + 解析复用 id 正常路径（A1）+ AC 含越界输入拒绝断言（零写）。
- 残余: 人交互时看串标题属人的失误（非系统缺陷），接受。

### 失败原因 4（技术维度）：surface/payload 失配
- 失败序列: 未来新操作或写路径设 surface=delegated 却漏 payload.delegated（或反之）-> 审计配对断裂 -> 回溯工具两边都不可信，受托面退化为「半个标记」。
- 预防: 单点派生函数（surface 与 payload 同函数同批落值，7 操作全走它，禁直接构造）+ AC 配对断言（全量：surface=delegated 事件必有有效 payload.delegated，反之亦然）。
- 残余: 无（断言为全量不变量，可机器验证）。

### 失败原因 5（技术维度）：approve 端点 body 变更回归
- 失败序列: `POST /{id}/approve`（现无 body）加可选 body 后实现把它当必填或解析变严 -> 既有 REST 调用方（e2e/人面脚本）422。
- 预防: body＝`DelegatedIn | None`（ReopenIn | None 先例，requirements.py:111）；AC 含无 body 回归用例。
- 残余: 无。

---

## 7. 业务不变量

### 强不变量（违反即业务失败）

1. **L0 人决定源**：任何终态/确认迁移（DONE/REJECTED/CANCELLED/release->OPEN）必须有已发生的人的决定（statement 或 agent 结构性做不了的 action）为源；agent 只翻译、不产生。执行面＝协议层（SKILL.md）+ 审计面（delegated + basis 板面可读）+ 人重裁权；无机器强制（威胁模型 C）。违反后果：唯一可信终态源被污染，看板核心资产（可回溯性）失效。
2. **不可能性即门禁**：delete/archive 等破坏性/非确认操作无受托参数入口（CLI/REST 结构性缺席）；MCP 12 工具面无受托入口（agent 自身动作恒 surface=mcp，结构性不可标 delegated）。违反后果：agent 可代执行破坏性操作/自我标代执行，审计模型崩塌。
3. **受托面与 payload 配对**：surface=delegated 与 payload.delegated={kind,basis} 结构有效（kind ∈ {statement, action}，basis 非空）当且仅当同时成立；服务端单点派生（同函数落值）。违反后果：审计配对断裂，回溯失锚。
4. **单向门纯 additive**：无受托参数路径、MCP 面、状态机、租约语义、错误码集、REST 无 body 调用、既有 surface 值行为均逐字不变；invalid_record 新触发实例为 additive（每码唯一触发条件纪律保持）。违反后果：存量调用方断裂，单向门纪律失守。
5. **零输入宁拒不猜**：0 待决＝提示零写；恰 1＝执行；多条 + 交互＝列号选（越界输入＝拒绝）；多条 + 非交互＝拒绝。一切拒绝分支零写。违反后果：错任务终态变更。

### 软约束（违反可容忍）

1. **basis 声明级**：不做机器验证（PRD §5.2 自报声明哲学，与 reported by 同边界）。违反后果：无（若未来做验证属独立演进）。
2. **Web 待决仅两按钮**：只 approve/release（限 awaiting_human 详情页）；不扩成全管理页。违反后果：Web 面膨胀，偏离「记录面不是控制面」定位。
3. **不做服务端事件检测/webhook**：YAGNI，演进点登记 known-gaps。违反后果：（若未来做）外部依赖 + 信任边界扩大，需单独评审。
4. **零 schema 变更**：不加表/列/索引。违反后果：部署/迁移面扩大，与本批档位不符。

---

## 修订记录

- 2026-10-27 创建（主循环）。来源：user 2026-10-27 会话两段原话（零输入痛点 + 收尾协议）+ 四决策点裁决（Q1 确认源 / Q2 委托范围 / Q3 审计形态 / Q4 兜底面，user「可以」）+ 现状代码取证（identity.py 服务端派生先例 / cli.py:280 approve required / requirements.py REST 面 + ReopenIn|None 先例 / web.py 详情页仅 archive/delete / awaiting_human 列 + list_awaiting 读路径 operations.py:936 / events.payload JSON 列 / PRD §29/§4.2/§4.3/§5.1/§5.2）。
