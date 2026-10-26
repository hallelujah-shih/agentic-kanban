# M1-6: board/detail 壳修复与防线（T1 转义 + T2 终态操作导航 + T3 深潜 description 展示）

**基分支**: main @ 1f1f47a（worktree `.worktree/m1-6-board-shell-js`，分支 `m1-6-board-shell-js`）
**档位**: 全六门（B/D 面交界按 D 取重：改动落在用户可见的 Web 壳，且新增测试资产）
**日期**: 2026-10-26

## 背景与机制结论（带证据）

- 症状（user 浏览器冒烟发现）：看板页永远"加载中"，右上角指示器恒停"连接中"，
  DevTools Network 无任何 `/board`、无 `stream` 请求。
- 机制：`web.py` 的壳是 Python 三引号字符串，`web.py:279` 的 JS 字面量
  `split("\n")` 被 Python 先转义成**真换行符**送出 → JS 字符串字面量跨两行
  → 整个 `<script>` 块 SyntaxError → JS 零执行（无 fetch、无 EventSource）。
- 证据：
  - `node --check` 对现网（容器 8765）送出的 board 壳 script 块：
    `SyntaxError: Invalid or unexpected token`（行 147，
    日志 /tmp/opencode/m1-5/logs/ 外的现场文件 /tmp/opencode/board-script.js）。
  - 现网 detail 壳 script 块 `node --check` 通过（对照，证明检查方法有效）。
  - 全仓扫描：仅此一处 JS 转义受损；`web.py:363` 的 `\\/` 是双反斜杠，
    Python 解释后送出 `\/`，JS 正则正确，不动。
  - 旧版 web.py（8767385，M1-5 前）无此模式 → 引入点 = M1-5 新建表单
    （nf-acc textarea 按换行拆分）。
- 为何既有 harness 未拦截：k_web 等用例只断言壳字符串存在（grep 级），从不
  执行 JS —— 即 M1-5 验证文档登记的盲区"浏览器 JS 无自动化"。

## 契约三锚

1. **规范逐字原文**：
   - `docs/superpowers/specs/2026-10-26-task-lifecycle-positioning-design.md:71`：
     "acceptance（textarea，一行一条锚） | 否 | 每行 -> `{"item": line}`
     （`normalize_anchors` 自动编号 a1/a2/...；空行忽略）"
     —— 前端按换行拆分 textarea，该换行符的 JS 转义必须原样到达浏览器。
   - `docs/web.md:11`："看板壳（HTML）：JS fetch `/board` 渲染，需要关注区置顶
     + 紧凑行；EventSource 订阅 `/events/stream`，收到事件或重连（onopen）即重拉"
     —— 看板壳可用的前提 = 壳内 JS 可解析。
2. **代码锚点**（main@1f1f47a 实测）：
   - `src/agent_kanban/api/web.py:279`：
     `var acc = document.getElementById("nf-acc").value.split("\n")`（唯一受损位）
   - 送出证据：/tmp/opencode/board.html 行 147-148（字符串被真换行截断）；
     /tmp/opencode/detail.html 的 script 块 node --check 通过（对照基线）。
3. **逐例期望**：
   - 基线：main@1f1f47a 全量 `uv run python tests/run_ac.py` = 509/509 PASS
     （M1-5 P5 复验）。
   - 新增 2 条断言（T1-A1/A2）在 base main（未修复代码）上必须红：
     A1 失败（送出壳含真换行而非字面 2 字符 \n）；A2 失败（script 块行 147/148
     引号不配对）。红证据先采集再动产品代码。
   - 修复后全绿：511/511（509 + 2，计数按断言行，与 M1-5 计数链同规）。
   - 一次性真机：修复后对两壳（board/detail）的 script 块 node --check 均通过
     （node v24.21.0，宿主实测在场；重跑规格见下）。

## 原子任务（T1/T2/T3 三任务批次）

### T1: 转义修复 + 2 条壳解析防线断言

**改动（单文件产品位 1 行 + 测试文件 2 断言）**：

1. `src/agent_kanban/api/web.py:279`：`split("\n")` → `split("\\n")`
   （Python 源双反斜杠 → 送出 JS 字面 2 字符 `\n` → 浏览器内 split 按换行工作，
   spec:71 的"一行一条锚"行为恢复）。
