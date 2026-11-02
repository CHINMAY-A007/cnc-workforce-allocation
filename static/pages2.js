/* Screens 5-11 */
"use strict";
const PALETTE = ["#1d5fd6", "#0f8a6a", "#b0560e", "#7a3fc2", "#c0305a", "#3b7a1c", "#2a7f9e", "#8a6d00"];

async function pickVersion(preferDraft) {
  const vs = await get("/api/versions");
  let id = ST.vid && vs.find((v) => v.id === ST.vid) ? ST.vid : null;
  if (preferDraft) { const d = vs.find((v) => v.status === "draft"); if (d) id = d.id; }
  if (!id) id = (vs.find((v) => v.status === "approved") || vs[0] || {}).id || null;
  return { vs, id };
}
const VST = { draft: ["blue", "Draft, waiting for approval"], approved: ["green", "Approved"], superseded: ["grey", "Replaced"], rejected: ["red", "Rejected"] };

/* ---------- GANTT ---------- */
PAGES.gantt = async (p) => {
  const { vs, id } = await pickVersion(false);
  p.innerHTML = `<h1>Schedule Chart</h1><p class="help">Every job on a timeline. Switch between people and machines, filter by order or day, and click a bar to see why that person was chosen. A lock means the job will not move unless a manager unlocks it.</p>`;
  if (!id) { p.innerHTML += empty("No schedule yet", "Go to AI Allocation Proposal and press Generate schedule.", '<button class="primary" onclick="go(\'plan\')">Go to AI Allocation Proposal</button>'); return; }
  const d = await get("/api/version/" + id);
  let by = "person", fo = "", fd = "";
  const orders = [...new Set(d.assignments.map((a) => a.order_id))];
  const col = Object.fromEntries(orders.map((o, i) => [o, PALETTE[i % PALETTE.length]]));
  const hs = new Date(d.horizon_start + "T00:00:00");
  const days = []; for (let i = 0; i < d.horizon_days; i++) { const dt = new Date(hs); dt.setDate(dt.getDate() + i); if (dt.getDay() !== 0) days.push({ i, dt }); }
  const PXH = 34, H0 = 6, H1 = 24, DW = (H1 - H0) * PXH;
  p.innerHTML += `<div class="card"><div class="row" style="align-items:end"><label class="f" style="margin:0">Schedule<select id="gv">${vs.map((v) => `<option value="${esc(v.id)}" ${v.id === id ? "selected" : ""}>${esc(v.id)} - ${esc(VST[v.status]?.[1] || v.status)}</option>`).join("")}</select></label>
  <label class="f" style="margin:0">Show by<select id="gby"><option value="person">People</option><option value="machine">Machines</option></select></label>
  <label class="f" style="margin:0">Order<select id="go2"><option value="">All orders</option>${orders.map((o) => `<option>${esc(o)}</option>`).join("")}</select></label>
  <label class="f" style="margin:0">Day<select id="gd"><option value="">All days</option>${days.map((x) => `<option value="${x.i}">${x.dt.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}</option>`).join("")}</select></label></div>
  <div style="margin-top:10px">${VST[d.version.status] ? chip(VST[d.version.status][0], VST[d.version.status][1]) : ""} ${d.violations.length ? chip("red", d.violations.length + " rule violations", "<i class=ic-cross></i>") : chip("green", "All hard rules satisfied", "<i class=ic-check></i>")}</div>
  <div class="legend">${orders.map((o) => `<span><i style="background:${col[o]}"></i>${esc(o)}</span>`).join("")}<span>${lockI} locked</span></div></div>
  <div class="card"><h2>Estimated delivery</h2><div class="row">${d.orders.map((o) => `<div class="ocard ${o.status}"><b>${esc(o.order_id)}</b> ${badge(o.status)}<br>Finishes <b>${esc(o.finish_text)}</b><br><span class="muted">Due ${esc(fmtDate(o.due_date))}</span></div>`).join("")}</div></div>
  <div class="gwrap"><div class="gantt" id="gchart"></div></div><div id="gdetail"></div>`;
  $("#gv").onchange = (e) => { ST.vid = e.target.value; sessionStorage.setItem("vid", ST.vid); render(); };
  const draw = () => {
    let items = d.assignments.filter((a) => (!fo || a.order_id === fo) && (fd === "" || Math.floor(a.start_slot / 96) === +fd));
    const dayList = fd === "" ? days : days.filter((x) => x.i === +fd);
    const idx = Object.fromEntries(dayList.map((x, k) => [x.i, k]));
    const rows = {};
    d.assignments.forEach((a) => { const keys = by === "person" ? a.employees.map((e) => [e.id, e.name]) : [[a.work_center_id, a.work_center_name]]; keys.forEach(([k, n]) => { rows[k] = n; }); });
    const keys = Object.keys(rows).sort();
    const W = dayList.length * DW;
    let h = `<div class="ghead"><div class="glab">${by === "person" ? "Person" : "Machine"}</div>${dayList.map((x) => `<div class="gday" style="width:${DW}px">${x.dt.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}${Array.from({ length: (H1 - H0) / 2 }, (_, k) => `<i style="left:${k * 2 * PXH}px">${String(H0 + k * 2).padStart(2, "0")}</i>`).join("")}</div>`).join("")}</div>`;
    keys.forEach((k) => {
      const mine = items.filter((a) => (by === "person" ? a.employee_ids.includes(k) : a.work_center_id === k));
      h += `<div class="grow"><div class="glab" title="${esc(rows[k])}">${esc(rows[k])}</div><div class="gtrack" style="width:${W}px;background-size:${PXH * 2}px 100%">${mine.map((a) => { const di = idx[Math.floor(a.start_slot / 96)]; if (di === undefined) return ""; const st = ((a.start_slot % 96) / 4 - H0) * PXH + di * DW, w = ((a.end_slot - a.start_slot) / 4) * PXH; const idxA = d.assignments.indexOf(a);
        return `<div class="bar ${a.locked ? "lk" : ""}" data-i="${idxA}" style="left:${st}px;width:${Math.max(w, 14)}px;background:${col[a.order_id]}" title="${esc(a.task_name)} (${esc(a.order_id)}) ${esc(a.start_text)} - ${esc(a.end_text)}" tabindex="0">${a.locked ? "<i class=ic-lock></i> " : ""}${esc(a.task_name)}</div>`; }).join("")}</div></div>`;
    });
    $("#gchart").style.width = 170 + W + "px"; $("#gchart").innerHTML = h;
    document.querySelectorAll(".bar").forEach((b) => { const open = () => { const a = d.assignments[+b.dataset.i]; $("#gdetail").innerHTML = `<div class="card"><h3>${esc(a.task_name)} (${esc(a.order_id)}) ${a.locked ? lockI : ""}</h3>${a.employees.map((e) => esc(e.name)).join(", ")} on ${esc(a.work_center_name)}<br>${esc(a.start_text)} to ${esc(a.end_text)} (${a.minutes / 60} h)${whyHTML(a.why)}</div>`; $("#gdetail").scrollIntoView({ behavior: "smooth" }); }; b.onclick = open; b.onkeydown = (e) => { if (e.key === "Enter") open(); }; });
    if (!items.length) $("#gchart").innerHTML += `<div class="empty" style="margin:10px">No jobs match these filters.</div>`;
  };
  $("#gby").onchange = (e) => { by = e.target.value; draw(); }; $("#go2").onchange = (e) => { fo = e.target.value; draw(); }; $("#gd").onchange = (e) => { fd = e.target.value; draw(); };
  draw();
};

