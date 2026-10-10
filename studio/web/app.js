/* Film Studio — client. Vanilla JS, no build step. */
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmtDur = s => { if (s == null) return "—"; s = Math.round(s); return s >= 60 ? `${Math.floor(s/60)} min ${s%60} s` : `${s} s`; };
const fmtAgo = t => { if (!t) return ""; const d = (Date.now()/1000 - t); if (d < 60) return "just now"; if (d < 3600) return `${Math.floor(d/60)} min ago`; if (d < 86400) return `${Math.floor(d/3600)} h ago`; return new Date(t*1000).toLocaleDateString("en-GB"); };
const fmtSize = b => b > 1e9 ? (b/1e9).toFixed(2)+" GB" : (b/1e6).toFixed(1)+" MB";
const KIND_LABEL = {motion:"Motion design", short:"Short", aesthetic:"Aesthetic", film:"Film", episode:"Episode"};
const KIND_DESC = {motion:"graphic animation, controlled motion, 6–90 s", short:"9:16, hook, captions, 15–60 s", aesthetic:"mood piece under music, long takes", film:"drama, 2–10 min", episode:"episode from a series bible"};
const STATUS = {queued:["queued","chip"], running:["running","chip accent"], done:["done","chip good"], error:["error","chip bad"], stopped:["stopped","chip warn"]};

let state = null, view = "studio", modalJob = null, pollTimer = null;
const form = {request:"", kind:"short", duration:0, format:"", quality:"", language:"ru", name:"", series:"", music:"auto", captions:null, notes:"", advanced:false, loop:false};

async function api(path, opts = {}) {
  const r = await fetch(path, Object.assign({headers: opts.body && !(opts.body instanceof FormData) ? {"Content-Type":"application/json"} : {}}, opts));
  let data = null; try { data = await r.json(); } catch (e) {}
  if (!r.ok) throw new Error((data && data.error) || `HTTP ${r.status}`);
  return data;
}
function toast(msg, bad = false) {
  const t = document.createElement("div"); t.className = "toast" + (bad ? " bad" : ""); t.textContent = msg;
  document.body.appendChild(t); setTimeout(() => t.remove(), bad ? 6000 : 3500);
}
async function refresh(full = false) {
  try { state = await api("/api/state"); } catch (e) { toast("No connection to the studio server: " + e.message, true); return; }
  render(!full);
}
function isInteracting() {
  const a = document.activeElement;
  return !!document.querySelector(".sel.open") || (a && /^(INPUT|TEXTAREA)$/.test(a.tagName) && $("#main").contains(a));
}
function schedule() {
  clearTimeout(pollTimer);
  const active = state && state.jobs.some(j => j.status === "running");
  pollTimer = setTimeout(refresh, active ? 2500 : 8000);
}

/* ---------- skeleton ---------- */
function render(partial = false) {
  if (!state) return;
  if (partial && view === "studio" && $("#panel-jobs")) {      // polling: refresh only the live panels, leave the form alone
    $("#panel-jobs").innerHTML = jobsPanel(); $("#panel-stats").innerHTML = statsPanel(); $("#panel-films").innerHTML = recentFilms();
    bind($("#panel-jobs")); bind($("#panel-films"));
    if (modalJob) refreshModalJob();
    schedule(); return;
  }
  if (partial && isInteracting()) { if (modalJob) refreshModalJob(); schedule(); return; }
  document.querySelectorAll(".nav").forEach(n => n.classList.toggle("active", n.dataset.view === view));
  const running = state.jobs.filter(j => j.status === "running").length;
  const b = $("#badge-jobs"); b.hidden = !running; b.textContent = running;
  const c = state.config;
  $("#foot").innerHTML = `<div><span class="dot ${c.has_runpod ? "on" : "off"}"></span>RunPod ${c.has_runpod ? "configured" : "not configured"}</div>
    <div><span class="dot ${c.llm_effective === "anthropic" ? "on" : ""}"></span>LLM: ${esc(c.llm_model)}</div>
    <div><span class="dot ${c.ffmpeg ? "on" : "off"}"></span>ffmpeg ${c.ffmpeg ? "yes" : "no"}</div>`;
  const views = {studio: viewStudio, jobs: viewJobs, plans: viewPlans, films: viewFilms, series: viewSeries, assets: viewAssets, settings: viewSettings};
  const main = $("#main");
  const scroll = main.scrollTop;
  main.innerHTML = views[view]();
  bind(main);
  main.scrollTop = scroll;
  if (modalJob) refreshModalJob();
  schedule();
}
document.querySelectorAll(".nav").forEach(n => n.onclick = () => { view = n.dataset.view; render(); });
function jobsPanel() {
  const jobs = state.jobs.filter(j => j.status === "running" || (Date.now()/1000 - (j.finished || 0)) < 3600).slice(0, 5);
  return `<div class="row between"><h3 style="margin:0">Jobs</h3><a href="#" data-view-link="jobs" class="small">all →</a></div>
    ${jobs.length ? `<div class="grid" style="margin-top:10px">${jobs.map(jobCard).join("")}</div>` : `<div class="empty" style="margin-top:10px">Nothing is running right now</div>`}`;
}
function statsPanel() {
  return `<div class="row" style="justify-content:space-around">
    <div class="stat"><b>${state.plans.length}</b><span>plans</span></div><div class="stat"><b>${state.films.length}</b><span>films</span></div>
    <div class="stat"><b>${state.series.length}</b><span>series</span></div><div class="stat"><b>${(state.library.music||[]).length + (state.library.sfx||[]).length}</b><span>sounds</span></div></div>`;
}
function recentFilms() {
  const films = state.films.slice(0, 3);
  return films.length ? `<h2>Recent films</h2><div class="grid auto">${films.map(f => filmCard(f, true)).join("")}</div>` : "";
}

