# 对抗审查报告：批 2 A1 短 id 前缀匹配 + A2 update_progress 返回租约态

**审查对象**: `docs/superpowers/specs/2026-10-27-a1a2-mcp-surface-design.md`（主）+ `docs/business-contracts/a1a2-mcp-surface.md`（BCD 随审）
**仓基**: worktree a1a2-mcp（只读审查；代码引用逐一到仓内核验，关键存储语义实测）
**日期**: 2026-10-27
**方法**: adversarial-review 全景入口；能力语义为主 -> requirements-review 主轴 + design-review 四层/线面/BCD 前置检查；对象为单向门（MCP 产品面新错误码 + 新返回字段）-> 全量深审

---

## verdict: REJECT

**最高 severity 摘要（P1-1）**：spec 核心设计主张「前缀解析单点改 `require_requirement` 即三面生效」与代码现状矛盾——解析结果不传播：全部调用方（`get_active_claim` 的 Claim 查询、`add_event`、`touch_activity`、`transition`、claim INSERT、view 子查询、返回 echo）后续都用**原始输入串**。按 spec 字面实施，唯一前缀输入（spec §4 矩阵声明「命中（新）」）在多数工具上产生 FK 违例裸异常（`PRAGMA foreign_keys=ON`，db.py:62）、假 `no_active_claim`、或读面静默空数据；且 spec §7 强 5 验收锚「前缀逻辑仅存在于 write_guard.py」会反向否决正确实施所需的调用点改动（自毁锚）。需重写 A1 传播机制后 resume 原审者续审。

共 3 条 P1 + 6 条 P2。修正路径明确、有界，重写预计为节级修订而非推倒。

---

## P1 清单

### P1-1 「单点生效」为假主张：解析结果传播机制缺失，字面实施使 A1 全线不可用

**位置**: spec §2.1（实现位置）、§2.2 步骤 2「1 命中 -> 用该 id 继续（后续逻辑与全 id 传入完全一致）」、§4 兼容矩阵第 3/5 行、§7 强 5 验收锚
**理由（逐点核到代码）**:
- `require_requirement`（write_guard.py:13-17）返回 `Requirement`，但**所有下游使用原始 `requirement_id` 参数串**：
  - write_guard.py:20-29 `get_active_claim`：先调 `require_requirement`（结果丢弃），再用**原始参数**查 `Claim.requirement_id == requirement_id` -> 前缀输入 0 行 -> 假 `no_active_claim`（需求明明有活跃认领）。影响 add_subtask/update_subtask/add_milestone/update_milestone/add_record/update_progress/request_review/mark_blocked（operations.py:522/564/618/646/682/721/754/837）。
  - operations.py `note`(:306-313) 等：`add_event(requirement_id=<原始串>)`（operations_util.py:34 原样落 `events.requirement_id`）-> FK 违例（db.py:62 `PRAGMA foreign_keys=ON`；models.py:125-127 events.requirement_id FK）-> `run_op` 只映射 locked/busy（db.py:184-189），IntegrityError 裸抛 -> MCP `_call` 只捕 BusinessError（server.py:46）-> 非结构化错误；REST -> 500。
  - operations.py:459-473 `claim_task`：`INSERT claims` 带原始 id -> 同样 FK 违例。
  - operations.py:328-339 `reopen` 经 `transition`（state_machine.py:51-63）：`UPDATE ... WHERE id=<原始串>` rowcount=0 -> 假 `not_found`。
  - lease.py:30-36 `touch_activity`：`UPDATE claims WHERE requirement_id=<原始串>` -> 0 行，**静默**不更 last_activity_at。
  - view.py:471-482 `detail` / :61-72 `summary`：requirement 命中，但 claim/subtask/milestone/event 子查询全用原始串 -> 全空 -> 深潜页静默显示「无认领、无事件」。
- 后果：spec §4 矩阵「8~31 位 hex，唯一命中 -> 命中（新）」在该设计下不可达；A1 验收用例 1（「写操作断言事件落进正确需求」）在字面实施下必红。
- 自毁锚：spec §7 强 5 验收锚「diff（前缀逻辑仅存在于 write_guard.py）」会把正确实施所必需的调用点 rebinding 判为违规。
- 归类：高频偏差模式「实现普查冒充契约推导」——普查了「各面都经过该函数」，未验证「解析结果是否被后续使用」；「已覆盖」未语义验证。
**建议（修正路径）**:
1. §2.1 改为「解析单点 + 传播规则」：`require_requirement` 返回解析后的 `Requirement`；每个 operations/view 函数在首次解析后将 `requirement_id` 重绑定为解析值（或向 `get_active_claim`/`transition`/`add_event`/`touch_activity` 传解析值）；`get_active_claim` 必须用解析值查 Claim。
2. 在 spec 中列出受影响调用点清单（get_active_claim Claim 查询、add_event、touch_activity、transition、claim_task INSERT、view.detail/summary 子查询、各函数返回 echo），实施 diff 逐点核对。
3. §7 强 5 锚改为「解析算法仅存在于 write_guard.py + 全部调用点下游使用解析值（diff 核对清单）」。
4. §4 矩阵加注：「命中（新）」以传播规则为前提下成立。

