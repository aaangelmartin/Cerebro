/* window.ui — shared components for the supervisor dashboard (see CONTRACT.md). Everything escapes text. */
(function () {
  "use strict";
  const SVGNS = "http://www.w3.org/2000/svg";

  // ------------------------------------------------------------------ el
  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v === undefined || v === null || v === false) continue;
        if (k === "class" || k === "className") node.className = Array.isArray(v) ? v.filter(Boolean).join(" ") : v;
        else if (k === "style" && typeof v === "object") Object.assign(node.style, v);
        else if (k === "dataset" && typeof v === "object") Object.assign(node.dataset, v);
        else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2).toLowerCase(), v);
        else if (k === "html") node.innerHTML = v;            // only for trusted, built-here markup (icons)
        else if (k === "text") node.textContent = v;
        else if (v === true) node.setAttribute(k, "");
        else node.setAttribute(k, v);
      }
    }
    append(node, children);
    return node;
  }
  function append(node, children) {
    for (const c of children.flat(Infinity)) {
      if (c === undefined || c === null || c === false) continue;
      node.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return node;
  }
  function esc(s) {
    return String(s === undefined || s === null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ------------------------------------------------------------------ icons (inline SVG, stroke = currentColor)
  const ICONS = {
    compra: '<path d="M17 7 7 17"/><path d="M15 17H7V9"/>',
    venta: '<path d="M7 17 17 7"/><path d="M9 7h8v8"/>',
    cambio: '<path d="M4 8h13l-3-3"/><path d="M20 16H7l3 3"/>',
    puja: '<path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V12"/><path d="M11 11.5v-2a1.5 1.5 0 0 1 3 0V12"/><path d="M14 10.5a1.5 1.5 0 0 1 3 0V12"/><path d="M17 11.5a1.5 1.5 0 0 1 3 0V15a6 6 0 0 1-6 6h-1.5a6 6 0 0 1-4.6-2.2L5 15.5a1.6 1.6 0 0 1 2.4-2.1L8 14"/>',
    duelo: '<path d="M14.5 17.5 3 6V3h3l11.5 11.5"/><path d="m13 19 6-6"/><path d="m16 16 4 4"/><path d="m19 21 2-2"/><path d="M9.5 6.5 6 3"/><path d="m21 3-7 7"/><path d="M3 21l4.5-4.5"/>',
    dealer: '<path d="M3 9 4.5 4h15L21 9"/><path d="M3 9h18v1.5a3 3 0 0 1-6 0 3 3 0 0 1-6 0 3 3 0 0 1-6 0Z"/><path d="M5 12.5V20h14v-7.5"/><path d="M10 20v-4h4v4"/>',
    anuncio: '<path d="M3 11v3l11 5V6L3 11Z"/><path d="M14 9a4 4 0 0 1 0 7"/><path d="M6 15.5V19h3v-2.2"/>',
    home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9v12h14V9"/><path d="M10 21v-6h4v6"/>',
    coleccion: '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>',
    mercado: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    competicion: '<path d="M8 21h8"/><path d="M12 17v4"/><path d="M7 4h10v5a5 5 0 0 1-10 0Z"/><path d="M17 5h3v2a3 3 0 0 1-3 3"/><path d="M7 5H4v2a3 3 0 0 0 3 3"/>',
    rivales: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7"/><path d="M18 14a6.5 6.5 0 0 1 3.5 6"/>',
    supervision: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    laboratorio: '<path d="M9 3h6"/><path d="M10 3v6L4.5 19a1.5 1.5 0 0 0 1.3 2h12.4a1.5 1.5 0 0 0 1.3-2L14 9V3"/><path d="M7 15h10"/>',
    bot: '<rect x="5" y="5" width="14" height="14"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
    bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/>',
    lock: '<rect x="4" y="11" width="16" height="10"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    alert: '<circle cx="12" cy="12" r="9"/><path d="M12 7v6"/><path d="M12 16.5v.5"/>',
    trend: '<path d="m3 17 6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    flask: '<path d="M9 3h6"/><path d="M10 3v6L4.5 19a1.5 1.5 0 0 0 1.3 2h12.4a1.5 1.5 0 0 0 1.3-2L14 9V3"/>',
    close: '<path d="M6 6l12 12M18 6 6 18"/>',
    arrow: '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
    check: '<path d="m5 12 5 5 9-10"/>',
    off: '<circle cx="12" cy="12" r="9"/><path d="M5.5 5.5l13 13"/>',
    cloud: '<path d="M7 18a5 5 0 1 1 1-9.9A6 6 0 0 1 19.5 10 4 4 0 0 1 18 18Z"/>',
    copy: '<rect x="8" y="8" width="13" height="13"/><path d="M16 8V3H3v13h5"/>',
    shield: '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6Z"/>',
    target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
    chevron: '<path d="m6 9 6 6 6-6"/>',
    cerebro: '<path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 3 3h1V4H9Z"/><path d="M15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-3 3h-1V4h1Z"/><path d="M7 10h3M14 14h3"/>',
  };
  ICONS.inicio = ICONS.home;
  ICONS.duelos = ICONS.duelo;
  function iconSvg(name, size) {
    const s = size || 14;
    return '<svg class="ic" width="' + s + '" height="' + s + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="1.8" stroke-linecap="square" stroke-linejoin="miter" aria-hidden="true">' + (ICONS[name] || ICONS.anuncio) + "</svg>";
  }
  function icon(name, size) { return el("span", { class: "ic-wrap", html: iconSvg(name, size) }); }

  // ------------------------------------------------------------------ types
  const TYPES = ["compra", "venta", "cambio", "puja", "duelo", "dealer", "anuncio"];
  const TYPE_LABEL = { compra: "Compra", venta: "Venta", cambio: "Cambio", puja: "Puja", duelo: "Duelo", dealer: "Dealer", anuncio: "Anuncio" };
  function normType(t) {
    t = String(t || "").toLowerCase();
    return TYPES.includes(t) ? t : "anuncio";
  }
  function typeChip(type, label, count) {
    const t = normType(type);
    return el("span", { class: "chip type t-" + t }, icon(t, 13),
      el("span", { class: "chip-label" }, label || TYPE_LABEL[t]),
      count !== undefined && count !== null ? el("span", { class: "chip-count num" }, String(count)) : null);
  }

  // ------------------------------------------------------------------ row
  // cells: strings/nodes or {v, cls, align, title}. opts.cols sets grid-template-columns.
  function row({ type, cells, onClick, cols, cls, us, title } = {}) {
    const r = el("div", { class: ["ui-row", type ? "t-" + normType(type) : "t-none", onClick ? "clickable" : "", us ? "us" : "", cls], title });
    if (cols) r.style.gridTemplateColumns = cols;
    for (const c of cells || []) {
      if (c && typeof c === "object" && !(c instanceof Node) && "v" in c) {
        r.appendChild(el("div", { class: ["cell", c.cls, c.align ? "al-" + c.align : ""], title: c.title }, c.v));
      } else r.appendChild(el("div", { class: "cell" }, c));
    }
    if (onClick) {
      r.tabIndex = 0;
      r.addEventListener("click", onClick);
      r.addEventListener("keydown", (e) => { if (e.key === "Enter") onClick(e); });
    }
    return r;
  }

  // ------------------------------------------------------------------ tags
  const SOURCES = { opus: "Opus", consejo: "Consejo", reserva: "Reserva", codigo: "Código", "código": "Código" };
  function sourceTag(source, extra) {
    let s = String(source || "codigo").toLowerCase();
    if (s.startsWith("council")) s = "consejo";
    else if (s.startsWith("llm") || s.includes("opus") || s.includes("claude") || s === "sonnet" || s === "haiku") s = "opus";
    else if (s.includes("fallback") || s.includes("reserve")) s = "reserva";
    else if (!SOURCES[s]) s = "codigo";
    if (s === "código") s = "codigo";
    return el("span", { class: "tag src src-" + s }, SOURCES[s], extra ? el("span", { class: "num src-extra" }, " " + extra) : null);
  }

  const RESULTS = {
    enviado: ["Enviado", "ok"], vetado: ["Vetado", "bad"], rechazado: ["Rechazado", "bad"], pendiente: ["Pendiente", "warn"],
    sin_enviar: ["Sin enviar", "mute"], cerrado: ["Cerrado", "ok"], sin_acuerdo: ["Sin acuerdo", "mute"],
    sent: ["Enviado", "ok"], deal: ["Cerrado", "ok"], vetoed: ["Vetado", "bad"], veto: ["Vetado", "bad"], rejected: ["Rechazado", "bad"],
    refused: ["Rechazado", "bad"], error: ["Rechazado", "bad"], pending: ["Pendiente", "warn"], dry_run: ["Sin enviar", "mute"],
    skipped: ["Sin enviar", "mute"], closed: ["Cerrado", "ok"], no_deal: ["Sin acuerdo", "mute"], expired: ["Sin acuerdo", "mute"],
  };
  function resultChip(status) {
    const k = String(status || "pendiente").toLowerCase();
    const [label, tone] = RESULTS[k] || [String(status), "mute"];
    return el("span", { class: "tag res tone-" + tone }, label);
  }

  function teamName(id) {
    const s = String(id || "");
    const m = /^t0*(\d+)$/i.exec(s);
    if (m) return "Team " + m[1];
    const names = { abuela: "Abuela", chato: "Chato", rastro: "El Rastro", org: "Organización", house: "Organización" };
    return names[s.toLowerCase()] || s;
  }
  function teamTag(teamId, opts) {
    opts = opts || {};
    const id = String(teamId || "");
    const us = opts.us !== undefined ? !!opts.us : id.toLowerCase() === "t10";
    const name = opts.name || teamName(id);
    const m = /^t0*(\d+)$/i.exec(id);
    const initials = m ? "T" + m[1] : name.slice(0, 2).toUpperCase();
    return el("span", { class: ["tag team", us ? "us" : ""], title: name },
      opts.short ? null : el("span", { class: "team-sq num" }, us ? "10" : initials),
      el("span", { class: "team-name" }, us ? (opts.short ? "Nosotros" : "Team 10 · Nosotros") : name));
  }

  // ------------------------------------------------------------------ filter bar
  function filterBar(o) {
    o = o || {};
    const types = o.types || TYPES;
    const counts = o.counts || {};
    const state = { types: new Set(o.selected || types), team: o.teamValue || "todos", q: "", extra: {} };
    const root = el("div", { class: "filterbar" });
    const fire = () => { if (o.onChange) o.onChange(state); };
    const typeRow = el("div", { class: "fb-row" });
    const chips = {};
    for (const t of types) {
      const b = el("button", { type: "button", class: "fb-type", "aria-pressed": "true" }, o.chip ? o.chip(t, counts[t] || 0) : typeChip(t, null, counts[t] || 0));
      b.addEventListener("click", (e) => {
        if (e.altKey || e.metaKey) { state.types = new Set([t]); }
        else if (state.types.has(t)) state.types.delete(t); else state.types.add(t);
        sync(); fire();
      });
      chips[t] = b; typeRow.appendChild(b);
    }
    function sync() {
      for (const t of types) {
        chips[t].classList.toggle("off", !state.types.has(t));
        chips[t].setAttribute("aria-pressed", state.types.has(t) ? "true" : "false");
      }
    }
    if (o.team) {
      const seg = el("div", { class: "fb-seg" });
      const opts = [["todos", "Todos"], ["nosotros", "Nos."], ["rivales", "Riv."]];
      const btns = {};
      const sel = el("select", { class: "fb-select", "aria-label": "Equipo" }, el("option", { value: "" }, "Equipo"));
      for (let i = 1; i <= (o.teamCount || 18); i++) {
        const id = "t" + String(i).padStart(2, "0");
        sel.appendChild(el("option", { value: id }, teamName(id) + (i === 10 ? " · Nosotros" : "")));
      }
      function setTeam(v) {
        state.team = v;
        for (const [k, b] of Object.entries(btns)) b.classList.toggle("on", k === v);
        sel.value = /^t\d+$/.test(v) ? v : "";
        sel.classList.toggle("on", /^t\d+$/.test(v));
      }
      for (const [k, label] of opts) {
        btns[k] = el("button", { type: "button", class: "fb-seg-btn" }, label);
        btns[k].addEventListener("click", () => { setTeam(k); fire(); });
        seg.appendChild(btns[k]);
      }
      sel.addEventListener("change", () => { setTeam(sel.value || "todos"); fire(); });
      seg.appendChild(sel);
      setTeam(state.team);
      typeRow.appendChild(seg);
    }
    if (o.search) {
      const inp = el("input", { type: "search", class: "fb-search", placeholder: o.placeholder || "Buscar…", "aria-label": "Buscar" });
      let tm = null;
      inp.addEventListener("input", () => { clearTimeout(tm); tm = setTimeout(() => { state.q = inp.value.trim(); fire(); }, 150); });
      typeRow.appendChild(el("label", { class: "fb-search-wrap" }, icon("search", 13), inp));
    }
    root.appendChild(typeRow);
    const extraCounts = {};
    for (const ex of o.extraRows || []) {
      const key = ex.key || ex.label;
      state.extra[key] = new Set(ex.selected || []);
      const r = el("div", { class: "fb-row fb-extra" }, el("span", { class: "fb-extra-label" }, ex.label));
      for (const opt of ex.options || []) {
        const b = el("button", { type: "button", class: "fb-opt" }, opt.icon ? icon(opt.icon, 13) : null,
          el("span", null, opt.label), opt.count !== undefined ? el("span", { class: "chip-count num" }, String(opt.count)) : null);
        extraCounts[key + "/" + opt.id] = b.querySelector(".chip-count");
        const upd = () => b.classList.toggle("on", state.extra[key].has(opt.id));
        b.addEventListener("click", () => {
          if (ex.single) { const had = state.extra[key].has(opt.id); state.extra[key].clear(); if (!had) state.extra[key].add(opt.id); r.querySelectorAll(".fb-opt").forEach((x) => x.classList.remove("on")); }
          else if (state.extra[key].has(opt.id)) state.extra[key].delete(opt.id); else state.extra[key].add(opt.id);
          upd(); fire();
        });
        upd();
        r.appendChild(b);
      }
      root.appendChild(r);
    }
    sync();
    root.state = state;
    // Update the counts without rebuilding (keeps focus and selection).
    root.setCounts = (c, extra) => {
      for (const t of types) { const n = chips[t].querySelector(".chip-count"); if (n) n.textContent = String((c || {})[t] || 0); }
      for (const [k, v] of Object.entries(extra || {})) { const n = extraCounts[k]; if (n) n.textContent = String(v); }
    };
    // Does an item {type, team, text} pass the current filters? (helper for screens)
    root.matches = (item) => matchFilter(state, item);
    return root;
  }
  function matchFilter(state, item) {
    if (item.type && !state.types.has(normType(item.type))) return false;
    const team = String(item.team || "").toLowerCase();
    const teams = (item.teams || [team]).map((x) => String(x || "").toLowerCase());
    if (state.team === "nosotros" && !teams.includes("t10")) return false;
    if (state.team === "rivales" && (teams.includes("t10") || !teams.some((x) => /^t\d+$/.test(x)))) return false;
    if (/^t\d+$/.test(state.team) && !teams.includes(state.team)) return false;
    if (state.q && !String(item.text || "").toLowerCase().includes(state.q.toLowerCase())) return false;
    return true;
  }

  // ------------------------------------------------------------------ price bar
  // One price bar for every negotiation. Labels always visible: "Nosotros" (filled dot), "Ellos" (hollow dot),
  // "Límite" (wall), agreement zone (band). closed:{price} marks the deal, noDeal greys it out.
  function priceBar(o) {
    o = o || {};
    const vals = [o.min, o.max, o.limit, o.ours, o.theirs, o.closed && o.closed.price]
      .concat(o.zone || []).concat((o.history || []).flatMap((h) => typeof h === "number" ? [h] : [h.price, h.ours, h.theirs]))
      .filter((v) => typeof v === "number" && isFinite(v));
    let lo = typeof o.min === "number" ? o.min : Math.min(...vals);
    let hi = typeof o.max === "number" ? o.max : Math.max(...vals);
    if (!vals.length) { lo = 0; hi = 1; }
    if (hi <= lo) { const pad = Math.max(1, Math.abs(hi) * 0.1); lo -= pad; hi += pad; }
    const pos = (v) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100));
    const root = el("div", { class: ["pricebar", o.compact ? "compact" : "", o.noDeal ? "nodeal" : "", o.closed ? "closed" : ""] });
    // tint may be a colour or a type name ("compra", "venta", …) -> that type's colour
    if (o.tint) root.style.setProperty("--pb-tint", /^[a-z]+$/.test(o.tint) && TYPES.includes(o.tint) ? "var(--t-" + o.tint + ")" : o.tint);
    const track = el("div", { class: "pb-track" });
    // Staggered label rows: Límite on its own row, Nosotros above the track, Ellos (and Cerrado) below.
    const limRow = el("div", { class: "pb-labels pb-lim" });
    const top = el("div", { class: "pb-labels pb-top" });
    const bottom = el("div", { class: "pb-labels pb-bottom" });
    if (typeof o.limit === "number") root.appendChild(limRow);
    root.appendChild(top);
    root.appendChild(track);
    root.appendChild(bottom);
    track.appendChild(el("div", { class: "pb-line" }));
    if (o.zone && o.zone.length === 2 && isFinite(o.zone[0]) && isFinite(o.zone[1]) && o.zone[1] >= o.zone[0]) {
      track.appendChild(el("div", { class: "pb-zone", title: "Zona de acuerdo " + fmtNum(o.zone[0]) + "–" + fmtNum(o.zone[1]),
        style: { left: pos(o.zone[0]) + "%", width: Math.max(0.8, pos(o.zone[1]) - pos(o.zone[0])) + "%" } }));
    }
    for (const h of o.history || []) {
      const items = typeof h === "number" ? [["theirs", h]] :
        h.who ? [[h.who === "ours" || h.who === "us" ? "ours" : "theirs", h.price]] : [["ours", h.ours], ["theirs", h.theirs]];
      for (const [who, p] of items) if (typeof p === "number") track.appendChild(el("div", { class: "pb-hist " + who, style: { left: pos(p) + "%" } }));
    }
    const label = (row, cls, text, v) => row.appendChild(el("div", { class: "pb-lab " + cls, style: { left: pos(v) + "%" } },
      el("span", null, text), " ", el("span", { class: "num" }, fmtNum(v, v % 1 ? 1 : 0))));
    if (typeof o.limit === "number") { track.appendChild(el("div", { class: "pb-limit", style: { left: pos(o.limit) + "%" } })); label(limRow, "lim", "Límite", o.limit); }
    if (typeof o.theirs === "number") { track.appendChild(el("div", { class: "pb-dot theirs", style: { left: pos(o.theirs) + "%" } })); label(bottom, "theirs", "Ellos", o.theirs); }
    if (typeof o.ours === "number") { track.appendChild(el("div", { class: "pb-dot ours", style: { left: pos(o.ours) + "%" } })); label(top, "ours", "Nosotros", o.ours); }
    if (o.closed && typeof o.closed.price === "number") {
      track.appendChild(el("div", { class: "pb-deal", style: { left: pos(o.closed.price) + "%" } }));
      label(bottom, "deal", "Cerrado", o.closed.price);
    }
    if (o.noDeal) root.appendChild(el("div", { class: "pb-nodeal" }, "Sin acuerdo"));
    // Nudge labels that overlap on the same row.
    requestAnimationFrame(() => [limRow, top, bottom].forEach(spread));
    return root;
  }
  function spread(row) {
    const labs = [...row.children].sort((a, b) => parseFloat(a.style.left) - parseFloat(b.style.left));
    const w = row.clientWidth; if (!w) return;
    let lastEnd = -Infinity;
    for (const l of labs) {
      const lw = l.offsetWidth; let x = (parseFloat(l.style.left) / 100) * w - lw / 2;
      x = Math.max(0, Math.min(w - lw, x)); if (x < lastEnd + 4) x = lastEnd + 4;
      l.style.left = x + "px"; l.style.transform = "none"; lastEnd = x + lw;
    }
  }

  // ------------------------------------------------------------------ small charts
  function kpi({ label, value, sub, tone } = {}) {
    return el("div", { class: ["kpi", tone ? "tone-" + tone : ""] }, el("div", { class: "kpi-label" }, label),
      el("div", { class: "kpi-value num" }, value === undefined || value === null ? "—" : value), sub ? el("div", { class: "kpi-sub" }, sub) : null);
  }
  function meter({ label, value, max, tone } = {}) {
    const v = Number(value) || 0, m = Number(max) || 0;
    const pct = m > 0 ? Math.max(0, Math.min(100, (v / m) * 100)) : 0;
    const t = tone || (m && v >= m ? "bad" : m && v / m >= 0.75 ? "warn" : "");
    return el("div", { class: ["meter", t ? "tone-" + t : ""] }, el("span", { class: "meter-label" }, label),
      el("span", { class: "meter-bar" }, el("span", { class: "meter-fill", style: { width: pct + "%" } })),
      el("span", { class: "meter-val num" }, (value === null || value === undefined ? "—" : fmtNum(v)) + "/" + (max === null || max === undefined ? "—" : fmtNum(m))));
  }
  function svg(tag, attrs) { const n = document.createElementNS(SVGNS, tag); for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v); return n; }
  function sparkline(values, opts) {
    opts = opts || {};
    const w = opts.w || 90, h = opts.h || 18;
    const s = svg("svg", { width: w, height: h, viewBox: "0 0 " + w + " " + h, class: "spark" });
    const v = (values || []).map(Number).filter((x) => isFinite(x));
    if (v.length < 2) return s;
    const lo = Math.min(...v), hi = Math.max(...v), span = hi - lo || 1;
    const pts = v.map((x, i) => [(i / (v.length - 1)) * (w - 2) + 1, h - 1 - ((x - lo) / span) * (h - 2)]);
    const trend = v[v.length - 1] - v[0];
    const color = opts.color || (opts.neutral ? "var(--ink-3)" : trend > 0 ? "var(--ok)" : trend < 0 ? "var(--bad)" : "var(--ink-3)");
    s.appendChild(svg("polyline", { points: pts.map((p) => p.map((x) => x.toFixed(1)).join(",")).join(" "), fill: "none", stroke: color, "stroke-width": opts.stroke || 1.3 }));
    if (opts.dot !== false) { const p = pts[pts.length - 1]; s.appendChild(svg("rect", { x: p[0] - 1.5, y: p[1] - 1.5, width: 3, height: 3, fill: color })); }
    return s;
  }
  // bars([1,2,3]) | bars([{label,value,color}]) | bars([{name,color,values:[..]}], {stacked:true}) — vertical columns.
  function bars(series, opts) {
    opts = opts || {};
    const w = opts.w || 240, h = opts.h || 60, gap = opts.gap === undefined ? 2 : opts.gap;
    const s = svg("svg", { width: opts.fluid ? "100%" : w, height: h, viewBox: "0 0 " + w + " " + h, preserveAspectRatio: "none", class: "bars" });
    series = series || [];
    let cols;
    if (series.length && series[0] && Array.isArray(series[0].values)) {
      const n = Math.max(...series.map((x) => x.values.length));
      cols = Array.from({ length: n }, (_, i) => series.map((x) => ({ value: Number(x.values[i]) || 0, color: x.color, label: x.name })));
    } else cols = series.map((x) => [typeof x === "number" ? { value: x } : { value: Number(x.value) || 0, color: x.color, label: x.label }]);
    const max = opts.max || Math.max(1, ...cols.map((c) => c.reduce((a, b) => a + Math.max(0, b.value), 0)));
    const bw = cols.length ? (w - gap * (cols.length - 1)) / cols.length : 0;
    cols.forEach((c, i) => {
      let y = h;
      for (const seg of c) {
        const bh = (Math.max(0, seg.value) / max) * h;
        if (bh <= 0) continue;
        y -= bh;
        const r = svg("rect", { x: (i * (bw + gap)).toFixed(2), y: y.toFixed(2), width: Math.max(0.5, bw).toFixed(2), height: bh.toFixed(2), fill: seg.color || opts.color || "var(--ink-3)" });
        const t = svg("title", {}); t.textContent = (seg.label ? seg.label + ": " : "") + fmtNum(seg.value) + (opts.labels && opts.labels[i] ? " · " + opts.labels[i] : "");
        r.appendChild(t); s.appendChild(r);
      }
    });
    return s;
  }

  // ------------------------------------------------------------------ panels, drawer, states
  function panel(title, opts) {
    opts = opts || {};
    const body = el("div", { class: "panel-body" });
    const p = el("section", { class: ["panel", opts.cls] },
      el("header", { class: "panel-head" }, el("h2", { class: "panel-title" }, title),
        opts.sub ? el("span", { class: "panel-sub" }, opts.sub) : null,
        el("div", { class: "panel-actions" }, opts.actions || [])), body);
    if (opts.body) append(body, [opts.body]);
    p.body = body;
    return p;
  }
  let drawerEl = null, drawerClose = null;
  function drawer({ title, body, onClose, wide } = {}) {
    closeDrawer(true);
    const content = el("div", { class: "drawer-body" }, body);
    const box = el("aside", { class: ["drawer", wide ? "wide" : ""], role: "dialog", "aria-label": typeof title === "string" ? title : "Detalle" },
      el("header", { class: "drawer-head" }, el("h2", null, title || ""),
        el("button", { type: "button", class: "icon-btn", "aria-label": "Cerrar", onclick: () => closeDrawer() , html: iconSvg("close", 16) })),
      content);
    const shade = el("div", { class: "drawer-shade", onclick: () => closeDrawer() });
    drawerEl = el("div", { class: "drawer-wrap" }, shade, box);
    drawerClose = onClose || null;
    document.body.appendChild(drawerEl);
    box.body = content;
    return box;
  }
  function closeDrawer(silent) {
    if (!drawerEl) return;
    drawerEl.remove(); drawerEl = null;
    const cb = drawerClose; drawerClose = null;
    if (cb && !silent) try { cb(); } catch (e) { console.error(e); }
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && drawerEl && !document.querySelector(".modal-wrap")) closeDrawer(); });

  function empty(text) { return el("div", { class: "state empty" }, text || "Sin datos todavía."); }
  function loading(text) { return el("div", { class: "state loading" }, el("span", { class: "spinner" }), text || "Cargando…"); }
  function error(err) {
    const status = err && err.status;
    const msg = status === 404 ? "Este dato aún no está disponible en la API." :
      status === 0 ? "Sin conexión con la API." : (err && err.message) || String(err || "Error");
    return el("div", { class: "state error" }, icon("alert", 14), el("span", null, msg));
  }

  // ------------------------------------------------------------------ formatting (es-ES, always grouped)
  function fmtNum(n, dec) {
    if (n === null || n === undefined || n === "" || !isFinite(Number(n))) return "—";
    n = Number(n);
    const d = dec === undefined ? (Number.isInteger(n) ? 0 : Math.abs(n) >= 100 ? 0 : 1) : dec;
    const neg = n < 0;
    const fixed = Math.abs(n).toFixed(d);
    let [i, f] = fixed.split(".");
    i = i.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    return (neg && Number(fixed) !== 0 ? "−" : "") + i + (f ? "," + f : "");
  }
  function fmtP(n, dec) { return n === null || n === undefined ? "—" : fmtNum(n, dec) + " P"; }
  function fmtUsd(n) { return n === null || n === undefined ? "—" : fmtNum(n, 2) + " $"; }
  function toDate(ts) {
    if (ts === null || ts === undefined || ts === "") return null;
    if (ts instanceof Date) return ts;
    if (typeof ts === "number" || /^\d+(\.\d+)?$/.test(String(ts))) { const n = Number(ts); return new Date(n < 1e12 ? n * 1000 : n); }
    const d = new Date(ts); return isNaN(d) ? null : d;
  }
  const pad = (x) => String(x).padStart(2, "0");
  function fmtTime(ts, withSeconds) {
    const d = toDate(ts); if (!d) return "—";
    return pad(d.getHours()) + ":" + pad(d.getMinutes()) + (withSeconds === false ? "" : ":" + pad(d.getSeconds()));
  }
  function fmtAgo(ts) {
    const d = toDate(ts); if (!d) return "—";
    const s = Math.max(0, (Date.now() - d.getTime()) / 1000);
    if (s < 45) return "ahora";
    if (s < 3600) return Math.round(s / 60) + " min";
    if (s < 86400) return Math.floor(s / 3600) + " h " + pad(Math.floor((s % 3600) / 60));
    return Math.floor(s / 86400) + " d";
  }
  function fmtDur(sec) {
    if (sec === null || sec === undefined || !isFinite(sec)) return "—";
    sec = Math.max(0, Math.round(sec));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return (h ? h + ":" + pad(m) : pad(m)) + ":" + pad(s);
  }
  let clockRef = null;   // set by app.js from overview.clock
  function setClock(c, now) { clockRef = c ? { tick: c.tick, tick_seconds: c.tick_seconds, at: now ? now * 1000 : Date.now() } : null; }
  function tickTime(tick) {
    if (tick === null || tick === undefined) return "—";
    if (!clockRef || clockRef.tick === null || clockRef.tick === undefined) return "t" + tick;
    return fmtTime(clockRef.at - (Number(clockRef.tick) - Number(tick)) * (clockRef.tick_seconds || 60) * 1000);
  }

  // tick -> wall time, from the recorder's clock stream (first time each tick was seen).
  // Beyond the last known tick it extrapolates with tick_seconds; before the first known tick it gives null.
  let tickMap = { ticks: [], ts: [], tickS: 30 };
  function setTickMap(rows) {
    const first = new Map(); let tickS = tickMap.tickS;
    for (const r of rows || []) {
      const t = Number(r.tick); const ts = Number(r.ts);
      if (!isFinite(t) || !isFinite(ts)) continue;
      if (!first.has(t) || ts < first.get(t)) first.set(t, ts);
      const d = r.data || {}; if (d.tick_seconds) tickS = Number(d.tick_seconds) || tickS;
    }
    const ticks = [...first.keys()].sort((a, b) => a - b);
    tickMap = { ticks, ts: ticks.map((t) => first.get(t)), tickS };
  }
  function tickWall(tick) {
    const t = Number(tick); if (tick === null || tick === undefined || !isFinite(t)) return null;
    const { ticks, ts, tickS } = tickMap;
    if (!ticks.length) {
      if (clockRef && clockRef.tick != null) return (clockRef.at - (Number(clockRef.tick) - t) * (clockRef.tick_seconds || 60) * 1000) / 1000;
      return null;
    }
    if (t < ticks[0]) return null;
    let lo = 0, hi = ticks.length - 1;
    while (lo < hi) { const m = (lo + hi + 1) >> 1; if (ticks[m] <= t) lo = m; else hi = m - 1; }
    if (ticks[lo] === t) return ts[lo];
    return ts[lo] + (t - ticks[lo]) * tickS;
  }
  // "HH:MM:SS" for a tick (or "t<tick>" when the time is unknown)
  function tickClock(tick, withSeconds) {
    const w = tickWall(tick);
    return w ? fmtTime(w, withSeconds) : (tick == null ? "—" : "t" + tick);
  }

  // ------------------------------------------------------------------ scroll-safe updates
  // Scroll positions of `node` and its scrolling ancestors (and the page), to put back after a DOM update.
  function scrollers(node) {
    const out = [];
    for (let n = node; n && n.nodeType === 1; n = n.parentElement) if (n.scrollTop > 0) out.push([n, n.scrollTop]);
    const se = document.scrollingElement;
    if (se && se.scrollTop > 0 && !out.some(([n]) => n === se)) out.push([se, se.scrollTop]);
    return out;
  }
  function restoreScroll(saved) { for (const [n, t] of saved) if (n.isConnected && Math.abs(n.scrollTop - t) > 1) n.scrollTop = t; }
  // Run a synchronous DOM update without the page (or `node`'s scrolling parents) jumping.
  function keepScroll(node, fn) { const saved = scrollers(node); try { return fn(); } finally { restoreScroll(saved); } }
  // Keyed list update: keeps a child whose signature did not change (so its scroll survives), re-renders the
  // rest, carries the inner scroll (selector `inner`) of a re-rendered child, and never empties the host.
  // opts: {key(item), sig(item), render(item), inner, stickEnd, tail: [nodes after the list]}
  function keyedList(host, list, opts) {
    const saved = scrollers(host);
    const old = new Map();
    for (const c of Array.from(host.children)) if (c.dataset && c.dataset.key) old.set(c.dataset.key, c);
    const restores = [];
    const want = list.map((it) => {
      const k = String(opts.key(it)), sg = String(opts.sig ? opts.sig(it) : "");
      const prev = old.get(k);
      if (prev && prev.dataset.sig === sg) return prev;
      const n = opts.render(it); n.dataset.key = k; n.dataset.sig = sg;
      if (prev && opts.inner) {
        const a = prev.querySelector(opts.inner);
        if (a) {
          const atEnd = a.scrollHeight - a.scrollTop - a.clientHeight < 8, top = a.scrollTop;
          restores.push(() => { const b = n.querySelector(opts.inner); if (b) b.scrollTop = atEnd && opts.stickEnd ? b.scrollHeight : top; });
        }
      } else if (opts.inner && opts.stickEnd) restores.push(() => { const b = n.querySelector(opts.inner); if (b) b.scrollTop = b.scrollHeight; });
      return n;
    });
    const all = want.concat((opts.tail || []).filter(Boolean));
    const keep = new Set(all);
    for (const c of Array.from(host.children)) if (!keep.has(c)) c.remove();
    all.forEach((n, i) => { if (host.children[i] !== n) host.insertBefore(n, host.children[i] || null); });
    restores.forEach((f) => f());
    restoreScroll(saved);
  }

  // ------------------------------------------------------------------ confirm + toast
  function confirm({ title, text, confirmLabel, cancelLabel, danger, body } = {}) {
    return new Promise((resolve) => {
      const yes = el("button", { type: "button", class: ["btn", danger ? "btn-danger" : "btn-primary"] }, confirmLabel || "Confirmar");
      const no = el("button", { type: "button", class: "btn" }, cancelLabel || "Cancelar");
      const box = el("div", { class: ["modal", danger ? "danger" : ""], role: "alertdialog", "aria-modal": "true" },
        el("h2", { class: "modal-title" }, danger ? icon("alert", 16) : null, title || "¿Seguro?"),
        text ? el("p", { class: "modal-text" }, text) : null, body || null,
        el("div", { class: "modal-actions" }, no, yes));
      const wrap = el("div", { class: "modal-wrap" }, box);
      const done = (v) => { wrap.remove(); document.removeEventListener("keydown", onKey, true); resolve(v); };
      const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); done(false); } };
      yes.addEventListener("click", () => done(true));
      no.addEventListener("click", () => done(false));
      wrap.addEventListener("click", (e) => { if (e.target === wrap) done(false); });
      document.addEventListener("keydown", onKey, true);
      document.body.appendChild(wrap);
      (danger ? no : yes).focus();
    });
  }

  const TOAST_TONE = { aprobar: "warn", pendiente: "warn", breaker: "bad", error: "bad", disyuntor: "bad", gran: "ok", deal: "ok",
    outcome: "ok", dealer: "teal", novedad: "teal", novelty: "teal", broker: "blue", duelo: "violet", duel: "violet", lab: "mute", limite: "mute", alerta: "warn" };
  const TOAST_ICON = { aprobar: "bell", pendiente: "bell", breaker: "alert", error: "alert", disyuntor: "alert", gran: "trend", deal: "trend",
    outcome: "trend", dealer: "dealer", novedad: "dealer", novelty: "dealer", broker: "flask", duelo: "duelo", duel: "duelo", lab: "laboratorio", alerta: "alert" };
  function toastKey(type) { const t = String(type || "").toLowerCase(); return Object.keys(TOAST_TONE).find((k) => t.startsWith(k)) || "lab"; }
  function toast({ type, title, text, href, ts, ttl } = {}) {
    let stack = document.getElementById("toasts");
    if (!stack) { stack = el("div", { id: "toasts", class: "toasts", "aria-live": "polite" }); document.body.appendChild(stack); }
    const k = toastKey(type);
    const close = el("button", { type: "button", class: "icon-btn", "aria-label": "Cerrar", html: iconSvg("close", 13) });
    const t = el("div", { class: "toast tone-" + (TOAST_TONE[k] || "mute") },
      el("div", { class: "toast-head" }, icon(TOAST_ICON[k] || "bell", 15), el("strong", null, title || ""),
        el("span", { class: "toast-time num" }, ts ? fmtAgo(ts) : "ahora"), close),
      text ? el("div", { class: "toast-text" }, text) : null,
      href ? el("a", { class: "toast-link", href }, "Abrir en Supervisión ", icon("arrow", 12)) : null);
    const remove = () => { t.classList.add("out"); setTimeout(() => t.remove(), 200); };
    close.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); remove(); });
    if (href) t.addEventListener("click", (e) => { if (!e.target.closest("button")) { location.hash = href.replace(/^#?/, "#"); remove(); } });
    stack.prepend(t);
    while (stack.children.length > 4) stack.lastChild.remove();
    setTimeout(remove, ttl || 9000);
    return t;
  }

  // API spend purposes as people read them; unknown purposes are shown as they come
  const PURPOSE_LABEL = { strategy: "Cerebro", council: "Consejo", duels: "Duelos", dealers: "Dealers", market: "Mercado", lab: "Laboratorio",
    smoke: "Pruebas", brain_eval: "Pruebas del cerebro", external_intel: "Mensajes externos", broker: "Broker" };
  const purposeLabel = (k) => PURPOSE_LABEL[k] || k;

  window.ui = {
    el, append, esc, icon, iconSvg, ICONS, TYPES, TYPE_LABEL, normType,
    typeChip, row, sourceTag, resultChip, teamTag, teamName, filterBar, matchFilter, priceBar,
    kpi, meter, sparkline, bars, panel, drawer, closeDrawer, empty, loading, error,
    fmtP, fmtNum, fmtUsd, fmtTime, fmtAgo, fmtDur, toDate, tickTime, setClock, setTickMap, tickWall, tickClock, keepScroll, keyedList, confirm, toast, purposeLabel, PURPOSE_LABEL,
  };
})();
