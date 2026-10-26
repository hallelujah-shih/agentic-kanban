# CI 建设：GitHub Actions 全测试线（后端套件 + 前端壳防线 + e2e + docker build）

**基分支**: main @ f764794（worktree `.worktree/ci-build`，分支 `ci-build`）
**档位**: 全六门（D 面部署工件 Dockerfile 双轨改造 + 新测试语义 e2e + 架构级 CI 基建）
**日期**: 2026-10-26
**板上任务**: 86dfe88f（a2/a3/a4/a5 为本批实施目标；a1 调研已完成）

## 背景与机制结论（带证据）

M1-6 的 P0（board 壳 `split("\n")` 被 Python 转成真换行 → JS 整块 SyntaxError → 看板恒"加载中"）
暴露了测试线两个洞：① 套件全绿但从不执行 JS；② 合入无自动门禁，全靠 user 手动点。本批补三层
自动防线 + 一个打包底线，并把「每次改动自动跑全部测试」设为合入门禁（user 裁决：必需 check）。

**镜像源双轨机制（ci-probe/ D 实验闭环，uv 0.11.12 实测）**：
- `uv sync --frozen` 严格用锁内 URL（`UV_INDEX_URL` 覆盖无效，B2 实验）→ 单一 aliyun 锁无法在
  海外 CI 直接 sync。
- `uv export --locked --all-groups` 产出纯钉版 requirements（含 sha256 哈希、零 URL，主仓 134 行
  含 `-e .`）→ 不重写锁、零漂移。
- CI 侧 `uv venv` + `UV_INDEX_URL=https://pypi.org/simple/ uv pip install -r <export>` 跨源安装
  实证成功（pythonhosted 下载 + 哈希校验，D 实验）→ 海外轨成立。
- 办公网零改动：uv.toml/uv.lock 保持 aliyun + `uv sync --frozen`（user 裁决：国内必须 aliyun）。
- 本地/CI 跑套件注意：`uv run` 默认按 aliyun 锁 sync——CI 一律用 `.venv/bin/python` 直跑。

## 契约三锚

1. **规范逐字原文**：
   - 板上 86dfe88f description（逐字）："user 要求（2026-10-26，M1-6 P0 修复后提出）：以后不要再有
     board 壳 JS 转义类问题……分层：①后端全量套件（run_ac，M1-6 后 511+ 例）②前端壳解析防线
     （node --check + 静态引号配对，M1-6 A2 已落套件）③e2e 真浏览器（Playwright 等，跑 web.md
     冒烟 checklist）④docker build 冒烟。"
   - user 5 项裁决（板上 note seq 80，2026-10-26）：① 镜像源=国内外两套（办公网/国内保留 aliyun
     为必须，海外 CI 走 pypi.org）② e2e 一期就上（覆盖圈定项，断网重连留人工）③ docker job
     一期进 ④ 分支保护 test+docker 全设必需 check ⑤ 顺序=先 CI 后 G12。
   - `docs/web.md:44-53` 冒烟 checklist 第 1/2/3/4/5/7 项 + 第 6 项"另一进程推进状态 -> 页面 2s
     内自动刷新"——e2e 圈定项（第 6 项"断网/重启重连"留人工、第 8 项 401 后端套件已覆盖，
     均不进 e2e）。
   - `docs/superpowers/plans/2026-10-26-board-shell-js-escape.md:15-20`（P0 机制 + node --check
     反证）：坏壳 `SyntaxError: Invalid or unexpected token` line 147 / 修复壳 PASS——② 层
     oracle 的历史锚。
   - 调研正典：/home/shih/.tmp-ak-m16/ci-research/report.md（hermetic 逐条核实、GH 环境规格、
     无 secret 结论、YAML 草案）。
