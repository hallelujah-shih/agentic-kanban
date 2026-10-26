"""Web 窗口 HTML 壳（M1-2.4，PRD §4.2 Web 窗口 surface 表；2026-10-23 UI 重构）。

反淹没结构保证：壳为静态 HTML + 内联 JS，零数据嵌入——数据一律由 JS fetch
REST 获取后渲染；看板壳只渲染 /board 返回的紧凑行（无 content/payload），
深潜壳事件流只渲染标题行（无 content/payload），原始输出结构上不进壳/渲染。
token 传播：页面从 URL ?token= 读 token 存入 sessionStorage，全部 fetch/EventSource 附 token
（EventSource 无法设 header，走 ?token= query）。
"""

from __future__ import annotations

# 两壳共享的主题 token 与渲染工具（内联进各自壳，保持壳自包含）。
_THEME = """
:root{
  --bg:#0d1014; --panel:#13171d; --card:#1a212b; --card-hi:#212b38;
  --border:#262f3a; --text:#e6ebf0; --muted:#8b98a5; --faint:#5b6672;
  --accent:#4f8ff7; --green:#3fb950; --amber:#d29922; --red:#f85149;
  --blue:#4f8ff7; --purple:#bc8cff; --orange:#f0883e;
}
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;background:var(--bg);color:var(--text);font-size:14px}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
h1{font-size:1.25rem;margin:0}
.topbar{position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:12px;
  padding:10px 20px;background:rgba(13,16,20,.92);backdrop-filter:blur(6px);border-bottom:1px solid var(--border)}
.topbar .title{font-weight:650;font-size:1rem;letter-spacing:.2px}
.live{margin-left:auto;display:flex;align-items:center;gap:6px;font-size:.75rem;color:var(--muted)}
.live .dot{width:8px;height:8px;border-radius:50%;background:var(--faint)}
.live.on .dot{background:var(--green);box-shadow:0 0 6px var(--green)}
.live.off .dot{background:var(--red)}
.pill{display:inline-block;font-size:.72rem;font-weight:600;padding:2px 9px;border-radius:999px;white-space:nowrap}
.pill.OPEN{background:rgba(79,143,247,.15);color:var(--blue)}
.pill.CLAIMED{background:rgba(63,185,80,.15);color:var(--green)}
.pill.BLOCKED{background:rgba(248,81,73,.15);color:var(--red)}
.pill.REOPEN{background:rgba(188,140,255,.15);color:var(--purple)}
.pill.DONE{background:rgba(63,185,80,.15);color:var(--green)}
.pill.REJECTED{background:rgba(248,81,73,.15);color:var(--red)}
.pill.CANCELLED{background:rgba(91,102,114,.25);color:var(--muted)}
.pill.ARCHIVED{background:rgba(91,102,114,.25);color:var(--muted)}
.pill.todo{background:rgba(139,152,165,.15);color:var(--muted)}
.pill.in_progress{background:rgba(63,185,80,.15);color:var(--green)}
.pill.done{background:rgba(139,152,165,.15);color:var(--muted)}
.pill.blocked{background:rgba(248,81,73,.15);color:var(--red)}
.pill.abandoned{background:rgba(91,102,114,.25);color:var(--muted)}
.badge{display:inline-block;font-size:.72rem;padding:1px 7px;border-radius:5px;white-space:nowrap}
.badge.attn{background:rgba(210,153,34,.16);color:var(--amber)}
.badge.risk{background:rgba(248,81,73,.14);color:var(--red)}
.badge.risk.critical{background:var(--red);color:#fff}
.badge.gap{background:rgba(210,153,34,.16);color:var(--amber)}
.meta{color:var(--muted);font-size:.76rem}
.muted{color:var(--faint);font-size:.8rem}
"""

