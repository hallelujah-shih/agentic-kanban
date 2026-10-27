# Spec: 人确认闭环——代执行一等受托面（delegated）+ CLI 零输入

**日期**: 2026-10-27
**状态**: v2（对抗审查第 1 轮 REJECT：P1×1 / P2×5 / N×5 全部折入——R1 stdin 继承实证修正 / R2+R5 parse 位置统一 handler 层先于零输入读 / R3 配对反向收窄 6 op 写点 + add_record 例外登记 / R4 非 conform body 200->422 登记 + n17b / R6 候选列加 state；N1-N5 全折入；事实表 #7 行号勘误 :199->:201）；待第 2 轮审查（resume 原审者）
**分支/worktree**: delegated-confirm（基于 main 5089bfe，.worktree/delegated-confirm）
**BCD**: `docs/business-contracts/delegated-confirm.md`（v2.1：7 节齐；user 裁决 2026-10-27 设计全批 + PM 评审拆分 Web 待决页）
**板上任务**: bcd3a69074b641dba70a08afbce1ac05（CLAIMED，main-loop）
**关联**: PRD §4.2（人面命令）§4.3（错误码）§5.1（actor 模型）§5.2（自报声明）；ADR 0002（服务端派生 actor 先例）；`identity.py`（派生单点）；`operations.py`（写事件 6 操作 + set_expectations）；`state_machine.py`（transition event_payload）；`cli.py`（_invoke）；`api/requirements.py`（REST 人面）；`skills/agent-kanban/SKILL.md`（收尾协议落点）；known-gaps G11（cli.py 涉改）

---

## 1. 范围与非目标

**范围内**：
- 受托面（delegated）：`parse_delegation` 单点校验（`identity.py`）+ surface 服务端派生（cli `_invoke` / REST `_run` 各一行）
  + **写事件**人面操作（7 个 op 函数：approve / release / release_all_stale / renew / note /
  reopen / abandon，对应 6 条 CLI 命令）加可选 `delegated` 参数、事件 payload 落
  `payload.delegated={kind,basis}`（含 transition 的 state_change 事件，经既有 `event_payload`）。
- CLI：6 命令加 `--on-behalf "<kind>:<basis>"`；approve / release 零输入模式（`--requirement-id`
  可省，经既有 `list_awaiting` 解析）。
- REST：`DelegatedIn` 模型 + 6 端点可选 delegated 字段（approve / renew 新增可选 body，
  ReopenIn|None 先例 requirements.py:111）。
- 契约同步：PRD 四处（§4.2 两命令句 / §4.3 invalid_record 实例 / §5.1 surface 枚举+派生规则）、
  SKILL.md 收尾协议节、AGENTS.md 人面 CLI 行。
- 测试：AC 新增（ac_cases_n.py）；e2e 无新增（既有 15 回归）。

**非目标**：
- **Web 面零改动**（待决页推迟至 G3 后，BCD v2 / pm-review 裁决 2）。
- **MCP 面零改动**（12 工具无受托参数入口，agent 自身动作恒 surface=mcp，结构性门禁）。
- **零 schema 变更**（无新表/列/索引；payload 为既有 JSON 列）。
- **set_expectations 无受托入口**（D1 细化，见下）：该操作**不写事件**（operations.py:115 仅置
  `req.acceptance` + `updated_at`），受托标记（BCD Q3「落在事件自身」）无载体——人亲手执行同样
  事件不可见（存量事实）。按「不可能性即门禁」同类处理：CLI 不加 flag、REST body 无字段。
  Q2 委托范围按**写事件的 6 个人面操作（7 个 op 函数）**实现，set_expectations 结构性
  排除——审计模型（事件承载受托痕）的结构性推论，非范围扩大。
- 服务端事件检测 / webhook（YAGNI，BCD 软约束 3）；basis 机器验证（BCD 软约束 1）。
- 展示渲染改动：delegated 可见面＝**既有通用渲染**透传（view detail 事件行
  `by delegated:cli`，view.py:616/700 已是 `by {surface}:{conn}` 通用格式；export/REST JSON
  事件行；SSE 触发帧 actor_surface 字段）——零代码改动。完整「代执行（依据：…）」措辞渲染随
  G3 后 Web 待决页统一（BCD 软约束 2）。

---

## 2. 设计 A：受托面（单点校验 + 派生 + payload 传播）

