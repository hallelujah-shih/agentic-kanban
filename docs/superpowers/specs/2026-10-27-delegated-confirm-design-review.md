# 审查报告：delegated 受托面 + CLI 零输入 spec（对抗审查）

**审查者**: 独立 subagent（fresh context，未参与设计/BCD 起草）
**日期**: 2026-10-27
**对象**: `docs/superpowers/specs/2026-10-27-delegated-confirm-design.md`（v1，worktree
delegated-confirm @ 7f3f8a7，基于 main 5089bfe）；前置 BCD
`docs/business-contracts/delegated-confirm.md`（v2.1，7 节齐，按对照表过审：§1 解读互斥成立、
§2 Who/How 覆盖、§3 Policy 9 条均有实现面、§4 场景与代码一致、§5 差异表冲突性质成立、
§6 六个失败原因可推出具体序列、§7 强/软分类有业务后果支撑——形式与实质均齐，不退回分诊）
**方法**: adversarial-review 设计路径（线面主轴 + 四层对抗审查：证伪/反例/边界/契约漂移），
全部行号与代码事实于 worktree 内逐一核验；AC 套件全量实跑一次（624/624）；
stdin 继承语义以 pty 实验实证。
**裁决边界尊重**: Web 待决页移出 / MCP 面零改动 / 零 schema / 错误码零新增均为 user 裁决，
本审查只核执行一致性，不开新需求。

## 终判（速览）

**verdict: REJECT**（P1 存在 = 不得 APPROVE；修复合入后按纪律 resume 本审查者续审）

- P1: 1（R1：n21 依赖的「harness stdin 恒非 tty」为错误事实，本地终端跑合并门槛套件必然挂起/红）
- P2: 5（R2 parse 位置自相矛盾；R3 配对不变量反向过claim；R4 approve/renew 新 body 校验未登记；
  R5 零输入与 --on-behalf 校验次序未钉，默认实现静默吞非法 flag；R6 tty 编号列缺状态显示）
- N: 5（见文末 N 节）

线（根因层）：方案落在根因——受托痕从散落两事件收进事件自身、id 誊抄从交互面根除，
非症状层绕行。面（波及面）：消费方/部署/失败邻座/退役/既有约束五格均有交代（G11 刷新、
零 schema、兼容矩阵、残余登记齐）。主要缺口集中在测试设计与文档断言精度，不在方向。

---

## 逐条发现

### R1【P1】n21 的「非 tty 拒绝」断言依赖错误 harness 事实；本地终端跑合并门槛套件必然挂起失败

**位置**: spec §7「harness 事实」（L228-229）「`cli()` 走真实 subprocess（stdin 恒非
tty）」；§7 n21（L262）；§3.2 分支 4 注（L134「此分支 AC 测不到——harness subprocess
stdin 恒非 tty」）；§9 残余 1（L289-290 同口径）。

**证伪过程**:
1. `tests/ac_lib.py:51-56` `cli()` 实现：`subprocess.run([VENV_PY, CLI, *args],
   capture_output=True, text=True, env=..., cwd=..., timeout=TIMEOUT)`——**未传 `stdin=`
   参数**。Python subprocess 语义：stdin=None（缺省）= 继承父进程 stdin。`capture_output`
   只重定向 stdout/stderr，不影响 stdin。
2. pty 实验实证（本审查执行，/tmp/opencode 下 pty.fork 起真实 tty 父进程，再
   `subprocess.run` 起孙进程查 `sys.stdin.isatty()`）：输出 `grandchild isatty: True`。
   即：人在终端跑 `python tests/run_ac.py` 时，任何经 `ac_lib.cli()` 起的 CLI 子进程
   stdin 都是 tty。「stdin 恒非 tty」仅在 CI（非 tty 环境）成立，作为 harness 事实不成立。
3. 失败序列（n21 按 spec 实现后，人本地跑 tier 2 全量套件——合并门槛 tier 5 的组成件）：
   - 测试种 2 条 awaiting，调 `cli(db, "approve")`（零输入）；
   - 新 CLI 代码走零输入解析：list_awaiting 得 2 条 -> 多条分支 -> `sys.stdin.isatty()`
     为 True（继承自开发者终端）-> 进入 **tty 交互分支**，打印编号列 + `输入序号: `
     （被 capture 吞掉，开发者看不见）后阻塞在 `sys.stdin.readline()` 读开发者终端；
   - 30s 后 `subprocess.run` 抛 `TimeoutExpired` -> run_ac 捕获记 FAIL -> 套件 exit 1。
   - 次生更差形态：开发者此时恰好往终端敲了 `1`（误以为有交互提示）-> CLI 真执行
     approve -> 断言（exit 1 + stderr 含拒绝文案）失败，且结果不确定。
   - 同一错误事实还使 §9 残余 1 的论证失效方向相反：spec 认为 tty 分支「AC 测不到」，
     实际本地终端下 tty 分支**可达**（且不可控），非 tty 分支反而**无保证**。

**建议修正**（三处联动）:
1. `ac_lib.cli()` 增加可选 `stdin=None` 透传参数（向后兼容）；n21（及一切零输入多条
   用例）显式 `stdin=subprocess.DEVNULL` 钉死非 tty。可顺手给 n19/n20/n22/n24 同钉
   （其分支不读 stdin，钉了零成本，杜绝未来分支扩张时踩坑）。
2. 改 §7「harness 事实」为：「`cli()` 走真实 subprocess，**stdin 继承父进程**（CI 下非
   tty；本地终端下为 tty）——零输入多条用例必须显式钉 stdin=DEVNULL 保证非 tty 分支」。
3. 改 §9 残余 1 论证为：「tty 交互分支 AC 不可测 = 不引 pty 注入（共享 ac_lib 改动面
   超出本批档位）；非 tty 分支由 n21 显式 DEVNULL 钉死保证」。

