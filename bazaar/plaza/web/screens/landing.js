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


  // ---- the animated demo: one deal from match to settled, the card flying into its slot, a page completing.
  // Everything here is a drawing with real cards of the catalog and is labelled "demo"; the counters stay real.
  const C = (ref, name, rarity, color) => ({ ref, name, rarity, color, art: "/plaza/art/" + ref + ".svg" });
  const SAL = "#2E86AB";
  const PAGE = [C("SAL-01", "Escaparate de Serrano", "common", SAL), C("SAL-02", "El Portero", "common", SAL), C("SAL-03", "Perrito con Abrigo", "common", SAL),
                C("SAL-04", "Café en Goya", "common", SAL), C("SAL-05", "Taxi Blanco", "common", SAL), C("SAL-06", "La Galería", "uncommon", SAL),
                C("SAL-07", "Mercado de la Paz", "uncommon", SAL), C("SAL-08", "Guantería Antigua", "uncommon", SAL), C("SAL-09", "El Marqués", "rare", SAL),
                C("SAL-10", "Museo Lázaro Galdiano", "rare", SAL)];
  // Two swaps of the same rarity; each one brings a card the page misses, the second one completes it.
  const DEALS = [{ gives: C("MAL-06", "Tienda de Discos", "uncommon", "#7B2CBF"), gets: PAGE[6] }, { gives: SAMPLE.gives, gets: PAGE[9] }];
  const STATES = ["proposed", "offer_on_v07", "accepted", "settled"];
  const DEMO_ROWS = [["t04", "t09", "SAL-10"], ["t02", "t13", "LAV-09"], ["t07", "t16", "RET-08"], ["t11", "t03", "MAL-06"], ["t05", "t14", "LAT-02"], ["t17", "t08", "SAL-07"]];
  const short = (ref) => String(ref).replace("-", " ");
  const still = () => { try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) { return false; } };

  /** Builds the stage, the page and the ticker; start() runs the loop and returns stop(). */
  function demo() {
    const seatA = el("div", { class: "landing-seat" }), seatB = el("div", { class: "landing-seat" });
    const talk = el("div", { class: "landing-talk", "aria-hidden": "true" });
    const states = el("ol", { class: "landing-states" }, STATES.map((k) => el("li", { class: "landing-state" }, t("state." + k))));
    const stage = el("div", { class: "landing-stage" },
      el("div", { class: "landing-stage-head" }, el("span", { class: "label" }, t("landing.anim.title")), el("span", { class: "chip" }, t("landing.anim.demo"))),
      el("div", { class: "landing-pair" },
        el("div", { class: "landing-side" }, K.label(t("landing.anim.agentA"), "give"), seatA),
        el("span", { class: "landing-swap" }, K.icon("swap", 22)),
        el("div", { class: "landing-side" }, K.label(t("landing.anim.agentB"), "get"), seatB)),
      talk, states);

    const count = el("span", { class: "landing-page-count num" });
    const done = el("span", { class: "landing-page-done" }, K.icon("check", 13), t("landing.anim.complete"));
    const news = el("span", { class: "landing-page-news" });
    const grid = el("div", { class: "landing-page-grid" });
    const page = el("section", { class: "landing-page", style: { "--set": SAL }, "aria-label": t("landing.anim.page") },
      el("div", { class: "landing-page-head" }, el("span", { class: "landing-page-name" }, t("landing.anim.page")), el("span", { class: "label" }, "SAL · 01–10"), count, news, done), grid);

    const tickerList = el("div", { class: "landing-ticker-list" });
    const tickerLabel = el("span", { class: "label" }, t("landing.ticker.demo"));
    const ticker = el("div", { class: "landing-ticker" }, el("div", { class: "landing-ticker-head" }, tickerLabel), tickerList);

    let owned = new Set();
    function drawPage(missing) {
      owned = new Set(PAGE.map((c) => c.ref).filter((r) => !missing.includes(r)));
      K.clear(grid);
      K.add(grid, PAGE.map((c) => el("div", { class: "landing-slot", "data-ref": c.ref }, K.card(c, { owned: owned.has(c.ref), size: "fluid" }),
        el("span", { class: "landing-slot-ref" }, short(c.ref)))));
      drawCount();
    }
    function drawCount() {
      count.textContent = t("landing.anim.count", { n: owned.size, of: PAGE.length });
      page.classList.toggle("is-complete", owned.size === PAGE.length);
    }
    function fill(c) {
      const slot = grid.querySelector('[data-ref="' + c.ref + '"]');
      if (!slot) return;
      const card = K.card(c, { size: "fluid" });
      card.classList.add("landing-pop");
      slot.replaceChild(card, slot.firstChild);
      owned.add(c.ref);
      news.textContent = t("landing.anim.joined", { card: c.name + " (" + short(c.ref) + ")" });
      drawCount();
    }
    function seat(d) {
      K.clear(seatA).appendChild(K.card(d.gives, { size: "fluid" }));
      K.clear(seatB).appendChild(K.card(d.gets, { size: "fluid" }));
    }
    function setState(i) { [...states.children].forEach((li, k) => { li.classList.toggle("is-on", k <= i); li.classList.toggle("is-now", k === i); }); }
    function say(who, text) {
      K.clear(talk);
      if (text) talk.appendChild(el("span", { class: "landing-say is-" + who }, K.icon("agent", 12), el("b", null, t("landing.anim.agent" + who.toUpperCase())), el("span", null, text)));
    }
    function row(r, real) {
      const node = el("div", { class: "landing-tick-row" }, el("span", { class: "landing-tick-teams" }, r[0] + " ⇄ " + r[1]), el("span", null, short(r[2])),
        el("span", { class: "landing-tick-ok" }, t("state.settled").toLowerCase()), el("span", { class: "landing-tick-t" }, typeof r[3] === "number" ? K.tick(r[3]) : ""));
      tickerList.appendChild(node);
      while (tickerList.children.length > 4) tickerList.removeChild(tickerList.firstChild);
      if (real) tickerLabel.textContent = t("landing.ticker.real");
    }

    function start() {
      let stopped = false, rows = DEMO_ROWS.map((r) => r.slice()), real = false, at = 0;
      // Time that only runs while the tab is seen.
      const wait = (ms) => new Promise((res) => {
        let left = ms, last = performance.now();
        (function step() {
          if (stopped) return;
          const now = performance.now();
          if (!document.hidden) left -= Math.min(now - last, 120);
          last = now;
          if (left <= 0) res(); else setTimeout(step, 40);
        })();
      });
      const baseTick = () => ((window.Plaza.state.status || {}).tick || 1500);

      // Real deals closed on v07 replace the demo rows when there are any.
      API.get("/api/floor").then((d) => {
        const got = ((d && d.items) || []).filter((it) => it && it.team && it.to && it.ref && ((it.src === "plaza" && it.kind === "match" && it.state === "settled")
          || (it.src === "game" && it.kind === "deal" && it.venue === "v07" && !it.dealer))).slice(-6).map((it) => [it.team, it.to, it.ref, it.tick]);
        if (got.length && !stopped) { rows = got; real = true; at = 0; K.clear(tickerList); got.slice(-3).forEach((r) => row(r, true)); }
      }, () => {});

      if (still()) {                                   // no motion asked: the last frame, drawn once
        const d = DEALS[DEALS.length - 1];
        drawPage([]); seat({ gives: d.gets, gets: d.gives }); setState(3);
        say("b", t("landing.anim.say2"));
        news.textContent = t("landing.anim.joined", { card: d.gets.name + " (" + short(d.gets.ref) + ")" });
        rows.slice(0, 3).forEach((r, i) => row(real ? r : [...r, baseTick() - 3 + i], real));
        return () => { stopped = true; };
      }

      (async function tickerLoop() {
        while (!stopped) {
          const r = rows[at++ % rows.length];
          row(real ? r : [r[0], r[1], r[2], baseTick()], real);
          await wait(2400);
        }
      })();

      (async function loop() {
        while (!stopped) {
          drawPage(DEALS.map((d) => d.gets.ref));
          news.textContent = "";
          for (const d of DEALS) {
            if (stopped) return;
            stage.classList.remove("is-out"); seat(d); setState(0); say(null);
            const a = seatA.firstChild, b = seatB.firstChild;
            await wait(900);
            say("a", t("landing.anim.say1", { a: short(d.gives.ref), b: short(d.gets.ref) }));
            await wait(1100);
            say("b", t("landing.anim.say2"));
            await wait(900);
            setState(1); say("a", t("landing.anim.say3"));
            await wait(900);
            setState(2);
            const dx = seatB.getBoundingClientRect().left - seatA.getBoundingClientRect().left;       // the cards cross
            a.style.transform = "translateX(" + dx + "px)"; b.style.transform = "translateX(" + (-dx) + "px)";
            await wait(800);
            setState(3); say(null);
            await wait(500);
            const slot = grid.querySelector('[data-ref="' + d.gets.ref + '"]');                         // the card received flies to its slot
            if (slot) {
              const from = b.getBoundingClientRect(), to = slot.firstChild.getBoundingClientRect();
              b.classList.add("is-flying");
              b.style.transform = "translate(" + (-dx + to.left - from.left) + "px," + (to.top - from.top) + "px) scale(" + (to.width / from.width) + ")";
              await wait(820);
              if (stopped) return;
              fill(d.gets);
              b.style.opacity = "0";
            }
            await wait(owned.size === PAGE.length ? 2200 : 900);
            stage.classList.add("is-out");
            await wait(380);
          }
        }
      })();
      return () => { stopped = true; };
    }
    return { stage, page, ticker, start };
  }

  /** Steps and reasons come in as they are scrolled to. Without motion, or without the observer, they are just there. */
  function reveal(nodes) {
    if (still() || !("IntersectionObserver" in window)) return () => {};
    const io = new IntersectionObserver((entries) => entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("is-in"); io.unobserve(e.target); } }), { threshold: 0.15 });
    nodes.forEach((n, i) => { n.classList.add("landing-reveal"); n.style.transitionDelay = (i % 4) * 70 + "ms"; io.observe(n); });
    return () => io.disconnect();
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

      const D = demo();
      const hero = el("section", { class: "landing-hero" },
        el("div", { class: "landing-hero-text" },
          el("h1", { class: "landing-title" }, t("landing.title1"), el("br"), t("landing.title2"), el("br"), t("landing.title3")),
          cta,
          el("p", { class: "landing-note" }, t("landing.note"))),
        el("div", { class: "landing-right" }, D.stage, D.ticker));

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

      K.add(root, [el("div", { class: "landing-top" }, hero, D.page, steps), whyBox, foot,
        el("div", { class: "landing-end" }, K.endpoint("GET /plaza/api/stats", "POST /plaza/api/connect/start"))]);

      // What has really happened on v07 so far; nothing is shown when the market does not answer.
      API.get("/api/stats").then((s) => {
        if (!s || typeof s.deals !== "number") return;
        live.textContent = t(s.deals === 1 ? "landing.live1" : "landing.live", { deals: K.num(s.deals), teams: K.num(s.teams_connected || 0) });
      }, () => {});

      const stopDemo = D.start();
      const stopReveal = reveal([...steps.children, ...whyBox.querySelectorAll(".landing-arg")]);
      return () => { stopDemo(); stopReveal(); };
    },
  });
})();