2. `tests/ac_cases_k.py` k_web 用例组 +2 断言：
   - **A1（逐例，spec 锚）**：送出的 board 壳（`GET /`，Accept text/html，
     走现有 REST 真 uvicorn 子进程通道）包含字面串 `.value.split("\n")`
     （2 字符：反斜杠+n；测试代码中写 `'.value.split("\\n")'`）。
   - **A2（类防线，物理不变式）**：board 与 detail 壳的 `<script>` 块逐行，
     剥离转义序列（`\\.` 类）后双引号计数为偶——JS 字符串字面量不得含未转义
     换行的静态化表达。探针已验证判别力与无假阳：修复前 board 精确 FAIL 于
     script 块行 147/148；修复后 board 与 detail 全 PASS。detail 壳取任一现存
     requirement 的深潜页（k_web 用例组既有 fixture 复用，不新增夹具）。
     **假阳边界（plan 审 P2 折入，断言处注释登记）**：单引号 JS 字符串/正则
     字面量/注释内含奇数个双引号的行会假红；当前两壳零命中，属未来维护面。

**oracle 三判据**：
- ① 独立于实现：A1 锚 = spec:71 逐字契约（按换行拆分必须以转义形式送达）；
  A2 锚 = JS 语法物理不变式（字符串字面量禁含裸换行），非实现镜像。
- ② 反证位：两断言先在 base main 跑红（红输出留档 /tmp/opencode/m1-6/logs/t1-red.log，
  关键行摘录入 ledger），再修产品代码转绿——红绿同源（同一 run_ac 入口）。
- ③ 对抗变体：A2 是类级断言，覆盖"未来任意 JS 字符串被 Python 误解释截断"
  的整个缺陷族，不只本例。

**验证命令**：
- 红：worktree 未修复态 `uv run python tests/run_ac.py --only k_web`
  （--only 过滤已实测存在；红证据须含 A1/A2 两行 FAIL）。
- 绿：`uv run python tests/run_ac.py --only k_web` 全绿。
- 最高 tier（合并门槛）：全量 `uv run python tests/run_ac.py` → 511/511。
- 一次性真机（非持久测试，环境依赖 node）：
  `uv run python -c "from agent_kanban.api.web import board_shell, detail_shell; open('/tmp/opencode/m1-6/board.js','w').write(board_shell())"`
  抽 `<script>` 块 → `node --check`；detail 同法（需 requirement_id 参数，
  用 detail_shell 实际签名）。重跑规格：node v24.21.0 + 上述命令。

**commit**：语义化单 commit（转义修复 + 防线断言 + 计划文档同 commit；
commit message 含红绿证据路径与不修清单登记引用）。
**tracked 交付物（plan 审 P2-3 折入，repo 惯例每 M1-x 一份）**：
`docs/ops/m1-6-verification.md`（P5 建：判据/红绿证据索引/511 基线/
一次性 node --check 真机重跑规格/盲区/不修清单/流程审计记录），
tier-2 合并门槛 = 全量全绿 + 本文档 + git ls-files 全 tracked。

### T2: 深潜页终态操作（archive/delete）成功后回看板（plan delta，user 冒烟第二轮）

**起因（user 原话，2026-10-26）**：
- delete：删除成功后停留深潜页渲染"任务不存在（可能已被人删除）"——归因错
  （暗示他人删的，实为本人刚删）+ 不回看板。
- archive："点了archive,毫无响应（实际已经archive了）……既然点击了archive,就不是期许
  还继续看详情。后续要看详情也应该是去archive中查看。"
- 共同机制（单根因）：`handleOpResult` 成功路径统一 `flash("操作成功"); load()` 重拉
  ——delete 重拉拉到 404（死页）；archive 重拉拉到 ARCHIVED 态（页面观感几乎不变 =
  静默成功）。doOp(archive) 与 doDelete 共用该路径（web.py:490/494/503-513）。

