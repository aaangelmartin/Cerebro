/* Laboratorio: ciclo de las lecciones, lista filtrable, acciones Promover/Retirar, avisos y novedades.
   Contrato: bazaar/dashboard/CONTRACT.md. Solo lee api.lessons(), api.novelty(); escribe POST lessons/<id>. */
(function () {
  "use strict";
  const U = () => window.ui || {};
  const A = () => window.api || {};
  const t = (k, v) => window.I18N.t(k, v);

  // ---------- helpers ----------
  function el(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "html") n.innerHTML = v; // only for our own static SVG
      else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids.flat()) {
      if (c == null || c === false) continue;
      n.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return n;
  }
  const num = (v) => (typeof v === "number" && isFinite(v) ? v : null);
  const fmt = (v, d = 2) => (num(v) == null ? "—" : v.toLocaleString(window.I18N.locale, { minimumFractionDigits: d, maximumFractionDigits: d }));
  const pct = (v) => (num(v) == null ? "—" : (v > 0 ? "+" : "") + Math.round(v * 100) + " %");
  function fmtTime(ts) {
    if (U().fmtTime) try { return U().fmtTime(ts, false); } catch (e) { /* fall through */ }
    if (!num(ts)) return "—";
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString(window.I18N.locale, { hour: "2-digit", minute: "2-digit" });
  }
  function fmtAgo(ts) {
    if (!num(ts)) return "—";
    const s = Math.max(0, Date.now() / 1000 - ts);
    if (s < 60) return t("laboratorio.ago.s", { n: Math.round(s) });
    if (s < 3600) return t("laboratorio.ago.min", { n: Math.round(s / 60) });
    if (s < 86400) return t("laboratorio.ago.h", { n: Math.round(s / 3600) });
    return t("laboratorio.ago.d", { n: Math.round(s / 86400) });
  }
  async function setLesson(id, status, why) {
    if (A().setLesson) return A().setLesson(id, status, why);
    return post(`lessons/${encodeURIComponent(id)}`, { status, why });
  }
  async function post(path, body) {
    const res = await fetch(`api/${path}`, {
      method: "POST", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-Dashboard": "1" },
      body: JSON.stringify(body || {}),
    });
    let data = null;
    try { data = await res.json(); } catch (e) { /* empty */ }
    if (!res.ok) {
      const err = new Error((data && (data.message || data.error)) || `HTTP ${res.status}`);
      err.status = res.status;
      throw err;
    }
    return data;
  }
  async function confirmBox(opts) {
    if (U().confirm) return U().confirm(opts);
    return false; // never window.confirm
  }
  function toast(type, title, text) {
    if (U().toast) try { U().toast({ type, title, text }); return; } catch (e) { /* ignore */ }
  }
  const loading = () => (U().loading ? U().loading() : el("div", { class: "lab-state" }, t("common.loading")));
  const empty = (x) => (U().empty ? U().empty(x) : el("div", { class: "lab-state" }, x));
  const errorBox = (e) => (U().error ? U().error(e) : el("div", { class: "lab-state lab-bad" }, t("laboratorio.error", { msg: e && e.message || e })));

  // ---------- icons (inline SVG, stroke = currentColor) ----------
  const P = {
    proposed: '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2V16h5v-.1c0-.8.4-1.5 1-2A6 6 0 0 0 12 3z"/>',
    shadow: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    canary: '<path d="M16 7h.01M3.4 18H12a8 8 0 0 0 8-8V7a4 4 0 0 0-7.3-2.2L2 20"/><path d="M20 7l2 .5-2 .5M10 18v3M14 17.7V21"/>',
    active: '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>',
    retired: '<rect x="3" y="4" width="18" height="4"/><path d="M5 8v12h14V8M10 12h4"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    up: '<path d="M12 19V5M6 11l6-6 6 6"/>',
    duel: '<path d="M14.5 17.5L3 6V3h3l11.5 11.5M13 19l6-6M16 16l4 4M19 21l2-2M9.5 14.5L4 20M5 14l5 5"/>',
    dealer: '<path d="M3 9l2-5h14l2 5M3 9v11h18V9M3 9h18M9 20v-6h6v6"/>',
    market: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    broker: '<path d="M4 7h14l-3-3M20 17H6l3 3"/>',
    global: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10 21h4"/>',
    flask: '<path d="M9 3h6M10 3v6L4 19a1 1 0 0 0 .9 1.5h14.2A1 1 0 0 0 20 19l-6-10V3"/>',
    down: '<path d="M12 5v14M6 13l6 6 6-6"/>',
  };
  const icon = (k, size = 14) => el("span", {
    class: "lab-ic",
    html: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="square" stroke-linejoin="miter" aria-hidden="true">${P[k] || ""}</svg>`,
  });

  // labels are read on every render so they follow the language
  const STATES = ["proposed", "shadow", "canary", "active", "retired"].map((id) => ({
    id, get label() { return t("laboratorio.state." + id); }, get sub() { return t("laboratorio.state." + id + ".sub"); },
  }));
  const STATE = Object.fromEntries(STATES.map((s) => [s.id, s]));
  const NEXT = { proposed: "shadow", shadow: "canary", canary: "active" };
  const SCOPES = [["duelos", "duel"], ["dealers", "dealer"], ["mercado", "market"], ["broker", "broker"], ["global", "global"]]
    .map(([id, icon]) => ({ id, icon, get label() { return t("laboratorio.scope." + id); } }));
  const SCOPE = Object.fromEntries(SCOPES.map((s) => [s.id, s]));
  function scopeOf(scope) {
    const s = String(scope || "");
    if (s === "duel") return "duelos";
    if (s === "dealer" || s.startsWith("dealer:")) return "dealers";
    if (s === "market") return "mercado";
    if (s === "broker") return "broker";
    return "global";
  }
  function scopeLabel(scope) {
    const s = String(scope || "");
    if (s.startsWith("dealer:")) return "Dealer " + s.slice(7);
    return (SCOPE[scopeOf(s)] || {}).label || s;
  }

  const stateChip = (st) => el("span", { class: `lab-chip lab-st-${st}` }, icon(st, 12), (STATE[st] || {}).label || st || "—");
  const scopeChip = (scope) => {
    const sc = scopeOf(scope);
    return el("span", { class: `lab-chip lab-sc lab-sc-${sc}`, title: String(scope || "") }, icon(SCOPE[sc].icon, 12), scopeLabel(scope));
  };
  function weightBar(w) {
    const v = num(w) == null ? 0 : Math.max(0, Math.min(1, w));
    const bar = el("span", { class: "lab-wbar" }, el("span", { style: `width:${Math.round(v * 100)}%` }));
    return el("span", { class: "lab-weight" }, bar, el("span", { class: "lab-mono" }, num(w) == null ? "—" : fmt(w)));
  }

  // ---------- state ----------
  const S = { data: null, novelty: null, err: null, filter: { states: new Set(), scopes: new Set(), q: "" }, busy: new Set(), drawerId: null };

  function filtered() {
    const f = S.filter;
    const q = f.q.trim().toLowerCase();
    return (S.data && S.data.lessons || []).filter((l) => {
      if (f.states.size && !f.states.has(l.status)) return false;
      if (f.scopes.size && !f.scopes.has(scopeOf(l.scope))) return false;
      if (q && !(`${l.id} ${l.rule} ${l.scope}`.toLowerCase().includes(q))) return false;
      return true;
    }).sort((a, b) => {
      const order = { active: 0, canary: 1, shadow: 2, proposed: 3, retired: 4 };
      return (order[a.status] ?? 9) - (order[b.status] ?? 9) || (b.weight || 0) - (a.weight || 0) || (b.updated || 0) - (a.updated || 0);
    });
  }

  // ---------- render ----------
  function renderPipeline(box) {
    const lessons = S.data && S.data.lessons || [];
    const counts = Object.fromEntries(STATES.map((s) => [s.id, 0]));
    for (const l of lessons) if (l.status in counts) counts[l.status]++;
    const actives = lessons.filter((l) => l.status === "active" && num(l.weight) != null);
    const avgW = actives.length ? actives.reduce((s, l) => s + l.weight, 0) / actives.length : null;
    const day = Date.now() / 1000 - 86400;
    box.replaceChildren(...STATES.flatMap((s, i) => {
      const today = (S.data.notices || []).filter((n) => n.kind === "lesson_status" && n.to === s.id && (n.ts || 0) > day).length;
      const card = el("button", {
        class: `lab-stage lab-st-${s.id}` + (S.filter.states.has(s.id) ? " is-on" : ""), type: "button",
        title: t("laboratorio.filter.by", { label: s.label }),
        onclick: () => { toggle(S.filter.states, s.id); paint(); },
      },
      el("div", { class: "lab-stage-h" }, icon(s.id, 15), el("span", {}, s.label), el("b", { class: "lab-mono" }, counts[s.id])),
      el("div", { class: "lab-blocks" }, ...Array.from({ length: Math.min(counts[s.id], 16) }, () => el("i"))),
      el("div", { class: "lab-stage-sub" }, s.sub),
      el("div", { class: "lab-stage-f lab-mono" }, s.id === "active" ? t("laboratorio.pipe.avg_weight", { w: avgW == null ? "—" : fmt(avgW) }) : (today ? t("laboratorio.pipe.today", { n: today }) : " ")));
      return i < STATES.length - 1 ? [card, el("span", { class: "lab-arrow" }, "›")] : [card];
    }));
    return lessons.length;
  }

  function toggle(set, v) { set.has(v) ? set.delete(v) : set.add(v); }

  function renderFilters(box) {
    const lessons = S.data && S.data.lessons || [];
    const sc = {}; const st = {};
    for (const l of lessons) { st[l.status] = (st[l.status] || 0) + 1; const k = scopeOf(l.scope); sc[k] = (sc[k] || 0) + 1; }
    const chips1 = STATES.map((s) => el("button", {
      type: "button", class: `lab-fchip lab-st-${s.id}` + (S.filter.states.has(s.id) ? " is-on" : ""),
      onclick: () => { toggle(S.filter.states, s.id); paint(); },
    }, icon(s.id, 12), s.label, el("span", { class: "lab-mono lab-n" }, st[s.id] || 0)));
    const chips2 = SCOPES.map((s) => el("button", {
      type: "button", class: `lab-fchip lab-sc-${s.id}` + (S.filter.scopes.has(s.id) ? " is-on" : ""),
      onclick: () => { toggle(S.filter.scopes, s.id); paint(); },
    }, icon(s.icon, 12), s.label, el("span", { class: "lab-mono lab-n" }, sc[s.id] || 0)));
    let search = box.querySelector("input.lab-search");
    const focused = search && document.activeElement === search;
    if (!search) {
      search = el("input", { class: "lab-search", type: "search", placeholder: t("laboratorio.filter.search"), "aria-label": t("laboratorio.filter.search_aria") });
      search.addEventListener("input", () => { S.filter.q = search.value; paintList(); });
    }
    const clear = (S.filter.states.size || S.filter.scopes.size || S.filter.q) ? el("button", {
      type: "button", class: "lab-link", onclick: () => { S.filter.states.clear(); S.filter.scopes.clear(); S.filter.q = ""; search.value = ""; paint(); },
    }, t("laboratorio.filter.clear")) : null;
    box.replaceChildren(
      el("div", { class: "lab-frow" }, ...chips1, el("span", { class: "lab-grow" }), clear, el("label", { class: "lab-searchbox" }, icon("search", 13), search)),
      el("div", { class: "lab-frow" }, el("span", { class: "lab-flabel" }, t("laboratorio.col.scope")), ...chips2));
    if (focused) search.focus();
  }

  function actionButtons(l) {
    const busy = S.busy.has(l.id);
    const out = [];
    if (NEXT[l.status]) out.push(el("button", { type: "button", class: "lab-btn", disabled: busy, onclick: (e) => { e.stopPropagation(); change(l, NEXT[l.status]); } }, icon("up", 12), t("laboratorio.promote")));
    if (l.status !== "retired") out.push(el("button", { type: "button", class: "lab-btn lab-btn-q", disabled: busy, onclick: (e) => { e.stopPropagation(); change(l, "retired"); } }, t("laboratorio.retire")));
    else out.push(el("button", { type: "button", class: "lab-btn lab-btn-q", disabled: busy, onclick: (e) => { e.stopPropagation(); change(l, "proposed"); } }, t("laboratorio.restore")));
    return el("div", { class: "lab-actions" }, ...out);
  }

  function paintList() {
    const box = S.root && S.root.querySelector(".lab-list");
    if (!box) return;
    if (S.err && !S.data) { box.replaceChildren(errorBox(S.err)); return; }
    if (!S.data) { box.replaceChildren(loading()); return; }
    const rows = filtered();
    const head = el("div", { class: "lab-row lab-head" },
      el("span", {}, t("laboratorio.col.lesson")), el("span", {}, t("laboratorio.col.scope")), el("span", {}, t("laboratorio.col.state")), el("span", {}, t("laboratorio.col.weight")),
      el("span", {}, t("laboratorio.col.evidence")), el("span", {}, t("laboratorio.col.effect")), el("span", {}, t("laboratorio.col.updated")), el("span", {}, ""));
    if (!rows.length) {
      box.replaceChildren(head, empty((S.data.lessons || []).length ? t("laboratorio.empty_filter") : t("laboratorio.empty_all")));
      return;
    }
    box.replaceChildren(head, ...rows.map((l) => {
      const lift = l.backtest && num(l.backtest.lift);
      return el("div", {
        class: `lab-row lab-st-${l.status}`, role: "button", tabindex: "0",
        onclick: () => openLesson(l.id),
        onkeydown: (e) => { if (e.key === "Enter") openLesson(l.id); },
      },
      el("span", { class: "lab-rule", title: l.rule }, `«${l.rule || l.id}»`),
      el("span", {}, scopeChip(l.scope)),
      el("span", {}, stateChip(l.status)),
      el("span", {}, weightBar(l.weight)),
      el("span", { class: "lab-mono lab-muted" }, window.I18N.plural(l.sources, "laboratorio.evidence", { cases: l.n ?? "—", n: l.sources ?? "—" })),
      el("span", { class: "lab-mono " + (lift == null ? "lab-muted" : lift > 0 ? "lab-ok" : lift < 0 ? "lab-bad" : "") }, pct(lift)),
      el("span", { class: "lab-mono lab-muted", title: fmtTime(l.updated) }, fmtAgo(l.updated)),
      actionButtons(l));
    }));
  }

  function noticeIcon(n) {
    if (n.kind === "lesson_status") {
      if (n.to === "retired") return "down";
      if (n.to === "active") return "active";
      return n.to in STATE ? n.to : "up";
    }
    if (n.kind === "hypotheses") return "flask";
    return "bell";
  }
  function paintSide() {
    const nb = S.root && S.root.querySelector(".lab-notices");
    const vb = S.root && S.root.querySelector(".lab-novelty");
    if (nb) {
      const ns = ((S.data && S.data.notices) || []).slice().sort((a, b) => (b.ts || 0) - (a.ts || 0)).slice(0, 20);
      S.root.querySelector(".lab-notices-n").textContent = ns.length || "";
      nb.replaceChildren(...(!S.data ? [S.err ? errorBox(S.err) : loading()] : ns.length ? ns.map((n) => el("div", {
        class: `lab-note lab-nk-${n.to || n.kind}` + (n.lesson_id ? " is-link" : ""),
        onclick: n.lesson_id ? () => openLesson(n.lesson_id) : null,
      }, icon(noticeIcon(n), 14), el("div", { class: "lab-note-b" }, el("div", {}, n.text || n.kind), n.lesson_id ? el("div", { class: "lab-muted lab-small" }, `${n.lesson_id} · ${scopeLabel(n.scope)}`) : null),
      el("span", { class: "lab-mono lab-muted lab-small" }, fmtTime(n.ts)))) : [empty(t("laboratorio.notices.empty"))]));
    }
    if (vb) {
      const items = S.novelty && (S.novelty.items || S.novelty.novelty || (Array.isArray(S.novelty) ? S.novelty : [])) || [];
      const list = items.slice().sort((a, b) => (b.at || b.ts || 0) - (a.at || a.ts || 0)).slice(0, 15);
      S.root.querySelector(".lab-novelty-n").textContent = list.length || "";
      vb.replaceChildren(...(S.novelty == null ? [S.novErr ? empty(t("laboratorio.novelty.unavailable")) : loading()] : list.length ? list.map((n) => {
        const d = n.detail;
        const text = typeof d === "string" ? d : d ? JSON.stringify(d).slice(0, 160) : "";
        return el("div", { class: "lab-note lab-nk-novelty" }, icon("bell", 14),
          el("div", { class: "lab-note-b" }, el("div", {}, n.title || n.kind || t("laboratorio.novelty.item")), text ? el("div", { class: "lab-muted lab-small" }, text) : null),
          el("span", { class: "lab-mono lab-muted lab-small" }, fmtTime(n.at || n.ts)));
      }) : [empty(t("laboratorio.novelty.empty"))]));
    }
  }

  function paint() {
    if (!S.root) return;
    const pipe = S.root.querySelector(".lab-pipe");
    const total = S.root.querySelector(".lab-total");
    if (S.data) {
      const n = renderPipeline(pipe);
      total.textContent = t("laboratorio.total", { n });
      renderFilters(S.root.querySelector(".lab-filters"));
    } else {
      pipe.replaceChildren(S.err ? errorBox(S.err) : loading());
    }
    paintList();
    paintSide();
    if (S.drawerId) renderDrawer(S.drawerId, false);
  }

  // ---------- actions ----------
  async function change(l, to) {
    const verb = to === "retired" ? "retire" : to === "proposed" ? "restore" : "promote";
    const ok = await confirmBox({
      title: t("laboratorio.confirm.title." + verb),
      text: t("laboratorio.confirm.text", { rule: l.rule, from: (STATE[l.status] || {}).label || l.status, to: (STATE[to] || {}).label || to }) +
        (to === "active" ? " " + t("laboratorio.confirm.to_active") : to === "retired" ? " " + t("laboratorio.confirm.to_retired") : ""),
      confirmLabel: t("laboratorio.confirm.yes." + verb), danger: to === "retired",
    });
    if (!ok) return;
    S.busy.add(l.id); paintList();
    try {
      const res = await setLesson(l.id, to, "dashboard");
      const i = (S.data.lessons || []).findIndex((x) => x.id === l.id);
      if (i >= 0 && res && res.id) S.data.lessons[i] = res;
      toast("outcome", t("laboratorio.toast.updated"), t("laboratorio.toast.now", { id: l.id, state: (STATE[to] || {}).label || to }));
    } catch (e) {
      toast("error", t("laboratorio.toast.fail"), e.message || String(e));
      if (!U().toast) alertInline(t("laboratorio.toast.fail_inline", { id: l.id, msg: e.message }));
    } finally {
      S.busy.delete(l.id);
      paint();
      load(true);
    }
  }
  function alertInline(msg) {
    const b = S.root && S.root.querySelector(".lab-msg");
    if (b) { b.textContent = msg; b.hidden = false; setTimeout(() => { b.hidden = true; }, 6000); }
  }

  // ---------- drawer ----------
  function kv(k, v) { return el("div", { class: "lab-kv" }, el("span", { class: "lab-muted" }, k), el("span", { class: "lab-mono" }, v)); }
  function renderDrawer(id, open) {
    const l = (S.data && S.data.lessons || []).find((x) => x.id === id);
    if (!l) {
      if (open && U().drawer) U().drawer({ title: t("laboratorio.drawer.title", { id }), body: S.data ? empty(t("laboratorio.drawer.missing")) : loading() });
      return;
    }
    const bt = l.backtest || {};
    const hist = (S.data.notices || []).filter((n) => n.lesson_id === l.id && n.kind === "lesson_status").sort((a, b) => (a.ts || 0) - (b.ts || 0));
    const live = bt.live || {};
    const shadow = bt.shadow || {};
    const body = el("div", { class: "scr-laboratorio lab-drawer" },
      el("div", { class: "lab-drow" }, stateChip(l.status), scopeChip(l.scope), el("span", { class: "lab-mono lab-muted" }, `v${l.version ?? 1} · ${l.created_by || "—"}`)),
      el("p", { class: "lab-drule" }, l.rule || "—"),
      actionButtons(l),
      el("h4", {}, t("laboratorio.drawer.weight")),
      weightBar(l.weight),
      kv(t("laboratorio.drawer.cases"), t("laboratorio.drawer.cases_v", { cases: l.n ?? "—", n: l.sources ?? "—" })),
      el("h4", {}, t("laboratorio.drawer.backtest")),
      kv(t("laboratorio.drawer.hit"), num(bt.hit) == null ? "—" : `${Math.round(bt.hit * 100)} %` + (num(bt.baseline_hit) != null ? " " + t("laboratorio.drawer.base", { n: Math.round(bt.baseline_hit * 100) }) : "")),
      kv(t("laboratorio.drawer.lift"), pct(bt.lift)),
      bt.kind ? kv(t("laboratorio.drawer.type"), bt.kind) : null,
      num(bt.n_eff) != null ? kv(t("laboratorio.drawer.n_eff"), fmt(bt.n_eff, 1)) : null,
      bt.note ? kv(t("laboratorio.drawer.note"), bt.note) : null,
      bt.gate ? el("div", { class: "lab-gate" }, ...Object.entries(bt.gate).map(([k, v]) => el("span", { class: "lab-chip " + (v ? "lab-ok" : "lab-muted") }, (v ? "✓ " : "· ") + k))) : null,
      el("h4", {}, t("laboratorio.drawer.uses")),
      kv(t("laboratorio.drawer.live"), t("laboratorio.drawer.live_v", { s: live.s ?? 0, f: live.f ?? 0 }) + (num(bt.live_hit) != null ? " · " + t("laboratorio.drawer.live_hit", { n: Math.round(bt.live_hit * 100) }) : "")),
      shadow.n != null ? kv(t("laboratorio.drawer.shadow"), t("laboratorio.drawer.shadow_v", { n: shadow.n, net: fmt(shadow.net, 1), pos: shadow.pos ?? 0, neg: shadow.neg ?? 0 })) : null,
      bt.sim && bt.sim.applicable ? kv(t("laboratorio.drawer.sim"), t("laboratorio.drawer.sim_v", { n: bt.sim.episodes ?? "—", delta: fmt(bt.sim.delta, 2) })) : null,
      el("h4", {}, t("laboratorio.drawer.params")),
      Object.keys(l.params || {}).length ? el("pre", { class: "lab-pre" }, JSON.stringify(l.params, null, 2)) : el("div", { class: "lab-muted" }, t("laboratorio.drawer.no_params")),
      el("h4", {}, t("laboratorio.drawer.evidence", { n: (l.evidence || []).length })),
      (l.evidence || []).length ? el("div", { class: "lab-ev" }, ...(l.evidence || []).map((e) => el("span", { class: "lab-mono" }, e))) : el("div", { class: "lab-muted" }, t("laboratorio.drawer.no_evidence")),
      el("h4", {}, t("laboratorio.drawer.history")),
      hist.length ? el("div", {}, ...hist.map((n) => el("div", { class: "lab-hist" },
        el("span", { class: "lab-mono lab-muted" }, fmtTime(n.ts)),
        el("span", {}, `${(STATE[n.from] || {}).label || n.from || "—"} → ${(STATE[n.to] || {}).label || n.to}`),
        el("span", { class: "lab-muted" }, n.by || "")))) : el("div", { class: "lab-muted" }, t("laboratorio.drawer.no_history")),
      kv(t("laboratorio.col.updated"), `${fmtTime(l.updated)} (${fmtAgo(l.updated)})`));
    const d = document.querySelector(".lab-drawer");
    if (!open && d && d.isConnected) { d.replaceWith(body); return; }
    if (open && U().drawer) U().drawer({ title: t("laboratorio.drawer.title", { id: l.id }), body, wide: true, onClose: closedDrawer });
  }
  function closedDrawer() {
    S.drawerId = null;
    if (location.hash.startsWith("#laboratorio/")) history.replaceState(null, "", "#laboratorio");
  }
  function openLesson(id) {
    S.drawerId = id;
    const want = `#laboratorio/${encodeURIComponent(id)}`;
    if (location.hash !== want) history.replaceState(null, "", want);
    renderDrawer(id, true);
  }

  // ---------- data ----------
  async function load(force) {
    const api = A();
    try {
      const d = api.lessons ? await api.lessons() : await (await fetch("api/lessons", { cache: "no-store" })).json();
      S.data = { lessons: Array.isArray(d && d.lessons) ? d.lessons : [], notices: Array.isArray(d && d.notices) ? d.notices : [] };
      S.err = null;
    } catch (e) { S.err = e; }
    try {
      S.novelty = api.novelty ? await api.novelty() : await (await fetch("api/novelty", { cache: "no-store" })).json();
      S.novErr = null;
    } catch (e) { S.novErr = e; if (S.novelty == null) S.novelty = { items: [] }; }
  }

  window.Screens = window.Screens || {};
  window.Screens["laboratorio"] = {
    get title() { return t("laboratorio.title"); },
    mount(root, params) {
      S.root = root;
      S.drawerId = null;
      root.classList.add("scr-laboratorio");
      root.replaceChildren(
        el("section", { class: "lab-panel lab-cycle" },
          el("div", { class: "lab-ph" }, el("h2", {}, t("laboratorio.cycle")), el("span", { class: "lab-total lab-mono lab-muted" }), el("span", { class: "lab-grow" }), el("span", { class: "lab-cycle-age lab-mono lab-ok" })),
          el("div", { class: "lab-pipe" }, loading())),
        el("div", { class: "lab-msg", hidden: true }),
        el("div", { class: "lab-grid" },
          el("section", { class: "lab-panel" },
            el("div", { class: "lab-ph" }, el("h2", {}, t("laboratorio.lessons"))),
            el("div", { class: "lab-filters" }),
            el("div", { class: "lab-list" }, loading())),
          el("div", { class: "lab-side" },
            el("section", { class: "lab-panel" }, el("div", { class: "lab-ph" }, el("h2", {}, t("laboratorio.notices.title")), el("span", { class: "lab-notices-n lab-mono lab-muted" })), el("div", { class: "lab-notices" }, loading())),
            el("section", { class: "lab-panel" }, el("div", { class: "lab-ph" }, el("h2", {}, t("laboratorio.novelty.title")), el("span", { class: "lab-novelty-n lab-mono lab-muted" })), el("div", { class: "lab-novelty" }, loading())))));
      if (params) S.pendingOpen = decodeURIComponent(params);
    },
    async refresh(root, data, params) {
      S.root = root;
      await load();
      const lab = data && data.lab;
      const age = root.querySelector(".lab-cycle-age");
      if (age) age.textContent = lab && num(lab.updated) ? t("laboratorio.last_cycle", { ago: fmtAgo(lab.updated) }) : "";
      paint();
      const p = params ? decodeURIComponent(params) : null;
      if (p && S.pendingOpen === p && S.data) { S.pendingOpen = null; openLesson(p); }
    },
    onParams(root, params) {
      const p = params ? decodeURIComponent(params) : null;
      if (p) { if (S.data) openLesson(p); else S.pendingOpen = p; }
      else if (S.drawerId && U().closeDrawer) { S.drawerId = null; U().closeDrawer(true); }
    },
    unmount(root) { S.root = null; S.drawerId = null; root.classList.remove("scr-laboratorio"); },
  };
})();