/* ---------- APPROVAL ---------- */
PAGES.approval = async (p) => {
  const { vs, id } = await pickVersion(true);
  p.innerHTML = `<h1>Approval and Changes</h1><p class="help">Review the proposal. You can change who does a job (a reason is required and only valid people are offered), lock jobs you do not want touched, then approve or reject. The AI suggests; you decide.</p>`;
  if (!id) { p.innerHTML += empty("Nothing to approve yet", "Generate a schedule first, then come back here.", '<button class="primary" onclick="go(\'plan\')">Go to AI Allocation Proposal</button>'); return; }
  const d = await get("/api/version/" + id);
  const v = d.version, draft = v.status === "draft", mgr = isManager();
  p.innerHTML += `<div class="card"><div class="row" style="align-items:end"><label class="f" style="margin:0">Schedule version<select id="av">${vs.map((x) => `<option value="${esc(x.id)}" ${x.id === id ? "selected" : ""}>${esc(x.id)} - ${esc(VST[x.status]?.[1] || x.status)} - ${esc(x.label)}</option>`).join("")}</select></label>
  <div>${chip(...VST[v.status] || ["grey", v.status])} ${d.violations.length ? chip("red", d.violations.length + " rule violations", "<i class=ic-cross></i>") : chip("green", "All hard rules satisfied", "<i class=ic-check></i>")}<br><span class="muted">${esc(v.label)}${v.approved_by ? ` &middot; approved by ${esc(v.approved_by)}` : ""}</span></div></div>
  ${d.violations.length ? `<div class="errbox">${d.violations.map(esc).join("<br>")}<br>This plan cannot be approved.</div>` : ""}
  ${!mgr ? `<div class="note warn">Only the Production Manager can approve, edit or lock. Switch role at the bottom left.</div>` : ""}
  <div class="row" style="margin-top:10px">${d.orders.map((o) => `<div class="ocard ${o.status}"><b>${esc(o.order_id)}</b> ${badge(o.status)}<br>Finishes ${esc(o.finish_text)} &middot; due ${esc(fmtDate(o.due_date))}</div>`).join("")}</div>
  ${draft ? `<div style="margin-top:14px"><button class="primary big" id="appr" ${mgr && !d.violations.length ? "" : "disabled"}>Approve this schedule</button> <button class="danger" id="rej" ${mgr ? "" : "disabled"}>Reject...</button> <span class="muted">${d.assignments.filter((a) => a.locked).length} job(s) locked</span></div>` : '<p class="muted" style="margin-top:10px">Only a draft can be edited or approved. Generate a new proposal on the AI Allocation Proposal screen.</p>'}</div>
  <div class="card"><h2>Assignments</h2><div class="tw"><table><thead><tr><th>Job</th><th>Order</th><th>Assigned to</th><th>Machine</th><th>When</th><th>Lock</th><th></th></tr></thead><tbody>
  ${d.assignments.map((a, i) => `<tr><td><b>${esc(a.task_name)}</b></td><td>${esc(a.order_id)}</td><td>${a.employees.map((e) => esc(e.name)).join(", ")}</td><td>${esc(a.work_center_id)}</td><td class="nowrap">${esc(a.start_text)} to ${esc(a.end_text.split(", ")[1])}</td><td>${a.locked ? lockI + " Locked" : "-"}</td>
  <td class="nowrap"><button class="sm" data-why="${i}">Why?</button> ${draft && mgr ? `<button class="sm" data-edit="${i}" ${a.locked ? "disabled title='Unlock first'" : ""}>Change person</button> <button class="sm" data-lock="${i}">${a.locked ? "Unlock..." : "Lock"}</button>` : ""}</td></tr><tr class="hidden" id="aw${i}"><td colspan="7">${whyHTML(a.why)}</td></tr><tr class="hidden" id="ae${i}"><td colspan="7"></td></tr>`).join("")}</tbody></table></div></div>`;
  $("#av").onchange = (e) => { ST.vid = e.target.value; sessionStorage.setItem("vid", ST.vid); render(); };
  p.querySelectorAll("[data-why]").forEach((b) => (b.onclick = () => $("#aw" + b.dataset.why).classList.toggle("hidden")));
  p.querySelectorAll("[data-lock]").forEach((b) => (b.onclick = () => guard(async () => { const a = d.assignments[+b.dataset.lock]; if (a.locked) { const r = await ask("Unlock this job?", "Reason for unlocking", "e.g. person is no longer available"); if (!r) return; await post("/api/unlock", { version_id: id, task_id: a.task_id, reason: r }); } else await post("/api/lock", { version_id: id, task_id: a.task_id }); toast(a.locked ? "Unlocked." : "Locked.", "ok"); render(); })));
  p.querySelectorAll("[data-edit]").forEach((b) => (b.onclick = () => guard(async () => {
    const a = d.assignments[+b.dataset.edit]; const row = $("#ae" + b.dataset.edit); const c = await get(`/api/version/${id}/candidates/${a.task_id}`);
    row.classList.remove("hidden");
    const opts = c.valid_candidates.map((x) => `<option value="${esc(x.employee_id)}">${esc(x.employee_name)} (level ${x.skill_level}, Shift ${esc(x.shift)})</option>`).join("");
    row.firstElementChild.innerHTML = `<div class="why"><b>Change who does ${esc(a.task_name)}.</b> Only people who pass every hard rule and are free at that time are listed.<br>${a.employee_ids.map((eid, k) => `<label class="f" style="display:inline-block;margin-right:10px">Replace ${esc(a.employees[k].name)} with<select class="ps" data-k="${k}"><option value="${esc(eid)}">${esc(a.employees[k].name)} (keep)</option>${c.valid_candidates.filter((x) => x.employee_id !== eid && !a.employee_ids.includes(x.employee_id)).map((x) => `<option value="${esc(x.employee_id)}">${esc(x.employee_name)} (level ${x.skill_level}, Shift ${esc(x.shift)})</option>`).join("")}</select></label>`).join("")}
    ${c.valid_candidates.filter((x) => !a.employee_ids.includes(x.employee_id)).length ? "" : '<div class="note warn">Nobody else qualifies at that time, so this job cannot be reassigned. That is the rules working as intended.</div>'}
    <label class="f">Reason (required)<input id="re${b.dataset.edit}" maxlength="200" placeholder="e.g. Priya is needed on the urgent order"></label><button class="primary sm" id="rs${b.dataset.edit}">Save change</button> <button class="sm" id="rc${b.dataset.edit}">Cancel</button></div>`;
    $("#rc" + b.dataset.edit).onclick = () => row.classList.add("hidden");
    $("#rs" + b.dataset.edit).onclick = () => guard(async () => { const ids = [...row.querySelectorAll(".ps")].map((s) => s.value); const reason = $("#re" + b.dataset.edit).value.trim(); if (!reason) throw new Error("Please give a reason. Every change is recorded."); await post("/api/reassign", { version_id: id, task_id: a.task_id, employee_ids: ids, reason }); toast("Change saved and recorded.", "ok"); render(); });
  })));
  if (draft) {
    $("#appr").onclick = () => guard(async () => { await post("/api/approve", { version_id: id }, "Approving..."); ST.vid = id; sessionStorage.setItem("vid", id); toast("Approved. Workers can now see their tasks.", "ok"); go("gantt"); });
    $("#rej").onclick = () => guard(async () => { const r = await ask("Reject this proposal?", "Reason for rejecting", "e.g. wrong priorities"); if (!r) return; await post("/api/reject", { version_id: id, reason: r }); toast("Rejected and recorded.", "ok"); render(); });
  }
};

