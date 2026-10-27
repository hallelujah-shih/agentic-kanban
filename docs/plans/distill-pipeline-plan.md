# Plan: distill-pipeline 记录管线蒸馏重构（R1-R4）

**基**: main `cfa8363`（本地已 ff）
**分支/worktree**: `distill-pipeline` / `.worktree/distill-pipeline`
**BCD（硬前置，已裁决）**: `docs/business-contracts/distill-pipeline.md`（5 项裁决 2026-10-27 user 均按推荐）
**批次产物目录**: `/home/shih/.tmp-ak-m16/distill-pipeline/`（ledger、dispatches/、红绿日志、导出基线冻结件）
**档位**: 全六门（D 面 ∧ 架构级 ∧ 单向门 ∧ 新测试语义）——plan 盲审走 adversarial-review 全量四层（含 rollback/兼容矩阵核查）

## 北极星（本批设计原则，BCD §3 Policies，将写入 PRD §0）

蒸馏恰好一次，在生成点：写契约强制人面提纲（服务端只校验结构，不生成语义）；
存储/展示忠实不聪明（不二次摘要、不做读侧语义挑选）。看板价值＝替人蒸馏。

## 范围纪律（不修清单，全任务生效）

1. 状态机边集与语义（ALLOWED_EDGES、transition 校验顺序、同事务内核）不动——
   `event_payload` 为 additive 参数，唯一例外（偏差 D1 登记：payload 键只增，kind 集冻结）。
2. 租约语义（2h/30min、signal 派生、renew 口径）不动。
3. 写保护/单写者 seq/写锁不动。
4. SSE 帧形状（7 字段 + keepalive）不动。
5. view.board / view.summary 派生口径（`_derived_signals`、验收对照、进度派生值、
   AC13 禁止面）不动。
6. `MAX_ACTIVE_CLAIMS=16` 代码不动（仅 PRD §4.3 笔误 6->16）。
7. prune / export CLI 语义（终态窗口原子性、confirm、错误路径）不动。
8. kind 12 集冻结：不加新 kind；payload/JSON 形状只增键不改键。
9. A1 短 id 前缀匹配挂账不碰。
10. known-gaps 本批不新增条目。

## 任务总览（串行，T1->T4；operations.py/run_ac.py 文件交集强制串行）

| 任务 | 面 | 主改文件 | oracle 基线变化 |
|---|---|---|---|
| T0 prep | 环境 | worktree `.venv` symlink、docs commit | - |
| T1 | R1 契约+工具自描述 | server.py、operations.py、state_machine.py、ac_cases_l.py(新)+run_ac.py、既有 test 调用点、e2e/seed.py | 521 + N1（实测） |
| T2 | R3 读侧 | view.py、operations.py、ac_cases_l.py+run_ac.py | 521 + N1 + N2（实测） |
| T3 | R4 展示+e2e | web.py、docs/web.md、smoke.spec.js、e2e/seed.py | e2e 12 -> 15 |
| T4 | R2 skill+正典 | SKILL.md、PRD.md、AGENTS.md | AGENTS.md 基线改实测值 |

---

## T0 prep（主循环直做，非 subagent）

1. `ln -s /home/shih/test/AgenticKanban/.venv .worktree/distill-pipeline/.venv`
   （主仓 .venv 存在；.gitignore:6,19 覆盖，不进版本库）。
2. **P0 环境修正（T0 实测发现，实证在 ledger T0 节）**：.venv 内
   agent_kanban 是 editable 安装（`_editable_impl_agent_kanban.pth` 固定指向
   主仓 `/home/shih/test/AgenticKanban/src`）。run_ac 侧无碍（ac_lib 自设
   `env["PYTHONPATH"]=SRC`，SRC 按 ac_lib 自身位置解析＝worktree src）；但
   playwright webServer 命令（playwright.config.js:16）`python -m agent_kanban.api`
   无 PYTHONPATH，从 worktree 跑 e2e 会**加载主仓代码**（已实证：worktree 内
   `import agent_kanban` -> 主仓 src；`PYTHONPATH=src` 前缀 -> worktree src）。
   修正：webServer 命令的服务段自携带
   `PYTHONPATH=${PYTHONPATH:+$PYTHONPATH:}src`（cwd＝执行目录，worktree/主仓/CI
   checkout 三种形态下均解析到对应 src；CI 侧包同为 editable 安装，同路径，
   零漂移）。不改重跑命令（config 自携带，ci-verification 规格不动）。
   独立 commit：`fix(test): playwright webServer 自携带 PYTHONPATH`。
3. 验证 symlink 生效（worktree 内，带 PYTHONPATH=src 前缀）：
   `PYTHONPATH=src .venv/bin/python -c "import agent_kanban; print(agent_kanban.__file__)"`
   应打印 worktree 路径。
3. commit BCD + 本 plan（docs-only，一条 commit：
   `docs: distill-pipeline BCD（已裁决）+ 实施 plan`）。
