# BCD：B3 派发循环增强（接单确认门 + 上下文自动装配 + 交付自检 + 收尾蒸馏）

- 关联规范：skills/agent-kanban/SKILL.md「门序」「交接与等待」「派发方协议」（main @ ffd117a）；B2 BCD＝docs/business-contracts/b2-dispatch.md（不变量 I1-I4 继承）
- 范围：A1 接单确认门（SKILL 条款，零代码）/ A2 上下文自动装配（dispatch.py 代码 + ac 用例）/ A4 交付自检清单（SKILL 条款）/ A6 收尾蒸馏强化（SKILL 条款）。A3 supersedes 与展示面 5 项归 B4（登记未立项）。
- 版本：v1（2026-10-28，B3 开工）

## 1. 客户原话语义分析

客户原话（2026-10-28 对话，逐字）：

- a. 「你对比一下V1和V2结果，看看分析结果是否符合预期？然后就是从专业产品视角剖析，首先功能是否哪些可以改进，其次哪些信息的展示可以优化，更人性。还有分析skill，拿到原始需求后是否对提示词进行了优化（转写，可能需求描述并不清晰），填充更多上下文，使其工作流程更顺畅？」
- b. 「按照建议继续」（建议＝u2/pm-product-analysis.md 落地分组；主循环定界＝协议面 A1/A4/A6 零代码 + 产品面 A2 代码；展示面 5 项 + A3 supersedes 归 B4 不立项）
- c. 「我对产品不熟，需要你调研分析，选择最优的进行迭代即可」（2026-10-28 设计门：范围与 Q1/Q2/Q3 裁决委托主循环；亦为 T3 dogfood 返工 release `--on-behalf` 的可引 statement 原话）

三种解读：

1. **解读 1：全部 11 项（功能 6 + 展示 5）本批落地**。与批纪律冲突（M1 试用优先/不为第二用户建东西）：展示面纯人体工学，没有正在运行的循环被卡。
2. **解读 2：只落「循环真痛点」四项**——A1（模糊理解在交付阶段才暴露，提前到接单时刻）+ A2（让 worker 顺畅的上下文靠派发方手写 env card＝手艺非产品能力，把板面已有的历史产品化）+ A4/A6（本轮 worker 自发做到的好行为是模型自觉非协议保证，固化后行为可预期）。
3. **解读 3：A2 含内容解析**（从交付物文档正文解析 open 项清单装配进派发稿）。与 B2 P-imp6（CLI 不解释环境卡内容）同构冲突：解析正文＝CLI 成为第二语义源，与 worker 文档层理解必然漂移。

我的解读：**解读 2**，其中 A2 取字面提取层（解读 3 的收敛版：只抽 evidence 字面量，不解析正文）。理由：a 的三问逐一对应——「功能改进」-> A1/A2/A4/A6（剖析 A 节 1/2/4/6 项）；「提示词转写」-> A1（显性化 worker 的接单转写，剖析第三节缺口判定）；「展示优化」-> 归 B4（a 问的是剖析，b 批准的范围是落地分组，展示面在分组里标 B4）。

待澄清项（主循环已裁决，PR 交 user 确认，不阻塞实施）：

- Q1：A2 历史源＝同需求 review_request 事件；跨需求基线（v1 需求 -> v2 新需求）不自动装配，仍靠派发方 env card 基线指针（既有 SKILL 预检能力）。裁决：接受。理由：跨需求装配需要 supersede 关系（B4 A3），无该关系时 CLI 猜「同名/同主题旧需求」会带错基线；单一事实源优先。
- Q2：A2 是否覆盖续接稿（REOPEN 复派、session 已存在的复用路径）。预钉＝只加 _build_prompt；主循环实核：REOPEN 复派 -> GET session 200 -> 走 _build_continuation，_build_prompt 永不命中——**返工轮恰恰是历史交付物最被需要的场景**。裁决：A2 做成共享 _history_digest(rid)，派发稿与续接稿双点装配（P-imp4 幂等复用的自然推论，非范围扩张）。
- Q3：A1 接单确认是否阻塞（等人在场确认理解后才开工）。裁决：非阻塞——阻塞缺口 -> mark_blocked 问人（既有路径）；非阻塞缺口 -> 记假设继续 + 交接时提请人确认。理由：门的目的＝把 20 分钟跑偏提前到 1 分钟暴露，不是新增人工确认步骤；一律阻塞会卡死无人值守派发循环。