/* ---------- MY TASKS ---------- */
PAGES.mytasks = async (p) => {
  const w = await get("/api/workforce");
  if (!w.employees.find((e) => e.id === ST.worker)) ST.worker = w.employees[0].id;
  const d = await get("/api/tasks/worker/" + ST.worker);
  p.innerHTML = `<h1>My Tasks</h1><p class="help">Jobs assigned to one person in the approved schedule. Press Start when you begin, Complete when done, or Report issue if something blocks the job.</p>
  <div class="card"><label class="f" style="margin:0;max-width:420px">Demo: view as this person<select id="mw">${w.employees.map((e) => `<option value="${esc(e.id)}" ${e.id === ST.worker ? "selected" : ""}>${esc(e.name)} - ${esc(e.role)}</option>`).join("")}</select></label>
  <p class="muted" style="margin:6px 0 0">Shift ${esc(d.employee.shift)}. This picker is a demo shortcut, not a login.</p></div>`;
  $("#mw").onchange = (e) => { ST.worker = e.target.value; sessionStorage.setItem("worker", ST.worker); render(); };
  if (!d.approved_version) { p.innerHTML += empty("No approved schedule yet", "Tasks appear here after a manager approves a schedule.", ST.role !== "Worker" ? '<button class="primary" onclick="go(\'approval\')">Go to Approval</button>' : ""); return; }
  if (!d.tasks.length) { p.innerHTML += empty("No tasks for this person", `${d.employee.name} has no jobs in schedule ${d.approved_version}. Pick someone else above.`); return; }
  const cls = { "In Progress": "prog", Completed: "done", Blocked: "blk" };
  p.innerHTML += d.tasks.map((t) => `<div class="tcard ${cls[t.status] || ""}"><div class="time">${esc(t.start_text)} to ${esc(t.end_text.split(", ")[1])}</div><div style="font-size:19px;font-weight:600">${esc(t.task_name)} <span class="muted" style="font-weight:400">for ${esc(t.order_id)}</span> ${prio(t.priority)}</div>
  <div class="muted">Machine ${esc(t.work_center)}${t.with.length ? " &middot; working with " + t.with.map(esc).join(", ") : ""} ${t.locked ? "&middot; " + lockI : ""}</div>
  <div style="margin-top:6px">${chip(t.status === "Completed" ? "green" : t.status === "Blocked" ? "red" : t.status === "In Progress" ? "blue" : "grey", t.status)} ${t.actual_start ? `<span class="muted">started ${esc(t.actual_start.replace("T", " "))}</span>` : ""} ${t.actual_end ? `<span class="muted">finished ${esc(t.actual_end.replace("T", " "))}</span>` : ""} ${t.blocker ? `<div class="note bad">Issue reported: ${esc(t.blocker)}</div>` : ""}</div>
  <div class="acts"><button class="primary" data-s="In Progress" data-t="${esc(t.task_id)}" ${["Completed", "In Progress"].includes(t.status) ? "disabled" : ""}>Start</button><button data-s="Completed" data-t="${esc(t.task_id)}" ${t.status === "Completed" ? "disabled" : ""}>Complete</button><button class="danger" data-s="Blocked" data-t="${esc(t.task_id)}" ${t.status === "Completed" ? "disabled" : ""}>Report issue</button></div></div>`).join("");
  p.querySelectorAll("[data-s]").forEach((b) => (b.onclick = () => guard(async () => { let blocker; if (b.dataset.s === "Blocked") { blocker = await ask("What is blocking this job?", "Describe the issue", "e.g. waiting for material"); if (!blocker) return; } await post("/api/tasks/" + b.dataset.t + "/status", { status: b.dataset.s, blocker, actor: d.employee.name }); toast("Saved: " + b.dataset.s, "ok"); render(); })));
};

