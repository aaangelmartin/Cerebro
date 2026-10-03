/* Bot: salud (procesos, pasarela, latencia, gasto, errores) y TODOS los controles.
   Contrato: bazaar/dashboard/CONTRACT.md. Palabras: Encender/Apagar, ENCENDIDO/APAGADO. */
(function () {
  "use strict";
  const U = () => window.ui || {};
  const A = () => window.api || {};
  const t = (k, v) => window.I18N.t(k, v);
  const plural = (n, k, v) => window.I18N.plural(n, k, v);

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
  const fmt = (v, d = 2) => (num(v) == null ? "—" : v.toLocaleString(window.I18N.locale, { minimumFractionDigits: d, maximumFractionDigits: d }));
  const usd = (v) => (num(v) == null ? "—" : fmt(v, 2) + " $");
  function fmtTime(ts) {
    if (U().fmtTime) try { return U().fmtTime(ts, false); } catch (e) { /* fall through */ }
    if (!num(ts)) return "—";
    return new Date(ts * 1000).toLocaleTimeString(window.I18N.locale, { hour: "2-digit", minute: "2-digit" });
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
  const loading = () => (U().loading ? U().loading() : el("div", { class: "bot-state" }, t("common.loading")));
  const empty = (x) => (U().empty ? U().empty(x) : el("div", { class: "bot-state" }, x));
  const errorBox = (e) => (U().error ? U().error(e) : el("div", { class: "bot-state bot-bad" }, t("bot.error", { msg: e && e.message || e })));

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

  // label and text are read on every render so they follow the language
  const named = (prefix, o) => Object.defineProperties(o, {
    label: { get: () => t(prefix + o.id), enumerable: true },
    text: { get: () => t(prefix + o.id + ".text"), enumerable: true },
  });
  const DOMAINS = {
    duels: named("bot.domain.", { id: "duels", icon: "duel", tone: "duelo" }),
    dealers: named("bot.domain.", { id: "dealers", icon: "dealer", tone: "dealer" }),
    market: named("bot.domain.", { id: "market", icon: "market", tone: "compra" }),
    broker: named("bot.domain.", { id: "broker", icon: "broker", tone: "cambio" }),
    packs: named("bot.domain.", { id: "packs", icon: "packs", tone: "puja" }),
  };
  const MODES = [
    named("bot.mode.", { id: "auto", icon: "auto" }),
    named("bot.mode.", { id: "observe", icon: "eye" }),
    named("bot.mode.", { id: "manual", icon: "hand" }),
  ];
  const DUEL_MODES = [named("bot.duel_mode.", { id: "bounded" }), named("bot.duel_mode.", { id: "full" }), named("bot.duel_mode.", { id: "code" })];
  const CAPS = [
    named("bot.cap.", { id: "cash_reserve", unit: "P", def: 15 }),
    named("bot.cap.", { id: "max_spend_per_deal", unit: "P", def: 120 }),
    named("bot.cap.", { id: "max_spend_per_hour", unit: "P", def: 250 }),
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
    if (rows.length < 3) { rows = S.llm.filter((r) => num(r.latency_s) != null).slice(-100); win = t("bot.lat.last_n", { n: rows.length }); }
    const by = {};
    for (const r of rows) {
      const m = /opus/i.test(r.model) ? "Opus" : /sonnet/i.test(r.model) ? "Sonnet" : /haiku/i.test(r.model) ? "Haiku" : (r.model || t("bot.lat.other"));
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
      { id: "bot", p: find(/^bot/i), fallbackAge: st && st.age_s },
      { id: "broker", p: find(/broker/i) },
      { id: "lab", p: find(/lab/i) },
      { id: "recorder", p: find(/record|grabad/i) },
      { id: "api", p: { ok: !S.err, age_s: 0 } },
    ];
    return list.map((x) => {
      const age = x.p ? x.p.age_s : x.fallbackAge;
      const ok = x.p ? (x.p.ok === true ? true : x.p.ok === false ? false : null) : null;
      return { id: x.id, name: t("bot.proc." + x.id), age, ok, warn: !!(x.p && x.p.warn), known: !!x.p };
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
      if (r.error || r.abandoned || r.late) out.push({ ts: r.ts, kind: r.error ? "error" : "aviso", where: `llm.${r.purpose || "?"}`, text: r.error ? String(r.error).slice(0, 160) : t(r.abandoned ? "bot.err.abandoned" : "bot.err.late", { model: r.model || "Claude", s: fmt(r.latency_s, 1) }) });
    }
    const b = st.breakers || {};
    if (b.cautious) out.push({ ts: st.updated, kind: "breaker", where: "breaker", text: t("bot.err.cautious", { tick: b.cautious_until }) });
    for (const [d, tk] of Object.entries(b.paused_until || {})) if (num(tk) != null && tk >= (st.tick || 0)) out.push({ ts: st.updated, kind: "breaker", where: d, text: t("bot.err.paused", { domain: (DOMAINS[d] || {}).label || d, tick: tk }) });
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
      tile("cpu", t("bot.tile.procs"), `${okN}/${ps.length}`, unknown.length ? t("bot.tile.no_beat", { list: unknown.join(", ") }) : t("bot.tile.beat", { age: fmtAge(maxAge) }), pLevel, pLevel === "ok" ? "OK" : pLevel === "bad" ? t("bot.chip.check") : t("bot.chip.watch")),
      tile("gate", t("bot.tile.gateway"), rps != null ? t("bot.tile.rps", { n: fmt(rps, 1) }) : gw && num(gw.latency_ms) != null ? `${Math.round(gw.latency_ms)} ms` : "—",
        gw ? (gw.ok ? t("bot.responding") : t("bot.not_responding")) + (rps != null && num(gw.latency_ms) != null ? ` · ${Math.round(gw.latency_ms)} ms` : "") : t("bot.no_data"), gwLevel, gw ? (gw.ok ? "OK" : t("bot.chip.down")) : "—"),
      tile("clock", t("bot.tile.latency"), op ? `${fmt(op.p50, 1)} / ${fmt(op.p90, 1)} s` : "—", op ? t("bot.tile.latency_sub", { win: lat.win, n: op.n }) : t("bot.tile.no_calls"), latLevel, op ? (latLevel === "ok" ? "OK" : latLevel === "bad" ? t("bot.chip.slow") : t("bot.chip.watch")) : "—"),
      tile("wallet", t("bot.tile.spend"), usd(sp.usd), t("bot.tile.spend_sub", { cap: usd(sp.cap), model: modelName(sp.model_now) }), spLevel, spLevel === "ok" ? "OK" : spLevel === "bad" ? t("bot.chip.cap") : t("bot.chip.degraded")),
      tile("warn", t("bot.tile.errors"), String(errs.length), [plural(nb, "bot.n_breakers"), plural(ne, "bot.n_errors"), t("bot.n_notices", { n: errs.length - nb - ne })].join(" · "), errLevel, errLevel === "ok" ? "OK" : t("bot.chip.check")));
  }
  function modelName(m) { return !m ? "—" : /opus/i.test(m) ? "Opus" : /sonnet/i.test(m) ? "Sonnet" : /haiku/i.test(m) ? "Haiku" : /cli|mac/i.test(m) ? t("bot.model.mac") : m; }

  function barList(title, obj, total, extra) {
    const entries = Object.entries(obj || {}).map(([k, v]) => [k, typeof v === "object" && v ? (v.usd_today ?? v.usd ?? 0) : v]).filter(([, v]) => num(v) != null).sort((a, b) => b[1] - a[1]);
    const max = Math.max(total || 0, ...entries.map((e) => e[1]), 0.0001);
    return el("div", { class: "bot-blist" }, el("div", { class: "bot-cap" }, title),
      ...(entries.length ? entries.map(([k, v]) => el("div", { class: "bot-brow" },
        el("div", { class: "bot-brow-h" }, el("span", {}, extra ? extra.label(k) : k), el("span", { class: "bot-mono bot-muted bot-small" }, extra && extra.note ? extra.note(k) : ""), el("span", { class: "bot-mono" }, usd(v))),
        el("div", { class: "bot-bar" }, el("span", { style: `width:${Math.max(1, Math.round((v / max) * 100))}%` }))))
        : [el("div", { class: "bot-muted bot-small" }, t("bot.no_spend"))]));
  }
  const purposeName = (k) => (U().purposeLabel ? U().purposeLabel(k) : k);

  // "Por clave": state chip, reason and since when, errors in the last 15 min, last error, spend today vs cap
  function keyList(sp) {
    const kh = window.__keyHealth || (window.ui.keyHealth ? window.ui.keyHealth(sp, [], null) : { keys: [] });
    const max = Math.max(0.0001, ...kh.keys.map((k) => Math.max(k.usd, +k.cap || 0)));
    const at = (ts) => (ts ? window.ui.fmtTime(ts) : null);
    return el("div", { class: "bot-blist bot-keys" }, el("div", { class: "bot-cap" }, t("bot.key.title")),
      ...(kh.keys.length ? kh.keys.map((k) => el("div", { class: "bot-key tone-" + k.tone },
        el("div", { class: "bot-brow-h" }, el("b", {}, t("bot.key.name", { label: k.label })),
          el("span", { class: "tag res tone-" + (k.tone === "ok" ? "ok" : k.tone) + " bot-key-chip" }, k.chip),
          el("span", { class: "bot-mono" }, usd(k.usd) + (k.cap ? " / " + fmt(k.cap, 0) + " $" : ""))),
        el("div", { class: "bot-bar" }, el("span", { style: `width:${Math.max(1, Math.round((k.usd / max) * 100))}%` })),
        k.ok ? el("div", { class: "bot-muted bot-small", title: k.lastError || "" }, k.errors15
            ? t("bot.key.back", { n: k.errors15 }) + (k.lastErrorTs ? t("bot.key.last_at", { time: at(k.lastErrorTs) }) : "") + (window.ui.keyProblem(k.lastError) ? ` (${window.ui.keyProblem(k.lastError).label.toLowerCase()})` : "")
            : t("bot.key.no_errors"))
          : el("div", { class: "bot-key-why" },
            el("div", {}, k.text),
            el("div", { class: "bot-muted bot-small bot-mono" }, [k.since ? t("bot.key.since", { time: at(k.since) }) : null, t("bot.key.errors15", { n: k.errors15 })].filter(Boolean).join(" · ")),
            k.lastError ? el("div", { class: "bot-muted bot-small bot-key-last", title: k.lastError }, t("bot.key.last_error", { text: k.lastError })) : null)))
        : [el("div", { class: "bot-muted bot-small" }, t("bot.key.none"))]));
  }
  function keyAlert() {
    const kh = window.__keyHealth;
    if (!kh || !kh.bad.length) return null;
    const hard = kh.allDown || kh.bad.some((k) => k.tone === "bad");
    const okL = kh.okLabels;
    return el("div", { class: "bot-keyalert tone-" + (hard ? "bad" : "warn") }, ic("warn", 16),
      el("div", {}, el("b", {}, kh.allDown ? t("bot.key.all_down")
        : t("bot.key.alert", { bad: kh.bad.map((k) => t("bot.key.alert_item", { label: k.label, chip: k.chip.toLowerCase() })).join(" · "), ok: okL.length ? okL.join(", ") : t("bot.key.alert_none") })),
        ...kh.bad.map((k) => el("div", { class: "bot-small" }, t("bot.key.detail", { label: k.label, text: k.text }) + (k.since ? ` (${t("bot.key.since", { time: window.ui.fmtTime(k.since) })})` : "")))));
  }
  // one line: where the brain reasons (Mac subscription = 0 $, or the API)
  function macLine(bd) {
    const mb = bd.mac_backend || {}, be = bd.brain_backend || mb.mode;
    if (!be) return null;
    const calls = num(bd.mac_calls_last_hour) ?? num(mb.calls_last_hour), cap = num(bd.mac_calls_per_hour) ?? num(mb.calls_per_hour);
    const st = bd.mac_backend_state || mb.state || "";
    return el("a", { class: "bot-brain-line", href: "#cerebro" }, el("span", { class: "bot-muted" }, t("bot.brain.reasons_with") + " "),
      el("b", {}, be === "api" ? "API" : be === "mac" ? t("bot.brain.mac") : t("bot.brain.auto")),
      el("span", { class: "bot-muted bot-mono" }, (calls != null ? " · " + t("bot.brain.calls_hour", { calls: `${calls}${cap != null ? "/" + cap : ""}` }) : "") + (st ? " · " + t("bot.brain.state", { state: st === "ok" ? "OK" : st }) : "")),
      num(mb.calls_today) ? el("span", { class: "bot-muted" }, " · " + t("bot.brain.plans_today", { n: mb.calls_today })) : null,
      el("span", { class: "bot-brain-go" }, " → " + t("bot.brain.change")));
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
        el("div", { class: "bot-brow-h" }, el("span", {}, purposeName(k)),
          k === "strategy" ? el("span", { class: "bot-mono bot-muted bot-small" }, [num(team.brain_day_cap) != null ? t("bot.team_cap") : null,
            num((bd.mac_backend || {}).calls_today) ? t("bot.brain.plans_mac", { n: bd.mac_backend.calls_today }) : null].filter(Boolean).join(" · ")) : el("span", {}),
          el("span", { class: "bot-mono" }, usd(v), cap != null ? el("span", { class: "bot-muted" }, " / " + usd(cap)) : null,
            pct != null ? el("span", { class: "bot-small bot-pp bot-pp-" + tone }, " " + Math.round(pct) + " %") : null)),
        el("div", { class: "bot-bar" + (tone ? " bot-bar-" + tone : " bot-bar-plain") }, el("span", { style: `width:${Math.max(1, Math.min(100, Math.round(pct != null ? pct : (v / max) * 100)))}%` })));
    });
    const dayCap = num(team.day_cap) != null && num(bd.day_cap) != null ? bd.day_cap : null;
    const planToday = num(plan.plan_today), spentDay = num(bd.day_total_spent) ?? num(sp.usd);
    const res = plan.reserves || {};
    const foot = [];
    if (false) {
      const ref = dayCap != null ? dayCap : planToday;
      const pct = ref > 0 ? (spentDay / ref) * 100 : 0;
      const tone = pct >= 100 ? "bad" : pct >= 80 ? "warn" : "ok";
      foot.push(el("div", { class: "bot-brow bot-ptotal" },
        el("div", { class: "bot-brow-h" }, el("b", {}, t("bot.total_today")), el("span", { class: "bot-mono bot-muted bot-small" }, dayCap != null ? t("bot.team_cap") + (planToday != null ? " · plan " + usd(planToday) : "") : "plan"),
          el("span", { class: "bot-mono" }, usd(spentDay), el("span", { class: "bot-muted" }, " / " + usd(ref)), el("span", { class: "bot-small bot-pp bot-pp-" + tone }, " " + Math.round(pct) + " %"))),
        el("div", { class: "bot-bar bot-bar-" + tone }, el("span", { style: `width:${Math.max(1, Math.min(100, Math.round(pct)))}%` }))));
    }
    if (num(res.today) != null || num(res.tomorrow) != null) {
      const ss = plan.sessions || {};
      foot.push(el("div", { class: "bot-muted bot-small bot-pres" }, t("bot.reserved", { today: num(res.today) != null ? usd(res.today) : "—", tomorrow: num(res.tomorrow) != null ? usd(res.tomorrow) : "—" }),
        ss.duels_today != null ? " " + t("bot.reserved_sessions", { a: ss.duels_today, b: ss.bench_today ?? 0, c: ss.duels_tomorrow ?? 0, d: ss.bench_tomorrow ?? 0 }) : ""));
    }
    return el("div", { class: "bot-blist" }, el("div", { class: "bot-cap" }, t("bot.purpose.title")),
      ...(rows.length ? rows : [el("div", { class: "bot-muted bot-small" }, t("bot.no_spend"))]), ...foot);
  }
  function paintSpend() {
    const box = S.root.querySelector(".bot-spend");
    const sp = S.spend || (S.ov && S.ov.spend);
    if (!sp) { box.replaceChildren(S.err ? errorBox(S.err) : loading()); return; }
    if (B.limits && B.limits.contains(document.activeElement)) return;   // someone is typing a limit: do not rebuild under them
    const cap = num(sp.cap) || 0;
    const scale = Math.max(cap, sp.usd || 0, 1);
    const pctOf = (v) => `${Math.max(0, Math.min(100, (v / scale) * 100))}%`;
    const marks = [["Sonnet", sp.degrade_at], ["Haiku", sp.haiku_at], [t("bot.spend.cap_mark"), cap]].filter(([, v]) => num(v) != null)
      .map(([l, v], i) => el("span", { class: "bot-mark" + (i % 2 ? " is-low" : ""), style: `left:${pctOf(v)}` }, el("span", { class: "bot-mark-l bot-mono" }, `${l} ≥ ${fmt(v, 0)} $`)));
    S.root.querySelector(".bot-spend-sub").textContent = t("bot.spend.sub", { day: sp.day || t("bot.today_lc"), cap: usd(cap) }) + (num(sp.cap_config) != null ? ` (config ${fmt(sp.cap_config, 0)} $${num(sp.share) != null ? ` × ${fmt(sp.share, 2)}` : ""})` : "");
    const calls = sp.calls;
    const bd = B.data || {};
    const lim = limitsEl();
    box.replaceChildren(
      keyAlert() || "",
      budgetKpis(sp),
      el("div", { class: "bot-spend-cols bot-spend-2" }, purposeList(sp),
        el("div", { class: "bot-spend-side" }, keyList(sp), barList(t("bot.spend.by_model"), sp.by_model, null, { label: modelName }),
          el("div", { class: "bot-muted bot-small bot-mono" }, t("bot.spend.calls", { n: calls ?? "—", model: modelName(sp.model_now) }) + (num(sp.degrade_at) != null ? " · " + t("bot.spend.sonnet_from", { usd: fmt(sp.degrade_at, 0) }) : "")),
          el("a", { class: "bot-brain-line", href: "#cerebro" }, el("span", { class: "bot-muted" }, t("bot.brain.intensity") + " "), el("b", { class: "bot-mono" }, String(bd.level ?? "—")),
            el("span", { class: "bot-muted" }, bd.mode ? " · " + (bd.mode === "manual" ? "manual" : "auto") : ""), el("span", { class: "bot-brain-go" }, " → " + t("bot.brain.see"))),
          macLine(bd))),
      lim);
    limitsSync();
    // ladder
    const lad = S.root.querySelector(".bot-ladder");
    const now = modelName(sp.model_now);
    const level = (sp.usd || 0) >= cap && cap ? 3 : now === "Haiku" ? 2 : now === "Sonnet" ? 1 : 0;
    const steps = [
      ["Opus", t("bot.ladder.normal", { usd: fmt(sp.degrade_at, 0) })],
      ["Sonnet", `${fmt(sp.degrade_at, 0)}–${fmt(sp.haiku_at, 0)} $`],
      ["Haiku", `${fmt(sp.haiku_at, 0)}–${fmt(cap, 0)} $`],
      [t("bot.ladder.code_only"), t("bot.ladder.code_when", { usd: fmt(cap, 0) })],
    ];
    S.root.querySelector(".bot-ladder-n").textContent = t("bot.ladder.level", { n: level + 1 });
    lad.replaceChildren(...steps.map(([n, d], i) => el("div", { class: "bot-step" + (i === level ? " is-on" : i < level ? " is-past" : "") },
      el("span", { class: "bot-dot" }), el("span", {}, n), el("span", { class: "bot-mono bot-muted bot-small" }, d))));
  }

  function paintLatency() {
    const box = S.root.querySelector(".bot-lat");
    const lat = latency();
    if (S.llm == null) { box.replaceChildren(empty(t("bot.lat.no_data"))); return; }
    if (!lat || !Object.keys(lat.by).length) { box.replaceChildren(empty(t("bot.lat.none"))); return; }
    S.root.querySelector(".bot-lat-n").textContent = `p50 · p90 · ${lat.win}`;
    const max = Math.max(8, ...Object.values(lat.by).map((v) => v.p90 || 0));
    box.replaceChildren(...Object.entries(lat.by).map(([m, v]) => el("div", { class: "bot-latrow" },
      el("span", {}, m),
      el("span", { class: "bot-latbar" },
        el("span", { class: "bot-latrange" + (v.p90 > 6 ? " is-bad" : v.p90 > 4 ? " is-warn" : ""), style: `left:${(v.p50 / max) * 100}%;width:${Math.max(1, ((v.p90 - v.p50) / max) * 100)}%` }),
        el("span", { class: "bot-latlimit", style: `left:${(6 / max) * 100}%`, title: "6 s" })),
      el("span", { class: "bot-mono bot-small" }, `${fmt(v.p50, 1)}/${fmt(v.p90, 1)} s`))),
      el("div", { class: "bot-small bot-bad" }, t("bot.lat.red_line")));
  }

  function paintProcs() {
    const box = S.root.querySelector(".bot-procs");
    const ps = processes();
    box.replaceChildren(...ps.map((p) => el("div", { class: "bot-proc" },
      el("span", { class: "bot-dot " + (p.ok === true ? (p.warn ? "is-warn" : "is-ok") : p.ok === false ? "is-bad" : "") }),
      el("span", {}, p.name),
      el("span", { class: "bot-mono bot-muted bot-small" }, p.known ? (p.id === "api" ? t("bot.responding") : t("bot.proc.beat", { age: fmtAge(p.age) })) : t("bot.proc.no_beat")))));
  }

  function paintErrors() {
    const box = S.root.querySelector(".bot-errs");
    const list = errorsList();
    const now = Date.now() / 1000;
    const span = 6 * 3600;
    const t0 = now - span;
    const lanes = [["breaker", t("bot.errs.breakers")], ["error", t("bot.errs.errors")], ["aviso", t("bot.errs.notices")]];
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
    box.replaceChildren(timeline, ...(rows.length ? rows : [empty(t("bot.errs.empty"))]));
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
      S.last = { ok: true, text: opts.done || t("bot.done"), ts: Date.now() / 1000 };
      if (res && typeof res === "object" && "armed" in res && !res.error) S.control = { ...ctrl(), ...(res.control && typeof res.control === "object" && !res.control.error ? res.control : res) };
      toast("outcome", opts.done || t("bot.done"), "");
    } catch (e) {
      S.last = { ok: false, text: `${opts.title}: ${e.message || e}`, ts: Date.now() / 1000 };
      toast("error", t("bot.apply_failed"), e.message || String(e));
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
        el("div", { class: "bot-live-t" }, stop ? t("bot.live.stop") : t(on ? "bot.live.on" : "bot.live.off", { mode: mode.label })),
        el("div", { class: "bot-mono bot-muted bot-small" }, [
          st.tick != null ? `tick ${st.tick}` : null, st.state || null, st.doors ? t(st.doors === "open" ? "bot.live.doors_open" : "bot.live.doors_closed") : null,
          num(st.age_s) != null ? t("bot.proc.beat", { age: fmtAge(st.age_s) }) : null, st.write === false && on ? t("bot.live.read_only") : null,
        ].filter(Boolean).join(" · "))));

    const btns = el("div", { class: "bot-btns" },
      el("button", {
        type: "button", class: "bot-b", disabled: S.busy || !ids.length,
        onclick: () => allPaused
          ? act({ title: t("bot.resume_all.title"), text: t("bot.resume_all.text"), confirmLabel: t("bot.yes_resume"), done: t("bot.resume_all.done") }, () => setControl({ paused_domains: [] }))
          : act({ title: t("bot.pause_all.title"), text: t("bot.pause_all.text", { list: ids.map((d) => (DOMAINS[d] || {}).label || d).join(", ") }), confirmLabel: t("bot.yes_pause"), done: t("bot.pause_all.done") }, () => setControl({ paused_domains: ids })),
      }, ic(allPaused ? "play" : "pause"), allPaused ? t("bot.resume") : t("bot.pause")),
      on || (armed() && stop)
        ? el("button", { type: "button", class: "bot-b", disabled: S.busy, onclick: () => act({ title: t("bot.off.title"), text: t("bot.off.text"), confirmLabel: t("bot.off.yes"), danger: true, done: t("bot.off.done") }, () => setControl({ armed: false })) }, ic("power"), t("common.turnOff"))
        : el("button", { type: "button", class: "bot-b bot-b-go", disabled: S.busy || stop, title: stop ? t("bot.on.blocked") : "",
          onclick: () => act({ title: t("bot.on.title"), text: t("bot.on.text", { mode: mode.label, what: mode.text || "" }), confirmLabel: t("bot.on.yes"), done: t("bot.on.done") }, () => setControl({ armed: true })) }, ic("power"), t("common.turnOn")),
      stop
        ? el("button", { type: "button", class: "bot-b bot-b-unstop", disabled: S.busy, onclick: () => act({ title: t("bot.unstop.title"), text: t("bot.unstop.text"), confirmLabel: t("bot.unstop.yes"), done: t("bot.unstop.done") }, () => (A().unstop ? A().unstop() : req("DELETE", "stop"))) }, ic("stop"), t("bot.unstop.label"))
        : el("button", { type: "button", class: "bot-b bot-b-stop", disabled: S.busy, onclick: () => act({ title: t("bot.stop.title"), text: t("bot.stop.text"), confirmLabel: t("bot.stop.yes"), danger: true, done: t("bot.stop.done") }, () => (A().stop ? A().stop() : req("POST", "stop", { by: "dashboard" }))) }, ic("stop"), "STOP"));

    const last = S.last ? el("div", { class: "bot-last " + (S.last.ok ? "bot-ok" : "bot-bad") }, `${S.last.ok ? "✓" : "✕"} ${S.last.text} · ${fmtTime(S.last.ts)}`) : null;

    const modeSeg = seg(MODES, c.mode || "auto", (o) => act({ title: t("bot.mode_change.title", { mode: o.label }), text: `${o.label}: ${o.text}.`, confirmLabel: t("bot.mode_change.yes", { mode: o.label }), done: t("bot.mode_change.done", { mode: o.label }) }, () => setControl({ mode: o.id })));
    const duelSeg = seg(DUEL_MODES, c.duel_claude_mode || "bounded", (o) => act({ title: t("bot.duel_change.title", { mode: o.label }), text: `${o.label}: ${o.text}.`, confirmLabel: t("bot.duel_change.yes", { mode: o.label }), done: t("bot.duel_change.done", { mode: o.label }) }, () => setControl({ duel_claude_mode: o.id })));

    const doms = el("div", { class: "bot-doms" }, ...ids.map((d) => {
      const meta = DOMAINS[d] || { label: d, icon: "code", tone: "anuncio" };
      const isOn = !paused.includes(d);
      const dst = ((st.domains || {})[d] || {}).state;
      return el("div", { class: `bot-dom bot-t-${meta.tone}` }, ic(meta.icon, 13), el("span", {}, meta.label),
        el("span", { class: "bot-grow" }),
        el("span", { class: "bot-mono bot-muted bot-small" }, isOn ? (dst ? dst.replace(/_/g, " ") : t("bot.dom.on")) : t("bot.dom.paused")),
        el("button", {
          type: "button", class: "bot-tg" + (isOn ? " is-on" : ""), role: "switch", "aria-checked": String(isOn), "aria-label": meta.label, disabled: S.busy,
          onclick: () => {
            const next = isOn ? [...new Set([...paused, d])] : paused.filter((x) => x !== d);
            act({ title: t(isOn ? "bot.dom.pause.title" : "bot.dom.resume.title", { domain: meta.label }), text: t(isOn ? "bot.dom.pause.text" : "bot.dom.resume.text", { domain: meta.label }), confirmLabel: isOn ? t("bot.yes_pause") : t("bot.yes_resume"), done: t(isOn ? "bot.dom.pause.done" : "bot.dom.resume.done", { domain: meta.label }) }, () => setControl({ paused_domains: next }));
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
      el("div", { class: "bot-cap-f" }, el("span", { class: "bot-muted bot-small" }, t("bot.caps.hint")), el("span", { class: "bot-grow" }),
        el("button", { type: "button", class: "bot-b bot-b-sm", disabled: S.busy, onclick: () => { S.capsDirty = false; paintControls(); } }, t("bot.caps.undo")),
        el("button", { type: "submit", class: "bot-b bot-b-sm bot-b-go", disabled: S.busy }, t("common.save"))));

    box.replaceChildren(
      panel(t("bot.panel.state"), null, stateBox, btns, last),
      panel(t("bot.panel.mode"), null, modeSeg, el("div", { class: "bot-muted bot-small bot-pad" }, mode.text || "")),
      panel(t("bot.panel.duel_mode"), null, duelSeg),
      panel(t("bot.panel.domains"), t("bot.panel.domains_sub"), doms),
      panel(t("bot.panel.caps"), null, form));
  }
  // ---------- Cerebro · intensidad y presupuesto ----------
  // GET brain/budget -> {mode, level, usd_per_hour_now, table:[{level, interval_ticks, usd_per_hour}], spent_today, cap_today,
  //   day_total_spent, day_cap, projected_spend_by_close, hours_left, keys_headroom, last_change:{ts, from, to, reason}}
  // POST control {brain_intensity, brain_intensity_mode} / {brain_day_cap} / {day_cap}
  const B = { data: null, state: "idle", err: null, busy: false, at: 0, limits: null, n: {} };
  // one collapsed "Cambiar límites" (event total, brain cap today, day cap); built once so typing survives the refresh
  function limitsEl() {
    if (B.limits) return B.limits;
    const n = B.n;
    const capIn = (name, label, help) => {
      const inp = el("input", { name, type: "number", min: "0", step: "1", inputmode: "numeric", class: "bot-brain-cap" });
      const btn = el("button", { type: "button", class: "bot-b bot-b-sm", onclick: async () => {
        const v = Number(inp.value);
        if (!isFinite(v) || v < 0 || inp.value === "") { toast("error", t("bot.limits.invalid"), label); return; }
        const ok = await confirmBox({ title: t("bot.limits.confirm", { label: label.toLowerCase(), usd: fmt(v, 0) }), text: help, confirmLabel: t("bot.limits.yes") });
        if (ok) setBrain({ [name]: v }, `${label}: ${fmt(v, 0)} $`);
      } }, t("common.save"));
      n[name] = inp;
      return el("label", { class: "bot-cap-row" }, el("span", {}, label), el("span", { class: "bot-cap-in" }, inp, el("span", { class: "bot-muted bot-small" }, "$"), btn));
    };
    B.limits = el("details", { class: "bot-limits" }, el("summary", {}, ic("warn", 13), t("bot.limits.title")),
      el("div", { class: "bot-limits-b" },
        capIn("budget_total_usd", t("bot.limits.total"), t("bot.limits.total.help")),
        capIn("brain_day_cap", t("bot.limits.brain"), t("bot.limits.brain.help")),
        capIn("day_cap", t("bot.limits.day"), t("bot.limits.day.help"))));
    return B.limits;
  }
  function limitsSync() {
    const d = B.data, n = B.n; if (!B.limits) return;
    for (const [k, v] of [["budget_total_usd", d && d.budget_total], ["brain_day_cap", d && d.cap_today], ["day_cap", d && d.day_cap]]) {
      if (!n[k]) continue;
      n[k].disabled = !d || B.busy;
      if (document.activeElement !== n[k]) n[k].value = v == null ? "" : String(v);
    }
  }
  // real $/h of the last hour (spend comes in bursts around duels and Market Tests, so a short window misleads), from the LLM call log (all purposes, or only the brain's planning calls)
  function measuredRate(purposes, span) {
    const rows = Array.isArray(S.llm) ? S.llm : [];
    const now = Date.now() / 1000;
    const first = rows.length ? Math.min(...rows.map((r) => r.ts || now)) : now;
    const win = Math.min(span || 3600, now - first);
    if (win < 300) return null;
    let sum = 0;
    for (const r of rows) if (now - (r.ts || 0) <= win && (!purposes || purposes.includes(r.purpose))) sum += num(r.cost_usd) || 0;
    return sum / (win / 3600);
  }
  // the four figures that answer "how are we doing with money", and a one-line verdict
  function budgetKpis(sp) {
    const d = B.data || {}, plan = d.plan || {};
    const tone = (v, ref) => (ref > 0 ? (v > ref ? "bad" : v >= ref * 0.9 ? "warn" : "ok") : "");
    const k = (label, value, sub, tn, pct, sub2) => el("div", { class: "bot-bk" + (tn ? " tone-" + tn : "") }, el("div", { class: "bot-cap" }, label), el("div", { class: "bot-bk-v bot-mono" }, value),
      el("div", { class: "bot-bar bot-bar-" + (tn || "plain") }, el("span", { style: `width:${Math.max(1, Math.min(100, Math.round(pct || 0)))}%` })), el("div", { class: "bot-muted bot-small" }, sub),
      sub2 ? el("div", { class: "bot-muted bot-small" }, sub2) : null);
    const bt = num(d.budget_total), stt = num(d.spent_total);
    const today = num(d.day_total_spent) ?? num(sp.usd) ?? 0;
    const teamDay = num((d.caps_set_by_team || {}).day_cap) != null ? num(d.day_cap) : null;
    const ref = teamDay ?? num(plan.plan_today) ?? num(d.plan_today) ?? num(sp.cap);          // today's cap (team) or plan
    const hours = num(d.hours_left) ?? num(plan.hours_today);
    // like with like: what we really spend per hour (all calls) against what the day's plan allows per hour from now
    const rate = measuredRate(null, 3600), rate30 = measuredRate(null, 1800);
    const allowed = ref != null && hours > 0 ? Math.max(0, ref - today) / hours : num(plan.day_usd_per_hour);
    const brainNow = num(d.usd_per_hour_now), brainTarget = num(d.usd_per_hour_target) ?? num(plan.usd_per_hour_target);
    const proj = rate != null && hours != null ? today + rate * hours : null;
    const verdictTone = proj != null && ref ? tone(proj, ref) : "";
    const tomorrow = bt != null && proj != null ? bt - ((stt ?? today) - today) - proj : num(d.plan_tomorrow);
    const kp = el("div", { class: "bot-bks" },
      k(t("bot.kpi.event"), bt != null ? [usd(stt ?? 0), el("span", { class: "bot-muted" }, " / " + fmt(bt, 0) + " $")] : usd(stt ?? today),
        bt != null ? t("bot.kpi.event_left", { usd: usd(Math.max(0, num(d.remaining_total) ?? bt - (stt || 0))) }) : t("bot.kpi.no_total"), tone(stt || 0, bt), bt ? ((stt || 0) / bt) * 100 : 0),
      k(t("bot.kpi.today"), [usd(today), ref != null ? el("span", { class: "bot-muted" }, " / " + fmt(ref, 0) + " $") : null],
        (teamDay != null ? t("bot.team_cap") : t("bot.kpi.plan_today")) + (num(plan.plan_today) != null && teamDay != null ? " · plan " + fmt(plan.plan_today, 0) + " $" : ""), tone(today, ref), ref ? (today / ref) * 100 : 0),
      k(t("bot.kpi.pace"), rate != null ? "≈ " + fmt(rate, 2) + " $/h" : t("bot.kpi.measuring"),
        t("bot.kpi.avg_hour") + (rate30 != null ? " · " + t("bot.kpi.last30", { v: fmt(rate30, 1) }) : "") + (allowed != null ? " · " + t("bot.kpi.allowed", { v: fmt(allowed, 2) }) : ""), verdictTone, allowed ? Math.min(100, ((rate || 0) / allowed) * 100) : 0,
        brainNow != null ? t("bot.kpi.brain", { v: fmt(brainNow, 2) }) + (brainTarget != null ? " · " + t("bot.kpi.target", { v: fmt(brainTarget, 2) }) : "") : null),
      k(t("bot.kpi.forecast"), proj != null ? "≈ " + usd(proj) : "—",
        (ref != null ? t("bot.kpi.of_today", { v: fmt(ref, 0) }) : "") + (hours != null ? " · " + t("bot.kpi.hours_left", { v: fmt(hours, 1) }) : ""), verdictTone, proj != null && ref ? (proj / ref) * 100 : 0));
    let verdict = null;
    if (proj != null && ref != null) {
      const over = proj - ref;
      verdict = el("div", { class: "bot-verdict tone-" + (over > 0 ? "bad" : verdictTone === "warn" ? "warn" : "ok") }, ic(over > 0 ? "warn" : "wallet", 14),
        el("span", {}, el("b", {}, t(over > 0 ? "bot.verdict.over" : verdictTone === "warn" ? "bot.verdict.tight" : "bot.verdict.fine") + " "),
          t("bot.verdict.body", { proj: fmt(proj, 0), ref: fmt(ref, 0) }) +
          (over > 0 ? " " + t("bot.verdict.excess", { over: fmt(over, 0) }) : "") + (tomorrow != null ? " " + t("bot.verdict.tomorrow", { v: fmt(Math.max(0, tomorrow), 0) }) : "") + "."));
    }
    return el("div", { class: "bot-bkwrap" }, kp, verdict);
  }
  async function brainPull(force) {
    if (!S.root || B.busy || (!force && Date.now() - B.at < 4000)) return;
    B.at = Date.now();
    try { B.data = await A().brainBudget(); B.state = "on"; }
    catch (e) { B.state = e && e.status === 404 ? "off" : "error"; B.err = e; if (e && e.status === 404) B.data = null; }
    if (S.root) paintSpend();
  }
  async function setBrain(body, done) {
    if (B.busy) return;
    B.busy = true; limitsSync();
    try { await req("POST", "control", body); toast("outcome", done, ""); }
    catch (e) { toast("error", t("bot.apply_failed"), e.message || String(e)); }
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
      if (raw === "") { if (k.id in next) { delete next[k.id]; lines.push(t("bot.caps.to_default", { label: k.label, def: k.def, unit: k.unit })); } continue; }
      const v = Number(raw);
      if (!isFinite(v) || v < 0) { S.last = { ok: false, text: t("bot.caps.invalid", { label: k.label }), ts: Date.now() / 1000 }; paintControls(); return; }
      if (next[k.id] !== v) lines.push(k.label + ": " + (cur[k.id] ?? t("bot.caps.default")) + ` → ${v} ${k.unit}`);
      next[k.id] = v;
    }
    if (!lines.length) { S.capsDirty = false; S.last = { ok: true, text: t("bot.caps.unchanged"), ts: Date.now() / 1000 }; paintControls(); return; }
    act({ title: t("bot.caps.confirm"), text: lines.join(" · "), confirmLabel: t("bot.caps.yes"), done: t("bot.caps.saved") }, async () => { const r = await setControl({ caps: next }); S.capsDirty = false; return r; });
  }

  function paintAll() {
    if (!S.root) return;
    paintHealth(); paintSpend(); paintLatency(); paintProcs(); paintErrors();
    const ae = document.activeElement;
    if (!(ae && ae.closest && ae.closest(".bot-caps"))) paintControls();
    const w = S.root.querySelector(".bot-warn");
    w.hidden = !S.partial;
    w.textContent = S.partial ? t("bot.partial", { list: S.partial }) : "";
  }

  window.Screens = window.Screens || {};
  window.Screens["bot"] = {
    get title() { return t("bot.title"); },
    mount(root) {
      S.root = root; S.capsDirty = false;
      root.classList.add("scr-bot");
      const sec = (title, cls, sub) => el("section", { class: "bot-panel" }, el("div", { class: "bot-ph" }, el("h2", {}, title), el("span", { class: `${cls}-n bot-muted bot-mono bot-small` }, sub || "")), el("div", { class: `${cls} bot-pb` }, loading()));
      root.replaceChildren(
        el("div", { class: "bot-tiles" }, loading()),
        el("div", { class: "bot-warn", hidden: true }),
        el("div", { class: "bot-grid" },
          el("div", { class: "bot-main" },
            el("section", { class: "bot-panel" }, el("div", { class: "bot-ph" }, el("h2", {}, t("bot.panel.spend")), el("span", { class: "bot-spend-sub bot-muted bot-mono bot-small" })), el("div", { class: "bot-spend bot-pb" }, loading())),
            el("div", { class: "bot-row3" }, sec(t("bot.panel.ladder"), "bot-ladder"), sec(t("bot.panel.latency"), "bot-lat"), sec(t("bot.tile.procs"), "bot-procs")),
            sec(t("bot.panel.errors"), "bot-errs", t("bot.panel.errors_sub"))),
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
