# BCD：B10 审查拒绝的状态路径（交接被拒可观测、可计数、可返工）

- 关联规范：docs/PRD.md §3.1 状态与边 / §3.2 认领与租约 / §3.4 完成语义 / §4.2 人面；skills/agent-kanban/SKILL.md「门序 8 等裁决」+「交接与等待」；skills/agent-kanban/references/contract.md「状态机边」；references/dispatch.md「循环（返工）」
- 版本：v1.2（2026-10-31，B10；v1.1＝plan 盲审折入；v1.2＝折入派发方补充约束「REOPEN 复派断点收口」，见 §3 末段与 §8）
- 需求来源：2026-10-30 派发方复验实测（板上 note seq 714）——worker 交接被拒时无可观测状态转移，「被拒」不可观测、不可计数，awaiting_human 一直挂着 kind=review

## 1. 客户原话语义分析

需求原文（看板 a111d9ce，指针行 workspace=/home/shih/test/AgenticKanban）：

> 给 review 加一条明确边（人面 op）：CLAIMED + awaiting_human(kind=review) -> 拒（REOPEN 或新增 REJECTED_BY_REVIEW，实现者判断后择一并说明理由）；拒时写事件（kind 与 payload 形态明确：拒因、指向哪个子任务/锚），使「返工轮次」可计数；SKILL 与 docs/PRD.md 同步：agent 面在被拒后该做什么（resume 续接 vs 重新派发），人面 CLI 命令写清；租约语义：拒后返工是否续租/是否重置 idle 时钟，写明口径。

判据（需求原文）：一次真实返工在板面上能读出——第几轮交接、谁拒、拒因、返工后状态；而不是只靠会话 resume 的隐式路径。

锚读法：a2「payload 含拒因文本与指向」是 payload 形态规定（字段恒在），不是输入必填规定——指向可空（整体退回合法，见 §7 I7 软约束），拒因必填。

实测事实（需求原文，勿再猜）：

1. ALLOWED_EDGES（state_machine.py:19-31）里 REOPEN 的入边只有 (DONE, REOPEN)；CLAIMED 不能转 REOPEN。
2. request_review 只设 awaiting_human(kind=review)，不改 state；被拒后需求停在 CLAIMED + 标记，人面看不出「已审且拒」。
3. 实操返工只能 cli.py resume 把意见投回同一会话，靠 worker 再次 request_review 覆盖等待面——「被拒」不进事件链，轮次不可计数。
4. REJECTED 状态已存在但语义是「需求被拒」（abandon --to-state REJECTED），与「交接被拒」不同义，不复用。

## 2. Impact Mapping

- **Why**：C1「默认视图回答三问」中「返工轮次 / 谁拒 / 拒因」目前无数据；评审拒绝是 agent-ops 循环的高频节点（Gmail 批先例：复验发现缺陷 -> 返工 -> 二次交接），其不可观测直接削弱看板「关键决策记录点/审计点」定位。
- **Who**：人（裁决方，看到「已拒 + 拒因 + 轮次」而非悬挂的 review 标记）；worker（被拒后拿到明确的重入路径与轮次编号）；派发方（复验拒绝有正典 op，不再靠隐式 resume）。
- **How**：状态机加边 (CLAIMED, REOPEN)（人面）；新人面 op `reject_review`（CLI `reject` + REST）单事务完成转移 + 结束认领 + 写 review_reject 事件（拒因/指向/轮次）；request_review 事件与标记带 round（第几轮交接）；SKILL/contract/PRD/dispatch 四处文档同口径同步；契约版本 3.2 -> 3.3。
- **What**：见 §3 Domain Event 流、§4 场景、§7 不变量。

## 3. Domain Event 流

事件 kind 全集 +1：`review_reject`（severity=attention）。不加表、不加列（awaiting_human 与 events.payload 均为既有 JSON 列）。

- **状态边**：`ALLOWED_EDGES` 新增 `("CLAIMED", "REOPEN"): HUMAN`。现有边逐条不动（I4）。
- **ReviewRejected**（新事件 kind=`review_reject`，severity=attention，title=`review rejected`）：
  - payload = `{reason: <拒因文本，必填>, target: <子任务 id 或验收锚 id，可空>, round: <被拒交接的轮次，int>}`（delegated 路径同事务事件均带 `payload.delegated`）。
  - 同事务伴随 `state_change` 事件（CLAIMED -> REOPEN，payload 带 reason/target/round，经 transition 的 event_payload 通道）。
  - round 口径：读自被拒时刻的 awaiting_human 标记（`marker.round`）——被拒的是哪一轮交接就是几，不自增、不另设计数器（结构上无双口径）。legacy 标记（3.3 前创建、无 round 键）round 按 1（纯防御：生产 DB 现无 awaiting_human 非空需求，实测 0 条）。
