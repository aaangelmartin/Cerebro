/* Bot: salud (procesos, pasarela, latencia, gasto, errores) y TODOS los controles.
   Contrato: bazaar/dashboard/CONTRACT.md. Palabras: Encender/Apagar, ENCENDIDO/APAGADO. */
(function () {
  "use strict";
  const U = () => window.ui || {};
  const A = () => window.api || {};

  function el(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "html") n.innerHTML = v; // only our own static SVG
      else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids.flat()) {
      if (c == null || c === false) continue;
      n.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return n;
  }
  const svgEl = (html, cls) => el("span", { class: cls || "bot-svg", html });
  const num = (v) => (typeof v === "number" && isFinite(v) ? v : null);
  const fmt = (v, d = 2) => (num(v) == null ? "—" : v.toLocaleString("es-ES", { minimumFractionDigits: d, maximumFractionDigits: d }));
  const usd = (v) => (num(v) == null ? "—" : fmt(v, 2) + " $");
  function fmtTime(ts) {
    if (U().fmtTime) try { return U().fmtTime(ts, false); } catch (e) { /* fall through */ }
    if (!num(ts)) return "—";
    return new Date(ts * 1000).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
  }
  function fmtAge(s) {
    if (num(s) == null) return "—";
    if (s < 90) return `${Math.round(s)} s`;
    if (s < 5400) return `${Math.round(s / 60)} min`;
    return `${Math.round(s / 3600)} h`;
  }
  async function req(method, path, body) {
    const res = await fetch(`api/${path}`, {
      method, cache: "no-store",
      headers: method === "GET" ? {} : { "Content-Type": "application/json", "X-Dashboard": "1" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let data = null;
    try { data = await res.json(); } catch (e) { /* empty */ }
    if (!res.ok) {
      const err = new Error((data && (data.message || data.error)) || `HTTP ${res.status}`);
      err.status = res.status;
      throw err;
    }
    return data;
  }
  const confirmBox = (o) => (U().confirm ? U().confirm(o) : Promise.resolve(false)); // never window.confirm
  function toast(type, title, text) { if (U().toast) try { U().toast({ type, title, text }); } catch (e) { /* ignore */ } }
  const loading = () => (U().loading ? U().loading() : el("div", { class: "bot-state" }, "Cargando…"));
  const empty = (t) => (U().empty ? U().empty(t) : el("div", { class: "bot-state" }, t));
  const errorBox = (e) => (U().error ? U().error(e) : el("div", { class: "bot-state bot-bad" }, "Error: " + (e && e.message || e)));

  const I = {
    cpu: '<rect x="6" y="6" width="12" height="12"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
    gate: '<path d="M4 7h16M4 12h16M4 17h10"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    wallet: '<rect x="3" y="6" width="18" height="13"/><path d="M3 10h18M16 14h2"/>',
    warn: '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18v.01"/>',
    pause: '<path d="M8 5v14M16 5v14"/>',
    play: '<path d="M7 5l12 7-12 7z"/>',
    power: '<path d="M12 3v9"/><path d="M6.3 6.3a8 8 0 1 0 11.4 0"/>',
    stop: '<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>',
    auto: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    hand: '<path d="M8 13V5a1.5 1.5 0 0 1 3 0v6M11 11V4a1.5 1.5 0 0 1 3 0v7M14 11V5.5a1.5 1.5 0 0 1 3 0V14a7 7 0 0 1-7 7h-1a6 6 0 0 1-5-3l-2.5-4a1.5 1.5 0 0 1 2.5-1.6L8 15"/>',
    duel: '<path d="M14.5 17.5L3 6V3h3l11.5 11.5M13 19l6-6M16 16l4 4M19 21l2-2M9.5 14.5L4 20M5 14l5 5"/>',
    dealer: '<path d="M3 9l2-5h14l2 5M3 9v11h18V9M3 9h18M9 20v-6h6v6"/>',
    market: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    broker: '<path d="M4 7h14l-3-3M20 17H6l3 3"/>',
    packs: '<path d="M12 2l9 5v10l-9 5-9-5V7z"/><path d="M3 7l9 5 9-5M12 12v10"/>',
    code: '<path d="M8 6l-6 6 6 6M16 6l6 6-6 6"/>',
  };
  const ic = (k, s = 14) => svgEl(`<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="square" aria-hidden="true">${I[k] || ""}</svg>`, "bot-ic");

  const DOMAINS = {
    duels: { label: "Duelos", icon: "duel", tone: "duelo" },
    dealers: { label: "Dealers", icon: "dealer", tone: "dealer" },
    market: { label: "Mercado", icon: "market", tone: "compra" },
    broker: { label: "Broker", icon: "broker", tone: "cambio" },
    packs: { label: "Packs", icon: "packs", tone: "puja" },
  };
  const MODES = [
    { id: "auto", label: "Auto", icon: "auto", text: "el bot decide y envía solo" },
    { id: "observe", label: "Observar", icon: "eye", text: "solo mira: decide pero no envía nada" },
    { id: "manual", label: "Manual", icon: "hand", text: "las decisiones grandes esperan a una persona" },
  ];
  const DUEL_MODES = [
    { id: "bounded", label: "Acotado", text: "Claude propone dentro de los límites del código" },
    { id: "full", label: "Libre", text: "Claude negocia con libertad (los raíles siguen mandando)" },
    { id: "code", label: "Código", text: "sin Claude: solo reglas de código" },
  ];
  const CAPS = [
    { id: "cash_reserve", label: "Reserva de caja", unit: "P", def: 15 },
    { id: "max_spend_per_deal", label: "Gasto máx. por trato", unit: "P", def: 120 },
    { id: "max_spend_per_hour", label: "Gasto máx. por hora", unit: "P", def: 250 },
  ];

  const S = { root: null, ov: null, status: null, spend: null, control: null, llm: null, err: null, busy: false, last: null, capsDirty: false };

  // ---------- data ----------
  async function load(ov) {
    const api = A();
    S.ov = ov || S.ov;
    const tasks = [
      (api.status ? api.status() : req("GET", "status")).then((d) => { S.status = d; }),
      (api.spend ? api.spend() : req("GET", "spend")).then((d) => { S.spend = d; }),
      (api.getControl ? api.getControl() : req("GET", "control")).then((d) => { S.control = d; }),
      (api.llm ? api.llm(undefined, 600) : req("GET", "llm?limit=600")).then((d) => { S.llm = (d && d.items) || []; }).catch(() => { S.llm = S.llm || null; }),
    ];
    const res = await Promise.allSettled(tasks);
    const bad = res.filter((r) => r.status === "rejected").slice(0, 3);
    S.err = bad.length === res.length ? bad[0].reason : null;
    S.partial = bad.length ? bad.map((r) => r.reason && r.reason.message).join(" · ") : null;
  }

  const ctrl = () => S.control || (S.status && S.status.control) || (S.ov && S.ov.status && S.ov.status.control) || {};
  const stopOn = () => !!((S.status && S.status.stop_file) || (S.ov && S.ov.status && S.ov.status.stop_file));
  const armed = () => !!ctrl().armed;
  function domainIds() {
    const set = new Set(Object.keys((S.status && S.status.domains) || (S.ov && S.ov.status && S.ov.status.domains) || {}));
    for (const d of ctrl().paused_domains || []) set.add(String(d));
    if (!set.size) ["duels", "dealers", "market"].forEach((d) => set.add(d));
    return [...set];
  }

  // ---------- health ----------
  function quant(arr, q) {
    if (!arr.length) return null;
    const s = arr.slice().sort((a, b) => a - b);
    return s[Math.min(s.length - 1, Math.floor(q * (s.length - 1) + 0.5))];
  }
  function latency() {
    if (!Array.isArray(S.llm) || !S.llm.length) return null;
    const now = Date.now() / 1000;
    let rows = S.llm.filter((r) => num(r.latency_s) != null && now - (r.ts || 0) < 1800);
    let win = "30 min";
    if (rows.length < 3) { rows = S.llm.filter((r) => num(r.latency_s) != null).slice(-100); win = "últimas " + rows.length; }
    const by = {};
    for (const r of rows) {
      const m = /opus/i.test(r.model) ? "Opus" : /sonnet/i.test(r.model) ? "Sonnet" : /haiku/i.test(r.model) ? "Haiku" : (r.model || "otro");
      (by[m] = by[m] || []).push(r.latency_s);
    }
    const out = {};
    for (const [m, a] of Object.entries(by)) out[m] = { p50: quant(a, 0.5), p90: quant(a, 0.9), n: a.length };
    return { by: out, win };
  }
  function processes() {
    const ps = (S.ov && S.ov.processes) || [];
    const find = (rx) => ps.find((p) => rx.test(String(p.name || p.id || "")));
    const st = S.status;
    const list = [
      { name: "Bot", p: find(/^bot/i), fallbackAge: st && st.age_s },
      { name: "Broker", p: find(/broker/i) },
      { name: "Laboratorio", p: find(/lab/i) },
      { name: "Grabadora", p: find(/record|grabad/i) },
      { name: "API", p: { ok: !S.err, age_s: 0 } },
    ];
    return list.map((x) => {
      const age = x.p ? x.p.age_s : x.fallbackAge;
      const ok = x.p ? (x.p.ok === true ? true : x.p.ok === false ? false : null) : null;
      return { name: x.name, age, ok, warn: !!(x.p && x.p.warn), known: !!x.p };
    });
  }
  function errorsList() {
    const out = [];
    const st = S.status || {};
    for (const e of st.last_errors || []) out.push({ ts: e.at || e.ts || st.updated, kind: e.where === "breaker" ? "breaker" : "error", where: e.where, text: e.error || e.msg || JSON.stringify(e) });
    for (const a of (S.ov && S.ov.alerts) || []) {
      if ((a.kind === "error" || a.kind === "breaker") && (a.where || "").startsWith("broker") || a.where === "lab" || a.kind === "novelty" || a.kind === "perceive")
        out.push({ ts: a.ts, kind: a.kind === "novelty" ? "aviso" : a.kind === "breaker" ? "breaker" : "error", where: a.where, text: a.text });
    }
    for (const r of Array.isArray(S.llm) ? S.llm : []) {
      if (r.error || r.abandoned || r.late) out.push({ ts: r.ts, kind: r.error ? "error" : "aviso", where: `llm.${r.purpose || "?"}`, text: r.error ? String(r.error).slice(0, 160) : `${r.model || "Claude"} ${r.abandoned ? "abandonada" : "tarde"} (${fmt(r.latency_s, 1)} s)` });
    }
    const b = st.breakers || {};
    if (b.cautious) out.push({ ts: st.updated, kind: "breaker", where: "breaker", text: `Modo prudente: sin compras hasta el tick ${b.cautious_until}` });
    for (const [d, t] of Object.entries(b.paused_until || {})) if (num(t) != null && t >= (st.tick || 0)) out.push({ ts: st.updated, kind: "breaker", where: d, text: `${(DOMAINS[d] || {}).label || d} en pausa por rechazos hasta el tick ${t}` });
    return out.filter((e) => num(e.ts) != null).sort((a, b2) => b2.ts - a.ts);
  }

  function chip(level, text) { return el("span", { class: `bot-chip bot-${level}` }, text); }
  function tile(icon, label, value, sub, level, chipText) {
    return el("div", { class: `bot-tile bot-l-${level}` },
      el("div", { class: "bot-tile-h" }, ic(icon, 12), el("span", {}, label), el("span", { class: "bot-grow" }), chip(level, chipText)),
      el("div", { class: "bot-tile-v bot-mono" }, value),
      el("div", { class: "bot-tile-s bot-mono" }, sub));
  }

  function paintHealth() {
    const box = S.root.querySelector(".bot-tiles");
    if (S.err && !S.status) { box.replaceChildren(errorBox(S.err)); return; }
    if (!S.status && !S.ov) { box.replaceChildren(loading()); return; }
    const ps = processes();
    const okN = ps.filter((p) => p.ok === true).length;
    const unknown = ps.filter((p) => !p.known).map((p) => p.name);
    const maxAge = Math.max(0, ...ps.filter((p) => p.ok && num(p.age)).map((p) => p.age));
    const pLevel = okN === ps.length ? "ok" : ps.some((p) => p.ok === false) ? "bad" : "warn";
    const gw = ((S.ov && S.ov.processes) || []).find((p) => /pasarela|gateway/i.test(p.name || ""));
    const rec = ((S.ov && S.ov.processes) || []).find((p) => /record|grabad/i.test(p.name || ""));
    const rps = rec && (num(rec.rps) ?? num(rec.rps_60s));
    const gwLevel = gw ? (gw.ok ? "ok" : "bad") : "warn";
    const lat = latency();
    const op = lat && lat.by.Opus;
    const latLevel = !op ? "warn" : op.p90 > 6 ? "bad" : op.p90 > 4 ? "warn" : "ok";
    const sp = S.spend || (S.ov && S.ov.spend) || {};
    const spLevel = num(sp.usd) == null ? "warn" : sp.usd >= (sp.cap || Infinity) ? "bad" : sp.usd >= (sp.degrade_at || Infinity) ? "warn" : "ok";
    const hour = Date.now() / 1000 - 3600;
    const errs = errorsList().filter((e) => e.ts >= hour);
    const nb = errs.filter((e) => e.kind === "breaker").length;
    const ne = errs.filter((e) => e.kind === "error").length;
    const errLevel = nb ? "bad" : ne ? "warn" : "ok";
    box.replaceChildren(
      tile("cpu", "Procesos", `${okN}/${ps.length}`, unknown.length ? `sin latido: ${unknown.join(", ")}` : `latido < ${fmtAge(maxAge)}`, pLevel, pLevel === "ok" ? "OK" : pLevel === "bad" ? "REVISAR" : "VIGILAR"),
      tile("gate", "Pasarela", rps != null ? `${fmt(rps, 1)} pet/s` : gw && num(gw.latency_ms) != null ? `${Math.round(gw.latency_ms)} ms` : "—",
        gw ? (gw.ok ? "responde" : "no responde") + (rps != null && num(gw.latency_ms) != null ? ` · ${Math.round(gw.latency_ms)} ms` : "") : "sin datos", gwLevel, gw ? (gw.ok ? "OK" : "CAÍDA") : "—"),
      tile("clock", "Latencia Opus", op ? `${fmt(op.p50, 1)} / ${fmt(op.p90, 1)} s` : "—", op ? `p50 / p90 · ${lat.win} · ${op.n} llamadas` : "sin llamadas recientes", latLevel, op ? (latLevel === "ok" ? "OK" : latLevel === "bad" ? "LENTO" : "VIGILAR") : "—"),
      tile("wallet", "Gasto hoy", usd(sp.usd), `tope efectivo ${usd(sp.cap)} · ${modelName(sp.model_now)}`, spLevel, spLevel === "ok" ? "OK" : spLevel === "bad" ? "TOPE" : "DEGRADA"),
      tile("warn", "Errores 1 h", String(errs.length), `${nb} disyuntor${nb === 1 ? "" : "es"} · ${ne} error${ne === 1 ? "" : "es"} · ${errs.length - nb - ne} avisos`, errLevel, errLevel === "ok" ? "OK" : "REVISAR"));
  }
  function modelName(m) { return !m ? "—" : /opus/i.test(m) ? "Opus" : /sonnet/i.test(m) ? "Sonnet" : /haiku/i.test(m) ? "Haiku" : m; }

  function barList(title, obj, total, extra) {
    const entries = Object.entries(obj || {}).map(([k, v]) => [k, typeof v === "object" && v ? (v.usd_today ?? v.usd ?? 0) : v]).filter(([, v]) => num(v) != null).sort((a, b) => b[1] - a[1]);
    const max = Math.max(total || 0, ...entries.map((e) => e[1]), 0.0001);
    return el("div", { class: "bot-blist" }, el("div", { class: "bot-cap" }, title),
      ...(entries.length ? entries.map(([k, v]) => el("div", { class: "bot-brow" },
        el("div", { class: "bot-brow-h" }, el("span", {}, extra ? extra.label(k) : k), el("span", { class: "bot-mono bot-muted bot-small" }, extra && extra.note ? extra.note(k) : ""), el("span", { class: "bot-mono" }, usd(v))),
        el("div", { class: "bot-bar" }, el("span", { style: `width:${Math.max(1, Math.round((v / max) * 100))}%` }))))
        : [el("div", { class: "bot-muted bot-small" }, "sin gasto")]));
  }
  const PURPOSE = (window.ui && window.ui.PURPOSE_LABEL) || {};

  // "Por clave": state chip, reason and since when, errors in the last 15 min, last error, spend today vs cap
  function keyList(sp) {
    const kh = window.__keyHealth || (window.ui.keyHealth ? window.ui.keyHealth(sp, [], null) : { keys: [] });
    const max = Math.max(0.0001, ...kh.keys.map((k) => Math.max(k.usd, +k.cap || 0)));
    const t = (ts) => (ts ? window.ui.fmtTime(ts) : null);
    return el("div", { class: "bot-blist bot-keys" }, el("div", { class: "bot-cap" }, "Por clave"),
      ...(kh.keys.length ? kh.keys.map((k) => el("div", { class: "bot-key tone-" + k.tone },
        el("div", { class: "bot-brow-h" }, el("b", {}, "Clave " + k.label),
          el("span", { class: "tag res tone-" + (k.tone === "ok" ? "ok" : k.tone) + " bot-key-chip" }, k.chip),
          el("span", { class: "bot-mono" }, usd(k.usd) + (k.cap ? " / " + fmt(k.cap, 0) + " $" : ""))),
        el("div", { class: "bot-bar" }, el("span", { style: `width:${Math.max(1, Math.round((k.usd / max) * 100))}%` })),
        k.ok ? el("div", { class: "bot-muted bot-small", title: k.lastError || "" }, k.errors15
            ? `ya responde · ${k.errors15} errores en 15 min` + (k.lastErrorTs ? `, el último a las ${t(k.lastErrorTs)}` : "") + (window.ui.keyProblem(k.lastError) ? ` (${window.ui.keyProblem(k.lastError).label.toLowerCase()})` : "")
            : "sin errores en los últimos 15 min")
          : el("div", { class: "bot-key-why" },
            el("div", {}, k.text),
            el("div", { class: "bot-muted bot-small bot-mono" }, [k.since ? "desde " + t(k.since) : null, k.errors15 + " errores en 15 min"].filter(Boolean).join(" · ")),
            k.lastError ? el("div", { class: "bot-muted bot-small bot-key-last", title: k.lastError }, "Último error: " + k.lastError) : null)))
        : [el("div", { class: "bot-muted bot-small" }, "sin claves")]));
  }
  function keyAlert() {
    const kh = window.__keyHealth;
    if (!kh || !kh.bad.length) return null;
    const hard = kh.allDown || kh.bad.some((k) => k.tone === "bad");
    const okL = kh.okLabels;
    return el("div", { class: "bot-keyalert tone-" + (hard ? "bad" : "warn") }, ic("warn", 16),
      el("div", {}, el("b", {}, kh.allDown ? "El bot juega sin Claude: ninguna clave funciona."
        : kh.bad.map((k) => `Clave ${k.label} ${k.chip.toLowerCase()}`).join(" · ") + ": el bot sigue con " + (okL.length ? okL.join(", ") : "ninguna") + "."),
        ...kh.bad.map((k) => el("div", { class: "bot-small" }, `Clave ${k.label}: ${k.text}` + (k.since ? ` (desde ${window.ui.fmtTime(k.since)})` : "")))));
  }
  // "Por propósito": spent today against that purpose's budget for today (GET brain/budget -> plan.purpose_caps);
  // the caps the team set by hand win for Cerebro (cap_today) and for the whole day (day_cap)
  function purposeList(sp) {
    const bd = B.data || {}, plan = bd.plan || {};
    const caps = { ...(plan.purpose_caps || {}) };
    const team = bd.caps_set_by_team || {};
    if (num(team.brain_day_cap) != null && num(bd.cap_today) != null) caps.strategy = bd.cap_today;
    const spent = { ...(sp.by_purpose || {}) };
    for (const [k, v] of Object.entries(plan.spent_by_purpose || {})) if (spent[k] == null) spent[k] = v;
    const keys = Object.keys(spent).filter((k) => num(spent[k]) != null).sort((a, b) => (num(caps[b]) != null) - (num(caps[a]) != null) || spent[b] - spent[a]);
    const max = Math.max(0.0001, ...keys.map((k) => spent[k]));
    const rows = keys.map((k) => {
      const v = spent[k], cap = num(caps[k]);
      const pct = cap > 0 ? (v / cap) * 100 : null;
      const tone = pct == null ? "" : pct >= 100 ? "bad" : pct >= 80 ? "warn" : "ok";
      return el("div", { class: "bot-brow" },
        el("div", { class: "bot-brow-h" }, el("span", {}, PURPOSE[k] || k),
          k === "strategy" && num(team.brain_day_cap) != null ? el("span", { class: "bot-mono bot-muted bot-small" }, "tope del equipo") : el("span", {}),
          el("span", { class: "bot-mono" }, usd(v), cap != null ? el("span", { class: "bot-muted" }, " / " + usd(cap)) : null,
            pct != null ? el("span", { class: "bot-small bot-pp bot-pp-" + tone }, " " + Math.round(pct) + " %") : null)),
        el("div", { class: "bot-bar" + (tone ? " bot-bar-" + tone : " bot-bar-plain") }, el("span", { style: `width:${Math.max(1, Math.min(100, Math.round(pct != null ? pct : (v / max) * 100)))}%` })));
    });
    const dayCap = num(team.day_cap) != null && num(bd.day_cap) != null ? bd.day_cap : null;
    const planToday = num(plan.plan_today), spentDay = num(bd.day_total_spent) ?? num(sp.usd);
    const res = plan.reserves || {};
    const foot = [];
    if (planToday != null || dayCap != null) {
      const ref = dayCap != null ? dayCap : planToday;
      const pct = ref > 0 ? (spentDay / ref) * 100 : 0;
      const tone = pct >= 100 ? "bad" : pct >= 80 ? "warn" : "ok";
      foot.push(el("div", { class: "bot-brow bot-ptotal" },
        el("div", { class: "bot-brow-h" }, el("b", {}, "Total hoy"), el("span", { class: "bot-mono bot-muted bot-small" }, dayCap != null ? "tope del equipo" + (planToday != null ? " · plan " + usd(planToday) : "") : "plan"),
          el("span", { class: "bot-mono" }, usd(spentDay), el("span", { class: "bot-muted" }, " / " + usd(ref)), el("span", { class: "bot-small bot-pp bot-pp-" + tone }, " " + Math.round(pct) + " %"))),
        el("div", { class: "bot-bar bot-bar-" + tone }, el("span", { style: `width:${Math.max(1, Math.min(100, Math.round(pct)))}%` }))));
    }
    if (num(res.today) != null || num(res.tomorrow) != null) {
      const ss = plan.sessions || {};
      foot.push(el("div", { class: "bot-muted bot-small bot-pres" }, `Reservado para duelos y Market Test: hoy ${num(res.today) != null ? usd(res.today) : "—"} · mañana ${num(res.tomorrow) != null ? usd(res.tomorrow) : "—"}`,
        ss.duels_today != null ? ` (hoy ${ss.duels_today} de duelos y ${ss.bench_today ?? 0} tests; mañana ${ss.duels_tomorrow ?? 0} y ${ss.bench_tomorrow ?? 0})` : ""));
    }
    return el("div", { class: "bot-blist" }, el("div", { class: "bot-cap" }, "Por propósito · gastado / presupuesto de hoy"),
      ...(rows.length ? rows : [el("div", { class: "bot-muted bot-small" }, "sin gasto")]), ...foot);
  }
  function paintSpend() {
    const box = S.root.querySelector(".bot-spend");
    const sp = S.spend || (S.ov && S.ov.spend);
    if (!sp) { box.replaceChildren(S.err ? errorBox(S.err) : loading()); return; }
    const cap = num(sp.cap) || 0;
    const scale = Math.max(cap, sp.usd || 0, 1);
    const pctOf = (v) => `${Math.max(0, Math.min(100, (v / scale) * 100))}%`;
    const marks = [["Sonnet", sp.degrade_at], ["Haiku", sp.haiku_at], ["tope", cap]].filter(([, v]) => num(v) != null)
      .map(([l, v], i) => el("span", { class: "bot-mark" + (i % 2 ? " is-low" : ""), style: `left:${pctOf(v)}` }, el("span", { class: "bot-mark-l bot-mono" }, `${l} ≥ ${fmt(v, 0)} $`)));
    S.root.querySelector(".bot-spend-sub").textContent = `${sp.day || "hoy"} · tope efectivo ${usd(cap)}` + (num(sp.cap_config) != null ? ` (config ${fmt(sp.cap_config, 0)} $${num(sp.share) != null ? ` × ${fmt(sp.share, 2)}` : ""})` : "");
    const calls = sp.calls;
    box.replaceChildren(
      keyAlert() || "",
      el("div", { class: "bot-spend-top" },
        el("div", {}, el("div", { class: "bot-big bot-mono" }, usd(sp.usd)), el("div", { class: "bot-muted bot-small bot-mono" }, `${calls ?? "—"} llamadas · ahora ${modelName(sp.model_now)}`)),
        el("div", { class: "bot-gauge" }, el("div", { class: "bot-gauge-bar" }, el("span", { style: `width:${pctOf(sp.usd || 0)}` }), ...marks),
          el("div", { class: "bot-mono bot-small bot-muted" }, cap ? `${Math.round(((sp.usd || 0) / cap) * 100)} % del tope` : ""))),
      el("div", { class: "bot-spend-cols" },
        keyList(sp),
        purposeList(sp),
        barList("Por modelo", sp.by_model, null, { label: modelName })));
    // ladder
    const lad = S.root.querySelector(".bot-ladder");
    const now = modelName(sp.model_now);
    const level = (sp.usd || 0) >= cap && cap ? 3 : now === "Haiku" ? 2 : now === "Sonnet" ? 1 : 0;
    const steps = [
      ["Opus", `normal · hasta ${fmt(sp.degrade_at, 0)} $`],
      ["Sonnet", `${fmt(sp.degrade_at, 0)}–${fmt(sp.haiku_at, 0)} $`],
      ["Haiku", `${fmt(sp.haiku_at, 0)}–${fmt(cap, 0)} $`],
      ["Solo código", `≥ ${fmt(cap, 0)} $ o API caída`],
    ];
    S.root.querySelector(".bot-ladder-n").textContent = `nivel ${level + 1} de 4`;
    lad.replaceChildren(...steps.map(([n, t], i) => el("div", { class: "bot-step" + (i === level ? " is-on" : i < level ? " is-past" : "") },
      el("span", { class: "bot-dot" }), el("span", {}, n), el("span", { class: "bot-mono bot-muted bot-small" }, t))));
  }

  function paintLatency() {
    const box = S.root.querySelector(".bot-lat");
    const lat = latency();
    if (S.llm == null) { box.replaceChildren(empty("Sin datos de llamadas a Claude.")); return; }
    if (!lat || !Object.keys(lat.by).length) { box.replaceChildren(empty("Sin llamadas a Claude registradas.")); return; }
    S.root.querySelector(".bot-lat-n").textContent = `p50 · p90 · ${lat.win}`;
    const max = Math.max(8, ...Object.values(lat.by).map((v) => v.p90 || 0));
    box.replaceChildren(...Object.entries(lat.by).map(([m, v]) => el("div", { class: "bot-latrow" },
      el("span", {}, m),
      el("span", { class: "bot-latbar" },
        el("span", { class: "bot-latrange" + (v.p90 > 6 ? " is-bad" : v.p90 > 4 ? " is-warn" : ""), style: `left:${(v.p50 / max) * 100}%;width:${Math.max(1, ((v.p90 - v.p50) / max) * 100)}%` }),
        el("span", { class: "bot-latlimit", style: `left:${(6 / max) * 100}%`, title: "6 s" })),
      el("span", { class: "bot-mono bot-small" }, `${fmt(v.p50, 1)}/${fmt(v.p90, 1)} s`))),
      el("div", { class: "bot-small bot-bad" }, "línea roja: 6 s"));
  }

  function paintProcs() {
    const box = S.root.querySelector(".bot-procs");
    const ps = processes();
    box.replaceChildren(...ps.map((p) => el("div", { class: "bot-proc" },
      el("span", { class: "bot-dot " + (p.ok === true ? (p.warn ? "is-warn" : "is-ok") : p.ok === false ? "is-bad" : "") }),
      el("span", {}, p.name),
      el("span", { class: "bot-mono bot-muted bot-small" }, p.known ? (p.name === "API" ? "responde" : `latido ${fmtAge(p.age)}`) : "sin latido expuesto"))));
  }

  function paintErrors() {
    const box = S.root.querySelector(".bot-errs");
    const list = errorsList();
    const now = Date.now() / 1000;
    const span = 6 * 3600;
    const t0 = now - span;
    const lanes = [["breaker", "Disyuntores"], ["error", "Errores"], ["aviso", "Avisos"]];
    const W = 600; const H = 22;
    const svg = lanes.map(([k], i) => {
      const y = i * H + H / 2;
      const dots = list.filter((e) => e.kind === k && e.ts >= t0).map((e) => `<rect x="${(((e.ts - t0) / span) * W - 3).toFixed(1)}" y="${y - 3}" width="6" height="6" class="bot-ev-${k}"><title>${esc(fmtTime(e.ts) + " " + (e.text || ""))}</title></rect>`).join("");
      return `<line x1="0" x2="${W}" y1="${y}" y2="${y}" class="bot-axis"/>${dots}`;
    }).join("");
    const timeline = el("div", { class: "bot-tl" },
      el("div", { class: "bot-tl-l" }, ...lanes.map(([, l]) => el("span", {}, l))),
      svgEl(`<svg viewBox="0 0 ${W} ${lanes.length * H}" preserveAspectRatio="none" width="100%" height="${lanes.length * H}">${svg}</svg>`, "bot-tl-svg"));
    const rows = list.slice(0, 25).map((e) => el("div", { class: `bot-err bot-k-${e.kind}` },
      ic(e.kind === "breaker" ? "stop" : "warn", 13),
      el("span", { class: "bot-err-t" }, e.where ? el("b", {}, e.where + " · ") : null, e.text || "—"),
      el("span", { class: "bot-mono bot-muted bot-small" }, fmtTime(e.ts))));
    box.replaceChildren(timeline, ...(rows.length ? rows : [empty("Sin disyuntores, errores ni avisos.")]));
  }
  function esc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

  // ---------- controls ----------
  async function act(opts, fn) {
    if (S.busy) return;
    const ok = await confirmBox(opts);
    if (!ok) return;
    S.busy = true; paintControls();
    try {
      const res = await fn();
      S.last = { ok: true, text: opts.done || "Hecho", ts: Date.now() / 1000 };
      if (res && typeof res === "object" && "armed" in res && !res.error) S.control = { ...ctrl(), ...(res.control && typeof res.control === "object" && !res.control.error ? res.control : res) };
      toast("outcome", opts.done || "Hecho", "");
    } catch (e) {
      S.last = { ok: false, text: `${opts.title}: ${e.message || e}`, ts: Date.now() / 1000 };
      toast("error", "No se pudo aplicar", e.message || String(e));
    } finally {
      S.busy = false;
      await load();
      paintAll();
    }
  }
  const setControl = (body) => (A().control && body ? A().control({ ...body, by: "dashboard" }) : req("POST", "control", { ...body, by: "dashboard" }));

  function seg(options, current, onPick, cls) {
    return el("div", { class: "bot-seg " + (cls || "") }, ...options.map((o) => el("button", {
      type: "button", class: o.id === current ? "is-on" : "", disabled: S.busy, title: o.text || "",
      onclick: () => { if (o.id !== current) onPick(o); },
    }, o.icon ? ic(o.icon, 13) : null, o.label)));
  }

  function paintControls() {
    const box = S.root.querySelector(".bot-ctrl");
    if (!S.control && !S.status) { box.replaceChildren(S.err ? errorBox(S.err) : loading()); return; }
    const c = ctrl();
    const stop = stopOn();
    const on = armed() && !stop;
    const paused = (c.paused_domains || []).map(String);
    const ids = domainIds();
    const allPaused = ids.length && ids.every((d) => paused.includes(d));
    const mode = MODES.find((m) => m.id === (c.mode || "auto")) || { label: c.mode };
    const st = S.status || {};

    const stateBox = el("div", { class: "bot-live " + (stop ? "is-stop" : on ? "is-live" : "is-off") },
      el("span", { class: "bot-dot" }),
      el("div", {},
        el("div", { class: "bot-live-t" }, stop ? "APAGADO · STOP activo" : on ? `ENCENDIDO · modo ${mode.label}` : `APAGADO · modo ${mode.label}`),
        el("div", { class: "bot-mono bot-muted bot-small" }, [
          st.tick != null ? `tick ${st.tick}` : null, st.state || null, st.doors ? `puertas ${st.doors === "open" ? "abiertas" : "cerradas"}` : null,
          num(st.age_s) != null ? `latido ${fmtAge(st.age_s)}` : null, st.write === false && on ? "sin escritura" : null,
        ].filter(Boolean).join(" · "))));

    const btns = el("div", { class: "bot-btns" },
      el("button", {
        type: "button", class: "bot-b", disabled: S.busy || !ids.length,
        onclick: () => allPaused
          ? act({ title: "¿Reanudar todos los dominios?", text: "El bot vuelve a trabajar en todos los dominios.", confirmLabel: "Sí, reanudar", done: "Dominios reanudados" }, () => setControl({ paused_domains: [] }))
          : act({ title: "¿Pausar todos los dominios?", text: `El bot deja de actuar en ${ids.map((d) => (DOMAINS[d] || {}).label || d).join(", ")}. Sigue encendido y leyendo el juego.`, confirmLabel: "Sí, pausar", done: "Dominios en pausa" }, () => setControl({ paused_domains: ids })),
      }, ic(allPaused ? "play" : "pause"), allPaused ? "Reanudar" : "Pausar"),
      on || (armed() && stop)
        ? el("button", { type: "button", class: "bot-b", disabled: S.busy, onclick: () => act({ title: "¿Apagar el bot?", text: "El bot queda APAGADO: deja de enviar órdenes. Sigue leyendo el juego. Para volver, pulsa Encender.", confirmLabel: "Sí, apagar", danger: true, done: "Bot apagado" }, () => setControl({ armed: false })) }, ic("power"), "Apagar")
        : el("button", { type: "button", class: "bot-b bot-b-go", disabled: S.busy || stop, title: stop ? "Quita el STOP antes de encender" : "",
          onclick: () => act({ title: "¿Encender el bot?", text: `El bot pasa a LIVE en modo ${mode.label}: ${mode.text || ""}. Enviará órdenes reales al juego.`, confirmLabel: "Sí, encender", done: "Bot encendido (LIVE)" }, () => setControl({ armed: true })) }, ic("power"), "Encender"),
      stop
        ? el("button", { type: "button", class: "bot-b bot-b-unstop", disabled: S.busy, onclick: () => act({ title: "¿Quitar el STOP?", text: "Se borra el fichero STOP. El bot sigue apagado hasta que alguien pulse Encender.", confirmLabel: "Sí, quitar STOP", done: "STOP quitado · el bot sigue apagado" }, () => (A().unstop ? A().unstop() : req("DELETE", "stop"))) }, ic("stop"), "Quitar STOP")
        : el("button", { type: "button", class: "bot-b bot-b-stop", disabled: S.busy, onclick: () => act({ title: "¿Parar el bot ahora?", text: "Crea el fichero STOP y apaga el bot: no sale ninguna orden más, ni de duelos, dealers, mercado ni broker. Para volver, quita el STOP y pulsa Encender.", confirmLabel: "Sí, parar todo", danger: true, done: "STOP activo · bot apagado" }, () => (A().stop ? A().stop() : req("POST", "stop", { by: "dashboard" }))) }, ic("stop"), "STOP"));

    const last = S.last ? el("div", { class: "bot-last " + (S.last.ok ? "bot-ok" : "bot-bad") }, `${S.last.ok ? "✓" : "✕"} ${S.last.text} · ${fmtTime(S.last.ts)}`) : null;

    const modeSeg = seg(MODES, c.mode || "auto", (o) => act({ title: `¿Cambiar a modo ${o.label}?`, text: `${o.label}: ${o.text}.`, confirmLabel: `Sí, modo ${o.label}`, done: `Modo ${o.label}` }, () => setControl({ mode: o.id })));
    const duelSeg = seg(DUEL_MODES, c.duel_claude_mode || "bounded", (o) => act({ title: `¿Claude en duelos: ${o.label}?`, text: `${o.label}: ${o.text}.`, confirmLabel: `Sí, ${o.label}`, done: `Claude en duelos: ${o.label}` }, () => setControl({ duel_claude_mode: o.id })));

    const doms = el("div", { class: "bot-doms" }, ...ids.map((d) => {
      const meta = DOMAINS[d] || { label: d, icon: "code", tone: "anuncio" };
      const isOn = !paused.includes(d);
      const dst = ((st.domains || {})[d] || {}).state;
      return el("div", { class: `bot-dom bot-t-${meta.tone}` }, ic(meta.icon, 13), el("span", {}, meta.label),
        el("span", { class: "bot-grow" }),
        el("span", { class: "bot-mono bot-muted bot-small" }, isOn ? (dst ? dst.replace(/_/g, " ") : "encendido") : "en pausa"),
        el("button", {
          type: "button", class: "bot-tg" + (isOn ? " is-on" : ""), role: "switch", "aria-checked": String(isOn), "aria-label": meta.label, disabled: S.busy,
          onclick: () => {
            const next = isOn ? [...new Set([...paused, d])] : paused.filter((x) => x !== d);
            act({ title: `¿${isOn ? "Pausar" : "Reanudar"} ${meta.label}?`, text: isOn ? `El bot deja de actuar en ${meta.label}.` : `El bot vuelve a actuar en ${meta.label}.`, confirmLabel: isOn ? "Sí, pausar" : "Sí, reanudar", done: `${meta.label} ${isOn ? "en pausa" : "reanudado"}` }, () => setControl({ paused_domains: next }));
          },
        }, el("span")));
    }));

    // caps form: keep what the user is typing between refreshes
    let form = box.querySelector(".bot-caps");
    const keep = form && S.capsDirty ? Object.fromEntries([...form.querySelectorAll("input")].map((i) => [i.name, i.value])) : null;
    const caps = c.caps || {};
    form = el("form", { class: "bot-caps", onsubmit: (e) => { e.preventDefault(); saveCaps(form); } },
      ...CAPS.map((k) => el("label", { class: "bot-cap-row" }, el("span", {}, k.label),
        el("span", { class: "bot-cap-in" }, el("input", { name: k.id, type: "number", min: "0", step: "1", inputmode: "numeric", placeholder: String(k.def), value: keep ? keep[k.id] : (num(caps[k.id]) != null ? String(caps[k.id]) : ""), oninput: () => { S.capsDirty = true; } }), el("span", { class: "bot-muted bot-mono" }, k.unit)))),
      el("div", { class: "bot-cap-f" }, el("span", { class: "bot-muted bot-small" }, "Vacío = valor por defecto del código"), el("span", { class: "bot-grow" }),
        el("button", { type: "button", class: "bot-b bot-b-sm", disabled: S.busy, onclick: () => { S.capsDirty = false; paintControls(); } }, "Deshacer"),
        el("button", { type: "submit", class: "bot-b bot-b-sm bot-b-go", disabled: S.busy }, "Guardar")));

    box.replaceChildren(
      panel("Estado y parada", null, stateBox, btns, last),
      panel("Modo de decisión", null, modeSeg, el("div", { class: "bot-muted bot-small bot-pad" }, mode.text || "")),
      panel("Modo de Claude en duelos", null, duelSeg),
      panel("Dominios", "gestionado por el bot", doms),
      panel("Topes y límites", null, form));
  }
  // ---------- Cerebro · intensidad y presupuesto ----------
  // GET brain/budget -> {mode, level, usd_per_hour_now, table:[{level, interval_ticks, usd_per_hour}], spent_today, cap_today,
  //   day_total_spent, day_cap, projected_spend_by_close, hours_left, keys_headroom, last_change:{ts, from, to, reason}}
  // POST control {brain_intensity, brain_intensity_mode} / {brain_day_cap} / {day_cap}
  const B = { host: null, data: null, state: "idle", err: null, dragging: false, busy: false, at: 0, n: {} };
  function brainMount() {
    const n = B.n = {};
    // intensity is controlled on the Cerebro screen; here only a read-only line that links there
    n.line = el("a", { class: "bot-brain-line", href: "#cerebro" }, "Intensidad del cerebro: —");
    n.proj = el("b", { class: "bot-mono" }, "—"); n.hours = el("b", { class: "bot-mono" }, "—"); n.head = el("b", { class: "bot-mono" }, "—");
    n.barBrain = el("div", { class: "bot-brain-bar" }); n.barDay = el("div", { class: "bot-brain-bar" });
    const capIn = (name, label) => {
      const inp = el("input", { name, type: "number", min: "0", step: "1", inputmode: "numeric", class: "bot-brain-cap" });
      const btn = el("button", { type: "button", class: "bot-b bot-b-sm", onclick: async () => {
        const v = Number(inp.value);
        if (!isFinite(v) || v < 0 || inp.value === "") { toast("error", "Número no válido", label); return; }
        const ok = await confirmBox({ title: `¿Cambiar ${label.toLowerCase()} a ${fmt(v, 0)} $?`, text: name === "budget_total_usd" ? "Es todo lo que puede gastar el bot en la API de Claude en lo que queda de evento (hoy y mañana). El reparto por día se recalcula."
          : "Es el máximo que puede gastar hoy en la API de Claude. Se aplica en la siguiente revisión.", confirmLabel: "Sí, cambiar" });
        if (ok) setBrain({ [name]: v }, `${label}: ${fmt(v, 0)} $`);
      } }, "Guardar");
      n[name] = inp;
      return el("label", { class: "bot-cap-row" }, el("span", {}, label), el("span", { class: "bot-cap-in" }, inp, el("span", { class: "bot-muted bot-small" }, "$"), btn));
    };
    // total budget of the whole event (today + tomorrow)
    n.total = el("div", { class: "bot-brain-total", hidden: true });
    n.totalBar = el("div", { class: "bot-brain-bar" });
    n.totalPlan = el("div", { class: "bot-brain-kv" });
    n.total.append(el("div", { class: "bot-cap" }, "Presupuesto total del evento"), n.totalBar, n.totalPlan,
      el("div", { class: "bot-brain-caps bot-brain-caps-1" }, capIn("budget_total_usd", "Presupuesto total del evento")));
    n.body = el("div", { class: "bot-pb bot-brain-body" },
      n.total,
      n.line,
      el("div", { class: "bot-brain-grid" },
        el("div", {}, el("div", { class: "bot-cap" }, "Cerebro hoy"), n.barBrain),
        el("div", {}, el("div", { class: "bot-cap" }, "Todo el día (todas las llamadas)"), n.barDay)),
      el("div", { class: "bot-brain-kv" },
        el("span", {}, el("span", { class: "bot-muted" }, "Gasto previsto al cierre "), n.proj),
        el("span", {}, el("span", { class: "bot-muted" }, "Quedan "), n.hours),
        el("span", {}, el("span", { class: "bot-muted" }, "Margen de las claves "), n.head)),
      el("div", { class: "bot-brain-caps" }, capIn("brain_day_cap", "Tope del cerebro hoy"), capIn("day_cap", "Tope de todo el día")));
    n.off = el("div", { class: "bot-pb bot-muted", hidden: true }, "El presupuesto del cerebro aún no está activo.");
    n.sub = el("span", { class: "bot-muted bot-mono bot-small" }, "");
    B.host = el("section", { class: "bot-panel bot-brain" }, el("div", { class: "bot-ph" }, el("h2", {}, "Presupuesto"), n.sub), n.body, n.off);
    brainPaint();
    return B.host;
  }
  function bar(host, spent, cap) {
    const pct = cap > 0 ? Math.min(100, (spent / cap) * 100) : 0;
    const tone = cap > 0 && spent >= cap ? "bad" : pct >= 80 ? "warn" : "ok";
    host.replaceChildren(el("div", { class: "bot-brow-h" }, el("span", { class: "bot-mono" }, usd(spent)), el("span", { class: "bot-muted bot-small bot-mono" }, cap ? `de ${fmt(cap, 0)} $ · ${Math.round(pct)} %` : "sin tope")),
      el("div", { class: "bot-bar bot-bar-" + tone }, el("span", { style: `width:${Math.max(1, Math.round(pct))}%` })));
  }
  function brainPaint() {
    const n = B.n, d = B.data; if (!B.host) return;
    const off = B.state === "off" || (B.state !== "on" && !d);
    n.off.hidden = !(B.state === "off" || B.state === "error");
    n.off.textContent = B.state === "error" ? "No se pudo leer el presupuesto del cerebro: " + ((B.err && B.err.message) || "") : "El presupuesto del cerebro aún no está activo.";
    n.body.classList.toggle("is-off", off);
    for (const x of [n.brain_day_cap, n.day_cap, n.budget_total_usd]) x.disabled = off || B.busy;
    if (!d) { n.sub.textContent = B.state === "idle" ? "cargando…" : ""; return; }
    const auto = d.mode !== "manual";
    n.sub.textContent = "total del evento, topes de hoy y reservas";
    n.line.replaceChildren(el("span", { class: "bot-muted" }, "Intensidad del cerebro: "), el("b", { class: "bot-mono" }, String(d.level ?? "—")),
      el("span", { class: "bot-muted" }, " · " + (auto ? "auto" : "manual") + (num(d.usd_per_hour_now) != null ? " · ≈ " + fmt(d.usd_per_hour_now, 2) + " $/h" : "")),
      el("span", { class: "bot-brain-go" }, " → ver en Cerebro"));
    // event total: shown only when the backend sends it
    const bt = num(d.budget_total), st = num(d.spent_total);
    n.total.hidden = bt == null && st == null;
    if (!n.total.hidden) {
      const rem = num(d.remaining_total) != null ? d.remaining_total : (bt != null && st != null ? bt - st : null);
      const pct = bt > 0 && st != null ? Math.min(100, (st / bt) * 100) : 0;
      const tone = bt > 0 && st >= bt ? "bad" : pct >= 85 ? "warn" : "ok";
      n.totalBar.replaceChildren(el("div", { class: "bot-brow-h" },
        el("span", {}, "gastado ", el("b", { class: "bot-mono" }, st != null ? usd(st) : "—"), bt != null ? " de " + fmt(bt, 0) + " $" : ""),
        el("span", { class: "bot-mono" + (rem != null && rem <= 0 ? " bot-bad" : "") }, rem != null ? "quedan " + usd(Math.max(0, rem)) : "")),
        el("div", { class: "bot-bar bot-bar-lg bot-bar-" + tone }, el("span", { style: `width:${Math.max(1, Math.round(pct))}%` })));
      const target = num(d.usd_per_hour_target), nowRate = num(d.usd_per_hour_now);
      const over = target != null && nowRate != null ? nowRate - target : null;
      const rateTone = over == null ? "" : over <= 0 ? "bot-okc" : over <= target * 0.25 ? "bot-warnc" : "bot-bad";
      n.totalPlan.replaceChildren(...[
        num(d.plan_today) != null || num(d.plan_tomorrow) != null ? el("span", {}, el("span", { class: "bot-muted" }, "Reparto previsto "),
          el("b", { class: "bot-mono" }, `Hoy ≈ ${num(d.plan_today) != null ? fmt(d.plan_today, 0) + " $" : "—"} · Mañana ≈ ${num(d.plan_tomorrow) != null ? fmt(d.plan_tomorrow, 0) + " $" : "—"}`)) : null,
        target != null ? el("span", {}, el("span", { class: "bot-muted" }, "Ritmo objetivo "), el("b", { class: "bot-mono" }, "≈ " + fmt(target, 2) + " $/h")) : null,
        target != null && nowRate != null ? el("span", { class: rateTone }, el("span", { class: "bot-muted" }, "Ahora "), el("b", { class: "bot-mono" }, "≈ " + fmt(nowRate, 2) + " $/h"),
          " " + (over <= 0 ? "(dentro del ritmo)" : `(${fmt(over, 2)} $/h por encima)`)) : null].filter(Boolean));
    }
    bar(n.barBrain, num(d.spent_today) || 0, num(d.cap_today) || 0);
    bar(n.barDay, num(d.day_total_spent) || 0, num(d.day_cap) || 0);
    n.proj.textContent = num(d.projected_spend_by_close) != null ? usd(d.projected_spend_by_close) : "—";
    n.proj.className = "bot-mono" + (num(d.day_cap) && d.projected_spend_by_close > d.day_cap ? " bot-bad" : "");
    n.hours.textContent = num(d.hours_left) != null ? fmt(d.hours_left, 1) + " h" : "—";
    const kh = d.keys_headroom;
    n.head.textContent = kh == null ? "—" : typeof kh === "number" ? usd(kh) : Object.entries(kh).map(([k, v]) => `${k} ${fmt(v, 0)} $`).join(" · ");
    for (const k of ["brain_day_cap", "day_cap", "budget_total_usd"]) if (document.activeElement !== n[k]) n[k].value = String((k === "brain_day_cap" ? d.cap_today : k === "day_cap" ? d.day_cap : d.budget_total) ?? "");
  }
  async function brainPull(force) {
    if (!B.host || B.busy || (!force && Date.now() - B.at < 4000)) return;
    B.at = Date.now();
    try { B.data = await A().brainBudget(); B.state = "on"; if (S.root) paintSpend(); }
    catch (e) { B.state = e && e.status === 404 ? "off" : "error"; B.err = e; if (e && e.status === 404) B.data = null; }
    brainPaint();
  }
  async function setBrain(body, done) {
    if (B.busy) return;
    B.busy = true; brainPaint();
    try { await req("POST", "control", body); toast("outcome", done, ""); }
    catch (e) { toast("error", "No se pudo aplicar", e.message || String(e)); }
    finally { B.busy = false; B.at = 0; await brainPull(true); }
  }
  function panel(title, sub, ...kids) {
    return el("section", { class: "bot-panel" }, el("div", { class: "bot-ph" }, el("h2", {}, title), sub ? el("span", { class: "bot-muted bot-mono bot-small" }, sub) : null), el("div", { class: "bot-pb" }, ...kids));
  }
  function saveCaps(form) {
    const cur = { ...(ctrl().caps || {}) };
    const next = { ...cur };
    const lines = [];
    for (const k of CAPS) {
      const raw = form.querySelector(`input[name="${k.id}"]`).value.trim();
      if (raw === "") { if (k.id in next) { delete next[k.id]; lines.push(`${k.label}: por defecto (${k.def} ${k.unit})`); } continue; }
      const v = Number(raw);
      if (!isFinite(v) || v < 0) { S.last = { ok: false, text: `${k.label}: número no válido`, ts: Date.now() / 1000 }; paintControls(); return; }
      if (next[k.id] !== v) lines.push(`${k.label}: ${cur[k.id] ?? "por defecto"} → ${v} ${k.unit}`);
      next[k.id] = v;
    }
    if (!lines.length) { S.capsDirty = false; S.last = { ok: true, text: "Topes sin cambios", ts: Date.now() / 1000 }; paintControls(); return; }
    act({ title: "¿Guardar los topes?", text: lines.join(" · "), confirmLabel: "Sí, guardar", done: "Topes guardados" }, async () => { const r = await setControl({ caps: next }); S.capsDirty = false; return r; });
  }

  function paintAll() {
    if (!S.root) return;
    paintHealth(); paintSpend(); paintLatency(); paintProcs(); paintErrors();
    const ae = document.activeElement;
    if (!(ae && ae.closest && ae.closest(".bot-caps"))) paintControls();
    const w = S.root.querySelector(".bot-warn");
    w.hidden = !S.partial;
    w.textContent = S.partial ? `Algunos datos no llegaron: ${S.partial}` : "";
  }

  window.Screens = window.Screens || {};
  window.Screens["bot"] = {
    title: "Bot",
    mount(root) {
      S.root = root; S.capsDirty = false;
      root.classList.add("scr-bot");
      const sec = (title, cls, sub) => el("section", { class: "bot-panel" }, el("div", { class: "bot-ph" }, el("h2", {}, title), el("span", { class: `${cls}-n bot-muted bot-mono bot-small` }, sub || "")), el("div", { class: `${cls} bot-pb` }, loading()));
      root.replaceChildren(
        el("div", { class: "bot-tiles" }, loading()),
        el("div", { class: "bot-warn", hidden: true }),
        el("div", { class: "bot-grid" },
          el("div", { class: "bot-main" },
            el("section", { class: "bot-panel" }, el("div", { class: "bot-ph" }, el("h2", {}, "Gasto de API"), el("span", { class: "bot-spend-sub bot-muted bot-mono bot-small" })), el("div", { class: "bot-spend bot-pb" }, loading())),
            brainMount(),
            el("div", { class: "bot-row3" }, sec("Escalera de degradado", "bot-ladder"), sec("Latencia", "bot-lat"), sec("Procesos", "bot-procs")),
            sec("Disyuntores, errores y avisos", "bot-errs", "últimas 6 h")),
          el("div", { class: "bot-ctrl" }, loading())));
    },
    async refresh(root, data) {
      S.root = root;
      await load(data);
      paintAll();
      brainPull();
    },
    unmount(root) { S.root = null; root.classList.remove("scr-bot"); },
  };
})();