### P1-2 A2 钉死返回代码与声明语义 / BCD 三处矛盾（单向门返回面）

**位置**: spec §3.1 代码块 vs §3.1 第 3 条 bullet vs BCD §4 Scenario 1 Then
**理由**: 钉死代码 `return {"requirement_id": requirement_id, "lease_expires_at": ...}` 用**函数原始参数**；其下 bullet 声明「原字段 `requirement_id` 保留（**返回解析后的 32 位全 id**）」；BCD Scenario 1 Then「返回用解析后的全 id，不回填短前缀」。现码结构下（operations.py:721 `get_active_claim(session, requirement_id)`，参数原样流到 :736 返回），照钉死代码实施：前缀输入 -> 返回短前缀，违背 spec 自己的声明与 BCD。P1-1 的「后续逻辑与全 id 传入完全一致」同样覆盖不到返回面（返回是行为的一部分）。三处指令在可观测行为上分歧、无一处钉死 -> 第三实现者必然掷硬币，且掷在单向门（MCP 产品面）上。
**建议**: 钉死代码改为 `claim.requirement_id`（claim 为已加载 Claim 行，其 requirement_id 即解析后全 id，零额外查询，与「零额外查询」声明一致）；或显式声明「函数入口已按 P1-1 传播规则重绑定，参数即全 id」并让代码块与之对齐。二选一，钉死一处。测试侧补「前缀输入 -> 返回 requirement_id 为 32 位」断言（见 P2-5）。

### P1-3 §5.5 SKILL.md 预核对基于误引：SKILL.md:22 实际含与 A2 显性化语义直接冲突的措辞

**位置**: spec §5.5；skills/agent-kanban/SKILL.md:22；ADR 0006；PRD §3.2:113
**理由**: SKILL.md:22 实际文本：「租约：lease 2h / idle 30min（可配置）。**任何 MCP 写操作都是活动**，**租约自动续**。长时间无活动 -> SUSPECT，过期 -> STALE」。「租约自动续」与 ADR 0006 / PRD §3.2（写操作只更 last_activity_at，lease_expires_at 固定，仅显式 renew 延长）直接矛盾，是**存量契约冲突**且未登记 known-gaps。spec §5.5 引用的示例措辞（「写 progress 不延租」）不是 SKILL.md 实际文本，其预期分支「无冲突 -> 零改动」不成立。此冲突正是 BCD §6 失败原因 2 要防的误读模式，且恰恰载于 agent 主读的协议文档。
**后果**: 本批落库后，docstring/PRD 说「返回仅为通知，不延长租约；续租用 renew」，SKILL.md 说「租约自动续」——同批两个契约面直接矛盾，agent 依 SKILL.md 停调 renew -> 租约过期 -> STALE -> 写操作 lease_expired，即 BCD 自己列的失败序列 2。
**建议**: §5 增 SKILL.md 修订项（:22 改为「任何 MCP 写操作都是活动（更 last_activity_at，防 SUSPECT）；租约不自动续——延长需显式 renew（或依 update_progress 返回的 lease_expires_at 决策）」，具体措辞由 user 裁决）；在 spec 修订记录登记该存量冲突（见本报告「正典老化 / 冲突」节）。若作者认为该措辞可解读为「活动使租约保持有效」，须在 spec 中显式引用原文并给出裁决，不得默认零改动。

---

## P2 清单

### P2-1 契约同步遗漏：4 处本批后变陈旧
**位置**: spec §5（同步面清单）
**理由**:
- docs/design.md:135 重复了 PRD §4.3 九码列表（正典副本），不在同步清单 -> 批后两处正典列表分叉。
- src/agent_kanban/errors.py:1 docstring「PRD 4.3 九码」-> 十码。
- src/agent_kanban/api/requirements.py:3-6 docstring 错误映射注释 -> 缺 ambiguous_id=409。
- skills/agent-kanban/SKILL.md 错误码速查表（:54-64）-> 缺 agent 开始会实际收到的新码（处置＝加长前缀重试）。
**建议**: §5 四处各补一行同步动作。

