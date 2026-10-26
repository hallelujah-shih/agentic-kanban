# G12 修复：list_awaiting 对已清 marker 任务泄漏（null 文本）

**基分支**: main @ ab48e4b（worktree `.worktree/g12-list-awaiting`，分支 `g12-list-awaiting`）
**档位**: 全六门（单向门：存量数据回填 = 数据变更，P2 升全量四层审查含回滚/兼容矩阵）
**日期**: 2026-10-26
**板上任务**: 3d2f99e442694c19985a0231d773403b（a1 过滤层不再泄漏 / a2 存量处理方案裁决并落地）

## 背景与机制结论（带证据）

G12（known-gaps 2026-10-26 登记，M1-5 T2 域外发现）：`list_awaiting` 放行已清 marker 任务。

- **机制**（本批主循环代码核死）：
  - `models.py:53`：`awaiting_human: Mapped[dict | None] = mapped_column(JSON, nullable=True)`——
    裸 `JSON` 类型，SQLAlchemy `none_as_null` 默认 **False**：显式绑定 None 时写 **文本 `"null"`**，
    非 SQL NULL。
  - 唯一清 marker 路径 `state_machine.py:65-67`：transition 到非 BLOCKED 时
    `update(Requirement)...values(awaiting_human=None)` → 落库文本 `"null"`。
  - 泄漏点 `operations.py:949`（list_awaiting）：`where(Requirement.awaiting_human.isnot(None))`
    → SQL `awaiting_human IS NOT NULL`，命中 `"null"` 文本 → 已清任务泄漏（awaiting_human 反序列化
    归一 None 输出）。
  - 可见面（detail/board/壳）不受影响 = 反序列化归一 None 的**侥幸**，非设计；SQL 层该列过滤引用
    全仓仅 list_awaiting 一处（grep 核过），故修好编码后 `IS NOT NULL` 谓词即恢复健全，**谓词本身
    不改**。
  - 复现（known-gaps 原文）：claim -> mark_blocked -> approve -> MCP list_awaiting。
- **user 裁决（2026-10-26，本批开工前提问，选项含归因/对照/裱糊-根治标注）**：
  1. **根治**：模型 `JSON(none_as_null=True)`（清除态=真 SQL NULL）+ 存量 `"null"` 文本行回填。
  2. 回填生效点 = **启动自愈**（走 `db.py` `ensure_schema()` 既有幂等初始化模式，生产容器下次
     重启自动跑，user 零操作；回滚安全=代码回退后数据不损）。
  - 被否选项（裱糊）：谓词补 `isnot("null")`——无迁移但把 `"null"` 编码 pin 死查询层，
    同构问题在一切未来按该列过滤处复发（写放大），无退役条件。

## 契约三锚

1. **规范逐字原文**：
   - 板上 3d2f99e4 description（逐字）："谓词 IS NOT NULL 匹配 JSON 列 null 文本；detail/board
     可见面不受影响。修复选项见 known-gaps G12。"
   - 验收项 a1（逐字）："list_awaiting 不再返回 awaiting_human 为 null 的任务"；
     a2（逐字）："存量 null 文本行处理方案裁决并落地"（裁决已落，见背景节）。
   - `docs/adr/0000-known-gaps.md` G12 行（逐字摘）："`awaiting_human` JSON 列 none_as_null=False，
     清 marker 存文本 'null'，SQL 谓词 `IS NOT NULL`（operations.py:918）匹配该文本 -> approve/
     abandon/archive on BLOCKED 后任务仍出现在 list_awaiting（awaiting_human=null）"。
     （行号 :918 为 M1-5 时点，现主代码 = operations.py:949，行号漂移归簿记。）
2. **代码锚点**（main@ab48e4b 实测）：
   - `src/agent_kanban/models.py:53`（列定义，改造点 1）。
   - `src/agent_kanban/services/state_machine.py:65-67`（唯一清 marker 路径，不改）。
   - `src/agent_kanban/services/operations.py:949`（list_awaiting 谓词，不改——编码修好后自健全）。
   - `src/agent_kanban/db.py:104-134` `ensure_schema()`（幂等建表 + seq 种子；回填挂接点，
     改造点 2；同函数既有模式 = 读引擎检查 / 写引擎变更 / 无事不写）。
   - `tests/ac_lib.py:38` `new_db()` / `query(db, sql)`（直读 DB 文件）/ `MCP` 子进程类
     （服务起法 = 子进程，`ensure_schema` 每次服务启动跑）。
   - 套件基线 514（docs/ops/ci-verification.md 实钉；本批增例后基线移动，T2 更新文档计数）。
