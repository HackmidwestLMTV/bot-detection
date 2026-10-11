// Follow It · Lab dashboard. Vanilla ES module. Pure helpers are exported for node tests.

const AGENTS = {
  red: { icon: "🔴", name: "Red", role: "tests synthetic pointer traces" },
  blue: { icon: "🔵", name: "Blue", role: "writes a tougher rule" },
  gate: { icon: "⚖️", name: "Gate", role: "measures the cost" },
  system: { icon: "⚙️", name: "System", role: "" },
};
const DEVICE_ORDER = ["mouse", "trackpad", "touch"];

// Plain-language names for the agents' tools. The raw tool name is still printed on the
// detail line, so nothing is hidden -- the headline is just readable from across a room.
const TOOL_PLAIN = {
  forge_and_submit: "Submits a synthetic pointer trace",
  get_active_variant: "Reads the rule that is live",
  get_forgeries: "Reads the stored bot attempts",
  get_human_stats: "Reads human movement summary statistics",
  propose_variant: "Writes a tougher rule",
  run_gate: "Sends the rule to the gate",
  activate_variant: "Asks to make the rule live",
};

const num = (v) => (typeof v === "number" ? String(Math.round(v * 1000) / 1000) : String(v));
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** Server event time, never receipt time: reconnects/replays keep their original date. */
export function formatTimestamp(ts, { locale, timeZone } = {}) {
  const date = new Date(typeof ts === "number" && Number.isFinite(ts) ? ts * 1000 : NaN);
  if (!Number.isFinite(date.getTime())) return { label: "Time unavailable", title: "This event has no valid recorded timestamp", dateTime: "" };
  return {
    label: date.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23", timeZone }),
    title: date.toLocaleString(locale, { dateStyle: "full", timeStyle: "long", timeZone }),
    dateTime: date.toISOString(),
  };
}

export function stampedMessage(message, ts = Date.now() / 1000) {
  return message ? `[${formatTimestamp(ts).label}] ${message}` : "";
}

/** Variant ids are 36 characters of hex. Show enough to tell two apart; keep the rest in a title. */
export function shortId(id) {
  const s = String(id == null ? "" : id);
  return s.length > 14 ? s.slice(0, 11) + "…" : s;
}

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

/** A proposed rule, as bands a person can read: "jitter_px 2.6-6 · pass >= 0.75". */
export function bandText(args) {
  if (!args || typeof args !== "object") return "";
  const feats = args.features && typeof args.features === "object" ? args.features : {};
  const enabled = Array.isArray(args.enabled) ? args.enabled : Object.keys(feats);
  const parts = enabled
    .filter((k) => Array.isArray(feats[k]) && feats[k].length === 2)
    .map((k) => `${k} ${num(feats[k][0])}–${num(feats[k][1])}`);
  if (args.pass_threshold != null) parts.push(`pass ≥ ${num(args.pass_threshold)}`);
  return parts.join(" · ");
}

export function verdictLabel(v) {
  if (v === "reject") return "REJECT";
  if (v === "approve_for_review") return "APPROVE FOR REVIEW";
  return String(v || "").toUpperCase();
}

export function countText(n, total) {
  return n == null || total == null ? "—" : `${n} of ${total}`;
}

/** How many human traces a gate actually replayed, across every device group. */
export function gateHumanSample(gate) {
  const h = (gate && gate.humans_rejected) || {};
  let n = 0;
  for (const dev of Object.keys(h)) {
    const t = h[dev] && h[dev].total;
    if (typeof t === "number") n += t;
  }
  return n;
}

/**
 * Where the "humans rejected" numbers came from -- the one thing a judge must not misread.
 *
 * `/healthz` counts the human_test rows this lab actually holds for the current motion and
 * display: those are recordings made by a person in tester mode, and they are the only
 * human evidence the gate can legitimately be measuring. If a gate reports more human
 * traces than this lab can account for (a replayed recording, a seeded sample), the counts
 * on screen are stand-in data and the UI has to say so. Nothing here needs editing when
 * real traces arrive: the same comparison then reads as a measurement.
 *
 * health: /healthz body or null. gates: GateResults in arrival order. opts: {replay}.
 */