- **ReviewRequested 扩展**（不是新事件，`review_request` payload 扩展）：
  - `payload.round` = 1 + 本需求此前 `review_request` 事件数（第 N 次交接 = round N）。
  - `awaiting_human` 标记新增键 `round`（同值）；既有键（reason/evidence/since/kind/summary_line）不动。
- **租约**：reject 单事务内结束认领（`ended_at` 置位 + `release_reason="review_rejected"`）。租约时钟与 idle 时钟随认领结束而停；**拒不改写 lease_expires_at（不续租）**。
- **重入路径（返工）**：REOPEN 后由人面 `reopen --continue`（既有 op，REOPEN -> OPEN）回到可认领；返工的 worker（续接会话或新派）重新 `claim_task`（新认领行、全新租约 2h / idle 30min）。即租约口径 = **重置**（返工 = 新认领周期），文档三处同口径（PRD §3.2 / contract.md / SKILL）。
- **幂等/覆盖语义（重复拒）**：每个交接轮次至多一次 reject——第一次拒后状态 = REOPEN，第二次 reject 前置不满足 -> `illegal_state`（明确拒写，非静默幂等）。再次拒绝必须经由新一轮交接（新的 review_request）。
- **REOPEN 复派断点收口（dispatch 自动折回，派发方 2026-10-31 补充约束，板上 note seq 1166）**：
  - 断点事实：dispatch 状态门收 REOPEN（`DISPATCHABLE_STATES=("OPEN","REOPEN")`），但 claim 硬写 from_state=OPEN——REOPEN 下 worker 首个动作 claim_task 即 `illegal_state`（探针 /home/shih/.tmp-ak-m16/b10-review-reject/probe_reopen_claim.py 实测）。本批 reject 停在 REOPEN 后复派必断。
  - 收法（三选一中择 ①，理由见批次 ledger decision 节）：dispatch 遇 REOPEN，在主链进入服务发现/会话创建前（MCP 预检之后，预检拒派保持零写）经**既有 (REOPEN, OPEN) 边**自动折回 OPEN——人面 actor（cli surface），state_change 事件带 delegated 受托痕（basis 指向 dispatch 折回意图）；板面另写一条人话 note（首行「自动折回」）；派发稿/续接稿均注明折回。折回后需求处于可认领态，worker 首个动作 claim_task 结构性可成功（断点闭合）。
  - 语义边界：折回后派发若失败不折回滚（需求已 OPEN，可直接认领或再派，幂等）；人面手返工路径（`reopen --continue`）不受影响，两路同一条边、不同触发，不冲突；加边 (REOPEN, CLAIMED) 已否（claim 绕过「回到可认领」窗口，与既有边冗余）；DISPATCHABLE_STATES 不收窄（②属既有行为变更，REOPEN 可派是既有契约）。

## 4. BDD Given-When-Then 场景

### S1（happy）：评审拒绝可观测
- Given：需求 CLAIMED + 活跃认领，worker 已 request_review（awaiting_human.kind=review，round=1）
- When：人面 `reject --requirement-id <id> --reason "复验发现缺陷：X"`
- Then：rc 0；state=REOPEN；事件链同事务新增 `state_change`（CLAIMED->REOPEN，payload 含 reason）+ `review_reject`（severity=attention，payload={reason, target: null, round: 1}）；认领 ended_at 置位（release_reason=review_rejected）；awaiting_human 清除；get_task_detail 可读全部（谁拒＝actor 归属、拒因、轮次）。

### S2（edge）：拒因必填
- When：reject 缺 reason / 空 reason
- Then：`invalid_record`；零写入（state/标记/事件链/认领逐字不变）。

### S3（edge）：状态前置
- Given：OPEN（未认领）/ DONE / REOPEN / BLOCKED 的需求
- When：reject
- Then：`illegal_state`；零写入。

### S4（edge）：无待审标记
- Given：需求 CLAIMED + 活跃认领，但从未 request_review（无 awaiting_human）
- When：reject
- Then：`illegal_state`（reject 的语义对象是「待审交接」；无标记的退回走既有 `release --reason`（CLAIMED->OPEN），两路不混用）。

### S5（edge）：重复拒
- Given：S1 已发生（state=REOPEN）
- When：再次 reject
- Then：`illegal_state`；事件链不新增 review_reject（轮次计数不污染）。

### S6（edge）：指向校验
- Given：S1 前置，需求有子任务 s1 与验收锚 a1
- When：reject `--target <s1 的 id>` -> 成功，payload.target = 归一后的子任务 id
- When：reject `--target a1` -> 成功，payload.target = "a1"
- When：reject `--target <不存在>` -> `invalid_record`，错误消息含本需求可用清单（子任务 id + 锚 id，B3.2 自纠口径）；零写入。