/* ---------- custom controls ---------- */
function selectHtml(id, options, value, opts = {}) {
  const cur = options.find(o => String(o.value) === String(value)) || options[0];
  return `<div class="sel" data-sel="${esc(id)}" data-value="${esc(cur.value)}">
    <button type="button" class="sel-btn"><span class="sel-label">${esc(cur.label)}</span><i class="sel-caret"></i></button>
    <div class="sel-menu">${options.map(o => `<div class="sel-opt ${String(o.value) === String(cur.value) ? "active" : ""}" data-value="${esc(o.value)}"><span>${esc(o.label)}</span>${o.hint ? `<small>${esc(o.hint)}</small>` : ""}</div>`).join("")}</div></div>`;
}
function selValue(id, root = document) { const el = root.querySelector(`[data-sel="${id}"]`); return el ? el.dataset.value : ""; }
function segHtml(id, options, value) {
  return `<div class="seg" data-seg="${esc(id)}" data-value="${esc(value)}">${options.map(o => `<button type="button" class="${String(o.value) === String(value) ? "active" : ""}" data-value="${esc(o.value)}">${o.icon ? `<em>${o.icon}</em>` : ""}${esc(o.label)}</button>`).join("")}</div>`;
}
function segValue(id, root = document) { const el = root.querySelector(`[data-seg="${id}"]`); return el ? el.dataset.value : ""; }
function toggleHtml(id, on, label) { return `<label class="toggle"><input type="checkbox" id="${esc(id)}" ${on ? "checked" : ""}><i></i><span>${esc(label)}</span></label>`; }
document.addEventListener("click", e => {
  const opt = e.target.closest(".sel-opt");
  if (opt) {
    const sel = opt.closest(".sel"); sel.dataset.value = opt.dataset.value;
    sel.querySelector(".sel-label").textContent = opt.querySelector("span").textContent;
    sel.querySelectorAll(".sel-opt").forEach(o => o.classList.toggle("active", o === opt));
    sel.classList.remove("open"); sel.dispatchEvent(new CustomEvent("change", {bubbles: true})); return;
  }
  const btn = e.target.closest(".sel-btn");
  document.querySelectorAll(".sel.open").forEach(x => { if (!btn || x !== btn.closest(".sel")) x.classList.remove("open"); });
  if (btn) btn.closest(".sel").classList.toggle("open");
  const sb = e.target.closest(".seg > button");
  if (sb) {
    const seg = sb.closest(".seg"); seg.dataset.value = sb.dataset.value;
    seg.querySelectorAll("button").forEach(b => b.classList.toggle("active", b === sb));
    seg.dispatchEvent(new CustomEvent("change", {bubbles: true}));
  }
});

