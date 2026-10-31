# BCD b11 - 协议 conformance 判据 + payload 校验加强

版本: v3（2026-10-31，折入 plan 盲审 r1 P1/P2 + r2 P1-A/P2 项）
关联: docs/adr/0000-known-gaps.md G36 / G17① / G39 / G31 / G27(a)；docs/PRD.md §4.2 §6；skills/agent-kanban/SKILL.md「工具命名」「拆解」「决策叙事」「被拒返工」；docs/mcp-config.md §1 §3.3；docs/design.md §6
批次: b11-conformance（分支 b11-conformance，基 commit 326e13f）

## 1. 客户原话与痛点证据

原话（user 裁决，2026-10-31）：「按照建议走」——建议内容为「判据 + 加强校验：服务端补 choice 必填 + acceptance item 文本非空 -> invalid_record，协议承诺与行为对齐」。

痛点证据链（全部当轮实测，非推断）：
- E1 已知缺陷登记 G36：「协议合规无 conformance 检查：本仓有服务端 AC 套件，但没有『agent 按 SKILL 执行是否达标』的 e2e -> SKILL 与代码漂移无机器判据（本次落点事故即此类）」。
- E2 实锤漂移 G32：SKILL 租约行曾指引 agent 调 `renew`，而 MCP 14 工具无 renew（人面 CLI 独占）——文本承诺一个服务端不存在的动作，agent 照文本执行必失败。
- E3 当轮探针（真实 MCP stdio + 临时 DB）：`add_record(kind=decision, payload={"rationale":..., "alternatives":[...]})`（缺 `choice`）被接受，`choice: "   "` 也被接受；同 payload 缺 `rationale` / `alternatives` 为空 / alternatives 缺 `rejected_reason` / 无 payload 均被拒。即三要素中只有两个被校验。
- E4 生产 DB 只读统计：decision 事件 13 条，缺 `choice` 4 条（31%）。
- E5 当轮探针：`add_subtask(acceptance=[{"id":"x1"}])`（无 item 文本）被接受且落库形态逐字保留（不归一、不合成 id）；生产 DB acceptance 条目 324 条（subtasks 184 + requirements 140），dict 形态缺 item 文本 0 条，纯字符串形态 31 条，空白条目 0 条。
- E6 既有裁定张力：`sa_blankacc`（R1 复审 P2-9）刻意允许空白验收条目并将其排除出覆盖分母，理由是「若计入分母，需求永久卡在漏评，唯一出路是 abandon」。即当前设计是「允许垃圾进入 + 事后排除」，而非「拒绝垃圾进入」。
- E7 文档计数与命令漂移（当轮 grep）：docs/mcp-config.md:10「工具面 | 12 个」、:165「工具原名固定为 12 个」、docs/design.md:118「约 12 个」——注册表实测 14 项；docs/mcp-config.md:20/:66 写 `agent-kanban serve`，CLI 无该子命令（G39 已登记）。
- E8 spec of record 与协议文本不对齐：PRD.md:175 add_record 行只写「decision 必含 alternatives[] + rationale + 拒绝理由」，PRD.md:218 invalid_record 触发条件列举亦无 choice。choice 承诺只在 SKILL 成立。

## 2. Impact Mapping（目标 -> 能力）

目标 G1：协议文本（SKILL + references + docs）与服务端实际行为双向咬合，漂移有机器判据。
- C1 静态双向核对能力：SKILL「工具命名」节集合 == MCP 注册表集合（双向 + 计数）；corpus 内工具计数与注册表大小一致；corpus 内每个 `agent-kanban <cmd>` 引用可分类（子命令 / flag / 路径 / 散文），不可分类即红。
- C2 canonical 剧本走查能力：按 SKILL 门序逐步执行真实 MCP stdio + 人面 CLI，断言每步可执行且板面结果与 SKILL 描述一致。
- C3 校验加强能力：SKILL 声称的「形态钉死」在服务端确实被拒——decision 三要素齐备、acceptance 条目 item 文本非空。

目标 G2：判据自身可信（能咬住回潮，不镜像实现）。
- C4 判别力自检：注入假工具名/假子命令必红；删除真实工具名必红（防退化提取 -> 空集 -> vacuous 绿）。

## 3. Domain Event 流与隐含 Policy

