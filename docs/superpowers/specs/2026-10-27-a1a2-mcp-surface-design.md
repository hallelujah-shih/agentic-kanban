# Spec: 批 2 A1 短 id 前缀匹配 + A2 update_progress 返回租约态

**日期**: 2026-10-27
**状态**: 对抗审查共识达成（2026-10-27，终态 APPROVE，3 轮同一审者）：第 1 轮 REJECT（3 P1 + 6 P2）全修正（v2）；第 2 轮 APPROVE-WITH-FIXES（P1-4 读回形态 + P2-7/P2-8）全折入（v3）；第 3 轮 3 项（N1 PRD 句自洽 / N2 用例 7 括注 / N3 BCD Who 连字符）折入（v3.1，审者声明不复审）。**user 审阅通过（2026-10-27，「按照你的建议实施」——含 §5.5 SKILL.md:22 建议措辞裁决）**
**分支/worktree**: a1a2-mcp（基于 main 8a60111，.worktree/a1a2-mcp）
**BCD**: `docs/business-contracts/a1a2-mcp-surface.md`（7 节齐；user 裁决 2026-10-27 设计草稿全批，四决策点按建议值：8 hex 最小前缀 / 仅 requirement_id / ambiguous_id REST=409 / A2 仅 lease_expires_at）
**板上任务**: 396f583730514ab5a3963dd58563bdcd
**关联**: PRD §4.1（MCP 工具面）§4.3（错误码）；ADR 0006（activity 口径）；`write_guard.py`（require_requirement choke point）；`operations.py`（update_progress/renew）；`api/main.py`（REST_ERROR_STATUS）；`server.py`（MCP docstring）；`skills/agent-kanban/SKILL.md`

---

## 1. 范围与非目标

**范围内**：
- A1：requirement_id 唯一前缀解析（解析单点 + 调用点传播规则，见 §2）+ 新错误码 `ambiguous_id`
- A2：`update_progress` 返回加 `lease_expires_at`
- 契约同步：PRD §4.3、api/main.py REST 映射、server.py docstring、SKILL.md（租约措辞修正 + 错误码表）、design.md/errors.py/api docstring（见 §5）
- 测试（AC 用例，见 §6）

**非目标（显式）**：
- 不动展示面（板面/web/export 仍显 32 位全 id；输入侧放宽、展示侧不短化）
- 不动 subtask_id / milestone_id / claim_id 解析（维持精确匹配）
- 不动租约语义：activity 只更 last_activity_at（ADR 0006），A2 返回是通知、不延长 lease_expires_at
- 不动 32 位小写全 id 精确匹配路径与 not_found 语义（逐字不变；大小写/空白统一归一属与 prefix 同类的 additive 放宽，见 §4）
- 解析算法只允许存在于 write_guard.py；禁止各面（MCP/REST/CLI）或下游助手函数（transition/add_event/touch_activity/get_active_claim）自行实现前缀逻辑（BCD Policy 4）
- 不做前缀长度可配置化（8 为代码常量）
- 零 schema 变更（不加表/列/索引）

## 2. A1 设计：id 前缀解析（解析单点 + 传播规则）

### 2.1 实现位置与传播规则（v2 重写，审 P1-1）

**解析单点**：`src/agent_kanban/services/write_guard.py::require_requirement` 内实现 §2.2 算法（只解析、返回 `Requirement` 或 raise；前缀逻辑全仓唯一）。

**传播规则（钉死）**：所有取 `requirement_id` 的公开函数**入口先解析、再重绑定**，下游一律用全 id：

```python
req = await require_requirement(session, requirement_id)
requirement_id = norm_id(req.id)  # 重绑定：下游（Claim 查询/事件/租约/子查询/返回 echo）统一用 32-hex 全 id
```

