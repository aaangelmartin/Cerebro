// home: the team watches its agent work. Nothing here needs a hand: the agent's log by tick, the two zones of
// cards and the trades it is running, redrawn as the market answers (CONTRACT.md, section 3).
Plaza.screen("home", {
  title: "nav.home", needsTeam: true,
  render(root, ctx) {
    const { el } = K;
    const LIVE = ["proposed", "offer_on_v07", "accepted"];
    const TONE = { proposed: null, offer_on_v07: "signal", accepted: "signal", settled: "ok", passed: "bad", expired: "warn", settled_elsewhere: "bad" };
    const S = { me: ctx.me, cards: null, trades: null, acts: [], seq: 0, failed: false };
    const sig = {};

    const slot = (cls) => root.appendChild(el("div", { class: cls }));
    const dom = { head: slot("home-head"), api: slot("home-api"), banner: slot("home-banner"), signals: root.appendChild(Signals.block(ctx, "both")), agent: slot("home-agent"),
                  zones: slot("home-zones"), trades: slot("home-trades") };
    dom.api.appendChild(K.endpoint("GET /plaza/api/me", "GET /plaza/api/me/activity?since=<seq>", "GET /plaza/api/me/cards", "GET /plaza/api/me/trades"));
    dom.agent.appendChild(K.state("loading"));

    /** Redraws one block only when what it shows has changed: no flicker between polls. */
    function draw(name, key, build) {
      const k = JSON.stringify(key);
      if (sig[name] === k) return;
      sig[name] = k;
      K.clear(dom[name]);
      K.add(dom[name], [build()]);
    }
    const status = () => Plaza.state.status || ctx.status || {};
    const offline = () => status().agent === "offline" || (S.me && S.me.status && S.me.status.agent_online === false && status().agent !== "connected");
    const lastAct = () => S.acts.length ? S.acts[S.acts.length - 1] : null;
    const lastByAgent = () => { for (let i = S.acts.length - 1; i >= 0; i--) if (S.acts[i].by === "agent") return S.acts[i]; return lastAct(); };
    const running = () => (S.trades ? S.trades.trades.filter((x) => LIVE.includes(x.state)).length
      : S.me && S.me.trades ? LIVE.reduce((n, k) => n + (S.me.trades[k] || 0), 0) : 0);

    function drawHead() {
      const me = S.me || {}, c = me.counts || {}, la = lastAct(), off = offline(), n = running();
      draw("head", [me.team, c, la && la.tick, status().tick, off, n, I18N.lang], () => el("header", { class: "home-top" },
        el("span", { class: "home-no" }, K.teamNo(me.team)),
        el("div", { class: "home-who" }, el("h1", { class: "page-title" }, me.name || K.teamName(me.team)),
          el("p", { class: "page-sub" }, [t("home.sub.have", { n: c.have || 0 }), t("home.sub.want", { n: c.want || 0 }), t("home.sub.limits", { n: c.limits_set || 0 }),
            la ? t(off ? "home.sub.lastUpdate" : "home.sub.updated", { ago: K.ago(la.tick, status().tick) }) : null].filter(Boolean).join(" · "))),
        K.link("/plaza/offers", { class: "btn home-running" }, off ? null : K.icon("bell", 15),
          t(off ? (n === 1 ? "home.onHold1" : "home.onHold") : n === 1 ? "home.running1" : "home.running", { n }), off ? null : K.icon("arrow", 14))));
    }

    function drawBanner() {
      const off = offline(), la = lastByAgent();
      draw("banner", [off, la && la.tick, status().tick, I18N.lang], () => !off ? null : el("div", { class: "home-offline", role: "alert" },
        K.icon("off", 18),
        el("div", { class: "home-offline-text" }, el("b", null, t("home.offline.title")),
          el("span", null, (la ? t("home.offline.last", { tick: K.tick(la.tick), ago: K.ago(la.tick, status().tick) }) + " " : "") + t("home.offline.text"))),
        K.link("/plaza/connect", { class: "btn sm" }, t("home.offline.prompt"))));
    }

    function drawAgent() {
      const off = offline(), rows = S.acts.slice(-6).reverse(), la = lastByAgent();
      draw("agent", [off, rows.map((r) => r.seq), S.failed, S.loaded, I18N.lang], () => {
        const body = !S.loaded && !rows.length ? (S.failed ? K.state("error", null, t("home.error")) : K.state("loading"))
          : !rows.length ? K.state("empty", t("home.agent.empty"), t("home.agent.emptyText"))
          : K.feed(rows.map((r, i) => ({ tick: r.tick, now: i === 0 && !off, text: K.say(r.text),
              extra: [r.by && r.by !== "agent" ? K.chip(t("home.by." + r.by)) : null,
                      r.match ? K.link("/plaza/offers/" + r.match, { class: "id home-mid" }, r.match) : null] })));
        return K.panel({ icon: "agent", flush: true, class: off ? "home-stopped" : null,
          title: t(off ? "home.agent.stopped" : "home.agent.title"),
          note: off ? (la ? t("home.agent.last", { tick: K.tick(la.tick) }) : "") : t("home.agent.note") }, body);
      });
    }

    function drawZones() {
      const c = S.cards;
      if (!c) return;
      const sell = (c.have || []).filter((x) => x.as === "duplicate" || x.as === "for_sale");
      const want = c.want || [];
      draw("zones", [sell.map((x) => x.ref), want.map((x) => x.ref), I18N.lang], () => {
        const more = () => K.link("/plaza/cards", { class: "panel-more" }, t("common.seeAll"));
        const strip = (list, owned, none) => list.length
          ? el("div", { class: "card-strip" }, list.slice(0, 8).map((x) => K.card(x, { owned, size: "md", href: "/plaza/card/" + x.ref })))
          : el("p", { class: "home-none" }, none);
        const count = (n) => t(n === 1 ? "common.card1" : "common.cards", { n });
        return el("div", { class: "home-zone-grid" },
          K.panel({ title: t("home.sell.title"), note: count(sell.length), icon: "give", zone: "give", more: more() }, strip(sell, true, t("home.sell.none"))),
          K.panel({ title: t("home.want.title"), note: count(want.length), icon: "get", zone: "get", more: more() }, strip(want, false, t("home.want.none"))));
      });
    }

    function tradeCell(tr, off) {
      const me = S.me.team, other = (tr.teams || []).find((x) => x !== me) || (tr.your_role === "seller" ? tr.buyer : tr.seller);
      const live = LIVE.includes(tr.state);
      const doing = off && live ? t("home.trade.waitingAgent")
        : tr.next && tr.next.why ? K.say(tr.next.why) : tr.next && tr.next.waiting ? K.say(tr.next.waiting)
        : tr.state === "settled" ? t("home.trade.settled", { tick: K.tick(tr.settled_tick || tr.state_tick) }) : t("state." + tr.state);
      const ids = [tr.id, typeof tr.offer === "number" ? "#" + tr.offer : null].filter(Boolean);
      return el("article", { class: "home-trade" + (live ? "" : " is-done") },
        K.swap(tr.gives, tr.receives, tr.cash || 0, "md"),
        el("div", { class: "home-trade-who" }, K.link("/plaza/offers/" + tr.id, { class: "home-trade-team" }, K.teamName(other)), K.id(other),
          K.chip(t("state." + tr.state), TONE[tr.state])),
        el("div", { class: "home-trade-doing" + (off && live ? " is-held" : "") }, K.icon(off && live ? "off" : "agent", 14), el("span", null, doing)),
        el("div", { class: "home-trade-price" }, el("b", null, "v07 " + K.price(tr.price)), el("span", null, t("common.noFee")),
          tr.saves ? el("span", null, t("home.trade.saves", { p: K.price(tr.saves) })) : null),
        el("div", { class: "home-trade-ids" }, ids.map((x) => K.id(x)),
          el("span", { class: "id" }, t("home.trade.ticks", { from: K.tick(tr.proposed_tick), now: K.tick(tr.state_tick) })),
          el("button", { class: "home-copy", type: "button", title: t("common.copy"), "aria-label": t("common.copy") + " " + tr.id,
                         onclick: () => K.copy(ids.join(" ")) }, K.icon("copy", 12))));
    }

    function drawTrades() {
      if (!S.trades) return;
      const off = offline(), all = S.trades.trades || [];
      const live = all.filter((x) => LIVE.includes(x.state));
      const done = all.filter((x) => !LIVE.includes(x.state)).sort((a, b) => (b.state_tick || 0) - (a.state_tick || 0));
      const shown = live.concat(done).slice(0, 3);
      draw("trades", [off, shown.map((x) => [x.id, x.state, x.state_tick, x.price, x.offer, x.next, x.messages]), I18N.lang], () => K.panel({
        icon: "trend", flush: true, title: t("home.trades.title"), class: off ? "home-held" : null,
        note: t(off ? "home.trades.hold" : "home.trades.note"),
        more: all.length > shown.length ? K.link("/plaza/offers", { class: "panel-more" }, t("common.seeAll")) : null },
        shown.length ? el("div", { class: "home-trade-grid" }, shown.map((x) => tradeCell(x, off)))
          : K.state("empty", t("home.trades.empty"), t("home.trades.emptyText"))));
    }

    function redraw() { drawHead(); drawBanner(); drawAgent(); drawZones(); drawTrades(); }

    const stops = [
      API.poll("/api/me", 3000, (me) => { S.me = me; Plaza.state.me = me; redraw(); }),
      API.poll(() => ["/api/me/activity", { since: S.seq, limit: 40 }], 3000, (d) => {
        const seen = new Set(S.acts.map((a) => a.seq));
        (d.items || []).forEach((a) => { if (!seen.has(a.seq)) S.acts.push(a); });
        S.acts.sort((a, b) => a.seq - b.seq);
        S.acts = S.acts.slice(-60);
        S.seq = S.acts.length ? S.acts[S.acts.length - 1].seq : 0;
        S.loaded = true; S.failed = false;
        redraw();
      }, () => { S.failed = true; redraw(); }),
      API.poll("/api/me/cards", 15000, (c) => { S.cards = c; redraw(); }),
      API.poll("/api/me/trades", 3000, (d) => { S.trades = d; redraw(); }, () => {
        if (!S.trades) { S.trades = { trades: [] }; sig.trades = null; K.clear(dom.trades).appendChild(K.state("error", null, t("home.error"))); }
      }),
    ];
    const clock = setInterval(() => { drawHead(); drawBanner(); drawAgent(); drawTrades(); }, 5000);   // the status box moves on its own
    redraw();
    return () => { stops.forEach((s) => s()); clearInterval(clock); };
  },
});
