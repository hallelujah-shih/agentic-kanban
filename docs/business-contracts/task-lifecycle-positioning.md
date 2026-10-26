# Business Contract: Task 生命周期与看板定位重述

**作者**: 主循环（task-lifecycle）
**日期**: 2026-10-26
**关联**: PRD §0（定位）/§3.1（状态机）/§3.4（完成语义）/§4.2（人面 surface）/§5.4（回溯判据）/§6（数据保留）；docs/web.md
**user 裁决**: 2026-10-26 三项——Q1 取 A（UI 瘦身为"读 + task 生命周期"，决策操作 Web 移除、REST/CLI 保留）；Q2 取方案 1（archive = 新终态 ARCHIVED，delete = 整需求硬删，REST + CLI + Web 三层齐）；Q3（对抗审查 P1-3 提出，user 委托主循环代裁，可于 spec 审阅时推翻）archive 事件 from=None 沿用 REJECTED 先例（"? -> ARCHIVED"，实际 from 由 state_change 链重建）

---

## 1. 客户原话语义分析

### 客户原话（未解读，逐字）

> 我们要定位清楚，agent kanban主要是AI和人对称关键信息的地方，但是不承担审核等逻辑，但是可以在关键位置上记录人在AI、AI自动的决策。子任务、里程碑信息都应该是人在AI中达成共识，并在dashboard上展现，而不是人和AI在dashbard上交互达成的共识，此处只是关键信息的记录点和关键审计点。然后理论上来说，task必须要人能够创建、删除、archive的。sub task当前可以不开放编辑

后续裁决原话（2026-10-26，对两个澄清问题的回答）："按照你的建议来"（Q1: UI 瘦身 + 决策操作 CLI-only）、"按照你的建议来处理"（Q2: 方案 1 + 三层齐）。

### 可能的解读（互斥，业务目标分歧）

| 解读 | 客户真实期望 | 证据 | 证据强度 |
|---|---|---|---|
| A. 看板 = 记录面/审计点；UI 上的人面权利 = task 生命周期（create/archive/delete）；决策操作（approve/release/...）降 CLI-only | dashboard 不再是人机交互达成共识的场所；决策在会话/终端达成，看板只记录与展现；C6 保持（人面 = CLI） | "此处只是关键信息的记录点和关键审计点"、"而不是人和AI在dashboard上交互达成的共识"；user 对 Q1 明确取 A | user 裁决 + 客户原话 |
| B. 看板保留"协作窗口"属性：UI 决策按钮保留（重新解释为"记录人的决策"），另加 create/archive/delete | dashboard 瘦身但不搬走决策动作；人仍在按钮上确认 DONE | "主要是...但是不承担审核等逻辑"——"主要是"留了空间；"记录...决策"可读作在看板上记录 | 客户原话（弱） |
| C. 看板 = 纯只读窗口：人连 task 生命周期操作都不在 UI 上做，全部（含 create）留 CLI | dashboard 是纯观察窗口，人的一切动作在终端 | "此处只是关键信息的记录点和关键审计点"（字面极值解读） | 客户原话（与下一条原话冲突） |

**互斥对**：A vs B（决策按钮去留——直接影响 C6 审计链落在哪个 surface、harness 壳契约、人面工作流）；A vs C（task 生命周期操作是否在 UI——直接影响"task 必须要人能够创建、删除、archive"在哪个 surface 兑现）。B vs C 在 UI 操作面上互斥（有操作 vs 纯只读）。

### 我的解读

**A**（user 已裁决）。要点：
- "不承担审核逻辑" = 看板不承载"人机交互达成共识"的过程；不是取消人确认——C6（DONE 只能由人确认）保持，人面从"dashboard + CLI"收窄为"CLI-only"
- "记录人在AI、AI自动的决策" = 两类决策来源的持久化记录：人在会话中（in-band）做出的决策由 agent 以既有 decision/note 事件记录（带 actor provenance），AI 自主决策同走 decision 事件。机制已存在，定位变更是把它从"可选行为"确立为"预期模式"
- "task 必须要人能够创建、删除、archive" = 三个 task 级生命周期操作，人在 UI 上可执行（REST + CLI + Web 三层齐，CLI 全量面 / Web 子集的既有惯例保持）
- "sub task 当前可以不开放编辑" = 确认现状（子任务只有 agent 面写入），本轮不做

### 待澄清项

