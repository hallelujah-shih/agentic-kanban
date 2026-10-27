# Spec: 批 2 A1 短 id 前缀匹配 + A2 update_progress 返回租约态

**日期**: 2026-10-27
**状态**: 待对抗审查（BCD 已齐，设计草稿 user 全批 2026-10-27）
**分支/worktree**: a1a2-mcp（基于 main 8a60111，.worktree/a1a2-mcp）
**BCD**: `docs/business-contracts/a1a2-mcp-surface.md`（7 节齐；user 裁决 2026-10-27 设计草稿全批，四决策点按建议值：8 hex 最小前缀 / 仅 requirement_id / ambiguous_id REST=409 / A2 仅 lease_expires_at）
**板上任务**: 396f583730514ab5a3963dd58563bdcd
**关联**: PRD §4.1（MCP 工具面）§4.3（错误码）；ADR 0006（activity 口径）；`write_guard.py`（require_requirement choke point）；`operations.py`（update_progress/renew）；`api/main.py`（REST_ERROR_STATUS）；`server.py`（MCP docstring）

---

## 1. 范围与非目标

**范围内**：
- A1：requirement_id 唯一前缀解析（choke point 单点实现）+ 新错误码 `ambiguous_id`
- A2：`update_progress` 返回加 `lease_expires_at`
- 契约同步：PRD §4.3、api/main.py REST 映射、server.py docstring（见 §5）
- 测试（AC 用例，见 §6）

**非目标（显式）**：
- 不动展示面（板面/web/export 仍显 32 位全 id；输入侧放宽、展示侧不短化）
- 不动 subtask_id / milestone_id / claim_id 解析（维持精确匹配）
- 不动租约语义：activity 只更 last_activity_at（ADR 0006），A2 返回是通知、不延长 lease_expires_at
- 不动 32 位全 id 精确匹配路径与 not_found 语义（逐字不变）
- 禁止各面（MCP/REST/CLI）在 choke point 之外自行实现前缀逻辑（BCD Policy 4 单点）
- 不做前缀长度可配置化（8 为代码常量）
- 零 schema 变更（不加表/列/索引）

## 2. A1 设计：id 前缀解析

### 2.1 实现位置

`src/agent_kanban/services/write_guard.py::require_requirement`（唯一实现点）。MCP 10 个带 requirement_id 工具、REST 路由、CLI 均经此函数（operations.py 全部写操作 + view.py:61/:471 读操作 + api/requirements.py 路由），单点生效、三面同源。

### 2.2 解析算法（钉死）

```
输入 raw（str）-> s = raw.strip().lower()
1. len(s) == 32 且全 hex -> 精确匹配（session.get，现行为逐字保留）；未命中 -> not_found（现消息形态）
2. 8 <= len(s) <= 31 且全 hex -> 前缀扫描：SELECT id FROM requirements WHERE id LIKE '<s>%' ORDER BY id（前缀锚定，主键索引可用；s 为纯 hex 不含 LIKE 通配符，无需 ESCAPE；禁 '%<suffix>'、禁全表取回后 Python 端过滤）
   - 0 命中 -> not_found（消息形态与现行为一致，含输入值）
   - 1 命中 -> 用该 id 继续（后续逻辑与全 id 传入完全一致）
   - >=2 命中 -> BusinessError("ambiguous_id", "ambiguous requirement_id prefix '<s>': <候选 id 列表，升序>; use a longer prefix", raw)
3. 其余（<8 位 / 非 hex / 空串 / 33+ 位）-> not_found（与现行为一致，不引入新错误码）
```

- 大小写/空白：输入侧 strip + lowercase（id 生成态为小写 hex；全 id 输入行为不受影响——合法全 id 本就小写）。
- 错误信息用**原始输入 raw**（非 s），便于调用方定位自己写错的形态。
- 前缀扫描候选上限：候选只取 id 列、按 id 升序、最多取 6 条（>=2 即短路，取 6 只为判定「>5」）；错误信息候选列表 <=5 时列全，>5 时列前 5 + 「等 N 个」（N=实际总数——总数需一次 COUNT，避免病态前缀撑爆错误消息）。

### 2.3 错误面

- 新错误码 `ambiguous_id`（唯一新增码）。语义：前缀命中 >=2 条需求。
- BusinessError 第三参数（task_id 位）传 raw 输入（与 not_found 现用法一致）。
- 解析失败（not_found / ambiguous_id）发生在任何写入之前——同事务无半态（require_requirement 是各操作第一步，raise 即回滚/未开始）。

## 3. A2 设计：update_progress 返回租约态

### 3.1 返回形状（钉死）

```python
# operations.py update_progress 末尾（现 return {"requirement_id": requirement_id}）
return {"requirement_id": requirement_id, "lease_expires_at": claim.lease_expires_at.isoformat()}
```

- `claim` 为该函数已加载的活跃认领（`get_active_claim` 返回值，现于 touch_activity 前取得）；`touch_activity` 只更 last_activity_at，`claim.lease_expires_at` 同事务内即当前值——**零额外查询**。
- iso 字符串口径与 `renew` 返回（operations.py:293 附近 `new_expiry.isoformat()`）逐字一致（naive UTC iso，与全仓时间序列化口径同源）。
- 原字段 `requirement_id` 保留（返回解析后的 32 位全 id）。

