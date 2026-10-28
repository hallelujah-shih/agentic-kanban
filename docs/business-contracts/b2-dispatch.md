# BCD：B2 dispatch / resume（需求 -> opencode worker 会话的分发规范入口）

- 关联规范：docs/PRD.md §2（description 工作区指针行）、skills/agent-kanban/SKILL.md「派发方协议」「Session 与恢复」「工作区就绪」（均随 0a33fec 合入 main）
- 关联 plan：/home/shih/.tmp-ak-m16/b2-dispatch/plan.md（批次产物目录，不入仓）
- 机制依据：/home/shih/.tmp-ak-m16/skill-resume/opencode-capability-survey.md（HTTP API 全链路实锤 + 本批 strace/OpenAPI 补锚，见 plan「机械预检」节）
- 版本：v1（2026-10-28，B2 开工）

## 1. 客户原话语义分析

客户原话（原文照抄，2026-10-28 对话裁决序列）：

- a. 「包装器＝kanban CLI 子命令（agent-kanban dispatch/resume）」
- b. 「租约心跳＝派发方心跳（派发方代理续租）」
- c. 「按照你的建议走，先开工」（建议＝B2 优先，理由＝卡住稳定分发主循环）
- d. 「提供合理的约束以及各种上下文和环境，就是harness，然后再调度实现」（harness 定义）
- e. B1 SKILL「派发方协议」（已在 main）：「留痕：... 派发后 add_record(kind=note)：session id + 模型 + transcript 路径 + 预算——这条 note 即恢复锚」

三种解读（存在业务目标分歧，a/c 支持 1 与 3 两解，e 支持 2）：

1. **解读 1：手工流程协议化**。dispatch＝把派发方今天手工做的事（组装派发稿 -> 拉起会话 -> 板上留痕）机制化，机制固化、派发方只带业务参数。真实期望＝派发方不再每次重查机制（gmail 试验中 run 语法 / MCP 位置 / 模型各手工查一遍）。
2. **解读 2：分发必经关口**。一切需求派给 opencode 会话必须经 dispatch；手工派发＝协议违规，板链视为断。真实期望＝恢复锚与分发 note 结构性存在，不依赖纪律。与解读 1 **互斥**：1 允许派发方选手工路径，2 使手工成为违规。
3. **解读 3：主动调度系统**。dispatch 含并发控制、排队、预算分配、模型选择策略、多任务编排。真实期望＝agent 群自动调度。与解读 1 **互斥**：1 是单次分发+留痕，3 是调度循环+资源分配。

我的解读：**解读 1**（B2 范围）。理由：c 的开工理由就是「卡住稳定分发」——稳定性瓶颈在手工组装与恢复锚缺失（gmail 试验实证），不在吞吐；解读 2 的强制点不在 CLI 而在协议+检测（B1 协议纪律 + B6 plugin 的 session 生命周期自动板事件可检测「无分发 note 的 session」）；解读 3 超出「不为第二用户建东西」批纪律（当前只有一个派发方：user 的 agent 主循环）。

待澄清项（主循环已裁决，PR 交 user 确认，不阻塞实施）：

- Q1：bg 心跳进程生命周期跟随派发方终端；派发方会话死则心跳停，worker 可能中途 SUSPECT。裁决：接受为本批已知局限（B6 plugin 心跳为结构替代；登记 known-gaps）。
- Q2：resume 是否受需求状态限制。裁决：不限（resume＝恢复/返工/换模型统一入口；DONE 需求上 resume 属协议违规，工具职责是如实记录——note 记需求当前状态），状态门只护 dispatch。
- Q3：--model 缺省语义。裁决：可选；缺省不传 model 参数（opencode 服务当前默认模型），note 如实记「未指定（服务默认）」；模型继承纪律归 SKILL 协议（派发方显式带当前模型），CLI 不自动继承（CLI 无法知道派发方模型）。

## 2. Impact Mapping