/* ---------- Studio (home) ---------- */
const DURATIONS = {motion: [6, 15, 30, 60], short: [15, 30, 45, 60], aesthetic: [30, 45, 60, 90], film: [120, 180, 300, 480], episode: [90, 120, 180, 300]};
const DUR_DEFAULT = {motion: 15, short: 45, aesthetic: 45, film: 180, episode: 120};
const KIND_ICON = {motion: "◈", short: "📱", aesthetic: "🌙", film: "🎬", episode: "📺"};
function durLabel(s) { return s < 120 ? `${s} s` : `${Math.round(s / 60)} min`; }
function estimate() {
  const secs = +form.duration || DUR_DEFAULT[form.kind];
  const [lo, hi] = ({motion: [3, 8], short: [3, 8], aesthetic: [5, 10], film: [4, 10], episode: [4, 10]})[form.kind];
  const shots = Math.max(1, Math.round(secs / ((lo + hi) / 2)));
  const high = (form.quality || state.config.quality) === "high";
  const minutes = shots * (high ? 3.2 : 1.3) + 6;
  return `≈ ${shots} shots · ~${Math.round(minutes)} min render · ≈ $${(minutes / 60 * state.config.gpu_price).toFixed(2)}`;
}
function viewStudio() {
  if (!form.duration) form.duration = DUR_DEFAULT[form.kind];
  const presets = DURATIONS[form.kind];
  const custom = !presets.includes(+form.duration);
  const musicOpts = [{value: "auto", label: "From the library"}, {value: "none", label: "No music"}, ...(state.library.music || []).map(m => ({value: m.file, label: m.file.split("/").pop()}))];
  return `
  <h1>What are we shooting?</h1>
  <p class="sub">Describe the idea in your own words. The studio does the rest: script, prompts, rendering, editing.</p>
  <div class="hero">
    <div class="card compose">
      <textarea id="f-request" placeholder="For example: an aesthetic short about a rainy evening in Tokyo — a girl with a red umbrella walks down a neon street, lo-fi mood">${esc(form.request)}</textarea>
      ${form.kind === "motion" ? `<p class="muted small">Describe: objects → 2D/3D style and materials → palette → starting layout → movement and acceleration → final layout. Example: three coral discs slide from the left, decelerate and settle into a centered stack on an ivory background; static camera, soft clicks. Exact text and logos need separate compositing.</p>` : ""}
      ${segHtml("kind", Object.keys(KIND_LABEL).map(k => ({value: k, label: KIND_LABEL[k], icon: KIND_ICON[k]})), form.kind)}
      <label><span>Creative direction · what must stay exact</span><textarea id="f-notes" placeholder="Visual style and references in words; subject appearance; must-have details; unwanted elements; camera; ending or loop. Example: natural overcast light, muted colors, locked camera, no neon or dialogue.">${esc(form.notes)}</textarea></label>
      <div class="row dur">
        <span class="muted small">Duration</span>
        ${segHtml("duration", [...presets.map(d => ({value: d, label: durLabel(d)})), {value: "custom", label: "custom"}], custom ? "custom" : form.duration)}
        <input id="f-duration" class="num" type="number" min="6" max="900" value="${esc(form.duration)}" ${custom ? "" : "hidden"}>
        <span class="muted small right" id="estimate">${estimate()}</span>
      </div>
      <div class="row actions">
        <button class="primary big" id="btn-make">🎬 Shoot</button>
        <button class="ghost" id="btn-plan">Script only</button>
        <button class="link right" id="btn-adv">${form.advanced ? "Hide settings ▴" : "More settings ▾"}</button>
      </div>
      <div class="advanced" ${form.advanced ? "" : "hidden"}>
        <div class="cols">
          <div class="field"><span>Format</span>${selectHtml("format", [{value: "", label: "By preset"}, ...state.config.formats.map(f => ({value: f, label: f}))], form.format)}</div>
          <div class="field"><span>Quality</span>${selectHtml("quality", [{value: "", label: `Default (${state.config.quality})`}, {value: "high", label: "High", hint: "DFR 1080p, 96 GB GPU"}, {value: "fast", label: "Fast", hint: "720p, faster and cheaper"}], form.quality)}</div>
          <div class="field"><span>Dialogue language</span>${selectHtml("language", [["ru", "Russian"], ["en", "English"], ["es", "Español"], ["fr", "Français"], ["de", "Deutsch"], ["ja", "日本語"], ["it", "Italiano"]].map(([v, l]) => ({value: v, label: l})), form.language)}</div>
          <div class="field"><span>Music</span>${selectHtml("music", musicOpts, form.music)}</div>
          <div class="field"><span>Captions</span>${selectHtml("captions", [{value: "", label: "By preset"}, {value: "1", label: "On"}, {value: "0", label: "Off"}], form.captions === null ? "" : form.captions ? "1" : "0")}</div>
          <div class="field"><span>Series</span>${selectHtml("series", [{value: "", label: "—"}, ...state.series.map(x => ({value: x.slug, label: x.title}))], form.series)}</div>
          <label><span>File name</span><input id="f-name" placeholder="auto" value="${esc(form.name)}"></label>
        </div>
        <div class="row">${toggleHtml("f-loop", form.loop, "Seamless loop: the end flows into the beginning")}</div>
      </div>
    </div>
    <div class="grid" style="align-content:start">
      <div class="card" id="panel-jobs">${jobsPanel()}</div>
      <div class="card" id="panel-stats">${statsPanel()}</div>
    </div>
  </div>
  <div id="panel-films">${recentFilms()}</div>`;
}
function readForm() {
  const q = s => $(s);
  if (!q("#f-request")) return;
  form.request = q("#f-request").value;
  const seg = segValue("duration");
  form.duration = seg === "custom" ? (+q("#f-duration").value || form.duration) : +seg;
  form.format = selValue("format"); form.quality = selValue("quality"); form.language = selValue("language") || "ru";
  form.music = selValue("music") || "auto"; form.series = selValue("series");
  const c = selValue("captions"); form.captions = c === "" ? null : c === "1";
  form.name = q("#f-name").value; form.notes = q("#f-notes").value;
  form.loop = !!(q("#f-loop") && q("#f-loop").checked);
}
async function submitPlan(renderToo) {
  readForm();
  if (!form.request.trim()) { toast("Describe what we are shooting", true); $("#f-request").focus(); return; }
  if (renderToo && !state.config.has_runpod) { toast("RunPod not configured — fill in film_config.json", true); return; }
  const body = Object.assign({}, form, {render: renderToo, duration: form.duration ? +form.duration : null});
  if (form.series) body.kind = "episode";
  try {
    const job = await api("/api/plan", {method: "POST", body: JSON.stringify(body)});
    toast(renderToo ? "Started: script, then render" : "Writing the script");
    form.request = ""; form.notes = ""; form.name = "";
    await refresh(true); openJob(job.id);
  } catch (e) { toast(e.message, true); }
}

