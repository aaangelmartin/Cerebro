// Trades: every match of every team, with its timeline in ticks and the full thread of the two agents.
(function () {
  "use strict";
  const { el } = K;
  const A = window.ADM;
  const STATES = ["proposed", "offer_on_v07", "accepted", "settled", "settled_elsewhere", "passed", "expired"];
  const STEPS = ["proposed", "offer_on_v07", "accepted", "settled"];

  function detail(m, again) {
    const cardOf = (m.sides || []).flatMap((s) => s.gives || []);
    const step = STEPS.indexOf(m.state), dead = step < 0;
    const when = (s) => (s === "proposed" ? m.proposed_tick : s === "settled" ? m.settled_tick : s === m.state ? m.state_tick : null);
    return K.panel({ title: m.id + " · " + (m.seller || "") + " → " + (m.buyer || "") + " · " + (m.ref || ""), note: m.kind === "sale" ? K.price(m.price) : t("admin.kind." + m.kind), flush: true },
      el("div", { class: "adm-trades-top" },
        el("div", { class: "card-row" }, cardOf.map((c) => K.card(c, { size: "md" })), m.kind === "sale" && typeof m.price === "number" ? K.cash(m.price, "md") : null),
        el("div", { class: "adm-trades-ids" }, A.stateChip(m.state), m.stalled ? K.chip(t("admin.trades.stalled"), "warn") : null, m.last_of_page ? K.chip(t("admin.trades.lastOfPage"), "signal") : null,
          K.id(t("admin.trades.venue", { v: m.settled_venue || m.venue || "v07" })), m.offer ? K.id(t("admin.trades.offer", { n: m.offer })) : null,
          m.settlement ? K.id(t("admin.trades.settlement", { n: m.settlement })) : null)),
      el("div", { class: "adm-trades-sides" }, (m.sides || []).map((s) => el("div", null, A.team(s.team), " ",
        (s.gives || []).length ? t("admin.trades.gives", { cards: s.gives.map((c) => c.ref).join(", ") }) : "",
        typeof s.pays === "number" ? t("admin.trades.pays", { p: K.price(s.pays) }) : "", typeof s.receives_cash === "number" ? " · " + t("admin.trades.gets", { p: K.price(s.receives_cash) }) : ""))),
      K.label(t("admin.trades.timeline"), "adm-sub"),
      el("div", { class: "adm-steps" + (dead ? " is-dead" : "") }, STEPS.map((s, i) => el("div", { class: "adm-step" + (!dead && i < step ? " is-done" : "") + (!dead && i === step ? " is-now" : "") },
        el("span", null, t("state." + s)), el("span", { class: "adm-step-tick" }, K.tick(when(s))))),
        dead ? el("div", { class: "adm-step is-now is-end" }, el("span", null, t("state." + m.state)), el("span", { class: "adm-step-tick" }, K.tick(m.state_tick))) : null),
      K.label(t("admin.trades.thread", { n: (m.thread || []).length }), "adm-sub"),
      (m.thread || []).length ? el("div", { class: "adm-trades-thread" }, K.thread(m.thread, m.seller)) : el("div", { class: "adm-quiet" }, t("admin.trades.noThread")),
      A.rows([
        [t("admin.col.limits"), A.limits(m.overlap)],
        [t("admin.col.why"), m.why || null],
        [t("admin.col.suggested"), m.kind === "sale" ? K.price(m.suggested) : null],
        [t("admin.trades.saves"), typeof m.saves === "number" ? K.price(m.saves) : null],
      ]),
      el("div", { class: "adm-actions adm-pad" },
        STEPS.indexOf(m.state) >= 0 && m.state !== "settled" ? A.actBtn(t("admin.mm.expire"), { action: "expire", match: m.id }, again, { confirm: true }) : null,
        (m.thread || []).map((x) => A.actBtn(t("admin.trades.hideMsg", { n: x.n }), { action: "hide", match: m.id, message: x.n }, again, { confirm: true }))));
  }

  Plaza.adminScreen("trades", {
    title: "nav.admin.trades",
    noOverlay: true,                                       // the panel is read with the game closed too
    render(root, ctx) {
      const pick = { state: ctx.query.state || "", team: ctx.query.team || "", match: ctx.query.match || "" };
      root.appendChild(A.head(t("nav.admin.trades"), t("admin.trades.sub")));
      root.appendChild(K.endpoint("GET /plaza/admin/api/trades?state=&team=", "POST /plaza/admin/api/action {expire | hide}"));
      const filters = root.appendChild(el("div", { class: "adm-strip" }));
      const body = root.appendChild(el("div", { class: "adm-trades adm-grid" }));
      const again = () => w.again();
      const drawFilters = (counts) => {
        K.clear(filters);
        K.add(filters, [K.label(t("admin.col.state")), el("div", { class: "adm-seg", role: "group" }, [""].concat(STATES).map((s) => el("button", { type: "button", class: pick.state === s ? "active" : null, "aria-pressed": String(pick.state === s),
          onclick: () => { pick.state = s; drawFilters(counts); again(); } }, s ? t("state." + s) : t("common.all"), s && counts && typeof counts[s] === "number" ? el("span", { class: "adm-seg-n" }, String(counts[s])) : null))),
          pick.team ? K.btn(pick.team + " ×", { small: true, onclick: () => { pick.team = ""; drawFilters(counts); again(); } }) : null]);
      };
      drawFilters(null);
      const w = A.watch(body, "/admin/api/trades", (d) => {
        drawFilters(d.counts);
        // The mock answers every query with the same file, so the filter is applied here as well.
        const all = (d.trades || []).filter((m) => (!pick.state || m.state === pick.state) && (!pick.team || (m.teams || []).includes(pick.team)));
        if (!all.length) { body.appendChild(K.state("empty", t("admin.trades.empty"), t("admin.trades.emptyText"))); return; }
        const sel = all.find((m) => m.id === pick.match) || all[0];
        body.appendChild(K.panel({ title: t("admin.trades.all"), note: t("admin.trades.allNote", { n: all.length, total: K.num(d.total || all.length) }), flush: true },
          el("div", { class: "adm-list" }, all.map((m) => el("button", { type: "button", class: "adm-list-row" + (m.id === sel.id ? " active" : ""), onclick: () => { pick.match = m.id; w.redraw(); } },
            K.id(m.id), A.pair(m.seller, m.buyer, m.kind !== "sale"), el("span", { class: "adm-ref" }, m.ref || ""), el("span", { class: "num" }, m.kind === "sale" ? K.price(m.price) : t("admin.kind." + m.kind)),
            A.stateChip(m.state), el("span", { class: "adm-list-tick" }, K.tick(m.state_tick)))))));
        body.appendChild(detail(sel, again));
      }, () => ({ state: pick.state, team: pick.team }));
      return w.stop;
    },
  });
})();