2. **代码锚点**（main@f764794 实测）：
   - `src/agent_kanban/api/web.py:91` `board_shell()` / `:302` `detail_shell()`（各 1 个
     `<script>` 块；node --check 两步链抽取正则 `<script>(.*?)</script>` re.S）。
   - `src/agent_kanban/api/requirements.py:74` `POST /requirements`（body：title/description/
     source/source_ref/acceptance[{item}]，201）；`:116` archive；`:121` DELETE；`:131` /board。
   - `src/agent_kanban/config.py:16-30`：`AGENT_KANBAN_HOST`（默认 127.0.0.1）/ `AGENT_KANBAN_PORT`
     （默认 8765）/ `AGENT_KANBAN_TOKEN`（localhost 请求豁免，Connection 对端判定）/
     `AGENT_KANBAN_DB`。
   - `Dockerfile:12-13`：`pip install uv --index-url mirrors.aliyun.com` + `uv sync --frozen`
     （双轨改造点）；`:15-16` ENV；`:20` CMD `/app/.venv/bin/python -m agent_kanban.api`。
   - `uv.toml`（aliyun 默认 index + allow-insecure-host）/ `uv.lock`（696 处 aliyun URL）——
     本批不动（办公网轨）。
   - `tests/run_ac.py:1` 入口（`--only` 单组）；基线 514/514（M1-6 合入后，docs/ops/m1-6-
     verification.md:24）。
3. **逐例期望**：
   - run_ac 套件计数**不变**（本批不向 run_ac 增删用例，基线 514；新测试资产 = e2e 9 例 +
     CI 步骤，计数口径另立，见 T3/T4）。
   - 本地 docker 双模：默认轨（aliyun frozen）build 成功 + 镜像 healthz 200（现状回归，
     基线 27s 冷构建）；pypi 轨（`--build-arg UV_DEPS_MODE=pip --build-arg
     UV_PIP_INDEX=https://pypi.org/simple/`）build 成功（日志含 pypi.org/pythonhosted 下载）
     + 镜像 import smoke + healthz 200。
   - e2e：健康服务上 9/9 绿（workers=1，估 1-2 min）；红探针双态（见 T3）。
   - CI 定谔 oracle：PR 上三 job（test/e2e/docker）真实 GH run 全绿（P5 阶段，merge 门槛）。

## oracle 版本（机械预检）

- 宿主实测（2026-10-26，f764794 worktree）：python 3.14.4（.venv）、node v24.21.0、
  docker 29.9.2、uv 0.11.12；playwright 版本 = T3 网络前置探针后 npm 钉版实测值
  （T4 文档钉死，plan 不预猜）。
- CI runner（GH 官方规格，调研 4.4）：ubuntu-latest = Ubuntu 24.04/4 核/16GB/14GB SSD，
  默认 node 22.23.3，docker 原生可用。
- 基线锚：run_ac 514/514（docs/ops/m1-6-verification.md:24）；docker 默认轨冷构建 27s
  （调研 4.3）；uv.lock aliyun URL 696 处（本批不动）。

## 影响面

- ① 命中（工件构建输入）：Dockerfile 新增 2 个 ARG，**默认值保持现行行为字节级不变**
  （办公网 build 零感知）；无存储格式/ABI/数据迁移，非单向门（ARG 可回滚、向后兼容）。
- ② 命中（新执行环境）：CI runner 新装依赖走 pypi.org/npmjs.org（官方源 + 哈希校验 + lock
  钉版）；CI 无 secret、服务绑 127.0.0.1 免 token（localhost 豁免，威胁模型 C 不变）；
  仓 PUBLIC（已公开），代码可见性无新增面。
- ③ 不命中（CI 为离线基建，非热路径）。
- ④ 不命中（无业务规则变化，BCD 不触发；显式声明不适用：本批不改任何状态机/视图/事件语义）。

## 原子任务

### T1: Dockerfile 镜像源双轨（ARG 化）

**Files**: Modify `Dockerfile:9-13`（注释 + 2 个 RUN；ENV/EXPOSE/CMD 不动）。

**改动**（目标形态）：
```dockerfile
# 双轨镜像源：默认国内轨（aliyun + 锁内 URL frozen sync，办公网零改动）；
# 海外 CI 传 --build-arg UV_DEPS_MODE=pip --build-arg UV_PIP_INDEX=https://pypi.org/simple/
ARG UV_PIP_INDEX=https://mirrors.aliyun.com/pypi/simple/
ARG UV_PIP_TRUSTED_HOST=mirrors.aliyun.com
RUN pip install --no-cache-dir uv --index-url ${UV_PIP_INDEX} ${UV_PIP_TRUSTED_HOST:+--trusted-host ${UV_PIP_TRUSTED_HOST}}
ARG UV_DEPS_MODE=frozen
RUN if [ "$UV_DEPS_MODE" = "frozen" ]; then \
      uv sync --frozen; \
    else \
      uv export --locked --all-groups -o /deps-ci.txt \
      && uv venv \
      && UV_INDEX_URL=${UV_PIP_INDEX} uv pip install -r /deps-ci.txt; \
    fi
```
机制：pip 轨（`uv` 本体的安装源）与依赖轨（`UV_DEPS_MODE`）同 ARG 驱动；pip 轨在 pypi 模式下
`--trusted-host mirrors.aliyun.com` 对未使用的 host 为 no-op（pip 接受，无害）。export 在容器内
`--locked` 零网络（用锁），仅 install 走 pypi。

