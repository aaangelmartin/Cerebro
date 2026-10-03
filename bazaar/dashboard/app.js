/* app.js — hash router, 3 s refresh, top bar, menu with status box, notifications (toasts + bell), global states. */
(function () {
  "use strict";
  const { el, icon, iconSvg, fmtNum, fmtP, fmtTime, fmtDur, fmtAgo } = window.ui;
  const api = window.api;
  window.Screens = window.Screens || {};

  const NAV = [
    ["home", "Home", "home"], ["cerebro", "Cerebro", "cerebro"], ["coleccion", "Colección", "coleccion"], ["mercado", "Mercado", "mercado"], ["broker", "Broker", "broker"],
    ["duelos", "Duelos", "duelo"], ["competicion", "Competición", "competicion"], ["rivales", "Rivales", "rivales"],
    ["supervision", "Supervisión", "supervision"], ["laboratorio", "Laboratorio", "laboratorio"], ["bot", "Bot", "bot"],
  ];
  const IDS = NAV.map((n) => n[0]);
  const EVENT_NAMES = { bench: "Market Test", duels: "Duelos", duel_session: "Duelos", round: "Ronda", set_release: "Nuevo set",
    level: "Nivel", persona: "Nuevo dealer", venue: "Tiendas", fee: "Comisiones", day_opens: "Apertura", day_closes: "Cierre" };

  const $ = (id) => document.getElementById(id);
  const S = {
    route: null, screen: null, params: "", mounted: false, data: null, apiDown: false, lastOk: 0, inflight: false,
    rec: { me: null, leaderboard: null, clock: null, venues: null, my_offers: null, dealers: null }, recAt: 0,
    dealerUse: {}, dealerAt: 0, notif: [], notifSince: null, notifInit: false, closedDismissed: false,
  };

  // ------------------------------------------------------------------ prefs (localStorage, never required)
  const PREF_KEY = "bazaar.dash.notif";
  const NOTIF_GROUPS = [
    ["aprobar", "Pendientes de aprobar"], ["breaker", "Disyuntores y errores"], ["gran", "Grandes operaciones"],
    ["novedad", "Nuevos dealers y novedades"], ["duelo", "Sesiones de duelos"], ["broker", "Broker y Market Test"],
    ["lab", "Laboratorio"], ["limite", "Cambios de límites"],
  ];
  function loadPrefs() {
    let p = {};
    try { p = JSON.parse(localStorage.getItem(PREF_KEY) || "{}") || {}; } catch (e) { p = {}; }
    return Object.assign({ toasts: true, muteUntil: 0, types: { limite: false, lab: false }, readTs: 0 }, p);
  }
  let prefs = loadPrefs();
  function savePrefs() { try { localStorage.setItem(PREF_KEY, JSON.stringify(prefs)); } catch (e) { /* private mode */ } }
  function groupOf(type) {
    const t = String(type || "").toLowerCase();
    if (t.startsWith("aprobar") || t.startsWith("pendiente")) return "aprobar";
    if (t.startsWith("breaker") || t.startsWith("error") || t.startsWith("alerta") || t.startsWith("disyuntor")) return "breaker";
    if (t.startsWith("gran") || t.startsWith("deal") || t.startsWith("outcome")) return "gran";
    if (t.startsWith("novedad") || t.startsWith("novelty") || t.startsWith("dealer")) return "novedad";
    if (t.startsWith("duel")) return "duelo";
    if (t.startsWith("broker")) return "broker";
    if (t.startsWith("limite")) return "limite";
    return "lab";
  }

  // ------------------------------------------------------------------ shell
  function buildNav() {
    const nav = $("nav-list");
    nav.innerHTML = "";
    for (const [id, label, ic] of NAV) {
      nav.appendChild(el("a", { href: "#" + id, class: "nav-item", dataset: { id } }, icon(ic, 16), el("span", null, label),
        el("span", { class: "nav-badge num", id: "nav-badge-" + id, hidden: true })));
    }
  }
  function parseHash() {
    const h = decodeURIComponent((location.hash || "").replace(/^#\/?/, ""));
    const i = h.indexOf("/");
    let id = i < 0 ? h : h.slice(0, i);
    const params = i < 0 ? "" : h.slice(i + 1);
    if (!IDS.includes(id)) id = "home";
    return { id, params };
  }
  function route() {
    const { id, params } = parseHash();
    if (S.route === id && S.mounted) {
      if (params !== S.params) {
        S.params = params;
        const sc = window.Screens[id];
        if (sc && sc.onParams) { try { sc.onParams($("screen"), params); } catch (e) { console.error(e); } }
        else remount(id, params);
        refreshScreen();
      }
      return;
    }
    remount(id, params);
  }
  function remount(id, params) {
    const root = $("screen");
    const old = S.screen;
    if (old && old.unmount) { try { old.unmount(root); } catch (e) { console.error(e); } }
    window.ui.closeDrawer(true);
    root.innerHTML = "";
    root.className = "screen scr-" + id;
    root.scrollTop = 0;
    S.route = id; S.params = params; S.screen = window.Screens[id] || null; S.mounted = true;
    document.querySelectorAll(".nav-item").forEach((a) => a.classList.toggle("active", a.dataset.id === id));
    const label = (NAV.find((n) => n[0] === id) || [])[1] || id;
    document.title = label + " · Bazaar";
    if (!S.screen) {
      root.appendChild(el("div", { class: "placeholder" }, el("h1", null, label), el("p", null, "En construcción.")));
      return;
    }
    try { S.screen.mount(root, params); } catch (e) { console.error(e); root.appendChild(window.ui.error(e)); }
    if (S.data) refreshScreen();
  }
  async function refreshScreen(force) {
    const sc = S.screen;
    if (!sc || !sc.refresh || !S.data) return;
    const route = S.route;
    try { await sc.refresh($("screen"), S.data, S.params, { force: !!force }); }
    catch (e) { if (route === S.route) console.error("refresh " + route, e); if (force) throw e; }
  }

  // ------------------------------------------------------------------ loop
  // Each tick carries a generation: a forced refresh starts a new one, so a slower tick that was already
  // in flight can never overwrite the fresh data when its responses arrive later.
  S.gen = 0;
  async function tick(force) {
    if (S.inflight && !force) return;
    const gen = force ? ++S.gen : S.gen;
    S.inflight = true;
    try {
      const data = await api.overview();
      if (gen !== S.gen) return;
      S.data = data; S.lastOk = Date.now(); S.apiDown = false;
      window.ui.setClock(data.clock, data.now);
      await loadRec(!!force);
      if (gen !== S.gen) return;
      if (force) tickMapAt = 0;
      loadTickMap();
      renderTop(data);
      renderStatus(data);
      renderBanners(data);
      await refreshScreen(force);
    } catch (e) {
      if (gen !== S.gen) return;
      if (force) throw e;
      S.apiDown = true;
      renderBanners(S.data);
    } finally { if (gen === S.gen) S.inflight = false; }
    pollNotifications();
    pollOutbox();
    pollKeys();
  }
  // Anthropic keys: one model for the sidebar, the banner, the toasts and the Bot screen (window.__keyHealth)
  let keysAt = 0, keysPrev = null, healthMissing = false;
  async function pollKeys(force) {
    if (!force && Date.now() - keysAt < 12000) return;
    keysAt = Date.now();
    try {
      let health = null;
      if (!healthMissing) { try { health = await api.llmHealth(); } catch (e) { if (e && e.status === 404) healthMissing = true; } }
      const [sp, llm] = await Promise.all([api.spend(), health ? Promise.resolve(null) : api.llm(null, 400).catch(() => null)]);
      const kh = window.ui.keyHealth(sp, (llm && llm.items) || [], health);
      window.__keyHealth = kh;
      const sig = kh.keys.map((k) => k.label + ":" + k.state).join(",");
      if (keysPrev !== null && sig !== keysPrev) {
        const before = Object.fromEntries(keysPrev.split(",").filter(Boolean).map((x) => x.split(":")));
        for (const k of kh.keys) {
          if (!k.ok && before[k.label] === "ok") window.ui.toast({ type: "error", title: `Clave ${k.label}: ${k.chip.toLowerCase()}`,
            text: kh.allDown ? "Ninguna clave funciona: el bot juega sin Claude." : "El bot sigue con " + listKeys(kh.okLabels) + ". " + k.text, href: "#bot", ttl: 12000 });
          if (k.ok && before[k.label] && before[k.label] !== "ok") window.ui.toast({ type: "deal", title: `Clave ${k.label} vuelve a funcionar`, href: "#bot" });
        }
      }
      keysPrev = sig;
      if (S.data) { renderStatus(S.data); renderBanners(S.data); }
    } catch (e) { /* the API banner already covers a dead API */ }
  }
  const listKeys = (ls) => (ls.length ? ls.slice(0, -1).join(", ") + (ls.length > 1 ? " y " : "") + ls[ls.length - 1] : "ninguna");
  function keysBlock() {
    const kh = window.__keyHealth;
    if (!kh || !kh.keys.length) return null;
    const n = kh.keys.length, ok = n - kh.bad.length;
    const tone = kh.allDown ? "bad" : kh.bad.some((k) => k.tone === "bad") ? "bad" : kh.bad.length ? "warn" : "ok";
    return el("a", { class: "sb-sec sb-keys", href: "#bot" },
      el("div", { class: "sb-line" }, el("span", null, "Claude"), pill(kh.allDown ? "SIN CLAUDE" : ok + "/" + n + " CLAVES", tone)),
      el("div", { class: "sb-sub" }, kh.allDown ? "ninguna clave funciona: juega con reglas" : kh.bad.length
        ? kh.bad.map((k) => "Clave " + k.label + ": " + k.chip.toLowerCase()).join(" · ") : "todas las claves responden"));
  }
  // open items in the brain's outbox (what the team must do by hand) -> badge on the Cerebro nav entry
  let outboxAt = 0;
  async function pollOutbox(force) {
    if (!force && Date.now() - outboxAt < 10000) return;
    outboxAt = Date.now();
    let n = 0;
    try {
      const r = await api.outbox();
      const items = Array.isArray(r) ? r : (r && r.items) || [];
      n = items.filter((x) => x && (x.status === "open" || x.status === "draft")).length;
    } catch (e) { n = 0; }
    const nb = $("nav-badge-cerebro");
    if (nb) { nb.textContent = n > 99 ? "99+" : String(n); nb.hidden = !n; nb.classList.toggle("is-alert", n > 0); nb.title = n ? n + " cosas para el equipo" : ""; }
  }
  window.__pollOutbox = () => pollOutbox(true);
  let tickMapAt = 0;
  async function loadTickMap() {
    if (Date.now() - tickMapAt < 30000) return;
    tickMapAt = Date.now();
    try { const r = await api.recStream("clock", { since_seq: 0, limit: 5000 }); window.ui.setTickMap((r && r.rows) || []); }
    catch (e) { tickMapAt = 0; }
  }
  async function loadRec(force) {
    const now = Date.now();
    if (!force && now - S.recAt < 10000) return;
    S.recAt = now;
    const names = ["me", "leaderboard", "clock", "venues", "my_offers", "dealers"];
    const got = await Promise.allSettled(names.map((n) => api.rec(n)));
    got.forEach((r, i) => { if (r.status === "fulfilled") S.rec[names[i]] = r.value; });
    if (S.rec.me && (S.rec.me.score || (S.rec.me.data || {}).score)) window.__meScore = S.rec.me.score || S.rec.me.data.score;
    if (now - S.dealerAt > 30000) {
      S.dealerAt = now;
      try {
        const out = await api.outcomes(null, 800);
        const since = Date.now() / 1000 - 3600;
        const use = {};
        for (const o of (out && out.items) || []) {
          if (o.domain !== "dealers" || (Number(o.ts) || 0) < since) continue;
          if (!["deal", "sent"].includes(o.status) || !/accept|buy|sell|deal/.test(String(o.kind || ""))) continue;
          const who = (o.params && (o.params.with || o.params.dealer || o.params.persona)) || o.with || o.dealer;
          if (who) use[who] = (use[who] || 0) + 1;
        }
        S.dealerUse = use;
      } catch (e) { /* keep last */ }
    }
  }

  // ------------------------------------------------------------------ top bar
  function stat(label, value, sub) {
    return el("div", { class: "tb-stat" }, el("div", { class: "tb-label" }, label),
      el("div", { class: "tb-value num" }, value, sub ? el("span", { class: "tb-sub" }, " " + sub) : null));
  }
  function myTeam() {
    const lb = S.rec.leaderboard;
    const teams = lb && (lb.teams || (lb.data && lb.data.teams));
    if (!Array.isArray(teams)) return null;
    return teams.find((t) => t.team === "t10") || null;
  }
  function renderTop(d) {
    const st = d.status || {}, team = d.team || {}, spend = d.spend || {};
    const me = S.rec.me || {}, lbMe = myTeam() || {};
    const cash = st.cash !== undefined && st.cash !== null ? st.cash : me.cash;
    const assets = Array.isArray(me.assets) ? me.assets : [];
    // the game's own figure (copies beyond the first count less, page bonuses included); the sum of the cards only as a fallback
    const value = Number(me.collection_value) > 0 ? Number(me.collection_value) : assets.reduce((a, x) => a + (Number(x.your_value) || 0), 0);
    const hasVenue = !!(team.venue || lbMe.venue);
    const level = lbMe.level !== undefined ? lbMe.level : me.level;
    const unlocked = Array.isArray(me.unlocked) ? me.unlocked.length : null;
    const g = $("tb-stats");
    g.replaceChildren(
      el("div", { class: "tb-group" }, stat("Puntos", fmtNum(team.score, 1), team.rank ? team.rank + ".º de " + (team.teams || "—") : "")),
      el("div", { class: "tb-group" }, stat("Dinero", fmtP(cash), hasVenue ? "+" + fmtNum(d.bond || 250) + " fianza" : ""),
        stat("Valor colección", assets.length ? fmtP(value) : "—")),
      el("div", { class: "tb-group" }, stat("Nivel", level !== undefined && level !== null ? String(level) : "—", unlocked !== null ? unlocked + " dealers" : ""),
        stat("Álbum", lbMe.album_slots ? lbMe.album_filled + "/" + lbMe.album_slots : (assets.length ? String(assets.length) : "—"),
          lbMe.pages_complete !== undefined ? lbMe.pages_complete + " págs" : "")),
      el("div", { class: "tb-group" }, stat("API hoy", spend.usd !== undefined && spend.usd !== null ? fmtNum(spend.usd, 2) + " $" : "—", spend.cap ? "de " + fmtNum(spend.cap, 0) : "")),
    );
    renderClock();
  }
  function evName(a) { return EVENT_NAMES[a] || (a ? String(a).replace(/_/g, " ") : "—"); }
  function renderClock() {
    const d = S.data; if (!d) return;
    const c = d.clock || {};
    const ageS = (Date.now() / 1000) - (d.now || Date.now() / 1000);
    const nextTick = c.next_tick_in !== null && c.next_tick_in !== undefined ? Math.max(0, c.next_tick_in - ageS) : null;
    let ev = "—";
    const ne = c.next_event;
    if (ne) {
      if (ne.at) ev = [evName(ne.action), " · ", fmtTime(ne.at, false), " ", el("span", { class: "tb-accent" }, "en " + fmtDur(ne.at - Date.now() / 1000))];
      else ev = evName(ne.action) + (ne.at_hours !== undefined ? " · h" + fmtNum(ne.at_hours, 1) : "");
    }
    const madrid = new Date().toLocaleTimeString("es-ES", { timeZone: "Europe/Madrid", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
    $("tb-wall").replaceChildren(el("span", { class: "tb-label" }, "Madrid"), el("span", { class: "num" }, madrid));
    $("tb-clock").replaceChildren(
      el("div", { class: "tb-cell" }, el("span", { class: "tb-label" }, "Tick"), el("span", { class: "num" }, c.tick !== undefined && c.tick !== null ? String(c.tick) : "—")),
      el("div", { class: "tb-cell" }, el("span", { class: "tb-label" }, "Sig."), el("span", { class: "num" }, nextTick !== null ? fmtDur(nextTick) : "—")),
      el("div", { class: "tb-cell" }, el("span", { class: "tb-label" }, "Próx."), el("span", { class: "num" }, ev)),
    );
  }

  // ------------------------------------------------------------------ status box (bottom of the menu)
  function pill(text, tone) { return el("span", { class: "pill tone-" + tone }, el("span", { class: "dot" }), text); }
  function opensAt() {
    const rc = S.rec.clock || {};
    const iso = rc.next_opens || null;
    const t = iso ? Date.parse(iso) : NaN;
    return isNaN(t) ? null : t / 1000;
  }
  function closesAt(d) {
    const rc = S.rec.clock || {};
    if (d.clock && d.clock.closes_at) return d.clock.closes_at;
    const t = rc.closes ? Date.parse(rc.closes) : NaN;
    return isNaN(t) ? null : t / 1000;
  }
  // An alert about the GAME's own request limit (60 requests/s per address) is not an Anthropic problem.
  const GAME_LIMIT_RX = /rate_limited|at most \d+ requests per second/i;
  const LLM_RX = /529|overload|anthropic|llmunavailable|llmtimeout|usage limits|api key/i;
  function alertSource(a) {
    if (a && a.source !== undefined && a.source !== null) return a.source;
    const blob = String((a && a.text) || "") + " " + String((a && a.where) || "");
    return GAME_LIMIT_RX.test(blob) ? "game" : LLM_RX.test(blob) ? "llm" : "";
  }
  function llmAlert(d) {
    const now = Date.now() / 1000;
    return (d.alerts || []).find((a) => (Number(a.ts) || 0) > now - 600 && alertSource(a) === "llm");
  }
  function degraded(d) {
    // "Sin Opus" only when the LLM really fails: an LLM alert, and not while the keys are answering fine.
    const kh = window.__keyHealth;
    if (kh && kh.allDown) return true;
    if (kh && kh.keys && kh.keys.length && !kh.bad.length) return false;
    return !!llmAlert(d);
  }
  function gameLimit(d) {
    // {since, last, what[]} while the game is rate-limiting our address (recorder lanes or the bot's reads).
    const now = Date.now() / 1000;
    const r = d.recorder || {};
    const lanes = Object.keys(r.rate_limited || {});
    const alerts = (d.alerts || []).filter((a) => alertSource(a) === "game" && (Number(a.ts) || 0) > now - 120);
    const recLast = Number(r.rate_limited_last) || 0;
    if (!lanes.length && !alerts.length) return null;
    const what = [];
    if (lanes.length) what.push("la grabadora (" + lanes.map((k) => k === "public" ? "lecturas públicas" : "lecturas con clave").join(" y ") + ")");
    if (alerts.length) what.push("las lecturas del bot (" + [...new Set(alerts.map((a) => a.where || "juego"))].join(", ") + ")");
    const times = alerts.map((a) => Number(a.ts) || 0).concat(recLast ? [recLast] : []);
    return { last: Math.max(...times, 0) || null, what };
  }
  function botState(d) {
    // Real state: ENCENDIDO only when switched on, no STOP, and the bot process is alive (fresh heartbeat).
    const st = d.status || {};
    const age = st.age_s;
    const alive = st.present && age != null && age <= 120;
    if (!alive) return ["APAGADO", "bad", st.present ? "sin latido hace " + Math.round(age || 0) + " s" : "proceso caído"];
    if (st.stop_file) return ["APAGADO", "bad", "STOP activo"];
    if (!st.armed) return ["APAGADO", "bad", "listo para encender"];
    if (d.clock && d.clock.doors !== "open") return ["ENCENDIDO", "ok", "esperando a que abran"];
    if (d.clock && d.clock.paused) return ["ENCENDIDO", "ok", "juego en pausa: espera al primer tick"];
    if (degraded(d)) return ["ENCENDIDO", "ok", "sin Opus: decide el código"];
    return ["ENCENDIDO", "ok", "jugando"];
  }
  function dealerShort(p) {
    const n = String(p.name || p.id || "");
    const words = n.split(/\s+/).filter((w) => !/^(el|la|los|las|don|doña)$/i.test(w));
    if (/abuela/i.test(n)) return "Abuela";
    return words[words.length > 1 && p.id && words.some((w) => w.toLowerCase() === p.id) ? words.findIndex((w) => w.toLowerCase() === p.id) : 0] || n;
  }
  function recorderBlock(r) {
    // Is everything that happens (ours and rivals') being recorded right now?
    const stale = r.age_s == null || r.age_s > 120;
    const down = (r.down || []).length > 0;
    // Real state: ENCENDIDA when the recorder process is alive and reaching the game; APAGADA otherwise.
    let text = "ENCENDIDA", tone = "ok";
    if (stale || r.state == null) { text = "APAGADA"; tone = "bad"; }
    else if (down || /down/.test(String(r.state))) { text = "APAGADA"; tone = "bad"; }
    const gaps = Number(r.feed_gaps || 0);
    const squeezed = Object.keys(r.rate_limited || {}).length > 0;
    const what = text === "APAGADA" ? (down ? "sin red con el juego" : "proceso sin latido")
      : r.state === "closed" ? "puertas cerradas: vigila cada 30 s"
      : squeezed ? "el juego nos limita: graba más despacio" : "grabando todo lo que pasa";
    const sub = what + " · " + (gaps ? gaps + " huecos en el feed" : "feed sin huecos");
    return el("div", { class: "sb-sec" },
      el("div", { class: "sb-line" }, el("span", null, "Grabación"), pill(text, tone)),
      el("div", { class: "sb-sub" }, sub));
  }

  function renderStatus(d) {
    const box = $("status-box");
    const procs = d.processes || [];
    const okN = procs.filter((p) => p.ok).length;
    const [bText, bTone, bSub] = botState(d);
    const open = d.clock && d.clock.doors === "open" && !d.clock.paused;
    const ca = closesAt(d), oa = opensAt();
    const paused = d.clock && d.clock.doors === "open" && d.clock.paused;
    const marketSub = open ? "abiertas · cierra " + (ca ? fmtTime(ca, false) : "—")
      : paused ? "puertas abiertas · reloj parado por la organización · cierra " + (ca ? fmtTime(ca, false) : "—")
      : "abre " + (oa ? fmtTime(oa, false) + " · en " + fmtDur(oa - Date.now() / 1000) : (d.clock && d.clock.opens_at) || "—");
    // This tick
    const limits = (S.rec.clock && S.rec.clock.limits) || {};
    const tickNo = d.clock && d.clock.tick;
    const accepted = (d.activity || []).filter((a) => a.tick === tickNo && /accept/.test(String(a.kind || "")) &&
      a.outcome && ["sent", "deal"].includes(a.outcome.status)).length;
    const threads = Object.keys(d.threads || {}).length;
    const offers = ((S.rec.my_offers && S.rec.my_offers.offers) || []).filter((o) => o.maker === "t10" && o.status === "open").length;
    // Dealer quotas
    const me = S.rec.me || {};
    const personas = (S.rec.dealers && S.rec.dealers.personas) || [];
    const unlocked = new Set(me.unlocked || []);
    const dealerRows = personas.filter((p) => unlocked.has(p.id)).map((p) => {
      const max = (p.menu && p.menu.deals_per_team_per_hour) || 0;
      const used = S.dealerUse[p.id] || 0;
      const segs = el("span", { class: "segs" });
      for (let i = 0; i < Math.min(max, 12); i++) segs.appendChild(el("span", { class: i < used ? "seg on" : "seg" }));
      return el("div", { class: "sb-line" }, el("span", { class: "sb-name" }, dealerShort(p)), segs, el("span", { class: "num" }, used + "/" + (max || "—")));
    });
    // Own venue
    const vid = (d.team && d.team.venue) || (myTeam() || {}).venue;
    const venues = (S.rec.venues && S.rec.venues.venues) || [];
    const v = vid ? venues.find((x) => x.venue === vid) : null;
    const venueBlock = v
      ? [el("div", { class: "sb-line" }, el("span", null, "Tienda " + v.venue), pill(v.status === "open" ? "ABIERTA" : String(v.status || "—").toUpperCase(), v.status === "open" ? "ok" : "bad")),
         el("div", { class: "sb-sub" }, fmtNum((v.fee_bps || 0) / 100, (v.fee_bps || 0) % 100 ? 1 : 0) + " % comisión · " + fmtNum(v.trades || 0) + " op.")]
      : [el("div", { class: "sb-sub" }, vid ? "Tienda " + vid : "Sin tienda propia")];

    box.replaceChildren(
      el("div", { class: "sb-sec" },
        el("div", { class: "sb-line" }, el("span", null, "Bot"), pill(bText, bTone)),
        el("div", { class: "sb-sub" }, bSub + " · " + okN + "/" + procs.length + " procesos"),
        el("div", { class: "sb-line" }, el("span", null, "Mercado"), pill(open ? "ABIERTO" : paused ? "EN PAUSA" : "CERRADO", open ? "ok" : paused ? "pause" : "bad")),
        el("div", { class: "sb-sub" }, marketSub)),
      recorderBlock(d.recorder || {}),
      keysBlock() || "",
      el("div", { class: "sb-sec" }, el("div", { class: "sb-head" }, "Este tick"),
        window.ui.meter({ label: "Aceptar", value: accepted, max: limits.accepts_per_team_per_tick }),
        window.ui.meter({ label: "Conversac.", value: threads, max: limits.max_open_threads_per_team }),
        window.ui.meter({ label: "Ofertas", value: offers, max: limits.max_open_offers_per_team })),
      el("div", { class: "sb-sec" }, el("div", { class: "sb-head" }, "Cupos dealers · esta hora"), dealerRows.length ? dealerRows : el("div", { class: "sb-sub" }, "—")),
      el("div", { class: "sb-sec" }, el("div", { class: "sb-head" }, "Tienda propia"), venueBlock),
    );
  }

  // ------------------------------------------------------------------ global states
  function renderBanners(d) {
    const host = $("banners");
    const items = [];
    if (S.apiDown) {
      items.push(el("div", { class: "banner tone-bad" }, icon("off", 18), el("div", null,
        el("strong", null, "Sin conexión con la API del dashboard"),
        el("div", null, S.lastOk ? "Último dato hace " + fmtAgo(S.lastOk / 1000) + ". Reintento automático cada 3 s; lo que ves puede estar desfasado." : "Reintentando cada 3 s."))));
    } else if (d && degraded(d)) {
      const a = llmAlert(d);
      items.push(el("div", { class: "banner tone-bad" }, icon("cloud", 18), el("div", null,
        el("strong", null, "API de Anthropic con problemas" + (a && a.ts ? " desde " + fmtTime(a.ts, false) : "")),
        el("div", null, "El bot sigue en modo Código: sin Opus ni Consejo, solo reglas y raíles. " + (a ? String(a.text || "").slice(0, 160) : ""))),
        el("a", { class: "btn", href: "#bot" }, "Ver Bot ", icon("arrow", 12))));
    }
    const gl = !S.apiDown && d ? gameLimit(d) : null;
    if (gl) {
      items.push(el("div", { class: "banner tone-warn" }, icon("alert", 18), el("div", null,
        el("strong", null, "El juego limita nuestras peticiones (60/s por dirección)" + (gl.last ? " · último aviso " + fmtTime(gl.last, false) : "")),
        el("div", null, "Afecta a " + gl.what.join(" y ") + ". No es un fallo de Claude: el bot sigue decidiendo con Opus. " +
          "El límite es por dirección de red y la compartimos con otros equipos; reintentamos solos con espera y se quita al recuperarse."))));
    }
    const kh = window.__keyHealth;
    if (!S.apiDown && kh && kh.bad.length) {
      const hard = kh.allDown || kh.bad.some((k) => k.tone === "bad");
      items.push(el("div", { class: "banner tone-" + (hard ? "bad" : "warn") }, icon("alert", 18), el("div", null,
        el("strong", null, kh.allDown ? "El bot juega sin Claude: ninguna clave funciona"
          : kh.bad.map((k) => "Clave " + k.label + " " + k.chip.toLowerCase()).join(" · ") + ": el bot sigue con " + listKeys(kh.okLabels)),
        el("div", null, kh.bad.map((k) => "Clave " + k.label + ": " + k.text.replace(/\.$/, "") + ".").join(" "))),
        el("a", { class: "btn", href: "#bot" }, "Ver claves ", icon("arrow", 12))));
    }
    if (d && d.status && d.status.stop_file) {
      items.push(el("div", { class: "banner tone-bad" }, icon("alert", 18), el("div", null, el("strong", null, "STOP activo"),
        el("div", null, "El bot no envía nada al juego hasta quitar el STOP y encenderlo en la pantalla Bot.")),
        el("a", { class: "btn", href: "#bot" }, "Ver Bot ", icon("arrow", 12))));
    }
    host.replaceChildren(...items);
    // Doors closed: dim the screen with a centred card (can be dismissed to keep working).
    const pausedOnly = d && d.clock && d.clock.doors === "open" && d.clock.paused;
    const closed = d && d.clock && (d.clock.doors === "closed" || pausedOnly);
    if (!closed) S.closedDismissed = false;
    const ov = $("closed-overlay");
    if (closed && !S.closedDismissed && S.route !== "bot" && S.route !== "supervision") {
      const oa = opensAt();
      const lbMe = myTeam() || {};
      ov.hidden = false;
      if (pausedOnly) {
        ov.replaceChildren(el("div", { class: "closed-card is-paused" },
          el("h2", null, icon("lock", 18), "Juego en pausa"),
          el("div", { class: "closed-sub num" }, "puertas abiertas · la organización ha parado el reloj (tick " + (d.clock.tick ?? "—") + ")"),
          el("p", null, "No hay cuenta atrás: se reanuda cuando lo decidan los organizadores. El bot arranca solo en el primer tick si está encendido."),
          el("div", { class: "closed-foot num" }, "Hoy: " + fmtNum(d.team && d.team.score, 1) + " pts" + (d.team && d.team.rank ? " · " + d.team.rank + ".º de " + d.team.teams : "")),
          el("button", { type: "button", class: "btn", onclick: () => { S.closedDismissed = true; ov.hidden = true; } }, "Ver el dashboard igualmente")));
        return;
      }
      ov.replaceChildren(el("div", { class: "closed-card" },
        el("h2", null, icon("lock", 18), "Mercado cerrado"),
        el("div", { class: "closed-sub num" }, oa ? "abre el " + new Date(oa * 1000).toLocaleDateString("es-ES", { weekday: "long" }) + " a las " + fmtTime(oa, false) : "abre " + ((d.clock && d.clock.opens_at) || "—")),
        el("div", { class: "closed-count num" }, oa ? fmtDur(oa - Date.now() / 1000) : "—"),
        el("p", null, "Mientras está cerrado el bot no hace nada; al abrir arranca solo si está encendido."),
        el("div", { class: "closed-foot num" }, "Hoy: " + fmtNum(d.team && d.team.score, 1) + " pts" + (d.team && d.team.rank ? " · " + d.team.rank + ".º de " + d.team.teams : "") +
          (lbMe.album_slots ? " · álbum " + lbMe.album_filled + "/" + lbMe.album_slots : "")),
        el("button", { type: "button", class: "btn", onclick: () => { S.closedDismissed = true; ov.hidden = true; } }, "Ver el dashboard igualmente")));
    } else ov.hidden = true;
  }

  // ------------------------------------------------------------------ notifications
  async function pollNotifications() {
    let res;
    try { res = await api.notifications(S.notifSince); } catch (e) { return; }
    const items = (res && res.items) || [];
    if (res && res.now && !S.notifInit) { /* first load: fill the bell, no toasts */ }
    const known = new Set(S.notif.map((n) => n.id));
    const fresh = items.filter((n) => !known.has(n.id));
    if (fresh.length) {
      S.notif = fresh.concat(S.notif).sort((a, b) => (Number(b.ts) || 0) - (Number(a.ts) || 0)).slice(0, 80);
      S.notifSince = Math.max(...S.notif.map((n) => Number(n.ts) || 0));
    }
    const now = Date.now() / 1000;
    if (S.notifInit && prefs.toasts && now > (prefs.muteUntil || 0) && S.route !== "supervision") {
      for (const n of fresh.slice(0, 4).reverse()) {
        if (prefs.types[groupOf(n.type)] === false) continue;
        if ((Number(n.ts) || 0) < now - 600) continue;
        window.ui.toast({ type: n.type, title: n.title, text: n.text, href: n.href || "#supervision/" + n.id, ts: n.ts });
      }
    }
    S.notifInit = true;
    renderBell();
  }
  function unread() { return S.notif.filter((n) => (Number(n.ts) || 0) > (prefs.readTs || 0) && prefs.types[groupOf(n.type)] !== false).length; }
  function renderBell() {
    const n = unread();
    const b = $("bell-count");
    b.textContent = n > 99 ? "99+" : String(n);
    b.hidden = n === 0;
    const sup = S.notif.filter((x) => groupOf(x.type) === "aprobar" && (Number(x.ts) || 0) > (prefs.readTs || 0)).length;
    const nb = $("nav-badge-supervision"); if (nb) { nb.textContent = String(sup); nb.hidden = !sup; }
    if (!$("bell-panel").hidden) renderBellPanel();
  }
  function toggle(on, onChange, label) {
    const b = el("button", { type: "button", class: ["switch", on ? "on" : ""], role: "switch", "aria-checked": on ? "true" : "false", "aria-label": label });
    b.addEventListener("click", () => onChange(!b.classList.contains("on")));
    return b;
  }
  function renderBellPanel() {
    const p = $("bell-panel");
    const muted = Date.now() / 1000 < (prefs.muteUntil || 0);
    const set = (fn) => (v) => { fn(v); savePrefs(); renderBell(); renderBellPanel(); };
    const list = S.notif.filter((n) => prefs.types[groupOf(n.type)] !== false).slice(0, 30).map((n) =>
      el("a", { class: ["bell-item", (Number(n.ts) || 0) > (prefs.readTs || 0) ? "unread" : "", "tone-" + groupOf(n.type)], href: n.href || "#supervision/" + n.id,
        onclick: () => { p.hidden = true; } },
        el("div", { class: "bell-item-head" }, icon(({ aprobar: "bell", breaker: "alert", gran: "trend", novedad: "dealer", duelo: "duelo", broker: "flask", lab: "laboratorio", limite: "shield" })[groupOf(n.type)], 14),
          el("strong", null, n.title || ""), el("span", { class: "num muted" }, fmtAgo(n.ts))),
        n.text ? el("div", { class: "bell-item-text" }, n.text) : null));
    p.replaceChildren(
      el("header", { class: "bell-head" }, el("strong", null, "Avisos"),
        el("button", { type: "button", class: "link-btn", onclick: () => { prefs.readTs = Date.now() / 1000; savePrefs(); renderBell(); } }, "Marcar leídos")),
      el("div", { class: "bell-sec" },
        el("div", { class: "bell-opt" }, el("div", null, "Mostrar avisos emergentes", el("div", { class: "muted small" }, "no se muestran en Supervisión")),
          toggle(prefs.toasts, set((v) => { prefs.toasts = v; }), "Mostrar avisos emergentes")),
        el("div", { class: "bell-opt" }, el("div", null, "Silenciar 30 min", muted ? el("div", { class: "muted small num" }, "hasta " + fmtTime(prefs.muteUntil, false)) : null),
          toggle(muted, set((v) => { prefs.muteUntil = v ? Date.now() / 1000 + 1800 : 0; }), "Silenciar 30 min"))),
      el("div", { class: "bell-sec" }, el("div", { class: "sb-head" }, "Por tipo"),
        NOTIF_GROUPS.map(([k, label]) => el("div", { class: "bell-opt" }, el("span", null, label),
          toggle(prefs.types[k] !== false, set((v) => { prefs.types[k] = v; }), label)))),
      el("div", { class: "bell-list" }, list.length ? list : window.ui.empty("Sin avisos.")),
      el("a", { class: "bell-foot", href: "#supervision", onclick: () => { p.hidden = true; } }, "Las aprobaciones se hacen en Supervisión", icon("arrow", 12)),
    );
  }

  // ------------------------------------------------------------------ boot
  function boot() {
    buildNav();
    $("refresh").addEventListener("click", async () => {
      // Refresh every panel right now, without reloading the page (keeps filters, scroll and drawers).
      const btn = $("refresh");
      if (btn.classList.contains("spin")) return;
      btn.classList.add("spin");
      const t0 = Date.now();
      try {
        if (window.api && window.api.clearCache) window.api.clearCache();
        window.__dashForceAt = Date.now();          // screens' own caches and stream throttles skip their wait once
        await tick(true);
        btn.classList.add("ok-flash");
        setTimeout(() => btn.classList.remove("ok-flash"), 900);
      } catch (e) {
        S.apiDown = true;
        renderBanners(S.data);
        window.ui.toast({ type: "error", title: "No se pudo actualizar", text: (e && e.message) || "La API no responde.", ttl: 5000 });
      } finally { setTimeout(() => btn.classList.remove("spin"), Math.max(0, 400 - (Date.now() - t0))); }
    });
    $("bell").addEventListener("click", (e) => {
      e.stopPropagation();
      const p = $("bell-panel");
      p.hidden = !p.hidden;
      if (!p.hidden) renderBellPanel();
    });
    document.addEventListener("click", (e) => {
      const p = $("bell-panel");
      if (!p.hidden && !p.contains(e.target) && !e.target.closest("#bell")) p.hidden = true;
    });
    window.addEventListener("hashchange", route);
    route();
    tick();
    setInterval(tick, 2000);
    setInterval(() => { renderClock(); if (S.data) { const ov = $("closed-overlay"); const c = ov.querySelector(".closed-card:not(.is-paused) .closed-count"); const oa = opensAt(); if (c && oa) c.textContent = fmtDur(oa - Date.now() / 1000); } }, 1000);
  }
  window.app = { state: S, refresh: tick, route, groupOf, reloadRec: () => loadRec(true) };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
