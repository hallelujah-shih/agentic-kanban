"""Web 窗口 HTML 壳（M1-2.4，PRD §4.2 Web 窗口 surface 表）。

反淹没结构保证：壳为静态 HTML + 内联 JS，零数据嵌入——数据一律由 JS fetch
REST 获取后渲染；看板壳只渲染 /board 返回的紧凑行（无 content/payload），
深潜壳事件流只渲染标题行（无 content/payload），原始输出结构上不进壳/渲染。
token 传播：页面从 URL ?token= 读 token 存入 sessionStorage，全部 fetch/EventSource 附 token
（EventSource 无法设 header，走 ?token= query）。
"""

from __future__ import annotations


def board_shell() -> str:
    """GET / 看板壳：fetch /board 渲染（需要关注区置顶 + 紧凑行）+ EventSource 重拉。"""
    return """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>agent-kanban 看板</title>
<style>
body{font-family:system-ui,sans-serif;margin:0;padding:16px;background:#fafafa;color:#1a1a1a}
h1{font-size:1.2rem;margin:0 0 12px}
.row{display:flex;gap:8px;align-items:center;padding:8px 0;border-bottom:1px solid #eee;font-size:0.9rem;flex-wrap:wrap}
.row a{color:#065fd4;text-decoration:none}
.tag{font-size:0.75rem;padding:2px 6px;border-radius:4px;background:#eee;white-space:nowrap}
.tag.attn{background:#fde68a}
.tag.risk{background:#fecaca}
.tag.state{background:#dbeafe}
.meta{color:#666;font-size:0.78rem}
</style></head>
<body>
<h1>agent-kanban 看板</h1>
<div id="board-root">加载中…</div>
<script>
(function(){
  var qs = new URLSearchParams(location.search);
  var t = qs.get("token");
  if (t) sessionStorage.setItem("kanban_token", t);
})();
var TOKEN = sessionStorage.getItem("kanban_token") || "";
function hdr(){ return TOKEN ? {"x-agent-kanban-token": TOKEN} : {}; }
function esc(s){ var d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }
async function loadBoard(){
  var root = document.getElementById("board-root");
  try {
    var resp = await fetch("/board", {headers: hdr()});
    if (!resp.ok) { root.innerHTML = "<p>加载失败: " + esc(resp.status) + "</p>"; return; }
    render(await resp.json());
  } catch (e) { root.innerHTML = "<p>加载失败: " + esc(String(e)) + "</p>"; }
}
function rowHTML(t){
  var attn = (t.needs_attention || []).map(function(n){ return "<span class='tag attn'>" + esc(n.type) + "</span>"; }).join(" ");
  var risks = (t.risks || []).map(function(x){ return "<span class='tag risk'>风险[" + esc(x.severity) + "]: " + esc(x.title) + "</span>"; }).join(" ");
  var meta = "<span class='meta'>进度 " + t.progress.done + "/" + t.progress.total + "</span>";
  if (t.claim) meta += " <span class='meta'>认领:" + esc(t.claim.agent_name) + "[" + esc(t.claim.signal) + "]</span>";
  if (t.awaiting_human) meta += " <span class='meta'>等待人:" + esc(t.awaiting_human.kind) + "</span>";
  return "<div class='row'><a href='/requirements/" + encodeURIComponent(t.requirement_id) + "'>" + esc(t.title) + "</a>"
    + "<span class='tag state'>" + esc(t.state) + "</span>" + (attn ? attn : "") + risks + meta + "</div>";
}
function render(data){
  var attn = {}, attnRows = [], otherRows = [];
  (data.attention_ids || []).forEach(function(id){ attn[id] = true; });
  data.tasks.forEach(function(t){ (attn[t.requirement_id] ? attnRows : otherRows).push(t); });
  var html = attnRows.map(rowHTML).join("") + otherRows.map(rowHTML).join("");
  document.getElementById("board-root").innerHTML = html || "<p>（无任务）</p>";
}
loadBoard();
var es = new EventSource("/events/stream" + (TOKEN ? "?token=" + encodeURIComponent(TOKEN) : ""));
es.onopen = loadBoard;
es.onmessage = loadBoard;
</script>
</body></html>
"""