export function humanProvenance(health, gates, opts) {
  const replay = !!(opts && opts.replay);
  const sample = gateHumanSample((gates || []).at(-1));
  const traces = health && health.human_traces;
  const real = traces && typeof traces.total === "number" ? traces.total : null;
  const devices = traces ? DEVICE_ORDER.map((d) => `${d}: ${traces[d] || "untested"}`).join(" · ") : "";
  const pre = replay ? "Recorded run. " : "";
  const out = (o) => ({ real, sample, devices, ...o });

  if (real === null) {
    return out({
      state: "unknown", cls: "warn", tag: "UNVERIFIED", cellTag: "unverified",
      short: "this lab could not say how many real recordings it holds",
      tile: "This lab did not report how many recordings it holds from real people.",
      banner: "This lab could not say how many recordings it holds from real people, so every “humans rejected” number here is unverified. Do not read them as people.",
    });
  }
  if (sample > real) {
    return out({
      state: "synthetic", cls: "warn", tag: "NOT REAL PEOPLE", cellTag: "stand-in data",
      short: real === 0 ? "no real recordings exist here; these counts are stand-in data"
        : `only ${real} of the ${sample} traces behind these counts came from real people`,
      tile: real === 0
        ? "Nobody real has been recorded here, so every “humans rejected” count on this page is stand-in data."
        : `The counts here were measured against ${sample} traces — more than this lab holds from real people.`,
      banner: real === 0
        ? `${pre}No real person has been recorded on this lab. The ${plural(sample, "“human” trace")} behind the numbers below are stand-in data, made up so the gate had something to measure. They describe nobody.`
        : `${pre}This lab holds ${plural(real, "recording")} from real people, but the numbers below were measured against ${plural(sample, "trace")}. The rest is stand-in data, not people.`,
    });
  }
  if (real === 0) {
    return out({
      state: "none", cls: "warn", tag: "NO REAL PEOPLE YET", cellTag: "stand-in data",
      short: "nobody has been recorded on this lab yet",
      tile: "Nobody has recorded a hand movement on this lab yet. Until someone does, there is no human cost to measure.",
      banner: `${pre}No real person has been recorded on this lab yet, so there is nothing real to measure. Any “humans rejected” number here would be stand-in data, not people.`,
    });
  }
  return out({
    state: "real", cls: "real", tag: "REAL PEOPLE", cellTag: "real recordings",
    short: `measured against ${plural(real, "recording")} by real people`,
    tile: `Measured from ${plural(real, "recording")} made by real people on this lab.`,
    banner: `The “humans rejected” numbers below are measured against ${plural(real, "recording")} made by real people on this lab (${devices}). A pilot sample, not a calibration.`,
  });
}

/**
 * LabEvent -> a log entry.
 * {cls, icon, who, head, detail, text}: `head` is the sentence a stranger reads at a glance,
 * `detail` keeps the raw evidence, `text` is the whole thing on one line. ctx: {attempt}.
 */