### 2.1 parse_delegation（identity.py 新增，唯一校验点）

```python
DELEGATION_KINDS = ("statement", "action")
DELEGATION_EXAMPLE = "statement:user said PR merged in session"

def parse_delegation(raw: str | dict | None) -> dict | None:
    """受托参数单点校验。CLI 传 raw string（"kind:basis"），REST 传 dict（{kind,basis}）。
    None -> None（无受托参数）。结构非法 -> BusinessError(invalid_record)，
    消息含参数名 + 正确示例（DELEGATION_EXAMPLE）。"""
```

校验规则（str / dict 两路同一函数）：
- `None` -> `None`（无参，现行为）。
- **str**：按**首个** `:` `partition`；无冒号 -> 格式非法。`kind = 左段.strip().lower()`，
  必须 ∈ {statement, action}；`basis = 右段.strip()`，必须非空。basis 可含冒号
  （`"statement:a:b"` -> basis=`"a:b"`）。
- **dict**：取 `kind` / `basis` 键（缺失或非 str -> 非法）；strip + lower 后同枚举/非空校验。
- 返回 `{"kind": <规范化 kind>, "basis": <strip 后 basis>}`。

错误消息（`delegated` 为参数名，括注 CLI flag 供两面自纠）：
- 格式：`invalid_record: delegated (CLI --on-behalf) must be "kind:basis" (kind in statement|action), e.g. "statement:user said PR merged in session"`
- kind 越枚举：`invalid_record: delegated kind must be statement|action, got "<raw>", e.g. "..."`
- basis 空：`invalid_record: delegated basis must be non-empty, e.g. "..."`

### 2.2 surface 派生（服务端单点，PRD §5.1 / ADR 0002 先例延续）

- `cli.py _invoke`：加 `delegated: dict | None = None` 参数（**已 parse 的 dict**，handler 层
  先行，与 REST `_run` 同构）；`delegated is not None` 时 `surface = "delegated"` 且
  `kwargs["delegated"] = delegated`（无参时 kwargs 不含该键 -> op 调用逐字不变）。
- `api/requirements.py _run`：加 `delegated: dict | None = None` 参数；非 None 时
  `surface = "delegated"` 并透传 `delegated=delegated` 给 op。
- **parse 统一在 handler 层（`_cmd_*` / 端点函数首语句），先于任何 DB 操作**（fail-fast，
  与 release reason 同纪律；否则 0 待决板会静默吞非法 flag——v1 审查 R5）：
  CLI handler 调 `parse_delegation(args.on_behalf)`，非法 -> stderr `invalid_record: <msg>`
  + `return 1`（与 `_invoke` 既有 except 同输出形态，**无 traceback**——对齐 k 用例
  「Traceback not in stderr」CLI 错误面契约）；REST 端点调
  `parse_delegation(body.model_dump() if body else None)`（approve/renew
  body 整体即 DelegatedIn）/ `parse_delegation(body.delegated.model_dump() if
  body.delegated else None)`（release/note/abandon/reopen 嵌套字段，§4 两形态分写），
  非法 -> 抛 BusinessError -> 既有映射 422。
- **surface 值与 delegated 参数同一调用点同批落值**（`_invoke` / `_run` 收已 parse 的
  dict）——配对不变量的结构耦合点。
- MCP 面：`server.py` 零改动，工具包装器不传 `delegated` -> 恒 None -> surface 恒 mcp。
  system 面（retry_limit marker / reconcile）不经 cli/rest 派生层，不受影响。

### 2.3 payload 传播（6 操作，零新机制）

6 个操作签名各加 `delegated: dict | None = None`（尾部 keyword，默认 None）。写事件处：
- **transition 路径**（approve / release / release_all_stale / reopen / abandon）：
  `transition(..., event_payload={"delegated": delegated} if delegated else None)`——
  transition 既有 `event_payload` 参数合并进 state_change 事件 payload（state_machine.py:69-71）。
- **add_event 路径**：payload 字典就地加键——
  - approve（CLAIMED 分支）：`payload={"state": "DONE", **({"delegated": delegated} if delegated else {})}`
  - release / release_all_stale：`payload={"reason": ..., "agent_name": ..., "delegated"?}`
  - renew：现无 payload -> `payload={"delegated": delegated} if delegated else None`
  - note：`payload={"content": content, "delegated"?}`
