# 独立包交付形态验收（skill-package 批）

日期: 2026-10-30
需求: ef007e262e9046cda1a8aa470126b6bd（交付形态自足：agent-kanban 作为 MCP + skill 树独立包）
工作区: `.worktree/ak-skill-package`（分支 feat/skill-package）
产物目录: `/home/shih/.tmp-ak-m16/skill-package/`（临时；重跑脚本与结论已落仓内）

## 1. 交付形状

`skills/agent-kanban/` 是**唯一来源**（入口 + references + templates 一棵树），构建期由 hatchling
force-include 注入 wheel 的 `agent_kanban/data/skill/`，取出入口是
`agent-kanban skill --print | --dest <父目录> | --check [目录]`。不存在第二份副本。

```
skills/agent-kanban/
├── SKILL.md                       入口：安装三步 / 版本对齐 / 工具命名 / 分层与何时读哪个 /
│                                  门序 / 认领纪律 / 工作区就绪 / 记录纪律 / 报告纪律 /
│                                  交接与等待 / Session 与恢复 / 派发指针 / 收尾协议 /
│                                  高频错误码（4 条）/ 诚实与归属 / 参考
├── references/
│   ├── contract.md                状态机边 / 租约双时钟 / 写保护 / 视图与回溯（唯一权威）+ 永久 URL
│   ├── errors.md                  错误码全表与处置（唯一权威）
│   ├── dispatch.md                派发方协议内核（五要素语义唯一权威，无客户端细节）
│   ├── client-opencode.md         客户端适配（OpenCode）：落点 / 注册 JSON / 派发续跑 / 恢复 / 模型继承
│   └── project-conventions.md     项目侧可选约定：环境卡 / 产物落点 / 本机分区 / 临时目录政策
└── templates/
    ├── env-card.md                环境卡模板
    ├── dispatch-brief.md          派发稿模板（形状；语义见 references/dispatch.md）
    └── requirement.md             需求登记模板（workspace 指针 + 验收锚）
```

镜像通道：`Dockerfile` 会 `COPY skills ./skills`（`.dockerignore` 不再排除它）——force-include 源不在
构建上下文里时 `uv sync` 阶段就会失败，故镜像内同样能 `skill --dest` 取出整棵树。实跑（默认轨）：

| 观测 | 结果 |
|---|---|
| build | `docker build -t ak-skillpkg-t1 .` rc 0（`[6/9] COPY skills` 在位） |
| import | `python -c "import agent_kanban"` => `0.1.0`，rc 0 |
| 镜像内断链检查 | `agent-kanban skill --check` => `14 个 skill 自引用全部存在` |
| 镜像内取出 | `skill --dest /tmp/sk` => 9 文件；再 `--check /tmp/sk` 全通过 |
| smoke | `--network host` + `AGENT_KANBAN_PORT=18831`，healthz 200 @t=8s，DB 0600 |
| CI（PR #21） | `test` / `e2e` / `docker` 三 job 全绿；docker job 走 pypi 轨（`UV_DEPS_MODE=pip`）验证同一 `COPY skills` 在无 MITM 环境成立 |

## 2. 自动化判据（进 AC 套件）

| 用例 | 断言要点 | 结果 |
|---|---|---|
| `p3_skill` | wheel 内 `agent_kanban/data/skill/` 文件集合与源一致且逐字节相同（单一来源）；解压后被测 `cli` 确实来自 wheel 树；`--print` 字节一致；`--dest` 复制出整棵树且与源一致；三种错误用法（缺省选项 / `--print` 与 `--dest` 同给 / `--dest` 指向普通文件）均 rc 1 + stderr 人话，不裸 traceback，不落残留；`dispatch` 派发稿的协议入口在 wheel 安装下 `is_file()` | 9/9 PASS |
| `p3_skill_text` | 树内全部 `.md` 无仓内相对路径引用（token 判据：含 `://` 的永久 URL、`<skill_dir>/`、四类装机落点放行）；AGENTS.md/docs 带仓内限定词（本仓/仓内/仓库根…）即红；判据正反对照自检（回潮必红、adopter 约定必绿）；自引用只允许 `<skill_dir>/` 或行内裸 `references/`；SKILL.md 覆盖 `build_server()` 真实注册表全部工具名；description 与「工具命名」节说明两种客户端前缀；`agent_kanban_` 全文不出现；description ≤1024；安装事实与代码反读一致（Python 下界 / 入口 / 默认 DB / 四类落点）；版本链一致（代码常量 = frontmatter = PRD 首行 = MCP server）；`--version` 同给两版本；SKILL.md 无客户端/本机特有内容且这些内容确实下沉到 references（不是被删）；分层到位（≤500 行、references≥4、templates≥2、每个 reference 在正文有时机说明、无 `scripts/`、无 `.sh`/`.py`、四个必执行节非空、正文错误码 1-4 行）；环境卡模板已下沉；errors.md 覆盖服务端错误码全表 | 16/16 PASS |
| `p3_skill_links` | 树内 `<skill_dir>/…` 与裸 `references\|templates/…` 引用（含嵌套/大小写/通配）逐个存在（独立于 CLI 的第二判据）；`<skill_dir>` 语义（＝加载目录绝对路径）在 SKILL.md 与 dispatch.md 各写明；`skill --check` rc 0 并报引用数；`--dest` 副本注入一条断链后 `--check <父目录>` rc 1 且点名该文件；`--check <skill 目录本身>` 等价可用；非 UTF-8 的 `.md` 报为问题而非裸 traceback；`--check` 指向不存在目录 rc 1 + 人话 | 7/7 PASS |

