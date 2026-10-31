# CI 建设验证记录（全测试线：后端套件 + 前端壳防线 + e2e 真浏览器 + docker 双轨）

位置: docs/ops/ci-verification.md（tracked，分支 ci-build，worktree .worktree/ci-build）
批次: CI 建设（板上 86dfe88f；GitHub Actions 全测试线：test = 导出锁 + pip 装依赖 + 壳 node --check + 全量套件，docker = pypi 轨 build，e2e = Playwright 冒烟 12 spec）
基线: main @ f764794；commit 链 1c84174(T1 Dockerfile 双轨) / 7d53b63(T2 ci.yml) / 7eb6c3b(T3 e2e 12 spec) + 本文档 commit（docs-only，代码态 = e95a652）
计划: docs/superpowers/plans/2026-10-26-ci-pipeline.md（21c548e 初版 / 4fb5e45 修订 1 / 974994b 修订 2 / 0160801 修订 3 / e95a652 修订 4 = HEAD）
计划审: 盲审三轮（ses_e882df87fffeYpURnlJ3DlTRUU，同审者续接）：首审 APPROVE-WITH-FIXES（1P1 F1 + 9P2 全折入）-> 复核 APPROVE-WITH-FIXES（1P1 N1 + 2P2 N2/N3 + 1 勘误 全折入）-> 轻量确认 **APPROVE**（P0/P1 清零）；报告 /home/shih/.tmp-ak-m16/ci-build/plan-review.md（333 行，三轮全留存）

## tier / 入口

- 最高 tier（本地，合并门槛）: 全量 run_ac **1090/1090**（断言数；b11 conformance 判据 +36 断言、sa_blankacc 净 -1，历史批次的 1055/997/988/976/950/918/902/859/835/816/696/521 等数字为当时基线，勿再引用）+ e2e **16/16** + docker 双轨 build + healthz 200（tier 组成的活口径以 AGENTS.md tier 2/5 为准）
  - b10 批次本地最高 tier 证据（2026-10-31，worktree b10-review-reject @ 3bfc339）: 全量 1055/1055（green-full-2.log rc=0）+ e2e 15/15（15.9s）+ docker 默认轨 build + smoke healthz 200（docker run 空闲端口 18765 + scratch 卷，pypi 轨容器段仍办公网环境面阻塞，闭合点＝GH 首跑 docker job）；批次产物 /home/shih/.tmp-ak-m16/b10-review-reject/
  - 默认轨（aliyun frozen）本地绿（t1/g4.log + t1/smoke-probes.log）；pypi 轨容器段办公网环境面阻塞，闭合点 = GH 首跑 docker job（见已知局限）
  - G12 批次红绿索引（2026-10-26，套件基线 514->521，k_g12 增例 N=7）: 红 = R1 泄漏复现 2 断言皆红（r1-red.log 0/2）/ 绿 = 521/521（g2-full.log）；产物目录 /home/shih/.tmp-ak-m16/g12/t1/；生产生效窗 = merge 回 main + 生产容器下次重启后启动自愈自动回填，此前生产行为不变（存量行数未知，自愈幂等 0 行也安全）
- CI 门槛: PR 三 job（test/e2e/docker）真实 GH run 全绿 + 分支保护必需 check
  - 必需 = `test` + `docker`（job 名即 check 名，ci.yml:15/:56；user 裁决④原文圈定 test+docker）
  - **e2e 首期非必需**：裁决原文只圈 test+docker，e2e 带 flaky 面；观察一两周无连红后补设（操作见分支保护交接）

## 重跑规格（本地三条，CWD 均 = worktree 根）

### a) pypi 模拟链（= ci.yml test job 命令序列同构复现，证据 t2/；命令与 ci.yml 逐字同源，差异全部为计划内同语义，对账表 t2/s2-reconcile.md）