- `add_event` / `transition` **签名零改动**（checkpoint 曾议 add_event 加参，实现层取
  操作级 merge：触点更少，且配对仍由 2.2 的单点派生保证）。

**配对不变量**（BCD 强 3，v2 审查 R3 收窄）：
- **正向（系统级，结构性成立）**：凡 surface=delegated 的事件必带有效 `payload.delegated`
  （surface=delegated 只能由 cli/rest 派生层置出，其可达的 6 个 op 写点全部落标；
  如 approve CLAIMED 分支 state_change + approval 两条均带）。
- **反向（限定 6 op 独占写出的 kind）**：kind ∈ {approval, release, renew} +
  6 op 触发的 state_change 行，`payload` 含 delegated 键 ⟺ surface=delegated（无参时
  键不出现；agent 面 transition 不传 delegated，state_change 反向仍结构成立）。
  **kind=note 不在此限定**：人面 `note` op 与 MCP `add_record` 共写 kind=note，仅凭
  kind 不可区分写者（note 配对由 n3 直测覆盖）。
- **例外登记**：MCP `add_record` 的 payload 为自由 JSON（agent 自报内容，PRD §5.2 同
  边界），可含同名 `delegated` 键（如记录某次委托讨论）-> surface=mcp + payload 含
  delegated 真实存在，不在反向保证范围。**审计检索代执行面的主键＝`actor_surface=
  delegated`，`payload.delegated` 为佐证**（不得以 payload 键为唯一检索条件）。

---

## 3. 设计 B：CLI --on-behalf + 零输入

### 3.1 --on-behalf（argparse）

6 命令（approve / release / renew / note / abandon / reopen）各加：
`p.add_argument("--on-behalf", metavar='"kind:basis"', help="受托代执行（kind: statement|action，basis 一行指向依据）")`。
set_expectations / archive / delete / new / export / view **不加**（结构性缺席：
`cli.py delete --on-behalf x` -> argparse `unrecognized arguments` exit 2）。

### 3.2 零输入（仅 approve / release）

`approve` 的 `--requirement-id` 由 `required=True`（cli.py:280）改可选；release 现已可选
（cli.py:284）。`--requirement-id` 缺省**且**非 `--all-stale` 时进入零输入解析：

0. **parse 先于读候选**（§2.2）：`--on-behalf` 结构校验在 handler 首语句完成，非法直接
   拒（零待决板不吞非法 flag——v1 审查 R5）。
1. 读候选：`run_op(get_session_factory(), ops.list_awaiting, is_write=False, actor_surface,
   actor_conn)`（operations.py:936，既有读路径；外层 `{"awaiting": [...]}` 包装，条目含
   `requirement_id`（32-hex 归一）/ `title` / `state` / `awaiting_human` / `waiting_seconds`
   / `claim`，updated_at 序）。
2. 分支（**宁拒不猜**，BCD 强 5）：
   - **0 条**：stdout `无待决项`，exit 0，零写。
   - **恰 1 条**：携该 32-hex 走既有写路径（与显式 `--requirement-id` 等价，A1 归一路径不变）。
   - **多条 + 非 tty**（`sys.stdin.isatty()` 为 False，含管道/脚本）：stderr 输出
     ```
     多条待决项，请用 --requirement-id 指定目标:
       1. <8hex> [CLAIMED] <title>
       2. <8hex> [BLOCKED] <title>
     ```
     exit 1，零写。
   - **多条 + tty**：stdout 同格式编号列表 + 提示 `输入序号: `；读一行，`int` 且在
     [1, N] 内 -> 执行对应项；非数字 / 越界 / EOF -> stderr `无效选择，未写入` exit 1 零写。
     （此分支 AC 不可测＝不引 pty 注入——harness stdin 只能钉非 tty，见 §9 残余 1；
     非 tty 分支由 n21 显式钉 stdin=DEVNULL 保证确定性。）
   - **行格式含 state**（`[CLAIMED]` / `[BLOCKED]`，取自 list_awaiting 返回 `state` 字段，
     零成本）：BLOCKED 候选被 approve 是解阻而非 DONE（见语义注 5），列表必须给人
     区分信息（v1 审查 R6）。
