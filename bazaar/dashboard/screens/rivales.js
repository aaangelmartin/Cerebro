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
    const c = await rec("clock", 5000); if (c) setClock(c);
    await rec("venues", 15000);
  }

  window.T10D = { prime, US, TYPES, TYPE_LABEL, TYPE_COLOR, num, esc, fmt, fmtP, hhmm, hhmmss, dayKey, el, html, teamName, isTeam, venueName,
    cached, rec, recErr, stream, setClock, tToWall, evTs, normalize, feed, board, events, dayEvents, involves, leaderboard, series, rankMove,
    svg, stackBars, spark, bucketize, chip, teamTag, state, errText, replace, names, anchors: () => anchors, calDays: () => calDays };
})();
/* ---- RIVALES ---- */
(function () {
  const D = window.T10D;
  const { el, fmt, fmtP, num, hhmm, hhmmss, TYPES, TYPE_LABEL, TYPE_COLOR, US } = D;
  const SET_COLORS = ["var(--t-dealer,#2bb3a3)", "#e0457b", "var(--t-venta,#e5534b)", "var(--t-puja,#e8a33d)", "#7b83eb", "#9acd32", "#c77dff"];
  let S = null;

  function mount(root) {
    S = { sel: null, types: new Set(), lastKey: null };
    root.innerHTML = "";
    root.append(el("div", { class: "scr-rivales" },
      el("section", { class: "t10-panel r-list" }, el("div", { class: "t10-head" }, el("h2", {}, "Rivales"), el("span", { class: "t10-sub t10-right r-count" }, "")), el("div", { class: "r-list-body" }, D.state("loading"))),
      el("div", { class: "r-main" },
        el("section", { class: "t10-panel r-head" }, D.state("loading")),
        el("div", { class: "r-mid" },
          el("section", { class: "t10-panel r-aff" }, el("div", { class: "t10-head" }, el("h2", {}, "Afinidades inferidas"), el("span", { class: "t10-sub t10-right r-aff-sub" }, "de sus pujas y compras")), el("div", { class: "r-aff-body" })),
          el("section", { class: "t10-panel r-types" }, el("div", { class: "t10-head" }, el("h2", {}, "Actividad por tipo · hoy")), el("div", { class: "r-types-body" }))),
        el("div", { class: "r-mid" },
          el("section", { class: "t10-panel r-offers" }, el("div", { class: "t10-head" }, el("h2", {}, "Sus ofertas en los libros")), el("div", { class: "r-offers-body" })),
          el("section", { class: "t10-panel r-cards" }, el("div", { class: "t10-head" }, el("h2", {}, "Cartas que ha movido")), el("div", { class: "r-cards-body" }))),
        el("section", { class: "t10-panel r-acts" },
          el("div", { class: "t10-head" }, el("h2", { class: "r-acts-title" }, "Lo que hace"), el("span", { class: "t10-right r-acts-filter" }, TYPES.map((t) => {
            const b = el("button", { class: "t10-chipbtn", "data-t": t }, D.chip(t));
            b.addEventListener("click", () => { S.types.has(t) ? S.types.delete(t) : S.types.add(t); b.classList.toggle("on", S.types.has(t)); S.lastKey = null; refresh(root, S.data, S.params); });
            return b;
          }))),
          el("div", { class: "r-acts-body" })))));
  }

  // per-team profile from the feed
  function profile(tid, rows) {
    const mine = rows.filter((r) => D.involves(r, tid));
    const counts = {}; for (const r of mine) counts[r.type] = (counts[r.type] || 0) + 1;
    const sets = {}; let signals = 0, dealerN = 0, bidN = 0; const bidSets = {}; const bidPrices = {};
    const add = (set, w) => { if (!set) return; sets[set] = (sets[set] || 0) + w; signals += w; };
    for (const r of mine) {
      if (r.type === "dealer") dealerN++;
      if (r.type === "puja" && r.actor === tid) { bidN++; for (const a of r.assets || []) { add(a.set || (a.ref || "").split("-")[0], 1); bidSets[a.set] = (bidSets[a.set] || 0) + 1; if (r.price != null) (bidPrices[a.set] = bidPrices[a.set] || []).push(r.price); } }
      if (r.kind === "settle") for (const i of r.items || []) if (i.kind === "card" && i.to === tid) add(i.set || (i.ref || "").split("-")[0], 1);
    }
    const max = Math.max(1, ...Object.values(sets));
    const aff = Object.entries(sets).map(([k, v]) => ({ set: k, v: v / max })).sort((a, b) => b.v - a.v);
    const last = mine.length ? mine[mine.length - 1].ts : null;
    return { mine, counts, aff, signals, dealerN, bidN, bidSets, bidPrices, last, total: mine.length };
  }
  function tags(t, p, avg) {
    const out = [];
    if (p.aff[0] && p.signals >= 2) out.push("valora " + p.aff.slice(0, p.aff[1] && p.aff[1].v > 0.7 ? 2 : 1).map((a) => a.set).join(" · "));
    if (p.dealerN >= 6 && p.dealerN >= 1.8 * (S.avgDealer || 0)) out.push("muy activo con dealers");
    if (t.venue) out.push("mercado propio " + t.venue);
    if (p.bidN >= 8) out.push("puja mucho · " + p.bidN + " pujas");
    if (p.total && p.total < avg * 0.3) out.push("pocas operaciones");
    if (!p.total) out.push("sin actividad grabada");
    else if (S.today && p.last && Date.now() / 1000 - p.last > 3600) out.push("sin actividad 1 h");
    return out;
  }

  function renderList(root, teams, profs, avg) {
    const box = root.querySelector(".r-list-body");
    root.querySelector(".r-count").textContent = teams.length ? String(teams.length - 1) : "";
    if (!teams.length) { const e = D.recErr("leaderboard"); return D.replace(box, D.state(e ? "error" : "empty", e ? D.errText(e) : "Sin clasificación todavía.")); }
    D.replace(box, teams.map((t) => {
      const p = profs[t.team]; const tg = t.team === US ? ["tú"] : tags(t, p, avg).slice(0, 2);
      return el("a", { class: "r-item" + (t.team === S.sel ? " on" : "") + (t.team === US ? " t10-usrow" : ""), href: "#rivales/" + t.team },
        el("span", { class: "num t10-muted" }, (t.rank || "") + ".º"),
        el("span", { class: "r-item-name" }, el("b", {}, t.team === US ? "Team 10 · Nosotros" : D.teamName(t.team)), el("span", { class: "t10-small t10-muted" }, tg.join(" · "))),
        el("span", { class: "r-item-acts t10-small t10-muted num", title: "eventos hoy" }, p.total ? String(p.total) : ""),
        el("span", { class: "num" }, fmt(t.score, 1)));
    }));
  }

  function renderProfile(root, t, teams, p, profs, avg, booksAll) {
    const me = teams.find((x) => x.team === US) || {};
    const diff = num(t.score) != null && num(me.score) != null ? num(t.score) - num(me.score) : null;
    const tg = t.team === US ? [] : tags(t, p, avg);
    const vsUs = p.mine.filter((r) => r.type === "duelo" && D.involves(r, US)).length;
    D.replace(root.querySelector(".r-head"),
      el("div", { class: "r-head-l" }, el("h1", {}, t.team === US ? "Team 10 · Nosotros" : D.teamName(t.team)),
        el("div", { class: "r-tags" }, tg.map((x) => el("span", { class: "r-tag" }, x)))),
      el("div", { class: "r-kpis" },
        kpi("Puesto", (t.rank || "—") + ".º"), kpi("Puntos", fmt(t.score, 1)),
        t.team === US ? null : kpi("vs Nosotros", diff == null ? "—" : (diff > 0 ? "+" : "") + fmt(diff, 1), diff > 0 ? "t10-down" : "t10-up"),
        kpi("Tratos", t.deals != null ? String(t.deals) : "—"), kpi("Nivel", t.level != null ? String(t.level) : "—"),
        kpi("Álbum", t.album_filled != null ? t.album_filled + "/" + t.album_slots : "—"),
        kpi("Tienda", t.venue || "—"), vsUs ? kpi("Duelos con nos.", String(vsUs)) : null),
      el("div", { class: "r-series" }, el("span", { class: "t10-cap" }, "Puntos en el tiempo"), D.spark(D.series(t.team), { w: 300, h: 34 })));
    // affinities with our marker
    const ours = profs[US] ? Object.fromEntries(profs[US].aff.map((a) => [a.set, a.v])) : {};
    root.querySelector(".r-aff-sub").textContent = "de sus pujas y compras · " + p.signals + " señales";
    D.replace(root.querySelector(".r-aff-body"), p.aff.length ? [
      ...p.aff.slice(0, 7).map((a, i) => el("div", { class: "r-aff-row" },
        el("span", { class: "r-aff-set", style: "border-left-color:" + SET_COLORS[i % SET_COLORS.length] }, a.set),
        el("span", { class: "r-aff-track" }, el("span", { style: `width:${a.v * 100}%;background:${SET_COLORS[i % SET_COLORS.length]}` }),
          ours[a.set] != null && t.team !== US ? el("i", { class: "r-aff-us", style: `left:${ours[a.set] * 100}%`, title: "la nuestra" }) : null),
        el("span", { class: "num" }, fmt(a.v * 100, 0) + " %"),
        ours[a.set] > 0.5 && a.v > 0.5 && t.team !== US ? el("span", { class: "t10-small t10-warn" }, "compite con nosotros") : el("span", {}))),
      el("div", { class: "t10-small t10-muted" }, "barra: su afinidad · marca blanca: la nuestra")]
      : D.state("empty", "Sin pujas ni compras grabadas."));
    // activity by type
    const tot = TYPES.reduce((s, x) => s + (p.counts[x] || 0), 0);
    D.replace(root.querySelector(".r-types-body"), tot ? [
      el("div", { class: "r-stack" }, TYPES.filter((x) => p.counts[x]).map((x) => el("span", { style: `flex:${p.counts[x]};background:${TYPE_COLOR[x]}`, title: TYPE_LABEL[x] + ": " + p.counts[x] }))),
      ...TYPES.map((x) => el("div", { class: "t10-kv" }, el("span", {}, el("i", { class: "r-sq", style: "background:" + TYPE_COLOR[x] }), TYPE_LABEL[x]), el("span", { class: "num" }, String(p.counts[x] || 0))))]
      : D.state("empty", "Sin actividad grabada hoy."));
    // offers in books
    const offers = [];
    for (const [venue, book] of Object.entries(booksAll)) for (const o of (book && book.offers) || []) if (o.maker === t.team) offers.push({ venue, o });
    D.replace(root.querySelector(".r-offers-body"), offers.length ? offers.slice(0, 30).map(({ venue, o }) => {
      const g = o.give || {}, w = o.want || {}; const sell = (g.assets || []).length && !(w.assets || []).length;
      const typ = sell ? "venta" : (g.assets || []).length ? "cambio" : "puja";
      const ref = sell ? (g.assets || []).map((a) => a.ref).join(", ") : ((w.assets || []).map((a) => a.ref).join(", ") || (g.assets || []).map((a) => a.ref).join(", "));
      const price = sell ? fmtP(w.cash) : typ === "puja" ? "≤ " + fmtP(g.cash) : "";
      return el("div", { class: "r-off t10-bar-" + typ }, D.chip(typ), el("span", {}, ref), el("span", { class: "t10-muted t10-small" }, D.venueName(venue)), el("span", { class: "num t10-right" }, price));
    }) : D.state("empty", "No tiene ofertas abiertas en los libros grabados."));
    // cards moved
    const moved = [];
    for (const r of p.mine) if (r.kind === "settle") for (const i of r.items || []) if (i.kind === "card" && (i.to === t.team || i.frm === t.team)) moved.push({ r, i, inn: i.to === t.team });
    D.replace(root.querySelector(".r-cards-body"), moved.length ? moved.slice(-30).reverse().map(({ r, i, inn }) => el("div", { class: "r-off" },
      el("span", { class: "num t10-muted" }, hhmm(r.ts)), el("span", {}, (inn ? "← " : "→ ") + (i.ref || i.name) + (i.rarity ? " · " + i.rarity : "")),
      el("span", { class: "t10-small t10-muted" }, inn ? "de " + D.teamName(i.frm) : "a " + D.teamName(i.to)), el("span", { class: "num t10-right" }, r.value || "")))
      : D.state("empty", "No ha movido cartas en el feed grabado."));
    // actions
    root.querySelector(".r-acts-title").textContent = "Lo que hace " + (t.team === US ? "Team 10 · Nosotros" : D.teamName(t.team));
    const acts = p.mine.filter((r) => !S.types.size || S.types.has(r.type)).slice(-120).reverse();
    D.replace(root.querySelector(".r-acts-body"), acts.length ? acts.map((r) => {
      const cells = [el("span", { class: "num t10-muted" }, hhmmss(r.ts)), D.chip(r.type), el("span", {}, r.text), el("span", { class: "num t10-right" }, r.value || "")];
      return window.ui && ui.row ? ui.row({ type: r.type, cells, cols: "74px 104px minmax(0,1fr) 84px", onClick: () => openEvent(r) }) : el("div", { class: "t10-row" }, cells);
    }) : D.state("empty", "Sin acciones con estos filtros."));
  }
  const kpi = (label, value, cls) => el("div", { class: "r-kpi" }, el("span", { class: "t10-cap" }, label), el("span", { class: "num r-kpi-v " + (cls || "") }, value));
  function openEvent(r) {
    if (window.ui && ui.drawer) ui.drawer({ title: TYPE_LABEL[r.type] + " · " + hhmm(r.ts), body: el("div", { class: "scr-rivales" }, el("p", {}, r.text), el("pre", { class: "t10-pre" }, JSON.stringify(r.raw, null, 2))) });
  }

  async function refresh(root, data, params) {
    if (!S) mount(root);
    S.data = data; S.params = params;
    await D.prime();
    await Promise.all([D.feed.pull(), D.board.pull()]);
    const teams = await D.leaderboard();
    const ven = await D.rec("venues", 8000);
    const booksAll = (await D.rec("books", 8000)) || {};
    const want = params ? String(params).split("/")[0] : null;
    const sel = (want && teams.find((t) => t.team === want)) ? want : (teams.find((t) => t.team !== US) || {}).team;
    const key = [D.feed.maxSeq, D.board.maxSeq, sel, teams.length, Object.values(booksAll).map((b) => b && b.tick).join(",")].join("|");
    if (key === S.lastKey) return;
    S.lastKey = key; S.sel = sel;
    const day = D.dayEvents();
    const profs = {}; for (const t of teams) profs[t.team] = profile(t.team, day.rows);
    const avg = teams.length ? teams.reduce((s, t) => s + profs[t.team].total, 0) / teams.length : 0;
    S.avgDealer = teams.length ? teams.reduce((s, t) => s + profs[t.team].dealerN, 0) / teams.length : 0; S.today = day.today;
    const safe = (f) => { try { f(); } catch (e) { console.error("rivales", e); } };
    safe(() => renderList(root, teams, profs, avg));
    const t = teams.find((x) => x.team === sel);
    if (!t) { D.replace(root.querySelector(".r-head"), D.state("empty", "Elige un equipo de la lista.")); return; }
    safe(() => renderProfile(root, t, teams, profs[sel], profs, avg, booksAll));
  }

  window.Screens = window.Screens || {};
  window.Screens["rivales"] = {
    title: "Rivales",
    mount(root, params) { mount(root); S.params = params; },
    onParams(root, params) { if (S) S.params = params; },
    async refresh(root, data, params) { return refresh(root, data, params); },
    unmount() { S = null; },
  };
})();
