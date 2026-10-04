// Venue v07: our venue as the game shows it. Read only: the fee and the description are changed by our bot with
// its game key, never from this page.
(function () {
  "use strict";
  const { el } = K;
  const A = window.ADM;

  Plaza.adminScreen("venue", {
    title: "nav.admin.venue",
    noOverlay: true,                                       // the panel is read with the game closed too
    render(root) {
      root.appendChild(A.head(t("nav.admin.venue"), t("admin.venue.sub")));
      root.appendChild(K.endpoint("GET /plaza/admin/api/venue"));
      const body = root.appendChild(el("div", { class: "adm-venue" }));
      const w = A.watch(body, "/admin/api/venue", (d) => {
        const v = d.venue || {};
        const n = (x) => (typeof x === "number" ? K.num(x) : t("admin.none"));
        body.appendChild(K.kpis([
          { label: t("admin.col.state"), value: v.status ? t("status." + v.status) : t("admin.none") },
          { label: t("common.fee"), value: typeof v.fee_bps === "number" ? K.num(v.fee_bps / 100) + " %" : t("admin.none") },
          { label: t("admin.venue.perCard"), value: K.price(v.fee_per_card) },
          { label: t("admin.col.deals"), value: n(v.trades) },
          { label: t("admin.col.volume"), value: K.price(v.volume) },
          { label: t("admin.col.traders"), value: n(v.traders), sub: t("admin.perf.pairs", { n: n(v.pairs) }) },
          { label: t("admin.venue.bond"), value: K.price(v.bond) },
        ]));
        const grid = body.appendChild(el("div", { class: "adm-grid adm-venue-mid" }));
        grid.appendChild(K.panel({ title: t("admin.venue.inGame"), icon: "venue", flush: true }, A.rows([
          [t("admin.venue.id"), v.venue || null],
          [t("admin.venue.name"), v.name || null],
          [t("admin.col.owner"), v.owner || null],
          [t("admin.venue.mechanism"), (v.rules || {}).mechanism || null],
          [t("admin.venue.description"), v.description || null],
          [t("admin.venue.opened"), K.tick(v.opened_tick)],
          [t("admin.venue.fees"), K.price(v.fees)],
          [t("admin.venue.pendingFee"), v.pending_fee === null || v.pending_fee === undefined ? t("admin.none") : JSON.stringify(v.pending_fee), v.pending_fee ? "warn" : null],
        ])));
        const url = d.public_url || "";
        grid.appendChild(K.panel({ title: t("admin.venue.address"), icon: "doc", flush: true }, A.rows([
          [t("admin.venue.public"), url || null],
          [t("admin.venue.agents"), url ? url + "/AGENTS.md" : null],
        ]), el("div", { class: "adm-actions adm-pad" },
          url ? K.btn(t("admin.venue.copyUrl"), { small: true, icon: "copy", onclick: () => K.copy(url) }) : null,
          url ? K.btn(t("admin.venue.copyAgents"), { small: true, icon: "copy", onclick: () => K.copy(url + "/AGENTS.md") }) : null),
          el("p", { class: "adm-note adm-pad" }, d.read_only ? t("admin.venue.readOnly") : "")));
        const others = d.others || [];
        body.appendChild(K.panel({ title: t("admin.venue.others"), note: t("admin.perf.venuesNote"), flush: true },
          others.length ? K.table([
            { label: t("admin.col.venue"), render: (x) => el("span", null, K.id(x.venue), " ", x.name || "") },
            { label: t("admin.col.owner"), render: (x) => (/^t\d\d$/.test(String(x.owner || "")) ? A.team(x.owner) : t("admin.house")) },
            { label: t("common.fee"), num: true, render: (x) => (typeof x.fee_bps === "number" ? K.num(x.fee_bps / 100) + " %" : "–") },
            { label: t("admin.col.deals"), num: true, render: (x) => K.num(x.trades || 0) },
            { label: t("admin.col.volume"), num: true, render: (x) => K.price(x.volume || 0) },
            { label: t("admin.col.traders"), num: true, render: (x) => K.num(x.traders || 0) },
          ], others) : K.state("empty", t("admin.noData"))));
        body.appendChild(K.panel({ title: t("admin.venue.rules"), note: t("admin.venue.rulesNote"), icon: "shield", flush: true }, A.rows([
          [t("admin.venue.rule1", { fee: typeof v.fee_bps === "number" ? K.num(v.fee_bps / 100) : "–" }), ""], [t("admin.venue.rule2"), ""], [t("admin.venue.rule3"), ""], [t("admin.venue.rule4"), ""], [t("admin.venue.rule5"), ""]])));
      });
      return w.stop;
    },
  });
})();