### P2-2 BCD §5 例 2 输入与已裁决的最小长度自相矛盾
**位置**: BCD §5 例 2 vs BCD §1 待澄清项 1 / spec §2.2 步骤 3
**理由**: 例 2 用 4 位前缀 `7f00` 期望 `ambiguous_id`；但裁决值是最小 8 hex，<8 位 -> not_found。照该例写歧义判别用例会得到错误测试（断言 not_found 场景返回 ambiguous_id）。
**建议**: 例 2 输入改为 8 位同前缀（如 `7f00aaaa`）。

### P2-3 测试用例 10「renew 与 update_progress 返回一致」调用顺序未钉
**位置**: spec §6 用例 10
**理由**: 值相等只在「renew 之后调 update_progress」时成立（renew 先更新 claim 行，update_progress 读回新值）；反序必不等（renew 返回 now+lease）。按字面「同场景」实施，顺序选择不同 -> 正确实现下测试可能红。
**建议**: 钉序列（renew -> update_progress -> 断言两 lease_expires_at 相等）；或改写为口径断言（两者均为 claim 行 lease_expires_at / now+lease 的 iso 序列化，格式逐字一致）。

### P2-4 「等 N 个」错误消息形态 N 的语义未钉
**位置**: spec §2.2 候选上限段
**理由**: 「>5 时列前 5 + 等 N 个（N=实际总数）」——总数 6 时读作「5 + 6 = 11」，与总数 6 矛盾；「等 N 个」习惯语义是剩余数（N=总数-5）。测试用例 3 只断言「计数形态存在」，不钉公式，两种实现都绿 -> 契约未定。
**建议**: 钉死模板（如「…等，共 6 个候选」，N=总数；或「等 1 个」，N=总数-5），用例 3 断言具体文案。

### P2-5 前缀输入下其余工具的返回 echo 语义未定义 + 无测试钉
**位置**: spec §3（仅钉 update_progress）、§6 用例 9
**理由**: 现码所有操作（note/renew/claim_task/add_record/…）返回 echo 原始参数。前缀输入时「返回哪个 id」是新行为，spec 只对 update_progress 声明（全 id），其余 10+ 操作未定义；用例 9 只断言「原字段仍在」，不断言值＝全 id。
**建议**: 在 A1 节声明「全部操作返回解析后全 id」（P1-1 传播规则下自然成立）；测试补至少一条非 A2 工具断言（如 claim_task 前缀输入 -> 返回 requirement_id 为 32 位 hex）。

### P2-6 32 位全 id 的大小写/空白行为未定义
**位置**: spec §2.2（s=strip().lower() 预计算 + 「全 id 输入行为不受影响」）vs §5.1 PRD 同步文「大小写不敏感」vs §4 矩阵
**理由**: 全 id 输入先 lower 后精确匹配，则大写 32 位 id（现 not_found）将变为命中——与「现行为逐字保留」表述冲突；PRD 同步文又写「大小写不敏感」。两文不一致，矩阵无大写全 id 行，用例 7 只覆盖前缀大小写。
**建议**: 裁决（建议与前端一致：大小写不敏感，统一 strip+lower）；§4 矩阵加大写全 id 行；用例 7 补全 id 形态。

---

## 疑点待核（不计入 verdict，供作者定向补证）

1. BCD 痛点「抄 32 位 id 易错且笨重」「agent 长任务反复写 progress 却不知何时 renew」为重建（调研交付原文未落盘，BCD §1 已诚实标注），非实际痛点记录。user 即疼痛者（单用户系统），转述失真风险低，不阻塞；如需补强，建议补一条真实误抄/多往返实例。
2. BCD §1 的 A1-a/b/c 集合意义上不互斥（b ⊃ a、c ⊃ a），作为「本批范围裁决」互斥（做 a 不做 b/c）且 BCD 已按交付面/范围裁决 framing——接受，不定级。
3. BCD §3 Commands「（MCP 12 工具 + REST + CLI）」：12 工具中仅 10 个带 requirement_id（list_tasks/list_awaiting 无）。措辞不精确，spec 的 10 工具清单正确，不影响实施。

## 正典老化 / 冲突（必填节）

1. **SKILL.md:22「租约自动续」 × ADR 0006 / PRD §3.2:113**——存量正典冲突，未登记 known-gaps。代码与 ADR 为事实（写不延租）；SKILL.md 措辞 stale/erroneous。本批（A2 显性化的目的）是天然修复点；spec §5.5 预期「零改动」不成立（见 P1-3）。交 user 裁决修订措辞。
2. **errors.py:1 / api/requirements.py:3-6 / docs/design.md:135 / SKILL.md 错误表** 四处错误码清单与 PRD §4.3 当前一致；本批 PRD 更新后四处变 stale（P2-1）。
3. ADR 0006 与代码一致（touch_activity 只更 last_activity_at、renew 更双字段+写事件，均已核）——未老化。AGENTS.md 基线 592/592、e2e 15/15 与 spec 引用一致（未重跑，见未核区）。

