/* RADIO · noticias y rumores del juego (Boletín del Bazar, Radio Rastro, El Tablón) y qué hizo el cerebro con ellos (#radio).
   GET news?since= -> {items:[{id, ts, tick, t_hours, source, title, text, claim, entities, prediction:{text, deadline_h}|null,
     status: confirmada|falsa|sin verificar|pendiente, actionable, brain_note}], sources:{boletin:{n, confirmed, false, reliability}, …}}
   window.RadioNews also feeds the Home panel and the toast for actionable news (app.js). */
(function () {
  "use strict";
  window.Screens = window.Screens || {};
  const U = () => window.ui;
  const A = () => window.api;
  const el = (...a) => U().el(...a);
  const when = (ts) => (ts ? U().fmtTime(ts) : "—");
  const SRC = { boletin: ["Boletín", "anuncio", "var(--t-cambio)"], radio: ["Radio Rastro", "bell", "var(--t-puja)"], tablon: ["El Tablón", "coleccion", "var(--t-dealer)"] };
  const SRC_IDS = Object.keys(SRC);
  const ST = { confirmada: ["Confirmada", "ok"], falsa: ["Falsa", "bad"], pendiente: ["Pendiente", "warn"], sin_verificar: ["Sin verificar", "mute"] };
  const R = { items: [], sources: {}, state: "idle", err: null, at: 0, busy: false, seen: null, feedSeq: 0, feedItems: [], origin: "", sent: {}, chatAt: 0 };
  const SENT_KEY = "bazaar.dash.newsSent";
  try { R.sent = JSON.parse(localStorage.getItem(SENT_KEY) || "{}") || {}; } catch (e) { R.sent = {}; }
  const keyOf = (x) => String(x.id ?? x.ts);
  const fullText = (x) => [x.head, x.body && x.body !== x.head ? x.body : ""].filter(Boolean).join(". ").replace(/\.\./g, ".");

  function srcOf(x) {
    const s = String(x.source || x.source_name || "").toLowerCase();
    if (/bolet/.test(s)) return "boletin";
    if (/tabl/.test(s)) return "tablon";
    if (/radio|rastro/.test(s)) return "radio";
    return SRC[s] ? s : "radio";
  }
  function statusOf(x) {
    const s = String(x.status || x.verdict || "").toLowerCase().replace(/\s+/g, "_");
    if (/confirm|true|cierta/.test(s)) return "confirmada";
    if (/fals|false/.test(s)) return "falsa";
    if (/pend/.test(s)) return "pendiente";
    return "sin_verificar";
  }
  const norm = (x) => ({ ...x, src: srcOf(x), st: statusOf(x), ts: +x.ts || +x.seen_at || 0,
    body: x.text || x.body || x.claim || "", head: x.title || x.headline || "", note: x.brain_note || x.note || (x.brain && x.brain.note) || "" });

  async function pull(force) {
    if (R.busy || (!force && Date.now() - R.at < 8000)) return R;
    R.busy = true; R.at = Date.now();
    try {
      const r = await A().get("news", {}, 0);
      R.items = (Array.isArray(r) ? r : (r && (r.items || r.news)) || []).map(norm).sort((a, b) => b.ts - a.ts);
      R.sources = (r && r.sources) || {};
      R.state = "on"; R.origin = "news";
    } catch (e) {
      if (e && e.status === 404) {
        // until GET news exists: the news the game publishes on its feed (news.posted), read once and then only what is new
        try { await pullFeedNews(); R.items = R.feedItems.slice().sort((a, b) => b.ts - a.ts); R.sources = {}; R.state = "on"; R.origin = "feed"; }
        catch (e2) { R.state = "error"; R.err = e2; }
      } else { R.state = "error"; R.err = e; }
    }
    finally { R.busy = false; }
    markSent().catch(() => {});
    return R;
  }
  async function pullFeedNews() {
    for (let g = 0; g < 40; g++) {
      const r = await A().recStream("feed", { since_seq: R.feedSeq, limit: 5000 });
      const rows = (r && r.rows) || [];
      for (const x of rows) if (String(x.type).startsWith("news")) {
        const p = x.payload || {};
        R.feedItems.push(norm({ id: "f" + (p.id ?? x.id), ts: x.seen_at || x.ts, tick: x.tick, t_hours: x.t, source: p.source || p.source_name, title: p.headline, text: p.body || "", status: "sin verificar" }));
      }
      if (rows.length) R.feedSeq = rows[rows.length - 1].seq;
      if (rows.length < 5000) break;
    }
  }
  // which news already went to the brain: what this browser sent (localStorage) + team chat messages that quote the headline
  async function markSent() {
    if (Date.now() - R.chatAt < 20000 || !A().brainChat) return;
    R.chatAt = Date.now();
    const r = await A().brainChat();
    const msgs = (Array.isArray(r) ? r : (r && (r.items || r.messages)) || []).filter((m) => m.role !== "brain");
    let changed = false;
    for (const x of R.items) {
      const k = keyOf(x); if (R.sent[k] || !x.head) continue;
      const m = msgs.find((mm) => String(mm.text || "").includes(x.head));
      if (m) { R.sent[k] = { ts: +m.ts || Date.now() / 1000, by: m.by || "equipo" }; changed = true; }
    }
    if (changed) { try { localStorage.setItem(SENT_KEY, JSON.stringify(R.sent)); } catch (e) { /* private mode */ } if (S.root) render(); }
  }
  async function sendToBrain(x, note, btn) {
    let by = "equipo"; try { by = localStorage.getItem("bazaar.dash.chatName") || "equipo"; } catch (e) { /* default */ }
    const text = `Noticia (${(SRC[x.src] || SRC.radio)[0]}, ${when(x.ts).slice(0, 5)}): ${fullText(x)}` + (note ? ` — ${note}` : "");
    btn.disabled = true;
    try {
      await A().brainSay(text, by);
      R.sent[keyOf(x)] = { ts: Date.now() / 1000, by };
      try { localStorage.setItem(SENT_KEY, JSON.stringify(R.sent)); } catch (e) { /* private mode */ }
      U().toast({ type: "deal", title: "Noticia enviada al cerebro", text: (x.head || x.body).slice(0, 120), href: "#cerebro" });
      render();
    } catch (e) { btn.disabled = false; U().toast({ type: "error", title: "No se pudo enviar al cerebro", text: (e && e.message) || "Error" }); }
  }
  // new actionable items since the last look (for the toast); the first load never toasts
  function fresh() {
    const ids = new Set(R.items.map((x) => String(x.id ?? x.ts)));
    if (R.seen === null) { R.seen = ids; return []; }
    const out = R.items.filter((x) => x.actionable && !R.seen.has(String(x.id ?? x.ts)));
    R.seen = ids;
    return out;
  }

  function srcChip(src) {
    const [label, ic, color] = SRC[src] || SRC.radio;
    const c = el("span", { class: "chip type rd-chip" }, U().icon(ic, 13), el("span", { class: "chip-label" }, label));
    c.style.setProperty("--tc", color);
    return c;
  }
  const stChip = (st) => { const [l, t] = ST[st] || ST.sin_verificar; return el("span", { class: "tag res tone-" + t }, l); };
  function reliability() {
    return SRC_IDS.map((k) => {
      const s = R.sources[k] || {};
      const items = R.items.filter((x) => x.src === k);
      const ok = s.confirmed ?? items.filter((x) => x.st === "confirmada").length;
      const bad = s.false ?? s.falsas ?? items.filter((x) => x.st === "falsa").length;
      const judged = ok + bad;
      return { k, label: SRC[k][0], n: s.n ?? items.length, text: judged ? `${ok}/${judged} ciertas` : "—", tone: !judged ? "mute" : ok / judged >= 0.75 ? "ok" : ok / judged >= 0.4 ? "warn" : "bad" };
    });
  }
  function row(x, compact) {
    const pred = x.prediction && (x.prediction.text || x.prediction.claim);
    const n = el("div", { class: "rd-row" + (x.actionable ? " is-act" : "") + (compact ? " is-compact" : "") },
      el("div", { class: "rd-h" }, el("span", { class: "num rd-time" }, when(x.ts)), srcChip(x.src), stChip(x.st),
        x.actionable ? el("span", { class: "tag rd-act" }, U().icon("bell", 12), "Hay que actuar") : null,
        x.tick != null && !compact ? el("span", { class: "num rd-muted" }, "tick " + x.tick) : null),
      x.head ? el("div", { class: "rd-title" }, x.head) : null,
      el("div", { class: "rd-text" + (compact ? " is-clip" : "") }, x.body),
      compact ? null : pred ? el("div", { class: "rd-sub" }, el("b", {}, "Predice: "), pred,
        x.prediction.deadline_h != null ? el("span", { class: "num rd-muted" }, " · antes de h" + U().fmtNum(x.prediction.deadline_h, 2)) : null,
        " · ", el("span", { class: "rd-" + x.st }, x.st === "confirmada" ? "se cumplió" : x.st === "falsa" ? "no se cumplió" : x.st === "pendiente" ? "aún por ver" : "sin comprobar")) : null,
      x.note ? el("div", { class: "rd-sub" }, el("b", {}, "El cerebro: "), x.note) : null,
      compact ? null : sendBox(x));
    n.style.setProperty("--tc", (SRC[x.src] || SRC.radio)[2]);
    return n;
  }
  function sendBox(x) {
    const sent = R.sent[keyOf(x)];
    const note = el("input", { class: "rd-note", placeholder: "Nota para el cerebro (opcional)" });
    const btn = el("button", { type: "button", class: "rd-send" }, U().icon("cerebro", 13), sent ? "Volver a pasar" : "Pasar al cerebro");
    btn.addEventListener("click", () => sendToBrain(x, note.value.trim(), btn));
    note.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); btn.click(); } });
    return el("div", { class: "rd-sendbox" }, sent ? el("span", { class: "rd-sent" }, U().icon("check", 12), `enviada al cerebro a las ${when(sent.ts)}` + (sent.by ? " por " + sent.by : "")) : null,
      el("span", { class: "rd-sp" }), note, btn);
  }
  // Home panel: the five latest
  function homePanel(host) {
    if (!host) return;
    const sub = host.querySelector(".rd-home-sub"), list = host.querySelector(".rd-home-list");
    if (R.state === "off") { sub.textContent = ""; list.replaceChildren(U().empty("Radio Rastro aún no está activa.")); return; }
    if (R.state === "error") { list.replaceChildren(U().error(R.err)); return; }
    if (R.state === "idle") { list.replaceChildren(U().loading()); return; }
    sub.textContent = reliability().map((r) => r.label + " " + r.text).join(" · ");
    if (!R.items.length) { list.replaceChildren(U().empty("Sin noticias todavía.")); return; }
    U().keyedList(list, R.items.slice(0, 5), { key: (x) => String(x.id ?? x.ts), sig: (x) => x.st + "|" + x.note, render: (x) => row(x, true) });
  }

  // ---------- screen ----------
  const S = { root: null, fb: null, st: null, fbKey: "" };
  function render() {
    const root = S.root; if (!root) return;
    const head = root.querySelector(".rd-rel"), list = root.querySelector(".rd-list"), fbHost = root.querySelector(".rd-fb");
    if (R.state === "off") { head.replaceChildren(); fbHost.replaceChildren(); list.replaceChildren(U().empty("Radio Rastro aún no está activa.")); return; }
    if (R.state === "error") { list.replaceChildren(U().error(R.err)); return; }
    if (R.state === "idle") { list.replaceChildren(U().loading()); return; }
    root.querySelector(".panel-sub").textContent = `${R.items.length} noticias · todas, la más reciente arriba` + (R.origin === "feed" ? " · leídas del feed del juego (el cerebro aún no las ha verificado)" : "");
    head.replaceChildren(...reliability().map((r) => el("div", { class: "rd-relbox tone-" + r.tone }, srcChip(r.k), el("b", { class: "num" }, r.text), el("span", { class: "rd-muted" }, r.n + " noticias"))));
    const counts = {}; for (const x of R.items) counts[x.src] = (counts[x.src] || 0) + 1;
    const stCounts = {}; for (const x of R.items) stCounts[x.st] = (stCounts[x.st] || 0) + 1;
    if (!S.fb) {
      S.fb = U().filterBar({ types: SRC_IDS, counts, search: true, placeholder: "Buscar en las noticias…", chip: (t, n) => { const c = srcChip(t); c.append(el("span", { class: "chip-count num" }, String(n))); return c; },
        extraRows: [{ key: "estado", label: "Estado", options: Object.keys(ST).map((k) => ({ id: k, label: ST[k][0], count: stCounts[k] || 0 })) },
          { key: "solo", label: "Mostrar", options: [{ id: "act", label: "Solo las que piden actuar", icon: "bell" }] }],
        onChange: (st) => { S.st = st; render(); } });
      S.st = S.fb.state; fbHost.replaceChildren(S.fb);
    } else S.fb.setCounts(counts, Object.fromEntries(Object.keys(ST).map((k) => ["estado/" + k, stCounts[k] || 0])));
    const st = S.st, q = (st.q || "").toLowerCase();
    const est = st.extra && st.extra.estado, solo = st.extra && st.extra.solo;
    const rows = R.items.filter((x) => st.types.has(x.src) && (!est || !est.size || est.has(x.st)) && (!solo || !solo.has("act") || x.actionable)
      && (!q || `${x.head} ${x.body} ${x.note} ${(x.prediction || {}).text || ""}`.toLowerCase().includes(q)));
    U().keyedList(list, rows.slice(0, 200), { key: (x) => String(x.id ?? x.ts), sig: (x) => x.st + "|" + x.note + "|" + x.actionable + "|" + ((R.sent[keyOf(x)] || {}).ts || ""), render: (x) => row(x, false),
      tail: rows.length ? [] : [U().empty(R.items.length ? "Nada coincide con el filtro." : "Sin noticias todavía.")] });
  }

  window.RadioNews = { pull, fresh, homePanel, state: () => R };
  window.Screens.noticias = {
    title: "Noticias",
    mount(root) {
      S.root = root; S.fb = null;
      root.replaceChildren(el("div", { class: "scr-radio" },
        el("section", { class: "panel" }, el("header", { class: "panel-head" }, el("h2", { class: "panel-title" }, "Noticias"),
          el("span", { class: "panel-sub" }, "noticias y rumores del juego · qué predicen, si se cumplen y qué hizo el cerebro")),
          el("div", { class: "rd-rel" }), el("div", { class: "rd-fb" }), el("div", { class: "rd-list" }, U().loading()))));
    },
    async refresh(root, data, params, opts) { S.root = root; await pull(opts && opts.force); render(); },
    unmount() { S.root = null; S.fb = null; },
  };
})();
