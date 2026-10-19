"use strict";
const STATUS = {todo:"할 일", in_progress:"진행 중", in_review:"리뷰", blocked:"막힘", done:"완료"};
const PRIORITY = ["highest","high","medium","low","lowest"];
const TYPE_LABEL = {project:"과제", item:"아이템", subitem:"서브"};
const CHILD = {project:"item", item:"subitem"};
const BAR_LABEL_MIN = 90;
const DAY = 26, NAME_W = 280;

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
let _st; function setStatus(msg, err) { const s = $("#status"); s.textContent = msg; s.className = err ? "err" : ""; s.title = msg; clearTimeout(_st); _st = setTimeout(() => s.textContent = "", 5000); }

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
const badge = st => `<span class="chip" style="--c:var(--${st})">${STATUS[st] || st}</span>`;
const todayISO = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`; };
const mmdd = s => s ? s.slice(5).replace("-", "/") : "";

function render() {
  document.querySelectorAll("#tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
  const v = $("#view");
  if (tab === "gantt") v.innerHTML = renderSummary() + renderGantt();
  else if (tab === "list") v.innerHTML = renderList();
  else v.innerHTML = renderText();
  v.querySelectorAll("[data-key]").forEach(el => {
    el.onclick = () => select(el.dataset.key);
    el.classList.toggle("sel", el.dataset.key === selected);
  });
  const tg = $("#sum-toggle");
  if (tg) tg.onclick = () => { try { localStorage.setItem("sumCollapsed", sumCollapsed() ? "0" : "1"); } catch (e) {} render(); };
  renderDetail();
}

// Today-first summary above the gantt: counts + what is late / due within a week.
const SUM_MAX = 5;
function sumCollapsed() { try { return localStorage.getItem("sumCollapsed") === "1"; } catch (e) { return false; } }
function renderSummary() {
  const t = todayISO(), work = flatten(tree).filter(r => r.type !== "project");
  if (!work.length) return "";
  const open = work.filter(r => r.status !== "done");
  const late = open.filter(r => r.due_date && r.due_date < t);
  const soon = open.filter(r => r.due_date && r.due_date >= t && diffDays(t, r.due_date) <= 7);
  const byDue = (a, b) => a.due_date.localeCompare(b.due_date);
  const row = r => `<div class="ag${r.due_date < t ? " late" : ""}" data-key="${r.key}"><span class="d">${mmdd(r.due_date)}</span><span class="ti">${esc(r.title)}</span>${badge(r.status)}<span class="who muted">${esc(r.assignee)}</span></div>`;
  const group = (title, rs) => {
    if (!rs.length) return "";
    const sorted = rs.slice().sort(byDue);
    return `<h4>${title}</h4>${sorted.slice(0, SUM_MAX).map(row).join("")}${sorted.length > SUM_MAX ? `<div class="more muted">외 ${sorted.length - SUM_MAX}개</div>` : ""}`;
  };
  const card = (n, label, cls = "") => `<div class="card ${cls}"><b>${n}</b><span>${label}</span></div>`;
  const body = sumCollapsed() ? "" : `<div class="strip">${card(late.length, "지연", late.length ? "warn" : "")}${card(soon.length, "이번 주 마감")}${card(work.filter(r => r.status === "in_progress").length, "진행 중")}${card(`${work.length - open.length}/${work.length}`, "완료")}</div>
    <div class="agenda">${group("지연", late) + group("이번 주", soon) || `<div class="muted ag-empty">지연되었거나 이번 주 마감인 일정이 없어요.</div>`}</div>`;
  return `<div class="sumwrap"><div class="sum-head"><b>오늘</b><span class="muted">${t.slice(5).replace("-", "월 ")}일</span><button class="ghost" id="sum-toggle">${sumCollapsed() ? "펼치기" : "접기"}</button></div>${body}</div>`;
}

function renderGantt() {
  const rows = flatten(tree);
  if (!rows.length) return `<div class="empty">아직 일정이 없어요.<br>오른쪽 어시스턴트에게 말하거나 “＋ 과제”를 눌러 시작하세요.</div>`;
  const today = todayISO();
  const spans = rows.map(r => span(r));
  const all = spans.filter(Boolean).flat().concat(today).sort();
  const start = iso(new Date(parse(all[0]).getTime() - 7 * 864e5));
  const end = iso(new Date(parse(all[all.length - 1]).getTime() + 21 * 864e5));
  const days = diffDays(start, end) + 1, W = days * DAY;
  // weekend shading: one repeating 7-day gradient shared by all rows
  const sw = parse(start).getUTCDay(), stops = [];
  for (let i = 0; i < 7; i++) {
    const wk = [0, 6].includes((sw + i) % 7), c = wk ? "var(--weekend)" : "transparent";
    stops.push(`${c} ${i * DAY}px ${(i + 1) * DAY}px`);
  }
  const wk = `linear-gradient(90deg,${stops.join(",")})`;
  let head = "";
  for (let i = 0; i < days; i++) {
    const d = new Date(parse(start).getTime() + i * 864e5);
    // the first label is skipped when the next month starts within 4 days, or the two labels overlap
    const nearNext = i === 0 && [1, 2, 3, 4].some(k => new Date(d.getTime() + k * 864e5).getUTCDate() === 1);
    if (d.getUTCDate() === 1 || (i === 0 && !nearNext)) head += `<div class="g-month" style="left:${i*DAY}px">${d.getUTCFullYear()}년 ${d.getUTCMonth()+1}월</div>`;
    if (d.getUTCDay() === 1) head += `<div class="g-wk" style="left:${i*DAY}px">${d.getUTCDate()}</div>`;
  }
  const todayX = diffDays(start, today) * DAY + DAY / 2;
  let h = `<div class="gantt" style="grid-template-columns:${NAME_W}px ${W}px;--wk:${wk};--wkw:${7*DAY}px">`;
  h += `<div class="g-name g-head">이름</div><div class="g-track g-head">${head}<div class="g-today" style="left:${todayX}px"><i class="g-today-h" style="bottom:-5px"></i></div></div>`;
  rows.forEach((r, i) => {
    const sp = spans[i];
    h += `<div class="g-name type-${r.type}" data-key="${r.key}" style="padding-left:${14 + r.depth*18}px" title="${esc(r.title)}"><span class="key">${r.key}</span><span class="g-title">${esc(r.title)}</span>${r.type === "project" ? "" : `<i class="sdot" style="--c:var(--${r.status})" title="${STATUS[r.status]}"></i>`}</div>`;
    h += `<div class="g-track"><div class="g-today" style="left:${todayX}px"></div>`;
    if (sp) {
      const x = diffDays(start, sp[0]) * DAY + 1, w = Math.max(DAY - 2, (diffDays(sp[0], sp[1]) + 1) * DAY - 2);
      h += `<div class="g-bar st-${r.status}${r.type === "project" ? " proj" : ""}" data-key="${r.key}" style="left:${x}px;width:${w}px" title="${esc(r.title)}  ${sp[0]} ~ ${sp[1]}"><div class="prog" style="width:${r.progress}%"></div>${r.type === "project" || w < BAR_LABEL_MIN ? "" : `<span>${esc(r.title)}</span>`}</div>`;
      if (r.type !== "project" && w < BAR_LABEL_MIN) h += `<div class="g-out" data-key="${r.key}" style="left:${x + w + 6}px">${esc(r.title)}</div>`;
    }
    h += `</div>`;
  });
  return h + `</div>`;
}

function renderList() {
  const rows = flatten(tree);
  if (!rows.length) return `<div class="empty">아직 일정이 없어요.</div>`;
  const t = todayISO();
  let h = `<table><tr><th>제목</th><th>상태</th><th>담당</th><th>마감</th><th>진행</th></tr>`;
  for (const r of rows) {
    const late = r.due_date && r.due_date < t && r.status !== "done";
    h += `<tr class="row type-${r.type}" data-key="${r.key}"><td class="t" style="padding-left:${14 + r.depth*20}px"><span class="key">${r.key}</span>${esc(r.title)}</td><td>${badge(r.status)}</td><td class="muted">${esc(r.assignee)}</td><td class="${late ? "overdue" : "muted"}">${mmdd(r.due_date)}</td><td class="muted">${r.progress ? r.progress + "%" : ""}</td></tr>`;
  }
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

// Anchor the popover just below the clicked row/bar (above it if there is no room), never on top of it.
function placeDetail(d) {
  const wrap = $("#view-wrap"), el = document.querySelector(`#view .g-bar[data-key="${selected}"]`) || document.querySelector(`#view [data-key="${selected}"]`);
  d.style.top = d.style.left = d.style.right = d.style.bottom = "";
  if (!el) { d.style.top = "14px"; d.style.right = "18px"; return; }
  const w = wrap.getBoundingClientRect(), r = el.getBoundingClientRect(), W = d.offsetWidth, H = d.offsetHeight;
  const cx = Math.max(r.left, w.left) + (Math.min(r.right, w.right) - Math.max(r.left, w.left)) / 2;
  d.style.left = Math.max(10, Math.min(cx - w.left - W / 2, w.width - W - 10)) + "px";
  const below = r.bottom - w.top + 8, above = r.top - w.top - H - 8;
  if (below + H <= w.height - 8) d.style.top = below + "px";
  else if (above >= 8) d.style.top = above + "px";
  else {  // no room above/below: sit beside the bar instead of covering it
    const right = r.right - w.left + 10, left = r.left - w.left - W - 10;
    d.style.left = Math.max(10, right + W <= w.width - 10 ? right : left) + "px";
    d.style.top = Math.max(8, Math.min(r.top - w.top, w.height - H - 8)) + "px";
  }
}