### R2【P2】§2.2 对 CLI 侧 parse_delegation 位置自相矛盾：一处实现读法下误用路径出 traceback

**位置**: spec §2.2 三条 bullet（L73-81）。

**证伪过程**:
- bullet 1（L73-76）：「`cli.py _invoke`：加 `on_behalf: str | None = None` 参数；**try
  块内** `delegated = parse_delegation(on_behalf)`（非法 -> BusinessError 被既有 except
  捕获 -> stderr + exit 1）」。
- bullet 3（L79-81）：「**各端点/命令 handler** 在调用 `_run` / `_invoke` 前调
  `parse_delegation`（…CLI：`args.on_behalf`）」。
- 二者对 CLI 互斥：handler 若先 parse，则 _invoke 收到的是 dict 而非 bullet 1 的
  `str` 参数（或重复 parse）。按 bullet 3 实现时，parse 发生在 handler（如
  `cli.py:64-65 _cmd_approve`，无 try/except；`main()` 亦无）-> 未捕获 BusinessError ->
  **traceback 落 stderr、exit 1**，而非 bullet 1 承诺的干净 `invalid_record: ...` 行。
  仓内 CLI 错误面契约是「无 traceback」（tests/ac_cases_k.py:259-262 k_delete 断言
  `"Traceback" not in res3.stderr`）。n6 若只断言「stderr 含 invalid_record + 示例 +
  exit 1 + 零写」，traceback 形态可能混过——测试无法替实现裁决这个分叉。
- REST 侧两 bullet 一致（handler parse -> `_run` 收 dict），矛盾仅 CLI。

**建议修正**: 删除 bullet 3 中 CLI 半句，或改 bullet 1 参数为 `delegated: dict | None`
（handler 已 parse），使两面同构：handler/endpoint 层 parse（失败走各自干净错误路径），
`_invoke`/`_run` 只做「surface 与 delegated 同批落值」。注：与 R5 联动——parse 必须
位于零输入读**之前**（见 R5 统一修法）。

### R3【P2】配对不变量反向（payload.delegated -> surface=delegated）非结构性成立，spec/BCD「当且仅当/结构上不可能单边」过claim

**位置**: spec §2.3 配对不变量段（L99-101「反之带 `payload.delegated` 的事件 surface
必为 delegated（无参时键不出现，结构上不可能单边）」）；§7 n11（L244「全量配对」）；
承自 BCD §3 配对规则（L87）/ §7 强 3（L239「当且仅当同时成立」）。

**证伪过程**:
- 正向（surface=delegated -> 每条事件带有效 payload.delegated）：6 个 op 的全部事件
  写点经同一 surface 变量 + §2.3 逐点 merge，结构性成立（已逐 op 核对写点枚举无遗漏：
  approve 两分支/ release/ release_all_stale 逐项/ renew/ note/ reopen/ abandon，
  operations.py:158-383）。
- 反向反例：**MCP `add_record` 接受自由 `payload: Any`**（server.py:127-139 ->
  operations.py:687-728，payload 除 size/kind 校验外不限键）。agent 完全可写一条
  `kind=decision/risk/note` 事件，payload 含 `"delegated": {"kind":"statement","basis":
  "..."}` 键（例如记录某次委托讨论）-> 该事件 **surface=mcp + payload 含 delegated**。
  此时「payload 有 delegated 但 surface 非 delegated」真实存在，n11 的「全表扫描 ⟺」
  若按系统级不变量解读即被违反。n11 作为**受控写集合上的回归断言**可通过（测试自写的
  mcp 事件不含该键），但 spec 把 n11 表述为「全量配对」不变量背书、§2.3 表述为
  「结构上不可能单边」——声明超出结构保证范围。
- 下游后果（低概率真实）：未来以 `payload.delegated` 为检索键的审计工具会把 agent
  记录事件误判为代执行确认。当前可见面主键是 surface（`by delegated:cli`），故无当前
  行为后果——定 P2 而非 P1。

**建议修正**（二选一，前者成本更低）:
1. 收窄表述：反向保证限定为「**6 个写事件 op 写出的**事件，无受托参数时 payload 不出现
   delegated 键」；显式登记例外「MCP add_record 的 payload 为自由 JSON，可含同名键
   （agent 内容不可信，威胁模型 B 同边界）——审计检索代执行面以 `actor_surface=
   delegated` 为主键，payload.delegated 为佐证」。n11 描述同步改为「本用例受控写集合
   上的回归断言」。BCD §3 配对规则/强 3 的「当且仅当」同口径修订。
2. 或保留键保留语义：`add_record` 拒收含 `delegated` 键的 payload（invalid_record
   新实例）——但这改变 MCP 面既有可接受输入，触碰单向门纯 additive（BCD 强 4），
   需 user 裁决，本审查不推荐默认走此路。

### R4【P2】approve/renew 新增 body 校验是未登记的隐性行为变化：任意非空 body 从 200（忽略）变 422

**位置**: spec §5 兼容矩阵（L178-179 两行「逐字不变」）；§4（L156-157 approve/renew
  签名加 `body: DelegatedIn | None = None`）；§7 n13 只钉无 body 回归。

**证伪过程**:
- 现状：`api/requirements.py:85-87`（approve）/`96-97`（renew）**无 body 参数**——
  FastAPI 对无 body 参数端点忽略请求体，携任意 JSON body 的 POST 返回 200。
- 变更后：`body: DelegatedIn | None = None`，DelegatedIn 要求 `kind: str` + `basis: str`
  必填（spec §4 L151-154）。携不符合 shape 的非空 body（如 `{"note":"x"}`、`{"foo":1}`、
  `{"delegated":"statement:x"}`）-> pydantic 校验失败 -> `RequestValidationError` ->
  既有 handler（`api/main.py:85-90`）映射 **422 invalid_record "request validation
  error"**。即：同一 URL 同一请求，200 -> 422。