/* ---------- LIVE ---------- */
PAGES.live = async (p) => {
  const [al, vs, w] = await Promise.all([get("/api/alerts"), get("/api/versions"), get("/api/workforce")]);
  const appr = vs.find((v) => v.status === "approved");
  const orders = await get("/api/orders"), tasks = await get("/api/tasks");
  const det = appr ? await get("/api/version/" + appr.id) : null;
  const wcs = det ? [...new Set(det.assignments.map((a) => a.work_center_id))].sort() : [];
  const KIND = { delivery_risk: "Delivery risk", conflict: "Conflict", schedule_change: "Schedule change", assignment: "New assignment", blocked: "Blocked job", schedule: "Proposal", overdue: "Overdue" };
  const SEV = { critical: ["red", "<i class=ic-cross></i>"], warning: ["amber", "<i class=ic-warn></i>"], info: ["blue", "<i class=ic-info></i>"] };
  p.innerHTML = `<h1>Live Progress and Alerts</h1><p class="help">See delivery risk on the approved plan, read alerts, and simulate a surprise. The planner changes the affected jobs and the jobs that wait for them, and shows you exactly what moved before anything is applied.</p>
  <div class="card"><h2>Delivery risk now</h2>${det ? `<div class="row">${det.orders.map((o) => `<div class="ocard ${o.status}"><b>${esc(o.order_id)}</b> ${badge(o.status)}<br>Finishes ${esc(o.finish_text)}<br><span class="muted">Due ${esc(fmtDate(o.due_date))}</span></div>`).join("")}</div><p class="muted" style="margin-top:8px">Jobs: ${["Planned", "Assigned", "In Progress", "Blocked", "Completed"].map((s) => `${s} ${tasks.filter((t) => t.status === s).length}`).join(" &middot; ")}</p>` : empty("No approved schedule yet", "Approve a schedule first, then simulate surprises.", '<button class="primary" onclick="go(\'plan\')">Go to AI Allocation Proposal</button>')}</div>
  <div class="card" id="simcard"><h2>Simulate a surprise</h2>${isManager() ? "" : '<div class="note warn">Only the Production Manager can run the replanning simulator.</div>'}
  <div class="row"><div><h3>Worker is absent</h3><label class="f">Person<select id="s_emp">${w.employees.map((e) => `<option value="${esc(e.id)}" ${e.id === "E03" ? "selected" : ""}>${esc(e.name)} (${esc(e.team)})</option>`).join("")}</select></label><label class="f">From day<select id="s_from">${[0, 1, 2, 3].map((i) => `<option value="${i}">${i === 0 ? "First planning day" : "Day " + (i + 1)}</option>`).join("")}</select></label><label class="f">For how many days<select id="s_days"><option>1</option><option selected>2</option><option>3</option><option>7</option></select></label><button class="primary" id="b_abs" ${det && isManager() ? "" : "disabled"}>Simulate absence</button></div>
  <div><h3>Machine breaks down</h3><label class="f">Machine<select id="s_wc">${wcs.map((m) => `<option>${esc(m)}</option>`).join("")}</select></label><button id="b_wc" ${det && isManager() ? "" : "disabled"}>Simulate breakdown (1 day)</button>
  <h3 style="margin-top:14px">A job runs late</h3><label class="f">Job<select id="s_task">${tasks.filter((t) => t.planned_start !== null).slice(0, 60).map((t) => `<option value="${esc(t.id)}">${esc(t.order_id)} - ${esc(t.name)}</option>`).join("")}</select></label><button id="b_delay" ${det && isManager() ? "" : "disabled"}>Add 2 hours to this job</button></div>
  <div><h3>New urgent order</h3><p class="muted">Adds an urgent Aluminium Flange order due in 3 days.</p><button id="b_urg" ${det && isManager() ? "" : "disabled"}>Simulate urgent order</button>
  <h3 style="margin-top:14px">Priority change</h3><label class="f">Order<select id="s_ord">${orders.map((o) => `<option value="${esc(o.id)}">${esc(o.id)} (${esc(o.priority)})</option>`).join("")}</select></label><button id="b_pr" ${det && isManager() ? "" : "disabled"}>Make this order Urgent</button>
  <h3 style="margin-top:14px">The impossible case</h3><p class="muted">What if every certified 5-axis person is absent? Nothing is saved.</p><button class="danger" id="b_imp" ${isManager() ? "" : "disabled"}>Run the impossible case</button></div></div>
  <div id="simres"></div></div>
  <div class="card" id="alertsbox"><div style="display:flex;justify-content:space-between;align-items:center"><h2>Alerts (${al.count} unread)</h2><button class="sm" id="readall">Mark all read</button></div>
  ${al.items.length ? `<div class="tw"><table><thead><tr><th>When</th><th>Type</th><th>Message</th><th></th></tr></thead><tbody>${al.items.map((a) => `<tr style="${a.read ? "opacity:.6" : ""}"><td class="nowrap">${esc(a.ts.replace("T", " ").slice(0, 16))}</td><td>${chip(SEV[a.severity][0], KIND[a.kind] || a.kind, SEV[a.severity][1])}</td><td>${esc(a.message)}</td><td>${a.read ? "" : `<button class="sm" data-r="${a.id}">Mark read</button>`}</td></tr>`).join("")}</tbody></table></div>` : empty("No alerts yet", "Alerts appear when schedules are proposed, approved or changed, and when orders are at risk.")}</div>`;
  const run = (ev) => guard(async () => { const r = await post("/api/replan", { event: ev }, "Replanning the affected work..."); drawSim(r); await refreshState(); });
  $("#b_abs") && ($("#b_abs").onclick = () => run({ type: "absence", employee_id: $("#s_emp").value, from_day: +$("#s_from").value, days: +$("#s_days").value }));
  $("#b_wc") && ($("#b_wc").onclick = () => run({ type: "breakdown", work_center_id: $("#s_wc").value, from_day: 0, days: 1 }));
  $("#b_delay") && ($("#b_delay").onclick = () => run({ type: "delay", task_id: $("#s_task").value, minutes: 120 }));
  $("#b_urg") && ($("#b_urg").onclick = () => run({ type: "urgent_order", product_id: "P-ALU-FLANGE", quantity: 10 }));
  $("#b_pr") && ($("#b_pr").onclick = () => run({ type: "priority", order_id: $("#s_ord").value, priority: "Urgent" }));
  $("#b_imp").onclick = () => run({ type: "impossible" });
  $("#readall").onclick = () => guard(async () => { await post("/api/alerts/read-all"); render(); });
  p.querySelectorAll("[data-r]").forEach((b) => (b.onclick = () => guard(async () => { await post("/api/alerts/" + b.dataset.r + "/read"); render(); })));
  if (ST.arg === "alerts") $("#alertsbox").scrollIntoView();
  function drawSim(r) {
    const box = $("#simres"); let h = `<div class="note info"><b>${esc(r.event_text || "")}</b></div>`;
    if (r.result === "conflict") {
      h += `<div class="note bad"><b>A locked job is affected. Nothing was changed.</b> ${esc(r.message)}</div><table>${r.conflicts.map((c) => `<tr><td>${esc(c.text)}</td><td><button class="sm" data-u="${esc(c.task_id)}">Unlock with a reason</button></td></tr>`).join("")}</table>`;
    } else if (r.result === "proposed") {
      const df = r.diff;
      h += `<div class="note good"><b>Revised plan proposed in ${r.runtime} s.</b> ${replanCause(df, r)} Locked jobs were not touched. It is a draft until you approve it.</div>
      <div class="two"><div class="card"><h3>Who changed (${df.moved.length})</h3><ul class="diff">${df.moved.map((m) => `<li>${esc(m.text)}</li>`).join("") || "<li class='muted'>Nobody was replaced.</li>"}</ul></div><div class="card"><h3>What shifted in time (${df.shifted.length})</h3><ul class="diff">${df.shifted.map((m) => `<li>${esc(m.text)} <span class="muted">(${causeText(m.cause)})</span></li>`).join("") || "<li class='muted'>Nothing else moved.</li>"}</ul></div></div>
      <div class="card"><h3>Delivery impact</h3>${df.delivery_impact.length ? `<table>${df.delivery_impact.map((x) => `<tr><td><b>${esc(x.order_id)}</b></td><td>${esc(x.before)} ${badge(x.before_status)}</td><td>&rarr;</td><td>${esc(x.after)} ${badge(x.after_status)}</td></tr>`).join("")}</table>` : '<p class="muted">No order finishes at a different time.</p>'}<p class="muted">${df.unchanged} other jobs are unchanged.</p>
      ${r.detail.violations.length ? `<div class="errbox">${r.detail.violations.map(esc).join("<br>")}</div>` : ""}<button class="primary big" id="apprev" ${r.detail.violations.length ? "disabled" : ""}>Approve revised plan</button> <button id="discard">Discard</button> <button onclick="go('gantt')">See the chart</button></div>`;
    } else if (r.result === "impossible" || r.result === "no_plan") {
      h += (r.result === "no_plan" ? `<div class="note bad"><b>No valid revised plan exists.</b> ${esc(r.message)} The current approved plan is unchanged.</div>` : '<div class="note warn"><b>What-if only.</b> Nothing was saved or changed.</div>') + noPlanHTML(r.diagnosis ? { ...r.diagnosis, status: "INFEASIBLE", message: "" } : r);
    }
    box.innerHTML = h; box.scrollIntoView({ behavior: "smooth" });
    box.querySelectorAll("[data-u]").forEach((b) => (b.onclick = () => guard(async () => { const reason = await ask("Unlock this job?", "Reason for unlocking", "e.g. the person is out sick"); if (!reason) return; await post("/api/unlock", { version_id: appr.id, task_id: b.dataset.u, reason }); toast("Unlocked. Run the simulation again.", "ok"); b.disabled = true; })));
    if ($("#apprev")) { $("#apprev").onclick = () => guard(async () => { await post("/api/approve", { version_id: r.version_id }, "Approving revised plan..."); ST.vid = r.version_id; sessionStorage.setItem("vid", r.version_id); toast("Revised plan approved. Workers see the new tasks.", "ok"); render(); }); $("#discard").onclick = () => guard(async () => { await post("/api/reject", { version_id: r.version_id, reason: "Discarded after review" }); toast("Revised plan discarded. The approved plan is unchanged.", "ok"); render(); }); }
  }
};

