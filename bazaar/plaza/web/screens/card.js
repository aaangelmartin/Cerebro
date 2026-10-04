// card: one card. Who can part with it, who wants it, the possible matches and the last deals by tick.
// The team's own limits for it (from /api/me, private) are shown only to the team.
Plaza.screen("card", {
  title: "nav.card",
  render(root, ctx) {
    const { el } = K;
    const ref = ctx.params.ref;
    const DEALERS = { picaros: "Los Pícaros", pilar: "Doña Pilar", chato: "El Chato", abuela: "Abuela Carmen", carmen: "Abuela Carmen", ernesto: "Don Ernesto", banco: "Don Ernesto" };
    const who = (x) => (/^t\d\d$/.test(String(x)) ? String(x) : DEALERS[x] || (x ? String(x) : t("card.dealer")));
    const teamChip = (team) => K.link("/plaza/team/" + team, { class: "chip card-team", title: K.teamName(team) }, team);

    root.appendChild(el("div", { class: "card-top" }, K.link("/plaza/market", { class: "btn sm quiet" }, K.icon("back", 13), t("nav.market"))));
    const body = root.appendChild(el("div"));
    body.appendChild(K.state("loading"));
    root.appendChild(K.endpoint("GET /plaza/api/card/" + ref));

    function draw(c) {
      K.clear(body);
      const you = c.you || null;
      const owned = !ctx.me || Boolean(you && you.owned);
      const parts = K.refParts(c.ref);
      const asks = (c.offers || []).filter((o) => o.side === "ask" && typeof o.price === "number").sort((a, b) => a.price - b.price);
      const bids = (c.offers || []).filter((o) => o.side === "bid" && typeof o.price === "number").sort((a, b) => b.price - a.price);
      const venue = (o) => (o.venue === "v07" ? "v07" : o.venue_name || o.venue || "");

      // last deals: team deals first-hand (`deals`), then what the recorder saw with dealers (`sales`)
      const deals = (c.deals || []).map((d) => ({ tick: d.tick, from: d.seller, to: d.buyer, venue: d.venue, price: d.price }))
        .concat((c.sales || []).map((s) => ({ tick: s.tick, from: s.from, to: s.to, venue: s.venue, price: s.price })))
        .sort((a, b) => (b.tick || 0) - (a.tick || 0)).slice(0, 12);

      const matches = (c.possible_matches || []).map((m) => el("div", { class: "card-match" },
        el("span", { class: "card-match-price num" }, K.price(m.price)),
        el("span", { class: "card-match-text" }, t(m.kind === "swap" ? "card.matchSwap" : "card.matchSale", { seller: K.teamName(m.seller), buyer: K.teamName(m.buyer) }),
          m.finishes_page ? K.chip(t("card.finishes"), "signal") : null),
        el("span", { class: "card-match-state" }, m.state ? K.chip(t("state." + m.state), m.state === "settled" ? "ok" : null) : el("span", { class: "id" }, t("card.notProposed")),
          m.id ? (ctx.me && (m.seller === ctx.me.team || m.buyer === ctx.me.team) ? K.link("/plaza/offers/" + m.id, { class: "id card-link" }, m.id) : K.id(m.id)) : null)));

      const mine = ctx.me && ctx.me.limits && ctx.me.limits[c.ref];
      const privLine = [];
      if (mine) for (const [k, key] of [["min", "card.yourMin"], ["max", "card.yourMax"], ["value", "card.worth"]]) if (typeof mine[k] === "number") privLine.push(t(key, { price: K.price(mine[k]) }));
      if (you && you.want) privLine.push(t("card.youWant"));
      if (you && you.as) privLine.push(t("card.youAs." + you.as));

      body.appendChild(el("div", { class: "card-layout" },
        el("div", { class: "card-side" }, K.card(c, { owned, size: "fluid" }),
          ctx.me ? el("span", { class: "chip" + (owned ? " tone-signal" : "") }, t(owned ? "card.youHave" : "card.youDont")) : null,
          ctx.me && owned ? K.link("/plaza/auctions?card=" + c.ref, { class: "btn sm" }, K.icon("offers", 13), t("card.auction")) : null),
        el("div", { class: "card-main" },
          el("h1", { class: "page-title" }, c.name || c.ref),
          el("div", { class: "card-facts id" }, [parts.set + " · " + parts.no, t("rarity." + (c.rarity || "common")), typeof c.minted === "number" ? (c.minted ? t("board.copies", { minted: K.num(c.minted), run: K.num(c.print_run) }) : t("board.notPulled")) : null, typeof c.tick === "number" ? K.tick(c.tick) : null].filter(Boolean).join("  ·  ")),
          K.kpis([
            { label: t("card.book"), value: K.price(c.book), sub: t("card.bookSub") },
            { label: t("card.bestAsk"), value: asks.length ? K.price(asks[0].price) : "–", sub: asks.length ? venue(asks[0]) : t("card.none") },
            { label: t("card.bestBid"), value: bids.length ? K.price(bids[0].price) : "–", sub: bids.length ? venue(bids[0]) : t("card.none") },
            { label: t("card.lastDeal"), value: K.price(deals.length ? deals[0].price : c.last_price), sub: deals.length ? K.tick(deals[0].tick) : t("card.none") }]),
          el("div", { class: "card-zones" },
            el("div", { class: "card-zone give" }, K.icon("give", 14), el("b", null, t("card.hasIt")),
              (c.holders || []).length ? c.holders.map((h) => teamChip(h.team)) : el("span", { class: "muted" }, t("card.nobody"))),
            el("div", { class: "card-zone get" }, K.icon("get", 14), el("b", null, t("card.wantsIt")),
              (c.seekers || []).length ? c.seekers.map((s) => teamChip(s.team)) : el("span", { class: "muted" }, t("card.nobody")))),
          K.panel({ title: t("card.matches"), note: t("card.matchesNote"), flush: true },
            matches.length ? el("div", { class: "card-list" }, matches) : el("p", { class: "muted card-none" }, t("card.noMatches"))),
          K.panel({ title: t("card.deals"), note: t("card.dealsNote"), flush: true },
            deals.length ? el("div", { class: "card-list" }, deals.map((d) => el("div", { class: "card-deal" }, el("span", { class: "id" }, K.tick(d.tick)),
              el("span", { class: "card-deal-text" }, who(d.from) + " → " + who(d.to) + (d.venue ? " · " + (d.venue === "rastro" ? "El Rastro" : d.venue) : "")),
              el("span", { class: "num" }, K.price(d.price))))) : el("p", { class: "muted card-none" }, t("card.noDeals"))),
          (c.offers || []).length ? K.panel({ title: t("card.offers"), note: t("card.offersNote"), flush: true },
            K.table([{ key: "venue", label: t("common.venue"), render: (o) => venue(o) }, { key: "side", label: t("card.side"), render: (o) => t(o.side === "ask" ? "card.sells" : "card.buys") },
                     { key: "maker", label: t("card.maker"), render: (o) => who(o.maker) }, { key: "price", label: t("common.price"), num: true, render: (o) => K.price(o.price) },
                     { key: "cost", label: t("card.cost"), num: true, render: (o) => K.price(o.cost) }, { key: "expires_tick", label: t("card.until"), num: true, render: (o) => K.tick(o.expires_tick) }],
                    c.offers)) : null,
          privLine.length ? el("div", { class: "card-private", title: t("common.private") }, K.icon("lock", 13), privLine.join("  ·  ")) : null)));
    }

    return API.poll("/api/card/" + ref, 15000, draw, (e) => {
      if (body.querySelector(".card-layout")) return;
      K.clear(body).appendChild(e && e.status === 404 ? K.state("empty", t("card.notFound", { ref }), null, K.btn(t("nav.market"), { small: true, onclick: () => ctx.go("/plaza/market") }))
        : K.state("error", t("common.error"), e && e.message));
    });
  },
});