4. 机械预检 4 项（结果记 ledger）：
   - P-1 BCD/plan 已 tracked（`git ls-files` 含两文件）。
   - P-2 锚点抽核：`git show cfa8363:src/agent_kanban/services/operations.py` 的
     :717 title="progress" 常量、:754 severity="info"、:880 stmt.limit(event_limit)
     + :938 event_limit=200 四处与本 plan「现状」节逐字一致。
   - P-3 产物清单：本 plan「任务总览」表文件集 + T0 环境修正的
     playwright.config.js = 全部将改文件（实施中新增文件须回报）。
   - P-4 oracle 版本 pin：`.venv/bin/python -c "import mcp, sqlalchemy; print(...)"`
     + node/playwright 版本，记入 ledger（导出基线冻结件依赖该环境）。
5. 跑基线留档（非 gate，T3 红绿的测量原点）：
   - 全量：`TMPDIR=.../tmp .venv/bin/python -u tests/run_ac.py` 应 521/521
     （log 落 t0-ac-baseline.log）。
   - e2e：`TMPDIR=.../tmp AK_E2E_DB=/home/shih/.tmp-ak-m16/distill-pipeline/ak-e2e.db npx playwright test`
     应 12/12（log 落 t0-e2e-baseline.log；P0 影子修正后首跑，同时验证修正生效）。

## T1 R1 写侧契约 + 工具自描述

**BCD 映射（五元组）**：
- 裁决 1(a) update_progress 必填 headline -> 本任务 l_headline oracle
- 强不变量 3「人面记录必带提纲」-> l_headline / l_summary_line / l_record_title
- 裁决 5/Scenario 2 交接一句话 -> l_summary_line
- Scenario 3 阻塞原因进追加链 -> l_blocked_reason_chain
- Premortem 1 带内兜底 -> l_tool_self_desc

**契约锚**：BCD §1 裁决 1/§3 Commands 1-4/§4 Scenario 1-3；PRD §4.1（工具表）、§4.3（错误码）。
**数据锚**：events 行（title/content/payload/severity）；requirements.awaiting_human dict。

### 现状（锚点，行号对基 cfa8363）

- operations.py:703-721 `update_progress`：`add_event(..., kind="progress_note", severity="info",
  title="progress", content=note, payload={"note": note} ...)`（title 常量＝第一 bug 根因）。
- operations.py:724-759 `request_review`：severity="info" 常量（:754）；
  `awaiting_human={"reason","evidence","since","kind"}`（:747-752，无一句话）；
  事件 payload={"evidence"}（:755）。
- operations.py:798-823 `mark_blocked`：reason 只落 awaiting_human（:817-820），
  事件链无痕；transition 调用（:813-816）不传任何 payload。
- operations.py `add_record`（:668-700）：title 签名必填但无空串校验（`""` 可写）。
- state_machine.py:34-74 `transition`：无 payload 参数；:74 写 `payload={"from": from_state, "to": to_state}`。
- mcp/server.py:51-133：12 工具包装器，全部无 docstring；build_server :136-154
  `MCPServer(name=..., version=...)` 无 instructions。SDK 已实测支持：
  `add_tool(fn, description=...)`（缺省取 fn docstring）、`MCPServer(instructions=...)`。
- 既有 test 调用点（T1 必须同批改，否则全量红）：
  - update_progress 成功路径（加 `headline`）：ac_cases_b.py:45、ac_cases_c.py:149、
    ac_cases_d.py:97、ac_cases_f.py:351,432、ac_cases_g.py:285、ac_cases_j.py:43、
    ac_cases_k.py:298。
  - update_progress 错误路径（校验顺序 state/claim 在前，缺 headline 不影响目标错误码，
    保持原样但须逐一确认）：ac_cases_b.py:28（no_active_claim）、ac_cases_d.py:94
    （8KB invalid_record——**加 headline**，确保被测错误是 8KB 而非缺 headline）。
  - request_review 成功路径（加 `summary_line`）：ac_cases_a.py:91,127、
    ac_cases_b.py:121,153,214、ac_cases_c.py:31,203,268,436,464、
    ac_cases_e.py:65,113,133、ac_cases_f.py:248,353、ac_cases_g.py:245。
  - request_review 错误路径（加 `summary_line` 保持被测错误单一）：
    ac_cases_a.py:166（illegal_state）、ac_cases_b.py:186、ac_cases_c.py:266、
    ac_cases_f.py:187,207,392（invalid_record/illegal_state）。
  - e2e seed：tests/e2e/seed.py:79 `update_progress`（加 headline；S3 提纲自定，
    E3c/E11 计数不受 title 影响）。
  - ac_cases_a.py:117-119 工具名列表（无 payload，不动）。

### 变更规格

1. **state_machine.py** `transition` 加可选参数 `event_payload: dict | None = None`；
   :74 处 `payload = {"from": ..., "to": ...}`，若 event_payload 非空则
   `payload.update(event_payload)`。其余逻辑零改动。
