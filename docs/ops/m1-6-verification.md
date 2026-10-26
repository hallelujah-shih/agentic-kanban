# M1-6 验证记录（board/detail 壳修复与防线：T1 转义 P0 + T2 终态操作导航 + T3 深潜 description 展示）

位置: docs/ops/m1-6-verification.md（tracked，m1-6-board-shell-js 分支）
批次: M1-6（T1 board 壳 JS 转义修复 + T2 终态操作成功回看板 + T3 深潜页 description 展示），全六门
基线: main @ 1f1f47a（worktree .worktree/m1-6-board-shell-js，分支 m1-6-board-shell-js）；commit 53ffc63(T1) / c236eed(T2) / db615aa(T3) + 本文档 commit（docs-only，代码态=db615aa）
计划: docs/superpowers/plans/2026-10-26-board-shell-js-escape.md（T1/T2/T3 三节 + 不修清单 + 影响面/验证入口；plan 盲审三轮：T1 APPROVE / T2 APPROVE-WITH-FIXES 2P1+3P2 全折入 / T3 APPROVE 2P2 折入，同审者续接）
契约源: T1 = spec:71（split 字面契约）+ user 冒烟 P0；T2 = user 原话两轮（delete 死页归因错 / archive 静默成功）+ web.md:42/49 旧行为同步；T3 = user 原话 + web.md 深潜页契约行 + spec:126 缺口溯源（M1-2 设计缺口非回归）。无业务规则变化（④ 不在），BCD 不触发。

## oracle 版本（机械预检）

- python 3.14.4（.venv）；node v24.21.0（仅一次性真机，非持久测试依赖）
- harness argv: `uv run python tests/run_ac.py`（工作目录 = worktree 根）；新用例 A1-A5 属既有 k_web 组，经 `--only k_web` 单跑
- tier 定义: 依 tracked 文档 docs/ops/m1-5-verification.md——tier-2 = 全量 run_ac（最高 tier = 合并门槛）
- 基线: 509/509（main@1f1f47a，承 M1-5 P5 复验，本批未重推）

## 判据（逐字引自契约源，oracle 独立于实现）

- T1（spec:71 一条锚 + JS 物理不变式）: board 壳 `split("\n")` 送出的必须是 2 字符（反斜杠+n）字面，非真换行；两壳 `<script>` 块逐行双引号配对（字符串字面量禁裸换行）。
- T2（user 第二轮原话）: 终态操作（archive/delete）成功即离开深潜页回看板（`location.href = "/"`）；成功路径不得残留 `load()` 重拉（delete 重拉=404 死页归因错，archive 重拉=静默成功）。失败路径契约不变：内联 `{code,message}` + 停留。深链 404 友好文案（直接访问不存在的任务）语义保留。
- T3（user 第三轮原话）: 深潜页以 esc 转义渲染 description 全文、保留用户换行（pre-wrap）；空 description 不渲染空节。

## 结果（主循环复验）

- tier-2: 全量 **514/514 PASS**（full-rerun-3.log，509 既有零回归 + 5 新增）。
- k_web 组: 21 -> 23(T1) -> 25(T2) -> 26/26（T3）；计数链 509+2+2+1 与各日志结果行一致。
- 一次性真机: node --check 两壳 script 块双 PASS（board 164 行 / detail 194 行，node-check-final.log 含被检路径+抽取命令）。

## 红绿证据（正典 /home/shih/.tmp-ak-m16/）

| 阶段 | 红 | 绿 | 说明 |
|---|---|---|---|
| T1 | t1-red 21/23（恰 A1/A2 红） | t1-green 23/23，full 511/511 | **原始日志随 /tmp 清扫灭失**；证据 = result-review.md 审者独立复现记录（红绿双态 + 阴性对照：还原真换行 rc=1 精确报 line 147 + 全壳字节枚举） |
| T2 | t2-red 23/25（A3 缺导航 + A4 残留 load()，红因可辨） | t2-green 25/25，full-rerun-2 513/513 | 红绿 = **stash 重建件**（清扫后 `git stash push web.py` 回 T1 态重跑）；整分支结果审以 git 对象 53ffc63 独立加载（非采信重建件）复现 A3/A4 红因与 A1/A2 绿，与机制逐条一致 |
| T3 | t3-red 25/26（仅 A5 红） | t3-green 26/26，full-rerun-3 514/514 | 原生件全在场 |