- 仓内调用方核查：tests/ 与 web.py 对 approve/renew 的既有调用全部无 body
  （ac_cases_c.py:416/420/446、ac_cases_h.py:100 均 `rest.req("POST", .../approve|renew)`
  不传 body；web.py 无 approve/renew 入口）——仓内无受害方，风险面＝假设的外部人面脚本。
  但 spec 兼容矩阵「逐字不变」断言未覆盖此面，BCD Premortem 5（L221-224）的预防
  （`X | None` 先例 + 无 body 回归用例）同样只钉无 body 形态——「非空非 conform body」
  行为变化在 spec/BCD 两处均未登记。

**建议修正**: 兼容矩阵加一行：「REST `POST /approve`、`POST /renew` 携非空非
DelegatedIn 形态 body | 200（体被忽略） | **422 invalid_record（request validation
error）——登记为已知行为变化**」；§7 加 1 条 AC（如 n17b：`POST /approve` body
`{"foo":1}` -> 422、零写、surface 无关），把新面钉死。若 user 裁决接受不测，至少矩阵
行必须落。

### R5【P2】零输入解析与 --on-behalf 校验次序未钉：spec 自身设计下，0 待决板静默吞非法 flag

**位置**: spec §3.2（L114-137，先「读候选」后分支）与 §2.2 bullet 1（parse 在
`_invoke` try 块内）的组合；§7 n6-n8 前置为「任意」。

**证伪过程**:
- 按 spec 描述的实现次序：handler 先做零输入解析（L119-121 读 list_awaiting）-> 分支
  -> 恰 1 条才进 `_invoke`（parse 在此发生）。推演三条序列：
  1. **0 待决 + `--on-behalf "badkind:x"`**：零输入分支直接输出「无待决项」exit 0，
     非法 flag **从未被校验**——静默接受。违背本批「宁拒不猜 / fail-fast」纪律
     （release reason fail-fast 正是同类：L135-137 在 DB 读取前拒）。
  2. **多条非 tty + 非法 flag**：先撞「多条待决项，请用 --requirement-id 指定目标」
     exit 1——用户被误导（真正错的是 flag，不是没给 id）。
  3. 恰 1 条 + 非法 flag：正常 invalid_record。
- n6-n8 前置「任意」无法区分上述形态，测试不替作者裁决。

**建议修正**: §3.2 显式钉「**--on-behalf 结构校验先于零输入读候选**（与 release reason
fail-fast 同纪律：DB 零触碰）」；n6-n8 前置改「0 待决板 + 恰 1 待决 + 2 待决非 tty 各一
（或至少覆盖 0 待决形态）」；与 R2 统一修法——parse 上移到 handler 首行（干净错误
路径 + 次序天然正确），`_invoke` 收已 parse 的 dict。

### R6【P2】tty/非 tty 编号候选列不含 state，BLOCKED 候选误操作向量未消（本批核心不变量强 5 的防线缺口）

**位置**: spec §3.2 分支 2/4 列表格式（L127-130 `1. <8hex> <title>`）；语义注
（L140-142 已声明 BLOCKED 候选 approve = 解阻）。

**证伪过程**:
- list_awaiting 候选 ∈ {CLAIMED(review), BLOCKED(blocked)}（已核：awaiting_human 仅
  request_review/mark_blocked 两路径设置，operations.py:794-800/876-879；transition 除
  BLOCKED 外一律清 marker，state_machine.py:65-68）。
- 误操作序列：板上 2 条 awaiting（1 review / 1 blocked），人零输入 `approve`（意图：
  确认完成的那条），tty 列表只有标题，人选中 blocked 那条 -> 执行结果是**解阻**
  （BLOCKED->CLAIMED）而非 DONE。spec 语义注声明了行为，但列表格式未给人区分信息。
- 缓解事实（定 P2 而非 P1 的原因）：返回 JSON 显含 `state`（CLAIMED），人当场可见
  结果非 DONE；无终态污染、可重跑。但 BCD Premortem 3（L211-214）把「零输入误伤」
  列为本批失败原因，其预防「编号列表带标题」是误选防线——数据已在手
  （list_awaiting 返回 `state` + `awaiting_human.kind`，operations.py:954-963），
  不显示 = 防线主动降级。

**建议修正**: 列表行加 state（或 kind）：`1. <8hex> [BLOCKED] <title>` /
`2. <8hex> [CLAIMED] <title>`；§3.2 两处格式串 + n21 断言同步（stderr 含
`[CLAIMED]`/`[BLOCKED]`）；BCD 边缘场景 2/例 4 措辞同改。

---

## 事实断言核验表

