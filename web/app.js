/* Precedent AP workbench — vanilla JS, no build step. */
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const inr = (x) => (x == null ? "—" : "₹" + Math.round(x).toLocaleString("en-IN"));
const inrShort = (x) => (x >= 1e5 ? "₹" + (x / 1e5).toFixed(x >= 1e6 ? 1 : 2) + "L" : inr(x));
const fmtDate = (iso) => new Date(iso + (iso.length === 10 ? "T00:00:00" : "")).toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
const ACTION_LABEL = { approve: "Approve", approve_adjusted: "Short-pay", reject: "Reject", hold: "Hold", schedule_early_payment: "Pay early (discount)" };
const BASIS_LABEL = { full: "Full invoice", at_po_price: "At PO price", received_qty_only: "Received qty only (GRN)", without_charges: "Strike extra charges",
  cap_charges: "Cap charges at…", early_payment_discount: "Early-payment discount", zero: "Nothing (reject / hold)" };
const GRADE = {
  straight_through: ["b-straight", "Straight-through"], correct_auto: ["b-auto", "Auto-resolved"], wrong_auto: ["b-wrong", "Overridden"],
  correct_escalation: ["b-human", "Human"], missed_automation: ["b-human", "Human"], pending: ["b-pending", "Deciding…"], queued: ["", ""],
};

let S = null;          // last /api/state
let viewing = null;    // invoice_id the user clicked (null = follow current)
let autopilot = false;
let busy = false;

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}
function toast(msg, ms = 3200) { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), ms); }
function setBusy(b, label) {
  busy = b;
  for (const id of ["nextBtn", "resetBtn"]) $("#" + id).disabled = b || autopilot;
  $("#nextBtn").innerHTML = b && label ? `<span class="spinner"></span>${esc(label)}` : "Next invoice";
}

// ------------------------------------------------------------------ render
function render(state) {
  S = state;
  const hs = state.memory_backend === "hindsight";
  const bp = $("#backendPill");
  bp.className = "pill " + (hs ? "ok" : "warn");
  bp.textContent = hs ? `Hindsight · bank ${state.bank_id}` : "Local test double (set HINDSIGHT_BASE_URL)";
  const lp = $("#llmPill");
  lp.className = "pill " + (state.llm === "disabled" ? "warn" : "ok");
  lp.textContent = state.llm === "disabled" ? "LLM off · heuristic mode" : state.llm;
  $("#memToggle").checked = state.use_memory;
  $("#autoBtn").textContent = autopilot ? "❚❚ Pause" : state.done ? "✓ Done" : "▶ Autopilot";
  $("#autoBtn").disabled = state.done && !autopilot;
  $("#nextBtn").disabled = busy || autopilot || state.done || !!(state.pending && state.pending.decision.route !== "straight_through");
  renderQueue(state);
  renderKpis(state.metrics, state.use_memory);
  renderChart(state.timeline);
  renderFeed(state.feed);
  if (!viewing) renderDetail(state.current, !!state.pending);
}

function renderQueue(state) {
  const q = $("#queue");
  const cur = viewing || state.current?.invoice.invoice_id;
  q.innerHTML = state.queue.map((it) => {
    const [cls, label] = GRADE[it.status] || ["", ""];
    const done = !["queued"].includes(it.status);
    return `<li class="${done ? "done" : "queued"} ${cur === it.invoice_id ? "active" : ""}" data-id="${it.invoice_id}">
      <span class="q-vendor">${esc(it.vendor)}</span><span class="q-amt">${inrShort(it.total_inr)}</span>
      <span class="q-meta">${esc(it.invoice_number)} · ${fmtDate(it.date)}</span>
      <span class="q-status">${label ? `<span class="badge ${cls}">${label}</span>` : ""}</span></li>`;
  }).join("");
  $("#inboxCount").textContent = `${state.metrics.processed}/${state.metrics.total}`;
  const active = $(".queue li.active");
  if (active && !viewing) active.scrollIntoView({ block: "nearest" });
}