**oracle**（红绿同源 = 同一条 build 命令，只换 ARG）：
- 红 R3：对**未改** Dockerfile（f764794）跑 pypi 轨 build——ARG 未声明，`--build-arg` 为 no-op，
  build 日志走 aliyun（证据：日志含 mirrors.aliyun.com、无 pypi.org/pythonhosted 依赖下载行）。
  这证明"不改则 CI 海外 build 只能赌 aliyun 可达性"。
- 绿 G3：新 Dockerfile pypi 轨 build 成功；日志含 pypi.org/pythonhosted 下载；镜像
  `docker run --rm <img> /app/.venv/bin/python -c "import agent_kanban"` PASS；
  `docker run -d -p 127.0.0.1:18811:8765 <img>` 后 `curl 127.0.0.1:18811/healthz` == 200（18811
  避开在跑的 8765 容器）。
- 回归 G4：默认轨 `docker build`（不带 ARG）成功 + 同法 healthz 200（办公网零改动实证；
  预期 ~27-60s）。

**验证命令**:
```
docker build [ARG...] -t ak-ci-t1 .
docker run --rm ak-ci-t1 /app/.venv/bin/python -c "import agent_kanban"
docker run -d --rm -p 127.0.0.1:18811:8765 --name ak-t1-smoke ak-ci-t1 && sleep 3 \
  && curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:18811/healthz && docker stop ak-t1-smoke
```
**Commit**: `ci: Dockerfile 双轨镜像源 ARG（默认 aliyun frozen 零改动；海外 CI 走 pypi export+pip）`

### T2: CI workflow（test job + docker job）+ 本地模拟

**Files**: Create `.github/workflows/ci.yml`。

**内容契约**（YAML 全量以 ci-probe 实证机制为准，禁凭记忆改安装链）：
- 触发：`pull_request: [main]` + `push: [main]`；`concurrency` 同 ref 取消旧 run（省分钟）。
- **test job**（name: `test`，分支保护必需 check 锚定此名）：
  - `actions/checkout@v4` + `astral-sh/setup-uv@v7`（python-version "3.14"）。
  - 装依赖（D 实验机制逐字）：
    `uv export --locked --all-groups -o requirements-ci.txt`
    → `uv venv` → `UV_INDEX_URL=https://pypi.org/simple/ uv pip install -r requirements-ci.txt`
  - ② node --check（runner 默认 node 22.23.3，不另装）：`.venv/bin/python` 内联脚本用
    `re.findall(r"<script>(.*?)</script>", html, re.S)` 抽两壳（board_shell()/detail_shell()）
    落 /tmp，逐个 `node --check`（findall 而非 search：防多块吞并；断言每壳至少 1 块）。
  - ① 全量套件：`.venv/bin/python -u tests/run_ac.py`（`-u` 关块缓冲实时见逐条；
    **禁** `uv run`——会按 aliyun 锁 sync）。
  - `timeout-minutes: 20`。
- **docker job**（name: `docker`，必需 check 锚定此名）：
  `docker build --build-arg UV_DEPS_MODE=pip --build-arg UV_PIP_INDEX=https://pypi.org/simple/ -t agentic-kanban:ci .`
  `timeout-minutes: 15`。
- e2e job **不在本任务**（T3 追加，保持每个 commit 的 CI 语义完整）。

**oracle**（本地模拟 = CI 命令序列在洁净环境的同构复现）：
- S1（CI-faithful 全链，绿）：洁净 venv + 独立缓存跑 test job 命令序列：
  `uv export --locked --all-groups -o <ledger 目录>/reqs-ci.txt`（断言：0 行含 aliyun/URL、
  含 `httpx2==`、含 `-e .`）→ `UV_CACHE_DIR=<独立> uv venv` →
  `UV_CACHE_DIR=<独立> UV_INDEX_URL=https://pypi.org/simple/ uv pip install -r reqs-ci.txt`
  （独立缓存强制真实下载，日志见 pythonhosted）→ `.venv/bin/python -c "import agent_kanban"`
  → ② 两步链双 PASS → **该 venv 全量 run_ac = 514/514**（~6 min，CI 同构绿）。