**契约三锚**：
1. **契约源**：user 裁决（上引原话两轮）。M1-5 spec 对终态操作后的导航未作规定，
   但 `docs/web.md:42/49` 逐字记载旧行为（成功 -> `load()` 重拉 / delete 后页面转
   "任务不存在"）——T2 按 user 第二轮裁决变更该旧契约，**web.md:42/49 同步为 T2
   交付物**（plan 审 P1-2 折入；"spec 静默"措辞已纠正）。板上任务 f49ce945 验收锚
   a2（原"archive 后行为不变（重拉显示 ARCHIVED 态）"，建任务时先于 user 第二轮
   反馈写成）被 user 原话"点了archive……不是期许还继续看详情"**取代**，锚已按
   更新行为改（plan 审 P1-1 折入，板上留 note）。"detail 404 友好文案"契约保留
   给深链场景（直接访问不存在的任务），不受本修复影响。业务规则无变化（④ 不在；
   纯 UI 导航语义，user 明示）。
2. **代码锚点**（worktree HEAD 实测）：
   - `src/agent_kanban/api/web.py:490-493` doOp（archive 按钮 data-op）与
     `:494-502` doDelete，共用
   - `:503-513` handleOpResult，成功路径 = :511-512 `flash("操作成功", false); load();`
     （修点）
   - `:518` 初始 `load()` 与 `:520` `es.onmessage = load`（SSE 重拉）——保留不动
   - `:372` 404 友好文案——保留（深链语义正确）
   - `:457` archive 按钮 disabled 态（ARCHIVED 时禁用）——保留
3. **逐例期望**：
   - 基线：T1 后全量 511/511（已实测）。
   - 新增 2 条断言（T2-A3/A4，正负独立，plan 审 P2-2 折入：红诊断可区分"缺导航"
     vs "残留 load()"）在 T1 HEAD 上必须红。红证据先采集（t2-red.log）。
   - 修复后全绿：513/513（511 + 2）。
   - 一次性真机：两壳 script 块 node --check 重跑（node-check-2.log；board 壳 T2
     未动，为防线完整性同跑）。

**修复（单产品位 1 处）**：
- `web.py:511-512`：`flash("操作成功", false); load();` -> `location.href = "/";`
  （终态操作成功即回看板，看板即反馈：任务消失/转 ARCHIVED。失败路径不动：
  flash 错误 + 停留。archive/delete 双调用方同享单点，无需分支——当前 data-op
  仅 archive，doOp 泛化性风险见不修清单）

**T2-A3/A4 断言（k_web 组 +2 例）**（plan 审 P2-2 折入：正负拆独立断言）：
- 抽取法（plan 审 P2-1 折入，探针实证）：自 `async function handleOpResult`
  行起，至**首个列 0 的 `}`（非缩进 `}`）**止——lstrip 形态（匹配缩进 `}`）会
  在 if 闭合处截断块，T2 后假红卡死。
  - A3（正）：块含 `location.href = "/"`（成功回看板）
  - A4（负）：块不含 `load()`（终态成功后不重拉）
- oracle 判据：① 独立于实现——锚 = user 行为契约（终态操作后离开深潜页）+
  "导航 vs 重拉"互斥形态，非实现镜像；② 反证位——T1 HEAD 先红留档（A3 红=缺
  导航，A4 红=残留重拉，红因各自可辨）；③ 对抗变体——A4 防"加了导航但保留
  load() 重拉"的半修复态。
- 形态耦合登记（同 A1 级）：锚函数块列 0 边界形态；壳格式风格变化需同步。
- 运行时归因：真机验收 = user 浏览器复测（archive->看板 / delete->看板，服务更新
  后）；持久浏览器 e2e 归 CI 批次（board task 86dfe88f，盲区登记不变）。
- A2 联动：新行 `location.href = "/";` 双引号计数偶，A2 无假阳（探针预验）。

**验证命令（T2）**：
- 红：`uv run python tests/run_ac.py --only k_web`（T1 HEAD，A3 FAIL 行留档
  t2-red.log）
- 绿：同命令 25/25（t2-green.log）
- 最高 tier：全量 513/513（full-rerun-2.log）
- 一次性真机：两壳 node --check（node v24.21.0；node-check-2.log 格式升级：
  记录被检文件路径与抽取命令，折入结果审勘误 1）