| # | 事件 | 触发 | 隐含 Policy | 传播机制 |
|---|---|---|---|---|
| P1 | `add_record(kind=decision)` | payload 缺 choice/rationale/alternatives 或 alternatives 条目缺两字段之一 | 拒绝写入，零副作用，错误消息含缺失字段名（风格与既有 `decision requires rationale` 一致） | operations 校验层 -> invalid_record -> MCP/REST 回码 |
| P2 | `new_requirement` / `set_expectations` / `add_subtask` | dict 形态 acceptance 条目 item 缺失或空白 | 拒绝写入；纯字符串形态照旧归一接受；add_subtask 落库形态逐字不变（不归一） | `validate_anchor_entries` 单一事实源，三入口显式调用 |
| P3 | canonical 剧本走查 | 每次全量套件运行 | 协议门序每一步必须可执行；不可执行即红（漂移显性化）；REOPEN 直接 claim 必须 illegal_state | run_ac 注册用例 |
| P4 | 静态引用/计数核对 | 每次全量套件运行 | skill 树与 docs corpus 引用的工具名、计数、子命令必须真实存在 | p3_skill_text 同类新断言（ac_cases_s） |

既有 Policy 不变：空白验收条目排除出覆盖分母（`_acc_text`）——加强校验后新写入不再产生空白条目，该逻辑仍为存量数据兜底，不删，且其 oracle 由剧本断言 36（直插 SQL 种子）保留。

## 4. BDD Given-When-Then

- S1 Given 需求已认领 When agent 提交 decision 记录缺 `choice` Then 返回 `invalid_record`，事件计数不变。
- S2 Given 需求已认领 When agent 提交 decision 记录三要素齐备 Then 写入成功，事件 payload 含 choice/rationale/alternatives。
- S3 Given 子任务验收条目 When 提交 `{"id":"x1"}`（无 item 文本）Then 返回 `invalid_record`，零写入，子任务行不存在。
- S4 Given 子任务验收条目 When 提交纯字符串 `"验收项一"` Then 照旧接受（需求侧归一，子任务侧落库形态逐字不变）。
- S5 Given SKILL「工具命名」节 When 全量套件运行 Then 该节集合与 MCP 注册表集合相等，且「14 个工具」计数与注册表大小一致。
- S6 Given corpus 内出现 `agent-kanban serve`（不存在子命令）When 静态判据运行 Then 该判据红（判别力自检）。
- S7 Given canonical 剧本 When 按门序执行 Then 接单确认记录、子任务状态迁移与进度、decision 记录、交接评审、等待面命中、评审拒绝转 REOPEN + round=1 全部成立；REOPEN 直接 claim 被拒（`illegal_state`），人面 `reopen --continue` 回 OPEN 后重认领，再次交接 round=2。
- S8 Given 存量数据含空白验收条目（直插 SQL 种子）When 交接自评 Then 空白条目不计分母，交接成功（兜底分支不退化）。

## 5. Spec by Example 差异表

| 场景 | 现行行为（实测） | 目标行为 | 收敛方式 |
|---|---|---|---|
| decision 缺 choice | 接受（含空白 choice） | invalid_record | operations 校验补 choice 必填（S1） |
| decision 缺 rationale | 已拒 | 不变 | 无 |
| alternatives 条目缺 rejected_reason | 已拒 | 不变 | 无 |
| acceptance dict 无 item 文本 | 接受，不进分母 | 拒写 | 写入前校验；分母排除逻辑保留为存量兜底（S3/S8） |
| acceptance 纯字符串 | 接受归一（需求侧）；子任务侧原样落库 | 不变 | 无（S4） |
| SKILL 工具命名节 vs 注册表 | 单向断言（文本覆盖注册表） | 双向 + 计数 | 新增判据（S5） |
| corpus CLI 引用 | 无断言 | 引用可分类，不可分类即红 | 新增判据 + 注入反例自检（S6） |
| docs 工具计数「12 个」 | 与注册表 14 不符 | 翻正为 14 | docs/mcp-config.md:10/:165、docs/design.md:118 措辞翻正 + 判据咬住 |
| docs `agent-kanban serve` | CLI 无该子命令（G39） | 翻正为 `python -m agent_kanban.api` | 判据咬住 + 文档翻正 |
| PRD §4.2 add_record 行 / §6 invalid_record 列举 | 无 choice | 含 choice + acceptance item 文本条款 | spec of record 措辞变更（契约版本仍 3.3） |

## 6. Premortem（失败原因与缓解）