| # | spec 断言 | 核验 | 结果 |
|---|---|---|---|
| 1 | `set_expectations`（operations.py:115）不写事件，仅置 acceptance+updated_at | 读 operations.py:115-155，无 add_event/transition 调用；CLI/REST 两入口（cli.py:57-61、requirements.py:80-82）均无旁路事件 | **对**。D1 推论链成立（受托痕须落事件自身[BCD Q3] -> 无事件 -> 无载体）；替代案（新增事件 kind）已在 §9 残余 3 登记为独立演进，非回避 |
| 2 | `transition` 的 `event_payload` 合并进 state_change payload（state_machine.py:69-71） | state_machine.py:44 参数、:69-71 `payload={"from","to"}; payload.update(event_payload)` | **对** |
| 3 | `list_awaiting`（operations.py:936）返回 requirement_id(32-hex)/title/state/awaiting_human/waiting_seconds/claim，updated_at 序 | operations.py:936-964 逐字段核对；:945 `order_by(Requirement.updated_at)` | **对**（返回外层 `{"awaiting": [...]}` 包装 spec 未提，不影响主张） |
| 4 | view.py:616/700 是 `by {surface}:{conn}` 通用渲染，零改动透传 `by delegated:cli` | view.py:616（detail 文本）/700（export markdown）逐字核对；web.py:511 前端同式渲染（esc 转义）；export CSV 列含 actor_surface（:716）；SSE 帧含 actor_surface（requirements.py:157,166） | **对** |
| 5 | requirements.py:111 有 `ReopenIn \| None = None` 先例；approve(:85)/renew(:96) 现无 body | :111-113、:85-87、:96-97 逐字核对 | **对** |
| 6 | cli.py:280 approve `--requirement-id` required=True；:284 release 已可选 | cli.py:279-287 核对 | **对** |
| 7 | PRD §4.2 :175（approve）/:176（release）、§4.3 :199、§5.1 :217 | :175/:176/:217 内容与行号相符；**§4.3 的 invalid_record 实例清单实际在 :201**（:199 是 10 码枚举行） | **:199 偏**（锚点漂移，勘误：改引 :201；主张本身成立） |
| 8 | PRD §3.4 approve 按当前状态判定（含 BLOCKED->CLAIMED 解阻） | PRD:127-140 决策表逐行核对（:136 BLOCKED/blocked -> 解除阻塞） | **对** |
| 9 | design.md 无 surface 枚举清单，无需同步 | 全文仅 1 处 "surface"（:30 events 表结构含 actor_surface 列）；:97 approve 语义描述本批不变 | **对**（既有陈旧见「正典老化」节 design.md:34） |
| 10 | skills/agent-kanban/SKILL.md 本仓 tracked | `git ls-files` 含该文件，`git check-ignore` 不忽略；「交接与等待」节在 :45 | **对** |
| 11 | 兼容矩阵：`release --all-stale` 无 on-behalf 时逐项 payload={reason:"stale",agent_name} 逐字不变 | operations.py:257-261 现值核对；变更仅 `if delegated else {}` 条件加键 | **对** |
| 12 | 兼容矩阵：REST archive 携 body 被忽略（200，surface=cli，无 payload.delegated） | requirements.py:116-118 无 body 参数（FastAPI 忽略体）；web.py:491/550-553 详情页仅 archive/delete 两操作且均不带 body | **对** |
| 13 | 兼容矩阵：MCP 12 工具零改动（「op 签名尾部 keyword 默认」） | server.py:205-218 共 12 工具，**无一调用 6 个人面 op**（approve/release/renew/note/reopen/abandon 无 MCP 入口）；零改动结论**对**，但括号理由归位错——MCP 不受影响是因为从未调用这些 op，非「尾部 keyword 默认」 | **结论对，理由偏**（勘误，见 N3） |
| 14 | system 面（retry_limit marker / reconcile）不经 cli/rest 派生层 | retry_limit.py:16-17 `RETRY_LIMIT_SURFACE="system"`；reconcile.py:23-24 `RECONCILE_SURFACE="system"`；CLI reconcile 入口不传 actor（cli.py:247），lifespan 对账同（main.py:56） | **对** |
| 15 | 全量 AC 基线 624/624 | **本审查实跑** `TMPDIR=... .venv/bin/python -u tests/run_ac.py`（主仓 5089bfe，与 worktree 测试/代码 diff 为空）：`== 结果: 624/624 PASS` | **对**（AGENTS.md 的 592/592 已陈旧，见 N4） |
| 16 | e2e 基线 15/15 | smoke.spec.js 计得 15 个 `test(`；e2e 套件本审查未实跑（见未核区） | **计数对，运行未核** |
| 17 | harness 事实：`cli()` 真实 subprocess「stdin 恒非 tty」；REST 真实 uvicorn 子进程 + urllib；MCP 真实 stdio 子进程；oracle＝sqlite 直查 | ac_lib.py:51-56 **未传 stdin=（继承父进程）**；api/__main__.py:12 uvicorn.run；ac_lib MCP 类 Popen stdio；ac_lib.query sqlite3 直查 | **stdin 条错**（见 R1，pty 实证）；其余对 |
| 18 | 零 schema 变更（payload 为既有 JSON 列；surface 值可加） | models.py:136 `actor_surface: String(16), nullable=False`，无 CHECK/Enum；"delegated"（10 字符）在限内 | **对**（:136 行尾注释 `# mcp \| cli \| system` 将陈旧，见 N1） |
| 19 | ADR 0002（服务端派生 actor 先例） | ADR 0002 正文为 MCP SDK 选型，相关条款在 :12（agent 身份经会话上下文传递、服务端仅记录不鉴权）；identity.py:1、server.py:2 均以「ADR 0002」同式引用派生单点 | **与仓内既有引用惯例一致**，不独立成发现 |
| 20 | known-gaps G11（cli.py 涉改需刷入口快照） | 0000-known-gaps.md:20 原文核对（force-include 快照机制 + 刷新纪律） | **对** |
| 21 | spec §1「7 op 函数…对应 6 CLI 命令」/§4「6 端点」 | 与代码一致（release_all_stale 为独立 op 函数、无独立 CLI 命令/REST 端点） | **对**（BCD 侧计数陈旧见 N2） |
| 22 | n10 可执行性：ac_lib MCP 客户端支持 tools/list 的 inputSchema 断言 | ac_lib.py:164-169 `rpc()` 通用 + :190-192 `list_tools()`（仅回传 name）；n10 需直调 `m.rpc("tools/list", {})` 取完整 tools（含 inputSchema）——**可执行，无需新 harness 机制** | **对**（实现注意用 rpc 直调而非 list_tools 辅助函数） |
| 23 | n21 断言稳健性（「stderr 含两条 8hex+title」） | 测试自控 title（spec 要求不同 title）；8-hex 前缀来自 seeded id；断言为子串包含（非正则）——特殊字符无影响 | **对**（前提：title 不同，spec 已写） |
| 24 | release 零输入 reason fail-fast 文案与 op 层一致（operations.py:203-205） | operations.py:203-204 `if not reason or not str(reason).strip(): raise BusinessError("invalid_record","release requires a reason")`；CLI 面错误输出格式 `{code}: {message}`（cli.py:32）拼出同文案 | **对**（L205 实为 require_requirement 行，锚点 ±1，勘误） |