### S7（round）：轮次可区分
- Given：S1 前置（round=1 的交接）
- When：reject#1 -> `reopen --continue` -> 重新 claim -> request_review 第 2 次
- Then：第 2 次交接的 awaiting_human.round = 2，review_request 事件 payload.round = 2；再 reject#2 的 payload.round = 2；第 3 次交接 round = 3。全程事件链可读出「第 2 轮交接被拒」。

### S8（delegated）：受托代执行
- When：reject `--on-behalf "statement:<原话>"`
- Then：两事件 actor_surface=delegated 且 payload.delegated={kind, basis}（与 release/approve 同口径）。

### S9（租约）：拒后返工 = 新认领周期
- Given：S1 前置
- When：reject -> `reopen --continue` -> claim
- Then：旧认领 ended_at 非空且 lease_expires_at 未被 reject 改写（拒不续租）；新认领 lease_expires_at = 新认领时刻 + 2h（全新窗口，idle 时钟随 last_activity_at 重置）。

### S10（agent 面边界）：reject 不进 MCP
- Then：MCP 14 工具集不含 reject/reject_review（ac3 既有断言 + 本批显式断言）；CLI/REST 可达。

### S11（REST 对等）：
- When：`POST /requirements/{id}/reject {reason, target?}`
- Then：与 CLI 同 service 层同语义；错误映射沿用 REST 契约（illegal_state=409 / invalid_record=422 / not_found=404）。

## 5. Spec by Example

| 例 | 输入（要点） | 期望 |
|---|---|---|
| E1 | 待审交接 + reason | REOPEN；两事件；认领结束；marker 清 |
| E2 | 无 reason | invalid_record；零写入 |
| E3 | OPEN/DONE/REOPEN/BLOCKED | illegal_state；零写入 |
| E4 | CLAIMED 无标记 | illegal_state |
| E5 | 连续两次 reject | 第二次 illegal_state |
| E6 | target=子任务 id / 锚 id / 垃圾 | 前二成功且 payload.target 正确；垃圾 invalid_record + 可用清单 |
| E7 | 交接1 -> 拒 -> 重入 -> 交接2 -> 拒 -> 重入 -> 交接3 | round 依次 1/2/3（标记与事件同值） |
| E8 | --on-behalf 合法/非法 | 合法 -> delegated 双事件；非法 -> invalid_record（先于状态校验） |
| E9 | 拒后重认领 | 旧租约未改写；新租约 = 新窗口 2h |
| E10 | MCP 调 reject | 工具不存在（14 工具集精确） |
| E11 | 零输入 reject（1 条待审 / 2 条待审 / 0 条 / 仅 1 条 blocked） | 1 条 -> 直接执行；2 条非交互 -> 列候选拒；0 条 -> 「无待审项」零写（候选＝kind=review 待审，blocked 在库不混入、文案区别于 approve/release 的「无待决项」）；blocked 不计入候选（仅 kind=review 可拒） |

## 6. Premortem（假设 6 个月后失败）

1. **REOPEN 双语义混淆**：DONE 被拒（既有）与交接被拒（新增）共用 REOPEN 状态，人看状态分不清来源。
   缓解：事件链天然区分（交接被拒必带 review_reject 事件 + state_change from=CLAIMED；DONE 被拒 from=DONE 且无 review_reject）；PRD/contract.md 明写两个来源。残余：状态名本身不区分——接受（状态面从简，事件面是审计正典；需求判据「板面能读出谁拒/拒因/轮次」由事件满足）。
2. **worker 忘记重认领**：被拒后 worker resume 上来直接写板 -> no_active_claim 卡死。
   缓解：SKILL 把「返工首个动作 = claim_task（重认领）」写成硬条款 + 错误码自解释。残余：仍靠人读 SKILL（与既有「释放是人的职责」同级别的协议纪律）。
3. **人忘 reopen --continue，需求悬在 REOPEN**：返工永远不开始。
   缓解：REOPEN 是未终态，list_tasks 常显，人面可见；**dispatch 复派路径由自动折回闭合**（§3 末段：人复派时 dispatch 自动 REOPEN->OPEN，不再依赖人先跑 reopen --continue）。残余：人工直认领路径仍需人先 `reopen --continue`；无自动提醒/TTL（需求明示不做，G37 另排）。
4. **版本漂移**：包升到 3.3 但 worker 客户端装的 skill 还是 3.2（无 reject 文档/判据）。
   缓解：契约版本 3.2 -> 3.3 本身就是漂移探测器（p3_skill_text(10) 版本链 + `--version` 对比口径既有）。残余：已装客户端不自动升级（既有运维事实，不在本批）。
