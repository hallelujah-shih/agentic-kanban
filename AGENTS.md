# AGENTS.md

strict-sdd-loop 适配契约 + 操作面速查。细节正典：docs/PRD.md（spec v3.2）、
docs/ops/ci-verification.md（CI/验证）、docs/adr/0000-known-gaps.md（残余登记）。

## 任务与看板操作面

- 看板（kanban）＝任务唯一事实源。看板协议（认领/拆解/记录/交接/释放/重试成本）
  以 `skills/agent-kanban/SKILL.md` 为正典，本文件不重复。
- 协议可发现性靠本机软链接 `.agents/skills/agent-kanban -> ../../skills/agent-kanban`
  （`.agents/` 与 `skills-lock.json` 已 gitignore；新机器/新 worktree 需重建这条
  链接，否则协议只能按文件路径读，不会出现在 skill 清单里）。
- **板上收尾动作**：agent 侧工作完成后（PR 流＝PR 发起后，本地合流＝合入后）
  立即调 `request_review`（evidence 含 pr_url/commit_range/test_summary，
  附验收自评；协议细节见协议 skill 门 7）。板 awaiting_human 是唯一等待面，
  禁留任务等租约过期变 stale。
- 人面 CLI（approve/release/note 等）：
  `AGENT_KANBAN_DB=/home/shih/.agent-kanban/kanban.db .venv/bin/python cli.py <cmd> --requirement-id <32hex>`
  （flag 式参数，非位置参数；approve/release 可省 --requirement-id＝零输入，agent 代执行携 `--on-behalf "<kind>:<basis>"`，判据见 SKILL.md 收尾协议）。
- dispatch/resume（worker 分发正典入口，协议见 SKILL.md「派发方协议」）：
  模型缺省选 `ks-local/Qwen3.8-27B`（2026-10-30 起：ks-cp 有 5 小时配额，长任务会中途
  报 provider.quota 中断；两个 provider 都可用，优先本地）
  `AGENT_KANBAN_DB=/home/shih/.agent-kanban/kanban.db .venv/bin/python cli.py dispatch --requirement-id <id> [--model provider/model] [--dir D] [--budget <秒|h/m/s>] [--bg]`；
  `cli.py resume --requirement-id <需求 id 或 ses_req_<8hex>> ["<指令>"] [--model provider/model]`（恢复/返工/换模型统一入口，不限需求状态）。
- dispatch/resume 语义：--budget＝同步 wait 墙钟预算（超时 rc=1 不杀会话，stdout 带 resume 提示；resume 缺省 1h）；--bg＝投递后返回，独立 bg 子进程心跳续租（周期 env AGENT_KANBAN_DISPATCH_HEARTBEAT_SEC 默认 60s），终态写板 note。深挖锚：输出含 session id + directory 顶层字段，人深挖 worker 现场＝`cd <directory>` + `opencode -s <session id>`（缺一即交接不完整）。
- 生产 DB `/home/shih/.agent-kanban/kanban.db` 只读侦察；操作面写走 CLI/MCP 正典路径。
- 生产部署：`docker compose up -d --build kanban`（仓根 docker-compose.yml，build 仓根，
  host 网络，挂载 ~/.agent-kanban:/data）；部署后核验 = healthz 200 + 容器代码态
  + list_awaiting。
- 合入涉及 cli.py 的变更，合入后跑 `uv sync --reinstall-package agent-kanban`
  刷新入口快照（known-gaps G11）。

## 验证入口与 tier 阶梯