## 2. Impact Mapping

- **Why**：dispatch 循环三个实证痛点（V1/V2 两轮 gmail 调研实锤，pm-product-analysis.md）：(1) 需求理解偏差只在 20 分钟后以「交付物不对」暴露 -> A1 提前到接单时刻 1 分钟；(2) 本轮 V2 质量的最大变量＝派发方手写 env card 基线指针，手艺非产品能力 -> A2 把板面已有的同需求历史产品化；(3) evidence 三件齐/红线自守/三行简报/收尾蒸馏本轮属模型自觉，下轮不保证 -> A4/A6 固化为协议条款。
- **Who**：worker 会话（A1/A4/A6 条款消费者、派发稿/续接稿历史节消费者）；派发方 agent（A2 减手抄，env card 只管跨需求基线）；user（板面多两条可读事件：接单确认 + 蒸馏 note）。
- **How**：SKILL.md 三处条款（门序插入「接单确认」步 / 交接与等待加自检与蒸馏条款 / 派发方协议预检补历史装配分工）+ dispatch.py 一个只读函数 _history_digest + 派发稿/续接稿两处装配 + ac 用例 2-3 条。
- **What**：SKILL.md（三处条款）+ dispatch.py（_history_digest + 两处装配）+ ac 用例（新增，mock 无状态读真 DB）+ 本 BCD + known-gaps 观察项登记。零 API 变更、零 schema 变更、零 web 变更、零 CLI flag 变更。

## 3. Domain Event 流

- **Commands**：不变（无新 op；A1 复用 update_progress/add_record/mark_blocked，A6 复用 add_record，A4 复用 request_review 既有参数）。
- **Domain Events**：无新 kind（接单确认＝progress_note 或 note；蒸馏＝note）。
- **Aggregates**：Requirement（只读，同 B2）；Event（只读，kind=review_request 子集）。
- **Policies（显式，B2 继承不动）**：状态门（仅 OPEN/REOPEN 可 dispatch）；id 派生 1:1 + 幂等复用；超时不杀；板 note 强制。
- **Policies（隐含——业务没说但实际会跑的）**：
  - P-imp1：A2 历史源＝同需求 review_request 事件（payload.evidence.document + payload.evidence.note，seq 升序）；无历史不加节（首轮零差异，不写「历史：无」占位）。
  - P-imp2：CLI 只抽字面量，不解释 evidence 内容、不做文件存在检查（B2 P-imp6 的推广：交付物路径是指针不是引用——可达性由 worker 接单确认门/就绪门自行核实，路径失效 worker 报缺口，dispatch 不因路径不存在而失败或警示）。
  - P-imp3：A1/A4/A6 是提醒级约束（SKILL 条款，worker 自律），无服务端校验；结构性强制归 B4（permission 模板）/B6（plugin 守卫）。与 B2 D1 差异同类，known-gaps 登记。
  - P-imp4：A1 非阻塞（Q3 裁决）；阻塞缺口走 mark_blocked 既有路径，无新状态机动作。

## 4. BDD Given-When-Then 场景

