# 调研：headless Linux 上让 agent 登录内网（SSO）并抓取认证页面

日期: 2026-10-23
场景: agent 处理"来源指针 = Jira"的需求时，collab2markdown 等 MCP 不可用的环境里，
需要自己完成公司 SSO 登录、拿到会话 cookie、再取页面内容。Jira 只是第一个例子，
方案对任何 SSO 保护的内网页面（Confluence、内部 wiki）通用。
配套参考实现: `tools/intranet_fetch.py`（本文所有结论已用它在本机实测验证）。

## 1. 环境与前提（Phase 0）

- Fedora 44 Workstation；agent 会话**无 DISPLAY**（纯 headless）
- 系统已装 Google Chrome / Firefox；py-playwright 1.62.0 + 浏览器缓存齐全
  （`~/.cache/ms-playwright/`，uv 隔离 venv 与系统 python 共享该缓存）
- uv 工作流；参考实现是 PEP 723 单文件脚本（`uv run tools/intranet_fetch.py`）

## 2. 为什么必须走浏览器（Five Whys）

1. 为什么 agent 拿不到 Jira 页面？——内网 SSO 保护，未认证请求 302 到登录页。
2. 为什么不能像普通 API 那样带 token？——公司 Jira 处于 SSO 管控下。
3. 那 REST API + 账号密码（basic auth）呢？——**不行**：Atlassian 官方社区确认
   SSO 开启的 Jira 不接受用户名密码的 basic auth（变通只有内部账号或管理员签发 token）。
4. 那管理员签发 PAT / API token 呢？——可以，且是最优解（**Tier 0**）：
   Cloud 用 API token（basic: email+token），DC 8.20+/9.x 用 PAT（bearer）。
   **但前提是管理员愿意签发**；内网 Server 老版本 + SSO 锁死时此路不通。
5. 所以浏览器登录是"没有 token 时的通用路径"，不是技术偏好——cookie 就是 SSO
   签发的会话凭证，浏览器只是获取它的标准手段。

**分层结论**：能拿到 PAT/API token 就用它（无浏览器、无会话过期问题）；
拿不到就本文的浏览器方案。

## 3. 方案对比

| 方案 | 结论 |
|---|---|
| **Playwright 脚本 CLI**（参考实现采用） | 登录一次导出 state，抓取走纯 HTTP。agent 调用面 = 一条 shell 命令，无长驻进程，成本最低 |
| Playwright MCP（microsoft/playwright-mcp） | agent 直接操控浏览器（persistent/isolated/extension 三种 profile 模式）。适合"页面交互多、需要人看着 agent 点来点去"；本场景 90% 是"取内容"，MCP 的 token 成本与不确定性不划算。可作为交互增强二期 |
| browser-use / 通用 AI 浏览器库 | 自带视觉/决策循环，与"agent 自己就是大脑"重叠；引入额外模型调用，不采用 |
| Selenium | 能力等同 Playwright，但等待/状态导出 API 不如 Playwright 现代（storageState/persistent context 是一等公民） |
| 人肉从日常浏览器拷 cookie | 不可自动化，agent 无法闭环；只作应急 |

## 4. 实测踩坑（文档里读不到，全部本机复现）

靶场: stdlib 搭的 SSO 风格登录服务（登录 -> 302 /sso/verify 发 cookie -> 302 /home，
模拟多跳重定向发 cookie），playwright 驱动 chromium。

**坑 1：SSO 常用 session cookie（expires=-1），Chromium 默认不落盘。**
persistent context（user-data-dir）登录 -> close -> 重开：cookie 丢失，401。
profile 的 `Default/Cookies` SQLite 表是**空的**——session cookie 压根没写进去。

**坑 2：`--preserve-session-state`（Chrome 118+ 官方方案）在 Playwright 驱动下无效。**
bundle 的 headless_shell 与系统 Chrome（headless=new）都试过，加
`--preserve-session-state --preserve-session-state-storage-types=Cookies,Localstorage`
均不生效。根因：Chromium 的会话保存只在**正常退出**时触发，而 Playwright 通过
CDP `Browser.close` 结束浏览器——是"杀进程"语义，不走正常退出路径。
（推论：凡是 Playwright/Puppeteer 驱动的自动化，别指望 profile 级会话持久化。）