```
cd /home/shih/test/AgenticKanban/.worktree/ci-build    # CWD = worktree 根：export 发现 lock + `-e .` 解析前提
L=/home/shih/.tmp-ak-m16/ci-build/t2                   # 证据目录：独立 cache/venv，不动办公网 .venv（plan 不变量）

# 1) export（ci.yml:32 同源；差异 = 仅 -o 落盘路径）
uv export --locked --all-groups -o $L/reqs-ci.txt
# 断言 5/5（t2/s1-export-assert.log）:
#   grep -cE 'aliyun|https?://' $L/reqs-ci.txt -> 0（模式写死，防 httpx2/httpcore2/httptools 包名误伤）
#   含 httpx2== ；含 `-e .`（行 3）
#   wc -l -> 786（含哈希）；grep -vcE '^[[:space:]]+--hash=' -> 134（非哈希 = spec 44 + `-e .` 1 + 注释 89）

# 2) venv（ci.yml:33 裸 `uv venv`；S1 加独立缓存 + 显式路径，防命中 worktree 办公网 .venv）
UV_CACHE_DIR=$L/cache uv venv $L/venv-pypi

# 3) install（ci.yml:34 同源；S1 加 UV_CACHE_DIR/VIRTUAL_ENV 定向——无定向时 uv 发现序命中
#    worktree 办公网 .venv，破坏"不动办公网"不变量；独立空缓存强制真实下载）
UV_CACHE_DIR=$L/cache VIRTUAL_ENV=$L/venv-pypi UV_INDEX_URL=https://pypi.org/simple/ uv pip install -r $L/reqs-ci.txt
# 预期: Resolved 43 packages；"Building agent-kanban @ file:///.../.worktree/ci-build"
#       （editable+hatchling PEP 660 首验段）；"Installed 43 packages"

# 4) import
$L/venv-pypi/bin/python -c "import agent_kanban"

# 5) ② 壳 node --check 两步链（脚本体与 ci.yml:39-49 逐行同一，提取件 t2/s2-extracted-script.py 411 字节；
#    S1 仅 OUT 与解释器不同）
$L/venv-pypi/bin/python - "$L" <<'PY'
import re, sys
out = sys.argv[1]
from agent_kanban.api.web import board_shell, detail_shell
for name, html in (("board", board_shell()), ("detail", detail_shell())):
    blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert blocks, name + ": no <script> block"
    for i, js in enumerate(blocks):
        with open(out + "/ak-" + name + "-" + str(i) + ".js", "w") as fh:
            fh.write(js)
PY
for f in "$L"/ak-board-*.js "$L"/ak-detail-*.js; do node --check "$f"; done   # 每壳 1 块，双 PASS

# 6) 全量套件（ci.yml:53 同源；S1 加 TMPDIR = /tmp usrquota 绕行）
TMPDIR=$L $L/venv-pypi/bin/python -u tests/run_ac.py   # 预期 "== 结果: <当前基线>/<当前基线> PASS"（~6 min；当前基线看 AGENTS.md tier 2，b11 批次后＝1090；1055/997/988/976/950/918/902/859/835/816/696 为历史值）
```

### b) e2e（证据 t3/）