/* ---------- jobs ---------- */
function jobCard(j) {
  const [label, cls] = STATUS[j.status] || [j.status, "chip"];
  const pct = j.shots ? Math.round(100 * (j.shot - (j.status === "running" ? 1 : 0)) / j.shots) : null;
  const bar = j.status === "running"
    ? `<div class="progress ${pct == null ? "indeterminate" : ""}"><i style="width:${pct ?? 35}%"></i></div>` : "";
  return `<div class="job card" style="padding:14px 16px;cursor:pointer" data-job="${j.id}">
    <div class="row between"><div class="title">${esc(j.title)}</div><span class="${cls}">${label}</span></div>
    ${bar}
    <div class="row small muted"><span>${esc(j.stage || "")}${j.shots ? ` · shot ${j.shot}/${j.shots}` : ""}</span><span class="right">${j.started ? elapsed(j) : ""}</span></div>
    ${j.error && j.status === "error" ? `<div class="small" style="color:var(--bad)">${esc(j.error)}</div>` : ""}
  </div>`;
}
function elapsed(j) { const end = j.finished || Date.now()/1000; const s = Math.round(end - j.started); return s < 60 ? `${s} s` : `${Math.floor(s/60)} min ${s%60} s`; }
function viewJobs() {
  return `<h1>Jobs</h1><p class="sub">Planning, rendering and re-assembly run as separate processes. Closing this page or the server does not stop them.</p>
  ${state.jobs.length ? `<div class="grid cols2">${state.jobs.map(jobCard).join("")}</div>` : `<div class="empty">No jobs yet</div>`}`;
}
async function openJob(id) {
  modalJob = id;
  openModal(`<div class="row between"><h3 id="mj-title" style="margin:0">Job</h3><div class="row"><button class="small danger" id="mj-stop">Stop</button><button class="small ghost" id="mj-close">Close</button></div></div>
  <div class="row small muted" id="mj-meta" style="margin:8px 0"></div><div class="progress" id="mj-bar" hidden><i></i></div>
  <div class="log" id="mj-log" style="margin-top:10px">…</div><div class="row" id="mj-actions" style="margin-top:12px"></div>`);
  $("#mj-close").onclick = closeModal;
  $("#mj-stop").onclick = async () => { if (confirm("Stop the job? The render will still download the log and delete the Pod.")) { await api(`/api/jobs/${id}/stop`, {method: "POST"}); refresh(); } };
  await refreshModalJob();
}
async function refreshModalJob() {
  if (!modalJob) return;
  let j; try { j = await api(`/api/jobs/${modalJob}?log=16000`); } catch (e) { return; }
  const [label, cls] = STATUS[j.status] || [j.status, "chip"];
  const t = $("#mj-title"); if (!t) return;
  t.innerHTML = `${esc(j.title)} <span class="${cls}" style="margin-left:8px">${label}</span>`;
  $("#mj-meta").innerHTML = `<span>${esc(j.stage || "")}${j.shots ? ` · shot ${j.shot}/${j.shots}` : ""}</span><span class="right">${j.started ? elapsed(j) : ""}</span>`;
  const bar = $("#mj-bar"); bar.hidden = j.status !== "running";
  if (j.shots) { bar.classList.remove("indeterminate"); bar.firstChild.style.width = Math.round(100 * (j.shot - 1) / j.shots) + "%"; } else bar.classList.add("indeterminate");
  const log = $("#mj-log"); const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  log.textContent = j.log || "(log is empty so far)"; if (atBottom) log.scrollTop = log.scrollHeight;
  $("#mj-stop").hidden = j.status !== "running";
  const acts = [];
  if (j.result && /\.json$/.test(j.result)) acts.push(`<button class="small" data-open-plan="${esc(j.result.split("/").pop().replace(/\.json$/, ""))}">Open plan</button>`);
  if (j.result && /\.mp4$/.test(j.result)) acts.push(`<button class="small" data-view-link="films">To films</button>`);
  if (j.status !== "running") acts.push(`<button class="small ghost" data-del-job="${j.id}">Remove from list</button>`);
  $("#mj-actions").innerHTML = acts.join(""); bind($("#mj-actions"));
}