function renderKpis(m, useMemory) {
  const pct = (x) => Math.round(x * 100) + "%";
  const hours = (m.minutes_saved / 60).toFixed(1);
  $("#kpis").innerHTML = [
    ["Auto-resolved (last 10)", pct(m.auto_rate_last10), `${m.auto_resolved} of ${m.exceptions} exceptions overall`, "k-good"],
    ["Human touches", `${m.human_touches}`, `vs ${m.exceptions} without memory`, "k-warn"],
    ["Clerk time saved", `${hours} h`, `${m.auto_resolved} × ${Math.round(m.minutes_saved / Math.max(1, m.auto_resolved)) || 18} min`, "k-info"],
    ["Wrong auto-decisions", `${m.wrong_auto}`, "overridden by the AP lead", m.wrong_auto ? "k-crit" : "k-good"],
    ["Overbilling stopped", inrShort(m.value_protected_inr), "short-pays, rejects, holds", "k-info"],
    ["Discounts captured", inrShort(m.discount_captured_inr), "early-payment terms", "k-good"],
  ].map(([l, v, s, k]) => `<div class="kpi ${k}"><div class="v">${v}</div><div class="l">${l}</div><div class="s">${esc(s)}</div></div>`).join("")
    + (useMemory ? "" : `<div class="kpi" style="grid-column:1/-1;background:var(--warn-bg)"><div class="l"><b>Memory is OFF.</b> The agent can't recall anything, so every exception lands on a human.</div></div>`);
}

function renderChart(tl) {
  const el = $("#chart");
  const W = el.clientWidth || 320, H = el.clientHeight || 190, P = { l: 28, r: 64, t: 10, b: 22 };
  if (!tl.length) { el.innerHTML = `<div class="none" style="padding-top:70px;text-align:center">The curve appears as invoices are processed.</div>`; return; }
  const n = Math.max(29, tl.length), maxY = Math.max(5, ...tl.map((d) => d.baseline_cum));
  const x = (i) => P.l + ((i - 1) / (n - 1)) * (W - P.l - P.r), y = (v) => H - P.b - (v / maxY) * (H - P.t - P.b);
  const path = (k) => tl.map((d, i) => `${i ? "L" : "M"}${x(d.n).toFixed(1)},${y(d[k]).toFixed(1)}`).join("");
  const ticks = [0, Math.round(maxY / 2), maxY];
  const last = tl[tl.length - 1];
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <g class="grid">${ticks.map((t) => `<line x1="${P.l}" x2="${W - P.r}" y1="${y(t)}" y2="${y(t)}"/>`).join("")}</g>
    <g class="axis">${ticks.map((t) => `<text x="${P.l - 6}" y="${y(t) + 3}" text-anchor="end">${t}</text>`).join("")}
      <text x="${P.l}" y="${H - 6}">${fmtDate(tl[0].date)}</text><text x="${W - P.r}" y="${H - 6}" text-anchor="end">invoice ${n}</text></g>
    <path class="l2" d="${path("baseline_cum")}"/><path class="l1" d="${path("human_cum")}"/>
    <circle class="dot2" r="4" cx="${x(last.n)}" cy="${y(last.baseline_cum)}"/><circle class="dot1" r="4" cx="${x(last.n)}" cy="${y(last.human_cum)}"/>
    ${last.baseline_cum === last.human_cum
      ? `<text class="dlabel" x="${x(last.n) + 8}" y="${y(last.human_cum) + 4}">${last.human_cum} (both)</text>`
      : `<text class="dlabel" x="${x(last.n) + 8}" y="${Math.min(y(last.baseline_cum) + 4, y(last.human_cum) - 10)}">${last.baseline_cum} no memory</text>
         <text class="dlabel" x="${x(last.n) + 8}" y="${Math.max(y(last.human_cum) + 4, y(last.baseline_cum) + 18)}">${last.human_cum} with memory</text>`}
    <line class="xhair" id="xhair" y1="${P.t}" y2="${H - P.b}" x1="-10" x2="-10"/>
    <rect id="hit" x="${P.l}" y="0" width="${W - P.l - P.r}" height="${H}" fill="transparent"/></svg><div class="tip" id="tip" hidden></div>`;
  const hit = $("#hit", el), tip = $("#tip", el), xh = $("#xhair", el);
  hit.addEventListener("mousemove", (ev) => {
    const r = el.getBoundingClientRect(), px = ((ev.clientX - r.left) / r.width) * W;
    const i = Math.min(tl.length - 1, Math.max(0, Math.round(((px - P.l) / (W - P.l - P.r)) * (n - 1))));
    const d = tl[i]; if (!d) return;
    xh.setAttribute("x1", x(d.n)); xh.setAttribute("x2", x(d.n));
    tip.hidden = false;
    tip.innerHTML = `<div class="muted">#${d.n} · ${fmtDate(d.date)} · ${esc(d.vendor)}</div>With memory <b>${d.human_cum}</b> · Without <b>${d.baseline_cum}</b>`;
    const left = (x(d.n) / W) * r.width; tip.style.left = Math.min(r.width - 200, Math.max(0, left - 90)) + "px"; tip.style.top = "-4px";
  });
  hit.addEventListener("mouseleave", () => { tip.hidden = true; xh.setAttribute("x1", -10); xh.setAttribute("x2", -10); });
}