- **Why**：让「把板上需求派给 opencode worker 会话并留痕」成为一条稳定可重复的命令——一次分发＝一条恢复锚＋一条不断板链。目标是稳定分发，**不是**多任务自动调度，**不是**替代 B4/B6 的结构性约束（permission 模板/plugin 守卫）。
- **Who**：派发方 agent（主用户，agent 主循环代 user 执行）；user（板面读分发 note、裁决 REOPEN/resume）；worker 会话（派发稿消费者，行为由派发稿内容决定）；未来派发方 agent（按 SKILL 复现流程，本命令是正典路径）。
- **How**：CLI 子命令封装：读需求（状态门）-> 解析指针行 -> 派生 session id（ses_req_<id8>）-> opencode HTTP（存在检查 -> 创建/复用 -> 投派发稿 -> wait/bg）-> 板 note（成功或失败都写）。
- **What**：dispatch/resume 两个子命令 + 6 新 ac 用例（mock opencode HTTP 服务）+ SKILL「待补」行改实用法 + AGENTS.md 操作面速查补两行。

## 3. Domain Event 流

- **Commands**：Dispatch(requirement_id, model?, dir?, budget?, bg?)、Resume(requirement_id|ses, instruction?, model?)——触发方＝派发方（CLI 是人面，派发方 agent 经 user 在场代执行）。
- **Domain Events**（时序）：WorkerSessionEnsured（创建或复用）-> DispatchDelivered（派发稿投递）-> DispatchCompleted（同步 wait 至 idle）| DispatchTimedOut（budget 超，session 不杀）| DispatchFailed（投递失败，note 记事实）；bg 路径：BgStarted -> BgHeartbeat*（周期 renew）-> BgFinished（终态 note）。
- **Aggregates**：Requirement（只读 + note 事件，不动状态机）；WorkerSession（派生对象，id＝ses_req_<需求 id 前 8hex>，与需求 1:1）；Claim（读 + renew）。
- **Policies（显式）**：状态门（仅 OPEN/REOPEN 可 dispatch，否则报错带当前 state）；id 派生 + 幂等复用（重复 dispatch＝续接稿投递，不新开会话）；超时不杀 session；板 note 强制（成功/失败/超时都写）。
- **Policies（隐含——业务没说但实际会跑的）**：
  - P-imp1：opencode 服务假定已在运行且可达；dispatch 不自动拉起服务；不可达＝报错（消息含发现路径 + env 覆盖名），不重试。
  - P-imp2：投递失败时板 note 记失败事实 + 错误码（否则失败的分发在板上零痕迹，派发方无从得知）。
  - P-imp3：bg 续租由 CLI 以合法人面（actor_surface=cli）执行，携受托痕（delegated：kind=statement，basis 指向分发 note seq + session id）；租约时长/阈值语义不变（心跳形态＝派发方代理续租，即 user 已裁决项，本批落地）。
  - P-imp4：一需求一 session（id 派生结构保证）；同需求并发 dispatch＝续接投递而非第二会话。
  - P-imp5：resume 换模型走 switchModel 端点（prompt 的 OpenAPI schema 无 model 字段且 additionalProperties:false，已实锤），切换成功后再投 prompt。
  - P-imp6：派发稿只抽指针行字面量（workspace=/env-card=）+ 环境卡红线节原文；环境卡语义解释是 worker 就绪门的职责，CLI 不解释。

## 4. BDD Given-When-Then 场景

