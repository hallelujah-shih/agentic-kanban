# Business Contract: 批 b4 派发门可执行化 + 规划入口进 MCP

**作者**: worker-b4-dispatch-gate（板上 4a3ac0e23cd746708aaf68f0060a9d12）
**日期**: 2026-10-30
**关联**: docs/PRD.md §4.1/§4.2（工具面）；b2-dispatch.md（dispatch 主链契约）；a1a2-mcp-surface.md（MCP 单向门先例）；skills/agent-kanban/SKILL.md + references/dispatch.md（协议面正典）；5defed11 note（首跑 flake 首记）；本批 probe 实测（opencode v2.2.0，四组目录 ×2 复跑）
**状态**: v1（有界批，判据直接取自需求 description 三事实 + 判据节；无独立设计审查轮）

---

## 1. 客户原话语义分析

### 客户原话（需求 description 原文摘录）

> 事实 1 — 主循环越权编码。Gmail 真实 API 适配器（新模块 + 改 CLI + 新测试，3 文件）由主循环直接写完，用户纠正「这些开发明显不应该你自己动手，应该委托」。现有 SKILL「何时派」只有一行软描述，没有任何可执行判据，也没有开工前的检查动作；实测就是没触发。
>
> 事实 2 — 规划入口不在 MCP。转成「先建需求再派发」时发现 MCP 12 工具里没有 new_requirement、也没有 set_expectations。建需求必须切 shell，长文本只能塞 argv：本轮先写成占位符、发现无法修改 description，只能 delete 硬删重建（硬删不写事件，规划痕迹丢失）。
>
> 事实 3 — 派发前预检有 flake。目标目录 opencode.json 配置齐全时，首跑 `opencode mcp list` 仍报「No MCP servers configured」，复跑立即正常（已记入 5defed11 note）。按一次结果判「不可达」会误拒派。
>
> 判据：主循环在任意项目目录，能在会话内完成「建需求（含长 description + 锚）-> 派发」全链路，全程不需要 argv 转义、不需要删了重建；且开工时有一条明确规则能拦住「直接改代码」。

### 解读与裁决

1. **规划入口二选一 -> 选 (a) MCP 增工具**（板上决策记录，a2）。理由：判据要求「会话内完成全链路、全程不切 shell」，(b) CLI --description-file 仍要切 shell 写文件，不满足；(a) 的 service 层 op 已存在（CLI `new`/`set_expectations` 同源），MCP 包装零新业务逻辑。
2. **派发门「可执行」= 事实判据 + 检查动作 + 硬门**（a1/a7/a8/a9/a4）：判据用「变更面」事实（跨文件/新增模块/新增依赖/新增测试文件/真实外部系统写入），不用体量直觉；开工前检查动作＝`list_tasks`（动作，不是自省）；归属声明＝动手前一句话（否决成本降到一句话）；`opencode mcp list` 从「派发方手动核」升级为 dispatch 入口硬门（复跑一次再判）。
3. **首跑 flake 依据**（a4「记录首跑 flake 依据」）：5defed11 note（2026-10-30 Gmail 批首记：配置齐全时首跑仍偶报「No MCP servers configured」，复跑立即正常）+ 本批 probe 复证（opencode v2.2.0）：配置齐全目录首跑报 flake、复跑正常；broken 条目稳定报「✗ kanban failed: NotFound: …」；无项目级 opencode.json 的目录只列全局服务器（无 kanban）。可达性判据＝**项目级 opencode.json 存在**（哪怕空对象），与条目是否写 `enabled` 无关；全局与项目级配置是**合并**不是替换。

---

## 2. Impact Mapping

### Why（业务目标）

让「用看板规划实现」这条路顺：主循环越权编码被明确判据拦住（事实 1），规划全链路会话内可完成（事实 2），派发不再被 flake 误拒（事实 3）。**不是**状态机/租约机制改造，**不是** release/approve/delete 入 MCP，**不是**「审查拒绝的状态路径」（那是需求 a111d9ce）。

### Who（受影响方）

1. **主循环（派发方）**：拿到可执行判据（变更面清单 + 归属声明 + 开工前 list_tasks 动作）；会话内 MCP 建需求（长文本免 argv 转义）；dispatch 入口自动预检（不再手动 `opencode mcp list`）。
2. **worker（被派发方）**：无行为变化——预检挡在派发前，worker 拿到的会话必然能看到看板（可达性由派发方保证）。
3. **人（审批/观察面）**：板上决策记录可追溯（归属声明 + 判据一句话）；预检拒派错误含目标目录与两次输出摘要，可操作。

