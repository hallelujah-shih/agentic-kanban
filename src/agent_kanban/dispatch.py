"""B2 dispatch：需求 -> opencode worker 会话主链（plan「dispatch 步骤 1-10」）。

服务发现：URL 与鉴权分离——URL＝env AGENT_KANBAN_OPENCODE_URL > `opencode service
status` 末行（subprocess，10s）；鉴权＝env AGENT_KANBAN_OPENCODE_AUTH=none 不发头，
否则读 ~/.config/opencode/service.json 的 password 发 Basic（strace 实锤）。
约束：stdlib urllib（不加依赖）；P-imp1 不自动拉起服务、不重试；密码永不进
stdout/错误消息（URL 可回显）。
--bg（T4，D1 Popen re-entry）：prompt 投递 + 分发 note 后 spawn 独立 bg 子进程
跑心跳续租（run_bg_loop 单一实现），父进程立即返回；终态判据＝GET 404 或
outcome ∈ {succeeded, failed} 或 S9 认领绑定判据（认领变更/需求释放），终态 note 后退出。
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from .db import get_read_session_factory, get_session_factory, run_op
from .errors import BusinessError
from .models import Claim, Event, Subtask
from .services import operations as ops
from .services.ids import norm_id
from .services.identity import cli_actor
from .services.write_guard import require_requirement

URL_ENV = "AGENT_KANBAN_OPENCODE_URL"
AUTH_ENV = "AGENT_KANBAN_OPENCODE_AUTH"
HEARTBEAT_ENV = "AGENT_KANBAN_DISPATCH_HEARTBEAT_SEC"
SERVICE_JSON = Path.home() / ".config" / "opencode" / "service.json"
DISPATCHABLE_STATES = ("OPEN", "REOPEN")
_SERVICE_TIMEOUT = 10  # 服务发现 subprocess 超时（秒）
_DEFAULT_HEARTBEAT_SEC = 60.0


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
                else:
                    warnings.append(f"env-card 指针值为空，忽略: {tok}")
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


def _placement_text(env_card: str) -> str | None:
    """环境卡「产物落点」字段原文（只抽字面量，不解释）。

    环境卡把落点写在 workspace 行的分号分隔字段里，不是行首键；按 ;/； 切段后
    找以「产物落点」开头的段。
    """
    try:
        text = Path(env_card).read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        for seg in re.split(r"[;；]", line):
            s = seg.strip().lstrip("-* ").strip()
            if s.startswith("产物落点") and (":" in s or "：" in s):
                sep = ":" if ":" in s else "："
                return s.split(sep, 1)[-1].strip() or None
    return None


def _build_prompt(*, req, rid: str, ws: str | None, env_card: str | None,
                  redline: str | None, placement: str | None,
                  budget_raw: str | None,
                  warnings: list[str], history: list[str]) -> str:
    """新建派发稿（五要素 + 预算 + 警示 + 有历史时的历轮交付物）：任务指针/协议入口/环境卡路径/交付规格/历轮交付物（仅当有历史）/红线提醒。"""
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
    if placement:
        lines.append(f"- 产物落点: {placement}")
    else:
        lines.append("- 产物落点: 环境卡未声明（按协议「工作区就绪」定落点："
                     "跨项目产物落所属项目仓，禁在本仓新建目录；无归属问人）")
    lines.append("- 交付物须落永久位置并用 ls 核存在（会话目录/批次 tmp 不是交付物落点，禁作唯一副本）")
    if history:
        lines += ["", "## 历轮交付物（本需求历史 request_review，seq 升序）"]
        lines += history
    lines += ["", "## 红线提醒"]
    if redline:
        lines.append(redline)
    lines += ["", f"## 墙钟预算\n{budget_raw or '未指定（无预算封顶）'}"]
    if warnings:
        lines += ["", "## 警示"]
        lines += [f"- {w}" for w in warnings]
    return "\n".join(lines)


def _subtask_progress(rid: str) -> tuple[int, int]:
    """子任务进度 done/total（只读直读，续接稿板面摘要用）。"""

    async def _read(session):
        rows = (await session.scalars(
            select(Subtask).where(Subtask.requirement_id == rid))).all()
        return sum(1 for s in rows if s.state == "done"), len(rows)

    return asyncio.run(run_op(get_read_session_factory(), _read, is_write=False))


def _history_digest(rid: str) -> list[str]:
    """历轮交付物（A2）：本需求 review_request 事件 evidence 字面提取，seq 升序。

    无历史返回空列表（调用方不加节）；只抽字面量（document/note/seq），不解释、
    不做存在检查（BCD b3 §3 P-imp1/P-imp2）；document/note 为协议级可选键
    （SKILL 交接条款），皆缺的轮次跳过；payload/evidence 非 dict 的畸形行跳过不崩。
    """

    async def _read(session):
        rows = (await session.scalars(
            select(Event).where(Event.requirement_id == rid)
            .where(Event.kind == "review_request")
            .order_by(Event.seq.asc()))).all()
        lines: list[str] = []
        n = 0
        for e in rows:
            payload = e.payload or {}
            ev = payload.get("evidence") if isinstance(payload, dict) else None
            doc = ev.get("document") if isinstance(ev, dict) else None
            note = ev.get("note") if isinstance(ev, dict) else None
            if not doc and not note:
                continue
            n += 1
            if doc:
                lines.append(f"- 第 {n} 轮（seq {e.seq}）: 交付物 {doc}")
            if note:
                lines.append(f"- note: {note}")
        return lines

    return asyncio.run(run_op(get_read_session_factory(), _read, is_write=False))


def _build_continuation(req, rid: str, history: list[str]) -> str:
    """续接稿（GET 200 复用路径，P-imp4）：会话已存在，继续当前需求 + 最近板面状态摘要 + 有历史时的历轮交付物。"""
    done, total = _subtask_progress(rid)
    awaiting = req.awaiting_human
    if isinstance(awaiting, dict) and awaiting:
        kind = awaiting.get("kind") or "未知"
        awaiting_desc = f"有（kind={kind}）"
    else:
        awaiting_desc = "无"
    lines = ["【续接稿】会话已存在，继续当前需求。", "",
             f"- 需求 id: {rid}", f"- 标题: {req.title}",
             f"- state: {req.state}", f"- awaiting: {awaiting_desc}",
             f"- 子任务进度: {done}/{total}"]
    if history:
        lines += ["", "## 历轮交付物（本需求历史 request_review，seq 升序）"]
        lines += history
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


def _delivery_fail_note(*, title: str, sid: str, model_desc: str, directory: str | None,
                        url: str, budget_desc: str, code: int) -> str:
    """投递失败 note（P-imp2）：首行人话含「分发失败」，content 记失败事实 + 错误码。"""
    return "\n".join([
        f"分发失败：{title}，prompt 投递返回 HTTP {code}",
        f"session id: {sid}",
        f"模型: {model_desc}",
        f"目录: {directory or '未指定（workspace 指针缺失或未指定）'}",
        f"服务 URL: {url}",
        f"预算: {budget_desc or '未指定'}",
        f"结局: 失败（prompt 投递 HTTP {code}）",
    ])


# ---------------------------------------------------------------- 主链
def run_dispatch(requirement_id: str, *, model: str | None = None,
                 directory: str | None = None, budget: str | None = None,
                 bg: bool = False) -> dict:
    """dispatch 主链：状态门 -> 指针解析 -> 服务发现 -> 存在检查 -> 创建（404）->
    派发稿 prompt -> 同步 wait（budget 封顶）或 --bg 心跳子进程 -> 板 note。
    --bg（D1）：不 wait，prompt 投递 + 分发 note 后 spawn 独立 bg 子进程
    （Popen re-entry，run_bg_loop 单一实现），父进程立即返回。"""
    budget_secs = parse_budget(budget)
    model_ref = split_model(model)
    if bg:
        _heartbeat_sec()  # 心跳 env 先行校验（非法值在投递前失败，不 spawn 后静默死）
    req = _load_requirement(requirement_id)
    rid = norm_id(req.id)
    # I1 状态门先于一切 HTTP（含服务发现/存在检查）
    if req.state not in DISPATCHABLE_STATES:
        raise DispatchError("illegal_state",
                            f"dispatch 仅支持 OPEN/REOPEN 需求，当前 state {req.state}")
    ws, env_card, warnings = _parse_pointers(req.description, directory)
    redline = _redline_text(env_card) if env_card else None
    placement = _placement_text(env_card) if env_card else None
    if env_card and redline is None:
        warnings.append("环境卡红线节缺失（worker 就绪门自核红线）")
    elif env_card is None:
        warnings.append("无环境卡路径，无红线提醒可给")
    history = _history_digest(rid)  # 板面只读，先于一切 HTTP（读失败不留半建会话）
    svc = discover_service()
    sid = f"ses_req_{rid[:8]}"
    created = False
    delivered = False
    prompt_code: int | None = None
    bg_pid: int | None = None
    wait_path = f"/api/experimental/session/{sid}/wait"
    try:
        # 存在检查前置：404 -> 创建（T1 主链）；401/400 -> 中止（P-imp1 类，不误判创建）
        code, _ = _api(svc, "GET", f"/api/session/{sid}")
        if code == 401:
            _check_http_error("GET", f"/api/session/{sid}", code)
        if code not in (200, 404):
            raise DispatchError("http_error", f"session 存在检查返回非预期状态 {code}")
        reused = code == 200
        if not reused:
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
        # 200：session 已存在 -> 复用投续接稿（P-imp4：同 id 不新 create）；
        # 404->创建：投完整五要素新建稿
        if reused:
            prompt = _build_continuation(req, rid, history)
        else:
            prompt = _build_prompt(req=req, rid=rid, ws=ws, env_card=env_card,
                                   redline=redline, placement=placement,
                                   budget_raw=budget, warnings=warnings,
                                   history=history)
        code, _ = _api(svc, "POST", f"/api/session/{sid}/prompt", {"text": prompt})
        prompt_code = code
        _check_http_error("POST", f"/api/session/{sid}/prompt", code)
        if code >= 400:
            raise DispatchError("http_error", f"prompt 投递返回非预期状态 {code}")
        delivered = True
        if not bg:
            code, _ = _api(svc, "POST", wait_path, timeout=budget_secs)
            _check_http_error("POST", wait_path, code)
            if code != 204:
                raise DispatchError("http_error", f"wait 返回非预期状态 {code}")
    except DispatchError as exc:
        # 板留痕全路径（P-imp2）：投递失败（prompt_code 有值）与投递后异常
        # （delivered：wait 阶段超时/鉴权/网络）都写 note，派发方从板面知失败；
        # 状态门/鉴权中止/服务不可达/创建失败（投递前）按契约不写
        if prompt_code is not None and not delivered:
            _write_note(rid, _delivery_fail_note(title=req.title, sid=sid,
                                                  model_desc=model or "未指定（服务默认）",
                                                  directory=ws, url=svc.url,
                                                  budget_desc=budget or "",
                                                  code=prompt_code))
            raise
        if not delivered:
            raise
        outcome = "超时" if exc.code == "timeout" else "失败"
        _write_note(rid, _note_content(title=req.title, sid=sid,
                                       model_desc=model or "未指定（服务默认）",
                                       directory=ws, url=svc.url,
                                       budget_desc=budget or "", outcome=outcome))
        raise
    outcome = "bg" if bg else "完成"
    note = _note_content(title=req.title, sid=sid,
                         model_desc=model or "未指定（服务默认）",
                         directory=ws, url=svc.url,
                         budget_desc=budget or "", outcome=outcome)
    _write_note(rid, note)
    bg_pid = None
    if bg:
        # --bg（D1）：分发 note 落库**后**才 spawn bg 子进程（T4 审 P1-1：子进程
        # _bg_note_seq 读取必须晚于父进程 note 写，否则 delegated basis（P-imp3）
        # 竞态取「缺失」或上一条 note 的 seq）
        try:
            bg_pid = _spawn_bg(rid).pid
        except DispatchError:
            # spawn 失败：prompt 已投递（session 活但无心跳）——板面记失败事实（P-imp2 类）
            _write_note(rid, "\n".join([
                f"分发失败：{req.title}，bg 子进程拉起失败（prompt 已投递，会话保留但心跳未启动）",
                f"session id: {sid}",
                f"模型: {model or '未指定（服务默认）'}",
                f"目录: {ws or '未指定（workspace 指针缺失或未指定）'}",
                f"服务 URL: {svc.url}",
                "结局: 失败（bg spawn 失败）",
            ]))
            raise
    result = {"requirement_id": rid, "session_id": sid, "created": created,
              "outcome": outcome, "service_url": svc.url, "directory": ws,
              "note": note}
    if bg:
        result["bg_pid"] = bg_pid
    return result


# ---------------------------------------------------------------- --bg 心跳（T4，D1 Popen re-entry）
def _heartbeat_sec() -> float:
    """心跳周期（I5 可注入常量）：env AGENT_KANBAN_DISPATCH_HEARTBEAT_SEC 覆盖，默认 60s。"""
    raw = (os.environ.get(HEARTBEAT_ENV) or "").strip()
    if not raw:
        return _DEFAULT_HEARTBEAT_SEC
    try:
        secs = float(raw)
    except ValueError:
        raise DispatchError("invalid_heartbeat",
                            f"心跳周期须为数字（秒）: {raw!r}") from None
    if secs <= 0:
        raise DispatchError("invalid_heartbeat", f"心跳周期须为正数（秒）: {raw!r}")
    return secs


def _spawn_bg(rid: str) -> subprocess.Popen:
    """bg 子进程 Popen re-entry（D1）：同解释器 + 仓根 cli.py dispatch
    --requirement-id <rid> --_bg-loop（隐藏 flag，不宣传）；stdin/stdout/stderr 全
    DEVNULL——不继承父进程管道，否则父端读 stdout 会阻塞到子进程存活期。"""
    cli_path = Path(__file__).resolve().parent.parent.parent / "cli.py"
    try:
        return subprocess.Popen(
            [sys.executable, str(cli_path), "dispatch", "--requirement-id", rid, "--_bg-loop"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise DispatchError("bg_spawn_failed", f"bg 子进程拉起失败: {exc}") from None


def _bg_note_seq(rid: str) -> int | None:
    """分发 note seq（renew delegated basis 的锚，I8）：只锚 content 前缀「分发：」的
    最新 note——worker 认领后写的接单确认等 note 不夺锚；无分发 note -> None（basis 记缺失）。"""

    async def _read(session):
        return await session.scalar(
            select(Event.seq).where(Event.requirement_id == rid, Event.kind == "note")
            .where(Event.content.like("分发：%"))
            .order_by(Event.seq.desc()).limit(1))

    return asyncio.run(run_op(get_read_session_factory(), _read, is_write=False))


def _bg_active_claim_id(rid: str) -> str | None:
    """当前 active claim id（S9 认领绑定 + pre-claim 窗口判定；无 active claim -> None）。"""

    async def _read(session):
        claim_id = await session.scalar(
            select(Claim.id).where(Claim.requirement_id == rid, Claim.ended_at.is_(None)))
        # Uuid(as_uuid=False) 读回 36-char 带连字符，归一 32-hex（与 MCP/事件引用一致）
        return norm_id(claim_id) if claim_id is not None else None

    return asyncio.run(run_op(get_read_session_factory(), _read, is_write=False))


def _bg_renew(rid: str, sid: str, note_seq: int | None, *, expected_claim_id: str) -> None:
    """bg 续租（P-imp3 + I8 写边界）：合法人面 renew（actor_surface=cli），携 delegated
    受托痕（kind=statement，basis 指向分发 note seq + session id）；expected_claim_id 与
    当前 active claim 在同一写事务内（写引擎 BEGIN IMMEDIATE，无跨写者交错）比对，
    不等即拒写（I8：心跳只续它绑定的认领——读 claim 与写 renew 间的复派窗口不越权）。"""
    surface, conn = cli_actor()
    basis = f"分发 note seq {note_seq if note_seq is not None else '缺失'} + {sid}"

    async def _do(session):
        active = await session.scalar(
            select(Claim.id).where(Claim.requirement_id == rid, Claim.ended_at.is_(None)))
        if active is None or norm_id(active) != norm_id(expected_claim_id):
            raise BusinessError(
                "claim_changed",
                f"active claim {active} != bound {expected_claim_id}（拒写 renew）", rid)
        return await ops.renew(session, requirement_id=rid, actor_surface=surface,
                               actor_conn=conn,
                               delegated={"kind": "statement", "basis": basis})

    asyncio.run(run_op(get_session_factory(), _do, is_write=True))


def _bg_final_note(*, title: str, sid: str, elapsed: float, renews: int,
                   pre_claim_skips: int, reason: str) -> str:
    """终态 note（Premortem F3 判据）：首行人话 + bg 存活时长 + renew 总数 +
    pre-claim 跳过次数 + 结束原因。"""
    return "\n".join([
        f"bg 心跳结束：{title}，会话 {sid}，renew {renews} 次，pre-claim 跳过 {pre_claim_skips} 次",
        f"session id: {sid}",
        f"bg 存活时长: {int(elapsed)}s",
        f"renew 总数: {renews}",
        f"pre-claim 跳过: {pre_claim_skips}",
        f"原因: {reason}",
    ])


def run_bg_loop(requirement_id: str) -> dict:
    """bg 心跳循环（T4；子进程经 cli.py dispatch --_bg-loop 进入，父/子共用本单一实现）：
    每周期探测 GET /api/session/{sid}（周期＝_heartbeat_sec，测试注入 1s）；
    存活且 claim active -> renew（delegated 受托痕）；pre-claim 窗口（尚未绑定 claim）->
    跳过，不报错、不写板事件（计跳过次数）；终态判据（钉死）：GET 404（session 消失）或
    GET 200 且 outcome ∈ {succeeded, failed} 或 S9 认领绑定判据 -> 终态 note 后退出；
    探测失败（服务不可达）-> 终态 note（原因=服务不可达）后退出（S8：不无限循环、不静默）。
    S9 认领绑定（G28/I8）：启动后首次观测到的 active claim 即绑定；绑定后 active claim
    变更（认领变更）或消失（需求释放）-> 终态 note 记原因后退出，不改绑、不续租新认领。
    已知局限（BCD Q1 裁决接受）：bg 进程随派发方终端死则心跳停。"""
    svc = discover_service()
    req = _load_requirement(requirement_id)
    rid = norm_id(req.id)
    sid = f"ses_req_{rid[:8]}"
    period = _heartbeat_sec()
    note_seq = _bg_note_seq(rid)
    start = time.monotonic()
    renews = 0
    pre_claim_skips = 0
    reason = ""
    bound_claim: str | None = None
    while True:
        try:
            code, body = _api(svc, "GET", f"/api/session/{sid}", timeout=10)
        except DispatchError as exc:
            reason = f"服务不可达（{exc.message}）"
        else:
            # 真服务 2.1.4 GET 200 body 为 {"data": {...}} 包装；裸形态亦容忍（版本漂移）。T5 审 D4
            raw = body or {}
            payload = raw.get("data") if isinstance(raw.get("data"), dict) else raw
            if code == 404:
                reason = "session 消失（GET 404）"
            elif code == 200 and payload.get("outcome") in ("succeeded", "failed"):
                reason = f"session 终态（outcome={payload.get('outcome')}）"
            elif code == 401:
                reason = "session 探测鉴权失败（GET 401）"
            elif code != 200:
                reason = f"session 探测返回非预期状态 {code}"
        if reason:
            break
        claim_id = _bg_active_claim_id(rid)
        if claim_id is None:
            if bound_claim is not None:
                reason = "需求释放（绑定认领已结束）"
                break
            pre_claim_skips += 1
        elif bound_claim is not None and claim_id != bound_claim:
            # S9：认领变更——旧 watcher 不改绑、不续租新 claim，记原因退场
            reason = "认领变更（active claim 已换，旧 watcher 不改绑）"
            break
        else:
            bound_claim = bound_claim or claim_id  # 首次观测到 active claim 即绑定
            try:
                _bg_renew(rid, sid, note_seq, expected_claim_id=bound_claim)
                renews += 1
            except BusinessError:
                # claim 刚结束/变更（写边界拒写）/租约过期（周期间隙）：不报错，下周期再判
                pass
        time.sleep(period)
    note = _bg_final_note(title=req.title, sid=sid, elapsed=time.monotonic() - start,
                          renews=renews, pre_claim_skips=pre_claim_skips, reason=reason)
    _write_note(rid, note)
    return {"requirement_id": rid, "session_id": sid, "outcome": "bg-end",
            "reason": reason, "renews": renews, "pre_claim_skips": pre_claim_skips,
            "note": note}


# ---------------------------------------------------------------- resume
_REQ_PREFIX_RE = re.compile(r"[0-9a-f]{8,32}")  # R6：接受面对齐 dispatch（32 精确 / 8-31 唯一前缀）
_SES_REQ_RE = re.compile(r"ses_req_([0-9a-f]{8})")


def _resolve_resume_target(target: str):
    """resume 目标定位（R6：接受面对齐 dispatch，与 write_guard.require_requirement
    同源归一：strip / 大小写 / 连字符）：归一后 ses_req_<8hex> 全匹配 -> 前缀反查
    （须存在且唯一）；[0-9a-f]{8,32} 全匹配 -> 需求 id（32 精确 / 8-31 唯一前缀）；
    否则 invalid_target。非派生形态 ses id 明确拒绝（看板是恢复入口，手工 session
    不走本命令）。不限需求状态（Q2：恢复/返工/换模型统一入口，note 如实记当前状态）。
    """
    t = str(target).strip().lower().replace("-", "")
    m = _SES_REQ_RE.fullmatch(t)
    if m:
        try:
            return _load_requirement(m.group(1))
        except BusinessError as exc:
            raise DispatchError(
                "session_unmapped",
                f"session 无法映射到需求: {t}（前缀反查 {exc.code}: {exc.message}）") from None
    if _REQ_PREFIX_RE.fullmatch(t):
        return _load_requirement(t)
    raise DispatchError(
        "invalid_target",
        f"resume 目标形态无效: {target!r}（接受需求 id 32hex 或 8-31 位唯一前缀"
        f"（大小写/连字符不敏感），或派生 session ses_req_<8hex>）")


def _resume_note_content(*, title: str, sid: str, model_desc: str, state: str,
                         instruction: str, directory: str | None) -> str:
    summary = instruction if len(instruction) <= 40 else instruction[:40] + "…"
    return "\n".join([
        f"续跑：{title}，{summary}，需求状态 {state}",
        f"session id: {sid}",
        f"模型: {model_desc}",
        f"需求 state: {state}",
        f"目录: {directory or '未指定'}",
    ])


def run_resume(target: str, instruction: str | None = None, *, model: str | None = None,
               budget: str | None = None) -> dict:
    """resume 主链：目标定位（不限状态）-> 服务发现 -> --model 先 switchModel（P-imp5）->
    prompt（空指令=「继续」）-> 同步 wait（budget 默认 1h）-> 板 note（I3 恢复锚）。
    不做计划外前置检查：session 不存在时 prompt 404 走既有 http_error 路径。"""
    budget_secs = parse_budget(budget or "1h")
    model_ref = split_model(model)
    req = _resolve_resume_target(target)
    rid = norm_id(req.id)
    state = req.state
    # U1 深挖锚：需求指针行只读解析取目录（禁新增 HTTP 调用）；缺失记「未指定」
    ws, _, _ = _parse_pointers(req.description, None)
    svc = discover_service()
    sid = f"ses_req_{rid[:8]}"
    text = (instruction or "").strip() or "继续"
    model_path = f"/api/session/{sid}/model"
    prompt_path = f"/api/session/{sid}/prompt"
    wait_path = f"/api/experimental/session/{sid}/wait"
    if model_ref is not None:
        code, _ = _api(svc, "POST", model_path, {"model": model_ref})
        _check_http_error("POST", model_path, code)
        if code != 200:
            raise DispatchError("http_error", f"switchModel 返回非预期状态 {code}")
    code, _ = _api(svc, "POST", prompt_path, {"text": text})
    _check_http_error("POST", prompt_path, code)
    if code >= 400:
        raise DispatchError("http_error", f"prompt 投递返回非预期状态 {code}")
    code, _ = _api(svc, "POST", wait_path, timeout=budget_secs)
    _check_http_error("POST", wait_path, code)
    if code != 204:
        raise DispatchError("http_error", f"wait 返回非预期状态 {code}")
    note = _resume_note_content(title=req.title, sid=sid,
                                model_desc=model or "未指定（未换模）",
                                state=state, instruction=text, directory=ws)
    _write_note(rid, note)
    return {"requirement_id": rid, "session_id": sid, "outcome": "完成",
            "service_url": svc.url, "directory": ws, "note": note}
