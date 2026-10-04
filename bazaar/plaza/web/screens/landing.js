// landing: the first page a team sees. Hero, the three steps and why to close deals here (variant A).
// It also keeps the pieces Connect and How it works share with it (window.F1).
(function () {
  "use strict";
  const { el } = K;

  // Two real cards of the catalog, to draw what a trade is. No team is named: nobody has connected yet.
  const SAMPLE = {
    gives: { ref: "LAV-09", name: "Cine Doré", rarity: "rare", color: "#E4572E", art: "/plaza/art/LAV-09.svg" },
    wants: { ref: "SAL-10", name: "Museo Lázaro Galdiano", rarity: "rare", color: "#2E86AB", art: "/plaza/art/SAL-10.svg" },
  };

  /** The four reasons, each one something the code keeps (SCORING.md, "Arguments we can state"). */
  function why() {
    const items = [["zero", "fee"], ["trend", "gain"], ["lock", "private"], ["agent", "agent"]];
    return el("div", { class: "landing-why-in" },
      el("div", { class: "landing-why-grid" }, items.map(([ic, k]) => el("div", { class: "landing-arg" },
        K.icon(ic, 18),
        el("div", { class: "landing-arg-big" }, t("landing.why." + k + ".big")),
        el("div", { class: "landing-arg-title" }, t("landing.why." + k + ".title")),
        el("p", { class: "landing-arg-text" }, t("landing.why." + k + ".text"))))),
      el("p", { class: "landing-also" }, t("landing.why.also")));
  }

  /** The bare header of the pages without the side nav: brand, what the page is, something on the right. */
  function head(sub, ...right) {
    return el("header", { class: "f1-head" },
      K.link("/plaza/", { class: "brand" }, el("span", { class: "brand-mark" }, "M"), el("span", { class: "brand-name" }, "v07 Market"),
        sub ? el("span", { class: "label" }, sub) : null),
      el("div", { class: "f1-head-right" }, right));
  }

  function langSwitch() {
    return el("div", { class: "lang-switch", role: "group", "aria-label": t("shell.language") }, I18N.LANGS.map((l) =>
      el("button", { type: "button", class: l === I18N.lang ? "active" : null, "aria-pressed": String(l === I18N.lang), onclick: () => I18N.setLang(l) }, l.toUpperCase())));
  }

  window.F1 = { why, head, langSwitch, SAMPLE };

  Plaza.screen("landing", {
    title: "nav.landing",
    noNav: true,
    noOverlay: true,
    render(root, ctx) {
      const connected = Boolean(ctx.me);
      const cta = connected
        ? K.btn(t("landing.enter"), { kind: "primary", iconAfter: "arrow", onclick: () => ctx.go("/plaza/home") })
        : K.btn(t("landing.connect"), { kind: "primary", icon: "agent", onclick: () => ctx.go("/plaza/connect") });
      cta.classList.add("landing-cta");

      const hero = el("section", { class: "landing-hero" },
        el("div", { class: "landing-hero-text" },
          el("h1", { class: "landing-title" }, t("landing.title1"), el("br"), t("landing.title2"), el("br"), t("landing.title3")),
          cta,
          el("p", { class: "landing-note" }, t("landing.note"))),
        el("div", { class: "landing-cards", "aria-hidden": "true" },
          el("div", { class: "landing-card" }, K.card(SAMPLE.gives, { size: "lg" }), K.label(t("landing.oneHas"), "give")),
          el("span", { class: "landing-swap" }, K.icon("swap", 22)),
          el("div", { class: "landing-card" }, K.card(SAMPLE.wants, { size: "lg" }), K.label(t("landing.otherHas"), "get"))));

      const steps = el("ol", { class: "landing-steps" }, [1, 2, 3].map((n) => el("li", { class: "landing-step" },
        el("span", { class: "landing-step-n" }, String(n)),
        el("div", null, el("div", { class: "landing-step-title" }, t("landing.step" + n)), el("div", { class: "landing-step-text" }, t("landing.step" + n + "Text"))))));

      const live = el("p", { class: "landing-live" });
      const whyBox = el("section", { class: "landing-why", "aria-labelledby": "landing-why-title" },
        el("div", { class: "landing-why-head" }, el("h2", { id: "landing-why-title", class: "landing-h2" }, t("landing.why.title")), live),
        why());

      const foot = el("footer", { class: "landing-foot" },
        K.link("/plaza/how", { class: "btn sm" }, K.icon("how", 13), t("nav.how")),
        K.link("/plaza/agents", { class: "btn sm" }, K.icon("doc", 13), "AGENTS.md"),
        K.link("/plaza/market", { class: "btn sm" }, K.icon("market", 13), t("nav.market")),
        K.link("/plaza/activity", { class: "btn sm" }, K.icon("activity", 13), t("nav.activity")),
        el("span", { class: "landing-foot-gap" }),
        langSwitch());

      K.add(root, [el("div", { class: "landing-top" }, hero, steps), whyBox, foot,
        el("div", { class: "landing-end" }, K.endpoint("GET /plaza/api/stats", "POST /plaza/api/connect/start"))]);

      // What has really happened on v07 so far; nothing is shown when the market does not answer.
      API.get("/api/stats").then((s) => {
        if (!s || typeof s.deals !== "number") return;
        live.textContent = t(s.deals === 1 ? "landing.live1" : "landing.live", { deals: K.num(s.deals), teams: K.num(s.teams_connected || 0) });
      }, () => {});
    },
  });
})();