### How（影响路径）

1. 协议面：SKILL.md「派发」节 + references/dispatch.md「何时派」改可执行判据（变更面/可自做通道/配置分界/归属声明/开工前动作）；预检第 3 项补硬门说明。
2. 工具面：server.py build_server 注册表 12->14（new_requirement/set_expectations，复用 operations 层，actor 派生机制不变）；PRD §4.1 表 + §4.2 同步。
3. 代码面：dispatch.py 状态门后插 `mcp_precheck`（subprocess，env 可覆盖命令，fail-closed）。

### What（具体交付物）

1. `skills/agent-kanban/SKILL.md` + `references/dispatch.md`（判据/归属声明/配置分界/预检硬门）。
2. `src/agent_kanban/mcp/server.py`（两工具包装器 + 注册）；`src/agent_kanban/dispatch.py`（mcp_precheck 链）。
3. 测试：`tests/ac_cases_q.py`（4 用例：规划入口/长文本/jira source/错误面）+ `tests/ac_cases_dispatch.py` 2 用例（flake 复跑恢复/持久不可达拒派）；既有 ac3/n10/http_mcp 计数断言 12->14。
4. 契约同步：PRD §4.1/§4.2、cli.py mcp help、本 BCD。

---

## 3. Domain Event 流

### Domain Events

**零新事件 kind、零事件形状变更**。规划通道（new_requirement/set_expectations）与 CLI `new`/`set_expectations` 同 service 层，**不写事件**（规划不是执行证据——事件流是审计链，规划噪音会污染回溯判据）。预检失败不写板 note（投递前中止契约，与状态门/服务不可达同分支，见 b2-dispatch.md S6 口径）。

### Commands

1. `new_requirement(title, description?, source=manual, source_ref?, acceptance?)` -> `{"requirement_id", "state": "OPEN"}`；acceptance 字符串或 {item,id} 形态，id 缺省自动分配 a1..（与 CLI 同源 normalize_anchors）。
2. `set_expectations(requirement_id, acceptance)` -> `{"requirement_id", "acceptance"}`；删除被 subtask links_to 引用的锚项 -> invalid_record（唯一入口语义两面一致）。
3. `run_dispatch`：状态门后、服务发现前插 `mcp_precheck(cwd=ws)`；ws 缺失跳过（worker 就绪门自核）。

### Aggregates

无新表/列/索引。规划工具走既有 requirements 行（new 插行、set_expectations 改 acceptance 列）。

### Policies（含隐含 Policy）

1. **规划通道免认领**：new/set_expectations 无需未结束认领（规划先于执行；写保护约束的是执行证据，不是规划）。
2. **预检 fail-closed**：首跑不可达复跑一次再判（5defed11 flake 依据）；复跑仍不可达 -> `mcp_unreachable` 拒派——宁可拒派，不放一个看不到看板的 worker（其产出在板上零痕迹，重试成本整轮丢失）。
3. **格式漂移按不可达**：`opencode mcp list` 输出行匹配不上既定形态（✓/✗ 标记 + 名字列 + 状态列）时按不可达处置——错的方向必须是「拒派」而不是「放过去」。
4. **env 覆盖是测试注入口**：`AGENT_KANBAN_DISPATCH_MCP_LIST_CMD` 覆盖命令（shlex 切分），缺省 `opencode mcp list`；单人工具，覆盖即显式行为，不做权限分级。

---

## 4. BDD Given-When-Then 场景

### Scenario 1（规划链路 happy：会话内建需求 -> 派发）
- Given: 主循环会话内（MCP 可达），无对应需求
- When: `list_tasks` 查无 -> `new_requirement(title, 长 description, acceptance)` -> `set_expectations` 补锚 -> `cli.py dispatch --requirement-id <rid>`
- Then: 全程无 argv 转义、无切 shell、无「占位 + delete 重建」；需求 OPEN 带锚落库；dispatch 经预检后建会话投派发稿

### Scenario 2（预检首跑 flake 复跑恢复）
- Given: 目标目录 opencode.json 配置齐全，`opencode mcp list` 首跑报「No MCP servers configured」（5defed11 flake 形态）
- When: `cli.py dispatch` 触发预检
- Then: 复跑一次，输出 `✓ kanban connected` -> 预检通过，派发正常进行（不拒派）

