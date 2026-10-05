// collections: every set card by card (copies handed out, price, how many teams want it), the scarcest and most
// wanted of each set, and every team's album as the game shows it. A connected team sees first what it still
// misses, each card with its best price and one click to ask for it on v07. Never whose page a card would finish.
Plaza.screen("collections", {
  title: "nav.collections",
  render(root, ctx) {
    const { el } = K;
    const st = { data: null, board: null, mine: null, error: null, busy: new Set(), asked: new Set() };

    root.appendChild(K.pageHead(t("nav.collections"), t("coll.sub"), K.link("/Cerebro/market/board", { class: "btn sm" }, K.icon("performance", 13), t("coll.toBoard"))));
    const own = root.appendChild(el("div"));
    root.appendChild(Signals.block(ctx, "buy"));
    const body = root.appendChild(el("div", { class: "coll-body" }));
    body.appendChild(K.state("loading"));
    root.appendChild(K.endpoint("GET /Cerebro/market/collections.json", "GET /Cerebro/market/board.json", ctx.me ? "POST /Cerebro/market/api/me/cards" : null));

    const price = (c) => (c.ask ? c.ask.price : typeof c.median === "number" ? c.median : c.book);

    function request(c) {
      const max = price(c);
      if (!max || st.busy.has(c.ref)) return;
      st.busy.add(c.ref); drawMine();
      API.post("/api/me/cards", { op: "add", list: "wants", ref: c.ref, max })
        .then(() => { st.asked.add(c.ref); K.toast(t("coll.done", { ref: c.ref }), "ok"); }, (e) => K.toast((e && e.message) || t("common.error"), "bad"))
        .then(() => { st.busy.delete(c.ref); drawMine(); });
    }

    function drawMine() {
      K.clear(own);
      if (!ctx.me) { own.appendChild(el("p", { class: "coll-connect" }, K.link("/Cerebro/market/connect", { class: "btn sm" }, K.icon("agent", 13), t("coll.connect")))); return; }
      if (!st.board || !st.mine) return;
      const have = new Set((st.mine.have || []).filter((c) => c.owned !== false).map((c) => c.ref));
      const want = new Set((st.mine.want || []).map((c) => c.ref));
      const cards = st.board.cards || [];
      if (!have.size) { own.appendChild(K.panel({ title: t("coll.mine"), note: t("coll.mineSub"), icon: "cards" }, el("p", { class: "muted" }, t("coll.none")))); return; }
      const sets = (st.board.sets || []).map((s) => {
        const page = cards.filter((c) => c.set === s.id && c.page);
        const miss = page.filter((c) => !have.has(c.ref));
        return el("div", { class: "coll-mine-set", style: { "--set": s.color } },
          el("div", { class: "coll-mine-head" }, el("span", { class: "coll-set-id" }, s.id), el("span", null, s.name),
            miss.length ? el("span", { class: "id muted" }, t("coll.missing", { n: miss.length })) : el("span", { class: "chip coll-ok" }, t("coll.complete"))),
          miss.length ? el("div", { class: "coll-mine-cards" }, miss.map((c) => {
            const p = price(c), asked = st.asked.has(c.ref) || want.has(c.ref);
            return el("div", { class: "coll-miss" }, K.card(c, { owned: false, size: "sm", href: "/Cerebro/market/card/" + c.ref }),
              el("span", { class: "id" }, c.ask ? t("coll.best", { price: K.price(c.ask.cost) }) : t("coll.noPrice")),
              asked ? el("span", { class: "chip coll-ok" }, t("common.want"))
                : K.btn(p ? t("coll.request", { price: K.price(p) }) : t("board.request"), { small: true, disabled: !p || st.busy.has(c.ref), onclick: () => request(c) }));
          })) : null);
      });
      const spare = (st.mine.have || []).filter((c) => c.as === "duplicate" || c.as === "for_sale" || c.as === "spare")
        .map((c) => ({ ...c, n: ((cards.find((b) => b.ref === c.ref) || {}).seekers || []).length })).filter((c) => c.n > 0);
      own.appendChild(K.panel({ title: t("coll.mine"), note: t("coll.mineSub"), icon: "cards" },
        el("div", { class: "coll-mine" }, sets), el("p", { class: "muted coll-help" }, t("coll.requestHelp")),
        el("div", { class: "label coll-sub" }, t("coll.spares")),
        spare.length ? el("div", { class: "card-strip" }, spare.map((c) => el("div", { class: "coll-miss" }, K.card(c, { size: "sm", href: "/Cerebro/market/card/" + c.ref }),
          el("span", { class: "id get" }, t("coll.wantedBy", { n: c.n })))))
          : el("p", { class: "muted" }, t("coll.sparesNone"))));
    }

    function tile(c, s) {
      const mark = s.scarcest.includes(c.ref) ? el("span", { class: "chip" }, t("coll.scarcest")) : s.most_wanted.includes(c.ref) ? el("span", { class: "chip coll-want" }, t("coll.mostWanted")) : null;
      return el("div", { class: "coll-tile" }, K.card(c, { owned: c.state === "in_play", size: "fluid", href: "/Cerebro/market/card/" + c.ref }),
        el("div", { class: "id" }, typeof c.minted === "number" ? (c.minted ? t("coll.copies", { minted: K.num(c.minted), run: K.num(c.print_run) }) : t("coll.notPulled")) : "–"),
        el("div", { class: "id" }, typeof c.ask === "number" ? t("coll.ask", { price: K.price(c.ask) }) : typeof c.last === "number" ? t("coll.last", { price: K.price(c.last) }) : t("coll.noPrice")),
        c.wanted_by ? el("div", { class: "id get" }, t("coll.wantedBy", { n: c.wanted_by })) : null, mark);
    }

    function draw() {
      K.clear(body);
      if (st.error) { body.appendChild(K.state("error", t("common.error"), st.error, K.btn(t("common.retry"), { small: true, onclick: () => ctx.go(location.pathname) }))); return; }
      const d = st.data;
      if (!d) { body.appendChild(K.state("loading")); return; }
      (d.sets || []).forEach((s) => body.appendChild(K.panel({ title: s.name || s.id, note: t("coll.inPlay", { n: s.in_play, total: s.total }), icon: "cards" },
        el("div", { class: "coll-grid", style: { "--set": s.color } }, s.cards.map((c) => tile(c, s))))));
      (d.unreleased_sets || []).forEach((s) => body.appendChild(K.panel({ title: s.name || s.id, note: t("coll.unreleased"), icon: "cards" },
        el("p", { class: "muted" }, t("coll.unreleased")))));
      if ((d.teams || []).length) {
        body.appendChild(K.panel({ title: t("coll.teams"), note: t("coll.teamsSub"), icon: "teams" },
          el("div", { class: "coll-teams" }, d.teams.map((x) => K.link("/Cerebro/market/team/" + x.team, { class: "coll-team" },
            el("span", null, K.teamName(x.team)), el("span", { class: "num" }, x.album || "–"),
            el("span", { class: "id muted" }, typeof x.pages === "number" ? t("coll.th.pages") + " · " + x.pages : ""))))));
      }
    }

    const stops = [API.poll("/api/collections", 20000, (d) => { st.data = d; st.error = null; draw(); },
      (e) => { if (!st.data) { st.error = (e && e.message) || t("common.error"); draw(); } })];
    if (ctx.me) {
      stops.push(API.poll("/api/board", 20000, (d) => { st.board = d; drawMine(); }, () => {}));
      stops.push(API.poll("/api/me/cards", 20000, (d) => { st.mine = d; drawMine(); }, () => {}));
    }
    drawMine();
    return () => stops.forEach((s) => s());
  },
});
