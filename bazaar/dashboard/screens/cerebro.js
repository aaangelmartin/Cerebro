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

  const tr = (k, v) => window.I18N.t(k, v);
  // A finding's evidence is a string, a list, or (deep research) an object {brief, files, ...}: show its words.
  const evText = (e) => (e === null || e === undefined || e === "" ? "" : typeof e === "string" ? e
    : Array.isArray(e) ? e.map(evText).filter(Boolean).join(" · ")
      : typeof e === "object" ? (e.brief || e.text || e.summary || Object.entries(e).map(([k, v]) => k + ": " + (typeof v === "object" ? JSON.stringify(v) : v)).join(" · "))
        : String(e));
  // labels in the tables below are i18n keys, resolved with tr() when rendered
  const DOMAINS = [["market", "cerebro.domain.market", "mercado"], ["dealers", "cerebro.domain.dealers", "dealer"], ["duels", "cerebro.domain.duels", "duelo"], ["broker", "cerebro.domain.broker", "flask"]];
  // finding topics: label, icon, colour
  const TOPICS = {
    self_review: ["cerebro.topic.self_review", "check", "var(--t-puja)"], rivals: ["cerebro.topic.rivals", "rivales", "var(--t-duelo)"],
    gap: ["cerebro.topic.gap", "trend", "var(--t-cambio)"], idle: ["cerebro.topic.idle", "alert", "var(--t-venta)"],
    llm: ["cerebro.topic.llm", "cloud", "var(--t-venta)"], offers: ["cerebro.topic.offers", "anuncio", "var(--t-puja)"],
    venues: ["cerebro.topic.venues", "mercado", "var(--t-dealer)"], goals: ["cerebro.topic.goals", "target", "var(--t-compra)"],
    events: ["cerebro.topic.events", "bell", "var(--t-dealer)"], general: ["cerebro.topic.general", "supervision", "var(--t-anuncio)"],
  };
  const topicOf = (t) => TOPICS[t] || TOPICS.general;
  function topicChip(t, count) {
    const [lk, ic, color] = topicOf(t); const label = tr(lk);
    const c = el("span", { class: "chip type cb-chip" }, U().icon(ic, 13), el("span", { class: "chip-label" }, label),
      count !== undefined && count !== null ? el("span", { class: "chip-count num" }, String(count)) : null);
    c.style.setProperty("--tc", color);
    return c;
  }
  function statusChip(st) {
    const map = { aplicado: ["cerebro.status.applied", "ok"], consejo: ["cerebro.status.council", "ok"], pendiente: ["cerebro.status.pending", "warn"],
      rechazado: ["cerebro.status.rejected", "bad"], visto: ["cerebro.status.noted", "mute"] };
    const [label, tone] = map[st] || map.visto;
    return el("span", { class: "tag res tone-" + tone }, tr(label));
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
    let budget = null;
    try { budget = await A().brainBudget(); } catch (e) { /* optional: 404 until the backend serves it */ }
    let control = null;
    try { control = await A().getControl(); } catch (e) { /* optional */ }
    const sv = (ov && ov.strategy) || null;
    const cur = (r && r.current) || null;
    const history = ((r && r.history) || []).slice().sort((a, b) => (num(a.updated) || 0) - (num(b.updated) || 0));
    if (cur && !history.some((h) => h.updated === cur.updated)) history.push(cur);
    return { cur, status: (r && r.status) || {}, history, findings: (r && r.findings) || [], sv, spend, control, budget, err };
  }

  // ---------- pieces ----------
  function statusPanel(d) {
    const st = d.status || {};
    const age = st.updated ? Date.now() / 1000 - st.updated : null;
    const on = age !== null && age < 300;
    const cur = d.cur || {};
    const nextT = num((cur.plan || {}).next_check_in_ticks);
    const spentStrategy = d.spend && d.spend.by_purpose ? d.spend.by_purpose.strategy : st.spent_today;
    const pill = el("span", { class: "pill tone-" + (on ? "ok" : "bad") }, el("span", { class: "dot" }), on ? tr("cerebro.on") : tr("cerebro.off"));
    const kpis = el("div", { class: "cb-kpis" },
      U().kpi({ label: tr("cerebro.st.state"), value: pill, sub: on ? tr("cerebro.st.beatAgo", { d: U().fmtDur(age) }) : age === null ? tr("cerebro.st.noBeat") : tr("cerebro.st.lastBeat", { ago: U().fmtAgo(st.updated) }) }),
      U().kpi({ label: tr("cerebro.st.lastPlan"), value: cur.updated ? when(cur.updated) : "—", sub: cur.tick != null ? "tick " + cur.tick + (cur.reason ? " · " + cur.reason : "") : "" }),
      U().kpi({ label: tr("cerebro.st.next"), value: nextT ? tr("cerebro.st.inTicks", { n: nextT }) : "—", sub: tr("cerebro.st.nextSub") }),
      U().kpi({ label: tr("cerebro.st.model"), value: (cur.model || "claude-opus-5-5").replace("claude-", "").replace(/-/g, " "), sub: tr("cerebro.st.effort") }),
      U().kpi({ label: tr("cerebro.st.spend"), value: (d.budget && num(d.budget.spent_today) != null) ? U().fmtUsd(d.budget.spent_today) : spentStrategy != null ? U().fmtUsd(spentStrategy) : "—",
        sub: (d.budget && d.budget.cap_today) ? tr("cerebro.st.cap", { v: U().fmtUsd(d.budget.cap_today) }) : st.day_cap ? tr("cerebro.st.cap", { v: U().fmtUsd(st.day_cap) }) : (st.calls != null ? tr("cerebro.st.calls", { n: st.calls }) : "") }));

    const errs = (st.errors || []).slice(-3);
    const p = U().panel(tr("cerebro.title"), { sub: tr("cerebro.sub"), cls: "cb-status" });
    const sit = (cur.plan || {}).situation;
    add(p.body, kpis,
      sit ? el("div", { class: "cb-situation" }, el("div", { class: "cb-cap" }, tr("cerebro.situation")), el("p", {}, sit)) : null,
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
    if (!keys.length) return el("div", { class: "cb-muted" }, tr("cerebro.goals.none"));
    return el("div", { class: "cb-goals" }, keys.map((ref) => {
      const got = held.has(ref.toUpperCase());
      const dropped = num(goals[ref]) === 0;
      return el("div", { class: "cb-goal" + (got ? " is-done" : "") + (dropped ? " is-dropped" : "") },
        U().icon(got ? "check" : "target", 14), el("b", { class: "num" }, ref),
        el("span", { class: "cb-muted" }, dropped ? tr("cerebro.goals.dropped") : tr("cerebro.goals.max", { p: fmtP(goals[ref]) })),
        el("span", { class: "cb-goal-st" }, got ? tr("cerebro.goals.got") : dropped ? "" : tr("cerebro.goals.looking")),
        manual[ref] != null ? el("span", { class: "tag res tone-mute" }, "manual") : null);
    }));
  }

  function planPanel(d) {
    const p = U().panel(tr("cerebro.plan.title"), { sub: d.cur && d.cur.tick != null ? "tick " + d.cur.tick : "" });
    const plan = (d.cur && d.cur.plan) || null;
    if (!plan) { add(p.body, U().empty(tr("cerebro.plan.none"))); return p; }
    const pri = (plan.priorities || []);
    const cp = plan.cash_policy || {};
    add(p.body, 
      el("div", { class: "cb-sec" }, el("div", { class: "cb-cap" }, tr("cerebro.plan.priorities")),
        pri.length ? el("ol", { class: "cb-pri" }, pri.map((x) => el("li", {}, x))) : el("div", { class: "cb-muted" }, tr("cerebro.plan.noPriorities"))),
      el("div", { class: "cb-two" },
        el("div", { class: "cb-sec" }, el("div", { class: "cb-cap" }, tr("cerebro.plan.goals")), goalsBlock(plan, d.control)),
        el("div", { class: "cb-sec" }, el("div", { class: "cb-cap" }, tr("cerebro.plan.cash")),
          el("div", { class: "cb-kv" }, el("span", {}, tr("cerebro.plan.reserve")), el("b", { class: "num" }, cp.reserve != null ? fmtP(cp.reserve) : tr("cerebro.plan.default"))),
          el("div", { class: "cb-kv" }, el("span", {}, tr("cerebro.plan.smallDeal")), el("b", { class: "num" }, cp.max_small_deal != null ? fmtP(cp.max_small_deal) : tr("cerebro.plan.default"))),
          plan.duel_claude_mode ? el("div", { class: "cb-kv" }, el("span", {}, tr("cerebro.plan.duelMode")), el("b", {}, plan.duel_claude_mode)) : null,
          (plan.pause_domains || []).length ? el("div", { class: "cb-kv" }, el("span", {}, tr("cerebro.plan.paused")), el("b", { class: "cb-bad" }, plan.pause_domains.join(", "))) : null)),
      el("div", { class: "cb-sec" }, el("div", { class: "cb-cap" }, tr("cerebro.plan.guidance")),
        el("div", { class: "cb-guid" }, DOMAINS.map(([k, label, ic]) => el("div", { class: "cb-guid-item" },
          el("div", { class: "cb-guid-h" }, U().icon(ic, 14), tr(label)),
          el("p", {}, (plan.guidance || {})[k] || el("span", { class: "cb-muted" }, tr("cerebro.plan.noGuidance"))))))),
      (plan.risks || []).length ? el("div", { class: "cb-sec" }, el("div", { class: "cb-cap" }, tr("cerebro.plan.risks")),
        el("ul", { class: "cb-risks" }, plan.risks.map((x) => el("li", {}, U().icon("alert", 13), el("span", {}, x))))) : null,
      (plan.cancel_offers || []).length ? el("div", { class: "cb-sec" }, el("div", { class: "cb-cap" }, tr("cerebro.plan.cancels")),
        el("div", { class: "cb-muted num" }, plan.cancel_offers.map((x) => "#" + x).join(" · "))) : null);
    return p;
  }

  // events: strings from the brain's detector, e.g. "offer #4310 addressed to us by abuela",
  // "level X: state a -> b", "schedule added: ...", "t06 score 11.1 -> 15.1",
  // "novelty <kind>: <untrusted source='game'>{json}</untrusted>". Parsed into {kind, text}.
  const EV_KIND = {
    offer: ["cerebro.evk.offer", "anuncio", "var(--t-puja)"], level: ["cerebro.evk.level", "trend", "var(--t-compra)"],
    schedule: ["cerebro.evk.schedule", "bell", "var(--t-cambio)"], score: ["cerebro.evk.score", "competicion", "var(--t-duelo)"],
    dealer: ["cerebro.evk.dealer", "dealer", "var(--t-dealer)"], venue: ["cerebro.evk.venue", "mercado", "var(--t-dealer)"],
    news: ["cerebro.evk.news", "anuncio", "var(--t-anuncio)"], other: ["cerebro.evk.other", "bell", "var(--t-anuncio)"],
  };
  const ACTION_KEY = { day_closes: "cerebro.action.day_closes", day_opens: "cerebro.action.day_opens", bench: "cerebro.action.bench", duels: "cerebro.action.duels", round: "cerebro.action.round" };
  const actionName = (a) => (ACTION_KEY[a] ? tr(ACTION_KEY[a]) : a);
  function parseEvent(raw) {
    let t = typeof raw === "string" ? raw : (raw && (raw.text || raw.event)) || JSON.stringify(raw);
    const m = t.match(/^novelty ([\w.]+):\s*<untrusted[^>]*>([\s\S]*?)(<\/untrusted>|$)/);
    if (m) {
      const kind = m[1];
      let j = null; try { j = JSON.parse(m[2]); } catch (e) { j = null; }
      if (kind === "schedule" && j) {
        const when = j.at_hours != null ? "h" + fmtNum(j.at_hours, 2) : "";
        return { kind: "schedule", text: tr("cerebro.ev.schedule", { action: actionName(j.action), when }) + (j.note ? " · " + j.note : "") };
      }
      if (j && j.type) {
        const ex = j.example || {}; const p = ex.payload || {};
        const head = p.headline || p.title || p.text || "";
        const k = /news/.test(j.type) ? "news" : /persona|dealer/.test(j.type) ? "dealer" : /venue/.test(j.type) ? "venue" : "other";
        return { kind: k, text: (ex.actor ? tr("cerebro.ev.newTypeBy", { type: j.type, actor: ex.actor }) : tr("cerebro.ev.newType", { type: j.type })) + (head ? ": " + head : "") };
      }
      return { kind: /persona|dealer/.test(kind) ? "dealer" : /venue/.test(kind) ? "venue" : "other", text: tr("cerebro.ev.novelty", { kind }) + (j ? "" : ": " + m[2].slice(0, 160)) };
    }
    if (/^offer /.test(t)) return { kind: "offer", text: t.replace(/^offer #(\d+) addressed to us by (\S+)/, tr("cerebro.ev.offerToUs", { id: "$1", by: "$2" })) };
    if (/^level /.test(t)) return { kind: /persona|dealer|chato|abuela|pilar/i.test(t) ? "dealer" : "level", text: t.replace(/^level /, tr("cerebro.ev.level") + " ").replace("state", tr("cerebro.ev.state")) };
    if (/^schedule (added|removed)/.test(t)) {
      const added = /added/.test(t);
      const items = t.replace(/^schedule [^:]*:\s*/, "").split(/,\s*/).map((x) => { const [h, a] = x.split("|"); return (actionName(a) || "?") + " h" + h; });
      return { kind: "schedule", text: tr(added ? "cerebro.ev.schedAdds" : "cerebro.ev.schedRemoves", { items: items.join(", ") }) };
    }
    const sc = t.match(/^(t\d+) score ([\d.]+) -> ([\d.]+)/);
    if (sc) return { kind: "score", text: tr("cerebro.ev.score", { team: U().teamName ? U().teamName(sc[1]) : sc[1], from: fmtNum(+sc[2], 1), to: fmtNum(+sc[3], 1), delta: (+sc[3] >= +sc[2] ? "+" : "") + fmtNum(+sc[3] - +sc[2], 1) }) };
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
    const [lk, ic, color] = EV_KIND[kind] || EV_KIND.other; const label = tr(lk);
    const c = el("span", { class: "chip type cb-chip" }, U().icon(ic, 13), el("span", { class: "chip-label" }, label));
    c.style.setProperty("--tc", color);
    return c;
  }
  function eventsPanel(d) {
    const rows = [];
    for (const doc of d.history) (doc.events || []).forEach((e, i) => { const pe = parseEvent(e); rows.push({ ts: doc.updated, tick: doc.tick, i, ...pe, doc }); });
    rows.sort((a, b) => (b.ts || 0) - (a.ts || 0) || a.i - b.i);
    const p = U().panel(tr("cerebro.events.title"), { sub: rows.length ? tr("cerebro.events.n", { n: rows.length }) : "" });
    if (!rows.length) { add(p.body, U().empty(tr("cerebro.events.empty"))); return p; }
    const host = el("div", { class: "cb-list cb-events" });
    U().keyedList(host, rows.slice(0, 80), {
      key: (r) => (r.ts || 0) + "|" + r.i, sig: () => "",
      render: (r) => {
        const n = el("div", { class: "cb-ev" },
          el("div", { class: "cb-ev-h" }, el("span", { class: "num cb-time" }, when(r.ts)), evChip(r.kind),
            el("span", { class: "num cb-muted" }, r.tick != null ? "tick " + r.tick : ""), el("span", { class: "cb-sp" }), statusChip(planStatus(r.doc))),
          el("div", { class: "cb-rowt", title: r.text }, short(r.text, 240)),
          evConcl(r) ? el("div", { class: "cb-rows" }, tr("cerebro.events.concl", { text: short(evConcl(r), 240) })) : null);
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
    const p = U().panel(tr("cerebro.find.title"), { sub: all.length ? tr("cerebro.find.n", { n: all.length }) : "" });
    const tkey = topics.join(",");
    if (!S.fb || S.fbKey !== tkey) {
      const prev = S.fbState;
      S.fbKey = tkey;
      S.fb = U().filterBar({ types: topics, counts, search: true, placeholder: tr("cerebro.find.search"),
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
      && (!q || `${r.finding || ""} ${evText(r.evidence)} ${r.fix || ""}`.toLowerCase().includes(q)));
    if (!rows.length) { U().keyedList(host, [], { key: () => "", render: () => el("div"), tail: [U().empty(S.findAll && S.findAll.length ? tr("cerebro.find.noMatch") : tr("cerebro.find.empty"))] }); return; }
    U().keyedList(host, rows.slice(0, 150), {
      key: (r) => (r.ts || 0) + "|" + (r.topic || "") + "|" + (r.finding || "").slice(0, 40), sig: () => "",
      render: (r) => U().row({ cls: "cb-t-" + (TOPICS[r.topic] ? r.topic : "general"), cols: "86px 150px minmax(0,1fr) auto auto", cells: [
        { v: el("span", { class: "num" }, when(r.ts)), cls: "cb-time" },
        topicChip(r.topic),
        { v: el("div", {}, el("div", { class: "cb-rowt" }, r.finding || ""),
          evText(r.evidence) ? el("div", { class: "cb-rows" }, tr("cerebro.find.evidence", { text: evText(r.evidence) })) : null,
          r.fix ? el("div", { class: "cb-rows" }, tr("cerebro.find.fix", { text: r.fix })) : null), cls: "wrap" },
        r.doc ? planSource(r.doc) : U().sourceTag("opus"),
        statusChip(r.status || (r.doc ? planStatus(r.doc) : "visto"))] }),
    });
  }

  function councilPanel(d) {
    const votes = d.history.filter((h) => h.council && Array.isArray(h.council.votes)).slice().reverse();
    const p = U().panel(tr("cerebro.council.title"), { sub: votes.length ? tr("cerebro.council.n", { n: votes.length }) : "" });
    if (!votes.length) { add(p.body, U().empty(tr("cerebro.council.empty"))); return p; }
    const host = el("div", { class: "cb-list" });
    U().keyedList(host, votes.slice(0, 30), {
      key: (h) => String(h.updated), sig: () => "",
      render: (h) => {
        const c = h.council;
        const box = el("div", { class: "cb-vote " + (c.ok ? "is-ok" : "is-bad") },
          el("div", { class: "cb-vote-h" }, el("span", { class: "num" }, when(h.updated)), el("span", { class: "num cb-muted" }, "tick " + (h.tick ?? "?")),
            U().sourceTag("consejo", `${c.yes ?? 0}/${(c.votes || []).length}`), statusChip(c.ok ? "consejo" : "rechazado")),
          el("div", { class: "cb-rows" }, tr("cerebro.council.changes", { text: (h.big_changes || []).join(" · ") || "—" })),
          (c.votes || []).map((v) => el("div", { class: "cb-voter" },
            el("span", { class: "tag res tone-" + (v.verdict === "reject" ? "bad" : "ok") }, v.verdict === "reject" ? tr("cerebro.council.against") : tr("cerebro.council.for")),
            el("b", {}, roleName(v.role)), el("span", {}, v.reason || ""))));
        return box;
      },
    });
    add(p.body, host);
    return p;
  }
  const ROLE = { auditor: "cerebro.role.auditor", negotiator: "cerebro.role.negotiator", analyst: "cerebro.role.analyst", judge: "cerebro.role.judge" };
  const roleName = (r) => (ROLE[r] ? tr(ROLE[r]) : r || "—");

  // history: each plan with what changed against the previous one
  function diffPlans(a, b) {
    const pa = (a && a.plan) || {}, pb = (b && b.plan) || {};
    const out = [];
    const ga = pa.goal_buys || {}, gb = pb.goal_buys || {};
    for (const k of new Set([...Object.keys(ga), ...Object.keys(gb)])) {
      if (!(k in ga)) out.push(["add", tr("cerebro.diff.goalAdd", { ref: k, max: fmtP(gb[k]) })]);
      else if (!(k in gb)) out.push(["del", tr("cerebro.diff.goalDel", { ref: k })]);
      else if (num(ga[k]) !== num(gb[k])) out.push(["chg", tr("cerebro.diff.goalChg", { ref: k, from: fmtP(ga[k]), to: fmtP(gb[k]) })]);
    }
    const ca = pa.cash_policy || {}, cb = pb.cash_policy || {};
    for (const k of ["reserve", "max_small_deal"]) if (num(ca[k]) !== num(cb[k])) out.push(["chg", tr(k === "reserve" ? "cerebro.diff.reserve" : "cerebro.diff.smallDeal", { from: ca[k] != null ? fmtP(ca[k]) : "—", to: cb[k] != null ? fmtP(cb[k]) : "—" })]);
    if ((pa.duel_claude_mode || "") !== (pb.duel_claude_mode || "") && pb.duel_claude_mode) out.push(["chg", tr("cerebro.diff.duels", { from: pa.duel_claude_mode || "—", to: pb.duel_claude_mode })]);
    const pda = (pa.pause_domains || []).join(","), pdb = (pb.pause_domains || []).join(",");
    if (pda !== pdb) out.push(["chg", tr("cerebro.diff.pause", { from: pda || tr("cerebro.diff.none"), to: pdb || tr("cerebro.diff.none") })]);
    const ta = (pa.priorities || [])[0], tb = (pb.priorities || [])[0];
    if (tb && ta !== tb) out.push(["pri", tr("cerebro.diff.newPri", { text: tb })]);
    return out;
  }
  function historyPanel(d) {
    const h = d.history;
    const p = U().panel(tr("cerebro.hist.title"), { sub: h.length ? tr("cerebro.hist.n", { n: h.length }) : "" });
    if (!h.length) { add(p.body, U().empty(tr("cerebro.hist.empty"))); return p; }
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
            : el("div", { class: "cb-muted" }, tr("cerebro.hist.noDiff"))),
          open ? el("div", { class: "cb-tl-body" },
            plan.situation ? el("p", {}, plan.situation) : null,
            el("ol", { class: "cb-pri" }, (plan.priorities || []).map((t) => el("li", {}, t))),
            x.doc.proposed ? el("div", { class: "cb-rows cb-bad" }, tr("cerebro.hist.rejected", { text: (x.doc.big_changes || []).join(" · ") || "—" })) : null) : null);
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
        const p = U().panel(tr("cerebro.plan.title"));
        add(p.body, U().empty(d.err.status === 404
          ? tr("cerebro.plan.none") : tr("cerebro.plan.readFail", { err: d.err.message || d.err })));
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

  // The chat opens on its latest messages: after entering the screen (or a reload) scroll to the bottom once the
  // messages are laid out; later renders keep the usual rule (follow only when already at the bottom).
  function stickEnd() {
    const go = () => {
      const list = C.list;
      if (!list || !list.isConnected || !C.needEnd) return;
      if (!C.msgs.length && C.state !== "on") return;      // still loading: try again on the next render
      list.scrollTop = list.scrollHeight;
    };
    const done = () => { go(); if (C.list && C.list.isConnected && (C.msgs.length || C.state === "on")) C.needEnd = false; };
    requestAnimationFrame(() => { go(); requestAnimationFrame(go); });
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(go);
    setTimeout(done, 350);
  }
  function chatMount() {
    C.needEnd = true;
    const list = el("div", { class: "cb-chat-list" });
    const input = el("textarea", { class: "cb-chat-in", rows: 2, placeholder: tr("cerebro.chat.ph") });
    const send = el("button", { type: "button", class: "cb-chat-send" }, U().icon("arrow", 14), tr("cerebro.chat.send"));
    // Enter sends, Shift+Enter is a new line; Enter that confirms an IME composition never sends
    input.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" || e.shiftKey || e.isComposing || e.keyCode === 229) return;
      e.preventDefault(); e.stopPropagation(); chatSend();
    });
    send.addEventListener("click", (e) => { e.preventDefault(); chatSend(); });
    const nameBox = el("div", { class: "cb-chat-name" });
    const host = el("aside", { class: "cb-chat" },
      el("header", { class: "cb-chat-h" }, U().icon("cerebro", 15), el("b", {}, tr("cerebro.chat.title")), el("span", { class: "cb-chat-st" })),
      list, nameBox, el("div", { class: "cb-chat-f" }, input, send));
    C.host = host; C.list = list; C.input = input; C.nameBox = nameBox; C.send = send;
    renderName(); renderChat();
    return host;
  }
  function renderName() {
    const box = C.nameBox; if (!box) return;
    const n = getName();
    if (n) { box.replaceChildren(el("span", { class: "cb-muted" }, tr("cerebro.chat.as") + " "), el("b", {}, n), " ",
      el("button", { type: "button", class: "cb-link", onclick: () => { setName(""); renderName(); } }, tr("cerebro.chat.change"))); return; }
    const inp = el("input", { class: "cb-q", placeholder: tr("cerebro.chat.namePh") });
    const ok = () => { setName(inp.value.trim() || "equipo"); renderName(); };
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") ok(); });
    box.replaceChildren(inp, el("button", { type: "button", class: "cb-seg", onclick: ok }, tr("cerebro.save")));
  }
  function renderChat() {
    const list = C.list; if (!list) return;
    const st = C.host.querySelector(".cb-chat-st");
    const since = thinkingSince();
    C.waiting = since != null;
    if (st) st.textContent = C.state === "off" ? tr("cerebro.chat.inactive") : since != null ? tr("cerebro.chat.thinking") : "";
    const atEnd = list.scrollHeight - list.scrollTop - list.clientHeight < 12;
    const kids = [];
    if (C.state === "off") kids.push(U().empty(tr("cerebro.chat.off")));
    else if (C.state === "error") kids.push(U().error(C.err));
    else if (!C.msgs.length && C.state === "idle") kids.push(U().loading());
    else if (!C.msgs.length) kids.push(U().empty(tr("cerebro.chat.empty")));
    const shown = [];
    for (const m of C.msgs) {
      // the same role + author + text within 15 s is one message (a double send or a local copy plus the server copy)
      const dup = shown.find((p) => p.role === m.role && (p.by || "") === (m.by || "") && p.text === m.text && Math.abs((+p.ts || 0) - (+m.ts || 0)) <= 15);
      if (dup) { if (dup.pending && !m.pending) dup.pending = false; continue; }
      shown.push(m);
      const me = m.role !== "brain";
      kids.push(el("div", { class: "cb-msg " + (me ? "is-user" : "is-brain") + (m.pending ? " is-pending" : "") },
        el("div", { class: "cb-msg-h" }, el("b", {}, me ? (m.by || "equipo") : tr("cerebro.chat.brain")), el("span", { class: "num" }, m.ts ? when(m.ts) : "")),
        el("div", { class: "cb-msg-t" }, m.text || ""),
        Array.isArray(m.refs) && m.refs.length ? el("div", { class: "cb-msg-refs num" }, m.refs.map((x) => typeof x === "string" ? x : (x.id || x.ref || JSON.stringify(x))).join(" · ")) : null));
    }
    C.thinkEl = null;
    if (since != null) {
      C.thinkEl = el("div", { class: "cb-msg is-brain is-thinking" },
        el("div", { class: "cb-think-h" }, U().icon("cerebro", 13), el("span", {}, tr("cerebro.think.title") + " "), el("span", { class: "num cb-think-since" }, tr("cerebro.think.since", { time: when(since) }))),
        el("div", { class: "cb-think-sub" }));
      kids.push(C.thinkEl);
      updateThinking();
    }
    U().keepScroll(list.parentNode, () => list.replaceChildren(...kids));
    if (atEnd || C.forceEnd) { list.scrollTop = list.scrollHeight; C.forceEnd = false; }
    if (C.needEnd) stickEnd();
  }
  // Thinking = the last message is ours (anyone's, also after a reload) and no brain reply came after it.
  function thinkingSince() {
    if (C.state === "off" || C.state === "error") return null;
    let lastUser = null, lastBrain = 0;
    for (const m of C.msgs) {
      const ts = +m.ts || 0;
      if (m.role === "brain") lastBrain = Math.max(lastBrain, ts);
      else if (lastUser == null || ts > lastUser) lastUser = ts;
    }
    return lastUser != null && lastUser > lastBrain ? lastUser : null;
  }
  // brain status from its heartbeat (GET strategy -> status {updated, last_call, last_reason}): working now or queued
  function updateThinking() {
    const n = C.thinkEl; if (!n) return;
    const since = thinkingSince(); if (since == null) return;
    const now = Date.now() / 1000, st = C.brainSt || {};
    const age = now - since;
    const beat = +st.updated || 0, beatAge = beat ? now - beat : null;
    // the brain writes its heartbeat every ~5 s between runs and not during an Opus call, so a heartbeat that is
    // 12 s-5 min old means it is planning right now; an explicit thinking_since (if the backend adds it) wins
    const busySince = +st.thinking_since || +st.planning_since || 0;
    let sub;
    if (busySince) sub = ["ok", tr("cerebro.think.now", { time: when(busySince) })];
    else if (beatAge == null) sub = ["mute", tr("cerebro.think.waiting")];
    else if (beatAge > 300) sub = ["bad", tr("cerebro.think.dead", { time: when(beat) })];
    else if (beatAge > 12 && beat < since - 1) sub = ["mute", tr("cerebro.think.finishing", { time: when(beat) })];
    else if (beatAge > 12) sub = ["ok", tr("cerebro.think.now", { time: when(beat) })];
    else sub = ["mute", tr("cerebro.think.queued")];
    const slow = age > 180;
    const box = n.querySelector(".cb-think-sub");
    const kids = [el("span", { class: "cb-think-" + sub[0] }, sub[1]), " · ", el("span", { class: "num" }, U().fmtDur(age))];
    if (slow) kids.push(el("span", { class: "cb-think-slow" }, " · " + tr("cerebro.think.slow")));
    box.replaceChildren(...kids);
  }
  async function brainStatus() {
    if (C.stBusy || Date.now() - (C.stAt || 0) < 3000) return;
    C.stBusy = true; C.stAt = Date.now();
    try { const r = await A().strategy(1); C.brainSt = (r && r.status) || null; } catch (e) { /* optional */ }
    finally { C.stBusy = false; updateThinking(); }
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
          if (m.role !== "brain") { const i = C.msgs.findIndex((x) => x.local && x.text === m.text); if (i >= 0) C.msgs.splice(i, 1); }
          C.msgs.push(m);

        }
        C.msgs.sort((a, b) => (a.ts || 0) - (b.ts || 0));
        C.since = Math.max(C.since || 0, ...got.map((m) => +m.ts || 0));
        if (added) renderChat();
      } else if (C.state !== C.lastState) renderChat();
      if (C.needEnd) stickEnd();
    } catch (e) {
      C.state = e && e.status === 404 ? "off" : "error"; C.err = e;
      renderChat();
    } finally { C.lastState = C.state; C.busy = false; }
  }
  // One POST per message: in-flight guard, inputs disabled while sending, the same text is not sent twice within
  // 3 s, the box is cleared only after the server accepted it, and a failed POST is never retried by itself.
  async function chatSend() {
    const text = (C.input.value || "").trim();
    if (!text || C.sending) return;
    if (C.state === "off") { renderChat(); return; }
    const now = Date.now();
    if (C.lastSent && C.lastSent.text === text && now - C.lastSent.at < 3000) return;
    const by = getName() || "equipo";
    C.sending = true; C.lastSent = { text, at: now };
    C.send.disabled = true; C.input.disabled = true;
    const mine = { ts: now / 1000, role: "user", by, text, pending: true, local: true };
    C.msgs.push(mine); C.forceEnd = true;
    renderChat();
    try {
      await A().brainSay(text, by);
      mine.pending = false;
      if ((C.input.value || "").trim() === text) C.input.value = "";
    } catch (e) {
      C.lastSent = null;
      const i = C.msgs.indexOf(mine); if (i >= 0) C.msgs.splice(i, 1);
      U().toast({ type: "error", title: tr("cerebro.sendFail"), text: e && e.status === 404 ? tr("cerebro.chat.off") : (e && e.message) || "Error" });
    } finally {
      C.sending = false; C.send.disabled = false; C.input.disabled = false; C.input.focus();
      renderChat(); chatPull();
    }
  }
  // poll faster than the 2 s screen refresh while waiting for a reply
  setInterval(() => {
    if (!(C.list && C.list.isConnected) || thinkingSince() == null) return;
    chatPull(); brainStatus(); updateThinking();
  }, 1500);


  // ---------- "Para el equipo": what the brain decided but people must do (outbox) ----------
  // GET outbox -> {items:[...]} with kind code | promo | task; POST outbox/<id> {status, note}
  const O = { items: [], state: "idle", err: null, tab: "code", open: new Set(), host: null, busy: false, at: 0, sig: "" };
  const OB_TABS = [["code", "cerebro.ob.tab.code", "bot"], ["task", "cerebro.ob.tab.task", "check"]];   // messages have their own section
  const SEV = { critical: ["cerebro.sev.critical", "var(--bad)", "alert"], high: ["cerebro.sev.high", "var(--t-venta)", "alert"], medium: ["cerebro.sev.medium", "var(--t-puja)", "alert"],
    low: ["cerebro.sev.low", "var(--t-anuncio)", "alert"] };
  const OB_STATUS = { open: ["cerebro.obst.open", "warn"], accepted: ["cerebro.obst.accepted", "ok"], done: ["cerebro.obst.done", "ok"], rejected: ["cerebro.obst.rejected", "bad"],
    draft: ["cerebro.obst.draft", "warn"], sent: ["cerebro.obst.sent", "ok"], discarded: ["cerebro.obst.discarded", "mute"] };
  const isOpen = (x) => x.status === "open" || x.status === "draft" || x.status === "accepted";
  const kindOf = (x) => x.kind || (x.channel ? "promo" : x.task ? "task" : "code");
  function obChip(label, color, ic) { const c = el("span", { class: "chip type cb-chip" }, U().icon(ic, 13), el("span", { class: "chip-label" }, label)); c.style.setProperty("--tc", color); return c; }
  function obStatus(st) { const [l, t] = OB_STATUS[st] || [null, "mute"]; return el("span", { class: "tag res tone-" + t }, l ? tr(l) : st || "—"); }

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
    } catch (e) { U().toast({ type: "error", title: tr("cerebro.saveFail"), text: (e && e.message) || "Error" }); }
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
      return [obChip(tr(l), c, ic), el("div", { class: "cb-ob-title" }, x.title || tr("cerebro.ob.codeChange")),
        x.occurrences > 1 ? el("span", { class: "tag res tone-" + (x.recurred ? "bad" : "mute") }, (x.recurred ? tr("cerebro.ob.recurs") + " · " : "") + "×" + x.occurrences) : null];
    }
    if (x.kind === "promo") return [obChip(x.channel === "whatsapp" ? "WhatsApp" : tr("cerebro.inGame"), x.channel === "whatsapp" ? "var(--t-compra)" : "var(--t-cambio)", "anuncio"),
      el("div", { class: "cb-ob-title" }, short(x.text, 140))];
    return [obChip(tr("cerebro.ob.task"), "var(--t-dealer)", "check"), el("div", { class: "cb-ob-title" }, x.task || tr("cerebro.ob.task")),
      x.occurrences > 1 ? el("span", { class: "tag res tone-mute" }, "×" + x.occurrences) : null];
  }
  function obDetail(x) {
    const ev = Array.isArray(x.evidence) ? x.evidence : x.evidence ? [x.evidence] : [];
    const sec = (cap, body) => body ? el("div", { class: "cb-ob-sec" }, el("div", { class: "cb-cap" }, cap), body) : null;
    const txt = (t) => t ? el("p", {}, t) : null;
    const note = el("input", { class: "cb-q cb-ob-note", placeholder: tr("cerebro.ob.notePh"), value: "" });
    const btn = (label, status, tone) => el("button", { type: "button", class: "cb-ob-btn tone-" + tone, onclick: (e) => { e.stopPropagation(); obSet(x, status, note.value.trim()); } }, label);
    let actions;
    if (x.kind === "promo") {
      const cp = el("button", { type: "button", class: "cb-ob-btn", onclick: async (e) => { e.stopPropagation(); const ok = await copyText(x.text || ""); cp.textContent = ok ? tr("cerebro.copied") : tr("cerebro.copyFail"); setTimeout(() => { cp.textContent = tr("cerebro.ob.copyText"); }, 1500); } }, tr("cerebro.ob.copyText"));
      actions = [cp, btn(tr("cerebro.markSent"), "sent", "ok"), btn(tr("cerebro.discard"), "discarded", "bad")];
    } else if (x.kind === "code") actions = [btn(tr("cerebro.ob.accept"), "accepted", "warn"), btn(tr("cerebro.obst.done"), "done", "ok"), btn(tr("cerebro.ob.reject"), "rejected", "bad")];
    else actions = [btn(tr("cerebro.obst.done"), "done", "ok"), btn(tr("cerebro.ob.reject"), "rejected", "bad")];
    return el("div", { class: "cb-ob-detail", onclick: (e) => e.stopPropagation() },
      x.kind === "promo" ? sec(tr("cerebro.ob.text"), el("pre", { class: "cb-ob-text" }, x.text || "")) : null,
      sec(tr("cerebro.ob.why"), txt(x.why)),
      sec(tr("cerebro.ob.diagnosis"), txt(x.diagnosis)),
      sec(tr("cerebro.ob.evidence"), ev.length ? el("ul", { class: "cb-ob-ev" }, ev.map((e) => el("li", {}, typeof e === "string" ? e : JSON.stringify(e)))) : null),
      sec(tr("cerebro.ob.proposed"), txt(x.proposed_change)),
      sec(tr("cerebro.ob.patch"), x.patch_sketch ? el("pre", { class: "cb-ob-code" }, x.patch_sketch) : null),
      sec(tr("cerebro.ob.impact"), txt(x.impact)),
      x.human_note ? sec(tr("cerebro.ob.teamNote"), txt(x.human_note)) : null,
      el("div", { class: "cb-ob-actions" }, note, actions));
  }
  function obRender() {
    const host = O.host; if (!host) return;
    const inTab = (x, k) => x.kind === k;
    const counts = {}; for (const [k] of OB_TABS) counts[k] = O.items.filter((x) => inTab(x, k) && isOpen(x)).length;
    const sig = JSON.stringify([O.state, O.tab, [...O.open], O.items.map((x) => [x.id, x.status, x.updated, x.occurrences])]);
    if (sig === O.sig) return; O.sig = sig;
    const totalOpen = Object.values(counts).reduce((a, b) => a + b, 0);
    const tabs = el("div", { class: "cb-ob-tabs" }, OB_TABS.map(([k, label, ic]) => el("button", { type: "button", class: "cb-ob-tab" + (O.tab === k ? " on" : ""),
      onclick: () => { O.tab = k; obRender(); } }, U().icon(ic, 14), tr(label), el("span", { class: "num cb-ob-n" + (counts[k] ? " has" : "") }, String(counts[k])))));
    const head = el("header", { class: "panel-head" }, el("h2", { class: "panel-title" }, tr("cerebro.ob.title")),
      el("span", { class: "panel-sub" }, O.state === "on" ? (totalOpen ? tr("cerebro.ob.sub", { n: totalOpen }) : tr("cerebro.ob.nothing")) : ""));
    const list = el("div", { class: "cb-list cb-ob-list" });
    let body;
    if (O.state === "idle") body = U().loading();
    else if (O.state === "off") body = U().empty(tr("cerebro.ob.off"));
    else if (O.state === "error") body = U().error(O.err);
    else {
      const rows = O.items.filter((x) => inTab(x, O.tab))
        .sort((a, b) => (isOpen(b) - isOpen(a)) || ((+b.updated || +b.ts || 0) - (+a.updated || +a.ts || 0)));
      if (!rows.length) body = U().empty(O.tab === "code" ? tr("cerebro.ob.noCode") : tr("cerebro.ob.noTasks"));
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


  // ---------- Mensajes: what to send (drafts) and what other teams said (pasted WhatsApp) ----------
  // drafts = outbox items kind promo (channel whatsapp | in_game); replies carry reply_to {external_id, author, team}
  // received = POST/GET brain/external records {id, ts, received_at, by, author, team, text, types, entities, actionable, brain_conclusion, reply_outbox_id}
  const X = { items: [], state: "idle", err: null, host: null, busy: false, at: 0, sig: "", sending: false, hist: { sent: false, discarded: false } };
  const XT = { request: ["cerebro.xt.request", "puja", "var(--t-puja)"], offer: ["cerebro.xt.offer", "venta", "var(--t-compra)"], tip: ["cerebro.xt.tip", "target", "var(--t-cambio)"],
    complaint: ["cerebro.xt.complaint", "alert", "var(--t-venta)"], promo: ["cerebro.xt.promo", "anuncio", "var(--t-anuncio)"], news: ["cerebro.xt.news", "bell", "var(--t-dealer)"],
    offer_ref: ["cerebro.xt.offer", "venta", "var(--t-compra)"], organiser: ["cerebro.org", "bell", "var(--t-dealer)"], alliance: ["cerebro.xt.alliance", "rivales", "var(--t-cambio)"],
    question: ["cerebro.xt.question", "search", "var(--t-puja)"], other: ["cerebro.xt.other", "anuncio", "var(--t-anuncio)"] };
  function xChip(t) { const [l, ic, c] = XT[t] || [null, "anuncio", "var(--t-anuncio)"]; const n = el("span", { class: "chip type cb-chip" }, U().icon(ic, 13), el("span", { class: "chip-label" }, l ? tr(l) : t)); n.style.setProperty("--tc", c); return n; }
  const replyKey = (o) => (o && o.reply_to ? (o.reply_to.external_id ?? o.reply_to.record ?? null) : null);
  const isReply = (o) => !!(o && o.kind === "promo" && o.reply_to);
  const promos = () => O.items.filter((o) => o.kind === "promo");
  function replyFor(x) {
    if (!x) return null;
    if (x.reply_outbox_id != null) { const o = O.items.find((y) => String(y.id) === String(x.reply_outbox_id)); if (o) return o; }
    return O.items.find((o) => isReply(o) && (String(replyKey(o)) === String(x.id) || extById(replyKey(o)) === x)) || null;
  }
  // reply_to.record is normally the message id; sometimes the brain writes its time ("11:06") or "11:02 Team 5"
  const extById = (id) => {
    if (id == null) return null;
    const hit = X.items.find((x) => String(x.id) === String(id));
    if (hit) return hit;
    const m = String(id).match(/^(\d{1,2}):(\d{2})/);
    if (!m) return null;
    const hm = m[1].padStart(2, "0") + ":" + m[2];
    const team = teamFromText(id);
    return X.items.find((x) => when(+x.received_at || +x.ts).startsWith(hm) && (!team || x.team === team)) || null;
  };
  const tTeam = (id) => (id ? U().teamTag(id, { us: id === "t10" }) : null);
  const TEAM_KEY = "bazaar.dash.waTeam";
  // prominent "who" line on top of every message card: team tag (us white) + person
  function whoLine(team, person, prefix) {
    const tag = team === "org" ? el("span", { class: "tag team cb-org" }, U().icon("bell", 12), tr("cerebro.org"))
      : team ? tTeam(team) : el("span", { class: "tag team cb-unk" }, tr("cerebro.x.unknownTeam"));
    return el("div", { class: "cb-who" }, prefix ? el("span", { class: "cb-who-pre" }, prefix) : null, tag,
      person ? el("span", { class: "cb-who-person" }, person) : null);
  }
  const teamFromText = (t) => { const m = String(t || "").match(/team\s*(\d{1,2})/i); return m ? "t" + m[1].padStart(2, "0") : null; };

  function externalMount() {
    const ta = el("textarea", { class: "cb-chat-in cb-x-in", rows: 3, placeholder: tr("cerebro.x.pastePh") });
    // who sent the pasted messages: required choice, remembered for the next paste
    const sel = el("select", { class: "fb-select cb-x-team", "aria-label": tr("cerebro.x.teamAria"), required: "required" },
      el("option", { value: "", disabled: "disabled" }, tr("cerebro.x.choose")));
    for (let i = 1; i <= 18; i++) { const id = "t" + String(i).padStart(2, "0"); sel.append(el("option", { value: id }, (U().teamName ? U().teamName(id) : id) + (id === "t10" ? " · " + tr("cerebro.x.us") : ""))); }
    sel.append(el("option", { value: "org" }, tr("cerebro.org")), el("option", { value: "auto" }, tr("cerebro.x.auto")));
    let saved = ""; try { saved = localStorage.getItem(TEAM_KEY) || ""; } catch (e) { saved = ""; }
    sel.value = saved; if (sel.value !== saved) sel.value = "";
    const markSel = () => sel.classList.toggle("is-empty", !sel.value);
    sel.addEventListener("change", () => { try { localStorage.setItem(TEAM_KEY, sel.value); } catch (e) { /* private mode */ } markSel(); });
    markSel();
    const send = el("button", { type: "button", class: "cb-chat-send" }, U().icon("arrow", 14), tr("cerebro.x.send"));
    const go = async () => {
      const text = ta.value.trim(); if (!text || X.sending) return;
      if (!sel.value) { sel.classList.add("is-missing"); sel.focus(); setTimeout(() => sel.classList.remove("is-missing"), 1500); return; }
      X.sending = true; send.disabled = true;
      try {
        const r = await A().externalAdd(text, getName() || "equipo", sel.value === "auto" ? undefined : sel.value);
        const n = ((r && r.added) || []).length, dup = (r && r.duplicates) || 0;
        U().toast({ type: "dealer", title: tr("cerebro.x.sentToast"), text: tr("cerebro.x.new", { n }) + (dup ? " · " + tr("cerebro.x.dup", { n: dup }) : "") });
        ta.value = ""; X.at = 0; extPull(true);
      } catch (e) {
        U().toast({ type: "error", title: tr("cerebro.sendFail"), text: e && e.status === 404 ? tr("cerebro.x.off") : (e && e.message) || "Error" });
      } finally { X.sending = false; send.disabled = false; }
    };
    send.addEventListener("click", go);
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); go(); } });
    X.head = el("header", { class: "panel-head" });
    X.sendHead = el("div", { class: "cb-m-h" });
    X.toSend = el("div", { class: "cb-m-body" });
    X.recvHead = el("div", { class: "cb-m-h" });
    X.recvList = el("div", { class: "cb-m-body" });
    X.histBox = el("div", { class: "cb-m-hist" });
    // two columns, each scrolls on its own: received (with the paste box) | to send (+ history)
    X.colL = el("div", { class: "cb-m-col" }, X.recvHead,
      el("div", { class: "cb-x-form" }, el("label", { class: "cb-x-who" }, el("span", { class: "cb-cap" }, tr("cerebro.x.sentBy")), sel), ta,
        el("div", { class: "cb-x-side" }, el("span", { class: "cb-muted" }, tr("cerebro.x.shortcut")), send)), X.recvList);
    X.colR = el("div", { class: "cb-m-col" }, X.sendHead, X.toSend, X.histBox);
    const host = el("section", { class: "panel cb-msgs" }, X.head, el("div", { class: "cb-m-cols" }, X.colL, X.colR));
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
    for (const o of en.offer_ids || []) out.push(el("span", { class: "tag res tone-mute num" }, tr("cerebro.x.offerN", { id: o })));
    for (const c of en.cards || []) out.push(el("span", { class: "tag res tone-mute num" }, c));
    for (const v of en.venues || []) out.push(el("span", { class: "tag res tone-mute num" }, v));
    for (const p of en.prices || []) out.push(el("span", { class: "tag res tone-mute num" }, fmtP(p)));
    for (const t of en.ticks || []) out.push(el("span", { class: "tag res tone-mute num" }, "tick " + t));
    return out;
  }
  // "Team 5: …", "Hi Team 5", "¡Gracias, Team 5!", "Hola equipo 5", "@Daniel …" at the start of a draft
  function guessAddressee(text) {
    const t = String(text || "").slice(0, 160);
    const m = t.match(/^[\s¡!¿]*(?:(?:hi|hey|hello|hola|thanks|thank you|gracias|buenas|ok|vale)[\s,!]*)?(?:team|equipo)\s*(\d{1,2})\b/i);
    const team = m ? "t" + m[1].padStart(2, "0") : null;
    const p = t.match(/(?:^|\s)@([A-ZÁÉÍÓÚÑa-záéíóúñ][\wÁÉÍÓÚÑáéíóúñ.-]{1,30}(?:\s[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+)?)/);
    return { team, person: p ? p[1] : null };
  }
  function recipientWho(o) {
    // explicit recipient fields (to_team, to_person, audience) win for replies and proactive drafts alike
    const pre = isReply(o) ? tr("cerebro.x.replyFor") : tr("cerebro.x.for");
    if (o.audience === "team" && o.to_team) return whoLine(o.to_team, o.to_person || null, pre);
    if (o.audience === "person" && (o.to_person || o.to_team)) return whoLine(o.to_team || null, o.to_person || null, pre);
    if (o.audience === "group") return el("div", { class: "cb-who" }, el("span", { class: "cb-who-pre" }, pre),
      el("span", { class: "tag team cb-group" }, U().icon("rivales", 12), o.channel === "in_game" ? tr("cerebro.x.everyoneGame") : tr("cerebro.x.wholeGroup")));
    const rt = o.reply_to || {};
    const ctxRec = extById(replyKey(o));
    if (isReply(o)) {
      const team = rt.team || (ctxRec && ctxRec.team) || teamFromText(rt.record) || teamFromText(ctxRec && ctxRec.text);
      const person = rt.author && rt.author !== "equipo" && rt.author !== (ctxRec && ctxRec.by) ? rt.author : null;
      return whoLine(team, person, tr("cerebro.x.replyFor"));
    }
    // explicit fields first (to_team, to_person, audience), then older to/recipient, then a guess from the text
    const toTeam = o.to_team || (/^t\d+$/.test(o.to || "") ? o.to : null) || (/^t\d+$/.test(o.recipient || "") ? o.recipient : null);
    const toPerson = o.to_person || (o.to && !/^t\d+$/.test(o.to) ? o.to : null) || (o.recipient && !/^t\d+$/.test(o.recipient) ? o.recipient : null);
    if (o.audience !== "group") {
      if (toTeam || toPerson) return whoLine(toTeam, toPerson, tr("cerebro.x.for"));
      const g = guessAddressee(o.text);
      if (g.team || g.person) return whoLine(g.team, g.person, tr("cerebro.x.for"));
    }
    return el("div", { class: "cb-who" }, el("span", { class: "cb-who-pre" }, tr("cerebro.x.for")), el("span", { class: "tag team cb-group" }, U().icon("rivales", 12), o.channel === "in_game" ? tr("cerebro.x.everyoneGame") : tr("cerebro.x.wholeGroup")));
  }
  function recipient(o) {
    const rt = o.reply_to || {};
    const ctxRec = extById(replyKey(o));
    const team = rt.team || (ctxRec && ctxRec.team);
    const author = rt.author && rt.author !== "equipo" && rt.author !== (ctxRec && ctxRec.by) ? rt.author : null;
    if (isReply(o)) return el("span", { class: "cb-m-to" }, el("span", { class: "cb-muted" }, tr("cerebro.x.replyTo")), author ? el("b", {}, author) : null,
      team ? tTeam(team) : (author ? null : el("b", {}, tr("cerebro.x.theirMsg"))),
      el("span", { class: "cb-muted" }, o.channel === "in_game" ? tr("cerebro.x.inGameLc") : tr("cerebro.x.inGroup")));
    const who = o.to || o.recipient;
    if (o.channel === "in_game") return el("span", { class: "cb-m-to" }, el("span", { class: "cb-muted" }, tr("cerebro.x.for")), who ? (/^t\d+$/.test(who) ? tTeam(who) : el("b", {}, who)) : el("b", {}, tr("cerebro.x.everyoneGameLc")));
    return el("span", { class: "cb-m-to" }, el("span", { class: "cb-muted" }, tr("cerebro.x.for")), who ? (/^t\d+$/.test(who) ? tTeam(who) : el("b", {}, who)) : el("b", {}, tr("cerebro.x.theGroup")));
  }
  function channelChip(o) { return o.channel === "in_game" ? obChip(tr("cerebro.inGame"), "var(--t-cambio)", "mercado") : obChip("WhatsApp", "var(--t-compra)", "anuncio"); }
  function sendCard(o, compact) {
    const ctx = isReply(o) ? extById(replyKey(o)) : null;
    const cp = el("button", { type: "button", class: "cb-ob-btn cb-m-copy" }, U().icon("copy", 13), tr("cerebro.copy"));
    cp.addEventListener("click", async () => { const ok = await copyText(o.text || ""); cp.lastChild.textContent = ok ? tr("cerebro.copied") : tr("cerebro.copyFail"); setTimeout(() => { cp.lastChild.textContent = tr("cerebro.copy"); }, 1500); });
    const act = (label, status, tone) => { const b = el("button", { type: "button", class: "cb-ob-btn tone-" + tone }, label); b.addEventListener("click", () => obSet(o, status, "")); return b; };
    const n = el("div", { class: "cb-m-card" + (compact ? " is-compact" : "") },
      recipientWho(o),
      el("div", { class: "cb-ev-h" }, el("span", { class: "num cb-time" }, when(+o.updated || +o.ts)), channelChip(o),
        el("span", { class: "cb-muted" }, o.channel === "in_game" ? tr("cerebro.x.goesGame") : tr("cerebro.x.goesGroup")), el("span", { class: "cb-sp" }), obStatus(o.status)),
      ctx ? el("div", { class: "cb-m-ctx" }, el("div", { class: "cb-cap" }, tr("cerebro.x.theirMsgCap") + " · " + when(+ctx.received_at || +ctx.ts)), el("div", {}, short(ctx.text, 400))) : null,
      el("pre", { class: "cb-m-text" }, o.text || ""),
      o.why && !compact ? el("div", { class: "cb-rows" }, tr("cerebro.x.why", { text: o.why })) : null,
      o.human_note ? el("div", { class: "cb-rows" }, tr("cerebro.x.note", { text: o.human_note })) : null,
      el("div", { class: "cb-ob-actions" }, cp, compact ? null : act(tr("cerebro.markSent"), "sent", "ok"), compact ? null : act(tr("cerebro.discard"), "discarded", "bad")));
    n.style.setProperty("--tc", o.channel === "in_game" ? "var(--t-cambio)" : "var(--t-compra)");
    return n;
  }
  function recvCard(x) {
    const llm = x.llm || {};
    const concl = x.brain_conclusion || llm.conclusion || llm.summary || llm.action || x.action_hint || "";
    const person = x.author && x.author !== x.by && x.author !== "equipo" && x.author !== (U().teamName ? U().teamName(x.team) : x.team) ? x.author : null;
    const r = replyFor(x);
    const n = el("div", { class: "cb-x-item" + (x.actionable ? " is-act" : "") },
      whoLine(x.team || teamFromText(x.text), person, tr("cerebro.x.from")),
      el("div", { class: "cb-ev-h" }, el("span", { class: "num cb-time" }, when(+x.received_at || +x.ts)),
        x.actionable ? el("span", { class: "tag cb-x-act" }, U().icon("bell", 12), tr("cerebro.x.act")) : null,
        (x.types || []).map(xChip), x.about_us ? el("span", { class: "tag res tone-warn" }, tr("cerebro.x.aboutUs")) : null,
        el("span", { class: "cb-sp" }), el("span", { class: "cb-muted" }, tr("cerebro.x.pastedBy", { by: x.by || "equipo" }))),
      el("div", { class: "cb-x-text" }, x.text || ""),
      entityChips(x.entities).length ? el("div", { class: "cb-x-ents" }, entityChips(x.entities)) : null,
      concl ? el("div", { class: "cb-x-concl" }, el("b", {}, (x.actionable ? tr("cerebro.x.todo") : tr("cerebro.x.concl")) + " "), concl) : null,
      r ? el("div", { class: "cb-rows" }, U().icon(r.status === "sent" ? "check" : "arrow", 12),
        " " + (r.status === "sent" ? tr("cerebro.x.replySent") : r.status === "discarded" ? tr("cerebro.x.replyDiscarded") : tr("cerebro.x.replyReady"))) : null);
    n.style.setProperty("--tc", x.actionable ? "var(--warn)" : (XT[(x.types || [])[0]] || [0, 0, "var(--t-anuncio)"])[2]);
    return n;
  }
  function xRender() {
    if (!X.host) return;
    const P = promos();
    const sig = JSON.stringify([X.state, O.state, X.hist, X.items.map((x) => [x.id, x.actionable, x.brain_conclusion, x.reply_outbox_id]),
      P.map((o) => [o.id, o.status, o.updated, o.text])]);
    if (sig === X.sig) return; X.sig = sig;
    const drafts = P.filter((o) => o.status === "draft" || o.status === "open")
      .sort((a, b) => (isReply(b) - isReply(a)) || ((+b.updated || +b.ts || 0) - (+a.updated || +a.ts || 0)));
    const sent = P.filter((o) => o.status === "sent").sort((a, b) => (+b.updated || 0) - (+a.updated || 0));
    const disc = P.filter((o) => o.status === "discarded").sort((a, b) => (+b.updated || 0) - (+a.updated || 0));
    const recv = X.items.slice().sort((a, b) => (!!b.actionable - !!a.actionable) || ((+b.received_at || +b.ts || 0) - (+a.received_at || +a.ts || 0)));
    const keepCols = (fn) => U().keepScroll(X.colL, () => U().keepScroll(X.colR, fn));
    keepCols(() => {
      X.head.replaceChildren(el("h2", { class: "panel-title" }, tr("cerebro.x.title")),
        el("span", { class: "panel-sub" }, tr("cerebro.x.sub", { drafts: drafts.length, recv: recv.length, sent: sent.length })));
      // 1) Por enviar
      const sendList = X.toSend.querySelector(":scope > .cb-m-list") || el("div", { class: "cb-m-list" });
      let sendBody;
      if (O.state === "off") sendBody = U().empty(tr("cerebro.ob.off"));
      else if (O.state === "idle") sendBody = U().loading();
      else if (!drafts.length) sendBody = U().empty(tr("cerebro.x.nothingToSend"));
      else { U().keyedList(sendList, drafts, { key: (o) => String(o.id), sig: (o) => [o.status, o.updated, o.text, isReply(o) && !!extById(replyKey(o))].join("|"), render: (o) => sendCard(o) }); sendBody = sendList; }
      X.sendHead.replaceChildren(U().icon("arrow", 14), el("b", {}, tr("cerebro.x.toSend")),
        el("span", { class: "num cb-ob-n" + (drafts.length ? " has" : "") }, String(drafts.length)),
        el("span", { class: "cb-muted cb-m-hint" }, tr("cerebro.x.sendHint")));
      if (sendBody !== sendList || !sendList.isConnected) X.toSend.replaceChildren(sendBody);
      // 2) Mensajes recibidos
      X.recvHead.replaceChildren(U().icon("anuncio", 14), el("b", {}, tr("cerebro.x.received")), el("span", { class: "num cb-ob-n" }, String(recv.length)),
        el("span", { class: "cb-muted cb-m-hint" }, tr("cerebro.x.recvHint")));
      if (X.state === "idle") X.recvList.replaceChildren(U().loading());
      else if (X.state === "off") X.recvList.replaceChildren(U().empty(tr("cerebro.x.off")));
      else if (X.state === "error") X.recvList.replaceChildren(U().error(X.err));
      else if (!recv.length) X.recvList.replaceChildren(U().empty(tr("cerebro.x.noRecv")));
      else {
        const list = X.recvList.querySelector(".cb-list") || el("div", { class: "cb-list cb-x-list" });
        U().keyedList(list, recv.slice(0, 120), { key: (x) => String(x.id),
          sig: (x) => { const r = replyFor(x); return [x.actionable, x.brain_conclusion, x.llm && JSON.stringify(x.llm).length, r && r.status].join("|"); }, render: recvCard });
        if (!list.isConnected) X.recvList.replaceChildren(list);
      }
      // 3) history, collapsed
      const hist = (key, label, items) => {
        const d = el("details", { class: "cb-m-det" }, el("summary", {}, U().icon("chevron", 13), el("b", {}, label), el("span", { class: "num cb-ob-n" }, String(items.length))),
          items.length ? el("div", { class: "cb-m-list" }, items.slice(0, 60).map((o) => sendCard(o, true))) : el("div", { class: "cb-muted cb-m-pad" }, tr("cerebro.x.noneHist")));
        d.open = X.hist[key];
        d.addEventListener("toggle", () => { X.hist[key] = d.open; });
        return d;
      };
      X.histBox.replaceChildren(hist("sent", tr("cerebro.x.histSent"), sent), hist("discarded", tr("cerebro.x.histDiscarded"), disc));
    });
  }


  // ---------- Intensidad del cerebro (the user asked for this control here, not on Bot) ----------
  // GET brain/budget -> {mode, level, reason, changed, usd_per_hour_now, table:[{level, interval_ticks, usd_per_hour}],
  //   settings:{interval_ticks, wake_kinds, wake_on_score_drop, min_gap_s}, history:[{ts, level, mode, reason}]}
  // POST control {brain_intensity, brain_intensity_mode:"manual"} | {brain_intensity_mode:"auto"}
  const I = { host: null, data: null, state: "idle", err: null, dragging: false, busy: false, at: 0, n: {} };
  const WAKE = { chat: "cerebro.wake.chat", external: "cerebro.wake.external", official: "cerebro.wake.official", bargain: "cerebro.wake.bargain", dealer: "cerebro.wake.dealer", level: "cerebro.wake.level", set: "cerebro.wake.set", schedule: "cerebro.wake.schedule", novelty: "cerebro.wake.novelty", review: "cerebro.wake.review", duel: "cerebro.wake.duel", bench: "cerebro.wake.bench", score: "cerebro.wake.score", offer: "cerebro.wake.offer", venue: "cerebro.wake.venue" };
  // the backend writes level-change reasons as short English phrases joined by ";": shown in the active language, numbers kept
  const REASON_RX = [
    [/^([\d.]+) \$ left for ([\d.]+) h -> ([\d.]+) \$\/h$/i, "cerebro.why.left", (m) => ({ left: es(m[1]), hours: es(m[2]), rate: es(m[3]) })],
    [/^bench within (\d+) min$/i, "cerebro.why.benchIn", (m) => ({ min: m[1] })],
    [/^bench (running|live|now)$/i, "cerebro.why.benchLive"],
    [/^duels? within (\d+) min$/i, "cerebro.why.duelsIn", (m) => ({ min: m[1] })],
    [/^duels? (running|live|now)$/i, "cerebro.why.duelsLive"],
    [/^team message$/i, "cerebro.why.teamMsg"],
    [/^session live$/i, "cerebro.why.session"],
    [/^(external|whatsapp) message$/i, "cerebro.why.waMsg"],
    [/^game paused$/i, "cerebro.why.paused"],
    [/^doors closed$/i, "cerebro.why.closed"],
    [/^behind (the )?pace$/i, "cerebro.why.behind"],
    [/^ahead of (the )?pace$/i, "cerebro.why.ahead"],
    [/^over (the )?pace$/i, "cerebro.why.over"],
    [/^bargain.*$/i, "cerebro.why.bargain"],
    [/^new dealer.*$/i, "cerebro.why.newDealer"],
    [/^score drop.*$/i, "cerebro.why.scoreDrop"],
    [/^quiet.*$/i, "cerebro.why.quiet"],
    [/^cap reached.*$/i, "cerebro.why.cap"],
    [/^manual.*$/i, "cerebro.why.manual"],
    [/^set by the team.*$/i, "cerebro.why.team"],
    [/^keys? .*down.*$/i, "cerebro.why.keys"],
  ];
  const es = (x) => (window.I18N.lang === "en" ? String(x) : String(x).replace(".", ","));
  function reasonEs(text) {
    return String(text || "").split(/\s*;\s*/).filter(Boolean).map((p) => {
      for (const [rx, key, vars] of REASON_RX) { const m = p.match(rx); if (m) return tr(key, vars ? vars(m) : undefined); }
      return p;
    }).join(" · ");
  }
  function levelInfo(level) {
    const t = ((I.data && I.data.table) || []).slice().sort((a, b) => a.level - b.level);
    if (!t.length) return null;
    if (level <= t[0].level) return t[0];
    for (let i = 1; i < t.length; i++) if (level <= t[i].level) {
      const a = t[i - 1], b = t[i], k = (level - a.level) / Math.max(1, b.level - a.level);
      return { usd_per_hour: a.usd_per_hour + (b.usd_per_hour - a.usd_per_hour) * k, interval_ticks: Math.max(1, Math.round(a.interval_ticks + (b.interval_ticks - a.interval_ticks) * k)) };
    }
    return t[t.length - 1];
  }
  function intensityMount() {
    const n = I.n = {};
    n.auto = el("button", { type: "button", class: "cb-seg", onclick: () => setIntensity({ brain_intensity_mode: "auto" }, tr("cerebro.int.autoSet")) }, "Auto");
    n.manual = el("button", { type: "button", class: "cb-seg", onclick: () => setIntensity({ brain_intensity: +n.slider.value, brain_intensity_mode: "manual" }, tr("cerebro.int.manualSet", { level: n.slider.value })) }, "Manual");
    n.slider = el("input", { type: "range", min: "0", max: "100", step: "1", class: "cb-range", "aria-label": tr("cerebro.int.title") });
    n.slider.addEventListener("input", () => { I.dragging = true; estimate(+n.slider.value); });
    n.slider.addEventListener("change", () => { I.dragging = false; setIntensity({ brain_intensity: +n.slider.value, brain_intensity_mode: "manual" }, tr("cerebro.int.levelSet", { level: n.slider.value })); });
    n.level = el("b", { class: "num cb-i-level" }, "—");
    n.rate = el("b", { class: "num cb-i-rate" }, "—");
    n.every = el("span", { class: "cb-muted num" }, "");
    n.why = el("div", { class: "cb-i-why" });
    n.wake = el("div", { class: "cb-i-wake" });
    n.hist = el("div", { class: "cb-i-hist" });
    n.sub = el("span", { class: "panel-sub" }, "");
    // where the brain reasons: on the Mac (Claude Code subscription, no API cost), on the API, or automatic
    n.be = {};
    for (const [id, label] of [["mac", "Mac"], ["api", "API"], ["auto", "Auto"]])
      n.be[id] = el("button", { type: "button", class: "cb-seg", onclick: () => setIntensity({ brain_backend: id }, tr("cerebro.int.backendSet", { label })) }, label);
    n.beState = el("span", { class: "cb-i-bestate" });
    n.macCap = el("input", { type: "number", min: "0", step: "1", inputmode: "numeric", class: "cb-q cb-i-cap-in", "aria-label": tr("cerebro.int.capAria") });
    const saveCap = el("button", { type: "button", class: "cb-seg", onclick: async () => {
      const v = Number(n.macCap.value);
      if (!isFinite(v) || v < 0 || n.macCap.value === "") { U().toast({ type: "error", title: tr("cerebro.int.badNumber") }); return; }
      if (await U().confirm({ title: tr("cerebro.int.capAsk", { n: v }), text: tr("cerebro.int.capText"), confirmLabel: tr("cerebro.int.capYes") }))
        setIntensity({ mac_calls_per_hour: v }, tr("cerebro.int.capSet", { n: v }));
    } }, tr("cerebro.save"));
    n.backend = el("div", { class: "cb-i-backend", hidden: true }, el("span", { class: "cb-cap cb-i-cap" }, tr("cerebro.int.reasonsWith")),
      el("div", { class: "cb-i-mode" }, n.be.mac, n.be.api, n.be.auto), n.beState, el("span", { class: "cb-sp" }),
      el("label", { class: "cb-i-caplab" }, el("span", { class: "cb-muted" }, tr("cerebro.int.capLabel")), n.macCap, saveCap));
    n.body = el("div", { class: "cb-i-body" },
      n.backend,
      el("div", { class: "cb-i-top" }, el("div", { class: "cb-i-mode" }, n.auto, n.manual),
        el("div", { class: "cb-i-slide" }, el("span", { class: "cb-muted num" }, "0"), n.slider, el("span", { class: "cb-muted num" }, "100"), n.level),
        el("div", { class: "cb-i-est" }, el("span", { class: "cb-muted" }, "≈"), n.rate, n.every)),
      n.why, el("div", { class: "cb-i-two" }, n.wake, n.hist));
    n.off = el("div", { class: "cb-i-off cb-muted", hidden: true }, "");
    I.host = el("section", { class: "panel cb-intensity" }, el("header", { class: "panel-head" }, el("h2", { class: "panel-title" }, tr("cerebro.int.title")), n.sub,
      el("div", { class: "panel-actions" }, el("a", { class: "cb-link", href: "#bot" }, tr("cerebro.int.budgetLink")))), n.body, n.off);
    intensityPaint();
    return I.host;
  }
  function estimate(level) {
    const n = I.n, li = levelInfo(level);
    n.level.textContent = String(level);
    n.rate.textContent = li ? fmtNum(li.usd_per_hour, 2) + " $/h" : "—";
    n.every.textContent = li ? tr(li.interval_ticks === 1 ? "cerebro.int.everyOne" : "cerebro.int.every", { n: li.interval_ticks }) : "";
  }
  function intensityPaint() {
    const n = I.n, d = I.data; if (!I.host) return;
    const off = !d;
    n.off.hidden = !(I.state === "off" || I.state === "error");
    n.off.textContent = I.state === "error" ? tr("cerebro.int.readFail", { err: (I.err && I.err.message) || "" }) : tr("cerebro.int.off");
    n.body.classList.toggle("is-off", off);
    for (const x of [n.slider, n.auto, n.manual, n.be.mac, n.be.api, n.be.auto, n.macCap]) x.disabled = off || I.busy;
    if (!d) { n.sub.textContent = I.state === "idle" ? tr("cerebro.loading") : ""; return; }
    const auto = d.mode !== "manual";
    n.auto.classList.toggle("on", auto); n.manual.classList.toggle("on", !auto);
    n.sub.textContent = tr(auto ? "cerebro.int.subAuto" : "cerebro.int.subManual", { level: d.level });
    if (!I.dragging && document.activeElement !== n.slider) {
      n.slider.value = String(d.level ?? 0); estimate(+n.slider.value);
      if (num(d.usd_per_hour_now) != null) n.rate.textContent = fmtNum(d.usd_per_hour_now, 2) + " $/h";
      const st = d.settings || {};
      if (st.interval_ticks) n.every.textContent = tr("cerebro.int.every", { n: st.interval_ticks });
    }
    // backend line (only when the API reports it)
    const mb = d.mac_backend || {};
    const be = d.brain_backend || mb.mode;
    n.backend.hidden = !be;
    if (be) {
      for (const k of ["mac", "api", "auto"]) n.be[k].classList.toggle("on", be === k);
      const stt = d.mac_backend_state || mb.state || "";
      const calls = num(d.mac_calls_last_hour) ?? num(mb.calls_last_hour), cap = num(d.mac_calls_per_hour) ?? num(mb.calls_per_hour);
      const ST_KEY = { ok: ["cerebro.be.ok", "ok"], cooling: ["cerebro.be.waiting", "warn"], backoff: ["cerebro.be.waiting", "warn"], off: ["cerebro.be.off", "mute"], error: ["cerebro.be.error", "bad"], unavailable: ["cerebro.be.unavailable", "bad"] };
      const [stk, stt2] = ST_KEY[stt] || [null, "mute"];
      const stl = stk ? tr(stk) : stt || "—";
      const now = be === "api" ? tr("cerebro.be.api") : be === "mac" ? tr("cerebro.be.mac") : (stt === "ok" && (cap == null || calls < cap) ? tr("cerebro.be.macFirst") : tr("cerebro.be.apiNow"));
      replace(n.beState, el("b", {}, now), calls != null ? el("span", { class: "num cb-muted" }, " · " + tr("cerebro.be.calls", { n: calls + (cap != null ? "/" + cap : "") })) : null,
        el("span", { class: "cb-muted" }, " · " + tr("cerebro.be.state") + " "), el("span", { class: "tag res tone-" + stt2 }, stl),
        mb.backoff_until ? el("span", { class: "cb-muted num" }, " · " + tr("cerebro.be.back", { time: when(mb.backoff_until) })) : null,
        mb.last_error ? el("span", { class: "cb-muted", title: mb.last_error }, " · " + tr("cerebro.be.lastError", { time: when(mb.last_error_ts) })) : null,
        num(mb.last_latency_s) != null ? el("span", { class: "cb-muted num" }, " · " + tr("cerebro.be.latency", { s: fmtNum(mb.last_latency_s, 0) })) : null);
      if (document.activeElement !== n.macCap) n.macCap.value = cap == null ? "" : String(cap);
    }
    const hist = (Array.isArray(d.history) ? d.history : []).slice().sort((a, b) => (a.ts || 0) - (b.ts || 0));
    const prev = hist.length > 1 ? hist[hist.length - 2] : null;
    const from = prev && prev.level != null ? prev.level : null;
    replace(n.why, el("span", { class: "cb-cap cb-i-cap" }, auto ? tr("cerebro.int.whyAt", { level: d.level }) : tr("cerebro.int.lastChange")),
      d.reason ? el("b", {}, (from != null && d.level > from ? tr("cerebro.int.up") + " " : from != null && d.level < from ? tr("cerebro.int.down") + " " : "") + reasonEs(d.reason)) : el("span", { class: "cb-muted" }, tr("cerebro.int.noReason")),
      d.changed ? el("span", { class: "cb-muted num" }, (from != null ? ` · ${from} → ${d.level}` : "") + " · " + when(d.changed)) : null);
    const st = d.settings || {};
    const kinds = (st.wake_kinds || []).map((k) => (WAKE[k] ? tr(WAKE[k]) : k));
    if (st.wake_on_score_drop) kinds.push(tr("cerebro.why.scoreDrop"));
    replace(n.wake, el("div", { class: "cb-cap" }, tr("cerebro.int.wakes")),
      kinds.length ? el("div", { class: "cb-i-chips" }, kinds.map((k) => el("span", { class: "tag res tone-mute" }, k))) : el("div", { class: "cb-muted" }, tr("cerebro.int.onlyInterval")),
      st.min_gap_s ? el("div", { class: "cb-rows" }, tr("cerebro.int.minGap", { s: Math.round(st.min_gap_s) })) : null);
    const rows = hist.slice(-8).reverse();
    replace(n.hist, el("div", { class: "cb-cap" }, tr("cerebro.int.history")),
      rows.length ? rows.map((h, i) => { const before = hist[hist.indexOf(h) - 1];
        const up = before && h.level > before.level, down = before && h.level < before.level;
        return el("div", { class: "cb-i-hrow" }, el("span", { class: "num cb-time" }, when(h.ts)),
          el("b", { class: "num " + (up ? "cb-i-up" : down ? "cb-i-down" : "") }, (before ? before.level + " → " : "") + h.level),
          el("span", { class: "tag res tone-mute" }, h.mode === "manual" ? "manual" : "auto"), el("span", { class: "cb-i-hwhy", title: reasonEs(h.reason) }, reasonEs(h.reason))); })
        : el("div", { class: "cb-muted" }, tr("cerebro.int.noHistory")));
  }
  function replace(node, ...kids) { node.replaceChildren(...kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false)); }
  async function intensityPull(force) {
    if (!I.host || I.busy || (!force && Date.now() - I.at < 4000)) return;
    I.at = Date.now();
    try { I.data = await A().brainBudget(); I.state = "on"; }
    catch (e) { I.state = e && e.status === 404 ? "off" : "error"; I.err = e; if (e && e.status === 404) I.data = null; }
    intensityPaint();
  }
  async function setIntensity(body, done) {
    if (I.busy) return;
    I.busy = true; intensityPaint();
    try { await A().control(body); U().toast({ type: "deal", title: done }); }
    catch (e) { U().toast({ type: "error", title: tr("cerebro.int.applyFail"), text: (e && e.message) || String(e) }); }
    finally { I.busy = false; I.at = 0; await intensityPull(true); }
  }

  window.Screens.cerebro = {
    get title() { return tr("cerebro.title"); },
    mount(root) {
      S.root = root;
      root.replaceChildren(el("div", { class: "cb-layout" },
        el("div", { class: "scr-cerebro" },
          intensityMount(), el("div", { class: "cb-top" }, U().loading()), outboxMount(), externalMount(), el("div", { class: "cb-mid" }), el("div", { class: "cb-bot" })),
        chatMount()));
    },
    async refresh(root, data, params, opts) {
      S.root = root;
      chatPull();
      outboxPull(opts && opts.force);
      intensityPull(opts && opts.force);
      extPull(opts && opts.force);
      try { const me = await A().rec("me"); window.__cbMe = (me && (me.data || me)) || {}; } catch (e) { /* optional */ }
      const d = await load(data);
      // avoid rebuilding when nothing changed (keeps scroll and open history item)
      const sig = JSON.stringify([d.cur && d.cur.updated, d.status && d.status.updated, d.history.length, d.findings.length, d.err && d.err.status, S.histSel, d.budget && [d.budget.level, d.budget.mode, d.budget.usd_per_hour_now, d.budget.spent_today, d.budget.cap_today]]);
      if (sig === S.sig && S.data && !(opts && opts.force)) return;
      S.sig = sig; S.data = d;
      render();
    },
    unmount() { S.root = null; S.sig = null; S.findHost = null; C.host = null; O.host = null; X.host = null; I.host = null; },
  };
})();