### Scenario 3（预检持久不可达拒派）
- Given: 目标目录 kanban 条目 broken（`✗ kanban failed: …`）或项目级 opencode.json 缺失（输出只有全局服务器，无 kanban）
- When: `cli.py dispatch` 触发预检
- Then: 首跑 + 复跑均判不可达 -> `mcp_unreachable`（rc=1，错误含目标目录 + 两次输出摘要）；**session 未创建、无板 note、不复跑第三次**

### 边缘场景 1（workspace 指针缺失）
- Given: 需求 description 无 workspace= 指针且未给 --dir
- When: `cli.py dispatch`
- Then: 预检跳过（无法确定目标目录），既有「workspace 指针缺失」警示照旧，worker 就绪门自核看板可达

### 边缘场景 2（agent 面边界不扩）
- Given: 本批后 MCP 14 工具
- When: 任意 agent 面调用
- Then: release/approve/delete 仍不可达（结构性缺席，既有断言回归）；状态机边与租约机制零改动

---

## 5. Spec by Example

### 例 1（长文本规划：a3 判据锚）
- 输入: `new_requirement(title, description=<4 行：含反引号 `_x`、$HOME/$(date)、双/单引号>, acceptance=["锚一","锚二","锚三"])`
- 操作: MCP 单次调用（JSON-RPC 结构化体经 stdin，不经 shell）
- 预期: description 逐字回读（get_task_detail）；字符串锚自动分配 id a1/a2/a3；无 delete 重建

### 例 2（预检输出解析形态，opencode v2.2.0 实测）
- 输入（stdout 行）: `✓ kanban           connected` / `✗ kanban           failed: NotFound: ChildProcess.spawn (no-such-cmd mcp)` / `No MCP servers configured`（整体，rc=0）
- 操作: `mcp_precheck` 解析
- 预期: 行 1 -> 可达；行 2 -> 不可达；行 3 -> 不可达（无 kanban 行）。名字列与状态列以 2+ 空格分隔；`failed:` 状态含空格，按「状态首 token == connected」判可达

### 例 3（预检复跑计数）
- 输入: 首跑 flake 文本、复跑 connected
- 操作: `mcp_precheck`
- 预期: 预检命令恰被调用 2 次；首跑即 connected 时恰 1 次（不浪费复跑）

### 客户期望 vs 系统行为差异表

| 场景 | 客户期望 | 系统行为（本批前） | 冲突性质 | 差距（本批填平） |
|---|---|---|---|---|
| 会话内建需求 | 不切 shell、无 argv 转义、不删了重建 | MCP 无 new/set_expectations，必须切 shell 塞 argv | 能力缺口 | MCP 两工具（同 service 层） |
| 派发前拦越权 | 一条明确规则拦住「直接改代码」 | SKILL「何时派」一行软描述，实测未触发 | 能力缺口 | 变更面判据 + 归属声明 + 开工前 list_tasks 动作 |
| 预检判不可达 | 配置齐全不被 flake 误拒 | 手动核 `opencode mcp list`，一次结果即判 | 能力缺口 + flake | 入口硬门 + 复跑一次再判 |
| agent 面边界 | release/approve/delete 保持人面 | 已满足 | 无缺口，防回归 | 断言回归（ac3 精确集） |

---

## 6. Premortem（假设 6 个月后失败）

### 失败原因 1（业务规则维度）：预检误拒——flake 判据失守
- 失败序列: 复跑逻辑被后人「简化」成一次判（或 flake 文本变体没被识别）-> 配置齐全的项目偶发拒派 -> 用户归因「看板派发不可靠」，绕回手工派发，硬门失去意义。
- 预防: 强不变量 5（fail-closed 但复跑一次）+ 两个 AC 用例钉死计数（flake 恰 2 次调用、持久不可达恰 2 次）；错误消息含两次输出摘要，误拒时人一眼看出是 flake 还是真 broken。
- 残余: 连续两次 flake 无实测先例（单用户低频面）——若发生，错误消息可操作（看两次输出，人工 `opencode mcp list` 复核），登记接受。

### 失败原因 2（跨边界语义维度）：预检误放——格式漂移被「宽容」解析
- 失败序列: opencode 升级改输出形态，解析被放宽到「有 kanban 字样就算可达」-> worker 拿到会话但看不到看板 -> worker 全程无法写板、派发方板上零痕迹 -> 重试成本整轮丢失，且归因困难（看起来像 worker 死了）。
- 预防: 强不变量 5/3（格式漂移按不可达，fail-closed）；解析正则锚定实测形态（✓/✗ 标记 + 2+ 空格列分隔 + connected 状态 token）；env 覆盖命令保留（形态漂移时可指向适配命令，不必改代码）。
- 残余: opencode 大版本升级需人工复核输出形态（无自动探测）——错误消息含原始输出摘要，复核成本低。