2. **operations.py**：
   - `update_progress` 加 `headline: str | None = None`（签名可选——必填签名参数
     会变成 MCP 框架错误而非本仓错误消息，陷阱库既定）。校验顺序：
     get_active_claim -> headline 校验 -> _check_payload_size -> add_event。
     校验：`headline` 为 None 或 `strip()` 空 -> `BusinessError("invalid_record",
     "update_progress requires headline: one-line human outline. e.g. headline=\"修了 test_view 竞态\"",
     requirement_id)`。写入：`title=headline.strip()`，content/payload 不变
     （payload={"note": note} 保留，旧数据读侧兼容）。
   - `request_review` 加 `summary_line: str | None = None`（同样可选签名+ops 校验）。
     校验顺序：state 检查（illegal_state）-> evidence 校验（既有 invalid_record）->
     summary_line 校验（消息：`request_review requires summary_line: one line of what
     was done / where to look first. e.g. summary_line="重做了记录管线，先看事件流"`）。
     写入：`severity="attention"`（原 "info"）；`awaiting_human` dict 增键
     `"summary_line": summary_line.strip()`；事件 payload 增键 `"summary_line"`
     （与 evidence 平级）。
   - `add_record`：kind 校验通过后、payload 校验前，加 title 校验：
     `title` None/strip 空 -> `invalid_record`，消息指明 title 须为一行人话提纲
     （带示例）。
   - `mark_blocked`：transition 调用加 `event_payload={"reason": reason}`。
     awaiting_human 设置不变（双写：marker 供等待面，事件供审计链）。
3. **mcp/server.py**：
   - `update_progress` 包装器加 `headline: str | None = None` 转发；
     `request_review` 包装器加 `summary_line: str | None = None` 转发。
   - 12 工具各加 docstring（自描述带内兜底）：一句话用途 + 关键参数 + 主要错误码。
     写工具（update_progress/add_record/request_review/mark_blocked）额外一句
     记录契约（提纲必填、报节点不报流水账）。每工具 2-4 行，禁复制 skill 全文。
   - `build_server`：`MCPServer(..., instructions=...)`——server 级说明 3-6 行：
     看板=记录面非控制面；每条人面记录必带一行人话提纲；交接附三行简报
     （做了什么/先看哪/还剩什么）；等待面只认 awaiting_human。
   - description 文案与 SKILL.md（T4）同一套措辞口径（本任务先写，T4 对齐引用，
     防带内外漂移）。
4. **tests/ac_cases_l.py（新文件）+ run_ac.py**（TESTS 字典加条目，import 行加
   `from ac_cases_l import ...`）。新用例（函数名=用例 id）：
   - `l_headline`：update_progress 缺 headline -> invalid_record 且 message 含
     "headline"；仅空白 headline -> invalid_record；正常 -> DB 直查事件
     title==headline.strip()、content==note、severity=="info"、payload.note==note。
   - `l_summary_line`：request_review 缺 summary_line -> invalid_record 且 message
     含 "summary_line"；BLOCKED 上 request_review 仍 -> illegal_state（顺序不回归）；
     正常 -> awaiting_human.summary_line == 传入值；DB 直查 review_request 事件
     severity=="attention" 且 payload.summary_line 在场。
   - `l_record_title`：add_record(kind=note, title="") -> invalid_record；
     title="   " -> invalid_record；正常 title 成功。
   - **无半态断言（BCD 边缘 2 Then，审 r1 P2-1）**：上述三个用例的每个
     错误路径分支都加事件链不变断言——写前 `SELECT COUNT(*) FROM events WHERE
     requirement_id=?` 与写后相等（且需求行 awaiting_human/state 未变）；
     防「先写事件再抛错」的实现使错误码绿而留半态。
   - `l_blocked_reason_chain`：claim -> mark_blocked(reason="等 user 裁决 X") ->
     DB 直查 state_change(CLAIMED->BLOCKED) payload 含 reason=="等 user 裁决 X"；
     CLI approve -> awaiting_human 清除；事件链 reason 仍在（审计可回溯）。
   - `l_tool_self_desc`：in-process `from agent_kanban.mcp.server import build_server`
     -> server.instructions 非空；12 工具 description 全部非空（工具名集合 ==
     {list_tasks, get_task_detail, claim_task, add_subtask, update_subtask,
     add_milestone, update_milestone, add_record, update_progress, request_review,
     mark_blocked, list_awaiting}）。
5. **既有 test 调用点**：按「现状」清单逐一加参数（成功路径必填；错误路径加参数
   保持被测错误单一；ac_cases_d.py:94 加 headline 后仍测 8KB）。
6. **e2e/seed.py:79** 加 headline。

### 红绿

- 红（对当前代码跑，日志落 `t1-red.log`）：`l_headline`（缺 headline 现返回 ok）、
  `l_summary_line`（现无该参数/无 summary_line 键、severity 恒 info）、
  `l_record_title`（空 title 现成功）、`l_blocked_reason_chain`（payload 现无 reason）、
  `l_tool_self_desc`（现 description 全空）。全部红 = 判别力在场。
- 绿：实现 + 调用点改毕 -> 全量套件绿。

### 验证命令