## BCD 7 节抽查

- **齐性**: 7 节齐（原话语义 / Impact Mapping / Domain Events / BDD / Spec by Example / Premortem / 业务不变量）。
- **§1 解读互斥**: A2-a vs A2-b 为真根本分歧（通知 vs 续租，动/不动租约模型）；A1 三读为范围裁决，framing 成立。原话未落盘的诚实标注在位。
- **§5 根本性冲突**: 「写 progress＝活跃＝续命」vs ADR 0006 冲突成立，收口方式（规则显性化 + 模型不动）与 spec 一致。
- **§6 失败原因具体性**: 4 条均可推出具体失败序列；F1/F4 可测可断言，F2/F3 残余声明正确（agent 带外认知 / 评审面）。
- **§7 分类与后果**: 强 1-5 各有真实违反后果；软 1-3 容忍理由具体。
- **BCD × spec 一致性**: Policy 1-6 与 spec 非目标/矩阵一致；例外两处——返回面三处矛盾（P1-2）、例 2 输入错误（P2-2）。

## 第 4 层事实核对（已核清单）

| 引用 | 核验结果 |
|---|---|
| 存储形态 32-hex 无连字符 | 实测：`UUIDHex` + `uuid4().hex`，SQLite 存储 32-hex；`id LIKE '<前缀>%'` 8/9/16 位前缀均命中；EXPLAIN QUERY PLAN = USING COVERING INDEX（主键索引）——BCD §3/§6-F4「前缀锚定、主键索引可用」主张成立 |
| write_guard.py choke point | ✓ 13-17 行如引；但「单点生效」结论不成立（P1-1） |
| operations.py update_progress / renew | ✓ :710/:736 返回 `{"requirement_id"}`；:293 `new_expiry.isoformat()`；A2「零额外查询」成立（claim 于 :721 加载、touch_activity :735 不更 lease_expires_at） |
| view.py:61/:471 读操作经 choke point | ✓ |
| MCP 12 工具、10 个带 requirement_id | ✓ server.py:204-217；spec 10 工具清单精确匹配 |
| REST/CLI 三面经 choke point | ✓ 结构成立（api/requirements.py:66-71/:191-193；cli.py:22-35；web.py JS 全部走 REST 路由无独立 id 处理）；「三面同源」≠「单点生效」（P1-1） |
| `PRAGMA foreign_keys=ON` | ✓ db.py:62（P1-1 后果依据）；run_op 不映射 IntegrityError（db.py:184-189） |
| ADR 0006 activity 口径 | ✓ 与代码一致 |
| PRD §4.3 :199 九码行 | ✓ 行号精确 |
| SKILL.md 租约措辞 | ✗ 与 spec §5.5 预想不符（P1-3） |

## 勘误附注（锚点/措辞漂移，不计 finding）

- BCD「operations.py:737 返回面」：实际 return 在 :736（:737 为空行）。
- BCD「write_guard.py:15 session.get」：实际 session.get 在 :14。
- spec §3.1「（naive UTC iso，与全仓时间序列化口径同源）」：实际两侧均为 **aware UTC**（UTCDateTime 读回附 timezone.utc；now_utc() aware），isoformat 形态 `…+00:00`（BCD 例 5 正确）；「口径一致」主张成立，「naive」措辞错误。

## 未核区 / 残留

- `spec-improvement-list.md:47`（跨批次产物，仓外）未核——BCD 已诚实标注原文未落盘。
- 592/592、e2e 15/15 基线未重跑（只读审查；与 AGENTS.md 正典一致）。
- api/web.py（31.6K）未通读；已核 JS fetch 路径（:240/:290/:392-393/:551/:560 全部指向 REST 路由，无独立 id 处理）。
- 用例 8（MCP × REST 跨面）在现有 harness 可行（ac_cases_f.py 真实 MCP HTTP 客户端 + ac_lib.py 真实子进程 REST），未实跑。

---

## 修正路径（resume 原审者续审的修订项）