- 入口形态：本地开发机＝构建机（仓根 `.venv`）；远端＝GitHub Actions。
- tier 阶梯（低 -> 高；tier 命名与组成按 ci-verification.md 正典）：
  1. 快速反馈（折入重跑最低 tier，SDD 机器纪律款）：`TMPDIR=<产物目录>/tmp .venv/bin/python tests/run_ac.py --only <用例 id>`
  2. 本地全量套件：`TMPDIR=<产物目录>/tmp .venv/bin/python -u tests/run_ac.py` —— 基线 **1090/1090**（b11 conformance 判据 +36 断言、sa_blankacc 净 -1；历史值 1055/997/988/976/950/918/902/859/835/816/696/521 为当时基线，勿再引用；worktree 内跑必带 `PYTHONPATH=$PWD/src` 且先 `uv sync`，见下）
  3. 本地 e2e：`TMPDIR=<产物目录>/tmp AK_E2E_DB=<产物目录>/ak-e2e.db npx playwright test` —— 基线 **16/16**（撞端口加 `E2E_PORT`；sqlite disk I/O error 先查 /tmp quota＝环境面）
  4. 本地 docker 双轨：默认轨 build + smoke healthz 200；pypi 轨命令与
     办公网 MITM 局限见 ci-verification.md
  5. **最高 tier（本地，合并门槛）**：2+3+4 全绿（正典组成＝全量 1090/1090 +
     e2e 16/16 + docker 双轨 build + healthz 200）
  6. **CI 门槛（合并门槛，远端）**：特性分支 push -> GH Actions 三 job
     test/e2e/docker 全绿 + 分支保护必需 check `test`+`docker`（e2e 观察期：
     自 CI 首跑 2026-10-26 起一两周无连红后补设，交接命令
     ci-verification.md:230）
- worktree 锚定：worktree 内跑全量套件必带 `PYTHONPATH=$PWD/src`（months_ago 管线修后 canonical 轨亦绿；锚定规则为 canonical 口径保留）。
- **禁 /tmp 作产物/证据目录**（/tmp usrquota 慢性满，EDQUOT 两次先例）：
  本地一切 run 必带 `TMPDIR=/home/shih/.tmp-ak-m16/<batch>/tmp`；
  批次产物目录 = `/home/shih/.tmp-ak-m16/<batch>/`（ledger、dispatches/、红绿日志、审查报告）。
- 重跑规格（pypi 模拟链/e2e/docker 双轨）逐字命令与实钉版本：ci-verification.md。

## 仓适配事实

- flake 签名/故障手册：未登记（截至 2026-10-27 无已登记 flake；批内遇到先登记
  docs/adr/0000-known-gaps.md 再派发）。
- 规范原文位置：docs/PRD.md（产品 spec v3.2）、docs/design.md、docs/web.md（前端契约）。
- 非代码资产检查清单：docs 改动复读变更节 + 核对交叉引用目标存在；yaml/shell 触及
  时 `bash -n`/解析核验；新增依赖须陈述收益。
- 历史陷阱归档/canary：docs/ops/ci-verification.md（已知局限/已知实践登记/P5 未核区）
  + docs/adr/0000-known-gaps.md；canary 用例＝e2e R2 历史坏壳（f764794^ web.py，
  ci-verification.md「红绿正典」）。

## 批次纪律（2026-10-27 PM 评审裁决，依据 docs/ops/pm-review-2026-10-27.md）

- 定位口径：个人 agent-ops 基础设施（非市场产品）；不为第二用户建东西
  （多用户/协作/外部对接永不进范围）。
- 每批判据：它让三问（PRD §1 C1）更可答（outcome），还是只减 builder 摩擦？
  后者仅在卡住正在运行的循环时合格。
- M1 完成以 G3 试用/AC14 跑完为准（known-gaps G3）；试用裁决前不排纯人体工学批次。

## 环境卡

