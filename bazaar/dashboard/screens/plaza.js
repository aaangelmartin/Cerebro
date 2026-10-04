/* MARKET v07 · what our market (bazaar/plaza, its own process) earns, read from its panel (#plaza).
   GET /plaza/admin/api/performance (through the gateway, dashboard login) -> {score:{market, mm_points, rank, total,
     best_other_market, bench_efficiency}, venue:{trades, volume, traders, pairs, value_created}, feed:{share, team_deals},
     ours:{settled, settled_elsewhere}, alerts:[{kind, text}], funnel, teams:{connected, verified, online},
     series:{value:[{tick, value_created, mm_points, trades}]}, venues:[…], broker:{state, detail}}
   Nothing here is a sample: a figure the market does not send is drawn as "—". The actions live in the market's panel. */
(function () {
  "use strict";
  window.Screens = window.Screens || {};
  const U = () => window.ui;
  const el = (...a) => U().el(...a);
  const tr = (k, v) => window.I18N.t(k, v);
  const num = (x) => (typeof x === "number" ? U().fmtNum(x) : "—");
  const ADMIN = "/plaza/admin/";
  const SRC = "/plaza/admin/api/performance";
  const S = { data: null, err: null, at: 0, busy: false, sig: "" };
  // The market's own line icon for the menu (a stall), in the style of ui.js.
  if (window.ui && window.ui.ICONS && !window.ui.ICONS.plaza) {
    window.ui.ICONS.plaza = '<path d="M3 9 4.5 4h15L21 9"/><path d="M3 9h18v1.5a3 3 0 0 1-6 0 3 3 0 0 1-6 0 3 3 0 0 1-6 0Z"/><path d="M5 12.5V20h14v-7.5"/><path d="M10 20v-4h4v4"/>';
  }
  // Which screen of the panel acts on each alert.
  const GO = { count: "trades", value_drop: "trades", lost: "trades", broker: "venue", no_agents: "teams", flat: "venue" };
  const BAD = { count: 1, value_drop: 1, lost: 1, broker: 1, no_agents: 1 };

  // The market writes its alerts in English; the known ones are said in Spanish when the dashboard is.
  const ALERT_ES = {
    count: [/^the game counts (\S+) trades on (\S+); our feed saw (\S+)\./, (m) => `el juego cuenta ${m[1]} tratos en ${m[2]}; nuestro feed ha visto ${m[3]}. Revisa huecos en el grabador antes de fiarte de estas cifras.`],
    value_drop: [/^a trade at tick (\S+) lowered the value created from (\S+) to (\S+):/, (m) => `un trato en el tick ${m[1]} bajó el valor creado de ${m[2]} a ${m[3]}: búscalo y aprieta el filtro.`],
    lost: [/^(\d+) matched trade\(s\) closed off (\S+) \(last: (.+)\):/, (m) => `${m[1]} trato(s) emparejado(s) se cerraron fuera de ${m[2]} (último: ${m[3]}): di a esos agentes que cierren en ${m[2]}.`],
    broker: [/^the broker is (\S+):/, (m) => `el broker está ${m[1]}: las ofertas públicas que se cruzan en v07 no se están emparejando. Reinícialo con el supervisor.`],
    no_agents: [/^no team has connected an agent/, () => "ningún equipo ha conectado un agente: no se puede emparejar nada. Pídeselo a los equipos en persona."],
    flat: [/^no value created for (\d+) ticks while teams closed (\d+) trade\(s\) on other venues/, (m) => `sin valor creado en ${m[1]} ticks mientras los equipos cerraban ${m[2]} trato(s) en otros venues: anuncia y habla con los equipos.`],
  };
  function say(a) {
    const rule = window.I18N.lang === "es" ? ALERT_ES[a.kind] : null, m = rule ? rule[0].exec(a.text || "") : null;
    return m ? rule[1](m) : a.text || "";
  }
  function beat(text) {
    const m = window.I18N.lang === "es" ? /^last beat (\d+) s ago$/.exec(String(text)) : null;
    return m ? `último latido hace ${m[1]} s` : text;
  }

  async function pull(force) {
    if (S.busy || (!force && Date.now() - S.at < 4000)) return;
    S.busy = true;
    try {
      const res = await fetch(SRC, { headers: { Accept: "application/json" }, cache: "no-store", credentials: "same-origin" });
      if (!res.ok) throw Object.assign(new Error("HTTP " + res.status), { status: res.status });
      S.data = await res.json(); S.err = null;
    } catch (e) { S.err = e; }
    S.at = Date.now(); S.busy = false;
  }

  function sample(rows, max) {
    if (rows.length <= max) return rows;
    const step = (rows.length - 1) / (max - 1);
    return Array.from({ length: max }, (_, i) => rows[Math.round(i * step)]);
  }
  function chart(title, rows, key) {
    const p = U().panel(title, { sub: rows.length ? num(rows[rows.length - 1][key]) : "" });
    if (!rows.length) { p.body.appendChild(U().empty(tr("plaza.noData"))); return p; }
    p.body.appendChild(el("div", { class: "pz-chart" }, U().bars(rows.map((r, i) => ({ value: r[key] || 0, color: i === rows.length - 1 ? "var(--signal)" : "var(--s3)" })),
      { fluid: true, h: 96, w: 480, labels: rows.map((r) => "t" + r.tick) }),
      el("div", { class: "pz-axis num" }, el("span", null, "t" + rows[0].tick), el("span", null, "t" + rows[rows.length - 1].tick))));
    return p;
  }
  function rows(list) {
    return el("div", { class: "pz-rows" }, list.filter(Boolean).map(([name, value, tone]) => el("div", { class: "pz-row" }, el("span", null, name),
      el("span", { class: ["num", tone ? "tone-" + tone : ""] }, value === null || value === undefined ? "—" : value))));
  }

  function draw(root) {
    const wrap = root.querySelector(".scr-plaza"); if (!wrap) return;
    const body = wrap.querySelector(".pz-body");
    if (!S.data) {
      body.replaceChildren(S.err ? el("div", { class: "state error" }, S.err.status === 404 || !S.err.status ? tr("plaza.unreachable") : tr("plaza.failed", { why: S.err.message })) : U().loading());
      return;
    }
    const d = S.data, s = d.score || {}, v = d.venue || {}, o = d.ours || {}, f = d.funnel || {}, fd = d.feed || {}, tm = d.teams || {};
    const lead = typeof s.market === "number" && typeof s.best_other_market === "number" ? Math.round((s.market - s.best_other_market) * 100) / 100 : null;
    const kpis = el("div", { class: "pz-kpis" },
      U().kpi({ label: tr("plaza.kpi.market"), value: typeof s.market === "number" ? tr("plaza.of30", { n: num(s.market) }) : "—", sub: lead === null ? null : tr("plaza.kpi.lead", { n: (lead >= 0 ? "+" : "") + num(lead) }), tone: lead !== null && lead < 0 ? "warn" : "" }),
      U().kpi({ label: tr("plaza.kpi.value"), value: num(v.value_created), sub: tr("plaza.kpi.mm", { n: num(s.mm_points) }) }),
      U().kpi({ label: tr("plaza.kpi.deals"), value: num(v.trades), sub: tr("plaza.kpi.volume", { n: U().fmtP(v.volume) }) }),
      U().kpi({ label: tr("plaza.kpi.share"), value: typeof fd.share === "number" ? Math.round(fd.share * 100) + " %" : "—", sub: typeof fd.team_deals === "number" ? tr("plaza.kpi.shareSub", { n: num(fd.team_deals) }) : null }),
      U().kpi({ label: tr("plaza.kpi.teams"), value: num(tm.connected), sub: tr("plaza.kpi.teamsSub", { v: num(tm.verified), o: num(tm.online) }), tone: tm.connected === 0 ? "bad" : "" }),
      U().kpi({ label: tr("plaza.kpi.lost"), value: num(o.settled_elsewhere), sub: tr("plaza.kpi.lostSub", { n: num(o.settled) }), tone: o.settled_elsewhere ? "bad" : "" }));

    const alerts = Array.isArray(d.alerts) ? d.alerts : d.alert ? [{ kind: "other", text: String(d.alert) }] : [];
    const al = U().panel(tr("plaza.alerts.title"), { sub: tr("plaza.alerts.sub") });
    al.body.appendChild(alerts.length ? el("div", { class: "pz-alerts" }, alerts.map((a) => el("div", { class: ["pz-alert", BAD[a.kind] ? "tone-bad" : "tone-warn"] },
      el("span", { class: "pz-dot" }), el("span", { class: "pz-alert-text" }, say(a)),
      el("a", { class: "btn", href: ADMIN + (GO[a.kind] || "performance") }, tr("plaza.go." + (GO[a.kind] || "performance"))))))
      : U().empty(tr("plaza.alerts.none")));

    const series = sample(((d.series || {}).value || []).filter((r) => typeof r.tick === "number"), 40);
    const charts = el("div", { class: "pz-two" }, chart(tr("plaza.chart.value"), series, "value_created"), chart(tr("plaza.chart.deals"), series, "trades"));

    const fn = U().panel(tr("plaza.funnel.title"), { sub: tr("plaza.funnel.sub") });
    fn.body.appendChild(rows([
      [tr("plaza.funnel.proposed"), num(f.proposed)], [tr("plaza.funnel.offer"), num(f.offer_on_v07)], [tr("plaza.funnel.accepted"), num(f.accepted)],
      [tr("plaza.funnel.settled"), num(f.settled), f.settled ? "ok" : ""], [tr("plaza.funnel.elsewhere"), num(f.settled_elsewhere), f.settled_elsewhere ? "bad" : ""],
      [tr("plaza.funnel.expired"), num(f.expired)],
      d.broker ? [tr("plaza.broker"), (d.broker.state === "on" ? tr("plaza.up") : tr("plaza.down")) + (d.broker.detail ? " · " + beat(d.broker.detail) : ""), d.broker.state === "on" ? "ok" : "bad"] : null,
      [tr("plaza.test"), typeof s.bench_efficiency === "number" ? s.bench_efficiency.toFixed(3) : "—"]]));
    const venues = (d.venues || []).slice(0, 8);
    const vn = U().panel(tr("plaza.venues.title"), { sub: tr("plaza.venues.sub") });
    vn.body.appendChild(venues.length ? el("table", { class: "pz-table" },
      el("thead", null, el("tr", null, [tr("plaza.venues.venue"), tr("plaza.venues.owner"), tr("plaza.venues.deals"), tr("plaza.venues.pairs"), tr("plaza.venues.market")].map((h, i) => el("th", { class: i > 1 ? "num" : "" }, h)))),
      el("tbody", null, venues.map((x) => el("tr", { class: x.ours ? "is-ours" : "" }, el("td", null, el("span", { class: "num pz-id" }, x.venue), " ", x.name || ""),
        el("td", { class: "num" }, /^t\d\d$/.test(String(x.owner || "")) ? x.owner : "—"), el("td", { class: "num" }, num(x.trades)), el("td", { class: "num" }, num(x.pairs)),
        el("td", { class: "num" }, num(x.market)))))) : U().empty(tr("plaza.noData")));

    U().keepScroll(wrap, () => body.replaceChildren(kpis, al, charts, el("div", { class: "pz-two" }, fn, vn),
      el("p", { class: "pz-note" }, tr("plaza.scoring"))));
  }

  window.Screens.plaza = {
    title: "Market v07",
    mount(root) {
      S.sig = "";
      root.replaceChildren(el("div", { class: "scr-plaza" },
        el("header", { class: "pz-head" }, el("h1", null, tr("plaza.title")), el("span", { class: "pz-sub" }, tr("plaza.sub")),
          el("a", { class: "btn btn-primary pz-open", href: ADMIN }, tr("plaza.open"))),
        el("div", { class: "pz-api num" }, "API · GET " + SRC + " · " + tr("plaza.api")),
        el("div", { class: "pz-body" }, U().loading())));
    },
    async refresh(root, data, params, opts) {
      await pull(opts && opts.force);
      const sig = JSON.stringify(S.data) + "|" + (S.err ? S.err.message : "");
      if (sig === S.sig && !(opts && opts.force)) return;
      S.sig = sig;
      draw(root);
    },
    unmount() { S.sig = ""; },
  };
})();