_JS_COMMON = """
(function(){
  var qs = new URLSearchParams(location.search);
  var t = qs.get("token");
  if (t) sessionStorage.setItem("kanban_token", t);
})();
var TOKEN = sessionStorage.getItem("kanban_token") || "";
function hdr(){ return TOKEN ? {"x-agent-kanban-token": TOKEN} : {}; }
function esc(s){ var d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }
var STATE_ZH = {OPEN:"待认领", CLAIMED:"进行中", BLOCKED:"阻塞", REOPEN:"返工", DONE:"已完成", REJECTED:"已拒绝", CANCELLED:"已取消", ARCHIVED:"已归档"};
var SIG_ZH = {blocked_subtask:"子任务阻塞", milestone_delay:"里程碑延误", abandoned_subtask:"子任务放弃",
              unexplained_abandonment:"未解释放弃", retry_limit:"重试超限", decomposition_added:"拆解变更"};
function sigLabel(t){ return SIG_ZH[t] || t; }
function stateZh(s){ return STATE_ZH[s] || s; }
function fmtTs(ts){
  if (!ts) return "";
  try {
    var d = new Date(ts);
    function p(n){ return (n < 10 ? "0" : "") + n; }
    return (d.getMonth()+1) + "-" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
  } catch (e) { return ts; }
}
function liveEl(state){
  var el = document.getElementById("live");
  if (el) { el.className = "live " + (state === "on" ? "on" : "off");
            el.querySelector("span:last-child").textContent = state === "on" ? "实时" : "重连中"; }
}
function setupSSE(){
  var es = new EventSource("/events/stream" + (TOKEN ? "?token=" + encodeURIComponent(TOKEN) : ""));
  es.onopen = function(){ liveEl("on"); };
  es.onerror = function(){ liveEl("off"); };
  return es;
}
"""