本地最高 tier 结论（PR #21，commit 2632c2f 起）：全量 **950/950 PASS**（`full-5.log`）+ e2e **15/15**
（`e2e.log`）+ docker 默认轨 build/healthz 200 + CI 三 job 全绿。

红基线：`red-p3-v8.log`（结构未落地时跑同一组用例）**14/24 PASS**，10 条红全部指向本批目标面：
wheel 内无 skill 树、`--dest` 裸 traceback、`dispatch` 协议入口指向不存在路径、SKILL.md 含
`opencode.json`/`opencode run`/`ses_`、references 为零、环境卡模板内联、`<skill_dir>` 引用为零。

a1 文本红另有一份独立证据（结构改造前的单文件版）：`git show HEAD:skills/agent-kanban/SKILL.md`
按 token 判据扫出 **5 处**仓内路径命中（`docs/PRD.md` ×2、`docs/mcp-config.md`、`mcp-config.md`
裸形、`cli.py`），日志 `red-a1-head.log`。改造后同一判据 0 命中。

## 3. 空目录验收（a6，一次性真机）

判据：与本仓无关的空目录里，只靠 pip 装的 wheel + 取出的 skill 树，按 SKILL.md 的安装三步部署并连上看板。

脚本（仓内永久位置，自包含，含极简 MCP stdio 客户端）：`tests/manual/a6-empty-dir.sh`

```sh
bash tests/manual/a6-empty-dir.sh <批次目录>/a6-v8 <批次目录>/dist-v8/agent_kanban-<版本>-py3-none-any.whl
```

实跑输出（2026-10-30）：

| 步 | 观测 |
|---|---|
| 装包 | `uv venv` + `uv pip install --offline <wheel>` 成功（命中本机 uv 缓存） |
| 版本 | `agent-kanban 0.1.0 (contract 3.2)` |
| 建 DB | 首次 `new` 自动建表；`stat` => `DB 600 .../kanban.db` |
| 落 skill | `--dest .opencode/skills` 产出 9 个文件（SKILL.md + references×5 + templates×3） |
| 断链检查 | `--check .opencode/skills` => `14 个 skill 自引用全部存在` |
| 连看板 | MCP stdio `list_tasks` => `1 条: a6 空目录验收 / OPEN` |
| 环境独立 | 空目录不是 git 仓；全程未读本仓任何文件（无 clone） |

## 4. 为何不把 a6 放进 AC 套件

a6 需要「新建 venv + 装全部运行依赖 + 起真实 MCP 子进程」，成本与环境耦合（CI 无 uv 缓存时必须联网装
30+ 依赖，属另一条失败面）。AC 已覆盖同一链路里**由本仓代码保证**的部分（wheel 内容与逐字节一致、
解包后 CLI 行为、`--check` 判别力），a6 只剩「装得下、起得来」，故按一次性真机 + 本文档 + 可重跑脚本守住。

## 5. 已知行为与判据边界

- `--dest <父目录>` **静默覆盖**同名文件（无 `--force`），但**不删除**目标里已不存在的旧文件：
  升级后若有文件改名/删除，先删 `<父目录>/agent-kanban/` 再取。
- `--check <目录>` 两种传法等价：`--dest` 用的父目录，或 `<父目录>/agent-kanban/` 本身。
  不带参数时检查包内树。
- 引用识别范围为 `references/`、`templates/` 下带 `.md` 的路径（含嵌套、大小写、通配符——通配符判缺，
  逼作者写实名文件）；其它散落链接（如指向仓外 URL、指向 `SKILL.md` 自身）不在断言面内。
- a1 的 `AGENTS.md` 判读口径：**裸文件名**是 adopter 自己的项目约定（「项目根的 AGENTS.md」），放行；
  带仓内限定词（本仓 / 仓内 / 仓库内 / 本仓库 / 仓库根）即红。同理裸 `docs/`、`README`。
- token 判据放行 `file:///x/docs/PRD.md` 这类伪 URL（含 `://` 即视为外部深挖入口），登记为边界。
- 包内 skill 树是构建期快照；改协议必须重新构建 wheel（editable 安装下 `--print`/`--dest` 回退到源码树，
  两者一致性由 `p3_skill(1)(2)` 断言）。
