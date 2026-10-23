#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright==1.62.0"]
# ///
"""内网认证页面抓取：浏览器登录一次，cookie 复用取页面（无 MCP 场景）。

原理（docs/research/browser-login.md 有完整调研与实测证据）：
- 登录：playwright 驱动 chromium 填表提交，成功后导出 storage_state
  （内存中的 cookie 含 session cookie + localStorage）到 ~/.agent-browsers/<site>/state.json
  （0600）。Chromium 不落盘 session cookie、Playwright 的 CDP 关闭方式让
  --preserve-session-state 失效，所以持久化靠导出文件而不是浏览器 profile。
- 抓取：默认纯 HTTP（urllib + cookie 头，不启动浏览器）；401/403/跳登录页
  视为会话过期——加 --browser 时启动 headless 浏览器带 state 重试（SSO 会话
  若还活着可自动续期，成功后自动重新导出 state）。
- 2FA：login 加 --headed，在有显示的终端手动完成，脚本等成功后导出。

用法：
  AGENT_JIRA_PW='...' intranet_fetch.py login --site jira \
      --url https://jira.intra/secure/Dashboard!draftboard.jsp --success-url jira.intra
  intranet_fetch.py fetch --site jira --url https://jira.intra/browse/PROJ-1 [--browser]
  intranet_fetch.py status --site jira

安全：密码只从环境变量读（不进命令行历史）；state.json 是会话凭证，0600，
不进 git、不进看板事件流、不进任何日志输出。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(os.environ.get("AGENT_BROWSER_HOME", str(Path.home() / ".agent-browsers")))
LOGIN_HINTS = ("login", "signin", "sign-in", "sso", "/auth", "cas/")


def state_path(site: str) -> Path:
    return BASE_DIR / site / "state.json"


def load_state(site: str) -> dict:
    p = state_path(site)
    if not p.exists():
        sys.exit(f"site '{site}' 未登录：先跑 login（state 文件 {p} 不存在）")
    return json.loads(p.read_text())


def save_state(site: str, state: dict) -> Path:
    p = state_path(site)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False))
    os.chmod(p, 0o600)
    return p


def cookie_header_for(state: dict, url: str) -> str:
    u = urlparse(url)
    host = u.hostname or ""
    parts = []
    for c in state.get("cookies", []):
        dom = (c.get("domain") or "").lstrip(".")
        if not dom or not (host == dom or host.endswith("." + dom)):
            continue
        if not u.path.startswith(c.get("path") or "/"):
            continue
        parts.append(f"{c['name']}={c['value']}")
    return "; ".join(parts)


def looks_like_login(url: str) -> bool:
    low = (urlparse(url).path + "?" + urlparse(url).query).lower()
    return any(h in low for h in LOGIN_HINTS)


# ---------------------------------------------------------------- login


def cmd_login(args: argparse.Namespace) -> int:
    pw_env = args.password_env or f"AGENT_{args.site.upper()}_PW"
    password = os.environ.get(pw_env, "")
    if not password and not args.headed:
        sys.exit(f"headless 登录需要密码：export {pw_env}='...' 后重跑（或 --headed 手动登录）")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(args.url, wait_until="domcontentloaded")
        login_url = page.url
        if args.headed:
            print(f"headed 模式：请在浏览器窗口手动完成登录（含 2FA）；"
                  f"成功后脚本自动导出（超时 {args.timeout}s）", flush=True)
        else:
            page.fill(args.username_selector, args.username)
            page.fill(args.password_selector, password)
            page.click(args.submit_selector)
        deadline = time.monotonic() + args.timeout
        ok = False
        while time.monotonic() < deadline:
            if args.success_url:
                if args.success_url in page.url:
                    ok = True
                    break
            elif page.url != login_url and not looks_like_login(page.url):
                ok = True
                break
            time.sleep(0.5)
        if not ok:
            sys.exit(f"登录未成功（{args.timeout}s 内未到达成功 URL）：当前 {page.url}\n"
                     f"若遇 2FA/图形验证：--headed 重跑并手动完成")
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        final_url = page.url
        state = ctx.storage_state()
        path = save_state(args.site, state)
        cookies = state.get("cookies", [])
        browser.close()
    expires = [c["expires"] for c in cookies if c.get("expires") and c["expires"] > 0]
    near = (datetime.fromtimestamp(min(expires), tz=timezone.utc).isoformat()
            if expires else "会话 cookie（无固定过期，随 SSO 策略）")
    print(f"登录成功：{final_url}\ncookie {len(cookies)} 个 -> {path} (0600)\n最近过期: {near}")
    return 0


# ---------------------------------------------------------------- fetch


def fetch_http(state: dict, url: str, timeout: float) -> tuple[int, str, str]:
    req = urllib.request.Request(url, headers={"Cookie": cookie_header_for(state, url),
                                               "User-Agent": "agent-intranet-fetch/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), e.url


def fetch_browser(site: str, state: dict, url: str) -> tuple[str, str, str]:
    """返回 (text, html, final_url)；cookie 集变化时自动重新落盘 state。"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=state)
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        text, html, final_url = page.inner_text("body"), page.content(), page.url
        new_state = ctx.storage_state()
        browser.close()
    if {c["name"]: c["value"] for c in new_state.get("cookies", [])} != \
       {c["name"]: c["value"] for c in state.get("cookies", [])}:
        save_state(site, new_state)
        print("[state 已自动续期]", file=sys.stderr)
    return text, html, final_url