// Long memory text -> one short, readable line (full text stays one click away).
const clip = (s, n = 150) => (s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s);
function memorySummary(text) {
  const outcome = (text.match(/Outcome:\s*([A-Z_]+)/) || [])[1];
  const reason = (text.match(/Reason:\s*([\s\S]*)$/) || [])[1];
  const head = reason ? reason.trim() : text.split(" | ")[0].trim();
  return { outcome: outcome ? outcome.toLowerCase() : null, head: clip(head) };
}
const outcomeChip = (o) => (o ? `<span class="chip-out o-${esc(o)}">${esc(ACTION_LABEL[o] || o)}</span>` : "");

function renderFeed(feed) {
  $("#feed").innerHTML = feed.length ? feed.map((f) => {
    const m = memorySummary(f.text);
    return `<li class="${f.policy ? "policy" : ""}"><details><summary><span class="who">${esc(f.vendor)}</span>${outcomeChip(m.outcome)}${f.policy ? `<span class="chip-out o-policy">+ policy</span>` : ""}
      <span class="snip">${esc(m.head)}</span></summary><div class="full">${esc(f.text)}</div></details></li>`;
  }).join("") : `<li class="muted">Nothing yet. Resolve an exception and it lands here.</li>`;
}

function daysBefore(occurred, invDate) {
  if (!occurred) return "";
  const d = (new Date(invDate) - new Date(occurred.slice(0, 10))) / 864e5;
  return isFinite(d) ? (d <= 0 ? "same day" : `${Math.round(d)} days earlier`) : "";
}

