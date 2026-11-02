/* CNC Workforce Allocation demo - front end (no external libraries, works offline) */
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const PAGES = {};
const ST = { state: null, page: "home", vid: sessionStorage.getItem("vid") || null, role: sessionStorage.getItem("role") || "Production Manager", worker: sessionStorage.getItem("worker") || "E02", plan: null };

const NAV = [
  ["home", "Home / Guided Demo", ["Production Manager", "Engineer/Supervisor", "HR/Workforce Admin", "ERP Administrator"]],
  ["orders", "Orders and Tasks", ["Production Manager", "Engineer/Supervisor", "ERP Administrator"]],
  ["workforce", "Workforce and Skills", ["Production Manager", "Engineer/Supervisor", "HR/Workforce Admin"]],
  ["plan", "AI Allocation Proposal", ["Production Manager", "Engineer/Supervisor"]],
  ["gantt", "Schedule Chart", ["Production Manager", "Engineer/Supervisor"]],
  ["approval", "Approval and Changes", ["Production Manager"]],
  ["mytasks", "My Tasks", ["Production Manager", "Engineer/Supervisor", "Worker"]],
  ["live", "Live Progress and Alerts", ["Production Manager", "Engineer/Supervisor"]],
  ["reports", "Reports", ["Production Manager", "Engineer/Supervisor"]],
  ["audit", "Audit and Settings", ["Production Manager", "ERP Administrator"]],
  ["about", "How it works / Requirements", ["Production Manager", "Engineer/Supervisor", "HR/Workforce Admin", "ERP Administrator"]],
];