## 契约同步面闭环检查（spec §6）

| 同步面 | 判定 |
|---|---|
| PRD §4.2 approve/release 句、§4.3 实例清单、§5.1 枚举+派生规则 | 闭环（§6.1-6.4；§4.3 锚点勘误 :199->:201） |
| SKILL.md 收尾协议节（:45 后） | 闭环；措辞审查通过——触发/kind 判据/本地仓反例/禁自产决定四要素齐，set_expectations 边界由「执行」节只列 approve/release 隐含（收尾协议域＝收尾操作，agent 不会误探 set_expectations 的 flag；撞了也自纠：argparse exit 2 unrecognized arguments） |
| AGENTS.md 人面 CLI 行 | 闭环（§6.6） |
| docs/design.md | 核毕无需同步（:30 表结构零 schema 变更；无枚举清单）——**确认非缺口** |
| docs/web.md | **核毕无需同步**（非缺口）：「人面 surface」节（:37 起）是 Web 边界描述（决策操作 CLI/REST-only、Web 无入口），本批后无一句变假；其规范锚指向 PRD §4.2（本批同步对象）。「语义与端点不变」为 2026-10-26 修订注的自述，非活性契约句 |
| docs/mcp-config.md | 核毕无相关面（零 surface/approve/release 内容）——非缺口 |
| PRD :318 文件树注释 / cli.py:1 docstring 子命令清单 | **无需同步**：两处均为**既已陈旧的局部清单**（:318 缺 mcp/view/reopen/archive/delete/prune/reconcile；cli.py:1 同缺），非契约面；本批不修不新增割裂（可顺手补全，不要求） |
| SKILL.md 错误码速查 invalid_record 行 | **可选**（非缺口）：PRD §4.3 加 delegated 实例后，速查表同加一句可保两表同步；操作面已由「错误消息带参数名与示例，据此自纠」既有原则兜底（SKILL.md:31） |
| models.py:136 行尾注释 | **同步清单盲区**（N1）：`# mcp \| cli \| system` 本批后陈旧，一行顺手改 |

错误消息面（攻击面 6 复核）：三种非法消息均含参数名 `delegated` + 正确示例
（DELEGATION_EXAMPLE），满足 AGENTS 协议「消息带参数名与示例」自纠要求；kind 越枚举/
basis 空两条消息 shape 中立（CLI/REST 通用）；「无冒号」条为 CLI 字符串特有（REST 侧
dict shape 由 pydantic 先行拦截，到不了该分支）；「(CLI --on-behalf)」括注对 REST
调用方略噪但不误导（参数名 + 示例仍承载自纠信息）——**通过，不立发现**。

## 正典老化 / 冲突

1. **AGENTS.md tier 2 基线 592/592 陈旧**（实测 624/624，本审查实跑证据见事实表 #15）。
   既有漂移，非 spec 引入；spec 自身数字正确。建议合入批顺手更新（spec §6.6 本就要
   碰 AGENTS.md）。
2. **design.md:34 事件 kind 清单缺 `renew`/`reconcile`**（PRD §2:72 已含二者）。既有
   漂移，非本批对象；design.md 本批零改动，不占 spec 问题位，留档供后续批次。
3. ADR 0002 被仓内三处（identity.py:1 / server.py:2 / 本 spec）以「服务端派生 actor
   先例」引用，而 ADR 正文是 SDK 选型（相关条款 :12）——仓内引用惯例一致、无 ADR×ADR
   冲突，不判 stale，仅注记。

## 未核区（显式）

- e2e 15/15 未实跑（playwright 环境本审查不启；spec 对 e2e 的主张是「零改动全回归」，
  代码级零改动论证成立：spec 不触碰 web.py/api 前端；15 用例计数已核）。
- R4 的 200->422 行为系 FastAPI/pydantic 语义 + 仓内 handler（main.py:85-90）代码路径
  推演，未起真服务实测（推演链完整，置信高）。
- docker 双轨 / CI tier 未跑（超出 spec 审查范围）。
- R1 的 tty 失败序列经 pty 实证了 stdin 继承机制（isatty=True），未实际实现 n21 后
  复现挂起（实现前审查，机制即决定行为，无额外不确定）。

## 残留（登记位置点名）

- R1-R6 全部在 spec 文本内可修，修复合入即闭合，无需 known-gaps 登记。
- 既有漂移两项（AGENTS.md 基线 592、design.md:34 kind 清单）非本批引入，建议随本批
  顺手修（AGENTS.md）或留档后续（design.md）；owner = 主循环（delegated-confirm 批）。

## 终判与修正路径

**verdict: REJECT**

P1 x1 + P2 x5。修正路径（均为 spec 文本 + 测试设计级修改，无方向性返工）：
1. R1：n21 钉 stdin=DEVNULL（ac_lib.cli 加可选 stdin 透传）+ 改写 §7 harness 事实与
   §9 残余 1 论证。
2. R2+R5（联动一处改）：parse 位置统一到 handler 层且先于零输入读候选；删/改 §2.2
   矛盾 bullet；§3.2 钉校验次序；n6-n8 前置收紧。
3. R3：§2.3/n11/BCD 强 3 反向表述收窄（限定 6 op 写点）+ 登记 add_record 自由 payload
   例外与审计主键指引。