3. **release 例外**：零输入仍须 `--reason`（语义字段不免输）。检查在 DB 读取**之前**
   fail-fast：无 `--reason` 或空白 -> stderr `invalid_record: release requires a reason`
   exit 1，零写、不触碰 DB（与 op 层既有同文案错误码一致，operations.py:203-205）。
4. **可与 --on-behalf 组合**（agent 主流程）：`cli.py approve --on-behalf
   "statement:user 会话表态收尾"`（零输入 + 受托，agent 依 user 表态代执行）。
5. 语义注：零输入候选＝awaiting_human 标记任务（板唯一等待面）；approve 按**当前状态**
   判定（PRD §3.4）——BLOCKED+awaiting 的候选被零输入 approve 将解阻（->CLAIMED），
   与显式 id 调用一致，无特殊处理。

---

## 4. 设计 C：REST delegated

`api/requirements.py`：

```python
class DelegatedIn(BaseModel):
    kind: str
    basis: str
```

- `approve`（:85，现无 body）/ `renew`（:96，现无 body）：签名加 `body: DelegatedIn | None = None`
  （`ReopenIn | None` 先例 :111）。**body 整体即 DelegatedIn（顶层 `kind` / `basis`，无
  `{"delegated": ...}` wrapper）**——body 存在即代表受托意图，wrapper 无信息量。
- `ReleaseIn` / `NoteIn` / `AbandonIn` / `ReopenIn`：各加可选字段
  `delegated: DelegatedIn | None = None`（release :91 / note :101 / abandon :106 / reopen :111）。
- `set_expectations` / `archive` / `delete`：body 模型**无** delegated 字段（结构性缺席；
  FastAPI 对无 body 参数的端点忽略请求体——POST /archive 携 delegated 体 -> 200 且
  surface=cli、无 payload.delegated，AC n18 断言）。
- 端点 handler：`delegated = parse_delegation(body...model_dump()...)` 后传入 `_run(...,
  delegated=delegated)`；pydantic 保证字段类型（str），枚举/非空校验收敛在 `parse_delegation`
  单点。非法 -> `invalid_record` -> 422（REST_ERROR_STATUS 既有映射，零新增）。
- conn：delegated 面沿用 `rest:<8hex>`（rest_actor 不变——conn 是连接身份，surface 才是
  派生值）。

---

## 5. 行为兼容矩阵（回归锚）

| 路径 | 现行为 | 变更后 |
|---|---|---|
| CLI 6 命令：显式 `--requirement-id`、无 `--on-behalf` | surface=cli，payload 无 delegated | **逐字不变**（on_behalf=None -> parse None -> kwargs 无 delegated 键） |
| CLI set_expectations / new / archive / delete / export / view / reconcile / prune | 无 --on-behalf | **零改动**（不带新 flag；携 flag -> argparse exit 2） |
| CLI `release --all-stale`（无 --on-behalf） | 逐项释放，payload={reason:"stale",agent_name} | **逐字不变** |
| REST 各端点：无 body / 既有 body | surface=cli，无 payload.delegated | **逐字不变**（可选字段默认 None） |
| REST `POST /approve`、`POST /renew` 无 body | 200（现无 body 参数） | **逐字不变**（`X \| None = None` 先例） |
| REST `POST /approve`、`POST /renew` 携任何 present 的非 conform body（`{"foo":1}` / 空对象 `{}`） | 200（body 被忽略） | **422**（body 参数化后 pydantic 校验）——已知行为变化，仓内无受害方（核毕）；n17b 钉 |
| REST archive / delete 携 delegated 体 | 200（体被忽略） | 不变（仍忽略）：surface=cli、无 payload.delegated（n18） |
| MCP 12 工具 | surface=mcp | **零改动**——12 工具本就不调 6 个人面写 op（server.py:205-218 工具清单：agent 面 op），结构性零触达 |
| system 面（retry_limit / reconcile 事件） | actor_surface=system | 不受派生层影响（不经 cli/rest 路径） |
| view / export / SSE | 事件行 `by {surface}:{conn}`（view.py:616/700 通用渲染） | **零代码改动**，delegated 值透传可见 |
| e2e 15 用例 | 15/15 | **零改动**，全回归 |
| 全量 AC | 624/624 | 无回退（新用例 additive） |

---

## 6. 契约同步面（逐文件）