```
cd /home/shih/test/AgenticKanban/.worktree/ci-build
# CI 全链（ci.yml e2e job 逐字）:
npm ci && npx playwright install --with-deps chromium && npx playwright test
# 本地形态（端口/DB 走 env 覆盖，零 config 改动、零 CI 漂移；默认值 E2E_PORT=18765 / AK_E2E_DB=/tmp/ak-e2e.db = CI 值）:
TMPDIR=/home/shih/.tmp-ak-m16/ci-build \
AK_E2E_DB=/home/shih/.tmp-ak-m16/ci-build/t3/ak-e2e.db \
npx playwright test
#   - 撞端口加 E2E_PORT=<port>；AK_E2E_DB 用绝对路径（本机 /tmp usrquota 慢性紧张，m1-6 两次 EDQUOT 先例）
#   - 新检出 / 新 worktree 首次跑先 `npm ci`（node_modules 不入版本库；缺失时 npx playwright 报
#     MODULE_NOT_FOUND = 环境面，非产品红；B3 实测 npm ci 673ms / 3 packages，浏览器缓存已装）
#   - 本地 e2e 遇 sqlite disk I/O error 先查 /tmp quota = 环境面，非产品红
#   - 浏览器仅本地首次装包需要（办公网 cdn.playwright.dev ~2MB/min 不可行）:
#     PLAYWRIGHT_DOWNLOAD_HOST=cdn.npmmirror.com npx playwright install chromium
#     （不带 --with-deps，本地非 root；宿主系统库依赖已满足 = g5 本地 12/12 绿；
#      package-lock 仍由 registry.npmjs.org 生成，降级不影响锁）
```

### c) docker 双轨（证据 t1/）

```
cd /home/shih/test/AgenticKanban/.worktree/ci-build
# 默认轨（办公网轨：aliyun + 锁内 URL frozen，零改动；依赖层 [7/8]+[8/8] 实测 ~10s，t1/g4.log）:
docker build -t ak-t1-g4 .
# pypi 轨（ci.yml:63 docker job 逐字；办公网容器 TLS 在 MITM 下确定性失败 = 已知局限，
# 容器级绿闭合点 = GH 首跑 docker job）:
docker build --build-arg UV_DEPS_MODE=pip --build-arg UV_PIP_INDEX=https://pypi.org/simple/ -t agentic-kanban:ci .

# smoke（一律 --network host + AGENT_KANBAN_PORT + 轮询锚。T1 域外发现 2：产品绑容器内
# 127.0.0.1（Dockerfile ENV），`-p 127.0.0.1:X:8765` DNAT 到 eth0 结构性不可达容器 loopback，
# 生产容器 NetworkMode=host 佐证；冷启动实测 4-6s，sleep 3 不足。禁 -p 映射形态）:
docker run --rm ak-t1-g4 /app/.venv/bin/python -c "import agent_kanban"      # 预期 exit 0
docker run -d --network host --name ak-t1-smoke -e AGENT_KANBAN_PORT=18812 ak-t1-g4
for i in $(seq 30); do curl -s -o /dev/null http://127.0.0.1:18812/healthz && break; sleep 1; done
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:18812/healthz        # 预期 200（t=6s 实测）
docker stop ak-t1-smoke
```

（18812 = T1 实测端口，避开在跑的 8765；plan 原值 18811。）

## 实钉版本（实测）

| 项 | 值 | 出处 |
|---|---|---|
| python | 3.14.4（worktree .venv + t2/venv-pypi）；CI 由 setup-uv@v7 钉 python-version "3.14" | plan oracle 版本节（宿主实测 2026-10-26）；t2/s1-venv.log "Using CPython 3.14.4"；ci.yml:25 |
| node | 宿主 v24.21.0（本地 e2e / node --check）；CI 由 setup-node@v4 钉 22（防 runner 默认 node 漂移） | plan oracle 版本节；t3/r2/node-check.log "Node.js v24.21.0"；ci.yml:22 |
| docker | 29.9.2 | plan oracle 版本节（宿主实测） |
| uv | 宿主 0.11.12；容器内 `pip install uv` 未钉版 -> 0.13.5（pypi 轨 build 同链） | plan oracle 版本节；t1/g4.log [7/8] "Successfully installed uv-0.13.5" |
| @playwright/test | 1.64.1（package.json `^1.64.1`，lock 钉 1.64.1，registry.npmjs.org 生成）；浏览器 chromium-1248（宿主 Fedora 走 ubuntu24.04 fallback 构建；CI 实跑 Ubuntu 26.04 启动正常） | t3/net-probe.log:42 "chromium-1248"；package-lock.json；GH run 40330909867 |
| e2e 计时 | 12 spec / **12.7s**（workers=1）；墙钟 **13.9s**（含 webServer 起服务 + seed） | t3/g5.log:24-25；t3/g5.start / g5.end |
| GH runner | ubuntu-latest **实测 = Ubuntu 26.04**（image 20261012.163；2026-10-19 起标签迁移，调研 4.4 的 24.04 规格已过时） | GH run 40330909867 "Set up job" 段 |