1. **P1-1（必改）**: 重写 §2.1 为「解析单点 + 传播规则」，列受影响调用点清单；同步修订 §4 矩阵注记与 §7 强 5 验收锚。
2. **P1-2（必改）**: A2 钉死代码改 `claim.requirement_id`（或显式声明重绑定前提）；测试补前缀输入返回全 id 断言。
3. **P1-3（必改）**: §5 增 SKILL.md:22 修订项（措辞交 user 裁决）；修订记录登记存量正典冲突。
4. **P2 折入**: 同步遗漏 4 处（P2-1）；BCD 例 2 改 8 位前缀（P2-2）；用例 10 钉顺序（P2-3）；「等 N 个」钉模板（P2-4）；echo 语义声明 + 测试（P2-5）；大写全 id 裁决 + 矩阵行（P2-6）。

---

# 第 2 轮续审（spec v2 @ git 8c9d41d + BCD 同步修订）

**verdict: APPROVE-WITH-FIXES**（1 条新 P1 为表达式级钉死错误 + 2 条 P2，修正清单机械可折入、由 spec 自有用例判别；不重开设计）

**第 1 轮 3 P1 结构层全部闭合**：P1-1 的传播架构（解析单点 + 入口重绑定）成立，21 调用点清单逐点核对**准确无误**（见下）；P1-2 前提钉死一处；P1-3 存量冲突登记 + user 裁决 + 联动残余齐备。但压 P1-1 新增面时命中一个新 P1：钉死的重绑定表达式取值形态错误（P1-4）——这是「传播规则无新洞」检查的命中项。

## 逐条三态

| 第 1 轮 | 三态 | 核验 |
|---|---|---|
| P1-1 | **部分闭合，残留转 P1-4** | 架构正确；21 清单准确（13 直调 set_expectations/approve/release/renew/note/reopen/abandon/archive_requirement/delete_preview/delete_requirement/claim_task/request_review/mark_blocked 逐一对照 operations.py 行号确认入口已直调 require_requirement；6 不直调 add_subtask/update_subtask/add_milestone/update_milestone/add_record/update_progress 确认经 get_active_claim；view summary :61/detail :471 确认）；零改动面声明与代码一致（transition/add_event/touch_activity/get_active_claim 均只接收参数，调用方重绑定后传全 id）；get_active_claim 内部既有 require「identity-map 命中无额外 SQL」主张成立（同 session 二次 session.get 走 identity map）；§7 强 5 锚自毁已解；§4 矩阵加前提注。**残留**：钉死表达式 `requirement_id = req.id` 的取值形态错误（P1-4） |
| P1-2 | **形式闭合，依赖 P1-4** | §3.1 前提钉死一处 ✓、用例 10 补 32 位断言 ✓；但断言在现钉死表达式下必红（req.id 为 36-hex，P1-4），折入 P1-4 修复后转绿 |
| P1-3 | **closed** | §5.5 登记存量冲突 ✓；建议措辞与 ADR 0006/PRD §3.2 语义逐字核对准确（写更 last_activity_at 防 SUSPECT / 租约固定 / 显式 renew 延长）✓；user 裁决挂起 ✓；§8 裁决联动残余（若维持原文则 docstring/PRD 回退、两面不得矛盾）完备 ✓ |
| P2-1 | **closed** | §5 扩至 9 处，第 1 轮 4 处遗漏全覆盖；§5.9 将 ambiguous_id 移出「agent 面专用码」归类正确（REST 路由可传前缀，存在触发端点） |
| P2-2 | **closed** | BCD 例 2 改 `7f00aaaa`/`7f00aaab` 共享 8 位前缀 ✓ |
| P2-3 | **closed** | 用例 11 钉 renew -> update_progress 顺序；值相等语义已核：renew 更新 claim 行后 update_progress 读回新值，相等成立 ✓ |
| P2-4 | **closed（一处依赖 P1-4）** | 模板钉死「共 {total} 个候选」N=总数 ✓、用例 3 逐字断言 ✓；错误消息内**候选 id 的形态**（32-hex 还是 36-hex）未钉——并入 P1-4 修复（候选来自 LIKE 扫描的 ORM 读回，未归一则错误消息列 36-hex 候选，agent 照候选加长前缀重试 -> len 36 -> not_found，补救路径自断） |
| P2-5 | **形式闭合，依赖 P1-4** | §2.1 统一声明 + 用例 9 claim_task 断言 ✓；同 P1-2，断言依赖 P1-4 修复 |
| P2-6 | **closed（一处延伸 -> P2-8）** | 归一裁决（strip + 大小写不敏感适用全部输入）✓、矩阵加大写全 id/空白行 ✓（「现行为 not_found」两格已实测准确：大写 32 位、空白填充 32 位现行为均 miss）、强 2 措辞 + 用例 7 ✓；**36 位连字符形态未覆盖**（P2-8） |
| 勘误 naive UTC | **closed** | §3.1 改 aware UTC（`…+00:00`）✓ |
| 勘误 BCD 行号 | **closed** | :736 / :14 已改 ✓（对照代码准确） |
| 疑点 1 | **closed** | BCD §1 补痛点实例（人面 approve 须抄 32 位全 id，每批收尾必做）具体可查 ✓ |
| 疑点 2 | **接受不定级** | 维持（范围裁决 framing 成立） |
| 疑点 3 | **closed** | BCD §2 Who / §3 Commands 改「MCP 10 个带 id 工具」✓ |

