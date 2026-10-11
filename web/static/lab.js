// Follow It · Lab dashboard. Vanilla ES module. Pure helpers are exported for node tests.

const AGENTS = {
  red: { icon: "🔴", name: "Red" },
  blue: { icon: "🔵", name: "Blue" },
  gate: { icon: "⚖️", name: "Gate" },
  system: { icon: "⚙️", name: "System" },
};
const DEVICE_ORDER = ["mouse", "trackpad", "touch"];

const num = (v) => (typeof v === "number" ? String(Math.round(v * 1000) / 1000) : String(v));

export function formatArgs(args) {
  if (!args || typeof args !== "object") return "";
  return Object.entries(args)
    .map(([k, v]) => {
      if (k === "lag_ms") return `lag ${num(v)} ms`;
      if (k === "noise_px") return `noise ${num(v)}`;
      return `${k}=${typeof v === "object" ? JSON.stringify(v) : num(v)}`;
    })
    .join(", ");
}

export function verdictLabel(v) {
  if (v === "reject") return "REJECT";
  if (v === "approve_for_review") return "APPROVE FOR REVIEW";
  return String(v || "").toUpperCase();
}

export function countText(n, total) {
  return n == null || total == null ? "—" : `${n} of ${total}`;
}

/** LabEvent -> {cls, text}. cls: line style key. */
export function formatEvent(ev) {
  const a = AGENTS[ev.agent] || { icon: "•", name: String(ev.agent || "?") };
  const d = ev.data || {};
  const who = `${a.icon} ${a.name}`;
  const base = ev.agent === "red" || ev.agent === "blue" ? ev.agent : "";
  switch (ev.type) {
    case "round_started":
      return { cls: base, text: `${who} round ${d.round ?? "?"} started` };
    case "tool_call": {
      if (d.tool === "propose_variant" && d.args && d.args.id) {
        return { cls: base, text: `${who} tool_call propose_variant ${d.args.id}${d.args.change ? ": " + d.args.change : ""}` };
      }
      return { cls: base, text: `${who} tool_call ${d.tool}(${formatArgs(d.args)})` };
    }
    case "tool_result":
      return { cls: base, text: `${who} ↳ ${d.summary ?? ""}` };
    case "attempt_scored": {
      const verdict = d.pass ? "✔ passed" : `✘ failed${d.failed && d.failed.length ? ": " + d.failed.join(", ") : ""}`;
      return { cls: base, text: `${who} attempt ${d.attempt_id} → score ${num(d.score)} ${verdict}` };
    }
    case "gate_result": {
      const why = d.reasons && d.reasons.length ? d.reasons.join("; ") : `forgeries ${countText(d.forgeries_passed?.candidate, d.forgeries_passed?.total)} vs baseline ${d.forgeries_passed?.baseline ?? "?"}, no extra human rejections`;
      return { cls: "gate", text: `⚖️ Gate ${d.candidate} vs ${d.baseline} → ${verdictLabel(d.verdict)} (${why})` };
    }
    case "approval_needed":
      return { cls: "gate", text: `🟡 Approval needed for ${d.variant_id} (${d.approval_id})` };
    case "round_report":
      return { cls: "report", text: `${a.icon} ${a.name} round ${d.round ?? "?"}: ${d.passed} of ${d.attempts} passed — ${d.what_changed ?? ""}` };
    case "variant_activated":
      return { cls: "live", text: `✅ ${d.variant_id} is now live` };
    case "error":
      return { cls: "error", text: `❌ ${a.name} error: ${d.message ?? d.error ?? JSON.stringify(d)}` };
    default:
      return { cls: base, text: `${who} ${ev.type} ${JSON.stringify(d)}` };
  }
}

/** Lines describing a GateResult, for the Decision card. */
export function gateSummaryLines(g) {
  const lines = [];
  const f = g.forgeries_passed || {};
  lines.push(`Forgeries passed: ${countText(f.candidate, f.total)} (baseline ${countText(f.baseline, f.total)})`);
  for (const dev of deviceList([g])) {
    const h = g.humans_rejected[dev];
    lines.push(`Humans rejected, ${dev}: ${countText(h.candidate, h.total)} (baseline ${h.baseline})`);
  }
  lines.push(`Gate verdict: ${verdictLabel(g.verdict)}`);
  for (const r of g.reasons || []) lines.push(`Reason: ${r}`);
  return lines;
}

function deviceList(gates) {
  const seen = new Set();
  for (const g of gates) for (const k of Object.keys(g.humans_rejected || {})) seen.add(k);
  return [...DEVICE_ORDER.filter((d) => seen.has(d)), ...[...seen].filter((d) => !DEVICE_ORDER.includes(d))];
}

/**
 * Build comparison rows.
 * variants: [{id,...}], gates: [GateResult] in arrival order, activeId: string|null.
 * Row: {id, active, forgeries, humans:[{device,text}], verdict, verdictClass, reasons}
 */