4. R4：兼容矩阵登记 approve/renew 非 conform body 200->422 + 加 1 条 AC（或 user
   裁决接受不测）。
5. R6：候选列表行加 state/kind 显示 + n21/BCD 边缘场景 2 同步。

修订后 **resume 本审查者（同 task_id）续审**：三态复核（R1-R6 closed/残留/新增）+
扫新增面。

### N 节（注记，不改也可）

- **N1**: models.py:136 行尾注释 `# mcp | cli | system` 本批后陈旧（新增 delegated 值），
  spec §6 同步清单只列文档、未含此一行代码注释——顺手改。
- **N2**: BCD What 3/4 计数陈旧：「--on-behalf（7 命令）」「7 端点」（BCD L69-70），
  实为 6 CLI 命令 / 6 REST 端点（7 op 函数）；spec §1:34 引「BCD Q2 的『7 操作』枚举」
  与现行 BCD Q2 文本（「6 个写事件的 6 个人面操作」，BCD L39）不符——spec 自身范围
  表述正确，建议同批把 BCD What 3/4 与 spec 引法对齐，免下批再撞。
- **N3**: spec §5 矩阵 MCP 行理由「op 签名尾部 keyword 默认」归位错（12 个 MCP 工具
  本就不调用 6 个人面 op）——结论对，理由改「MCP 工具面无 6 个人面 op 入口（server.py
  205-218），结构性零触达」。
- **N4**: AGENTS.md tier 2 基线 592/592 -> 624/624（实测），随 §6.6 顺手更新。
- **N5**: §9 残余 1 人工核验规格可执行（临时 DB + 真终端 + 99 拒绝 + 1 执行），建议补
  「非数字输入（如 abc）-> 无效选择，未写入，exit 1 零写」一步，覆盖 §3.2 非数字分支。

---

## 第 2 轮续审（2026-10-28）

**对象**: spec v2 + BCD v2.2（commit ceee10d，worktree 同路径）；第 1 轮 = REJECT
（P1×1 / P2×5 / N×5，主循环声明全部折入）。
**方法**: 三态复核（R1-R6 / N1-N5）+ v2 新增面扫描 + 增量事实核验；全部行号于 worktree
逐条重核（分支仅加文档，代码与 main 同源；套件第 1 轮实跑 624/624，v2 不涉代码，
本轮未重跑）。

### 三态复核表

| 项 | 判定 | 证据 / 差距 |
|---|---|---|
| R1 (P1) | closed | §7 harness 事实重写（spec L255-260）与实测一致：ac_lib.py:51-56 `cli()` 无 `stdin=`（继承父进程）；零输入用例 n19-n24 case-local helper 钉 `stdin=subprocess.DEVNULL`（L258-259）；ac_cases_k.py:37-44 `_run_cli` 同模式（case-local + subprocess.run 显式 stdin 控制，现用 input= 注入）属实，ac_cases_n.py 可 import VENV_PY/CLI/REPO_ROOT/TIMEOUT/env_for（ac_cases_k.py:22-23 先例）定义自有变体，不动共享 ac_lib，方案可行；§9 残余 1 重写（L321-325）；n21 显式钉（L294）；§3.2 分支 4 注（L152-153）与 §9 口径一致 |
| R2 (P2) | closed | §2.2 矛盾消解：bullet 1 `_invoke` 收已 parse 的 dict（L73-75）+ bullet 3 parse 统一 handler 层（L78-84），不再有「_invoke try 块内 parse」读法；handler 层「无 traceback」输出路径可达——handler 级 try/except BusinessError -> stderr + return 1 形态仓内有 4 处先例（_cmd_delete cli.py:95-115 / _cmd_prune :200-235 / _cmd_view :149-168 / _cmd_export :127-137）；n6-n8「stderr 无 Traceback」钉死错误面契约（L270-272） |
| R3 (P2) | **残留（部分）** | 已闭合：spec §2.3 正向系统级 + 反向收窄 + add_record 例外登记 + 审计主键（L104-116）、n11 收窄（L275）、BCD §3 配对规则收窄（BCD L87）、Premortem 4 预防收窄（BCD L218）。**差距：BCD §7 强 3（BCD L239）「当且仅当同时成立」裸 iff 未收窄**——与同文档 §3 收窄口径不一致（例外登记正是系统级反向的破坏项）；v2.2 修订记录所称「强 3 预防」实指 Premortem 4 预防（BCD L218），强 3 命题本身未动。修＝一行范围限定（见终判条件 1） |
| R4 (P2) | closed | §5 矩阵行 6 登记「非 conform body 200->422，仓内无受害方（核毕），n17b 钉」（L203）；n17b 新增（L286）；与 n13（无 body -> 200）不冲突（不同请求形态）；422 双路径代码级核毕（main.py:80-83 BusinessError invalid_record / :85-90 RequestValidationError，均 422 且 code=invalid_record），断言「422；零写」稳健 |
| R5 (P2) | closed | §2.2 L78-79「parse 统一在 handler 层（`_cmd_*` / 端点函数首语句），先于任何 DB 操作（fail-fast……否则 0 待决板会静默吞非法 flag——v1 审查 R5）」；§3.2 步骤 0（L134-135）一致；n6-n8 前置收紧为 0/1/2 三形态 + 零写 + exit 1 + 无 Traceback（L270-272） |
| R6 (P2) | closed | §3.2 行格式 `<8hex> [CLAIMED] <title>`（L146-147）+「行格式含 state（取自 list_awaiting 返回 state 字段，零成本）」（L154-156）；n21 断言含 state（L294）；BCD Policy 6（L106）/ 边缘场景 2（L138）/ 例 4（L182）同改 |
| N1 | closed | §6.7 新增（spec L246-247）；models.py:136 确为 actor_surface 列 + `# mcp \| cli \| system` 行尾注释，改动纯注释不涉行为；「注释是 surface 枚举唯一代码内清单」成立（grep src/ 全量：retry_limit.py:16-17 / reconcile.py:23-24 为单值常量，无其他枚举清单） |
| N2 | closed | BCD How 2（L61）/ What 3（L69）/ What 4（L70）均 6 命令 / 6 端点；spec §1（L34）「写事件的 6 个人面操作（7 个 op 函数）」与 BCD Q2（L39）一致 |
| N3 | closed | §5 矩阵 MCP 行（L205）「12 工具本就不调 6 个人面写 op（server.py:205-218 工具清单：agent 面 op），结构性零触达」；server.py:205-218 确为 build_server 12 工具注册表，无一调 6 个人面 op，行号准确 |
| N4 | closed | §6.6（L244-245）「592/592 -> 624/624，最高 tier 行同数同步」 |
| N5 | closed | §9 残余 1 (a) 非数字 abc -> 拒绝零写 (b) 越界 99 -> 拒绝零写 (c) 再跑输入 1 执行（L323-325） |