- 快反：`TMPDIR=/home/shih/.tmp-ak-m16/distill-pipeline/tmp .venv/bin/python tests/run_ac.py --only l_headline,l_summary_line,l_record_title,l_blocked_reason_chain,l_tool_self_desc`
- 全量：`TMPDIR=... .venv/bin/python -u tests/run_ac.py`（521 + N1，N1=新断言数，实测记录）
- e2e 不回退（seed 已改）：`TMPDIR=... AK_E2E_DB=/home/shih/.tmp-ak-m16/distill-pipeline/ak-e2e.db npx playwright test`（12/12）

### 任务级不修

- 不改 update_progress 的 payload 形状（note 双写保留）。
- 不删/不改其余 10 工具签名。
- 不动 _check_payload_size 8KB 语义。

### 验收与 commit

- 全量 + e2e 绿；N1 实测值回报主循环。
- commit：`feat(mcp): 人面记录必带提纲 + 工具自描述（R1，BCD distill-pipeline 裁决1/3）`

---

## T2 R3 读侧：detail 合并 + 最新优先 + audience 单点

**BCD 映射**：
- 裁决 3 关键事件=最新优先+提纲、无读侧挑选 -> l_latest_first
- Policy 4 人/机分类单点同源 -> l_audience
- 强不变量 1 蒸馏不破坏追加链/export 全量 -> l_export_stable（回归 oracle）
- 强不变量 2 存储忠实不聪明 -> l_latest_first 只按 seq 截取，无内容判断

**契约锚**：BCD §3 Policies 1-2/§4 边缘 3/§7 强 1-2；PRD §4.1:151（关键事件口径）。
**数据锚**：view.detail 返回 dict；export 三种 fmt 文本。

### 现状（锚点）

- 双源：operations.py:859-925 `_requirement_detail`（MCP get_task_detail :928-939
  带 event_limit=200、export_data :974+ 带 None）与 view.py:441-516 `detail`
  （web 深潜+REST，全链无 limit，含 state_at_event/history_note）。
- 双源形状差异已实测核完（合并安全前提）：
  - `claims` 两源同形状（均为全 claims 按 started_at、逐条 claim_view 9 键含
    release_reason；view 侧 _claim_timeline:289-299 与 ops 侧 :892-899 同构）。
  - view.detail 多 `history_note` 键（:485）与事件多 `state_at_event` 键（:512）
    ——均为 additive，旧消费者（markdown/csv 渲染器显式取键）不受影响。
  - ops 侧多无——合并方向＝view.detail 吸收 event_limit，删 ops 侧。
- 最旧 200：ops _requirement_detail :878-881 `order_by(Event.seq)` + `.limit(event_limit)`
  （升序+limit＝最旧 N 条，丢最新）。
- export 渲染器消费面（view.py）：render_export_markdown :642-682 显式取键
  （title/state/id/source/source_ref/description/acceptance/subtasks/milestones/
  claim(agent_name,agent_conn,started_at,ended_at,release_reason)/
  events(seq,ts,kind,severity,actor_surface,actor_conn,title,content,payload)）；
  CSV_RECORD_FIELDS :685-693 显式字段表（event 行无 state_at_event；requirement 行
  含 claims）。两渲染器均忽略 dict 中未列键 -> **markdown/csv 对 additive 键天然免疫**。

### 变更规格

1. **view.py**：
   - 新增 `event_audience(kind: str) -> str` 单点：
     `BOOKKEEPING_KINDS = {"state_change", "decomposition", "reconcile", "release", "renew"}`；
     其余（progress_note/decision/deviation/review_request/approval/note/risk）-> "human"；
     未登记 kind（防御未来漂移）-> "human"（保守：宁可人面多显示，不把人面记录藏进簿记）。
   - `detail()` 加 `event_limit: int | None = None`。选取口径（写进 docstring）：
     全链 all_events（现 :463-465，reconstruct_states 永远用全链 :466 不动）->
     as_of 过滤（:469-471 现口径）-> 若 event_limit 非空：取**最新 N**
     （all_events 已 seq 升序，`filtered[-event_limit:]`；**加守卫
     `if event_limit and event_limit > 0`**——`[-0:]` 切片陷阱，审 r1 疑点 4）
     -> 再套 kinds/severities 过滤（先 limit 后 filter，结果可 < N，口径钉死）
     -> 输出保持 seq 升序。
   - 事件行（:506-514）加 `"audience": event_audience(e.kind)`。
2. **operations.py**：
   - `get_task_detail`（:928-939）改委托 view.detail：函数内惰性
     `from .view import detail as _view_detail`（沿用 export_data :1001 惰性 import
     模式，无循环依赖），传 event_limit=200 + 透传 actor_surface/actor_conn/now。
   - `export_data`（:974+）两处 `_requirement_detail(...)` 调用改 `_view_detail(...,
     event_limit=None)`。
   - 删 `_requirement_detail`（:859-925）。ops 本地 `_claim_view` 保留
     （list_tasks :853 / list_awaiting :967 仍用）。