function renderDetail() {
  const d = $("#detail"), n = selected && find(selected);
  if (!n) { d.hidden = true; return; }
  d.hidden = false;
  const inp = (f, t = "text", extra = "") => `<input data-f="${f}" type="${t}" value="${esc(n[f] ?? "")}" ${extra}>`;
  const sel = (f, opts) => `<select data-f="${f}">${opts.map(([v, l]) => `<option value="${v}"${n[f] === v ? " selected" : ""}>${l}</option>`).join("")}</select>`;
  d.innerHTML = `<div class="top"><span class="key">${n.key}</span><span class="muted">${TYPE_LABEL[n.type]}</span><button class="x" id="d-close" title="닫기">✕</button></div>
    <input class="title" data-f="title" value="${esc(n.title)}">
    <div class="grid">
      <label>상태</label>${sel("status", Object.entries(STATUS))}
      <label>담당자</label>${inp("assignee")}
      <label>마감일</label>${inp("due_date", "date")}
      <label>진행률 <span id="pv">${n.progress}%</span></label><input data-f="progress" type="range" min="0" max="100" step="5" value="${n.progress}">
    </div>
    <textarea data-f="description" placeholder="설명  ([[P1-2]]로 다른 항목 연결)">${esc(n.description)}</textarea>
    <details><summary>더 보기</summary><div class="grid">
      <label>시작일</label>${inp("start_date", "date")}
      <label>우선순위</label>${sel("priority", PRIORITY.map(p => [p, p]))}
      <label>보고자</label>${inp("reporter")}
      <label>라벨</label>${inp("labels", "text", 'placeholder="쉼표로 구분"')}
      <label>예상 시간(h)</label>${inp("estimate_h", "number")}
    </div><div class="muted" style="font-size:11px">생성 ${n.created_at} · 수정 ${n.updated_at}</div></details>
    <div class="links" id="d-links"></div>
    <div class="actions">${CHILD[n.type] ? `<button id="d-add">＋ ${TYPE_LABEL[CHILD[n.type]]}</button>` : ""}<button id="d-del" class="danger">삭제</button></div>`;
  d.querySelectorAll("[data-f]").forEach(el => {
    if (el.type === "range") el.oninput = () => $("#pv").textContent = el.value + "%";
    el.onchange = async () => { await call("update", n.key, {[el.dataset.f]: el.value}); await reload(); };
  });
  $("#d-close").onclick = () => { selected = null; render(); };
  call("get_item", n.key).then(g => {
    const el = $("#d-links"); if (!el || selected !== n.key || !(g.links.length || g.backlinks.length)) return;
    const a = ks => ks.map(k => `<a data-go="${k}">${k}</a>`).join("");
    el.innerHTML = (g.links.length ? `연결 ${a(g.links)} ` : "") + (g.backlinks.length ? `· 참조됨 ${a(g.backlinks)}` : "");
    el.querySelectorAll("[data-go]").forEach(x => x.onclick = () => select(x.dataset.go));
  }).catch(() => {});
  $("#d-del").onclick = async () => {
    if (!confirm(`${n.key} 및 하위 항목을 삭제할까요?`)) return;
    await call("delete", n.key); selected = null; await reload();
  };
  placeDetail(d);
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
  inp.value = ""; $("#llm-send").disabled = true; inp.style.height = "";
  addMsg("user", esc(text));
  const pend = addMsg("pending", "생각하는 중…");
  try {
    const r = await call("chat", text, history.slice());
    history.push({role: "user", content: text}, {role: "assistant", content: r.answer});
    let h = linkKeys(r.answer || "(응답 없음)");
    if (r.results.length) h += `<div class="ops">${r.results.map(x => "✓ " + linkKeys(x)).join("<br>")}</div>`;
    if (r.steps.length) h += `<details><summary>조회 ${r.steps.length}회</summary>${r.steps.map(s => esc(s.tool + " " + JSON.stringify(s.args))).join("<br>")}</details>`;
    pend.remove(); addMsg("bot", h);
    if (r.results.length) await reload();
  } catch (e) { pend.remove(); addMsg("bot err", esc(e.message)); }
  $("#llm-send").disabled = false; inp.focus();
}

