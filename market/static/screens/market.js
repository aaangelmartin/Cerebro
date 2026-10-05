// market: every card on v07 right now: who can part with it (red), who wants it (green), best ask and bid and
// the last price. Cards the team does not hold are drawn as Colección slots. /Cerebro/market/team/tXX shows one team's
// public sheet on top.
Plaza.screen("market", {
  title: "nav.market",
  render(root, ctx) {
    const { el } = K;
    const st = { data: null, error: null, q: "", set: null, rarity: "", kind: "all", team: null };
    const RARITIES = ["common", "uncommon", "rare", "epic", "legendary"];

    root.appendChild(K.pageHead(t("nav.market"), t("market.sub")));
    const bar = root.appendChild(el("div", { class: "market-bar" }));
    const sheet = root.appendChild(el("div"));
    const body = root.appendChild(el("div", { class: "market-body" }));
    body.appendChild(K.state("loading"));
    root.appendChild(K.endpoint("GET /Cerebro/market/api/market?set=&rarity=", "GET /Cerebro/market/api/card/<ref>", ctx.params.team ? "GET /Cerebro/market/api/team/" + ctx.params.team : null));

    // Without a connected team nothing is "not owned": the cards are shown in colour.
    const owned = (c) => !ctx.me || c.you === "have";
    const teams = (n, one, many) => t(n === 1 ? one : many, { n });

    function tile(c, zone) {
      const main = zone === "give" ? c.best_ask : c.best_bid;
      return el("div", { class: "market-tile" },
        K.card(c, { owned: owned(c), size: "fluid", href: "/Cerebro/market/card/" + c.ref }),
        el("div", { class: "market-price" }, el("span", { class: "num market-main" }, typeof main === "number" ? K.price(main) : "–"),
          el("span", { class: "label" }, t(zone === "give" ? "market.ask" : "market.bid")),
          c.you ? el("span", { class: "chip market-you" }, t(c.you === "have" ? "common.have" : "common.want")) : null),
        el("div", { class: "market-meta" }, (zone === "give"
          ? (c.seekers ? teams(c.seekers, "market.want1", "market.wantN") : t("market.nobodyAsking"))
          : (c.holders ? teams(c.holders, "market.hold1", "market.holdN") : t("market.nobodySelling")))
          + (c.matches ? " · " + t(c.matches === 1 ? "market.match1" : "market.matchN", { n: c.matches }) : "")),
        el("div", { class: "market-meta id" }, typeof c.last_price === "number" ? t("market.last", { price: K.price(c.last_price), tick: K.tick(c.last_tick) }) : t("market.noDeal")));
    }

    function drawBar() {
      K.clear(bar);
      const d = st.data || {};
      const search = el("input", { class: "input market-search", type: "search", maxlength: "40", autocomplete: "off", placeholder: t("market.search"), "aria-label": t("market.search"), value: st.q,
        oninput: () => { st.q = search.value; drawBody(); } });
      const sets = (d.sets || []).map((s) => el("button", { type: "button", class: "market-set" + (st.set === s.id ? " active" : ""), style: { "--set": s.color }, title: s.name,
        "aria-pressed": String(st.set === s.id), onclick: () => { st.set = st.set === s.id ? null : s.id; drawBar(); drawBody(); } }, s.id));
      const rarity = el("select", { class: "input market-rarity", "aria-label": t("market.anyRarity"), onchange: () => { st.rarity = rarity.value; drawBody(); } },
        el("option", { value: "" }, t("market.anyRarity")), RARITIES.map((r) => el("option", { value: r, selected: st.rarity === r }, t("rarity." + r))));
      const kinds = el("div", { class: "market-seg", role: "group" }, [["all", "common.all"], ["give", "market.kindSell"], ["get", "market.kindWanted"]].map(([k, key]) =>
        el("button", { type: "button", class: st.kind === k ? "active" : null, "aria-pressed": String(st.kind === k), onclick: () => { st.kind = k; drawBar(); drawBody(); } }, t(key))));
      K.add(bar, [el("label", { class: "market-find" }, K.icon("search", 14), search), el("div", { class: "market-sets" }, sets), rarity, kinds]);
    }

    function drawSheet() {
      K.clear(sheet);
      const s = st.team;
      if (!ctx.params.team) return;
      if (!s) { sheet.appendChild(K.state("loading")); return; }
      const strip = (cards, own) => (cards.length ? el("div", { class: "card-strip" }, cards.map((c) => K.card(c, { owned: own, size: "sm", href: "/Cerebro/market/card/" + c.ref })))
        : el("p", { class: "muted" }, t("market.sheetNone")));
      sheet.appendChild(K.panel({ title: t("market.sheet", { team: K.teamName(s.team) }), note: s.album ? t("market.album", { album: s.album }) : null, icon: "teams",
        more: K.link("/Cerebro/market/market", { class: "panel-more" }, t("market.allTeams")) },
        el("div", { class: "market-sheet" },
          el("div", null, el("div", { class: "label market-lab give" }, t("market.canPart")), strip([].concat(s.for_sale || [], s.spares || []), true)),
          el("div", null, el("div", { class: "label market-lab get" }, t("market.looksFor")), strip(s.wants || [], false)))));
    }

    function drawBody() {
      K.clear(body);
      if (st.error) { body.appendChild(K.state("error", t("common.error"), st.error, K.btn(t("common.retry"), { small: true, onclick: () => ctx.go(location.pathname) }))); return; }
      if (!st.data) { body.appendChild(K.state("loading")); return; }
      const q = st.q.trim().toLowerCase();
      const cards = (st.data.cards || []).filter((c) => (!st.set || c.set === st.set) && (!st.rarity || c.rarity === st.rarity)
        && (!q || c.ref.toLowerCase().includes(q) || (c.name || "").toLowerCase().includes(q)));
      const give = cards.filter((c) => c.holders > 0 || typeof c.best_ask === "number");
      const get = cards.filter((c) => c.seekers > 0 || typeof c.best_bid === "number");
      if (!give.length && !get.length) {
        body.appendChild(K.state("empty", t((st.data.cards || []).length ? "market.noneFilter" : "market.emptyTitle"), (st.data.cards || []).length ? null : t("market.emptyText")));
        return;
      }
      const count = (n) => t(n === 1 ? "common.card1" : "common.cards", { n });
      const zone = (kind, title, list) => K.panel({ title, note: count(list.length), icon: kind, zone: kind },
        list.length ? el("div", { class: "market-grid" }, list.map((c) => tile(c, kind))) : el("p", { class: "muted" }, t("market.noneZone")));
      if (st.kind !== "get") body.appendChild(zone("give", t("market.forSale"), give));
      if (st.kind !== "give") body.appendChild(zone("get", t("market.wanted"), get));
      if (st.kind === "all") {
        const gap = cards.filter((c) => c.seekers > 0 && !c.holders && typeof c.best_ask !== "number");
        const spare = cards.filter((c) => c.holders > 0 && !c.seekers && typeof c.best_bid !== "number");
        const small = (title, icon, list, hint) => K.panel({ title, icon, note: count(list.length) },
          list.length ? el("div", { class: "market-small" }, el("div", { class: "card-strip" }, list.map((c) => K.card(c, { owned: owned(c), size: "sm", href: "/Cerebro/market/card/" + c.ref }))),
            el("span", { class: "muted" }, hint)) : el("p", { class: "muted" }, t("market.noneZone")));
        body.appendChild(el("div", { class: "market-pair" }, small(t("market.gap"), "get", gap, t("market.gapHint")), small(t("market.spare"), "give", spare, t("market.spareHint"))));
      }
    }

    drawBar();
    const stop = API.poll("/api/market", 15000, (d) => {
      const first = !st.data;
      st.data = d; st.error = null;
      if (first) drawBar();
      drawBody();
    }, (e) => { if (!st.data) { st.error = (e && e.message) || t("common.error"); drawBody(); } });
    let stopTeam = null;
    if (ctx.params.team) {
      drawSheet();
      stopTeam = API.poll("/api/team/" + ctx.params.team, 15000, (s) => { st.team = s; drawSheet(); },
        () => { K.clear(sheet).appendChild(K.state("error", t("market.noTeam", { team: ctx.params.team }))); });
    }
    return () => { stop(); if (stopTeam) stopTeam(); };
  },
});