- S2（YAML 有效性）：`python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`
  + 逐 step 与 S1 实跑命令序列逐字对账（模拟与 YAML 命令同源是纪律要求：YAML 里任何 S1 没
  跑过的命令形态 = P1 级偏差，须在回报中列出）。
- 红基线：本任务的"红"＝T1 的 R3（机制依赖：不改 Dockerfile 则 docker job 必红）+ 现状
  无 `.github/workflows/`（`git ls-files .github/` 为空 = CI 不存在）。无独立红跑。
- **定谔 oracle**（P5 阶段）：PR 上真实 GH run 三 job 全绿。本地模拟只证机制，不证
  GH runner 环境（网络/预装）——两者差异在 P5 首次真实 run 收口，该 run 是 merge 前置证据。

**验证命令**: 见 oracle S1/S2（命令全文由派发 brief 给出，执行者禁自创安装链变体）。
**Commit**: `ci: workflow 上线（test=导出锁+pip 装依赖+壳 node --check+全量套件；docker=pypi 轨 build）`

### T3: e2e 真浏览器层（Playwright，冒烟圈定 9 例）

**Files**: Create `package.json` + `package-lock.json`（根目录，`@playwright/test` 钉版 devDep，
lock 由 `npm i -D @playwright/test` 生成、**registry 必须 npmjs.org**——本地若被网络挡，
见"网络前置探针"）、`playwright.config.js`（根目录）、`tests/e2e/seed.py`、
`tests/e2e/*.spec.js`；Modify `.github/workflows/ci.yml`（追加 e2e job）、`.gitignore`
（+ `node_modules/`、`test-results/`、`playwright-report/`）。

**网络前置探针（T3 第一步，产物落 ledger）**：`npm ping`（registry 可达性）+
`npx playwright install --dry-run chromium` 或实际下载（浏览器 CDN 可达性）。任一不通：
登记 + 按预案降级（npm 换 npmmirror 仅本地装包，**lock 仍须 npmjs.org 生成**——可
`npm i -D --registry=... @playwright/test` 后 `npm i --registry=https://registry.npmjs.org`
重锁，或在 GH 首跑收口；降级须记 ledger，禁静默）。

**服务与夹具（webServer 一体管）**：
```js
// playwright.config.js（契约形态；选择器/细节由执行者按壳实读定，见下）
module.exports = require('@playwright/test').defineConfig({
  testDir: './tests/e2e',
  workers: 1,                    // 共享单服务+单 DB，串行防串扰（冒烟规模，串行成本可忽略）
  timeout: 30000,
  expect: { timeout: 15000 },    // SSE 2s 轮询刷新留足窗（flaky 对策：expect.poll，禁固定 sleep）
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: 'http://127.0.0.1:18765' },
  webServer: {
    command: 'rm -f /tmp/ak-e2e.db* && .venv/bin/python tests/e2e/seed.py /tmp/ak-e2e.db \
              && AGENT_KANBAN_DB=/tmp/ak-e2e.db AGENT_KANBAN_PORT=18765 .venv/bin/python -m agent_kanban.api',
    url: 'http://127.0.0.1:18765/healthz',
    reuseExistingServer: false,
    timeout: 60000,
  },
});
```
- 端口 18765 固定：GH runner 是全新 VM 无冲突；本地撞端口即换（登记）——CI-first 取舍，
  登记不修清单。
- 免 token（localhost 豁免，config 默认 127.0.0.1）：token 传播链由后端套件 security 用例
  API 层覆盖，e2e 不重复（裁决留人工/不覆盖面见不修清单）。
- `seed.py`（服务启动前直写 DB，无并发）：复用 `tests/ac_lib`（`sys.path` 插入 tests/），
  造 6 种子——s1 OPEN+description（**含对抗内容**：`<img src=x onerror=alert(1)>` + 引号 +
  换行，真浏览器 XSS 探针）、s2 OPEN+acceptance 2 锚 0 子任务（缺口标红对象）、
  s3 CLAIMED+BLOCKED（MCP `claim_task`+`mark_blocked`，awaiting_human 对象）、s4 OPEN（archive
  对象）、s5 OPEN（delete 对象）、s6 CLAIMED（status 过滤对象）。