## 证据索引（根目录 /home/shih/.tmp-ak-m16/ci-build/）

| 证据 | 路径 |
|---|---|
| 批次 ledger（门序/裁决/域外发现全记录） | ledger.md |
| plan 审三轮报告 | plan-review.md（333 行） |
| T1 红 R3（未改 Dockerfile pypi 轨 = no-op，全走 aliyun） | t1/r3.log |
| T1 红 G3（pypi 轨容器 MITM TLS 失败 [7/8]） | t1/g3.log |
| T1 绿 G4（默认轨 build）+ smoke（healthz 200 @t=6s）+ MITM 归因探针 | t1/g4.log + t1/smoke-probes.log（+ t1/mirror-root.pem） |
| T2 export + 断言 5/5 | t2/s1-export.log + t2/s1-export-assert.log |
| T2 venv / install 43 包（editable PEP 660）/ CWD 偏差保全件 | t2/s1-venv.log + t2/s1-install.log（+ t2/s1-install-attempt1-cwd-mainrepo.log） |
| T2 全量 514/514 | t2/s1-full.log |
| T2 保真论证（两 venv freeze diff = IDENTICAL） | t2/s1-fidelity.md + t2/freeze-worktree-venv.txt + t2/freeze-venv-pypi.txt |
| T2 YAML 有效性 + 命令同源对账表 | t2/s2-reconcile.md（+ t2/s2-extracted-script.py） |
| T3 网络前置探针（npm 双源 / 浏览器 CDN 降级） | t3/net-probe.log |
| T3 绿 G5 12/12 | t3/g5.log（+ g5.start / g5.end 墙钟） |
| T3 红 R1（断端口反证位） | t3/r1.log |
| T3 红 R2（坏壳 E1 断言红 + node --check 147 行红） | t3/r2/e1.log + t3/r2/node-check.log |
| 活体探针（attention_ids=[] + s3 事件 4 条） | t3/probe/live-probe.log |

## 红绿正典（本批三任务）

- **T1**（1c84174，Dockerfile 双轨 ARG）:
  - 红 R3: 未改 Dockerfile（f764794）跑 pypi 轨 build——ARG 未声明、`--build-arg` no-op，全日志走 aliyun、0 行 pypi/pythonhosted（t1/r3.log，616B dockerfile + [8/8] `RUN uv sync --frozen`）——证"不改则 CI 海外 build 只能赌 aliyun 可达性"
  - 红 G3（环境面）: pypi 轨容器 build，[7/8] uv 本体安装 TLS `CERTIFICATE_VERIFY_FAILED`（Knownsec 自签链，容器信任库 0 张，pip 5 重试同错 = 确定性非竞态）（t1/g3.log）
  - 绿 G4: 默认轨 build 成功（ARG 展开与旧 :12 逐字一致）+ import exit 0 + healthz 200 @t=6s（t1/g4.log + t1/smoke-probes.log）
- **T2**（7d53b63，ci.yml）:
  - 绿 S1: 模拟链全绿——export 断言 5/5（0 URL/aliyun、httpx2==、`-e .`、786/134 双口径）-> install 43 包（editable+hatchling PEP 660 首验段绿）-> import OK -> ② 两步链双 PASS -> 全量 514/514（t2/s1-export-assert.log + t2/s1-install.log + t2/s1-full.log）
  - 绿 S2: YAML OK + test job 5 命令全部在 S1 实跑过（对账表 5 条均"计划内同语义差异"：差仅在 -o 路径 / venv 定向+缓存 / OUT 取值 / TMPDIR，命令本体逐字一致，0 漂移）；docker build pypi 轨 = 未跑形态单列（闭合点 P5）（t2/s2-reconcile.md）
  - 红基线: T1-R3（机制依赖：不改 Dockerfile 则 docker job 必红）+ f764794 无 `.github/workflows/`（`git ls-files` 空 = CI 不存在）。无独立红跑（plan T2 oracle）