第 1 轮事实表 #7 勘误（PRD invalid_record 实例清单 :199 -> :201）：§6.3 已改引 :201
（L219），closed。

### 新增面扫描（v2 新写文字）

1. **§2.2/§3.2 parse 次序 + 两面同构**：自洽——CLI handler parse -> `_invoke` 收
   dict，REST handler parse -> `_run` 收 dict，§3.2 步骤 0 与 §2.2 一致；handler 层
   异常输出路径与「无 traceback」契约实际可达（见 R2 行）。例外：§2.2 L82-84 的 REST
   表达式 `body.delegated.model_dump() if body.delegated else None` 仅适用 4 个 wrapper
   端点（release/note/abandon/reopen，body 模型加嵌套 delegated 字段）；approve/renew
   按 §4 body 整体即顶层 DelegatedIn（正确表达式 `body.model_dump() if body else
   None`），该表达式对 DelegatedIn 字面不可用（无 .delegated 属性）——见 N6。
2. **§2.3 反向 kind 集合 {approval,release,renew,state_change}**：operations.py 全表 +
   src/ 全量 kind= 写入点 grep——
   - kind ∈ {approval,release,renew}：写入点仅 approve(:179) / release(:220) /
     release_all_stale(:258) / renew(:293)，全在 6 内、全人面，**无第 7 写入点**；
   - kind=state_change 写入点：transition()（state_machine.py:75）调用方＝6 内 5 op
     （approve/release/release_all_stale/reopen/abandon）+ **archive_requirement
     （唯一第 7 人面写点，:401）**+ claim_task(:495) + mark_blocked(:870)；另有
     update_subtask(:591) / update_milestone(:679) 经 add_event 直写 state_change
     （子任务/里程碑级，agent 面）；
   - 非 6 写点均**不可能**产出 delegated 键：archive_requirement 无 delegated 参数且
     无 event_payload（payload 仅 {from,to}）；claim_task 无 event_payload；mark_blocked
     event_payload={"reason"} 固定键；update_subtask/update_milestone payload 为
     {subtask_id|milestone_id, from, to} 固定形态；system 面 retry_limit(:616,
     kind=risk) / reconcile(reconcile.py:98, kind=reconcile) 不写 state_change；
   - add_record 受 RECORD_KINDS={decision,risk,deviation,decomposition,note} 约束
     (:31, :704)，结构性写不出反向集合 4 种 kind——反向保证实际比 spec 表述更强。
   **无新发现。**
3. **n17b 422 语义**：`{"foo":1}` 在 pydantic 层拒 -> RequestValidationError ->
   main.py:85-90 -> 422 {code:"invalid_record", message:"request validation error"}
   （非 BusinessError 路径）；n17（kind 越枚举）走 parse_delegation BusinessError ->
   main.py:80-83 -> 422 {code:"invalid_record", message: parse 消息}。两路均 422 且
   code=invalid_record，n17b 只断「422；零写」——钉得住且稳健（端点函数执行前校验
   失败，零写平凡成立）。**无新发现。**
4. **§5 矩阵新行 vs n13**：不冲突（无 body -> 200 为 n13；携 body 且非 conform -> 422
   为 n17b，两请求形态不相交）。措辞缺口：行文「任意非 conform **非空** body（如
   {"foo":1}）」——空对象 {}（present 但空 JSON 对象）同样 pydantic 拒 200->422（与
   {"foo":1} 同类变化），按「非空」读法落在登记范围外——见 N7。
5. **§6.7 models.py:136**：该行确为 surface 枚举注释，改动纯注释（见 N1 行）。
   **无新发现。**
6. **§7 harness 事实 + §9 残余 1 DEVNULL 表述**：ac_lib.cli() 现文无 stdin=，与 spec
   一致；case-local helper 方案可行（见 R1 行）。「harness stdin 只能钉非 tty」措辞
   严格说过强（pty 可钉 tty），但同句后段「不引 pty 注入」已澄清意图，不立发现。
   **无新发现。**

### 增量事实表（v2 新引入行号 / 代码断言）