1. **S1 A2 装配（happy，代码面）**。Given：REOPEN 需求，板上有 2 条 review_request 事件（第 1 轮 evidence={document:"/a.md", note:"..."}，第 2 轮 document="/b.md"，note 缺省）。When：dispatch（session 已存在走续接稿）。Then：续接稿含「历轮交付物」节，条目 seq 升序：`- 第 1 轮（seq <seq>）: 交付物 /a.md` + `- note: ...`；第二条只有交付物行（`- 第 2 轮（seq <seq>）: 交付物 /b.md`，note 缺省不报错）；其余既有摘要行（state/awaiting/子任务进度）不变。
2. **S2 A2 首轮（edge，代码面）**。Given：OPEN 需求，无 review_request 事件。When：dispatch（新建走派发稿）。Then：派发稿**不含**「历轮交付物」节（无占位）；B2 五要素断言全部不变（存量用例回归不红）。
3. **S3 A1 阻塞缺口（协议面，dogfood 真机 oracle）**。Given：描述含阻塞缺口的需求。When：worker 按 SKILL 执行。Then：板上 mark_blocked（reason＝缺什么 + 已核实到哪），无子任务执行记录。
4. **S4 A1 非阻塞缺口 + A4 自检（协议面，dogfood 真机 oracle）**。Given：描述含非阻塞缺口（约束缺失但可假设）的需求。When：worker 执行。Then：接单确认记录含「理解/假设/缺口」三段（理解＝转述非照抄原文）；request_review 时 evidence 指向真实交付物 + 逐项自评 + summary_line 三行简报，红线未越。
5. **S5 A6 蒸馏（协议面，dogfood 真机 oracle）**。Given：worker 本轮产生持久教训（如环境事实）。When：request_review 前。Then：环境卡「ops 教训」追加 + 板 note 一行；无持久教训时板 note 显式记「无持久教训」（禁静默省略）。

S1/S2 为 ac 用例（mock opencode HTTP + 真 sqlite）；S3/S4/S5 为 T3 dogfood 真机 oracle（故意含模糊性的需求派发，判据写进 dogfood 脚本）。

## 5. Spec by Example

- E1（代码）：需求 2 轮 review_request（document=/a.md note=「遗留：X 待核」；document=/b.md）。续接稿含节：

  ```
  ## 历轮交付物（本需求历史 request_review，seq 升序）
  - 第 1 轮（seq 42）: 交付物 /a.md
  - note: 遗留：X 待核
  - 第 2 轮（seq 57）: 交付物 /b.md
  ```

  断言＝两路径 + note 字面出现、顺序正确（字面匹配，禁语义断言）。
- E2（代码）：新需求 dispatch -> 派发稿无「历轮交付物」字样；五要素行逐字回归 B2 断言。
- E3（代码）：evidence 无 document 只有 note -> 该轮条目只有 note 行；evidence 全缺（invalid 数据）-> 该轮跳过，不报错。
- E4（dogfood）：模糊需求（故意缺 1 个阻塞约束 + 1 个可假设约束）-> worker 接单后 1 分钟内板上出现接单确认（含对两个缺口的分类处置：阻塞->mark_blocked 或可假设->记假设继续）；若阻塞缺口成立则任务 BLOCKED，不执行子任务。
- E5（dogfood）：对 E4 需求 resume 返工一轮 -> 续接稿历史节出现第 1 轮交付物路径 -> worker 续接而非重跑（交付物为增量修订，非全新文档）。

**客户期望 vs 系统行为差异表**：

| # | 客户期望 | 系统行为（本批） | 差异定性 |
|---|---|---|---|
| D1 | 接单确认门结构性防跑偏 | A1＝SKILL 条款（提醒级），无服务端门；worker 不执行则退回 B2 现状 | 根本性业务冲突（同 B2 D1）：harness 强制 vs 纪律提醒。缓解：SKILL 门序硬步骤 + dogfood 真机 oracle；结构性归 B4/B6 |
| D2 | 上下文自动装配＝worker「知道全部该知道的」 | A2 只装配同需求历史交付物指针；跨需求基线（supersede 场景）仍靠派发方 env card 指针 | 有意取舍（Q1）：无 supersede 关系（B4 A3）时 CLI 不猜跨需求历史，单一事实源；派发方手艺面收窄到跨需求场景 |
| D3 | 蒸馏保证执行且落环境卡 | A6＝SKILL 条款；worker 无环境卡写条件时回落板 note；无教训须显式记「无」 | 软约束（P-imp3）；「必须显式」是本次对 B2 软条款的唯一强化（防静默省略） |

## 6. Premortem（假设 6 个月后失败）