- **归一形态（v3，审 P1-4）**：`Requirement.id` 的 ORM 读回形态是 **36 连字符**（UUIDHex 类型；ids.py norm_id docstring 为正典声明，已实测 `session.get(...).id` = 36 连字符）。`norm_id`（ids.py 既有 canonical 助手）统一为 32-hex——一切重绑定值、返回 echo、错误消息候选必须是 32-hex 形态（写路径内存实例本就是 32-hex，norm_id 即对齐该形态）。write_guard.py 加 import `from .ids import norm_id`。
- 全 id 输入时重绑定为 no-op（norm_id 对 32-hex 输入是恒等），零行为变化；prefix 输入时下游与「全 id 传入」逐字一致。
- **调用点清单（21 处，实施 diff 逐点核对）**：
  - operations.py 19 个函数：
    - 入口已直调 require_requirement（13 个，加 1 行重绑定）：set_expectations / approve / release / renew / note / reopen / abandon / archive_requirement / delete_preview / delete_requirement / claim_task / request_review / mark_blocked
    - 入口不直调（6 个，加 resolve + 重绑定 2 行）：add_subtask / update_subtask / add_milestone / update_milestone / add_record / update_progress
  - view.py 2 个函数（加 1 行重绑定）：summary（:61 附近）/ detail（:471 附近）
  - operations.py get_task_detail（:892）与 export_data（:943，requirement_id 可选）纯委托 view.detail，零改动（审 P2-7 补列名）
- **零改动面**：`transition` / `add_event` / `touch_activity` / `get_active_claim` 签名与逻辑不动——只接收重绑定后的全 id；`get_active_claim` 内部既有 require_requirement 调用保持（幂等，SQLAlchemy identity-map 命中，无额外 SQL）。api/requirements.py 路由与 cli.py 无本地 id 处理，随 choke point 生效。
- 该规则同时保证**返回面**：所有取 id 操作返回解析后的 32 位全 id（统一声明，审 P2-5），包括 claim_task/note/renew/add_record 等（现码 echo 原始参数，重绑定后 echo 全 id——对全 id 输入零变化）。

### 2.2 解析算法（钉死）

```
输入 raw（str）-> s = raw.strip().lower().replace("-", "")   # 统一归一（空白/大小写/连字符），适用于全部输入
   （审 P2-6 + P2-8 裁决：36 连字符全 id 现行为命中（实测），归一后走 32-hex 精确匹配＝行为不变；
    归一后长度以去连字符的 s 计）
1. len(s) == 32 且全 hex -> 精确匹配（session.get，精确路径本身不变）；未命中 -> not_found（消息用原始输入 raw，与现形态一致）
2. 8 <= len(s) <= 31 且全 hex -> 前缀扫描：SELECT id FROM requirements WHERE id LIKE '<s>%' ORDER BY id
   （前缀锚定、主键 covering index——审者已实测 EXPLAIN = USING COVERING INDEX；s 为纯 hex 不含 LIKE 通配符，无需 ESCAPE；
    禁 '%<suffix>'、禁全表取回后 Python 端过滤；候选读回为 36 连字符形态，norm_id 归一 32-hex 后再入错误消息/解析，审 P1-4）
   - 0 命中 -> not_found（消息用原始输入 raw）
   - 1 命中 -> session.get(Requirement, norm_id(唯一候选)) -> 返回该 Requirement
   - >=2 命中 -> BusinessError("ambiguous_id", 见下方模板, raw)
3. 其余（归一后 <8 位 / 非 hex / 空串 / 33+ 位）-> not_found（与现行为一致，不引入新错误码）
```

- **ambiguous_id 消息模板（钉死，审 P2-4）**：候选最多取 6 行（判定 >5），总数另走一次 COUNT；候选列表为 **norm_id 归一后的 32-hex**（审 P1-4）；
  `ambiguous requirement_id prefix '<s>': <候选 id 32-hex 升序，<=5 列全、>5 列前 5 + …>, 共 {total} 个候选; use a longer prefix`
  ——total 为实际总数（「共 N 个候选」语义＝总数，非剩余数）。
- 错误 task_id 位传**原始输入 raw**（与 not_found 现用法一致，便于调用方定位自己写错的形态）。
- 解析失败（not_found / ambiguous_id）发生在各操作第一步、任何写入之前——同事务无半态。

### 2.3 错误面

- 新错误码 `ambiguous_id`（唯一新增码）。语义：前缀命中 >=2 条需求。
- REST 映射 409（api/main.py，裁决值）；REST 存在触发端点（人面路由可传前缀），不属「agent 面专用码」类（见 §5.9）。

