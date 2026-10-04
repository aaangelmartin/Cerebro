// Performance: what the venue earns us, and what to do about it. Every number is the game's or our own count of
// settled matches; a figure the server does not send is drawn as "no data yet", never as an example.
(function () {
  "use strict";
  const { el } = K;
  const A = window.ADM;

  /** The signals of SCORING.md, section 5, read from the numbers on this page. Each one names what to do. */
  const isTeam = (o) => /^t\d\d$/.test(String(o || ""));
  // Where each of the server's alerts is acted on.
  const GO = { count: ["/plaza/admin/trades?state=settled", "trades"], value_drop: ["/plaza/admin/trades?state=settled", "trades"],
               lost: ["/plaza/admin/trades?state=settled_elsewhere", "trades"], broker: ["/plaza/admin/venue", "venue"],
               no_agents: ["/plaza/admin/teams", "teams"], flat: ["/plaza/admin/venue", "venue"] };
  const BAD = { count: 1, value_drop: 1, lost: 1, broker: 1, no_agents: 1 };

  // The server writes its alerts in English; the known ones are said in Spanish when the page is.
  const ALERT_ES = {
    count: [/^the game counts (\S+) trades on (\S+); our feed saw (\S+)\./, (m) => `el juego cuenta ${m[1]} tratos en ${m[2]}; nuestro feed ha visto ${m[3]}. Revisa huecos en el grabador antes de fiarte de las cifras de abajo.`],
    value_drop: [/^a trade at tick (\S+) lowered the value created from (\S+) to (\S+):/, (m) => `un trato en el tick ${m[1]} bajó el valor creado de ${m[2]} a ${m[3]}: búscalo y aprieta el filtro.`],
    lost: [/^(\d+) matched trade\(s\) closed off (\S+) \(last: (.+)\):/, (m) => `${m[1]} trato(s) emparejado(s) se cerraron fuera de ${m[2]} (último: ${m[3]}): di a esos agentes que cierren en ${m[2]}.`],
    broker: [/^the broker is (\S+):/, (m) => `el broker está ${m[1]}: las ofertas públicas que se cruzan en v07 no se están emparejando. Reinícialo con el supervisor.`],
    no_agents: [/^no team has connected an agent/, () => "ningún equipo ha conectado un agente: no se puede emparejar nada. Pídeselo a los equipos en persona."],
    flat: [/^no value created for (\d+) ticks while teams closed (\d+) trade\(s\) on other venues/, (m) => `sin valor creado en ${m[1]} ticks mientras los equipos cerraban ${m[2]} trato(s) en otros venues: anuncia y habla con los equipos.`],
  };
  function alertText(a) {
    const rule = I18N.lang === "es" ? ALERT_ES[a.kind] : null, m = rule ? rule[0].exec(a.text || "") : null;
    return m ? rule[1](m) : a.text || "";
  }
  /** The server's alerts as they come; without them, the signals of SCORING.md read from the numbers here. */
  function signals(d, ov) {
    if (Array.isArray(d.alerts)) return d.alerts.map((a) => { const [to, scr] = GO[a.kind] || GO.count;
      return { tone: BAD[a.kind] ? "bad" : "warn", title: t("admin.sig.kind." + (GO[a.kind] ? a.kind : "other")), text: alertText(a), to, cta: t("nav.admin." + scr) }; });
    const out = [], f = d.funnel || {}, venues = d.venues || [];
    if (d.alert) out.push({ tone: "bad", title: t("admin.sig.kind.other"), text: String(d.alert), to: "/plaza/admin/trades?state=settled", cta: t("nav.admin.trades") });
    if (f.settled_elsewhere) out.push({ tone: "bad", title: t("admin.sig.elsewhere", { n: K.num(f.settled_elsewhere) }), text: t("admin.sig.elsewhereText"), to: "/plaza/admin/trades?state=settled_elsewhere", cta: t("nav.admin.trades") });
    if (ov) {
      const idle = (ov.connected_teams || 0) - (ov.online_teams || 0);
      if (!ov.connected_teams) out.push({ tone: "bad", title: t("admin.sig.nobody"), text: t("admin.sig.nobodyText"), to: "/plaza/admin/teams", cta: t("nav.admin.teams") });
      else if (idle > 0) out.push({ tone: "warn", title: t("admin.sig.idle", { n: K.num(idle) }), text: t("admin.sig.idleText"), to: "/plaza/admin/teams", cta: t("nav.admin.teams") });
    }
    const live = (f.proposed || 0) + (f.offer_on_v07 || 0) + (f.accepted || 0) + (f.settled || 0);
    if (live >= 5 && (f.offer_on_v07 || 0) + (f.accepted || 0) + (f.settled || 0) < 0.3 * live)
      out.push({ tone: "warn", title: t("admin.sig.noOffer"), text: t("admin.sig.noOfferText"), to: "/plaza/admin/matchmaker", cta: t("nav.admin.matchmaker") });
    if ((f.expired || 0) >= 5 && (f.expired || 0) > 2 * (f.settled || 0))
      out.push({ tone: "warn", title: t("admin.sig.expire", { n: K.num(f.expired) }), text: t("admin.sig.expireText"), to: "/plaza/admin/trades?state=expired", cta: t("nav.admin.trades") });
    const ours = venues.find((v) => v.ours), rival = venues.filter((v) => !v.ours && isTeam(v.owner)).sort((a, b) => (b.trades || 0) - (a.trades || 0))[0];
    if (ours && rival && (rival.trades || 0) >= (ours.trades || 0))
      out.push({ tone: "warn", title: t("admin.sig.rival", { venue: rival.venue, owner: rival.owner }), text: t("admin.sig.rivalText", { a: K.num(rival.trades || 0), b: K.num(ours.trades || 0) }), to: "/plaza/admin/venue", cta: t("nav.admin.venue") });
    return out;
  }
  /** Up to `max` points of a series by tick, keeping the last one. */
  function sample(rows, max) {
    if (rows.length <= max) return rows;
    const step = (rows.length - 1) / (max - 1);
    return Array.from({ length: max }, (_, i) => rows[Math.round(i * step)]);
  }

  Plaza.adminScreen("performance", {
    title: "nav.admin.performance",
    noOverlay: true,                                       // the panel is read with the game closed too
    render(root) {
      let last = null, ov = null;
      root.appendChild(A.head(t("nav.admin.performance"), t("admin.perf.sub"),
        K.btn(t("admin.perf.copy"), { small: true, icon: "copy", onclick: () => (last ? K.copy(JSON.stringify(last, null, 1)) : K.toast(t("admin.noData"), "bad")) })));
      root.appendChild(K.endpoint("GET /plaza/admin/api/performance", "GET /plaza/admin/api/overview"));
      const body = root.appendChild(el("div", { class: "adm-performance" }));
      const stopOv = API.poll("/admin/api/overview", 15000, (d) => { ov = d; w.redraw(); }, () => {});
      const w = A.watch(body, "/admin/api/performance", (d) => {
        last = d;
        const s = d.score || {}, v = d.venue || {}, o = d.ours || {}, f = d.funnel || {}, st = d.settle || {};
        const n = (x, unit) => (typeof x === "number" ? K.num(x) + (unit || "") : t("admin.none"));
        const fd = d.feed || {}, tm = d.teams || null;
        const lead = typeof s.market === "number" && typeof s.best_other_market === "number" ? s.market - s.best_other_market : null;
        body.appendChild(K.kpis([
          { label: t("admin.perf.market"), value: typeof s.market === "number" ? t("admin.of30", { n: K.num(s.market) }) : t("admin.none"),
            sub: lead === null ? t("admin.perf.marketSub") : t("admin.perf.lead", { n: (lead >= 0 ? "+" : "") + K.num(Math.round(lead * 100) / 100) }) },
          { label: t("admin.perf.value"), value: n(v.value_created), sub: t("admin.perf.valueSub", { n: n(s.mm_points) }) },
          { label: t("admin.perf.rank"), value: typeof s.rank === "number" ? "#" + s.rank : t("admin.none"), sub: typeof s.total === "number" ? t("admin.perf.rankSub", { n: K.num(s.total) }) : null },
          { label: t("admin.perf.deals"), value: n(v.trades), sub: t("admin.perf.dealsSub", { n: n(o.settled) }) },
          { label: t("admin.perf.share"), value: typeof fd.share === "number" ? Math.round(fd.share * 100) + " %" : t("admin.none"),
            sub: typeof fd.team_deals === "number" ? t("admin.perf.shareSub", { n: K.num(fd.team_deals) }) : null },
          { label: t("admin.perf.traders"), value: n(v.traders), sub: t("admin.perf.pairs", { n: n(v.pairs) }) },
          { label: t("admin.perf.connected"), value: tm ? K.num(tm.connected || 0) : ov ? K.num(ov.connected_teams || 0) + " / " + K.num((ov.teams || []).length) : t("admin.none"),
            sub: tm ? t("admin.perf.connectedSub", { v: K.num(tm.verified || 0), o: K.num(tm.online || 0) }) : ov ? t("admin.perf.connectedSub", { v: K.num(ov.verified_teams || 0), o: K.num(ov.online_teams || 0) }) : null },
          { label: t("admin.perf.test"), value: typeof s.bench_efficiency === "number" ? K.num(s.bench_efficiency) : t("admin.none"),
            sub: typeof s.bench_points === "number" ? t("admin.perf.testSub", { n: K.num(s.bench_points) }) : null },
        ]));

        const sig = signals(d, ov);
        body.appendChild(K.panel({ title: t("admin.sig.title"), note: t("admin.sig.note"), icon: "bell", flush: true },
          sig.length ? el("div", { class: "adm-alerts" }, sig.map((a) => el("div", { class: "adm-alert tone-" + a.tone }, el("span", { class: "adm-alert-dot" }),
            el("div", { class: "adm-alert-text" }, el("b", null, a.title), el("span", null, a.text)),
            K.btn(a.cta, { small: true, iconAfter: "arrow", onclick: () => Plaza.go(a.to) }))))
            : el("div", { class: "adm-quiet" }, K.icon("check", 14), t("admin.sig.none"))));

        const mid = body.appendChild(el("div", { class: "adm-grid adm-performance-mid" }));
        const series = sample(((d.series || {}).value || []).filter((r) => typeof r.tick === "number"), 30);
        const chart = (key) => (series.length ? A.bars(series.map((r, i) => ({ label: i === 0 || i === series.length - 1 ? K.tick(r.tick) : "", value: r[key] || 0, hi: i === series.length - 1 })), { plain: true })
          : K.state("empty", t("admin.noData")));
        const lastOf = (key) => (series.length ? K.num(series[series.length - 1][key] || 0) : "");
        mid.appendChild(K.panel({ title: t("admin.perf.valueTick"), note: lastOf("value_created"), icon: "trend" }, chart("value_created")));
        mid.appendChild(K.panel({ title: t("admin.perf.mmTick"), note: lastOf("mm_points"), icon: "performance" }, chart("mm_points")));
        mid.appendChild(K.panel({ title: t("admin.perf.dealsTick"), note: lastOf("trades"), icon: "offers" }, chart("trades")));
        const mk = sample(((d.series || {}).market || []).filter((r) => typeof r.tick === "number"), 30);
        if (mk.length) body.appendChild(K.panel({ title: t("admin.perf.marketTick"), note: t("admin.perf.marketTickNote"), icon: "target" },
          A.bars(mk.map((r, i) => ({ label: i === 0 || i === mk.length - 1 ? K.tick(r.tick) : "", value: Math.round(((r.ours || 0) - (r.best_other || 0)) * 100) / 100, hi: i === mk.length - 1 })))));
        const perTick = d.per_tick || [];
        const mid2 = body.appendChild(el("div", { class: "adm-grid adm-performance-low" }));
        mid2.appendChild(K.panel({ title: t("admin.perf.closedTick"), note: t("admin.perf.closedTickNote"), icon: "check" },
          perTick.length ? A.bars(perTick.slice(-30).map((r, i, all) => ({ label: K.tick(r.tick), value: r.settled || 0, hi: i === all.length - 1 })))
            : K.state("empty", t("admin.perf.noDeals"), t("admin.perf.noDealsText"))));
        const lost = d.lost || [];
        mid2.appendChild(K.panel({ title: t("admin.perf.lost"), note: t("admin.perf.lostNote"), icon: "alert", flush: true },
          lost.length ? K.table([
            { label: t("shell.tick"), render: (x) => K.tick(x.tick) }, { label: t("admin.col.match"), render: (x) => K.id(x.id) },
            { label: t("admin.col.pair"), render: (x) => A.pair(x.seller, x.buyer) }, { label: t("admin.col.card"), render: (x) => x.ref || "–" },
            { label: t("common.price"), num: true, render: (x) => K.price(x.price) }, { label: t("admin.col.venue"), render: (x) => K.chip(x.venue || "–", "bad") },
          ], lost, { onrow: (x) => Plaza.go("/plaza/admin/trades?match=" + x.id) }) : el("div", { class: "adm-quiet" }, K.icon("check", 14), t("admin.perf.noLost"))));

        const low = body.appendChild(el("div", { class: "adm-grid adm-performance-low" }));
        low.appendChild(K.panel({ title: t("admin.funnel.title"), note: t("admin.funnel.note"), icon: "trend" },
          A.funnel([{ label: t("admin.funnel.proposed"), value: f.proposed || 0 }, { label: t("admin.funnel.offer"), value: f.offer_on_v07 || 0, tone: "signal" },
                    { label: t("admin.funnel.accepted"), value: f.accepted || 0, tone: "signal" }, { label: t("admin.funnel.settled"), value: f.settled || 0, tone: "ok" }]),
          A.rows([
            [t("admin.rates.settleRate"), typeof st.rate === "number" ? Math.round(st.rate * 100) + " %" : null],
            [t("admin.rates.median"), typeof st.median_ticks === "number" ? t("common.ticks", { n: K.num(st.median_ticks) }) : null],
            [t("admin.rates.expired"), K.num(f.expired || 0), f.expired ? "warn" : null],
            [t("admin.rates.passed"), K.num(f.passed || 0)],
            [t("admin.rates.elsewhere"), K.num(f.settled_elsewhere || 0), f.settled_elsewhere ? "bad" : "ok"],
            [t("admin.kpi.saved"), K.price(o.saved_fees)],
            d.broker ? [t("admin.perf.broker"), t("status." + (d.broker.state === "on" ? "on" : "down")) + (d.broker.detail ? " · " + d.broker.detail : ""), d.broker.state === "on" ? "ok" : "bad"] : null,
          ])));
        const teams = d.per_team || [];
        low.appendChild(K.panel({ title: t("admin.perf.byTeam"), note: t("admin.perf.byTeamNote"), icon: "teams", flush: true },
          teams.length ? K.table([
            { label: t("admin.col.team"), render: (x) => A.team(x.team) },
            { label: t("admin.col.venueDeals"), num: true, render: (x) => (typeof x.venue_deals === "number" ? K.num(x.venue_deals) : "–") },
            { label: t("admin.col.fromMatches"), num: true, render: (x) => K.num(x.deals || 0) },
            { label: t("admin.col.volume"), num: true, render: (x) => K.price(x.volume || 0) },
            { label: t("admin.col.sold"), num: true, render: (x) => K.num(x.as_seller || 0) },
            { label: t("admin.col.bought"), num: true, render: (x) => K.num(x.as_buyer || 0) },
            { label: t("admin.col.agent"), render: (x) => K.pill(t("status." + (x.connected ? "connected" : "offline")), x.connected ? "ok" : "mute") },
          ], teams, { onrow: (x) => Plaza.go("/plaza/admin/teams?team=" + x.team) }) : K.state("empty", t("admin.perf.noDeals"), t("admin.perf.noDealsText"))));

        const venues = d.venues || [];
        body.appendChild(K.panel({ title: t("admin.perf.venues"), note: t("admin.perf.venuesNote"), icon: "venue", flush: true },
          venues.length ? K.table([
            { label: t("admin.col.venue"), render: (x) => el("span", { class: x.ours ? "adm-ours" : null }, K.id(x.venue), " ", x.name || "") },
            { label: t("admin.col.owner"), render: (x) => (isTeam(x.owner) ? A.team(x.owner) : t("admin.house")) },
            { label: t("common.fee"), num: true, render: (x) => (typeof x.fee_bps === "number" ? K.num(x.fee_bps / 100) + " %" : "–") },
            { label: t("admin.col.deals"), num: true, render: (x) => K.num(x.trades || 0) },
            { label: t("admin.col.volume"), num: true, render: (x) => K.price(x.volume || 0) },
            { label: t("admin.col.traders"), num: true, render: (x) => K.num(x.traders || 0) },
            { label: t("admin.col.pairs"), num: true, render: (x) => (typeof x.pairs === "number" ? K.num(x.pairs) : "–") },
            { label: t("admin.col.market"), num: true, render: (x) => (typeof x.market === "number" ? K.num(x.market) : "–") },
          ], venues) : K.state("empty", t("admin.noData"))));
        body.appendChild(el("p", { class: "adm-note" }, t("admin.perf.scoring")));
      });
      return () => { w.stop(); stopOv(); };
    },
  });
})();