1. **in-band 决策是否需要专用记录通道**（如 agent 侧新工具 record_human_decision）：判定为**不需要**——既有 decision/note 事件 + actor provenance 足以表达"agent 记录：人在会话中做了决策 X"；正式确认动作（approve）仍必须来自人面（C6）。若 user 认为 in-band 决策需要更强的结构性区分，后续可加 payload 标记，零迁移
2. **unarchive 需求**：user 未提及，按 YAGNI 判为非目标（ARCHIVED 数据全留存且可见；日后加一条人面边即可，零迁移）。若实际使用中出现"归档了想恢复"的强需求，触发 BCD 修订
3. **"archive ≠ 取消"的语义区分能否在使用中保持**：人可能用 archive 替代 abandon(CANCELLED) 来"让任务消失"（Premortem F1）。当前设计靠 UI 语义提示 + PRD 措辞，不做结构强制。user 确认接受此风险

---

## 2. Impact Mapping

- **Why**：让 task 集的生命周期归属人（创建/删除/archive），并让看板作为"决策记录点/审计点"的定位字面成立。目标是**记录面与审计面 + 生命周期管理权**，不是给 dashboard 增加交互能力
- **Who**：
  1. 人（owner，单用户 localhost）：task 集管理权 + 回溯审计 + in-band 决策的持久化落点
  2. agent（opencode 会话，MCP 面）：在 task 上工作；task 被删除/归档时需要明确地（既有错误码）发现
  3. 未来维护者/审计者：事件链是唯一审计资产，语义必须可区分（archive vs abandon）
- **How**：UI 瘦身为"读 + task 生命周期"；状态机加 ARCHIVED 终态；新增整需求硬删；决策操作降 CLI-only（语义零改动）
- **What**：
  - 代码：state_machine.py（边）、operations.py（archive/delete）、view.py（TERMINAL_STATES/过滤/tab 数据）、api/requirements.py（REST 端点）、api/web.py（壳瘦身 + 生命周期操作 + 新建表单）、cli.py（archive/delete 命令）
  - 文档：PRD §0/§3.1/§3.4/§4.2/§6、docs/web.md
  - 契约：harness 壳契约断言更新 + 新增用例

---

## 3. Domain Event 流

### Domain Events（时间顺序）

1. 需求行创建（`new_requirement` 写行，**不写事件**——既有口径，created_at/source/source_ref 在行上，导出可见）
2. claim_task -> state_change(OPEN -> CLAIMED) + claims 行（既有）
3. agent 工作期事件（decision/risk/deviation/decomposition/progress_note/review_request/...，既有）
4. **archive -> state_change(任意 -> ARCHIVED)**（新增；actor = 人面；同事务：claim ended_at + release_reason="archive"，awaiting_human 清除）
5. 终态窗口内 prune 整删（既有，终态集合扩展含 ARCHIVED）或 **delete 即时整删（新增，不写事件——事件链随属主一起消失）**

### Commands（谁触发，做什么）

| Command | 触发者 | 面 | 动作 |
|---|---|---|---|
| create | 人 | Web 表单 / CLI new / REST POST /requirements | 创建 OPEN 需求（可选 acceptance/jira 引用） |
| archive | 人 | Web 按钮 / CLI archive / REST POST /requirements/{id}/archive | 任意状态 -> ARCHIVED 终态 |
| delete | 人 | Web 按钮（标题确认）/ CLI delete（确认提示）/ REST DELETE /requirements/{id} | 整需求原子硬删 |

### Aggregates

Requirement（根）：Subtask[]、Milestone[]、Claim[]、Event[]——delete 的原子边界就是这个聚合的全部行。

### Policies（含隐含）

- P1 archive 从任意状态（含终态）可达；**无 unarchive**（ARCHIVED 是冷存储，不可回到活跃流）
- P2 archive 同事务结束未结束认领（release_reason="archive"）+ 清除 awaiting_human（transition 通规：to != BLOCKED）
- P3 delete 单事务原子、按 FK 顺序（events -> claims/subtasks/milestones -> requirement）、不写事件
- P4 **隐含**：delete 不受数据保留窗口约束——prune 是窗口化批量策略（仅终态），delete 是显式即时操作（任意状态），显式意图覆盖保留策略
- P5 ARCHIVED 并入 prune 终态集合（12 个月窗口整删照旧适用）
- P6 agent 对 ARCHIVED 任务：不能认领（state != OPEN）、不能写（无活跃认领 -> no_active_claim）、可读历史（get_task_detail）
- P7 delete/archive 仅人面（REST/CLI/Web）；MCP（agent）面无这两个工具
- **隐含 Policy A**：awaiting_human banner 不是交互点——UI 瘦身后 banner 提供静态 CLI 提示（kind=review/blocked -> `kanban approve <id>`），保持"看板不承载交互"但不留死路
- **隐含 Policy B**：delete 的确认门槛高于 archive——UI 要求输入 task 标题，CLI 要求确认提示（展示 title/状态/事件数 + 导出建议）；archive 无额外确认
- **隐含 Policy C**：创建不写事件、无"创建者归属"事件（非目标）；回溯判据 5 条（PRD §5.4）均不要求"谁创建"