1. **（业务规则）接单确认门变成仪式**：worker 照抄需求原文充「理解」、缺口恒空 -> 门无判别力，模糊需求仍 20 分钟后以交付物形式暴露。失败序列：dogfood 过（模型自觉强）-> 真实模糊需求 -> 接单确认=复述 -> 跑偏 -> 人发现「门在但没用」。预防：T3 dogfood 用**故意含模糊性的需求**当 oracle（缺口必须真实触发分类处置）；SKILL 条款写明「理解＝转述（用自己的话压缩到 1-2 行），照抄需求原文视为未执行」。残余：模型自觉波动仍在（P-imp3 类，known-gaps）。
2. **（跨边界语义）A2 历史节与 env card 基线指针双源漂移**：派发方习惯在 env card 手写基线指针（B2 后仍会），同需求场景板面又自动装配历史 -> worker 面对两个「上轮」输入，手动抄的若是旧版 -> 按错基线续接。失败序列：派发方习惯性写 env card 旧路径 -> 板面历史是新版 -> worker 信 env card -> 增量基于旧基线。预防：SKILL 派发方协议预检条款补一句——同需求历史由 A2 自动装配，env card 基线指针只用于跨需求（supersede）场景，不手抄同需求历史。残余：纪律级。
3. **（草稿长度）多轮需求历史节膨胀**：review_request 历史累积（每轮 2-4 行）-> 派发稿/续接稿 token 成本上升。裁决：全附不截断（个人板场景单需求轮次通常 <=5，量级无害）；若 B4 后出现长链需求再议截断策略。登记 known-gaps 观察项。
4. **（mock/真机分叉）历史读取路径**：_history_digest 是真 sqlite 只读（无 mock 边界，测试 DB 即真库）-> mock 与真机分叉面小；dogfood 真机（E5 返工轮）验证装配输出进真实 prompt。

## 7. 业务不变量

强不变量（违反＝业务失败）：

- I1 **同需求单一事实源**：A2 历史只取本需求 review_request 事件；不扫盘、不跨需求。违反后果（跨需求猜装配）：带错基线（worker 按错误上轮续接，交付物漂移）；双语义源（盘 + 板），B2 单一事实源原则失效。
- I2 **字面提取**：历史节内容＝事件 payload 字面量（document/note/seq），CLI 不解释、不做存在检查、无历史不加节。违反后果（CLI 解释内容/占位节）：与 worker 文档层理解双源漂移（B2 P-imp6 违规先例重演）；首轮派发稿被占位节污染，worker 误判「有历史」。
- I3 **B2 不变量继承**：状态门 / id 派生 1:1 / 恢复锚强制 / 超时不杀（B2 I1-I4）本批不改；新增装配与条款不弱化任何 B2 不变量（ac 存量用例回归不红为机器证据）。

软约束（违反可容忍）：

- I4：A1/A4/A6 为协议条款（提醒级），行为 oracle＝T3 dogfood 真机；无服务端门。违反后果：worker 未执行门 -> 退回 B2 现状（不失败，只退化）。
- I5：历史节格式稳定（每轮：`第 N 轮（seq X）: 交付物 <path>` + 可选 note 行，seq 升序）——B4 展示面（轮次总结/状态卡）的机器可读锚。违反后果：B4 无可解析锚，重新约定。

## 修订记录

- 2026-10-29 r3（T1 盲审折入，主循环）：§4 S1 条目格式对齐 §5 E1/§7 I5（`- 第 N 轮（seq X）: 交付物 <path>`）；§4 S5 蒸馏判据钉死为三形态（环境卡 + 板 note / 板 note 全文 / 板 note「无持久教训」），板 note 恒有。
- 2026-10-28 r2（plan 盲审 r1 折入，主循环）：§1 补原话 c（设计门委托裁决原话，兼 dogfood release 受托 basis 引用锚）。
- 2026-10-28 r1（主循环）：Q2 裁决变更——A2 装配点从「只加 _build_prompt」修正为「派发稿 + 续接稿双点装配（共享 _history_digest）」；实核依据＝REOPEN 复派走 _build_continuation（dispatch.py 主链 reused 分支），只改 _build_prompt 则返工轮永不命中历史节。传播面：§3 P-imp1、§4 S1、§5 E1/E5。
