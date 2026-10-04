// offers: every trade the team's agent runs, and one of them in full: the cards, both agents, the steps in ticks
// and the negotiation in a box of fixed height that scrolls by itself. The orders at the bottom are optional.
Plaza.screen("offers", {
  title: "nav.offers", needsTeam: true,
  render(root, ctx) {
    const { el } = K;
    const LIVE = ["proposed", "offer_on_v07", "accepted"];
    const TONE = { proposed: null, offer_on_v07: "signal", accepted: "signal", settled: "ok", passed: "bad", expired: "warn", settled_elsewhere: "bad" };
    const STEPS = ["matched", "negotiating", "offer_on_v07", "accepted", "settled"];
    const S = { me: ctx.me, data: null, sel: ctx.params.match || null, failed: false, busy: false, stats: null, counter: {} };
    const sig = {};
    const team = () => S.me.team;
    const status = () => Plaza.state.status || ctx.status || {};

    const slot = (cls, parent) => (parent || root).appendChild(el("div", { class: cls }));
    const dom = { head: slot("offers-head"), api: slot("offers-api") };
    dom.grid = slot("offers-grid");
    dom.list = slot("offers-list", dom.grid);
    dom.detail = slot("offers-detail", dom.grid);
    dom.api.appendChild(K.endpoint("GET /plaza/api/me/trades", "GET /plaza/api/agent/next", "POST /plaza/api/me/trade/<match> {mode | order, price}",
                                   "POST /plaza/api/match/<match>/message"));
    dom.list.appendChild(K.state("loading"));

    function draw(name, key, build) {
      const k = JSON.stringify(key);
      if (sig[name] === k) return false;
      sig[name] = k;
      K.clear(dom[name]);
      K.add(dom[name], [build()]);
      return true;
    }
    const other = (tr) => (tr.teams || []).find((x) => x !== team()) || (tr.your_role === "seller" ? tr.buyer : tr.seller);
    const trades = () => {
      const all = (S.data && S.data.trades) || [];
      const rank = (x) => (LIVE.includes(x.state) ? 0 : 1);
      return all.slice().sort((a, b) => rank(a) - rank(b) || (b.state_tick || 0) - (a.state_tick || 0));
    };
    const selected = () => { const all = trades(); return all.find((x) => x.id === S.sel) || all[0] || null; };
    /** "LAV-09 for 80 P" or "MAL-06 for RET-11" */
    function what(tr) {
      const g = (tr.gives || []).map((c) => c.ref), r = (tr.receives || []).map((c) => c.ref);
      const card = (r.length ? r : g).join(" + ");
      if (g.length && r.length) return t("offers.swapFor", { give: g.join(" + "), get: r.join(" + ") });
      return t("offers.cardFor", { card, price: K.price(tr.price) });
    }
    /** What the team's agent does next, in one line. */
    function mine(tr) {
      if (status().agent === "offline" && LIVE.includes(tr.state)) return t("offers.waitingAgent");
      if (tr.next && tr.next.why) return K.say(tr.next.why);
      if (tr.next && tr.next.waiting) return K.say(tr.next.waiting);
      return tr.state === "settled" ? t("offers.done") : t("state." + tr.state);
    }
    /** The last thing the other agent said. */
    function theirs(tr) {
      const o = other(tr), th = tr.thread || [];
      for (let i = th.length - 1; i >= 0; i--) {
        if (th[i].team !== o) continue;
        const m = th[i];
        return t("action." + (m.action || "note")) + (typeof m.price === "number" ? " " + K.price(m.price) : "") + " · " + K.tick(m.tick);
      }
      return tr.state === "settled" ? t("offers.done") : t("offers.silent");
    }

    function drawHead() {
      const all = trades(), run = all.filter((x) => LIVE.includes(x.state)).length, done = all.filter((x) => x.state === "settled").length;
      const mode = (S.me.settings && S.me.settings.default_mode) || (S.me.agent && S.me.agent.default_mode) || "auto";
      draw("head", [run, done, mode, I18N.lang], () => el("header", { class: "page-head" },
        el("div", { class: "offers-title" }, el("h1", { class: "page-title" }, t("nav.offers")), el("p", { class: "page-sub" }, t("offers.sub"))),
        el("div", { class: "offers-kpis" },
          el("div", null, K.label(t("offers.kpi.running")), el("b", { class: "num" }, t(run === 1 ? "offers.trades1" : "offers.trades", { n: run }))),
          el("div", null, K.label(t("offers.kpi.settled")), el("b", { class: "num" }, String(done))),
          el("div", null, K.label(t("offers.kpi.agent")), el("b", null, t("offers.mode." + mode))))));
    }

    function listItem(tr) {
      const o = other(tr), on = selected() && selected().id === tr.id;
      const side = (cards, money, owned) => el("div", { class: "offers-mini" }, (cards || []).slice(0, 2).map((c) => K.card(c, { owned, size: "sm" })), money ? K.cash(money, "sm") : null);
      return el("a", { class: "offers-item" + (on ? " active" : "") + (LIVE.includes(tr.state) ? "" : " is-done"), href: "/plaza/offers/" + tr.id,
                       "aria-current": on ? "true" : null, onclick: (e) => { if (e.metaKey || e.ctrlKey || e.shiftKey) return; e.preventDefault(); select(tr.id, true); } },
        el("div", { class: "offers-item-top" },
          side(tr.gives, tr.cash < 0 ? -tr.cash : 0, true), el("span", { class: "offers-arrow" }, K.icon("swap", 14)), side(tr.receives, tr.cash > 0 ? tr.cash : 0, false),
          el("div", { class: "offers-item-who" }, el("div", null, el("b", null, K.teamName(o)), K.id(tr.id)),
            el("div", { class: "offers-item-state" }, K.chip(t("state." + tr.state), TONE[tr.state]), K.id(K.tick(tr.settled_tick || tr.state_tick))))),
        el("div", { class: "offers-item-agents" },
          el("span", { class: "offers-tag" }, K.icon("agent", 12), team()), el("span", { class: "offers-say" }, mine(tr)),
          el("span", { class: "offers-tag" }, K.icon("agent", 12), o), el("span", { class: "offers-say" }, theirs(tr))));
    }

    function drawList() {
      const all = trades(), sel = selected();
      draw("list", [all.map((x) => [x.id, x.state, x.state_tick, x.price, x.next, x.messages, (x.thread || []).length]), sel && sel.id, status().agent, I18N.lang],
        () => all.map(listItem));
    }

    function steps(tr) {
      const th = tr.thread || [], hist = {};
      (tr.history || []).forEach((h) => { hist[h.state] = h.tick; });
      const reached = { proposed: th.length ? 1 : 0, offer_on_v07: 2, accepted: 3, settled: 4 }[tr.state];
      const ended = reached === undefined;                       // passed, expired, closed elsewhere
      const at = ended ? (hist.accepted ? 3 : hist.offer_on_v07 ? 2 : th.length ? 1 : 0) : reached;
      const when = [K.tick(tr.proposed_tick),
        th.length ? (th[0].tick === th[th.length - 1].tick ? K.tick(th[0].tick) : K.tick(th[0].tick) + "–" + K.tick(th[th.length - 1].tick)) : "–",
        hist.offer_on_v07 ? K.tick(hist.offer_on_v07) : at === 2 ? K.tick(tr.state_tick) : at > 2 ? "" : "–",
        hist.accepted ? K.tick(hist.accepted) : at === 3 ? K.tick(tr.state_tick) : at > 3 ? "" : "–",
        at === 4 ? K.tick(tr.settled_tick || tr.state_tick) : "–"];
      return el("ol", { class: "offers-steps" + (ended ? " is-ended" : "") }, STEPS.map((s, i) =>
        el("li", { class: i < at ? "is-done" : i === at ? "is-now" : null, "aria-current": i === at ? "step" : null },
          el("span", { class: "offers-step-box" }), el("span", { class: "offers-step-name" }, t("offers.step." + s)), el("span", { class: "id" }, when[i]))));
    }

    function act(tr, body, done) {
      if (S.busy) return;
      S.busy = true;
      API.post("/api/me/trade/" + tr.id, body).then(() => { K.toast(done, "ok"); return API.get("/api/me/trades").then((d) => { S.data = d; }); },
        (e) => K.toast((e && e.message) || t("common.error"), "bad")).finally(() => { S.busy = false; sig.detail = null; redraw(); });
    }

    function orders(tr) {
      if (!LIVE.includes(tr.state)) return null;
      if (S.me.read_only) return el("div", { class: "offers-orders" }, K.label(t("offers.readOnly")));
      const mode = tr.mode || "auto";
      const seg = (m) => el("button", { type: "button", class: mode === m ? "active" : null, "aria-pressed": String(mode === m),
                                        onclick: () => { if (mode !== m) act(tr, { mode: m }, t("offers.sent.mode", { mode: t("offers.mode." + m) })); } }, t("offers.mode." + m));
      const input = el("input", { class: "input offers-price", type: "number", min: "1", max: "2000", step: "1", inputmode: "numeric", "aria-label": t("offers.counterPrice"),
                                  placeholder: String(tr.price || ""), value: S.counter[tr.id] || "", oninput: (e) => { S.counter[tr.id] = e.target.value; } });
      const counter = () => {
        const p = parseInt(input.value, 10);
        if (!(p >= 1 && p <= 2000)) { K.toast(t("offers.badPrice"), "bad"); input.focus(); return; }
        act(tr, { order: "counter", price: p }, t("offers.sent.order", { order: t("action.counter") + " " + K.price(p) }));
      };
      return el("div", { class: "offers-orders" }, K.label(t("offers.optional")),
        el("div", { class: "offers-seg", role: "group", "aria-label": t("offers.kpi.agent") }, seg("auto"), seg("ask_me")),
        K.btn(t("offers.order.accept"), { small: true, icon: "check", onclick: () => act(tr, { order: "accept" }, t("offers.sent.order", { order: t("action.accept") })) }),
        el("span", { class: "offers-counter" }, input, K.btn(t("offers.order.counter"), { small: true, icon: "swap", onclick: counter })),
        K.btn(t("offers.order.pass"), { small: true, icon: "close", onclick: () => act(tr, { order: "pass" }, t("offers.sent.order", { order: t("action.pass") })) }),
        tr.order ? el("span", { class: "id" }, t("offers.orderPending", { order: typeof tr.order === "string" ? tr.order : (tr.order.order || "") + (tr.order.price ? " " + K.price(tr.order.price) : "") })) : null);
    }

    function drawDetail() {
      const tr = selected();
      if (!tr) { K.clear(dom.detail); sig.detail = null; return; }
      const th = tr.thread || [], o = other(tr);
      // the thread keeps its scroll: read it before the redraw, give it back after
      const old = dom.detail.querySelector(".thread-list");
      const keep = old && sig.shown === tr.id ? { top: old.scrollTop, end: old.scrollHeight - old.scrollTop - old.clientHeight < 24 } : null;
      const changed = draw("detail", [tr.id, tr.state, tr.state_tick, tr.price, tr.mode, tr.order, tr.next, tr.offer, th.map((m) => m.n || m.tick), status().agent, S.busy, I18N.lang], () => {
        const ids = [tr.id, typeof tr.offer === "number" ? "#" + tr.offer : null, tr.settlement ? "s" + tr.settlement : null].filter(Boolean);
        const earlier = Math.max(0, (tr.messages || 0) - th.length);
        return K.panel({ flush: true, class: "offers-panel" },
          el("div", { class: "offers-d-head" }, el("h2", { class: "panel-title" }, K.teamName(o) + " · " + what(tr)), K.chip(t("state." + tr.state), TONE[tr.state]),
            el("span", { class: "panel-note" }, t("offers.settlesOn")),
            el("span", { class: "offers-d-ids" }, ids.map((x) => K.id(x)),
              el("button", { class: "offers-copy", type: "button", title: t("common.copy"), "aria-label": t("common.copy") + " " + tr.id, onclick: () => K.copy(ids.join(" ")) }, K.icon("copy", 12)))),
          el("div", { class: "offers-d-body" },
            el("div", { class: "offers-sides" },
              el("div", { class: "offers-agent" }, K.label(t("offers.yourAgent")), el("b", null, K.icon("agent", 15), team()), el("span", null, mine(tr))),
              K.swap(tr.gives, tr.receives, tr.cash || 0, "md"),
              el("div", { class: "offers-agent" }, K.label(t("offers.theirAgent")), el("b", null, K.icon("agent", 15), o), el("span", null, theirs(tr)))),
            tr.why ? el("p", { class: "offers-why" }, K.say(tr.why)) : null,
            steps(tr),
            el("div", { class: "offers-neg-head" }, K.label(t(th.length === 1 ? "offers.neg1" : "offers.neg", { n: tr.messages || th.length })), K.label(t("offers.negNote"))),
            th.length ? K.thread(th, team(), { earlier }) : el("div", { class: "thread offers-nothread" }, t("offers.noMessages")),
            el("div", { class: "offers-prices" },
              el("div", { class: "is-main" }, K.label("v07 · " + t("common.noFee")), el("b", { class: "num" }, K.price(tr.price))),
              typeof tr.suggested === "number" ? el("div", null, K.label(t("offers.suggested")), el("b", { class: "num" }, K.price(tr.suggested))) : null,
              tr.saves ? el("div", null, K.label(t("offers.saves")), el("b", { class: "num" }, K.price(tr.saves))) : null,
              tr.last_of_page ? el("div", null, K.label(t("offers.lastOfPage")), el("b", null, t("offers.yes"))) : null),
            orders(tr)));
      });
      if (changed && keep && !keep.end) {
        const list = dom.detail.querySelector(".thread-list");
        if (list) requestAnimationFrame(() => requestAnimationFrame(() => { list.scrollTop = keep.top; }));
      }
      sig.shown = tr.id;
    }

    function drawEmpty() {
      const c = S.me.counts || {}, st = S.stats;
      draw("list", ["empty", c, st && [st.teams_connected, st.teams, st.agents_online], status().tick, I18N.lang], () => [
        K.panel({ title: t("offers.empty.head"), note: t("offers.empty.checked", { tick: K.tick(status().tick) }) },
          K.state("empty", t("offers.empty.title"), t("offers.empty.text"))),
        K.panel({ title: t("offers.help.title"), flush: true }, el("div", { class: "offers-help" },
          el("div", null, t("offers.help.cards", { want: c.want || 0, sale: (c.for_sale || 0) + (c.duplicates || 0) })),
          el("div", null, t("offers.help.limits", { n: c.limits_set || 0 })),
          st ? el("div", null, t("offers.help.teams", { n: st.teams_connected || 0, of: st.teams || 0, online: st.agents_online || 0 })) : null)),
      ]);
      K.clear(dom.detail); sig.detail = null;
    }

    function redraw() {
      if (!S.data) {
        if (S.failed) draw("list", ["error", I18N.lang], () => K.state("error", null, t("offers.error"), K.btn(t("common.retry"), { small: true, onclick: () => Plaza.refresh() })));
        return;
      }
      drawHead();
      const none = !trades().length;
      dom.grid.classList.toggle("is-empty", none);
      if (none) { if (!S.stats) API.get("/api/stats").then((s) => { S.stats = s; redraw(); }, () => {}); drawEmpty(); return; }
      drawList(); drawDetail();
    }

    function select(id, byHand) {
      S.sel = id;
      const path = "/plaza/offers/" + id;
      if (location.pathname !== path) history.replaceState({}, "", path + location.search);
      redraw();
      if (byHand && window.matchMedia("(max-width: 1000px)").matches) dom.detail.scrollIntoView({ block: "start", behavior: "smooth" });
    }

    const opened = Date.now();                                 // the stream first replays what is already on the floor
    let soon = null;
    const stops = [
      () => clearTimeout(soon),
      API.poll("/api/me/trades", 3000, (d) => { S.data = d; S.failed = false; redraw(); }, () => { S.failed = true; redraw(); }),
      API.poll("/api/me", 15000, (me) => { S.me = me; redraw(); }),
      // a message on the floor for one of our matches: read the trades now instead of waiting for the next poll
      API.stream((item) => {
        if (Date.now() - opened < 2000 || soon || !item || !item.match || !S.data || !(S.data.trades || []).some((x) => x.id === item.match)) return;
        soon = setTimeout(() => { soon = null; API.get("/api/me/trades").then((d) => { S.data = d; redraw(); }, () => {}); }, 600);
      }),
    ];
    const clock = setInterval(redraw, 5000);
    return () => { stops.forEach((s) => s()); clearInterval(clock); };
  },
});