/* ---------- REPORTS ---------- */
PAGES.reports = async (p) => {
  const r = await get("/api/reports");
  p.innerHTML = `<h1>Reports</h1><p class="help">How busy people and machines are, how much overtime the plan needs, which machine is the bottleneck, how many orders are on time, and how actual work compares with the plan.</p>`;
  if (r.empty) { p.innerHTML += empty("No schedule yet", r.message, '<button class="primary" onclick="go(\'plan\')">Go to AI Allocation Proposal</button>'); return; }
  const bar = (label, pct, text, cls) => `<div class="br"><span>${esc(label)}</span><div class="track"><div class="fill ${cls || ""}" style="width:${Math.min(100, pct)}%"></div></div><span class="right">${esc(text)}</span></div>`;
  p.innerHTML += `${r.basis === "draft" ? '<div class="note warn">Showing a draft proposal because nothing is approved yet.</div>' : ""}<div class="metrics"><div class="metric"><div class="v">${r.on_time_pct}%</div><div class="l">of orders expected to finish by their due date</div></div><div class="metric"><div class="v">${r.total_overtime_hours} h</div><div class="l">overtime needed (within the allowed cap)</div></div><div class="metric"><div class="v">${r.bottleneck ? esc(r.bottleneck.id) : "-"}</div><div class="l">busiest machine${r.bottleneck ? ` (${r.bottleneck.booked_hours} h booked)` : ""}</div></div></div>
  <div class="two"><div class="card"><h2>Utilization by person</h2><p class="muted" style="margin-top:0">Assigned hours as a share of available hours (working days, minus leave).</p><div class="bars">${r.people.map((x) => bar(x.name, x.utilization_pct, `${x.assigned_hours} of ${x.available_hours} h`, x.overtime_hours ? "hi" : "")).join("")}</div><p class="muted" style="font-size:14px">Amber bars include overtime days.</p></div>
  <div class="card"><h2>Machine load</h2><div class="bars">${r.work_centers.map((x) => bar(x.id, x.load_pct, `${x.booked_hours} h`, x.id === (r.bottleneck || {}).id ? "hi" : "")).join("")}</div><h2 style="margin-top:16px">Workload by team</h2><table><tr><th>Team</th><th>Assigned</th><th>Available</th><th>Overtime</th></tr>${r.teams.map((t) => `<tr><td>${esc(t.team)}</td><td>${t.assigned_hours} h</td><td>${t.available_hours} h</td><td>${t.overtime_hours} h</td></tr>`).join("")}</table></div></div>
  <div class="card"><h2>Orders: estimated delivery</h2><table><tr><th>Order</th><th>Priority</th><th>Finishes</th><th>Due</th><th>Status</th></tr>${r.orders.map((o) => `<tr><td>${esc(o.order_id)}</td><td>${prio(o.priority)}</td><td>${esc(o.finish_text)}</td><td>${esc(fmtDate(o.due_date))}</td><td>${badge(o.status)}</td></tr>`).join("")}</table></div>
  <div class="card"><h2>Overdue jobs</h2>${r.overdue.length ? `<table>${r.overdue.map((o) => `<tr><td>${esc(o.task_name)} (${esc(o.order_id)})</td><td>${esc(o.people)}</td><td>planned end ${esc(o.planned_end)}</td></tr>`).join("")}</table>` : '<p class="muted">No planned job is past its end time and unfinished.</p>'}</div>
  <div class="card"><h2>Planned vs actual</h2><p class="muted">${esc(r.demo_clock_note)} Use My Tasks to press Start / Complete and see this table fill in.</p><div class="tw"><table><thead><tr><th>Job</th><th>Order</th><th>People</th><th>Planned</th><th>Status</th><th>Actual start</th><th>Actual end</th><th>Difference</th></tr></thead><tbody>${r.planned_vs_actual.map((x) => `<tr><td>${esc(x.task_name)}</td><td>${esc(x.order_id)}</td><td>${esc(x.people)}</td><td class="nowrap">${esc(x.planned_start)} to ${esc(x.planned_end.split(", ")[1])}</td><td>${chip(x.status === "Completed" ? "green" : x.status === "Blocked" ? "red" : "grey", x.status)}${x.blocker ? `<br><span class="muted">${esc(x.blocker)}</span>` : ""}</td><td class="nowrap">${esc((x.actual_start || "-").replace("T", " "))}</td><td class="nowrap">${esc((x.actual_end || "-").replace("T", " "))}</td><td>${x.variance_min === null ? "-" : (x.variance_min <= 0 ? Math.abs(x.variance_min) + " min early" : x.variance_min + " min late")}</td></tr>`).join("")}</tbody></table></div></div>`;
};