export function formatEvent(ev, ctx) {
  const c = ctx || {};
  const a = AGENTS[ev.agent] || { icon: "•", name: String(ev.agent || "?"), role: "" };
  const d = ev.data || {};
  const base = ev.agent === "red" || ev.agent === "blue" ? ev.agent : "";
  const timestamp = formatTimestamp(ev.ts);
  const out = (cls, head, detail) => ({
    cls, icon: a.icon, who: a.name, head, detail: detail || "", timestamp,
    text: [`[${timestamp.label}] ${a.icon} ${a.name}`, head, detail].filter(Boolean).join(" · "),
  });

  switch (ev.type) {
    case "round_started":
      return out(base, `Round ${d.round ?? "?"} started`,
        `${a.name} ${a.role || "starts"}${d.variant ? ` against ${shortId(d.variant)}` : ""}`);
    case "tool_call": {
      const plain = TOOL_PLAIN[d.tool] || `Calls ${d.tool}`;
      if (d.tool === "propose_variant") {
        const id = d.args && d.args.id ? ` ${shortId(d.args.id)}` : "";
        const change = d.args && d.args.change ? `${d.args.change} · ` : "";
        return out(base, plain + id, `${change}${bandText(d.args) || formatArgs(d.args)}`);
      }
      return out(base, plain, `${d.tool}(${formatArgs(d.args)})`);
    }
    case "tool_result":
      return out(`${base} quiet`.trim(), "", `↳ ${d.summary ?? ""}`);
    case "attempt_scored": {
      const label = c.attempt ? `Forgery ${c.attempt}` : "Forgery";
      const head = d.pass ? `${label} — ✔ PASSED the live rule` : `${label} — ✘ blocked`;
      const bits = [`score ${num(d.score)}`];
      if (d.failed && d.failed.length) bits.push(`out of band: ${d.failed.join(", ")}`);
      if (d.attempt_id) bits.push(d.attempt_id);
      return out(`${base}${d.pass ? " hit" : ""}`.trim(), head, bits.join(" · "));
    }
    case "gate_result": {
      const f = d.forgeries_passed || {};
      const why = d.reasons && d.reasons.length
        ? d.reasons.join("; ")
        : `forgeries ${countText(f.candidate, f.total)} vs baseline ${f.baseline ?? "?"}, no extra human rejections`;
      return out("gate", `Gate: ${d.verdict === "reject" ? "✘ " : "✔ "}${verdictLabel(d.verdict)}`,
        `${shortId(d.candidate)} vs ${shortId(d.baseline)} — ${why}`);
    }
    case "approval_needed":
      return out("gate wait", "🟡 A person has to decide",
        `${shortId(d.variant_id)} is waiting for approval · ${d.approval_id}`);
    case "round_report":
      return out("report", `${a.name} round ${d.round ?? "?"}: ${d.passed} of ${d.attempts} ${ev.agent === "blue" ? "proposals activated" : "forgeries passed"}`,
        d.what_changed ?? "");
    case "variant_activated":
      return out("live", "✅ A new rule is live",
        d.previous ? `${shortId(d.variant_id)} replaced ${shortId(d.previous)}` : `${shortId(d.variant_id)} is the active rule`);
    case "error":
      return out("error", `❌ ${a.name} error`, d.message ?? d.error ?? JSON.stringify(d));
    default:
      return out(base, `${a.name} ${ev.type}`, JSON.stringify(d));
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
  for (const dev of DEVICE_ORDER.filter((d) => !g.humans_rejected?.[d]?.total)) {
    lines.push(`${dev}: untested — no human evidence`);
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
 * Row: {id, label, active, forgeries, humans:[{device,text}], verdict, verdictClass, reasons}
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
    const row = { id, label: shortId(id), active: id === activeId, forgeries: "—", humans: [], verdict: "not gated", verdictClass: "base", reasons: [] };
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
  const state = {
    key: null, variants: [], gates: [], activeId: null, approvals: new Map(), es: null,
    health: null, attempts: 0, gateChips: [], prov: null,
  };
  // A replayed run only posts events; the DB never changes, so the events decide which variant is active.
  const replay = params.get("replay") === "1";

  if (replay) $("replay-banner").hidden = false;

  const toast = (m) => { $("toast").textContent = stampedMessage(m); };
  const getKey = () => { try { return localStorage.getItem("followit_lab_key"); } catch { return null; } };
  const setKey = (k) => { try { k ? localStorage.setItem("followit_lab_key", k) : localStorage.removeItem("followit_lab_key"); } catch { /* ignore */ } };

  function setConn(on) {
    const c = $("conn");
    c.textContent = on ? (replay ? "● replay connected" : "● connected") : "○ disconnected";
    c.className = "badge " + (on ? "conn-on" : "conn-off");
    for (const id of ["btn-red", "btn-blue", "btn-reset"]) $(id).disabled = !on || replay;
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

  // ---- provenance of the human numbers
  function provenance() {
    if (!state.prov) state.prov = humanProvenance(state.health, state.gates, { replay });
    return state.prov;
  }
  function tagEl(prov, extra) {
    const s = document.createElement("span");
    s.className = `prov-tag prov-${prov.cls}${extra ? " " + extra : ""}`;
    s.textContent = prov.tag;
    return s;
  }
  function renderProvenance() {
    state.prov = humanProvenance(state.health, state.gates, { replay });
    const p = state.prov;
    $("metric-humans").textContent = p.real === null ? "—" : String(p.real);
    $("metric-devices").textContent = p.devices || "Waiting for device coverage";
    const tile = $("metric-prov");
    tile.textContent = "";
    tile.appendChild(tagEl(p));
    tile.append(" " + p.tile);
    const banner = $("prov-banner");
    banner.textContent = "";
    banner.appendChild(tagEl(p, "prov-tag-lg"));
    banner.append(" " + p.banner);
    banner.className = `prov-banner prov-${p.cls}`;
    for (const chip of state.gateChips) { chip.textContent = p.tag; chip.className = `prov-chip prov-${p.cls}`; }
    for (const entry of state.approvals.values()) if (entry.prov) {
      entry.prov.textContent = "";
      entry.prov.appendChild(tagEl(p));
      entry.prov.append(` Humans rejected below: ${p.short}.`);
      entry.prov.className = `card-prov prov-${p.cls}`;
    }
  }

  // ---- log
  const log = $("log");
  function addLine(entry) {
    log.querySelector(".empty-state")?.remove();
    const stick = log.scrollTop + log.clientHeight >= log.scrollHeight - 40;
    const div = document.createElement("div");
    div.className = "line " + (entry.cls || "");
    const meta = document.createElement("span");
    meta.className = "line-meta";
    if (entry.icon) {
      const who = document.createElement("span");
      who.className = "line-who";
      who.textContent = `${entry.icon} ${entry.who}`;
      meta.appendChild(who);
    }
    const time = document.createElement("time");
    time.className = "line-time";
    time.textContent = entry.timestamp.label;
    time.title = entry.timestamp.title;
    if (entry.timestamp.dateTime) time.dateTime = entry.timestamp.dateTime;
    meta.appendChild(time);
    div.appendChild(meta);
    const body = document.createElement("span");
    body.className = "line-body";
    if (entry.head) {
      const h = document.createElement("span");
      h.className = "line-head";
      h.textContent = entry.head;
      body.appendChild(h);
    }
    if (entry.detail) {
      const dd = document.createElement("span");
      dd.className = "line-detail";
      dd.textContent = entry.detail;
      body.appendChild(dd);
    }
    div.appendChild(body);
    log.appendChild(div);
    while (log.childElementCount > 500) log.firstChild.remove();
    if (stick) log.scrollTop = log.scrollHeight;
    return { div, body };
  }

  // ---- comparison
  const COLUMNS = [
    ["Rule", "variant id"],
    ["Forgeries passed", "bot attempts that beat it"],
    ["Humans rejected", "people it would block · mouse · trackpad · touch"],
    ["Gate verdict", "fixed arithmetic, no model"],
  ];
  function renderCmp() {
    const active = state.activeId || "—";
    const vm = $("metric-variant");
    vm.textContent = shortId(active);
    vm.title = active;
    const latest = state.gates.at(-1)?.forgeries_passed;
    $("metric-forgeries").textContent = latest ? `${latest.candidate} / ${latest.total}` : "—";
    $("metric-baseline").textContent = latest ? `Baseline: ${latest.baseline} / ${latest.total}` : "Run a gate to compare";
    const prov = provenance();
    const rows = buildRows(state.variants, state.gates, state.activeId);
    const root = $("cmp");
    root.textContent = "";
    if (!rows.length) { root.innerHTML = '<p class="muted">No variants yet.</p>'; return; }
    const t = document.createElement("table");
    const head = t.createTHead().insertRow();
    COLUMNS.forEach(([title, sub], i) => {
      const th = document.createElement("th");
      th.scope = "col";
      const strong = document.createElement("span");
      strong.className = "th-main";
      strong.textContent = title;
      th.appendChild(strong);
      if (i === 2) th.appendChild(tagEl(prov, "prov-tag-th"));
      const small = document.createElement("span");
      small.className = "th-sub";
      small.textContent = sub;
      th.appendChild(small);
      head.appendChild(th);
    });
    for (const r of rows) {
      const tb = t.createTBody();
      const tr = tb.insertRow();
      if (r.active) tr.className = "active";
      const idc = tr.insertCell();
      idc.title = r.id;
      idc.textContent = r.label;
      if (r.active) {
        const chip = document.createElement("span");
        chip.className = "active-chip";
        chip.textContent = "ACTIVE";
        idc.appendChild(chip);
      }
      tr.insertCell().textContent = r.forgeries;
      const hc = tr.insertCell();
      hc.textContent = r.humans.length ? r.humans.map((h) => `${h.device} ${h.text}`).join(" · ") : "—";
      if (r.humans.length) {
        const tag = document.createElement("span");
        tag.className = `cell-tag prov-${prov.cls}`;
        tag.textContent = prov.cellTag;
        hc.appendChild(tag);
      }
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
  function pendingCount() {
    let n = 0;
    for (const e of state.approvals.values()) if (!e.decided) n++;
    return n;
  }
  function syncDecisionFlag() {
    $("dec-flag").hidden = pendingCount() === 0;
  }
  function showApproval(d, ts) {
    if (state.approvals.has(d.approval_id)) return;
    const dec = $("decision");
    if (!state.approvals.size) dec.textContent = "";
    const card = document.createElement("div");
    card.className = "card";
    const flag = document.createElement("p");
    flag.className = "card-flag";
    flag.textContent = "DECISION REQUIRED";
    card.appendChild(flag);
    const requested = document.createElement("time");
    const stamp = formatTimestamp(ts);
    requested.className = "decision-time";
    requested.textContent = `Recorded ${stamp.label}`;
    requested.title = stamp.title;
    if (stamp.dateTime) requested.dateTime = stamp.dateTime;
    card.appendChild(requested);
    const h = document.createElement("h3");
    h.textContent = `Approve ${shortId(d.variant_id)}?`;
    h.title = d.variant_id || "";
    card.appendChild(h);
    const prov = document.createElement("p");
    prov.className = "card-prov";
    card.appendChild(prov);
    const ul = document.createElement("ul");
    for (const l of gateSummaryLines(d.gate || {})) { const li = document.createElement("li"); li.textContent = l; ul.appendChild(li); }
    card.appendChild(ul);
    const btns = document.createElement("div"); btns.className = "btns";
    const ok = document.createElement("button"); ok.type = "button"; ok.className = "btn-approve"; ok.textContent = "✔ Approve";
    const no = document.createElement("button"); no.type = "button"; no.className = "btn-deny"; no.textContent = "✘ Deny";
    btns.append(ok, no); card.appendChild(btns);
    const out = document.createElement("div"); out.className = "outcome"; out.setAttribute("role", "status"); card.appendChild(out);
    dec.prepend(card);
    const entry = { ok, no, out, card, prov, decided: false };
    state.approvals.set(d.approval_id, entry);
    renderProvenance();
    if (replay) {
      ok.disabled = no.disabled = true;
      entry.decided = true;
      out.textContent = stampedMessage("Recorded decision · controls disabled", ts);
      flag.textContent = "RECORDED DECISION";
      syncDecisionFlag();
      return;
    }
    syncDecisionFlag();
    const decide = async (approve) => {
      ok.disabled = no.disabled = true; entry.decided = true; syncDecisionFlag();
      out.textContent = stampedMessage("Sending…"); out.className = "outcome";
      try {
        await api("POST", `/v1/lab/approvals/${encodeURIComponent(d.approval_id)}/decide`, { approve });
        setOutcome(d.approval_id, approve);
      } catch (e) {
        ok.disabled = no.disabled = false; entry.decided = false; syncDecisionFlag();
        out.textContent = stampedMessage("Failed: " + (e.message || e)); out.className = "outcome bad";
      }
    };
    ok.addEventListener("click", () => decide(true));
    no.addEventListener("click", () => decide(false));
    ok.disabled = no.disabled = true;
    out.textContent = stampedMessage("Checking decision status…");
    api("GET", `/v1/lab/approvals/${encodeURIComponent(d.approval_id)}`).then((approval) => {
      if (entry.decided) return;
      if (approval?.status === "approved" || approval?.status === "denied") {
        setOutcome(d.approval_id, approval.status === "approved");
      } else if (approval?.status === "pending") {
        ok.disabled = no.disabled = false;
        out.textContent = "";
      } else {
        out.textContent = stampedMessage("Decision unavailable. Refresh the lab before continuing.");
      }
    }).catch(() => {
      // An activation that already landed is the decision; don't overwrite it with a probe failure.
      if (entry.decided) return;
      out.textContent = stampedMessage("Unable to verify this decision. Reconnect to continue.");
    });
  }
  function setOutcome(id, approved, ts = Date.now() / 1000) {
    const e = state.approvals.get(id);
    if (!e) return;
    e.decided = true;
    e.ok.disabled = e.no.disabled = true;
    e.out.textContent = stampedMessage(approved ? "✔ Approval confirmed" : "✘ Denial confirmed", ts);
    e.out.className = "outcome " + (approved ? "ok" : "bad");
    e.card.classList.add("decided");
    const flag = e.card.querySelector(".card-flag");
    if (flag) flag.textContent = approved ? "APPROVED BY A PERSON" : "DENIED BY A PERSON";
    syncDecisionFlag();
  }

  // ---- events
  function onEvent(ev) {
    if (ev.type === "attempt_scored" && ev.agent === "red") state.attempts += 1;
    const entry = formatEvent(ev, { attempt: ev.type === "attempt_scored" ? state.attempts : 0 });
    const node = addLine(entry);
    const d = ev.data || {};
    if (ev.type === "gate_result") {
      const chip = document.createElement("span");
      chip.className = "prov-chip";
      node.body.appendChild(chip);
      state.gateChips.push(chip);
      state.gates.push(d);
      renderProvenance(); renderCmp(); refreshVariants();
    } else if (ev.type === "approval_needed") showApproval(d, ev.ts);
    else if (ev.type === "variant_activated") {
      state.activeId = d.variant_id;
      const tile = $("metric-variant").closest(".metric");
      if (tile) { tile.classList.remove("just-changed"); void tile.offsetWidth; tile.classList.add("just-changed"); }
      renderCmp(); refreshVariants();
      if (d.approval_id) { showApproval({ approval_id: d.approval_id, variant_id: d.variant_id, gate: {} }, ev.ts); setOutcome(d.approval_id, true, ev.ts); }
    }
  }

  function connect() {
    if (state.es) state.es.close();
    const es = new EventSource("/v1/lab/stream?key=" + encodeURIComponent(state.key));
    state.es = es;
    es.onopen = () => {
      log.innerHTML = '<p class="empty-state">Ready for the next experiment.<br><span>Run an agent to watch its decisions unfold.</span></p>';
      state.attempts = 0; state.gateChips = [];
      setConn(true);
    };
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
    try { await api("POST", "/v1/lab/runs", { kind }); toast(`${kind === "red" ? "Red" : "Blue"} queued. The worker will pick it up.`); }
    catch (e) { toast(String(e.message || e)); }
  }
  $("btn-red").addEventListener("click", () => run("red"));
  $("btn-blue").addEventListener("click", () => run("blue"));
  $("btn-reset").addEventListener("click", async () => {
    if (!confirm("Reset the demo? This deletes red attempts, approvals and candidate variants.")) return;
    try { await api("POST", "/v1/lab/reset"); location.reload(); }
    catch (e) { toast(String(e.message || e)); }
  });

  fetch("/healthz").then((r) => r.json()).then((h) => {
    if (h && h.engine === "stubs") $("stub-badge").hidden = false;
    state.health = h || null;
    renderProvenance();
    renderCmp();
  }).catch(() => { state.health = null; renderProvenance(); });

  function start() {
    $("keyprompt").hidden = true;
    renderProvenance();
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
  renderProvenance();
  if (state.key) start(); else badKey("Enter the lab key to continue.");
}

if (typeof document !== "undefined") boot();