def board_shell() -> str:
    """GET / 看板壳：fetch /board 渲染（状态分列 + 卡片）+ EventSource 实时重拉。"""
    return """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>agent-kanban 看板</title>
<style>
""" + _THEME + """
.tabs{display:flex;gap:4px;padding:12px 20px 0}
.tab{background:transparent;border:1px solid transparent;color:var(--muted);padding:5px 14px;
  border-radius:8px 8px 0 0;font-size:.85rem;cursor:pointer}
.tab:hover{color:var(--text)}
.tab.active{color:var(--text);background:var(--panel);border-color:var(--border)}
.cols{display:grid;grid-template-columns:repeat(4,minmax(250px,1fr));gap:12px;padding:16px 20px;align-items:start}
@media (max-width:1000px){.cols{grid-template-columns:repeat(2,minmax(240px,1fr))}}
@media (max-width:560px){.cols{grid-template-columns:1fr}}
.col{background:var(--panel);border:1px solid var(--border);border-radius:10px;overflow:hidden}
.col-hd{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid var(--border)}
.col-hd .cdot{width:9px;height:9px;border-radius:50%}
.col-hd .cname{font-weight:600;font-size:.85rem}
.col-hd .ccount{margin-left:auto;font-size:.75rem;color:var(--muted);background:var(--card);
  border-radius:999px;padding:1px 8px;min-width:22px;text-align:center}
.col-body{padding:10px;display:flex;flex-direction:column;gap:8px;min-height:60px}
.card{display:block;background:var(--card);border:1px solid var(--border);border-radius:8px;
  padding:10px 12px;transition:background .12s,border-color .12s}
.card:hover{background:var(--card-hi);border-color:#35414f;text-decoration:none}
.card.attn{border-left:3px solid var(--amber)}
.card .ct{font-weight:600;font-size:.9rem;color:var(--text);margin-bottom:6px;line-height:1.35}
.card .ct:hover{color:var(--accent)}
.pbar{height:4px;border-radius:2px;background:var(--border);overflow:hidden;display:flex;margin:6px 0}
.pbar .pd{background:var(--green)}
.pbar .pb{background:var(--orange)}
.card .badges{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}
.card .who{display:flex;align-items:center;gap:6px;margin-top:7px;font-size:.76rem;color:var(--muted)}
.card .who .sdot{width:7px;height:7px;border-radius:50%}
.card .wait{margin-top:7px;font-size:.75rem;color:var(--amber);background:rgba(210,153,34,.1);
  border-radius:5px;padding:3px 8px}
.empty{color:var(--faint);font-size:.78rem;text-align:center;padding:14px 0}
.done-list{padding:14px 20px 40px;display:flex;flex-direction:column;gap:7px;max-width:1200px}
.done-row{display:flex;align-items:center;gap:10px;background:var(--card);border:1px solid var(--border);
  border-radius:8px;padding:9px 12px;flex-wrap:wrap}
.done-row:hover{background:var(--card-hi);text-decoration:none}
.done-row .dt{font-weight:600;color:var(--text);font-size:.88rem}
.done-row .grow{flex:1}
input,textarea{background:var(--card);color:var(--text);border:1px solid var(--border);
  border-radius:7px;padding:6px 8px;font-size:.82rem}
#nf-msg.err{color:var(--red)}
#nf-msg.ok{color:var(--green)}
</style></head>
<body>
<div class="topbar">
  <span class="title">agent-kanban</span>
  <span class="meta" id="top-count"></span>
  <button id="new-btn">新建</button>
  <div class="live" id="live"><div class="dot"></div><span>连接中</span></div>
</div>
<div id="new-form" style="display:none;padding:10px 20px 0;max-width:720px">
  <div style="display:flex;flex-direction:column;gap:6px">
    <input id="nf-title" placeholder="标题（必填）" style="width:100%;box-sizing:border-box">
    <textarea id="nf-desc" rows="2" placeholder="描述（可选）"></textarea>
    <textarea id="nf-acc" rows="3" placeholder="预期验收（可选，一行一条锚）"></textarea>
    <input id="nf-jira" placeholder="Jira 链接（可选，非空则 source=jira）" style="width:100%;box-sizing:border-box">
    <div style="display:flex;gap:8px;align-items:center">
      <button class="primary" onclick="submitNew()">创建</button>
      <button onclick="document.getElementById('new-form').style.display='none'">取消</button>
      <span id="nf-msg" style="font-size:.8rem"></span>
    </div>
  </div>
</div>
<div class="tabs">
  <button class="tab active" data-tab="active">在板</button>
  <button class="tab" data-tab="done">已完成</button>
  <button class="tab" data-tab="archived">已归档</button>
</div>
<div id="board-root"><p class="meta" style="padding:24px">加载中…</p></div>
<script>
""" + _JS_COMMON + """
var COLS = [["OPEN","var(--blue)"],["CLAIMED","var(--green)"],["BLOCKED","var(--red)"],["REOPEN","var(--purple)"]];
function cardHTML(t){
  var attn = (t.needs_attention || []).map(function(n){
    return "<span class='badge attn'>" + esc(sigLabel(n.type)) + "</span>"; }).join("");
  var risks = (t.risks || []).map(function(x){
    return "<span class='badge risk" + (x.severity === "critical" ? " critical" : "") + "'>"
      + esc(x.severity === "critical" ? "严重风险" : "风险") + ": " + esc(x.title) + "</span>"; }).join("");
  var p = t.progress || {done:0,total:0,blocked:0};
  var pct = p.total ? Math.round(p.done / p.total * 100) : 0;
  var pbar = p.total ? "<div class='pbar'><div class='pd' style='width:" + pct + "%'></div>"
    + "<div class='pb' style='width:" + Math.round(p.blocked / p.total * 100) + "%'></div></div>" : "";
  var who = "";
  if (t.claim) {
    var c = t.claim;
    var ccol = c.signal === "active" ? "var(--green)" : c.signal === "suspect" ? "var(--amber)" : "var(--red)";
    who = "<div class='who'><span class='sdot' style='background:" + ccol + "'></span>"
      + esc(c.agent_name) + " <span class='meta'>· " + esc(c.signal) + "</span></div>";
  }
  var wait = t.awaiting_human ? "<div class='wait'>等待人: " + esc(t.awaiting_human.reason || t.awaiting_human.kind || "")
    + " <span class='meta'>kanban approve " + esc(t.requirement_id) + "</span></div>" : "";
  return "<a class='card" + (t._attn ? " attn" : "") + "' href='/requirements/" + encodeURIComponent(t.requirement_id) + "'>"
    + "<div class='ct'>" + esc(t.title) + "</div>" + pbar
    + (p.total ? "<div class='meta'>进度 " + p.done + "/" + p.total + "</div>" : "")
    + ((attn || risks) ? "<div class='badges'>" + attn + risks + "</div>" : "") + who + wait + "</a>";
}
function renderActive(data){
  var attn = {};
  (data.attention_ids || []).forEach(function(id){ attn[id] = true; });
  var byCol = {};
  COLS.forEach(function(c){ byCol[c[0]] = []; });
  data.tasks.forEach(function(t){ t._attn = !!attn[t.requirement_id]; if (byCol[t.state]) byCol[t.state].push(t); });
  var html = COLS.map(function(c){
    var rows = byCol[c[0]];
    var cards = rows.length ? rows.map(cardHTML).join("") : "<div class='empty'>（空）</div>";
    return "<div class='col'><div class='col-hd'><span class='cdot' style='background:" + c[1] + "'></span>"
      + "<span class='cname'>" + stateZh(c[0]) + "</span><span class='ccount'>" + rows.length + "</span></div>"
      + "<div class='col-body'>" + cards + "</div></div>";
  }).join("");
  document.getElementById("board-root").innerHTML = "<div class='cols'>" + html + "</div>";
  document.getElementById("top-count").textContent = data.tasks.length + " 个在板需求";
}
var DONE_ZH = {DONE:"已完成", CANCELLED:"已取消", REJECTED:"已拒绝", ARCHIVED:"已归档"};
var TAB = "active";
function renderDone(tasks, label, empty){
  tasks.sort(function(a, b){
    var fa = a.finished_at || "", fb = b.finished_at || "";
    return fa < fb ? 1 : (fa > fb ? -1 : 0);
  });
  var rows = tasks.map(function(t){
    var flag = t.reviewed ? "" : "<span class='badge attn'>无评审交接</span>";
    return "<a class='done-row' href='/requirements/" + encodeURIComponent(t.requirement_id) + "'>"
      + "<span class='pill " + esc(t.state) + "'>" + esc(DONE_ZH[t.state] || t.state) + "</span>"
      + "<span class='dt'>" + esc(t.title) + "</span><span class='grow'></span>"
      + "<span class='meta'>完成 " + (esc(fmtTs(t.finished_at)) || "-") + "</span>"
      + "<span class='meta'>决策 " + (t.decision_count || 0) + " · 偏离 " + (t.deviation_count || 0) + "</span>"
      + flag + "</a>";
  }).join("");
  document.getElementById("board-root").innerHTML = "<div class='done-list'>"
    + (rows || "<div class='empty'>" + empty + "</div>") + "</div>";
  document.getElementById("top-count").textContent = tasks.length + " " + label;
}
async function loadBoard(){
  var root = document.getElementById("board-root");
  function fail(msg){ root.innerHTML = "<p class='meta' style='padding:24px'>" + esc(msg) + "</p>"; }
  try {
    if (TAB === "active") {
      var resp = await fetch("/board", {headers: hdr()});
      if (!resp.ok) { fail("加载失败: " + resp.status); return; }
      renderActive(await resp.json());
    } else {
      var sts = TAB === "archived" ? ["ARCHIVED"] : ["DONE", "CANCELLED", "REJECTED"];
      var resps = [];
      for (var i = 0; i < sts.length; i++) {
        resps.push(await fetch("/board?status=" + sts[i], {headers: hdr()}));
      }
      for (var j = 0; j < resps.length; j++) {
        if (!resps[j].ok) { fail("加载失败: " + resps[j].status); return; }
      }
      var all = [];
      for (var k = 0; k < resps.length; k++) {
        (await resps[k].json()).tasks.forEach(function(t){ all.push(t); });
      }
      if (TAB === "archived") renderDone(all, "个已归档", "（无已归档需求）");
      else renderDone(all, "个已完成", "（无已完成需求）");
    }
  } catch (e) { fail("加载失败: " + String(e)); }
}
Array.prototype.forEach.call(document.querySelectorAll(".tab"), function(b){
  b.onclick = function(){
    if (b.getAttribute("data-tab") === TAB) return;
    TAB = b.getAttribute("data-tab");
    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function(x){
      x.className = "tab" + (x === b ? " active" : "");
    });
    loadBoard();
  };
});
document.getElementById("new-btn").onclick = function(){
  var f = document.getElementById("new-form");
  f.style.display = f.style.display === "none" ? "block" : "none";
};
function nfMsg(m, isErr){
  var el = document.getElementById("nf-msg");
  el.textContent = m; el.className = isErr ? "err" : "ok";
}
async function submitNew(){
  var title = document.getElementById("nf-title").value.trim();
  if (!title) { nfMsg("标题必填", true); return; }
  var body = {title: title};
  var desc = document.getElementById("nf-desc").value.trim();
  if (desc) body.description = desc;
  var acc = document.getElementById("nf-acc").value.split("\n")
    .map(function(s){ return s.trim(); }).filter(Boolean);
  if (acc.length) body.acceptance = acc.map(function(s){ return {item: s}; });
  var jira = document.getElementById("nf-jira").value.trim();
  if (jira) { body.source = "jira"; body.source_ref = jira; }
  var resp = await fetch("/requirements", {method: "POST",
    headers: Object.assign(hdr(), {"Content-Type": "application/json"}), body: JSON.stringify(body)});
  var txt = await resp.text(); var b = null;
  try { b = JSON.parse(txt); } catch (e) {}
  if (!resp.ok) { nfMsg("创建失败: " + (b && b.code ? b.code + ": " + (b.message || "") : txt), true); return; }
  ["nf-title", "nf-desc", "nf-acc", "nf-jira"].forEach(function(id){ document.getElementById(id).value = ""; });
  document.getElementById("new-form").style.display = "none";
  nfMsg("已创建", false);
  loadBoard();  // create 不写事件，SSE 无触发器——主动重拉（spec 4.1 / 审 P1-2）
}
loadBoard();
var es = setupSSE();
es.onmessage = loadBoard;
</script>
</body></html>
"""


