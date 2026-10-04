// board: every card at its best public ask and bid on any venue, with what it really costs after the venue's fee,
// its usual range between teams, a little chart, and who holds or wants it. From a row a connected team adds the
// card to its wants or spares, so the matchmaker proposes the trade on v07. Public offers and sales only.
Plaza.screen("board", {
  title: "nav.board",
  render(root, ctx) {
    const { el } = K;
    const st = { data: null, error: null, q: "", set: null, rarity: "", kind: "all", open: null };
    const RARITIES = ["common", "uncommon", "rare", "epic", "legendary"];
    const KINDS = [["all", "board.f.all"], ["ask", "board.f.ask"], ["bid", "board.f.bid"], ["hot", "board.f.hot"], ["none", "board.f.none"]];
    const SVG = "http://www.w3.org/2000/svg";

    root.appendChild(K.pageHead(t("nav.board"), t("board.sub")));
    const bar = root.appendChild(el("div", { class: "market-bar board-bar" }));
    const info = root.appendChild(el("div", { class: "board-info" }));
    const feeds = root.appendChild(el("div", { class: "board-feeds id" }));
    const body = root.appendChild(el("div", { class: "board-body" }));
    body.appendChild(K.state("loading"));
    root.appendChild(el("p", { class: "muted board-note" }, t("board.note")));
    root.appendChild(K.endpoint("GET /plaza/board.json", "GET /plaza/board/history.json", "POST /plaza/api/me/cards"));

    function spark(prices) {
      if (!prices || prices.length < 2) return el("span", { class: "board-spark none" });
      const w = 84, h = 24, lo = Math.min(...prices), hi = Math.max(...prices), span = hi - lo || 1;
      const pts = prices.map((p, i) => (2 + (i * (w - 4)) / (prices.length - 1)).toFixed(1) + "," + (h - 3 - ((p - lo) * (h - 6)) / span).toFixed(1));
      const svg = document.createElementNS(SVG, "svg");
      svg.setAttribute("viewBox", "0 0 " + w + " " + h); svg.setAttribute("class", "board-spark"); svg.setAttribute("aria-hidden", "true");
      const line = document.createElementNS(SVG, "polyline");
      line.setAttribute("points", pts.join(" ")); line.setAttribute("fill", "none"); line.setAttribute("stroke", "currentColor"); line.setAttribute("stroke-width", "1.4");
      const last = pts[pts.length - 1].split(",");
      const dot = document.createElementNS(SVG, "rect");
      dot.setAttribute("x", String(Number(last[0]) - 1.5)); dot.setAttribute("y", String(Number(last[1]) - 1.5)); dot.setAttribute("width", "3"); dot.setAttribute("height", "3"); dot.setAttribute("fill", "currentColor");
      svg.appendChild(line); svg.appendChild(dot);
      return svg;
    }

    function side(o, kind, more) {
      if (!o) return el("div", { class: "board-side none" }, el("span", { class: "muted" }, t(kind === "ask" ? "board.noAsk" : "board.noBid")));
      const real = kind === "ask" ? o.cost : o.nets;
      return el("div", { class: "board-side " + kind },
        el("div", { class: "board-main" }, el("span", { class: "num board-price" }, K.price(real)),
          o.on_v07 ? el("span", { class: "chip board-v07" }, t("board.onV07")) : null),
        el("div", { class: "board-how id" }, o.fee ? t(kind === "ask" ? "board.fee" : "board.minusFee", { price: K.num(o.price), fee: K.num(o.fee) }) : t("board.noFee")),
        el("div", { class: "board-where" }, t("board.at", { venue: o.venue_name || o.venue, team: K.teamName(o.team) }), more > 1 ? el("span", { class: "muted" }, " · " + t("board.more", { n: more - 1 })) : null),
        o.saves_on_v07 > 0 ? el("div", { class: "board-saves" }, t("board.saves", { n: o.saves_on_v07 })) : null);
    }

    function prices(c) {
      const arrow = { up: "↑", down: "↓", flat: "→" }[c.trend];
      return el("div", { class: "board-hist" },
        el("div", { class: "board-hist-top" }, spark(c.spark),
          arrow ? el("span", { class: "board-trend " + c.trend, title: t("board.trend." + c.trend) }, arrow) : null),
        el("div", { class: "id" }, typeof c.last === "number" ? t("board.last", { price: K.price(c.last), tick: K.tick(c.last_tick) }) : t("board.noDeals")),
        typeof c.low === "number" ? el("div", { class: "id" }, t("board.range", { low: K.num(c.low), high: K.num(c.high) }) + " P")
          : c.deals ? el("div", { class: "id muted" }, t(c.deals === 1 ? "board.fewDeals" : "board.fewDealsN", { n: c.deals })) : null);
    }

    function who(c) {
      return el("div", { class: "board-who" },
        c.hot ? el("span", { class: "chip board-hot", title: t("board.hotTitle") }, t("board.hot")) : null,
        c.minted === 0 ? el("span", { class: "chip" }, t("board.notPulled")) : c.state === "not_seen" ? el("span", { class: "chip" }, t("board.notSeen")) : null,
        c.minted > 0 ? el("span", { class: "id muted" }, t("board.copies", { minted: K.num(c.minted), run: K.num(c.print_run) })) : null,
        c.holders.length ? el("span", { class: "id give" }, t("board.holders", { n: c.holders.length })) : null,
        c.seekers.length ? el("span", { class: "id get" }, t("board.seekers", { n: c.seekers.length })) : null,
        typeof c.book === "number" && c.book > 0 ? el("span", { class: "id muted" }, t("board.book", { price: K.price(c.book) })) : null);
    }

    function form(c, list) {
      const input = el("input", { class: "input board-input", type: "number", min: "1", max: "2000", step: "1", inputmode: "numeric",
        "aria-label": t(list === "wants" ? "board.maxLabel" : "board.minLabel"),
        value: String(list === "wants" ? (c.ask ? c.ask.price : c.median || c.book || "") : (c.bid ? c.bid.price : c.median || c.book || "")) });
      const send = K.btn(t("board.send"), { small: true, kind: "primary", onclick: () => {
        const n = Number(input.value);
        if (!Number.isInteger(n) || n < 1 || n > 2000) return K.toast(t("board.badPrice"), "bad");
        send.disabled = true;
        API.post("/api/me/cards", { op: "add", list, ref: c.ref, ...(list === "wants" ? { max: n } : { min: n }) })
          .then(() => { K.toast(t("board.done", { ref: c.ref }), "ok"); st.open = null; drawBody(); },
            (e) => { send.disabled = false; K.toast((e && e.message) || t("common.error"), "bad"); });
      } });
      return el("div", { class: "board-form" },
        el("label", { class: "label" }, t(list === "wants" ? "board.maxLabel" : "board.minLabel")), input,
        el("div", { class: "board-form-btns" }, send, K.btn(t("board.cancel"), { small: true, onclick: () => { st.open = null; drawBody(); } })),
        el("p", { class: "muted board-help" }, t(list === "wants" ? "board.wantHelp" : "board.sellHelp")));
    }

    function act(c) {
      if (!ctx.me) return el("div", { class: "board-act" }, K.link("/plaza/connect", { class: "btn sm", title: t("board.connectFirst") }, K.icon("agent", 13), t(c.ask ? "board.want" : "board.request")));
      const open = (list) => () => { st.open = st.open && st.open.ref === c.ref && st.open.list === list ? null : { ref: c.ref, list }; drawBody(); };
      return el("div", { class: "board-act" },
        K.btn(t(c.ask ? "board.want" : "board.request"), { small: true, onclick: open("wants") }),
        K.btn(t("board.sell"), { small: true, onclick: open("spares") }));
    }

    function row(c) {
      const opened = st.open && st.open.ref === c.ref;
      return el("div", { class: "board-row" + (c.hot ? " is-hot" : "") + (opened ? " is-open" : "") },
        el("div", { class: "board-card" }, K.card(c, { size: "sm", href: "/plaza/card/" + c.ref }),
          el("div", { class: "board-name" }, K.link("/plaza/card/" + c.ref, { class: "board-title" }, c.name),
            el("span", { class: "id" }, c.ref.replace("-", " · ")), el("span", { class: "label" }, t("rarity." + (c.rarity || "common"))))),
        el("div", { class: "board-cell", "data-h": t("board.col.ask") }, side(c.ask, "ask", c.asks)),
        el("div", { class: "board-cell", "data-h": t("board.col.bid") }, side(c.bid, "bid", c.bids)),
        el("div", { class: "board-cell", "data-h": t("board.col.price") }, prices(c)),
        el("div", { class: "board-cell", "data-h": t("board.col.status") }, who(c)),
        el("div", { class: "board-cell", "data-h": t("board.col.act") }, act(c)),
        opened ? form(c, st.open.list) : null);
    }

    function drawBar() {
      K.clear(bar);
      const d = st.data || {};
      const search = el("input", { class: "input market-search", type: "search", maxlength: "40", autocomplete: "off", placeholder: t("board.search"), "aria-label": t("board.search"), value: st.q,
        oninput: () => { st.q = search.value; drawBody(); } });
      const sets = (d.sets || []).map((s) => el("button", { type: "button", class: "market-set" + (st.set === s.id ? " active" : ""), style: { "--set": s.color }, title: s.name,
        "aria-pressed": String(st.set === s.id), onclick: () => { st.set = st.set === s.id ? null : s.id; drawBar(); drawBody(); } }, s.id));
      const rarity = el("select", { class: "input market-rarity", "aria-label": t("board.anyRarity"), onchange: () => { st.rarity = rarity.value; drawBody(); } },
        el("option", { value: "" }, t("board.anyRarity")), RARITIES.map((r) => el("option", { value: r, selected: st.rarity === r }, t("rarity." + r))));
      const kinds = el("div", { class: "market-seg", role: "group" }, KINDS.map(([k, key]) =>
        el("button", { type: "button", class: st.kind === k ? "active" : null, "aria-pressed": String(st.kind === k), onclick: () => { st.kind = k; drawBar(); drawBody(); } }, t(key))));
      K.add(bar, [el("label", { class: "market-find" }, K.icon("search", 14), search), el("div", { class: "market-sets" }, sets), rarity, kinds]);
      K.clear(info);
      if (!st.data) return;
      K.add(info, [el("span", { class: "id" }, t(d.offers === 1 ? "board.offers1" : "board.offersNow", { n: d.offers }) + " · " + K.tick(d.tick)),
        (d.unreleased_sets || []).map((s) => el("span", { class: "chip" }, t("board.unreleased") + " · " + (s.name || s.id)))]);
      const abs = (p) => location.origin + p;
      const feed = (path, key) => el("span", { class: "board-feed" },
        el("a", { href: path, target: "_blank", rel: "noopener" }, path.replace("/plaza/board/", "").replace("/plaza/", "")),
        key ? el("span", { class: "muted" }, " (" + t(key) + ")") : null,
        el("button", { type: "button", class: "board-copy", title: t("board.copy"), "aria-label": t("board.copy") + " " + path, onclick: () => K.copy(abs(path)) }, K.icon("copy", 12)));
      K.clear(feeds);
      K.add(feeds, [el("span", { class: "label" }, t("board.json")), feed("/plaza/board.json"), feed("/plaza/board/live.json", "board.jsonLive"),
        feed("/plaza/board/history.json", "board.jsonHistory"), feed("/plaza/collections.json"), feed("/plaza/AGENTS.md"),
        K.link("/plaza/collections", { class: "btn sm board-json" }, K.icon("cards", 13), t("board.collections"))]);
    }

    function drawBody() {
      K.clear(body);
      if (st.error) { body.appendChild(K.state("error", t("common.error"), st.error, K.btn(t("common.retry"), { small: true, onclick: () => ctx.go(location.pathname) }))); return; }
      if (!st.data) { body.appendChild(K.state("loading")); return; }
      const q = st.q.trim().toLowerCase();
      const cards = (st.data.cards || []).filter((c) => (!st.set || c.set === st.set) && (!st.rarity || c.rarity === st.rarity)
        && (!q || c.ref.toLowerCase().includes(q) || (c.name || "").toLowerCase().includes(q) || (c.set_name || "").toLowerCase().includes(q))
        && (st.kind === "all" || (st.kind === "ask" && c.ask) || (st.kind === "bid" && c.bid) || (st.kind === "hot" && c.hot) || (st.kind === "none" && !c.ask && !c.bid)));
      if (!cards.length) { body.appendChild(K.state("empty", t("board.empty"))); return; }
      body.appendChild(el("div", { class: "board-table" },
        el("div", { class: "board-row board-head label" }, ["card", "ask", "bid", "price", "status", "act"].map((k) => el("div", null, t("board.col." + k)))),
        cards.map(row)));
    }

    drawBar();
    const stop = API.poll("/api/board", 15000, (d) => {
      const first = !st.data;
      st.data = d; st.error = null;
      drawBar();
      if (!st.open) drawBody();                      // a form being filled is not redrawn under the hand
    }, (e) => { if (!st.data) { st.error = (e && e.message) || t("common.error"); drawBody(); } });
    return () => stop();
  },
});