## 新增发现

### P1-4（新）钉死重绑定表达式 `requirement_id = req.id` 取到 ORM 读回形态＝36 位连字符，非 32-hex

**位置**: spec §2.1 传播规则代码块；连带 §2.2 ambiguous_id 模板候选列表、§2.1 返回面声明、§4 矩阵「全 id 输入零变化」
**理由（实测证据）**:
- `session.get(Requirement, "32hex").id` 读回 = `'396f5837-3051-4ab5-a396-3dd58563bdcd'`（len 36，带连字符）；`claim.requirement_id` 读回同样 36 连字符。仓内 `ids.py:5` norm_id docstring 早已声明此事实：「Uuid(as_uuid=False) 读回 36-char 带连字符，统一为 32-hex 无连字符——与写路径内存实例/create 响应及事件 payload 引用一致」。存储层是 32-hex（第 1 轮实测），但 **ORM 读回形态是 36 连字符**——models.py 顶部「UUID 存 32 位无连字符 hex」指的是存储，作者把存储形态当成了读回形态。
- 后果一（返回面契约违背，单向门）：19 个重绑定函数的返回 echo 全部变为 36 连字符，而 §2.1 第 5 条 / §3.1 / §4 矩阵 / BCD Scenario 1 钉的是「32 位全 id」；用例 9/10 的「32 位 hex」断言在钉死代码下必红。
- 后果二（既有行为回归，违背强 2/强 3）：现码对 32-hex 输入 echo 原始参数（响应 32-hex）；重绑定后同一输入响应变 36 连字符——§4 矩阵「全 id 输入零变化」为假。现有一切消费响应 requirement_id 的自动化（含人面 CLI 输出）形态变更。
- 后果三（解析器往返死路，契约自相矛盾）：新算法 len 36 -> 步骤 3 -> not_found。系统 echo 出自身输入契约拒绝的 id 形态：agent 取 claim_task 返回的 requirement_id 续调 -> not_found。这直接摧毁 A2「返回自足、无需再调 list_tasks」的立项目的（BCD §2 Why），并经 ambiguous_id 错误消息的候选列表二次出现（见 P2-4 依赖项）。
- 附注（第 1 轮审者责任）：第 1 轮 P1-2 建议的 `claim.requirement_id` 同样读到 36 连字符，单用亦不足——根因在读回形态，本轮实测补上。v2 的入口重绑定架构正确，只差取值归一。
**建议（折入修复）**:
1. §2.1 钉死表达式改为 `requirement_id = norm_id(req.id)`（ids.py 既有 canonical 助手，docstring 声明与 create 响应/事件 payload 形态对齐）；BCD §2 What 1 / 强 5「重绑定解析值」同步明确「归一 32-hex（norm_id）」。
2. §2.2 ambiguous_id 模板钉死：候选 id 列表为 32-hex 归一形态（扫描读回经 norm_id）。
3. 用例 9/10 的「32 位 hex」断言保持不动（折入后转绿；若再钉错则红——判别力保留）。

### P2-7（新）21 调用点台账漏列 export_data

**位置**: spec §2.1 调用点清单 / 零改动面
**理由**: operations.py:946 `export_data`（可选 requirement_id 参数，委托 view.detail）是第 20 个 operations 取 id 函数，与 get_task_detail 同为纯委托，正确处置＝零改动（view.detail 入口重绑定已覆盖）；但清单只列了 get_task_detail 一个委托零改动项，export_data 未列。「实施 diff 逐点核对」会撞上未列名的取 id 函数（误判遗漏，或实施者加冗余重绑定）。全仓 `requirement_id: str` 签名系统 grep 已穷举：除 21 + get_task_detail + export_data 外，其余均为私有助手（_check_payload_size/_maybe_write_retry_limit/_persist_self_assessment/_claim_timeline）或零改动面，无其他遗漏。
**建议**: 零改动委托注扩为「get_task_detail / export_data 纯委托 view.detail，零改动」。

### P2-8（新）36 位连字符全 id 输入：现行为命中，v2 算法 not_found，未声明

