// kit: every shared component on one page, drawn from the fixtures. Screens copy from here.
Plaza.screen("kit", {
  title: "nav.kit",
  noOverlay: true,
  render(root, ctx) {
    const { el } = K;
    const sample = [
      { ref: "LAV-09", name: "Cine Doré", rarity: "rare", color: "#E4572E", art: "/plaza/art/LAV-09.svg" },
      { ref: "SAL-10", name: "Museo Lázaro Galdiano", rarity: "rare", color: "#2E86AB", art: "/plaza/art/SAL-10.svg" },
      { ref: "MAL-06", name: "Tienda de Discos", rarity: "uncommon", color: "#7B2CBF", art: "/plaza/art/MAL-06.svg" },
      { ref: "RET-11", name: "Palacio de Cristal", rarity: "epic", color: "#3BB273", art: "/plaza/art/RET-11.svg" },
    ];
    const box = (title, note, ...body) => K.panel({ title, note }, ...body);
    root.appendChild(K.pageHead(t("kit.title"), t("kit.sub")));
    const grid = root.appendChild(el("div", { class: "kit-grid" }));
    grid.appendChild(box("K.card", "owned · not owned · sizes",
      el("div", { class: "kit-row" }, sample.map((c) => K.card(c, { size: "md" }))),
      el("div", { class: "kit-row", style: { marginTop: "12px" } }, sample.map((c) => K.card(c, { owned: false, size: "md" }))),
      el("div", { class: "kit-row", style: { marginTop: "12px" } }, K.card(sample[0], { size: "sm" }), K.card(sample[1], { owned: false, size: "sm" }),
        K.card(sample[3], { size: "lg", href: "/plaza/card/RET-11" }), K.cash(80), K.cardLine(sample[1]))));
    grid.appendChild(box("K.swap", "what you give · what you get", K.swap([sample[0]], [], 80), el("div", { style: { height: "14px" } }), K.swap([], [sample[1]], -58),
      el("div", { style: { height: "14px" } }), K.swap([sample[2]], [sample[3]], 0)));
    grid.appendChild(box("K.statusBox · K.pill", "name + bordered label",
      el("div", { class: "kit-row", style: { alignItems: "flex-start" } },
        el("div", { style: { width: "184px" } }, K.statusBox([{ name: t("status.agent"), state: "connected" }, { name: t("status.market"), state: "open" }, { name: t("status.matchmaker"), state: "on" }])),
        el("div", { style: { width: "184px" } }, K.statusBox([{ name: t("status.agent"), state: "offline" }, { name: t("status.market"), state: "closed" }, { name: t("status.matchmaker"), state: "waiting" }])),
        el("div", { style: { width: "184px" } }, K.statusBox([{ name: t("status.agent"), state: "connected" }, { name: t("status.market"), state: "paused" }, { name: t("status.matchmaker"), state: "stale" }])))));
    grid.appendChild(box("K.btn · K.chip · K.id", "",
      el("div", { class: "kit-row" }, K.btn("Primary", { kind: "primary", iconAfter: "arrow" }), K.btn("Default", { icon: "copy" }), K.btn("Quiet", { kind: "quiet" }),
        K.btn("Danger", { kind: "danger" }), K.btn("Small", { small: true }), K.btn("Disabled", { disabled: true })),
      el("div", { class: "kit-row", style: { marginTop: "12px" } }, K.chip(t("state.proposed")), K.chip(t("state.offer_on_v07"), "signal"), K.chip(t("state.settled"), "ok"),
        K.chip(t("state.expired"), "warn"), K.chip(t("state.passed"), "bad"), K.id("m-ba346d6c75"), K.id("#20311"), K.id("t1446"))));
    grid.appendChild(K.panel({ title: "K.feed", note: "the agent's work, by tick", icon: "agent", flush: true },
      K.feed([{ tick: 1446, text: "Accepting offer #20311 from t05: LAV-09 for 80 P", now: true }, { tick: 1445, text: "Read 3 new proposals from the matchmaker" },
              { tick: 1444, text: "Countered at 80 P for LAV-09", extra: K.id("m-ba346d6c75") }])));
    const thread = grid.appendChild(box("K.thread", "fixed height, its own scroll"));
    API.get("/api/match/m-ba346d6c75").then((m) => {
      const many = [].concat(m.thread || [], m.thread || [], m.thread || [], m.thread || []);
      thread.querySelector(".panel-body").appendChild(K.thread(many, (m.thread && m.thread[0] || {}).team, { earlier: 9 }));
    }, () => thread.querySelector(".panel-body").appendChild(K.state("error")));
    grid.appendChild(K.panel({ title: "K.panel zones", note: "red: give · green: get" },
      el("div", { class: "kit-row", style: { alignItems: "stretch" } },
        K.panel({ title: "Available to sell & trade", note: "2 cards", icon: "give", zone: "give" }, el("div", { class: "card-strip" }, sample.slice(0, 2).map((c) => K.card(c)))),
        K.panel({ title: "Wanted", note: "2 cards", icon: "get", zone: "get" }, el("div", { class: "card-strip" }, sample.slice(2).map((c) => K.card(c, { owned: false })))))));
    grid.appendChild(box("K.kpis · K.table", "",
      K.kpis([{ label: "Deals on v07", value: K.num(41), sub: "23 from matches" }, { label: "Volume", value: K.price(1870) }, { label: "Fee", value: "0 %" }]),
      el("div", { style: { height: "12px" } }),
      K.table([{ key: "team", label: "Team", render: (r) => K.teamName(r.team) }, { key: "deals", label: "Deals", num: true }, { key: "volume", label: "Volume", num: true, render: (r) => K.price(r.volume) }],
              [{ team: "t16", deals: 6, volume: 310 }, { team: "t05", deals: 5, volume: 262 }])));
    grid.appendChild(box("K.state", "loading · empty · error · offline",
      el("div", { class: "kit-grid", style: { gridTemplateColumns: "1fr 1fr" } }, K.state("loading"), K.state("empty", null, "No trades yet"),
        K.state("error", null, "the market does not answer", K.btn(t("common.retry"), { small: true })), K.state("offline", t("shell.connectFirst")))));
    grid.appendChild(box("K.icon", "line icons, stroke 1.8, square caps",
      el("div", { class: "kit-icons" }, Object.keys(K.ICONS).map((n) => el("div", { class: "kit-icon" }, K.icon(n, 18), n)))));
    root.appendChild(K.endpoint("GET /plaza/api/status", "GET /plaza/api/match/<id>", "mock: " + (API.mock || "off")));
  },
});