/* ---------- helpers ---------- */
async function api(method, path, body, opts = {}) {
  if (!opts.quiet) busy(opts.msg || "Working...");
  try {
    const r = await fetch(path, { method, headers: { "Content-Type": "application/json", "x-role": ST.role }, body: body ? JSON.stringify(body) : undefined });
    let data = null;
    try { data = await r.json(); } catch (e) { /* not json */ }
    if (!r.ok) {
      const msg = (data && data.error) || `The server answered with an error (${r.status}).`;
      console.error("API error", method, path, r.status, data);
      const err = new Error(msg); err.data = data; err.status = r.status; throw err;
    }
    return data;
  } catch (e) {
    if (!e.status) { console.error(e); e.message = "Could not reach the server. Check your connection and try again. (A free server may take about 30 seconds to wake up.)"; }
    throw e;
  } finally { if (!opts.quiet) busy(false); }
}
const get = (p, o) => api("GET", p, null, { quiet: true, ...o });
const post = (p, b, m) => api("POST", p, b || {}, { msg: m });
function busy(msg) { const b = $("#busy"); if (msg) { $("#busytext").textContent = msg; b.classList.remove("hidden"); } else b.classList.add("hidden"); }
function toast(msg, kind = "info", ms = 4500) { const t = document.createElement("div"); t.className = "toast " + kind; t.textContent = msg; $("#toasts").appendChild(t); setTimeout(() => t.remove(), ms); }
function fail(e) { toast(e.message || String(e), "err", 8000); const p = $("#page"); const box = document.createElement("div"); box.className = "errbox"; box.innerHTML = "<b>Something needs your attention.</b> " + esc(e.message || e); p.prepend(box); window.scrollTo({ top: 0, behavior: "smooth" }); }
async function guard(fn) { try { return await fn(); } catch (e) { fail(e); } }
function chip(kind, text, icon) { return `<span class="chip ${kind}">${icon ? icon + " " : ""}${esc(text)}</span>`; }
const BADGE = { on_time: ["green", "On time", "&#10004;"], at_risk: ["amber", "At risk", "&#9888;"], late: ["red", "Late", "&#10006;"] };
const badge = (s) => { const b = BADGE[s] || ["grey", s, ""]; return chip(b[0], b[1], b[2]); };
const PRIO = { Urgent: ["red", "Urgent"], High: ["amber", "High"], Normal: ["grey", "Normal"] };
const prio = (p) => chip(PRIO[p]?.[0] || "grey", PRIO[p]?.[1] || p);
const lockI = '<span title="Locked: only an explicit unlock can change it">&#128274;</span>';
function fmtDate(iso) { if (!iso) return ""; const d = new Date(iso + "T00:00:00"); return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" }); }
function empty(title, text, btn) { return `<div class="empty"><b>${esc(title)}</b>${esc(text)}${btn ? `<div style="margin-top:12px">${btn}</div>` : ""}</div>`; }
function modal(html) { $("#modalbody").innerHTML = html; $("#modal").classList.remove("hidden"); }
function closeModal() { $("#modal").classList.add("hidden"); }
function ask(title, label, placeholder = "") {
  return new Promise((res) => {
    modal(`<h2>${esc(title)}</h2><label class="f">${esc(label)}<input id="askin" placeholder="${esc(placeholder)}" maxlength="200"></label><p class="muted" id="askerr"></p><button class="primary" id="askok">OK</button> <button id="askno">Cancel</button>`);
    const done = (v) => { closeModal(); res(v); };
    $("#askin").focus();
    $("#askok").onclick = () => { const v = $("#askin").value.trim(); if (!v) { $("#askerr").textContent = "Please type a reason. It is saved in the audit log."; return; } done(v); };
    $("#askno").onclick = () => done(null);
    $("#askin").onkeydown = (e) => { if (e.key === "Enter") $("#askok").click(); };
  });
}
const can = (page) => NAV.find((n) => n[0] === page)[2].includes(ST.role);
const isManager = () => ST.role === "Production Manager";

/* ---------- shell ---------- */
function go(page, arg) { if (!can(page)) { toast(`The ${ST.role} role cannot open that screen in the demo. Switch role at the bottom left.`, "info"); return; } ST.page = page; ST.arg = arg; location.hash = page; render(); $("#side").classList.remove("open"); window.scrollTo(0, 0); }
async function refreshState() { ST.state = await get("/api/state"); $("#bellcount").textContent = ST.state.unread_alerts; $("#bellcount").classList.toggle("zero", !ST.state.unread_alerts); const nowt = new Date().toLocaleString("en-GB", { timeZone: ST.state.timezone, weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }); $("#clock").textContent = nowt + " " + ST.state.timezone; }
function drawNav() {
  $("#nav").innerHTML = NAV.filter((n) => n[2].includes(ST.role)).map((n, i) => `<a data-p="${n[0]}" class="${n[0] === ST.page ? "on" : ""}" tabindex="0"><span class="n">${NAV.indexOf(n) + 1}</span>${esc(n[1])}</a>`).join("");
  document.querySelectorAll("#nav a").forEach((a) => { a.onclick = () => go(a.dataset.p); a.onkeydown = (e) => { if (e.key === "Enter") go(a.dataset.p); }; });
}
async function render() {
  const p = $("#page");
  drawNav(); drawGuide();
  if (!can(ST.page)) ST.page = NAV.find((n) => n[2].includes(ST.role))[0];
  try { await refreshState(); } catch (e) { p.innerHTML = `<div class="errbox">${esc(e.message)}</div>`; return; }
  drawBanner();
  p.innerHTML = '<p class="muted">Loading...</p>';
  try { await PAGES[ST.page](p); } catch (e) { console.error(e); p.innerHTML = `<h1>Something went wrong</h1><div class="errbox">${esc(e.message)}</div>${"<button onclick='render()'>Try again</button>"}`; }
  drawGuide();
}
function drawBanner() {
  const s = ST.state; let h = "";
  if (s.dates_stale) h += `<p class="b" style="background:#fff1d6">The demo dates start on ${esc(s.horizon_text)}, which is in the past. Open Home and press <b>Reset demo data</b> to move the whole demo to the next working day.</p>`;
  if (ST.role !== "Production Manager") h += `<p class="b" style="background:#e8f0ff">You are viewing the demo as <b>${esc(ST.role)}</b>. Some buttons are limited for this role (demo simulation, not real security).</p>`;
  $("#banner").innerHTML = h;
}

/* ---------- demo script panel ---------- */
const SCRIPT = [
  ["Show the orders", "orders", "Open Orders and Tasks. Point out the five sample orders and their task counts.", "\"An order arrives from the ERP. The app has already split each one into the real jobs from the product's routing.\""],
  ["Add an urgent order", "orders", "Press 'Fill the demo example', then Create order.", "\"The manager types a note. The reader picks out titanium and a certified inspector. Anything it does not recognise is shown, never silently applied.\""],
  ["See who qualifies", "orders", "On any task press 'Who can do this?'.", "\"Only people with the right skill, valid certificate, shift and no leave qualify. The others are listed with the reason. Nobody can override this.\""],
  ["Generate the schedule", "plan", "Pick a priority style and press Generate schedule.", "\"The planner assigns a person and a machine to every job and estimates when each order finishes.\""],
  ["Review, edit, lock, approve", "approval", "Edit one assignment with a reason, lock two, then Approve.", "\"The AI suggests, the manager decides. Every change needs a reason and is recorded.\""],
  ["Someone calls in sick", "live", "Choose a person in the simulator and press Simulate.", "\"Only the affected work is replanned. Locked work is never changed silently; if it is affected, we get a clear question.\""],
  ["The impossible case", "live", "Press 'Run the impossible case'.", "\"When no valid plan exists, the app says so and shows why. It never invents a person. Due dates and overtime cannot create a certified worker.\""],
  ["Reports", "reports", "Open Reports.", "\"Utilization, overtime, busiest machine, on-time percentage and planned vs actual.\""],
];
function drawGuide() {
  const g = $("#guide");
  g.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center"><h2 style="margin:0">Demo script</h2><button class="sm" onclick="$('#guide').classList.add('hidden')">Close</button></div><p class="muted">What to click and what to say. Press Go to jump to the screen.</p>` +
    SCRIPT.map((s, i) => `<div class="gs ${ST.page === s[1] ? "cur" : ""}"><b>${i + 1}. ${esc(s[0])}</b><div>${esc(s[2])}</div><div class="say">${esc(s[3])}</div><button class="sm" style="margin-top:6px" onclick="go('${s[1]}')">Go to this screen</button></div>`).join("");
}

/* ---------- HOME ---------- */
PAGES.home = async (p) => {
  const s = ST.state;
  const steps = [
    { t: "Look at the incoming orders", d: "Five sample orders from the simulated ERP. Each is already broken into jobs.", done: s.orders > 0 && s.tasks > 0, btn: "Open orders", page: "orders" },
    { t: "Add an urgent order", d: "Type a note such as 'Needs titanium, certified inspector only'. The app adds those requirements and creates the jobs.", done: false, optional: true, btn: "Add an order", page: "orders", arg: "new" },
    { t: "Generate the AI schedule", d: "One button. The planner picks a person and a machine for every job and says why.", done: !!s.latest_version, btn: "Generate schedule", page: "plan" },
    { t: "Review and approve", d: "Change one assignment (with a reason), lock jobs you do not want touched, then approve.", done: !!s.approved_version, btn: "Review and approve", page: "approval" },
    { t: "Handle a surprise", d: "A worker calls in sick or a machine breaks. Only the affected work is replanned and you see what changed.", done: s.revisions > 0, btn: "Try a surprise", page: "live" },
    { t: "See the results", d: "Utilization, overtime, busiest machine, on-time delivery and planned vs actual.", done: !!s.approved_version, btn: "Open reports", page: "reports" },
  ];
  const next = steps.findIndex((x) => !x.done && !x.optional);
  p.innerHTML = `
  <div class="hero">
    <h1>Plan the factory floor in minutes, not hours</h1>
    <p>An order comes in. The app breaks it into jobs, checks who is allowed to do each one, and proposes who works on what and when. <b>You stay in charge</b>: you review, change, lock and approve.</p>
    <div class="flow"><span class="node">1 Order<small>from the ERP</small></span><span class="arrow">&rarr;</span><span class="node">2 Jobs<small>from the routing</small></span><span class="arrow">&rarr;</span><span class="node">3 Who is allowed<small>skills, certificates, leave</small></span><span class="arrow">&rarr;</span><span class="node">4 AI schedule<small>person + machine + time</small></span><span class="arrow">&rarr;</span><span class="node">5 You approve<small>edit, lock, reject</small></span></div>
    <p style="font-size:15px;color:#b9cdf5">Benefits: less manual planning, no unqualified assignments, early warning for late orders, and a recorded reason for every decision. Demo data only. Nothing here controls a machine.</p>
  </div>
  <div class="card"><h2>Quick start for presenters</h2><p class="help" style="margin-bottom:10px">Want to jump straight to a finished schedule? This creates a plan and approves it as the Production Manager, exactly like steps 3 and 4 below.</p>
    <button class="primary big" id="quick" ${isManager() ? "" : "disabled"}>Prepare a ready schedule for me</button> ${isManager() ? "" : '<span class="muted">Switch to the Production Manager role to use this.</span>'}</div>
  <h2>Guided demo: six steps</h2>
  <div class="steps">${steps.map((x, i) => `<div class="step ${x.done ? "done" : i === next ? "next" : ""}"><div class="num">${x.done ? "&#10004;" : i + 1}</div><div class="t"><b>${esc(x.t)}</b><span>${esc(x.d)}</span></div><button class="${i === next ? "primary" : ""}" data-i="${i}">${esc(x.btn)}</button></div>`).join("")}</div>
  <div class="card" style="margin-top:18px"><h3>Starting point</h3>
    <p>The plan starts on <b>${esc(s.horizon_text)}</b> and covers ${s.horizon_days} days (Monday to Saturday working, Sunday off; a demo assumption you can change in Settings). Dates are always set relative to the day you load the demo.</p>
    <button id="resetbtn">Reset demo data...</button> <button id="exportbtn">Download a backup (JSON)</button></div>`;
  p.querySelectorAll(".step button").forEach((b) => (b.onclick = () => { const x = steps[+b.dataset.i]; go(x.page, x.arg); }));
  $("#quick").onclick = () => guard(async () => {
    const r = await post("/api/plan", {}, "Planning every job... this takes a few seconds");
    if (!r.version_id) { toast(r.message || "No plan could be made. Open the Plan screen for details.", "err"); go("plan"); ST.plan = r; return; }
    await post("/api/approve", { version_id: r.version_id }, "Approving...");
    ST.vid = r.version_id; sessionStorage.setItem("vid", ST.vid);
    toast("Schedule created and approved. Open the Schedule Chart.", "ok"); go("gantt");
  });
  $("#exportbtn").onclick = () => { window.location = "/api/export"; };
  $("#resetbtn").onclick = () => {
    modal(`<h2>Reset demo data?</h2><p>This replaces all current orders, schedules, alerts and the audit log with fresh demo data starting on the next working day. A backup copy is saved on the server first. You can also download your own backup.</p>
    <p><button id="rx">Download backup first</button></p><label class="f">Type RESET to confirm<input id="rc" autocomplete="off"></label><button class="danger" id="rok">Reset demo data</button> <button id="rno">Cancel</button>`);
    $("#rx").onclick = () => { window.location = "/api/export"; };
    $("#rno").onclick = closeModal;
    $("#rok").onclick = () => guard(async () => { if ($("#rc").value.trim() !== "RESET") { toast("Type RESET to confirm.", "err"); return; } await post("/api/reset", { confirm: "RESET" }, "Resetting..."); closeModal(); ST.vid = null; sessionStorage.removeItem("vid"); ST.plan = null; toast("Demo data reset.", "ok"); render(); });
  };
};

/* ---------- ORDERS ---------- */
PAGES.orders = async (p) => {
  const [orders, prods] = await Promise.all([get("/api/orders"), get("/api/products")]);
  const s = ST.state;
  const sel = ST.arg && ST.arg !== "new" ? ST.arg : null;
  p.innerHTML = `<h1>Orders and Tasks</h1><p class="help">Orders arrive from the Simulated ERP. Each order is turned into jobs automatically using the product's routing. Add an order below, then open its jobs to see who can do each one.</p>
  <div class="card"><h2>Incoming orders</h2><div class="tw"><table><thead><tr><th>Order</th><th>Product</th><th>Qty</th><th>Priority</th><th>Due</th><th>Jobs</th><th>Note requirements</th><th></th></tr></thead><tbody>
  ${orders.map((o) => `<tr><td><b>${esc(o.id)}</b></td><td>${esc(o.product_name)}</td><td>${o.quantity}</td><td>${prio(o.priority)}</td><td class="nowrap">${esc(fmtDate(o.due_date))}</td><td>${o.task_count}</td>
  <td>${[...(o.requirements.skills || []), ...(o.requirements.certs || []), ...(o.requirements.notes || [])].map((x) => chip("blue", x)).join(" ") || '<span class="muted">none</span>'}</td>
  <td class="nowrap"><button class="sm" data-open="${esc(o.id)}">Show jobs</button> ${can("orders") && isManager() || ST.role === "ERP Administrator" ? `<button class="sm danger" data-del="${esc(o.id)}">Remove</button>` : ""}</td></tr>`).join("")}
  </tbody></table></div></div>
  <div id="tasks"></div>
  <div class="card" id="newbox"><h2>Add a new order</h2><p class="help" style="margin-bottom:10px">Fill in the form and press Create order. Jobs are generated immediately. The note box is optional and read with a keyword reader.</p>
  <div class="row"><div>
    <label class="f">Product<select id="np">${prods.map((x) => `<option value="${esc(x.id)}">${esc(x.name)}</option>`).join("")}</select></label>
    <label class="f">Quantity (pieces)<input id="nq" type="number" min="1" max="1000" value="10"></label>
    <label class="f">Priority<select id="npr"><option>Urgent</option><option selected>High</option><option>Normal</option></select></label>
    <label class="f">Due date (required)<input id="nd" type="date" min="${esc(s.horizon_start)}"></label>
    <div class="errbox hidden" id="derr">Please pick a due date. An order cannot be scheduled without one.</div>
    <label class="f">Customer commitment<input id="nc" placeholder="e.g. Aero customer, firm date" maxlength="80"></label></div>
  <div><label class="f">Notes (optional)<textarea id="nn" rows="5" maxlength="500" placeholder="Certified inspector only, surface finish N6, gift wrap please"></textarea></label>
    <p class="note info" style="font-size:14px">Note reader: <b>${esc(s.note_reader.label)}</b>. It matches known words only. It does not understand free language and can miss other phrasings. Anything it does not recognise is shown to you and never applied.</p>
    <button id="fill">Fill the demo example</button> <button class="primary big" id="create">Create order</button><div id="newres"></div></div></div></div>`;
  p.querySelectorAll("[data-open]").forEach((b) => (b.onclick = () => showTasks(b.dataset.open)));
  p.querySelectorAll("[data-del]").forEach((b) => (b.onclick = () => guard(async () => { modal(`<h2>Remove ${esc(b.dataset.del)}?</h2><p>The order and its jobs are removed. This is recorded in the audit log.</p><button class="danger" id="dy">Remove</button> <button id="dn">Cancel</button>`); $("#dn").onclick = closeModal; $("#dy").onclick = () => guard(async () => { await api("DELETE", "/api/orders/" + b.dataset.del); closeModal(); toast("Order removed.", "ok"); render(); }); })));
  $("#fill").onclick = () => { $("#np").value = "P-ALU-FLANGE"; $("#nq").value = 8; $("#npr").value = "Urgent"; $("#nc").value = "Aero customer, urgent"; $("#nn").value = "Certified inspector only, surface finish N6, gift wrap please"; const d = new Date(s.horizon_start + "T00:00:00"); d.setDate(d.getDate() + 4); if (d.getDay() === 0) d.setDate(d.getDate() + 1); $("#nd").value = d.toISOString().slice(0, 10); };
  $("#create").onclick = () => guard(async () => {
    $("#derr").classList.add("hidden");
    if (!$("#nd").value) { $("#derr").classList.remove("hidden"); $("#nd").focus(); return; }
    const r = await post("/api/orders", { product_id: $("#np").value, quantity: $("#nq").value, priority: $("#npr").value, due_date: $("#nd").value, customer_commitment: $("#nc").value, notes: $("#nn").value }, "Creating order and jobs...");
    const pn = r.parsed_notes;
    $("#newres").innerHTML = `<div class="note good"><b>Order ${esc(r.order_id)} created</b> with ${r.task_count} jobs.</div>` + (pn ? `<div class="note info"><b>What the note reader found</b> (${esc(pn.source === "gemini" ? "AI-assisted" : "keyword reader")}):<br>Added: ${[...pn.required_skills, ...pn.required_certifications, ...pn.special_notes].map((x) => chip("blue", x)).join(" ") || "nothing"}<br>Not recognised, not applied: ${pn.rejected.length ? pn.rejected.map((x) => chip("amber", x)).join(" ") : "nothing"}<br><span class="muted">Skills and certificates are applied to the matching jobs. Surface finish is kept as a note for people.</span></div>` : "");
    toast("Order created. Next: generate the schedule.", "ok"); await refreshState(); ST.newOrder = r.order_id;
    const t = $("#tasks"); showTasks(r.order_id, true);
  });
  if (sel) showTasks(sel); else if (ST.arg === "new") $("#newbox").scrollIntoView({ behavior: "smooth" });
  async function showTasks(oid) {
    const [tasks] = await Promise.all([get("/api/tasks?order_id=" + encodeURIComponent(oid))]);
    const byId = Object.fromEntries(tasks.map((t) => [t.id, t]));
    $("#tasks").innerHTML = `<div class="card"><h2>Jobs for ${esc(oid)}</h2><p class="help" style="margin-bottom:8px">Jobs run in the order shown; a job starts only after the jobs it depends on finish. Quality gates are marked.</p>
    <div class="flow" style="color:#16202e">${tasks.filter((t) => t.chunk_index === 0).map((t, i) => `${i ? '<span class="arrow" style="color:#7b8aa3">&rarr;</span>' : ""}<span class="chip ${t.is_quality_gate ? "amber" : "blue"}" style="font-size:14px">${esc(t.name)}${t.is_quality_gate ? " (quality gate)" : ""}</span>`).join("")}</div>
    <div class="tw"><table><thead><tr><th>Job</th><th>Time needed</th><th>Needs</th><th>Machine type</th><th>People</th><th>Starts after</th><th>Status</th><th></th></tr></thead><tbody>
    ${tasks.map((t) => `<tr><td><b>${esc(t.name)}</b></td><td>${(t.duration_min / 60).toFixed(1)} h</td><td>${esc(t.required_skill)} L${t.min_level}${t.extra_skill ? `<br>${chip("blue", "+ " + t.extra_skill + " (note)")}` : ""}${t.required_cert ? `<br>${chip("blue", "certified: " + t.required_cert.replace(" Cert", ""))}` : ""}<br><span class="muted">${esc(t.required_role)}</span></td><td>${esc(t.work_center_kind)}</td><td>${t.multi_person}</td><td>${t.depends_on.map((d) => esc(byId[d]?.name || d)).join(", ") || "-"}</td><td>${chip("grey", t.status)}${t.locked ? " " + lockI : ""}</td><td><button class="sm" data-el="${esc(t.id)}">Who can do this?</button></td></tr>`).join("")}
    </tbody></table></div></div>`;
    $("#tasks").querySelectorAll("[data-el]").forEach((b) => (b.onclick = () => eligibility(b.dataset.el)));
    $("#tasks").scrollIntoView({ behavior: "smooth" });
  }
};
async function eligibility(tid) {
  const e = await get("/api/eligibility/" + encodeURIComponent(tid));
  const blocked = e.excluded.filter((x) => x.kind === "blocked"), nq = e.excluded.filter((x) => x.kind !== "blocked");
  modal(`<h2>Who can do: ${esc(e.task.name)} (${esc(e.task.order_id)})</h2><p class="muted">Checked for ${esc(e.day_text)}. Needs ${esc(e.task.required_skill)} level ${e.task.min_level}${e.task.extra_skill ? " and " + esc(e.task.extra_skill) : ""}, role ${esc(e.task.required_role)}. These rules have no override.</p>
  <h3>${chip("green", e.candidates.length + " eligible", "&#10004;")}</h3>${e.candidates.length ? `<table><tr><th>Person</th><th>Shift</th><th>Skill level</th></tr>${e.candidates.map((c) => `<tr><td>${esc(c.employee_name)}</td><td>${esc(c.shift)}</td><td>${c.skill_level}</td></tr>`).join("")}</table>` : '<div class="note bad">Nobody is eligible on this day.</div>'}
  <h3 style="margin-top:14px">${chip("red", blocked.length + " excluded for a specific reason", "&#10006;")}</h3>${blocked.length ? `<table>${blocked.map((x) => `<tr><td><b>${esc(x.person)}</b></td><td>${x.reasons.map(esc).join("<br>")}</td></tr>`).join("")}</table>` : '<p class="muted">None.</p>'}
  <details style="margin-top:12px"><summary>${nq.length} other people are not qualified for this job (wrong role or skill)</summary><table>${nq.map((x) => `<tr><td>${esc(x.person)}</td><td class="muted">${x.reasons.map(esc).join("; ")}</td></tr>`).join("")}</table></details>`);
}

/* ---------- WORKFORCE ---------- */
PAGES.workforce = async (p) => {
  const w = await get("/api/workforce");
  const edit = ST.role === "HR/Workforce Admin" || isManager();
  const CS = { expired: ["red", "Expired", "&#10006;"], "expiring soon": ["amber", "Expiring soon", "&#9888;"], valid: ["green", "Valid", "&#10004;"] };
  p.innerHTML = `<h1>Workforce and Skill Matrix</h1><p class="help">Who works here, what they are good at (level 1 to 5) and whether their certificates are valid. Darker blue means higher skill. Certificates that are expired or expiring soon are flagged, and expired ones remove the person from matching jobs.</p>
  <div class="card"><h2>Skill heatmap</h2><div class="legend">${[0, 1, 2, 3, 4, 5].map((l) => `<span><i class="l${l}"></i>${l ? "Level " + l : "No skill"}</span>`).join("")}</div><div class="tw"><table class="heat"><thead><tr><th>Person</th><th>Team / shift</th>${w.skills.map((s) => `<th class="c">${esc(s)}</th>`).join("")}</tr></thead><tbody>
  ${w.employees.map((e) => `<tr><td><b>${esc(e.name)}</b><br><span class="muted" style="font-size:13px">${esc(e.role)}</span></td><td>${esc(e.team)} / Shift ${esc(e.shift)}</td>${w.skills.map((s) => `<td class="c l${e.levels[s]}" title="${esc(e.name)}: ${esc(s)} level ${e.levels[s]}">${e.levels[s] || "-"}</td>`).join("")}</tr>`).join("")}</tbody></table></div></div>
  <div class="card"><h2>Certificates and leave</h2><p class="muted">Reference date: ${esc(fmtDate(w.reference_date))} (first planning day).</p><div class="tw"><table><thead><tr><th>Person</th><th>Certificate</th><th>Expires</th><th>Status</th><th>Leave days</th></tr></thead><tbody>
  ${w.employees.filter((e) => e.certs.length || e.leave_dates.length).map((e) => e.certs.map((c, i) => `<tr><td>${i ? "" : "<b>" + esc(e.name) + "</b>"}</td><td>${esc(c.cert)}</td><td>${esc(fmtDate(c.expires_on))}</td><td>${chip(CS[c.state][0], CS[c.state][1] + (c.state === "expiring soon" ? ` (${c.days_left} days)` : ""), CS[c.state][2])}</td><td>${i ? "" : e.leave_dates.map((d) => esc(fmtDate(d))).join(", ") || "-"}</td></tr>`).join("") || `<tr><td><b>${esc(e.name)}</b></td><td colspan="3" class="muted">No certificates</td><td>${e.leave_dates.map((d) => esc(fmtDate(d))).join(", ")}</td></tr>`).join("")}</tbody></table></div></div>
  <div class="card"><h2>Edit workforce</h2>${edit ? `<p class="help" style="margin-bottom:8px">HR / Workforce Admin and the Production Manager can change skill levels and leave. Changes apply to the next schedule you generate and are recorded.</p><div class="row"><label class="f">Person<select id="ep">${w.employees.map((e) => `<option value="${esc(e.id)}">${esc(e.name)}</option>`).join("")}</select></label><label class="f">Skill<select id="es">${w.skills.map((s) => `<option>${esc(s)}</option>`).join("")}</select></label><label class="f">New level (0 removes it)<input id="el" type="number" min="0" max="5" value="3"></label></div><button id="esave">Save skill level</button>
  <div class="row" style="margin-top:14px"><label class="f">Add a leave day<input id="ed" type="date"></label><label class="f">&nbsp;<button id="eleave">Add leave day</button></label></div>` : `<p class="muted">Only the HR / Workforce Admin or Production Manager role can edit. Switch role at the bottom left.</p>`}</div>`;
  if (edit) {
    $("#esave").onclick = () => guard(async () => { await post("/api/employees/" + $("#ep").value, { skill: $("#es").value, level: $("#el").value }); toast("Skill level saved.", "ok"); render(); });
    $("#eleave").onclick = () => guard(async () => { const e = w.employees.find((x) => x.id === $("#ep").value); if (!$("#ed").value) throw new Error("Pick a date first."); await post("/api/employees/" + e.id, { leave_dates: [...e.leave_dates, $("#ed").value] }); toast("Leave day added.", "ok"); render(); });
  }
};

/* ---------- PLAN ---------- */
PAGES.plan = async (p) => {
  const s = ST.state;
  const W = { ...s.weights };
  let preset = "balanced";
  p.innerHTML = `<h1>AI Allocation Proposal</h1><p class="help">Pick what matters most, press <b>Generate schedule</b>, and get a recommended person and machine for every job, with a reason. Nothing is final until a manager approves it.</p>
  <div class="card"><h2>1. What matters most?</h2><div class="presets" id="presets">${Object.entries(s.presets).map(([k, v]) => `<button data-k="${k}" class="${k === preset ? "on" : ""}">${esc(v.label)}</button>`).join("")}</div>
  <div id="sliders"></div><p class="muted" style="font-size:14px">Different priorities do not always change the plan. If the best plan is the same under both, that is a correct result.</p>
  <h2 style="margin-top:14px">2. Create the proposal</h2><button class="primary big" id="gen">Generate schedule</button> <span class="muted" id="genhint">Plans all ${s.orders} orders (${s.tasks} jobs). Takes a few seconds.</span></div><div id="result"></div>`;
  const drawSliders = () => { $("#sliders").innerHTML = Object.entries(s.weight_labels).map(([k, l]) => `<div class="sliderrow"><label for="w_${k}">${esc(l)}</label><input id="w_${k}" type="range" min="0" max="30" step="0.5" value="${W[k]}"><b>${W[k]}</b></div>`).join(""); Object.keys(s.weight_labels).forEach((k) => { $("#w_" + k).oninput = (e) => { W[k] = +e.target.value; e.target.nextElementSibling.textContent = W[k]; preset = null; document.querySelectorAll("#presets button").forEach((b) => b.classList.remove("on")); }; }); };
  drawSliders();
  p.querySelectorAll("#presets button").forEach((b) => (b.onclick = () => { preset = b.dataset.k; Object.assign(W, s.presets[preset].weights); drawSliders(); document.querySelectorAll("#presets button").forEach((x) => x.classList.toggle("on", x === b)); }));
  $("#gen").onclick = () => guard(async () => {
    const r = await post("/api/plan", preset ? { preset } : { weights: W }, "Planning every job... this takes a few seconds");
    ST.plan = r; if (r.version_id) { ST.vid = r.version_id; sessionStorage.setItem("vid", ST.vid); }
    await refreshState(); drawResult(r);
  });
  if (ST.plan) drawResult(ST.plan);
  function drawResult(r) {
    const box = $("#result");
    if (!r.version_id) { box.innerHTML = noPlanHTML(r); return; }
    const ok = r.orders.filter((o) => o.status !== "late").length;
    box.innerHTML = `<div class="note good" style="font-size:17px"><b>Solved in ${r.runtime} seconds</b> (${esc(r.status === "OPTIMAL" ? "best possible plan found" : "good plan found within the time limit")}). Proposal <b>${esc(r.version_id)}</b> is a draft until you approve it.</div>
    <div class="metrics"><div class="metric"><div class="v">${r.assignments.length}</div><div class="l">jobs assigned a person and a machine</div></div><div class="metric"><div class="v">${ok} of ${r.orders.length}</div><div class="l">orders expected on time or at risk (not late)</div></div><div class="metric"><div class="v">${r.violations.length}</div><div class="l">hard-rule violations (checked independently)</div></div></div>
    <div class="card"><h2>Estimated delivery per order</h2><div class="row">${r.orders.map((o) => `<div class="ocard ${o.status}"><b>${esc(o.order_id)}</b> ${prio(o.priority)}<br>${badge(o.status)}<br>Finishes <b>${esc(o.finish_text)}</b><br><span class="muted">Due ${esc(fmtDate(o.due_date))}${o.hours_late ? ` &middot; ${o.hours_late} h late` : ""}</span></div>`).join("")}</div></div>
    <div class="card"><h2>Who does what</h2><div style="margin-bottom:8px"><button class="primary" onclick="go('approval')">Review and approve</button> <button onclick="go('gantt')">See the chart</button></div><div class="tw"><table><thead><tr><th>Job</th><th>Order</th><th>Assigned to</th><th>Machine</th><th>When</th><th></th></tr></thead><tbody>${r.assignments.map((a, i) => `<tr><td><b>${esc(a.task_name)}</b></td><td>${esc(a.order_id)}</td><td>${a.employees.map((e) => esc(e.name)).join(", ")}</td><td>${esc(a.work_center_id)}</td><td class="nowrap">${esc(a.start_text)} to ${esc(a.end_text.split(", ")[1])}</td><td><button class="sm" data-w="${i}">Why?</button></td></tr><tr class="hidden" id="why${i}"><td colspan="6">${whyHTML(a.why)}</td></tr>`).join("")}</tbody></table></div></div>`;
    box.querySelectorAll("[data-w]").forEach((b) => (b.onclick = () => $("#why" + b.dataset.w).classList.toggle("hidden")));
    box.scrollIntoView({ behavior: "smooth" });
  }
};
function whyHTML(w) {
  if (!w || !w.summary) return '<span class="muted">No explanation stored.</span>';
  return `<div class="why"><b>Why this person?</b><br>${esc(w.summary)}<br><span class="muted">${esc(w.shift_fit)}${w.continuity ? " &middot; same person as the last approved plan" : ""}</span>${w.alternatives && w.alternatives.length ? `<br><b>Others considered:</b><ul>${w.alternatives.map((a) => `<li>${esc(a.person)} (level ${a.skill_level}, Shift ${esc(a.shift)}): ${esc(a.why_not)}</li>`).join("")}</ul>` : "<br>Nobody else was qualified at that time."}</div>`;
}
function noPlanHTML(r) {
  const d = r.diagnosis || r;
  const st = r.status;
  let h = "";
  if (st === "UNKNOWN") h += `<div class="note warn"><b>The scheduler ran out of time.</b> This is not the same as "impossible". Your last approved schedule is unchanged. You can try again, or plan manually.</div>`;
  else if (st === "EMPTY" || st === "BAD_DATA") h += `<div class="note warn"><b>${esc(r.message)}</b></div>`;
  else h += `<div class="note bad"><b>No valid plan exists.</b> ${esc(r.message || "")} No rule was bent.</div>`;
  if (d && d.zero_eligibility && d.zero_eligibility.length) h += `<div class="card"><h3>Proven blocker: jobs with nobody eligible</h3><table>${d.zero_eligibility.map((z) => `<tr><td><b>${esc(z.task_name)}</b> (${esc(z.order_id)})</td><td>${esc(z.needs)}</td><td>${esc(z.why)}</td></tr>`).join("")}</table></div>`;
  if (d && d.relaxation_tests) h += `<div class="card"><h3>What-if tests (labelled tests, not proof)</h3><table>${d.relaxation_tests.map((t) => `<tr><td>${esc(t.label)}</td><td>${esc(t.what_if)}</td><td>${t.fixes ? chip("green", "a plan exists", "&#10004;") : chip("red", "still no plan", "&#10006;")}</td></tr>`).join("")}</table><h3 style="margin-top:12px">What could fix it</h3><ul>${d.remedies.map((x) => `<li>${esc(x)}</li>`).join("")}</ul><p class="muted">Fallback: plan manually using the Orders and Workforce screens. The last approved schedule stays in place.</p></div>`;
  return h;
}

/* ---------- boot ---------- */
document.addEventListener("DOMContentLoaded", async () => {
  const roleSel = $("#role");
  try { await refreshState(); } catch (e) { $("#page").innerHTML = `<div class="errbox">${esc(e.message)}</div>`; return; }
  roleSel.innerHTML = ST.state.roles.map((r) => `<option ${r === ST.role ? "selected" : ""}>${esc(r)}</option>`).join("");
  roleSel.onchange = () => { ST.role = roleSel.value; sessionStorage.setItem("role", ST.role); if (!can(ST.page)) ST.page = NAV.find((n) => n[2].includes(ST.role))[0]; toast(`Viewing as ${ST.role}. This is a demo simulation of permissions.`, "info"); render(); };
  $("#bell").onclick = () => go("live", "alerts"); $("#guidebtn").onclick = () => $("#guide").classList.toggle("hidden");
  $("#menu").onclick = () => $("#side").classList.toggle("open"); $("#modalx").onclick = closeModal; $("#modal").onclick = (e) => { if (e.target.id === "modal") closeModal(); };
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });
  const h = location.hash.replace("#", ""); if (h && PAGES[h]) ST.page = h; if (!can(ST.page)) ST.page = NAV.find((n) => n[2].includes(ST.role))[0];
  window.addEventListener("hashchange", () => { const h2 = location.hash.replace("#", ""); if (h2 && PAGES[h2] && h2 !== ST.page && can(h2)) { ST.page = h2; render(); } });
  render();
});
window.addEventListener("unhandledrejection", (e) => { console.error(e.reason); toast("Something went wrong: " + (e.reason?.message || "unknown error"), "err"); });