export function buildRows(variants, gates, activeId) {
  const ids = [];
  const add = (id) => id && !ids.includes(id) && ids.push(id);
  (variants || []).forEach((v) => add(v.id));
  gates.forEach((g) => { add(g.baseline); add(g.candidate); });
  if (activeId) add(activeId);
  const last = (fn) => { for (let i = gates.length - 1; i >= 0; i--) if (fn(gates[i])) return gates[i]; return null; };
  return ids.map((id) => {
    const cg = last((g) => g.candidate === id);
    const bg = last((g) => g.baseline === id);
    const src = cg || bg; // candidate numbers win
    const key = cg ? "candidate" : "baseline";
    const row = { id, active: id === activeId, forgeries: "—", humans: [], verdict: "not gated", verdictClass: "base", reasons: [] };
    if (src) {
      const f = src.forgeries_passed || {};
      row.forgeries = countText(f[key], f.total);
      for (const dev of deviceList([src])) {
        const h = src.humans_rejected[dev];
        row.humans.push({ device: dev, text: countText(h[key], h.total) });
      }
    }
    if (cg) {
      row.verdict = verdictLabel(cg.verdict);
      row.verdictClass = cg.verdict === "reject" ? "bad" : "ok";
      row.reasons = cg.reasons || [];
    } else if (bg) {
      row.verdict = "baseline";
    }
    return row;
  });
}