def detail_shell() -> str:
    """GET /requirements/{id}（Accept 含 text/html）深潜壳：fetch detail+summary 渲染
    验收对照/子任务/里程碑/决策风险偏离/事件流过滤/需要关注/认领租约/awaiting_human；
    人面操作 approve/release(reason)/renew/note(content)/abandon(to_state)/reopen(continue)/
    set_expectations(JSON textarea)；操作失败内联展示 body {code,message}。"""
    return """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>需求深潜</title>
<style>
body{font-family:system-ui,sans-serif;margin:0;padding:16px;background:#fafafa;color:#1a1a1a}
h1{font-size:1.2rem}
h2{font-size:1rem;margin:16px 0 6px}
.tag{font-size:0.75rem;padding:2px 6px;border-radius:4px;background:#eee;white-space:nowrap}
.tag.attn{background:#fde68a}
.tag.gap{background:#fecaca}
.tag.state{background:#dbeafe}
.meta{color:#666;font-size:0.78rem}
ul{padding-left:18px;margin:4px 0}
li{font-size:0.85rem;margin:2px 0}
#op-msg{color:#b91c1c;font-size:0.85rem;margin:8px 0}
button{font-size:0.8rem;margin-right:6px}
textarea,select,input{font-size:0.85rem}
</style></head>
<body>
<div id="detail-root">加载中…</div>
<script>
(function(){
  var qs = new URLSearchParams(location.search);
  var t = qs.get("token");
  if (t) sessionStorage.setItem("kanban_token", t);
})();
var TOKEN = sessionStorage.getItem("kanban_token") || "";
function hdr(){ return TOKEN ? {"x-agent-kanban-token": TOKEN} : {}; }
function esc(s){ var d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }
var RID = decodeURIComponent(location.pathname.replace(/^\\/requirements\\//, "").split("/")[0]);
async function load(){
  var root = document.getElementById("detail-root");
  try {
    var [dr, sr] = await Promise.all([
      fetch("/requirements/" + encodeURIComponent(RID), {headers: hdr()}),
      fetch("/requirements/" + encodeURIComponent(RID) + "/summary", {headers: hdr()}),
    ]);
    if (!dr.ok || !sr.ok) { root.innerHTML = "<p>加载失败: " + dr.status + " / " + sr.status + "</p>"; return; }
    render(await dr.json(), await sr.json());
  } catch (e) { root.innerHTML = "<p>加载失败: " + esc(String(e)) + "</p>"; }
}
function attnTags(list){
  return (list || []).map(function(n){ return "<span class='tag attn'>" + esc(n.type) + "</span>"; }).join(" ");
}
function render(d, s){
  var html = "<h1>" + esc(s.title) + " <span class='tag state'>" + esc(s.state) + "</span></h1>";
  html += "<p class='meta'>id: " + esc(s.requirement_id) + "</p>";
  if (s.awaiting_human) html += "<p>等待人: kind=" + esc(s.awaiting_human.kind) + " reason=" + esc(s.awaiting_human.reason || "") + "</p>";
  var c = s.claim;
  if (c) html += "<p class='meta'>认领: " + esc(c.agent_name) + " conn=" + esc(c.agent_conn) + " signal=" + esc(c.signal) + " 租约到期=" + esc(c.lease_expires_at) + "</p>";
  var p = s.progress;
  html += "<p class='meta'>进度 " + p.done + "/" + p.total + "（blocked=" + p.blocked + "、abandoned=" + p.abandoned + "）</p>";
  html += "<h2>验收对照</h2><ul>";
  s.acceptance_table.forEach(function(a){
    if (a.uncovered) html += "<li><span class='tag gap'>覆盖缺口</span> " + esc(a.item) + "</li>";
    else html += "<li>" + esc(a.item) + " -> " + a.linked.map(function(x){ return esc(x.item) + "(" + esc(x.state) + ")@" + esc(x.subtask_title); }).join(", ") + "</li>";
  });
  html += "</ul><h2>子任务</h2><ul>";
  d.subtasks.forEach(function(st){
    html += "<li>(" + st.ordinal + ") " + esc(st.title) + " [" + esc(st.state) + "]";
    (st.acceptance || []).forEach(function(acc){ html += " <span class='meta'>" + esc(acc.item) + ":" + esc(acc.state || "") + "</span>"; });
    html += "</li>";
  });
  html += "</ul><h2>里程碑</h2><ul>";
  d.milestones.forEach(function(m){ html += "<li>" + esc(m.title) + " [" + esc(m.state) + "] planned=" + esc(m.planned_at || "-") + " actual=" + esc(m.actual_at || "-") + "</li>"; });
  html += "</ul><h2>决策 / 风险 / 偏离</h2><ul>";
  s.decisions.forEach(function(x){ html += "<li>决策: " + esc(x.title) + " -> " + esc(x.choice || "") + "（备选 " + (x.alternatives || []).length + "）</li>"; });
  s.risks.forEach(function(x){ html += "<li>风险 [" + esc(x.severity) + "]: " + esc(x.title) + "</li>"; });
  s.deviations.forEach(function(x){ html += "<li>偏离 [" + esc(x.severity) + "]: " + esc(x.title) + "</li>"; });
  html += "</ul><h2>需要关注</h2><p>" + (attnTags(s.needs_attention) || "无") + "</p>";
  html += "<h2>事件流</h2><div>过滤 kind: <select id='ev-kind'><option value=''>全部</option>";
  ["decision","risk","deviation","decomposition","progress_note","state_change","review_request","approval","release","note","reconcile"].forEach(function(k){
    html += "<option value='" + k + "'>" + k + "</option>";
  });
  html += "</select> severity: <select id='ev-sev'><option value=''>全部</option>";
  ["info","attention","critical"].forEach(function(v){ html += "<option value='" + v + "'>" + v + "</option>"; });
  html += "</select></div><ul id='ev-list'></ul>";
  html += "<h2>人面操作</h2><div id='op-msg'></div>";
  html += "<button onclick='doOp(\"approve\")'>approve</button>";
  html += "<button onclick='doRelease()'>release(reason)</button>";
  html += "<button onclick='doOp(\"renew\")'>renew</button>";
  html += "<button onclick='doReopen(false)'>reopen</button>";
  html += "<button onclick='doReopen(true)'>reopen --continue</button>";
  html += "<button onclick='doAbandon()'>abandon</button>";
  html += "<br><br><textarea id='note-input' rows='2' cols='50' placeholder='note content'></textarea>"
    + " <button onclick='doNote()'>note</button>";
  html += "<br><br><textarea id='acc-input' rows='6' cols='70' placeholder='set_expectations: JSON acceptance 数组'></textarea>"
    + " <button onclick='doExpectations()'>set_expectations</button>";
  html += "<br><br><select id='abandon-state'><option value='REJECTED'>REJECTED</option><option value='CANCELLED'>CANCELLED</option></select>";
  document.getElementById("detail-root").innerHTML = html;
  renderEvents(d);
  var k = document.getElementById("ev-kind"), v = document.getElementById("ev-sev");
  k.onchange = function(){ renderEvents(d); };
  v.onchange = function(){ renderEvents(d); };
}
function renderEvents(d){
  var k = document.getElementById("ev-kind").value, v = document.getElementById("ev-sev").value;
  var html = "";
  d.events.forEach(function(e){
    if (k && e.kind !== k) return;
    if (v && e.severity !== v) return;
    html += "<li>#" + e.seq + " [" + esc(e.state_at_event || "") + "] " + esc(e.ts) + " "
      + esc(e.kind) + "/" + esc(e.severity) + " by " + esc(e.actor_surface) + ":" + esc(e.actor_conn || "-")
      + " " + esc(e.title) + "</li>";
  });
  document.getElementById("ev-list").innerHTML = html || "<li>（无匹配事件）</li>";
}
async function doOp(name){
  var resp = await fetch("/requirements/" + encodeURIComponent(RID) + "/" + name, {method: "POST", headers: hdr()});
  handleOpResult(resp);
}
async function doRelease(){
  var reason = prompt("release reason");
  if (reason === null) return;
  var resp = await fetch("/requirements/" + encodeURIComponent(RID) + "/release",
    {method: "POST", headers: Object.assign(hdr(), {"Content-Type": "application/json"}), body: JSON.stringify({reason: reason})});
  handleOpResult(resp);
}
async function doReopen(cont){
  var opts = {method: "POST", headers: hdr()};
  if (cont) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify({continue: true}); }
  var resp = await fetch("/requirements/" + encodeURIComponent(RID) + "/reopen", opts);
  handleOpResult(resp);
}
async function doAbandon(){
  var st = document.getElementById("abandon-state").value;
  var resp = await fetch("/requirements/" + encodeURIComponent(RID) + "/abandon",
    {method: "POST", headers: Object.assign(hdr(), {"Content-Type": "application/json"}), body: JSON.stringify({to_state: st})});
  handleOpResult(resp);
}
async function doNote(){
  var content = document.getElementById("note-input").value;
  var resp = await fetch("/requirements/" + encodeURIComponent(RID) + "/note",
    {method: "POST", headers: Object.assign(hdr(), {"Content-Type": "application/json"}), body: JSON.stringify({content: content})});
  handleOpResult(resp);
}
async function doExpectations(){
  var txt = document.getElementById("acc-input").value;
  var acceptance;
  try { acceptance = JSON.parse(txt); } catch (e) { flash("set_expectations: JSON 解析失败"); return; }
  var resp = await fetch("/requirements/" + encodeURIComponent(RID) + "/expectations",
    {method: "PUT", headers: Object.assign(hdr(), {"Content-Type": "application/json"}), body: JSON.stringify({acceptance: acceptance})});
  handleOpResult(resp);
}
async function handleOpResult(resp){
  var txt = await resp.text();
  var body = null;
  try { body = JSON.parse(txt); } catch (e) {}
  if (!resp.ok) {
    // 操作失败内联展示 body {code,message}（审#P2-3）
    flash("操作失败: " + (body && body.code ? body.code + ": " + (body.message || "") : txt));
    return;
  }
  flash("操作成功");
  load();
}
function flash(msg){ var el = document.getElementById("op-msg"); if (el) el.textContent = msg; }
load();
</script>
</body></html>
"""