1. **docs/PRD.md §4.2** approve 句（:175）：追加——`--on-behalf "<kind>:<basis>"` 受托代执行；
   零输入（无 --requirement-id）：awaiting_human 恰 1 条直接执行 / 0 条提示零写 / 多条非交互
   通道拒绝（tty 编号列选）。
2. **docs/PRD.md §4.2** release 句（:176）：同上（`release_reason` 必填，零输入不免输）。
3. **docs/PRD.md §4.3**（:201）invalid_record 实例清单 additive：「delegated 结构非法
   （kind 越 statement|action 枚举 / basis 空 / 字符串形缺冒号）」。「每码唯一触发条件」
   纪律保持：invalid_record＝记录结构字段缺失/非法，实例清单只增。
4. **docs/PRD.md §5.1**（:217）：枚举句 `actor_surface`（`mcp`/`cli`/`system`）->
   （`mcp`/`cli`/`system`/`delegated`）；派生规则句追加：「`delegated`＝人面上代执行：
   人面入口（CLI/REST）+ 结构有效受托参数（kind ∈ statement|action、basis 非空）->
   服务端派生落此值，且该命令写出的每条事件必带 `payload.delegated={kind,basis}`（单点派生，
   配对）；delegated 的源必须是已发生的人的决定（statement＝人会话表态 / action＝人工作面
   动作中 agent 结构性做不了的），agent 只翻译不产生。MCP 面无受托参数入口，恒 mcp。」
5. **skills/agent-kanban/SKILL.md**（本仓 tracked，skills/agent-kanban/ 非独立 git 仓）：
   「交接与等待」（:45）后新增「收尾协议（代执行）」节——
   - **触发（pull）**：agent 侧工作完成后（PR 流＝PR 发起后 / 本地合流＝合入后），人表态
     （「合了」「收尾吧」）或 agent 检测到人工作面动作完成 -> 会话内 `list_awaiting` 查
     等待面，有待决任务即代执行收尾。
   - **kind 判据**：`statement`＝人会话表态（basis 指向可引用的真实原话）；`action`＝人
     工作面动作且 agent 结构性做不了（如远端 PR merge：git fetch 后确认目标 commit 在
     origin main）。**本地仓检测不算**——本地 ff 折入 / 分支合并是 agent 自己的动作，
     标 action 即自我认证（显式反例）。
   - **执行**：`cli.py approve --requirement-id <id> --on-behalf "<kind>:<basis>"`
     （release 同，携 `--reason`）。受托痕在事件自身（payload.delegated），**不再要求前置
     note**。
   - **禁**：agent 自产决定（编造 statement basis / 把自己动作标 action）。终态/确认迁移
     的源必须是已发生的人的决定。
6. **AGENTS.md**「任务与看板操作面」人面 CLI 行：补零输入 + `--on-behalf` 一句
   （approve/release 可省 --requirement-id；agent 代执行携 `--on-behalf "<kind>:<basis>"`，
   判据见 SKILL.md 收尾协议）；另顺手修「验证入口与 tier 阶梯」基线 **592/592 -> 624/624**
   （批 2 合入后未同步的存量漂移，v1 审查 N4；最高 tier 行同数同步）。
7. **src/agent_kanban/models.py:136** 行尾注释：`# mcp | cli | system` ->
   `# mcp | cli | system | delegated`（v1 审查 N1；注释是 surface 枚举唯一代码内清单）。
8. **docs/design.md**：核毕**无需同步**（:30 表结构含 actor_surface 列，零 schema 变更；
   无 surface 枚举清单）。

---

## 7. 测试策略（AC 用例，先红后绿，新文件 tests/ac_cases_n.py）

harness 事实（v1 审查 R1 实证修正）：`cli()`（ac_lib.py:51-56）走真实 subprocess 但**未
传 `stdin=` -> 继承父进程**——CI（非 tty）下非 tty；**本地终端下子进程 stdin 是 tty**，
多条待决走 tty 分支阻塞 readline，30s 超时 FAIL。故零输入用例（n19-n24）用
**case-local helper 钉 `stdin=subprocess.DEVNULL`**（`ac_cases_k.py:37-44 _run_cli`
同模式——delete/prune 确认门用例已用此模式注入 stdin）；不改共享 ac_lib（改动面控制）。
`REST` 走真实 uvicorn 子进程 + urllib；`MCP` 走真实 stdio 子进程；oracle＝sqlite 直查。

