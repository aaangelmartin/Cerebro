/* Mercado · mesa de negociación en vivo (#mercado) e historial completo (#mercado/historial). */
(function () {
  "use strict";
  const US = "t10";
  const TYPES = ["compra", "venta", "cambio", "puja", "duelo", "dealer", "anuncio"];
  const TYPE_LABEL = { compra: "Compra", venta: "Venta", cambio: "Cambio", puja: "Puja", duelo: "Duelo", dealer: "Dealer", anuncio: "Anuncio" };

  // ---------- helpers ----------
  function h(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    if (attrs) for (const k in attrs) {
      const v = attrs[k];
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "style") n.setAttribute("style", v);
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v);
    }
    for (const c of kids.flat(Infinity)) {
      if (c == null || c === false) continue;
      n.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return n;
  }
  const U = () => window.ui || {};
  const fmtP = (n) => (n == null || !isFinite(n) ? "—" : U().fmtP ? U().fmtP(n) : (Math.round(n * 10) / 10).toLocaleString("es-ES") + " P");
  const pad = (n) => String(n).padStart(2, "0");
  const tclock = (tick) => (U().tickClock ? U().tickClock(tick) : "t" + (tick != null ? tick : "?"));
  const DAYS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
  function fmtTs(ts, withDay) {
    if (!ts) return "—";
    const d = new Date(ts * 1000);
    const t = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    return withDay ? `${DAYS[d.getDay()]} ${t}` : t;
  }
  function arr(x) {
    if (Array.isArray(x)) return x;
    if (x && typeof x === "object") {
      for (const k of ["items", "rows", "threads", "offers", "list", "data"]) if (Array.isArray(x[k])) return x[k];
      for (const k in x) if (Array.isArray(x[k])) return x[k];
    }
    return [];
  }
  async function safe(fn) { try { return { ok: true, v: await fn() }; } catch (e) { return { ok: false, err: e }; } }
  function stateBox(kind, text) {
    const u = U();
    if (kind === "loading" && u.loading) return u.loading();
    if (kind === "error" && u.error) return u.error(text);
    if (kind === "empty" && u.empty) return u.empty(text);
    if (kind === "loading" && u.loading) return u.loading(text);
    return h("div", { class: "mk-state mk-" + kind }, kind === "error" ? "Error: " + ((text && text.message) || text) : (text || "Cargando…"));
  }
  function typeChip(type, label) {
    if (U().typeChip) return U().typeChip(type, label);
    return h("span", { class: "mk-chip mk-t-" + type }, label || TYPE_LABEL[type] || type);
  }
  function teamTag(id) {
    if (!id) return h("span", { class: "mk-team" }, "—");
    if (U().teamTag) return U().teamTag(id, { us: id === US });
    return h("span", { class: "mk-team" + (id === US ? " is-us" : "") }, id === US ? "Nosotros" : teamName(id));
  }
  let NAMES = {};
  const teamName = (id) => (id === US ? "Nosotros" : NAMES[id] || (/^t\d+$/.test(id) ? "Team " + Number(id.slice(1)) : id));
  const refsOf = (side) => {
    const out = [];
    for (const a of (side && side.assets) || []) if (a) out.push(a.ref || (a.kind === "pack" ? "pack" : "#" + a.id));
    for (const t of (side && side.types) || []) if (typeof t === "string") out.push(t.replace(/^card:/, ""));
    return out;
  };
  const offerCash = (o) => (o ? (o.give && o.give.cash) || (o.want && o.want.cash) || null : null);
  function offerKind(o) {
    const g = refsOf(o.give), w = refsOf(o.want);
    if (g.length && w.length) return "cambio";
    if (g.length) return "venta";
    if (w.length) return "puja";
    return "anuncio";
  }
  function offerText(o) {
    const g = refsOf(o.give), w = refsOf(o.want);
    if (g.length && w.length) return `${g.join("+")}${o.give.cash ? " + " + o.give.cash + " P" : ""} ↔ ${w.join("+")}${o.want.cash ? " + " + o.want.cash + " P" : ""}`;
    if (g.length) return `${g.join(", ")} por ${fmtP(o.want && o.want.cash)}`;
    if (w.length) return `${w.join(", ")} por ≤ ${fmtP(o.give && o.give.cash)}`;
    return `${fmtP(offerCash(o))}`;
  }

  // ---------- feed classification ----------
  function classify(r) {
    const p = r.payload || {};
    const e = { seq: r.seq, ts: r.ts || r.seen_at, tick: r.tick, raw: r.type, type: "anuncio", team: r.actor || "", text: "", price: null, venue: p.venue || "", refs: [], teams: new Set() };
    if (r.actor) e.teams.add(r.actor);
    switch (r.type) {
      case "offer.listed": {
        const o = p.offer || {};
        e.type = offerKind(o); e.team = o.maker || r.actor; e.teams.add(o.maker);
        if (o.to) e.teams.add(o.to);
        e.refs = refsOf(o.give).concat(refsOf(o.want));
        e.text = offerText(o) + (o.venue ? " · " + o.venue : "");
        e.price = offerCash(o); e.venue = o.venue || "";
        e.label = TYPE_LABEL[e.type];
        break;
      }
      case "offer.cancelled":
        e.type = "anuncio"; e.label = "Retirada"; e.text = `oferta #${p.offer} retirada` + (p.venue ? " · " + p.venue : "");
        break;
      case "settlement": {
        const items = p.items || [];
        (p.parties || []).forEach((t) => e.teams.add(t));
        const cards = items.filter((i) => i.kind === "card" || i.kind === "pack");
        e.refs = cards.map((i) => i.ref);
        e.price = p.price || null;
        e.venue = p.venue || (p.persona ? p.persona : "");
        if (p.persona) { e.type = "dealer"; e.label = "Dealer"; }
        else if (p.kind === "swap" || (cards.length > 1 && !p.price)) { e.type = "cambio"; e.label = "Cambio"; }
        else { e.type = "compra"; e.label = "Compra"; }
        const buyer = cards[0] && cards[0].to;
        e.team = buyer || (p.parties || [])[0] || "";
        e.text = cards.map((i) => `${i.ref}${i.name ? " " + i.name : ""} · ${teamName(i.frm)} → ${teamName(i.to)}`).join("; ") || (p.kind || "liquidación");
        break;
      }
      case "duel.closed":
        e.type = "duelo"; e.label = "Duelo"; e.text = `${p.item || "duelo " + p.duel} · ${p.status === "deal" ? "acuerdo" : p.status === "no_deal" ? "sin acuerdo" : p.status || ""}`;
        if (p.team) { e.team = p.team; e.teams.add(p.team); }
        break;
      case "thread.opened": case "thread.message": case "thread.closed":
        e.type = "dealer"; e.label = "Dealer"; e.team = p.team || r.actor; if (p.team) e.teams.add(p.team);
        e.venue = p.with || "";
        e.text = r.type === "thread.opened" ? `abre conversación con ${p.with}` + (p.topic ? " · " + JSON.stringify(p.topic).replace(/[{}"]/g, "") : "") : `${p.sender || ""}: ${(p.text || "").slice(0, 140)}`;
        if (p.offer && typeof p.offer === "object") e.price = offerCash(p.offer);
        break;
      case "pack.opened":
        e.type = "dealer"; e.label = "Sobre"; e.team = p.team; e.teams.add(p.team); e.text = `abre ${p.pack}` + (p.best ? " · mejor " + p.best : ""); break;
      case "gift.given":
        e.type = "dealer"; e.label = "Regalo"; e.team = p.team; e.teams.add(p.team); e.refs = p.cards || []; e.text = `${r.actor} regala ${(p.cards || []).join(", ")}${p.cash ? " + " + p.cash + " P" : ""}`; break;
      default:
        e.type = "anuncio"; e.label = "Anuncio";
        e.text = p.text || p.why || Object.entries(p).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · ").slice(0, 160);
        if (p.team) { e.team = p.team; e.teams.add(p.team); }
    }
    e.teams.delete(""); e.teams.delete(undefined);
    e.us = e.teams.has(US);
    return e;
  }

  // ---------- shared state ----------
  const S = {
    feed: [], lastSeq: null, feedErr: null,
    live: { scope: "todos", filter: null },
    conv: { cache: {}, list: [], err: null, f: { kind: "", status: "", q: "" }, limit: 24, at: 0 },
    hist: { view: "eventos", rows: [], lastSeq: 0, loading: false, done: false, err: null, page: 0, f: { type: "", team: "", card: "", venue: "", from: "", to: "", q: "", us: false } },
  };

  async function pullFeedTail() {
    const api = window.api;
    if (S.lastSeq == null) {
      const r = await api.recStream("feed", { tail: 300 });
      S.feed = arr(r.rows || r);
      S.lastSeq = r.last_seq != null ? r.last_seq : (S.feed.length ? S.feed[S.feed.length - 1].seq : 0);
    } else {
      const r = await api.recStream("feed", { since_seq: S.lastSeq, limit: 500 });
      const rows = arr(r.rows || r);
      if (rows.length) { S.feed = S.feed.concat(rows).slice(-600); S.lastSeq = rows[rows.length - 1].seq; }
    }
  }

  // ---------- live: chats ----------
  function decisionsFor(decs, th) {
    const tp = th.topic ? JSON.stringify(th.topic) : null;
    return decs.filter((d) => d.thread === th.id || (Array.isArray(d.args) && d.args[0] === th.id) ||
      (tp && (d.dealer === th.with || (Array.isArray(d.args) && d.args[0] === th.with)) &&
        JSON.stringify(d.topic || (d.kwargs && d.kwargs.topic) || null) === tp));
  }
  function nextMove(ds) {
    const d = ds[ds.length - 1];
    if (!d) return null;
    let txt = d.action || "";
    if (d.action === "say" && Array.isArray(d.args)) txt = `Decir: «${String(d.args[1] || "").slice(0, 120)}»` + (d.kwargs && d.kwargs.price != null ? ` a ${d.kwargs.price} P` : "");
    else if (d.action === "walk away") txt = `Se retira: ellos ${d.theirs} P, nuestro límite ${d.limit} P`;
    else if (d.action === "deal") txt = `Trato a ${d.price} P (empezó en ${d.first})`;
    else if (d.why || d.reason) txt += " · " + (d.why || d.reason);
    const src = d.model ? "opus" : d.council ? "consejo" : d.strategy === "llm" ? "opus" : "codigo";
    return { txt, src, at: d.at };
  }
  function limitsFor(ds) {
    let limit = null, theirs = null;
    for (const d of ds) {
      if (d.limit != null) limit = d.limit;
      if (d.theirs != null) theirs = d.theirs;
      if (d.remembered_floor != null) theirs = d.remembered_floor;
      if (d.kwargs && d.kwargs.limit != null) limit = d.kwargs.limit;
    }
    return { limit, theirs };
  }
  function renderChat(th, decs, dealerNames, opts) {
    const full = !!(opts && opts.full);
    const tp = th.topic || {};
    const goal = tp.sell ? "venta" : tp.buy ? "compra" : "dealer";
    const who = th.with === US ? th.team : th.with;
    const isDealer = th.kind !== "team" && !/^t\d+$/.test(who || "");
    const msgs = arr(th.messages).slice().sort((a, b) => (a.tick || 0) - (b.tick || 0) || (a.id || 0) - (b.id || 0));
    const ours = msgs.filter((m) => m.sender === US && m.offer).map((m) => m.offer);
    const theirs = msgs.filter((m) => m.sender !== US && m.offer).map((m) => m.offer);
    const standing = arr(th.standing_offers).filter((o) => o.maker !== US && (!o.status || o.status === "open"));
    const ds = decisionsFor(decs, th);
    const lim = limitsFor(ds);
    const oursP = ours.length ? offerCash(ours[ours.length - 1]) : null;
    const theirsP = standing.length ? offerCash(standing[standing.length - 1]) : theirs.length ? offerCash(theirs[theirs.length - 1]) : null;
    const anyFinal = standing.some((o) => o.final) || theirs.some((o) => o.final && o.status === "open");
    const item = th.item || (tp.buy && (tp.buy.card || tp.buy.pack)) || (tp.sell && (tp.sell.assets || []).map((a) => "#" + a).join(", ")) || "";
    const status = anyFinal ? "última oferta" : th.status === "open" ? (msgs.length ? "negociando" : "abriendo") : th.status;

    const nums = [oursP, theirsP, lim.limit, lim.theirs].filter((x) => x != null);
    const max = nums.length ? Math.ceil(Math.max(...nums) * 1.4 / 10) * 10 : 40;
    let bar = null;
    if (U().priceBar && nums.length) {
      try { bar = U().priceBar({ min: 0, max, limit: lim.limit, ours: oursP, theirs: theirsP, compact: true, tint: goal }); } catch (e) { bar = null; }
    }
    if (!bar) bar = h("div", { class: "mk-pbar-fallback" }, `Nosotros ${fmtP(oursP)} · Ellos ${fmtP(theirsP)} · Límite ${fmtP(lim.limit)}`);

    const mv = nextMove(ds);
    const card = h("article", { class: "mk-chat" + (anyFinal ? " is-final" : "") },
      h("header", { class: "mk-chat-h" },
        typeChip(isDealer ? "dealer" : goal, isDealer ? "Dealer" : TYPE_LABEL[goal]),
        h("b", { class: "mk-chat-who" }, isDealer ? dealerNames[who] || who : teamName(who)),
        h("span", { class: "mk-status" + (anyFinal ? " is-final" : "") }, status)),
      h("div", { class: "mk-chat-sub" },
        h("span", null, `${goal === "venta" ? "Vendemos" : goal === "compra" ? "Compramos" : ""} ${item}`),
        h("span", { class: "mk-muted" }, `#${th.id} · ${msgs.length} mensajes` + (msgs.length ? ` · ${tclock(msgs[0].tick)}–${tclock(msgs[msgs.length - 1].tick)}` : ""))),
      h("div", { class: "mk-chat-bar" }, bar, h("span", { class: "mk-lims" }, `lím ${lim.limit != null ? lim.limit : "?"} · ${isDealer ? "él" : "ellos"} ~${lim.theirs != null ? lim.theirs : theirsP != null ? theirsP : "?"}`)),
      h("div", { class: "mk-msgs" }, msgs.length ? (full ? msgs : msgs.slice(-8)).map((m) => {
        const us = m.sender === US;
        return h("div", { class: "mk-msg" + (us ? " is-us" : "") + (m.offer && m.offer.final ? " is-final" : "") },
          h("div", { class: "mk-msg-h" }, h("span", null, us ? "Nosotros" : dealerNames[m.sender] || teamName(m.sender)),
            h("b", null, m.offer ? fmtP(offerCash(m.offer)) : ""), h("span", { class: "mk-muted", title: "tick " + (m.tick != null ? m.tick : "?") }, tclock(m.tick) + (m.offer && m.offer.status && m.offer.status !== "open" ? " · " + m.offer.status : ""))),
          h("div", { class: "mk-msg-t" }, m.text || ""));
      }) : stateBox("empty", "Sin mensajes todavía.")),
      h("footer", { class: "mk-chat-f" },
        h("div", { class: "mk-standing" + (anyFinal ? " is-final" : "") }, h("span", { class: "mk-k" }, "OFERTA EN PIE"),
          standing.length ? standing.map((o) => h("span", null, h("b", null, fmtP(offerCash(o))), " · " + offerText(o), o.final ? h("span", { class: "mk-final" }, "final: true") : null)) : h("span", { class: "mk-muted" }, "ninguna")),
        h("div", { class: "mk-next" }, h("span", { class: "mk-k" }, "SIGUIENTE"), mv ? [h("span", { class: "mk-next-t" }, mv.txt), U().sourceTag ? U().sourceTag(mv.src) : h("span", { class: "mk-src" }, mv.src)] : h("span", { class: "mk-muted" }, "sin decisión registrada"))));
    return card;
  }

  // ---------- live: side ----------
  function tapeRow(e) {
    const row = h("div", { class: "mk-tape-row mk-t-" + e.type + (e.us ? " is-us" : "") },
      h("div", { class: "mk-tape-a" }, typeChip(e.type, e.label), teamTag(e.team), h("span", { class: "mk-grow" }), h("b", null, e.price != null ? (e.type === "puja" ? "≤ " : "") + fmtP(e.price) : ""), h("span", { class: "mk-muted" }, fmtTs(e.ts))),
      h("div", { class: "mk-tape-b" }, e.text));
    return row;
  }
  function ticksLeft(o, clock) {
    if (o.expires_tick == null || !clock || clock.tick == null) return "—";
    const t = o.expires_tick - clock.tick;
    const secs = t * (clock.tick_seconds || 60);
    const s = Math.max(0, Math.round(secs));
    return `${t} ticks · ${Math.floor(s / 60)}:${pad(s % 60)}`;
  }

  function renderSide(root, ctx) {
    const side = root.querySelector(".mk-side");
    if (!side) return;
    const f = S.live;
    const events = S.feed.map(classify).reverse();
    const counts = {};
    for (const e of events) counts[e.type] = (counts[e.type] || 0) + 1;
    const seg = h("div", { class: "mk-seg-row" },
      h("div", { class: "mk-seg" }, h("button", { class: "on" }, "● En vivo"), h("button", { onclick: () => { location.hash = "#mercado/historial"; } }, "Historial")),
      h("div", { class: "mk-seg" }, ["todos", "nosotros"].map((s) => h("button", { class: f.scope === s ? "on" : "", onclick: () => { f.scope = s; renderSide(root, ctx); } }, s === "todos" ? "Todos" : "Nosotros"))));
    let fb = side.querySelector(".mk-fb");
    if (!fb) {
      if (U().filterBar) {
        try {
          fb = U().filterBar({ types: TYPES, counts, team: true, search: true, onChange: (st) => { f.filter = st; renderSide(root, ctx); } });
        } catch (e) { fb = null; }
      }
      if (!fb) fb = h("div", null, h("input", { class: "mk-input", placeholder: "Buscar…", oninput: (ev) => { f.filter = { q: ev.target.value }; renderSide(root, ctx); } }));
      fb.classList.add("mk-fb");
    }
    const st = f.filter || {};
    if (fb.setCounts) fb.setCounts(counts);
    const shown = events.filter((e) => {
      if (f.scope === "nosotros" && !e.us) return false;
      if (fb.matches) return fb.matches({ type: e.type, teams: [...e.teams], text: e.text + " " + e.team + " " + e.refs.join(" ") + " " + e.venue });
      if (st.types && st.types.size && !st.types.has(e.type)) return false;
      if (st.team === "nosotros" && !e.us) return false;
      if (st.team === "rivales" && e.us) return false;
      if (st.team && /^t\d+$/.test(st.team) && !e.teams.has(st.team)) return false;
      if (st.q) { const q = st.q.toLowerCase(); if (!(e.text + " " + e.team + " " + e.refs.join(" ") + " " + e.venue).toLowerCase().includes(q)) return false; }
      return true;
    });
    const tape = h("div", { class: "mk-tape" }, S.feedErr && !S.feed.length ? stateBox("error", S.feedErr) : shown.length ? shown.slice(0, 120).map(tapeRow) : stateBox("empty", S.feed.length ? "Nada coincide con los filtros." : "El feed está vacío (mercado cerrado o grabadora sin datos)."));

    const offers = ctx.myOffers || [];
    const mine = offers.filter((o) => o.maker === US);
    const toUs = offers.filter((o) => o.to === US && o.maker !== US);
    const decs = ctx.decisions || [];
    const decFor = (o) => {
      const d = decs.filter((x) => x.offer === o.id || (Array.isArray(x.args) && x.args.includes(o.id))).pop();
      return d ? (d.action || "") + (d.why ? " · " + d.why : "") : "sin decisión aún";
    };
    const offerRow = (o, dec) => h("div", { class: "mk-off mk-t-" + offerKind(o) },
      h("div", { class: "mk-tape-a" }, typeChip(offerKind(o)), h("span", null, offerText(o)), h("span", { class: "mk-grow" }),
        h("span", { class: "mk-muted" }, o.venue || (o.thread ? "chat #" + o.thread : o.to ? "a " + teamName(o.to) : ""))),
      h("div", { class: "mk-tape-b" }, h("span", null, `#${o.id} · ${o.created_tick != null ? tclock(o.created_tick) + " · " : ""}${o.status || "open"} · vence en ${ticksLeft(o, ctx.clock)}`), o.final ? h("span", { class: "mk-final" }, "final") : null, dec ? h("span", { class: "mk-muted" }, " · bot: " + dec) : null));

    side.replaceChildren(seg, fb, tape,
      h("div", { class: "mk-sec" }, `NUESTRAS OFERTAS ABIERTAS · ${mine.length}`),
      h("div", { class: "mk-offs" }, mine.length ? mine.map((o) => offerRow(o)) : stateBox("empty", "No tenemos ofertas abiertas.")),
      h("div", { class: "mk-sec" }, `OFERTAS A NOSOTROS · ${toUs.length}`),
      h("div", { class: "mk-offs" }, toUs.length ? toUs.map((o) => offerRow(o, decFor(o))) : stateBox("empty", "Nadie nos ha dirigido ofertas.")));
  }

  async function refreshLive(root, data) {
    const api = window.api;
    if (!api) throw new Error("api.js no cargado");
    const [threads, decisions, myOffers, clock, dealers, lb] = await Promise.all([
      safe(() => api.recThreads()), safe(() => api.decisions()), safe(() => api.rec("my_offers")),
      safe(() => api.rec("clock")), safe(() => api.rec("dealers")), safe(() => api.rec("leaderboard")),
    ]);
    const feedRes = await safe(pullFeedTail);
    S.feedErr = feedRes.ok ? null : feedRes.err;
    if (lb.ok) for (const r of arr(lb.v.data || lb.v)) if (r && (r.team || r.id)) NAMES[r.team || r.id] = r.name;
    const dealerNames = {};
    if (dealers.ok) for (const p of arr(dealers.v.personas || dealers.v)) if (p && p.id) dealerNames[p.id] = p.name;
    const decs = decisions.ok ? arr(decisions.v) : [];
    const ctx = { myOffers: myOffers.ok ? arr(myOffers.v.offers || myOffers.v) : [], clock: clock.ok ? clock.v : null, decisions: decs };

    const chatsHost = root.querySelector(".mk-chats");
    const head = root.querySelector(".mk-head-sub");
    if (!threads.ok) {
      chatsHost.replaceChildren(stateBox("error", threads.err));
    } else {
      const open = arr(threads.v).filter((t) => !t.status || t.status === "open");
      const details = await Promise.all(open.map((t) => safe(() => api.recThread(t.id))));
      const full = details.map((d, i) => (d.ok ? { ...open[i], ...(d.v.thread || d.v) } : open[i]));
      const nd = full.filter((t) => t.kind !== "team").length;
      if (head) head.textContent = `${full.length} conversaciones abiertas · ${nd} con dealers y ${full.length - nd} con equipos`;
      chatsHost.replaceChildren(...(full.length ? full.map((t) => renderChat(t, decs, dealerNames)) : [stateBox("empty", "No hay conversaciones abiertas ahora mismo. El mercado puede estar cerrado.")]));
    }
    renderSide(root, ctx);
  }

  // ---------- historial ----------
  async function pullHistory() {
    const H = S.hist;
    if (H.loading) return;
    H.loading = true;
    try {
      for (let guard = 0; guard < 60; guard++) {
        const r = await window.api.recStream("feed", { since_seq: H.lastSeq, limit: 2000 });
        const rows = arr(r.rows || r);
        if (!rows.length) break;
        for (const x of rows) H.rows.push(classify(x));
        H.lastSeq = rows[rows.length - 1].seq;
        if (rows.length < 2000) break;
      }
      H.err = null; H.done = true;
    } catch (e) { H.err = e; } finally { H.loading = false; }
  }
  function histFiltered() {
    const f = S.hist.f;
    const from = f.from ? new Date(f.from).getTime() / 1000 : null;
    const to = f.to ? new Date(f.to).getTime() / 1000 : null;
    const q = f.q.toLowerCase(), card = f.card.toUpperCase();
    return S.hist.rows.filter((e) => {
      if (f.us && !e.us) return false;
      if (f.type && e.type !== f.type) return false;
      if (f.team && !e.teams.has(f.team)) return false;
      if (card && !e.refs.some((r) => r && r.toUpperCase().startsWith(card))) return false;
      if (f.venue && e.venue !== f.venue) return false;
      if (from && e.ts < from) return false;
      if (to && e.ts > to) return false;
      if (q && !(e.text + " " + e.team + " " + e.refs.join(" ") + " " + e.venue + " " + e.raw).toLowerCase().includes(q)) return false;
      return true;
    }).reverse();
  }
  const csvCell = (v) => { const s = v == null ? "" : String(v); return /[",\n;]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  function toCSV(rows) {
    const head = ["seq", "fecha", "tick", "tipo", "evento", "equipo", "equipos", "detalle", "sede", "precio", "cartas", "nosotros"];
    const lines = [head.join(",")];
    for (const e of rows) lines.push([e.seq, e.ts ? new Date(e.ts * 1000).toISOString() : "", e.tick, e.type, e.raw, e.team, [...e.teams].join(" "), e.text, e.venue, e.price, e.refs.join(" "), e.us ? "sí" : ""].map(csvCell).join(","));
    return lines.join("\n");
  }
  function renderHistory(root) {
    const host = root.querySelector(".mk-hist");
    if (!host) return;
    const H = S.hist, f = H.f;
    if (!H.rows.length) {
      host.querySelector(".mk-hist-table").replaceChildren(H.err ? stateBox("error", H.err) : H.loading || !H.done ? stateBox("loading") : stateBox("empty", "Aún no hay eventos grabados."));
      return;
    }
    // populate selects once
    const teamSel = host.querySelector("[data-f=team]"), venueSel = host.querySelector("[data-f=venue]");
    const teams = new Set(), venues = new Set();
    for (const e of H.rows) { e.teams.forEach((t) => teams.add(t)); if (e.venue) venues.add(e.venue); }
    const fill = (sel, vals, label) => {
      if (sel.options.length - 1 === vals.length) return;
      const cur = sel.value;
      sel.replaceChildren(h("option", { value: "" }, label), ...vals.map((v) => h("option", { value: v }, v === US ? "Nosotros (t10)" : v)));
      sel.value = cur;
    };
    fill(teamSel, [...teams].sort(), "Equipo: todos");
    fill(venueSel, [...venues].sort(), "Sede: todas");

    const rows = histFiltered();
    const per = 50, pages = Math.max(1, Math.ceil(rows.length / per));
    H.page = Math.min(H.page, pages - 1);
    const slice = rows.slice(H.page * per, H.page * per + per);
    const usRows = rows.filter((e) => e.us);
    const usVol = usRows.reduce((a, e) => a + (e.price || 0), 0);
    host.querySelector(".mk-hist-sum").textContent = `${rows.length} de ${H.rows.length} eventos · Nosotros: ${usRows.length} · volumen con precio ${fmtP(usVol)}` + (H.loading ? " · cargando…" : "");
    const table = h("table", { class: "mk-table" },
      h("thead", null, h("tr", null, ["Fecha", "Tick", "Tipo", "Equipo", "Detalle", "Sede", "Precio"].map((x) => h("th", null, x)))),
      h("tbody", null, slice.map((e) => h("tr", { class: "mk-t-" + e.type + (e.us ? " is-us" : "") },
        h("td", { class: "mk-mono" }, fmtTs(e.ts, true)), h("td", { class: "mk-mono" }, e.tick != null ? "t" + e.tick : ""),
        h("td", null, typeChip(e.type, e.label)), h("td", null, teamTag(e.team)),
        h("td", { class: "mk-det" }, e.text), h("td", { class: "mk-mono" }, e.venue), h("td", { class: "mk-mono mk-r" }, e.price != null ? fmtP(e.price) : "")))));
    host.querySelector(".mk-hist-table").replaceChildren(slice.length ? table : stateBox("empty", "Ningún evento coincide con los filtros."));
    // pager
    const pg = host.querySelector(".mk-pager");
    const btn = (label, p, on) => h("button", { class: on ? "on" : "", disabled: p < 0 || p >= pages ? "disabled" : null, onclick: () => { H.page = p; renderHistory(root); } }, label);
    const nums = new Set([0, pages - 1, H.page - 1, H.page, H.page + 1].filter((p) => p >= 0 && p < pages));
    const list = [...nums].sort((a, b) => a - b);
    const parts = [btn("‹", H.page - 1)];
    list.forEach((p, i) => { if (i && p - list[i - 1] > 1) parts.push(h("span", null, "…")); parts.push(btn(String(p + 1), p, p === H.page)); });
    parts.push(btn("›", H.page + 1));
    pg.replaceChildren(h("span", { class: "mk-muted" }, `${rows.length ? H.page * per + 1 : 0}–${Math.min(rows.length, (H.page + 1) * per)} de ${rows.length}`), h("span", { class: "mk-grow" }), ...parts);
    // export
    const csv = toCSV(rows);
    const a = host.querySelector(".mk-export");
    a.setAttribute("href", "data:text/csv;charset=utf-8," + encodeURIComponent("﻿" + csv));
    a.setAttribute("download", "bazaar-historial.csv");
    S.hist.csv = csv;
  }
  // ---------- historial: every conversation we had, full transcripts ----------
  const TH_STATUS = { deal: "acuerdo", closed: "cerrada", open: "abierta", expired: "caducada" };
  async function pullConversations() {
    const api = window.api, C = S.conv;
    if (Date.now() - C.at < 4000 && C.list.length) return;
    C.at = Date.now();
    const r = await safe(() => api.recThreads());
    if (!r.ok) { C.err = r.err; return; }
    C.err = null;
    C.list = arr(r.v).slice().sort((a, b) => (b.last_change_tick || b.created_tick || 0) - (a.last_change_tick || a.created_tick || 0) || b.id - a.id);
    const want = convFiltered().slice(0, C.limit);
    const need = want.filter((t) => { const c = C.cache[t.id]; return !c || c.count !== t.message_count || (t.status === "open" && Date.now() - c.at > 4000); });
    const got = await Promise.all(need.map((t) => safe(() => api.recThread(t.id))));
    got.forEach((g, i) => { if (g.ok) C.cache[need[i].id] = { count: need[i].message_count, at: Date.now(), data: { ...need[i], ...(g.v.thread || g.v) } }; });
  }
  function convFiltered() {
    const f = S.conv.f, q = f.q.toLowerCase();
    return S.conv.list.filter((t) => {
      const other = t.with === US ? t.team : t.with;
      const isDealer = t.kind !== "team" && !/^t\d+$/.test(other || "");
      if (f.kind === "dealer" && !isDealer) return false;
      if (f.kind === "equipo" && isDealer) return false;
      if (f.status && t.status !== f.status) return false;
      if (q && !`${t.with} ${t.team} ${t.item || ""} ${JSON.stringify(t.topic || {})} #${t.id}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }
  function renderConversations(root, dealerNames) {
    const host = root.querySelector(".mk-conv-list"); if (!host) return;
    const C = S.conv;
    if (C.err && !C.list.length) { host.replaceChildren(stateBox("error", C.err)); return; }
    if (!C.list.length) { host.replaceChildren(stateBox("loading")); return; }
    const rows = convFiltered();
    const counts = {}; for (const t of C.list) counts[t.status] = (counts[t.status] || 0) + 1;
    root.querySelector(".mk-conv-sum").textContent = `${rows.length} de ${C.list.length} conversaciones · ` +
      Object.entries(counts).map(([k, v]) => `${v} ${TH_STATUS[k] || k}`).join(" · ");
    const shown = rows.slice(0, C.limit);
    const cards = shown.map((t) => {
      const c = C.cache[t.id];
      const card = renderChat(c ? c.data : t, [], dealerNames, { full: true });
      card.classList.add("mk-chat-hist", "mk-st-" + (t.status || "open"));
      const st = card.querySelector(".mk-status"); if (st) st.textContent = TH_STATUS[t.status] || t.status || "";
      return card;
    });
    host.replaceChildren(...(cards.length ? cards : [stateBox("empty", "Ninguna conversación coincide con los filtros.")]),
      rows.length > C.limit ? h("button", { class: "mk-btn mk-more", onclick: () => { C.limit += 24; C.at = 0; window.Screens.mercado.refresh(root, null, "historial"); } }, `Mostrar más (${rows.length - C.limit})`) : null);
  }
  let DEALER_NAMES = {};

  function mountHistory(root) {
    const f = S.hist.f;
    const upd = (k) => (ev) => { f[k] = ev.target.type === "checkbox" ? ev.target.checked : ev.target.value; S.hist.page = 0; renderHistory(root); };
    const copyBtn = h("button", { class: "mk-btn", onclick: async (ev) => {
      const t = S.hist.csv || "";
      let ok = false;
      try { await navigator.clipboard.writeText(t); ok = true; } catch (e) {
        const ta = h("textarea", { style: "position:fixed;left:-9999px" }); ta.value = t; document.body.appendChild(ta); ta.select();
        try { ok = document.execCommand("copy"); } catch (e2) { ok = false; } ta.remove();
      }
      ev.target.textContent = ok ? "Copiado" : "No se pudo copiar"; setTimeout(() => { ev.target.textContent = "Copiar CSV"; }, 1800);
    } }, "Copiar CSV");
    root.replaceChildren(h("div", { class: "scr-mercado is-hist" },
      h("div", { class: "mk-head" }, h("h1", null, "Mercado · Historial"), h("span", { class: "mk-muted" }, S.hist.view === "conv" ? "todas nuestras conversaciones, completas" : "todos los eventos del feed desde el viernes"),
        h("span", { class: "mk-grow" }),
        h("div", { class: "mk-seg mk-histview" }, ["eventos", "conv"].map((v) => h("button", { class: S.hist.view === v ? "on" : "", "data-v": v, onclick: () => { S.hist.view = v; mountHistory(root); window.Screens.mercado.refresh(root, null, "historial"); } }, v === "eventos" ? "Eventos" : "Conversaciones"))),
        h("div", { class: "mk-seg" }, h("button", { onclick: () => { location.hash = "#mercado"; } }, "● En vivo"), h("button", { class: "on" }, "Historial"))),
      S.hist.view === "conv" ? h("div", { class: "mk-conv" },
        h("div", { class: "mk-hfilters" },
          h("select", { class: "mk-input", onchange: (ev) => { S.conv.f.kind = ev.target.value; S.conv.at = 0; window.Screens.mercado.refresh(root, null, "historial"); } },
            [["", "Con: todos"], ["dealer", "Dealers"], ["equipo", "Equipos"]].map(([v, l]) => h("option", { value: v, selected: S.conv.f.kind === v ? "selected" : null }, l))),
          h("select", { class: "mk-input", onchange: (ev) => { S.conv.f.status = ev.target.value; S.conv.at = 0; window.Screens.mercado.refresh(root, null, "historial"); } },
            [["", "Estado: todos"], ["deal", "Con acuerdo"], ["closed", "Cerradas sin acuerdo"], ["open", "Abiertas"]].map(([v, l]) => h("option", { value: v, selected: S.conv.f.status === v ? "selected" : null }, l))),
          h("input", { class: "mk-input mk-q", placeholder: "Buscar dealer, equipo, carta…", value: S.conv.f.q, oninput: (ev) => { S.conv.f.q = ev.target.value; S.conv.at = 0; renderConversations(root, DEALER_NAMES); } })),
        h("div", { class: "mk-conv-sum mk-muted" }),
        h("div", { class: "mk-conv-list" }, stateBox("loading"))) :
      h("div", { class: "mk-hist" },
        h("div", { class: "mk-hfilters" },
          h("select", { class: "mk-input", onchange: upd("type") }, h("option", { value: "" }, "Tipo: todos"), TYPES.map((t) => h("option", { value: t }, TYPE_LABEL[t]))),
          h("select", { class: "mk-input", "data-f": "team", onchange: upd("team") }, h("option", { value: "" }, "Equipo: todos")),
          h("input", { class: "mk-input", placeholder: "Carta o set (LAV, MAL-04)", oninput: upd("card") }),
          h("select", { class: "mk-input", "data-f": "venue", onchange: upd("venue") }, h("option", { value: "" }, "Sede: todas")),
          h("label", { class: "mk-muted" }, "desde ", h("input", { class: "mk-input", type: "datetime-local", onchange: upd("from") })),
          h("label", { class: "mk-muted" }, "hasta ", h("input", { class: "mk-input", type: "datetime-local", onchange: upd("to") })),
          h("label", { class: "mk-muted" }, h("input", { type: "checkbox", onchange: upd("us") }), " solo nosotros"),
          h("input", { class: "mk-input mk-q", placeholder: "Buscar texto…", oninput: upd("q") }),
          h("span", { class: "mk-grow" }),
          h("a", { class: "mk-btn mk-export", href: "#", download: "bazaar-historial.csv" }, "Exportar CSV"), copyBtn),
        h("div", { class: "mk-hist-sum mk-muted" }),
        h("div", { class: "mk-hist-table" }, stateBox("loading")),
        h("div", { class: "mk-pager" }))));
  }

  // ---------- screen ----------
  function mountLive(root) {
    root.replaceChildren(h("div", { class: "scr-mercado" },
      h("div", { class: "mk-main" },
        h("div", { class: "mk-head" }, h("h1", null, "Mercado"), h("span", { class: "mk-muted mk-head-sub" }, "")),
        h("div", { class: "mk-chats" }, stateBox("loading"))),
      h("aside", { class: "mk-side" }, stateBox("loading"))));
  }

  window.Screens = window.Screens || {};
  window.Screens["mercado"] = {
    title: "Mercado",
    mount(root, params) {
      S.mode = params === "historial" || params === "conversaciones" ? "hist" : "live";
      if (params === "conversaciones") S.hist.view = "conv";
      S.live.filter = null;
      if (S.mode === "hist") mountHistory(root); else mountLive(root);
    },
    async refresh(root, data, params) {
      const mode = params === "historial" || params === "conversaciones" ? "hist" : "live";
      if (mode !== S.mode) { this.mount(root, params); }
      try {
        if (S.mode === "hist" && S.hist.view === "conv") {
          if (!Object.keys(DEALER_NAMES).length) { const d = await safe(() => window.api.rec("dealers")); if (d.ok) for (const p of arr(d.v.personas || d.v)) if (p && p.id) DEALER_NAMES[p.id] = p.name; }
          await pullConversations(); renderConversations(root, DEALER_NAMES);
        } else if (S.mode === "hist") { await pullHistory(); renderHistory(root); }
        else await refreshLive(root, data);
      } catch (e) {
        const host = root.querySelector(S.mode === "hist" ? ".mk-hist-table, .mk-conv-list" : ".mk-chats");
        if (host) host.replaceChildren(stateBox("error", e));
      }
    },
    onParams(root, params) { this.mount(root, params); this.refresh(root, null, params); },
    unmount() {},
    _test: { classify, toCSV },
  };
})();