3. **tests/ac_cases_l.py 续 + run_ac.py**：
   - `l_audience`：12 kind 逐一断言（5 簿记/7 人面，与 BCD §3 kind 集一致）；
     未知 kind "future_x" -> "human"。
   - `l_latest_first`：直 SQL 种子 250 条事件（bench.py 种子模式：seq 同步
     seq_counter、datetime 经绑定参数、payload 形状对齐）。**种子组成钉死
     （审 r1 P2-2，防判别力空真）**：250 条全 kind=note（人面）；severity 按
     seq 奇偶交替（偶=info、奇=attention）；边界事件固定 title：seq 50="e50"
     （info）、seq 51="e51"（attention）、seq 250="e250"（info）。
     断言：get_task_detail -> 恰好 200 条、seq 区间 [51,250]（含 e51/e250、
     不含 e50）、输出 seq 升序；kinds=["note"] 过滤后仍 200（先 limit 后
     filter 口径）；**低 severity 负判别**：seq 52/54（info 人面事件）在结果
     内（读侧不按 severity 过滤，Premortem 4 反向判别非空真）；
     export(fmt=json) -> 250 条全量。
   - `l_export_stable`（回归 oracle，红绿性质不同，见下）：fixture DB（直 SQL：
     1 需求 + 1 claim(ended, release_reason) + 1 subtask + 1 milestone + 事件集含
     旧形状 progress_note(title="progress", payload.note)、decision(结构化 payload)、
     review_request(severity=info)、state_change、blocked 链）->
     `ops.export_data` 三 fmt 输出：
     - markdown：与冻结基线 **byte-identical**；
     - csv：与冻结基线 **byte-identical**；
     - json：旧键值逐一相等 + 新增键 ⊆ {history_note, state_at_event, audience}。
   - **基线冻结（仪器冻结）**：T2 红步先在当前代码（T1 合入后、T2 改动前）对
     fixture 跑三 fmt 导出，输出存
     `/home/shih/.tmp-ak-m16/distill-pipeline/export-baseline/{md,csv,json}`；
     fixture 建库脚本同目录存档（export-fixture.py），重跑规格可复现。
     注意：T1 不触碰 export 读路径（只改写路径），故 T1 后捕获的基线 == 基 cfa8363
     行为，有效。
4. PRD §4.1:151 关键事件口径同步 -> **T4 做**（本任务只改码，docs 归 T4，防文档半态）。

### 红绿

- 红（`t2-red.log`）：`l_latest_first`（现返回最旧 200：seq [1,200]）、
  `l_audience`（函数不存在）、`l_export_stable` 的 audience 白名单断言在合并前
  为平凡绿（本用例主体是回归保护：合并后 md/csv byte-identical 若失败即抓出
  合并破坏）。红步同时完成基线冻结。
- 绿：全量套件 + l 系全绿。

### 验证命令

- 快反：`TMPDIR=... .venv/bin/python tests/run_ac.py --only l_latest_first,l_audience,l_export_stable`
- 全量：`TMPDIR=... .venv/bin/python -u tests/run_ac.py`（521 + N1 + N2）
- 生产 DB 只读冒烟（**P5 必做**，主循环做；审 r1 P2-5：强不变量 5「现成调用
  可读」在真实存量数据上的承接，E10 只有合成旧形状夹具）：新代码对
  `/home/shih/.agent-kanban/kanban.db` 跑 `export_data` 单需求导出成功（只读，
  不改生产）；若确不跑，ledger 记跳过理由 + 补偿承接说明。

### 任务级不修

- view.summary/board 不动（不消费 raw 事件行，无需 audience；单点函数留作后续读点）。
- reconstruct_states 算法/口径不动。
- export CLI 命令面/错误路径不动。
- get_task_detail 的 event_limit=200 数值不动（只改方向）。

### 验收与 commit

- 全量绿；md/csv byte-identical 证据（diff 输出）落批次目录。
- commit：`refactor(view): detail 双源合并 + 关键事件最新优先 + audience 单点派生（R3）`

---

## T3 R4 展示层：深潜页三层结构 + e2e 15 用例

**BCD 映射**：
- 差异表「默认视图关键节点」（根本性业务冲突）-> E3c 改写 + E11
- 裁决 5 web.md 新设计 -> docs/web.md 修订 + E9/E10
- 边缘 1 旧数据容忍 -> E10（空 title 降级 + 旧 "progress" 原样）
- Premortem 3 e2e 判别力 -> E9 XSS + canary 复验（主循环 P5 做）

**契约锚**：BCD §5 例 1/3/5；docs/web.md（本任务修订后为新契约）。
**数据锚**：/requirements/{id} JSON（events[].audience/additive 键）、/board JSON
（awaiting_human.summary_line）。

### 现状（锚点）

- web.py：_THEME :13-53（保留）；board_shell :91-299（卡片 wait div :186-187 显
  awaiting_human.reason）；detail_shell :302-524（平铺同级盒子零层级；事件流
  renderEvents :473-490 只渲 title 行 + kind badge；决策备选「（N 个备选）」
  不可交互 span :439（拒绝理由不可见）；
  wait-banner :391-396 显 reason + approve 静态文案）。