**D1 受托面（CLI 派生/校验/payload/配对）**
| id | 前置 | 操作 | 断言（oracle） |
|---|---|---|---|
| n1 | CLAIMED+awaiting | `approve --on-behalf "statement:测试表态"` | exit 0，DONE；sqlite：approval 事件与 state_change 事件**均** actor_surface=delegated、actor_conn=cli、payload.delegated={kind:statement,basis:测试表态}；approval payload.state=DONE |
| n2 | CLAIMED（有 claim） | `release --reason "x" --on-behalf "action:PR merged (abc123)"` | OPEN；release 事件 + state_change 事件均 delegated（kind=action）；release_reason=x |
| n3 | CLAIMED | `note --on-behalf ...` / `renew --on-behalf ...` | note 事件 payload.content + payload.delegated；renew 事件 payload.delegated；surface=delegated |
| n4 | DONE | `reopen --on-behalf ...`；再 `abandon --to-state REJECTED --on-behalf ...` | 两条 state_change 事件均 delegated（DONE->REOPEN / ->REJECTED） |
| n5 | 2 个 STALE CLAIMED | `release --all-stale --on-behalf ...` | 每个 ok=True 项的 release 事件 delegated；部分失败语义不变 |
| n6 | 0/1/2 awaiting 三形态各跑 | `approve --on-behalf "foo"`（无冒号） | 三形态均：stderr invalid_record + 示例、**stderr 无 Traceback**；事件计数不变（零写）；exit 1（parse 先于读候选，R5） |
| n7 | 同 n6 | `--on-behalf "badkind:x"` | 三形态均 invalid_record；零写；无 Traceback |
| n8 | 同 n6 | `--on-behalf "statement:"`（basis 空） | 三形态均 invalid_record；零写；无 Traceback |
| n9 | CLAIMED | `approve --requirement-id <id>`（无 on-behalf） | surface=cli；approval payload **无** delegated 键（回归） |
| n10 | 任意 | MCP 直调 rpc `tools/list`（ac_lib `list_tools` 辅助仅回 name，schema 断言需走原始 rpc）+ 调一个写事件工具 | 12 工具 inputSchema 无 on_behalf/delegated 字段；写出事件 surface=mcp、无 payload.delegated（结构性门禁） |
| n11 | 混合写（n1 式 + n9 式 + mcp 写） | sqlite 全表扫 events | **正向（全表）**：actor_surface=delegated 的行必含有效 payload.delegated（kind ∈ {statement,action} + basis 非空）；**反向（限定独占 kind）**：kind ∈ {approval,release,renew,state_change} 的行，payload 含 delegated 键 ⟺ surface=delegated。kind=note 共享（人面 note / add_record）与 add_record 自由 payload 的其余 kind（decision/risk/deviation/decomposition）不在反向范围（§2.3 例外登记）；note 配对由 n3 直测 |

**D2 REST**
| id | 操作 | 断言 |
|---|---|---|
| n12 | `POST /approve` body `{"kind":"statement","basis":"user 会话原话"}`（顶层形态，§4） | 200；事件 surface=delegated、conn 前缀 rest:；payload.delegated 落值 |
| n13 | `POST /approve` 无 body | 200；surface=cli；无 payload.delegated（回归） |
| n14 | `POST /release` body `{reason, delegated}` | release 事件 delegated |
| n15 | `POST /note` body `{content, delegated}` | note 事件 delegated |
| n16 | `POST /reopen` body `{delegated}` | 200；state_change delegated |
| n17 | `POST /approve` body `{"kind":"foo","basis":"x"}`（顶层形态，kind 越枚举） | 422 invalid_record；零写 |
| n17b | `POST /approve` body `{"foo":1}`（present 非 conform body，R4；`{}` 同路径不另立用例） | 422；零写（兼容矩阵登记的行为变化锚） |
| n18 | `POST /archive` body `{"delegated":{...}}`（结构门禁） | 200 ARCHIVED；state_change 事件 surface=**cli**、payload **无** delegated |