function fmtDiag(d) {
  const err = v => v && v.error, L = [];
  const row = (k, v) => L.push(k.padEnd(14) + v);
  row("서버", d.base_url + (d.ollama ? `  (Ollama ${d.version})` : "  (Ollama API 없음 - 일반 OpenAI 호환 서버)"));
  row("모델 설정값", d.model || "(비어 있음)");
  row("앱이 보내는 값", JSON.stringify(d.request_params) + "  <- 요청마다 모델 기본값을 덮어씀");
  if (d.model_info) {
    if (err(d.model_info)) row("모델 조회", "실패 " + d.model_info.error);
    else {
      const m = d.model_info;
      row("모델 기본값", Object.entries(m.model_defaults).map(([k, v]) => k + "=" + v).join("  ") || "(없음)");
      row("최대 컨텍스트", Object.values(m.context_max).join(", ") || "?");
      row("기반 모델", m.parent || "-");
      row("기능", (m.capabilities || []).join(", "));
      row("시스템프롬프트", m.has_system_prompt ? "있음" : "없음");
    }
  }
  const list = (k, v, f) => err(v) ? row(k, "실패 " + v.error) : row(k, v.length ? "" : "(없음)") || v.forEach(x => L.push("  - " + f(x)));
  if (d.loaded) list("메모리 로드됨", d.loaded, x => `${x.name}  VRAM ${x.vram_gb}/${x.size_gb}GB`);
  if (d.installed) list("설치됨", d.installed, x => `${x.name}  ${x.params} ${x.quant} ${x.size_gb}GB`);
  if (d.models) list("서버 모델", d.models, x => x);
  const t = d.test;
  row("테스트 호출", err(t) ? "실패 " + t.error : `${t.seconds}초, JSON 형식 ${t.json_ok ? "OK" : "실패"}`);
  if (t && t.reply) L.push("  응답: " + t.reply.replace(/\s+/g, " "));
  return L.join("\n");
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
  document.querySelectorAll("#tabs button").forEach(b => b.onclick = () => { tab = b.dataset.tab; render(); });
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
  $("#s-diag").onclick = async () => {
    const out = $("#s-diag-out"); out.hidden = false; out.textContent = "진단 중... (모델 호출 포함)";
    await call("save_settings", readSettings());
    try { out.textContent = fmtDiag(await call("diagnose_llm")); } catch (e) { out.textContent = "실패: " + e.message; }
  };
  $("#llm-send").onclick = sendLLM;
  $("#llm-input").oninput = e => { const t = e.target; t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 160) + "px"; };
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