1. **S1 首次分发（happy）**。Given：OPEN 需求，description 带工作区指针行，opencode 服务可达，派生 session 不存在。When：dispatch <req> --model provider/model --budget 2h。Then：POST /api/session 以派生 id 创建（title 含 ak-<id8> 与需求标题，model 解析正确，location.directory＝指针目录）；派发稿（五要素：任务指针/协议入口/环境卡路径/交付规格/红线提醒 + 预算）经 prompt 投递；wait 阻塞至 204；板 note 存在（人话 title + content 含 session id/模型/目录/结局=完成）；stdout 输出 session id 与 note。
2. **S2 幂等复用（happy）**。Given：S1 完成，session 已存在。When：同需求再次 dispatch。Then：GET /api/session/{id} 200 -> 不新 create；同 id；投递续接稿（含板面状态摘要：state/awaiting/子任务进度）；板 note 第二条。
3. **S3 resume 返工（happy）**。Given：需求 REOPEN（评审拒绝），worker session 存在。When：resume <req> 「返工意见...」。Then：同 session id 投 prompt（text＝指令）；板 note 含「续跑」+ 需求当前状态。
4. **S4 状态门（edge）**。Given：需求 DONE。When：dispatch。Then：非零退出，错误消息含当前 state（DONE）；无 session 创建；无 note。
5. **S5 超时（edge）**。Given：budget 2s，wait 阻塞 10s。When：dispatch --budget 2s。Then：超时退出（退出码与输出契约明确）；**不杀 session**（无 delete 调用）；note 记超时 + resume 提示；session 可被 resume 续跑。
6. **S6 服务不可达（配置变更）**。Given：AGENT_KANBAN_OPENCODE_URL 指向死端口。When：dispatch。Then：报错含发现路径 + env 覆盖名；无 session 操作；无 note（未触达需求写入前）；P-imp1 不重试。
7. **S7 bg 心跳（跨时段）**。Given：--bg 分发，worker session 长活，claim active。When：bg 循环运行 10min。Then：周期 renew（claim last_activity_at 推进，renew 事件带 delegated 受托痕）；session idle 且无新 prompt -> 终态 note（含 bg 存活时长 + renew 次数）后退出。
8. **S8 bg 终态（跨时段，session 消失）**。Given：S7 运行中 session 被外部终止。When：bg 循环探测。Then：终态 note（记 bg 结束原因）+ 退出，不无限循环、不静默。

## 5. Spec by Example

- E1：req id=abcd1234…（OPEN，description 含 `workspace=/home/x/proj env-card=/home/x/proj/AGENTS.md`），服务可达。`agent-kanban dispatch abcd1234… --model ks-cp/glm-5-3-flash` -> 创建 {id:"ses_req_abcd1234", model:{id:"glm-5-3-flash",providerID:"ks-cp"}, location:{directory:"/home/x/proj"}}；prompt text 含五要素；note content 含 ses_req_abcd1234 / ks-cp/glm-5-3-flash / /home/x/proj / 结局。
- E2：同 req 第二次 dispatch -> create 调用仍为 1 次（mock 计数）；prompt 为续接稿（含 state/awaiting 摘要）。
- E3：`agent-kanban resume abcd1234… 「落点改 tmp 目录」` -> 对 ses_req_abcd1234 投 prompt（text 逐字）；note「续跑：...」含需求当前状态。
- E4：`agent-kanban resume ses_req_abcd1234 --model other/model 「继续」`（直给 ses id + 换模型）-> 先 switchModel（{model:{id:"model",providerID:"other"}}）后投 prompt。
- E5：DONE 需求 dispatch -> 退出码非 0，stderr 含 DONE，mock 零调用。
- E6：description 无指针行 -> 不阻塞；派发稿含「指针缺失」警示（P-imp6：CLI 不解释环境卡）；note 记目录=未指定。
- E7：budget 2s / wait 10s -> 约 2s 后超时退出；mock 无 delete；note 含「超时」。

**客户期望 vs 系统行为差异表**：

| # | 客户期望 | 系统行为（本批） | 差异定性 |
|---|---|---|---|
| D1 | 分发即 worker **结构性受约束**（红线不可触） | 派发稿只**告知**约束（红线节原文提醒）；结构性约束＝B4 permission 模板 + B6 plugin 守卫，不在本批 | **根本性业务冲突**：harness 强制 vs 纪律提醒。缓解：SKILL 协议纪律（红线即止）+ B4/B6 排期；本批 note 如实记录「约束=提醒级」 |
| D2 | 心跳保证「worker 活着则租约恒有效」 | bg 进程随派发方终端死则心跳停（Q1 裁决接受）；worker 长段可能 SUSPECT | 残余登记（known-gaps），B6 plugin 心跳为结构替代 |
| D3 | 恢复零查表 | id 派生＝ses_req_<前 8hex>；需求若被硬删重登（新 id），旧 session 孤儿化（无映射表可回指） | 有意取舍：零查表 vs 孤儿可追溯，选前者；孤儿 session 无害（不可被 dispatch 触达） |
| D4 | dispatch 一条命令 worker 即「知道全部该知道的」 | 派发稿给指针与路径，环境卡**内容**由 worker 就绪门自读（K3 协议） | 有意取舍：CLI 不解释环境卡（P-imp6），避免双份语义源 |

## 6. Premortem（假设 6 个月后失败）