def cmd_fetch(args: argparse.Namespace) -> int:
    state = load_state(args.site)
    status, body, final_url = fetch_http(state, args.url, args.timeout)
    expired = status in (401, 403, 407) or looks_like_login(final_url)
    if not expired:
        print(body)
        return 0
    if not args.browser:
        sys.exit(f"会话已过期（HTTP {status}，最终 URL {final_url}）：重跑 login，或加 --browser 尝试浏览器续期")
    print(f"纯 HTTP 被拒（HTTP {status}）-> 浏览器路径", file=sys.stderr)
    text, html, burl = fetch_browser(args.site, state, args.url)
    if looks_like_login(burl) or len(text.strip()) < 40:
        sys.exit("浏览器路径也未通过认证：SSO 会话已死，重跑 login（2FA 用 --headed）")
    print(html if args.html else re.sub(r"\n{3,}", "\n\n", text))
    return 0


# ---------------------------------------------------------------- status


def cmd_status(args: argparse.Namespace) -> int:
    p = state_path(args.site)
    if not p.exists():
        print(f"site '{args.site}': 未登录（{p} 不存在）")
        return 1
    st = json.loads(p.read_text())
    cookies = st.get("cookies", [])
    sess = sum(1 for c in cookies if not c.get("expires") or c["expires"] <= 0)
    pers = [c for c in cookies if c.get("expires") and c["expires"] > 0]
    near = min((c["expires"] for c in pers), default=None)
    print(f"site '{args.site}': state {p} (mtime {datetime.fromtimestamp(p.stat().st_mtime):%Y-%m-%d %H:%M:%S})")
    print(f"cookie {len(cookies)} 个（会话 {sess} / 持久 {len(pers)}）")
    if near:
        print(f"最近过期: {datetime.fromtimestamp(near, tz=timezone.utc).isoformat()}")
    else:
        print("最近过期: 无持久 cookie 过期信息（会话 cookie 随 SSO 策略）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("login", help="浏览器登录并导出 state")
    pl.add_argument("--site", required=True)
    pl.add_argument("--url", required=True, help="登录页 URL")
    pl.add_argument("--username")
    pl.add_argument("--password-env", help=f"密码环境变量名（默认 AGENT_<SITE>_PW）")
    pl.add_argument("--username-selector", default="input[name=username], input[name=userId]")
    pl.add_argument("--password-selector", default="input[type=password]")
    pl.add_argument("--submit-selector", default="button[type=submit]")
    pl.add_argument("--success-url", help="登录成功后 URL 包含串（SSO 多跳时建议给）")
    pl.add_argument("--headed", action="store_true", help="有显示的终端手动登录（2FA）")
    pl.add_argument("--timeout", type=int, default=120)
    pl.set_defaults(fn=cmd_login)

    pf = sub.add_parser("fetch", help="抓页面（默认纯 HTTP，--browser 走浏览器）")
    pf.add_argument("--site", required=True)
    pf.add_argument("--url", required=True)
    pf.add_argument("--browser", action="store_true", help="认证失败时启动 headless 浏览器重试")
    pf.add_argument("--html", action="store_true", help="浏览器路径输出原始 HTML（默认输出渲染后纯文本）")
    pf.add_argument("--timeout", type=float, default=30)
    pf.set_defaults(fn=cmd_fetch)

    ps = sub.add_parser("status", help="查看 state 与 cookie 状态")
    ps.add_argument("--site", required=True)
    ps.set_defaults(fn=cmd_status)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