**位置**: spec §2.2 步骤 3（「33+ 位 -> not_found（与现行为一致）」括注对该形态为假）/ §4 矩阵
**理由**: 实测 `session.get(Requirement, "396f5837-3051-...")`（36 连字符）现行为**命中**（Uuid 类型 bind 归一）；v2 算法 len 36 -> 步骤 3 not_found——精确匹配路径对该现存合法输入形态收窄，矩阵无行、BCD 强 2（「小写 32 位」措辞）未覆盖、PRD 同步句未提及。现实暴露低（无现响应面输出 36 形态，人面需手工粘贴 ORM 形态才触发），但属未声明的输入面行为变更，且步骤 3 括注「与现行为一致」失实。
**建议（二选一，须显式裁决）**: 推荐归一扩展 `s = raw.strip().lower().replace("-", "")`（保持精确路径现接纳，additive；连字符前缀如 "396f-5837" 归一后 8 位进前缀路径，同属 additive 放宽）+ 矩阵加行 + 用例 7 补形态；或显式声明收窄（矩阵加行「36 连字符全 id | 命中 | not_found（声明收窄）」+ PRD 同步句注明）。

### 新增勘误（不计 finding）

- spec §5.4 docstring「8+ 位唯一前缀」：8+ 含 33+，实际 33+ 不受理；宜「8~31 位唯一前缀」（§5.1 PRD 句已准确）。
- spec §2.2 步骤 1「未命中 -> not_found（现消息形态）」：消息内用 raw 还是 s 未钉（大写全 id 未命中时消息现显大写、归一后显小写）；宜三路径统一钉 raw（与步骤 2 括注及 task_id 钉法一致）。

## 新增面扫描（v2 新内容本身）

- 21 调用点清单：逐点核对**准确**（13+6+2 无多列、无错分；直调/不直调分类与代码行号一致）。
- 传播规则无其他新洞：DB 操作对 36-hex/32-hex bind 均归一（实测 WHERE 比较两形态均命中），形态问题只落在**字符串输出面**（返回 echo / 错误消息候选）与**输入契约**（长度门），已由 P1-4/P2-8 覆盖。
- §5.5 建议措辞：与 ADR 0006 核对准确；§8 裁决联动残余完备。
- §5.9 归类修正：正确（ambiguous_id 有 REST 触发端点）。
- 用例 11 顺序语义：值相等成立（renew 先行更新行）。
- §4 矩阵「现行为」列：大写全 id / 空白填充 / 33+ 三格实测均为 miss（现 not_found），准确。
- 新正典冲突：无新增（SKILL.md:22 仍待 user 裁决，已登记）。

## 折入修复清单（APPROVE-WITH-FIXES）

1. **P1-4**：§2.1 表达式改 `norm_id(req.id)`；§2.2 候选列表钉 32-hex 归一；BCD What/强 5 同步明确归一形态；用例 9/10 断言保持不动。
2. **P2-7**：§2.1 零改动委托注补 export_data。
3. **P2-8**：36 连字符形态裁决（推荐归一接纳）+ 矩阵行 + 用例 + PRD 同步句（若归一，§5.1 句补「连字符归一」）。
4. 勘误 2 条（§5.4「8~31 位」；步骤 1 消息用 raw）。
5. 折入后 spec 状态行与修订记录记 v3；BCD 修订记录同步一行。
6. 实施 diff 审查锚不变：21 调用点入口重绑定（norm_id 形态）+ 前缀逻辑仅 write_guard.py + 用例 9/10 红绿判别。

## 第 3 轮续审（终，spec v3 @ 370f838）

**范围**：核验第 2 轮折入清单 6 项闭合 + 扫 v3 折入引入的新面（`.replace("-","")` 归一边界、norm_id 出口覆盖）+ 终 verdict。

### 逐条三态（6 项折入）

| 项 | 三态 | 核验锚（v3 文件行） |
| --- | --- | --- |
| P1-4 | closed | §2.1 重绑定表达式 `norm_id(req.id)` + 归一形态段（:42：读回 36 连字符实测、norm_id canonical 助手、write_guard 加 import）；§2.2 候选读回 norm_id 归一后再入消息（:62）；BCD What（:68）/强 5（:211）同步；用例 9/10 断言未动（保持红绿判别） |
| P2-7 | closed | §2.1 调用点清单列 export_data（:943，requirement_id 可选）纯委托 view.detail 零改动，括注「审 P2-7 补列名」 |
| P2-8 | closed | §2.2 步骤 0 `s = raw.strip().lower().replace("-", "")` + 括注（:57-58：现行为命中实测、归一后走精确匹配＝行为不变、长度以去连字符 s 计）；§4 矩阵加 36 连字符行（:104）；用例 7 补形态（:136）；§5.1 PRD 句补「连字符去除」 |
| 勘误 1 | closed | §5.4 docstring「8~31 位唯一前缀」（:119） |
| 勘误 2 | closed | §2.2 步骤 1/3 消息统一钉原始输入 raw（:59/:63） |
| 状态/修订 | closed | spec 状态行 v3（:4）+ 修订记录 v3 节（:180-184）；BCD 修订记录一行（:225） |