- e2e：E3c :148-168（断言事件行=4、badge 排序、kind 过滤 2/1——绑旧壳 DOM）、
  E5 :246-256（wait-banner 文案）。
- seed.py：s3 = claim+mark_blocked+update_progress（事件链 3 + 启动 reconcile 1）。
- ac_cases_g web_shell：断言壳静态、无数据嵌入（prog_secret/long_content 不进壳 HTML）
  ——新壳必须保持零数据嵌入（数据仍由 fetch 渲染）。

### 变更规格

1. **docs/web.md（先行修订，e2e 断言的契约源）**：
   - :29 事件流节改写：人面事件（events[].audience=="human"）`<details>` 提纲优先
     ——summary＝title（空/纯空白 -> 降级显 kind 标签），展开＝content + payload
     （JSON 缩进），默认收起；簿记事件（audience=="bookkeeping"）折入单一
     `<details>`「簿记 N」默认收起（N=计数，展开为平铺行）；kind 过滤 select 保留：
     选中某 kind 时按过滤结果平铺渲染（覆盖分组，负方向排除仍有效）；
     原始输出仍不默认展示（无 run_logs，展开的是写侧已蒸馏文字）。
   - board JSON 行：awaiting_human 增 summary_line（additive，request_review 设置；
     缺失时卡片/横幅降级显 reason）。
   - detail JSON 行：events[] 增 audience（additive）。
   - 冒烟 checklist 同步（E3c/E5 新断言口径 + E9/E10/E11）。
2. **web.py detail_shell**：
   - 层0 决策线（唯一「花力气」区）：wait-banner 升级——awaiting_human.summary_line
     在场显一句话（review 交接：做了什么/先看哪），否则显 reason（blocked）；
     approve 静态文案保留。needs_attention 面板保留现结构（层0 内）。
   - 层1 蒸馏：验收对照表（既有）+ 决策/风险/偏离区；决策行改 `<details>`：
     summary＝title，展开＝choice/rationale/alternatives（逐条 option +
     rejected_reason 可读列表）——修 :439 不可交互占位（现只显示「（N 个备选）」
     计数，拒绝理由不可见）。
   - 层2 次要：子任务/里程碑区下移（内容不变）。
   - **保留 load() fetch 失败分支的深链 404 友好文案**（web.md 冒烟项 4 口径
     不变，审 r1 P2-3）。
   - 事件流：按 web.md 新契约渲染（audience 分两组；JS 无分类表——只信服务端
     audience 字段）；title 为空/纯空白 -> 提纲位显 kind 标签（旧数据容忍）；
     旧 title="progress" 原样显示（不做特殊识别）。
   - 全部动态串过 `esc()`（现壳已有 esc 工具；headline/content/payload JSON
     dump 都是新 XSS 面，必须覆盖）。
   - 零数据嵌入不变：壳 HTML 仍不含任何事件/需求数据（web_shell AC 用例依赖）。
   - CSS 用 _THEME 既有 token（text/muted/faint + accent），不新增视觉语言。
3. **web.py board_shell** 卡片 wait div：summary_line 在场优先显，否则 reason。
4. **tests/e2e/smoke.spec.js**（断言跟 web.md 新契约，禁镜像实现）：
   - E3c 改写：s3 链（state_change×2 + progress_note×1 + reconcile×1）->
     人面行=1（progress_note，提纲=seed headline）、簿记组在场且计数=3、
     默认收起；kind 过滤 state_change -> 平铺 2 行；progress_note -> 1 行
     （负方向排除仍断言）。
   - E5 微调：s3 是 blocked（无 summary_line）-> 横幅显 reason + approve 文案
     （断言保持；若横幅 DOM 因 summary_line 槽位变化需改选择器，按新契约最小改）。
   - E9 新增（headline 提纲+展开+XSS）：seed s9（新需求，E9/E10 专用，不碰 s3
     计数）：progress 事件 headline 含 `<img src=x onerror=alert(1)>` + 正常
     content。断言：提纲位 esc 生效（无 IMG 元素注入，页面文本含转义形态）、
     点开 details 见 content 全文。
   - E10 新增（旧数据容忍）：s9 直 SQL 补两条旧形状事件：note title=""（空）+
     progress_note title="progress" payload.note。断言：空 title 行提纲位显 kind
     标签；旧 "progress" 行原样显 "progress"；页面不崩（深潜 200 + 其余断言绿）。
   - E11 新增（簿记折叠）：s3 簿记组标题计数=3、默认收起（closed）、展开后 3 行。
   - **E1/E7 期望值更新（审 r1 P1-1，陷阱库 3 预先声明：s9 = CLAIMED 非终态
     在板，seed 扩容＝夹具变更，期望值同步更新）**：E1 在板总数 6 -> 7；
     E7 /board?status=CLAIMED id 集合 [SEEDS.s6] -> [SEEDS.s6, SEEDS.s9]
     （已 sort，序无关）。E2 为集合自适应断言，不受影响。
   - 基线 12 -> 15。
