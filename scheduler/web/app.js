"use strict";
const STATUS = {todo:"할 일", in_progress:"진행 중", in_review:"리뷰", blocked:"막힘", done:"완료"};
const PRIORITY = ["highest","high","medium","low","lowest"];
const TYPE_LABEL = {project:"과제", item:"아이템", subitem:"서브"};
const CHILD = {project:"item", item:"subitem"};
const DAY = 24, NAME_W = 300;

let tree = [], tab = "gantt", selected = null;
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

// pywebview in the exe; plain HTTP shim when run via `python -m scheduler.devserver`
async function call(name, ...args) {
  let res;
  if (window.pywebview && window.pywebview.api) res = await window.pywebview.api[name](...args);
  else res = await (await fetch("/api/" + name, {method:"POST", body: JSON.stringify(args)})).json();
  if (!res.ok) { setStatus(res.error, true); throw new Error(res.error); }
  return res.data;
}
function setStatus(msg, err) { const s = $("#status"); s.textContent = msg; s.className = err ? "err" : ""; s.title = msg; }

function flatten(nodes, depth = 0, out = []) {
  for (const n of nodes) { out.push({...n, depth}); flatten(n.children, depth + 1, out); }
  return out;
}
const iso = d => d.toISOString().slice(0, 10);
const parse = s => new Date(s + "T00:00:00Z");
const diffDays = (a, b) => Math.round((parse(b) - parse(a)) / 864e5);

// own span, else min/max over descendants
function span(n) {
  let s = n.start_date || n.due_date, e = n.due_date || n.start_date;
  if (!s) for (const c of n.children) {
    const cs = span(c); if (!cs) continue;
    if (!s || cs[0] < s) s = cs[0];
    if (!e || cs[1] > e) e = cs[1];
  }
  return s ? [s, e || s] : null;
}
const badge = st => `<span class="badge" style="background:var(--${st})">${STATUS[st] || st}</span>`;