// ---------------------------------------------------------------- browser part
function boot() {
  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const state = { key: null, variants: [], gates: [], activeId: null, approvals: new Map(), es: null };
  // A replayed run only posts events; the DB never changes, so the events decide which variant is active.
  const replay = params.get("replay") === "1";

  if (replay) $("replay-banner").hidden = false;

  const toast = (m) => { $("toast").textContent = m || ""; };
  const getKey = () => { try { return localStorage.getItem("followit_lab_key"); } catch { return null; } };
  const setKey = (k) => { try { k ? localStorage.setItem("followit_lab_key", k) : localStorage.removeItem("followit_lab_key"); } catch { /* ignore */ } };

  function setConn(on) {
    const c = $("conn");
    c.textContent = on ? "● live" : "○ reconnecting…";
    c.className = "badge " + (on ? "conn-on" : "conn-off");
  }

  async function api(method, path, body) {
    const opts = { method, headers: { "X-Lab-Key": state.key || "" } };
    if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    const r = await fetch(path, opts);
    if (r.status === 403) { badKey(); throw new Error("403 bad lab key"); }
    if (!r.ok) throw new Error(`${method} ${path} → ${r.status}`);
    return r.status === 204 ? null : r.json().catch(() => null);
  }

  function badKey(msg = "Lab key rejected. Enter it again.") {
    setKey(null); state.key = null;
    if (state.es) { state.es.close(); state.es = null; }
    setConn(false);
    $("keymsg").textContent = msg;
    $("keyprompt").hidden = false;
    $("keyinput").focus();
  }

  // ---- log
  const log = $("log");
  function addLine({ cls, text }) {
    const stick = log.scrollTop + log.clientHeight >= log.scrollHeight - 40;
    const div = document.createElement("div");
    div.className = "line " + (cls || "");
    div.textContent = text;
    log.appendChild(div);
    while (log.childElementCount > 500) log.firstChild.remove();
    if (stick) log.scrollTop = log.scrollHeight;
  }

  // ---- comparison
  function renderCmp() {
    const rows = buildRows(state.variants, state.gates, state.activeId);
    const root = $("cmp");
    root.textContent = "";
    if (!rows.length) { root.innerHTML = '<p class="muted">No variants yet.</p>'; return; }
    const t = document.createElement("table");
    const head = t.createTHead().insertRow();
    ["Variant", "Forgeries passed", "Humans rejected (mouse · trackpad · touch)", "Gate verdict"].forEach((h) => {
      const th = document.createElement("th"); th.scope = "col"; th.textContent = h; head.appendChild(th);
    });
    for (const r of rows) {
      const tb = t.createTBody();
      const tr = tb.insertRow();
      if (r.active) tr.className = "active";
      tr.insertCell().textContent = r.id + (r.active ? " (active)" : "");
      tr.insertCell().textContent = r.forgeries;
      tr.insertCell().textContent = r.humans.length ? r.humans.map((h) => `${h.device} ${h.text}`).join(" · ") : "—";
      const vc = tr.insertCell();
      vc.textContent = (r.verdictClass === "ok" ? "✔ " : r.verdictClass === "bad" ? "✘ " : "") + r.verdict;
      vc.className = "verdict-" + r.verdictClass;
      if (r.reasons.length) {
        const rr = tb.insertRow(); rr.className = "reasons";
        const c = rr.insertCell(); c.colSpan = 4; c.textContent = r.reasons.join("; ");
      }
    }
    root.appendChild(t);
  }

  async function refreshVariants() {
    try {
      const [vs, act] = await Promise.all([api("GET", "/v1/variants"), api("GET", "/v1/variants/active")]);
      if (Array.isArray(vs)) state.variants = vs;
      if (act && act.id && !(replay && state.activeId)) state.activeId = act.id;
    } catch (e) { toast(String(e.message || e)); }
    renderCmp();
  }

  // ---- decision
  function showApproval(d) {
    if (state.approvals.has(d.approval_id)) return;
    const dec = $("decision");
    if (!state.approvals.size) dec.textContent = "";
    const card = document.createElement("div");
    card.className = "card";
    const h = document.createElement("h3");
    h.textContent = `Approve ${d.variant_id}?`;
    card.appendChild(h);
    const ul = document.createElement("ul");
    for (const l of gateSummaryLines(d.gate || {})) { const li = document.createElement("li"); li.textContent = l; ul.appendChild(li); }
    card.appendChild(ul);
    const btns = document.createElement("div"); btns.className = "btns";
    const ok = document.createElement("button"); ok.type = "button"; ok.className = "btn-approve"; ok.textContent = "✔ Approve";
    const no = document.createElement("button"); no.type = "button"; no.className = "btn-deny"; no.textContent = "✘ Deny";
    btns.append(ok, no); card.appendChild(btns);
    const out = document.createElement("div"); out.className = "outcome"; out.setAttribute("role", "status"); card.appendChild(out);
    dec.prepend(card);
    const entry = { ok, no, out, decided: false };
    state.approvals.set(d.approval_id, entry);
    const decide = async (approve) => {
      ok.disabled = no.disabled = true; entry.decided = true;
      out.textContent = "Sending…"; out.className = "outcome";
      try {
        await api("POST", `/v1/lab/approvals/${encodeURIComponent(d.approval_id)}/decide`, { approve });
        setOutcome(d.approval_id, approve);
      } catch (e) {
        ok.disabled = no.disabled = false; entry.decided = false;
        out.textContent = "Failed: " + (e.message || e); out.className = "outcome bad";
      }
    };
    ok.addEventListener("click", () => decide(true));
    no.addEventListener("click", () => decide(false));
  }
  function setOutcome(id, approved) {
    const e = state.approvals.get(id);
    if (!e) return;
    e.ok.disabled = e.no.disabled = true;
    e.out.textContent = approved ? "✔ Approved" : "✘ Denied";
    e.out.className = "outcome " + (approved ? "ok" : "bad");
  }

  // ---- events
  function onEvent(ev) {
    addLine(formatEvent(ev));
    const d = ev.data || {};
    if (ev.type === "gate_result") { state.gates.push(d); renderCmp(); refreshVariants(); }
    else if (ev.type === "approval_needed") showApproval(d);
    else if (ev.type === "variant_activated") {
      state.activeId = d.variant_id; renderCmp(); refreshVariants();
      if (d.approval_id) { showApproval({ approval_id: d.approval_id, variant_id: d.variant_id, gate: {} }); setOutcome(d.approval_id, true); }
    }
  }

  function connect() {
    if (state.es) state.es.close();
    const es = new EventSource("/v1/lab/stream?key=" + encodeURIComponent(state.key));
    state.es = es;
    es.onopen = () => { log.textContent = ""; setConn(true); };
    es.onmessage = (m) => { try { onEvent(JSON.parse(m.data)); } catch (e) { console.error("bad event", e); } };
    es.onerror = async () => {
      setConn(false);
      try { // EventSource hides the status; probe to detect a bad key
        const r = await fetch("/v1/variants/active", { headers: { "X-Lab-Key": state.key || "" } });
        if (r.status === 403) badKey();
      } catch { /* offline: EventSource retries by itself */ }
    };
  }

  // ---- buttons
  async function run(kind) {
    toast("");
    try { await api("POST", "/v1/lab/runs", { kind }); toast(""); }
    catch (e) { toast(String(e.message || e)); }
  }
  $("btn-red").addEventListener("click", () => run("red"));
  $("btn-blue").addEventListener("click", () => run("blue"));
  $("btn-reset").addEventListener("click", async () => {
    if (!confirm("Reset the demo? This deletes red attempts, approvals and candidate variants.")) return;
    try { await api("POST", "/v1/lab/reset"); location.reload(); }
    catch (e) { toast(String(e.message || e)); }
  });

  fetch("/healthz").then((r) => r.json()).then((h) => { if (h && h.engine === "stubs") $("stub-badge").hidden = false; }).catch(() => {});

  function start() {
    $("keyprompt").hidden = true;
    renderCmp();
    refreshVariants();
    connect();
  }
  $("keyform").addEventListener("submit", (e) => {
    e.preventDefault();
    const k = $("keyinput").value.trim();
    if (!k) return;
    setKey(k); state.key = k; $("keyinput").value = ""; $("keymsg").textContent = "";
    start();
  });

  state.key = getKey();
  if (state.key) start(); else badKey("Enter the lab key to continue.");
}

if (typeof document !== "undefined") boot();