/* ---------- AUDIT & SETTINGS ---------- */
PAGES.audit = async (p) => {
  const [au, pol, s] = await Promise.all([get("/api/audit"), get("/api/policy"), Promise.resolve(ST.state)]);
  const WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  p.innerHTML = `<h1>Audit and Settings</h1><p class="help">Every important action is recorded with who, when and why. Settings below change how the planner behaves.</p>
  <div class="card"><h2>Settings</h2>${["Production Manager", "ERP Administrator"].includes(ST.role) ? "" : '<div class="note warn">Only the Production Manager or ERP Administrator can change settings.</div>'}
  <h3>What the planner cares about</h3>${Object.entries(s.weight_labels).map(([k, l]) => `<div class="sliderrow"><label for="pw_${k}">${esc(l)}</label><input id="pw_${k}" type="range" min="0" max="30" step="0.5" value="${pol.objective_weights[k]}"><b>${pol.objective_weights[k]}</b></div>`).join("")}
  <div class="row"><label class="f">Overtime cap (hours per day)<input id="pot" type="number" min="0" max="4" step="0.5" value="${pol.overtime_cap_hours}"></label><div><b style="font-size:14px">Working days</b><div>${WD.map((d, i) => `<label style="margin-right:8px"><input type="checkbox" class="wd" value="${i}" ${pol.working_weekdays.includes(i) ? "checked" : ""}> ${d}</label>`).join("")}</div><small class="muted">Monday to Saturday with Sunday off is a demo assumption you can change here.</small></div></div>
  <button class="primary" id="psave">Save settings</button></div>
  <div class="card"><h2>Audit log</h2><label class="f" style="max-width:340px">Search<input id="asr" placeholder="Search by action, person, reason..."></label><div class="tw"><table><thead><tr><th>When</th><th>Who</th><th>What</th><th>On</th><th>Before</th><th>After</th><th>Why</th><th>Version</th></tr></thead><tbody id="arows"></tbody></table></div></div>`;
  const rows = (q) => { const f = au.filter((a) => !q || JSON.stringify(a).toLowerCase().includes(q.toLowerCase())); $("#arows").innerHTML = f.map((a) => `<tr><td class="nowrap">${esc(a.ts.replace("T", " "))}</td><td>${esc(a.role)}</td><td><b>${esc(a.action.replace(/_/g, " "))}</b></td><td>${esc(a.entity)}</td><td>${esc((a.before_val || "").slice(0, 80))}</td><td>${esc((a.after_val || "").slice(0, 80))}</td><td>${esc(a.reason || "")}</td><td>${esc(a.version_id || "")}</td></tr>`).join("") || `<tr><td colspan="8" class="muted">No entries match.</td></tr>`; };
  rows(""); $("#asr").oninput = (e) => rows(e.target.value);
  Object.keys(s.weight_labels).forEach((k) => { $("#pw_" + k).oninput = (e) => { e.target.nextElementSibling.textContent = e.target.value; }; });
  $("#psave").onclick = () => guard(async () => { const w = {}; Object.keys(s.weight_labels).forEach((k) => (w[k] = +$("#pw_" + k).value)); await post("/api/policy", { objective_weights: w, overtime_cap_hours: +$("#pot").value, working_weekdays: [...document.querySelectorAll(".wd:checked")].map((c) => +c.value), reason: "Settings screen" }); toast("Settings saved and recorded.", "ok"); render(); });
};