- **T3**（7eb6c3b，e2e 12 spec）:
  - 绿 G5: 12/12 @12.7s（t3/g5.log）；主循环独立复跑 12/12（12.7s，committed config `reuseExistingServer:false` 态）确认
  - 红 R1（反证位）: config baseURL sed 至 18799（服务不在该端口），E1 `net::ERR_CONNECTION_REFUSED`（t3/r1.log:16）——证测试真依赖活服务
  - 红 R2（历史坏壳 canary）: 坏壳 = f764794^ web.py（M1-6 前）——E1 断言红（boardReady:58 `#board-root .cols` toBeVisible 15s 超时，卡"加载中"；红因 = E1 断言非 webServer/端口/种子 infra）+ ② 两步链 `ak-board-0.js:147 SyntaxError`（= M1-6 P0 原签名，detail 壳 rc=0 对照有效）（t3/r2/e1.log + t3/r2/node-check.log）

## 盲区登记（e2e 不覆盖面）

1. **token 真机传播** — localhost 豁免下 e2e 无 token 场景；token 链已由后端套件 security 用例 API 层覆盖
2. **断网/重启 SSE 重连**（web.md 第 6 项）— 确定性模拟需掐网/杀服务，flaky 面最大；user 裁决留人工
3. **web.md 第 8 项（非 localhost 401）** — 后端套件已覆盖，e2e 不重复
4. **浏览器视觉与手感** — e2e 是契约锚（渲染/数据一致/操作/刷新），不做视觉回归
5. **A1-A5 静态防线固有边界**（承 m1-6-verification.md 盲区 2）— A2 假阴（破损行双引号恰偶数会漏）；A5 盲区 (a) esc 字面在场但注入点另取未转义值的诡计形态、(b) esc() 函数体未来被改坏（断言钉文本不钉实现）；A1 只钉 :279 本位。真实防线 = esc 实现（既有）+ e2e
6. **"(无任务)"空态**（web.md:46）— 需空 DB 服务，与 7 种子服务互斥；人工冒烟
7. **置顶顺序**（web.md:27/46）— Q2 裁决前 e2e 不断言置顶序（断言 = 镜像现实现）；E1 仅断言 s3 行 `.wait` 等待人横幅在场
8. **E4d 深链友好文案**（web.md:49）— Q1 裁决前 e2e 不覆盖，spec 内无该断言
9. **E6 的 note 触发器形态** — Q3 裁决前 E6 不代表"create 自动刷新"（E6 = create + note 触发 SSE，断言 = 新标题 15s 内上板）
10. **tests/bench.py / tests/alembic_diff.py** — 独立工具，不在 run_ac 门内，CI 不跑（plan 不修清单）

## 已知实践登记

1. **CI actions 以 tag 钉版**（actions/checkout@v4 / setup-node@v4 / setup-uv@v7，非全 SHA）— 单用户、无 secret 威胁模型下可接受（日志无 secret 面，仓 PUBLIC），二期再议升 SHA 钉版（plan 审 F10 补记）
2. **本地 npm 双源** — 宿主默认 registry = npmmirror（t3/net-probe.log:3）；package-lock.json 由 registry.npmjs.org 生成（T3 纪律）。后续本地 npm 操作（装新依赖等）须显式 `--registry=https://registry.npmjs.org` 或按 lock 走 `npm ci`，防锁与源漂移
3. **e2e 浏览器下载不加 GH 缓存** — 20-40s 在 15min timeout 预算内，缓存键维护不划算（不修清单，二期再议）
4. **actions Node.js 20 deprecation** — checkout@v4 / setup-node@v4 当前被 GH 强制跑在 Node 24（警告不红）；强制兼容策略撤销前须 bump 版本（GH 首跑警告在案，p5-gh-run1.full.log）