/* ---------- plans ---------- */
function viewPlans() {
  if (!state.plans.length) return `<h1>Plans</h1><div class="empty">No plans yet. Create the first one on the Studio tab.</div>`;
  return `<h1>Plans</h1><p class="sub">A plan is JSON with the story, style and shot prompts. You can edit it by hand before rendering.</p>
  <div class="card" style="padding:0"><table class="table"><thead><tr><th>Title</th><th>Type</th><th>Shots</th><th>Running time</th><th>Quality</th><th>Modified</th><th></th></tr></thead><tbody>
  ${state.plans.map(p => p.broken ? `<tr><td>${esc(p.name)}</td><td colspan="5" style="color:var(--bad)">file unreadable</td><td></td></tr>` :
  `<tr class="clickable" data-open-plan="${esc(p.name)}"><td><b>${esc(p.title)}</b><div class="small muted">${esc(p.name)}.json${p.logline ? " · " + esc(p.logline) : ""}</div></td>
   <td><span class="chip">${KIND_LABEL[p.kind] || p.kind}</span> <span class="chip">${p.format}</span></td><td>${p.shots}</td><td>${fmtDur(p.seconds)}</td><td>${esc(p.quality)}</td><td class="muted small">${fmtAgo(p.modified)}</td>
   <td class="row" style="justify-content:flex-end">${p.has_film ? `<span class="chip good">has film</span>` : ""}<button class="small primary" data-render="${esc(p.name)}">Render</button></td></tr>`).join("")}
  </tbody></table></div>`;
}
async function openPlan(name, tab = "shots") {
  let d; try { d = await api(`/api/plan/${name}`); } catch (e) { toast(e.message, true); return; }
  const errs = d.issues.filter(i => i.level === "error").length, warns = d.issues.length - errs;
  const p = d.plan;
  const body = tab === "json" ? `<textarea class="code" id="plan-raw">${esc(d.raw)}</textarea><div class="row" style="margin-top:10px"><button class="primary" id="plan-save">Save</button><span class="muted small">After saving, the plan is re-checked by the linter</span></div>`
    : tab === "issues" ? (d.problems.length || d.issues.length ? `${d.problems.map(x => `<div class="issue error">⛔ ${esc(x)}</div>`).join("")}${d.issues.map(i => `<div class="issue ${i.level}">${i.level === "error" ? "✖" : "▲"} shot ${esc(i.shot)} · ${esc(i.code)}: ${esc(i.message)}</div>`).join("")}` : `<div class="empty">No issues</div>`)
    : p ? `<div class="kv" style="margin-bottom:14px"><div>Logline</div><div>${esc(p.logline || "—")}</div><div>Synopsis</div><div>${esc(p.synopsis || "—")}</div>
        <div>Style</div><div class="small">${Object.entries(p.style || {}).map(([k, v]) => `<b>${esc(k)}</b>: ${esc(v)}`).join(" · ") || "—"}</div>
        <div>Creative brief</div><div class="small">${Object.entries(p.creative_brief || {}).map(([k, v]) => `<b>${esc(k)}</b>: ${esc(Array.isArray(v) ? v.join("; ") : v || "—")}`).join("<br>") || "—"}</div>
        <div>Director review</div><div class="small">${(p.review_notes || []).map(esc).join("<br>") || "—"}</div>
        <div>Characters</div><div class="small">${(p.characters || []).map(c => `<b>${esc(c.name)}</b> — ${esc(c.descriptor || c.description || "")}`).join("<br>") || "—"}</div>
        <div>Music</div><div>${p.music ? esc(p.music.file || "(no track chosen)") + (p.music.mood ? " · " + esc(p.music.mood) : "") : "—"}</div></div>
        <div class="shots">${p.shots.map((s, i) => `<div class="shot"><div class="head"><span class="id">${esc(s.id)}</span><span class="chip">${s.seconds} s</span>${i ? `<span class="chip ${s.transition === "continue" ? "blue" : s.transition === "dissolve" ? "accent" : ""}">${s.transition || "cut"}</span>` : ""}${s.caption ? `<span class="chip warn">💬 ${esc(s.caption)}</span>` : ""}${(s.sfx || []).map(x => `<span class="chip">🔊 ${esc(x.file.split("/").pop())}</span>`).join("")}${s.beat ? `<span class="muted small">${esc(s.beat)}</span>` : ""}</div><p>${esc(s.prompt)}</p>${Object.keys(s.direction || {}).length ? `<details><summary>Shot direction</summary><div class="small">${Object.entries(s.direction).map(([k,v]) => `<b>${esc(k)}</b>: ${esc(v)}`).join("<br>")}</div></details>` : ""}</div>`).join("")}</div>` : `<div class="issue error">${esc(d.error)}</div>`;
  openModal(`<div class="row between"><div><h3 style="margin:0">${esc(p ? p.title : name)}</h3><div class="small muted mono">${esc(d.path || name)}</div></div>
    <div class="row"><button class="small" data-review="${esc(name)}" title="Director review against your request, continuity checks and prompt fixes">✨ Fix prompts</button><button class="small primary" data-render="${esc(name)}">🎬 Render</button><button class="small danger" data-del-plan="${esc(name)}">Delete</button><button class="small ghost" id="pm-close">Close</button></div></div>
    ${d.summary ? `<pre class="small muted" style="white-space:pre-wrap;margin:10px 0 0">${esc(d.summary)}</pre>` : ""}
    <div class="tabs" style="margin-top:12px">${[["shots","Shots"],["issues",`Check ${errs ? `<span class="chip bad">${errs}</span>` : ""} ${warns ? `<span class="chip warn">${warns}</span>` : ""}`],["json","JSON"]].map(([k, l]) => `<div class="tab ${tab === k ? "active" : ""}" data-plan-tab="${k}" data-plan-name="${esc(name)}">${l}</div>`).join("")}</div>
    ${body}`);
  $("#pm-close").onclick = closeModal;
  bind($("#modal"));
  const save = $("#plan-save");
  if (save) save.onclick = async () => { try { await api(`/api/plan/${name}`, {method: "PUT", body: $("#plan-raw").value}); toast("Plan saved"); await refresh(); openPlan(name, "issues"); } catch (e) { toast(e.message, true); } };
}