1. **（业务规则/跨边界）分发 note 不被当作恢复锚**：CLI 稳定后，派发方 agent（或人）习惯手工 `opencode run` 直接派，板上无分发 note——恢复锚断裂：40min 调研段死在中间，人不知道 session id / 模型 / transcript 在哪，无法续跑；板三问「谁派的、哪个会话、到哪了」答不出。失败序列：手工派一次 -> 无 note -> worker 死 -> 人翻 transcript 目录找不到 -> 任务重做。预防：B1 SKILL 派发方协议已把留痕定为纪律；本批 T5 dogfood 用真命令留痕验证板链；B6 plugin 使「session 存在但无分发 note」可自动报 risk。
2. **opencode 实验性端点漂移**（wait 是 experimental）：opencode 小版本升级 -> wait 语义变化（如立即返回不阻塞）-> dispatch 提前判「完成」并把假完成写进 note -> 板面与真实 worker 状态脱节且假完成被记为事实。失败序列：升级 -> 长调研任务 wait 秒回 -> 派发方认为交付 -> 人 approve -> 实际 worker 还在跑（或已死）。预防：T5 dogfood 锚定当前版本（2.1.4）；wait 漂移退化方案＝轮询 GET /api/session/{id}（outcome/time.idle，OpenAPI 实锤存在）；note 记 opencode 服务 URL（版本可回溯）。
3. **（跨边界语义）bg 心跳活态误判——「进程活着 != 在干活」**：bg 以 session 非终态判活，但 worker 卡死（模型长思考/工具挂起）时心跳永续租约，任务无 SUSPECT 静默卡死；人看板面「正常进行中」实为 stuck。失败序列：worker 卡 3h -> 租约被心跳续住 -> 无告警 -> user 2 天后发现。预防：终态 note 记 bg 存活时长 + renew 总数（人可判异常）；SUSPECT 阈值语义不属本批（B3b 裁决面）；已知残余＝「卡死但活着」仍会误判——登记 known-gaps。
4. **mock 与真服务行为分叉**：mock 的「已存在」语义（200/404）若与真服务实际响应不符 -> 幂等复用路径在真环境未验（第二次 dispatch 可能 409 或建新 session）。失败序列：测试全绿 -> 真机第二次 dispatch 建了第二个 session -> 两个 worker 抢一需求。预防：T5 dogfood 真机走 create + reuse 两步；dogfood 不过不宣称完成（oracle 纪律）。

## 7. 业务不变量

强不变量（违反＝业务失败）：

- I1 **状态门**：dispatch 仅对 OPEN/REOPEN 需求生效，其余状态拒绝且报错含当前 state。违反后果：板状态机与实际 worker 状态脱节（worker 在跑但板说 DONE，反之亦然），恢复锚语义作废。
- I2 **id 派生 1:1**：session id＝ses_req_<需求 id 前 8hex>，与需求一一对应、无查表。违反后果（随机 id/查表 id）：零查表恢复承诺失效；dispatch 幂等失效（重复 dispatch 开第二会话，两 worker 抢一需求）。
- I3 **恢复锚强制**：成功分发必留板 note 含 session id + 模型 + 目录 + 结局；失败分发必留 note 含失败事实。违反后果：worker 死后无人可恢复（gmail 试验教训：session 死，人不知怎么续）。
- I4 **超时不杀**：budget 超时不终止 session。违反后果：数十分钟长调研工作被销毁，无产物可 resume，重试成本（token/墙钟）全损。

软约束（违反可容忍）：

- I5：bg 心跳周期与租约阈值的匹配——只要「worker 活着时不 SUSPECT」即满足，精确周期是实现细节。违反后果：心跳过密＝板事件噪声；过疏＝理论窗口 SUSPECT（B3b 面）。
- I6：派发稿五要素齐全——单要素缺失可容忍**当且仅当** note/派发稿带警示（如指针缺失已警示）；红线提醒缺失且无警示＝协议违规（升级处理）。违反后果：worker 就绪门无料可核，落点/红线靠 worker 自由发挥（试验已证明会跑偏）。
- I7：note title 一行人话——缺失时人面视图退化为机器日志，不破坏板链。违反后果：人读板体验下降，无业务失败。