function renderDetail(v, isPending) {
  const box = $("#detail");
  if (!v) { box.hidden = true; $("#emptyState").hidden = false; return; }
  $("#emptyState").hidden = true; box.hidden = false;
  const { invoice: inv, vendor, po, grn, decision: d } = v;
  const poLine = Object.fromEntries((po?.lines || []).map((l) => [l.sku, l]));
  const grnQ = Object.fromEntries((grn?.lines || []).map((l) => [l.sku, l.qty_received]));
  const route = d.route, pendingHere = isPending && S.pending && S.pending.invoice.invoice_id === inv.invoice_id;
  const [gcls, glabel] = pendingHere ? (route === "auto" ? ["b-auto", "Agent wants to auto-resolve"] : ["b-human", "Needs you"]) : (GRADE[v.grade] || ["", ""]);
  const bankChanged = vendor.bank_account.account !== inv.bank_account.account;

  const lines = inv.lines.map((l) => {
    const p = poLine[l.sku];
    const priceDiff = p && p.uom === l.uom && Math.abs(p.unit_price - l.unit_price) > 0.001;
    const uomDiff = p && p.uom !== l.uom;
    const rec = grnQ[l.sku];
    return `<tr><td>${esc(l.description)}</td><td class="num ${uomDiff ? "diff" : ""}">${l.qty} ${esc(l.uom)}</td>
      <td class="num">${p ? `${p.qty} ${esc(p.uom)}` : "—"}</td><td class="num ${rec != null && !uomDiff && rec < l.qty ? "diff" : ""}">${rec ?? "—"}</td>
      <td class="num ${priceDiff ? "diff" : ""}">${l.unit_price.toLocaleString("en-IN")}</td><td class="num">${p ? p.unit_price.toLocaleString("en-IN") : "—"}</td>
      <td class="num">${(l.qty * l.unit_price).toLocaleString("en-IN", { maximumFractionDigits: 0 })}</td></tr>`;
  }).join("") + inv.charges.map((c) => `<tr><td>${esc(c.description)}</td><td></td><td class="num diff">not on PO</td><td></td><td></td><td></td><td class="num diff">${c.amount.toLocaleString("en-IN")}</td></tr>`).join("");

  const excs = d.exceptions.length ? d.exceptions.map((e) => `<div class="exc ${e.severity}"><span class="code">${esc(e.code)}</span><span>${esc(e.summary)}</span></div>`).join("")
    : `<div class="none">None — price, quantity, receipt, tax and bank details all agree.</div>`;

  const vendorPrec = d.precedents.filter((p) => p.scope === "vendor"), hints = d.precedents.filter((p) => p.scope !== "vendor");
  const precCard = (p) => {
    const used = d.precedents_used.includes(p.id);
    const out = (p.tags.find((t) => t.startsWith("outcome:")) || "").slice(8) || memorySummary(p.text).outcome;
    const long = p.text.length > 160;
    return `<div class="prec ${used ? "used" : ""}"><div class="meta">${used ? `<span class="used-tag">✓ cited</span>` : ""}${outcomeChip(out)}
      <span>${p.occurred ? fmtDate(p.occurred.slice(0, 10)) : ""}</span><span>${daysBefore(p.occurred, inv.received_on)}</span></div>
      <div class="text">${esc(memorySummary(p.text).head)}</div>
      ${long ? `<details class="more"><summary>Full memory</summary><div class="full">${esc(p.text)}</div></details>` : ""}</div>`;
  };
  const memorySection = route === "straight_through" ? "" : `
    <div class="card"><div class="card-head"><h3>Recalled from Hindsight</h3><span class="badge soft">recall · tag vendor:${esc(vendor.vendor_id)}</span></div>
      ${!d.memory_enabled ? `<div class="none">Memory is off — nothing recalled.</div>` : vendorPrec.length ? `<div class="precedents">${vendorPrec.map(precCard).join("")}</div>` : `<div class="none">No precedent for ${esc(vendor.name)} yet. This is the first time the agent has seen this.</div>`}
      ${hints.length ? `<div class="card-head" style="margin-top:12px"><h3>Pattern hints — other vendors</h3><span class="badge soft">not citable</span></div><div class="precedents">${hints.map(precCard).join("")}</div>` : ""}
      ${d.directives_applied.length ? `<div class="card-head" style="margin-top:12px"><h3>Directives applied</h3></div>${d.directives_applied.map((x) => `<div class="exc critical"><span class="code">policy</span><span>${esc(x)}</span></div>`).join("")}` : ""}
    </div>`;

  const decisionCard = `
    <div class="card decision ${route === "auto" ? "auto" : route === "human" ? "human" : "straight"}">
      <div class="card-head"><h3>Agent decision</h3><span class="badge ${gcls}">${glabel}</span></div>
      <div class="verdict"><span class="action">${esc(ACTION_LABEL[d.action] || d.action || "—")}</span><span class="pay">${inr(d.payable_amount)}</span>
        <span class="conf">confidence <span class="bar"><i style="width:${Math.round(d.confidence * 100)}%"></i></span>${Math.round(d.confidence * 100)}%</span></div>
      ${d.reasoning ? `<p class="reason">${esc(d.reasoning)}</p>` : ""}
      ${d.conditions_checked.length ? `<ul class="checks">${d.conditions_checked.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>` : ""}
      ${d.guardrail ? `<div class="guard"><b>Routed to a human:</b>${esc(d.guardrail)}</div>` : ""}
      <div class="byline">${d.decided_by === "llm" ? "LLM decision" : d.decided_by === "heuristic" ? "Deterministic fallback (LLM unavailable)" : "Rules engine"} · ${d.latency_ms} ms · basis: ${esc(BASIS_LABEL[d.payable_basis] || d.payable_basis || "—")}</div>
      ${pendingHere && route !== "straight_through" ? `<div class="row"><button class="btn small ghost" id="compareBtn">Compare without memory</button></div><div id="compareOut"></div>` : ""}
    </div>`;

  const resolveCard = pendingHere && route !== "straight_through" ? resolveForm(v) : v.retained ? `
    <div class="card"><div class="card-head"><h3>Outcome</h3><span class="badge soft">${esc(ACTION_LABEL[v.final_action] || v.final_action)} · ${inr(v.final_payable)}</span></div>
      <div class="retained"><b>✓ Retained to Hindsight</b> <span>${esc(memorySummary(v.retained).head)}</span>
      <details class="more"><summary>What was stored</summary><div class="full">${esc(v.retained)}</div></details></div></div>` : "";

  box.innerHTML = `
    <div class="card">
      <div class="inv-head"><div><h2>${esc(vendor.name)}</h2>
        <div class="inv-sub">${esc(inv.invoice_number)} · ${esc(vendor.category)} · ${esc(vendor.city)}</div></div>
        <div class="inv-total"><div class="amt">${inr(inv.total_inr)}</div><div class="inv-sub">${inv.currency !== "INR" ? `${inv.currency} ${inv.total.toLocaleString()} @ ${inv.fx_rate} · ` : ""}${esc(inv.tax_type)}</div></div></div>
      <dl class="facts">
        <div><dt>Invoice date</dt><dd>${fmtDate(inv.date)} 2026</dd></div><div><dt>Received</dt><dd>${fmtDate(inv.received_on)}</dd></div>
        <div><dt>PO</dt><dd>${esc(inv.po_number || "—")}</dd></div><div><dt>Terms</dt><dd>${esc(inv.payment_terms)}</dd></div>
        <div><dt>Remit to</dt><dd style="${bankChanged ? "color:var(--crit);font-weight:700" : ""}">${esc(inv.bank_account.bank)} ••${esc(inv.bank_account.account.slice(-4))}</dd></div>
        <div><dt>GSTIN</dt><dd>${esc(vendor.gstin || "foreign")}</dd></div></dl>
      <details class="lines"><summary>Line items · invoice vs PO vs GRN (${inv.lines.length + inv.charges.length})</summary>
      <div class="table-wrap"><table><thead><tr><th>Line</th><th class="num">Billed</th><th class="num">PO</th><th class="num">GRN</th><th class="num">Price</th><th class="num">PO price</th><th class="num">Value</th></tr></thead><tbody>${lines}</tbody></table></div></details>
    </div>
    <div class="card"><div class="card-head"><h3>3-way match exceptions</h3><span class="badge soft">${d.exceptions.length}</span></div><div class="exceptions">${excs}</div></div>
    ${decisionCard}${memorySection}${resolveCard}`;
  wireDetail(v);
}

function resolveForm(v) {
  const d = v.decision, opts = v.payable_options;
  const isAuto = d.route === "auto";
  const actionOpts = Object.entries(ACTION_LABEL).map(([k, l]) => `<option value="${k}" ${k === d.action ? "selected" : ""}>${l}</option>`).join("");
  const basisOpts = Object.keys(BASIS_LABEL).filter((k) => k === "cap_charges" ? v.invoice.charges.length : k in opts)
    .map((k) => `<option value="${k}" ${k === d.payable_basis ? "selected" : ""}>${BASIS_LABEL[k]}${k in opts && k !== "cap_charges" ? " — " + inr(opts[k]) : ""}</option>`).join("");
  return `<div class="card"><div class="card-head"><h3>${isAuto ? "Confirm or override" : "Your decision — the agent learns from it"}</h3><span class="badge soft">→ retain</span></div>
    ${isAuto ? `<div class="row" style="margin-top:0"><button class="btn good" id="acceptBtn">✓ Accept agent decision</button><button class="btn ghost" id="overrideBtn">Override…</button><button class="btn ghost" id="recordedBtn" title="What the AP lead actually decided">Use AP lead's recorded decision</button></div>` : ""}
    <form id="resolveForm" ${isAuto ? "hidden" : ""} style="margin-top:${isAuto ? "12px" : "0"}">
      <div class="resolve-grid">
        <label class="field">Action<select name="action">${actionOpts}</select></label>
        <label class="field">Pay<select name="basis">${basisOpts}</select></label>
        <label class="field" id="capField" ${d.payable_basis === "cap_charges" ? "" : "hidden"}>Charge cap (₹)<input name="charge_cap" type="number" min="0" step="100" value="${d.charge_cap ?? 3000}"></label>
      </div>
      <label class="field" style="margin-top:10px">Why? (this is what the agent will remember)<textarea name="note" placeholder="e.g. Contract clause 7.2 lets Deccan bill freight separately up to ₹3,000 per delivery."></textarea></label>
      <div class="row"><label class="check"><input type="checkbox" name="make_policy"> Make this a standing policy (Hindsight directive)</label></div>
      <div class="row"><button class="btn primary" type="submit">Resolve &amp; retain</button>${isAuto ? "" : `<button class="btn ghost" type="button" id="recordedBtn" title="Fill with what the AP lead actually decided">Use AP lead's recorded decision</button>`}</div>
    </form></div>`;
}

function wireDetail(v) {
  $("#acceptBtn")?.addEventListener("click", () => act(() => api("/api/resolve", { accept: true }), "Retaining…"));
  $("#overrideBtn")?.addEventListener("click", () => { $("#resolveForm").hidden = false; });
  $("#recordedBtn")?.addEventListener("click", () => act(() => api("/api/autopilot", {}).then((r) => r.state), "Retaining…"));
  $("#compareBtn")?.addEventListener("click", async (ev) => {
    ev.target.disabled = true; ev.target.innerHTML = `<span class="spinner"></span>Asking without memory…`;
    try {
      const off = await api("/api/compare", {});
      const on = v.decision;
      const col = (t, d) => `<div><h4>${t}</h4><b>${esc(ACTION_LABEL[d.action] || d.action)}</b> · ${inr(d.payable_amount)} · ${Math.round(d.confidence * 100)}%<p style="margin:6px 0 0">${esc(d.reasoning)}</p></div>`;
      $("#compareOut").innerHTML = `<div class="compare" style="margin-top:10px">${col("Without memory (stateless)", off)}${col("With Hindsight memory", on)}</div>`;
      ev.target.remove();
    } catch (e) { toast(e.message); ev.target.disabled = false; ev.target.textContent = "Compare without memory"; }
  });
  const form = $("#resolveForm");
  if (!form) return;
  form.basis.addEventListener("change", () => { $("#capField").hidden = form.basis.value !== "cap_charges"; });
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const body = { action: form.action.value, basis: form.basis.value, note: form.note.value, make_policy: form.make_policy.checked,
      charge_cap: form.basis.value === "cap_charges" ? Number(form.charge_cap.value) : null };
    if (["reject", "hold"].includes(body.action)) body.basis = "zero";
    act(() => api("/api/resolve", body), "Retaining…");
  });
}

// ------------------------------------------------------------------ actions
async function act(fn, label) {
  if (busy) return;
  setBusy(true, label);
  try { viewing = null; render(await fn()); } catch (e) { toast(e.message, 5000); } finally { setBusy(false); if (S) render(S); }
}

async function runAutopilot() {
  autopilot = !autopilot;
  render(S);
  while (autopilot && S && !S.done) {
    try {
      setBusy(true, "Autopilot…");
      const r = await api("/api/autopilot", {});
      viewing = null; render(r.state);
    } catch (e) { toast(e.message, 5000); autopilot = false; }
    finally { setBusy(false); }
    await new Promise((res) => setTimeout(res, 900));
  }
  autopilot = false; if (S) render(S);
}

$("#nextBtn").addEventListener("click", () => act(() => api("/api/next", {}), "Recalling…"));
$("#autoBtn").addEventListener("click", runAutopilot);
$("#resetBtn").addEventListener("click", () => {
  const b = $("#resetBtn");
  if (b.dataset.armed !== "1") { b.dataset.armed = "1"; b.textContent = "Wipe memory?"; setTimeout(() => { b.dataset.armed = ""; b.textContent = "Reset"; }, 3000); return; }
  b.dataset.armed = ""; b.textContent = "Reset";
  act(() => api("/api/reset", { use_memory: $("#memToggle").checked, wipe_memory: true }), "Resetting…");
});
$("#memToggle").addEventListener("change", (ev) => act(() => api("/api/reset", { use_memory: ev.target.checked, wipe_memory: ev.target.checked }), "Resetting…")
  .then(() => toast(ev.target.checked ? "Memory ON — fresh bank, inbox restarted." : "Memory OFF — inbox restarted. Watch every exception land on a human.")));
$("#queue").addEventListener("click", async (ev) => {
  const li = ev.target.closest("li.done"); if (!li) return;
  const id = li.dataset.id;
  if (S.current && id === S.current.invoice.invoice_id) { viewing = null; render(S); return; }
  try { const v = await api("/api/steps/" + id); viewing = id; renderDetail(v, false); renderQueue(S); } catch (e) { toast(e.message); }
});
$("#askForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const q = $("#askInput").value.trim(); if (!q) return;
  const out = $("#askOut"); out.hidden = false; out.innerHTML = `<span class="spinner"></span>Hindsight is reflecting over the AP history…`;
  try { const r = await api("/api/ask", { question: q }); out.textContent = r.answer || "(no answer)"; } catch (e) { out.textContent = e.message; }
});
$("#askChips").addEventListener("click", (ev) => { const b = ev.target.closest("button"); if (!b) return; $("#askInput").value = b.dataset.q; $("#askForm").requestSubmit(); });
$("#vendorSel").addEventListener("change", async (ev) => {
  const id = ev.target.value, box = $("#playbook"); if (!id) return;
  box.innerHTML = `<span class="spinner"></span>Loading…`;
  try { const r = await api(`/api/vendors/${id}/playbook`); box.textContent = r.content || "No playbook yet — Hindsight builds one after the first resolution for this vendor (it refreshes as memories consolidate)."; }
  catch (e) { box.textContent = e.message; }
});
window.addEventListener("resize", () => S && renderChart(S.timeline));

// Light / dark toggle (remembered per browser; falls back to the OS setting).
function applyTheme(t) {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  const dark = t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  $("#themeBtn").textContent = dark ? "☀" : "🌙";
}
try { applyTheme(localStorage.getItem("precedent-theme")); } catch { applyTheme(null); }
$("#themeBtn").addEventListener("click", () => {
  const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const next = cur === "dark" ? "light" : "dark";
  applyTheme(next);
  try { localStorage.setItem("precedent-theme", next); } catch {}
  if (S) renderChart(S.timeline);
});

(async function init() {
  const st = await api("/api/state");
  const vendors = [...new Map(st.queue.map((q) => [q.vendor_id, q.vendor])).entries()];
  $("#vendorSel").innerHTML = `<option value="">Select vendor…</option>` + vendors.map(([id, n]) => `<option value="${id}">${esc(n)}</option>`).join("");
  render(st);
})();