### 新增发现

#### N1（P2）§5.1 PRD 同步句「响应/错误中的 id 均为 32-hex 形态」与 §2.2 raw 钉法冲突

**位置**: spec §5.1 第 1 条 PRD §4.3 id 解析口径句（:116）；BCD 强 2（:208）「响应/错误中 id 均为 32-hex 形态（norm_id 归一）」同句同源。
**理由**: 同文档 §2.2 已钉「错误 task_id 位传原始输入 raw」（:72）与「not_found 消息用原始输入 raw」（:59/:63）、ambiguous_id 第三参 raw（:65）——错误的 task_id 位与 not_found 消息可载 raw（大写/连字符/空白填充形态），不满足「均为 32-hex」。按 §5.1 句字面落入 PRD 会写入一条与本 spec 自身钉法矛盾的契约声明（ambiguous_id 消息内候选列表是 32-hex，但 task_id 位与 not_found 消息不是）。
**建议（单句改法）**: PRD 句末改为「响应的 requirement_id 与 ambiguous_id 错误候选列表为 32-hex 形态；not_found 消息与错误 task_id 保留原始输入」；BCD 强 2 同句同步限定。

### 新增勘误（不计 finding）

- **N2**: §6 用例 7（:136）「36 连字符全 id -> 命中且返回 echo 为 32-hex（现行为保持，审 P2-8）」括注不准——现 echo 为 36 连字符（P1-4 实测读回形态），新 echo 32-hex 属声明归一，保持的是命中结果而非 echo 字符串。宜改「（命中结果保持；echo 归一 32-hex）」。断言本身（echo 32-hex）正确，红绿判别不受影响。
- **N3**: BCD §2 Who 第 3 条（:58）「（大小写/空白统一归一属同类 additive 放宽）」漏「连字符」——Policy 3（:95）与强 2（:208）已三全（空白/大小写/连字符），此行系 v2 残留。补「连字符」。

### 新增面扫描（v3 折入本身）

**P2-8 归一边界（`.replace("-","")`）——自洽，无新洞**：
- 全连字符串（"-"、"---"）：s = "" -> len < 8 -> not_found，算法自然落位，无需特判。
- 连字符 + 前缀混合（"396f-5837"）：归一后 8 位 hex -> 前缀路径，additive 放宽，与 P2-8 推荐修法意图一致。
- 归一后 33+（连字符形态多拼位）：len(s) > 32 -> not_found，与步骤 3 一致；:58 括注「长度以去连字符的 s 计」已显式钉。
- 大写 + 连字符混合：lower + 去连字符 -> 精确命中，additive。
- LIKE 安全：进精确/前缀路径的 s 为纯 hex（hex 不含 %/_），无通配符转义面。
- 空串/纯空白：s = "" -> not_found，与现行为（session.get("") miss）一致。

**P1-4 norm_id 出口覆盖——全部 id 出口已覆盖**：
- 受影响出口三类均钉：21 调用点重绑定值（§2.1 表达式）、返回 echo（§2.1「返回面」统一声明）、ambiguous_id 候选列表（§2.2 :62）。
- 不受影响面核对：new_requirement 内存实例本就 32-hex；view/SSE 既有 norm_id 用法不动；subtask_id/milestone_id/claim_id 不参与归一（§1 非目标显式）。
- 无第四类 id 出口遗漏（REST 响应体经同一 operations 返回面；CLI 复用同函数）。

**正典老化/冲突**：无新增（SKILL.md:22 租约措辞仍待 user 裁决，已登记 §5.5/§8）。

### 终 verdict: APPROVE-WITH-FIXES

共识终态：以下 3 项折入即合，不复审。

1. **N1**（唯一 P2）：§5.1 PRD 句限定 32-hex 声明范围（响应 requirement_id + ambiguous_id 候选列表 32-hex；not_found 消息与 task_id 保留 raw），BCD 强 2 同句同步。
2. **N2** 勘误：用例 7 括注改「（命中结果保持；echo 归一 32-hex）」。
3. **N3** 勘误：BCD Who 第 3 条归一列举补「连字符」。