/* ---------- films ---------- */
function filmCard(f, compact = false) {
  const vertical = f.resolution && (() => { const [w, h] = f.resolution.split("x").map(Number); return h > w; })();
  const pipes = f.shots.filter(s => s.pipeline === "distilled").length;
  const tl = f.timeline.length ? `<div class="timeline" title="shot timeline">${f.timeline.map(t => { const s = f.shots.find(x => x.id === t.shot) || {}; return `<div class="${s.pipeline === "distilled" ? "distilled" : ""}" style="flex:${Math.max(0.5, t.end - t.start)}" title="shot ${t.shot}: ${t.start}–${t.end} s, ${s.pipeline || ""} ${t.transition}">${t.shot}</div>`; }).join("")}${f.shots_failed.map(id => `<div class="failed" style="flex:1" title="shot ${id} failed">${id}</div>`).join("")}</div>` : "";
  return `<div class="card film ${vertical ? "" : "wide"}">
    <video src="/files/${esc(f.file)}" poster="/api/poster/${esc(f.slug)}" controls preload="none" playsinline></video>
    <div class="grid" style="align-content:start;gap:8px">
      <div class="row between"><h3 style="margin:0">${esc(f.title)}</h3><span class="muted small">${fmtAgo(f.modified)}</span></div>
      <div class="row small"><span class="chip">${esc(f.resolution || "")}</span><span class="chip">${fmtDur(f.seconds)}</span><span class="chip">${esc(f.quality || "")}</span>${f.shots_ok != null ? `<span class="chip ${f.shots_failed.length ? "warn" : "good"}">${f.shots_ok} shots${f.shots_failed.length ? `, ${f.shots_failed.length} failed` : ""}</span>` : ""}${pipes ? `<span class="chip warn" title="some shots were rendered with the fast pipeline after a DFR error">${pipes} distilled</span>` : ""}${f.music ? `<span class="chip">♫ music</span>` : ""}${f.captions ? `<span class="chip">💬 captions</span>` : ""}${f.minutes ? `<span class="chip">${f.minutes} min GPU</span>` : ""}</div>
      ${tl}
      ${compact ? "" : `<div class="row small muted">${fmtSize(f.size)} · <span class="mono">${esc(f.file)}</span></div>`}
      <div class="row"><a class="small" href="/files/${esc(f.file)}" download>⬇ download</a>${f.has_manifest ? `<button class="small" data-recut="${esc(f.slug)}">♫ Re-assemble</button>` : ""}${f.recuts.length ? `<span class="small muted">re-cuts: ${f.recuts.map(r => `<a href="/files/${esc(r)}" target="_blank">${esc(r.split("/").pop())}</a>`).join(", ")}</span>` : ""}${compact ? "" : `<button class="small danger right" data-del-film="${esc(f.slug)}">Delete</button>`}</div>
    </div></div>`;
}
function viewFilms() {
  return `<h1>Films</h1><p class="sub">Finished films with a per-shot report. Re-assembly changes music and captions without a GPU (needs ffmpeg).</p>
  ${state.films.length ? `<div class="grid">${state.films.map(f => filmCard(f)).join("")}</div>` : `<div class="empty">No films yet</div>`}`;
}
function openRecut(slug) {
  openModal(`<h3>Re-assemble “${esc(slug)}»</h3><p class="muted small">The clips are already rendered. Only music, volume and captions change.</p>
  <div class="form"><div class="field"><span>Music</span>${selectHtml("rc-music", [{value: "", label: "As in the plan"}, {value: "none", label: "No music"}, ...(state.library.music || []).map(m => ({value: m.file, label: m.file.split("/").pop()}))], "")}</div>
  <label><span>Music volume (0.1–0.5)</span><input id="rc-vol" type="number" step="0.05" min="0" max="1" placeholder="as in the plan"></label>
  ${toggleHtml("rc-cap", false, "Captions")}
  <div class="row"><button class="primary" id="rc-go">Assemble</button><button class="ghost" id="rc-close">Cancel</button></div></div>`);
  $("#rc-close").onclick = closeModal;
  $("#rc-go").onclick = async () => { try { const j = await api("/api/assemble", {method: "POST", body: JSON.stringify({film: slug, music: selValue("rc-music"), music_volume: $("#rc-vol").value, captions: $("#rc-cap").checked})}); toast("Re-assembly started"); await refresh(true); openJob(j.id); } catch (e) { toast(e.message, true); } };
}

/* ---------- series ---------- */
function viewSeries() {
  return `<h1>Series</h1><p class="sub">The bible defines characters, locations and style; every episode is planned against it so the characters stay consistent.</p>
  <div class="grid cols2">
    <div class="card form"><h3>New series</h3>
      <textarea id="s-desc" placeholder="What the series is about, the characters, tone, episode count…"></textarea>
      <div class="cols"><label><span>Slug</span><input id="s-name" placeholder="auto"></label><label><span>Episodes per season</span><input id="s-eps" type="number" value="6" min="1" max="24"></label><div class="field"><span>Language</span>${selectHtml("s-lang", [["ru", "Russian"], ["en", "English"], ["es", "Español"], ["fr", "Français"], ["de", "Deutsch"], ["ja", "日本語"]].map(([v, l]) => ({value: v, label: l})), "ru")}</div></div>
      <div class="row"><button class="primary" id="s-create">Create bible</button></div></div>
    <div class="grid" style="align-content:start">${state.series.length ? state.series.map(s => `<div class="card" style="cursor:pointer" data-bible="${esc(s.slug)}"><div class="row between"><h3 style="margin:0">${esc(s.title)}</h3><span class="chip">${s.episodes}/${s.planned || "?"} episodes</span></div><div class="small muted" style="margin-top:6px">${esc(s.premise || "")}</div><div class="row small" style="margin-top:8px"><span class="chip">${s.characters} characters</span><span class="mono dim">${esc(s.slug)}</span></div></div>`).join("") : `<div class="empty">No series yet</div>`}</div>
  </div>`;
}
async function openBible(slug) {
  let b; try { b = await api(`/api/series/${slug}`); } catch (e) { toast(e.message, true); return; }
  openModal(`<div class="row between"><h3 style="margin:0">${esc(b.title)} <span class="mono dim small">${esc(slug)}</span></h3><div class="row"><button class="small primary" id="b-episode">📝 New episode</button><button class="small ghost" id="b-close">Close</button></div></div>
  <div class="kv" style="margin-top:12px"><div>Premise</div><div>${esc(b.premise)}</div><div>Tone</div><div>${esc(b.tone)} · ${esc(b.genre || "")}</div><div>Style</div><div class="small">${Object.entries(b.style || {}).map(([k, v]) => `<b>${esc(k)}</b>: ${esc(v)}`).join(" · ")}</div><div>Sound</div><div class="small">${esc(b.sound_signature || "")}</div></div>
  <h3 style="margin-top:16px">Characters</h3>${(b.characters || []).map(c => `<div class="shot"><div class="head"><b>${esc(c.name)}</b><span class="chip accent">${esc(c.descriptor)}</span></div><p>${esc(c.description)} <span class="muted">Voice: ${esc(c.voice)}. Arc: ${esc(c.arc)}</span></p></div>`).join("")}
  <h3 style="margin-top:16px">Season arc</h3><ol class="small">${(b.season_arc || []).map(a => `<li>${esc(a)}</li>`).join("")}</ol>
  <h3>Episodes made</h3>${(b.episodes || []).length ? (b.episodes).map(e => `<div class="small">Ep. ${e.episode}: <b>${esc(e.title)}</b> — ${esc(e.summary || e.logline || "")} <span class="dim">(${esc(e.slug)}.json)</span></div>`).join("") : `<div class="dim small">none yet</div>`}
  <h3 style="margin-top:16px">Continuity notes</h3>${(b.notes || []).map(n => `<div class="small">• ${esc(n)}</div>`).join("")}<div class="row" style="margin-top:8px"><input id="b-note" placeholder="e.g. the hero now has a scar on his left cheek"><button class="small" id="b-add">Add</button></div>`);
  $("#b-close").onclick = closeModal;
  $("#b-episode").onclick = () => { form.series = slug; form.kind = "episode"; closeModal(); view = "studio"; render(); $("#f-request").focus(); };
  $("#b-add").onclick = async () => { const t = $("#b-note").value.trim(); if (!t) return; await api("/api/series/note", {method: "POST", body: JSON.stringify({name: slug, text: t})}); toast("Note added"); openBible(slug); };
}

