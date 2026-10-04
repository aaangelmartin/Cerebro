/* SUPERVISIÓN · ver y aprobar (sin controles de encendido ni de modo: eso vive en Bot).
   Detalle: #supervision/<id de decisión> (id del ledger o id de la acción). */
(function () {
  "use strict";
  window.Screens = window.Screens || {};

  const U = () => window.ui || {};
  const A = () => window.api || {};
  const t = (k, v) => window.I18N.t(k, v);
  const lang = () => window.I18N.lang;
  const loc = () => window.I18N.locale;
  function h(tag, attrs, ...kids) {
    if (U().el) return U().el(tag, attrs || {}, ...kids.filter((k) => k !== null && k !== undefined && k !== false));
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") e.className = v;
      else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v);
    }
    for (const k of kids.flat()) {
      if (k === null || k === undefined || k === false) continue;
      e.append(k instanceof Node ? k : document.createTextNode(String(k)));
    }
    return e;
  }
  const comp = (name, ...args) => {
    try { if (U()[name]) return U()[name](...args); } catch (e) { console.warn("ui." + name, e); }
    return null;
  };
  const num = (x) => (x === null || x === undefined || x === "" || isNaN(+x) ? null : +x);
  const fmtNum = (n, d = 0) => (n === null || n === undefined ? "—" : U().fmtNum ? U().fmtNum(n, d) : (+n).toFixed(d).replace(".", ","));
  const fmtP = (n) => (n === null || n === undefined ? "—" : U().fmtP ? U().fmtP(n) : fmtNum(n, 0) + " P");
  const fmtTime = (ts) => (U().fmtTime ? U().fmtTime(ts) : ts ? new Date(ts * 1000).toLocaleTimeString(loc()) : "");
  const items = (r, ...keys) => {
    if (Array.isArray(r)) return r;
    if (!r || typeof r !== "object") return [];
    for (const k of [...keys, "items", "rows"]) if (Array.isArray(r[k])) return r[k];
    return [];
  };
  async function safe(fn, fallback) {
    try { const f = fn(); return f && f.then ? await f : f === undefined ? fallback : f; }
    catch (e) { return { __error: e, __fallback: fallback }; }
  }
  const isErr = (x) => x && x.__error;
  const val = (x) => (isErr(x) ? x.__fallback : x);
  const toSet = (v) => (v instanceof Set ? v : Array.isArray(v) ? new Set(v) : v && v !== "todos" ? new Set([v]) : null);

  // ---------- mapping ----------
  const TYPES = ["compra", "venta", "cambio", "puja", "duelo", "dealer", "anuncio"];
  const assetsOf = (side) => (side && (side.assets || []).length) || 0;
  const cashOf = (side) => (side && num(side.cash)) || 0;
  function typeOf(a) {
    const k = a.kind || "", p = a.params || {}, dom = a.domain || "";
    if (k.startsWith("duel") || dom === "duels") return "duelo";
    if (k.includes("thread") || dom === "dealers") return "dealer";
    if (k === "post_offer") {
      if (p.mechanism === "auction" || p.bid || p.auction) return "puja";
      if (cashOf(p.give) > 0 && assetsOf(p.want)) return "compra";
      if (assetsOf(p.give) && cashOf(p.want) > 0) return "venta";
      return "cambio";
    }
    if (k === "accept_offer") {
      const e = p.expect || {};
      if (assetsOf(e.give) && cashOf(e.want) > 0) return "compra";  // they give cards, want cash -> we buy
      if (cashOf(e.give) > 0 && assetsOf(e.want)) return "venta";
      return "cambio";
    }
    if (k === "broker_match") return "cambio";
    if (k === "open_pack") return "compra";
    return "anuncio";
  }
  const SRC = { opus: "opus", sonnet: "opus", haiku: "opus", council: "consejo", consejo: "consejo", fallback: "reserva", reserva: "reserva", code: "codigo", codigo: "codigo" };
  const SRC_IDS = ["opus", "consejo", "reserva", "codigo"];
  const RES_IDS = ["enviado", "vetado", "rechazado", "pendiente", "sin_enviar", "cerrado", "sin_acuerdo"];
  const RAIL_IDS = ["council", "value", "cash_floor", "per_tick", "protected", "bond", "otro"];
  const MODE_IDS = ["auto", "observe", "manual", "review"];
  const srcLabel = (id) => (SRC_IDS.includes(id) ? t("supervision.src." + id) : id);
  const resLabel = (id) => (RES_IDS.includes(id) ? t("supervision.res." + id) : id);
  const railLabel = (id) => (RAIL_IDS.includes(id) ? t("supervision.rail." + id) : id);
  const modeLabel = (id) => (MODE_IDS.includes(id) ? t("supervision.mode." + id) : id || "—");
  const OUT = { sent: "enviado", deal: "cerrado", no_deal: "sin_acuerdo", expired: "sin_acuerdo", refused: "rechazado", error: "rechazado", vetoed: "vetado" };

  function enrich(dec, ctx) {
    const a = dec.action || {};
    const c = ctx.councilByAction[a.id];
    const outs = ctx.outsByAction[a.id] || [];
    const o = outs.find((x) => x.status === "deal") || outs[outs.length - 1];
    const v = dec.verdict || {};
    let src = SRC[String(dec.source || a.source || "").toLowerCase()] || "codigo";
    let extra = null;
    if (c) {
      const votes = c.votes || [];
      const total = (c.roles || []).length || votes.length;
      extra = `${votes.filter((x) => x.verdict !== "reject").length}/${total}`;
      src = "consejo";
    }
    let res;
    if (v.ok === false) res = "vetado";
    else if (dec.dry_run) res = "sin_enviar";
    else if (o) res = OUT[o.status] || "pendiente";
    else res = "pendiente";
    return { dec, a, c, o, outs, v, src, extra, res, type: typeOf(a) };
  }

  function title(a) {
    const p = a.params || {};
    const e = p.expect || {};
    switch (a.kind) {
      case "duel_message": return p.days != null ? t("supervision.act.duel_message_days", { price: fmtP(p.price), days: p.days, duel: String(p.duel) }) : t("supervision.act.duel_message", { price: fmtP(p.price), duel: String(p.duel) });
      case "duel_accept": return t("supervision.act.duel_accept", { price: fmtP(e.price), duel: String(p.duel) });
      case "thread_message": return t("supervision.act.thread_message", { price: fmtP(p.price), thread: String(p.thread) });
      case "open_thread": return t("supervision.act.open_thread", { who: p.with || "dealer" }) + (p.topic && typeof p.topic !== "object" ? " · " + p.topic : "");
      case "close_thread": return t("supervision.act.close_thread", { thread: String(p.thread) });
      case "post_offer": return t("supervision.act.post_offer", { venue: p.venue || "?", give: side(p.give), want: side(p.want) });
      case "accept_offer": return t("supervision.act.accept_offer", { offer: String(p.offer) });
      case "cancel_offer": return t("supervision.act.cancel_offer", { offer: String(p.offer) });
      case "venue_open": return t("supervision.act.venue_open", { name: p.name || "" });
      case "venue_patch": return t("supervision.act.venue_patch", { venue: p.venue || "" });
      case "broker_match": return t("supervision.act.broker_match", { sell: String(p.sell), buy: String(p.buy), price: fmtP(p.price) });
      case "broker_announce": return t("supervision.act.broker_announce");
      case "open_pack": return t("supervision.act.open_pack", { asset: String(p.asset) });
      case "brain_plan": return t("supervision.act.brain_plan", { what: [...(p.changes || []), ...((p.cancel_offers || []).length ? [t("supervision.act.brain_withdraws", { ids: p.cancel_offers.map((x) => "#" + x).join(", ") })] : [])].join(" · ") || t("supervision.act.plan") });
      default: return a.kind || t("supervision.act.default");
    }
  }
  function side(s) {
    if (!s) return "—";
    const parts = [];
    if (cashOf(s)) parts.push(fmtP(s.cash));
    for (const x of s.assets || []) parts.push(typeof x === "object" ? x.ref || x.kind || "#" + x.id : "#" + x);
    for (const t of s.types || []) parts.push(typeof t === "string" ? t : t.ref || JSON.stringify(t));
    return parts.join(" + ") || t("supervision.side.nothing");
  }

  // decisions of the brain (strategist): each plan that changed settings or cancelled offers is a decision too
  function brainRows(r) {
    if (!r || typeof r !== "object") return [];
    const docs = (r.history || []).slice();
    if (r.current && !docs.some((d) => d.updated === r.current.updated)) docs.push(r.current);
    const out = [];
    for (const doc of docs) {
      const plan = doc.plan || {};
      const changes = (doc.big_changes || []).slice();
      const cancels = plan.cancel_offers || [];
      if (!changes.length && !cancels.length) continue;
      const c = doc.council;
      const total = c && Array.isArray(c.votes) ? c.votes.length : 0;
      const a = { id: "cerebro-" + Math.round(doc.updated || 0), kind: "brain_plan", domain: "cerebro", source: c ? "council" : "opus",
        params: { changes, cancel_offers: cancels }, reason: (plan.priorities || [])[0] || plan.situation || doc.reason || "" };
      out.push({ dec: { id: a.id, ts: doc.updated, tick: doc.tick, source: a.source, action: a }, a, c: null, o: null, outs: [], v: { ok: !(c && c.ok === false) },
        src: c ? "consejo" : "opus", extra: c ? `${c.yes ?? 0}/${total}` : null, res: c && c.ok === false ? "vetado" : "enviado", type: "anuncio" });
    }
    return out;
  }

  // ---------- state ----------
  const S = { root: null, filter: null, extra: {}, drawerFor: null, selected: null, params: "", lastData: null };

  async function load() {
    const [stR, decR, couR, outR, logR, strR] = await Promise.all([
      safe(() => A().status(), {}),
      safe(() => A().decisions(undefined), { items: [] }),
      safe(() => A().council(undefined), { items: [] }),
      safe(() => A().outcomes(undefined), { items: [] }),
      safe(() => (A().controlLog ? A().controlLog() : A().journal ? A().journal("control") : null), null),
      safe(() => (A().strategy ? A().strategy(100) : null), null),
    ]);
    const councilByAction = {}; for (const c of items(val(couR))) if (c.action_id) councilByAction[c.action_id] = c;
    const outsByAction = {}; for (const o of items(val(outR))) if (o.action_id) (outsByAction[o.action_id] = outsByAction[o.action_id] || []).push(o);
    const ctx = { councilByAction, outsByAction };
    const rows = items(val(decR)).map((d) => enrich(d, ctx)).concat(brainRows(val(strR)))
      .sort((a, b) => (b.dec.ts ?? 0) - (a.dec.ts ?? 0) || (b.dec.id ?? 0) - (a.dec.id ?? 0));
    return {
      status: val(stR) || {}, rows, council: items(val(couR)), log: logR === null ? null : items(val(logR)),
      decErr: isErr(decR) ? decR.__error : null, statErr: isErr(stR) ? stR.__error : null,
    };
  }

  // ---------- pieces ----------
  function strip(st) {
    const ctl = st.control || {};
    const live = !!(st.armed && !st.stop_file && st.age_s != null && st.age_s <= 120);
    const doms = Object.keys(st.domains || {});
    const paused = new Set(ctl.paused_domains || []);
    const active = doms.filter((d) => !paused.has(d)).length;
    const mode = modeLabel(ctl.mode);
    return h("div", { class: "sv-strip" },
      h("span", { class: "sv-dot " + (live ? "on" : "off") }), h("b", { class: "sv-state " + (live ? "on" : "off") }, live ? t("supervision.strip.on") : t("supervision.strip.off")),
      h("span", { class: "sv-mono" }, t("supervision.strip.summary", { mode, active, total: doms.length || 0 })),
      st.stop_file ? h("span", { class: "sv-bad" }, t("supervision.strip.stop")) : null,
      st.doors ? h("span", { class: "sv-muted sv-mono" }, st.doors === "open" ? t("supervision.strip.market_open") : t("supervision.strip.market_closed")) : null,
      h("span", { class: "sv-sp" }),
      h("a", { href: "#bot", class: "sv-btn" }, t("supervision.strip.link")));
  }

  function queuePanel(data) {
    const mode = ((data.status || {}).control || {}).mode || "auto";
    const auto = mode === "auto";
    const pending = data.rows.filter((r) => r.res === "pendiente").slice(0, 6);
    const hasApproval = typeof A().approve === "function";
    const panel = h("section", { class: "sv-panel sv-queue" + (auto ? " sv-grey" : "") },
      h("div", { class: "sv-ph" }, h("b", {}, t("supervision.queue.title")),
        h("span", { class: "sv-muted" }, auto ? t("supervision.queue.auto") : hasApproval ? t("supervision.queue.waiting") : t("supervision.queue.no_api")),
        h("span", { class: "sv-sp" }), h("button", { class: "sv-btn", disabled: "" }, t("supervision.queue.approve_all"))));
    if (!pending.length) {
      panel.append(h("div", { class: "sv-empty" }, auto ? t("supervision.queue.empty_auto") : t("supervision.queue.empty")));
      return panel;
    }
    for (const r of pending) {
      const btn = (label) => h("button", { class: "sv-btn", disabled: "", title: auto ? t("supervision.queue.tip_auto") : t("supervision.queue.tip_none") }, label);
      panel.append(h("div", { class: "sv-qrow t-" + r.type },
        comp("typeChip", r.type) || h("span", {}, r.type),
        h("div", { class: "sv-grow" }, h("div", {}, title(r.a)), h("div", { class: "sv-muted sv-small" }, r.a.reason || "")),
        btn(t("supervision.queue.approve")), btn(t("supervision.queue.edit")), btn(t("supervision.queue.reject"))));
    }
    return panel;
  }

  function countBy(rows, f) { const m = {}; for (const r of rows) { const k = f(r); m[k] = (m[k] || 0) + 1; } return m; }

  function applyFilter(rows) {
    const f = S.filter || {};
    const types = toSet(f.types);
    const ex = f.extra || {};
    const fuente = toSet(ex.fuente);
    const resu = toSet(ex.resultado);
    const q = String(f.q || "").trim().toLowerCase();
    return rows.filter((r) => (!types || !types.size || types.has(r.type))
      && (!fuente || !fuente.size || fuente.has(r.src))
      && (!resu || !resu.size || resu.has(r.res))
      && (!q || `${title(r.a)} ${r.a.reason || ""} ${r.a.kind} ${r.a.id} ${r.dec.id}`.toLowerCase().includes(q)));
  }

  function streamRows(list, data) {
    const box = h("div", { class: "sv-list" });
    if (data.decErr) { box.append(comp("error", data.decErr) || h("div", {}, t("supervision.stream.error"))); return box; }
    if (!data.rows.length) { box.append(comp("empty", t("supervision.stream.empty_all")) || h("div", {}, t("supervision.stream.none"))); return box; }
    if (!list.length) { box.append(comp("empty", t("supervision.stream.empty_filter")) || h("div", {}, t("supervision.stream.no_results"))); return box; }
    for (const r of list.slice(0, 300)) {
      const id = r.dec.id ?? r.a.id;
      const cells = [
        h("span", { class: "sv-mono sv-muted sv-time" }, fmtTime(r.dec.ts), h("br", {}), h("small", {}, "t" + (r.dec.tick ?? "?"))),
        comp("typeChip", r.type) || h("span", {}, r.type),
        h("div", { class: "sv-grow" }, h("div", { class: "sv-title" }, title(r.a)), h("div", { class: "sv-muted sv-small" }, r.a.reason || ""),
          r.v.ok === false && (r.v.rail || r.v.detail) ? h("div", { class: "sv-bad sv-small" }, `${r.v.rail}: ${r.v.detail}`) : null),
        comp("sourceTag", r.src, r.extra) || h("span", {}, srcLabel(r.src) + (r.extra ? " " + r.extra : "")),
        comp("resultChip", r.res) || h("span", {}, resLabel(r.res)),
      ];
      const onClick = () => { S.selected = String(id); location.hash = "#supervision/" + id; };
      const row = comp("row", { type: r.type, cells, onClick, cols: "64px 112px minmax(0,1fr) 120px 112px" }) || h("div", { class: "sv-row", onclick: onClick }, ...cells);
      row.classList.add("sv-drow");
      if (S.selected === String(id) || S.selected === r.a.id) row.classList.add("sv-sel");
      box.append(row);
    }
    return box;
  }

  function votesPanel(sel) {
    const panel = h("section", { class: "sv-panel" }, h("div", { class: "sv-ph" }, h("b", {}, t("supervision.votes.title")), h("span", { class: "sv-muted" }, t("supervision.votes.sub"))));
    if (!sel) { panel.append(h("div", { class: "sv-empty" }, t("supervision.votes.pick"))); return panel; }
    panel.append(h("div", { class: "sv-pad" }, h("div", { class: "sv-mono sv-muted sv-small" }, `${fmtTime(sel.dec.ts)} · ${(sel.a.domain || "").toUpperCase()}`), h("b", {}, title(sel.a))));
    if (!sel.c) { panel.append(h("div", { class: "sv-empty" }, t("supervision.votes.none"))); return panel; }
    panel.append(votesList(sel.c));
    return panel;
  }
  function votesList(c) {
    const box = h("div", { class: "sv-pad sv-votes" });
    const roles = c.roles || [];
    const votes = c.votes || [];
    const seg = h("div", { class: "sv-segbar" });
    for (const role of roles) { const v = votes.find((x) => x.role === role); seg.append(h("i", { class: v ? v.verdict : "none" })); }
    box.append(seg);
    for (const role of roles.length ? roles : votes.map((v) => v.role)) {
      const v = votes.find((x) => x.role === role);
      const verdict = v ? (["approve", "modify", "reject"].includes(v.verdict) ? t("supervision.votes.verdict." + v.verdict) : v.verdict) : t("supervision.votes.abstain");
      const detail = v ? (v.reason || (v.params && Object.keys(v.params).length ? t("supervision.votes.proposes", { params: JSON.stringify(v.params) }) : "")) : t("supervision.votes.no_answer");
      box.append(h("div", { class: "sv-vote" },
        h("div", { class: "sv-row2" }, h("b", {}, role), v && v.model ? h("span", { class: "sv-muted sv-small" }, v.model) : null, h("span", { class: "sv-sp" }),
          h("span", { class: "sv-verdict " + (v ? v.verdict : "none") }, verdict)),
        detail ? h("div", { class: "sv-small" }, detail) : null,
        v && (v.injection || v.rail_risk) ? h("div", { class: "sv-bad sv-small" }, [v.injection ? t("supervision.votes.injection") : null, v.rail_risk ? t("supervision.votes.rail_risk") : null].filter(Boolean).join(" · ")) : null));
    }
    box.append(h("div", { class: "sv-muted sv-small" }, t("supervision.votes.result", { result: c.result || "—" }) + ` · ${c.why || ""}${c.latency_s != null ? " · " + fmtNum(c.latency_s, 1) + " s" : ""}`));
    for (const e of c.errors || []) box.append(h("div", { class: "sv-bad sv-small" }, typeof e === "string" ? e : JSON.stringify(e)));
    return box;
  }

  function railsPanel(rows) {
    const vetoed = rows.filter((r) => r.res === "vetado");
    const by = countBy(vetoed, (r) => r.v.rail || "otro");
    const entries = Object.entries(by).sort((a, b) => b[1] - a[1]);
    const max = Math.max(1, ...entries.map((e) => e[1]));
    const panel = h("section", { class: "sv-panel" }, h("div", { class: "sv-ph" }, h("b", {}, t("supervision.rails.title")), h("span", { class: "sv-muted" }, String(vetoed.length))));
    if (!entries.length) { panel.append(h("div", { class: "sv-empty" }, t("supervision.rails.empty"))); return panel; }
    const box = h("div", { class: "sv-pad" });
    for (const [rail, n] of entries)
      box.append(h("div", { class: "sv-bar" }, h("span", {}, railLabel(rail)), h("span", { class: "sv-track" }, h("i", { style: `width:${(n / max) * 100}%` })), h("b", { class: "sv-mono" }, String(n))));
    const last = vetoed[0];
    if (last) box.append(h("div", { class: "sv-muted sv-small" }, t("supervision.rails.last", { title: title(last.a), detail: last.v.detail || last.v.rail || "" })));
    panel.append(box);
    return panel;
  }

  function logPanel(data) {
    const panel = h("section", { class: "sv-panel" }, h("div", { class: "sv-ph" }, h("b", {}, t("supervision.log.title"))));
    const box = h("div", { class: "sv-pad" });
    if (data.log === null) {
      const ctl = (data.status || {}).control || {};
      box.append(h("div", { class: "sv-muted sv-small" }, t("supervision.log.not_served")));
      box.append(h("div", { class: "sv-logrow" }, h("span", {}, t(ctl.armed ? "supervision.log.state_on" : "supervision.log.state_off", { mode: modeLabel(ctl.mode) })), h("span", { class: "sv-sp" }),
        h("span", { class: "sv-mono sv-muted" }, ctl.updated ? fmtTime(ctl.updated) : "")));
      if ((ctl.paused_domains || []).length) box.append(h("div", { class: "sv-logrow" }, t("supervision.log.paused", { list: ctl.paused_domains.join(", ") })));
      if ((ctl.protected || []).length) box.append(h("div", { class: "sv-logrow" }, t("supervision.log.protected", { list: ctl.protected.join(", ") })));
    } else if (!data.log.length) {
      box.append(h("div", { class: "sv-empty" }, t("supervision.log.empty")));
    } else {
      for (const r of data.log.slice().reverse().slice(0, 30)) {
        const ch = r.change || {};
        const txt = Object.entries(ch).map(([k, v]) => {
          if (k === "armed") return v ? t("supervision.log.bot_on") : t("supervision.log.bot_off");
          if (k === "stop_file") return v ? t("supervision.log.stop_on") : t("supervision.log.stop_off");
          if (k === "mode") return t("supervision.log.mode_changed", { mode: modeLabel(v) });
          if (k === "paused_domains") return t("supervision.log.paused", { list: (v || []).join(", ") || t("supervision.log.nobody") });
          return `${k}: ${JSON.stringify(v)}`;
        }).join(" · ");
        box.append(h("div", { class: "sv-logrow" }, h("span", {}, txt || t("supervision.log.change")), h("span", { class: "sv-sp" }), h("span", { class: "sv-mono sv-muted" }, fmtTime(r.ts))));
      }
    }
    panel.append(box);
    return panel;
  }

  // ---------- drawer ----------
  const kv = (obj) => {
    const box = h("div", { class: "sv-kv" });
    for (const [k, v] of Object.entries(obj || {})) box.append(h("span", { class: "sv-muted" }, k), h("span", { class: "sv-mono" }, typeof v === "object" ? JSON.stringify(v) : String(v)));
    return box;
  };
  function drawerBody(r, data) {
    const b = h("div", { class: "scr-supervision sv-drawer" });
    b.append(h("div", { class: "sv-row2" }, comp("typeChip", r.type) || r.type, comp("sourceTag", r.src, r.extra) || r.src, comp("resultChip", r.res) || r.res, h("span", { class: "sv-sp" }),
      h("span", { class: "sv-mono sv-muted sv-small" }, `#${r.dec.id} · ${r.a.id || ""} · t${r.dec.tick ?? "?"} · ${fmtTime(r.dec.ts)}`)));
    b.append(h("h3", {}, title(r.a)));
    b.append(h("div", { class: "sv-sec" }, t("supervision.drawer.reasoning")), h("div", {}, r.a.reason || "—"));
    b.append(h("div", { class: "sv-sec" }, t("supervision.drawer.action", { kind: r.a.kind || "", domain: r.a.domain || "" })), kv(r.a.params));
    if (r.a.big || r.a.priority) b.append(h("div", { class: "sv-muted sv-small" }, [r.a.big ? t("supervision.drawer.big") : null, t("supervision.drawer.priority", { n: fmtNum(r.a.priority, 2) }), r.dec.latency_s != null ? t("supervision.drawer.latency", { s: fmtNum(r.dec.latency_s, 2) }) : null].filter(Boolean).join(" · ")));
    // expected vs realised
    b.append(h("div", { class: "sv-sec" }, t("supervision.drawer.evr")));
    const realised = {}; for (const o of r.outs) Object.assign(realised, o.realised || {});
    const grid = h("div", { class: "sv-evr" }, h("div", {}, h("small", {}, t("supervision.drawer.expected")), kv(r.a.expected)), h("div", {}, h("small", {}, t("supervision.drawer.real")),
      r.outs.length ? kv({ [t("supervision.drawer.status")]: [...new Set(r.outs.map((o) => o.status))].join(" → "), ...realised }) : h("div", { class: "sv-muted" }, r.res === "sin_enviar" ? t("supervision.drawer.not_sent") : t("supervision.drawer.no_result"))));
    b.append(grid);
    if (r.o && r.o.response && Object.keys(r.o.response).length) b.append(h("details", {}, h("summary", { class: "sv-muted sv-small" }, t("supervision.drawer.server")), kv(r.o.response)));
    // rails
    b.append(h("div", { class: "sv-sec" }, t("supervision.drawer.rails")), h("div", { class: r.v.ok === false ? "sv-bad" : "sv-ok" }, r.v.ok === false ? t("supervision.drawer.vetoed_by", { rail: railLabel(r.v.rail), detail: r.v.detail || "" }) : t(r.dec.dry_run ? "supervision.drawer.rails_ok_dry" : "supervision.drawer.rails_ok")));
    // council
    b.append(h("div", { class: "sv-sec" }, t("supervision.drawer.council")));
    if (r.c) {
      b.append(votesList(r.c));
      if (r.c.final_params) b.append(h("div", { class: "sv-muted sv-small" }, t("supervision.drawer.final_params")), kv(r.c.final_params));
    } else b.append(h("div", { class: "sv-muted" }, t("supervision.drawer.no_council")));
    // lessons
    b.append(h("div", { class: "sv-sec" }, t("supervision.drawer.lessons")));
    const ls = r.a.lesson_ids || [];
    b.append(ls.length ? h("div", { class: "sv-row2" }, ...ls.map((id) => h("a", { href: "#laboratorio/" + id, class: "sv-link sv-mono" }, id))) : h("div", { class: "sv-muted" }, t("supervision.drawer.none")));
    if (r.type === "duelo" && (r.a.params || {}).duel != null) b.append(h("a", { href: "#duelos/" + r.a.params.duel, class: "sv-link" }, t("supervision.drawer.see_duel")));
    return b;
  }

  function findRow(data, id) { return data.rows.find((r) => String(r.dec.id) === id || r.a.id === id); }

  function render(root, data, params) {
    root.querySelector(".sv-strip-wrap").replaceChildren(data.statErr ? comp("error", data.statErr) || h("div", {}, t("supervision.no_status")) : strip(data.status));
    root.querySelector(".sv-queue-wrap").replaceChildren(queuePanel(data));
    // filter bar (built once; counts refreshed by rebuilding only when counts change)
    const tc = countBy(data.rows, (r) => r.type), sc = countBy(data.rows, (r) => r.src), rc = countBy(data.rows, (r) => r.res);
    const sig = JSON.stringify([tc, sc, rc]);
    const fbw = root.querySelector(".sv-fb");
    if (!S.fb || !fbw.contains(S.fb) || S.fbLang !== lang()) {
      S.fbLang = lang();
      fbw.dataset.sig = sig;
      S.fb = comp("filterBar", {
        types: TYPES, counts: tc, team: false, search: true,
        extraRows: [
          { key: "fuente", label: t("supervision.filter.source"), options: SRC_IDS.map((id) => ({ id, label: srcLabel(id), count: sc[id] || 0 })) },
          { key: "resultado", label: t("supervision.filter.result"), options: RES_IDS.map((id) => ({ id, label: resLabel(id), count: rc[id] || 0 })) },
        ],
        onChange: (st) => { S.filter = st; if (S.renderList) S.renderList(); },
      });
      if (S.fb && S.fb.state) S.filter = S.fb.state;
      fbw.replaceChildren(S.fb || h("div", { class: "sv-muted sv-small" }, t("supervision.filter.unavailable")));
    } else if (fbw.dataset.sig !== sig && S.fb.setCounts) {
      fbw.dataset.sig = sig;
      const ex = {};
      for (const id of SRC_IDS) ex["fuente/" + id] = sc[id] || 0;
      for (const id of RES_IDS) ex["resultado/" + id] = rc[id] || 0;
      S.fb.setCounts(tc, ex);
    }
    const p = params ? decodeURIComponent(String(params).split("/")[0]) : "";
    if (p) S.selected = p;
    const sel = S.selected ? findRow(data, S.selected) : null;
    const renderList = () => {
      const list = applyFilter(data.rows);
      const lw = root.querySelector(".sv-list-wrap");
      const st = lw.scrollTop;
      lw.replaceChildren(streamRows(list, data));
      lw.scrollTop = st;
      root.querySelector(".sv-count").textContent = t("supervision.count", { shown: list.length, total: data.rows.length });
    };
    S.renderList = renderList;
    renderList();
    root.querySelector(".sv-right").replaceChildren(votesPanel(sel || data.rows.find((r) => r.c) || null), railsPanel(data.rows), logPanel(data));
    if (p && p !== S.drawerFor) {
      S.drawerFor = p;
      comp("drawer", { wide: true, onClose: () => { S.drawerFor = null; if (/^#supervision\//.test(location.hash)) location.hash = "#supervision"; },
        title: sel ? t("supervision.drawer.title", { id: String(sel.dec.id) }) : t("supervision.drawer.title_raw", { id: p }), body: sel ? drawerBody(sel, data) : comp("empty", t("supervision.drawer.not_found")) || h("div", {}, t("supervision.drawer.not_found_short")) });
    }
    if (!p) S.drawerFor = null;
  }

  function skeleton(root) {
      S.lang = lang(); S.fb = null;
      root.replaceChildren(h("div", { class: "sv-layout" },
        h("div", { class: "sv-strip-wrap" }, window.ui.loading()),
        h("div", { class: "sv-main" },
          h("div", { class: "sv-queue-wrap" }),
          h("section", { class: "sv-panel" },
            h("div", { class: "sv-ph" }, h("b", {}, t("supervision.doing")), h("span", { class: "sv-mono sv-muted sv-count" }, "")),
            h("div", { class: "sv-fb" }),
            h("div", { class: "sv-list-wrap" }, window.ui.loading()))),
        h("aside", { class: "sv-right" })));
  }

  window.Screens["supervision"] = {
    get title() { return t("supervision.title"); },
    mount(root, params) {
      S.root = root; S.drawerFor = null; S.params = params;
      root.classList.add("scr-supervision");
      skeleton(root);
    },
    async refresh(root, data, params) {
      S.lastData = data; S.params = params;
      try {
        const d = await load();
        if (S.root !== root || !root.isConnected) return;
        if (S.lang !== lang()) { skeleton(root); S.drawerFor = null; }   // language changed: rebuild the static frame
        render(root, d, params);
      } catch (e) {
        console.error("supervision", e);
        const lw = root.querySelector(".sv-list-wrap");
        if (lw) lw.replaceChildren(comp("error", e) || h("div", {}, t("supervision.error", { msg: e.message })));
      }
    },
    onParams(root, params) { S.params = params; if (!params) { S.drawerFor = null; comp("closeDrawer", true); } },
    unmount(root) { S.root = null; S.fb = null; S.drawerFor = null; root.classList.remove("scr-supervision"); },
  };
})();
