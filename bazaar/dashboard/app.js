// Supervisor dashboard for the Bazaar bot. No build step: plain DOM, polls api/overview every 3 s.
// URLs are relative so the same page works at 127.0.0.1:8791/ and behind the gateway at /v2/.
"use strict";

const POLL_MS = 3000;
const KEEP_ROWS = 150;
const $ = (id) => document.getElementById(id);

const state = {
  lastId: null,        // last decision id we have
  rows: new Map(),     // decision id -> row
  data: null,          // last overview
  lastOk: 0,           // epoch ms of the last good poll
  failing: false,
  confirm: null,       // pending confirmation action
  busy: false,
  seen: new Set(),     // row keys already shown (for the "new" flash)
};

// ------------------------------------------------------------------ formatting
const nf = (n, d = 1) => (n === null || n === undefined || Number.isNaN(+n)) ? "—"
  : (+n).toLocaleString("es-ES", { maximumFractionDigits: d, minimumFractionDigits: 0 });
const nf2 = (n) => (n === null || n === undefined) ? "—"
  : (+n).toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const P = (n) => `${nf(n, 1)} P`;
const signed = (n, d = 1) => (n > 0 ? "+" : n < 0 ? "−" : "±") + nf(Math.abs(n), d);
const hhmmss = (ts) => ts ? new Date(ts * 1000).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) : "—";
const hhmm = (ts) => ts ? new Date(ts * 1000).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", hour12: false }) : "—";
function ago(s) {
  if (s === null || s === undefined) return "sin datos";
  s = Math.max(0, Math.round(s));
  if (s < 90) return `hace ${s} s`;
  if (s < 5400) return `hace ${Math.round(s / 60)} min`;
  return `hace ${nf(s / 3600, 1)} h`;
}
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}
function chip(text, tone) { return el("span", `chip chip--${tone}`, text); }

// ------------------------------------------------------------------ plain-Spanish phrasing
const DOMAINS = { duels: "Duelos", dealers: "Dealers", market: "Mercado", broker: "Broker", lab: "Laboratorio", venue: "Tienda" };
const SOURCES = {
  opus: ["Opus", "ai"], sonnet: ["Sonnet", "ai"], haiku: ["Haiku", "ai"], council: ["Consejo", "warn"],
  fallback: ["Reserva", "muted"], code: ["Código", "muted"],
};
const MODES = { auto: "automático", observe: "solo observa", manual: "manual" };
const EVENTS = {
  bench: "Market Test", duels: "duelos", grant_all: "reparto de P", day_opens: "abren puertas", day_closes: "cierran puertas",
  round: "nueva ronda", set_release: "nueva colección", persona: "nuevo dealer", announce: "anuncio", end_round: "fin de ronda",
};
const RAILS = {
  council: "el consejo", breaker_cautious: "el modo prudente (no compra)", stop: "el STOP",
  armed: "estar desarmado", cash: "el raíl de caja", value: "el raíl de valor", pace: "el límite de ritmo",
  arbiter: "el árbitro (otra acción tenía prioridad)", cards: "el raíl de cartas protegidas", duel: "el raíl de duelos",
  fair_play: "el juego limpio", fresh: "la oferta cambió antes de aceptar", late: "llegar tarde al tick",
  pack: "el raíl de sobres", rails_error: "un error en los raíles", rails_missing: "faltar los raíles",
};
const dealerName = (w) => w ? String(w).charAt(0).toUpperCase() + String(w).slice(1) : "";

function side(x) {
  if (!x || typeof x !== "object") return "nada";
  const parts = [];
  if (x.cash) parts.push(P(x.cash));
  for (const a of x.assets || []) parts.push(typeof a === "object" ? (a.ref || `carta #${a.id}`) : `carta #${a}`);
  for (const t of x.types || []) parts.push(typeof t === "object" ? (t.ref || t.type || JSON.stringify(t)) : String(t));
  return parts.length ? parts.join(" + ") : "nada";
}