| # | 断言 | 核验 | 结果 |
|---|---|---|---|
| F1 | models.py:136 actor_surface 列 + 行尾注释，注释为代码内唯一枚举清单 | models.py:136 逐字 `actor_surface: Mapped[str] = mapped_column(String(16), nullable=False)  # mcp \| cli \| system`；src/ grep 无其他枚举清单 | **对** |
| F2 | server.py:205-218 = 12 工具注册表，无一调 6 个人面写 op | server.py:205-218 恰为 build_server 内 12 工具（list_tasks/get_task_detail/claim_task/add_subtask/update_subtask/add_milestone/update_milestone/add_record/update_progress/request_review/mark_blocked/list_awaiting） | **对**（行号准确） |
| F3 | ac_lib.py:51-56 cli() 真实 subprocess 无 stdin= | ac_lib.py:51-56 逐字（subprocess.run + capture_output，无 stdin= 参数） | **对**（行号准确） |
| F4 | ac_cases_k.py:37-44 _run_cli case-local 注入 stdin | ac_cases_k.py:37-44 逐字（case-local 函数 + subprocess.run(input=input_text)） | **对**（行号准确；现为 input= 字符串注入，spec「同模式」指「case-local + 显式 stdin 控制」同形，n 用 stdin=DEVNULL 变体） |
| F5 | operations.py:300/314 note op（payload={"content": content}） | note op :300-318；:313-317 add_event kind="note" payload={"content": content} | **对** |
| F6 | operations.py:687/704 add_record + RECORD_KINDS | add_record :687；:704 `if kind not in RECORD_KINDS: raise invalid_record`；RECORD_KINDS={decision,risk,deviation,decomposition,note}（:31） | **对** |
| F7 | requirements.py:85/:96 现无 body；:91/:101/:106/:111 为 release/note/abandon/reopen 签名行 | requirements.py:85-87/95-97 无 body 参数；:91 body: ReleaseIn / :101 body: NoteIn / :106 body: AbandonIn / :111 body: ReopenIn \| None = None | **对**（行号准确） |
| F8 | 422 双映射（BusinessError invalid_record + RequestValidationError），body code 均 invalid_record | main.py:80-83（REST_ERROR_STATUS，文件头契约 L1-7 列 invalid_record=422）+ :85-90（硬编码 422 + code:"invalid_record"） | **对** |
| F9 | state_machine.py:69-71 event_payload 合并进 state_change payload | state_machine.py:69-71 `payload={"from","to"}; payload.update(event_payload)`；kind="state_change"（:75） | **对** |
| F10 | list_awaiting（operations.py:936）字段集 + updated_at 序 + {"awaiting"} 外层 | operations.py:936-964 逐字段；:958 `"state": r.state`（R6 零成本 state 显示来源） | **对** |
| F11 | add_event 签名 payload: dict \| None = None（renew 无 payload 现状 -> None 回落逐字回归） | operations_util.py:14-29 | **对** |
| F12 | cli_actor()->("cli","cli") / rest_actor()->("cli","rest:<8hex>")（delegated 面 conn 沿用 rest: 前缀，n12 断言钉得住） | identity.py:56-63 | **对** |
| F13 | ac_lib rpc():164-169 通用 + list_tools():190-192 仅回 name | ac_lib.py:164-169/190-192 | **对**（n10 schema 断言走原始 rpc，可执行） |
| F14 | cli.py:280 approve required=True / :284 release 可选 | cli.py:279-287 | **对** |
| F15 | handler 层 try/except BusinessError -> stderr + return 1 形态仓内成立（R2 输出路径可达） | _cmd_delete cli.py:95-115 / _cmd_prune :200-235 / _cmd_view :149-168 / _cmd_export :127-137 | **对** |

### 新发现

- **N6**（注记，措辞）：§2.2 L82-84 REST parse 表达式 `body.delegated.model_dump() if
  body.delegated else None` 仅适用 4 个 wrapper 端点（release/note/abandon/reopen）；
  approve/renew 按 §4 body 整体即顶层 DelegatedIn（正确表达式 `body.model_dump() if
  body else None`），DelegatedIn 无 .delegated 属性，该表达式对这两端点字面不可用。
  §4（L178-180）正确且 n12/n17 钉顶层形态（错误实现会 AttributeError -> 500，n12
  即红），不占问题位；修＝§2.2 表达式与 §4 对齐（如 §4 式「body...model_dump()」或
  两形态分写）。
- **N7**（注记，措辞）：§5 矩阵 L203「携任意非 conform **非空** body」——空对象 {}
  （present 但空 JSON 对象）同样 pydantic 拒 200->422（与 {"foo":1} 同类变化），按
  「非空」读法落在登记范围外。修＝行改「任何 present 的非 conform body（含空对象
  {}）」，与 n13「无 body（absent）-> 200」对照明确。

### 未核区（承接第 1 轮，无新增）

- e2e 15/15 未实跑（v2 不触 web.py / REST 前端，零改动论证不变）。
- R4 的 422 双路径本轮已补代码级核毕（main.py 两 handler，见 F8），仍未起真服务
  实测（推演链完整，置信同第 1 轮）。
- docker 双轨 / CI tier 未跑（超出审查范围）。

### 终判

**verdict: APPROVE-WITH-FIXES**

- 三态计数：closed 10（R1/R2/R4/R5/R6 + N1-N5）/ 残留 1（R3 部分：BCD §7 强 3）/
  新增 P1-P2：0 / 新增 N：2（N6、N7）。
- 无 P1。唯一残留为 BCD 契约文字层，无行为/测试/实现后果：
  1. **R3 残留（P2，必修）**：BCD §7 强 3（L239）「当且仅当同时成立」收窄至与 §3
     配对规则同口径——建议：「写事件的 6 个人面操作写出的事件，surface=delegated 与
     payload.delegated={kind,basis} 结构有效当且仅当同时成立（MCP add_record 自由
     payload 例外与审计主键见 §3 配对规则）；服务端单点派生（同函数落值）」；并更正
     v2.2 修订记录「强 3 预防」归位（实为 Premortem 4 预防，BCD L218）。
  2. **N6/N7（可选，顺手）**：§2.2 表达式与 §4 对齐；§5 矩阵行「非空」改「present
     （含空对象 {}）」。
- 修复合入后文本级复核即闭合（无需重走全轮）：强 3 新表述对 §3 复读 + N6/N7 两处
  一行复读。
