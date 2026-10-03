/* ---- T10 shared data helpers (identical copy in home.js, competicion.js, rivales.js; first one loaded wins) ---- */
(function () {
  if (window.T10D) return;
  const US = "t10";
  const TYPES = ["compra", "venta", "cambio", "puja", "duelo", "dealer", "anuncio"];
  const TYPE_LABEL = { compra: "Compra", venta: "Venta", cambio: "Cambio", puja: "Puja", duelo: "Duelo", dealer: "Dealer", anuncio: "Anuncio" };
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
    if (/^m[0-9a-f]{6,}$/.test(id)) return "Creador de mercado";
    return id;
  }
  const isTeam = (id) => /^t\d+$/.test(id || "");

  // --------- generic cached reads
  const cache = {};
  async function cached(key, ttlMs, fn) {
    const c = cache[key];
    if (c && Date.now() - c.at < ttlMs) return c.val;
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
      if (s.loaded && Date.now() - s.at < 2500) return Promise.resolve();
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

  // --------- clock: game hours -> wall time (days run back to back in game hours)
  let anchors = [];
  function setClock(clock) {
    const days = (clock && clock.days) || [];
    let t = 0; anchors = [];
    for (const d of days) {
      const o = Date.parse(d.opens) / 1000, c = Date.parse(d.closes) / 1000;
      if (!o || !c) continue;
      anchors.push({ t0: t, o, c, day: d.day, name: d.name }); t += (c - o) / 3600;
    }
  }
  function tToWall(t) {
    t = num(t); if (t === null || !anchors.length) return null;
    let a = anchors[0];
    for (const x of anchors) if (t >= x.t0 - 1e-6) a = x;
    return a.o + (t - a.t0) * 3600;
  }
  const evTs = (e) => tToWall(e.t) || num(e.seen_at) || num(e.ts) || 0;

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
        const where = p.venue ? " en " + venueName(p.venue) : "";
        if (persona) {
          const team = parties.find((x) => x !== persona);
          const buy = items.some((i) => i.to === team);
          return { ...base, type: "dealer", actor: team, teams: [team], venue: null,
            text: (buy ? "Compra " : "Vende ") + ref + (buy ? " a " : " a ") + teamName(persona), value: price != null ? fmtP(price) : "", price, items, kind: "settle" };
        }
        if (flows.size > 1 && !price) {
          const [a, b] = parties;
          return { ...base, type: "cambio", actor: a, teams: parties, venue: p.venue, text: "Cambian " + ref + where, value: items.length + " cartas", items, kind: "settle" };
        }
        const buyer = (items[0] || {}).to, seller = (items[0] || {}).frm;
        const usSell = seller === US;
        const actor = usSell ? seller : buyer;
        return { ...base, type: usSell ? "venta" : "compra", actor, teams: [buyer, seller].filter(Boolean), venue: p.venue,
          text: usSell ? "Vende " + ref + " a " + teamName(buyer) + where : "Compra " + ref + " a " + teamName(seller) + where,
          value: price != null ? fmtP(price) : "", price, items, cards, buyer, seller, kind: "settle", fee: p.fee };
      }
      case "offer.listed": {
        const o = p.offer || {}; const g = o.give || {}, w = o.want || {};
        const gA = g.assets || [], wA = w.assets || [];
        const where = " en " + venueName(p.venue || o.venue);
        const actor = o.maker || e.actor;
        if (gA.length && wA.length) return { ...base, type: "cambio", actor, teams: [actor], venue: p.venue, text: "Ofrece " + assetsLabel(gA) + " por " + assetsLabel(wA) + where, value: gA.length + " × " + wA.length, offer: o, kind: "offer" };
        if (gA.length) return { ...base, type: "venta", actor, teams: [actor], venue: p.venue, text: "Pone a la venta " + assetsLabel(gA) + where, value: fmtP(w.cash), price: num(w.cash), assets: gA, offer: o, kind: "offer" };
        if (wA.length || (w.types || []).length) return { ...base, type: "puja", actor, teams: [actor], venue: p.venue, text: "Puja por " + (assetsLabel(wA) || (w.types || []).map((t) => (typeof t === "string" ? t.replace(/^card:/, "") : t.ref || t.set || t.rarity || JSON.stringify(t))).join(", ")) + where, value: "≤ " + fmtP(g.cash), price: num(g.cash), assets: wA, offer: o, kind: "offer" };
        return { ...base, type: "anuncio", actor, teams: [actor], text: "Publica una oferta" + where, value: "", offer: o, kind: "offer" };
      }
      case "offer.cancelled": return null;
      case "thread.message": {
        const team = p.team; const who = p.sender === team ? teamName(team) : teamName(p.sender);
        const off = p.offer && (p.offer.give || p.offer.want) ? " · con oferta" : "";
        return { ...base, type: "dealer", actor: team, teams: [team], text: who + " → " + (p.sender === team ? teamName(p.with) : teamName(team)) + ": " + (p.text || "").slice(0, 120) + off, value: "", kind: "thread" };
      }
      case "thread.opened": return { ...base, type: "dealer", actor: p.team, teams: [p.team], text: "Abre conversación con " + teamName(p.with), value: "nueva", kind: "thread" };
      case "duel.closed": {
        const st = p.status === "deal" ? "Duelo cerrado con acuerdo" : p.status === "no_deal" ? "Duelo cerrado sin acuerdo" : "Duelo cerrado (" + (p.status || "?") + ")";
        const teams = [p.buyer, p.seller, p.a, p.b, ...(p.teams || []), ...(p.parties || [])].filter(isTeam);
        return { ...base, type: "duelo", actor: teams[0] || "", teams, text: st + (p.item ? " · " + p.item : "") + (p.duel ? " · #" + p.duel : ""), value: num(p.price) != null ? fmtP(p.price) : "", kind: "duel" };
      }
      case "pack.opened": return { ...base, type: "anuncio", actor: p.team, teams: [p.team], text: "Abre un sobre" + (p.best ? " · mejor: " + (p.best.ref || p.best.name || "") : ""), value: "", kind: "info" };
      case "gift.given": return { ...base, type: "anuncio", actor: p.team, teams: [p.team], text: "Regalo de " + teamName(e.actor) + ": " + [...(p.cards || []), ...(p.packs || [])].join(", ") + (p.cash ? " " + fmtP(p.cash) : ""), value: "", kind: "info" };
      case "level.unlocked": return { ...base, type: "anuncio", actor: p.team, teams: [p.team], text: "Nivel " + p.level + " desbloqueado con " + (p.persona_name || teamName(p.persona)), value: "nivel " + p.level, kind: "info" };
      case "persona.open_to_all": return { ...base, type: "anuncio", actor: "org", teams: [], text: (p.name || teamName(p.persona)) + " abierto a todos (nivel " + p.level + ")", value: "", kind: "info" };
      case "venue.fee_announced": return { ...base, type: "anuncio", actor: p.venue, teams: [], text: "Comisión " + fmt((p.fee_bps || 0) / 100, 1) + " %" + (p.fee_per_card ? " + " + p.fee_per_card + " P/carta" : "") + " en " + venueName(p.venue) + " desde tick " + p.effective_tick, value: fmt((p.fee_bps || 0) / 100, 1) + " %", kind: "venue" };
      case "venue.fee_changed": return { ...base, type: "anuncio", actor: p.venue, teams: [], text: "Nueva comisión en " + venueName(p.venue), value: fmt((p.fee_bps || 0) / 100, 1) + " %", kind: "venue" };
      case "venue.announcement": return { ...base, type: "anuncio", actor: p.venue, teams: [], text: (p.name || venueName(p.venue)) + ": " + (p.text || ""), value: "", kind: "venue" };
      case "announcement": return { ...base, type: "anuncio", actor: "org", teams: [], text: p.text || "Anuncio", value: "", kind: "info" };
      default: {
        if (/^venue\./.test(e.type || "")) return { ...base, type: "anuncio", actor: p.venue || "", teams: [], text: (e.type || "") + " · " + venueName(p.venue), value: "", kind: "venue" };
        return { ...base, type: "anuncio", actor: e.actor || "org", teams: isTeam(p.team) ? [p.team] : [], text: (e.type || "evento") + (p.text ? " · " + p.text : ""), value: "", kind: "info" };
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
  const events = () => feed.rows.filter((r) => !r.skip);
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
    return el("span", { class: "t10-who" + (id === US ? " t10-us" : "") }, id === US ? "Team 10 · Nosotros" : (id === "org" ? "Organización" : teamName(id) || venueName(id)));
  }
  const state = (kind, text) => {
    if (window.ui) { if (kind === "loading" && ui.loading) return ui.loading(); if (kind === "error" && ui.error) return ui.error(text); if (kind === "empty" && ui.empty) return ui.empty(text); }
    return el("div", { class: "t10-state" }, kind === "loading" ? "Cargando…" : kind === "error" ? "Error: " + ((text && text.message) || text) : text);
  };
  const errText = (e) => (e && e.status === 404 ? "Este dato aún no está disponible en la API." : "No se pudo leer: " + ((e && e.message) || e));
  function replace(node, ...kids) { if (!node) return; node.replaceChildren(...kids.flat().filter((k) => k != null)); }

  async function prime() {
    const c = await rec("clock", 60000); if (c && !anchors.length) setClock(c);
    await rec("venues", 15000);
  }

  window.T10D = { prime, US, TYPES, TYPE_LABEL, TYPE_COLOR, num, esc, fmt, fmtP, hhmm, hhmmss, dayKey, el, html, teamName, isTeam, venueName,
    cached, rec, recErr, stream, setClock, tToWall, evTs, normalize, feed, board, events, dayEvents, involves, leaderboard, series, rankMove,
    svg, stackBars, spark, bucketize, chip, teamTag, state, errText, replace, names, anchors: () => anchors };
})();
/* ---- HOME ---- */
(function () {
  const D = window.T10D;
  const { el, fmt, fmtP, num, hhmm, hhmmss, TYPES, TYPE_LABEL, US } = D;
  const sched = D.stream("schedule", 60, 400, (r) => r);
  let S = null;

  const ACTION_LANE = { bench: "mt", duels: "duel" };
  function evLabel(u) {
    const p = u.params || {};
    if (u.action === "bench") return p.name && /hard/i.test(p.name) ? "M. Test duro" : "M. Test";
    if (u.action === "duels") return (p.name || "Duelos").replace(/^Duels/, "Duelos").replace(/^Final duels/, "Duelos finales");
    if (u.action === "round") return "Ronda: " + (p.name || "");
    if (u.action === "set_release") return "Llega " + (p.set || "set");
    if (u.action === "grant_all") return "Reparto para todos";
    if (u.action === "day_opens") return "Apertura";
    if (u.action === "day_closes") return "Cierre";
    if (u.action === "end_round") return "Se congelan puntos";
    return u.note || u.action;
  }
  function schedule() {
    const map = new Map();
    for (const r of sched.rows) for (const u of ((r.data || r).upcoming || [])) map.set(u.at_hours + "|" + u.action + "|" + (u.note || ""), u);
    const out = [...map.values()].map((u) => ({ ...u, wall: D.tToWall(u.at_hours) })).filter((u) => u.wall);
    out.sort((a, b) => a.wall - b.wall);
    return out;
  }
  const countdown = (s) => { s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60; return (h ? h + ":" : "") + String(m).padStart(h ? 2 : 1, "0") + ":" + String(x).padStart(2, "0"); };

  function mount(root) {
    S = { filter: { types: new Set(TYPES), team: "todos", q: "" }, lastSeq: -2, fb: null, sel: null };
    root.innerHTML = "";
    root.append(el("div", { class: "scr-home" },
      el("div", { class: "h-top" },
        el("section", { class: "t10-panel h-score" }, el("div", { class: "t10-cap" }, "Puntuación de hoy"), el("div", { class: "h-score-body" }, D.state("loading"))),
        el("section", { class: "t10-panel h-agenda" },
          el("div", { class: "h-next" }, el("div", { class: "t10-cap" }, "Siguiente evento"), el("div", { class: "h-next-body" }, D.state("loading"))),
          el("div", { class: "h-lanes" })),
        el("section", { class: "t10-panel h-market" }, el("div", { class: "t10-cap t10-split" }, el("span", {}, "Actividad del mercado"), el("span", { class: "h-market-win" }, "últ. 2 h")), el("div", { class: "h-market-body" }))),
      el("div", { class: "h-bottom" },
        el("section", { class: "t10-panel h-feed" },
          el("div", { class: "t10-head" }, el("h2", {}, "Todo lo que pasa"), el("span", { class: "t10-sub h-feed-sub" }, "nosotros y los rivales · en directo"), el("span", { class: "t10-sub t10-right h-feed-count" }, "")),
          el("div", { class: "h-filter" }),
          el("div", { class: "h-list" }, D.state("loading"))),
        el("section", { class: "t10-panel h-board" },
          el("div", { class: "t10-head" }, el("h2", {}, "Clasificación"), el("span", { class: "t10-sub t10-right h-board-sub" }, "")),
          el("div", { class: "h-board-list" }, D.state("loading"))))));
  }

  // ---------------------------------------------------------------- score
  function renderScore(root, data, teams) {
    const box = root.querySelector(".h-score-body"); const t = (data && data.team) || {};
    const me = teams.find((x) => x.team === US) || {};
    const score = num(t.score) != null ? num(t.score) : num(me.score);
    if (score == null && !teams.length) return D.replace(box, D.state("empty", "Sin puntuación todavía."));
    const rank = num(t.rank) || num(me.rank); const nTeams = num(t.teams) || teams.length;
    const delta = num(t.delta_1h);
    const neg = num(t.negotiating) != null ? num(t.negotiating) : num(me.negotiating);
    const mkt = num(t.market) != null ? num(t.market) : num(me.market);
    const leadNeg = Math.max(0, ...teams.map((x) => num(x.negotiating) || 0));
    const leadMkt = Math.max(0, ...teams.map((x) => num(x.market) || 0));
    const idx = teams.findIndex((x) => x.team === US);
    const ladder = idx < 0 ? teams.slice(0, 4) : teams.slice(Math.max(0, idx - 2), Math.max(0, idx - 2) + 4);
    const ser = D.series(US);
    const bar = (label, v, lead) => el("div", { class: "h-bar" }, el("span", { class: "h-bar-l" }, label),
      el("span", { class: "h-bar-track" }, el("span", { class: "h-bar-fill", style: `width:${Math.min(100, ((v || 0) / 30) * 100)}%` }),
        lead ? el("span", { class: "h-bar-lead", title: "líder: " + fmt(lead, 1), style: `left:${Math.min(100, (lead / 30) * 100)}%` }) : null),
      el("span", { class: "h-bar-v num" }, fmt(v, 1) + "/30"));
    D.replace(box,
      el("div", { class: "h-score-l" },
        el("div", { class: "h-big num" }, fmt(score, 1), el("span", { class: "h-of" }, " / 60")),
        el("div", { class: "h-delta num " + (delta > 0 ? "t10-up" : delta < 0 ? "t10-down" : "") }, delta == null ? "sin cambio medido en la última hora" : (delta > 0 ? "+" : "") + fmt(delta, 1) + " en la última hora"),
        el("div", { class: "h-spark" }, D.spark(ser.slice(-120), { w: 220, h: 34 })),
        bar("Negociación", neg, leadNeg), bar("Mercado", mkt, leadMkt)),
      el("div", { class: "h-ladder" }, ladder.map((x) => {
        const d = num(x.score) != null && score != null ? num(x.score) - score : null;
        return el("div", { class: "h-lad" + (x.team === US ? " t10-usrow" : "") },
          el("span", { class: "num t10-muted" }, (x.rank || "") + ".º"),
          el("span", {}, x.team === US ? "Team 10 · Nos." : D.teamName(x.team)),
          el("span", { class: "num" }, fmt(x.score, 1)),
          el("span", { class: "num " + (d > 0 ? "t10-down" : "t10-up") }, x.team === US || d == null ? "" : (d > 0 ? "+" : "") + fmt(d, 1)));
      }), rank ? el("div", { class: "t10-muted t10-small" }, rank + ".º de " + nTeams) : null));
  }

  // ---------------------------------------------------------------- agenda
  function renderAgenda(root, data) {
    const now = Date.now() / 1000; const all = schedule();
    const nextBox = root.querySelector(".h-next-body"), lanes = root.querySelector(".h-lanes");
    const up = all.filter((u) => u.wall > now && !["day_opens", "day_closes", "announce", "persona"].includes(u.action));
    const nx = up[0];
    const ov = data && data.clock && data.clock.next_event;
    if (!nx && !ov) D.replace(nextBox, D.state("empty", sched.err ? D.errText(sched.err) : "No hay eventos próximos en el calendario."));
    else {
      const head = nx ? { label: evLabel(nx), wall: nx.wall, note: nx.note } : { label: ov.action, wall: ov.at, note: "" };
      D.replace(nextBox,
        el("div", { class: "h-next-title" }, head.label),
        el("div", { class: "h-next-when num" }, hhmm(head.wall), " ", el("span", { class: "t10-accent" }, "en " + countdown(head.wall - now))),
        head.note ? el("div", { class: "t10-muted t10-small" }, head.note) : null,
        el("div", { class: "h-next-list" }, up.slice(1, 4).map((u) => el("div", { class: "h-next-row t10-lane-" + (ACTION_LANE[u.action] || "day") },
          el("span", { class: "num" }, hhmm(u.wall)), el("span", {}, evLabel(u)), el("span", { class: "num t10-accent" }, "en " + countdown(u.wall - now))))));
    }
    // timeline of the day (today, or the next day that opens)
    const anchors = D.anchors();
    const today = D.dayKey(now);
    const day = anchors.find((a) => D.dayKey(a.o) === today) || anchors.find((a) => a.o > now) || anchors[anchors.length - 1];
    if (!day) return D.replace(lanes, D.state("empty", "Sin calendario."));
    const W = 320, H = 120, L = 52, t0 = day.o, t1 = day.c, x = (t) => L + ((t - t0) / (t1 - t0)) * (W - L - 8);
    const lanesDef = [["mt", "M. Test", 22], ["duel", "Duelos", 52], ["day", "Día", 82]];
    let s = "";
    for (const [, name, y] of lanesDef) s += `<text x="0" y="${y + 4}" class="t10-svgtxt">${name}</text><line x1="${L}" x2="${W - 8}" y1="${y}" y2="${y}" stroke="var(--line,#2a2a2a)"/>`;
    for (let h = new Date(t0 * 1000); h.getTime() / 1000 <= t1; h = new Date(h.getTime() + 2 * 3600e3)) {
      const tx = x(h.getTime() / 1000); s += `<text x="${tx}" y="${H - 4}" class="t10-svgtxt" text-anchor="middle">${hhmm(h.getTime() / 1000).slice(0, 2)}</text>`;
    }
    for (const u of all) {
      if (u.wall < t0 - 1 || u.wall > t1 + 1) continue;
      const lane = ACTION_LANE[u.action] || "day"; const y = lanesDef.find((l) => l[0] === lane)[2];
      const p = u.params || {}; const tickS = num(p.tick_seconds) || 30;
      const dur = u.action === "bench" ? (num(p.ticks) || 16) * tickS : u.action === "duels" ? (num(p.duel_ticks) || 16) * tickS * (num(p.rounds) || 1) * 3 : 0;
      const cls = lane === "mt" ? "var(--t-cambio,#4c8dff)" : lane === "duel" ? "var(--t-duelo,#9b7bff)" : "var(--t-anuncio,#8a8f98)";
      if (dur) s += `<rect x="${x(u.wall)}" y="${y - 5}" width="${Math.max(6, x(u.wall + dur) - x(u.wall))}" height="10" fill="${cls}"><title>${D.esc(hhmm(u.wall) + " · " + evLabel(u))}</title></rect>`;
      else s += `<rect x="${x(u.wall) - 1}" y="${y - 7}" width="2" height="14" fill="${cls}"><title>${D.esc(hhmm(u.wall) + " · " + evLabel(u))}</title></rect>`;
      if (lane === "duel") s += `<text x="${x(u.wall)}" y="${y + 18}" class="t10-svgtxt" text-anchor="middle">${D.esc(evLabel(u) + " " + hhmm(u.wall))}</text>`;
    }
    if (now >= t0 && now <= t1) s += `<line x1="${x(now)}" x2="${x(now)}" y1="4" y2="${H - 14}" stroke="var(--t-venta,#e5534b)" stroke-width="1.5"/><text x="${x(now) + 3}" y="10" class="t10-svgtxt t10-now">ahora ${hhmm(now)}</text>`;
    D.replace(lanes, el("div", { class: "t10-cap" }, day.name ? "Agenda · " + day.name : "Agenda"), D.svg(W, H, s, "h-tl", true));
  }

  // ---------------------------------------------------------------- market activity
  function renderMarket(root, dayRows) {
    const box = root.querySelector(".h-market-body");
    const ops = dayRows.rows.filter((r) => r.type !== "anuncio");
    if (!ops.length) return D.replace(box, D.state("empty", D.feed.err ? D.errText(D.feed.err) : "Sin actividad registrada."));
    const end = dayRows.today ? Date.now() / 1000 : ops[ops.length - 1].ts, start = end - 7200;
    const win = ops.filter((r) => r.ts >= start && r.ts <= end);
    root.querySelector(".h-market-win").textContent = dayRows.today ? "últ. 2 h" : "últ. 2 h con datos · " + hhmm(end);
    D.replace(box, el("div", { class: "h-market-n num" }, D.fmt(win.length, 0) + " operaciones"),
      D.stackBars(D.bucketize(win, 24, start, end), { w: 240, h: 90 }));
  }

  // ---------------------------------------------------------------- feed list
  function passes(r, f) {
    if (f.types && !f.types.has(r.type)) return false;
    const tm = f.team || "todos";
    if (tm === "nosotros" && !D.involves(r, US)) return false;
    if (tm === "rivales" && (D.involves(r, US) || !(r.teams || []).some(D.isTeam))) return false;
    if (/^t\d+$/.test(tm) && !D.involves(r, tm)) return false;
    if (f.q) { const q = f.q.toLowerCase(); if (!(r.text + " " + D.teamName(r.actor) + " " + (r.value || "")).toLowerCase().includes(q)) return false; }
    return true;
  }
  function actorCell(r) {
    if (r.type === "cambio" && (r.teams || []).length === 2) return el("span", { class: "t10-who" }, D.teamName(r.teams[0]) + " ↔ " + D.teamName(r.teams[1]));
    if (!r.actor || r.actor === "org" || (!D.isTeam(r.actor) && r.kind !== "thread" && r.kind !== "settle" && r.kind !== "offer")) return el("span", { class: "t10-who" }, r.kind === "venue" ? D.venueName(r.actor) || "Tienda" : "Organización");
    return D.teamTag(r.actor);
  }
  function openDetail(r) {
    const raw = r.raw || {}; const p = raw.payload || {};
    const kv = (k, v) => (v == null || v === "" ? null : el("div", { class: "t10-kv" }, el("span", { class: "t10-muted" }, k), el("span", {}, v)));
    const body = el("div", { class: "scr-home h-detail" },
      el("div", { class: "h-detail-head" }, D.chip(r.type), " ", actorCell(r)),
      el("p", {}, r.text),
      kv("Hora", hhmmss(r.ts)), kv("Tick", raw.tick != null ? String(raw.tick) : null), kv("Tipo de evento", raw.type),
      kv("Valor", r.value), kv("Tienda", p.venue ? D.venueName(p.venue) : null), kv("Comisión", p.fee != null ? fmtP(p.fee) : null),
      kv("Equipos", (r.teams || []).filter(Boolean).map((t) => t === US ? "Team 10 · Nosotros" : D.teamName(t)).join(", ")),
      (r.items || r.assets) ? el("div", { class: "h-items" }, (r.items || r.assets).map((i) => el("div", { class: "t10-kv" }, el("span", {}, (i.ref || i.name || "#" + i.id) + (i.rarity ? " · " + i.rarity : "")), el("span", { class: "t10-muted" }, i.frm ? D.teamName(i.frm) + " → " + D.teamName(i.to) : (i.serial ? "n.º " + i.serial : ""))))) : null,
      el("div", { class: "t10-cap" }, "Evento completo"),
      el("pre", { class: "t10-pre" }, JSON.stringify(raw, null, 2)));
    if (window.ui && ui.drawer) ui.drawer({ title: TYPE_LABEL[r.type] + " · " + hhmm(r.ts), body });
  }
  function renderFeed(root, dayRows, force) {
    const list = root.querySelector(".h-list");
    if (!force && S.lastSeq === D.feed.maxSeq) return;
    S.lastSeq = D.feed.maxSeq;
    const rows = dayRows.rows;
    if (!S.fb && window.ui && ui.filterBar) {
      const counts = {}; for (const r of rows) counts[r.type] = (counts[r.type] || 0) + 1;
      try {
        S.fb = ui.filterBar({ types: TYPES, counts, team: true, teamCount: 18, search: true, onChange: (st) => { S.filter = st || S.filter; renderFeed(root, D.dayEvents(), true); } });
        D.replace(root.querySelector(".h-filter"), S.fb);
      } catch (e) { S.fb = true; }
    }
    if (!rows.length) return D.replace(list, D.state(D.feed.err ? "error" : "empty", D.feed.err ? D.errText(D.feed.err) : "Todavía no hay eventos grabados."));
    const f = S.filter; const shown = rows.filter((r) => passes(r, f));
    const typesOn = f.types ? f.types.size : TYPES.length;
    if (S.fb && S.fb.setCounts) { const c = {}; for (const r of rows) c[r.type] = (c[r.type] || 0) + 1; S.fb.setCounts(c); }
    root.querySelector(".h-feed-count").textContent = typesOn + " de 7 tipos · " + D.fmt(shown.length, 0) + " eventos" + (dayRows.today ? "" : " · " + dayRows.day);
    root.querySelector(".h-feed-sub").textContent = "nosotros y los " + Math.max(0, (D.names && Object.keys(D.names).length - 1) || 17) + " rivales · " + (dayRows.today ? "en directo" : "último día con datos");
    if (!shown.length) return D.replace(list, D.state("empty", "Ningún evento con estos filtros."));
    const sc = list.scrollTop;
    D.replace(list, shown.slice(-200).reverse().map((r) => {
      const cells = [el("span", { class: "num t10-muted" }, hhmmss(r.ts)), D.chip(r.type), actorCell(r), el("span", { class: "h-text" }, r.text), el("span", { class: "num t10-right" }, r.value || "")];
      return window.ui && ui.row ? ui.row({ type: r.type, cells, cols: "74px 104px 168px minmax(0,1fr) 84px", us: D.involves(r, US), onClick: () => openDetail(r) })
        : el("div", { class: "t10-row t10-" + r.type, onclick: () => openDetail(r) }, cells);
    }));
    list.scrollTop = sc;
  }

  // ---------------------------------------------------------------- leaderboard
  function renderBoard(root, teams) {
    const box = root.querySelector(".h-board-list");
    root.querySelector(".h-board-sub").textContent = teams.length ? teams.length + " equipos" : "";
    if (!teams.length) { const e = D.recErr("leaderboard"); return D.replace(box, D.state(e ? "error" : "empty", e ? D.errText(e) : "Clasificación vacía.")); }
    D.replace(box, teams.map((t) => {
      const mv = D.rankMove(t.team);
      return el("a", { class: "h-lb" + (t.team === US ? " t10-usrow" : ""), href: "#rivales/" + t.team },
        el("span", { class: "num t10-muted" }, String(t.rank || "")),
        el("span", { class: "num " + (mv > 0 ? "t10-up" : mv < 0 ? "t10-down" : "t10-muted") }, mv > 0 ? "▲" + mv : mv < 0 ? "▼" + -mv : "·"),
        el("span", { class: "h-lb-name" }, t.team === US ? "Team 10 · Nosotros" : D.teamName(t.team)),
        D.spark(D.series(t.team).slice(-80), { w: 60, h: 18, color: t.team === US ? "var(--ink,#eee)" : null }),
        el("span", { class: "num" }, fmt(t.score, 1)));
    }));
  }

  async function refresh(root, data) {
    if (!S) mount(root);
    await D.prime();
    await Promise.all([D.feed.pull(), D.board.pull(), sched.pull()]);
    const teams = await D.leaderboard();
    const day = D.dayEvents();
    const safe = (f) => { try { f(); } catch (e) { console.error("home", e); } };
    safe(() => renderScore(root, data, teams));
    safe(() => renderAgenda(root, data));
    safe(() => renderMarket(root, day));
    safe(() => renderFeed(root, day));
    safe(() => renderBoard(root, teams));
  }

  window.Screens = window.Screens || {};
  window.Screens["home"] = {
    title: "Home",
    mount(root) { mount(root); },
    async refresh(root, data) { return refresh(root, data); },
    unmount() { S = null; },
  };
})();
