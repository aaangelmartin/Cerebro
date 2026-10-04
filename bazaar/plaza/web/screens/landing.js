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
      el("p", { class: "landing-hidden" }, t("landing.hidden")),
      el("p", { class: "landing-also" }, t("landing.why.also")),
      el("p", { class: "landing-rule" }, K.icon("warning", 13), t("landing.why.rule")));
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


  // ---- the animated demo: one deal from match to settled, the card received dropping into its slot, and a
  // different collection on every lap, each one at its own point. Everything here is a drawing with real cards of
  // the catalog and is labelled "demo"; the counters stay real.
  const SETS = {
    LAV: ["Lavapiés", "#E4572E", ["La Corrala", "El Frutero de Argumosa", "Té Moruno", "Mural de la Esquina", "Bici de Reparto", "La Tabacalera", "Samosas de la Plaza", "Teatro Valle-Inclán", "Cine Doré", "Fiesta de San Cayetano"]],
    MAL: ["Malasaña", "#7B2CBF", ["Vinilo de la Movida", "Plaza del Dos de Mayo", "Cartel de Conciertos", "El Tatuador", "Café de Madrugada", "Tienda de Discos", "Mercado de San Ildefonso", "La Vía Láctea", "La Heroína del Dos de Mayo", "Noche de Movida"]],
    SAL: ["Salamanca", "#2E86AB", ["Escaparate de Serrano", "El Portero", "Perrito con Abrigo", "Café en Goya", "Taxi Blanco", "La Galería", "Mercado de la Paz", "Guantería Antigua", "El Marqués", "Museo Lázaro Galdiano"]],
    LAT: ["La Latina", "#F4A259", ["Caña en la Cava Baja", "Puesto del Rastro", "Huevos Rotos", "Mercado de la Cebada", "El Organillero", "La Chulapa", "Vermut del Domingo", "Las Vistillas", "San Isidro", "El Mesón de la Cava"]],
    RET: ["El Retiro", "#3BB273", ["Barca del Estanque", "La Castañera", "El Titiritero", "Paseo de Coches", "La Ardilla", "La Rosaleda", "Fuente de la Alcachofa", "Palacio de Velázquez", "El Ángel Caído", "Monumento a Alfonso XII"]],
  };
  const RAR = (n) => (n <= 5 ? "common" : n <= 8 ? "uncommon" : "rare");
  const cardOf = (set, n) => { const ref = set + "-" + String(n).padStart(2, "0"); return { ref, name: SETS[set][2][n - 1], rarity: RAR(n), color: SETS[set][1], art: "/plaza/art/" + ref + ".svg" }; };
  // One collection at a time, until it is complete: the page starts with these slots empty and one deal after
  // another brings each card. The card given for it is the same number of the next collection (same rarity).
  const ORDER = ["SAL", "LAV", "MAL", "RET", "LAT"];
  const MISSING = { SAL: [3, 7, 10], LAV: [2, 5, 8, 9], MAL: [1, 6, 10], RET: [4, 7, 9], LAT: [2, 5, 6, 8] };
  const STATES = ["proposed", "offer_on_v07", "accepted", "settled"];
  const DEMO_ROWS = [["t04", "t09", "SAL-10"], ["t02", "t13", "LAV-09"], ["t07", "t16", "RET-08"], ["t11", "t03", "MAL-06"], ["t05", "t14", "LAT-02"], ["t17", "t08", "SAL-07"]];
  const short = (ref) => String(ref).replace("-", " ");
  const still = () => { try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) { return false; } };

  /** Builds the animation (the deal on top, the page under it, nothing boxed) and the ticker; start() runs the
   *  loop and returns stop(). */
  function demo() {
    const seatA = el("div", { class: "landing-seat" }), seatB = el("div", { class: "landing-seat" });
    // The four steps of a deal, as one line of nodes: done ones carry a check, the current one is lit.
    const states = el("ol", { class: "landing-steps4" }, STATES.map((k) => el("li", { class: "landing-s4" },
      el("span", { class: "landing-s4-node" }, K.icon("check", 11)), el("span", { class: "landing-s4-name" }, t("state." + k)))));
    // Each agent on its side of the deal: who it is, what it is doing and what it says.
    const agent = (side) => {
      const team = el("span", { class: "landing-agent-team" }), status = el("span", { class: "landing-agent-status" }), says = el("div", { class: "landing-agent-says", "aria-hidden": "true" });
      const node = el("div", { class: "landing-agent is-" + side },
        el("div", { class: "landing-agent-chip" }, K.icon("agent", 16), el("div", { class: "landing-agent-id" }, el("span", { class: "landing-agent-name" }, t("landing.anim.agent" + side.toUpperCase())), team), status), says);
      return { node, team, status, says };
    };
    const A = agent("a"), B = agent("b");
    const name = el("span", { class: "landing-page-name" }), count = el("span", { class: "landing-page-count num" });
    const done = el("span", { class: "landing-page-done" }, K.icon("check", 13), t("landing.anim.complete"));
    const news = el("span", { class: "landing-page-news" });
    const slots = Array.from({ length: 10 }, () => el("div", { class: "landing-slot" }));
    const page = el("div", { class: "landing-page" }, el("div", { class: "landing-page-head" }, name, count, news, done), el("div", { class: "landing-page-grid" }, slots));
    // Two panels, one over the other and of the same width: the deal and the page it feeds.
    const anim = el("div", { class: "landing-anim", role: "img", "aria-label": t("landing.anim.title") },
      el("div", { class: "landing-box landing-deal" },
        el("div", { class: "landing-deal-head" }, el("span", { class: "label" }, t("landing.anim.demo") + " · " + t("landing.anim.title")), states),
        A.node,
        el("div", { class: "landing-pair" }, seatA, el("span", { class: "landing-swap" }, K.icon("swap", 20)), seatB),
        B.node),
      el("div", { class: "landing-box" }, page));

    const tickerList = el("div", { class: "landing-ticker-list" });
    const tickerLabel = el("span", { class: "label" }, t("landing.ticker.demo"));
    const ticker = el("div", { class: "landing-ticker" }, el("div", { class: "landing-ticker-head" }, tickerLabel), tickerList);

    let owned = 0;
    function drawCount() {
      count.textContent = t("landing.anim.count", { n: owned, of: 10 });
      page.classList.toggle("is-complete", owned === 10);
    }
    /** Puts a collection on the page. The slots stay where they are; only what is inside them changes. */
    function drawPage(set, missing) {
      anim.style.setProperty("--set", SETS[set][1]);
      name.textContent = t("landing.anim.page", { set: SETS[set][0] }) + " · " + set;
      news.textContent = "";
      owned = 10 - missing.length;
      slots.forEach((slot, i) => {
        const c = cardOf(set, i + 1);
        K.clear(slot);
        K.add(slot, [K.card(c, { owned: !missing.includes(i + 1), size: "fluid" }), el("span", { class: "landing-slot-ref" }, short(c.ref)), el("span", { class: "landing-slot-name" }, c.name)]);
      });
      drawCount();
    }
    function fill(c, n) {
      const slot = slots[n - 1], card = K.card(c, { size: "fluid" });
      card.classList.add("landing-pop");
      slot.replaceChild(card, slot.firstChild);
      owned += 1;
      news.textContent = t("landing.anim.joined", { card: c.name + " (" + short(c.ref) + ")" });
      drawCount();
    }
    function seat(gives, gets) {
      const a = K.card(gives, { size: "fluid" }), b = K.card(gets, { size: "fluid" });
      a.classList.add("landing-enter"); b.classList.add("landing-enter");
      K.clear(seatA).appendChild(a); K.clear(seatB).appendChild(b);
      return [a, b];
    }
    function setState(i) {
      [...states.children].forEach((li, k) => { li.classList.toggle("is-done", k < i); li.classList.toggle("is-now", k === i); });
      anim.classList.toggle("is-settled", i === 3);
    }
    /** One agent speaks at a time; its line comes in next to its own chip. */
    function say(who, text) {
      K.clear(A.says); K.clear(B.says);
      if (who && text) (who === "a" ? A : B).says.appendChild(el("span", { class: "landing-say" }, text));
    }
    function status(a, b) { A.status.textContent = a ? t("landing.anim.st." + a) : ""; B.status.textContent = b ? t("landing.anim.st." + b) : ""; }
    function teams(b) { A.team.textContent = t("landing.anim.team", { n: 4 }); B.team.textContent = t("landing.anim.team", { n: b }); }
    function row(r, real) {
      tickerList.appendChild(el("div", { class: "landing-tick-row" }, el("span", { class: "landing-tick-teams" }, r[0] + " ⇄ " + r[1]), el("span", null, short(r[2])),
        el("span", { class: "landing-tick-ok" }, t("state.settled").toLowerCase()), el("span", { class: "landing-tick-t" }, typeof r[3] === "number" ? K.tick(r[3]) : "")));
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
      const demoRow = (back) => { const r = rows[at++ % rows.length]; return real ? r : [r[0], r[1], r[2], baseTick() - (back || 0)]; };

      for (let k = 4; k > 0; k--) row(demoRow(k), false);
      // Real deals closed on v07 replace the demo rows when there are any.
      API.get("/api/floor").then((d) => {
        const got = ((d && d.items) || []).filter((it) => it && it.team && it.to && it.ref && ((it.src === "plaza" && it.kind === "match" && it.state === "settled")
          || (it.src === "game" && it.kind === "deal" && it.venue === "v07" && !it.dealer))).slice(-6).map((it) => [it.team, it.to, it.ref, it.tick]);
        if (got.length && !stopped) { rows = got; real = true; at = 0; K.clear(tickerList); got.forEach((r) => row(r, true)); }
      }, () => {});

      if (still()) {                                   // no motion asked: a completed page, drawn once
        drawPage("SAL", []); seat(cardOf("LAV", 10), cardOf("SAL", 10)); setState(3); teams(9); status("settled", "settled"); say("a", t("landing.anim.say4"));
        news.textContent = t("landing.anim.joined", { card: cardOf("SAL", 10).name + " (SAL 10)" });
        return () => { stopped = true; };
      }

      (async function tickerLoop() {
        while (!stopped) { await wait(2600); if (!real || rows.length > 1) row(demoRow(0), real); }
      })();

      (async function loop() {
        let first = true, deals = 0;
        const BTEAMS = [9, 13, 16, 2, 7];
        while (!stopped) {
          for (let si = 0; si < ORDER.length; si++) {
            const set = ORDER[si], other = ORDER[(si + 1) % ORDER.length];
            if (first) { drawPage(set, MISSING[set]); first = false; }
            else {                                                       // the next collection: slot by slot out, then in
              anim.classList.add("is-turning");
              await wait(700);
              if (stopped) return;
              K.clear(seatA); K.clear(seatB);
              drawPage(set, MISSING[set]); setState(-1); say(null); status(null, null);
              anim.classList.remove("is-turning");
              await wait(500);
            }
            for (const n of MISSING[set]) {
              if (stopped) return;
              const gives = cardOf(other, n), gets = cardOf(set, n);
              const [a, b] = seat(gives, gets);
              teams(BTEAMS[deals++ % BTEAMS.length]);
              setState(0); say(null); status("matched", "matched");
              await wait(800);
              say("a", t("landing.anim.say1", { a: short(gives.ref), b: short(gets.ref) }));
              await wait(1300);
              say("b", t("landing.anim.say2"));
              await wait(1200);
              setState(1); say("a", t("landing.anim.say3")); status("posted", "matched");
              await wait(1200);
              setState(2); say("b", t("landing.anim.say5")); status("posted", "accepted");
              await wait(700);
              // The two cards cross: both lift, one passes in front and one behind along an arc, and each settles
              // on the other side's slot. The slots stay drawn, so it shows where each card came from.
              const dx = seatB.getBoundingClientRect().left - seatA.getBoundingClientRect().left;
              const lift = "0 22px 44px -10px rgba(0,0,0,.85)", flat = "0 0 0 0 rgba(0,0,0,0)", arc = Math.round(a.offsetHeight * 0.16);
              a.classList.remove("landing-enter"); b.classList.remove("landing-enter");
              a.style.zIndex = "46"; b.style.zIndex = "44";
              const opt = { duration: 1500, easing: "ease-in-out", fill: "forwards" };
              a.animate([{ transform: "none", boxShadow: flat }, { transform: "translate(0," + (-arc / 3) + "px) scale(1.07)", boxShadow: lift, offset: 0.18 },
                         { transform: "translate(" + dx / 2 + "px," + (-arc) + "px) scale(1.1)", boxShadow: lift, offset: 0.5 },
                         { transform: "translate(" + dx + "px," + (-arc / 4) + "px) scale(1.05)", boxShadow: lift, offset: 0.84 },
                         { transform: "translate(" + dx + "px,3px) scale(.99)", boxShadow: flat, offset: 0.94 }, { transform: "translate(" + dx + "px,0)", boxShadow: flat }], opt);
              b.animate([{ transform: "none", boxShadow: flat }, { transform: "translate(0," + arc / 3 + "px) scale(1.02)", boxShadow: lift, offset: 0.18 },
                         { transform: "translate(" + (-dx / 2) + "px," + arc + "px) scale(.9)", boxShadow: lift, offset: 0.5 },
                         { transform: "translate(" + (-dx) + "px," + arc / 4 + "px) scale(1.03)", boxShadow: lift, offset: 0.84 },
                         { transform: "translate(" + (-dx) + "px,3px) scale(.99)", boxShadow: flat, offset: 0.94 }, { transform: "translate(" + (-dx) + "px,0)", boxShadow: flat }], opt);
              await wait(1560);
              setState(3); say("a", t("landing.anim.say4")); status("settled", "settled");
              await wait(600);
              // And the one received goes on to its slot on the page, leaving its slot of the deal empty.
              const from = b.getBoundingClientRect(), to = slots[n - 1].firstChild.getBoundingClientRect();
              const tx = -dx + (to.left + to.width / 2) - (from.left + from.width / 2), ty = (to.top + to.height / 2) - (from.top + from.height / 2), k = to.width / from.width;
              b.style.zIndex = "48";
              b.animate([{ transform: "translate(" + (-dx) + "px,0)", boxShadow: flat }, { transform: "translate(" + (-dx) + "px," + (-arc / 2) + "px) scale(1.06)", boxShadow: lift, offset: 0.2 },
                         { transform: "translate(" + tx + "px," + ty + "px) scale(" + k * 1.08 + ")", boxShadow: lift, offset: 0.9 },
                         { transform: "translate(" + tx + "px," + ty + "px) scale(" + k + ")", boxShadow: flat }], { duration: 1150, easing: "ease-in-out", fill: "forwards" });
              await wait(1160);
              if (stopped) return;
              fill(gets, n);
              b.remove();
              await wait(owned === 10 ? 2800 : 900);
              a.classList.add("is-leaving");
              await wait(320);
            }
          }
        }
      })();
      return () => { stopped = true; };
    }
    return { anim, ticker, start };
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

      const steps = el("ol", { class: "landing-steps" }, [1, 2, 3].map((n) => el("li", { class: "landing-step" },
        el("span", { class: "landing-step-n" }, String(n)),
        el("div", null, el("div", { class: "landing-step-title" }, t("landing.step" + n)), el("div", { class: "landing-step-text" }, t("landing.step" + n + "Text"))))));
      const D = demo();
      const hero = el("section", { class: "landing-hero" },
        el("div", { class: "landing-hero-text" },
          el("h1", { class: "landing-title" }, t("landing.title1"), el("br"), t("landing.title2"), el("br"), t("landing.title3")),
          cta,
          el("p", { class: "landing-note" }, t("landing.note"))),
        D.anim,
        el("div", { class: "landing-under" }, steps, D.ticker));


      const live = el("p", { class: "landing-live" });
      const whyBox = el("section", { class: "landing-why", "aria-labelledby": "landing-why-title" },
        el("div", { class: "landing-why-head" }, el("h2", { id: "landing-why-title", class: "landing-h2" }, t("landing.why.title")), live),
        why());

      const foot = el("footer", { class: "landing-foot" },
        K.link("/plaza/how", { class: "btn sm" }, K.icon("how", 13), t("nav.how")),
        K.link("/plaza/agents", { class: "btn sm" }, K.icon("doc", 13), "AGENTS.md"),
        K.link("/plaza/board", { class: "btn sm" }, K.icon("performance", 13), t("nav.board")),
        K.link("/plaza/market", { class: "btn sm" }, K.icon("market", 13), t("nav.market")),
        K.link("/plaza/activity", { class: "btn sm" }, K.icon("activity", 13), t("nav.activity")),
        el("span", { class: "landing-foot-gap" }),
        langSwitch());

      K.add(root, [hero, whyBox, foot,
        el("div", { class: "landing-end" }, K.endpoint("GET /plaza/api/stats", "POST /plaza/api/connect/start"))]);

      // What has really happened on v07 so far; nothing is shown when the market does not answer.
      API.get("/api/stats").then((s) => {
        if (!s || typeof s.deals !== "number") return;
        live.textContent = t(s.deals === 1 ? "landing.live1" : "landing.live", { deals: K.num(s.deals), teams: K.num(s.teams_connected || 0) });
      }, () => {});

      const stopDemo = D.start();
      const stopReveal = reveal([...whyBox.querySelectorAll(".landing-arg")]);
      return () => { stopDemo(); stopReveal(); };
    },
  });
})();
