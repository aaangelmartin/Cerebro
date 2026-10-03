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
/* ---- COMPETICIÓN ---- */
(function () {
  const D = window.T10D;
  const { el, fmt, fmtP, num, hhmm, TYPES, US } = D;
  const RAR = [["legendary", "Legendaria", "var(--ink,#f2f2f2)"], ["epic", "Épica", "#c9c9c9"], ["rare", "Rara", "#9a9a9a"], ["uncommon", "Poco común", "#737373"], ["common", "Común", "#555"]];
  const REF_COLORS = ["var(--ink,#f2f2f2)", "var(--t-cambio,#4c8dff)", "var(--t-puja,#e8a33d)", "var(--t-dealer,#2bb3a3)"];
  let S = null;

  function mount(root) {
    S = { mode: "rareza", drawerFor: null };
    root.innerHTML = "";
    root.append(el("div", { class: "scr-competicion" },
      el("div", { class: "c-top" },
        el("section", { class: "t10-panel c-chart" },
          el("div", { class: "t10-head" }, el("h2", {}, "Competición · precios y volumen"),
            el("span", { class: "t10-right c-toggle" },
              el("button", { class: "t10-seg on", "data-m": "rareza" }, "Por rareza"), el("button", { class: "t10-seg", "data-m": "carta" }, "Por carta")),
            el("span", { class: "t10-sub c-win" }, "")),
          el("div", { class: "c-legend" }), el("div", { class: "c-lines" }, D.state("loading")),
          el("div", { class: "t10-cap c-volcap" }, "Volumen por tipo"), el("div", { class: "c-vol" })),
        el("section", { class: "t10-panel c-venues" },
          el("div", { class: "t10-head" }, el("h2", {}, "Sedes"), el("span", { class: "t10-sub t10-right" }, "cuota de volumen")),
          el("div", { class: "c-venue-list" }, D.state("loading")))),
      el("div", { class: "c-bottom" },
        el("section", { class: "t10-panel c-book c-book-a" }, D.state("loading")),
        el("section", { class: "t10-panel c-book c-book-b" }, D.state("loading")),
        el("section", { class: "t10-panel c-mt" },
          el("div", { class: "t10-head" }, el("h2", {}, "Market Test · nuestra sede"), el("span", { class: "t10-sub t10-right" }, "eficiencia vs puesto gratis")),
          el("div", { class: "c-mt-body" }, D.state("loading"))))));
    root.querySelectorAll(".c-toggle button").forEach((b) => b.addEventListener("click", () => {
      S.mode = b.dataset.m; root.querySelectorAll(".c-toggle button").forEach((x) => x.classList.toggle("on", x === b)); S.lastSeq = null; refresh(root, S.data, S.params);
    }));
  }

  const settles = (rows) => rows.filter((r) => r.kind === "settle");
  const unitPrice = (r) => { const n = (r.items || []).filter((i) => i.kind === "card").length; return r.price != null && n ? r.price / n : null; };

  // ---------------------------------------------------------------- price lines
  function renderChart(root, day) {
    const rows = day.rows; const box = root.querySelector(".c-lines");
    const st = settles(rows).filter((r) => unitPrice(r) != null && r.type !== "dealer" || (r.type === "dealer" && unitPrice(r) != null));
    if (!rows.length) { D.replace(root.querySelector(".c-legend")); D.replace(root.querySelector(".c-vol")); return D.replace(box, D.state(D.feed.err ? "error" : "empty", D.feed.err ? D.errText(D.feed.err) : "Sin operaciones grabadas todavía.")); }
    const t0 = rows[0].ts, t1 = day.today ? Date.now() / 1000 : rows[rows.length - 1].ts;
    root.querySelector(".c-win").textContent = (day.today ? "Hoy · " : day.day + " · ") + hhmm(t0) + "–" + hhmm(t1);
    let groups;
    if (S.mode === "carta") {
      const cnt = {}; for (const r of st) for (const i of r.items || []) if (i.kind === "card") cnt[i.ref] = (cnt[i.ref] || 0) + 1;
      groups = Object.entries(cnt).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([ref], k) => [ref, ref, REF_COLORS[k], (r) => (r.items || []).some((i) => i.ref === ref)]);
    } else groups = RAR.map(([id, label, col]) => [id, label, col, (r) => (r.items || []).some((i) => i.rarity === id)]);
    const N = 16, span = Math.max(60, t1 - t0);
    const series = groups.map(([id, label, col, fn]) => {
      const b = Array.from({ length: N }, () => []);
      for (const r of st) if (fn(r)) b[Math.min(N - 1, Math.floor(((r.ts - t0) / span) * N))].push(unitPrice(r));
      const vals = b.map((a) => (a.length ? a.sort((x, y) => x - y)[Math.floor(a.length / 2)] : null));
      const last = [...vals].reverse().find((v) => v != null);
      return { id, label, col, vals, last };
    }).filter((s) => s.last != null);
    D.replace(root.querySelector(".c-legend"), series.map((s) => el("span", { class: "c-leg" }, el("i", { style: "background:" + s.col }), s.label + " ", el("b", { class: "num" }, fmtP(Math.round(s.last))))));
    if (!series.length) D.replace(box, D.state("empty", "Sin ventas con precio en este periodo."));
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
  const feeText = (v) => fmt((num(v.fee_bps) || 0) / 100, (num(v.fee_bps) || 0) % 100 ? 1 : 0) + " %" + (num(v.fee_per_card) ? " + " + v.fee_per_card + " P/carta" : "");
  function renderVenues(root, rows, books, ourVenue) {
    const box = root.querySelector(".c-venue-list");
    if (!rows.length) { const e = D.recErr("venues"); return D.replace(box, D.state(e ? "error" : "empty", e ? D.errText(e) : "No hay sedes abiertas.")); }
    D.replace(box, rows.map((v) => {
      const bs = bookStats(books[v.venue]); const ours = v.venue === ourVenue || v.owner === US;
      return el("a", { class: "c-venue" + (ours ? " t10-usrow" : ""), href: "#competicion/" + v.venue },
        el("div", { class: "t10-split" }, el("b", {}, v.name || v.venue), el("span", { class: "t10-small " + (ours ? "" : "t10-muted") }, ours ? "Team 10 · Nosotros" : (v.house ? "La casa" : v.owner_name || D.teamName(v.owner)))),
        el("div", { class: "c-meter" }, el("span", { class: "t10-cap" }, "Cuota de volumen"), el("span", { class: "c-meter-track" }, el("span", { style: `width:${(v.share * 100).toFixed(1)}%` })), el("span", { class: "num" }, fmt(v.share * 100, 0) + " %")),
        el("div", { class: "c-stats" },
          el("div", {}, el("span", { class: "t10-cap" }, "Comisión"), el("span", { class: "num" }, feeText(v))),
          el("div", {}, el("span", { class: "t10-cap" }, "Operaciones hoy"), el("span", { class: "num" }, String(v.opsToday || num(v.trades) || 0))),
          el("div", {}, el("span", { class: "t10-cap" }, "Diferencial medio"), el("span", { class: "num" }, bs.spread == null ? "—" : fmtP(Math.round(bs.spread * 10) / 10)))),
        v.status && v.status !== "open" ? el("div", { class: "t10-small t10-down" }, "Estado: " + v.status) : null);
    }));
  }
  function bookPanel(v, book, ourVenue) {
    const panel = [el("div", { class: "t10-head" }, el("h2", {}, v ? v.name || v.venue : "Libro"), el("span", { class: "t10-sub t10-right" }, v ? "libro · " + feeText(v) : ""))];
    if (!v) return panel.concat(D.state("empty", "Sin sede."));
    if (!book) { const e = D.recErr("books") || D.recErr("books/" + v.venue); return panel.concat(D.state(e ? "error" : "empty", e ? D.errText(e) : "Libro vacío.")); }
    const bs = bookStats(book);
    const line = (x, bid) => el("div", { class: "c-bk" + (bid ? " c-bid" : "") },
      el("span", { class: "c-ref" }, x.ref), el("span", { class: "num " + (bid ? "c-bidp" : "c-askp") }, (bid ? "≤ " : "") + fmtP(x.price)),
      el("span", { class: x.maker === US ? "t10-us" : "t10-muted" }, x.maker === US ? "Nosotros" : D.teamName(x.maker)));
    panel.push(el("div", { class: "c-bk c-bkh t10-cap" }, el("span", {}, "Carta"), el("span", {}, "Precio"), el("span", {}, "Equipo")));
    if (!bs.asks.length && !bs.bids.length) return panel.concat(D.state("empty", "Sin ofertas abiertas."));
    panel.push(...bs.asks.slice(0, 6).map((x) => line(x, false)));
    panel.push(el("div", { class: "c-spread t10-cap" }, "Diferencial medio ", el("b", { class: "num" }, bs.spread == null ? "—" : fmtP(Math.round(bs.spread * 10) / 10)), " · " + bs.asks.length + " ventas · " + bs.bids.length + " pujas"));
    panel.push(...bs.bids.slice(0, 6).map((x) => line(x, true)));
    return panel;
  }

  // ---------------------------------------------------------------- market test
  function renderMT(root, broker, ourRow) {
    const box = root.querySelector(".c-mt-body");
    if (!broker) return D.replace(box, D.state("empty", "Sin datos del broker."));
    const hist = ((broker.vs_stall || {}).history || []).slice();
    const lr = broker.last_result;
    if (lr && lr.vs_stall && lr.vs_stall.ours != null && !hist.some((h) => h.run === lr.session)) hist.push({ run: lr.session, ours: lr.vs_stall.ours, stall: lr.vs_stall.stall, basis: lr.vs_stall.basis });
    let chart;
    if (!hist.length) chart = D.state("empty", "Aún no hay sesiones de Market Test con resultado.");
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
      el("div", { class: "c-leg-row t10-small" }, el("span", { class: "c-leg" }, el("i", { style: "background:var(--t-compra,#3fbf7f)" }), "nuestra eficiencia"), el("span", { class: "c-leg" }, el("i", { style: "background:var(--t-puja,#e8a33d)" }), "puesto gratis"),
        el("span", { class: "t10-muted" }, " · modo " + (broker.mode || "—") + (broker.session ? " · sesión " + broker.session : ""))),
      el("div", { class: "t10-cap" }, "Actividad de nuestra sede · hoy"),
      el("div", { class: "c-stats c-stats4" },
        el("div", {}, el("span", { class: "t10-cap" }, "Operaciones"), el("span", { class: "num c-bignum" }, String(ourRow ? ourRow.opsToday || num(ourRow.trades) || 0 : "—"))),
        el("div", {}, el("span", { class: "t10-cap" }, "Volumen"), el("span", { class: "num c-bignum" }, ourRow ? fmtP(ourRow.volToday || num(ourRow.volume) || 0) : "—")),
        el("div", {}, el("span", { class: "t10-cap" }, "Cruces del broker"), el("span", { class: "num c-bignum" }, String(num(broker.matches_total) ?? num(ss.matches) ?? 0))),
        el("div", {}, el("span", { class: "t10-cap" }, "Comisión"), el("span", { class: "num c-bignum" }, ourRow ? feeText(ourRow) : "—"))),
      ourRow ? null : el("div", { class: "t10-muted t10-small" }, "No tenemos tienda propia abierta."));
  }

  // ---------------------------------------------------------------- venue drawer
  function openVenue(v, book, day) {
    if (!v || !(window.ui && ui.drawer)) return;
    const bs = bookStats(book);
    const st = settles(day.rows).filter((r) => (r.venue || "rastro") === v.venue && r.type !== "dealer").slice(-30).reverse();
    const kv = (k, val) => el("div", { class: "t10-kv" }, el("span", { class: "t10-muted" }, k), el("span", { class: "num" }, val == null ? "—" : String(val)));
    const body = el("div", { class: "scr-competicion c-drawer" },
      v.description ? el("p", { class: "t10-muted" }, v.description) : null,
      kv("Dueño", v.house ? "La casa" : v.owner === US ? "Team 10 · Nosotros" : v.owner_name || D.teamName(v.owner)),
      kv("Estado", v.status), kv("Comisión", feeText(v)),
      v.pending_fee ? kv("Comisión anunciada", fmt((v.pending_fee.fee_bps || 0) / 100, 1) + " % desde tick " + v.pending_fee.effective_tick) : null,
      kv("Mecanismo", (v.rules || {}).mechanism), kv("Abierta en tick", v.opened_tick),
      kv("Operaciones (total)", v.trades), kv("Volumen (total)", v.volume != null ? fmtP(v.volume) : null), kv("Comisiones cobradas", v.fees != null ? fmtP(v.fees) : null),
      kv("Equipos que operan", v.traders), kv("Operaciones hoy (feed)", v.opsToday), kv("Cuota de volumen hoy", fmt(v.share * 100, 1) + " %"),
      kv("Diferencial medio", bs.spread == null ? "—" : fmtP(Math.round(bs.spread * 10) / 10)),
      el("div", { class: "t10-cap" }, "Libro (" + bs.asks.length + " ventas · " + bs.bids.length + " pujas)"),
      ...bookPanel(v, book).slice(1),
      el("div", { class: "t10-cap" }, "Últimas operaciones"),
      st.length ? st.map((r) => el("div", { class: "t10-kv" }, el("span", {}, hhmm(r.ts) + " · " + r.text), el("span", { class: "num" }, r.value))) : D.state("empty", "Sin operaciones en el feed."));
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
    const want = params ? String(params).split("/")[0] : null;
    if (want && S.drawerFor !== want) { S.drawerFor = want; safe(() => openVenue(rows.find((v) => v.venue === want), books[want], day)); }
    if (!want) S.drawerFor = null;
  }

  window.Screens = window.Screens || {};
  window.Screens["competicion"] = {
    title: "Competición",
    mount(root, params) { mount(root); S.params = params; },
    onParams(root, params) { if (S) S.params = params; },
    async refresh(root, data, params) { return refresh(root, data, params); },
    unmount() { S = null; },
  };
})();