- 在场产物（/home/shih/.tmp-ak-m16/）: m1-6/{t2-red,t2-green,t3-red,t3-green,full-rerun-3.log,node-check-final.log,result-review.md,result-review-plan-t3.md,result-review-b.md,review-probe-p4b/} + full-rerun-2.log（父目录）。

## /tmp 清扫事件与证据重建链（provenance）

- 2026-10-26 /tmp tmpfs **usrquota 满触发系统清扫**（13G -> 152M）：/tmp/opencode/m1-6 全灭——T1 四份日志（t1-red/t1-green/full-rerun/node-check）、T2 首轮红绿与 node-check-2、两轮 plan 审报告、commit msg 文件、主循环 ledger。此前同因已致 T2 首轮全量中断（sqlite disk I/O error，非测试红）。
- 幸存面: worktree 代码（在 /home）零影响；清扫时在跑的 T2 全量因 TMPDIR+日志已绕行 /home 而完整落档。
- 重建策略: T1 已合入 c1 不可回滚重跑红 -> 证据取 result-review.md（审者当时已独立复现全部红绿 + 阴性对照，重建前完成）；T2 代码可回滚 -> stash 重建红绿；T3 天然先红。
- 防再发: 本批一切证据/ledger 落 /home/shih/.tmp-ak-m16/（quota 免疫），**禁再写 /tmp**；重跑规格（下节）保证任何丢失证据可再生。

## 重跑规格

```
cd /home/shih/test/AgenticKanban/.worktree/m1-6-board-shell-js
TMPDIR=/home/shih/.tmp-ak-m16 uv run python tests/run_ac.py                # 全量（~5-6 min）
TMPDIR=/home/shih/.tmp-ak-m16 uv run python tests/run_ac.py --only k_web   # 单组
# node --check 两步链（照抄单条必红，须分步）:
# 1) uv run python 抽 board_shell()/detail_shell() 的 <script> 块（正则 <script>(.*)</script> re.S）落 .js
# 2) node --check <各 .js>（node v24.21.0）
# T2 红重建: git stash push src/agent_kanban/api/web.py（回 T1 态）-> --only k_web 红 -> git stash pop -> 绿
```

- TMPDIR 绕行不改变断言语义（M1-5 已核验: new_db 走 tempfile.mkdtemp 跟随 TMPDIR，无硬编码 /tmp 路径、无路径断言）；/tmp usrquota 慢性紧张，全量若 disk I/O error 即切换，属环境面非产品面。

## 盲区登记

1. **真浏览器运行时**（沿 M1-5 盲区 1）: 导航 UX、SSE 重连/token 真机传播、Gmail 任务描述渲染、空 description 不占位——归 user 浏览器复测（web.md 冒烟 checklist）+ 持久 e2e（板上 86dfe88f CI 批次）。
2. **静态防线固有边界**: A2 假阴（破损行双引号恰偶数会漏）；A5 盲区 (a) esc 字面在场但注入点另取未转义值的诡计形态、(b) esc() 函数体未来被改坏（断言钉文本不钉实现，实现健全性已静态核）；A1 只钉 :279 本位，未来新增转义位不自动覆盖（仅 A2 部分覆盖）。真实防线 = esc 实现（既有）+ e2e（86dfe88f）。
3. **SSE-导航 micro-race**: delete 不写事件（spec §4.3），archive 事件触发 load() 显示 ARCHIVED 态（非 404）；真 404 闪现仅 delete 后无关事件触发重拉，窗口 < fetch 往返（通常页面先卸载）。登记不修。
4. **基线 509 内部既有断言**承 M1-5 P5 复验，本批未重推。
5. **容器 8765 镜像构建/部署链**未验证（user 裁决：先行部署修复分支，合入后从 main 重建收敛）。

## 不修清单（plan 全量 10 项，P4b 逐一核未动）

G12（单独立项 3d2f99e4）/ web.py:363 `\\/`（正确形态，不动）/ live 指示器文案机 / 浏览器 e2e（归 86dfe88f）/ 容器部署（user 裁决）/ 深链 404 文案 :372（深链语义正确）/ load() 本体与初始+SSE 调用点 / SSE micro-race / doOp 泛化性（未来非终态操作复用需加参数，维护面登记）/ board 卡片紧凑行不展示 description（看板定位概览，深潜为阅读入口）。边缘登记：whitespace-only description 渲染近空节（可忽略，数据异常非本批引入）。

