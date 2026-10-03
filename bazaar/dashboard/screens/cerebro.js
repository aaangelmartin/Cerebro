/* CEREBRO · lo que el cerebro (estratega con Opus) piensa, decide y aplica (#cerebro).
   Datos: GET strategy → {current, status, history[], findings[]} y overview.strategy (resumen).
   Solo se ve: los cambios los aplica el cerebro (los grandes, tras votar el consejo). */
(function () {
  "use strict";
  window.Screens = window.Screens || {};
  const U = () => window.ui;
  const A = () => window.api;
  const el = (...a) => U().el(...a);
  const num = (x) => (x === null || x === undefined || x === "" || isNaN(+x) ? null : +x);
  const fmtP = (n) => (n === null || n === undefined ? "—" : U().fmtP(n));
  const fmtNum = (n, d) => U().fmtNum(n, d);
  const when = (ts) => (ts ? U().fmtTime(ts) : "—");
  // DOM append that skips null/false (Element.append would print "null")
  const add = (node, ...kids) => { for (const k of kids.flat(Infinity)) if (k !== null && k !== undefined && k !== false) node.append(k); return node; };

  const DOMAINS = [["market", "Mercado", "mercado"], ["dealers", "Dealers", "dealer"], ["duels", "Duelos", "duelo"], ["broker", "Broker", "flask"]];
  // finding topics: label, icon, colour
  const TOPICS = {
    self_review: ["Autorrevisión", "check", "var(--t-puja)"], rivals: ["Rivales", "rivales", "var(--t-duelo)"],
    gap: ["Distancia", "trend", "var(--t-cambio)"], idle: ["Bot parado", "alert", "var(--t-venta)"],
    llm: ["Claves y gasto", "cloud", "var(--t-venta)"], offers: ["Ofertas", "anuncio", "var(--t-puja)"],
    venues: ["Tiendas", "mercado", "var(--t-dealer)"], goals: ["Objetivos", "target", "var(--t-compra)"],
    events: ["Evento", "bell", "var(--t-dealer)"], general: ["General", "supervision", "var(--t-anuncio)"],
  };
  const topicOf = (t) => TOPICS[t] || TOPICS.general;
  function topicChip(t) {
    const [label, ic, color] = topicOf(t);
    const c = el("span", { class: "chip type cb-chip" }, U().icon(ic, 13), el("span", { class: "chip-label" }, label));
    c.style.setProperty("--tc", color);
    return c;
  }
  function statusChip(st) {
    const map = { aplicado: ["Aplicado", "ok"], consejo: ["Aplicado · consejo", "ok"], pendiente: ["Pendiente de consejo", "warn"],
      rechazado: ["Rechazado", "bad"], visto: ["Anotado", "mute"] };
    const [label, tone] = map[st] || map.visto;
    return el("span", { class: "tag res tone-" + tone }, label);
  }
  // status of what a plan document decided: council outcome of its big changes
  function planStatus(doc) {
    if (!doc) return "visto";
    const c = doc.council;
    if (c && c.ok === false) return "rechazado";
    if (c && c.ok) return "consejo";
    if ((doc.big_changes || []).length && !c) return "pendiente";
    return "aplicado";
  }
  function planSource(doc) {
    const c = doc && doc.council;
    if (c && Array.isArray(c.votes)) return U().sourceTag("consejo", `${c.yes ?? c.votes.filter((v) => v.verdict !== "reject").length}/${c.votes.length}`);
    return U().sourceTag("opus");
  }

  // ---------- state ----------
  const S = { root: null, data: null, err: null, topic: "todos", q: "", histSel: null };

  async function load(ov) {
    let r = null, err = null;
    try { r = await A().strategy(200); } catch (e) { err = e; }
    let spend = null;
    try { spend = await A().spend(); } catch (e) { /* optional */ }
    let control = null;
    try { control = await A().getControl(); } catch (e) { /* optional */ }
    const sv = (ov && ov.strategy) || null;
    const cur = (r && r.current) || null;
    const history = ((r && r.history) || []).slice().sort((a, b) => (num(a.updated) || 0) - (num(b.updated) || 0));
    if (cur && !history.some((h) => h.updated === cur.updated)) history.push(cur);
    return { cur, status: (r && r.status) || {}, history, findings: (r && r.findings) || [], sv, spend, control, err };
  }

  // ---------- pieces ----------
  function statusPanel(d) {
    const st = d.status || {};
    const age = st.updated ? Date.now() / 1000 - st.updated : null;
    const on = age !== null && age < 300;
    const cur = d.cur || {};
    const nextT = num((cur.plan || {}).next_check_in_ticks);
    const spentStrategy = d.spend && d.spend.by_purpose ? d.spend.by_purpose.strategy : st.spent_today;
    const pill = el("span", { class: "pill tone-" + (on ? "ok" : "bad") }, el("span", { class: "dot" }), on ? "ENCENDIDO" : "APAGADO");
    const kpis = el("div", { class: "cb-kpis" },
      U().kpi({ label: "Estado", value: pill, sub: on ? "latido hace " + U().fmtDur(age) : age === null ? "sin latido todavía" : "último latido " + U().fmtAgo(st.updated) }),
      U().kpi({ label: "Último plan", value: cur.updated ? when(cur.updated) : "—", sub: cur.tick != null ? "tick " + cur.tick + (cur.reason ? " · " + cur.reason : "") : "" }),
      U().kpi({ label: "Siguiente revisión", value: nextT ? "en " + nextT + " ticks" : "—", sub: "antes si pasa algo (evento)" }),
      U().kpi({ label: "Modelo", value: (cur.model || "claude-opus-5-5").replace("claude-", "").replace(/-/g, " "), sub: "esfuerzo medio" }),
      U().kpi({ label: "Gasto hoy", value: spentStrategy != null ? U().fmtUsd(spentStrategy) : "—", sub: st.day_cap ? "tope " + U().fmtUsd(st.day_cap) : (st.calls != null ? st.calls + " llamadas" : "") }));
    const errs = (st.errors || []).slice(-3);
    const p = U().panel("Cerebro", { sub: "Opus piensa, investiga y decide; el consejo vota los cambios grandes", cls: "cb-status" });
    const sit = (cur.plan || {}).situation;
    add(p.body, kpis,
      sit ? el("div", { class: "cb-situation" }, el("div", { class: "cb-cap" }, "Situación"), el("p", {}, sit)) : null,
      errs.length ? el("div", { class: "cb-errs" }, errs.map((e) => el("div", { class: "cb-err" }, U().icon("alert", 13), el("span", { class: "num" }, when(e.ts)), " ", e.error || String(e)))) : null);
    return p;
  }

  function goalsBlock(plan, control) {
    const goals = { ...(plan.goal_buys || {}) };
    const manual = (control && control.goal_buys) || {};
    for (const k of Object.keys(manual)) if (!(k in goals)) goals[k] = manual[k];
    const held = new Set();
    const me = (window.__cbMe || {});
    for (const a of me.assets || []) if (a && a.ref) held.add(String(a.ref).toUpperCase());
    const keys = Object.keys(goals);
    if (!keys.length) return el("div", { class: "cb-muted" }, "Sin objetivos de compra ahora.");
    return el("div", { class: "cb-goals" }, keys.map((ref) => {
      const got = held.has(ref.toUpperCase());
      const dropped = num(goals[ref]) === 0;
      return el("div", { class: "cb-goal" + (got ? " is-done" : "") + (dropped ? " is-dropped" : "") },
        U().icon(got ? "check" : "target", 14), el("b", { class: "num" }, ref),
        el("span", { class: "cb-muted" }, dropped ? "descartado" : "máx " + fmtP(goals[ref])),
        el("span", { class: "cb-goal-st" }, got ? "conseguido" : dropped ? "" : "buscando"),
        manual[ref] != null ? el("span", { class: "tag res tone-mute" }, "manual") : null);
    }));
  }

  function planPanel(d) {
    const p = U().panel("Plan actual", { sub: d.cur && d.cur.tick != null ? "tick " + d.cur.tick : "" });
    const plan = (d.cur && d.cur.plan) || null;
    if (!plan) { add(p.body, U().empty("El cerebro aún no ha publicado su plan.")); return p; }
    const pri = (plan.priorities || []);
    const cp = plan.cash_policy || {};
    add(p.body, 
      el("div", { class: "cb-sec" }, el("div", { class: "cb-cap" }, "Prioridades"),
        pri.length ? el("ol", { class: "cb-pri" }, pri.map((x) => el("li", {}, x))) : el("div", { class: "cb-muted" }, "Sin prioridades.")),
      el("div", { class: "cb-two" },
        el("div", { class: "cb-sec" }, el("div", { class: "cb-cap" }, "Objetivos de compra"), goalsBlock(plan, d.control)),
        el("div", { class: "cb-sec" }, el("div", { class: "cb-cap" }, "Política de caja"),
          el("div", { class: "cb-kv" }, el("span", {}, "Reserva"), el("b", { class: "num" }, cp.reserve != null ? fmtP(cp.reserve) : "por defecto")),
          el("div", { class: "cb-kv" }, el("span", {}, "Trato pequeño máx. (con objetivo)"), el("b", { class: "num" }, cp.max_small_deal != null ? fmtP(cp.max_small_deal) : "por defecto")),
          plan.duel_claude_mode ? el("div", { class: "cb-kv" }, el("span", {}, "Modo de duelos"), el("b", {}, plan.duel_claude_mode)) : null,
          (plan.pause_domains || []).length ? el("div", { class: "cb-kv" }, el("span", {}, "Dominios en pausa"), el("b", { class: "cb-bad" }, plan.pause_domains.join(", "))) : null)),
      el("div", { class: "cb-sec" }, el("div", { class: "cb-cap" }, "Indicaciones por dominio"),
        el("div", { class: "cb-guid" }, DOMAINS.map(([k, label, ic]) => el("div", { class: "cb-guid-item" },
          el("div", { class: "cb-guid-h" }, U().icon(ic, 14), label),
          el("p", {}, (plan.guidance || {})[k] || el("span", { class: "cb-muted" }, "Sin indicaciones.")))))),
      (plan.risks || []).length ? el("div", { class: "cb-sec" }, el("div", { class: "cb-cap" }, "Riesgos"),
        el("ul", { class: "cb-risks" }, plan.risks.map((x) => el("li", {}, U().icon("alert", 13), el("span", {}, x))))) : null,
      (plan.cancel_offers || []).length ? el("div", { class: "cb-sec" }, el("div", { class: "cb-cap" }, "Ofertas que retira"),
        el("div", { class: "cb-muted num" }, plan.cancel_offers.map((x) => "#" + x).join(" · "))) : null);
    return p;
  }

  // events: from every plan doc (doc.events) + the overview summary
  function eventsPanel(d) {
    const rows = [];
    for (const doc of d.history) for (const e of doc.events || []) rows.push({ ts: doc.updated, tick: doc.tick, text: typeof e === "string" ? e : (e.text || e.event || JSON.stringify(e)), doc });
    rows.sort((a, b) => (b.ts || 0) - (a.ts || 0));
    const p = U().panel("Eventos detectados", { sub: rows.length ? rows.length + " eventos" : "" });
    if (!rows.length) { add(p.body, U().empty("Aún no ha detectado eventos (dealer nuevo, nivel, calendario, tiendas, saltos de puntos).")); return p; }
    const host = el("div", { class: "cb-list" });
    U().keyedList(host, rows.slice(0, 60), {
      key: (r) => (r.ts || 0) + "|" + r.text, sig: () => "",
      render: (r) => U().row({ cls: "cb-t-events", cols: "86px minmax(0,1fr) auto", cells: [
        { v: el("span", { class: "num" }, when(r.ts)), cls: "cb-time" },
        { v: el("div", {}, el("div", { class: "cb-rowt", title: r.text }, short(r.text, 220)), el("div", { class: "cb-rows" }, "Conclusión: " + short(concl(r.doc), 260))), cls: "wrap" },
        statusChip(planStatus(r.doc))] }),
    });
    add(p.body, host);
    return p;
  }
  const short = (t, n) => { t = String(t || "").replace(/<\/?untrusted[^>]*>/g, "").replace(/\s+/g, " ").trim(); return t.length > n ? t.slice(0, n - 1) + "…" : t; };
  function concl(doc) {
    const pri = ((doc && doc.plan) || {}).priorities || [];
    return pri[0] || ((doc && doc.plan) || {}).situation || "—";
  }

  // findings + self-review: strategist_findings.jsonl, else the findings inside each plan
  function findingRows(d) {
    let rows = (d.findings || []).map((f) => ({ ...f }));
    if (!rows.length) for (const doc of d.history) for (const f of ((doc.plan || {}).findings || [])) rows.push({ ts: doc.updated, tick: doc.tick, ...f });
    const byTick = new Map(d.history.map((h) => [h.tick, h]));
    for (const r of rows) r.doc = byTick.get(r.tick) || d.history.find((h) => Math.abs((h.updated || 0) - (r.ts || 0)) < 5) || null;
    return rows.sort((a, b) => (b.ts || 0) - (a.ts || 0));
  }
  function findingsPanel(d) {
    const all = findingRows(d);
    const counts = {};
    for (const r of all) counts[r.topic || "general"] = (counts[r.topic || "general"] || 0) + 1;
    const p = U().panel("Hallazgos y autorrevisión", { sub: all.length ? all.length + " hallazgos" : "" });
    const bar = el("div", { class: "cb-fbar" },
      el("button", { type: "button", class: "cb-seg" + (S.topic === "todos" ? " on" : ""), onclick: () => { S.topic = "todos"; render(); } }, "Todos ", el("span", { class: "num" }, String(all.length))),
      Object.keys(TOPICS).filter((t) => counts[t]).map((t) => {
        const b = el("button", { type: "button", class: "cb-seg" + (S.topic === t ? " on" : ""), onclick: () => { S.topic = t; render(); } }, topicChip(t), el("span", { class: "num" }, String(counts[t])));
        return b;
      }),
      el("input", { class: "cb-q", placeholder: "Buscar…", value: S.q, oninput: (e) => { S.q = e.target.value; renderFindings(); } }));
    const host = el("div", { class: "cb-list cb-findings" });
    add(p.body, bar, host);
    S.findHost = host; S.findAll = all;
    renderFindings();
    return p;
  }
  function renderFindings() {
    const host = S.findHost; if (!host) return;
    const q = S.q.trim().toLowerCase();
    const rows = (S.findAll || []).filter((r) => (S.topic === "todos" || (r.topic || "general") === S.topic)
      && (!q || `${r.finding || ""} ${r.evidence || ""} ${r.fix || ""}`.toLowerCase().includes(q)));
    if (!rows.length) { U().keyedList(host, [], { key: () => "", render: () => el("div") , tail: [U().empty(S.findAll && S.findAll.length ? "Nada coincide con el filtro." : "Aún no hay hallazgos. El cerebro los publica en cada revisión.")] }); return; }
    U().keyedList(host, rows.slice(0, 150), {
      key: (r) => (r.ts || 0) + "|" + (r.topic || "") + "|" + (r.finding || "").slice(0, 40), sig: () => "",
      render: (r) => U().row({ cls: "cb-t-" + (TOPICS[r.topic] ? r.topic : "general"), cols: "86px 150px minmax(0,1fr) auto auto", cells: [
        { v: el("span", { class: "num" }, when(r.ts)), cls: "cb-time" },
        topicChip(r.topic),
        { v: el("div", {}, el("div", { class: "cb-rowt" }, r.finding || ""),
          r.evidence ? el("div", { class: "cb-rows" }, "Prueba: " + r.evidence) : null,
          r.fix ? el("div", { class: "cb-rows" }, "Arreglo: " + r.fix) : null), cls: "wrap" },
        r.doc ? planSource(r.doc) : U().sourceTag("opus"),
        statusChip(r.status || (r.doc ? planStatus(r.doc) : "visto"))] }),
    });
  }

  function councilPanel(d) {
    const votes = d.history.filter((h) => h.council && Array.isArray(h.council.votes)).slice().reverse();
    const p = U().panel("Votos del consejo sobre el cerebro", { sub: votes.length ? votes.length + " votaciones" : "" });
    if (!votes.length) { add(p.body, U().empty("Todavía no ha hecho falta votar: no hubo cambios grandes.")); return p; }
    const host = el("div", { class: "cb-list" });
    U().keyedList(host, votes.slice(0, 30), {
      key: (h) => String(h.updated), sig: () => "",
      render: (h) => {
        const c = h.council;
        const box = el("div", { class: "cb-vote " + (c.ok ? "is-ok" : "is-bad") },
          el("div", { class: "cb-vote-h" }, el("span", { class: "num" }, when(h.updated)), el("span", { class: "num cb-muted" }, "tick " + (h.tick ?? "?")),
            U().sourceTag("consejo", `${c.yes ?? 0}/${(c.votes || []).length}`), statusChip(c.ok ? "consejo" : "rechazado")),
          el("div", { class: "cb-rows" }, "Cambios: " + ((h.big_changes || []).join(" · ") || "—")),
          (c.votes || []).map((v) => el("div", { class: "cb-voter" },
            el("span", { class: "tag res tone-" + (v.verdict === "reject" ? "bad" : "ok") }, v.verdict === "reject" ? "En contra" : "A favor"),
            el("b", {}, roleName(v.role)), el("span", {}, v.reason || ""))));
        return box;
      },
    });
    add(p.body, host);
    return p;
  }
  const roleName = (r) => ({ auditor: "Auditor", negotiator: "Negociador", analyst: "Analista", judge: "Juez" }[r] || r || "—");

  // history: each plan with what changed against the previous one
  function diffPlans(a, b) {
    const pa = (a && a.plan) || {}, pb = (b && b.plan) || {};
    const out = [];
    const ga = pa.goal_buys || {}, gb = pb.goal_buys || {};
    for (const k of new Set([...Object.keys(ga), ...Object.keys(gb)])) {
      if (!(k in ga)) out.push(["add", `Objetivo ${k} hasta ${fmtP(gb[k])}`]);
      else if (!(k in gb)) out.push(["del", `Quita objetivo ${k}`]);
      else if (num(ga[k]) !== num(gb[k])) out.push(["chg", `Objetivo ${k}: ${fmtP(ga[k])} → ${fmtP(gb[k])}`]);
    }
    const ca = pa.cash_policy || {}, cb = pb.cash_policy || {};
    for (const k of ["reserve", "max_small_deal"]) if (num(ca[k]) !== num(cb[k])) out.push(["chg", `${k === "reserve" ? "Reserva" : "Trato pequeño"}: ${ca[k] != null ? fmtP(ca[k]) : "—"} → ${cb[k] != null ? fmtP(cb[k]) : "—"}`]);
    if ((pa.duel_claude_mode || "") !== (pb.duel_claude_mode || "") && pb.duel_claude_mode) out.push(["chg", `Duelos: ${pa.duel_claude_mode || "—"} → ${pb.duel_claude_mode}`]);
    const pda = (pa.pause_domains || []).join(","), pdb = (pb.pause_domains || []).join(",");
    if (pda !== pdb) out.push(["chg", `Pausa: ${pda || "ninguno"} → ${pdb || "ninguno"}`]);
    const ta = (pa.priorities || [])[0], tb = (pb.priorities || [])[0];
    if (tb && ta !== tb) out.push(["pri", "Nueva prioridad 1: " + tb]);
    return out;
  }
  function historyPanel(d) {
    const h = d.history;
    const p = U().panel("Historial de planes", { sub: h.length ? h.length + " planes" : "" });
    if (!h.length) { add(p.body, U().empty("Sin planes todavía.")); return p; }
    const items = h.map((doc, i) => ({ doc, diff: diffPlans(i ? h[i - 1] : null, doc) })).reverse();
    const host = el("div", { class: "cb-timeline" });
    U().keyedList(host, items.slice(0, 40), {
      key: (x) => String(x.doc.updated), sig: (x) => (S.histSel === String(x.doc.updated) ? "o" : "c"),
      render: (x) => {
        const open = S.histSel === String(x.doc.updated);
        const plan = x.doc.plan || {};
        return el("div", { class: "cb-tl" + (open ? " is-open" : "") },
          el("button", { type: "button", class: "cb-tl-h", onclick: () => { S.histSel = open ? null : String(x.doc.updated); render(); } },
            el("span", { class: "num" }, when(x.doc.updated)), el("span", { class: "num cb-muted" }, "tick " + (x.doc.tick ?? "?")),
            el("span", { class: "cb-tl-why" }, x.doc.reason || ""), planSource(x.doc), statusChip(planStatus(x.doc)),
            x.doc.cost_usd != null ? el("span", { class: "num cb-muted" }, U().fmtUsd(x.doc.cost_usd)) : null,
            U().icon("chevron", 13)),
          el("div", { class: "cb-diff" }, x.diff.length ? x.diff.map(([k, t]) => el("div", { class: "cb-d cb-d-" + k }, k === "add" ? "+ " : k === "del" ? "− " : "~ ", t))
            : el("div", { class: "cb-muted" }, "Sin cambios de ajustes respecto al plan anterior.")),
          open ? el("div", { class: "cb-tl-body" },
            plan.situation ? el("p", {}, plan.situation) : null,
            el("ol", { class: "cb-pri" }, (plan.priorities || []).map((t) => el("li", {}, t))),
            x.doc.proposed ? el("div", { class: "cb-rows cb-bad" }, "Propuesta rechazada por el consejo: " + ((x.doc.big_changes || []).join(" · ") || "—")) : null) : null);
      },
    });
    add(p.body, host);
    return p;
  }

  // ---------- render ----------
  function render() {
    const root = S.root; if (!root) return;
    const d = S.data;
    const wrap = root.querySelector(".scr-cerebro");
    if (!d) return;
    U().keepScroll(wrap, () => {
      const top = wrap.querySelector(".cb-top"), mid = wrap.querySelector(".cb-mid"), bot = wrap.querySelector(".cb-bot");
      if (d.err && !d.cur && !(d.sv && d.sv.situation)) {
        const p = U().panel("Plan actual");
        add(p.body, U().empty(d.err.status === 404
          ? "El cerebro aún no ha publicado su plan." : "No se pudo leer el plan: " + (d.err.message || d.err)));
        top.replaceChildren(statusPanel(d));
        mid.replaceChildren(p);
        bot.replaceChildren();
        return;
      }
      top.replaceChildren(statusPanel(d));
      mid.replaceChildren(planPanel(d), el("div", { class: "cb-col" }, eventsPanel(d), councilPanel(d)));
      bot.replaceChildren(findingsPanel(d), historyPanel(d));
    });
  }

  window.Screens.cerebro = {
    title: "Cerebro",
    mount(root) {
      S.root = root;
      root.replaceChildren(el("div", { class: "scr-cerebro" },
        el("div", { class: "cb-top" }, U().loading()), el("div", { class: "cb-mid" }), el("div", { class: "cb-bot" })));
    },
    async refresh(root, data, params, opts) {
      S.root = root;
      try { const me = await A().rec("me"); window.__cbMe = (me && (me.data || me)) || {}; } catch (e) { /* optional */ }
      const d = await load(data);
      // avoid rebuilding when nothing changed (keeps scroll and open history item)
      const sig = JSON.stringify([d.cur && d.cur.updated, d.status && d.status.updated, d.history.length, d.findings.length, d.err && d.err.status, S.topic, S.histSel]);
      if (sig === S.sig && S.data && !(opts && opts.force)) return;
      S.sig = sig; S.data = d;
      render();
    },
    unmount() { S.root = null; S.sig = null; S.findHost = null; },
  };
})();