3. **逐例期望**：
   - run_ac 基线 514 → **514+N**（N = 本批新增 ok() 断言数，T1 绿跑实测钉死，T2 折文档）；
     既有用例零删改（含 k_archive:163 的 G12 注释——措辞更新为已 pin 指向，不算改断言）。
   - 红（修复前）：claim->mark_blocked->approve 后 list_awaiting **含**该任务（awaiting_human=None
     输出）+ 原 DB 列 = 文本 `"null"`（raw query 证）。
   - 绿（修复后）：同序列 list_awaiting **不含**该任务 + 原 DB 列 = **SQL NULL**（机制断言，
     非仅过滤结果）；存活 marker（claim->mark_blocked 未清）仍出现在 list_awaiting 且带完整
     marker 对象（正向守卫，防过度过滤）；启动自愈：预置存量 `"null"` 文本行 + 存活 marker 行 ->
     服务重启 -> `"null"` 行变 SQL NULL、存活行**逐字节不动**（对抗守卫，精确匹配判据）。
   - 全量套件 514+N 全绿 = 最高 tier。

## oracle 版本（机械预检）

- python 3.14.4（worktree .venv，T 前由派发者 `uv sync --frozen` 重建——worktree 不共享主仓
  untracked，CI 批次 T2 先例）；node/docker 面本批不涉及。
- 生产容器 `agentickanban-kanban-1`（compose，host 网络，8765 健康）**全程禁碰**——回填经
  启动自愈，user 下次重部署自动生效，本批不在生产库执行任何写操作。

## 影响面

- ① **命中（单向门：存量数据变更）**：回填 = 单条精确匹配 UPDATE（`awaiting_human = 'null'`
  文本行 -> SQL NULL）。**回滚/兼容矩阵**：
  - 数据回滚性：UPDATE 只触 `"null"` 文本（真实 marker 恒为 `{...}` JSON 对象文本，不可能精确
    匹配 4 字节 `null`）；回滚 = 反向 UPDATE（`SET awaiting_human='null' WHERE awaiting_human IS
    NULL AND <曾为 null 文本>`——不可精确逆推，但**无需逆推**：新代码下 SQL NULL 与 `"null"` 文本
    语义同义（都=已清），旧代码读 SQL NULL 同样归一 None（JSON 反序列化对 NULL 列值返回 None），
    唯一差异 = 旧代码谓词 `IS NOT NULL` 对 SQL NULL 正确排除（泄漏消失=旧行为改善非破坏）。
  - 代码回滚性：模型行回退后，SQL NULL 行读写均正常；新清除写回 `"null"` 文本（旧行为恢复）。
    无 DDL 变更（`none_as_null` 是绑定行为非列类型，SQLite 列 DDL 不变，`tests/alembic_diff.py`
    口径无漂移，**不加 alembic revision**——生产建表路径 = create_all/ensure_schema，非 alembic
    upgrade）。
  - 前向兼容：回填后不变量 `awaiting_human IS NULL ⇔ 无存活 marker` 对新旧数据同真。
  - 生效窗：merge 后到生产容器下次重启前，生产库泄漏行为不变（存量 `"null"` 行仍在、旧镜像
    代码未变）——user 知情项，随 T2 交接。
- ② 不命中（无新执行环境；回填跑在既有服务进程既有写引擎上）。
- ③ 不命中（ensure_schema 每次启动多一条 COUNT 读检查（读引擎，不抢写锁），COUNT=0 时零写——
  稳态零成本；非热路径）。
- ④ 命中（**业务可见行为变化**：list_awaiting 结果集收缩——已清任务不再出现）。
  **BCD 判定**：变化方向 = 消除已登记缺陷（G12），向 known-gaps 声明的期望行为回归，
  非新增业务规则；无派生状态/事件/契约形状变化（list_awaiting 输出形状不变，仅结果集正确化）。
  按 strict-sdd-loop 判据"客户或用户可见语义变化"属**有界路径**（单查询结果集修正，无跨模块
  契约），BCD 不触发，本 plan 三锚即契约。

## 原子任务

### T1: 红复现 + 修复（模型编码 + 启动自愈回填）

**Files**: Modify `src/agent_kanban/models.py:53`（1 行）、`src/agent_kanban/db.py`
（ensure_schema 挂接 + 回填函数）、`tests/ac_cases_k.py`（新增 `k_g12()` + k_archive:163 注释
指向更新）、`tests/run_ac.py`（注册 k_g12）。

**改动契约**：
1. `models.py:53` → `mapped_column(JSON(none_as_null=True))`（类型注释同步）。
2. `db.py`：新增 `async def heal_null_text_markers() -> int`（命名随执行者风格，语义固定）：
   - 读引擎 `SELECT COUNT(*) FROM requirements WHERE awaiting_human = 'null'`，
     **COUNT=0 直接返回 0（零写）**；
   - COUNT>0 → 写引擎 `UPDATE requirements SET awaiting_human = NULL WHERE awaiting_human = 'null'`，
     返回 rowcount。
   - `ensure_schema()` 在 seq 种子后调用（幂等：稳态 COUNT=0，零写零锁）。
   - 精确匹配判据注释一行：真实 marker 恒为 JSON 对象文本，4 字节 `null` 只可能来自旧编码清除。
3. **不改**：state_machine 清除路径、list_awaiting 谓词、任何 alembic 文件。

**oracle（红先于绿，序不可换）**：
- 红 R1（复现，修复前 HEAD 态）：`k_g12` 先行落盘（只含泄漏断言部分），`uv run --no-sync
  python tests/run_ac.py --only k_g12`（或既有单跑口径）→ **必须红**：approve 后
  list_awaiting 含该任务（red 输出留档：泄漏行 + raw query 列值 `"null"`）。
