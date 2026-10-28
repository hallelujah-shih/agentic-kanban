"""B2 dispatch：需求 -> opencode worker 会话主链（plan「dispatch 步骤 1-10」）。

服务发现：URL 与鉴权分离——URL＝env AGENT_KANBAN_OPENCODE_URL > `opencode service
status` 末行（subprocess，10s）；鉴权＝env AGENT_KANBAN_OPENCODE_AUTH=none 不发头，
否则读 ~/.config/opencode/service.json 的 password 发 Basic（strace 实锤）。
约束：stdlib urllib（不加依赖）；P-imp1 不自动拉起服务、不重试；密码永不进
stdout/错误消息（URL 可回显）。
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import socket
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .db import get_read_session_factory, get_session_factory, run_op
from .services import operations as ops
from .services.ids import norm_id
from .services.identity import cli_actor
from .services.write_guard import require_requirement

URL_ENV = "AGENT_KANBAN_OPENCODE_URL"
AUTH_ENV = "AGENT_KANBAN_OPENCODE_AUTH"
SERVICE_JSON = Path.home() / ".config" / "opencode" / "service.json"
DISPATCHABLE_STATES = ("OPEN", "REOPEN")
_SERVICE_TIMEOUT = 10  # 服务发现 subprocess 超时（秒）


class DispatchError(Exception):
    """dispatch 链错误（code: message，handler 打印到 stderr 并返回 1）。"""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class Service:
    url: str
    auth_header: str | None


# ---------------------------------------------------------------- 参数解析
def parse_budget(raw: str | None) -> int | None:
    """裸数＝秒；支持 h/m/s 后缀。缺省 None（无预算封顶）。"""
    if raw is None or not raw.strip():
        return None
    m = re.fullmatch(r"(\d+)([hms]?)", raw.strip())
    if not m:
        raise DispatchError("invalid_budget", f"预算解析失败: {raw!r}（裸数＝秒，支持 h/m/s 后缀）")
    secs = int(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600}[m.group(2)]
    if secs <= 0:
        raise DispatchError("invalid_budget", f"预算须为正数: {raw!r}")
    return secs


def split_model(raw: str | None) -> dict | None:
    """--model provider/model 按首个 / 拆 providerID/model id；缺省 None（服务默认，Q3）。"""
    if raw is None:
        return None
    provider, sep, model_id = raw.partition("/")
    if not sep or not provider or not model_id:
        raise DispatchError("invalid_model", f"model 须为 provider/model 形态: {raw!r}")
    return {"id": model_id, "providerID": provider}


def _parse_pointers(description: str | None, explicit_dir: str | None
                    ) -> tuple[str | None, str | None, list[str]]:
    """指针行解析（P-imp6：只抽字面量，不解释环境卡）。

    按空白切 token 扫描：首个以 workspace= / env-card= 开头的 token 生效
    （值＝= 后全部，非空）；无行首/行尾锚（单行两键标准格式靠 token 化，分行两键
    同覆盖）；workspace 值须 / 开头绝对路径，否则忽略并警示；--dir 显式优先。
    指针缺失不阻塞（worker 就绪门分级处置），派发稿带警示。
    """
    warnings: list[str] = []
    ws: str | None = None
    env_card: str | None = None
    if description:
        for tok in description.split():
            if ws is None and tok.startswith("workspace="):
                val = tok[len("workspace="):]
                if not val:
                    warnings.append(f"workspace 指针值为空，忽略: {tok}")
                elif not val.startswith("/"):
                    warnings.append(f"workspace 指针非绝对路径，忽略: {tok}")
                else:
                    ws = val
            elif env_card is None and tok.startswith("env-card="):
                val = tok[len("env-card="):]
                if val:
                    env_card = val
    if explicit_dir:
        ws = explicit_dir
    if ws is None:
        warnings.append("workspace 指针缺失（worker 就绪门分级处置）")
    if env_card is None:
        warnings.append("环境卡指针缺失（worker 就绪门分级处置）")
    return ws, env_card, warnings


# ---------------------------------------------------------------- 服务发现
def discover_service() -> Service:
    url = (os.environ.get(URL_ENV) or "").strip()
    if not url:
        try:
            out = subprocess.run(["opencode", "service", "status"],
                                 capture_output=True, text=True, timeout=_SERVICE_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired):
            raise DispatchError(
                "service_unreachable",
                f"opencode 服务发现失败（`opencode service status` 执行失败）；可用 {URL_ENV} 覆盖") from None
        if out.returncode != 0:
            raise DispatchError(
                "service_unreachable",
                f"opencode 服务发现失败（service status rc={out.returncode}）；可用 {URL_ENV} 覆盖")
        url = out.stdout.strip().splitlines()[-1].strip() if out.stdout.strip() else ""
        if not url:
            raise DispatchError(
                "service_unreachable",
                f"opencode 服务发现失败（service status 输出无 URL 行）；可用 {URL_ENV} 覆盖")
    url = url.rstrip("/")
    if (os.environ.get(AUTH_ENV) or "").strip() == "none":
        return Service(url=url, auth_header=None)
    try:
        pw = json.loads(SERVICE_JSON.read_text(encoding="utf-8")).get("password")
    except (OSError, json.JSONDecodeError):
        raise DispatchError("auth_missing", f"鉴权配置缺失: 读不到 {SERVICE_JSON}（或非法 JSON）") from None
    if not pw:
        raise DispatchError("auth_missing", f"鉴权配置缺失: {SERVICE_JSON} 无 password 字段")
    token = base64.b64encode(f"opencode:{pw}".encode()).decode()
    return Service(url=url, auth_header=f"Basic {token}")


# ---------------------------------------------------------------- HTTP（stdlib urllib，不重试）
def _http(svc: Service, method: str, path: str, body: dict | None = None,
          timeout: float | None = None) -> tuple[int, bytes]:
    headers = {"Content-Type": "application/json"}
    if svc.auth_header:
        headers["Authorization"] = svc.auth_header
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(svc.url + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except urllib.error.URLError as exc:
        raise DispatchError("service_unreachable",
                            f"opencode 服务不可达 ({svc.url}): {exc.reason}") from None
    except (TimeoutError, socket.timeout):
        raise DispatchError("timeout",
                            f"opencode 请求超时 ({svc.url}{path}, timeout={timeout})") from None
    except (ConnectionError, OSError) as exc:
        raise DispatchError("service_unreachable",
                            f"opencode 服务不可达 ({svc.url}): {exc}") from None


def _api(svc: Service, method: str, path: str, body: dict | None = None,
         timeout: float | None = None) -> tuple[int, dict | None]:
    code, raw = _http(svc, method, path, body, timeout)
    parsed = None
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
    return code, parsed


def _check_http_error(method: str, path: str, code: int) -> None:
    if code == 401:
        raise DispatchError(
            "auth_failed",
            f"opencode 服务 {method} {path} 返回 401（auth 鉴权失败；"
            f"检查 {AUTH_ENV} / {SERVICE_JSON} 凭据）")
    if code >= 400:
        raise DispatchError("http_error", f"opencode 服务 {method} {path} 返回 {code}")


# ---------------------------------------------------------------- 板读/留痕
def _load_requirement(requirement_id: str):
    """DB 直读（只读 factory；requirement 不存在的 not_found 由 require_requirement 抛）。"""

    async def _read(session):
        return await require_requirement(session, requirement_id)

    return asyncio.run(run_op(get_read_session_factory(), _read, is_write=False))


def _write_note(rid: str, content: str) -> None:
    """板留痕经 operations.note()（actor_surface=cli；该 op 不改，人话义务在 content 首行）。"""
    surface, conn = cli_actor()

    async def _do(session):
        return await ops.note(session, requirement_id=rid, content=content,
                              actor_surface=surface, actor_conn=conn)

    asyncio.run(run_op(get_session_factory(), _do, is_write=True))


# ---------------------------------------------------------------- 派发稿
def _skill_path() -> str:
    """协议入口＝CLI 所在仓 skills/agent-kanban/SKILL.md（按本文件位置解析，worktree 无关）。"""
    root = Path(__file__).resolve().parent.parent.parent
    return (root / "skills" / "agent-kanban" / "SKILL.md").as_posix()


def _redline_text(env_card: str) -> str | None:
    """环境卡「红线」行原文（P-imp6：只抽原文，不解释）。"""
    try:
        text = Path(env_card).read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        s = line.strip().lstrip("-* ").strip()
        if s.startswith("红线") and (":" in s or "：" in s):
            sep = ":" if ":" in s else "："
            return s.split(sep, 1)[-1].strip() or None
    return None


def _build_prompt(*, req, rid: str, ws: str | None, env_card: str | None,
                  redline: str | None, budget_raw: str | None,
                  warnings: list[str]) -> str:
    """新建派发稿（五要素 + 预算 + 警示）：任务指针/协议入口/环境卡路径/交付规格/红线提醒。"""
    lines = ["【派发稿】你是本需求的 worker 会话，按看板协议执行。", "", "## 任务指针",
             f"- 需求 id: {rid}", f"- 标题: {req.title}"]
    ptr_lines = [l.strip() for l in (req.description or "").splitlines()
                 if "workspace=" in l or "env-card=" in l]
    lines.append("- 指针行（原文）: " + " / ".join(ptr_lines[:2]) if ptr_lines
                 else "- 指针行: 缺失")
    lines += ["", "## 协议入口", f"看板协议正典路径: {_skill_path()}（认领后先读，按协议执行）",
              "", "## 环境卡路径"]
    if env_card:
        lines.append(env_card)
    lines += ["", "## 交付规格"]
    acc = req.acceptance or []
    if acc:
        for a in acc:
            item = a.get("item") if isinstance(a, dict) else a
            lines.append(f"- {item}")
    else:
        lines.append("无需求级锚，拆出子任务验收=事实锚")
    lines += ["", "## 红线提醒"]
    if redline:
        lines.append(redline)
    lines += ["", f"## 墙钟预算\n{budget_raw or '未指定（无预算封顶）'}"]
    if warnings:
        lines += ["", "## 警示"]
        lines += [f"- {w}" for w in warnings]
    return "\n".join(lines)


def _note_content(*, title: str, sid: str, model_desc: str, directory: str | None,
                  url: str, budget_desc: str, outcome: str) -> str:
    return "\n".join([
        f"分发：{title}，会话 {sid}，模型 {model_desc}",
        f"session id: {sid}",
        f"模型: {model_desc}",
        f"目录: {directory or '未指定（workspace 指针缺失或未指定）'}",
        f"服务 URL: {url}",
        f"预算: {budget_desc or '未指定'}",
        f"结局: {outcome}",
    ])


# ---------------------------------------------------------------- 主链
def run_dispatch(requirement_id: str, *, model: str | None = None,
                 directory: str | None = None, budget: str | None = None,
                 bg: bool = False) -> dict:
    """dispatch 主链（同步路径）：状态门 -> 指针解析 -> 服务发现 -> 存在检查 ->
    创建（404）-> 派发稿 prompt -> 同步 wait（budget 封顶）-> 板 note。
    --bg 本阶段（T1）只解析不实现，T4 交付心跳。"""
    _ = bg  # T1 解析不实现（T4）
    budget_secs = parse_budget(budget)
    model_ref = split_model(model)
    req = _load_requirement(requirement_id)
    rid = norm_id(req.id)
    # I1 状态门先于一切 HTTP（含服务发现/存在检查）
    if req.state not in DISPATCHABLE_STATES:
        raise DispatchError("illegal_state",
                            f"dispatch 仅支持 OPEN/REOPEN 需求，当前 state {req.state}")
    ws, env_card, warnings = _parse_pointers(req.description, directory)
    redline = _redline_text(env_card) if env_card else None
    if env_card and redline is None:
        warnings.append("环境卡红线节缺失（worker 就绪门自核红线）")
    elif env_card is None:
        warnings.append("无环境卡路径，无红线提醒可给")
    svc = discover_service()
    sid = f"ses_req_{rid[:8]}"
    created = False
    delivered = False
    outcome = "完成"
    wait_path = f"/api/experimental/session/{sid}/wait"
    try:
        # 存在检查前置：404 -> 创建（T1 主链）；401/400 -> 中止（P-imp1 类，不误判创建）
        code, _ = _api(svc, "GET", f"/api/session/{sid}")
        if code == 401:
            _check_http_error("GET", f"/api/session/{sid}", code)
        if code not in (200, 404):
            raise DispatchError("http_error", f"session 存在检查返回非预期状态 {code}")
        if code == 404:
            body: dict = {"id": sid, "title": f"ak-{rid[:8]} {req.title}"}
            if model_ref is not None:
                body["model"] = model_ref
            if ws:
                body["location"] = {"directory": ws}
            code, _ = _api(svc, "POST", "/api/session", body)
            _check_http_error("POST", "/api/session", code)
            if code != 200:
                raise DispatchError("http_error", f"session 创建返回非预期状态 {code}")
            created = True
        # 200：session 已存在 -> 复用（续接稿 + 板面状态摘要由 T2 交付；当前投新建稿）
        prompt = _build_prompt(req=req, rid=rid, ws=ws, env_card=env_card,
                               redline=redline, budget_raw=budget, warnings=warnings)
        code, _ = _api(svc, "POST", f"/api/session/{sid}/prompt", {"text": prompt})
        _check_http_error("POST", f"/api/session/{sid}/prompt", code)
        if code >= 400:
            raise DispatchError("http_error", f"prompt 投递返回非预期状态 {code}")
        delivered = True
        code, _ = _api(svc, "POST", wait_path, timeout=budget_secs)
        _check_http_error("POST", wait_path, code)
        if code != 204:
            raise DispatchError("http_error", f"wait 返回非预期状态 {code}")
    except DispatchError as exc:
        # 失败/超时写 note（派发方从板面知失败）。T1 只覆盖 wait 阶段（delivered=True）；
        # 不写：prompt 投递失败（500 等，delivered=False，下方 raise）与投递后鉴权/
        # 网络异常（下方 else: raise）＝T3 k_dispatch_failnote / 板留痕全路径（P-imp2）；
        # 状态门/鉴权中止/服务不可达/创建失败（投递前）按契约不写
        if not delivered:
            raise
        if exc.code == "timeout":
            outcome = "超时"
        elif exc.code == "http_error":
            outcome = "失败"
        else:
            raise
        _write_note(rid, _note_content(title=req.title, sid=sid,
                                       model_desc=model or "未指定（服务默认）",
                                       directory=ws, url=svc.url,
                                       budget_desc=budget or "", outcome=outcome))
        raise
    _write_note(rid, _note_content(title=req.title, sid=sid,
                                   model_desc=model or "未指定（服务默认）",
                                   directory=ws, url=svc.url,
                                   budget_desc=budget or "", outcome=outcome))
    return {"requirement_id": rid, "session_id": sid, "created": created,
            "outcome": outcome, "service_url": svc.url,
            "note": _note_content(title=req.title, sid=sid,
                                  model_desc=model or "未指定（服务默认）",
                                  directory=ws, url=svc.url,
                                  budget_desc=budget or "", outcome=outcome)}