### 失败原因 3（业务规则维度）：规划入口造成重复需求
- 失败序列: 主循环用 MCP 建了一个需求，人面又用 CLI `new` 建了同题需求（不知板上已有）-> 两需求并行派发 -> 重复实现 + 事件链分叉。
- 预防: 协议面「开工前检查动作」把 `list_tasks` 钉为动作（不是自省）——建需求前先查；本批不引入「查重」机制（规划通道零事件，查重需要语义相似度，超出本批档位）。
- 残余: 语义级重复检测不做（登记）；list_tasks 查重靠人/agent 判标题，误判方向是「多一个需求」不是「丢失」。

### 失败原因 4（配置面）：env 覆盖被误用作绕过预检
- 失败序列: 某环境给 `AGENT_KANBAN_DISPATCH_MCP_LIST_CMD` 配了恒回 connected 的命令「解决」偶发拒派 -> 预检形同虚设，broken 目录照放 worker。
- 预防: Policy 4 明示覆盖是测试注入口；单人工具无权限分级。
- 残余: 接受（自己给自己配假预检＝自伤，错误消息仍含两次输出，板上痕迹可审计）。

---

## 7. 业务不变量

### 强不变量（违反即业务失败）

1. **agent 面无 release/approve/delete**：MCP 注册表结构性缺席三工具，既有精确集断言回归。违反后果：agent 可释放他人认领/自我确认完成/硬删需求，审计模型崩塌（C6 与释放人面裁决失效）。
2. **状态机边与租约机制零改动**：operations 状态转移与 lease.py 零 diff；新工具与预检不引入任何转移/续租路径。违反后果：状态机回归，既有 AC 面（k_state/retry_*/m_lease_*）大面积失效。
3. **零新事件 kind；规划通道不写事件**：new_requirement/set_expectations 与 CLI 同源（不写事件）；预检失败不写板 note（投递前中止契约）。违反后果：事件流混入规划噪音，回溯判据（审计链完整性）退化。
4. **MCP 单向门纯 additive**：12->14 只增不删不改，既有 12 工具参数/返回/错误码逐字不变；acceptance 唯一入口语义保持（两面同 service 层，links_to 删除保护两面一致）。违反后果：存量 agent 自动化断裂，单向门纪律失守。
5. **预检 fail-closed + 复跑一次**：首跑不可达必复跑一次再判（flake 依据 5defed11）；复跑仍不可达必拒派（mcp_unreachable，不建会话、不写 note、不复跑第三次）。违反后果（两个方向都是业务失败）：误拒＝派发链被 flake 卡死、硬门失去信任；误放＝worker 看不到看板，整轮产出板上零痕迹。

### 软约束（违反可容忍）

1. **server 名常量 `kanban`**（env 覆盖命令，不覆盖 server 名）：用户重命名自己的 MCP server 会致预检误拒。违反后果：错误消息可操作（提示检查项目级 opencode.json 的 kanban 条目），登记接受。
2. **ws 缺失跳过预检**：无法确定目标目录时不猜（在派发方 cwd 跑＝检查了错误的目录）。违反后果：该类需求靠 worker 就绪门自核兜底，既有警示条款覆盖。
3. **resume 路径无预检**：a4 范围＝dispatch 入口；run_resume 保持「不做计划外前置检查」（b2-dispatch 既有裁决）。违反后果：resume 投给 MCP 不可达的会话时 worker 无法写板——登记为已知局限（resume 通常发生在 dispatch 刚验过可达的会话上，窗口小）。
4. **基线计数**：全量套件基线 950 -> 976（+26：q_* 4 用例 14 断言 + k_mcp_precheck_* 2 用例 9 断言 + 预检通过路径既有条件断言 3），docs/ops/ci-verification.md 与 AGENTS.md 同步。违反后果：tier 阶梯判据失真，后续批次红绿比对失锚。

---

## 修订记录

- 2026-10-30 创建（worker-b4-dispatch-gate）。来源：需求 4a3ac0e2 description 三事实 + 判据节；板上决策记录（规划入口选 a：MCP）；5defed11 note（首跑 flake 首记）+ 本批 probe 实测（opencode v2.2.0 四组目录 ×2：配置齐全目录首跑 flake/复跑正常、broken 条目稳定 failed、空目录只列全局服务器、全局与项目级合并非替换、可达性判据＝项目级 opencode.json 存在与 enabled 字段无关）。