5. **round 双口径漂移**：交接轮次（review_request 计数）与拒事件 round（读自标记）在「release 不拒再交接」的异常流下数值错位。
   缓解：reject 的 round 恒读自被拒交接的标记，不自增——结构上单计数源（review_request 计数），无第二个计数器可漂移。PRD 写明两口径定义。残余：异常流下「第 N 次拒」≠「第 N 次交接」（拒事件只声明被拒的是哪一轮，不声明自己是第几次拒）——接受，需求判据只要求「第几轮交接可区分」。

## 7. 业务不变量

强不变量（违反＝业务失败）：

- **I1 拒绝可观测**：任何一次评审拒绝必须同事务产生 `review_reject` 事件（含拒因）+ `state_change`（CLAIMED->REOPEN）；拒绝后不得存在「板面看不出已拒」的状态（awaiting 标记必被清除）。违反后果：需求永久悬挂 kind=review，人面把「已审且拒」读成「等待中」（本批要消灭的现状）。
- **I2 拒绝原子性**：reject 的状态转移、认领结束、两事件在同一事务；任一失败 = 零写入（不出现「状态转了但事件没写」或「事件写了但认领没结束」的半态）。违反后果：审计链半断，租约/状态失配（claim-state drift 误报源）。
- **I3 轮次可区分**：任何一次 request_review 的轮次 = 1 + 本需求此前 review_request 事件数，标记与事件同值；任何一次 review_reject 的 round = 被拒交接标记的 round。重复拒不产生歧义（每轮交接至多一次 reject，第二次 = illegal_state）。违反后果：返工轮次不可计数（需求判据直接失败）。
- **I4 现有边语义不变**：OPEN/CLAIMED/DONE 既有边逐条不动；MCP 面 14 工具集不变，release/approve/delete 仍只在人面。违反后果：存量行为回归（ac3/ac16 等既有断言红）＝契约变更越界。
- **I5 租约口径一致**：reject 结束认领且不续租（lease_expires_at 不改写）；返工经新认领获得全新租约窗口。文档三处（PRD §3.2 / contract.md / SKILL）口径与实现一致。违反后果：文档口径与实现漂移＝协议信任崩塌（本仓第一红线）。
- **I6 单一状态口径**：新边 (CLAIMED, REOPEN) 在 state_machine.ALLOWED_EDGES 与 docs/PRD.md §3.1 状态表（及 contract.md 镜像）同时登记，三处同一条边。违反后果：两处漂移（需求 a1 明确禁止）。

软约束（违反可容忍）：

- **I7**：target 指向可空（整体退回合法）；target 非空时必须是本需求子任务 id 或验收锚 id。
- **I8**：零输入 reject 只把 kind=review 的待审项列为候选（blocked 待决不混入拒绝候选）。

## 8. 范围（实现者纪律）

- 改：`src/agent_kanban/services/state_machine.py`（+1 边）、`src/agent_kanban/services/operations.py`（`reject_review` 新 op + `request_review` round 扩展）、`cli.py`（`reject` 子命令，含零输入候选）、`src/agent_kanban/api/requirements.py`（REST reject 端点）、`src/agent_kanban/api/web.py`（事件 kind 过滤列表 +review_reject）、`src/agent_kanban/mcp/server.py`（request_review docstring 补 round 说明）、`src/agent_kanban/__init__.py`（CONTRACT_VERSION 3.3）、`src/agent_kanban/dispatch.py`（REOPEN 自动折回：状态门后、服务发现前，§3 末段语义）、`tests/ac_cases_dispatch.py`（新用例 k_dispatch_reopen_foldback + k_history_assembly 摘要行口径修正）、`tests/ac_cases_r.py`（新）+ `tests/run_ac.py`（注册）、`docs/PRD.md`（v3.3：§2 标记字段与 kind / §3.1 边表 / §3.2 租约口径 / §3.4 或就近新增拒绝语义 / §4.2 reject 命令）、`skills/agent-kanban/SKILL.md`（frontmatter 3.3 + 门序 8 + 交接与等待 + 认领纪律租约行）、`skills/agent-kanban/references/contract.md`（边表 + 租约行）、`skills/agent-kanban/references/dispatch.md`（循环节：复验拒绝正典路径）、`AGENTS.md` + `docs/ops/ci-verification.md`（基线四处同步）、`docs/adr/0000-known-gaps.md`（残余登记，若新增需编号连续）。
- 不改：`src/agent_kanban/models.py` / `alembic/`（无 schema 变更）、`lease.py` / `reconcile.py` / `retry_limit.py` / `write_guard.py`、`skills/agent-kanban/templates/`、`tests/e2e/`（只跑不回归）、release/approve/renew/reopen 既有逻辑、e2e 用例。
- 先红后绿：新断言先跑红（reject 不存在/边不存在），红绿日志分文件留档批次目录。
- skill 树 token 门：树内任何 .md 禁仓内路径 token（cli.py 等），CLI 一律以 `agent-kanban` 指称（AGENTS.md 教训，b4 实锤）。