def detail_shell() -> str:
    """GET /requirements/{id}（Accept 含 text/html）深潜壳：fetch detail+summary 渲染
    验收对照/子任务/里程碑/决策风险偏离/事件时间线/需要关注/认领租约/awaiting_human；
    人面操作 = task 生命周期（archive / delete 标题确认）；决策操作 CLI/REST-only（PRD §4.2 修订）；操作失败内联展示 body {code,message}。"""
    return """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>需求深潜</title>
<style>
""" + _THEME + """
.wrap{max-width:1100px;margin:0 auto;padding:16px 20px 60px}
.head{margin:6px 0 14px}
.head h1{display:inline;margin-right:10px;word-break:break-all}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;align-items:start}
@media (max-width:860px){.grid{grid-template-columns:1fr}}
.sec{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:12px 14px;margin-bottom:12px}
.sec.wide{grid-column:1 / -1}
.sec h2{font-size:.82rem;font-weight:650;color:var(--muted);margin:0 0 10px;letter-spacing:.4px}
.kv{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:.8rem;color:var(--muted);margin:6px 0}
.kv b{color:var(--text);font-weight:600}
ul{list-style:none;padding:0;margin:0}
li{padding:5px 0;border-bottom:1px solid var(--border);font-size:.84rem;line-height:1.45}
li:last-child{border-bottom:none}
.li-t{display:flex;flex-wrap:wrap;align-items:center;gap:6px}
.attn-panel{background:rgba(210,153,34,.08);border:1px solid rgba(210,153,34,.35);border-radius:10px;padding:12px 14px;margin-bottom:12px}
.attn-panel h2{font-size:.82rem;font-weight:650;color:var(--amber);margin:0 0 8px}
.attn-panel .ab{display:inline-block;margin:2px 6px 2px 0}
.ev{display:flex;gap:10px;padding:7px 0;border-bottom:1px solid var(--border);font-size:.82rem}
.ev:last-child{border-bottom:none}
.ev .rail{flex:none;width:8px;height:8px;border-radius:50%;margin-top:5px;background:var(--faint)}
.ev .rail.attention{background:var(--amber)}
.ev .rail.critical{background:var(--red)}
.ev .ehd{display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center}
.ev .et{margin-top:2px;color:var(--text)}
.ops{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
button{background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:7px;
  padding:6px 14px;font-size:.82rem;cursor:pointer;transition:background .12s}
button:hover{background:var(--card-hi);border-color:#35414f}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
button.primary:hover{filter:brightness(1.1)}
textarea,select{background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:7px;
  padding:6px 8px;font-size:.82rem;width:100%}
.op-row{margin-top:10px}
#op-msg{font-size:.8rem;margin-top:10px;min-height:1em}
#op-msg.err{color:var(--red)}
#op-msg.ok{color:var(--green)}
.pbar{height:5px;border-radius:3px;background:var(--border);overflow:hidden;display:flex;width:220px;max-width:100%}
.pbar .pd{background:var(--green)}
.pbar .pb{background:var(--orange)}
.wait-banner{background:rgba(210,153,34,.1);border:1px solid rgba(210,153,34,.35);color:var(--amber);
  border-radius:8px;padding:8px 12px;font-size:.82rem;margin:8px 0}
</style></head>
<body>
<div class="topbar">
  <a href="/" style="font-size:.85rem">← 看板</a>
  <span class="title">需求深潜</span>
  <div class="live" id="live"><div class="dot"></div><span>连接中</span></div>
</div>
<div id="detail-root"><p class="meta" style="padding:24px">加载中…</p></div>
<script>
""" + _JS_COMMON + """
var RID = decodeURIComponent(location.pathname.replace(/^\\/requirements\\//, "").split("/")[0]);
async function load(){
  var root = document.getElementById("detail-root");
  try {
    var [dr, sr] = await Promise.all([
      fetch("/requirements/" + encodeURIComponent(RID), {headers: hdr()}),
      fetch("/requirements/" + encodeURIComponent(RID) + "/summary", {headers: hdr()}),
    ]);
    if (!dr.ok || !sr.ok) {
      var msg = dr.status === 404 ? "任务不存在（可能已被人删除）" : "加载失败: " + dr.status + " / " + sr.status;
      root.innerHTML = "<p class='meta'>" + msg + "</p>"; return;
    }
    render(await dr.json(), await sr.json());
  } catch (e) { root.innerHTML = "<p class='meta'>加载失败: " + esc(String(e)) + "</p>"; }
}
var _D = null;
var _S = null;
function render(d, s){
  _D = d;
  _S = s;
  var p = s.progress || {done:0,total:0,blocked:0};
  var pct = p.total ? Math.round(p.done / p.total * 100) : 0;
  var html = "<div class='wrap'>";
  html += "<div class='head'><h1>" + esc(s.title) + "</h1><span class='pill " + esc(s.state) + "'>"
    + esc(stateZh(s.state)) + "</span></div>";
  html += "<p class='meta'>id: " + esc(s.requirement_id) + "</p>";
  if (d.history_note) html += "<p class='meta'>" + esc(d.history_note) + "</p>";
  if (s.awaiting_human) {
    var hint = s.awaiting_human.kind === "blocked" ? "解除阻塞: kanban approve " : "人面确认: kanban approve ";
    html += "<div class='wait-banner'>等待人决策: kind=" + esc(s.awaiting_human.kind)
      + " reason=" + esc(s.awaiting_human.reason || "")
      + " <span class='meta'>（" + hint + esc(s.requirement_id) + "）</span></div>";
  }
  var c = s.claim;
  if (c) {
    var ccol = c.signal === "active" ? "var(--green)" : c.signal === "suspect" ? "var(--amber)" : "var(--red)";
    html += "<div class='kv'><span>认领 <b>" + esc(c.agent_name) + "</b> <span style='color:" + ccol + "'>● " + esc(c.signal) + "</span></span>"
      + "<span>conn " + esc(c.agent_conn || "-") + "</span><span>租约到期 " + esc(fmtTs(c.lease_expires_at)) + "</span>"
      + "<span>最近活跃 " + esc(fmtTs(c.last_activity_at)) + "</span></div>";
  }
  html += "<div class='pbar'><div class='pd' style='width:" + pct + "%'></div>"
    + "<div class='pb' style='width:" + (p.total ? Math.round(p.blocked / p.total * 100) : 0) + "%'></div></div>";
  html += "<p class='meta' style='margin-top:4px'>进度 " + p.done + "/" + p.total
    + "（blocked=" + (p.blocked || 0) + "、abandoned=" + (p.abandoned || 0) + "）</p>";

  var attn = (s.needs_attention || []).map(function(n){
    return "<span class='badge attn ab'>" + esc(sigLabel(n.type)) + "</span>"; }).join("");
  if (attn) html += "<div class='attn-panel'><h2>需要关注</h2>" + attn + "</div>";

  html += "<div class='grid'>";
  html += "<div class='sec'><h2>验收对照</h2><ul>";
  s.acceptance_table.forEach(function(a){
    if (a.uncovered) html += "<li><span class='badge gap'>覆盖缺口</span> " + esc(a.item) + "</li>";
    else html += "<li>" + esc(a.item) + " → " + a.linked.map(function(x){
      return "<span class='pill " + esc(x.state) + "'>" + esc(x.state) + "</span> " + esc(x.item) + " @ " + esc(x.subtask_title);
    }).join("，") + "</li>";
  });
  html += "</ul></div>";
  html += "<div class='sec'><h2>子任务</h2><ul>";
  d.subtasks.forEach(function(st){
    html += "<li><span class='meta'>" + st.ordinal + ".</span> " + esc(st.title)
      + " <span class='pill " + esc(st.state) + "'>" + esc(st.state) + "</span>";
    (st.acceptance || []).forEach(function(acc){ html += " <span class='meta'>" + esc(acc.item) + ":" + esc(acc.state || "") + "</span>"; });
    html += "</li>";
  });
  html += "</ul></div>";
  html += "<div class='sec'><h2>里程碑</h2><ul>";
  if (!d.milestones.length) html += "<li class='muted'>（无）</li>";
  d.milestones.forEach(function(m){
    html += "<li><span class='pill " + esc(m.state) + "'>" + esc(m.state) + "</span> " + esc(m.title)
      + " <span class='meta'>计划 " + esc(fmtTs(m.planned_at) || "-") + " · 实际 " + esc(fmtTs(m.actual_at) || "-") + "</span></li>";
  });
  html += "</ul></div>";
  html += "<div class='sec'><h2>决策 / 风险 / 偏离</h2><ul>";
  s.decisions.forEach(function(x){ html += "<li><b>决策</b> " + esc(x.title) + " → " + esc(x.choice || "")
    + (x.alternatives && x.alternatives.length ? " <span class='meta'>（" + x.alternatives.length + " 个备选）</span>" : "") + "</li>"; });
  s.risks.forEach(function(x){ html += "<li><span class='badge risk" + (x.severity === "critical" ? " critical" : "") + "'>" + esc(x.severity) + "</span> " + esc(x.title) + "</li>"; });
  s.deviations.forEach(function(x){ html += "<li><span class='badge attn'>" + esc(x.severity) + " 偏离</span> " + esc(x.title) + "</li>"; });
  if (!s.decisions.length && !s.risks.length && !s.deviations.length) html += "<li class='muted'>（无）</li>";
  html += "</ul></div>";
  html += "</div>";

  html += "<div class='sec wide'><h2>事件流</h2><div class='ops' style='margin-bottom:10px'>"
    + "<select id='ev-kind' style='width:auto'><option value=''>kind: 全部</option>";
  ["decision","risk","deviation","decomposition","progress_note","state_change","review_request","approval","release","renew","note","reconcile"].forEach(function(k){
    html += "<option value='" + k + "'>" + k + "</option>";
  });
  html += "</select>";
  html += "<select id='ev-sev' style='width:auto'><option value=''>severity: 全部</option>";
  ["info","attention","critical"].forEach(function(v){ html += "<option value='" + v + "'>" + v + "</option>"; });
  html += "</select></div><div id='ev-list'></div></div>";

  html += "<div class='sec wide'><h2>Task 生命周期</h2><div id='op-msg'></div>"
    + "<div class='ops'>"
    + "<button class='primary' data-op='archive'" + (s.state === "ARCHIVED" ? " disabled" : "") + ">archive</button>"
    + "</div>"
    + "<div class='op-row' style='margin-top:14px'>"
    + "<button onclick='doDelete()'>delete</button>"
    + "<span class='meta'>整需求硬删（不可逆，建议先 kanban export；输入标题确认）</span></div></div>";
  html += "</div>";
  document.getElementById("detail-root").innerHTML = html;
  Array.prototype.forEach.call(document.querySelectorAll("[data-op]"), function(b){
    b.onclick = function(){ doOp(b.getAttribute("data-op")); };
  });
  renderEvents();
  var k = document.getElementById("ev-kind"), v = document.getElementById("ev-sev");
  k.onchange = renderEvents;
  v.onchange = renderEvents;
}
function renderEvents(){
  if (!_D) return;
  var k = document.getElementById("ev-kind").value, v = document.getElementById("ev-sev").value;
  var html = "";
  _D.events.forEach(function(e){
    if (k && e.kind !== k) return;
    if (v && e.severity !== v) return;
    html += "<div class='ev'><div class='rail " + esc(e.severity) + "'></div><div style='flex:1'>"
      + "<div class='ehd'><span class='meta'>#" + e.seq + "</span>"
      + "<span class='meta'>" + esc(fmtTs(e.ts)) + "</span>"
      + "<span class='badge " + (e.severity === "critical" ? "risk critical" : e.severity === "attention" ? "attn" : "") + "'>"
      + esc(e.kind) + "/" + esc(e.severity) + "</span>"
      + "<span class='meta'>" + esc(e.actor_surface) + ":" + esc(e.actor_conn || "-") + "</span>"
      + (e.state_at_event ? "<span class='meta'>state=" + esc(e.state_at_event) + "</span>" : "")
      + "</div><div class='et'>" + esc(e.title) + "</div></div></div>";
  });
  document.getElementById("ev-list").innerHTML = html || "<p class='muted'>（无匹配事件）</p>";
}
async function doOp(name){
  var resp = await fetch("/requirements/" + encodeURIComponent(RID) + "/" + name, {method: "POST", headers: hdr()});
  handleOpResult(resp);
}
async function doDelete(){
  if (!_S) return;
  var t = prompt("删除不可逆（建议先 kanban export）。当前状态: " + stateZh(_S.state)
    + "，事件 " + _D.events.length + " 条。输入任务标题确认删除:");
  if (t === null) return;
  if (t.trim() !== _S.title) { flash("标题不匹配，已取消删除", true); return; }
  var resp = await fetch("/requirements/" + encodeURIComponent(RID), {method: "DELETE", headers: hdr()});
  handleOpResult(resp);
}
async function handleOpResult(resp){
  var txt = await resp.text();
  var body = null;
  try { body = JSON.parse(txt); } catch (e) {}
  if (!resp.ok) {
    flash("操作失败: " + (body && body.code ? body.code + ": " + (body.message || "") : txt), true);
    return;
  }
  flash("操作成功", false);
  load();
}
function flash(msg, isErr){
  var el = document.getElementById("op-msg");
  if (el) { el.textContent = msg; el.className = isErr ? "err" : "ok"; }
}
load();
var es = setupSSE();
es.onmessage = load;
</script>
</body></html>
"""
