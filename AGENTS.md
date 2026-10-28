# AGENTS.md

strict-sdd-loop 适配契约 + 操作面速查。细节正典：docs/PRD.md（spec v3.2）、
docs/ops/ci-verification.md（CI/验证）、docs/adr/0000-known-gaps.md（残余登记）。

## 任务与看板操作面

- 看板（kanban）＝任务唯一事实源。看板协议（认领/拆解/记录/交接/释放/重试成本）
  以 `skills/agent-kanban/SKILL.md` 为正典，本文件不重复。
- **板上收尾动作**：agent 侧工作完成后（PR 流＝PR 发起后，本地合流＝合入后）
  立即调 `request_review`（evidence 含 pr_url/commit_range/test_summary，
  附验收自评；协议细节见协议 skill 门 6）。板 awaiting_human 是唯一等待面，
  禁留任务等租约过期变 stale。
- 人面 CLI（approve/release/note 等）：
  `AGENT_KANBAN_DB=/home/shih/.agent-kanban/kanban.db .venv/bin/python cli.py <cmd> --requirement-id <32hex>`
  （flag 式参数，非位置参数；approve/release 可省 --requirement-id＝零输入，agent 代执行携 `--on-behalf "<kind>:<basis>"`，判据见 SKILL.md 收尾协议）。
- dispatch/resume（worker 分发正典入口，协议见 SKILL.md「派发方协议」）：
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
  2. 本地全量套件：`TMPDIR=<产物目录>/tmp .venv/bin/python -u tests/run_ac.py` —— 基线 **793/793**（B2 合入后；worktree 内跑必带 `PYTHONPATH=$PWD/src`，见下）
  3. 本地 e2e：`TMPDIR=<产物目录>/tmp AK_E2E_DB=<产物目录>/ak-e2e.db npx playwright test` —— 基线 **15/15**（撞端口加 `E2E_PORT`；sqlite disk I/O error 先查 /tmp quota＝环境面）
  4. 本地 docker 双轨：默认轨 build + smoke healthz 200；pypi 轨命令与
     办公网 MITM 局限见 ci-verification.md
  5. **最高 tier（本地，合并门槛）**：2+3+4 全绿（正典组成＝全量 793/793 +
     e2e 15/15 + docker 双轨 build + healthz 200）
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
- tools/mcp: kanban（项目级 ./.venv/bin/agent-kanban mcp；跨目录用全局注册，见 docs/mcp-config.md §3.0）/ searxng（user 级）/ webfetch
- reach: 操作面 = 本地构建机（仓根 .venv）；测试 = tests/run_ac.py + npx playwright e2e（tier 阶梯见上「验证入口」）；观察面 = 生产 DB ~/.agent-kanban/kanban.db（只读）+ docker 容器 + healthz
- 红线: 禁直推 main（仅 MR）；生产 DB 只读，写走 CLI/MCP；禁 /tmp 作产物目录；Q1/Q2/Q3 裁决前禁 test/e2e 镜像现实现凑绿；merge 由 user 裁决
- ops 教训:
  - github ssh 路由（22/443）间歇挂；push 走 origin HTTPS（代理 127.0.0.1:8888）稳定；网络命令一律 timeout 包装，失败重试
  - gh 无独立代理配置，读标准 env，须 bash -lc 加载
  - 管道后 rc=$? 取的是管道末命令退出码；关键命令 rc 裸捕获（不接管道）

## 主循环纪律

- 编辑文件前用 repr 核目标区精确空白（read 行号前缀不等于文件缩进，猜缩进会致
  edit 失败）；oldString 必须逐字。
- Q1/Q2/Q3 三则存量契约分歧待 user 裁决：裁决前 test/e2e 禁镜像现实现（加断言
  凑绿），详见 ci-verification.md「Q1/Q2/Q3 交接」。
