// K: every shared component of v07 Market. See them all at /plaza/_kit.
// Rule: text from the API is only ever written with textContent (K.el does it). No innerHTML with data.
(function () {
  "use strict";
  const t = (k, v) => window.I18N.t(k, v);

  // ---- elements
  /** el("div", { class: "x", onclick: fn, "aria-label": "…" }, child, "text", [more]) */
  function el(tag, attrs, ...kids) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "style" && typeof v === "object") {
        for (const [prop, val] of Object.entries(v)) { if (prop.startsWith("--")) node.style.setProperty(prop, val); else node.style[prop] = val; }
      }
      else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
      else if (k === "dataset") Object.assign(node.dataset, v);
      else node.setAttribute(k, v === true ? "" : String(v));
    }
    add(node, kids);
    return node;
  }
  function add(node, kids) {
    for (const kid of kids.flat(Infinity)) {
      if (kid === null || kid === undefined || kid === false) continue;
      node.appendChild(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return node;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }

  // ---- icons: the dashboard's line icons (stroke 1.8, square caps). Constant strings, never data.
  const ICONS = {
    home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9v12h14V9"/><path d="M10 21v-6h4v6"/>',
    cards: '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>',
    offers: '<path d="M4 8h13l-3-3"/><path d="M20 16H7l3 3"/>',
    activity: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    market: '<path d="M3 9 4.5 4h15L21 9"/><path d="M3 9h18v1.5a3 3 0 0 1-6 0 3 3 0 0 1-6 0 3 3 0 0 1-6 0Z"/><path d="M5 12.5V20h14v-7.5"/><path d="M10 20v-4h4v4"/>',
    api: '<path d="m8 7-5 5 5 5"/><path d="m16 7 5 5-5 5"/><path d="m13.5 5-3 14"/>',
    how: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 1-1 1.7"/><path d="M12 16.5v.5"/>',
    settings: '<path d="M4 7h10"/><path d="M18 7h2"/><rect x="14" y="5" width="4" height="4"/><path d="M4 17h2"/><path d="M10 17h10"/><rect x="6" y="15" width="4" height="4"/>',
    suggest: '<path d="M4 4h16v12H9l-5 4Z"/>',
    refresh: '<path d="M20 12a8 8 0 1 1-2.6-5.9"/><path d="M20 4v5h-5"/>',
    agent: '<rect x="5" y="5" width="14" height="14"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
    give: '<path d="M7 17 17 7"/><path d="M9 7h8v8"/>',
    get: '<path d="M17 7 7 17"/><path d="M15 17H7V9"/>',
    swap: '<path d="M4 8h13l-3-3"/><path d="M20 16H7l3 3"/>',
    trend: '<path d="m3 17 6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/>',
    lock: '<rect x="4" y="11" width="16" height="10"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    pause: '<path d="M8 5v14M16 5v14"/>',
    alert: '<circle cx="12" cy="12" r="9"/><path d="M12 7v6"/><path d="M12 16.5v.5"/>',
    warning: '<path d="M12 3.5 21.5 20h-19z"/><path d="M12 10v5"/><path d="M12 17.3v.4"/>',
    banned: '<circle cx="12" cy="12" r="9"/><path d="M5.7 5.7l12.6 12.6"/>',
    close: '<path d="M6 6l12 12M18 6 6 18"/>',
    arrow: '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
    back: '<path d="M19 12H5"/><path d="m11 6-6 6 6 6"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
    check: '<path d="m5 12 5 5 9-10"/>',
    off: '<circle cx="12" cy="12" r="9"/><path d="M5.5 5.5l13 13"/>',
    copy: '<rect x="8" y="8" width="13" height="13"/><path d="M16 8V3H3v13h5"/>',
    shield: '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6Z"/>',
    target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
    chevron: '<path d="m6 9 6 6 6-6"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    doc: '<path d="M6 3h9l4 4v14H6Z"/><path d="M14 3v5h5"/><path d="M9 13h7M9 17h7"/>',
    teams: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7"/><path d="M18 14a6.5 6.5 0 0 1 3.5 6"/>',
    overview: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    performance: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    matchmaker: '<circle cx="7" cy="12" r="3"/><circle cx="17" cy="12" r="3"/><path d="M10 12h4"/>',
    venue: '<path d="M4 21V8l8-5 8 5v13"/><path d="M9 21v-6h6v6"/>',
    hand: '<path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V12"/><path d="M11 11.5v-2a1.5 1.5 0 0 1 3 0V12"/><path d="M14 10.5a1.5 1.5 0 0 1 3 0V12"/><path d="M17 11.5a1.5 1.5 0 0 1 3 0V15a6 6 0 0 1-6 6h-1.5a6 6 0 0 1-4.6-2.2L5 15.5a1.6 1.6 0 0 1 2.4-2.1L8 14"/>',
    zero: '<circle cx="12" cy="12" r="9"/><path d="M8 16 16 8"/>',
  };
  function icon(name, size) {
    const s = size || 14;
    const span = document.createElement("span");
    span.className = "ic-wrap";
    span.innerHTML = '<svg class="ic" width="' + s + '" height="' + s + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="1.8" stroke-linecap="square" stroke-linejoin="miter" aria-hidden="true">' + (ICONS[name] || ICONS.alert) + "</svg>";
    return span;
  }

  // ---- words and numbers
  const RARITY = { common: "#9AA4B8", uncommon: "#3DDC97", rare: "#4C8DFF", epic: "#B061FF", legendary: "#FFC44D" };
  const num = (n) => window.I18N.n(n);
  const price = (p) => (typeof p === "number" ? num(p) + " P" : "–");
  const tick = (n) => (typeof n === "number" ? "t" + n : "–");
  /** "3 ticks ago" from two tick numbers. */
  function ago(then, now) {
    if (typeof then !== "number" || typeof now !== "number") return "–";
    const d = Math.max(0, now - then);
    return d === 0 ? t("common.thisTick") : t(d === 1 ? "common.tickAgo" : "common.ticksAgo", { n: d });
  }
  const teamNo = (team) => String(parseInt(String(team || "").slice(1), 10) || "?");
  const teamName = (team) => t("common.team", { n: teamNo(team) });
  /** "SAL · 10" from "SAL-10". */
  function refParts(ref) {
    const m = /^([A-Z]{3})-(\d{2})$/.exec(String(ref || ""));
    return m ? { set: m[1], no: m[2] } : { set: String(ref || "").slice(0, 3), no: "" };
  }


  // ---- sentences the server writes in English (the agent's log, the "why" of a trade, the next step of the queue):
  // the known ones are said in the page's language, anything else stays as it came.
  const SAY_ES = [
    [/^(t\d\d) can part with ([A-Z]{3}-\d\d); (t\d\d) looks for it( \(probably the last card of its page\))?$/, (m) => `${m[1]} puede soltar ${m[2]}; ${m[3]} la busca` + (m[4] ? " (probablemente la última carta de su página)" : "")],
    [/^(t\d\d) has (\S+) and wants (\S+); (t\d\d) has \S+ and wants \S+$/, (m) => `${m[1]} tiene ${m[2]} y busca ${m[3]}; ${m[4]} tiene ${m[3]} y busca ${m[2]}`],
    [/^(t\d\d) gives (\S+) to (t\d\d), (t\d\d) gives (\S+) to (t\d\d), (t\d\d) gives (\S+) to (t\d\d)$/, (m) => `${m[1]} da ${m[2]} a ${m[3]}, ${m[4]} da ${m[5]} a ${m[6]}, ${m[7]} da ${m[8]} a ${m[9]}`],
    [/^three-way swap: agree on the thread first$/, () => "cambio a tres: primero hay que acordarlo en el hilo"],
    [/^ask_me: waiting for your human$/, () => "pregúntame antes: esperando a tu humano"],
    [/^waiting for the other side to post the offer$/, () => "esperando a que la otra parte publique la oferta"],
    [/^your offer is on the venue; waiting for the accept$/, () => "tu oferta está en el venue; esperando a que la acepten"],
    [/^accepted; it settles on the next tick$/, () => "aceptado; se cierra en el próximo tick"],
    [/^nothing to do now$/, () => "nada que hacer ahora"],
    [/^publish your current duplicates, cards for sale and wants/, () => "publicar tus repetidas, cartas en venta y buscadas"],
    [/^your human passed on this trade$/, () => "tu humano ha pasado de este trato"],
    [/^your human counters at (\d+) P/, (m) => `tu humano contraoferta a ${m[1]} P`],
    [/^the price on the table is outside your own limits: counter or pass/, () => "el precio sobre la mesa está fuera de tus límites: contraoferta o pasa"],
    [/^post this addressed offer in the game, on venue (\S+) and nowhere/, (m) => `publicar esta oferta dirigida en el juego, en el venue ${m[1]} y en ningún otro`],
    [/^your offer (\d+) for this match is on ([^:\s]+):/, (m) => `tu oferta ${m[1]} de este trato está en ${m[2]}: cancélala y publícala en v07`],
    [/^your offer (\d+) for (\S+) is on ([^:\s]+):/, (m) => `tu oferta ${m[1]} por ${m[2]} está en ${m[3]}: este trato solo se cierra en v07 (sin comisión). Cancélala y publícala en v07.`],
    [/^tell the other side you take these terms; it then posts the offer/, () => "decir a la otra parte que aceptas estas condiciones; después publica la oferta"],
    [/^accept offer (\d+) in the game/, (m) => `aceptar la oferta ${m[1]} en el juego`],
    [/^say on the thread that you accepted$/, () => "decir en el hilo que has aceptado"],
    [/^connected and proved its code in the game$/, () => "conectado; ha probado su código en el juego"],
    [/^published (\d+) cards? it has and (\d+) it wants$/, (m) => `ha publicado ${m[1]} cartas que tiene y ${m[2]} que busca`],
    [/^set private limits on (\d+) cards?$/, (m) => `ha puesto límites privados en ${m[1]} cartas`],
    [/^matched with (t\d\d): (\S+) at (\d+) P$/, (m) => `emparejado con ${m[1]}: ${m[2]} a ${m[3]} P`],
    [/^countered at (\d+) P$/, (m) => `ha contraofertado a ${m[1]} P`],
    [/^posted the addressed offer on v07$/, () => "ha publicado la oferta dirigida en v07"],
    [/^read its queue: (\d+) actions?$/, (m) => `ha leído su cola: ${m[1]} ${m[1] === "1" ? "acción" : "acciones"}`],
    [/^(\S+) settled on v07 at (\d+) P with (t\d\d)$/, (m) => `${m[1]} cerrada en v07 a ${m[2]} P con ${m[3]}`],
    [/^the host answered your suggestion: (\S+)$/, (m) => `el anfitrión ha respondido a tu sugerencia: ${m[1]}`],
  ];
  function say(text) {
    if (typeof text !== "string" || I18N.lang !== "es") return text;
    for (const [rx, fn] of SAY_ES) { const m = rx.exec(text); if (m) return fn(m); }
    return text;
  }

  // ---- small pieces
  function pill(text, tone) { return el("span", { class: "pill tone-" + (tone || "mute") }, el("span", { class: "dot" }), text); }
  function chip(text, tone, ic) { return el("span", { class: "chip" + (tone ? " tone-" + tone : "") }, ic ? icon(ic, 11) : null, text); }
  function id(text) { return el("span", { class: "id" }, text); }
  function label(text, cls) { return el("span", { class: "label" + (cls ? " " + cls : "") }, text); }
  function btn(text, opts) {
    const o = opts || {};
    return el(o.href ? "a" : "button", { class: "btn" + (o.kind ? " " + o.kind : "") + (o.small ? " sm" : ""), type: o.href ? null : "button",
                                           href: o.href, onclick: o.onclick, disabled: o.disabled, title: o.title, "aria-label": o.label },
              o.icon ? icon(o.icon, 14) : null, text, o.iconAfter ? icon(o.iconAfter, 14) : null);
  }
  /** A link the router follows without reloading. */
  function link(path, attrs, ...kids) {
    return el("a", { ...(attrs || {}), href: path, onclick: (e) => {
      if (e.metaKey || e.ctrlKey || e.shiftKey) return;
      e.preventDefault();
      window.Plaza.go(path);
    } }, ...kids);
  }
  function panel(o, ...body) {
    const head = o.title ? el("div", { class: "panel-head" }, o.icon ? icon(o.icon, 15) : null, el("h2", { class: "panel-title" }, o.title),
                              o.note ? el("span", { class: "panel-note" }, o.note) : null, o.more || null) : null;
    return el("section", { class: "panel" + (o.zone ? " zone-" + o.zone : "") + (o.class ? " " + o.class : "") }, head,
              o.flush ? body : el("div", { class: "panel-body" }, body));
  }
  function pageHead(title, sub, ...right) {
    return el("header", { class: "page-head" }, el("div", null, el("h1", { class: "page-title" }, title), sub ? el("p", { class: "page-sub" }, sub) : null),
              right.length ? el("div", { style: { marginLeft: "auto", display: "flex", gap: "8px", flexWrap: "wrap" } }, right) : null);
  }
  function kpis(rows) {
    return el("div", { class: "kpis" }, rows.map((r) => el("div", { class: "kpi" }, label(r.label), el("span", { class: "kpi-value" }, r.value),
                                                           r.sub ? el("span", { class: "kpi-sub" }, r.sub) : null)));
  }
  /** table([{ key, label, num, render(row) }], rows) */
  function table(cols, rows, opts) {
    const o = opts || {};
    return el("table", { class: "table" },
      el("thead", null, el("tr", null, cols.map((c) => el("th", { class: c.num ? "num" : null }, c.label)))),
      el("tbody", null, rows.map((r) => el("tr", { onclick: o.onrow ? () => o.onrow(r) : null, style: o.onrow ? { cursor: "pointer" } : null },
        cols.map((c) => el("td", { class: c.num ? "num" : null }, c.render ? c.render(r) : r[c.key] === null || r[c.key] === undefined ? "–" : r[c.key])))))
    );
  }
  /** The call that feeds a screen: endpoint("GET /plaza/api/me", "GET /plaza/api/agent/next") */
  function endpoint(...calls) { return el("div", { class: "endpoint" }, el("span", null, "API"), calls.map((c) => el("b", null, c))); }
  /** A screen's own state: loading, empty, error, offline. */
  function state(kind, title, text, action) {
    if (kind === "loading") return el("div", { class: "state is-loading", role: "status" }, el("div", { class: "skeleton", style: { width: "180px" } }), el("span", null, title || t("common.loading")));
    const ic = { empty: "zero", error: "alert", offline: "off" }[kind] || "alert";
    return el("div", { class: "state is-" + kind }, icon(ic, 22), el("div", { class: "state-title" }, title || t("common." + kind)),
              text ? el("div", null, text) : null, action || null);
  }
  function toast(text, tone) {
    let box = document.querySelector(".toasts");
    if (!box) box = document.body.appendChild(el("div", { class: "toasts", "aria-live": "polite" }));
    const node = box.appendChild(el("div", { class: "toast" + (tone ? " is-" + tone : "") }, text));
    setTimeout(() => node.remove(), 4000);
  }
  function copy(text, done) {
    const ok = () => toast(done || t("common.copied"), "ok");
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text).then(ok, () => toast(t("common.copyFailed"), "bad"));
    const ta = document.body.appendChild(el("textarea", { style: { position: "fixed", opacity: "0" } }, text));
    ta.select();
    try { document.execCommand("copy"); ok(); } catch (e) { toast(t("common.copyFailed"), "bad"); }
    ta.remove();
  }

  // ---- the status box of the side nav: a name and a bordered label per row (v11)
  const TONES = { connected: "ok", open: "ok", on: "ok", ok: "ok", closed: "bad", offline: "bad", off: "bad", down: "bad",
                  paused: "pause", waiting: "pause", stale: "warn", unknown: "warn", suspended: "bad" };
  function statusBox(rows) {
    return el("div", { class: "status-box" }, rows.map((r) => el("div", { class: "sb-line" }, el("span", { class: "sb-name" }, r.name),
      pill(r.label || t("status." + r.state), r.tone || TONES[r.state] || "mute"))));
  }

  // ---- cards
  /** card({ref, name, rarity, color, art}, { owned: true|false, size: "sm"|"md"|"lg"|"fluid", href })
   *  Owned: the official art. Not owned: the Colección slot. Name, set letters and number always readable. */
  function card(c, opts) {
    const o = opts || {};
    const { set, no } = refParts(c.ref);
    const owned = o.owned !== false;
    const cls = "card sz-" + (o.size || "md") + (owned ? "" : " is-missing") + (c.art ? " has-art" : "");
    const node = el(o.href ? "a" : "div", { class: cls, href: o.href, title: c.ref + " · " + (c.name || ""), "aria-label": set + " " + no + " " + (c.name || ""),
                                             style: { "--set": c.color || "#5c6b73", "--rar": RARITY[c.rarity] || RARITY.common },
                                             onclick: o.href ? (e) => { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); window.Plaza.go(o.href); } : o.onclick });
    if (c.art) {
      art(c.art).then((svg) => {
        if (!svg) { node.classList.remove("has-art"); return; }
        node.insertBefore(svg.cloneNode(true), node.firstChild);
        node.classList.add("loaded");
      });
    }
    if (!owned) node.appendChild(el("span", { class: "card-no" }, no));
    node.appendChild(el("span", { class: "card-name" }, c.name || c.ref));
    node.appendChild(el("span", { class: "card-bar" }, el("span", null, set + " · " + no), el("span", { class: "card-pip" })));
    return node;
  }
  // The official art is an SVG that takes its fonts from the page, so it is drawn inline: fetched once per card,
  // parsed as SVG (never as HTML) and stripped of anything that could run.
  const ART = new Map();
  function art(url) {
    if (!ART.has(url)) {
      ART.set(url, fetch(url).then((r) => (r.ok ? r.text() : null)).then((text) => {
        if (!text) return null;
        const svg = new DOMParser().parseFromString(text, "image/svg+xml").documentElement;
        if (!svg || svg.nodeName !== "svg") return null;
        svg.querySelectorAll("script, foreignObject, iframe, a").forEach((n) => n.remove());
        svg.querySelectorAll("*").forEach((n) => [...n.attributes].forEach((at) => { if (/^on/i.test(at.name) || /^\s*javascript:/i.test(at.value)) n.removeAttribute(at.name); }));
        svg.setAttribute("class", "card-art");
        svg.setAttribute("preserveAspectRatio", "xMidYMid slice");
        return document.importNode(svg, true);
      }).catch(() => null));
    }
    return ART.get(url);
  }
  /** The cash side of a trade, drawn as a card. */
  function cash(p, size) { return el("div", { class: "card is-cash sz-" + (size || "md") }, el("span", { class: "card-cash" }, num(p)), el("span", { class: "label" }, "P")); }
  /** A card in a line of text: [SAL-10] Museo Lázaro Galdiano */
  function cardLine(c) {
    return el("span", { class: "cardline", style: { "--set": c.color || "#5c6b73" } }, el("span", { class: "cardline-ref" }, c.ref), el("span", null, c.name || ""));
  }
  /** What you give and what you get, side by side. gives/receives: cards; cash > 0 means you receive it. */
  function swap(gives, receives, cashP, size) {
    const side = (cards, money, cls, text) => el("div", { class: "swap-side" }, label(text, cls),
      el("div", { class: "card-row" }, cards.map((c) => card(c, { owned: cls === "give", size })), money ? cash(money, size) : null));
    return el("div", { class: "swap" }, side(gives || [], cashP < 0 ? -cashP : 0, "give", t("common.youGive")), el("span", { class: "swap-arrow" }, icon("swap", 18)),
              side(receives || [], cashP > 0 ? cashP : 0, "get", t("common.youGet")));
  }

  // ---- rows of activity (the agent's work, the floor)
  /** feed([{ tick, text, now }]) */
  function feed(rows) {
    return el("div", { class: "feed" }, rows.map((r) => el("div", { class: "feed-row" + (r.now ? " is-now" : "") }, el("span", { class: "feed-tick" }, tick(r.tick)),
      el("span", { class: "feed-dot" }), el("span", { class: "feed-text" }, r.text), r.extra || null)));
  }
  /** The negotiation: a box of fixed height with its own scroll, newest at the bottom.
   *  thread(messages, myTeam, { earlier: 9 }) ; a message: { team, action, price, text, tick } */
  function thread(messages, mine, opts) {
    const o = opts || {};
    const list = el("div", { class: "thread-list" }, (messages || []).map((m) => el("div", { class: "msg" + (m.team === mine ? " is-mine" : "") },
      el("div", { class: "msg-head" }, el("span", null, teamName(m.team)), el("span", null, tick(m.tick)), m.action ? el("span", null, t("action." + m.action)) : null),
      typeof m.price === "number" ? el("div", { class: "msg-price" }, price(m.price)) : null, m.text ? el("div", null, m.text) : null)));
    const box = el("div", { class: "thread" }, o.earlier ? el("div", { class: "thread-more" }, t("common.earlier", { n: o.earlier })) : null, list);
    requestAnimationFrame(() => { list.scrollTop = list.scrollHeight; });
    return box;
  }

  window.K = { el, add, clear, icon, ICONS, pill, chip, id, label, btn, link, panel, pageHead, kpis, table, endpoint, state, toast, copy, statusBox,
               card, cash, cardLine, swap, feed, thread, num, price, tick, ago, teamNo, teamName, refParts, say, RARITY, TONES };
})();