## 3. A2 设计：update_progress 返回租约态

### 3.1 返回形状（钉死）

```python
# operations.py update_progress 末尾（现 return {"requirement_id": requirement_id}）
return {"requirement_id": requirement_id, "lease_expires_at": claim.lease_expires_at.isoformat()}
```

- **前提（审 P1-2 裁决，钉死一处）**：update_progress 入口已按 §2.1 传播规则重绑定，返回点 `requirement_id` 即 32 位全 id——与 BCD Scenario 1「返回用解析后的全 id，不回填短前缀」一致。
- `claim` 为该函数已加载的活跃认领（`get_active_claim` 返回值，touch_activity 前取得）；`touch_activity` 只更 last_activity_at，`claim.lease_expires_at` 同事务内即当前值——**零额外查询**。
- iso 形态＝**aware UTC**（`…+00:00`，全仓 UTCDateTime 序列化口径，与 `renew` 返回的 `new_expiry.isoformat()` 逐字同源；v1「naive」措辞为勘误）。

### 3.2 语义边界（防误读，BCD §6 失败原因 2）

- 返回 `lease_expires_at` **不代表本操作延长了租约**；agent 依该值决定何时调 `renew`。
- 该措辞进 server.py docstring 与 PRD §4.1 行（§5）。

## 4. 行为兼容矩阵（回归锚）

| 输入 | 现行为 | 新行为 |
|---|---|---|
| 32 位小写全 id（存在） | 精确命中 | 相同（精确路径，逐字） |
| 32 位**大写**全 id（存在） | not_found | **命中（新）**——统一归一的 additive 放宽 |
| 36 连字符全 id（存在） | 命中（现行为，实测） | 相同（连字符归一 -> 32-hex 精确匹配） |
| 32 位全 id（不存在） | not_found | 相同 |
| 8~31 位 hex，唯一命中 | not_found | **命中（新）**——以 §2.1 传播规则为前提 |
| 8~31 位 hex，0 命中 | not_found | not_found（消息形态一致） |
| 8~31 位 hex，>=2 命中 | not_found | **ambiguous_id（新）** |
| <8 位 / 非 hex / 空 | not_found | not_found（相同） |
| 前导/尾随空白（全 id 或前缀） | 全 id 现 not_found / 前缀现 not_found | **命中（新）**——统一 strip |
| update_progress 返回 | `{"requirement_id"}` | **加 `lease_expires_at`（新）**，原字段＝32 位全 id |
| 其余取 id 操作返回 echo | 原始参数 | **解析后全 id**（全 id 输入零变化） |

## 5. 契约同步面（逐文件，v2 扩至 9 处）

1. **PRD §4.3**：错误码列表行（:199）加 `ambiguous_id`；「每个码有唯一触发条件」段加 `ambiguous_id = requirement_id 短前缀（8~31 hex）命中 >=2 条需求（0 命中 -> not_found）`；§4.3 末加 id 解析口径句：「requirement_id 输入统一归一（strip + 大小写不敏感 + 连字符去除）；8~31 位 hex 唯一前缀可解析（>=2 命中 -> ambiguous_id）；32 位全 id 精确匹配优先；<8 位或非 hex -> not_found；MCP/REST/CLI 三面同源；响应的 requirement_id 与 ambiguous_id 错误候选列表为 32-hex 形态，not_found 消息与错误 task_id 保留原始输入」。
2. **PRD §4.1**：update_progress 行语义加「返回 lease_expires_at（租约到期时间，仅通知不延长租约——延长用 renew）」。
3. **api/main.py**：REST_ERROR_STATUS 加 `"ambiguous_id": 409`。
4. **server.py docstring**：10 个带 requirement_id 工具（get_task_detail/claim_task/add_subtask/update_subtask/add_milestone/update_milestone/add_record/update_progress/request_review/mark_blocked）：参数行 requirement_id 注明「32 位全 id 或 8~31 位唯一前缀（空白/大小写/连字符不敏感）」；错误行 not_found 处加 `ambiguous_id（前缀命中多条，错误信息含候选，加长前缀重试）`。update_progress docstring 加返回行：「返回: requirement_id（32 位全 id）+ lease_expires_at（租约到期时间；本操作不延长租约，续租用 renew）」。
5. **SKILL.md:22 租约措辞修正（v2 新增，审 P1-3；存量正典冲突登记）**：现状「任何 MCP 写操作都是活动，**租约自动续**」与 ADR 0006 / PRD §3.2（写操作只更 last_activity_at，租约固定、显式 renew 才延长）直接矛盾，此前未登记 known-gaps，本批修正是其闭合。建议措辞（**交 user 在 spec 审阅时裁决**）：
   > 租约：lease 2h / idle 30min（可配置）。任何 MCP 写操作都是活动（更 last_activity_at，防 SUSPECT）；租约**不自动续**——延长需显式 renew（可据 update_progress 返回的 lease_expires_at 决策）。长时间无活动 -> SUSPECT，过期 -> STALE（人可见告警）。