function phrase(r, threads) {
  const p = r.params || {};
  const who = (t) => threads[String(t)] ? dealerName(threads[String(t)]) : `conversación ${t}`;
  const days = (p.days !== undefined && p.days !== null && p.days !== 0) ? ` · ${p.days} días` : "";
  switch (r.kind) {
    case "duel_message": return `Ofrece ${P(p.price)}${days} · duelo ${p.duel}`;
    case "duel_accept": return `Acepta ${P((p.expect || {}).price)} · duelo ${p.duel}`;
    case "thread_message": return `Ofrece ${P(p.price)} a ${who(p.thread)}`;
    case "open_thread": {
      const topic = typeof p.topic === "string" ? p.topic : (p.topic && (p.topic.ref || p.topic.kind || p.topic.card)) || "";
      return `Abre conversación con ${dealerName(p.with)}${topic ? ` por ${topic}` : ""}`;
    }
    case "close_thread": return `Cierra la conversación con ${who(p.thread)}`;
    case "accept_offer": return `Acepta la oferta ${p.offer}${p.expect ? `: da ${side(p.expect.want)}, recibe ${side(p.expect.give)}` : ""}`;
    case "post_offer": {
      const where = p.venue === "rastro" ? "El Rastro" : (p.venue || "mercado");
      const to = p.to ? ` para ${p.to}` : "";
      return `Publica en ${where}${to}: da ${side(p.give)} por ${side(p.want)}`;
    }
    case "cancel_offer": return `Retira la oferta ${p.offer}`;
    case "venue_open": return `Abre la tienda «${p.name || "board"}» (comisión ${nf((p.fee_bps || 0) / 100, 2)} %)`;
    case "venue_patch": return `Cambia la tienda${p.fee_bps !== undefined ? ` · comisión ${nf(p.fee_bps / 100, 2)} %` : ""}`;
    case "broker_match": return `Empareja ${p.sell} con ${p.buy} a ${P(p.price)}`;
    case "broker_announce": return `Anuncia en la tienda: «${String(p.text || "").slice(0, 80)}»`;
    case "noop": return "Espera sin hacer nada";
    default: return `${r.kind || "acción"} ${JSON.stringify(p).slice(0, 80)}`;
  }
}

function result(r) {
  const v = r.verdict || {};
  if (v.ok === false) {
    const rail = RAILS[v.rail] || (v.rail ? `el raíl «${v.rail}»` : "los raíles");
    return { label: "Vetado", tone: "bad", why: `Vetado por ${rail}${v.detail ? `: ${v.detail}` : ""}.` };
  }
  const o = r.outcome;
  if (!o) {
    return r.dry_run ? { label: "Sin enviar", tone: "muted", why: "Bot desarmado: solo lo registra." }
      : { label: "Pendiente", tone: "muted" };
  }
  switch (o.status) {
    case "sent": return { label: "Enviado", tone: "ok" };
    case "deal": return { label: "Acuerdo", tone: "ok" };
    case "vetoed": return { label: "Vetado", tone: "bad" };
    case "refused": case "error": case "expired": case "no_deal":
      return { label: "Rechazado", tone: "bad", why: `El juego respondió ${o.error || o.status}${o.message ? `: ${o.message}` : ""}.` };
    default: return { label: o.status, tone: "muted" };
  }
}

function alertText(a) {
  const t = String(a.text || "");
  let m;
  if (a.kind === "breaker") {
    if ((m = t.match(/^(\w+) paused (\d+) ticks after (\d+) refusals/))) return `${m[3]} rechazos seguidos en ${DOMAINS[m[1]] || m[1]}: pausado ${m[2]} ticks.`;
    if ((m = t.match(/^(\w+) fell from ([\d.]+) to ([\d.]+)/))) return `La cartera bajó de ${nf(+m[2])} a ${nf(+m[3])}: modo prudente, no compra.`;
    if ((m = t.match(/^injection flood \((\d+) texts\): code only for (\d+) ticks/))) return `Muchos textos con inyección (${m[1]}): solo código durante ${m[2]} ticks.`;
    return `Disyuntor: ${t}`;
  }
  if (a.kind === "novelty") {
    const raw = a.raw || {};
    const d = raw.detail;
    switch (a.where) {
      case "limits": return `Cambian los límites del juego: ${Object.entries(d || {}).map(([k, v]) => `${k} ${v[0]} → ${v[1]}`).join(", ")}.`;
      case "tick_seconds": return `El tick pasa de ${d[0]} s a ${d[1]} s.`;
      case "schedule": return `Nuevo evento en el calendario: ${EVENTS[raw.action] || raw.action || ""} a la hora ${nf(raw.at_hours, 2)}.`;
      case "feed_gap": return `Hueco en el feed público: ${t}`;
      default: return `Novedad (${a.where}): ${t}`;
    }
  }
  if (a.kind === "perceive") return `Error leyendo el juego: ${t}`;
  return `Error en ${a.where || "?"}: ${t}`;
}

