/* ---- T10 shared data helpers (identical copy in home.js, competicion.js, rivales.js; first one loaded wins) ---- */
(function () {
  if (window.T10D) return;
  const US = "t10";
  const TYPES = ["compra", "venta", "cambio", "puja", "duelo", "dealer", "anuncio"];
  // interface texts: looked up on every read, so a language switch shows on the next paint
  const T = (k, v) => (window.I18N ? window.I18N.t(k, v) : k);
  const lang = () => (window.I18N && window.I18N.lang) || "es";
  const TYPE_LABEL = {};
  for (const k of TYPES) Object.defineProperty(TYPE_LABEL, k, { enumerable: true, get: () => T("home.type." + k) });
  const TYPE_COLOR = { compra: "var(--t-compra, #3fbf7f)", venta: "var(--t-venta, #e5534b)", cambio: "var(--t-cambio, #4c8dff)",
    puja: "var(--t-puja, #e8a33d)", duelo: "var(--t-duelo, #9b7bff)", dealer: "var(--t-dealer, #2bb3a3)", anuncio: "var(--t-anuncio, #8a8f98)" };
  const PERSONAS = { abuela: "Abuela", chato: "Chato" };

  const num = (x) => (x === null || x === undefined || x === "" || isNaN(+x) ? null : +x);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (n, dec = 1) => {
    n = num(n); if (n === null) return "—";
    if (window.ui && ui.fmtNum) return ui.fmtNum(n, dec);
    return n.toLocaleString("es-ES", { minimumFractionDigits: dec, maximumFractionDigits: dec });
  };
  const fmtP = (n) => (num(n) === null ? "—" : (window.ui && ui.fmtP ? ui.fmtP(n) : fmt(n, Number.isInteger(+n) ? 0 : 1) + " P"));
  const hhmm = (ts) => { if (!ts) return "—"; const d = new Date(ts * 1000); return d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Madrid" }); };
  const hhmmss = (ts) => { if (!ts) return "—"; const d = new Date(ts * 1000); return d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "Europe/Madrid" }); };
  const dayKey = (ts) => new Date(ts * 1000).toLocaleDateString("sv-SE", { timeZone: "Europe/Madrid" });

  function el(tag, attrs, ...kids) {
    if (window.ui && ui.el) return ui.el(tag, attrs, ...kids);
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") e.className = v; else if (k === "style") e.style.cssText = v;
      else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v);
    }
    for (const c of kids.flat()) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(String(c)));
    return e;
  }
  function html(str) { const t = document.createElement("template"); t.innerHTML = str.trim(); return t.content.firstElementChild || document.createTextNode(""); }

  // --------- names
  const names = {};
  function teamName(id) {
    if (!id) return "";
    if (PERSONAS[id]) return PERSONAS[id];
    if (names[id]) return names[id];
    const m = /^t(\d+)$/.exec(id); if (m) return "Team " + (+m[1]);
    if (/^m[0-9a-f]{6,}$/.test(id)) return T("home.market_maker");
    return id;
  }
  const isTeam = (id) => /^t\d+$/.test(id || "");

  // --------- generic cached reads
  const cache = {};
  async function cached(key, ttlMs, fn) {
    const c = cache[key];
    if (c && Date.now() - c.at < ttlMs && c.at > (window.__dashForceAt || 0)) return c.val;
    if (c && c.busy) return c.busy;
    const slot = cache[key] = c || {};
    slot.busy = (async () => {
      try { slot.val = await fn(); slot.err = null; } catch (e) { slot.err = e; if (slot.val === undefined) slot.val = null; }
      slot.at = Date.now(); slot.busy = null; return slot.val;
    })();
    return slot.busy;
  }
  const rec = (name, ttl = 10000) => cached("rec:" + name, ttl, () => api.rec(name));
  const recErr = (name) => (cache["rec:" + name] || {}).err || null;

  // --------- incremental streams (kept for the whole page life)
  function stream(name, tail, keep, map) {
    const s = { rows: [], last: null, at: 0, busy: null, err: null, loaded: false, maxSeq: -1 };
    s.pull = function () {
      if (s.busy) return s.busy;
      if (s.loaded && Date.now() - s.at < 2500 && s.at > (window.__dashForceAt || 0)) return Promise.resolve();
      s.busy = (async () => {
        try {
          const r = s.last == null ? await api.recStream(name, { tail }) : await api.recStream(name, { since_seq: s.last, limit: 2000 });
          const rows = (r && r.rows) || [];
          for (const row of rows) {
            if (num(row.seq) !== null && row.seq <= s.maxSeq) continue;
            if (num(row.seq) !== null) s.maxSeq = row.seq;
            const m = map ? map(row) : row; if (m) s.rows.push(m);
          }
          if (s.rows.length > keep) s.rows.splice(0, s.rows.length - keep);
          s.last = r && r.last_seq != null ? r.last_seq : (s.maxSeq >= 0 ? s.maxSeq : (s.last == null ? 0 : s.last));
          s.err = null; s.loaded = true;
        } catch (e) { s.err = e; s.loaded = true; }
        s.at = Date.now(); s.busy = null;
      })();
      return s.busy;
    };
    return s;
  }

  // --------- clock: game hours -> wall time. The game clock does not follow the calendar
  // (it pauses and resumes), so a game hour is placed relative to the live clock, where one
  // game hour takes one real hour. Past events use their recorded timestamps instead.
  let anchors = [], calDays = [];
  function setClock(clock) {
    const t = clock && num(clock.t_hours);
    if (t === null || t === undefined) return;
    const at = num(clock.recorded_at) || num(clock.ts) || Date.now() / 1000;
    anchors = [{ t0: t, o: at, day: clock.today, name: clock.today_name }];
    calDays = ((clock && clock.days) || []).map((d) => ({ day: d.day, name: d.name, o: Date.parse(d.opens) / 1000, c: Date.parse(d.closes) / 1000 })).filter((d) => d.o && d.c);
  }
  function tToWall(t) {
    t = num(t); if (t === null || !anchors.length) return null;
    const a = anchors[0];
    return a.o + (t - a.t0) * 3600;
  }
  const evTs = (e) => num(e.seen_at) || num(e.ts) || tToWall(e.t) || 0;

  // --------- feed events -> normalised rows {type, actor, teams[], text, value, ts, raw}
  function venueName(v) {
    if (!v) return "";
    if (v === "rastro") return "El Rastro";
    const ven = (cache["rec:venues"] || {}).val;
    const x = ven && (ven.venues || []).find((z) => z.venue === v);
    return x ? x.name : v;
  }
  function assetsLabel(assets) { return (assets || []).map((a) => a.ref || a.name || ("#" + a.id)).join(", "); }

  function normalize(e) {
    const p = e.payload || {}; const ts = evTs(e);
    const base = { id: e.seq, ts, tick: e.tick, raw: e, evType: e.type };
    switch (e.type) {
      case "settlement": {
        const items = p.items || [];
        const parties = p.parties || [];
        const persona = p.persona;
        const price = num(p.price);
        const flows = new Set(items.map((i) => i.frm));
        const cards = items.filter((i) => i.kind === "card");
        const ref = assetsLabel(items);
        const where = p.venue ? T("home.ev.where", { venue: venueName(p.venue) }) : "";
        if (persona) {
          const team = parties.find((x) => x !== persona);
          const buy = items.some((i) => i.to === team);
          return { ...base, type: "dealer", actor: team, teams: [team], venue: null,
            text: T(buy ? "home.ev.buys_from" : "home.ev.sells_to", { cards: ref, who: teamName(persona), where: "" }), value: price != null ? fmtP(price) : "", price, items, kind: "settle" };
        }
        if (flows.size > 1 && !price) {
          const [a, b] = parties;
          return { ...base, type: "cambio", actor: a, teams: parties, venue: p.venue, text: T("home.ev.swap", { cards: ref, where }), value: T("home.ev.n_cards", { n: items.length }), items, kind: "settle" };
        }
        const buyer = (items[0] || {}).to, seller = (items[0] || {}).frm;
        const usSell = seller === US;
        const actor = usSell ? seller : buyer;
        return { ...base, type: usSell ? "venta" : "compra", actor, teams: [buyer, seller].filter(Boolean), venue: p.venue,
          text: usSell ? T("home.ev.sells_to", { cards: ref, who: teamName(buyer), where }) : T("home.ev.buys_from", { cards: ref, who: teamName(seller), where }),
          value: price != null ? fmtP(price) : "", price, items, cards, buyer, seller, kind: "settle", fee: p.fee };
      }
      case "offer.listed": {
        const o = p.offer || {}; const g = o.give || {}, w = o.want || {};
        const gA = g.assets || [], wA = w.assets || [];
        const where = T("home.ev.where", { venue: venueName(p.venue || o.venue) });
        const actor = o.maker || e.actor;
        if (gA.length && wA.length) return { ...base, type: "cambio", actor, teams: [actor], venue: p.venue, text: T("home.ev.offers_swap", { give: assetsLabel(gA), want: assetsLabel(wA), where }), value: gA.length + " × " + wA.length, offer: o, kind: "offer" };
        if (gA.length) return { ...base, type: "venta", actor, teams: [actor], venue: p.venue, text: T("home.ev.lists", { cards: assetsLabel(gA), where }), value: fmtP(w.cash), price: num(w.cash), assets: gA, offer: o, kind: "offer" };
        if (wA.length || (w.types || []).length) return { ...base, type: "puja", actor, teams: [actor], venue: p.venue, text: T("home.ev.bids", { cards: assetsLabel(wA) || (w.types || []).map((t) => (typeof t === "string" ? t.replace(/^card:/, "") : t.ref || t.set || t.rarity || JSON.stringify(t))).join(", "), where }), value: "≤ " + fmtP(g.cash), price: num(g.cash), assets: wA, offer: o, kind: "offer" };
        return { ...base, type: "anuncio", actor, teams: [actor], text: T("home.ev.posts", { where }), value: "", offer: o, kind: "offer" };
      }
      case "offer.cancelled": return null;
      case "thread.message": {
        const team = p.team; const who = p.sender === team ? teamName(team) : teamName(p.sender);
        const off = p.offer && (p.offer.give || p.offer.want) ? T("home.ev.with_offer") : "";
        return { ...base, type: "dealer", actor: team, teams: [team], text: who + " → " + (p.sender === team ? teamName(p.with) : teamName(team)) + ": " + (p.text || "").slice(0, 120) + off, value: "", kind: "thread" };
      }
      case "thread.opened": return { ...base, type: "dealer", actor: p.team, teams: [p.team], text: T("home.ev.opens_thread", { who: teamName(p.with) }), value: T("home.ev.new"), kind: "thread" };
      case "duel.closed": {
        const st = p.status === "deal" ? T("home.ev.duel_deal") : p.status === "no_deal" ? T("home.ev.duel_no_deal") : T("home.ev.duel_other", { status: p.status || "?" });
        const teams = [p.buyer, p.seller, p.a, p.b, ...(p.teams || []), ...(p.parties || [])].filter(isTeam);
        return { ...base, type: "duelo", actor: teams[0] || "", teams, text: st + (p.item ? " · " + p.item : "") + (p.duel ? " · #" + p.duel : ""), value: num(p.price) != null ? fmtP(p.price) : "", kind: "duel" };
      }
      case "pack.opened": return { ...base, type: "anuncio", actor: p.team, teams: [p.team], text: T("home.ev.opens_pack") + (p.best ? T("home.ev.best", { card: p.best.ref || p.best.name || "" }) : ""), value: "", kind: "info" };
      case "gift.given": return { ...base, type: "anuncio", actor: p.team, teams: [p.team], text: T("home.ev.gift", { who: teamName(e.actor), items: [...(p.cards || []), ...(p.packs || [])].join(", ") + (p.cash ? " " + fmtP(p.cash) : "") }), value: "", kind: "info" };
      case "level.unlocked": return { ...base, type: "anuncio", actor: p.team, teams: [p.team], text: T("home.ev.level", { level: p.level, who: p.persona_name || teamName(p.persona) }), value: T("home.ev.level_short", { level: p.level }), kind: "info" };
      case "persona.open_to_all": return { ...base, type: "anuncio", actor: "org", teams: [], text: T("home.ev.open_all", { who: p.name || teamName(p.persona), level: p.level }), value: "", kind: "info" };
      case "venue.fee_announced": return { ...base, type: "anuncio", actor: p.venue, teams: [], text: T("home.ev.fee", { pct: fmt((p.fee_bps || 0) / 100, 1), per_card: p.fee_per_card ? T("home.ev.fee_per_card", { n: p.fee_per_card }) : "", venue: venueName(p.venue), tick: p.effective_tick }), value: fmt((p.fee_bps || 0) / 100, 1) + " %", kind: "venue" };
      case "venue.fee_changed": return { ...base, type: "anuncio", actor: p.venue, teams: [], text: T("home.ev.fee_new", { venue: venueName(p.venue) }), value: fmt((p.fee_bps || 0) / 100, 1) + " %", kind: "venue" };
      case "venue.announcement": return { ...base, type: "anuncio", actor: p.venue, teams: [], text: (p.name || venueName(p.venue)) + ": " + (p.text || ""), value: "", kind: "venue" };
      case "announcement": return { ...base, type: "anuncio", actor: "org", teams: [], text: p.text || T("home.type.anuncio"), value: "", kind: "info" };
      default: {
        if (/^venue\./.test(e.type || "")) return { ...base, type: "anuncio", actor: p.venue || "", teams: [], text: (e.type || "") + " · " + venueName(p.venue), value: "", kind: "venue" };
        return { ...base, type: "anuncio", actor: e.actor || "org", teams: isTeam(p.team) ? [p.team] : [], text: (e.type || T("home.ev.event")) + (p.text ? " · " + p.text : ""), value: "", kind: "info" };
      }
    }
  }

  const feed = stream("feed", 3000, 8000, (row) => { const n = normalize(row); return n ? n : { skip: true, raw: row, ts: evTs(row), evType: row.type }; });
  const board = stream("leaderboard", 400, 3000, (row) => {
    const d = row.data || row; let teams = d.teams || [];
    if (!Array.isArray(teams)) teams = Object.values(teams);
    const scores = {}, ranks = {};
    for (const t of teams) { if (!t || !t.team) continue; scores[t.team] = num(t.score); ranks[t.team] = num(t.rank); if (t.name) names[t.team] = t.name; }
    return { ts: num(row.ts) || 0, tick: d.tick, scores, ranks };
  });

  // feed rows (normalised, no skips), re-normalising venue names lazily is not needed
  // the texts of a row are written when it is read: write them again when the language changes
  let feedLang = lang();
  function relang() {
    if (feedLang === lang()) return;
    feedLang = lang();
    feed.rows = feed.rows.map((r) => normalize(r.raw) || { skip: true, raw: r.raw, ts: evTs(r.raw), evType: r.raw.type });
  }
  const events = () => { relang(); return feed.rows.filter((r) => !r.skip); };
  // events of the latest day that has data (today, or Friday when today has nothing yet)
  function dayEvents() {
    const ev = events(); if (!ev.length) return { rows: [], day: null, today: true };
    const today = dayKey(Date.now() / 1000);
    const has = ev.some((e) => e.ts && dayKey(e.ts) === today);
    const day = has ? today : dayKey(ev[ev.length - 1].ts);
    return { rows: ev.filter((e) => e.ts && dayKey(e.ts) === day), day, today: has };
  }
  const involves = (e, tid) => e.actor === tid || (e.teams || []).includes(tid);

  async function leaderboard() {
    const lb = await rec("leaderboard", 5000);
    let teams = (lb && (lb.teams || (lb.data && lb.data.teams))) || [];
    if (!Array.isArray(teams)) teams = Object.values(teams);
    teams = teams.filter((t) => t && t.team).slice().sort((a, b) => (num(a.rank) || 99) - (num(b.rank) || 99));
    for (const t of teams) if (t.name) names[t.team] = t.name;
    return teams;
  }
  function series(tid) { return board.rows.map((r) => r.scores[tid]).filter((x) => x != null); }
  function rankMove(tid) {
    const rows = board.rows; if (rows.length < 2) return 0;
    const last = rows[rows.length - 1]; const ref = rows.filter((r) => last.ts - r.ts >= 3600).pop() || rows[0];
    const a = ref.ranks[tid], b = last.ranks[tid];
    return a != null && b != null ? a - b : 0;
  }

  // --------- tiny SVG charts (own, so axes/colours match the design)
  function svg(w, h, inner, cls, keep) { return html(`<svg class="${cls || ""}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="${keep ? "xMinYMid meet" : "none"}" width="100%" height="${h}">${inner}</svg>`); }
  function stackBars(buckets, opts = {}) {
    // buckets: [{counts:{type:n}}]
    const w = opts.w || 300, h = opts.h || 60, gap = opts.gap == null ? 2 : opts.gap; const n = buckets.length || 1;
    const max = Math.max(1, ...buckets.map((b) => TYPES.reduce((s, t) => s + (b.counts[t] || 0), 0)));
    const bw = w / n - gap; let out = "";
    buckets.forEach((b, i) => {
      let y = h;
      for (const t of TYPES) {
        const v = b.counts[t] || 0; if (!v) continue;
        const bh = (v / max) * (h - 2); y -= bh;
        out += `<rect x="${(i * (w / n) + gap / 2).toFixed(1)}" y="${y.toFixed(1)}" width="${Math.max(1, bw).toFixed(1)}" height="${Math.max(0.5, bh - 1).toFixed(1)}" fill="${TYPE_COLOR[t]}"><title>${esc(b.label || "")} · ${TYPE_LABEL[t]}: ${v}</title></rect>`;
      }
    });
    return svg(w, h, out, "t10-stack");
  }
  function spark(values, opts = {}) {
    const w = opts.w || 120, h = opts.h || 24; const v = values.filter((x) => x != null);
    if (v.length < 2) return svg(w, h, `<line x1="0" y1="${h / 2}" x2="${w}" y2="${h / 2}" stroke="var(--line, #333)" stroke-dasharray="2 3"/>`, "t10-spark");
    const lo = Math.min(...v), hi = Math.max(...v), r = hi - lo || 1;
    const pts = v.map((x, i) => `${((i / (v.length - 1)) * w).toFixed(1)},${(h - 2 - ((x - lo) / r) * (h - 4)).toFixed(1)}`).join(" ");
    const col = opts.color || (v[v.length - 1] > v[0] ? "var(--t-compra, #3fbf7f)" : v[v.length - 1] < v[0] ? "var(--t-venta, #e5534b)" : "var(--ink-3, #8a8f98)");
    return svg(w, h, `<polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.4" vector-effect="non-scaling-stroke"/>`, "t10-spark");
  }
  function bucketize(rows, n, t0, t1) {
    const span = Math.max(1, t1 - t0); const out = [];
    for (let i = 0; i < n; i++) out.push({ t: t0 + (span * i) / n, label: hhmm(t0 + (span * i) / n), counts: {}, rows: [] });
    for (const r of rows) {
      if (!r.ts || r.ts < t0 || r.ts > t1) continue;
      const i = Math.min(n - 1, Math.floor(((r.ts - t0) / span) * n));
      out[i].counts[r.type] = (out[i].counts[r.type] || 0) + 1; out[i].rows.push(r);
    }
    return out;
  }

  // --------- UI fallbacks
  function chip(type, label, count) {
    if (window.ui && ui.typeChip) return ui.typeChip(type, label, count);
    return el("span", { class: "t10-chip t10-" + type }, (label || TYPE_LABEL[type] || type) + (count != null ? " " + count : ""));
  }
  function teamTag(id) {
    if (!id) return el("span", { class: "t10-muted" }, "—");
    if (isTeam(id) && window.ui && ui.teamTag) return ui.teamTag(id, { us: id === US });
    return el("span", { class: "t10-who" + (id === US ? " t10-us" : "") }, id === US ? T("home.us_full") : (id === "org" ? T("home.org") : teamName(id) || venueName(id)));
  }
  const state = (kind, text) => {
    if (window.ui) { if (kind === "loading" && ui.loading) return ui.loading(); if (kind === "error" && ui.error) return ui.error(text); if (kind === "empty" && ui.empty) return ui.empty(text); }
    return el("div", { class: "t10-state" }, kind === "loading" ? T("home.loading") : kind === "error" ? T("home.error", { err: (text && text.message) || text }) : text);
  };
  const errText = (e) => (e && e.status === 404 ? T("home.err_404") : T("home.err_read", { err: (e && e.message) || e }));
  function replace(node, ...kids) { if (!node) return; node.replaceChildren(...kids.flat().filter((k) => k != null)); }

  async function prime() {
    const c = await rec("clock", 5000); if (c) setClock(c);
    await rec("venues", 15000);
  }

  window.T10D = { prime, US, TYPES, TYPE_LABEL, TYPE_COLOR, num, esc, fmt, fmtP, hhmm, hhmmss, dayKey, el, html, teamName, isTeam, venueName,
    cached, rec, recErr, stream, setClock, tToWall, evTs, normalize, feed, board, events, dayEvents, involves, leaderboard, series, rankMove,
    svg, stackBars, spark, bucketize, chip, teamTag, state, errText, replace, names, anchors: () => anchors, calDays: () => calDays };
})();
/* ---- COMPETICIÓN ---- */
(function () {
  const D = window.T10D;
  const { el, fmt, fmtP, num, hhmm, TYPES, US } = D;
  const tr = (k, v) => window.I18N.t(k, v);
  const RAR = [["legendary", "common.rarity.legendary", "var(--ink,#f2f2f2)"], ["epic", "common.rarity.epic", "#c9c9c9"], ["rare", "common.rarity.rare", "#9a9a9a"], ["uncommon", "competicion.rarity.uncommon", "#737373"], ["common", "common.rarity.common", "#555"]];
  const REF_COLORS = ["var(--ink,#f2f2f2)", "var(--t-cambio,#4c8dff)", "var(--t-puja,#e8a33d)", "var(--t-dealer,#2bb3a3)"];
  let S = null;

  function mount(root) {
    S = { mode: "rareza", drawerFor: null, gtab: "all" };
    try { S.gtab = localStorage.getItem("t10.comp.gtab") || "all"; } catch (e) { /* storage blocked */ }
    root.innerHTML = "";
    let tab = "precios";
    try { tab = localStorage.getItem("t10.comp.tab") || "precios"; } catch (e) { /* storage blocked */ }
    root.append(el("div", { class: "scr-competicion c-tab-" + tab },
      el("div", { class: "c-tabs" },
        el("button", { class: "t10-seg" + (tab === "precios" ? " on" : ""), "data-tab": "precios" }, tr("competicion.tab.prices")),
        el("button", { class: "t10-seg" + (tab === "mercados" ? " on" : ""), "data-tab": "mercados" }, tr("competicion.allMarkets"))),
      el("section", { class: "t10-panel c-global" },
        el("div", { class: "t10-head" }, el("h2", {}, tr("competicion.global.title")), el("span", { class: "t10-sub t10-right c-global-sub" }, "")),
        el("div", { class: "c-global-body" }, D.state("loading"))),
      el("div", { class: "c-top" },
        el("section", { class: "t10-panel c-chart" },
          el("div", { class: "t10-head" }, el("h2", {}, tr("competicion.chart.title")),
            el("span", { class: "t10-right c-toggle" },
              el("button", { class: "t10-seg on", "data-m": "rareza" }, tr("competicion.chart.byRarity")), el("button", { class: "t10-seg", "data-m": "carta" }, tr("competicion.chart.byCard"))),
            el("span", { class: "t10-sub c-win" }, "")),
          el("div", { class: "c-legend" }), el("div", { class: "c-lines" }, D.state("loading")),
          el("div", { class: "t10-cap c-volcap" }, tr("competicion.chart.volByType")), el("div", { class: "c-vol" })),
        el("section", { class: "t10-panel c-venues" },
          el("div", { class: "t10-head" }, el("h2", {}, tr("competicion.venues")), el("span", { class: "t10-sub t10-right" }, tr("competicion.volShareLower"))),
          el("div", { class: "c-venue-list" }, D.state("loading")))),
      el("div", { class: "c-bottom" },
        el("section", { class: "t10-panel c-book c-book-a" }, D.state("loading")),
        el("section", { class: "t10-panel c-book c-book-b" }, D.state("loading")),
        el("section", { class: "t10-panel c-mt" },
          el("div", { class: "t10-head" }, el("h2", {}, tr("competicion.mt.title")), el("span", { class: "t10-sub t10-right" }, tr("competicion.mt.sub"))),
          el("div", { class: "c-mt-body" }, D.state("loading")))),
      el("section", { class: "t10-panel c-markets" },
        el("div", { class: "t10-head" }, el("h2", {}, tr("competicion.allMarkets")), el("span", { class: "t10-sub t10-right" }, tr("competicion.allMarkets.sub"))),
        el("div", { class: "c-markets-body" }))));
    if (window.T10Markets) window.T10Markets.mount(root.querySelector(".c-markets-body"));
    root.querySelectorAll(".c-tabs button").forEach((b) => b.addEventListener("click", () => {
      const scr = root.querySelector(".scr-competicion"), t = b.dataset.tab;
      scr.classList.toggle("c-tab-precios", t === "precios"); scr.classList.toggle("c-tab-mercados", t === "mercados");
      root.querySelectorAll(".c-tabs button").forEach((x) => x.classList.toggle("on", x === b));
      try { localStorage.setItem("t10.comp.tab", t); } catch (e) { /* storage blocked */ }
      if (t === "mercados" && window.T10Markets) window.T10Markets.refresh();
    }));
    root.querySelectorAll(".c-toggle button").forEach((b) => b.addEventListener("click", () => {
      S.mode = b.dataset.m; root.querySelectorAll(".c-toggle button").forEach((x) => x.classList.toggle("on", x === b)); S.lastSeq = null; refresh(root, S.data, S.params);
    }));
  }

  // ---------------------------------------------------------------- the three days
  // The server publishes one table mark per team: the mean of the rounds, each by its weight and phase.
  // Three cuts give every round back: the first one of Saturday (Friday alone), the first one of Sunday
  // (through Saturday, as the organisers left it) and the latest one. Same sums as tools/global_leaderboard.py.
  const PARTS = ["negotiating", "market"];
  function globalBoard(rows) {
    const cuts = [];
    for (const row of rows || []) {
      const d = row.data || row; let teams = d.teams || []; const rounds = d.rounds || [];
      if (!Array.isArray(teams)) teams = Object.values(teams);
      if (!teams.length || !rounds.length) continue;
      const phase = {}, weight = {}, byTeam = {};
      for (const r of rounds) { phase[r.round] = num(r.phase) || 0; weight[r.round] = num(r.weight) || 0; }
      for (const t of teams) if (t && t.team) byTeam[t.team] = t;
      cuts.push({ ts: num(row.ts), tick: d.tick, phase, weight, teams: byTeam, snap: num(d.snapshot_tick), next: num(d.next_refresh_tick) });
    }
    if (!cuts.length) return null;
    const now = cuts[cuts.length - 1];
    const first2 = cuts.find((c) => c.phase[2] != null && c.phase[3] == null) || null;
    const sunday = cuts.filter((c) => c.phase[3] != null);
    const first3 = sunday[0] || null;
    const ph = now.phase[3] || 0, w12 = (now.weight[1] || 0.5) + (now.weight[2] || 1), w3 = now.weight[3] || 1;
    const m = (t, part) => num(t && t[part]) || 0;
    const teams = Object.values(now.teams).map((t) => {
      const row = { team: t.team, name: t.name || t.team, table: num(t.score) || 0, parts: {} };
      for (const part of PARTS) {
        let r1 = null;
        if (first2 && first2.teams[t.team]) { const w1 = first2.weight[1] || 0.5, p2 = first2.phase[2] || 0; r1 = m(first2.teams[t.team], part) * (w1 + p2) / w1; }
        const through2 = first3 && first3.teams[t.team] ? m(first3.teams[t.team], part) * (w12 + (first3.phase[3] || 0)) / w12 : m(t, part);
        const r2 = r1 == null ? null : w12 * through2 - 0.5 * r1;
        const r3 = ph > 0 ? (m(t, part) * (w12 + ph) - w12 * through2) / ph : 0;
        row.parts[part] = { r1, r2, r3, final: (w12 * through2 + w3 * r3) / (w12 + w3) };
      }
      const sum = (k) => PARTS.every((p) => row.parts[p][k] != null) ? PARTS.reduce((a, p) => a + row.parts[p][k], 0) : null;
      row.r1 = sum("r1"); row.r2 = sum("r2"); row.r3 = sum("r3"); row.final = sum("final");
      row.through2 = first3 && first3.teams[t.team] ? (num(first3.teams[t.team].score) || 0) * (w12 + (first3.phase[3] || 0)) / w12 : null;
      row.server = { pages: num(t.pages_complete), album: num(t.album_filled), slots: num(t.album_slots), deals: num(t.deals), level: num(t.level), venue: t.venue || null };
      return row;
    });
    for (const key of ["r1", "r2", "r3", "table", "final"]) {
      teams.filter((t) => t[key] != null).sort((a, b) => b[key] - a[key]).forEach((t, i) => { t["rank_" + key] = i + 1; });
    }
    const top = teams.slice().sort((a, b) => b.table - a.table).slice(0, 5).map((t) => t.team); if (!top.includes(US)) top.push(US);
    teams.sort((a, b) => b.final - a.final);        // by where each team would end
    // Sunday's own mark at every cut of today, for the five best of the day and us
    const top3 = teams.slice().sort((a, b) => b.r3 - a.r3).slice(0, 5).map((t) => t.team); if (!top3.includes(US)) top3.push(US);
    const base = Object.fromEntries(teams.map((t) => [t.team, t.through2]));
    const day3 = new Map();
    for (const c of sunday) {
      const p = c.phase[3] || 0; if (p < 0.1) continue;      // too little of the day played to read it
      day3.set(c.tick, { ts: c.ts, tick: c.tick, scores: Object.fromEntries(top3.map((id) => [id, c.teams[id] && base[id] != null ? ((num(c.teams[id].score) || 0) * (w12 + p) - w12 * base[id]) / p : null])) });
    }
    const seen = new Map();
    for (const c of sunday) seen.set(c.tick, { ts: c.ts, tick: c.tick, scores: Object.fromEntries(top.map((id) => [id, c.teams[id] ? num(c.teams[id].score) : null])) });
    return { tick: now.tick, ts: now.ts, phase: ph, teams, top, timeline: [...seen.values()], top3, timeline3: [...day3.values()], snap: now.snap, next: now.next };
  }

  // the countdown to the next cut: the server says at which tick it refreshes the table
  function tickGlobal(root) {
    const sub = root.querySelector(".c-global-sub"), g = S && S.global; if (!sub || !g) return;
    const wall = g.next != null ? window.ui.tickWall(g.next) : null;
    const left = wall == null ? null : Math.round(wall - Date.now() / 1000);
    const mmss = (s) => String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
    const last = tr("competicion.global.last", { time: g.ts ? window.ui.fmtTime(g.ts) : "—", tick: g.snap, pct: g.pct });
    const next = left == null ? "" : left > 0 ? tr("competicion.global.next", { in: mmss(left), tick: g.next }) : tr("competicion.global.due", { tick: g.next });
    D.replace(sub, el("span", { class: "c-g-clock num" + (left != null && left <= 0 ? " c-g-due" : "") }, next), el("span", { class: "c-g-last" }, last));
    if (left != null && left <= -4 && Date.now() - (S.globalPulled || 0) > 5000) { S.globalPulled = Date.now(); renderGlobal(root).catch(() => {}); }
  }

  async function renderGlobal(root) {
    const box = root.querySelector(".c-global-body"); if (!box) return;
    let doc = null;
    try { doc = globalBoard(((await D.cached("global:lb", 8000, () => api.recStream("leaderboard", { tail: 400 }))) || {}).rows); }
    catch (e) { return D.replace(box, D.state("error", D.errText(e))); }
    if (!doc) return D.replace(box, D.state("empty", tr("competicion.global.none")));
    let me = null; try { me = await D.rec("me", 8000); } catch (e) { me = null; }
    const f = (x, nd = 1) => (x == null ? "—" : fmt(Math.abs(x) < 0.05 ? 0 : x, nd));
    const move = (t) => { const d = t.rank_table - t.rank_final; return d ? el("i", { class: "c-g-move " + (d > 0 ? "c-g-up" : "c-g-down"), title: tr(d > 0 ? "competicion.global.up" : "competicion.global.down", { n: Math.abs(d) }) }, (d > 0 ? "▲" : "▼") + Math.abs(d)) : null; };
    const cell = (v, rank, extra) => el("span", { class: "num c-g-cell" }, f(v), rank ? el("i", { class: "c-g-rank" }, "#" + rank) : null, extra || null);
    const name = (t, extra) => el("span", { class: "c-g-name" }, t.team === US ? tr("common.team10us") : t.name, extra || null);
    // one line per team, the day's five best and us
    function lines(tl, ids, label) {
      if (tl.length < 2) return null;
      const W = 640, H = 140, all = tl.flatMap((r) => Object.values(r.scores).filter((x) => x != null));
      const lo = Math.min(...all) - 0.3, hi = Math.max(...all) + 0.3;
      const x = (i) => (i / (tl.length - 1)) * (W - 70) + 4, y = (v) => H - 14 - ((v - lo) / (hi - lo || 1)) * (H - 24);
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("class", "c-g-chart"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", label);
      ids.forEach((id) => {
        const pts = tl.map((r, i) => (r.scores[id] == null ? null : x(i).toFixed(1) + "," + y(r.scores[id]).toFixed(1))).filter(Boolean);
        const pl = document.createElementNS(svg.namespaceURI, "polyline");
        pl.setAttribute("points", pts.join(" ")); pl.setAttribute("fill", "none"); pl.setAttribute("class", "c-g-line" + (id === US ? " c-g-line-us" : ""));
        svg.append(pl);
      });
      // the labels at the end of each line, pushed apart when two teams are level
      const ends = ids.map((id) => ({ id, v: tl[tl.length - 1].scores[id] })).filter((e) => e.v != null).sort((a, b) => b.v - a.v);
      let prev = -Infinity;
      for (const e of ends) {
        const yy = Math.max(y(e.v) + 3, prev + 10); prev = yy;
        const tx = document.createElementNS(svg.namespaceURI, "text"); tx.setAttribute("x", W - 62); tx.setAttribute("y", yy);
        tx.setAttribute("class", "c-g-lbl" + (e.id === US ? " c-g-lbl-us" : "")); tx.textContent = e.id + " " + f(e.v, 2); svg.append(tx);
      }
      return el("div", { class: "c-g-today" }, el("div", { class: "t10-cap" }, label), svg);
    }
    const src = (k) => el("i", { class: "c-g-src c-g-src-" + k, title: tr("competicion.global.src." + k + ".title") }, tr("competicion.global.src." + k));
    function viewGlobal() {
      const head = el("div", { class: "c-g-row c-g-head t10-cap" },
        el("span", {}, "#"), el("span", {}, tr("common.team")), el("span", {}, tr("competicion.global.fri")), el("span", {}, tr("competicion.global.sat")),
        el("span", {}, tr("competicion.global.sun")), el("span", {}, tr("competicion.global.now")), el("span", {}, tr("competicion.global.final") + " ↓"));
      const rows = doc.teams.map((t) => el("div", { class: "c-g-row" + (t.team === US ? " c-g-us" : "") },
        el("span", { class: "num" }, String(t.rank_final)), name(t, move(t)),
        cell(t.r1, t.rank_r1), cell(t.r2, t.rank_r2),
        cell(t.r3, t.rank_r3, el("i", { class: "c-g-split" }, f(t.parts.negotiating.r3) + " · " + f(t.parts.market.r3))),
        cell(t.table, t.rank_table),
        el("span", { class: "num c-g-cell c-g-strong" }, f(t.final, 2))));
      return [el("div", { class: "c-g-table" }, head, rows), lines(doc.timeline, doc.top, tr("competicion.global.today")), el("div", { class: "t10-small t10-muted c-g-note" }, tr("competicion.global.note"))];
    }
    function viewDay(k) {
      const day = { r1: "fri", r2: "sat", r3: "sun" }[k], sun = k === "r3";
      const by = (part) => { const o = doc.teams.filter((t) => t.parts[part][k] != null).sort((a, b) => b.parts[part][k] - a.parts[part][k]); return Object.fromEntries(o.map((t, i) => [t.team, i + 1])); };
      const rn = by("negotiating"), rm = by("market");
      const teams = doc.teams.filter((t) => t[k] != null).sort((a, b) => b[k] - a[k]);
      if (!teams.length) return [D.state("empty", tr("competicion.global.none"))];
      const head = el("div", { class: "c-g-row c-g-day c-g-head t10-cap" + (sun ? " c-g-day-sun" : "") },
        el("span", {}, "#"), el("span", {}, tr("common.team")),
        el("span", {}, tr("competicion.global.neg"), src("calc")), el("span", {}, tr("competicion.global.mkt"), src("calc")),
        el("span", {}, tr("competicion.global.dayMark", { day: tr("competicion.global." + (sun ? "sunShort" : day)) }) + " ↓", src("calc")),
        sun ? el("span", {}, tr("competicion.global.pages"), src("srv")) : null,
        sun ? el("span", {}, tr("competicion.global.deals"), src("srv")) : null,
        el("span", {}, tr("competicion.global.now"), src("srv")));
      const rows = teams.map((t, i) => el("div", { class: "c-g-row c-g-day" + (sun ? " c-g-day-sun" : "") + (t.team === US ? " c-g-us" : "") },
        el("span", { class: "num" }, String(i + 1)), name(t),
        cell(t.parts.negotiating[k], rn[t.team]), cell(t.parts.market[k], rm[t.team]),
        el("span", { class: "num c-g-cell c-g-strong" }, f(t[k], 2)),
        sun ? el("span", { class: "num c-g-cell" }, t.server.pages == null ? "—" : String(t.server.pages), t.server.album != null ? el("i", { class: "c-g-rank" }, t.server.album + "/" + (t.server.slots || 60)) : null) : null,
        sun ? el("span", { class: "num c-g-cell" }, t.server.deals == null ? "—" : String(t.server.deals)) : null,
        cell(t.table, t.rank_table)));
      const out = [];
      if (sun && me && me.score) {
        const sc = me.score, kv = (label, v, hint) => el("div", { class: "c-g-kv" }, el("span", { class: "t10-cap" }, label), el("b", { class: "num" }, v), hint ? el("span", { class: "t10-small t10-muted" }, hint) : null);
        out.push(el("div", { class: "c-g-ours" },
          el("div", { class: "t10-cap c-g-ours-h" }, tr("competicion.global.ours"), src("srv")),
          el("div", { class: "c-g-kvs" },
            kv(tr("competicion.global.o.neg"), f(num(sc.neg_points), 1), tr("competicion.global.o.neg.h")),
            kv(tr("competicion.global.o.duel"), f(num(sc.duel_points), 2), tr("competicion.global.o.duel.h")),
            kv(tr("competicion.global.o.ladder"), f(num(sc.ladder_points), 3), tr("competicion.global.o.ladder.h")),
            kv(tr("competicion.global.o.bench"), f(num(sc.bench_points), 2), tr("competicion.global.o.bench.h", { eff: f((num(sc.bench_efficiency) || 0) * 100, 1), venue: sc.bench_venue || "—" })),
            kv(tr("competicion.global.o.mm"), f(num(sc.mm_points), 1), tr("competicion.global.o.mm.h")))));
      }
      out.push(el("div", { class: "c-g-table" }, head, rows));
      if (sun) out.push(lines(doc.timeline3, doc.top3, tr("competicion.global.today3")));
      out.push(el("div", { class: "t10-small t10-muted c-g-note" }, tr(sun ? "competicion.global.noteSun" : "competicion.global.noteDay")));
      return out;
    }
    const tab = S.gtab || "all";
    const tabs = el("div", { class: "c-g-tabs" }, [["all", "competicion.global.tab.all"], ["r1", "competicion.global.fri"], ["r2", "competicion.global.sat"], ["r3", "competicion.global.sunShort"]].map(([id, key]) =>
      el("button", { class: "t10-seg" + (tab === id ? " on" : ""), type: "button", onclick: () => { S.gtab = id; try { localStorage.setItem("t10.comp.gtab", id); } catch (e) { /* storage blocked */ } renderGlobal(root).catch(() => {}); } }, tr(key))));
    S.global = { snap: doc.snap || doc.tick, next: doc.next, ts: doc.ts, pct: fmt(doc.phase * 100, 0) };
    tickGlobal(root);
    if (!S.globalTimer) S.globalTimer = setInterval(() => { if (S) tickGlobal(root); }, 1000);
    D.replace(box, [tabs].concat(tab === "all" ? viewGlobal() : viewDay(tab)));
  }

  const settles = (rows) => rows.filter((r) => r.kind === "settle");
  const unitPrice = (r) => { const n = (r.items || []).filter((i) => i.kind === "card").length; return r.price != null && n ? r.price / n : null; };

  // ---------------------------------------------------------------- price lines
  function renderChart(root, day) {
    const rows = day.rows; const box = root.querySelector(".c-lines");
    const st = settles(rows).filter((r) => unitPrice(r) != null && r.type !== "dealer" || (r.type === "dealer" && unitPrice(r) != null));
    if (!rows.length) { D.replace(root.querySelector(".c-legend")); D.replace(root.querySelector(".c-vol")); return D.replace(box, D.state(D.feed.err ? "error" : "empty", D.feed.err ? D.errText(D.feed.err) : tr("competicion.chart.noTrades"))); }
    const t0 = rows[0].ts, t1 = day.today ? Date.now() / 1000 : rows[rows.length - 1].ts;
    root.querySelector(".c-win").textContent = (day.today ? tr("common.today") + " · " : day.day + " · ") + hhmm(t0) + "–" + hhmm(t1);
    let groups;
    if (S.mode === "carta") {
      const cnt = {}; for (const r of st) for (const i of r.items || []) if (i.kind === "card") cnt[i.ref] = (cnt[i.ref] || 0) + 1;
      groups = Object.entries(cnt).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([ref], k) => [ref, ref, REF_COLORS[k], (r) => (r.items || []).some((i) => i.ref === ref)]);
    } else groups = RAR.map(([id, key, col]) => [id, tr(key), col, (r) => (r.items || []).some((i) => i.rarity === id)]);
    const N = 16, span = Math.max(60, t1 - t0);
    const series = groups.map(([id, label, col, fn]) => {
      const b = Array.from({ length: N }, () => []);
      for (const r of st) if (fn(r)) b[Math.min(N - 1, Math.floor(((r.ts - t0) / span) * N))].push(unitPrice(r));
      const vals = b.map((a) => (a.length ? a.sort((x, y) => x - y)[Math.floor(a.length / 2)] : null));
      const last = [...vals].reverse().find((v) => v != null);
      return { id, label, col, vals, last };
    }).filter((s) => s.last != null);
    D.replace(root.querySelector(".c-legend"), series.map((s) => el("span", { class: "c-leg" }, el("i", { style: "background:" + s.col }), s.label + " ", el("b", { class: "num" }, fmtP(Math.round(s.last))))));
    if (!series.length) D.replace(box, D.state("empty", tr("competicion.chart.noSales")));
    else {
      const W = 640, H = 200, L = 30, max = Math.max(1, ...series.flatMap((s) => s.vals.filter((v) => v != null))) * 1.1;
      const x = (i) => L + (i / (N - 1)) * (W - L - 4), y = (v) => H - 18 - (v / max) * (H - 26);
      let s = "";
      for (let k = 0; k <= 4; k++) { const v = (max / 4) * k; s += `<line x1="${L}" x2="${W}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line,#262626)"/><text x="0" y="${y(v) + 3}" class="t10-svgtxt">${Math.round(v)}</text>`; }
      for (let i = 0; i < N; i += 3) s += `<text x="${x(i)}" y="${H - 4}" class="t10-svgtxt" text-anchor="middle">${hhmm(t0 + (span * i) / N)}</text>`;
      for (const se of series) {
        let d = "", pen = false;
        se.vals.forEach((v, i) => { if (v == null) return; d += (pen ? "L" : "M") + x(i).toFixed(1) + "," + y(v).toFixed(1); pen = true; });
        s += `<path d="${d}" fill="none" stroke="${se.col}" stroke-width="1.6" vector-effect="non-scaling-stroke"/>`;
        se.vals.forEach((v, i) => { if (v != null) s += `<rect x="${x(i) - 1.5}" y="${y(v) - 1.5}" width="3" height="3" fill="${se.col}"><title>${D.esc(se.label)} · ${Math.round(v)} P</title></rect>`; });
      }
      D.replace(box, D.svg(W, H, s, "c-svg", true));
    }
    const vb = D.bucketize(rows.filter((r) => r.type !== "anuncio" || true), 12, t0, t1);
    D.replace(root.querySelector(".c-vol"), el("div", { class: "c-vol-legend" }, TYPES.map((t) => D.chip(t))), D.stackBars(vb, { w: 640, h: 56, gap: 4 }));
  }

  // ---------------------------------------------------------------- venues
  function bookStats(book) {
    const offers = (book && book.offers) || []; const asks = [], bids = [];
    for (const o of offers) {
      const g = o.give || {}, w = o.want || {};
      if ((g.assets || []).length && !(w.assets || []).length) asks.push({ ref: g.assets.map((a) => a.ref).join("+"), price: num(w.cash), maker: o.maker, o });
      else if (!(g.assets || []).length && (w.assets || []).length) bids.push({ ref: w.assets.map((a) => a.ref).join("+"), price: num(g.cash), maker: o.maker, o });
    }
    asks.sort((a, b) => (a.price ?? 1e9) - (b.price ?? 1e9)); bids.sort((a, b) => (b.price ?? 0) - (a.price ?? 0));
    const spreads = [];
    for (const a of asks) { const b = bids.find((x) => x.ref === a.ref); if (b && a.price != null && b.price != null) spreads.push(a.price - b.price); }
    return { asks, bids, spread: spreads.length ? spreads.reduce((s, x) => s + x, 0) / spreads.length : null };
  }
  async function loadBooks(venues) {
    const all = await D.rec("books", 8000);
    if (all && typeof all === "object" && !all.offers) return all;
    const out = {};
    await Promise.all(venues.map(async (v) => { out[v.venue] = await D.rec("books/" + v.venue, 8000); }));
    return out;
  }
  function venueRows(ven, day) {
    const list = ((ven && ven.venues) || []).slice();
    const st = settles(day.rows);
    const vol = {}, ops = {};
    for (const r of st) { const k = r.venue || (r.type === "dealer" ? null : "rastro"); if (!k) continue; vol[k] = (vol[k] || 0) + (r.price || 0); ops[k] = (ops[k] || 0) + 1; }
    const tot = Object.values(vol).reduce((s, x) => s + x, 0);
    return list.map((v) => ({ ...v, opsToday: ops[v.venue] || 0, volToday: vol[v.venue] || 0, share: tot ? (vol[v.venue] || 0) / tot : (num(v.volume) || 0) / Math.max(1, list.reduce((s, x) => s + (num(x.volume) || 0), 0)) }))
      .sort((a, b) => b.share - a.share || (num(b.trades) || 0) - (num(a.trades) || 0));
  }
  const feeText = (v) => fmt((num(v.fee_bps) || 0) / 100, (num(v.fee_bps) || 0) % 100 ? 1 : 0) + " %" + (num(v.fee_per_card) ? " + " + v.fee_per_card + " " + tr("competicion.perCard") : "");
  function renderVenues(root, rows, books, ourVenue) {
    const box = root.querySelector(".c-venue-list");
    if (!rows.length) { const e = D.recErr("venues"); return D.replace(box, D.state(e ? "error" : "empty", e ? D.errText(e) : tr("competicion.noVenues"))); }
    D.replace(box, rows.map((v) => {
      const bs = bookStats(books[v.venue]); const ours = v.venue === ourVenue || v.owner === US;
      return el("a", { class: "c-venue" + (ours ? " t10-usrow" : ""), href: "#competicion/" + v.venue },
        el("div", { class: "t10-split" }, el("b", {}, v.name || v.venue), el("span", { class: "t10-small " + (ours ? "" : "t10-muted") }, ours ? tr("common.team10us") : (v.house ? tr("competicion.house") : v.owner_name || D.teamName(v.owner)))),
        el("div", { class: "c-meter" }, el("span", { class: "t10-cap" }, tr("competicion.volShare")), el("span", { class: "c-meter-track" }, el("span", { style: `width:${(v.share * 100).toFixed(1)}%` })), el("span", { class: "num" }, fmt(v.share * 100, 0) + " %")),
        el("div", { class: "c-stats" },
          el("div", {}, el("span", { class: "t10-cap" }, tr("common.fee")), el("span", { class: "num" }, feeText(v))),
          el("div", {}, el("span", { class: "t10-cap" }, tr("competicion.tradesToday")), el("span", { class: "num" }, String(v.opsToday || num(v.trades) || 0))),
          el("div", {}, el("span", { class: "t10-cap" }, tr("competicion.avgSpread")), el("span", { class: "num" }, bs.spread == null ? "—" : fmtP(Math.round(bs.spread * 10) / 10)))),
        v.status && v.status !== "open" ? el("div", { class: "t10-small t10-down" }, tr("competicion.status") + ": " + v.status) : null);
    }));
  }
  function bookPanel(v, book, ourVenue) {
    const panel = [el("div", { class: "t10-head" }, el("h2", {}, v ? v.name || v.venue : tr("competicion.book")), el("span", { class: "t10-sub t10-right" }, v ? tr("competicion.bookLower") + " · " + feeText(v) : ""))];
    if (!v) return panel.concat(D.state("empty", tr("competicion.book.noVenue")));
    if (!book) { const e = D.recErr("books") || D.recErr("books/" + v.venue); return panel.concat(D.state(e ? "error" : "empty", e ? D.errText(e) : tr("competicion.book.empty"))); }
    const bs = bookStats(book);
    const line = (x, bid) => el("div", { class: "c-bk" + (bid ? " c-bid" : "") },
      el("span", { class: "c-ref" }, x.ref), el("span", { class: "num " + (bid ? "c-bidp" : "c-askp") }, (bid ? "≤ " : "") + fmtP(x.price)),
      el("span", { class: x.maker === US ? "t10-us" : "t10-muted" }, x.maker === US ? tr("common.us") : D.teamName(x.maker)));
    panel.push(el("div", { class: "c-bk c-bkh t10-cap" }, el("span", {}, tr("competicion.th.card")), el("span", {}, tr("competicion.th.price")), el("span", {}, tr("common.team"))));
    if (!bs.asks.length && !bs.bids.length) return panel.concat(D.state("empty", tr("competicion.book.noOffers")));
    panel.push(...bs.asks.slice(0, 6).map((x) => line(x, false)));
    panel.push(el("div", { class: "c-spread t10-cap" }, tr("competicion.avgSpread") + " ", el("b", { class: "num" }, bs.spread == null ? "—" : fmtP(Math.round(bs.spread * 10) / 10)), " · " + tr("competicion.book.counts", { asks: bs.asks.length, bids: bs.bids.length })));
    panel.push(...bs.bids.slice(0, 6).map((x) => line(x, true)));
    return panel;
  }

  // ---------------------------------------------------------------- market test
  function renderMT(root, broker, ourRow) {
    const box = root.querySelector(".c-mt-body");
    if (!broker) return D.replace(box, D.state("empty", tr("competicion.mt.noBroker")));
    const hist = ((broker.vs_stall || {}).history || []).slice();
    const lr = broker.last_result;
    if (lr && lr.vs_stall && lr.vs_stall.ours != null && !hist.some((h) => h.run === lr.session)) hist.push({ run: lr.session, ours: lr.vs_stall.ours, stall: lr.vs_stall.stall, basis: lr.vs_stall.basis });
    let chart;
    if (!hist.length) chart = D.state("empty", tr("competicion.mt.noSessions"));
    else {
      const W = 420, H = 150, n = hist.length, bw = Math.min(40, (W - 20) / n - 16);
      let s = "";
      hist.forEach((h, i) => {
        const cx = 20 + (i + 0.5) * ((W - 20) / n), o = num(h.ours) || 0, st = num(h.stall);
        const y = (v) => H - 20 - Math.min(1, v) * (H - 40);
        s += `<rect x="${cx - bw / 2}" y="${y(o)}" width="${bw}" height="${H - 20 - y(o)}" fill="${h.below ? "var(--s2,#2a2a2a)" : "var(--t-compra,#3fbf7f)"}"/>`;
        if (st != null) s += `<rect x="${cx - bw / 2 - 4}" y="${y(st) - 1}" width="${bw + 8}" height="2" fill="var(--t-puja,#e8a33d)"/>`;
        s += `<text x="${cx}" y="${y(o) - 4}" class="t10-svgtxt" text-anchor="middle">${fmt(o, 2)}</text><text x="${cx}" y="${H - 6}" class="t10-svgtxt" text-anchor="middle">${D.esc(String(h.run || "MT" + (i + 1)).slice(-8))}</text>`;
      });
      chart = D.svg(W, H, s, "c-mt-svg", true);
    }
    const ss = broker.session_stats || {};
    D.replace(box, chart,
      el("div", { class: "c-leg-row t10-small" }, el("span", { class: "c-leg" }, el("i", { style: "background:var(--t-compra,#3fbf7f)" }), tr("competicion.mt.ours")), el("span", { class: "c-leg" }, el("i", { style: "background:var(--t-puja,#e8a33d)" }), tr("competicion.mt.stall")),
        el("span", { class: "t10-muted" }, " · " + tr("competicion.mt.mode", { mode: broker.mode || "—" }) + (broker.session ? " · " + tr("competicion.mt.session", { s: broker.session }) : ""))),
      el("div", { class: "t10-cap" }, tr("competicion.mt.activity")),
      el("div", { class: "c-stats c-stats4" },
        el("div", {}, el("span", { class: "t10-cap" }, tr("competicion.trades")), el("span", { class: "num c-bignum" }, String(ourRow ? ourRow.opsToday || num(ourRow.trades) || 0 : "—"))),
        el("div", {}, el("span", { class: "t10-cap" }, tr("competicion.volume")), el("span", { class: "num c-bignum" }, ourRow ? fmtP(ourRow.volToday || num(ourRow.volume) || 0) : "—")),
        el("div", {}, el("span", { class: "t10-cap" }, tr("competicion.mt.matches")), el("span", { class: "num c-bignum" }, String(num(broker.matches_total) ?? num(ss.matches) ?? 0))),
        el("div", {}, el("span", { class: "t10-cap" }, tr("common.fee")), el("span", { class: "num c-bignum" }, ourRow ? feeText(ourRow) : "—"))),
      ourRow ? null : el("div", { class: "t10-muted t10-small" }, tr("competicion.mt.noVenue")));
  }

  // ---------------------------------------------------------------- venue drawer
  function openVenue(v, book, day) {
    if (!v || !(window.ui && ui.drawer)) return;
    const bs = bookStats(book);
    const st = settles(day.rows).filter((r) => (r.venue || "rastro") === v.venue && r.type !== "dealer").slice(-30).reverse();
    const kv = (k, val) => el("div", { class: "t10-kv" }, el("span", { class: "t10-muted" }, k), el("span", { class: "num" }, val == null ? "—" : String(val)));
    const body = el("div", { class: "scr-competicion c-drawer" },
      v.description ? el("p", { class: "t10-muted" }, v.description) : null,
      kv(tr("competicion.owner"), v.house ? tr("competicion.house") : v.owner === US ? tr("common.team10us") : v.owner_name || D.teamName(v.owner)),
      kv(tr("competicion.status"), v.status), kv(tr("common.fee"), feeText(v)),
      v.pending_fee ? kv(tr("competicion.dr.pendingFee"), tr("competicion.dr.pendingFeeVal", { pct: fmt((v.pending_fee.fee_bps || 0) / 100, 1), tick: v.pending_fee.effective_tick })) : null,
      kv(tr("competicion.dr.mechanism"), (v.rules || {}).mechanism), kv(tr("competicion.dr.openedTick"), v.opened_tick),
      kv(tr("competicion.dr.tradesTotal"), v.trades), kv(tr("competicion.dr.volumeTotal"), v.volume != null ? fmtP(v.volume) : null), kv(tr("competicion.dr.feesCollected"), v.fees != null ? fmtP(v.fees) : null),
      kv(tr("competicion.dr.traders"), v.traders), kv(tr("competicion.dr.tradesTodayFeed"), v.opsToday), kv(tr("competicion.dr.shareToday"), fmt(v.share * 100, 1) + " %"),
      kv(tr("competicion.avgSpread"), bs.spread == null ? "—" : fmtP(Math.round(bs.spread * 10) / 10)),
      el("div", { class: "t10-cap" }, tr("competicion.book") + " (" + tr("competicion.book.counts", { asks: bs.asks.length, bids: bs.bids.length }) + ")"),
      ...bookPanel(v, book).slice(1),
      el("div", { class: "t10-cap" }, tr("competicion.dr.latest")),
      st.length ? st.map((r) => el("div", { class: "t10-kv" }, el("span", {}, hhmm(r.ts) + " · " + r.text), el("span", { class: "num" }, r.value))) : D.state("empty", tr("competicion.dr.noTrades")));
    ui.drawer({ title: v.name || v.venue, body, wide: true, onClose: () => { if (/^#competicion\//.test(location.hash)) location.hash = "#competicion"; } });
  }

  async function refresh(root, data, params) {
    if (!S) mount(root);
    S.data = data; S.params = params;
    await D.prime();
    await D.feed.pull();
    const [ven, broker, teams] = await Promise.all([D.rec("venues", 8000), D.cached("broker", 4000, () => api.broker()), D.leaderboard()]);
    const day = D.dayEvents();
    const ourVenue = (data && data.team && data.team.venue) || ((teams.find((t) => t.team === US) || {}).venue) || null;
    const rows = venueRows(ven, day);
    const books = await loadBooks(rows);
    const safe = (f) => { try { f(); } catch (e) { console.error("competicion", e); } };
    if (S.lastSeq !== D.feed.maxSeq) { S.lastSeq = D.feed.maxSeq; safe(() => renderChart(root, day)); }
    safe(() => renderVenues(root, rows, books, ourVenue));
    const ourRow = rows.find((v) => v.venue === ourVenue || v.owner === US) || null;
    const picks = [rows.find((v) => v.venue === "rastro") || rows[0], ourRow || rows.find((v) => v.venue !== "rastro")].filter(Boolean);
    const pA = picks[0], pB = picks[1] && picks[1] !== pA ? picks[1] : rows.find((v) => v !== pA);
    safe(() => D.replace(root.querySelector(".c-book-a"), bookPanel(pA, pA && books[pA.venue], ourVenue)));
    safe(() => D.replace(root.querySelector(".c-book-b"), bookPanel(pB, pB && books[pB.venue], ourVenue)));
    safe(() => renderMT(root, broker, ourRow));
    renderGlobal(root).catch((e) => console.error("competicion", e));
    const want = params ? String(params).split("/")[0] : null;
    if (want && S.drawerFor !== want) { S.drawerFor = want; safe(() => openVenue(rows.find((v) => v.venue === want), books[want], day)); }
    if (!want) S.drawerFor = null;
  }

  window.Screens = window.Screens || {};
  window.Screens["competicion"] = {
    get title() { return tr("competicion.title"); },
    mount(root, params) { mount(root); S.params = params; },
    onParams(root, params) { if (S) S.params = params; },
    async refresh(root, data, params) { if (window.T10Markets) window.T10Markets.refresh(); return refresh(root, data, params); },
    unmount() { if (S && S.globalTimer) clearInterval(S.globalTimer); S = null; },
  };
})();
/* ---- TODOS LOS MERCADOS (sección de Competición) ----
   Todas las tiendas del juego (El Rastro, la nuestra y las de los demás equipos): qué hay en venta y qué se
   busca, cambios, operaciones y anuncios de cada una, y las conversaciones públicas de todos los equipos con
   los dealers. Se elige en la lista de la izquierda (sin tocar el hash, que es del cajón de sedes). */
(function () {
  "use strict";
  const US = "t10", OUR_VENUE_FALLBACK = "v07";
  const U = () => window.ui;
  const tr = (k, v) => window.I18N.t(k, v);
  const el = (...a) => U().el(...a);
  const num = (x) => (x === null || x === undefined || x === "" || isNaN(+x) ? null : +x);
  const fmtP = (n) => (n == null ? "—" : U().fmtP(n));
  const tclock = (tick) => U().tickClock(tick);
  const wallOf = (row) => num(row.seen_at) || num(row.ts) || U().tickWall(row.tick);
  const hhmmss = (ts) => (ts ? U().fmtTime(ts) : "—");
  const isTeam = (id) => /^t\d+$/.test(String(id || ""));

  const S = {
    sel: null, q: "", side: "todo",
    feed: [], lastSeq: null, feedErr: null,
    venues: [], venuesErr: null, books: {}, dealers: {},
    conv: { team: "", dealer: "", q: "", limit: 30 },
  };

  // ---------- data ----------
  async function pullFeed() {
    const api = window.api;
    if (S.lastSeq == null) {
      // the API caps `tail` at 500 rows (a few minutes): read the last 8000 events by pages so "última hora" is real
      const t = await api.recStream("feed", { tail: 1 });
      const last = t && t.last_seq != null ? t.last_seq : ((t && t.rows && t.rows.length) ? t.rows[t.rows.length - 1].seq : 0);
      let seq = Math.max(0, last - 8000), rows = [];
      for (let guard = 0; guard < 6; guard++) {
        const r = await api.recStream("feed", { since_seq: seq, limit: 5000 });
        const got = (r && r.rows) || [];
        rows = rows.concat(got);
        if (got.length) seq = got[got.length - 1].seq;
        if (got.length < 5000) break;
      }
      S.feed = rows;
      S.lastSeq = rows.length ? rows[rows.length - 1].seq : last;
    } else {
      const r = await api.recStream("feed", { since_seq: S.lastSeq, limit: 2000 });
      const rows = (r && r.rows) || [];
      if (rows.length) { S.feed = S.feed.concat(rows).slice(-8000); S.lastSeq = rows[rows.length - 1].seq; }
    }
  }
  async function load() {
    const api = window.api;
    const [v, d] = await Promise.allSettled([api.rec("venues"), Object.keys(S.dealers).length ? Promise.resolve(null) : api.rec("dealers")]);
    if (v.status === "fulfilled") { S.venues = (v.value && v.value.venues) || []; S.venuesErr = null; } else S.venuesErr = v.reason;
    if (d.status === "fulfilled" && d.value) for (const p of d.value.personas || []) if (p && p.id) S.dealers[p.id] = p.name;
    try { await pullFeed(); S.feedErr = null; } catch (e) { S.feedErr = e; }
    if (S.sel === "resumen") {
      await Promise.all(S.venues.map(async (v) => { try { S.books[v.venue] = await api.rec("books/" + v.venue); } catch (e) { S.books[v.venue] = { err: e }; } }));
    } else if (S.sel && S.sel !== "conversaciones") {
      try { S.books[S.sel] = await api.rec("books/" + S.sel); } catch (e) { S.books[S.sel] = { err: e }; }
    }
  }
  function ourVenue() {
    const v = S.venues.find((x) => x.owner === US && x.status !== "closed");
    return v ? v.venue : OUR_VENUE_FALLBACK;
  }
  // who made each offer (public books only show an anonymous maker; the feed says who listed it)
  function makerIndex() {
    const m = {};
    for (const e of S.feed) if (e.type === "offer.listed" && e.payload && e.payload.offer) m[e.payload.offer.id] = e.actor || e.payload.offer.maker;
    return m;
  }

  // ---------- helpers ----------
  const refs = (side) => [
    ...((side && side.assets) || []).map((a) => a.ref || (a.kind === "pack" ? tr("competicion.pack") : "#" + a.id)),
    ...((side && side.types) || []).map((t) => String(t).replace(/^card:/, "").replace(/^pack:/, tr("competicion.pack") + " ")),
  ];
  function offerKind(o) {
    const gc = num(o.give && o.give.cash) || 0, wc = num(o.want && o.want.cash) || 0;
    const gi = refs(o.give).length, wi = refs(o.want).length;
    if (gi && wc && !wi) return "venta";      // they sell a card for cash
    if (wi && gc && !gi) return "puja";       // they want a card and pay cash
    if (gi && wi) return "cambio";
    return gi ? "venta" : "puja";
  }
  function who(id) {
    if (!id) return el("span", { class: "ms-muted" }, tr("competicion.anon"));
    if (isTeam(id)) return U().teamTag(id, { us: id === US });
    if (S.dealers[id]) return el("span", { class: "ms-dealer" }, S.dealers[id]);
    return el("span", { class: "ms-muted", title: tr("competicion.anon.title") }, tr("competicion.anon"));
  }
  const matchQ = (texts) => { const q = S.q.trim().toUpperCase(); return !q || texts.some((t) => String(t || "").toUpperCase().includes(q)); };

  // ---------- render: venue list ----------
  function venueList(root) {
    const host = root.querySelector(".ms-list");
    const ours = ourVenue();
    const order = (v) => (v.venue === "rastro" ? 0 : v.venue === ours ? 1 : 2);
    const vs = S.venues.slice().sort((a, b) => order(a) - order(b) || String(a.venue).localeCompare(String(b.venue)));
    const nTh = new Set(S.feed.filter((e) => e.type === "thread.message").map((e) => e.payload && e.payload.thread)).size;
    const item = (id, title, sub, extra, cls) => el("button", { type: "button", class: ["ms-item", S.sel === id ? "on" : "", cls || ""], onclick: () => { S.sel = id; S.q = ""; render(S.host); T10Markets.refresh(); } },
      el("div", { class: "ms-item-h" }, title, el("span", { class: "ms-grow" }), extra || null), el("div", { class: "ms-item-s" }, sub));
    const rows = vs.map((v) => {
      const fee = v.venue === "rastro" ? "5 % + 1 " + tr("competicion.perCard") : feeText(v);
      const tag = v.venue === "rastro" ? el("span", { class: "ms-muted" }, tr("common.organisers")) : U().teamTag(v.owner, { us: v.owner === US });
      return item(v.venue, el("span", {}, v.name || v.venue),
        el("span", { class: "ms-mono" }, `${v.venue} · ${fee} · ${fmtP(v.volume || 0)} · ` + tr("competicion.mk.venueLine", { trades: v.trades || 0, teams: v.traders || 0, pairs: v.pairs || 0 }) + (openOffers(v.venue) != null ? " · " + tr("competicion.mk.nOffers", { n: openOffers(v.venue).length }) : "")),
        el("div", { class: "ms-item-t" }, tag, v.status && v.status !== "open" ? el("span", { class: "ms-bad" }, v.status) : null),
        v.venue === ours ? "is-us" : v.venue === "rastro" ? "is-rastro" : "");
    });
    host.replaceChildren(
      el("div", { class: "ms-cap" }, tr("competicion.mk.overview")),
      item("resumen", el("span", {}, tr("competicion.allMarkets")), el("span", { class: "ms-mono" }, tr("competicion.mk.sumLine", { n: vs.length, trades: vs.reduce((a, v) => a + (num(v.trades) || 0), 0) }) + " · " + fmtP(vs.reduce((a, v) => a + (num(v.volume) || 0), 0))), null, "is-sum"),
      el("div", { class: "ms-cap" }, "Dealers"),
      item("conversaciones", el("span", {}, U().icon("dealer", 13), " " + tr("competicion.mk.convAll")), el("span", { class: "ms-mono" }, tr("competicion.mk.threads", { n: nTh })), null, "is-conv"),
      el("div", { class: "ms-cap" }, tr("competicion.mk.venuesN", { n: vs.length })),
      ...(rows.length ? rows : [S.venuesErr ? U().error(S.venuesErr) : U().loading()]));
  }
  function feeText(v) {
    const bps = num(v.fee_bps) || 0, per = num(v.fee_per_card) || 0;
    if (!bps && !per) return tr("competicion.zeroFee");
    return `${(bps / 100).toLocaleString(window.I18N.locale)} %` + (per ? ` + ${per} ` + tr("competicion.perCard") : "");
  }

  // ---------- render: one venue ----------
  function venueView(root) {
    const host = root.querySelector(".ms-detail");
    const v = S.venues.find((x) => x.venue === S.sel);
    if (!v) { host.replaceChildren(S.venues.length ? U().empty(tr("competicion.mk.notListed")) : U().loading()); return; }
    const book = S.books[S.sel];
    const makers = makerIndex();
    const offers = book && book.offers ? book.offers.filter((o) => !o.status || o.status === "open") : null;
    const tick = S.feed.length ? S.feed[S.feed.length - 1].tick : null;
    const ours = v.venue === ourVenue();

    const kpi = (l, val, sub) => el("div", { class: "ms-kpi" }, el("span", { class: "ms-kpi-l" }, l), el("b", { class: "ms-mono" }, val), sub ? el("span", { class: "ms-kpi-s" }, sub) : null);
    const head = el("div", { class: ["ms-head", ours ? "is-us" : ""] },
      el("div", { class: "ms-title" }, el("h1", {}, v.name || v.venue), el("span", { class: "ms-mono ms-muted" }, v.venue),
        v.venue === "rastro" ? el("span", { class: "ms-muted" }, tr("common.organisers")) : U().teamTag(v.owner, { us: v.owner === US })),
      v.description ? el("div", { class: "ms-desc" }, v.description) : null,
      el("div", { class: "ms-kpis" },
        kpi(tr("common.fee"), v.venue === "rastro" ? "5 % + 1 P" : feeText(v)),
        kpi(tr("competicion.openOffers"), offers ? String(offers.length) : "—"),
        kpi(tr("competicion.trades"), String(v.trades || 0), fmtP(v.volume || 0)),
        kpi(tr("common.teams"), String(v.traders || 0), tr("competicion.mk.nPairs", { n: v.pairs || 0 })),
        kpi(tr("competicion.fees"), fmtP(v.fees || 0)),
        kpi(tr("competicion.mk.opened"), v.opened_tick != null ? tclock(v.opened_tick) : "—", (v.rules && v.rules.mechanism) || "")));

    const filt = el("div", { class: "ms-filters" },
      el("input", { class: "ms-input", placeholder: tr("competicion.mk.cardPh"), value: S.q, oninput: (e) => { S.q = e.target.value; venueView(root); const i = root.querySelector(".ms-input"); if (i) { i.focus(); i.setSelectionRange(i.value.length, i.value.length); } } }),
      el("div", { class: "ms-seg" }, [["todo", tr("competicion.mk.everything")], ["venta", tr("competicion.forSale")], ["puja", tr("competicion.wanted")], ["cambio", tr("competicion.swaps")]].map(([k, l]) =>
        el("button", { type: "button", class: S.side === k ? "on" : "", onclick: () => { S.side = k; venueView(root); } }, l))));

    let bookBox;
    if (!book) bookBox = U().loading();
    else if (book.err) bookBox = U().error(book.err);
    else {
      const rows = offers.map((o) => ({ o, kind: offerKind(o), give: refs(o.give), want: refs(o.want) }))
        .filter((r) => (S.side === "todo" || r.kind === S.side) && matchQ([...r.give, ...r.want]))
        .sort((a, b) => a.kind.localeCompare(b.kind) || String(a.give[0] || a.want[0]).localeCompare(String(b.give[0] || b.want[0])) || (offerPrice(a.o) - offerPrice(b.o)));
      const counts = { venta: 0, puja: 0, cambio: 0 }; for (const o of offers) counts[offerKind(o)]++;
      bookBox = el("div", { class: "ms-book" },
        el("div", { class: "ms-sec" }, tr("competicion.mk.bookLine", { sale: counts.venta, wanted: counts.puja, swaps: counts.cambio }), book.tick != null ? el("span", { class: "ms-muted" }, " · " + tr("competicion.mk.read") + " " + tclock(book.tick)) : null),
        rows.length ? el("table", { class: "ms-table" },
          el("thead", {}, el("tr", {}, ["type", "gives", "wants", "price", "who", "listed", "expires"].map((x) => el("th", {}, tr("competicion.th." + x))))),
          el("tbody", {}, rows.map(({ o, kind, give, want }) => {
            const mk = makers[o.id] || o.maker;
            return el("tr", { class: ["ms-t-" + kind, mk === US ? "is-us" : ""] },
              el("td", {}, U().typeChip(kind)),
              el("td", { class: "ms-mono" }, [num(o.give && o.give.cash) ? fmtP(o.give.cash) : null, ...give].filter(Boolean).join(" + ") || "—"),
              el("td", { class: "ms-mono" }, [num(o.want && o.want.cash) ? fmtP(o.want.cash) : null, ...want].filter(Boolean).join(" + ") || "—"),
              el("td", { class: "ms-mono ms-r" }, offerPrice(o) ? fmtP(offerPrice(o)) : "—"),
              el("td", {}, who(mk)),
              el("td", { class: "ms-mono ms-muted" }, o.created_tick != null ? tclock(o.created_tick) : "—"),
              el("td", { class: "ms-mono ms-muted" }, o.expires_tick != null ? tclock(o.expires_tick) + (tick != null ? ` · ${Math.max(0, o.expires_tick - tick)} t` : "") : "—"));
          }))) : U().empty(offers.length ? tr("competicion.mk.noMatch") : tr("competicion.mk.emptyBook")));
    }

    // activity on this venue from the feed: trades, listings, cancellations, announcements
    const act = S.feed.filter((e) => e.payload && (e.payload.venue === v.venue || (e.type === "venue.announcement" && e.actor === v.venue)) &&
      ["settlement", "offer.listed", "venue.announcement", "venue.opened", "venue.fee_changed", "venue.fee_announced"].includes(e.type))
      .filter((e) => matchQ([JSON.stringify(e.payload)])).slice(-150).reverse();
    const trades = act.filter((e) => e.type === "settlement");
    const actBox = el("div", { class: "ms-act" },
      el("div", { class: "ms-sec" }, tr("competicion.mk.activity", { trades: trades.length, other: act.length - trades.length })),
      act.length ? act.map(activityRow) : U().empty(tr("competicion.mk.noActivity")));
    host.replaceChildren(head, filt, el("div", { class: "ms-cols" }, bookBox, actBox));
  }
  function openOffers(venue) {
    const b = S.books[venue];
    return b && b.offers ? b.offers.filter((o) => !o.status || o.status === "open") : null;
  }
  // ---------- render: every venue side by side ----------
  function summaryView(root) {
    const host = root.querySelector(".ms-detail");
    const ours = ourVenue();
    const since = Date.now() / 1000 - 3600;
    const lastHour = {}, hourVol = {};
    for (const e of S.feed) if (e.type === "settlement" && e.payload && (wallOf(e) || 0) >= since) {
      const k = e.payload.venue || (e.payload.persona ? null : "rastro");
      if (k) { lastHour[k] = (lastHour[k] || 0) + 1; hourVol[k] = (hourVol[k] || 0) + (num(e.payload.price) || 0); }
    }
    Object.assign(hourVol, U().venueHourVolume(S.feed));   // same rule as the Broker screen
    for (const k of Object.keys(hourVol)) if (!U().venueHourVolume(S.feed)[k]) delete hourVol[k];
    const rows = S.venues.map((v) => {
      const offs = openOffers(v.venue); const c = { venta: 0, puja: 0, cambio: 0 };
      if (offs) for (const o of offs) c[offerKind(o)]++;
      return { v, offs, c, h: lastHour[v.venue] || 0, hv: hourVol[v.venue] || 0 };
    });
    // sortable: click a numeric header (again to flip); default = volume, highest first
    const SORTS = { trades: (r) => num(r.v.trades) || 0, hour: (r) => r.h, volume: (r) => num(r.v.volume) || 0, hvol: (r) => r.hv, traders: (r) => num(r.v.traders) || 0,
      pairs: (r) => num(r.v.pairs) || 0, fees: (r) => num(r.v.fees) || 0, venta: (r) => r.c.venta, puja: (r) => r.c.puja, cambio: (r) => r.c.cambio };
    const sk = SORTS[S.sumSort] ? S.sumSort : "volume", dir = S.sumDir === 1 ? 1 : -1;
    rows.sort((a, b) => dir * (SORTS[sk](a) - SORTS[sk](b)) || (num(b.v.volume) || 0) - (num(a.v.volume) || 0) || String(a.v.venue).localeCompare(String(b.v.venue)));
    const byVol = rows.slice().sort((a, b) => (num(b.v.volume) || 0) - (num(a.v.volume) || 0) || (num(b.v.trades) || 0) - (num(a.v.trades) || 0));
    const volRank = (v) => byVol.findIndex((r) => r.v.venue === v.venue) + 1;
    const tot = rows.reduce((a, r) => ({ t: a.t + (num(r.v.trades) || 0), vol: a.vol + (num(r.v.volume) || 0), o: a.o + (r.offs ? r.offs.length : 0) }), { t: 0, vol: 0, o: 0 });
    const kpi = (l, val) => el("div", { class: "ms-kpi" }, el("span", { class: "ms-kpi-l" }, l), el("b", { class: "ms-mono" }, val));
    const head = el("div", { class: "ms-head" },
      el("div", { class: "ms-title" }, el("h1", {}, tr("competicion.allMarkets")), el("span", { class: "ms-muted" }, tr("competicion.mk.sumSub"))),
      el("div", { class: "ms-kpis" }, kpi(tr("common.venues"), String(rows.length)), kpi(tr("competicion.trades"), String(tot.t)), kpi(tr("competicion.volume"), fmtP(tot.vol)), kpi(tr("competicion.openOffers"), String(tot.o))));
    const n = (x) => el("td", { class: "ms-mono ms-r" }, x);
    const COLS = [["#", null], [tr("common.venue"), null], [tr("competicion.owner"), null], [tr("common.fee"), null], [tr("competicion.volume"), "volume"], [tr("competicion.mk.volHour"), "hvol"], [tr("competicion.trades"), "trades"], [tr("competicion.mk.tradesHour"), "hour"],
      [tr("common.teams"), "traders"], [tr("competicion.mk.pairs"), "pairs"], [tr("competicion.fees"), "fees"], [tr("competicion.forSale"), "venta"], [tr("competicion.wanted"), "puja"], [tr("competicion.swaps"), "cambio"]];
    const th = ([label, key], i) => el("th", { class: [i >= 4 ? "ms-r" : "", key ? "ms-sortable" : "", key === sk ? "is-sorted" : ""],
      onclick: key ? () => { if (S.sumSort === key) S.sumDir = S.sumDir === 1 ? -1 : 1; else { S.sumSort = key; S.sumDir = -1; } summaryView(root); } : null },
      label, key === sk ? (dir === -1 ? " ↓" : " ↑") : "");
    const chart = el("div", { class: "ms-volchart" }, el("div", { class: "ms-cap" }, tr("competicion.mk.volChart")),
      U().venueRanking({ venues: S.venues, hourVol, ours, onPick: (id) => { S.sel = id; render(root); T10Markets.refresh(); } }));
    const table = el("table", { class: "ms-table ms-sum" },
      el("thead", {}, el("tr", {}, COLS.map(th))),
      el("tbody", {}, rows.map(({ v, offs, c, h, hv }) => el("tr", { class: ["ms-click", v.venue === ours ? "is-us" : ""], onclick: () => { S.sel = v.venue; render(root); T10Markets.refresh(); } },
        el("td", { class: "ms-mono ms-muted" }, volRank(v) + "."),
        el("td", {}, el("b", {}, v.name || v.venue), el("span", { class: "ms-mono ms-muted" }, " " + v.venue),
          U().ALLIED_VENUES[v.venue] ? el("span", { class: "tag vrank-tag ally" }, tr("common.ally")) : null,
          v.status && v.status !== "open" ? el("span", { class: "ms-bad" }, " " + v.status) : null),
        el("td", {}, v.venue === "rastro" ? el("span", { class: "ms-muted" }, tr("common.organisers")) : U().teamTag(v.owner, { us: v.owner === US })),
        el("td", { class: "ms-mono" }, v.venue === "rastro" ? "5 % + 1 P" : feeText(v)),
        n(el("b", {}, fmtP(v.volume || 0))), n(hv ? "+" + fmtP(hv) : "—"), n(String(v.trades || 0)), n(h ? "+" + h : "—"),
        n(String(v.traders || 0)), n(String(v.pairs || 0)), n(v.fees ? fmtP(v.fees) : "—"),
        n(offs ? String(c.venta) : "…"), n(offs ? String(c.puja) : "…"), n(offs ? String(c.cambio) : "…")))));
    host.replaceChildren(head, rows.length ? chart : "", rows.length ? el("div", { class: "ms-tablewrap" }, table) : (S.venuesErr ? U().error(S.venuesErr) : U().loading()));
  }
  function offerPrice(o) { return num(o.want && o.want.cash) || num(o.give && o.give.cash) || 0; }
  function activityRow(e) {
    const p = e.payload || {};
    let type = "anuncio", text = "", price = null, team = e.actor;
    if (e.type === "settlement") {
      type = "compra"; price = num(p.price);
      const items = (p.items || []).map((i) => `${i.ref || "#" + i.id} ${i.frm || "?"}→${i.to || "?"}`).join(", ");
      text = tr("competicion.mk.trade", { items }) + (p.fee ? " · " + tr("competicion.mk.feeN", { fee: fmtP(p.fee) }) : ""); team = (p.parties || []).find(isTeam) || e.actor;
    } else if (e.type === "offer.listed") {
      const o = p.offer || {}; type = offerKind(o); price = offerPrice(o);
      text = tr("competicion.mk.listed." + type, { give: [...refs(o.give)].join(", ") || fmtP(o.give && o.give.cash), want: [...refs(o.want)].join(", ") || fmtP(o.want && o.want.cash) });
    } else { text = p.text || p.name || e.type; team = null; }
    return U().row({ type, cells: [
      el("span", { class: "ms-mono ms-muted", title: "tick " + e.tick }, hhmmss(wallOf(e))),
      team ? who(team) : el("span", {}, ""),
      el("span", { class: "ms-txt" }, text),
      el("span", { class: "ms-mono ms-r" }, price ? fmtP(price) : ""),
    ], cols: "64px auto 1fr 64px" });
  }

  // ---------- render: every team's public dealer conversations ----------
  function convView(root) {
    const host = root.querySelector(".ms-detail");
    const threads = new Map();
    for (const e of S.feed) {
      const p = e.payload || {};
      if (e.type !== "thread.message" && e.type !== "thread.opened" && e.type !== "thread.closed") continue;
      const id = p.thread; if (id == null) continue;
      const t = threads.get(id) || { id, team: p.team, with: p.with, topic: null, msgs: [], last: 0, status: "abierta" };
      if (p.team) t.team = p.team; if (p.with) t.with = p.with; if (p.topic) t.topic = p.topic;
      if (e.type === "thread.message") t.msgs.push(e);
      if (e.type === "thread.closed") t.status = p.status || "cerrada";
      t.last = Math.max(t.last, wallOf(e) || 0);
      threads.set(id, t);
    }
    const all = [...threads.values()];
    const teams = [...new Set(all.map((t) => t.team).filter(Boolean))].sort((a, b) => Number(a.slice(1)) - Number(b.slice(1)));
    const dealers = [...new Set(all.map((t) => t.with).filter(Boolean))];
    const f = S.conv;
    const list = all.filter((t) => (!f.team || t.team === f.team) && (!f.dealer || t.with === f.dealer) &&
      (!f.q || JSON.stringify([t.topic, t.msgs.map((m) => m.payload.text)]).toLowerCase().includes(f.q.toLowerCase())))
      .sort((a, b) => b.last - a.last);
    const rerender = () => convView(root);
    const filters = el("div", { class: "ms-filters" },
      el("select", { class: "ms-input", onchange: (e) => { f.team = e.target.value; rerender(); } }, el("option", { value: "" }, tr("competicion.conv.teamAll")),
        teams.map((t) => el("option", { value: t, selected: f.team === t ? "selected" : null }, t === US ? tr("common.us") + " (t10)" : U().teamName(t)))),
      el("select", { class: "ms-input", onchange: (e) => { f.dealer = e.target.value; rerender(); } }, el("option", { value: "" }, tr("competicion.conv.dealerAll")),
        dealers.map((d) => el("option", { value: d, selected: f.dealer === d ? "selected" : null }, S.dealers[d] || d))),
      el("input", { class: "ms-input", placeholder: tr("competicion.conv.searchPh"), value: f.q, onchange: (e) => { f.q = e.target.value; rerender(); } }));
    const cards = list.slice(0, f.limit).map((t) => {
      const msgs = t.msgs.slice().sort((a, b) => (a.payload.message || 0) - (b.payload.message || 0));
      const topic = t.topic ? (t.topic.buy ? tr("competicion.conv.buys") + " " + (t.topic.buy.card || t.topic.buy.pack || JSON.stringify(t.topic.buy)) : t.topic.sell ? tr("competicion.conv.sells") : "") : "";
      return el("article", { class: ["ms-chat", t.team === US ? "is-us" : ""] },
        el("header", { class: "ms-chat-h" }, U().typeChip("dealer", S.dealers[t.with] || t.with || "Dealer"), who(t.team),
          el("span", { class: "ms-grow" }), el("span", { class: "ms-mono ms-muted" }, `#${t.id} · ${tr("competicion.conv.nMsg", { n: msgs.length })} · ${hhmmss(t.last)}`)),
        topic ? el("div", { class: "ms-chat-s ms-mono" }, topic) : null,
        el("div", { class: "ms-msgs" }, msgs.map((m) => {
          const p = m.payload, o = p.offer, fromTeam = isTeam(p.sender);
          const price = o ? offerPrice(o) : null;
          return el("div", { class: ["ms-msg", fromTeam ? "is-team" : "is-dealer", p.sender === US ? "is-us" : ""] },
            el("div", { class: "ms-msg-h" }, el("span", {}, fromTeam ? U().teamName(p.sender) : S.dealers[p.sender] || p.sender),
              price ? el("b", { class: "ms-mono" }, fmtP(price) + (o.final ? " · final" : "")) : null,
              el("span", { class: "ms-mono ms-muted", title: "tick " + m.tick }, hhmmss(wallOf(m)))),
            p.text ? el("div", { class: "ms-msg-t" }, p.text) : o ? el("div", { class: "ms-msg-t ms-muted" }, tr("competicion.conv.offer", { give: refs(o.give).join(", ") || fmtP(o.give && o.give.cash), want: refs(o.want).join(", ") || fmtP(o.want && o.want.cash) })) : null);
        })));
    });
    host.replaceChildren(
      el("div", { class: "ms-head" }, el("div", { class: "ms-title" }, el("h1", {}, tr("competicion.conv.title")), el("span", { class: "ms-muted" }, tr("competicion.conv.sub"))),
        el("div", { class: "ms-desc" }, tr("competicion.conv.count", { n: list.length, total: all.length }) + " · " + (S.feedErr ? tr("competicion.conv.feedError") : tr("competicion.conv.auto")))),
      filters,
      el("div", { class: "ms-chats" }, ...(cards.length ? cards : [S.feed.length ? U().empty(tr("competicion.conv.noMatch")) : U().loading()])),
      list.length > f.limit ? el("button", { type: "button", class: "ms-more", onclick: () => { f.limit += 30; rerender(); } }, tr("competicion.showMore", { n: list.length - f.limit })) : null);
  }

  function render(root) {
    venueList(root);
    if (S.sel === "conversaciones") convView(root); else if (S.sel === "resumen") summaryView(root); else venueView(root);
  }

  const T10Markets = window.T10Markets = {
    mount(host) {
      S.host = host;
      host.replaceChildren(el("div", { class: "scr-mercados" },
        el("aside", { class: "ms-list" }, U().loading()),
        el("section", { class: "ms-detail" }, U().loading())));
    },
    async refresh() {
      const root = S.host; if (!root || !root.isConnected || S.busy) return;
      S.busy = true;
      try {
        if (!S.sel) S.sel = ourVenue();
        await load();
        const special = S.sel === "conversaciones" || S.sel === "resumen";
        if (!S.sel || (!special && !S.venues.some((v) => v.venue === S.sel))) S.sel = ourVenue();
        if (!special && !S.books[S.sel]) await load();
        if (!root.isConnected) return;
        // keep focus while typing in a filter box
        const a = document.activeElement;
        if (a && root.contains(a) && /INPUT|SELECT/.test(a.tagName)) { venueList(root); return; }
        render(root);
      } finally { S.busy = false; }
    },
  };
})();
