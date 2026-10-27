# AGENTS.md

strict-sdd-loop 适配契约 + 操作面速查。细节正典：docs/PRD.md（spec v3.2）、
docs/ops/ci-verification.md（CI/验证）、docs/adr/0000-known-gaps.md（残余登记）。

## 任务与看板操作面

- 看板（kanban）＝任务唯一事实源。看板协议（认领/拆解/记录/交接/释放/重试成本）
  以 `skills/agent-kanban/SKILL.md` 为正典，本文件不重复。
- **板上收尾动作**：agent 侧工作完成后（PR 流＝PR 发起后，本地合流＝合入后）
  立即调 `request_review`（evidence 含 pr_url/commit_range/test_summary，
  附验收自评；协议细节见协议 skill 门 5）。板 awaiting_human 是唯一等待面，
  禁留任务等租约过期变 stale。
- 人面 CLI（approve/release/note 等）：
  `AGENT_KANBAN_DB=/home/shih/.agent-kanban/kanban.db .venv/bin/python cli.py <cmd> --requirement-id <32hex>`
  （flag 式参数，非位置参数）。
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
  2. 本地全量套件：`TMPDIR=<产物目录>/tmp .venv/bin/python -u tests/run_ac.py` —— 基线 **521/521**
  3. 本地 e2e：`TMPDIR=<产物目录>/tmp AK_E2E_DB=<产物目录>/ak-e2e.db npx playwright test` —— 基线 **12/12**（撞端口加 `E2E_PORT`；sqlite disk I/O error 先查 /tmp quota＝环境面）
  4. 本地 docker 双轨：默认轨 build + smoke healthz 200；pypi 轨命令与
     办公网 MITM 局限见 ci-verification.md
  5. **最高 tier（本地，合并门槛）**：2+3+4 全绿（正典组成＝全量 521/521 +
     e2e 12/12 + docker 双轨 build + healthz 200）
  6. **CI 门槛（合并门槛，远端）**：特性分支 push -> GH Actions 三 job
     test/e2e/docker 全绿 + 分支保护必需 check `test`+`docker`（e2e 观察期：
     自 CI 首跑 2026-10-26 起一两周无连红后补设，交接命令
     ci-verification.md:230）
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

## 主循环纪律

- 编辑文件前用 repr 核目标区精确空白（read 行号前缀不等于文件缩进，猜缩进会致
  edit 失败）；oldString 必须逐字。
- Q1/Q2/Q3 三则存量契约分歧待 user 裁决：裁决前 test/e2e 禁镜像现实现（加断言
  凑绿），详见 ci-verification.md「Q1/Q2/Q3 交接」。