5. **tests/e2e/seed.py**：新增 s9（REST create + claim + update_progress(headline=
   XSS 串) + 直 SQL 两条旧形状事件）；seeds.json 增 s9 id + S9 常量导出给 spec；
   预探针同步（s3 链不变，E3c/E11 计数不变）。

### 红绿

- 红（`t3-red.log`），红因两类显性区分：
  - **壳变更红**：E3c 改写版（现壳无簿记组）、E9/E10/E11（新断言对旧壳全红）。
  - **夹具变更红（seed 扩容，陷阱库 3 声明）**：E1（在板总数 6->7）、
    E7（CLAIMED 集合 +s9）——旧壳上 s9 在场即红，红因是期望值未更新，
    非壳缺陷。
  红步先确认 s9 seed 在**旧壳**上不崩（壳容忍未知事件行——现状 title-only 渲染
  天然容忍，若红步出现 s9 页面白屏，是 seed 问题先修 seed）。
  红步验收口径（15 条 spec 全集）：红集合 == {E1, E7, E3c, E9, E10, E11}
  （6 条）；绿集合 == {E2, E3a, E3b, E4a, E4b, E4c, E5, E6, E8}（9 条）——
  E5 按旧断言在红步应绿，若绿步需微调选择器则 E5 归入壳变更面。
- 绿：e2e 15/15 + 全量套件（T2 后基线）不回退 + web_shell AC 用例绿。

### 验证命令

- e2e：`TMPDIR=/home/shih/.tmp-ak-m16/distill-pipeline/tmp AK_E2E_DB=/home/shih/.tmp-ak-m16/distill-pipeline/ak-e2e.db npx playwright test`（15/15）
- 全量：`TMPDIR=... .venv/bin/python -u tests/run_ac.py`

### 任务级不修

- 看板壳（board_shell）除卡片 wait div 一句话外不动（布局/置顶/信号不动）。
- SSE 刷新机制不动（EventSource 重拉结构不变）。
- 不加新前端依赖/构建步骤（内联 JS 壳形态不变）。

### 验收与 commit

- e2e 15/15 + 全量绿。
- commit：`feat(web): 深潜页三层结构 + 事件流提纲优先 + e2e 15（R4，web.md 新契约）`

---

## T4 R2 skill 记录契约 + 正典同步

**BCD 映射**：
- R2 命名记录契约（提纲->所以呢->可选细节）+ 三行人简报 -> SKILL.md 记录纪律节
- 裁决 2 queue_full=16 -> PRD §4.3:196 笔误修正
- 裁决 4 管线原则入 PRD §0 -> §0 补段
- Premortem 1 带内外一致 -> MCP description（T1）与 SKILL.md 措辞口径核对
- 强不变量 5 现成调用可读 -> PRD §4.1 工具表同步（headline/summary_line/自描述）

**契约锚**：BCD §1 裁决 2/4、§2 What 1-4、§3 Policy 6（三处表述一致）。
**数据锚**：无（纯文档；AGENTS.md 基线数字=当轮实测值）。

### 变更规格

1. **skills/agent-kanban/SKILL.md**：
   - 记录纪律节（:27-35 现「执行+记录」）改写为命名记录契约：
     每条人面记录三段——提纲（一行人话：update_progress.headline /
     add_record.title / request_review.summary_line / mark_blocked.reason，
     服务端强制非空）-> 所以呢（对预期的影响/需要人做什么）-> 可选细节
     （content/payload，倒日志式细节不写）；报节点不报流水账。
   - 交接纪律：request_review 附三行人简报（做了什么/先看哪/还剩什么），
     summary_line 承载第一二句，evidence 三字段照旧。
   - 砍操作机制篇幅：MCP 工具语义/错误码细节由工具自描述（T1 description）
     承载，skill 只留门序/认领纪律/重试成本/等待面纪律（协议骨架）；
     错误码表保留但补 invalid_record 新触发面（缺 headline/summary_line、空 title）。
   - 措辞与 T1 的 MCP description/instructions 逐句核对一致（同批交付，防漂移）。
2. **docs/PRD.md**：
   - :8 关联节加 BCD 引用行（distill-pipeline）。
   - §0（:14-26）补管线原则段：蒸馏恰好一次在生成点（写契约强制提纲，服务端只
     校验结构）；存储/展示忠实不聪明（不二次摘要、无读侧语义挑选）；人面记录
     必带提纲。置于「报告纪律」段后（互补：报告纪律管写什么，本段管蒸馏位置）。
   - §2 :56 requirements 行 awaiting_human 形状增 summary_line（additive，
     request_review 设置，mark_blocked 不设——blocked 用 reason）。
   - §4.1 工具表：update_progress 行加「headline 必填（人面一句话提纲，缺/空 ->
     invalid_record）」；request_review 行加「summary_line 必填（交接一句话）」+
     review_request severity=attention；表头或表下加一句工具面自描述
     （description + server instructions，带内兜底，威胁模型 B）。
   - §4.1:151 get_task_detail 行：关键事件口径＝最新优先（有界 200）+ 事件自带
     提纲（生成点写），无读侧语义挑选。
   - §4.3:196：`queue_full = claim_task 计数超上限（6）` -> `（16）`（笔误修正，
     与 §6/AC8/db.py/SKILL 四源一致）。
   - §5.3（:236-240）深潜视图行：三层结构（层0 决策线：等待横幅一句话+需要关注；
     层1 蒸馏：验收对照+决策/风险/偏离，决策展开备选与拒绝理由；层2 次要：
     子任务/里程碑）；事件流提纲优先点开全文、簿记折叠；audience 单点派生
     （kind -> human/bookkeeping，未登记 kind 归人面）。