- F1 加强校验导致存量 worker 写法被拒，产生返工摩擦。缓解：错误消息含缺失字段名（`decision requires choice`，与既有风格一致）；生产 4 条缺 choice 的存量记录不迁移、不追溯。
- F2 剧本走查断言镜像实现（oracle 独立性失效）。缓解：断言逐字引自 SKILL 文本（协议 spec 为 oracle），用例头 docstring 标注场景号来源；审者按 oracle 三判据核。
- F3 静态引用提取假阴性（退化提取 -> 空集 -> 子集断言 vacuous 绿）。缓解：判据自带正反对照（注入假引用必红 + 删除真实工具名必红），分类规则逐字写进实现，匹配按 token 边界不跨行。
- F4 剧本走查与真实 agent 行为不一致（剧本不是真 agent，只测服务端可执行性）。缓解：明确边界——本判据测「SKILL prescribed 动作服务端是否可执行 + 板面结果是否符合描述」，不测 agent 自觉性；该边界写进用例 docstring 与 G36 闭合措辞，残余归 G27(a)。
- F5 基线数字四处漂移。缓解：断言数钉死 36（逐例编号），sa_blankacc 3 -> 2，基线 1055 -> 1090，四处口径同步以实跑数字。
- F6 与既有裁定 sa_blankacc 冲突未登记。缓解：差异表 §5 显式登记，sa_blankacc 断言随行为变更改写（夹具变更红预先声明）。
- F7 兜底逻辑失去唯一 oracle（原空白条目夹具被拆）。缓解：剧本断言 36 用直插 SQL 种子保留 legacy 空白条目 oracle（仓内先例 ac_cases_m.py:43 `_seed`）。
- F8 corpus 边界外（docs/adr、docs/ops、docs/plans）仍可能漂移。缓解：登记为残余，不强行纳入（改写历史验证记录＝伪造证据）。
- F9 分类规则盲区（实测确认）：flag 名漂移（写 `--force` 而 CLI 无）、JSON 数组形态命令引用（`"args": ["run", "agent-kanban", "mcp"]`）、基线数字与套件实跑数不一致——规则不咬。缓解：登记进 known-gaps corpus 边界行；基线同步仍靠 T4 人工四处核对。

## 7. 业务不变量

强不变量（违反即拒写/用例红）：
- I1 decision 事件 payload 必含非空 `choice`、非空 `rationale`、`alternatives` 非空数组且每条含 `option` + `rejected_reason`。
- I2 dict 形态 acceptance 条目必含非空 `item` 文本（纯字符串形态照旧接受）。
- I3 SKILL「工具命名」节工具集合 == MCP 注册表集合（双向），且计数一致。
- I4 corpus 内引用的 `agent-kanban <cmd>` 子命令必须存在于 CLI 子命令表。
- I5 每个新增判据必须能咬住反例（注入假引用/删除真实引用必红）。
- I6 REOPEN 上直接 claim 必 `illegal_state`（机制：claim 起点写死 OPEN + transition rowcount 守卫；ALLOWED_EDGES 表加 (REOPEN,CLAIMED) 边不改变此结果，r1 盲审实测 17/17 仍绿）。

软不变量（登记残余，不强制）：
- S1 存量数据不迁移：历史缺 choice 的 decision 事件保留。
- S2 空白验收条目排除出覆盖分母的逻辑保留（存量兜底），新写入不再产生；oracle 由 SQL 种子断言保留。
- S3 同一子任务 acceptance 的同文本重复条目不去重（G31），本批不闭合。

## 8. 范围

改：
- `src/agent_kanban/services/operations.py`（decision payload 校验补 choice；三入口 acceptance 条目校验）
- `src/agent_kanban/services/operations_util.py`（新增 `validate_anchor_entries`，与 `normalize_anchors` 分离）
- `tests/ac_cases_s.py`（新增：静态双向核对 + canonical 剧本走查 + 负例腿 + 判别力自检，36 断言）
- `tests/ac_cases_o.py`（sa_blankacc 改写为「拒写 + 零写入」2 断言）
- `tests/run_ac.py`（注册）
- `docs/PRD.md`（§4.2 add_record/add_subtask/set_expectations 行 + §6 invalid_record 列举措辞对齐；版本链仍 v3.3）
- `docs/mcp-config.md`（:10/:165 计数翻正；:20/:66 `serve` 翻正为 `python -m agent_kanban.api`）
- `docs/design.md`（§6 计数翻正 + 工具表补 new_requirement / set_expectations）
- `docs/adr/0000-known-gaps.md`（G36 闭合含覆盖边界；G17① 闭合；G39 闭合；G31 重申未闭合；新增 corpus 边界残余行）
- `AGENTS.md` + `docs/ops/ci-verification.md`（基线数字四处同步）

不改（明确边界）：
- MCP 工具集数量与名称（仍 14 工具）；状态机边；schema/alembic/迁移；租约语义；e2e 夹具（除非全量红）；`normalize_anchors` 归一逻辑；add_subtask 落库形态（不归一）；人面 CLI 子命令集合；SKILL 文本内容本身（除措辞核对，不新增承诺）；存量缺 choice 的 decision 事件。

契约版本：3.3 不变。理由：本批不新增状态、边、工具或字段语义，只使服务端校验与已发布文本一致，并把文本中未写出的校验条款补进 spec of record（先例：b3.2 服务端门未 bump）。