/* ---------- sound ---------- */
function viewAssets() {
  const lib = state.library;
  const list = (items, kind) => items.length ? `<table class="table"><thead><tr><th>File</th><th>Tags</th><th>Length</th><th></th></tr></thead><tbody>${items.map(e => `<tr><td class="mono">${esc(e.file.split("/").pop())}</td><td class="small muted">${(e.tags || []).join(", ")}${e.mood ? ` · <i>${esc(e.mood)}</i>` : ""}</td><td>${e.seconds ? fmtDur(e.seconds) : "—"}</td><td><audio src="/files/${esc(e.file)}" controls preload="none" style="height:28px;width:220px"></audio></td></tr>`).join("")}</tbody></table>` : `<div class="empty">Empty. Upload files or put them into assets/${kind}/</div>`;
  return `<h1>Sound</h1><p class="sub">Music and effects the planner picks by tags. Tags come from file names and can be edited in assets/index.json.</p>
  <div class="grid cols2">
    <div class="card"><div class="row between"><h3 style="margin:0">Music</h3><label class="upload"><input type="file" id="up-music" accept="audio/*" multiple hidden><span>⬆ Upload</span></label></div>${list(lib.music || [], "music")}</div>
    <div class="card"><div class="row between"><h3 style="margin:0">Effects</h3><label class="upload"><input type="file" id="up-sfx" accept="audio/*" multiple hidden><span>⬆ Upload</span></label></div>${list(lib.sfx || [], "sfx")}</div>
  </div><div class="row" style="margin-top:12px"><button id="reindex">Re-index</button><span class="muted small">after copying files into the folders manually</span></div>`;
}
async function upload(kind, files) {
  for (const f of files) { const fd = new FormData(); fd.append("file", f, f.name); try { await api(`/api/assets/upload?kind=${kind}`, {method: "POST", body: fd}); toast(`Uploaded: ${f.name}`); } catch (e) { toast(e.message, true); } }
  refresh();
}

/* ---------- settings ---------- */
function viewSettings() {
  const c = state.config;
  return `<h1>Settings</h1><p class="sub">Keys and parameters live in <span class="mono">${esc(c.config_path)}</span>. Here: environment check and standing planner preferences.</p>
  <div class="grid cols2">
    <div class="card"><h3>Environment</h3><div class="kv">
      <div>LLM</div><div>${esc(c.llm_effective)} · ${esc(c.llm_model)} ${c.has_anthropic ? `<span class="chip good">Anthropic key present</span>` : `<span class="chip warn">no ANTHROPIC_API_KEY — local Ollama, lower script quality</span>`}</div>
      <div>RunPod</div><div>${c.has_runpod ? `<span class="chip good">configured</span>` : `<span class="chip bad">not configured</span>`} · default quality <b>${esc(c.quality)}</b> · limit ${c.max_hours} h · ~$${c.gpu_price}/h</div>
      <div>GPUs (fast)</div><div class="small">${(c.gpu_types || []).map(esc).join(", ")}</div>
      <div>ffmpeg</div><div>${c.ffmpeg ? `<span class="chip good">yes</span>` : `<span class="chip warn">no — re-assembly unavailable (brew install ffmpeg)</span>`}</div>
      <div>Voice-over</div><div>${c.has_elevenlabs ? `<span class="chip good">ElevenLabs configured</span>` : `<span class="chip">no (narration in the plan stays as text)</span>`}</div>
    </div><div class="row" style="margin-top:12px"><button class="small" id="doctor">Full diagnostics</button></div><pre class="log small" id="doctor-out" hidden></pre></div>
    <div class="card form"><h3>Planner preferences</h3><p class="muted small" style="margin:0">Applied to every plan. For example: “fewer close-ups”, “always end on a wide shot”, “no dissolves”.</p>
      <textarea id="prefs" style="min-height:220px">${esc(state.prefs)}</textarea><div class="row"><button class="primary" id="prefs-save">Save</button></div></div>
  </div>`;
}