## 已知局限

- **办公网透明 MITM**（T1 域外发现 1，非本批引入）: mirrors.aliyun.com 与 files.pythonhosted.org 均 DNS 重写内网 10.10.0.117（宿主/容器一致），Knownsec 自签链（t1/mirror-root.pem 在档）。宿主 ca-trust 含该根（宿主级"办公网到 pypi 可达"成立），python:3.14-slim 容器信任库 0 张 -> **pypi 轨容器 build 在办公网确定性 TLS 失败**（非竞态：pip 5 重试同错；t1/g3.log [7/8]）。宿主级实证不可迁移到容器
- **处置**: 办公网一律默认轨（aliyun frozen）；pypi 轨仅限无 MITM 网络（海外 CI）。容器内 pypi 段（export + venv + uv pip install 全链，含 editable+hatchling PEP 660）主机级已由 T2-S1 闭合（t2/s1-full.log），容器级闭合点 = **GH 首跑 docker job**（runner 无 MITM，公开证书）——该 job 绿 = G3 闭合
- **user 知情项**: 办公网存在 TLS 拦截面（Knownsec 内网镜像），随本批交接

## Q1/Q2/Q3 交接（存量契约分歧三则，非本批引入，需 user 裁决）

三则均为基 commit f764794 已在的规范 vs 实现分歧，e2e 是首个会撞见它们的真浏览器层。按 E4d 先例处置：裁决前 e2e 不镜像现实现（不覆盖/不断言，禁按现实现改断言凑绿 = 陷阱库 3）。裁决权 = user。

### Q1 深链 404

- **分歧**: web.md:49"深链直接访问不存在的任务 -> 友好文案『任务不存在（可能已被人删除）』" vs 实现 = **404 JSON `{code:not_found}`，HTML 壳不送达**。证据：主循环活体探针（2026-10-26，容器 8765，浏览器 Accept 头，ledger P2 记录）+ 代码链 requirements.py:184-196 -> write_guard.py:13-16 抛 BusinessError(not_found) -> main.py:79-82 返回 JSONResponse 404；友好文案仅存于壳 JS web.py:371-373，仅当壳已送达（任务存在）才执行，前提不成立（plan-review.md F2）
- **两选项**: a) web.md 为准 = 产品缺陷立项（深链 404 送壳 + JS 友好文案，或 API 层 content-type 协商返回 HTML 404 页）；b) 实现为准 = 改 web.md 契约行
- **裁决前状态**: e2e 不覆盖此项，套件无该断言

### Q2 置顶

- **分歧**: web.md:27/46"需要关注需求置顶（attention_ids）" vs 现行四列状态序壳——`renderActive` 无 attention 排序（web.py:193-207 主循环实读），`t._attn` 仅供卡片徽章；b05e73b UI 重构起。活体探针实测本种子集 `attention_ids=[]`（t3/probe/live-probe.log:2）
- **两选项**: a) web.md 为准 = 立项实现 attention 置顶排序；b) 实现为准 = 改 web.md（"按四列状态分组，需要关注以卡片徽章表达"）
- **裁决前状态**: e2e 不断言置顶序（E1 改断言 s3 行 `.wait` 等待人横幅在场）

### Q3 create 无事件

- **分歧**: `new_requirement` 无 add_event（services/operations.py:87-113 主循环实读；壳自述 web.py:292"create 不写事件，SSE 无触发器——主动重拉"）-> agent 新建任务时人面看板不自动刷新；web.md:51"另一进程推进状态 -> 页面 2s 内自动刷新"未覆盖创建场景
- **两选项**: a) web.md 为准 = create 补 add_event（SSE 触发）；b) 实现为准 = 改 web.md 补"创建不刷新看板，待下一事件触发"（或前端壳加周期重拉）
- **裁决前状态**: e2e 不断言"create 即刷新"（E6 补 note 触发器执行，断言不变）