## Verdicts

- T1: split 换行以 2 字符字面送达（全壳字节枚举仅 1 个反斜杠）；两壳 node --check PASS；A1/A2 防线进套件。P0 消除（看板恒"加载中"根因 = 整 script 块 SyntaxError）。
- T2: 终态操作成功回看板（单点 location.href="/"，双调用方共享）；失败路径 flash+停留完好；flash() 无死代码；token 经 sessionStorage 传播，同域导航不丢（非 localhost 无回归）；web.md:42/49 同步新契约；板上 f49ce945 锚 a2 按 user 第二轮裁决更新（plan 审 P1-1）。
- T3: 描述节 esc+pre-wrap、空不占位；`s.description` 数据面闭环（summary payload 实测含字段，9acea09b7 174 字在场）；web.md 深潜页契约行同步；板上 07755135 三锚对应。
- 回归: 509 既有零回归（514/514）；board 壳 c1/HEAD 字节相同（T2/T3 零触碰 board 壳）。

## 结果盲审（两段式，均 APPROVE）

- T1 单任务: 0P0/0P1，独立复现全部红绿+阴性对照+计数链+不修清单 5 项（报告 m1-6/result-review.md，原 /tmp 件灭失后自审者交付原文重存）。3 勘误全折入（node-check 格式升级含路径+抽取命令 / 两步链说明 / commit msg 与日志一致确认）。
- 整分支（T1+T2+T3，1f1f47a..HEAD）: 0P0/0P1（报告 m1-6/result-review-b.md）。覆盖面闭合（4 文件与 plan 三节逐一对齐）；T2 重建件 provenance 核实（git 对象独立加载复现）；T3 XSS 面安全（esc 全壳唯一渲染位）；板上状态核实（f49ce945 锚 a2 已更新 + 07755135 三锚对应）。4 勘误处置: ① f49ce945 description 旧措辞 -> 板上 note 落账（description 为原始报告不改写）；② plan 验证入口 /tmp 路径 -> 本 commit 折入改 /home 正典；③ 审者探针自身文件名大小写误报（复跑双 PASS，留档）；④ web.md 行号与 HEAD 一致（确认项）。

## 域外发现

1. **plan 审 T3 轮"board 全空"断言被实测推翻**: 板上 6 任务在场、9acea09b7 可达且 description 174 字完好、容器 Up、WAL 活跃——审者疑混淆测试夹具空 DB 与现网。板上事实已实测核死（ledger 在案），P4b 对账以实测为准。
2. **环境（非产品）**: /tmp usrquota 满两次发作（全量中断 + 系统清扫灭证据），处置与重跑规格见上；quota 大头为其他项目旧产物（未擅动）。

## 流程审计（六门）

- P6 独立流程审（ses_e886ce0d9ffei2ZmP4PbSnE6dH，merge 前，未参与实现/plan 审/结果审）: **PASS-WITH-DEVIATIONS**（无 P0/P1，3 P2 登记级，不阻塞合入；报告 m1-6/process-audit.md，工作产物不入库）。
- 关键核销: 六门门序完整（三轮 plan 审 10 处折入标注逐一在场）；计数链四方交叉（ledger/commit msg/plan/结果审）零矛盾；T1 证据=审者独立复现且时序早于清扫（合法），T2 stash 重建经 git 对象独立复现 + board c1==HEAD 字节相同；user 裁决四项与主循环自裁决四项均落实可实测（容器=T1 态镜像吻合）；四件事故（EDQUOT 中断 / /tmp 清扫 / 服务器重启 / "board 空"误判）全有记录+处置+防再发；tests/ac_cases_k.py diff = +35/0 纯新增零弱化；web.md 三处与代码行为逐行一致；main 未动、push 仅特性分支。
- P2 偏差（登记级）: ① plan 审 T1 轮 3 P2 中 2 条无显式"折入"标注且原报告灭失（结论存 ledger + c1 commit msg，核销缺口登记）；② plan 审 T3 原报告保留"board 空"错误勘验文本（更正已落 ledger/本文档，P4b+P6 双实测核死）；③ PR body"两轮 P1/P2 全折入"为压缩措辞（详实 T2 轮 2P1+3P2，已修正）。
- 主循环 ledger: /home/shih/.tmp-ak-m16/m1-6/ledger.md（门序/派发/裁决/事故全记录）。