**9 例契约表**（选择器由执行者先读 `web.py:91/302` 两壳实定，**优先 id>稳定文本**，
选定选择器登记在 spec 文件头注释；壳零产品改动——找不到稳定选择器 = 域外发现上报，
禁私改 web.py 加 data-testid）：

| 例 | web.md 锚 | 步骤 | 断言 |
|---|---|---|---|
| E1 | 1 | 打开 `/` | 不停在"加载中"；6 条种子任务行标题全部渲染 |
| E2 | 2 | 页面渲染后 node `fetch /board` | 页面标题集合 == JSON 标题集合（6 条，逐 id 对账） |
| E3a | 3 | 点 s1 标题进深潜页 | description 以**纯文本**呈现（含换行）；该节内 `img` 元素数 = 0（XSS 中和，真浏览器对抗位） |
| E3b | 3 | 点 s2 进深潜页 | 验收对照表 2 行；缺口标红样式在场（执行者实读壳定红标判定，登记） |
| E4a | 4 | 顶栏新建：title `e2e-new-<ts>` + acceptance 两行 + Jira 链接，提交 | 看板出现新标题（poll ≤10s）；新任务 source=jira（fetch /board 核） |
| E4b | 4 | 深潜 s4 -> archive | 回看板（URL `/`）；「已归档」tab 内 s4 在场 |
| E4c | 4 | 深潜 s5 -> delete：dialog 先输**错误**标题，再输正确标题 | 第一次：停留深潜页（未离开）；第二次：回看板且 s5 行消失 |
| E4d | 4 | 直接 `page.goto(/requirements/no-such-<rand>)` | 友好文案"任务不存在"（浏览器导航 Accept 含 text/html -> HTML 壳，执行者首跑实证此前提，前提不成立 = 域外发现上报） |
| E5 | 5 | 看板 s3 行 + 深潜 s3 | 看板行有待处理信号标识；深潜页横幅含 `kanban approve <id>` 静态文案 |
| E6 | 6 | 看板打开状态下，node `fetch POST /requirements`（title `e2e-live-<ts>`） | 新标题 **15s 内**出现在看板（expect.poll；SSE 重拉，禁固定 sleep） |
| E7 | 7 | node `fetch /board?status=CLAIMED` | 返回集 state 全为 CLAIMED 且含 s6、不含 s1（s3 为 BLOCKED 亦不含——执行者按实跑核口径并登记） |

**oracle 红绿**：
- 红 R1（反证位：测试真依赖活服务）：临时把 config 的 baseURL/webServer 端口 sed 成
  18799（服务不在），跑 E1 -> 必须红（连接失败，非静默跳）；恢复 config。
- 红 R2（历史坏壳 = P0 类真红，canary 式阴性对照）：一次性 worktree
  `git worktree add .worktree/ci-r2-probe f764794` 后
  `git checkout f764794^ -- src/agent_kanban/api/web.py`（= M1-6 前坏壳），以该 worktree 代码
  起服务（port 18766 + 独立 DB，PYTHONPATH=src 走主 worktree 的 .venv）→ 跑 E1 -> 必须红
  （"加载中"卡死）；同一坏壳跑 ② 两步链 -> 必须红（SyntaxError，行号 ≈147）。用完删
  probe worktree。
- 绿 G5：健康服务 9/9 全绿，计时落 ledger（预期 1-2 min，超 3 min 须在回报解释）。

**CI e2e job**（追加进 ci.yml，name: `e2e`）：checkout + setup-node@v4(node 22) +
setup-uv@v7(3.14) + 同 test job 的 export+pip 装依赖 + `npm ci` +
`npx playwright install --with-deps chromium` + `npx playwright test`；`timeout-minutes: 15`。
（浏览器下载无缓存，20-40s，登记不修清单；`--with-deps` 装系统库，GH runner root 可 apt。）

**验证命令**: `npm ci && npx playwright install --with-deps chromium && npx playwright test`
（CI 全链逐字）；本地红探针命令见 oracle R1/R2。
**Commit**: `ci: e2e 真浏览器层（Playwright 冒烟 9 例：渲染/数据一致/深潜/生命周期/awaiting/SSE 刷新/过滤）`