## 分支保护操作交接（user 执行，agent 不碰仓设置）

- 仓库: hallelujah-shih/agentic-kanban（public）
- 必需 check = `test` + `docker`（job 名即 check 名；.github/workflows/ci.yml:15 `name: test` / :56 `name: docker`）；e2e 待观察一两周无连红后补设

**a) 网页路径**（docs.github.com 2026 现行入口，写前已核对 "Managing a branch protection rule"）:
1. 仓库主页 -> **Settings**（无 Settings 页签时：右上角 `...` 下拉 -> Settings）
2. 左侧栏 "Code, planning, and automation" 节 -> **Branches**
3. "Branch protection rules" 下点 **Add classic branch protection rule**
4. Branch name pattern 填 `main`
5. 勾选 **Require status checks to pass before merging**，搜索框选 `test`、`docker`
6. 点 **Create**

**b) gh 命令**（required_status_checks 子端点；分支尚无保护规则时该端点 404，先走第 1 条创建）:

```
# 1) 首次创建保护规则 + 必需 check（PUT /branches/main/protection，一次成型）:
gh api repos/hallelujah-shih/agentic-kanban/branches/main/protection -X PUT --input - <<'JSON'
{
  "required_status_checks": { "strict": false, "contexts": ["test", "docker"] },
  "enforce_admins": null,
  "required_pull_request_reviews": null,
  "restrictions": null
}
JSON

# 2) 核验:
gh api repos/hallelujah-shih/agentic-kanban/branches/main/protection/required_status_checks

# 3) 规则已存在时（如网页已建）只改必需 check（PATCH 子端点）;
#    观察期满后补 e2e = 同一命令 contexts 改 ["test","docker","e2e"]:
gh api repos/hallelujah-shih/agentic-kanban/branches/main/protection/required_status_checks -X PATCH --input - <<'JSON'
{ "strict": false, "contexts": ["test", "docker"] }
JSON
```

（strict=false = 不要求合入前分支最新（loose）；如需 up-to-date 改 true。）

## GH 首跑记录（PR #4，run 40330909867，2026-10-26，merge 前置证据）

三 job 全绿：test 2m43s / e2e 41s / docker 18s（runner 实测 Ubuntu 26.04）。关键证据（p5-gh-run1.full.log，产物目录 /home/shih/.tmp-ak-m16/ci-build/）：
- test: `== 结果: 514/514 PASS`（GH 单一 pypi venv 态首测，混合态保真缺口 0 论证 t2/s1-fidelity.md 收口）+ 壳 node --check 步在场
- e2e: `12 passed (12.8s)`（npm ci 跨 registry 复现 + `--with-deps chromium` ubuntu apt 全通）
- docker: pypi 轨实证（`pip install uv --index-url https://pypi.org/simple/` + export/venv/`UV_INDEX_URL=pypi uv pip install` 分支展开）= **G3b 闭合**（T1-G3 环境面阻塞双点收口完毕）
- 观察项（非缺陷）: actions/checkout@v4 与 setup-node@v4 触发 Node.js 20 deprecation 警告（被强制跑在 Node 24）——强制兼容期内无碍，强制策略撤销前须 bump action 版本（已知实践 4）；setup-uv 并行 job cache 抢占警告一次（自动恢复）

## P5 未核区登记（交接）

1. ~~GH runner 全链~~ **已收口**（上节 GH 首跑记录，2026-10-26）
2. **E6 单次运行无 flaky 样本**（12/12 单样本 + GH 首跑单样本）；CI `retries:1` 已预置（playwright.config.js:13，仅 CI env 生效）+ e2e 首期非必需 check = 限险双保险