// ------------------------------------------------------------------ network
async function api(path, opts = {}) {
  const res = await fetch(`api/${path}`, { cache: "no-store", ...opts });
  let body = null;
  try { body = await res.json(); } catch (_) { /* not json */ }
  if (!res.ok) {
    const err = new Error((body && (body.message || body.error)) || `HTTP ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return body;
}
const write = (path, method, body) => api(path, {
  method, headers: { "X-Dashboard": "1", "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined,
});

async function poll() {
  try {
    const q = state.lastId !== null ? `?since=${state.lastId}` : "";
    const d = await api(`overview${q}`);
    state.data = d;
    state.lastOk = Date.now();
    state.failing = false;
    // A journal rotated or restarted: start again from scratch.
    if (state.lastId !== null && d.last_id !== null && d.last_id < state.lastId) { state.rows.clear(); state.lastId = null; }
    for (const r of d.activity || []) state.rows.set(`d${r.id}`, r);
    if (d.last_id !== null && d.last_id !== undefined) state.lastId = d.last_id;
    if (state.rows.size > KEEP_ROWS) {
      const keys = [...state.rows.keys()].sort((a, b) => (+a.slice(1)) - (+b.slice(1)));
      for (const k of keys.slice(0, state.rows.size - KEEP_ROWS)) state.rows.delete(k);
    }
  } catch (e) {
    state.failing = true;
    state.error = e.message;
  }
  render();
}

// ------------------------------------------------------------------ render
function render() {
  const d = state.data;
  renderTop(d);
  if (!d) return;
  renderKpis(d);
  renderActivity(d);
  renderDuels(d);
  renderAlerts(d);
  renderLab(d);
  renderProcs(d);
  if (Date.now() < (state.flashUntil || 0)) return;
  $("foot").textContent = state.failing
    ? `Sin conexión con la API · último dato ${hhmmss(state.lastOk / 1000)}`
    : `Actualizado ${hhmmss(d.now)} · se refresca solo cada 3 s`;
}

function renderTop(d) {
  const pill = $("state-pill"), text = $("state-text"), banner = $("banner");
  const st = d && d.status, ck = d && d.clock;
  let tone = "muted", label = "Cargando…";
  const banners = [];
  if (state.failing) {
    tone = "bad"; label = "API CAÍDA";
    const since = state.lastOk ? ` desde las ${hhmmss(state.lastOk / 1000)}` : "";
    banners.push(["bad", `API caída: no responde${since}. Se reintenta sola cada 3 s. ${state.error || ""}`]);
  } else if (st) {
    const mode = MODES[(st.control || {}).mode] || (st.control || {}).mode || "";
    if (st.stop_file) { tone = "bad"; label = "STOP ACTIVO"; }
    else if (st.armed) { tone = "ok"; label = `ARMADO · ${mode}`; }
    else { tone = "warn"; label = `DESARMADO · ${mode}`; }
    if (!st.present) banners.push(["warn", "El bot todavía no ha escrito su estado (status.json). ¿Está arrancado?"]);
    if (st.stop_file) banners.push(["bad", "STOP activo: el bot no envía nada al juego (existe el archivo bazaar/STOP).", "unstop"]);
    if (st.allow_real === false) banners.push(["warn", "El bot corre sin BAZAAR_ALLOW_REAL=1: aunque se arme, no escribirá en el juego."]);
    if (ck && (ck.doors !== "open" || ck.paused)) {
      banners.push(["warn", ck.paused && ck.doors === "open" ? "Juego en pausa: el bot espera." :
        `Puertas cerradas hasta las ${ck.opens_at || "09:00"}. El bot espera; no habrá decisiones hasta entonces.`]);
    }
  }
  pill.className = `pill pill--${tone}`;
  text.textContent = label;

  banner.replaceChildren();
  banner.hidden = !banners.length;
  if (banners.length) {
    const worst = banners.find((b) => b[0] === "bad") ? "bad" : "warn";
    banner.className = `banner${worst === "warn" ? " banner--warn" : ""}`;
    banners.forEach(([, msg, act], i) => {
      const p = el("p", null, msg);
      if (act === "unstop") {
        const b = el("button", "btn", "Quitar STOP");
        b.type = "button";
        b.onclick = () => ask("unstop");
        p.append(b);
      }
      if (i) p.style.marginTop = "4px";
      banner.append(p);
    });
  }

  // buttons
  const arm = $("btn-arm"), stop = $("btn-stop");
  if (!st || state.failing) { arm.disabled = stop.disabled = true; arm.textContent = st && st.armed ? "Desarmar" : "Armar"; }
  else {
    arm.textContent = st.armed ? "Desarmar" : "Armar";
    arm.className = st.armed ? "btn" : "btn btn--primary";
    arm.disabled = state.busy || (!st.armed && st.stop_file);
    arm.title = (!st.armed && st.stop_file) ? "Quita antes el STOP" : "";
    stop.disabled = state.busy;
  }

  // clock
  if (!ck) return;
  $("c-tick").textContent = ck.tick ?? "—";
  $("c-next").textContent = ck.next_tick_in !== null && ck.next_tick_in !== undefined ? `en ${Math.round(ck.next_tick_in)} s` : "—";
  $("c-doors").textContent = ck.doors === "open" && !ck.paused
    ? `abiertas${ck.closes_at ? ` · cierran ${hhmm(ck.closes_at)}` : ""}`
    : ck.paused && ck.doors === "open" ? "en pausa" : `cerradas · abren ${ck.opens_at || "09:00"}`;
  const ev = ck.next_event;
  $("c-event").textContent = ev ? `${ev.at ? hhmm(ev.at) : `hora ${nf(ev.at_hours, 2)}`} · ${EVENTS[ev.action] || ev.action}` : "—";
}

function renderKpis(d) {
  const t = d.team || {}, s = d.status || {}, sp = d.spend || {}, b = d.broker || {};
  $("k-score").textContent = t.score !== null && t.score !== undefined ? nf(t.score, 1) : "—";
  const sub = $("k-score-sub");
  const parts = [];
  if (t.rank) parts.push(`${t.rank}.º de ${t.teams || "?"}`);
  if (t.delta_1h !== null && t.delta_1h !== undefined) parts.push(`${signed(t.delta_1h)} última hora`);
  sub.textContent = parts.join(" · ") || "sin clasificación todavía";
  sub.className = `kpi__sub ${t.delta_1h > 0 ? "is-ok" : t.delta_1h < 0 ? "is-bad" : ""}`;

  $("k-neg").textContent = t.negotiating !== null && t.negotiating !== undefined ? `${nf(t.negotiating)} · ${nf(t.market)}` : "—";
  $("k-neg-sub").textContent = t.round || "negociación · mercado";

  $("k-cash").textContent = s.cash !== null && s.cash !== undefined ? P(s.cash) : "—";
  $("k-cash-sub").textContent = t.venue ? `+ ${P(d.bond)} de fianza (tienda ${t.venue})` : "sin tienda propia todavía";

  const usd = +sp.usd || 0, cap = +sp.cap || 100, pct = Math.min(100, (usd / cap) * 100);
  $("k-spend").textContent = sp.usd !== undefined && sp.usd !== null ? `${nf2(usd)} $` : "—";
  const model = String(sp.model_now || "").replace("claude-", "").split("-")[0];
  $("k-spend-sub").textContent = `de ${nf(cap, 0)} $${model ? ` · ${model.charAt(0).toUpperCase() + model.slice(1)}` : ""}${sp.calls ? ` · ${sp.calls} llamadas` : ""}`;
  const bar = $("k-spend-bar");
  bar.style.width = `${pct}%`;
  bar.className = `bar__fill${pct >= 90 ? " is-bad" : pct >= (+sp.degrade_at || 80) ? " is-warn" : ""}`;

  const real = b.last_result && b.last_result.score && b.last_result.score.bench_efficiency;
  const est = b.efficiency_estimate;
  const val = real ?? est;
  $("k-mt").textContent = val !== null && val !== undefined ? nf2(val) : "—";
  const mtParts = [];
  if (real !== null && real !== undefined) mtParts.push(`último ${b.last_result.session || ""}`.trim());
  else if (est !== null && est !== undefined) mtParts.push(`estimada · ${b.session || "sesión"}`);
  if (b.stall_efficiency !== null && b.stall_efficiency !== undefined) mtParts.push(`puesto gratis ${nf2(b.stall_efficiency)}`);
  if (!mtParts.length) mtParts.push(b.updated ? "sin sesión todavía" : "broker sin datos");
  const mtSub = $("k-mt-sub");
  mtSub.textContent = mtParts.join(" · ");
  mtSub.className = `kpi__sub ${val !== null && val !== undefined && b.stall_efficiency ? (val >= b.stall_efficiency ? "is-ok" : "is-bad") : ""}`;
}

function labRows(d) {
  return ((d.lab || {}).notices || []).map((n, i) => ({
    _key: `n${n.ts}-${i}`, ts: n.ts, domain: "lab", lab: true, text: n.text || n.kind,
  }));
}

function renderActivity(d) {
  const list = $("activity");
  const threads = d.threads || {};
  const rows = [...state.rows.entries()].map(([k, r]) => ({ ...r, _key: k })).concat(labRows(d))
    .sort((a, b) => (b.ts || 0) - (a.ts || 0)).slice(0, 120);
  if (!rows.length) {
    const ck = d.clock || {};
    const why = ck.doors !== "open" ? `Puertas cerradas hasta las ${ck.opens_at || "09:00"}: todavía no hay decisiones.`
      : "Aún no hay decisiones. Aparecerán aquí en cuanto el bot actúe.";
    list.replaceChildren(el("li", "empty", why));
    return;
  }
  const frag = document.createDocumentFragment();
  const first = state.seen.size === 0;
  for (const r of rows) {
    const li = el("li", "row");
    if (!first && !state.seen.has(r._key)) li.classList.add("is-new");
    state.seen.add(r._key);
    li.append(el("span", "row__time", hhmmss(r.ts)));
    li.append(el("span", "row__domain", DOMAINS[r.domain] || r.domain || "—"));
    const what = el("div", "row__what");
    const chips = el("span", "row__chips");
    if (r.lab) {
      what.append(el("p", "row__action", r.text));
      chips.append(chip("Código", "muted"), chip("Aviso", "warn"));
    } else {
      const res = result(r);
      what.append(el("p", "row__action", phrase(r, threads)));
      const why = [];
      if (r.council && r.council.result === "veto") why.push(`El consejo vetó: ${r.council.why || ""}`);
      else if (r.council && r.council.result) why.push(`Consejo: ${r.council.result === "approved" ? "aprobado" : r.council.result}${r.council.why ? ` (${r.council.why})` : ""}`);
      if (r.reason) why.push(r.reason);
      if (res.why && !(r.council && r.council.result === "veto" && (r.verdict || {}).rail === "council")) why.push(res.why);
      if (why.length) what.append(el("p", "row__why", why.join(" · ")));
      const [lbl, tone] = SOURCES[r.source] || [r.source || "?", "muted"];
      chips.append(chip(lbl, tone), chip(res.label, res.tone));
    }
    li.append(what, chips);
    frag.append(li);
  }
  list.replaceChildren(frag);
  if (state.seen.size > 2000) state.seen = new Set(rows.map((r) => r._key));
}

function line(left, right, tone) {
  const li = el("li", "line");
  li.append(el("span", "line__left", left), el("span", `line__right${tone ? ` is-${tone}` : ""}`, right || ""));
  return li;
}

function renderDuels(d) {
  const du = d.duels || {}, live = du.live || [];
  $("h-duels").textContent = `Duelos en vivo${live.length ? ` · ${live.length}` : ""}`;
  const out = [];
  for (const x of live) {
    const role = x.role === "buyer" ? "Compra" : x.role === "seller" ? "Vende" : "Duelo";
    const lim = x.role === "seller" ? `coste ${nf(x.limit)}` : `límite ${nf(x.limit)}`;
    const left = `${role} · ${x.rival || "rival"} · ${lim}${x.item ? ` · ${x.item}` : ""}`;
    if (x.rival_price === null || x.rival_price === undefined) {
      out.push(line(left, `sin oferta${x.silent_ticks ? ` · ${x.silent_ticks} ticks` : ""}`, "warn"));
    } else {
      const m = x.margin;
      out.push(line(left, `${P(x.rival_price)} · ronda ${x.rounds ?? 0}${m !== null && m !== undefined ? ` · ${signed(m, 0)}` : ""}`,
        m > 0 ? "ok" : m < 0 ? "bad" : null));
    }
  }
  if (!live.length) out.push(el("li", "empty", "No hay duelos abiertos ahora."));
  const today = du.today || {};
  out.push(line(`Hoy: ${today.accepted || 0} aceptados · ${today.messages || 0} ofertas enviadas`, ""));
  $("duels").replaceChildren(...out);
}

function renderAlerts(d) {
  const a = d.alerts || [];
  const out = a.map((x) => line(alertText(x), hhmm(x.ts), x.level === "bad" ? "bad" : "warn"));
  const br = (d.status || {}).breakers || {};
  if (br.cautious) out.unshift(line("Modo prudente activo: el bot no compra.", `hasta tick ${br.cautious_until}`, "bad"));
  for (const [dom, until] of Object.entries(br.paused_until || {})) {
    if ((d.clock || {}).tick !== null && until > (d.clock || {}).tick) out.unshift(line(`${DOMAINS[dom] || dom} en pausa por rechazos.`, `hasta tick ${until}`, "bad"));
  }
  $("alerts").replaceChildren(...(out.length ? out : [el("li", "empty", "Sin alertas. Todo en orden.")]));
}

function renderLab(d) {
  const lab = d.lab || {}, c = lab.counts || {};
  const parts = [["active", "lab-active"], ["canary", "lab-canary"], ["shadow", "lab-shadow"], ["proposed", "lab-proposed"]];
  const total = parts.reduce((s, [k]) => s + (c[k] || 0), 0);
  $("lab-bar").replaceChildren(...parts.filter(([k]) => c[k]).map(([k, tok]) => {
    const s = el("span");
    s.style.flex = String(c[k]);
    s.style.background = `var(--${tok})`;
    s.title = `${k}: ${c[k]}`;
    return s;
  }));
  const out = [];
  out.push(line(total ? `${c.active || 0} activas · ${c.canary || 0} canary · ${c.shadow || 0} en sombra · ${c.proposed || 0} propuestas`
    : "Sin lecciones todavía.", lab.spent_today !== undefined && lab.spent_today !== null ? `${nf2(lab.spent_today)} $ hoy` : ""));
  for (const n of (lab.notices || []).slice(0, 3)) out.push(line(n.text || n.kind, hhmm(n.ts)));
  $("lab").replaceChildren(...out);
}

function renderProcs(d) {
  const out = (d.processes || []).map((p) => {
    const li = el("li", "proc");
    const tone = p.ok ? (p.warn ? "warn" : "ok") : "bad";
    li.append(el("span", `dot is-${tone}`), el("span", "proc__name", p.name));
    let txt;
    if (p.name === "Pasarela") txt = p.ok ? `responde · ${p.latency_ms} ms` : "no responde";
    else if (p.name === "Laboratorio") txt = p.age_s === null || p.age_s === undefined ? "sin datos" : `ciclo ${ago(p.age_s)}`;
    else txt = p.age_s === null || p.age_s === undefined ? "sin latido" : `latido ${ago(p.age_s)}`;
    li.append(el("span", `line__right${p.ok ? "" : " is-bad"}`, txt));
    return li;
  });
  out.push((() => { const li = el("li", "proc"); li.append(el("span", "dot is-ok"), el("span", "proc__name", "API"),
    el("span", "line__right", state.failing ? "no responde" : "responde")); if (state.failing) li.firstChild.className = "dot is-bad"; return li; })());
  $("procs").replaceChildren(...out);
}

// ------------------------------------------------------------------ controls (in-page confirmation)
const ACTIONS = {
  arm: {
    title: "¿Armar el bot?",
    body: "Empezará a enviar mensajes, ofertas y aceptaciones al juego real por su cuenta.",
    yes: "Sí, armar", tone: "primary",
    run: () => write("control", "POST", { armed: true, by: "dashboard" }), done: "Bot armado.",
  },
  stop: {
    title: "¿Parar en seco?",
    body: "Desarma el bot y crea el archivo bazaar/STOP: no saldrá ninguna escritura al juego hasta quitarlo. "
      + "Sin dashboard se hace igual desde la terminal del Mac: touch bazaar/STOP (y rm bazaar/STOP para quitarlo).",
    yes: "Sí, STOP", tone: "danger",
    run: async () => {
      try { return await write("stop", "POST", { by: "dashboard" }); }
      catch (e) {
        if (e.status !== 404) throw e;   // older API without /stop: at least disarm
        await write("control", "POST", { armed: false, by: "dashboard" });
        throw new Error("Desarmado, pero esta API no sabe crear bazaar/STOP: hazlo a mano con touch bazaar/STOP");
      }
    },
    done: "STOP activado y bot desarmado.",
  },
  unstop: {
    title: "¿Quitar el STOP?",
    body: "Borra bazaar/STOP. El bot sigue desarmado: para que vuelva a enviar hay que pulsar Armar.",
    yes: "Sí, quitar STOP", tone: "primary",
    run: () => write("stop", "DELETE"), done: "STOP quitado. El bot sigue desarmado.",
  },
};

function ask(kind) {
  const a = ACTIONS[kind];
  state.confirm = kind;
  $("confirm-title").textContent = a.title;
  $("confirm-body").textContent = a.body;
  const yes = $("confirm-yes");
  yes.textContent = a.yes;
  yes.className = `btn btn--${a.tone}`;
  $("confirm").hidden = false;
  yes.focus();
}

function closeConfirm() { state.confirm = null; $("confirm").hidden = true; }

async function run(kind) {
  const a = ACTIONS[kind];
  state.busy = true;
  render();
  try {
    await a.run();
    flash(a.done);
  } catch (e) {
    flash(`No se pudo: ${e.message}`, true);
  } finally {
    state.busy = false;
    await poll();
  }
}

function flash(msg, bad) {
  const f = $("foot");
  f.textContent = msg;
  f.className = `foot ${bad ? "is-bad" : "is-ok"}`;
  state.flashUntil = Date.now() + 8000;
  setTimeout(() => { f.className = "foot"; }, 8000);
}

$("btn-arm").onclick = () => {
  const st = state.data && state.data.status;
  if (!st) return;
  if (st.armed) run("disarm_now");
  else ask("arm");
};
ACTIONS.disarm_now = { run: () => write("control", "POST", { armed: false, by: "dashboard" }), done: "Bot desarmado." };
$("btn-stop").onclick = () => ask("stop");
$("confirm-yes").onclick = () => { const k = state.confirm; closeConfirm(); if (k) run(k); };
$("confirm-no").onclick = closeConfirm;
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && state.confirm) closeConfirm(); });

// ------------------------------------------------------------------ go
poll();
setInterval(() => { if (!state.busy) poll(); }, POLL_MS);