### T4: 验证文档 + 分支保护交接

**Files**: Create `docs/ops/ci-verification.md`（tracked，仓库验证正典惯例同 m1-6-verification.md）；
Modify 板上 86dfe88f note（状态推进）。

**文档内容契约**：
- tier/入口：最高 tier = 本地全量 run_ac 514/514 + e2e 9/9 + docker 双轨 build+healthz；
  CI 门槛 = PR 三 job 绿 + 分支保护必需 check（test/docker 必需，**e2e 首期非必需**——
  裁决原文只圈 test+docker，e2e 带 flaky 面，观察一两周无连红后补设，交接单列）。
- 重跑规格（本地三条：pypi 模拟链 / e2e / docker 双轨，含精确 argv）。
- 实钉版本（机械预检项）：python/node/docker/uv/playwright 实测版本 + e2e 计时。
- 盲区登记：e2e 不覆盖 token 真机传播（API 层已覆盖）/ 断网重启重连（留人工，user 裁决）/
  第 8 项 401（后端已覆盖）/ 浏览器视觉与手感 / A1-A5 静态防线固有边界（承 m1-6 登记）。
- 分支保护操作交接（user 执行，agent 不碰仓设置；附 gh 命令 + 网页路径两步）：
  必需 check = `test` + `docker`（job 名即 check 名）；e2e 待观察。

**oracle**: 文档与当轮磁盘产物逐项对账（版本/计时/命令可复跑）；板上 note 落账。
**Commit**: `docs: CI 批次验证正典（tier/重跑规格/盲区/分支保护交接）`

## 不修清单

| 项 | 理由 | 登记位置 |
|---|---|---|
| `uv.toml` / `uv.lock`（aliyun 默认 + 696 URL） | 办公网轨零改动，user 裁决国内必须 aliyun | 本 plan 镜像源节 |
| `tests/run_ac.py` 及 ac_cases_*（514 例不动） | 本批不向 run_ac 增删用例；node --check 是 CI 步骤非套件用例（套件 hermetic 不依赖宿主 node） | 契约三锚.3 |
| e2e 不覆盖 token 真机传播 | localhost 豁免下无 token 场景；token 链已由后端 security 用例 API 层覆盖 | ci-verification.md 盲区 |
| e2e 不覆盖断网/重启 SSE 重连 | 确定性模拟需掐网/杀服务，flaky 面最大；user 裁决留人工 | 同上 |
| e2e 不覆盖第 8 项（非 localhost 401） | 后端套件已覆盖，重复 | 同上 |
| 两壳零产品改动（不加 data-testid） | e2e 选择器漂移是 user 裁决接受的维护面；私改壳 = 域外 | 本表 + T3 纪律 |
| e2e 浏览器下载不加 GH 缓存 | 20-40s 在 15min 预算内，缓存键维护不划算（二期再议） | 同上 |
| e2e job 首期非必需 check | 裁决原文圈 test+docker；e2e 观察无连红后补设 | ci-verification.md 交接 |
| G12（3d2f99e4 list_awaiting 泄漏） | 独立板上任务，顺序裁决=CI 先行 | 板上 |
| 本地 npm 网络抖动 | 预案降级登记制，不预先做镜像切换基建 | T3 网络前置探针 |
| `tests/bench.py` / `tests/alembic_diff.py` | 独立工具，不在 run_ac 门内，CI 不跑（调研 4.4 核实） | 调研 report.md:304 |

## 执行纪律

- 同仓未提交改动互斥 → T1-T4 **严格串行**，每任务红绿齐备后 commit。
- 派发 prompt 必含：worktree 路径 `.worktree/ci-build`、基 f764794、本 plan 路径、
  ci-probe/ 目录指针、陷阱库全文、产物目录 /home/shih/.tmp-ak-m16/ci-build/（**禁写 /tmp
  作证据**——本机 /tmp usrquota 慢性满；CI 语境下的 /tmp 无此问题，YAML 内 /tmp 路径合法）。
- 域外发现（npm/浏览器网络不可达、GH 首跑异常、套件新签名红）强制回报单列，禁静默绕过。
- 证据保全：每轮 build/e2e/sim 日志 cp 落 ledger 目录后再重跑（死亡 run 保全纪律）。