### 3.2 语义边界（防误读，BCD §6 失败原因 2）

- 返回 `lease_expires_at` **不代表本操作延长了租约**；agent 依该值决定何时调 `renew`。
- 该措辞进 server.py docstring 与 PRD §4.1 行（§5）。

## 4. 行为兼容矩阵（回归锚）

| 输入 | 现行为 | 新行为 |
|---|---|---|
| 32 位全 id（存在） | 精确命中 | 相同（精确路径，不进前缀扫描） |
| 32 位全 id（不存在） | not_found | 相同 |
| 8~31 位 hex，唯一命中 | not_found | **命中（新）** |
| 8~31 位 hex，0 命中 | not_found | not_found（消息形态一致） |
| 8~31 位 hex，>=2 命中 | not_found | **ambiguous_id（新）** |
| <8 位 / 非 hex / 空 | not_found | not_found（相同） |
| update_progress 返回 | `{"requirement_id"}` | **加 `lease_expires_at`（新）**，原字段不变 |

## 5. 契约同步面（逐文件）

1. **PRD §4.3**：错误码列表行（:199）加 `ambiguous_id`；「每个码有唯一触发条件」段加 `ambiguous_id = requirement_id 短前缀（8~31 hex）命中 >=2 条需求（0 命中 -> not_found）`；§4.3 末加一句 id 解析口径：「requirement_id 接受 8~31 位 hex 唯一前缀（输入 strip + 大小写不敏感；32 位全 id 精确匹配优先；<8 位或非 hex -> not_found）；MCP/REST/CLI 三面同源」。
2. **PRD §4.1**：update_progress 行语义加「返回 lease_expires_at（租约到期时间，仅通知不延长租约——延长用 renew）」。
3. **api/main.py**：REST_ERROR_STATUS 加 `"ambiguous_id": 409`（裁决值）。
4. **server.py docstring**：
   - 10 个带 requirement_id 工具（get_task_detail/claim_task/add_subtask/update_subtask/add_milestone/update_milestone/add_record/update_progress/request_review/mark_blocked）：参数行 requirement_id 注明「32 位全 id 或 8+ 位唯一前缀」；错误行 not_found 处加 `ambiguous_id（前缀命中多条，错误信息含候选，加长前缀重试）`。
   - update_progress docstring 加返回行：「返回: requirement_id + lease_expires_at（租约到期时间；本操作不延长租约，续租用 renew）」。
5. **skills/agent-kanban/SKILL.md**：实施前逐字核对 id 抄写/租约相关措辞——无与新语义冲突（「写 progress 不延租」「短前缀可重试」不与其矛盾）-> 零改动；有冲突 -> 上抛主循环裁决，实施者不自决。

## 6. 测试策略（AC 用例，先红后绿）

新增用例（挂 tests/ 现有 AC 框架，命名随现有惯例）：

**A1**：
1. 唯一前缀（8 位）经 choke point 解析到目标需求，操作成功（写操作断言事件落进正确需求）。
2. 歧义：两需求同 8 位前缀 -> `ambiguous_id`，错误信息含两候选 id，且**零写入**（事件数/claim/状态全不变）。
3. 歧义短路：错误信息含「等 N 个」计数形态（>=6 候选时不列全量）。
4. 0 命中前缀 -> `not_found`（消息含输入值，形态同现行为）。
5. <8 位（4/7 位）/ 非 hex / 空串 -> `not_found`。
6. 全 id 回归：存在 -> 命中；不存在 -> not_found（精确路径）。
7. 大小写/空白：大写前缀与带首尾空白的前缀均解析成功。
8. 跨面一致性：同一唯一前缀经 MCP 面与 REST 面调用同结果（同目标/同错误码）。

**A2**：
9. update_progress 返回含 `lease_expires_at`，值与当前 claim 的到期时间一致（iso 形态）；原 `requirement_id` 字段仍在。
10. 同场景 renew 返回的 lease_expires_at 与 update_progress 返回一致（口径同源判别）。

**回归保护**：全量 592/592 基线不回退（not_found 既有断言逐条仍绿）。

## 7. 不变量映射（BCD §7 -> 验收锚）

| 不变量 | 验收锚 |
|---|---|
| 强 1 宁拒不猜 | 用例 2/3 |
| 强 2 全 id 行为不变 | 用例 6 + 全量基线 |
| 强 3 单向门纯 additive | diff 审查（无既有码/字段/参数删除或改形）+ 兼容矩阵 §4 |
| 强 4 租约语义零改动 | 用例 9/10（返回不改变 claim 行的 lease_expires_at）+ diff（touch_activity 零改动） |
| 强 5 三面同源单点 | 用例 8 + diff（前缀逻辑仅存在于 write_guard.py） |
| 软 1/2/3 | diff 审查（展示面/配置面/schema 零改动） |

## 8. 残余与已知局限

- 前缀唯一性随板面增长只收紧不放松（BCD §4 跨时段场景）：曾用短前缀的自动化在撞前缀后转 ambiguous_id——既定行为＝加长前缀重试（docstring 明示），不视为回归。
- 错误消息候选列表截断（前 5 + 计数）：极端撞前缀下调用方需自行加长定位——可接受（单用户板面规模）。
- agent 对「返回=通知」的认知约束上限＝语义显性化（威胁模型 B 边界，与 distill-pipeline 批同一残余类别）。