/* ---------- shared handlers ---------- */
function bind(root) {
  const kindSeg = root.querySelector('[data-seg="kind"]');
  if (kindSeg) kindSeg.addEventListener("change", () => { readForm(); form.kind = kindSeg.dataset.value; form.duration = DUR_DEFAULT[form.kind]; render(); });
  const durSeg = root.querySelector('[data-seg="duration"]');
  if (durSeg) durSeg.addEventListener("change", () => { const v = durSeg.dataset.value; const inp = root.querySelector("#f-duration"); if (v === "custom") { inp.hidden = false; inp.focus(); } else { inp.hidden = true; inp.value = v; form.duration = +v; } $("#estimate").textContent = estimate(); });
  const durInp = root.querySelector("#f-duration");
  if (durInp) durInp.oninput = () => { form.duration = +durInp.value || form.duration; $("#estimate").textContent = estimate(); };
  const qSel = root.querySelector('[data-sel="quality"]');
  if (qSel) qSel.addEventListener("change", () => { form.quality = qSel.dataset.value; $("#estimate").textContent = estimate(); });
  if (root.querySelector("#btn-adv")) root.querySelector("#btn-adv").onclick = () => { readForm(); form.advanced = !form.advanced; render(); };
  root.querySelectorAll("[data-job]").forEach(el => el.onclick = () => openJob(el.dataset.job));
  root.querySelectorAll("[data-open-plan]").forEach(el => el.onclick = e => { e.stopPropagation(); openPlan(el.dataset.openPlan); });
  root.querySelectorAll("[data-plan-tab]").forEach(el => el.onclick = () => openPlan(el.dataset.planName, el.dataset.planTab));
  root.querySelectorAll("[data-render]").forEach(el => el.onclick = async e => { e.stopPropagation(); if (!confirm("Start the render on RunPod? This costs money.")) return; try { const j = await api("/api/render", {method: "POST", body: JSON.stringify({plan: el.dataset.render})}); toast("Render started"); await refresh(true); openJob(j.id); } catch (err) { toast(err.message, true); } });
  root.querySelectorAll("[data-review]").forEach(el => el.onclick = async () => { try { const j = await api("/api/review", {method: "POST", body: JSON.stringify({plan: el.dataset.review})}); toast("Prompt fixing started"); await refresh(true); openJob(j.id); } catch (err) { toast(err.message, true); } });
  root.querySelectorAll("[data-del-plan]").forEach(el => el.onclick = async () => { if (!confirm(`Delete plan ${el.dataset.delPlan}?`)) return; await api(`/api/plan/${el.dataset.delPlan}`, {method: "DELETE"}); closeModal(); refresh(); });
  root.querySelectorAll("[data-del-film]").forEach(el => el.onclick = async () => { if (!confirm(`Delete film ${el.dataset.delFilm} from disk together with its clips?`)) return; await api(`/api/film/${el.dataset.delFilm}`, {method: "DELETE"}); refresh(); });
  root.querySelectorAll("[data-del-job]").forEach(el => el.onclick = async () => { await api(`/api/jobs/${el.dataset.delJob}`, {method: "DELETE"}); closeModal(); refresh(); });
  root.querySelectorAll("[data-recut]").forEach(el => el.onclick = () => openRecut(el.dataset.recut));
  root.querySelectorAll("[data-bible]").forEach(el => el.onclick = () => openBible(el.dataset.bible));
  root.querySelectorAll("[data-view-link]").forEach(el => el.onclick = e => { e.preventDefault(); closeModal(); view = el.dataset.viewLink; render(); });
  const q = s => root.querySelector(s);
  if (q("#btn-make")) q("#btn-make").onclick = () => submitPlan(true);
  if (q("#btn-plan")) q("#btn-plan").onclick = () => submitPlan(false);
  if (q("#s-create")) q("#s-create").onclick = async () => { try { const j = await api("/api/series", {method: "POST", body: JSON.stringify({description: q("#s-desc").value, name: q("#s-name").value, episodes: q("#s-eps").value, language: selValue("s-lang")})}); toast("Creating the bible"); await refresh(true); openJob(j.id); } catch (e) { toast(e.message, true); } };
  if (q("#up-music")) q("#up-music").onchange = e => upload("music", e.target.files);
  if (q("#up-sfx")) q("#up-sfx").onchange = e => upload("sfx", e.target.files);
  if (q("#reindex")) q("#reindex").onclick = async () => { await api("/api/assets/reindex", {method: "POST"}); toast("Index updated"); refresh(); };
  if (q("#prefs-save")) q("#prefs-save").onclick = async () => { await api("/api/prefs", {method: "PUT", body: JSON.stringify({text: q("#prefs").value})}); toast("Saved"); };
  if (q("#doctor")) q("#doctor").onclick = async () => { const d = await api("/api/doctor"); const o = q("#doctor-out"); o.hidden = false; o.textContent = d.lines.join("\n"); };
  const req = q("#f-request"); if (req) req.oninput = () => { form.request = req.value; };
}
function openModal(html) { $("#modal").innerHTML = html; $("#modal-bg").classList.add("open"); }
function closeModal() { $("#modal-bg").classList.remove("open"); modalJob = null; }
$("#modal-bg").onclick = e => { if (e.target.id === "modal-bg") closeModal(); };
document.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });

refresh();