**commit**：T2 独立 commit（修复 + A3/A4 + plan delta + web.md:42/49 同步同
commit），与 T1 同分支，user 一次性裁决合入。

### T3: 深潜页展示任务 description（plan delta，user 冒烟第三轮）

**起因（user 原话，2026-10-26）**："我手动创建了一个任务：面向Gmail的邮件AI
Agent调研，写了详细的描述，但是我进入详情，完全看不到了。"
**板上任务**: 07755135（三锚 a1/a2/a3 与本节交付物一一对应；plan 审 P2-1 折入）。
**机制**（单点，证据坐实）：深潜壳 render() 无 description 展示位——payload 有
字段（9acea09b7 JSON 实测 description=174 字）但 JS 不渲染；全 web.py 仅新建
表单引用 description（:278）。缺口溯源：M1-5 spec:126"深潜页零改动"→ 缺口早于
M1-5（M1-2 设计缺口，**非回归**）；web.md 深潜页契约行同样未列 description。

**契约三锚**：
1. **契约源**：user 原话 + web.md 深潜页契约行（记载现有内容清单、无
   description——T3 新增该节并同步 web.md，同 P1-2 纪律）；spec:126 零改动
   证明缺口溯源（登记）。业务规则无变化（④ 不在；纯展示补全）。
2. **代码锚点**（worktree HEAD 实测）：`web.py:380-389` render() 头部区
   （插入位：history_note 行后、awaiting_human 横幅前）；`esc()` 既有（:386
   标题同款）；`sec`/`wide` 样式类既有。
3. **逐例期望**：
   - 基线：T2 后全量 513/513。
   - 新增 1 条断言（T3-A5）在 T3 前 HEAD 上必须红：深潜壳无 description 渲染。
   - 修复后全绿：514/514（513 + 1）；k_web 26/26。
   - 一次性真机：两壳 node --check（node-check-3.log）。

**修复（单产品位 1 行）**：
- `web.py:389` 后（render() 内）：
  `if (s.description) html += "<div class='sec wide'><h2>描述</h2><div style='white-space:pre-wrap'>" + esc(s.description) + "</div></div>";`
  （esc 必带——description 是用户输入，全壳转义纪律同 ;pre-wrap 保留用户换行;
  空 description 不渲染空节）

**T3-A5 断言（k_web 组 +1 例）**：
- 正：detail 壳含描述节且以 esc 渲染（字面 `esc(s.description)` + `描述</h2>`
  同在）——esc 在场同时覆盖 XSS 面（无转义渲染=注入向量，全壳无先例）。
- 形态耦合登记（同 A1 级）。运行时归因 = user 浏览器复测（Gmail 任务详情页
  见描述全文）；浏览器 e2e 归 CI 批次（86dfe88f）。
- A2 联动：新行双引号计数偶（探针预验）。

**验证命令（T3）**：
- 红：`--only k_web`（T3 前 HEAD，A5 FAIL，t3-red.log）
- 绿：26/26（t3-green.log）；最高 tier 全量 514/514（full-rerun-3.log）
- 一次性真机：两壳 node --check（node-check-3.log）

**commit**：c3（修复 + A5 + plan delta + web.md 深潜页契约行同步），与 T1/T2
同分支，user 一次性裁决合入。

## 影响面

- ① 对外接口/工件格式/数据迁移：不在（REST/MCP 契约零改动；送出壳的 JS
  内容从"损坏"变"有效"，非接口形状变化）
- ② 新入口/信任边界/凭据/反序列化：不在
- ③ 热路径/资源敏感：不在（壳为静态字符串）
- ④ 业务规则变化：不在 → Phase 0.5 不触发（T1 纯缺陷修复，行为回归 spec 原意；
  T2 为 user 明示的 UI 导航语义，spec 静默已登记于 T2 节，非业务规则；
  T3 为纯展示补全，无既有契约（spec 缺口登记于 T3 节），非业务规则）

## 单向门检查

无（无存储格式/对外 ABI/数据迁移/已发版对外契约变化；MCP/REST 契约不动）。

## 不修清单

- G12（`docs/adr/0000-known-gaps.md` G12 行，list_awaiting null 文本泄漏，
  修复单独立项，user 已裁决归看板任务管理）。