/* ---------- ABOUT / REQUIREMENTS ---------- */
PAGES.about = async (p) => {
  const r = await get("/api/requirements");
  const screen = { orders: "orders", workforce: "workforce", plan: "plan", gantt: "gantt", approval: "approval", mytasks: "mytasks", live: "live", reports: "reports", audit: "audit" };
  const SC = { orders: "Orders and Tasks", workforce: "Workforce and Skills", plan: "AI Allocation Proposal", gantt: "Schedule Chart", approval: "Approval and Changes", mytasks: "My Tasks", live: "Live Progress and Alerts", reports: "Reports", audit: "Audit and Settings" };
  const where = { "FR-01": "orders", "FR-02": "orders", "FR-03": "workforce", "FR-04": "workforce", "FR-05": "plan", "FR-06": "plan", "FR-07": "gantt", "FR-08": "plan", "FR-09": "plan", "FR-10": "approval", "FR-11": "mytasks", "FR-12": "live", "FR-13": "live", "FR-14": "reports", "FR-15": "audit" };
  p.innerHTML = `<h1>How it works and Requirements Coverage</h1><p class="help">The flow in one picture, what is real and what is simulated, and a checklist of the 15 requirements. A requirement gets a green tick only after the built-in self-test has run its check.</p>
  <div class="card"><h2>The flow</h2><div class="flow" style="color:#16202e">${["Order (Simulated ERP)", "Jobs from the routing", "Who is allowed (skills, certificates, leave)", "Planner (OR-Tools solver)", "Manager approval", "Back to the ERP (simulated)"].map((x, i) => `${i ? '<span class="arrow" style="color:#7b8aa3">&rarr;</span>' : ""}<span class="chip blue" style="font-size:15px;padding:6px 12px">${esc(x)}</span>`).join("")}</div>
  <ul><li><b>The planner</b> is Google OR-Tools CP-SAT, a free optimization engine. It alone decides who does what and when. It never uses an AI chat service.</li><li><b>The note reader</b>: ${esc(ST.state.note_reader.label)}. It only picks out known skills and certificates from a note. It does not understand free language and can miss other phrasings. ${ST.state.note_reader.mode === "keyword" ? "No outside AI service is called." : ""}</li><li><b>Simulated:</b> the ERP is a local database. All people, customers and orders are fictional. The system plans people and work only and never controls a machine.</li><li><b>Assumptions:</b> Monday to Saturday working, Sunday off; Shift A 06:00 to 14:00 and Shift B 14:00 to 22:00; overtime up to 2 hours a day; job time = routing minutes x 4 per lot of 10 pieces plus setup. All of these can be changed in Settings or the config file.</li><li><b>The role switcher</b> is a demonstration of permissions, not real security.</li></ul></div>
  <div class="card"><h2>Requirements checklist</h2><button class="primary" id="vrun">Run the self-test</button> <span class="muted" id="vstat">${r.selftest.state === "running" ? "Running..." : "The self-test runs the whole workflow on a scratch copy. Your demo data is not touched. It takes under a minute."}</span>
  <div class="tw" style="margin-top:10px"><table><thead><tr><th>Requirement</th><th>What it means</th><th>Status</th><th>Evidence</th><th></th></tr></thead><tbody>${r.items.map((x) => `<tr><td><b>${esc(x.fr_id)}</b></td><td>${esc(x.title)}</td><td>${x.status === "verified" ? chip("green", "Verified", "<i class=ic-check></i>") : x.status === "check failed" ? chip("red", "Check failed", "<i class=ic-cross></i>") : chip("grey", "Not yet verified")}</td><td style="font-size:14px">${esc(x.evidence)}</td><td><button class="sm" data-go="${esc(where[x.fr_id])}">Show me</button></td></tr>`).join("")}</tbody></table></div></div>`;
  p.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => go(b.dataset.go)));
  const poll = async () => { for (let i = 0; i < 120; i++) { await new Promise((r) => setTimeout(r, 2500)); const s = await get("/api/requirements"); if (s.selftest.state !== "running") { if (ST.page === "about") render(); return; } } };
  $("#vrun").onclick = () => guard(async () => { await post("/api/requirements/verify", {}, "Starting the self-test..."); $("#vstat").textContent = "Running... this page updates when it finishes."; poll(); });
  if (r.selftest.state === "running") poll();
};

function causeText(c) { return { affected: "directly affected", follows: "waits for an earlier job that moved", priority: "priority change", capacity: "moved to make room" }[c] || ""; }
function replanCause(df, r) {
  const b = df.by_cause || {}, o = (b.capacity || 0);
  return `Directly affected jobs: ${b.affected || 0}. Jobs that wait for them in the same order: ${b.follows || 0}.` + (o ? ` ${o} other job(s) also had to move to make room, because no other valid plan existed.` : " No unrelated job moved.");
}