- 绿 G1：修复后同命令 → 全绿；断言集（k_g12 完整体）：
  1. 序列 claim→mark_blocked→approve 后 list_awaiting **不含**该任务（a1 字面）；
  2. raw query：该行 awaiting_human = **SQL NULL**（`IS NULL` 谓词直查，机制断言）；
  3. 正向守卫：另一任务 claim→mark_blocked（存活）→ list_awaiting **含**且 marker 对象
     完整（kind/reason 在场）；
  4. 启动自愈：新 DB 起服务（schema 建）-> 停 -> raw 写一行 `awaiting_human='null'`
     （忠实存量态）+ 一行存活 marker -> 再起服务（ensure_schema 跑）-> raw 查：`'null'` 行
     = SQL NULL、存活行**未变**（raw 文本比对）-> list_awaiting 只含存活行；
  5. 自愈零写判据（可选）：稳态（无 `"null"` 行）下 ensure_schema 不产生该 UPDATE
     （执行者按可观测方式定，如 sqlite 日志或 rowcount 断言，定不下来降登记不硬造）。
- 绿 G2（回归）：全量 `run_ac` = 514+N 全绿（N 实测钉死回报；k_archive:163 注释更新后
  k 组全绿）。

**验证命令**: 见 oracle R1/G1/G2（argv 以派发 brief 为准）。
**Commit**: `fix: G12 list_awaiting 泄漏——awaiting_human 清除态改真 SQL NULL（none_as_null=True + 启动自愈回填存量 null 文本）`

### T2: known-gaps 收口 + 文档基线更新 + 板上 note

**Files**: Modify `docs/adr/0000-known-gaps.md`（G12 行状态 -> 已修复，日期 + 本批指针）、
`docs/ops/ci-verification.md`（514 -> 514+N 计数更新，全部出现处）、板上 3d2f99e4 note。

**内容契约**：
- known-gaps G12 行：档位列不动，处置列改"已修复（2026-10-26，g12-list-awaiting 分支；
  根治=none_as_null=True+启动自愈回填，user 裁决）"，保留机制描述（历史价值）。
- ci-verification.md：tier 行/重跑规格/红绿正典中 514 计数全量更新为实测新基线 + 本批红绿
  一句话索引（不新立验证文档——本批规模不立 m1-x-verification 级文档，known-gaps 行 +
  ci-verification 计数更新即正典收口；**若 plan 审认为需独立验证文档，按审者意见升**）。
- 板上 note：修复机制 + 生产生效窗（下次重部署重启后自动回填，此前生产行为不变）+
  存量行数未知（自愈幂等，0 行也安全）。

**oracle**: known-gaps 行与 ci-verification 计数与当轮实测一致；板上 note 落账。
**Commit**: `docs: G12 收口（known-gaps 已修复 + CI 基线计数更新 + 生产生效窗登记）`

## 不修清单

| 项 | 理由 | 登记位置 |
|---|---|---|
| list_awaiting 谓词（isnot(None)） | 编码修好后自健全，加 isnot("null") 即把旧编码 pin 回查询层（= 被否裱糊选项的残留） | 本 plan 背景节 |
| state_machine 清除路径 | `values(awaiting_human=None)` 语义正确，错在类型绑定行为；改路径=绕过根因 | 本 plan 机制节 |
| alembic revision | 无 DDL 变更（none_as_null 非列类型）；生产建表路径 = create_all/ensure_schema | 影响面 ① 回滚矩阵 |
| detail/board/壳可见面 | 本就正确（反序列化归一），零改动 | 契约三锚.2 |
| 生产库本批执行任何写 | 回填=启动自愈，user 重部署时自动跑；禁 agent 触碰生产数据（单向门纪律） | oracle 版本节 |
| 独立验证文档（m1-x 级） | 批次规模 = 2 文件代码改动 + 注释级文档更新；known-gaps 行 + ci-verification 计数即正典 | T2 契约 |
| e2e 层覆盖 list_awaiting | list_awaiting 是 MCP 面（无 web 壳消费面——壳用 /board 的 attention_ids，Q2 待裁决）；MCP 面由 run_ac 覆盖 | 本表 + 板上 Q2 关联 |

## 执行纪律

- 同仓未提交改动互斥 → T1/T2 严格串行，每任务红绿齐备后 commit。
- 派发 prompt 必含：worktree 路径、基 ab48e4b、本 plan 路径、陷阱库全文、产物目录
  /home/shih/.tmp-ak-m16/g12/（**禁写 /tmp 作证据**）；**worktree .venv 须先
  `uv sync --frozen` 重建**（CI 批次先例：worktree 不共享主仓 untracked）。
- **纯测试断言时序不变量（CI 批次 P6 审 A1 纪律注记，本批生效）**：先落红测试采红证据 ->
  实现 -> 绿 -> commit。
- 域外发现（含生产 DB 形态差异、ensure_schema 并发窗新风险）强制回报单列，禁静默绕过。
- 证据保全：每轮红绿日志 cp 落产物目录后再重跑。
