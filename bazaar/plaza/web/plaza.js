// Plaza: the shell of v07 Market. Top bar with the clock, side nav with the status box, router, the closed and
// paused overlay. One screen per file registers itself:
//   Plaza.screen("home", { title: "home.title", needsTeam: true, render(root, ctx) { …; return stop; } });
// ctx: { params, query, me, status, go(path), t }. `render` may return a function, called when the screen is left.
(function () {
  "use strict";
  const K = window.K, API = window.API, I18N = window.I18N;
  const t = (k, v) => I18N.t(k, v);
  const ADMIN = document.body.dataset.app === "admin";
  const ROOT = ADMIN ? "/plaza/admin" : "/plaza";

  // ---- routes: path -> screen and its parameters
  const ROUTES = ADMIN ? [
    [/^\/plaza\/admin\/?$/, "overview"],
    [/^\/plaza\/admin\/(overview|performance|matchmaker|trades|teams|activity|suggestions|venue|docs)$/, (m) => m[1]],
  ] : [
    [/^\/plaza\/?$/, "landing"], [/^\/plaza\/connect$/, "connect"], [/^\/plaza\/how$/, "how"], [/^\/plaza\/agents$/, "agents"],
    [/^\/plaza\/(home|me)$/, "home"], [/^\/plaza\/(activity|floor)$/, "activity"], [/^\/plaza\/offers$/, "offers"],
    [/^\/plaza\/(?:offers|match)\/(m-[0-9a-f]{10})$/, "offers", (m) => ({ match: m[1] })],
    [/^\/plaza\/cards$/, "cards"], [/^\/plaza\/(market|wall)$/, "market"],
    [/^\/plaza\/card\/([A-Z]{3}-\d{2})$/, "card", (m) => ({ ref: m[1] })],
    [/^\/plaza\/team\/(t\d{2})$/, "market", (m) => ({ team: m[1] })],
    [/^\/plaza\/settings$/, "settings"], [/^\/plaza\/suggest$/, "suggest"], [/^\/plaza\/docs$/, "docs"], [/^\/plaza\/_kit$/, "kit"],
  ];
  const NAV = ADMIN
    ? ["overview", "performance", "matchmaker", "trades", "teams", "activity", "suggestions", "venue", "docs"].map((n) => ({ name: n, path: "/plaza/admin/" + n, icon: { docs: "api", trades: "offers", suggestions: "suggest" }[n] || n }))
    : [{ name: "home", path: "/plaza/home", icon: "home" }, { name: "cards", path: "/plaza/cards", icon: "cards" },
       { name: "offers", path: "/plaza/offers", icon: "offers", badge: "trades" }, { name: "activity", path: "/plaza/activity", icon: "activity" },
       { name: "market", path: "/plaza/market", icon: "market" }, { name: "docs", path: "/plaza/docs", icon: "api" },
       { name: "how", path: "/plaza/how", icon: "how" }];

  const screens = {};
  const state = { me: null, status: null, admin: null, current: null, leave: null, dismissed: null, tickAt: 0 };
  const dom = {};

  function screen(name, def) { screens[name] = def; }

  function match(path) {
    for (const [rx, name, params] of ROUTES) {
      const m = rx.exec(path);
      if (m) return { name: typeof name === "function" ? name(m) : name, params: params ? params(m) : {} };
    }
    return null;
  }

  function go(path, replace) {
    if (path !== location.pathname + location.search) history[replace ? "replaceState" : "pushState"]({}, "", path);
    document.body.classList.remove("nav-open");
    render();
  }

  // ---- the shell
  function buildShell() {
    dom.time = K.el("span", { class: "num" }, "–");
    dom.tick = K.el("span", { class: "num" }, "–");
    dom.bar = K.el("i", { style: { width: "0%" } });
    dom.next = K.el("span", { class: "num" }, "–");
    dom.refresh = K.el("button", { class: "tb-btn", type: "button", title: t("shell.refresh"), "aria-label": t("shell.refresh"), onclick: () => {
      dom.refresh.classList.add("spin");
      setTimeout(() => dom.refresh.classList.remove("spin"), 600);
      anon(false);
      Promise.all([loadStatus(), loadMe()]).then(render);
    } }, K.icon("refresh", 16));
    dom.topbar = K.el("header", { class: "topbar" },
      K.el("button", { class: "tb-btn tb-menu", type: "button", "aria-label": t("shell.menu"), onclick: () => document.body.classList.toggle("nav-open") }, K.icon("menu", 16)),
      K.link(ADMIN ? "/plaza/admin/" : state.me ? "/plaza/home" : "/plaza/", { class: "brand" }, K.el("span", { class: "brand-mark" }, "M"),
        K.el("span", { class: "brand-name" }, "v07 Market"), ADMIN ? K.el("span", { class: "brand-sub" }, t("shell.admin")) : null),
      K.el("div", { class: "tb-clock" },
        K.el("div", { class: "tb-cell tb-time" }, K.label(t("shell.time")), dom.time),
        K.el("div", { class: "tb-cell" }, K.label(t("shell.tick")), dom.tick),
        K.el("div", { class: "tb-cell" }, K.label(t("shell.nextTick")), K.el("span", { class: "tb-bar" }, dom.bar), dom.next)),
      dom.refresh);
    dom.nav = K.el("nav", { class: "sidenav", "aria-label": t("shell.menu") });
    dom.main = K.el("main", { class: "main", id: "main" });
    const app = document.getElementById("app");
    K.clear(app);
    K.add(app, [dom.topbar, K.el("div", { class: "layout" }, dom.nav, dom.main)]);
  }

  function drawNav() {
    const trades = state.me && state.me.trades ? (state.me.trades.proposed || 0) + (state.me.trades.offer_on_v07 || 0) + (state.me.trades.accepted || 0) : 0;
    const items = NAV.map((n) => K.link(n.path, { class: "nav-item" + (state.current === n.name ? " active" : ""), "aria-current": state.current === n.name ? "page" : null },
      K.icon(n.icon, 16), K.el("span", null, t("nav." + (ADMIN ? "admin." : "") + n.name)),
      n.badge === "trades" && trades ? K.el("span", { class: "nav-badge" }, String(trades)) : null));
    const s = state.status || {};
    const waiting = s.market && s.market !== "open";
    const rows = ADMIN
      ? ((state.admin && state.admin.processes) || []).map((p) => ({ name: p.name, state: p.state }))
      : [{ name: t("status.agent"), state: s.agent || (state.me ? "offline" : "off") }, { name: t("status.market"), state: s.market || "stale" },
         { name: t("status.matchmaker"), state: waiting ? "waiting" : s.matchmaker || "stale" }];
    const lang = K.el("div", { class: "lang-switch", role: "group", "aria-label": t("shell.language") }, I18N.LANGS.map((l) =>
      K.el("button", { type: "button", class: l === I18N.lang ? "active" : null, "aria-pressed": String(l === I18N.lang), onclick: () => I18N.setLang(l) }, l.toUpperCase())));
    K.clear(dom.nav);
    K.add(dom.nav, [K.el("div", { class: "nav-list" }, items), K.statusBox(rows),
      K.el("div", { class: "nav-foot" }, lang,
        ADMIN ? K.btn(t("shell.publicPage"), { href: "/plaza/", small: true }) : [
          K.link("/plaza/suggest", { class: "btn sm" }, K.icon("suggest", 13), t("nav.suggest")),
          K.link("/plaza/settings", { class: "btn sm", "aria-label": t("nav.settings"), title: t("nav.settings") }, K.icon("settings", 13))])]);
  }

  // ---- the clock: the wall time, the tick, and the seconds to the next one counted locally between polls
  function drawClock() {
    const s = state.status;
    dom.time.textContent = new Date().toLocaleTimeString("en-GB");
    if (!s) return;
    const running = s.game === "open" && typeof s.seconds_to_tick === "number";
    let left = running ? (state.tickAt - Date.now()) / 1000 : null, tick = s.tick;
    const len = s.tick_seconds || 15;
    while (running && left < 0) { left += len; tick += 1; }
    dom.tick.textContent = typeof tick === "number" ? String(tick) : "–";
    dom.next.textContent = running ? Math.ceil(left) + " s" : t("status." + (s.game === "paused" ? "paused" : "closed")).toLowerCase();
    dom.bar.style.width = running ? Math.max(0, Math.min(100, 100 - (left / len) * 100)) + "%" : "0%";
  }

  function loadStatus() {
    const jobs = [API.get("/api/status").then((s) => {
      state.status = s;
      if (typeof s.seconds_to_tick === "number") state.tickAt = Date.now() + s.seconds_to_tick * 1000;
    }, () => { state.status = { ...(state.status || {}), market: "stale", matchmaker: "stale", feed: "stale" }; })];
    if (ADMIN) jobs.push(API.get("/admin/api/status").then((a) => { state.admin = a; }, () => {}));
    return Promise.all(jobs).then(() => { drawNav(); drawClock(); drawOverlay(); });
  }
  function anon(set) {
    try {
      if (set === true) sessionStorage.setItem("plaza.anon", "1");
      else if (set === false) sessionStorage.removeItem("plaza.anon");
      return sessionStorage.getItem("plaza.anon") === "1";
    } catch (e) { return false; }
  }
  function loadMe() {
    if (ADMIN) return Promise.resolve();
    // A browser that was told "no session" stops asking (no 401 every poll) until Connect starts a new one.
    if (!API.mock && anon()) { state.me = null; state.meError = false; return Promise.resolve(); }
    return API.get("/api/me").then((me) => { state.me = me; state.meError = false; }, (e) => {
      const none = e && [401, 403, 404].includes(e.status);
      if (none) { state.me = null; anon(true); }
      state.meError = !none;                        // the market did not answer: keep what we knew, say so
    });
  }

  // ---- closed and paused: the dashboard's overlay over the screen
  function drawOverlay() {
    const s = state.status || {};
    const old = dom.main.querySelector(".closed-overlay");
    if (old) old.remove();
    const def = screens[state.current] || {};
    const kind = s.market === "closed" || s.market === "off" ? "closed" : s.market === "paused" ? "paused" : null;
    if (!kind || def.bare || def.noOverlay || state.dismissed === kind + ":" + s.tick) return;
    const opens = typeof s.opens_in_s === "number" ? Math.max(0, s.opens_in_s) : null;
    const hms = opens === null ? null : [Math.floor(opens / 3600), Math.floor((opens % 3600) / 60), opens % 60].map((x, i) => (i ? String(x).padStart(2, "0") : String(x))).join(":");
    dom.main.appendChild(K.el("div", { class: "closed-overlay" }, K.el("div", { class: "closed-card" + (kind === "paused" ? " is-paused" : ""), role: "dialog", "aria-label": t("closed." + kind + ".title") },
      K.el("h2", null, K.icon(kind === "paused" ? "pause" : "lock", 18), t("closed." + kind + ".title")),
      K.el("div", { class: "closed-sub" }, kind === "paused" ? t("closed.paused.sub", { tick: s.tick }) : typeof s.opens_tick === "number" ? t("closed.closed.sub", { tick: s.opens_tick }) : t("closed.closed.subNoTick")),
      hms ? K.el("div", { class: "closed-count" }, hms) : null,
      K.el("p", null, t("closed." + kind + ".text")),
      K.btn(t("closed.keepLooking"), { onclick: () => { state.dismissed = kind + ":" + s.tick; drawOverlay(); } }))));
  }

  // ---- drawing a screen
  function render() {
    if (state.leave) { try { state.leave(); } catch (e) { console.error(e); } state.leave = null; }
    const found = match(location.pathname);
    const name = found ? found.name : null;
    const def = name ? screens[name] : null;
    state.current = name;
    document.body.classList.toggle("bare", Boolean(def && def.bare));
    document.body.classList.toggle("no-nav", Boolean(def && def.noNav));
    drawNav();
    K.clear(dom.main);
    const root = dom.main.appendChild(K.el("div", { class: "page scr-" + (name || "none") }));
    dom.main.scrollTop = 0;
    document.title = (def && def.title ? t(def.title) + " · " : "") + "v07 Market";
    if (!def) {
      root.appendChild(K.state("empty", t("shell.notFound"), location.pathname, K.btn(t("shell.goHome"), { onclick: () => go(ROOT + "/") })));
      return;
    }
    if (def.needsTeam && !state.me && state.meError) {
      root.appendChild(K.state("error", t("common.error"), t("shell.noAnswer"), K.btn(t("common.retry"), { onclick: () => loadMe().then(render) })));
      return;
    }
    if (def.needsTeam && !state.me) {
      root.appendChild(K.state("offline", t("shell.connectFirst"), t("shell.connectFirstText"),
        K.btn(t("shell.connect"), { kind: "primary", iconAfter: "arrow", onclick: () => go("/plaza/connect") })));
      return;
    }
    const ctx = { params: found.params, query: Object.fromEntries(new URLSearchParams(location.search)), me: state.me, status: state.status, go, t };
    try {
      const leave = def.render(root, ctx);
      state.leave = typeof leave === "function" ? leave : null;
    } catch (e) {
      console.error(e);
      K.clear(root).appendChild(K.state("error", t("common.error"), String(e && e.message || e)));
    }
    drawOverlay();
  }

  function boot() {
    buildShell();
    window.addEventListener("popstate", render);
    I18N.onChange(() => { buildShell(); render(); drawClock(); });
    Promise.all([loadStatus(), loadMe()]).then(render, render);
    setInterval(drawClock, 250);
    setInterval(loadStatus, 5000);
    setInterval(() => loadMe().then(drawNav), 15000);
  }

  window.Plaza = { screen, adminScreen: screen, go, state, admin: ADMIN, refresh: () => { anon(false); return Promise.all([loadStatus(), loadMe()]).then(render); } };
  document.addEventListener("DOMContentLoaded", boot);
})();
