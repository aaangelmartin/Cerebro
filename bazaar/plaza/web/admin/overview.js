// The panel's shared helpers (ADM) and its first screen. This file loads before the other panel screens, so they
// all draw with ADM: one way to poll, to show a missing route, to run an action and to draw bars and rows.
// Nothing here shows a private limit: the panel only ever gets "limits set" and "overlap".
(function () {
  "use strict";
  const { el } = K;

  /** Polls `path` every 5 s and calls draw(data, body) when the answer changed. A route that is not built yet
   *  (404) draws "no data yet" instead of a number. Returns { stop, again, data }. */
  function watch(body, path, draw, query) {
    let last = null;
    const h = { data: null, stop: null, again: null, redraw: null };
    const paint = () => {
      K.clear(body);
      try { draw(h.data, body); } catch (e) { console.error(e); body.appendChild(K.state("error", null, String((e && e.message) || e))); }
    };
    const ok = (d) => {
      const s = JSON.stringify(d);
      if (s === last) return;
      last = s; h.data = d; paint();
    };
    const bad = (e) => {
      if (last !== null && e && e.status !== 404) return;                     // keep the last picture on a hiccup
      last = null; h.data = null;
      K.clear(body);
      body.appendChild(e && e.status === 404 ? K.state("empty", t("admin.noData"), t("admin.noDataText", { path: "/plaza" + path }))
        : K.state("error", null, (e && e.message) || "", K.btn(t("common.retry"), { small: true, onclick: () => h.again() })));
    };
    const where = () => [path, query ? query() : undefined];
    body.appendChild(K.state("loading"));
    h.stop = API.poll(where, 5000, ok, bad);
    h.again = () => { last = null; const [p, q] = where(); return API.get(p, q).then(ok, bad); };
    h.redraw = () => { if (h.data) paint(); };
    return h;
  }

  /** One of our switches. Says what happened and reads the screen again. */
  function act(body, then, done) {
    return API.post("/admin/api/action", body).then(() => {
      K.toast(done || t("admin.done", { action: body.action }), "ok");
      if (window.Plaza.refresh && (body.action === "on" || body.action === "off")) window.Plaza.refresh();
      return then ? then() : null;
    }, (e) => { K.toast(t("admin.failed", { action: body.action, why: (e && e.message) || "" }), "bad"); });
  }
  /** A button that runs an action after a second click (nothing here can be undone by accident). */
  function actBtn(text, body, then, opts) {
    const o = opts || {};
    let armed = false, timer = null;
    const b = K.btn(text, { small: true, kind: o.kind, icon: o.icon, title: "POST /plaza/admin/api/action " + JSON.stringify(body), onclick: (e) => {
      e.stopPropagation();
      if (!o.confirm || armed) { armed = false; clearTimeout(timer); b.classList.remove("adm-armed"); b.lastChild.textContent = text; return act(body, then, o.done); }
      armed = true; b.classList.add("adm-armed"); b.lastChild.textContent = t("admin.sure");
      timer = setTimeout(() => { armed = false; b.classList.remove("adm-armed"); b.lastChild.textContent = text; }, 3000);
    } });
    return b;
  }

  /** rows([[label, value, tone]]) : a list of name and value, the value in mono. */
  function rows(list) {
    return el("div", { class: "adm-rows" }, list.filter(Boolean).map(([name, value, tone]) => el("div", { class: "adm-row" },
      el("span", { class: "adm-row-name" }, name), el("span", { class: "adm-row-value" + (tone ? " tone-" + tone : "") }, value === null || value === undefined ? t("admin.none") : value))));
  }
  /** funnel([{label, value, tone}]) : horizontal bars against the largest value. */
  function funnel(steps) {
    const max = Math.max(1, ...steps.map((s) => s.value || 0));
    return el("div", { class: "adm-funnel" }, steps.map((s) => el("div", { class: "adm-funnel-row" },
      el("span", { class: "adm-funnel-name" }, s.label),
      el("span", { class: "adm-funnel-track" }, el("i", { class: s.tone ? "tone-" + s.tone : null, style: { width: (100 * (s.value || 0)) / max + "%" } })),
      el("span", { class: "adm-funnel-value" }, K.num(s.value || 0)))));
  }
  /** bars([{label, value, hi}]) : vertical bars, the tallest in white when `hi`. */
  function bars(list, opts) {
    const o = opts || {};
    if (!list.length) return K.state("empty", t("admin.noData"));
    const max = Math.max(1, ...list.map((b) => b.value || 0));
    return el("div", { class: "adm-bars" + (o.plain ? " is-plain" : ""), role: "img", "aria-label": o.label || "" }, list.map((b) => el("div", { class: "adm-bar", title: b.label + " · " + K.num(b.value || 0) },
      o.plain ? null : el("span", { class: "adm-bar-value" }, K.num(b.value || 0)),
      el("i", { class: b.hi ? "is-hi" : null, style: { height: Math.max(2, (100 * (b.value || 0)) / max) + "%" } }),
      el("span", { class: "adm-bar-label" }, b.label))));
  }
  const pct = (a, b) => (b ? Math.round((100 * a) / b) + " %" : t("admin.none"));
  const team = (id) => el("b", { class: "adm-team" }, id || "–");
  const pair = (a, b, swap) => el("span", { class: "adm-pair" }, team(a), K.icon(swap ? "swap" : "arrow", 11), team(b));
  const STATE_TONE = { proposed: "", offer_on_v07: "signal", accepted: "signal", settled: "ok", passed: "bad", expired: "warn", settled_elsewhere: "bad" };
  const stateChip = (s) => K.chip(t("state." + s), STATE_TONE[s] || "");
  /** Limits as the panel may know them: set on both sides and overlapping, or not. Never a number. */
  function limits(overlap) {
    if (overlap === true) return el("span", { class: "adm-limits" }, K.chip(t("admin.limits.set")), K.chip(t("admin.limits.overlap"), "ok"));
    if (overlap === false) return el("span", { class: "adm-limits" }, K.chip(t("admin.limits.set")), K.chip(t("admin.limits.noOverlap"), "bad"));
    return el("span", { class: "adm-limits" }, K.chip(t("admin.limits.notSet")));
  }
  /** A time of day from the server as ticks ago, since the panel talks in ticks. */
  function ticksAgo(ts) {
    if (typeof ts !== "number") return t("admin.none");
    const len = (window.Plaza.state.status && window.Plaza.state.status.tick_seconds) || 15;
    const n = Math.max(0, Math.round((Date.now() / 1000 - ts) / len));
    return n === 0 ? t("common.thisTick") : t(n === 1 ? "common.tickAgo" : "common.ticksAgo", { n: K.num(n) });
  }
  const hourLabel = (h) => String(h || "").slice(11, 13) + " h";
  const head = (title, sub, ...right) => K.pageHead(title, sub, ...right);

  window.ADM = { watch, act, actBtn, rows, funnel, bars, pct, team, pair, stateChip, limits, ticksAgo, hourLabel, head };

  // ---- overview: everything on v07 Market, measured
  Plaza.adminScreen("overview", {
    title: "nav.admin.overview",
    noOverlay: true,                                       // the panel is read with the game closed too
    render(root) {
      root.appendChild(head(t("nav.admin.overview"), t("admin.overview.sub"), K.btn(t("admin.overview.public"), { href: "/plaza/", kind: "primary", small: true })));
      root.appendChild(K.endpoint("GET /plaza/admin/api/overview"));
      const body = root.appendChild(el("div", { class: "adm-overview" }));
      const w = watch(body, "/admin/api/overview", (d) => {
        const teams = d.teams || [], f = d.match_funnel || {}, v = d.value || {}, fl = d.funnel || {}, tot = d.totals || {};
        body.appendChild(K.kpis([
          { label: t("admin.kpi.connected"), value: K.num(d.connected_teams || 0) + " / " + K.num(teams.length) },
          { label: t("admin.kpi.verified"), value: K.num(d.verified_teams || 0) },
          { label: t("admin.kpi.online"), value: K.num(d.online_teams || 0) },
          { label: t("admin.kpi.matches"), value: K.num((f.proposed || 0) + (f.offer_on_v07 || 0) + (f.accepted || 0)), sub: t("admin.kpi.matchesSub") },
          { label: t("admin.kpi.settled"), value: K.num(f.settled || 0), sub: t("admin.kpi.settledSub", { n: K.num(fl.deals_on_venue || 0) }) },
          { label: t("admin.kpi.mmPoints"), value: typeof v.mm_points === "number" ? K.num(v.mm_points) : t("admin.none"), sub: typeof v.market === "number" ? t("admin.kpi.marketSub", { n: K.num(v.market) }) : null },
          { label: t("admin.kpi.saved"), value: K.price(v.saved_fees) },
          { label: t("admin.kpi.errors"), value: K.num(tot.errors || 0), sub: t("admin.kpi.errorsSub", { n: K.num(tot.requests || 0) }) },
        ]));
        const grid = body.appendChild(el("div", { class: "adm-grid adm-overview-top" }));
        grid.appendChild(K.panel({ title: t("admin.overview.teams"), note: t("admin.overview.teamsNote", { n: teams.length }), icon: "teams" },
          teams.length ? el("div", { class: "adm-overview-tiles" }, teams.map((x) => {
            const st = x.blocked ? "blocked" : x.verified ? "verified" : x.connected ? "connected" : "notYet";
            return K.link("/plaza/admin/teams?team=" + x.team, { class: "adm-tile is-" + st + (x.online ? " is-online" : ""), title: x.team },
              el("span", { class: "adm-tile-id" }, x.team, x.online ? K.icon("agent", 12) : null), el("span", { class: "adm-tile-state" }, t("admin.team." + st)));
          })) : K.state("empty", t("admin.noData"))));
        const right = grid.appendChild(el("div", { class: "adm-stack" }));
        right.appendChild(K.panel({ title: t("admin.funnel.title"), note: t("admin.funnel.note"), icon: "trend" }, funnel([
          { label: t("admin.funnel.proposed"), value: f.proposed || 0 }, { label: t("admin.funnel.offer"), value: f.offer_on_v07 || 0, tone: "signal" },
          { label: t("admin.funnel.accepted"), value: f.accepted || 0, tone: "signal" }, { label: t("admin.funnel.settled"), value: f.settled || 0, tone: "ok" }])));
        right.appendChild(K.panel({ title: t("admin.overview.requests"), note: t("admin.overview.requestsNote"), icon: "activity" },
          bars((d.hourly || []).slice(-12).map((h, i, all) => ({ label: hourLabel(h.hour), value: h.requests || 0, hi: i === all.length - 1 })))));

        const low = body.appendChild(el("div", { class: "adm-grid adm-overview-low" }));
        const shown = teams.filter((x) => x.connected || x.verified || x.claimed || x.pending_sessions).sort((a, b) => Number(b.online) - Number(a.online) || Number(b.verified) - Number(a.verified));
        low.appendChild(K.panel({ title: t("admin.overview.detail"), note: t("admin.overview.detailNote"), flush: true },
          shown.length ? K.table([
            { label: t("admin.col.team"), render: (x) => team(x.team) },
            { label: t("admin.col.state"), render: (x) => t("admin.team." + (x.verified ? "verified" : x.connected ? "connected" : x.pending_sessions ? "pending" : "notYet")) },
            { label: t("admin.col.agent"), render: (x) => K.pill(t("status." + (x.online ? "connected" : "offline")), x.online ? "ok" : x.agent ? "bad" : "mute") },
            { label: t("admin.col.lastSync"), render: (x) => ticksAgo(x.last_sync) },
            { label: t("admin.col.cards"), num: true, render: (x) => K.num(x.available || 0) + " / " + K.num(x.wants || 0) },
            { label: t("admin.col.matches"), num: true, render: (x) => K.num(x.matches || 0) },
          ], shown, { onrow: (x) => Plaza.go("/plaza/admin/teams?team=" + x.team) }) : K.state("empty", t("admin.overview.nobody"), t("admin.overview.nobodyText"))));
        const done = (f.settled || 0) + (f.passed || 0) + (f.expired || 0) + (f.settled_elsewhere || 0), all = done + (f.proposed || 0) + (f.offer_on_v07 || 0) + (f.accepted || 0);
        low.appendChild(K.panel({ title: t("admin.rates.title"), flush: true }, rows([
          [t("admin.rates.all"), K.num(all)],
          [t("admin.rates.settled"), pct(f.settled || 0, all), f.settled ? "ok" : null],
          [t("admin.rates.expired"), K.num(f.expired || 0), f.expired ? "warn" : null],
          [t("admin.rates.passed"), K.num(f.passed || 0), f.passed ? "bad" : null],
          [t("admin.rates.elsewhere"), K.num(f.settled_elsewhere || 0), f.settled_elsewhere ? "bad" : null],
          [t("admin.rates.following"), K.num(fl.open_offers_following_a_match || 0) + " / " + K.num(fl.open_offers_on_venue || 0)],
        ])));
        low.appendChild(K.panel({ title: t("admin.health.title"), flush: true }, rows([
          [t("admin.health.market"), t("status." + (d.enabled ? "on" : "off")), d.enabled ? "ok" : "bad"],
          [t("admin.health.uptime"), typeof d.uptime_s === "number" ? Math.floor(d.uptime_s / 3600) + " h " + Math.floor((d.uptime_s % 3600) / 60) + " min" : null],
          [t("admin.health.errors"), K.num(tot.errors || 0) + " / " + K.num(tot.requests || 0), tot.errors ? "warn" : "ok"],
          [t("admin.health.floor"), K.num((d.floor || {}).items || 0) + " · " + t("admin.health.streams", { n: K.num((d.floor || {}).streams || 0) })],
          [t("admin.health.hidden"), K.num((d.floor || {}).hidden || 0)],
          [t("admin.health.listed"), K.num(fl.offers_listed_on_venue || 0)],
          [t("admin.health.deals"), K.num(fl.deals_on_venue || 0) + " · " + K.price(fl.volume_on_venue || 0)],
          [t("admin.health.market30"), typeof v.market === "number" ? t("admin.of30", { n: K.num(v.market) }) : null],
        ])));
      });
      return w.stop;
    },
  });
})();
