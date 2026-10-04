// activity: the whole market as it happens. The latest matches drawn as cards, then every item of the floor
// (agents talking, matches moving, offers and deals of the game), newest first. New rows come in at the top
// without redrawing the rest, so nothing flickers and the reader keeps their place.
Plaza.screen("activity", {
  title: "nav.activity",
  render(root, ctx) {
    const { el } = K;
    const KEEP = 120;
    const TONE = { proposed: null, offer_on_v07: "signal", accepted: "signal", settled: "ok", passed: "bad", expired: "warn", settled_elsewhere: "bad" };
    const me = ctx.me ? ctx.me.team : null;
    const S = { items: [], seen: new Set(), filter: "all", cat: {}, colors: {}, matches: null, stale: false, got: false, last: null };
    const sig = {};
    const status = () => Plaza.state.status || ctx.status || {};

    const FILTERS = ["all", "trades", "agents"].concat(me ? ["mine"] : []);
    const tabs = el("div", { class: "activity-tabs", role: "group", "aria-label": t("activity.filter") });
    root.appendChild(el("header", { class: "page-head" },
      el("div", { class: "activity-title" }, el("h1", { class: "page-title" }, t("nav.activity")), el("p", { class: "page-sub" }, t("activity.sub"))), tabs));
    root.appendChild(K.endpoint("GET /plaza/api/floor/stream", "GET /plaza/api/floor?since=<seq>", "GET /plaza/api/matches"));
    const dom = { warn: root.appendChild(el("div", { class: "activity-warn" })), strip: root.appendChild(el("div", { class: "activity-strip" })) };
    const list = el("div", { class: "activity-list" });
    dom.body = el("div", { class: "activity-body" }, K.state("loading"));
    const note = root.appendChild(K.panel({ title: t("activity.talking"), note: t("activity.newest"), flush: true, class: "activity-panel" }, dom.body)).querySelector(".panel-note");

    function drawTabs() {
      K.clear(tabs);
      K.add(tabs, FILTERS.map((f) => el("button", { type: "button", class: S.filter === f ? "active" : null, "aria-pressed": String(S.filter === f),
                                                    onclick: () => { S.filter = f; drawTabs(); drawList(); } }, t("activity.f." + f))));
    }

    /** A card from its ref: the catalog of /api/market when it has it, else the set's colour and the official art. */
    function card(ref) {
      if (!ref) return null;
      const c = S.cat[ref];
      return c || { ref, name: ref, rarity: "common", color: S.colors[String(ref).slice(0, 3)] || "#5c6b73", art: "/plaza/art/" + ref + ".svg" };
    }
    const cardName = (ref) => { const c = S.cat[ref]; return c && c.name ? c.name : ref; };
    const owns = (ref) => !me || Boolean(Plaza.state.me && (Plaza.state.me.owned || []).includes(ref));   // a visitor sees every card in colour
    const who = (x) => (/^t\d\d$/.test(String(x || "")) ? K.teamName(x) : String(x || "–"));
    const venue = (v) => (v === "rastro" ? "El Rastro" : v || "–");

    /** One floor item as { tone, text, quote } : a sentence of ours, and what the agent wrote, if anything. */
    function say(it) {
      const p = typeof it.price === "number" ? K.price(it.price) : null, c = it.ref ? cardName(it.ref) : null, v = { team: who(it.team), to: who(it.to), card: c, price: p, venue: venue(it.venue) };
      if (it.src === "agent") {
        const key = it.kind === "want" ? (p ? "wantAt" : "want") : it.kind === "offer" ? (p ? "sellAt" : "sell") : it.kind === "accept" ? (it.to ? "acceptTo" : "accept") : null;
        return { tone: it.kind === "want" ? "get" : it.kind === "offer" ? "give" : null, text: key && c ? t("activity.a." + key, v) : null, quote: it.text };
      }
      if (it.src === "plaza") {
        if (it.kind === "match") return { tone: it.state === "settled" ? "ok" : null, text: t("activity.m." + (it.state in TONE ? it.state : "proposed"), v), chip: it.state };
        const key = it.kind === "counter" ? (p ? "counterAt" : "counter") : it.kind === "accept" ? "accept" : it.kind === "pass" ? "pass" : "note";
        return { tone: null, text: t("activity.t." + key, v), quote: it.text };
      }
      if (it.kind === "offer") return { tone: it.side === "bid" ? "get" : "give", text: t("activity.g." + (it.side === "bid" ? "bid" : "ask") + (it.to ? "To" : ""), v) };
      if (it.kind === "deal") return { tone: "ok", text: it.dealer ? t("activity.g.dealer", { ...v, dealer: it.dealer }) : t("activity.g.deal", v) };
      if (it.kind === "announce") return { tone: null, text: t("activity.g.announce", v), quote: it.text };
      if (it.kind === "pack") return { tone: null, text: t("activity.g.pack", v) };
      if (it.kind === "craft") return { tone: null, text: t("activity.g.craft", { ...v, card: it.text || c || "" }) };
      return { tone: null, text: it.text || it.kind || "" };
    }
    function passes(it) {
      if (S.filter === "trades") return (it.src === "plaza" && it.kind === "match") || it.kind === "deal" || (it.kind === "offer" && it.src === "game" && it.venue === "v07");
      if (S.filter === "agents") return it.src === "agent" || (it.src === "plaza" && it.kind !== "match");
      if (S.filter === "mine") return it.team === me || it.to === me;
      return true;
    }
    function row(it) {
      const s = say(it), c = card(it.ref);
      const src = it.src === "game" ? (it.venue ? venue(it.venue) : t("activity.src.game")) : it.src === "plaza" ? "v07" : t("activity.src.agent");
      return el("div", { class: "activity-row" + (it.highlight ? " is-high" : "") + (it.team === me || it.to === me ? " is-mine" : ""), dataset: { seq: String(it.seq) } },
        el("span", { class: "activity-tag" }, K.icon(it.src === "game" ? "market" : "agent", 12), String(it.team || "–")),
        el("span", { class: "activity-dir" + (s.tone ? " tone-" + s.tone : "") }, s.tone === "give" ? K.icon("give", 14) : s.tone === "get" ? K.icon("get", 14) : s.tone === "ok" ? K.icon("check", 14) : null),
        c ? K.card(c, { owned: owns(c.ref), size: "sm", href: "/plaza/card/" + c.ref }) : el("span", { class: "activity-nocard" }),
        el("div", { class: "activity-text" }, s.quote ? el("div", { class: "activity-quote" }, s.quote) : null, s.text ? el("div", { class: s.quote ? "activity-what" : "activity-main" }, s.text) : null),
        el("div", { class: "activity-meta" }, s.chip ? K.chip(t("state." + s.chip), TONE[s.chip]) : null,
          it.match ? (me ? K.link("/plaza/offers/" + it.match, { class: "id" }, it.match) : K.id(it.match)) : null,
          typeof it.offer === "number" ? K.id("#" + it.offer) : null, K.id(src), it.ref ? K.id(it.ref) : null, K.id(K.tick(it.tick))));
    }

    function drawList() {
      const shown = S.items.filter(passes);
      K.clear(list);
      K.add(list, shown.map(row));
      K.clear(dom.body);
      if (shown.length) dom.body.appendChild(list);
      else dom.body.appendChild(!S.got ? (S.stale ? K.state("error", null, t("activity.error")) : K.state("loading")) : K.state("empty", t("activity.empty"), t("activity.emptyText")));
      note.textContent = t("activity.newest") + (S.items.length ? " · " + t("activity.shown", { n: shown.length }) : "");
    }

    /** New items go in at the top; the page keeps its place when the reader has scrolled down. */
    let pending = [], raf = 0;
    function flush() {
      raf = 0;
      const fresh = pending; pending = [];
      if (!fresh.length) return;
      S.got = true;
      fresh.sort((a, b) => (a.seq || 0) - (b.seq || 0));
      const main = document.getElementById("main"), wasEmpty = !list.isConnected, before = list.offsetHeight;
      fresh.forEach((it) => {
        S.items.unshift(it);
        if (!wasEmpty && passes(it)) list.insertBefore(row(it), list.firstChild);
      });
      if (S.items.length > KEEP) {
        S.items.splice(KEEP).forEach((old) => S.seen.delete(old.seq));
        while (list.children.length > KEEP) list.removeChild(list.lastChild);
      }
      S.last = S.items[0];
      if (wasEmpty) drawList();
      else {
        note.textContent = t("activity.newest") + " · " + t("activity.shown", { n: list.children.length });
        if (main && main.scrollTop > list.offsetTop) main.scrollTop += list.offsetHeight - before;
      }
      drawStrip();
    }
    function onItem(it) {
      if (!it || typeof it.seq !== "number" || S.seen.has(it.seq)) return;
      S.seen.add(it.seq);
      pending.push(it);
      if (!raf) raf = requestAnimationFrame(flush);
    }

    /** The latest matches of the market, one card each: who, what, at how much, and where it stands. */
    function drawStrip() {
      const byId = {};
      ((S.matches && S.matches.matches) || []).forEach((m) => { byId[m.id] = { id: m.id, seller: m.seller, buyer: m.buyer, ref: m.ref, ref_back: m.ref_back, price: m.price, state: m.state, tick: m.state_tick || m.proposed_tick, offer: m.offer }; });
      S.items.slice().reverse().forEach((it) => {              // the floor is fresher than the last poll
        if (it.src !== "plaza" || it.kind !== "match" || !it.match) return;
        byId[it.match] = { ...(byId[it.match] || {}), id: it.match, seller: it.team, buyer: it.to, ref: it.ref, ref_back: it.ref_back, price: it.price, state: it.state, tick: it.tick };
      });
      const rank = { settled: 0, accepted: 1, offer_on_v07: 1 };
      const top = Object.values(byId).filter((m) => m.ref).sort((a, b) => (b.tick || 0) - (a.tick || 0) || (rank[a.state] ?? 2) - (rank[b.state] ?? 2)).slice(0, 4);
      const k = JSON.stringify([top, Object.keys(S.cat).length, I18N.lang]);
      if (sig.strip === k) return;
      sig.strip = k;
      K.clear(dom.strip);
      K.add(dom.strip, top.map((m) => el(me && (m.seller === me || m.buyer === me) ? "a" : "div", {
          class: "activity-deal", href: me && (m.seller === me || m.buyer === me) ? "/plaza/offers/" + m.id : null },
        el("div", { class: "activity-deal-who" }, el("b", { class: "num" }, m.seller), K.icon("swap", 13), el("b", { class: "num" }, m.buyer)),
        el("div", { class: "activity-deal-cards" }, K.card(card(m.ref), { owned: owns(m.ref), size: "md" }),
          m.ref_back ? K.card(card(m.ref_back), { owned: owns(m.ref_back), size: "md" }) : typeof m.price === "number" ? K.cash(m.price, "md") : null),
        el("div", { class: "activity-deal-state" }, K.chip(t("state." + m.state), TONE[m.state]), K.id(K.tick(m.tick))),
        el("div", { class: "activity-deal-ids" }, K.id(m.id), typeof m.offer === "number" ? K.id("#" + m.offer) : null, K.id(t("activity.settlesOn"))))));
    }

    function drawWarn() {
      const stale = S.stale || status().feed === "stale";
      const k = JSON.stringify([stale, S.last && S.last.tick, I18N.lang]);
      if (sig.warn === k) return;
      sig.warn = k;
      K.clear(dom.warn);
      if (stale) dom.warn.appendChild(el("div", { class: "activity-stale", role: "status" }, K.pill(t("status.stale"), "warn"),
        el("span", null, t(S.stale ? "activity.stale.conn" : "activity.stale.feed") + (S.last ? " " + t("activity.stale.until", { tick: K.tick(S.last.tick) }) : ""))));
    }

    drawTabs();
    const stops = [
      API.stream(onItem),
      API.poll("/api/matches", 15000, (d) => { S.matches = d; S.stale = false; drawStrip(); drawWarn(); if (!S.got) { S.got = true; drawList(); } },
               () => { S.stale = true; drawWarn(); if (!S.items.length) drawList(); }),
    ];
    API.get("/api/market").then((d) => {
      (d.sets || []).forEach((s) => { S.colors[s.id] = s.color; });
      (d.cards || []).forEach((c) => { S.cat[c.ref] = c; });
      sig.strip = null; drawStrip(); if (S.items.length) drawList();
    }, () => {});
    const clock = setInterval(drawWarn, 5000);
    return () => { stops.forEach((s) => s()); clearInterval(clock); if (raf) cancelAnimationFrame(raf); };
  },
});