6. **SKILL.md 错误码速查表（:54-64）**：加行 `ambiguous_id | 前缀命中多条需求 | 加长前缀重试`。
7. **docs/design.md:135**：错误码九码列表 -> 十码（加 ambiguous_id）。
8. **errors.py:1 docstring**：「PRD 4.3 九码」->「十码」。
9. **api/requirements.py:3-6 docstring**：错误映射注释加 `ambiguous_id=409`，并将其从「agent 面专用码（REST 无触发端点）」归类移出（REST 路由可传前缀，存在触发端点）。

## 6. 测试策略（AC 用例，先红后绿）

**A1**：
1. 唯一前缀（8 位）经 choke point 解析到目标需求，写操作成功且**事件 requirement_id 落 32 位全 id**（传播规则判别）。
2. 歧义：两需求同 8 位前缀 -> `ambiguous_id`，错误信息含两候选 id，且**零写入**（事件数/claim/状态全不变）。
3. 候选 >5：错误信息逐字匹配钉死模板（含「共 6 个候选」、候选列表截断 5 个 + …）。
4. 0 命中前缀 -> `not_found`（消息含原始输入，形态同现行为）。
5. <8 位（4/7 位）/ 非 hex / 空串 -> `not_found`。
6. 全 id 回归：小写存在 -> 命中；不存在 -> not_found（精确路径）。
7. 归一面：大写 32 位全 id -> 命中（新行为断言）；大写前缀 -> 命中；带首尾空白 -> 命中；36 连字符全 id -> 命中且返回 echo 为 32-hex（命中结果保持；echo 归一 32-hex，审 P2-8）。
8. 跨面一致性：同一唯一前缀经 MCP 面与 REST 面调用同结果（同目标/同错误码）。
9. 返回 echo（非 A2 工具，审 P2-5）：claim_task 前缀输入 -> 返回 requirement_id 为 32 位 hex。

**A2**：
10. update_progress 返回含 `lease_expires_at`（aware UTC iso 形态）；前缀输入时 `requirement_id` 字段＝32 位全 id（审 P1-2 断言）。
11. 口径（顺序钉死，审 P2-3）：renew -> update_progress -> 断言两返回的 lease_expires_at 相等。

**回归保护**：全量 592/592 基线不回退（not_found 既有断言逐条仍绿）。

## 7. 不变量映射（BCD §7 -> 验收锚）

| 不变量 | 验收锚 |
|---|---|
| 强 1 宁拒不猜 | 用例 2/3 |
| 强 2 小写全 id 逐字不变 + 归一 additive | 用例 6/7 + 全量基线 |
| 强 3 单向门纯 additive | diff 审查（无既有码/字段/参数删除或改形）+ 兼容矩阵 §4 |
| 强 4 租约语义零改动 | 用例 10/11 + diff（touch_activity 零改动） |
| 强 5 解析单点 + 传播规则 | 用例 1/8/9 + diff 核对：前缀逻辑仅 write_guard.py **且 21 调用点入口重绑定、下游用全 id**（审 P1-1 自毁锚修正） |
| 软 1/2/3 | diff 审查（展示面/配置面/schema 零改动） |

## 8. 残余与已知局限