**D3 CLI 零输入**
| id | 前置 | 操作 | 断言 |
|---|---|---|---|
| n19 | 0 awaiting | `approve` | exit 0；stdout 含「无待决项」；零写 |
| n20 | 恰 1 awaiting | `approve` | exit 0，DONE；事件 surface=cli（无 on-behalf）；等价显式 id |
| n21 | 2 awaiting（1 CLAIMED + 1 BLOCKED，不同 title） | `approve`（case-local helper，stdin=DEVNULL 钉死，R1） | exit 1；stderr 含两条「<8hex> [CLAIMED] <title>」/「<8hex> [BLOCKED] <title>」（行含 state，R6）+「--requirement-id」；无 Traceback；零写 |
| n22 | 1 awaiting（有 claim） | `release`（无 --reason） | exit 1；stderr `invalid_record: release requires a reason`；零写、DB 未触碰（事件计数不变） |
| n23 | 1 awaiting（有 claim） | `release --reason "方向不对"` | OPEN；release 事件 |
| n24 | 1 awaiting | `approve --on-behalf "statement:user 表态收尾"`（组合＝agent 主流程） | DONE；delegated 事件 |
| n25 | 2 awaiting（tty） | 编号选择 / 越界拒绝 | **AC 测不到**（见 §9 残余 1 人工核验规格） |
| n26 | n1 式写后 | `view detail --requirement-id` | 事件行含 `by delegated:cli`（既有通用渲染透传） |
| n27 | n1 式写后 | `export --format json` | 事件行 actor_surface=delegated + payload.delegated |
| n28 | 任意 | `delete --on-behalf x` | exit 2；stderr `unrecognized arguments`（CLI 结构门禁） |

e2e：无新增（Web 面零改动），既有 15/15 全回归。基线 624/624 无回退。

---

## 8. 不变量映射（BCD §7 -> 验收锚）

| BCD 不变量 | 验收锚 |
|---|---|
| 强 1 L0 人决定源（协议+审计面执行，非机器强制） | 协议层＝SKILL.md 收尾协议节（kind 判据 + 本地仓反例 + 禁自产决定，文档静态检查）；审计面＝n1/n2（delegated+basis 直读）；MCP 门禁＝n10；机器强制缺失＝威胁模型 C 系统上限（§9 残余 2） |
| 强 2 不可能性即门禁 | n10（MCP 无参数）/ n18（REST archive 无字段）/ n28（CLI delete 无 flag）/ set_expectations 同 n28 机制（argparse 结构缺席） |
| 强 3 受托面与 payload 配对 | n11（正向全表 ⟹ + 反向限定独占 kind ⟺，R3 收窄；审计主键 actor_surface=delegated）+ n1-n5 逐事件配对断言 |
| 强 4 单向门纯 additive | n9 / n13（无参回归）+ 全量 624/624 无回退 + e2e 15/15 |
| 强 5 零输入宁拒不猜 | n19（0 条）/ n20（恰 1）/ n21（多条非 tty）/ n22（reason 不免输）/ n25（tty 越界，人工） |

---

## 9. 残余与已知局限

1. **tty 交互分支无 AC 覆盖**（零输入用例 case-local helper 钉 stdin=DEVNULL 保非 tty
   确定性——R1 修正后本地终端跑套件不再阻塞；pty 注入不引，共享 ac_lib 改动面超出本批
   档位）。P5 人工核验规格：临时 DB 造 2 条 awaiting 任务，真终端跑 `cli.py approve`：
   (a) 输入非数字 `abc` -> 预期 stderr 拒绝零写；(b) 输入越界序号 99 -> 预期拒绝零写；
   (c) 再跑一次输入 1 -> 预期执行第 1 条。核验记录入批次 ledger。
2. **basis 声明级**：不机器验证（BCD 软约束 1；与 reported by 自报声明同边界，PRD §5.2）。
   L0 的机器强制缺失是威胁模型 C（单主机不可机辨人/agent 跑 CLI）的系统上限，残余由人
   回溯（reopen + note）吸收。
3. **set_expectations 事件不可见**（存量：人亲手同样无事件）-> 受托入口结构性缺席（§1 非目标
   D1）。预期锚变更若要可审计，需新增事件 kind，属独立演进（单独评审）。
4. **delegated 可见面**＝既有通用渲染透传（view detail `by delegated:cli` / export JSON /
   REST JSON / SSE 触发帧）；完整「代执行（依据：…）」措辞渲染随 G3 后 Web 待决页统一
   （BCD 软约束 2）。
5. **G11**：本批动 cli.py -> 合入后 `uv sync --reinstall-package agent-kanban` 刷新入口快照。