**坑 3：所以持久化要靠"登录时导出"，不靠浏览器 profile。**
`context.storage_state(path=...)` 在登录成功后把**内存中**的 cookie（含 session
cookie）+ localStorage 落盘成 JSON——这是唯一在实测中可靠的复用介质。
SSO 的长期 token 若放 localStorage，storage_state 一并带走（profile 方案即使
cookie 侥幸保住也会漏掉 localStorage，storage_state 更完整）。

**坑 4（正面结论）：cookie 可直接给纯 HTTP 用，取页不需要每次起浏览器。**
导出的 cookie 拼进 `Cookie` 头，urllib/curl 直接取 200 + 正文。浏览器只在
"会话过期要续"或"页面必须 JS 渲染"时才起。

**登录成功判定**：SSO 多跳 302 下，别盯"登录表单消失"，等**最终 URL**
（playwright `wait_for_url` / 轮询 URL 前缀）——cookie 是在跳转链中途中发的。

## 5. 参考实现架构（tools/intranet_fetch.py，~200 行，实测 7 场景通过）

```
login  --site jira --url <登录页> [--username u] [--success-url 串]
       headless 自动填表（选择器可配）；2FA 时 --headed 在有显示的终端手动完成
       成功后导出 ~/.agent-browsers/<site>/state.json（0600）
fetch  --site jira --url <页面> [--browser]
       默认纯 HTTP（cookie 头，毫秒级）；401/403/跳登录页 = 会话过期：
       无 --browser -> 明确报错"重跑 login"
       有 --browser -> headless 浏览器带 state 重试（SSO 会话若活着可自动续期，
       cookie 集变化时自动重新落盘 state）；SSO 已死 -> 明确报错"重跑 login"
status --site jira
       state mtime / cookie 数（会话 vs 持久）/ 最近过期
```

实测场景（靶场 2 跳 SSO）：headless 自动登录、纯 HTTP 取页、浏览器取页、
status、未登录报错、过期后两条路径的报错信息——全部符合预期。

## 6. 安全边界

- **密码**只从环境变量读（`AGENT_<SITE>_PW`），不进命令行参数（避免 shell 历史）、
  不进 git、不进看板事件流、不进日志输出
- **state.json 是会话凭证**：0600、不进 git（目录在 `~/.agent-browsers/`，仓外）、
  不进看板；泄露 = 会话被冒用，过期即失效（SSO 策略决定窗口）
- 抓取输出（页面正文）可能含敏感内容：进看板时遵守"来源指针 + 摘要"纪律，
  不整页倒进 note

## 7. Jira 专项注记

- cookie 不只用来取 HTML：拿到会话 cookie 后可以打 Jira REST
  `GET /rest/api/2/issue/<KEY>`（带 Cookie 头）直接得结构化 JSON——
  比解析 HTML 稳。**优先顺序：PAT > 会话 cookie + REST > 会话 cookie + 页面 HTML**
- SSO 跳数/登录页路径因公司而异：`--success-url` 给"登录后一定包含的串"
  （如域名或 /secure/），登录页特征（login/sso/cas）工具已内置启发式
- 具体表单字段名以 `--username-selector/--password-selector/--submit-selector`
  覆盖；2FA 策略（是否有、周期多长）需要内网首登一次才知道（见下）

## 8. 边界与未知（诚实声明）

- 未对真实公司 SSO 验证过：本方案验证的是**机制**（表单登录/多跳重定向/
  session cookie/过期续期），真实环境的差异在"登录页长什么样 + 2FA 策略 +
  cookie 有效期"，首登一次即可标定（10 分钟内）
- 2FA 路径（--headed + 无 DISPLAY 机器需 Xvfb/VNC 或换有显示的终端）未实测
  ——本机没有 Xvfb，机制上等价于"人在浏览器里手动登录，脚本等着导出"
- 反爬/指纹检测：内网 SSO 通常无此问题；若目标有，headless 指纹可被识别，
  需要 headed 或指纹伪装（超出本调研范围）

## 9. 参考来源

- Playwright 官方 auth 文档（storageState / persistent context 两种模式）
- microsoft/playwright-mcp（profile 模式表：persistent/isolated/extension）
- Atlassian 官方: Basic auth for REST APIs（API token）; PAT 文档（DC）
- Atlassian Community: "Basic Auth JIRA's Rest API (with SSO enabled)"
  （SSO 下 basic auth 不可用的官方确认）
- 本机实测（本文第 4 节，靶场脚本在 /tmp/opencode/login_srv*.py，可复跑）
