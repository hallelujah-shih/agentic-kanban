# M1-6: board 壳 JS 转义修复 + 壳解析防线

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

## 原子任务（单任务批次）

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

## 影响面

- ① 对外接口/工件格式/数据迁移：不在（REST/MCP 契约零改动；送出壳的 JS
  内容从"损坏"变"有效"，非接口形状变化）
- ② 新入口/信任边界/凭据/反序列化：不在
- ③ 热路径/资源敏感：不在（壳为静态字符串）
- ④ 业务规则变化：不在 → Phase 0.5 不触发（纯缺陷修复，行为回归 spec 原意）

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
- 容器 8765 当前跑含 bug 代码：本批合并后由 user 裁决重建（docker compose
  up -d --build），不在本批内动生产部署。

## 验证入口与 tier

- 入口：`uv run python tests/run_ac.py`（本机；开发机即构建机）。
- tier 定义：依 tracked 文档 `docs/ops/m1-5-verification.md`——tier-2 = 全量
  run_ac（最高 tier = 合并门槛）。
- 基线数字：509/509（main@1f1f47a）；本批期望 511/511。
- 当轮产物目录：/tmp/opencode/m1-6/logs/（t1-red / t1-green / full-rerun /
  node-check 四份）。
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
