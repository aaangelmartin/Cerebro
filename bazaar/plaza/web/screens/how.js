// how: how everything works, on one page. Right after Connect (?first=1) it is shown once with nothing behind it and
// ends in "Enter the market"; from the side nav it opens inside the app; a visitor reads it in the public frame.
(function () {
  "use strict";
  const { el } = K;
  const C = (ref, name, rarity, color) => ({ ref, name, rarity, color, art: "/plaza/art/" + ref + ".svg" });
  // Cards of the catalog used as drawings when the team's own lists are not there yet.
  const GIVE = [C("LAV-09", "Cine Doré", "rare", "#E4572E"), C("LAT-11", "San Francisco el Grande", "epic", "#F4A259"),
                C("SAL-04", "Café en Goya", "common", "#2E86AB"), C("RET-01", "Barca del Estanque", "common", "#3BB273")];
  const WANT = [C("SAL-10", "Museo Lázaro Galdiano", "rare", "#2E86AB"), C("LAV-10", "Fiesta de San Cayetano", "rare", "#E4572E"),
                C("SAL-08", "Guantería Antigua", "uncommon", "#2E86AB"), C("LAT-06", "La Chulapa", "uncommon", "#F4A259")];
  const SEEN_KEY = "plaza.how.seen";

  function section(n, title, text, ...body) {
    return el("section", { class: "how-sec", "aria-labelledby": "how-h" + n },
      el("h2", { class: "how-h", id: "how-h" + n }, el("span", { class: "how-n" }, String(n)), title),
      text ? el("p", { class: "how-p" }, text) : null, body);
  }

  Plaza.screen("how", {
    title: "nav.how",
    frame: ({ team, query }) => (team && query.first ? "bare" : "auto"),
    render(root, ctx) {
      const me = ctx.me, first = ctx.frame === "bare", inApp = ctx.frame === "app";
      try { localStorage.setItem(SEEN_KEY, "1"); } catch (e) { /* private window */ }
      const enter = (big) => {
        const b = inApp ? K.btn(t("nav.home"), { iconAfter: big ? "arrow" : null, onclick: () => ctx.go("/plaza/home") })     // already inside: no way out, just Home
                : me ? K.btn(t("how.enter"), { kind: "primary", iconAfter: big ? "arrow" : null, onclick: () => ctx.go("/plaza/home") })
                     : K.btn(t("landing.connect"), { kind: "primary", icon: "agent", onclick: () => ctx.go("/plaza/connect") });
        if (big) b.classList.add("how-enter");
        return b;
      };

      // Only the first time, with nothing behind, the page draws its own head; otherwise the frame has one.
      if (first) root.appendChild(F1.head(t("nav.how"),
        el("span", { class: "how-who" }, el("span", { class: "how-dot" }), t("how.who", { name: me.name || K.teamName(me.team), team: me.team })),
        enter(false)));

      const body = root.appendChild(el("div", { class: "how-body" }));
      body.appendChild(el("div", { class: "how-top" },
        el("h1", { class: "how-title" }, me ? t("how.title1") : t("how.title1Out"), el("br"), t("how.title2")),
        el("p", { class: "how-lead" }, t("how.lead"))));

      // 1. what the agent does: the two lists
      const giveStrip = el("div", { class: "card-strip" }, GIVE.map((c) => K.card(c, { size: "md" })));
      const wantStrip = el("div", { class: "card-strip" }, WANT.map((c) => K.card(c, { owned: false, size: "md" })));
      body.appendChild(section(1, t("how.s1.title"), t("how.s1.text"),
        el("div", { class: "how-zones" },
          K.panel({ title: t("how.s1.give"), icon: "give", zone: "give" }, giveStrip),
          K.panel({ title: t("how.s1.want"), icon: "get", zone: "get" }, wantStrip)),
        el("p", { class: "how-fine" }, K.icon("lock", 13), t("common.private"))));

      // 2. how you get matched
      body.appendChild(section(2, t("how.s2.title"), t("how.s2.text"),
        el("div", { class: "how-box how-match" },
          el("div", { class: "how-match-cards" },
            el("div", { class: "how-match-card" }, K.label(t("how.s2.wants"), "get"), K.card(WANT[0], { owned: false, size: "md" })),
            el("span", { class: "how-swap" }, K.icon("swap", 18)),
            el("div", { class: "how-match-card" }, K.label(t("how.s2.has"), "give"), K.card(WANT[0], { size: "md" }))),
          el("ul", { class: "how-list" }, ["last", "dear", "sale", "swap", "gain"].map((k) => el("li", null, K.icon("check", 13), t("how.s2." + k)))))));

      // 3. negotiated and closed on v07
      const bubble = (side, who, text) => el("div", { class: "how-bubble is-" + side }, K.icon("agent", 12), el("span", { class: "how-bubble-who" }, who), el("span", null, text));
      const steps = ["proposed", "offer_on_v07", "accepted", "settled"];
      body.appendChild(section(3, t("how.s3.title"), t("how.s3.text"),
        el("div", { class: "how-box how-deal" },
          el("div", { class: "how-talk", "aria-hidden": "true" },
            bubble("a", t("how.s3.seller"), "62 P"), bubble("b", t("how.s3.buyer"), "55 P"),
            bubble("a", t("how.s3.seller"), "58 P"), bubble("b", t("how.s3.buyer"), "58 P · " + t("how.s3.deal"))),
          el("ol", { class: "how-states" }, steps.map((s, i) => el("li", { class: "how-state" + (i === 1 ? " is-now" : "") },
            el("span", { class: "how-state-name" }, t("state." + s)), el("span", { class: "how-state-sub" }, t("how.s3.st." + s)))))),
        el("p", { class: "how-fine" }, K.icon("alert", 13), t("how.s3.only"))));

      // 4. what you will see on each screen
      const screens = [["home", [GIVE[0]], []], ["cards", [GIVE[0]], [WANT[0]]], ["offers", [GIVE[2]], [WANT[2]]], ["activity", [], [WANT[3]]], ["market", [GIVE[1]], [WANT[1]]]];
      body.appendChild(section(4, t("how.s4.title"), t("how.s4.text"),
        el("div", { class: "how-screens" }, screens.map(([name, own, miss]) => el("div", { class: "how-screen" },
          el("div", { class: "how-screen-name" }, K.icon(name, 15), t("nav." + name)),
          el("p", { class: "how-screen-text" }, t("how.s4." + name)),
          el("div", { class: "how-screen-cards", "aria-hidden": "true" }, own.map((c) => K.card(c, { size: "sm" })), miss.map((c) => K.card(c, { owned: false, size: "sm" }))))))));

      // 5. why
      body.appendChild(section(5, t("landing.why.title"), t("how.s5.text"), el("div", { class: "how-why" }, F1.why())));

      // the end
      const counts = el("p", { class: "how-end-sub" }, t("how.end.again"));
      body.appendChild(el("div", { class: "how-end" },
        el("div", null, el("div", { class: "how-end-title" }, me ? t("how.end.title") : t("how.end.titleOut")), counts), enter(true)));
      body.appendChild(el("div", { class: "how-foot" }, K.endpoint("GET /plaza/api/me", "GET /plaza/AGENTS.md"), first ? F1.langSwitch() : null));

      if (me && me.counts) {
        const c = me.counts, live = me.trades ? (me.trades.proposed || 0) + (me.trades.offer_on_v07 || 0) + (me.trades.accepted || 0) : 0;
        counts.textContent = t("how.end.counts", { sell: K.num((c.for_sale || 0) + (c.duplicates || 0)), want: K.num(c.want || 0), live: K.num(live) }) + " · " + t("how.end.again");
      }

      // The team's own lists replace the drawings as soon as they are there.
      let left = false;
      if (me) {
        API.get("/api/me/cards").then((d) => {
          if (left || !d) return;
          const own = (d.have || []).filter((c) => c && c.ref && (c.as === "for_sale" || c.as === "duplicate")).slice(0, 4);
          const want = (d.want || []).filter((c) => c && c.ref).slice(0, 4);
          if (own.length) K.add(K.clear(giveStrip), own.map((c) => K.card(c, { size: "md" })));
          if (want.length) K.add(K.clear(wantStrip), want.map((c) => K.card(c, { owned: false, size: "md" })));
        }, () => {});
      }
      return () => { left = true; };
    },
  });
})();
