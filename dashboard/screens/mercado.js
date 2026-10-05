/* Mercado · mesa de negociación en vivo (#mercado) e historial completo (#mercado/historial). */
(function () {
  "use strict";
  const US = "t10";
  const TYPES = ["compra", "venta", "cambio", "puja", "duelo", "dealer", "anuncio"];
  // interface texts: looked up on every read, so a language switch shows on the next paint
  const T = (k, v) => (window.I18N ? window.I18N.t(k, v) : k);
  const lang = () => (window.I18N && window.I18N.lang) || "es";
  const LOC = () => (lang() === "en" ? "en-GB" : "es-ES");
  const lazy = (map) => { const o = {}; for (const k in map) Object.defineProperty(o, k, { enumerable: true, get: () => T(map[k]) }); return o; };
  const TYPE_LABEL = lazy({ compra: "mercado.type.compra", venta: "mercado.type.venta", cambio: "mercado.type.cambio", puja: "mercado.type.puja", duelo: "mercado.type.duelo", dealer: "mercado.type.dealer", anuncio: "mercado.type.anuncio" });

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
  const fmtP = (n) => (n == null || !isFinite(n) ? "—" : U().fmtP ? U().fmtP(n) : (Math.round(n * 10) / 10).toLocaleString(LOC()) + " P");
  const pad = (n) => String(n).padStart(2, "0");
  const num = (x) => (x === null || x === undefined || x === "" || isNaN(+x) ? null : +x);
  const tclock = (tick) => (U().tickClock ? U().tickClock(tick) : "t" + (tick != null ? tick : "?"));
  const DAYS = () => T("mercado.days").split(",");
  function fmtTs(ts, withDay) {
    if (!ts) return "—";
    const d = new Date(ts * 1000);
    const t = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    return withDay ? `${DAYS()[d.getDay()]} ${t}` : t;
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
    return h("div", { class: "mk-state mk-" + kind }, kind === "error" ? T("mercado.error", { err: (text && text.message) || text }) : (text || T("mercado.loading")));
  }
  function typeChip(type, label) {
    if (U().typeChip) return U().typeChip(type, label);
    return h("span", { class: "mk-chip mk-t-" + type }, label || TYPE_LABEL[type] || type);
  }
  function teamTag(id) {
    if (!id) return h("span", { class: "mk-team" }, "—");
    if (U().teamTag) return U().teamTag(id, { us: id === US });
    return h("span", { class: "mk-team" + (id === US ? " is-us" : "") }, teamName(id));
  }
  let NAMES = {};
  const teamName = (id) => (id === US ? T("mercado.us") : NAMES[id] || (/^t\d+$/.test(id) ? "Team " + Number(id.slice(1)) : id));
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
    if (g.length) return T("mercado.offer.for", { cards: g.join(", "), price: fmtP(o.want && o.want.cash) });
    if (w.length) return T("mercado.offer.for_max", { cards: w.join(", "), price: fmtP(o.give && o.give.cash) });
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
        e.type = "anuncio"; e.label = T("mercado.type.withdrawn"); e.text = T("mercado.ev.withdrawn", { id: p.offer }) + (p.venue ? " · " + p.venue : "");
        break;
      case "settlement": {
        const items = p.items || [];
        (p.parties || []).forEach((t) => e.teams.add(t));
        const cards = items.filter((i) => i.kind === "card" || i.kind === "pack");
        e.refs = cards.map((i) => i.ref);
        e.price = p.price || null;
        e.venue = p.venue || (p.persona ? p.persona : "");
        if (p.persona) { e.type = "dealer"; e.label = TYPE_LABEL.dealer; }
        else if (p.kind === "swap" || (cards.length > 1 && !p.price)) { e.type = "cambio"; e.label = TYPE_LABEL.cambio; }
        else { e.type = "compra"; e.label = TYPE_LABEL.compra; }
        const buyer = cards[0] && cards[0].to;
        e.team = buyer || (p.parties || [])[0] || "";
        e.text = cards.map((i) => `${i.ref}${i.name ? " " + i.name : ""} · ${teamName(i.frm)} → ${teamName(i.to)}`).join("; ") || (p.kind || T("mercado.ev.settlement"));
        break;
      }
      case "duel.closed":
        e.type = "duelo"; e.label = TYPE_LABEL.duelo; e.text = `${p.item || T("mercado.ev.duel", { id: p.duel })} · ${p.status === "deal" ? T("mercado.ev.deal") : p.status === "no_deal" ? T("mercado.ev.no_deal") : p.status || ""}`;
        if (p.team) { e.team = p.team; e.teams.add(p.team); }
        break;
      case "thread.opened": case "thread.message": case "thread.closed":
        e.type = "dealer"; e.label = TYPE_LABEL.dealer; e.team = p.team || r.actor; if (p.team) e.teams.add(p.team);
        e.venue = p.with || "";
        e.text = r.type === "thread.opened" ? T("mercado.ev.opens_thread", { who: p.with }) + (p.topic ? " · " + JSON.stringify(p.topic).replace(/[{}"]/g, "") : "") : `${p.sender || ""}: ${(p.text || "").slice(0, 140)}`;
        if (p.offer && typeof p.offer === "object") e.price = offerCash(p.offer);
        break;
      case "pack.opened":
        e.type = "dealer"; e.label = T("mercado.type.pack"); e.team = p.team; e.teams.add(p.team); e.text = T("mercado.ev.opens_pack", { pack: p.pack }) + (p.best ? T("mercado.ev.best", { best: p.best }) : ""); break;
      case "gift.given":
        e.type = "dealer"; e.label = T("mercado.type.gift"); e.team = p.team; e.teams.add(p.team); e.refs = p.cards || []; e.text = T("mercado.ev.gift", { who: r.actor, cards: (p.cards || []).join(", ") + (p.cash ? " + " + p.cash + " P" : "") }); break;
      default:
        e.type = "anuncio"; e.label = TYPE_LABEL.anuncio;
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
    hist: { view: "conv", rows: [], lastSeq: 0, loading: false, done: false, err: null, page: 0, f: { type: "", team: "", card: "", venue: "", from: "", to: "", q: "", us: false } },
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
  // bot decisions (decisions.jsonl rows) -> the flat shape the chat helpers read
  const KIND_TXT = lazy({ thread_message: "mercado.dec.thread_message", open_thread: "mercado.dec.open_thread", close_thread: "mercado.dec.close_thread", accept_offer: "mercado.dec.accept", thread_accept: "mercado.dec.accept" });
  function normDec(r) {
    if (!r || !r.action || typeof r.action !== "object") return r;
    const a = r.action, p = a.params || {}, x = a.expected || {};
    const isOpen = a.kind === "open_thread";
    const out = { thread: p.thread, dealer: p.with, topic: p.topic, at: r.ts, why: a.reason, model: r.source === "opus" ? "opus" : null,
      council: r.source === "council", strategy: r.source === "opus" ? "llm" : "code", kind: a.kind, price: p.price };
    out.action = a.kind === "thread_message" ? "say" : KIND_TXT[a.kind] || a.kind;
    if (a.kind === "thread_message") out.args = [p.thread, p.text];
    if (a.kind === "thread_message" && p.price != null) out.kwargs = { price: p.price };
    // our ceiling/floor: the limit set when the conversation opened, else our value for the card
    if (isOpen && x.limit != null) out.limit = x.limit; else if (x.value != null) out.value = x.value;
    if (x.dealer_limit_est != null) out.theirs = Math.round(x.dealer_limit_est * 10) / 10;
    return out;
  }
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
    if (d.action === "say" && Array.isArray(d.args)) txt = T(d.kwargs && d.kwargs.price != null ? "mercado.dec.say_price" : "mercado.dec.say", { text: String(d.args[1] || "").slice(0, 120), price: d.kwargs && d.kwargs.price });
    else if (d.action === "walk away") txt = T("mercado.dec.walk", { theirs: d.theirs, limit: d.limit });
    else if (d.action === "deal") txt = T("mercado.dec.deal", { price: d.price, first: d.first });
    else if (d.why || d.reason) txt += " · " + (d.why || d.reason);
    const src = d.model ? "opus" : d.council ? "consejo" : d.strategy === "llm" ? "opus" : "codigo";
    return { txt, src, at: d.at };
  }
  function limitsFor(ds) {
    let limit = null, theirs = null, value = null;
    for (const d of ds) {
      if (d.value != null) value = d.value;
      if (d.limit != null) limit = d.limit;
      if (d.theirs != null) theirs = d.theirs;
      if (d.remembered_floor != null) theirs = d.remembered_floor;
      if (d.kwargs && d.kwargs.limit != null) limit = d.kwargs.limit;
    }
    return { limit: limit != null ? limit : value, theirs };
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
    const status = anyFinal ? T("mercado.chat.final") : th.status === "open" ? T(msgs.length ? "mercado.chat.negotiating" : "mercado.chat.opening") : th.status;

    const nums = [oursP, theirsP, lim.limit, lim.theirs].filter((x) => x != null);
    const max = nums.length ? Math.ceil(Math.max(...nums) * 1.4 / 10) * 10 : 40;
    let bar = null;
    if (U().priceBar && nums.length) {
      try { bar = U().priceBar({ min: 0, max, limit: lim.limit, ours: oursP, theirs: theirsP, compact: true, tint: goal }); } catch (e) { bar = null; }
    }
    if (!bar) bar = h("div", { class: "mk-pbar-fallback" }, T("mercado.chat.bar", { ours: fmtP(oursP), theirs: fmtP(theirsP), limit: fmtP(lim.limit) }));

    const mv = nextMove(ds);
    const card = h("article", { class: "mk-chat" + (anyFinal ? " is-final" : "") },
      h("header", { class: "mk-chat-h" },
        typeChip(isDealer ? "dealer" : goal === "dealer" ? "cambio" : goal, isDealer ? TYPE_LABEL.dealer : goal === "dealer" ? T("mercado.type.team") : TYPE_LABEL[goal]),
        h("b", { class: "mk-chat-who" }, isDealer ? dealerNames[who] || who : teamName(who)),
        h("span", { class: "mk-status" + (anyFinal ? " is-final" : "") }, status)),
      h("div", { class: "mk-chat-sub" },
        h("span", null, goal === "venta" ? T("mercado.chat.we_sell", { item }) : goal === "compra" ? T("mercado.chat.we_buy", { item }) : " " + item),
        h("span", { class: "mk-muted" }, `#${th.id} · ` + T(msgs.length === 1 ? "mercado.chat.msg_one" : "mercado.chat.msgs", { n: msgs.length }) + (msgs.length ? ` · ${tclock(msgs[0].tick)}–${tclock(msgs[msgs.length - 1].tick)}` : ""))),
      h("div", { class: "mk-chat-bar" }, bar, h("span", { class: "mk-lims" }, [lim.limit != null ? T("mercado.chat.lim", { n: lim.limit }) : null, (lim.theirs != null || theirsP != null) ? T(isDealer ? "mercado.chat.him" : "mercado.chat.them", { n: lim.theirs != null ? lim.theirs : theirsP }) : null].filter(Boolean).join(" · "))),
      h("div", { class: "mk-msgs" }, msgs.length ? (full ? msgs : msgs.slice(-8)).map((m) => {
        const us = m.sender === US;
        return h("div", { class: "mk-msg" + (us ? " is-us" : "") + (m.offer && m.offer.final ? " is-final" : "") },
          h("div", { class: "mk-msg-h" }, h("span", null, us ? T("mercado.us") : dealerNames[m.sender] || teamName(m.sender)),
            h("b", null, m.offer ? fmtP(offerCash(m.offer)) : ""), h("span", { class: "mk-muted", title: "tick " + (m.tick != null ? m.tick : "?") }, tclock(m.tick) + (m.offer && m.offer.status && m.offer.status !== "open" ? " · " + m.offer.status : ""))),
          h("div", { class: "mk-msg-t" }, m.text || ""));
      }) : stateBox("empty", T("mercado.chat.no_msgs"))),
      h("footer", { class: "mk-chat-f" },
        h("div", { class: "mk-standing" + (anyFinal ? " is-final" : "") }, h("span", { class: "mk-k" }, T("mercado.chat.standing")),
          standing.length ? standing.map((o) => h("span", null, h("b", null, fmtP(offerCash(o))), " · " + offerText(o), o.final ? h("span", { class: "mk-final" }, "final: true") : null)) : h("span", { class: "mk-muted" }, T("mercado.none_f"))),
        h("div", { class: "mk-next" }, h("span", { class: "mk-k" }, T("mercado.chat.next")), mv ? [h("span", { class: "mk-next-t" }, mv.txt), U().sourceTag ? U().sourceTag(mv.src) : h("span", { class: "mk-src" }, mv.src)] : h("span", { class: "mk-muted" }, T("mercado.dec.none")))));
    return card;
  }

  // final state on a live-grid card: "● en vivo" for open threads, else how it ended, at what price and when
  function threadEnd(t) {
    const msgs = arr(t.messages).slice().sort((a, b) => (a.tick || 0) - (b.tick || 0) || (a.id || 0) - (b.id || 0));
    const last = msgs[msgs.length - 1];
    const when = last ? tclock(last.tick) : t.last_change_tick != null ? tclock(t.last_change_tick) : "";
    if (!t.status || t.status === "open") return { cls: "is-live", text: T("mercado.end.live"), when };
    if (t.status === "deal") {
      const acc = msgs.filter((m) => m.offer && /accept|deal|settled|filled/.test(String(m.offer.status))).pop() || msgs.filter((m) => m.offer).pop();
      const p = acc ? offerCash(acc.offer) : null;
      return { cls: "is-deal", text: p != null ? T("mercado.end.deal_at", { price: fmtP(p) }) : T("mercado.end.deal"), when };
    }
    if (t.status === "walked") return { cls: "is-walked", text: T("mercado.end.walked"), when };
    if (t.status === "expired") return { cls: "is-closed", text: T("mercado.end.expired"), when };
    return { cls: "is-closed", text: T("mercado.end.closed"), when };
  }
  function markState(card, t) {
    const e = threadEnd(t);
    const st = card.querySelector(".mk-status");
    if (st) { st.textContent = e.text; st.className = "mk-status mk-end " + e.cls; st.after(h("span", { class: "mk-end-when mk-muted" }, e.when)); }
    if (e.cls !== "is-live") card.classList.add("is-ended");
    return card;
  }

  // an offer attached to a message, as a small card: what they give, what they want, price and status
  const OFFER_ST = { open: ["open", "ok"], cancelled: ["cancelled", "mute"], expired: ["expired", "mute"], accepted: ["accepted", "ok"], filled: ["accepted", "ok"], settled: ["accepted", "ok"], rejected: ["rejected", "bad"] };
  function sideTxt(s2) {
    const parts = [];
    if (s2 && s2.cash) parts.push(fmtP(s2.cash));
    for (const a of (s2 && s2.assets) || []) parts.push(a.ref || "#" + a.id);
    for (const t of (s2 && s2.types) || []) parts.push(String(t).replace(/^card:/, ""));
    return parts.join(" + ") || T("mercado.nothing");
  }
  function offerCard(o) {
    const known = OFFER_ST[o.status];
    const [stl, tone] = known ? [T("mercado.ost." + known[0]), known[1]] : [o.status || "—", "mute"];
    const kind = o.give && o.give.cash && !((o.give.assets || []).length + (o.give.types || []).length) ? "compra" : o.want && o.want.cash ? "venta" : "cambio";
    const c = h("div", { class: "mk-offer mk-t-" + kind }, typeChip(kind, T(kind === "compra" ? "mercado.ocard.buy" : kind === "venta" ? "mercado.ocard.sell" : "mercado.ocard.swap")),
      h("span", null, T("mercado.ocard.gives"), h("b", null, sideTxt(o.give))), h("span", null, T("mercado.ocard.wants"), h("b", null, sideTxt(o.want))),
      h("span", { class: "mk-grow" }), h("span", { class: "mk-muted mk-mono" }, "#" + o.id + (o.venue ? " · " + o.venue : "") + (o.expires_tick != null ? T("mercado.ocard.expires", { tick: tclock(o.expires_tick) }) : "")),
      h("span", { class: "tag res tone-" + tone }, stl));
    return c;
  }
  // one conversation with another team: who, where, when, how it stands, every message and its offer
  function teamCard(t) {
    const other = t.with === US ? t.team : t.with;
    const weOpened = t.team === US;
    const msgs = arr(t.messages).slice().sort((a, b) => (a.tick || 0) - (b.tick || 0) || (a.id || 0) - (b.id || 0));
    const e = threadEnd(t);
    const tp = t.topic || {};
    const about = t.item || (tp.buy && (tp.buy.card || tp.buy.pack)) || (tp.sell && (tp.sell.card || (tp.sell.assets || []).map((a) => "#" + a).join(", "))) || "";
    const card = h("article", { class: "mk-chat mk-team" + (e.cls === "is-live" ? "" : " is-ended") + (S.focusThread === t.id ? " is-focus" : "") },
      h("header", { class: "mk-chat-h" }, U().teamTag ? U().teamTag(other) : h("b", null, teamName(other)),
        h("span", { class: "mk-muted" }, T(weOpened ? "mercado.team.we_opened" : "mercado.team.they_wrote")),
        h("span", { class: "mk-grow" }), h("span", { class: "mk-status mk-end " + e.cls }, e.text), h("span", { class: "mk-end-when mk-muted" }, e.when)),
      h("div", { class: "mk-chat-sub" }, h("span", null, about ? (tp.buy ? T("mercado.team.want", { item: about }) : tp.sell ? T("mercado.team.offer", { item: about }) : about) : T("mercado.team.no_topic")),
        h("span", { class: "mk-muted" }, `#${t.id}` + (t.venue ? " · " + t.venue : "") + " · " + T(msgs.length === 1 ? "mercado.chat.msg_one" : "mercado.chat.msgs", { n: msgs.length }) + (t.closed_reason ? " · " + t.closed_reason : ""))),
      h("div", { class: "mk-msgs" }, msgs.length ? msgs.map((m) => {
        const us = m.sender === US;
        return h("div", { class: "mk-msg" + (us ? " is-us" : "") },
          h("div", { class: "mk-msg-h" }, h("span", null, us ? T("mercado.us") : teamName(m.sender)), h("b", null, ""), h("span", { class: "mk-muted", title: "tick " + m.tick }, tclock(m.tick))),
          h("div", { class: "mk-msg-t" }, String(m.text || "").replace(/<\/?untrusted[^>]*>/g, "")),
          m.offer ? offerCard(m.offer) : null);
      }) : stateBox("empty", T("mercado.chat.no_msgs_rec"))));
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
      h("div", { class: "mk-seg" }, ["todos", "nosotros"].map((s) => h("button", { class: f.scope === s ? "on" : "", onclick: () => { f.scope = s; renderSide(root, ctx); } }, T(s === "todos" ? "mercado.side.all" : "mercado.us")))),
      h("div", { class: "mk-seg" }, h("button", { class: "on" }, T("mercado.live")), h("button", { onclick: () => { location.hash = "#mercado/historial"; } }, T("mercado.history"))));
    let fb = side.querySelector(".mk-fb");
    if (!fb) {
      if (U().filterBar) {
        try {
          fb = U().filterBar({ types: TYPES, counts, team: true, search: true, onChange: (st) => { f.filter = st; renderSide(root, ctx); } });
        } catch (e) { fb = null; }
      }
      if (!fb) fb = h("div", null, h("input", { class: "mk-input", placeholder: T("mercado.search"), oninput: (ev) => { f.filter = { q: ev.target.value }; renderSide(root, ctx); } }));
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
    const tape = h("div", { class: "mk-tape" }, S.feedErr && !S.feed.length ? stateBox("error", S.feedErr) : shown.length ? shown.slice(0, 120).map(tapeRow) : stateBox("empty", T(S.feed.length ? "mercado.side.no_match" : "mercado.side.empty")));

    const offers = ctx.myOffers || [];
    const mine = offers.filter((o) => o.maker === US);
    const toUs = offers.filter((o) => o.to === US && o.maker !== US);
    const decs = ctx.decisions || [];
    const decFor = (o) => {
      const d = decs.filter((x) => x.offer === o.id || (Array.isArray(x.args) && x.args.includes(o.id))).pop();
      return d ? (d.action || "") + (d.why ? " · " + d.why : "") : T("mercado.dec.none_yet");
    };
    const offerRow = (o, dec) => h("div", { class: "mk-off mk-t-" + offerKind(o) },
      h("div", { class: "mk-tape-a" }, typeChip(offerKind(o)), h("span", null, offerText(o)), h("span", { class: "mk-grow" }),
        h("span", { class: "mk-muted" }, o.venue || (o.thread ? "chat #" + o.thread : o.to ? T("mercado.side.to", { team: teamName(o.to) }) : ""))),
      h("div", { class: "mk-tape-b" }, h("span", null, T("mercado.side.offer_line", { head: `#${o.id} · ${o.created_tick != null ? tclock(o.created_tick) + " · " : ""}`, status: OFFER_ST[o.status || "open"] ? T("mercado.ost." + OFFER_ST[o.status || "open"][0]) : o.status, left: ticksLeft(o, ctx.clock) })), o.final ? h("span", { class: "mk-final" }, "final") : null, dec ? h("span", { class: "mk-muted" }, T("mercado.side.bot", { dec })) : null));

    U().keepScroll(side, () => side.replaceChildren(seg, fb, tape,
      h("div", { class: "mk-sec" }, T("mercado.side.ours", { n: mine.length })),
      h("div", { class: "mk-offs" }, mine.length ? mine.map((o) => offerRow(o)) : stateBox("empty", T("mercado.side.ours_none"))),
      h("div", { class: "mk-sec" }, T("mercado.side.to_us", { n: toUs.length })),
      h("div", { class: "mk-offs" }, toUs.length ? toUs.map((o) => offerRow(o, decFor(o))) : stateBox("empty", T("mercado.side.to_us_none")))));
  }

  async function refreshLive(root, data) {
    const api = window.api;
    if (!api) throw new Error(T("mercado.no_api"));
    const [threads, decisions, myOffers, clock, dealers, lb] = await Promise.all([
      safe(() => api.recThreads()), safe(() => api.decisions()), safe(() => api.rec("my_offers")),
      safe(() => api.rec("clock")), safe(() => api.rec("dealers")), safe(() => api.rec("leaderboard")),
    ]);
    const feedRes = await safe(pullFeedTail);
    S.feedErr = feedRes.ok ? null : feedRes.err;
    if (lb.ok) for (const r of arr(lb.v.data || lb.v)) if (r && (r.team || r.id)) NAMES[r.team || r.id] = r.name;
    const dealerNames = {};
    if (dealers.ok) for (const p of arr(dealers.v.personas || dealers.v)) if (p && p.id) dealerNames[p.id] = p.name;
    const decs = decisions.ok ? arr(decisions.v).map(normDec) : [];
    const ctx = { myOffers: myOffers.ok ? arr(myOffers.v.offers || myOffers.v) : [], clock: clock.ok ? clock.v : null, decisions: decs };

    const chatsHost = root.querySelector(".mk-chats");
    const head = root.querySelector(".mk-head-sub");
    if (!threads.ok) {
      chatsHost.replaceChildren(stateBox("error", threads.err));
    } else {
      // The live grid never looks empty: open conversations first, then the most recent finished ones up to 6.
      const all = arr(threads.v.items || threads.v);
      const open = all.filter((t) => !t.status || t.status === "open");
      const act = (t) => num(t.updated) || (U().tickWall && U().tickWall(t.last_change_tick)) || num(t.last_change_tick) || 0;
      const recent = all.filter((t) => t.status && t.status !== "open").sort((a, b) => act(b) - act(a)).slice(0, Math.max(0, 6 - open.length));
      S.thCache = S.thCache || {};
      const detail = async (t, cache) => {
        const c = S.thCache[t.id];
        if (cache && c && c.n === t.message_count && c.st === t.status) return c.v;
        const d = await safe(() => api.recThread(t.id));
        const v = d.ok ? { ...t, ...(d.v.thread || d.v) } : t;
        if (cache && d.ok) S.thCache[t.id] = { n: t.message_count, st: t.status, v };
        return v;
      };
      const full = (await Promise.all(open.map((t) => detail(t, false)))).concat(await Promise.all(recent.map((t) => detail(t, true))));
      const nd = open.filter((t) => t.kind !== "team").length;
      if (head) head.textContent = open.length
        ? T("mercado.head.open", { open: open.length, dealers: nd, teams: open.length - nd }) + (recent.length ? T("mercado.head.recent", { n: recent.length }) : "")
        : T("mercado.head.none_open", { n: recent.length });
      U().keyedList(chatsHost, full, {
        key: (t) => t.id,
        sig: (t) => JSON.stringify([lang(), arr(t.messages).length, t.status, arr(t.messages).map((m) => m.offer && m.offer.status), arr(t.standing_offers).map((o) => [o.id, o.status]), decisionsFor(decs, t).length]),
        render: (t) => markState(renderChat(t, decs, dealerNames), t), inner: ".mk-msgs", stickEnd: true,
        tail: full.length ? [] : [stateBox("empty", T("mercado.head.no_conv"))] });
      // conversations with other teams: always their own block (open first, then the latest ones)
      const teamsAll = all.filter((t) => t.kind === "team" || /^t\d+$/.test(String(t.with === US ? t.team : t.with)));
      const tOpen = teamsAll.filter((t) => !t.status || t.status === "open").sort((a, b) => act(b) - act(a));
      const tRest = teamsAll.filter((t) => t.status && t.status !== "open").sort((a, b) => act(b) - act(a) || b.id - a.id);
      const tShow = tOpen.concat(tRest.slice(0, Math.max(8 - tOpen.length, 0)));
      if (S.focusThread != null && !tShow.some((t) => t.id === S.focusThread)) { const ft = teamsAll.find((t) => t.id === S.focusThread); if (ft) tShow.push(ft); }
      const tFull = await Promise.all(tShow.map((t) => detail(t, !(!t.status || t.status === "open"))));
      const tHost = root.querySelector(".mk-teams-list");
      root.querySelector(".mk-teams-sub").textContent = T("mercado.teams.sub", { open: tOpen.length, total: teamsAll.length }) + (teamsAll.length > tShow.length ? T("mercado.teams.showing", { n: tShow.length }) : "");
      U().keyedList(tHost, tFull, { key: (t) => "tm" + t.id,
        sig: (t) => JSON.stringify([lang(), arr(t.messages).length, t.status, arr(t.messages).map((m) => m.offer && m.offer.status), S.focusThread === t.id]),
        render: teamCard, inner: ".mk-msgs",
        tail: [tFull.length ? null : stateBox("empty", T("mercado.teams.none")),
          teamsAll.length > tShow.length ? h("a", { class: "mk-btn mk-more", href: "#mercado/conversaciones" }, T("mercado.teams.more", { n: teamsAll.length })) : null] });
      if (S.focusThread != null) { const n = tHost.querySelector('[data-key="tm' + S.focusThread + '"]'); if (n && !S.focusDone) { n.scrollIntoView({ block: "center" }); S.focusDone = true; } }
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
    const head = T("mercado.csv.head").split(",");
    const lines = [head.join(",")];
    for (const e of rows) lines.push([e.seq, e.ts ? new Date(e.ts * 1000).toISOString() : "", e.tick, e.type, e.raw, e.team, [...e.teams].join(" "), e.text, e.venue, e.price, e.refs.join(" "), e.us ? T("mercado.csv.yes") : ""].map(csvCell).join(","));
    return lines.join("\n");
  }
  function renderHistory(root) {
    const host = root.querySelector(".mk-hist");
    if (!host) return;
    const H = S.hist, f = H.f;
    if (!H.rows.length) {
      host.querySelector(".mk-hist-table").replaceChildren(H.err ? stateBox("error", H.err) : H.loading || !H.done ? stateBox("loading") : stateBox("empty", T("mercado.hist.none")));
      return;
    }
    // populate selects once
    const teamSel = host.querySelector("[data-f=team]"), venueSel = host.querySelector("[data-f=venue]");
    const teams = new Set(), venues = new Set();
    for (const e of H.rows) { e.teams.forEach((t) => teams.add(t)); if (e.venue) venues.add(e.venue); }
    const fill = (sel, vals, label) => {
      if (sel.options.length - 1 === vals.length) return;
      const cur = sel.value;
      sel.replaceChildren(h("option", { value: "" }, label), ...vals.map((v) => h("option", { value: v }, v === US ? T("mercado.hist.us_t10") : v)));
      sel.value = cur;
    };
    fill(teamSel, [...teams].sort(), T("mercado.hist.f_team"));
    fill(venueSel, [...venues].sort(), T("mercado.hist.f_venue"));

    const rows = histFiltered();
    const per = 50, pages = Math.max(1, Math.ceil(rows.length / per));
    H.page = Math.min(H.page, pages - 1);
    const slice = rows.slice(H.page * per, H.page * per + per);
    const usRows = rows.filter((e) => e.us);
    const usVol = usRows.reduce((a, e) => a + (e.price || 0), 0);
    host.querySelector(".mk-hist-sum").textContent = T("mercado.hist.sum", { n: rows.length, total: H.rows.length, us: usRows.length, vol: fmtP(usVol) }) + (H.loading ? T("mercado.hist.sum_loading") : "");
    const table = h("table", { class: "mk-table" },
      h("thead", null, h("tr", null, T("mercado.hist.cols").split(",").map((x) => h("th", null, x)))),
      h("tbody", null, slice.map((e) => h("tr", { class: "mk-t-" + e.type + (e.us ? " is-us" : "") },
        h("td", { class: "mk-mono" }, fmtTs(e.ts, true)), h("td", { class: "mk-mono" }, e.tick != null ? "t" + e.tick : ""),
        h("td", null, typeChip(e.type, e.label)), h("td", null, teamTag(e.team)),
        h("td", { class: "mk-det" }, e.text), h("td", { class: "mk-mono" }, e.venue), h("td", { class: "mk-mono mk-r" }, e.price != null ? fmtP(e.price) : "")))));
    const tHost = host.querySelector(".mk-hist-table");
    U().keepScroll(tHost, () => tHost.replaceChildren(slice.length ? table : stateBox("empty", T("mercado.hist.no_match"))));
    // pager
    const pg = host.querySelector(".mk-pager");
    const btn = (label, p, on) => h("button", { class: on ? "on" : "", disabled: p < 0 || p >= pages ? "disabled" : null, onclick: () => { H.page = p; renderHistory(root); } }, label);
    const nums = new Set([0, pages - 1, H.page - 1, H.page, H.page + 1].filter((p) => p >= 0 && p < pages));
    const list = [...nums].sort((a, b) => a - b);
    const parts = [btn("‹", H.page - 1)];
    list.forEach((p, i) => { if (i && p - list[i - 1] > 1) parts.push(h("span", null, "…")); parts.push(btn(String(p + 1), p, p === H.page)); });
    parts.push(btn("›", H.page + 1));
    pg.replaceChildren(h("span", { class: "mk-muted" }, T("mercado.hist.range", { from: rows.length ? H.page * per + 1 : 0, to: Math.min(rows.length, (H.page + 1) * per), n: rows.length })), h("span", { class: "mk-grow" }), ...parts);
    // export
    const csv = toCSV(rows);
    const a = host.querySelector(".mk-export");
    a.setAttribute("href", "data:text/csv;charset=utf-8," + encodeURIComponent("﻿" + csv));
    a.setAttribute("download", "bazaar-historial.csv");
    S.hist.csv = csv;
  }
  // ---------- historial: every conversation we had, full transcripts ----------
  const TH_STATUS = lazy({ deal: "mercado.th.deal", closed: "mercado.th.closed", open: "mercado.th.open", expired: "mercado.th.expired" });
  async function pullConversations() {
    const api = window.api, C = S.conv;
    if (Date.now() - C.at < 4000 && C.list.length && C.at > (window.__dashForceAt || 0)) return;
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
    root.querySelector(".mk-conv-sum").textContent = T("mercado.conv.sum", { n: rows.length, total: C.list.length,
      parts: Object.entries(counts).map(([k, v]) => `${v} ${TH_STATUS[k] || k}`).join(" · ") });
    const shown = rows.slice(0, C.limit);
    const decs = S.conv.decs || [];
    const render = (t) => {
      const c = C.cache[t.id];
      const card = renderChat(c ? c.data : t, decs, dealerNames, { full: true });
      card.classList.add("mk-chat-hist", "mk-st-" + (t.status || "open"));
      const st = card.querySelector(".mk-status"); if (st) st.textContent = TH_STATUS[t.status] || t.status || "";
      return card;
    };
    // a card is only rebuilt when its transcript, status or bot decisions change, so scrolling survives the refresh
    U().keyedList(host, shown, {
      key: (t) => t.id,
      sig: (t) => { const c = C.cache[t.id]; return [c ? c.count : "-", t.status, decisionsFor(decs, c ? c.data : t).length].join("|"); },
      render, inner: ".mk-msgs",
      tail: [shown.length ? null : stateBox("empty", T("mercado.conv.no_match")),
        rows.length > C.limit ? h("button", { class: "mk-btn mk-more", onclick: () => { C.limit += 24; C.at = 0; window.Screens.mercado.refresh(root, null, "historial"); } }, T("mercado.conv.more", { n: rows.length - C.limit })) : null] });
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
      ev.target.textContent = T(ok ? "mercado.hist.copied" : "mercado.hist.copy_fail"); setTimeout(() => { ev.target.textContent = T("mercado.hist.copy"); }, 1800);
    } }, T("mercado.hist.copy"));
    root.replaceChildren(h("div", { class: "scr-mercado is-hist" },
      h("div", { class: "mk-head" }, h("h1", null, T("mercado.hist.title")), h("span", { class: "mk-muted" }, T(S.hist.view === "conv" ? "mercado.hist.sub_conv" : "mercado.hist.sub_events")),
        h("span", { class: "mk-grow" }),
        h("div", { class: "mk-seg mk-histview" }, ["conv", "eventos"].map((v) => h("button", { class: S.hist.view === v ? "on" : "", "data-v": v, onclick: () => { S.hist.view = v; mountHistory(root); window.Screens.mercado.refresh(root, null, "historial"); } }, T(v === "eventos" ? "mercado.hist.events" : "mercado.hist.convs")))),
        h("div", { class: "mk-seg" }, h("button", { onclick: () => { location.hash = "#mercado"; } }, T("mercado.live")), h("button", { class: "on" }, T("mercado.history")))),
      S.hist.view === "conv" ? h("div", { class: "mk-conv" },
        h("div", { class: "mk-hfilters" },
          h("select", { class: "mk-input", onchange: (ev) => { S.conv.f.kind = ev.target.value; S.conv.at = 0; window.Screens.mercado.refresh(root, null, "historial"); } },
            [["", T("mercado.conv.f_with")], ["dealer", T("mercado.conv.f_dealers")], ["equipo", T("mercado.conv.f_teams")]].map(([v, l]) => h("option", { value: v, selected: S.conv.f.kind === v ? "selected" : null }, l))),
          h("select", { class: "mk-input", onchange: (ev) => { S.conv.f.status = ev.target.value; S.conv.at = 0; window.Screens.mercado.refresh(root, null, "historial"); } },
            [["", T("mercado.conv.f_status")], ["deal", T("mercado.conv.f_deal")], ["closed", T("mercado.conv.f_closed")], ["open", T("mercado.conv.f_open")]].map(([v, l]) => h("option", { value: v, selected: S.conv.f.status === v ? "selected" : null }, l))),
          h("input", { class: "mk-input mk-q", placeholder: T("mercado.conv.search"), value: S.conv.f.q, oninput: (ev) => { S.conv.f.q = ev.target.value; S.conv.at = 0; renderConversations(root, DEALER_NAMES); } })),
        h("div", { class: "mk-conv-sum mk-muted" }),
        h("div", { class: "mk-conv-list" }, stateBox("loading"))) :
      h("div", { class: "mk-hist" },
        h("div", { class: "mk-hfilters" },
          h("select", { class: "mk-input", onchange: upd("type") }, h("option", { value: "" }, T("mercado.hist.f_type")), TYPES.map((t) => h("option", { value: t }, TYPE_LABEL[t]))),
          h("select", { class: "mk-input", "data-f": "team", onchange: upd("team") }, h("option", { value: "" }, T("mercado.hist.f_team"))),
          h("input", { class: "mk-input", placeholder: T("mercado.hist.f_card"), oninput: upd("card") }),
          h("select", { class: "mk-input", "data-f": "venue", onchange: upd("venue") }, h("option", { value: "" }, T("mercado.hist.f_venue"))),
          h("label", { class: "mk-muted" }, T("mercado.hist.f_from"), h("input", { class: "mk-input", type: "datetime-local", onchange: upd("from") })),
          h("label", { class: "mk-muted" }, T("mercado.hist.f_to"), h("input", { class: "mk-input", type: "datetime-local", onchange: upd("to") })),
          h("label", { class: "mk-muted" }, h("input", { type: "checkbox", onchange: upd("us") }), T("mercado.hist.f_us")),
          h("input", { class: "mk-input mk-q", placeholder: T("mercado.hist.f_text"), oninput: upd("q") }),
          h("span", { class: "mk-grow" }),
          h("a", { class: "mk-btn mk-export", href: "#", download: "bazaar-historial.csv" }, T("mercado.hist.export")), copyBtn),
        h("div", { class: "mk-hist-sum mk-muted" }),
        h("div", { class: "mk-hist-table" }, stateBox("loading")),
        h("div", { class: "mk-pager" }))));
  }

  // ---------- hablar con un dealer (a human's own thread; the bot leaves it alone) ----------
  const TALK = { dealer: "banco", st: null, busy: false, err: null, sig: "" };
  function sideText(side) {
    const parts = [];
    if (side && side.cash) parts.push(fmtP(side.cash));
    for (const t of arr(side && side.types)) parts.push(String(t).replace(/^card:|^pack:/, ""));
    for (const a of arr(side && side.assets)) parts.push(a && a.ref ? a.ref : "#" + (a && a.id != null ? a.id : a));
    return parts.join(" + ") || T("mercado.nothing");
  }
  function talkCheck(c) {
    if (!c) return h("span", { class: "mk-muted" }, T("mercado.none_f"));
    return [h("span", null, T("mercado.talk.we_get"), h("b", null, sideText({ cash: c.receive_cash, types: c.we_get })), T("mercado.talk.we_give"), h("b", null, sideText({ cash: c.pay, types: c.we_give }))),
      h("span", { class: "mk-talk-val" }, T("mercado.talk.value", { get: c.known ? fmtP(c.value_get) : T("mercado.talk.unknown"), give: fmtP(c.value_give) })),
      h("b", { class: "mk-talk-gain " + (c.gain >= 0 && c.known ? "is-up" : "is-down") }, c.known ? (c.gain >= 0 ? "+" : "") + fmtP(c.gain) : "?"),
      c.final ? h("span", { class: "mk-final" }, "final: true") : null,
      c.blocked ? h("span", { class: "mk-talk-block" }, T("mercado.talk.blocked", { why: c.blocked })) : null];
  }
  function renderTalk(root) {
    const box = root.querySelector(".mk-talk");
    if (!box) return;
    const st = TALK.st, th = st && st.thread;
    const sel = box.querySelector(".mk-talk-dealer");
    if (st && sel && sel.options.length !== arr(st.dealers).length) {
      sel.replaceChildren(...arr(st.dealers).map((d) => h("option", { value: d.id, selected: d.id === TALK.dealer ? "selected" : null },
        T(d.unlocked ? "mercado.talk.dealer_opt" : "mercado.talk.dealer_locked", { name: d.name, level: d.level }))));
    }
    const cards = box.querySelector("#mk-talk-items");
    if (st && cards && !cards.children.length) {
      const d = arr(st.dealers).find((x) => x.id === TALK.dealer);
      const packs = arr(d && d.menu && d.menu.sells).filter((x) => x.pack).map((x) => x.pack);
      cards.replaceChildren(...packs.concat(arr(st.cards).map((c) => c.ref)).map((v) => h("option", { value: v })));
    }
    box.querySelector(".mk-talk-sub").textContent = TALK.err ? T("mercado.error", { err: TALK.err }) : !st ? T("mercado.loading_lc") :
      T(th ? (th.manual ? "mercado.talk.sub_manual" : "mercado.talk.sub_bot") : "mercado.talk.sub_none", { cash: fmtP(st.cash), id: th && th.id });
    const sig = JSON.stringify([lang(), th && th.id, th && arr(th.messages).map((m) => [m.id, m.offer && m.offer.status]), st && st.check]);
    if (sig !== TALK.sig) {
      TALK.sig = sig;
      const msgs = box.querySelector(".mk-msgs");
      const atEnd = msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight < 40;
      msgs.replaceChildren(...(th && arr(th.messages).length ? arr(th.messages).map((m) => {
        const us = m.sender === US;
        return h("div", { class: "mk-msg" + (us ? " is-us" : "") + (m.offer && m.offer.final ? " is-final" : "") },
          h("div", { class: "mk-msg-h" }, h("span", null, us ? T("mercado.us") : DEALER_NAMES[m.sender] || m.sender),
            h("b", null, m.offer ? T("mercado.talk.give_for_want", { give: sideText(m.offer.give), want: sideText(m.offer.want) }) : ""),
            h("span", { class: "mk-muted" }, tclock(m.tick) + (m.offer && m.offer.status && m.offer.status !== "open" ? " · " + m.offer.status : ""))),
          h("div", { class: "mk-msg-t" }, m.text || ""));
      }) : [stateBox("empty", T(th ? "mercado.chat.no_msgs" : "mercado.talk.start"))]));
      if (atEnd) msgs.scrollTop = msgs.scrollHeight;
      box.querySelector(".mk-talk-standing").replaceChildren(h("span", { class: "mk-k" }, T("mercado.talk.standing")), ...[talkCheck(st && st.check)].flat());
    }
    const open = !!th;
    for (const n of box.querySelectorAll(".mk-talk-open")) n.disabled = open;
    box.querySelector(".mk-talk-accept").disabled = TALK.busy || !(st && st.check) || !!(st.check && st.check.blocked);
    box.querySelector(".mk-talk-close").disabled = TALK.busy || !open;
    box.querySelector(".mk-talk-release").disabled = TALK.busy || !(open && th.manual);
    box.querySelector(".mk-talk-send").disabled = TALK.busy;
  }
  async function pullTalk(root, force) {
    if (!root.querySelector(".mk-talk") || !window.api.dealerChat) return;
    if (!force && Date.now() - (TALK.at || 0) < 5000) return;      // each pull reads the game: every 5 s is enough
    TALK.at = Date.now();
    const r = await safe(() => window.api.dealerChat(TALK.dealer));
    if (r.ok) { TALK.st = r.v; TALK.err = null; for (const d of arr(r.v.dealers)) DEALER_NAMES[d.id] = d.name; }
    else TALK.err = r.err && r.err.message ? r.err.message : String(r.err);
    renderTalk(root);
  }
  async function talkDo(root, what, body, okText) {
    if (TALK.busy) return null;
    TALK.busy = true; renderTalk(root);
    let out = null;
    try {
      out = await window.api.dealerChatDo(what, Object.assign({ dealer: TALK.dealer }, body));
      if (okText && U().toast) U().toast({ type: "dealer", title: okText });
    } catch (e) {
      if (U().toast) U().toast({ type: "error", title: "Dealer", text: e.message || String(e) });
    }
    TALK.busy = false;
    await pullTalk(root, true);
    return out;
  }
  function talkPanel(root) {
    const text = h("textarea", { class: "mk-input mk-talk-text", rows: "2", placeholder: T("mercado.talk.ph_text") });
    const side = h("select", { class: "mk-input mk-talk-open mk-talk-side" }, [["buy", T("mercado.talk.buy")], ["sell", T("mercado.talk.sell")]].map(([v, l]) => h("option", { value: v }, l)));
    const item = h("input", { class: "mk-input mk-talk-open mk-talk-item", list: "mk-talk-items", placeholder: T("mercado.talk.ph_item") });
    const price = h("input", { class: "mk-input mk-talk-price", type: "number", min: "1", step: "1", placeholder: T("mercado.talk.ph_price") });
    const send = async () => {
      const p = price.value === "" ? null : +price.value;
      if (!text.value.trim() && p == null) return;
      const out = await talkDo(root, "send", { text: text.value, price: p, side: side.value, item: item.value.trim() });
      if (out) { text.value = ""; price.value = ""; }
    };
    text.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); } });
    const accept = async () => {
      const st = TALK.st;
      if (!st || !st.standing) return;
      const pre = await talkDo(root, "accept", { offer: st.standing.id });
      const c = pre && pre.check;
      if (!pre || !pre.needs_confirm || !c) { if (c && c.blocked && U().toast) U().toast({ type: "error", title: T("mercado.talk.not_accepted"), text: c.blocked }); return; }
      const msg = T("mercado.talk.confirm_msg", { get: sideText({ cash: c.receive_cash, types: c.we_get }), vget: fmtP(c.value_get), give: sideText({ cash: c.pay, types: c.we_give }), vgive: fmtP(c.value_give),
        gain: (c.gain >= 0 ? "+" : "") + fmtP(c.gain), from: fmtP(c.cash), to: fmtP(c.cash - c.pay + c.receive_cash) });
      const ok = U().confirm ? await U().confirm({ title: T("mercado.talk.confirm_title"), text: msg, confirmLabel: T("mercado.talk.confirm_ok") }) : window.confirm(msg);
      if (ok) await talkDo(root, "accept", { offer: st.standing.id, confirm: true }, T("mercado.talk.accepted"));
    };
    const closeIt = async () => {
      const th = TALK.st && TALK.st.thread;
      if (!th) return;
      const ok = U().confirm ? await U().confirm({ title: T("mercado.talk.close_title"), text: T("mercado.talk.close_text"), confirmLabel: T("mercado.talk.close"), danger: true }) : true;
      if (ok) await talkDo(root, "close", { thread: th.id }, T("mercado.talk.closed"));
    };
    TALK.sig = ""; TALK.at = 0;
    return h("section", { class: "mk-talk" },
      h("div", { class: "mk-head mk-teams-h" }, h("h2", null, T("mercado.talk.title")),
        h("select", { class: "mk-input mk-talk-dealer", onchange: (e) => { TALK.dealer = e.target.value; TALK.st = null; TALK.sig = ""; const dl = root.querySelector("#mk-talk-items"); if (dl) dl.replaceChildren(); pullTalk(root, true); } },
          h("option", { value: "banco" }, "Don Ernesto")),
        h("span", { class: "mk-muted mk-talk-sub" }, T("mercado.loading_lc"))),
      h("div", { class: "mk-talk-box" },
        h("div", { class: "mk-msgs" }, stateBox("loading")),
        h("div", { class: "mk-standing mk-talk-standing" }, h("span", { class: "mk-k" }, T("mercado.talk.standing"))),
        h("div", { class: "mk-talk-form" },
          h("div", { class: "mk-talk-row" }, side, item, price, h("datalist", { id: "mk-talk-items" }),
            h("span", { class: "mk-muted mk-talk-hint" }, T("mercado.talk.hint"))),
          text,
          h("div", { class: "mk-talk-row" },
            h("button", { type: "button", class: "mk-btn mk-talk-send", onclick: send }, T("mercado.talk.send")),
            h("button", { type: "button", class: "mk-btn mk-talk-accept", onclick: accept }, T("mercado.talk.accept")),
            h("span", { class: "mk-grow" }),
            h("button", { type: "button", class: "mk-btn mk-talk-release", title: T("mercado.talk.release_tip"), onclick: () => { const th = TALK.st && TALK.st.thread; if (th) talkDo(root, "release", { thread: th.id }, T("mercado.talk.released")); } }, T("mercado.talk.release")),
            h("button", { type: "button", class: "mk-btn mk-talk-close", onclick: closeIt }, T("mercado.talk.close"))))));
  }

  // ---------- screen ----------
  function mountLive(root) {
    root.replaceChildren(h("div", { class: "scr-mercado" },
      h("div", { class: "mk-main" },
        h("div", { class: "mk-head" }, h("h1", null, T("mercado.title")), h("span", { class: "mk-muted mk-head-sub" }, "")),
        h("section", { class: "mk-teams" },
          h("div", { class: "mk-head mk-teams-h" }, h("h2", null, T("mercado.head.teams")), h("span", { class: "mk-muted mk-teams-sub" }, "")),
          h("div", { class: "mk-teams-list" }, stateBox("loading"))),
        talkPanel(root),
        h("div", { class: "mk-head mk-teams-h mk-dealers-h" }, h("h2", null, T("mercado.head.dealers"))),
        h("div", { class: "mk-chats" }, stateBox("loading"))),
      h("aside", { class: "mk-side" }, stateBox("loading"))));
  }

  window.Screens = window.Screens || {};
  window.Screens["mercado"] = {
    get title() { return T("mercado.title"); },
    mount(root, params) {
      // the history rows carry their texts: read them again when the language changes
      if (S.lang && S.lang !== lang()) { S.hist.rows = []; S.hist.lastSeq = 0; S.hist.done = false; }
      S.lang = lang();
      S.mode = params === "historial" || params === "conversaciones" || params === "eventos" ? "hist" : "live";
      const fm = /^hilo-(\d+)$/.exec(params || ""); S.focusThread = fm ? +fm[1] : null; S.focusDone = false;
      if (params === "conversaciones") S.hist.view = "conv";
      if (params === "eventos") S.hist.view = "eventos";
      S.live.filter = null;
      if (S.mode === "hist") mountHistory(root); else mountLive(root);
    },
    async refresh(root, data, params) {
      const mode = params === "historial" || params === "conversaciones" || params === "eventos" ? "hist" : "live";
      if (mode !== S.mode || S.lang !== lang()) { this.mount(root, params); }
      try {
        if (S.mode === "hist" && S.hist.view === "conv") {
          if (!Object.keys(DEALER_NAMES).length) { const d = await safe(() => window.api.rec("dealers")); if (d.ok) for (const p of arr(d.v.personas || d.v)) if (p && p.id) DEALER_NAMES[p.id] = p.name; }
          const dr = await safe(() => window.api.decisions());
          if (dr.ok) S.conv.decs = arr(dr.v).map(normDec);
          await pullConversations(); renderConversations(root, DEALER_NAMES);
        } else if (S.mode === "hist") { await pullHistory(); renderHistory(root); }
        else { pullTalk(root); await refreshLive(root, data); }
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