function render() {
  document.querySelectorAll(".tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
  const v = $("#view");
  if (tab === "gantt") v.innerHTML = renderGantt();
  else if (tab === "list") v.innerHTML = renderList();
  else v.innerHTML = renderText();
  v.querySelectorAll("[data-key]").forEach(el => {
    el.onclick = () => select(el.dataset.key);
    el.classList.toggle("sel", el.dataset.key === selected);
  });
  renderDetail();
}

function renderGantt() {
  const rows = flatten(tree);
  if (!rows.length) return `<p style="padding:16px;color:var(--muted)">과제가 없습니다. 아래 입력창에 일정을 적거나 “+ 과제”를 누르세요.</p>`;
  const today = iso(new Date());
  const spans = rows.map(r => span(r));
  const all = spans.filter(Boolean).flat().concat(today).sort();
  const start = iso(new Date(parse(all[0]).getTime() - 7 * 864e5));
  const end = iso(new Date(parse(all[all.length - 1]).getTime() + 21 * 864e5));
  const days = diffDays(start, end) + 1, W = days * DAY;
  let ticks = "", months = "";
  for (let i = 0; i < days; i++) {
    const d = new Date(parse(start).getTime() + i * 864e5);
    if (d.getUTCDay() === 1) ticks += `<div class="g-tick" style="left:${i*DAY}px"></div>`;
    if (d.getUTCDate() === 1 || i === 0) months += `<div class="g-month" style="left:${i*DAY}px">${d.getUTCFullYear()}-${String(d.getUTCMonth()+1).padStart(2,"0")}</div>`;
  }
  const todayX = diffDays(start, today) * DAY + DAY / 2;
  let h = `<div class="gantt" style="grid-template-columns:${NAME_W}px ${W}px">`;
  h += `<div class="g-name g-head">이름</div><div class="g-head g-track" style="position:sticky">${months}${ticks}</div>`;
  rows.forEach((r, i) => {
    const sp = spans[i];
    h += `<div class="g-name type-${r.type}" data-key="${r.key}" style="padding-left:${8 + r.depth*16}px" title="${esc(r.title)}"><span class="key">${r.key}</span>${esc(r.title)}</div>`;
    h += `<div class="g-track">${ticks}<div class="g-today" style="left:${todayX}px"></div>`;
    if (sp) {
      const x = diffDays(start, sp[0]) * DAY, w = (diffDays(sp[0], sp[1]) + 1) * DAY;
      h += `<div class="g-bar" data-key="${r.key}" style="left:${x}px;width:${w}px;background:var(--${r.status})" title="${esc(r.title)} ${sp[0]} ~ ${sp[1]}"><div class="prog" style="width:${r.progress}%"></div><span style="position:relative">${r.progress ? r.progress + "%" : ""}</span></div>`;
    }
    h += `</div>`;
  });
  return h + `</div>`;
}

function renderList() {
  const rows = flatten(tree);
  let h = `<table><tr><th>키</th><th>제목</th><th>유형</th><th>상태</th><th>우선순위</th><th>담당</th><th>시작</th><th>마감</th><th>진행</th><th>예상(h)</th><th>라벨</th></tr>`;
  for (const r of rows) h += `<tr class="row type-${r.type}" data-key="${r.key}"><td>${r.key}</td><td style="padding-left:${8 + r.depth*18}px">${esc(r.title)}</td><td>${TYPE_LABEL[r.type]}</td><td>${badge(r.status)}</td><td>${r.priority}</td><td>${esc(r.assignee)}</td><td>${r.start_date||""}</td><td>${r.due_date||""}</td><td>${r.progress}%</td><td>${r.estimate_h ?? ""}</td><td>${esc(r.labels)}</td></tr>`;
  return h + `</table>`;
}

function renderText() {
  const lines = [];
  const walk = (nodes, d) => nodes.forEach(n => {
    const meta = [STATUS[n.status], n.priority, n.assignee && "@" + n.assignee, n.due_date && "~" + n.due_date, n.progress && n.progress + "%"].filter(Boolean).join(" | ");
    lines.push(`${"  ".repeat(d)}${d ? "- " : ""}[${n.key}] ${n.title}  (${meta})`);
    if (n.description) lines.push(`${"  ".repeat(d + 1)}  ${n.description.replace(/\n/g, "\n" + "  ".repeat(d + 1) + "  ")}`);
    walk(n.children, d + 1);
  });
  walk(tree, 0);
  return `<pre class="text">${esc(lines.join("\n")) || "(비어 있음)"}</pre>`;
}

function find(key, nodes = tree) {
  for (const n of nodes) { if (n.key === key) return n; const f = find(key, n.children); if (f) return f; }
}
function select(key) { selected = key; render(); }

function renderDetail() {
  const d = $("#detail"), n = selected && find(selected);
  if (!n) { d.hidden = true; return; }
  d.hidden = false;
  const inp = (f, t = "text") => `<input data-f="${f}" type="${t}" value="${esc(n[f] ?? "")}">`;
  const sel = (f, opts) => `<select data-f="${f}">${opts.map(([v, l]) => `<option value="${v}"${n[f] === v ? " selected" : ""}>${l}</option>`).join("")}</select>`;
  d.innerHTML = `<h3>${n.key} <small>${TYPE_LABEL[n.type]}</small></h3>
    <label>제목</label>${inp("title")}
    <label>설명</label><textarea data-f="description" rows="5">${esc(n.description)}</textarea>
    <label>상태</label>${sel("status", Object.entries(STATUS))}
    <label>우선순위</label>${sel("priority", PRIORITY.map(p => [p, p]))}
    <label>담당자</label>${inp("assignee")}
    <label>보고자</label>${inp("reporter")}
    <label>라벨 (쉼표 구분)</label>${inp("labels")}
    <label>시작일</label>${inp("start_date", "date")}
    <label>마감일</label>${inp("due_date", "date")}
    <label>예상 시간(h)</label>${inp("estimate_h", "number")}
    <label>진행률(%)</label>${inp("progress", "number")}
    <div class="links" id="d-links"></div>
    <p style="color:var(--muted)">생성 ${n.created_at} · 수정 ${n.updated_at}</p>
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      ${CHILD[n.type] ? `<button id="d-add">+ ${TYPE_LABEL[CHILD[n.type]]}</button>` : ""}
      <button id="d-del">삭제</button><button id="d-close">닫기</button></div>`;
  d.querySelectorAll("[data-f]").forEach(el => el.onchange = async () => {
    await call("update", n.key, {[el.dataset.f]: el.value}); await reload();
  });
  $("#d-close").onclick = () => { selected = null; render(); };
  call("get_item", n.key).then(g => {
    const el = $("#d-links"); if (!el || selected !== n.key) return;
    const a = ks => ks.map(k => `<a data-go="${k}">${k}</a>`).join("") || "-";
    el.innerHTML = `<label>연결 (→ 이 항목이 참조)</label>${a(g.links)}<label>백링크 (← 참조하는 항목)</label>${a(g.backlinks)}`;
    el.querySelectorAll("[data-go]").forEach(x => x.onclick = () => select(x.dataset.go));
  }).catch(() => {});
  $("#d-del").onclick = async () => {
    if (!confirm(`${n.key} 및 하위 항목을 삭제할까요?`)) return;
    await call("delete", n.key); selected = null; await reload();
  };
  const add = $("#d-add");
  if (add) add.onclick = async () => {
    const t = prompt(`${TYPE_LABEL[CHILD[n.type]]} 제목`); if (!t) return;
    const r = await call("create", CHILD[n.type], t, n.key); selected = r.key; await reload();
  };
}

async function reload() { tree = await call("tree"); render(); }

const history = [];
function linkKeys(text) {
  return esc(text).replace(/\[?\b([A-Za-z0-9]+-\d+|P\d+)\b\]?/g, (m, k) => find(k) ? `<a class="k" data-go="${k}">${m}</a>` : m);
}
function addMsg(cls, html) {
  const m = document.createElement("div"); m.className = "msg " + cls; m.innerHTML = html;
  m.querySelectorAll("[data-go]").forEach(x => x.onclick = () => select(x.dataset.go));
  const box = $("#msgs"); box.appendChild(m); box.scrollTop = box.scrollHeight; return m;
}
async function sendLLM() {
  const inp = $("#llm-input"), text = inp.value.trim(); if (!text) return;
  inp.value = ""; $("#llm-send").disabled = true;
  addMsg("user", esc(text));
  const pend = addMsg("pending", "생각 중...");
  try {
    const r = await call("chat", text, history.slice());
    history.push({role: "user", content: text}, {role: "assistant", content: r.answer});
    let h = linkKeys(r.answer || "(응답 없음)");
    if (r.results.length) h += `<div class="ops">${r.results.map(x => "✔ " + linkKeys(x)).join("<br>")}</div>`;
    if (r.steps.length) h += `<details><summary>조회 ${r.steps.length}회</summary>${r.steps.map(s => esc(s.tool + " " + JSON.stringify(s.args))).join("<br>")}</details>`;
    pend.remove(); addMsg("bot", h);
    if (r.results.length) await reload();
  } catch (e) { pend.remove(); addMsg("bot err", esc(e.message)); }
  $("#llm-send").disabled = false; inp.focus();
}

async function openSettings() {
  const s = await call("get_settings");
  $("#s-proto").value = s.llm_protocol; $("#s-url").value = s.llm_base_url;
  $("#s-model").value = s.llm_model; $("#s-key").value = s.llm_api_key; $("#s-timeout").value = s.llm_timeout;
  $("#s-result").textContent = ""; $("#settings-dlg").showModal();
}
const readSettings = () => ({llm_protocol: $("#s-proto").value, llm_base_url: $("#s-url").value.trim(),
  llm_model: $("#s-model").value.trim(), llm_api_key: $("#s-key").value, llm_timeout: $("#s-timeout").value});

async function init() {
  document.querySelectorAll(".tabs button").forEach(b => b.onclick = () => { tab = b.dataset.tab; render(); });
  $("#btn-new-project").onclick = async () => {
    const t = prompt("과제 이름"); if (!t) return;
    const r = await call("create", "project", t); selected = r.key; await reload();
  };
  $("#btn-settings").onclick = openSettings;
  $("#s-save").onclick = async () => { await call("save_settings", readSettings()); $("#settings-dlg").close(); setStatus("설정 저장됨"); };
  $("#s-test").onclick = async () => {
    await call("save_settings", readSettings()); $("#s-result").textContent = "확인 중...";
    try { $("#s-result").textContent = "OK: " + await call("test_llm"); } catch (e) { $("#s-result").textContent = "실패"; }
  };
  $("#llm-send").onclick = sendLLM;
  $("#llm-input").onkeydown = e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendLLM(); } };
  $("#chat-clear").onclick = () => { history.length = 0; $("#msgs").innerHTML = ""; };
  $("#splitter").onmousedown = e => {
    e.preventDefault();
    const mv = ev => { $("#chat").style.width = Math.max(260, Math.min(800, window.innerWidth - ev.clientX)) + "px"; };
    const up = () => { removeEventListener("mousemove", mv); removeEventListener("mouseup", up); };
    addEventListener("mousemove", mv); addEventListener("mouseup", up);
  };
  $("#llm-undo").onclick = async () => {
    const l = await call("undo");
    addMsg("bot", l == null ? "되돌릴 내용이 없습니다." : `↶ 되돌렸습니다: ${esc(l)}`); await reload();
  };
  $("#version").textContent = await call("version");
  document.title = "My Scheduler " + $("#version").textContent;
  await reload();
}
if (window.pywebview) window.addEventListener("pywebviewready", init);
else window.addEventListener("DOMContentLoaded", () => setTimeout(() => window.pywebview ? null : init(), 100));