- `web.py:363` `replace(/^\\/requirements\\//, "")`：Python 解释后送出 `\/`，
  是正确 JS 正则转义，不动。
- live 指示器文案机（on→"实时"/off→"重连中"/初始"连接中"）：设计内状态机，
  非本批缺陷；user 报"连接中"恒停的根因是 JS 零执行，非文案问题。
- 盲区"浏览器 JS 无自动化"：本批只落静态解析防线（A2）；真浏览器 e2e
  （Playwright 等）归 CI 批次——user 已裁决该事项作为看板任务统一管理
  （本批次外立项）。
- 容器 8765：user 裁决（2026-10-26）先行部署修复分支（worktree 构建镜像，
  compose 原配置重建，现网壳 node --check PASS）；合入 main 后从 main 重建
  收敛（内容相同）。
- (T2) `web.py:372` "任务不存在（可能已被人删除）"：深链语义（直接访问不存在
  的任务）正确，保留；修复后"本人刚删"场景不再到达该文案。
- (T2) SSE 事件与导航的 micro-race（plan 审 P2-3 措辞修正）：delete 不写事件
  （spec §4.3），无"delete 事件渲染 404"的 race；location.href 生效前 archive
  事件触发 load() 显示 ARCHIVED 态（非 404）；真 404 闪现仅由 delete 后无关事件
  触发重拉产生（窗口 < fetch 往返，通常页面先卸载）；登记不修。
- (T2) `load()` 函数本体与初始（:518）/SSE（:520）调用点、archive 按钮 disabled
  态（:457）、board 壳：不动（本问题仅 detail 壳）。
- (T2) doOp 泛化性：未来若新增非终态操作复用 handleOpResult 会被迫回看板——
  届时成功路径需加参数；维护面登记，本批不修。
- (T3) board 卡片紧凑行不展示 description：看板定位概览，深潜页为阅读入口，
  本任务范围仅深潜页。

## 验证入口与 tier

- 入口：`uv run python tests/run_ac.py`（本机；开发机即构建机）。
- tier 定义：依 tracked 文档 `docs/ops/m1-5-verification.md`——tier-2 = 全量
  run_ac（最高 tier = 合并门槛）。
- 基线数字：509/509（main@1f1f47a）；T1 后 511/511（已实测）；T2 后 513/513；
  T3 后本批期望 514/514。
- 当轮产物目录（正典，2026-10-26 起）：/home/shih/.tmp-ak-m16/ —— m1-6/:
  t2-red(23/25) / t2-green(25/25) / t3-red(25/26) / t3-green(26/26) /
  node-check-final(两壳 PASS，含被检路径+抽取命令) / full-rerun-3.log(514/514) /
  result-review.md(T1 结果审) / result-review-plan-t3.md / result-review-b.md
  (整分支结果审)；full-rerun-2.log(513/513) 在父目录。
- 事件（plan 审 P4b 勘误 2 折入）：/tmp usrquota 满触发系统清扫，原
  /tmp/opencode/m1-6/logs/ 十二份全灭（T1 四份 / T2 首轮两份 / node-check-2）。
  T1 证据 = result-review.md 审者独立复现记录（红绿双态+阴性对照+字节枚举）；
  T2 红绿 = stash 重建件（整分支结果审以 git 对象 53ffc63 独立加载复现，与机制
  一致）。重建链详情 = docs/ops/m1-6-verification.md。
- **适配登记**：目标仓无 AGENTS.md；验证入口/tier/基线以 tracked 的
  docs/ops/m1-5-verification.md + docs/adr/0000-known-gaps.md 为正典。

## 环境与已知 flake

- python 3.14.4（.venv）；node v24.21.0（仅一次性真机，非持久测试依赖）。
- 已知 provider flake：subagent 回报生成阶段偶发
  "OpenAI Chat received content after the finish reason"（M1-5 登记 3 次，
  工作产物完整时以现场验收不重派）。
- /tmp tmpfs usrquota 接近满时：`TMPDIR=/home/shih/.tmp-ak-m15` 执行
  （不改变断言语义，M1-5 已核验）。
- 陷阱库（本批通用七条全文注入派发；仓库侧：G12 签名 + TMPDIR 约束 +
  provider flake 签名如上）。