---

## 4. BDD Given-When-Then 场景

**S1（happy，create）**
Given 看板页顶栏有"新建"入口
When 人提交 title + 两行 acceptance（无 jira 链接）
Then 看板"待认领"列出现新任务（state=OPEN），深潜页验收对照表显示两条锚（自动编号 a1/a2），SSE 推送使看板自动刷新

**S2（happy，archive 活跃任务）**
Given 一个 CLAIMED 任务（有活跃认领，无 awaiting_human）
When 人执行 archive（Web 按钮或 CLI）
Then 任务出现在"已归档"tab（finished_at = archive 事件 ts），在板四列与 list_tasks 默认列表均不再出现；claim 行 ended_at 置位且 release_reason="archive"；事件链尾为 state_change(from=None, to=ARCHIVED, claim_id 归属, actor=人面——事件形态与 REJECTED 先例一致，"? -> ARCHIVED"，归档时点的实际 from 由 state_change 链重建，Q3 裁决）；agent 下一次写操作拿 no_active_claim（MCP is_error）

**修订记录**: 2026-10-26 主循环——对抗审查 P1-3（BCD S2/E2 声称"实际 from 记录"与 spec §3 from=None 设计冲突）裁决案 A：沿用 REJECTED 先例，S2/E2 相应修订。理由：transition 零改动声明保持 + 审计无损（状态链可重建实际 from）。

**S3（happy，archive 终态任务）**
Given "已完成"tab 中的一个 DONE 任务
When 人执行 archive
Then 任务移入"已归档"tab，"已完成"tab 不再显示；深潜页全轨迹可回溯（事件链完整）

**S4（happy，delete）**
Given 一个有 10+ 事件、2 子任务、1 里程碑、1 已结束 claim 的任务
When 人在 Web 深潜页执行 delete 并输入正确标题确认
Then requirement + 全部子行（events/subtasks/milestones/claims）原子删除；后续 REST GET /requirements/{id} -> 404 {code:not_found}；MCP get_task_detail -> is_error not_found；list_tasks 不再返回该任务

**S5（edge，带 marker 的 archive）**
Given 一个 BLOCKED 任务，awaiting_human(kind=blocked)
When 人执行 archive
Then awaiting_human 被清除（任务不再出现在"等你决策"清单/list_awaiting），claim 同事务结束，state=ARCHIVED

**S6（edge，并发 delete）**
Given agent 正在活跃写入一个任务（SQLite 并发写事务）
When 人同时执行 delete
Then 写事务串行化：要么 agent 写入先提交随后被 delete 整删，要么 agent 拿 no_active_claim/not_found（瞬时锁竞争走既有 db_busy 重试）——任何时刻不存在 FK 悬空或半删状态

**S7（跨时段，prune 覆盖）**
Given 一个 ARCHIVED 任务，其全部事件早于 12 个月窗口
When `kanban prune --months 12` 执行
Then 该任务被终态需求级窗口整删（deleted 计数包含其事件数）；反之，ARCHIVED 但有事件未出窗的任务保留；非终态任务（含僵尸 STALE）全保留

**S8（跨边界，agent 面感知 delete）**
Given 一个任务已被人删除
When 持有该 task id 的 agent 会话调用任意 MCP 工具
Then get_task_detail/list_tasks 无该任务或 is_error not_found；写操作（update_subtask 等）is_error not_found——agent 可明确判定"任务不存在/已被删除"，而非系统故障

---

## 5. Spec by Example

**E1（Web create，带 acceptance）**
输入：Web 新建表单：title="日志管道迁移到新集群"，description 空，acceptance 两行"吞吐 >= 5000 events/s""p99 延迟 < 200ms"，jira 链接空
操作：POST /requirements {"title": ..., "acceptance": [{"item": "吞吐 >= 5000 events/s"}, {"item": "p99 延迟 < 200ms"}]}
预期：201 {"requirement_id": ..., "state": "OPEN"}；board OPEN 列 +1；深潜页验收对照表 a1/a2（新任务无子任务，显示"覆盖缺口"为正常态）

**E2（CLI archive，CLAIMED 任务）**
输入：`kanban archive <id>`，任务 state=CLAIMED，agent 活跃工作中
操作：人面 REST 调用 -> ops.archive_requirement
预期：{"requirement_id": ..., "state": "ARCHIVED"}；DB：requirements.state=ARCHIVED、claims.ended_at 非空且 release_reason="archive"、awaiting_human=NULL；events 尾行 state_change "? -> ARCHIVED"（from=None, to=ARCHIVED, claim_id 归属——REJECTED 先例形态，Q3 裁决）actor_surface=cli；agent 下一次 update_progress -> MCP is_error no_active_claim

**E3（Web delete，确认流程）**
输入：Web 深潜页点 delete -> 确认框（显示 title + 事件数 + 当前状态 + "删除不可逆，建议先导出"）
操作：输入错误标题 -> 拒绝（提示不匹配，任务不变）；输入正确标题 -> DELETE /requirements/{id}
预期：首次拒绝零副作用；确认后 200 {"requirement_id": ..., "deleted": true}；GET /requirements/{id} -> 404；GET /requirements/{id}（Accept: text/html）-> 壳显示未找到

**E4（prune 覆盖 ARCHIVED）**
输入：任务 A（ARCHIVED，全部事件早于 12 个月）+ 任务 B（ARCHIVED，有 1 条近期事件）+ 任务 C（CLAIMED 僵尸 STALE）
操作：`kanban prune --months 12 --yes`
预期：A 整删（deleted 计数含其事件数）、B 保留、C 保留（非终态全留）；导出文件（清理前强制）包含三者

**E5（C6 路径不变）**
输入：CLAIMED 任务 + awaiting_human(kind=review)
操作：人执行 `kanban approve <id>`（CLI）
预期：DONE + approval + state_change 事件（actor_surface=cli）；Web 深潜页上无 approve 按钮（已移除）——同一确认动作在 Web 上无入口

### "客户期望 vs 系统行为"差异表

| 客户期望 | 当前系统行为 | 差距性质 |
|---|---|---|
| 任务创建可在 Web 上做 | 仅 CLI/REST，Web 无入口 | 能力差距（本次补齐） |
| 人可删除任务 | 系统无任何 delete 操作（只有 prune 窗口化批量） | 能力差距（本次补齐） |
| archive 与取消语义区分 | 只有 REJECTED/CANCELLED；"让任务消失"只能靠 cancel（语义污染）或留在"已完成"tab | 业务语义差距（本次补齐：新终态） |
| **看板是记录点/审计点，决策在终端/会话中做出并落记录** | **看板是人面决策面：7 个决策按钮，人在看板上点按钮确认 DONE，C6 审计链终结于 UI 点击** | **根本性业务冲突**：两语义在"终态确认的审计权重来自哪个 surface"上冲突。裁决：C6 要求人面，人面收窄为 CLI-only（终端命令是更 deliberate 的人的动作，审计权重不降反升）；看板降为展示面。见 user 裁决 Q1=A |
| 删除是人的权利 | 看板 = 可回溯审计资产（PRD 定位） | 根本性张力：delete 主动销毁审计链。裁决：delete = 人显式意图，非默认路径（保留策略默认仍是 prune 窗口化 + 强制导出），确认时提示"建议先导出"，不强制 |

---

## 6. Premortem（假设 6 个月后失败）

**F1（业务规则）"archive ≠ 取消"的区分在使用中失效**
失败序列：任务做不下去 -> 人觉得"取消"太重，用 archive 让任务消失 -> 归档量远超预期，"已完成"tab 反而干净 -> 6 个月回溯时发现 REJECTED/CANCELLED 极少、ARCHIVED 泛滥，abandon 事件链（带工作判断语义：为什么拒绝/取消）丢失，审计上无法区分"工作被放弃"与"只是移出视野" -> "关键审计点"定位被掏空。
预防：PRD §0/§4.2 写明语义边界（archive = 移出活跃视野，无工作判断；abandon = 工作判断）；UI archive 确认/操作位显示语义；人工定期观察 archive 与 abandon 的比例（运营观测，不做自动化告警——单用户规模下自动化是过度设计）

**F2（跨边界）agent 侧 harness 不处理 delete 后的 not_found**
失败序列：agent 工作循环中 -> 人删除任务 -> agent 下一次写操作拿 not_found -> harness 当作系统故障重试/上报"系统异常"（实为人意图）-> 信息错乱，人误以为看板坏了；或 agent 会话卡死在重试。
预防：错误码语义清晰（not_found 的 message 含 requirement id，既有）；本仓 README/docs 写明"requirement not_found = 任务被删除或从未存在，属人面操作结果"；harness 断言 delete 后 agent 面拿 not_found。残余：agent 的 harness（strict-sdd-loop 等）在本仓之外（opencode 会话层），本仓只能靠错误码语义 + 文档，不能结构强制

**F3（工作流）UI 瘦身后人失去看板确认习惯，awaiting 堆积**
失败序列：agent 完成 request_review -> 板上看板横幅"等待人" -> 人习惯点按钮，发现没有按钮 -> 不知道要去终端 approve -> 任务滞留 CLAIMED，租约 STALE -> "等你决策"堆积，看板退化为纯展示板，"AI 和人对称关键信息"的沟通渠道功能退化 -> 定位失败（看板变黑箱展示板）。
预防：awaiting 横幅加静态 CLI 提示（kind=review/blocked -> "人面确认: kanban approve <id>"）；板面"等待人"区同样展示命令；README/web.md 加"人面命令速查"（决策操作全表 + 命令）。残余：习惯迁移仍可能慢，横幅提示是最小干预

**F4（数据/误操作）delete 误删应归档的需求，不可恢复**
失败序列：人想 archive 但点错 delete -> 输入标题确认（可能没细看提示就输入）-> 带完整历史的任务永久消失 -> 回溯不可能，审计资产永久丢失，且**无 unarchive 可兜底**（归档是恢复的最近邻，但 delete 没有）。
预防：确认框展示"事件数 + 当前状态 + 最近活动时间 + 删除不可逆，建议先 kanban export"并要求输入标题；delete 按钮与 archive 按钮视觉分离（不并排同组）；CLI delete 确认提示含导出建议。残余接受：单用户 localhost，误操作概率低、成本高但可容忍；不做 undo/回收站（YAGNI）

---

## 7. 业务不变量

| # | 分类 | 维度 | 不变量 | 违反后果 |
|---|---|---|---|---|
| I1 | 强 | 业务语义 | 终态可信（C6）：DONE 只能来自人面（CLI）approve；agent 从任何面（含 MCP）无法把需求置为 DONE | 完成状态不可审计，看板立身（可回溯审计资产）失败 |
| I2 | 强 | 业务语义 | 事件链永不半断：任何删除操作以"整个需求"为单位（delete = 整需求 + 整链同事务；prune = 窗口内终态需求整链）；不存在只删某需求部分事件的操作 | 回溯判据 5 条不可答，审计链自相矛盾 |
| I3 | 强 | 业务语义 | archive 与 abandon 是语义区分的记录：archive 事件（state_change -> ARCHIVED，claim release_reason="archive"）与 abandon 事件（-> REJECTED/CANCELLED）可区分；archive 不重写/不改判 REJECTED/CANCELLED 的工作判断语义 | "移出视野"与"取消工作"在审计中不可区分，违反"关键审计点"定位 |
| I4 | 强 | 业务语义 | delete/archive 仅人面：MCP（agent）面无 delete/archive 工具；销毁审计链的唯一路径（delete）只能由人发起 | agent 可销毁审计链，威胁模型边界被打破 |
| I5 | 强 | 技术 | delete 单事务原子：events -> claims/subtasks/milestones -> requirement 同事务删除；崩溃/并发下要么全删要么全不删，无 FK 悬空 | 数据损坏、视图查询崩溃、事件引用悬空 |
| I6 | 软 | 业务规则 | archive 任意状态（含终态）可达，无 unarchive；ARCHIVED 任务 agent 可读（get_task_detail）但不可认领（state != OPEN）/不可写（无活跃认领） | 软：已归档任务成为僵尸（agent 仍可开工）或人失去冷存储层管理能力；可恢复（状态机边可后加） |
| I7 | 软 | 业务规则 | 保留分工：delete 不受保留窗口约束（显式即时）；ARCHIVED 入 prune 终态集合（12 个月窗口整删）；非终态不被 prune 删除 | 保留策略不一致：归档数据永不清理（容量/隐私风险），或活任务被 prune 误删（活审计主体被毁） |
