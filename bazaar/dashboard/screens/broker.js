/* BROKER · nuestro broker del Market Test y la tienda v07 (#broker).
   Datos: GET broker (latido del proceso broker), rec/stream/feed (bench.started, liquidaciones en v07),
   rec/stream/leaderboard (puntos de mercado a lo largo del día), rec/latest/books/v07 (libro público).
   Aún sin API: el registro por tick de cada sesión (data/live/bench/<día>-<run>.jsonl) y los resultados
   oficiales por sesión (bench/results.jsonl) -> se muestran en cuanto exista GET broker/sessions. */
(function () {
  "use strict";
  window.Screens = window.Screens || {};
  const U = () => window.ui;
  const A = () => window.api;
  const el = (...a) => U().el(...a);
  const num = (x) => (x === null || x === undefined || x === "" || isNaN(+x) ? null : +x);
  const fmtNum = (n, d) => (n === null || n === undefined ? "—" : U().fmtNum(n, d));
  const fmtP = (n) => (n === null || n === undefined ? "—" : U().fmtP(n));
  const pct = (x) => (x === null || x === undefined ? "—" : fmtNum(x * 100, 1) + " %");
  const when = (ts) => (ts ? U().fmtTime(ts) : "—");
  const tick2wall = (t) => (U().tickWall ? U().tickWall(t) : null);
  const add = (node, ...kids) => { for (const k of kids.flat(Infinity)) if (k !== null && k !== undefined && k !== false) node.append(k); return node; };
  const US = "t10", VENUE = "v07";

  const S = { root: null, feed: [], feedSeq: 0, feedAt: 0, lb: [], lbAt: 0, sessions: null, sessErr: null, sig: "" };

  async function pullFeed(force) {
    if (!force && Date.now() - S.feedAt < 15000 && S.feed.length) return;
    S.feedAt = Date.now();
    for (let guard = 0; guard < 40; guard++) {
      const r = await A().recStream("feed", { since_seq: S.feedSeq, limit: 5000 });
      const rows = (r && r.rows) || [];
      for (const x of rows) {
        const p = x.payload || {};
        if (String(x.type).startsWith("bench") || p.venue === VENUE || (x.type === "venue.announcement" && x.actor === US)) S.feed.push(x);
      }
      if (rows.length) S.feedSeq = rows[rows.length - 1].seq;
      if (rows.length < 5000) break;
    }
  }
  async function pullLb(force) {
    if (!force && Date.now() - S.lbAt < 30000 && S.lb.length) return;
    S.lbAt = Date.now();
    const r = await A().recStream("leaderboard", { since_seq: 0, limit: 5000 });
    S.lb = ((r && r.rows) || []).map((x) => {
      const d = x.data || x; const us = (d.teams || []).find((t) => t.team === US) || {};
      const best = Math.max(0, ...(d.teams || []).map((t) => +t.market || 0));
      return { ts: x.ts, tick: d.tick ?? x.tick, market: num(us.market), best, rank: us.rank };
    }).filter((x) => x.market !== null);
  }
  async function pullSessions() {
    try { const r = await A().get("broker/sessions", {}, 10000); S.sessions = (r && (r.items || r.sessions)) || (Array.isArray(r) ? r : []); S.sessErr = null; }
    catch (e) { S.sessions = null; S.sessErr = e; }
  }

  // ---------- pieces ----------
  function onOff(ok, on, off) { return el("span", { class: "pill tone-" + (ok ? "ok" : "bad") }, el("span", { class: "dot" }), ok ? on : off); }
  function statusPanel(b) {
    const age = b.updated ? Date.now() / 1000 - b.updated : null;
    const alive = age !== null && age < 120;
    const ss = b.session_stats || {};
    const live = (b.active_runs || []).length > 0;
    const p = U().panel("Broker", { sub: "empareja ofertas en el Market Test y en nuestra tienda " + VENUE });
    const kp = el("div", { class: "bk-kpis" },
      U().kpi({ label: "Proceso", value: onOff(alive, "ENCENDIDO", "APAGADO"), sub: age === null ? "sin latido" : "latido hace " + U().fmtDur(age) }),
      U().kpi({ label: "Clave del broker", value: onOff(!!b.has_key, "PRESENTE", "FALTA"), sub: b.writes ? "escrituras activadas" : "escrituras desactivadas" }),
      U().kpi({ label: "Modo", value: b.mode === "stall" ? "Puesto (stall)" : b.mode === "smart" ? "Inteligente" : (b.mode || "—"), sub: "regla de cruce: " + (b.rule || "—") }),
      U().kpi({ label: "Sesión", value: live ? el("span", { class: "pill tone-ok" }, el("span", { class: "dot" }), "EN CURSO") : el("span", { class: "pill tone-mute" }, "SIN TEST"),
        sub: b.session ? b.session + (ss.start_tick != null ? " · desde t" + ss.start_tick + " (" + (b.tick - ss.start_tick + 1) + " ticks)" : "") : "esperando al próximo Market Test" }),
      U().kpi({ label: "Perfil", value: ss.profile === "hard" ? "Duro" : ss.profile === "normal" ? "Normal" : ss.profile ? "Auto" : "—", sub: "tick " + (b.tick ?? "—") }));
    const st = el("div", { class: "bk-kpis bk-kpis-2" },
      U().kpi({ label: "Cruces esta sesión", value: fmtNum(ss.matches ?? 0), sub: `${ss.refused ?? 0} rechazados · ${ss.probes ?? 0} sondeos · ${ss.fallback ?? 0} de reserva` }),
      U().kpi({ label: "Excedente estimado", value: ss.est_surplus != null ? fmtP(ss.est_surplus) : "—", sub: "valor creado en la sesión" }),
      U().kpi({ label: "Eficiencia (nuestra est.)", value: pct(num(b.efficiency_estimate)), sub: "frente al puesto: " + pct(num(b.stall_efficiency)) }),
      U().kpi({ label: "Cruces totales", value: fmtNum(b.matches_total ?? 0), sub: `${b.public_matches_total ?? 0} públicos en ${VENUE}` }));
    const errs = (b.errors || []).slice(-3);
    add(p.body, kp, st, errs.length ? el("div", { class: "bk-errs" }, errs.map((e) => el("div", { class: "bk-err" }, U().icon("alert", 13), typeof e === "string" ? e : (e.error || JSON.stringify(e))))) : null);
    return p;
  }

  // sessions: official results when the API serves them, else what the broker heartbeat keeps (vs_stall.history)
  function sessionRows(b) {
    if (Array.isArray(S.sessions) && S.sessions.length) return S.sessions.map((r) => ({
      run: r.run, tick: r.tick, official: num((r.score || {}).bench_efficiency), stall: num(r.stall_efficiency), ours: num(r.est_efficiency),
      matches: (r.stats || {}).matches, refused: (r.stats || {}).refused, probes: (r.stats || {}).probes, surplus: num((r.stats || {}).est_surplus),
      bench_points: num((r.score || {}).bench_points), mm_points: num((r.score || {}).mm_points), profile: (r.stats || {}).profile, src: "oficial" }));
    const hist = ((b.vs_stall || {}).history || []).map((h) => ({ run: h.run, ours: num(h.ours), stall: num(h.stall), basis: h.basis, below: h.below, src: "latido" }));
    const ss = b.session_stats;
    if ((b.active_runs || []).length && ss && !hist.some((h) => h.run === b.active_runs[0]))
      hist.push({ run: b.active_runs[0], tick: ss.start_tick, ours: num(b.efficiency_estimate), stall: num(b.stall_efficiency), matches: ss.matches, refused: ss.refused,
        probes: ss.probes, surplus: num(ss.est_surplus), profile: ss.profile, live: true, src: "en curso" });
    return hist;
  }
  // market points before/after each Market Test, from the leaderboard stream and bench.started ticks
  function marketDeltas() {
    const starts = S.feed.filter((x) => x.type === "bench.started").map((x) => ({ tick: x.tick, ticks: (x.payload || {}).ticks || 16, session: (x.payload || {}).session }));
    return starts.map((s) => {
      const before = S.lb.filter((x) => x.tick <= s.tick).slice(-1)[0];
      const after = S.lb.find((x) => x.tick >= s.tick + s.ticks + 1);
      return { ...s, before: before && before.market, after: after && after.market, delta: before && after ? after.market - before.market : null };
    });
  }
  function sessionsPanel(b) {
    const rows = sessionRows(b);
    const deltas = marketDeltas();
    const p = U().panel("Sesiones del Market Test", { sub: rows.length ? rows.length + " sesiones" : "" });
    if (!rows.length && !deltas.length) { add(p.body, U().empty("Aún no hay sesiones registradas.")); return p; }
    const official = Array.isArray(S.sessions) && S.sessions.length;
    const head = ["Sesión", "Inicio", "Eficiencia oficial", "Puesto (stall)", "Nuestra est.", "Cruces", "Rech.", "Sondeos", "Excedente", "Puntos test", "Puntos mercado", "Δ mercado"];
    const table = el("table", { class: "bk-table" }, el("thead", {}, el("tr", {}, head.map((h) => el("th", {}, h)))),
      el("tbody", {}, rows.map((r, i) => {
        const d = deltas[i] || {};
        const t0 = r.tick ?? d.tick;
        const w = t0 != null ? tick2wall(t0) : null;
        const beat = r.ours != null && r.stall != null ? r.ours - r.stall : null;
        return el("tr", { class: r.live ? "is-live" : "" },
          el("td", { class: "num" }, el("b", {}, r.run || "—"), r.live ? el("span", { class: "pill tone-ok bk-live" }, el("span", { class: "dot" }), "en curso") : null),
          el("td", { class: "num" }, w ? when(w) : t0 != null ? "t" + t0 : "—"),
          el("td", { class: "num" }, r.official != null ? pct(r.official) : el("span", { class: "bk-muted" }, official ? "—" : "sin API")),
          el("td", { class: "num" }, pct(r.stall)),
          el("td", { class: "num " + (beat == null ? "" : beat >= 0 ? "bk-ok" : "bk-bad") }, pct(r.ours)),
          el("td", { class: "num" }, r.matches ?? "—"), el("td", { class: "num" }, r.refused ?? "—"), el("td", { class: "num" }, r.probes ?? "—"),
          el("td", { class: "num" }, r.surplus != null ? fmtP(r.surplus) : "—"),
          el("td", { class: "num" }, r.bench_points != null ? fmtNum(r.bench_points, 2) : "—"),
          el("td", { class: "num" }, r.mm_points != null ? fmtNum(r.mm_points, 2) : "—"),
          el("td", { class: "num " + (d.delta == null ? "" : d.delta > 0 ? "bk-ok" : d.delta < 0 ? "bk-bad" : "") }, d.delta == null ? "—" : (d.delta > 0 ? "+" : "") + fmtNum(d.delta, 2)));
      })));
    add(p.body, el("div", { class: "bk-tablewrap" }, table),
      official ? null : el("div", { class: "bk-note" }, U().icon("alert", 13), "La eficiencia oficial y los puntos por sesión aún no se sirven: falta GET broker/sessions (bench/results.jsonl)."));
    return p;
  }

  // our market points across the day, with Market Test windows shaded
  function chartPanel() {
    const p = U().panel("Puntos de mercado hoy", { sub: "nosotros frente al mejor · franjas = Market Test" });
    const pts = S.lb;
    if (pts.length < 2) { add(p.body, U().empty("Aún no hay suficientes datos de la clasificación.")); return p; }
    const W = 760, H = 180, L = 36, R = 10, T = 12, B = 24;
    const t0 = pts[0].tick, t1 = Math.max(pts[pts.length - 1].tick, t0 + 1);
    const ymax = Math.max(30, ...pts.map((x) => x.best || 0));
    const x = (t) => L + ((t - t0) / (t1 - t0)) * (W - L - R), y = (v) => T + (1 - v / ymax) * (H - T - B);
    let s = "";
    for (const v of [0, 10, 20, 30].filter((v) => v <= ymax)) s += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)"/><text x="${L - 6}" y="${y(v) + 3}" text-anchor="end" class="bk-ax">${v}</text>`;
    for (const d of marketDeltas()) if (d.tick + d.ticks >= t0) s += `<rect x="${x(Math.max(t0, d.tick))}" y="${T}" width="${Math.max(2, x(d.tick + d.ticks) - x(Math.max(t0, d.tick)))}" height="${H - T - B}" fill="var(--t-cambio)" opacity=".12"/>`;
    const path = (k) => pts.map((p2, i) => (i ? "L" : "M") + x(p2.tick).toFixed(1) + " " + y(p2[k]).toFixed(1)).join(" ");
    s += `<path d="${path("best")}" fill="none" stroke="var(--ink-3)" stroke-dasharray="4 3" stroke-width="1.5"/>`;
    s += `<path d="${path("market")}" fill="none" stroke="var(--t-cambio)" stroke-width="2"/>`;
    const last = pts[pts.length - 1];
    s += `<circle cx="${x(last.tick)}" cy="${y(last.market)}" r="3.5" fill="var(--t-cambio)"/><text x="${x(last.tick) - 6}" y="${y(last.market) - 8}" text-anchor="end" class="bk-lab">${fmtNum(last.market, 2)}</text>`;
    s += `<text x="${L}" y="${H - 6}" class="bk-ax">t${t0}</text><text x="${W - R}" y="${H - 6}" text-anchor="end" class="bk-ax">t${t1}</text>`;
    const box = el("div", { class: "bk-chart" }); box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="xMidYMid meet">${s}</svg>`;
    add(p.body, box, el("div", { class: "bk-legend" }, el("span", { class: "bk-lg-us" }, "— Nosotros"), el("span", { class: "bk-lg-best" }, "- - Mejor equipo"), el("span", { class: "bk-lg-mt" }, "■ Market Test")));
    return p;
  }

  // live session book/plan/results per tick: needs GET broker/session/<run>
  function livePanel(b) {
    const run = (b.active_runs || [])[0] || ((b.vs_stall || {}).history || []).slice(-1).map((h) => h.run)[0];
    const p = U().panel("Sesión en directo", { sub: run ? "run " + run : "" });
    const r = S.liveRun;
    if (r && r.run === run && Array.isArray(r.rows) && r.rows.length) {
      const ticks = r.rows.filter((x) => x.type === "tick").slice(-16).reverse();
      add(p.body, el("div", { class: "bk-list" }, ticks.map((t) => el("div", { class: "bk-tick" },
        el("div", { class: "bk-tick-h" }, el("b", { class: "num" }, "t" + t.tick), el("span", { class: "bk-muted" }, (t.bench || []).length + " ofertas del test"),
          el("span", { class: "bk-muted" }, (t.plan || []).length + " planeados"), el("span", { class: "bk-sp" }),
          el("span", { class: "tag res tone-" + ((t.results || []).some((x) => x.status !== "ok") ? "warn" : "ok") }, (t.results || []).filter((x) => x.status === "ok").length + " cruces")),
        (t.results || []).map((x) => el("div", { class: "bk-res" }, el("span", { class: "num" }, x.sell + " → " + x.buy), el("b", { class: "num" }, fmtP(x.price)),
          el("span", { class: "tag res tone-" + (x.status === "ok" ? "ok" : "bad") }, x.status === "ok" ? "cruzado" : (x.error || x.status)),
          x.message ? el("span", { class: "bk-muted" }, x.message) : null))))));
    } else {
      const ss = b.session_stats || {};
      add(p.body, el("div", { class: "bk-pad" },
        (b.active_runs || []).length
          ? el("p", {}, `Sesión ${b.session} en curso desde t${ss.start_tick}: ${ss.matches ?? 0} cruces, ${ss.refused ?? 0} rechazados, excedente estimado ${fmtP(ss.est_surplus)}.`)
          : el("p", { class: "bk-muted" }, "No hay un Market Test en curso."),
        el("div", { class: "bk-note" }, U().icon("alert", 13), "El libro del test, los cruces planeados y sus resultados por tick aún no se sirven: falta GET broker/session/<run> (data/live/bench/<día>-<run>.jsonl).")));
    }
    return p;
  }

  // v07: our venue's public book and trades settled on it
  function venuePanel(book) {
    const trades = S.feed.filter((x) => x.type === "settlement" && (x.payload || {}).venue === VENUE).slice().reverse();
    const offers = ((book && (book.offers || (book.data || {}).offers)) || []).filter((o) => !o.status || o.status === "open");
    const p = U().panel("Nuestra tienda " + VENUE, { sub: `${offers.length} ofertas abiertas · ${trades.length} cruces públicos` });
    const side = (s) => [s && s.cash ? fmtP(s.cash) : null, ...((s && s.assets) || []).map((a) => a.ref || "#" + a.id), ...((s && s.types) || []).map((t) => String(t).replace(/^card:/, ""))].filter(Boolean).join(" + ") || "—";
    const kind = (o) => (o.give && o.give.cash ? "compra" : (o.want && o.want.cash) ? "venta" : "cambio");
    const tl = el("div", { class: "bk-list" });
    if (!trades.length) add(tl, U().empty("Aún no hay cruces públicos en " + VENUE + "."));
    else U().keyedList(tl, trades.slice(0, 40), { key: (x) => String(x.seq), render: (x) => {
      const pl = x.payload || {};
      return U().row({ type: "cambio", cols: "86px auto minmax(0,1fr) auto", cells: [
        { v: el("span", { class: "num" }, when(x.seen_at || x.ts)), cls: "bk-time" },
        el("span", { class: "bk-who" }, U().teamTag(pl.parties && pl.parties[0], { us: pl.parties && pl.parties[0] === US }), " → ", U().teamTag(pl.parties && pl.parties[1], { us: pl.parties && pl.parties[1] === US })),
        (pl.items || []).map((i) => i.ref).join(", "),
        { v: el("b", { class: "num" }, fmtP(pl.price)), align: "right" }] });
    } });
    const ol = el("div", { class: "bk-list" });
    if (!offers.length) add(ol, U().empty("El libro de " + VENUE + " está vacío."));
    else U().keyedList(ol, offers.slice(0, 60), { key: (o) => String(o.id), sig: (o) => o.status + "|" + o.expires_tick, render: (o) => U().row({ type: kind(o), cols: "auto minmax(0,1fr) minmax(0,1fr) auto", cells: [
      U().typeChip(kind(o)), el("span", {}, "da ", el("b", {}, side(o.give))), el("span", {}, "pide ", el("b", {}, side(o.want))),
      { v: el("span", { class: "num bk-muted" }, o.expires_tick ? "vence t" + o.expires_tick : ""), align: "right" }] }) });
    add(p.body, el("div", { class: "bk-two" }, el("div", {}, el("div", { class: "bk-cap" }, "Cruces públicos"), tl), el("div", {}, el("div", { class: "bk-cap" }, "Libro público"), ol)));
    return p;
  }

  async function load(force) {
    const [b, book] = await Promise.all([A().broker().catch(() => ({})), A().rec("books/" + VENUE).catch(() => null)]);
    await Promise.all([pullFeed(force).catch(() => {}), pullLb(force).catch(() => {}), pullSessions()]);
    const run = (b.active_runs || [])[0];
    if (run) { try { S.liveRun = { run, rows: ((await A().get("broker/session/" + encodeURIComponent(run), {}, 3000)) || {}).rows }; } catch (e) { S.liveRun = null; } }
    return { b: b || {}, book };
  }

  window.Screens.broker = {
    title: "Broker",
    mount(root) {
      S.root = root;
      root.replaceChildren(el("div", { class: "scr-broker" }, el("div", { class: "bk-top" }, U().loading()),
        el("div", { class: "bk-mid" }), el("div", { class: "bk-bot" }), el("div", { class: "bk-ven" })));
    },
    async refresh(root, data, params, opts) {
      S.root = root;
      const d = await load(opts && opts.force);
      const wrap = root.querySelector(".scr-broker"); if (!wrap) return;
      const sig = JSON.stringify([d.b.updated, d.b.tick, (d.b.session_stats || {}).matches, S.feed.length, S.lb.length, S.sessions && S.sessions.length,
        S.liveRun && S.liveRun.rows && S.liveRun.rows.length, d.book && d.book.tick]);
      if (sig === S.sig && !(opts && opts.force)) return;
      S.sig = sig;
      U().keepScroll(wrap, () => {
        wrap.querySelector(".bk-top").replaceChildren(statusPanel(d.b));
        wrap.querySelector(".bk-mid").replaceChildren(sessionsPanel(d.b));
        wrap.querySelector(".bk-bot").replaceChildren(chartPanel(), livePanel(d.b));
        wrap.querySelector(".bk-ven").replaceChildren(venuePanel(d.book));
      });
    },
    unmount() { S.root = null; S.sig = ""; },
  };
})();