- 前缀唯一性随板面增长只收紧不放松（BCD §4 跨时段场景）：曾用短前缀的自动化在撞前缀后转 ambiguous_id——既定行为＝加长前缀重试（docstring 明示），不视为回归。
- 错误消息候选截断（前 5 + 总数）：极端撞前缀下调用方需自行加长定位——可接受（单用户板面规模）。
- agent 对「返回=通知」的认知约束上限＝语义显性化（威胁模型 B 边界，与 distill-pipeline 批同一残余类别）。
- SKILL.md:22 措辞为 user 裁决项（§5.5 建议文）；若裁决维持原文，则 docstring/PRD 的「不延长租约」表述须同步回退为不提及延长机制（两面不得矛盾）——代码事实（ADR 0006）不变。

## 修订记录

- v1（2026-10-27）创建；spec 自查折入 3 处收紧（ESC/候选计数/SKILL.md 核对分支）。
- v2（2026-10-27）：对抗审查 REJECT（3 P1 + 6 P2 + 3 疑点 + 勘误）全修正：
  - P1-1：§2.1 重写为「解析单点 + 传播规则」，21 调用点清单，§7 强 5 锚去自毁，§4 矩阵加前提注。
  - P1-2：§3.1 钉死「重绑定参数」前提（钉死一处），用例 10 补前缀输入返回全 id 断言。
  - P1-3：§5.5 SKILL.md:22 租约措辞修正项（建议文交 user 裁决）+ 存量正典冲突登记；§8 加裁决联动残余。
  - P2-1：§5 扩至 9 处（design.md/errors.py/api docstring/SKILL.md 错误表）。
  - P2-3：用例 11 钉 renew -> update_progress 顺序。
  - P2-4：ambiguous_id 消息模板钉死（「共 N 个候选」N=总数），用例 3 断言逐字模板。
  - P2-5：§2.1 统一声明「所有取 id 操作返回解析后全 id」，用例 9 补 claim_task 断言。
  - P2-6：归一裁决＝strip + 大小写不敏感适用于全部输入；§4 加大写全 id/空白行；强 2 措辞调整；用例 7 补全 id 形态。
  - 勘误：「naive UTC」-> aware UTC（`…+00:00`）。
  - BCD 同步修订：例 2 改 8 位前缀；Commands 措辞（10 个带 id 工具）；强 2/强 5 措辞对齐；§2 What 加 21 调用点；§1 补痛点实例；行号勘误（operations.py:737->:736）。
  - 疑点 1（痛点重建）：BCD §1 补真实实例（人面 approve 命令须抄全 32 位 id，每批收尾必做）；疑点 2/3 接受不定级 / 措辞已修。
- v3（2026-10-27）：第 2 轮续审 APPROVE-WITH-FIXES（残留 P1 0 + 新增 1 P1 / 2 P2 + 勘误 2）全折入：
  - P1-4：重绑定表达式钉 `norm_id(req.id)`（`Requirement.id` ORM 读回为 36 连字符，实测 + ids.py docstring 为证；一切重绑定/echo/错误候选须 32-hex 形态）；§2.2 单命中路径与候选列表钉 norm_id 归一；write_guard 加 import；用例 9/10 断言保持（折入后即红绿判别）。
  - P2-7：§2.1 零改动面补列 export_data（:943，requirement_id 可选，纯委托）。
  - P2-8：连字符归一裁决＝接纳（`s.replace("-","")`）；36 连字符全 id 现行为命中（实测），归一后走精确匹配＝行为不变；§4 矩阵加行；用例 7 补形态；§5.1 PRD 句补「连字符去除 + 响应 id 均 32-hex」。
  - 勘误：§5.4「8+ 位」->「8~31 位」；步骤 1 not_found 消息统一钉 raw。
  - BCD 同步：What/强 5 钉 norm_id 归一形态；强 2/Policy 3 归一措辞加连字符；修订记录一行。
- v3.1（2026-10-27）：第 3 轮续审 3 项折入（审者声明折入即共识、不复审）：N1 §5.1 PRD 句自洽（响应 id/候选列表 32-hex；not_found 消息与 task_id 保留原始输入）+ BCD 强 2 同句；N2 用例 7 括注改「命中结果保持；echo 归一 32-hex」；N3 BCD Who 归一列举补连字符。