- workspace: /home/shih/test/AgenticKanban（主仓，main 只读）；开发工作走 .worktree/<name>；产物落点: docs/（文档）/ tests/（用例）；临时产物: /home/shih/.tmp-ak-m16/<batch>/
- context: docs/PRD.md（spec v3.2）/ docs/design.md / docs/web.md / docs/ops/ci-verification.md / docs/adr/0000-known-gaps.md；看板协议 = skills/agent-kanban/SKILL.md
- skills: strict-sdd-loop（开发循环）/ adversarial-review（审查）/ technical-research（调研，调研类任务默认）
- tools/mcp: kanban（项目级 ./.venv/bin/agent-kanban mcp；跨目录派发＝目标项目自声明项目级 kanban 条目（绝对路径 + 显式 DB），见 docs/mcp-config.md §3.0）/ searxng（user 级）/ webfetch
- reach: 操作面 = 本地构建机（仓根 .venv）；测试 = tests/run_ac.py + npx playwright e2e（tier 阶梯见上「验证入口」）；观察面 = 生产 DB ~/.agent-kanban/kanban.db（只读）+ docker 容器 + healthz
- 红线: 禁直推 main（仅 MR）；生产 DB 只读，写走 CLI/MCP；禁 /tmp 作产物目录；Q1/Q2/Q3 裁决前禁 test/e2e 镜像现实现凑绿；merge 由 user 裁决
- ops 教训:
  - github ssh 路由（22/443）间歇挂；push 走 origin HTTPS（代理 127.0.0.1:8888）稳定；网络命令一律 timeout 包装，失败重试
  - gh 无独立代理配置，读标准 env；`bash -lc` 登录 shell **不含**代理变量，必须命令前显式带（`HTTPS_PROXY=http://127.0.0.1:8888 HTTP_PROXY=... gh ...`），只靠 git 的 `http.proxy` 配置无效（B3 开 PR 实测：不带 env 报 TLS handshake timeout，带上立即成功）
  - 管道后 rc=$? 取的是管道末命令退出码；关键命令 rc 裸捕获（不接管道）
  - 代理抖动对 gh 是分端点的：`api.github.com/graphql`（`gh pr create/edit`）反复 TLS handshake timeout，同刻 `curl -x` 打 REST `/pulls/20` 稳定 200。gh 卡住时先 `gh auth token` 取 token，再用 `curl -x <proxy> -X PATCH -H "Authorization: Bearer"` 打 REST，不换网络不重登
  - CI 逐 job 状态打 `/check-suites/<id>/check-runs`；`/commits/<sha>/check-suites` 只给 suite 级 conclusion + `check_runs_url`，无 `workflow_runs` 键（2026-10-31 实锤：按 `workflow_runs` 解析的轮询循环空转 20 次，suite 级 conclusion 已 success 时直接读 check-runs）
  - 给 CLI 传长文本（resume 指令、note、description）先把内容写文件再 `"$(cat f)"`：直接写双引号串时反引号会被 shell 当命令执行（2026-10-30 实锤：指令里的 `_default_transport` 变成 command not found，路径信息被吃，返工指令残缺，只能补发一次）
  - 测试种子插 events 表：id 是全局主键（跨需求也须唯一，用 uuid），seq 才是每需求维度；_seed_review 的 f"{seq:032x}" 形态只在 seq 全局唯一时安全
  - request_review 逐项自评 assessments 正典形态＝[{subtask_id, items:[{item 逐字（按子任务验收文本精确匹配）, state, deviation_reason（not_met/deviated 必填）}]}]；形态错/漏项/重复/引用已 abandon 子任务/超 8KB -> invalid_record（B3.2 起服务端门，消息含可用清单）；**不传 assessments 不构成豁免**；交接前 get_task_detail 核子任务 acceptance 落 state
  - 宿主里跑着的 kanban MCP server 在进程启动时快照代码（`opencode.json` 指向主仓 src）：合并后需重启 MCP server 新逻辑才生效；worker 在 worktree 里交接走的是主仓代码（旧），因此新契约不会在它自己那次交接上生效（B3.2 实测：payload 无 assessment 键）
  - 落点纪律：跨项目/跨仓产物禁落本仓（含 `docs/`）。调研类先按宿主分区找既有项目（`~/test` 自研与试验、`~/projects` 线上工程与 bundle、`~/src` 开源镜像），同类产物押在哪就押在哪；无归属先问人，禁自决新建目录（2026-10-29 实锤：gmail 调研落仓根 `research/`、browser-login 调研落本仓 `docs/research/`，两处均已迁出）
  - 交付物必须落永久位置：批次 tmp（`/home/shih/.tmp-ak-m16/`）会被清理，禁作唯一副本；`request_review` 前 `ls` 核路径存在（B2 v2 交付物随 tmp 工作区丢失实锤）
  - models 的 UUIDHex＝sa.Uuid(as_uuid=False)：ORM 读回 36-char 带连字符，写路径/MCP 返回/事件 claim_id 均 32-hex——跨面比对先 services.ids.norm_id 归一
  - worktree 内 docker smoke 禁裸 `docker compose up`（compose 挂生产 ~/.agent-kanban:/data 且撞生产 8765 端口，restart 策略会crash-loop）：用 `docker run --rm --network host -e AGENT_KANBAN_PORT=<空闲端口> -v <scratch>:/data <image>` + curl healthz 后即 rm
  - opencode 服务 switchModel（POST /api/session/{id}/model）成功返回 204 No Content（非 200），wait 端点同为 204；mock 与状态判定须对齐真实回码，禁镜像实现假设（2026-10-30 实锤：resume --model 必失败，mock 回 200 掩盖此差异）
  - worktree 里跑全量套件前先 `uv sync`：worktree 的 `.venv` 不会随主仓同步，缺 `dependency-groups.test`（如 hatchling）会让 AC 的 wheel 构建用例报 `No module named hatchling`，看起来像代码红（2026-10-30 skill-package 批复验实锤，白白怀疑一轮）
  - worktree 里跑 e2e 前先 `npm ci`：node_modules 同样不随 worktree 同步，裸 `npx playwright test` 命中 npx 缓存缺 `@playwright/test` 报 MODULE_NOT_FOUND（2026-10-30 b5 实锤）
  - 新 worktree 切出后先 warm-up 再 dispatch：新目录首开 `opencode mcp list` 连空 2 次、甚至第 3 次 pending 是已知首开 flake，dispatch 预检 2 次尝试会误拒（mcp_unreachable）；在目标目录跑 warm-up 到 `kanban` 行出现 connected 为止（实测需 3-9 次，上限 10；2026-10-30 user 裁决：走派发方 warm-up，预检复跑次数不变）
  - skill 树仓内相对路径 token 门（p3_skill_text(1)）：skill 树内任何 .md（含 references/）禁出现仓内路径 token（如 `cli.py`）——CLI 一律以 `agent-kanban`（console script 名）指称。客户端特有 token 在 references/ 是正典要求（p3_skill_text(13)），但仓内路径在树内任何位置都禁（2026-10-30 b4 实锤：dispatch.md 首稿写 `cli.py dispatch`，全量红 1，改 `agent-kanban dispatch` 即绿）
  - `tests/run_ac.py --only` 只收一个参数（逗号分隔列表）；写多个 --only flag 只取**第一个**，「结果 N/M」只对应第一例——多选须 `--only a,b,c`（2026-10-30 b6 实锤：连写三个 --only 只跑了 9/9 的第一例，误读为三例全绿）
  - Playwright/Jest toEqual 忽略数组尾部 undefined 元素：红预先声明步骤里期望值含尚未扩容的 manifest 键（SEEDS.x = undefined）时断言不红（[s6,s9] vs [s6,s9,undefined] 判等）——红的出生证需「键在场值不同」态或 mutation 探针（2026-10-31 b12 实锤：plan 红步预期 4 failed 实跑 3，E7 缺夹具态不红，判别力经 defined-id 对照验证成立）

## 主循环纪律

- 编辑文件前用 repr 核目标区精确空白（read 行号前缀不等于文件缩进，猜缩进会致
  edit 失败）；oldString 必须逐字。
- Q1/Q2/Q3 三则存量契约分歧待 user 裁决：裁决前 test/e2e 禁镜像现实现（加断言
  凑绿），详见 ci-verification.md「Q1/Q2/Q3 交接」。
