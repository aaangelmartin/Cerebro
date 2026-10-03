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
  function topicChip(t, count) {
    const [label, ic, color] = topicOf(t);
    const c = el("span", { class: "chip type cb-chip" }, U().icon(ic, 13), el("span", { class: "chip-label" }, label),
      count !== undefined && count !== null ? el("span", { class: "chip-count num" }, String(count)) : null);
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
  const S = { root: null, data: null, err: null, histSel: null, fb: null, fbKey: null, fbState: null, fbKnown: null };

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

  // events: strings from the brain's detector, e.g. "offer #4310 addressed to us by abuela",
  // "level X: state a -> b", "schedule added: ...", "t06 score 11.1 -> 15.1",
  // "novelty <kind>: <untrusted source='game'>{json}</untrusted>". Parsed into {kind, text}.
  const EV_KIND = {
    offer: ["Oferta", "anuncio", "var(--t-puja)"], level: ["Nivel", "trend", "var(--t-compra)"],
    schedule: ["Calendario", "bell", "var(--t-cambio)"], score: ["Puntos", "competicion", "var(--t-duelo)"],
    dealer: ["Dealer", "dealer", "var(--t-dealer)"], venue: ["Tienda", "mercado", "var(--t-dealer)"],
    news: ["Noticia", "anuncio", "var(--t-anuncio)"], other: ["Evento", "bell", "var(--t-anuncio)"],
  };
  const ACTION_ES = { day_closes: "cierre", day_opens: "apertura", bench: "Market Test", duels: "duelos", round: "ronda" };
  function parseEvent(raw) {
    let t = typeof raw === "string" ? raw : (raw && (raw.text || raw.event)) || JSON.stringify(raw);
    const m = t.match(/^novelty ([\w.]+):\s*<untrusted[^>]*>([\s\S]*?)(<\/untrusted>|$)/);
    if (m) {
      const kind = m[1];
      let j = null; try { j = JSON.parse(m[2]); } catch (e) { j = null; }
      if (kind === "schedule" && j) {
        const when = j.at_hours != null ? "h" + fmtNum(j.at_hours, 2) : "";
        return { kind: "schedule", text: `Calendario: ${ACTION_ES[j.action] || j.action} ${when}${j.note ? " · " + j.note : ""}` };
      }
      if (j && j.type) {
        const ex = j.example || {}; const p = ex.payload || {};
        const head = p.headline || p.title || p.text || "";
        const k = /news/.test(j.type) ? "news" : /persona|dealer/.test(j.type) ? "dealer" : /venue/.test(j.type) ? "venue" : "other";
        return { kind: k, text: `Nuevo tipo de evento «${j.type}»${ex.actor ? " de " + ex.actor : ""}${head ? ": " + head : ""}` };
      }
      return { kind: /persona|dealer/.test(kind) ? "dealer" : /venue/.test(kind) ? "venue" : "other", text: "Novedad " + kind + (j ? "" : ": " + m[2].slice(0, 160)) };
    }
    if (/^offer /.test(t)) return { kind: "offer", text: t.replace(/^offer #(\d+) addressed to us by (\S+)/, "Oferta #$1 dirigida a nosotros por $2") };
    if (/^level /.test(t)) return { kind: /persona|dealer|chato|abuela|pilar/i.test(t) ? "dealer" : "level", text: t.replace(/^level /, "Nivel/dealer ").replace("state", "estado") };
    if (/^schedule (added|removed)/.test(t)) {
      const added = /added/.test(t);
      const items = t.replace(/^schedule [^:]*:\s*/, "").split(/,\s*/).map((x) => { const [h, a] = x.split("|"); return (ACTION_ES[a] || a || "?") + " h" + h; });
      return { kind: "schedule", text: (added ? "Calendario añade: " : "Calendario quita: ") + items.join(", ") };
    }
    const sc = t.match(/^(t\d+) score ([\d.]+) -> ([\d.]+)/);
    if (sc) return { kind: "score", text: `${U().teamName ? U().teamName(sc[1]) : sc[1]}: ${fmtNum(+sc[2], 1)} → ${fmtNum(+sc[3], 1)} puntos (${+sc[3] >= +sc[2] ? "+" : ""}${fmtNum(+sc[3] - +sc[2], 1)})` };
    if (/venue/.test(t)) return { kind: "venue", text: t };
    return { kind: "other", text: t.replace(/<\/?untrusted[^>]*>/g, "") };
  }
  // the plan's priority that talks about this kind of event; the first event of a plan falls back to priority 1
  const EV_WORDS = { schedule: /schedule|calendar|calendario/i, offer: /offer|#\d+|thread/i, score: /score|points|t\d\d/i,
    level: /level|unlock|dealer/i, dealer: /dealer|unlock|chato|abuela|pilar/i, venue: /venue|v\d\d|market/i, news: /news|radio|rumour/i };
  function evConcl(r) {
    const pri = ((r.doc && r.doc.plan) || {}).priorities || [];
    const rx = EV_WORDS[r.kind];
    const hit = rx && pri.find((p) => rx.test(p));
    return hit || (r.i === 0 ? pri[0] || ((r.doc && r.doc.plan) || {}).situation : "");
  }
  function evChip(kind) {
    const [label, ic, color] = EV_KIND[kind] || EV_KIND.other;
    const c = el("span", { class: "chip type cb-chip" }, U().icon(ic, 13), el("span", { class: "chip-label" }, label));
    c.style.setProperty("--tc", color);
    return c;
  }
  function eventsPanel(d) {
    const rows = [];
    for (const doc of d.history) (doc.events || []).forEach((e, i) => { const pe = parseEvent(e); rows.push({ ts: doc.updated, tick: doc.tick, i, ...pe, doc }); });
    rows.sort((a, b) => (b.ts || 0) - (a.ts || 0) || a.i - b.i);
    const p = U().panel("Eventos detectados", { sub: rows.length ? rows.length + " eventos" : "" });
    if (!rows.length) { add(p.body, U().empty("Aún no ha detectado eventos (dealer nuevo, nivel, calendario, tiendas, saltos de puntos).")); return p; }
    const host = el("div", { class: "cb-list cb-events" });
    U().keyedList(host, rows.slice(0, 80), {
      key: (r) => (r.ts || 0) + "|" + r.i, sig: () => "",
      render: (r) => {
        const n = el("div", { class: "cb-ev" },
          el("div", { class: "cb-ev-h" }, el("span", { class: "num cb-time" }, when(r.ts)), evChip(r.kind),
            el("span", { class: "num cb-muted" }, r.tick != null ? "tick " + r.tick : ""), el("span", { class: "cb-sp" }), statusChip(planStatus(r.doc))),
          el("div", { class: "cb-rowt", title: r.text }, short(r.text, 240)),
          evConcl(r) ? el("div", { class: "cb-rows" }, "Conclusión del cerebro: " + short(evConcl(r), 240)) : null);
        n.style.setProperty("--tc", (EV_KIND[r.kind] || EV_KIND.other)[2]);
        return n;
      },
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
  // filter bar: the shared ui.filterBar (as in Home/Colección) with one chip per finding topic; built once and kept
  function findingsPanel(d) {
    const all = findingRows(d);
    const counts = {};
    for (const r of all) { const t = TOPICS[r.topic] ? r.topic : "general"; counts[t] = (counts[t] || 0) + 1; }
    const topics = Object.keys(TOPICS).filter((t) => counts[t]);
    const p = U().panel("Hallazgos y autorrevisión", { sub: all.length ? all.length + " hallazgos" : "" });
    const tkey = topics.join(",");
    if (!S.fb || S.fbKey !== tkey) {
      const prev = S.fbState;
      S.fbKey = tkey;
      S.fb = U().filterBar({ types: topics, counts, search: true, placeholder: "Buscar en hallazgos…",
        selected: prev ? topics.filter((t) => prev.types.has(t) || !S.fbKnown || !S.fbKnown.has(t)) : topics,
        chip: (t, n) => topicChip(t, n),
        onChange: (st) => { S.fbState = st; renderFindings(); } });
      S.fbState = S.fb.state; S.fbKnown = new Set(topics);
    } else S.fb.setCounts(counts);
    const host = el("div", { class: "cb-list cb-findings" });
    add(p.body, topics.length ? S.fb : null, host);
    S.findHost = host; S.findAll = all;
    renderFindings();
    return p;
  }
  function renderFindings() {
    const host = S.findHost; if (!host) return;
    const st = S.fbState || { types: null, q: "" };
    const q = (st.q || "").toLowerCase();
    const rows = (S.findAll || []).filter((r) => (!st.types || st.types.has(TOPICS[r.topic] ? r.topic : "general"))
      && (!q || `${r.finding || ""} ${r.evidence || ""} ${r.fix || ""}`.toLowerCase().includes(q)));
    if (!rows.length) { U().keyedList(host, [], { key: () => "", render: () => el("div"), tail: [U().empty(S.findAll && S.findAll.length ? "Nada coincide con el filtro." : "Aún no hay hallazgos. El cerebro los publica en cada revisión.")] }); return; }
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


  // ---------- chat with the brain ----------
  // GET brain/chat?since=<ts> -> list (or {messages}/{items}) of {ts, role:"user"|"brain", by, text, refs?}
  const C = { msgs: [], since: null, host: null, list: null, input: null, state: "idle", err: null, waiting: false, busy: false };
  const NAME_KEY = "bazaar.dash.chatName";
  const getName = () => { try { return localStorage.getItem(NAME_KEY) || ""; } catch (e) { return ""; } };
  const setName = (n) => { try { localStorage.setItem(NAME_KEY, n); } catch (e) { /* private mode */ } };
  const msgList = (r) => (Array.isArray(r) ? r : r && Array.isArray(r.messages) ? r.messages : r && Array.isArray(r.items) ? r.items : []);

  function chatMount() {
    const list = el("div", { class: "cb-chat-list" });
    const input = el("textarea", { class: "cb-chat-in", rows: 2, placeholder: "Pregunta o pide algo al cerebro…" });
    const send = el("button", { type: "button", class: "cb-chat-send" }, U().icon("arrow", 14), "Enviar");
    input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); chatSend(); } });
    send.addEventListener("click", chatSend);
    const nameBox = el("div", { class: "cb-chat-name" });
    const host = el("aside", { class: "cb-chat" },
      el("header", { class: "cb-chat-h" }, U().icon("cerebro", 15), el("b", {}, "Habla con el cerebro"), el("span", { class: "cb-chat-st" })),
      list, nameBox, el("div", { class: "cb-chat-f" }, input, send));
    C.host = host; C.list = list; C.input = input; C.nameBox = nameBox; C.send = send;
    renderName(); renderChat();
    return host;
  }
  function renderName() {
    const box = C.nameBox; if (!box) return;
    const n = getName();
    if (n) { box.replaceChildren(el("span", { class: "cb-muted" }, "Escribes como "), el("b", {}, n), " ",
      el("button", { type: "button", class: "cb-link", onclick: () => { setName(""); renderName(); } }, "cambiar")); return; }
    const inp = el("input", { class: "cb-q", placeholder: "Tu nombre (por defecto: equipo)" });
    const ok = () => { setName(inp.value.trim() || "equipo"); renderName(); };
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") ok(); });
    box.replaceChildren(inp, el("button", { type: "button", class: "cb-seg", onclick: ok }, "Guardar"));
  }
  function renderChat() {
    const list = C.list; if (!list) return;
    const st = C.host.querySelector(".cb-chat-st");
    if (st) st.textContent = C.state === "off" ? "inactivo" : C.waiting ? "pensando…" : "";
    const atEnd = list.scrollHeight - list.scrollTop - list.clientHeight < 12;
    const kids = [];
    if (C.state === "off") kids.push(U().empty("El chat del cerebro aún no está activo."));
    else if (C.state === "error") kids.push(U().error(C.err));
    else if (!C.msgs.length && C.state === "idle") kids.push(U().loading());
    else if (!C.msgs.length) kids.push(U().empty("Aún no hay mensajes. Pregúntale qué está pensando o por qué tomó una decisión."));
    for (const m of C.msgs) {
      const me = m.role !== "brain";
      kids.push(el("div", { class: "cb-msg " + (me ? "is-user" : "is-brain") + (m.pending ? " is-pending" : "") },
        el("div", { class: "cb-msg-h" }, el("b", {}, me ? (m.by || "equipo") : "Cerebro"), el("span", { class: "num" }, m.ts ? when(m.ts) : "")),
        el("div", { class: "cb-msg-t" }, m.text || ""),
        Array.isArray(m.refs) && m.refs.length ? el("div", { class: "cb-msg-refs num" }, m.refs.map((x) => typeof x === "string" ? x : (x.id || x.ref || JSON.stringify(x))).join(" · ")) : null));
    }
    if (C.waiting) kids.push(el("div", { class: "cb-msg is-brain is-thinking" }, U().icon("cerebro", 13), "El cerebro está pensando…"));
    U().keepScroll(list.parentNode, () => list.replaceChildren(...kids));
    if (atEnd || C.forceEnd) { list.scrollTop = list.scrollHeight; C.forceEnd = false; }
  }
  async function chatPull() {
    if (C.busy || !C.list) return;
    C.busy = true;
    try {
      const r = await A().brainChat(C.since == null ? undefined : C.since);
      const got = msgList(r);
      C.state = "on";
      if (got.length) {
        const seen = new Set(C.msgs.filter((m) => !m.pending).map((m) => (m.ts || 0) + "|" + m.role + "|" + m.text));
        let added = false;
        for (const m of got) {
          const k = (m.ts || 0) + "|" + m.role + "|" + m.text;
          if (seen.has(k)) continue;
          seen.add(k); added = true;
          // the server copy of our own message replaces the local pending one
          if (m.role !== "brain") { const i = C.msgs.findIndex((x) => x.pending && x.text === m.text); if (i >= 0) C.msgs.splice(i, 1); }
          C.msgs.push(m);
          if (m.role === "brain") C.waiting = false;
        }
        C.msgs.sort((a, b) => (a.ts || 0) - (b.ts || 0));
        C.since = Math.max(C.since || 0, ...got.map((m) => +m.ts || 0));
        if (added) renderChat();
      } else if (C.state !== C.lastState) renderChat();
    } catch (e) {
      C.state = e && e.status === 404 ? "off" : "error"; C.err = e;
      renderChat();
    } finally { C.lastState = C.state; C.busy = false; }
  }
  async function chatSend() {
    const text = (C.input.value || "").trim();
    if (!text || C.sending) return;
    if (C.state === "off") { renderChat(); return; }
    const by = getName() || "equipo";
    C.sending = true; C.send.disabled = true;
    const mine = { ts: Date.now() / 1000, role: "user", by, text, pending: true };
    C.msgs.push(mine); C.waiting = true; C.forceEnd = true; C.input.value = "";
    renderChat();
    try { await A().brainSay(text, by); mine.pending = false; }
    catch (e) {
      C.waiting = false; C.msgs.splice(C.msgs.indexOf(mine), 1); C.input.value = text;
      U().toast({ type: "error", title: "No se pudo enviar", text: e && e.status === 404 ? "El chat del cerebro aún no está activo." : (e && e.message) || "Error" });
    } finally { C.sending = false; C.send.disabled = false; renderChat(); chatPull(); }
  }
  // poll faster than the 2 s screen refresh while waiting for a reply
  setInterval(() => { if (C.list && C.list.isConnected && C.waiting) chatPull(); }, 1500);


  // ---------- "Para el equipo": what the brain decided but people must do (outbox) ----------
  // GET outbox -> {items:[...]} with kind code | promo | task; POST outbox/<id> {status, note}
  const O = { items: [], state: "idle", err: null, tab: "code", open: new Set(), host: null, busy: false, at: 0, sig: "" };
  const OB_TABS = [["code", "Cambios de código", "bot"], ["promo", "Mensajes", "anuncio"], ["task", "Tareas", "check"]];
  const SEV = { critical: ["Crítico", "var(--bad)", "alert"], high: ["Alto", "var(--t-venta)", "alert"], medium: ["Medio", "var(--t-puja)", "alert"],
    low: ["Bajo", "var(--t-anuncio)", "alert"] };
  const OB_STATUS = { open: ["Abierto", "warn"], accepted: ["Aceptado", "ok"], done: ["Hecho", "ok"], rejected: ["Rechazado", "bad"],
    draft: ["Borrador", "warn"], sent: ["Enviado", "ok"], discarded: ["Descartado", "mute"] };
  const isOpen = (x) => x.status === "open" || x.status === "draft" || x.status === "accepted";
  const kindOf = (x) => x.kind || (x.channel ? "promo" : x.task ? "task" : "code");
  function obChip(label, color, ic) { const c = el("span", { class: "chip type cb-chip" }, U().icon(ic, 13), el("span", { class: "chip-label" }, label)); c.style.setProperty("--tc", color); return c; }
  function obStatus(st) { const [l, t] = OB_STATUS[st] || [st || "—", "mute"]; return el("span", { class: "tag res tone-" + t }, l); }

  function outboxMount() {
    const host = el("section", { class: "panel cb-outbox" });
    O.host = host; O.sig = "";
    obRender();
    return host;
  }
  async function outboxPull(force) {
    if (!O.host || O.busy || (!force && Date.now() - O.at < 4000)) return;
    O.busy = true; O.at = Date.now();
    try {
      const r = await A().outbox();
      O.items = (Array.isArray(r) ? r : (r && r.items) || []).map((x) => ({ ...x, kind: kindOf(x) }));
      O.state = "on";
    } catch (e) { O.state = e && e.status === 404 ? "off" : "error"; O.err = e; }
    finally { O.busy = false; }
    obRender();
  }
  async function obSet(item, status, note) {
    try {
      const r = await A().outboxSet(item.id, status, note);
      const nx = (r && r.item) || { ...item, status, human_note: note };
      const i = O.items.findIndex((x) => x.id === item.id); if (i >= 0) O.items[i] = { ...nx, kind: kindOf(nx) };
      O.sig = ""; obRender();
      if (window.__pollOutbox) window.__pollOutbox();
    } catch (e) { U().toast({ type: "error", title: "No se pudo guardar", text: (e && e.message) || "Error" }); }
  }
  async function copyText(t) {
    try { await navigator.clipboard.writeText(t); return true; } catch (e) {
      const ta = el("textarea", { style: "position:fixed;left:-9999px" }); ta.value = t; document.body.appendChild(ta); ta.select();
      let ok = false; try { ok = document.execCommand("copy"); } catch (e2) { ok = false; } ta.remove(); return ok;
    }
  }

  function obHead(x) {
    if (x.kind === "code") {
      const [l, c, ic] = SEV[x.severity] || SEV.low;
      return [obChip(l, c, ic), el("div", { class: "cb-ob-title" }, x.title || "Cambio de código"),
        x.occurrences > 1 ? el("span", { class: "tag res tone-" + (x.recurred ? "bad" : "mute") }, (x.recurred ? "vuelve a pasar · " : "") + "×" + x.occurrences) : null];
    }
    if (x.kind === "promo") return [obChip(x.channel === "whatsapp" ? "WhatsApp" : "En el juego", x.channel === "whatsapp" ? "var(--t-compra)" : "var(--t-cambio)", "anuncio"),
      el("div", { class: "cb-ob-title" }, short(x.text, 140))];
    return [obChip("Tarea", "var(--t-dealer)", "check"), el("div", { class: "cb-ob-title" }, x.task || "Tarea"),
      x.occurrences > 1 ? el("span", { class: "tag res tone-mute" }, "×" + x.occurrences) : null];
  }
  function obDetail(x) {
    const ev = Array.isArray(x.evidence) ? x.evidence : x.evidence ? [x.evidence] : [];
    const sec = (cap, body) => body ? el("div", { class: "cb-ob-sec" }, el("div", { class: "cb-cap" }, cap), body) : null;
    const txt = (t) => t ? el("p", {}, t) : null;
    const note = el("input", { class: "cb-q cb-ob-note", placeholder: "Nota (opcional)", value: "" });
    const btn = (label, status, tone) => el("button", { type: "button", class: "cb-ob-btn tone-" + tone, onclick: (e) => { e.stopPropagation(); obSet(x, status, note.value.trim()); } }, label);
    let actions;
    if (x.kind === "promo") {
      const cp = el("button", { type: "button", class: "cb-ob-btn", onclick: async (e) => { e.stopPropagation(); const ok = await copyText(x.text || ""); cp.textContent = ok ? "Copiado" : "No se pudo copiar"; setTimeout(() => { cp.textContent = "Copiar texto"; }, 1500); } }, "Copiar texto");
      actions = [cp, btn("Marcar enviado", "sent", "ok"), btn("Descartar", "discarded", "bad")];
    } else if (x.kind === "code") actions = [btn("Aceptar", "accepted", "warn"), btn("Hecho", "done", "ok"), btn("Rechazar", "rejected", "bad")];
    else actions = [btn("Hecho", "done", "ok"), btn("Rechazar", "rejected", "bad")];
    return el("div", { class: "cb-ob-detail", onclick: (e) => e.stopPropagation() },
      x.kind === "promo" ? sec("Texto", el("pre", { class: "cb-ob-text" }, x.text || "")) : null,
      sec("Por qué", txt(x.why)),
      sec("Diagnóstico", txt(x.diagnosis)),
      sec("Pruebas", ev.length ? el("ul", { class: "cb-ob-ev" }, ev.map((e) => el("li", {}, typeof e === "string" ? e : JSON.stringify(e)))) : null),
      sec("Cambio propuesto", txt(x.proposed_change)),
      sec("Esbozo del parche", x.patch_sketch ? el("pre", { class: "cb-ob-code" }, x.patch_sketch) : null),
      sec("Impacto", txt(x.impact)),
      x.human_note ? sec("Nota del equipo", txt(x.human_note)) : null,
      el("div", { class: "cb-ob-actions" }, note, actions));
  }
  function obRender() {
    const host = O.host; if (!host) return;
    const inTab = (x, k) => x.kind === k && !isReply(x);   // replies to pasted messages are shown under that message
    const counts = {}; for (const [k] of OB_TABS) counts[k] = O.items.filter((x) => inTab(x, k) && isOpen(x)).length;
    const sig = JSON.stringify([O.state, O.tab, [...O.open], O.items.map((x) => [x.id, x.status, x.updated, x.occurrences])]);
    if (sig === O.sig) return; O.sig = sig;
    const totalOpen = Object.values(counts).reduce((a, b) => a + b, 0);
    const tabs = el("div", { class: "cb-ob-tabs" }, OB_TABS.map(([k, label, ic]) => el("button", { type: "button", class: "cb-ob-tab" + (O.tab === k ? " on" : ""),
      onclick: () => { O.tab = k; obRender(); } }, U().icon(ic, 14), label, el("span", { class: "num cb-ob-n" + (counts[k] ? " has" : "") }, String(counts[k])))));
    const head = el("header", { class: "panel-head" }, el("h2", { class: "panel-title" }, "Para el equipo"),
      el("span", { class: "panel-sub" }, O.state === "on" ? (totalOpen ? totalOpen + " pendientes · lo decidió el cerebro y lo hacéis vosotros" : "nada pendiente") : ""));
    const list = el("div", { class: "cb-list cb-ob-list" });
    let body;
    if (O.state === "idle") body = U().loading();
    else if (O.state === "off") body = U().empty("La bandeja del cerebro aún no está activa.");
    else if (O.state === "error") body = U().error(O.err);
    else {
      const rows = O.items.filter((x) => inTab(x, O.tab))
        .sort((a, b) => (isOpen(b) - isOpen(a)) || ((+b.updated || +b.ts || 0) - (+a.updated || +a.ts || 0)));
      if (!rows.length) body = U().empty(O.tab === "code" ? "Sin cambios de código propuestos." : O.tab === "promo" ? "Sin mensajes para enviar." : "Sin tareas.");
      else {
        U().keyedList(list, rows, {
          key: (x) => String(x.id), sig: (x) => [x.status, x.updated, x.occurrences, O.open.has(String(x.id))].join("|"),
          render: (x) => {
            const opened = O.open.has(String(x.id));
            const color = x.kind === "code" ? (SEV[x.severity] || SEV.low)[1] : x.kind === "promo" ? "var(--t-compra)" : "var(--t-dealer)";
            const n = el("div", { class: "cb-ob-item" + (isOpen(x) ? "" : " is-closed") + (opened ? " is-open" : ""),
              onclick: () => { const k = String(x.id); if (O.open.has(k)) O.open.delete(k); else O.open.add(k); O.sig = ""; obRender(); } },
              el("div", { class: "cb-ob-row" }, el("span", { class: "num cb-time" }, when(+x.updated || +x.ts)), ...obHead(x).filter(Boolean),
                el("span", { class: "cb-sp" }), obStatus(x.status), U().icon("chevron", 13)),
              opened ? obDetail(x) : null);
            n.style.setProperty("--tc", color);
            return n;
          },
        });
        body = list;
      }
    }
    U().keepScroll(host, () => host.replaceChildren(head, tabs, el("div", { class: "panel-body" }, body)));
    if (typeof xRender === "function") xRender();
  }


  // ---------- WhatsApp messages from other teams, pasted by the team for the brain ----------
  // POST brain/external {text, by, team_hint?} -> {added, duplicates}; GET brain/external?since= -> {items}
  const X = { items: [], state: "idle", err: null, host: null, list: null, busy: false, at: 0, sig: "", sending: false };
  const XT = { request: ["Petición", "puja", "var(--t-puja)"], offer: ["Oferta", "venta", "var(--t-compra)"], tip: ["Pista", "target", "var(--t-cambio)"],
    complaint: ["Queja", "alert", "var(--t-venta)"], promo: ["Promo", "anuncio", "var(--t-anuncio)"], news: ["Noticia", "bell", "var(--t-dealer)"] };
  function xChip(t) { const [l, ic, c] = XT[t] || [t, "anuncio", "var(--t-anuncio)"]; const n = el("span", { class: "chip type cb-chip" }, U().icon(ic, 13), el("span", { class: "chip-label" }, l)); n.style.setProperty("--tc", c); return n; }
  function externalMount() {
    const ta = el("textarea", { class: "cb-chat-in cb-x-in", rows: 3, placeholder: "Pega aquí mensajes del grupo de WhatsApp (uno o varios)…" });
    const sel = el("select", { class: "fb-select cb-x-team", "aria-label": "Equipo" }, el("option", { value: "" }, "Equipo: detectar"));
    for (let i = 1; i <= 18; i++) { const id = "t" + String(i).padStart(2, "0"); sel.append(el("option", { value: id }, (U().teamName ? U().teamName(id) : id) + (id === "t10" ? " · Nosotros" : ""))); }
    const send = el("button", { type: "button", class: "cb-chat-send" }, U().icon("arrow", 14), "Enviar al cerebro");
    const go = async () => {
      const text = ta.value.trim(); if (!text || X.sending) return;
      X.sending = true; send.disabled = true;
      try {
        const r = await A().externalAdd(text, getName() || "equipo", sel.value || undefined);
        const n = ((r && r.added) || []).length, dup = (r && r.duplicates) || 0;
        U().toast({ type: "dealer", title: "Mensajes enviados al cerebro", text: `${n} nuevos${dup ? " · " + dup + " repetidos" : ""}` });
        ta.value = ""; sel.value = ""; X.at = 0; extPull(true);
      } catch (e) {
        U().toast({ type: "error", title: "No se pudo enviar", text: e && e.status === 404 ? "La entrada de mensajes aún no está activa." : (e && e.message) || "Error" });
      } finally { X.sending = false; send.disabled = false; }
    };
    send.addEventListener("click", go);
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); go(); } });
    X.list = el("div", { class: "cb-x-body" });
    const host = el("section", { class: "panel cb-x" },
      el("header", { class: "panel-head" }, el("h2", { class: "panel-title" }, "Mensajes de WhatsApp"),
        el("span", { class: "panel-sub" }, "lo que dicen otros equipos, para que el cerebro lo tenga en cuenta")),
      el("div", { class: "cb-x-form" }, ta, el("div", { class: "cb-x-side" }, sel, send)), X.list);
    X.host = host; X.sig = "";
    xRender();
    return host;
  }
  async function extPull(force) {
    if (!X.host || X.busy || (!force && Date.now() - X.at < 5000)) return;
    X.busy = true; X.at = Date.now();
    try { const r = await A().external(); X.items = Array.isArray(r) ? r : (r && r.items) || []; X.state = "on"; }
    catch (e) { X.state = e && e.status === 404 ? "off" : "error"; X.err = e; }
    finally { X.busy = false; }
    xRender();
  }
  function entityChips(en) {
    if (!en) return [];
    const out = [];
    for (const o of en.offer_ids || []) out.push(el("span", { class: "tag res tone-mute num" }, "oferta #" + o));
    for (const c of en.cards || []) out.push(el("span", { class: "tag res tone-mute num" }, c));
    for (const v of en.venues || []) out.push(el("span", { class: "tag res tone-mute num" }, v));
    for (const p of en.prices || []) out.push(el("span", { class: "tag res tone-mute num" }, fmtP(p)));
    for (const t of en.ticks || []) out.push(el("span", { class: "tag res tone-mute num" }, "tick " + t));
    return out;
  }
  // replies the brain drafted for a pasted message live in the outbox (promo, channel whatsapp, reply_to.external_id)
  const isReply = (o) => o && o.kind === "promo" && o.reply_to && o.reply_to.external_id != null;
  function replyFor(x) {
    if (!x) return null;
    if (x.reply_outbox_id != null) { const o = O.items.find((y) => String(y.id) === String(x.reply_outbox_id)); if (o) return o; }
    return O.items.find((o) => isReply(o) && String(o.reply_to.external_id) === String(x.id)) || null;
  }
  function replyBlock(x) {
    const o = replyFor(x);
    if (!o) return x.reply_outbox_id != null && O.state !== "on" ? el("div", { class: "cb-rows" }, "Respuesta preparada (la bandeja aún no está activa).") : null;
    const done = o.status === "sent" || o.status === "discarded";
    const cp = el("button", { type: "button", class: "cb-ob-btn" }, "Copiar respuesta");
    cp.addEventListener("click", async () => { const ok = await copyText(o.text || ""); cp.textContent = ok ? "Copiado" : "No se pudo copiar"; setTimeout(() => { cp.textContent = "Copiar respuesta"; }, 1500); });
    const act = (label, status, tone) => { const b = el("button", { type: "button", class: "cb-ob-btn tone-" + tone }, label); b.addEventListener("click", () => obSet(o, status, "")); return b; };
    return el("div", { class: "cb-x-reply" + (done ? " is-done" : "") },
      el("div", { class: "cb-ev-h" }, el("span", { class: "cb-cap" }, "Respuesta del cerebro"), (o.reply_to && o.reply_to.author) ? el("span", { class: "cb-muted" }, "para " + o.reply_to.author) : null,
        el("span", { class: "cb-sp" }), obStatus(o.status)),
      el("pre", { class: "cb-ob-text" }, o.text || ""),
      o.why ? el("div", { class: "cb-rows" }, "Por qué: " + o.why) : null,
      el("div", { class: "cb-ob-actions" }, cp, done ? null : act("Marcar enviado", "sent", "ok"), done ? null : act("Descartar", "discarded", "bad")));
  }
  function xRender() {
    const box = X.list; if (!box) return;
    const sig = JSON.stringify([X.state, X.items.map((x) => [x.id, x.actionable, x.brain_conclusion, x.llm && JSON.stringify(x.llm).length]),
      O.items.filter(isReply).map((o) => [o.id, o.status, o.text])]);
    if (sig === X.sig) return; X.sig = sig;
    if (X.state === "idle") return box.replaceChildren(U().loading());
    if (X.state === "off") return box.replaceChildren(U().empty("La entrada de mensajes aún no está activa."));
    if (X.state === "error") return box.replaceChildren(U().error(X.err));
    if (!X.items.length) return box.replaceChildren(U().empty("Aún no habéis pegado mensajes."));
    const rows = X.items.slice().sort((a, b) => (!!b.actionable - !!a.actionable) || ((+b.received_at || +b.ts || 0) - (+a.received_at || +a.ts || 0)));
    const list = box.querySelector(".cb-list") || el("div", { class: "cb-list cb-x-list" });
    U().keyedList(list, rows.slice(0, 120), {
      key: (x) => String(x.id), sig: (x) => { const r = replyFor(x); return [x.actionable, x.brain_conclusion, x.llm && JSON.stringify(x.llm).length, r && r.id, r && r.status, r && r.text].join("|"); },
      render: (x) => {
        const llm = x.llm || {};
        const concl = x.brain_conclusion || llm.conclusion || llm.summary || llm.action || x.action_hint || "";
        const team = x.team ? (x.team === "t10" ? U().teamTag("t10", { us: true }) : U().teamTag(x.team)) : el("span", { class: "cb-muted" }, x.author || "¿equipo?");
        const n = el("div", { class: "cb-x-item" + (x.actionable ? " is-act" : "") },
          el("div", { class: "cb-ev-h" }, el("span", { class: "num cb-time" }, when(+x.received_at || +x.ts)),
            x.actionable ? el("span", { class: "tag cb-x-act" }, U().icon("bell", 12), "Hay que actuar") : null,
            team, x.author && x.team && x.author !== (U().teamName ? U().teamName(x.team) : x.team) ? el("span", { class: "cb-muted" }, x.author) : null,
            (x.types || []).map(xChip), x.about_us ? el("span", { class: "tag res tone-warn" }, "Sobre nosotros") : null,
            el("span", { class: "cb-sp" }), el("span", { class: "cb-muted" }, "pegado por " + (x.by || "equipo"))),
          el("div", { class: "cb-x-text" }, x.text || ""),
          entityChips(x.entities).length ? el("div", { class: "cb-x-ents" }, entityChips(x.entities)) : null,
          concl ? el("div", { class: "cb-rows" }, (x.actionable ? "Qué hacer: " : "Conclusión del cerebro: ") + concl) : null,
          replyBlock(x));
        n.style.setProperty("--tc", x.actionable ? "var(--warn)" : (XT[(x.types || [])[0]] || [0, 0, "var(--t-anuncio)"])[2]);
        return n;
      },
    });
    if (!list.isConnected) box.replaceChildren(list);
  }

  window.Screens.cerebro = {
    title: "Cerebro",
    mount(root) {
      S.root = root;
      root.replaceChildren(el("div", { class: "cb-layout" },
        el("div", { class: "scr-cerebro" },
          el("div", { class: "cb-top" }, U().loading()), outboxMount(), externalMount(), el("div", { class: "cb-mid" }), el("div", { class: "cb-bot" })),
        chatMount()));
    },
    async refresh(root, data, params, opts) {
      S.root = root;
      chatPull();
      outboxPull(opts && opts.force);
      extPull(opts && opts.force);
      try { const me = await A().rec("me"); window.__cbMe = (me && (me.data || me)) || {}; } catch (e) { /* optional */ }
      const d = await load(data);
      // avoid rebuilding when nothing changed (keeps scroll and open history item)
      const sig = JSON.stringify([d.cur && d.cur.updated, d.status && d.status.updated, d.history.length, d.findings.length, d.err && d.err.status, S.histSel]);
      if (sig === S.sig && S.data && !(opts && opts.force)) return;
      S.sig = sig; S.data = d;
      render();
    },
    unmount() { S.root = null; S.sig = null; S.findHost = null; C.host = null; O.host = null; X.host = null; },
  };
})();