3. **AGENTS.md**（worktree 内 tracked 副本）：基线数字改当轮实测值——
   全量套件 `521/521` -> 实测（521+N1+N2）；e2e `12/12` -> `15/15`；
   最高 tier 组成行同步两个数字。**证据锚（审 r1 P2-4，防自证）**：全量数字
   以 P5 最高 tier（全量+e2e+docker 双轨）全绿跑日志为准，日志路径记 ledger，
   P6 流程审计逐字对账日志与 AGENTS.md 数字（e2e 15/15 由 T3 固定，
   仅全量数字需锚）。
4. 交叉引用核验：PRD 新 BCD 引用行路径存在；web.md（T3 已改）与 PRD §5.3
   表述一致；SKILL.md 与 MCP description 措辞一致（逐句 diff 自查）。

### 验证

- 文档复读变更节 + 交叉引用目标存在（仓适配事实：非代码资产检查清单）。
- 全量套件 + e2e 15/15 复跑（文档改动零码面，防手误）。
- 无红绿（非码任务）；gate = 全量+e2e 绿 + 主循环复读。

### 验收与 commit

- commit：`docs: skill 记录契约 + PRD 管线原则/关键事件口径/笔误修正 + 基线同步（R2）`

---

## 回滚与兼容矩阵（单向门升级审查对象）

**回滚路径**：git revert 特性分支 + `docker compose up -d --build kanban` 重部署；
零数据迁移（无 alembic、无新列、无新表、kind 集冻结）。

| 组合 | 行为 | 判定 |
|---|---|---|
| 旧数据 x 新码 | title="progress" 原样显；空 title -> kind 标签降级；旧 review_request（severity=info、无 summary_line）横幅降级显 reason；旧 state_change 无 reason（本批前阻塞原因本就不在链上，既有缺口非本批引入） | 容忍（BCD 边缘 1，E10 覆盖） |
| 旧调用 x 新码 | 缺 headline/summary_line/空 title -> invalid_record，消息带参数名+示例（agent 自纠）；工具不删不改名 | 单向门已跨，消息即迁移（BCD 失败 2 预防） |
| 新数据 x 旧码（回滚后） | payload 新键（summary_line/reason）旧码忽略；JSON 新键（audience/state_at_event/history_note）旧渲染器忽略；progress title=headline 旧展示原样渲 title（可读性不回退）；review_request severity=attention 旧摘要风险计数只数 risk kind，不回归 | 回滚安全 |
| 旧 skill x 新码 | 未加载新 skill 的 agent：MCP description/instructions 带内兜底 + 服务端结构校验兜底（错误消息带修法） | 预防链完整（Premortem 1） |

## 机械预检（T0 执行，结果记 ledger）

- P-1 BCD/plan tracked。
- P-2 锚点抽核（operations.py 三处，`git show cfa8363:...` 逐字）。
- P-3 产物清单 = 任务总览文件集（实施中新增须回报）。
- P-4 oracle 版本 pin（mcp/sqlalchemy 版本 + node/playwright 版本记 ledger）。

## 红绿纪律（全任务）

- 新行为 oracle 先红后绿（红日志落 `tN-red.log`，绿落 `tN-green.log`）。
- 回归 oracle（l_export_stable）红步冻结基线（仪器冻结，重跑规格=export-fixture.py）。
- 折入/每任务后跑最低 tier（--only 新用例）+ 每任务末跑全量；最高 tier
  （全量+e2e+docker 双轨）留 P5。
- e2e/AC 断言跟契约（BCD/web.md），禁镜像实现；裁决前的 Q1/Q2/Q3 存量分歧
  不碰（本批与三则无交集）。

## 派发提示（P3 用，非任务规格）

- 每任务独立 dispatch，串行；prompt 逐字注入陷阱库 7 条（ci-verification.md
  已知局限/已知实践登记节）+ worktree 路径 + 基 commit + 本 plan 对应任务节
  + 必读清单 + 验证命令；dispatch 原文落 `dispatches/tN-r1.md`。
- T1 调用点清单是本 plan「现状」节的逐字内容（派发时原样注入，禁 subagent
  自行 grep 重新决定改法——但允许其复核行号漂移并回报）。
- subagent 只改「变更规格」列明文件；越界改动（尤其不修清单 10 条）= 返工。