---

## 修订记录

- 2026-10-27 创建（主循环）。来源：BCD v2.1（user 全批四决策点 + PM 评审拆分 Web 待决页）+
  代码取证（identity.py 派生单点 / operations.py 写事件操作路径——set_expectations 无事件
  -> D1 / state_machine.py transition event_payload 合并 / cli.py _invoke + argparse /
  requirements.py 端点 + ReopenIn|None 先例 / view.py:616/700 通用渲染 / list_awaiting
  operations.py:936 / ac_lib 三面 harness 形态 / PRD §4.2:175-176 §4.3:199 §5.1:217 /
  design.md 无 surface 枚举 / SKILL.md 本仓 tracked / AGENTS.md 人面 CLI 行）。
  设计决策：parse_delegation 单点（str/dict 两路同函数）；操作级 payload merge（add_event /
  transition 签名零改动）；零输入经 list_awaiting 客户端编排（服务端零新接口）；release 零
  输入 reason fail-fast 于 DB 读取前。
- 2026-10-27 v2（对抗审查第 1 轮 REJECT：P1×1 / P2×5 / N×5，主循环逐条独立核验成立，
  全部折入）：
  - R1(P1)：「harness subprocess stdin 恒非 tty」为错误事实——`ac_lib.cli()` 未传 stdin=
    继承父进程，本地终端跑合并门槛套件时多条待决走 tty 分支阻塞。修：零输入用例
    case-local helper 钉 stdin=DEVNULL（ac_cases_k.py:37-44 _run_cli 同模式，不改共享
    ac_lib）；§7 harness 事实与 §9 残余 1 重写；n21 显式钉 DEVNULL。
  - R2(P2)+R5(P2)：parse 位置自相矛盾（_invoke try 内 vs handler 前）+ 0 待决板静默吞
    非法 flag。修：parse 统一 handler 首语句（fail-fast 先于任何 DB 操作），`_invoke` /
    `_run` 收已 parse 的 dict（两面同构）；无 traceback 对齐 k 用例 CLI 错误面契约；
    n6-n8 前置收紧为 0/1/2 待决三形态 + 无 Traceback 断言。
  - R3(P2)：配对不变量反向过claim（MCP add_record 自由 payload 可产 surface=mcp +
    payload.delegated）。修：正向＝系统级结构保证；反向限定 6 op 独占 kind
    {approval,release,renew,state_change}（kind=note 人面/agent 共写，不在限定内，
    n3 直测）；例外登记 + 审计主键＝actor_surface=delegated；n11 同收窄。
  - R4(P2)：approve/renew 加 body 后任意非 conform 非空 body 200->422（仓内无受害方，
    核毕）。修：兼容矩阵登记已知行为变化 + n17b（body {"foo":1} -> 422 零写）。
  - R6(P2)：零输入候选列表缺 state 显示（BLOCKED 误操作向量）。修：行格式
    `<8hex> [STATE] <title>`（list_awaiting 已返回 state，零成本）；n21 断言含 state；
    BCD 边缘场景同改。
  - N1-N5：models.py:136 行尾注释加 delegated（§6.7）；AGENTS.md 基线 592/592->624/624
    顺手修（§6.6，批 2 合入后存量漂移）；兼容矩阵 MCP 行理由改结构性零触达（server.py
    12 工具不调 6 人面 op）；人工核验规格补非数字输入步（§9 残余 1）；§4 body 顶层
    形态钉死（n12/n17 同改，无 wrapper）。
  - 事实表 #7 行号勘误：PRD invalid_record 实例清单在 :201（:199 是码枚举行）。
  - 主循环自查（审者未及）：n12/n17 body wrapper 与 §4 顶层 DelegatedIn 签名矛盾，
    统一为顶层 kind/basis。
- 2026-10-27 v2.1（第 2 轮续审 APPROVE-WITH-FIXES 折入，N6/N7 注记级）：§2.2 REST
  parse 表达式按 §4 两形态分写（approve/renew `body.model_dump()` vs 嵌套端点
  `body.delegated.model_dump()`）；§5 矩阵行「非空 body」改「任何 present 的非
  conform body（含空对象 {}）」，n17b 措辞同步（`{}` 同路径不另立用例）。BCD 侧
  R3 残留（§7 强 3 裸 iff）于 BCD 续条闭合。
