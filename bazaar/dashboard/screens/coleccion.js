/* Colección · álbum por set, estados sobre cada carta, cajón de detalle. */
(function () {
  "use strict";
  const US = "t10";
  const SET_COLORS = { LAV: "#E4572E", MAL: "#E83F8C", LAT: "#F2A541", SAL: "#2EC4B6", RET: "#7B8CDE", CHA: "#9BC53D" };
  const RAR_COLORS = { common: "#9AA4B8", uncommon: "#3DDC97", rare: "#4C8DFF", epic: "#B061FF", legendary: "#FFC44D" };
  const RAR_LABEL = { common: "común", uncommon: "infrecuente", rare: "rara", epic: "épica", legendary: "legendaria" };
  const TARGET_SETS = ["LAV", "MAL", "RET"];
  const STATES = [
    { id: "dup", label: "Duplicado" },
    { id: "venta", label: "En venta" },
    { id: "compra", label: "Comprando" },
    { id: "puja", label: "Puja" },
    { id: "cambio", label: "Cambio" },
    { id: "dealer", label: "Conversación" },
    { id: "objetivo", label: "Objetivo" },
    { id: "protegida", label: "Protegida" },
  ];
  const ICONS = {
    dup: '<path d="M4 4h7v7H4z M6 2h7v7" fill="none" stroke="currentColor" stroke-width="1.4"/>',
    venta: '<path d="M4 12L12 4M6 4h6v6" fill="none" stroke="currentColor" stroke-width="1.6"/>',
    compra: '<path d="M12 4L4 12M4 6v6h6" fill="none" stroke="currentColor" stroke-width="1.6"/>',
    puja: '<path d="M5 8V4h2v4M7 7V3h2v5M9 7V4h2v5M5 8c0 3 1 5 4 5s3-2 3-4V6" fill="none" stroke="currentColor" stroke-width="1.2"/>',
    cambio: '<path d="M3 6h9l-2-2M13 10H4l2 2" fill="none" stroke="currentColor" stroke-width="1.5"/>',
    dealer: '<path d="M2 6l1-3h10l1 3M3 6v7h10V6M2 6h12" fill="none" stroke="currentColor" stroke-width="1.3"/>',
    objetivo: '<circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="1.4"/><circle cx="8" cy="8" r="2" fill="currentColor"/>',
    protegida: '<path d="M4 7h8v6H4zM6 7V5a2 2 0 014 0v2" fill="none" stroke="currentColor" stroke-width="1.4"/>',
  };

  // ---------- helpers ----------
  function h(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    if (attrs) for (const k in attrs) {
      const v = attrs[k];
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "style") n.setAttribute("style", v);
      else if (k === "html") n.innerHTML = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v);
    }
    for (const c of kids.flat(Infinity)) {
      if (c == null || c === false) continue;
      n.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return n;
  }
  const U = () => window.ui || {};
  function fmtP(n) {
    if (n == null || !isFinite(n)) return "—";
    if (U().fmtP) return U().fmtP(n);
    return (Math.round(n * 10) / 10).toLocaleString("es-ES") + " P";
  }
  function fmtN(n, d) {
    if (n == null || !isFinite(n)) return "—";
    return Number(n).toLocaleString("es-ES", { maximumFractionDigits: d == null ? 1 : d });
  }
  function icon(id) {
    return h("span", { class: "cc-ico", html: `<svg viewBox="0 0 16 16" width="11" height="11">${ICONS[id] || ""}</svg>` });
  }
  function arr(x) {
    if (Array.isArray(x)) return x;
    if (x && typeof x === "object") {
      for (const k of ["items", "rows", "threads", "offers", "list", "data"]) if (Array.isArray(x[k])) return x[k];
      for (const k in x) if (Array.isArray(x[k])) return x[k];
    }
    return [];
  }
  async function safe(fn) {
    try { return { ok: true, v: await fn() }; } catch (e) { return { ok: false, err: e }; }
  }
  function stateBox(kind, text) {
    const u = U();
    if (kind === "loading" && u.loading) return u.loading();
    if (kind === "error" && u.error) return u.error(text);
    if (kind === "empty" && u.empty) return u.empty(text);
    return h("div", { class: "cc-state cc-" + kind }, kind === "error" ? "Error: " + ((text && text.message) || text) : (text || "Cargando…"));
  }
  const refsOf = (side) => {
    const out = [];
    for (const a of (side && side.assets) || []) if (a && a.ref) out.push(a.ref);
    for (const t of (side && side.types) || []) if (typeof t === "string" && t.startsWith("card:")) out.push(t.slice(5));
    return out;
  };
  const hasAssets = (side) => ((side && side.assets) || []).length + ((side && side.types) || []).length > 0;

  // ---------- model ----------
  function buildModel(d) {
    const cat = d.catalog || {};
    const me = d.me || {};
    const sets = cat.sets || [];
    const values = cat.values || {};
    const cardInfo = {};
    for (const s of sets) for (const c of s.cards || []) cardInfo[c.id] = { ...c, set: s.id };
    for (const s of sets) CROMO.sets[s.id] = s;

    const owned = {};
    for (const a of me.assets || []) {
      if (a.kind !== "card" || !a.ref) continue;
      (owned[a.ref] = owned[a.ref] || []).push(a);
    }
    const ourIds = new Set((me.assets || []).map((a) => a.id));

    // states per ref
    const st = {};
    const S = (ref) => (st[ref] = st[ref] || { offers: [], threads: [] });
    const myOffers = arr(d.myOffers && d.myOffers.offers ? d.myOffers.offers : d.myOffers);
    for (const o of myOffers) {
      if (o.status && o.status !== "open") continue;
      const giveRefs = refsOf(o.give), wantRefs = refsOf(o.want);
      if (o.maker === US) {
        if (giveRefs.length && wantRefs.length) {
          for (const r of giveRefs.concat(wantRefs)) { S(r).cambio = true; S(r).offers.push(o); }
        } else if (giveRefs.length) {
          for (const r of giveRefs) {
            if (o.thread) S(r).dealerOffer = o; else { S(r).venta = o.want && o.want.cash; }
            S(r).offers.push(o);
          }
        } else if (wantRefs.length) {
          for (const r of wantRefs) {
            if (o.thread) S(r).dealerOffer = o;
            else if (o.to) S(r).compra = o.give && o.give.cash;
            else S(r).puja = o.give && o.give.cash;
            S(r).offers.push(o);
          }
        }
      } else if (o.to === US) {
        for (const r of giveRefs.concat(wantRefs)) { S(r).offers.push(o); if (giveRefs.length && wantRefs.length) S(r).cambio = true; }
      }
    }
    // rival bids/asks from books
    for (const b of d.books || []) {
      for (const o of (b && b.offers) || []) {
        if (o.maker === US || (o.status && o.status !== "open")) continue;
        const wantRefs = refsOf(o.want), giveRefs = refsOf(o.give);
        for (const r of wantRefs) { S(r).rivalBids = (S(r).rivalBids || 0) + 1; S(r).offers.push(o); }
        for (const r of giveRefs) { S(r).rivalAsks = (S(r).rivalAsks || 0) + 1; S(r).offers.push(o); }
      }
    }
    // threads (open conversations)
    const nameToRef = {};
    for (const id in cardInfo) nameToRef[cardInfo[id].name] = id;
    for (const t of d.threads || []) {
      if (t.status && !["open", "negotiating", "active"].includes(t.status)) continue;
      const refs = new Set();
      const tp = t.topic || {};
      for (const side of ["buy", "sell"]) {
        const x = tp[side];
        if (!x) continue;
        if (x.card) refs.add(x.card);
        for (const aid of x.assets || []) {
          const a = (me.assets || []).find((z) => z.id === aid);
          if (a && a.ref) refs.add(a.ref);
          else if (d.cards && d.cards[aid]) refs.add(d.cards[aid].ref);
        }
      }
      if (t.item && nameToRef[t.item]) refs.add(nameToRef[t.item]);
      for (const r of refs) { S(r).threads.push(t); S(r).dealer = t.with; }
    }
    // protected
    const prot = new Set();
    const pr = (d.status && d.status.control && d.status.control.protected) || [];
    for (const p of pr) {
      if (typeof p === "string") prot.add(p);
      else if (typeof p === "number") {
        const a = (me.assets || []).find((z) => z.id === p);
        if (a) prot.add(a.ref);
      } else if (p && p.ref) prot.add(p.ref);
    }
    // market price from settlements
    const market = {};
    for (const r of d.feed || []) {
      if (r.type !== "settlement") continue;
      const p = r.payload || {};
      const cards = (p.items || []).filter((i) => i.kind === "card");
      if (cards.length !== 1 || !(p.price > 0) || (p.items || []).length !== 1) continue;
      (market[cards[0].ref] = market[cards[0].ref] || []).push({ tick: r.tick, price: p.price, ts: r.ts, venue: p.venue, persona: p.persona, parties: p.parties });
    }

    const album = {};
    for (const p of (me.album && me.album.pages) || []) album[p.set] = p;

    const cards = {};
    for (const s of sets) {
      for (const c of s.cards || []) {
        const own = owned[c.id] || [];
        const x = st[c.id] || { offers: [], threads: [] };
        const mk = market[c.id] || [];
        const states = {};
        if (own.length > 1) states.dup = own.length;
        if (x.venta != null) states.venta = x.venta;
        if (x.compra != null) states.compra = x.compra;
        if (x.puja != null) states.puja = x.puja;
        if (x.cambio) states.cambio = true;
        if (x.threads.length || x.dealerOffer) states.dealer = x.dealer || (x.dealerOffer && x.dealerOffer.to) || true;
        if (!own.length && c.page && TARGET_SETS.includes(s.id) && s.released) states.objetivo = true;
        if (prot.has(c.id)) states.protegida = true;
        cards[c.id] = {
          info: { ...c, set: s.id, setName: s.name },
          own, ourValue: own.length ? Math.max(...own.map((a) => a.your_value || 0)) : null,
          market: mk.length ? mk[mk.length - 1].price : null, marketHist: mk,
          book: c.book, states, offers: x.offers, threads: x.threads, rivalBids: x.rivalBids || 0,
        };
      }
    }
    return { cat, me, sets, values, cards, album, decisions: d.decisions || [], cardsRec: d.cards || {}, feed: d.feed || [], prot };
  }

  // ---------- rendering ----------
  function chip(id, text) {
    return h("span", { class: "cc-chip cc-chip-" + id }, icon(id), text);
  }
  function cardChips(c) {
    const s = c.states, out = [];
    if (s.protegida) out.push(chip("protegida", "PROTEGIDA"));
    if (s.venta != null) out.push(chip("venta", "EN VENTA " + fmtN(s.venta, 0)));
    if (s.dealer) out.push(chip("dealer", "DEALER" + (typeof s.dealer === "string" ? " · " + s.dealer : "")));
    if (s.cambio) out.push(chip("cambio", "CAMBIO ofrecido"));
    if (s.compra != null) out.push(chip("compra", "COMPRANDO " + fmtN(s.compra, 0)));
    if (s.puja != null) out.push(chip("puja", "PUJA ≤" + fmtN(s.puja, 0)));
    if (s.objetivo) out.push(chip("objetivo", "OBJETIVO"));
    if (s.dup) out.push(chip("dup", "×" + s.dup));
    return out;
  }
  // Official artwork: dashboard/cards.json (ref -> inline SVG), written by tools/fetch_cards.py from
  // bazaar.causaprima.ai. Our own trusted file, so it goes in with innerHTML.
  const ART = { map: null, at: 0 };
  async function loadArt() {
    if (ART.map && Date.now() - ART.at < 10 * 60 * 1000) return ART.map;
    try {
      const r = await fetch("static/cards.json", { cache: "no-store" });
      if (r.ok) { const j = await r.json(); if (j && typeof j === "object") { ART.map = j; ART.at = Date.now(); } }
    } catch (e) { /* keep the fallback design */ }
    return ART.map || {};
  }
  // Our port of the official card component (static/cromo.js), used for the official empty slot.
  const CROMO = { mod: null, tried: false, sets: {} };
  function loadCromo() {
    if (CROMO.tried) return Promise.resolve(CROMO.mod);
    CROMO.tried = true;
    return import(new URL("static/cromo.js", document.baseURI).href)
      .then((m) => (CROMO.mod = m && typeof m.cromo === "function" ? m : null))
      .catch(() => null);
  }
  function slotHtml(i) {
    if (!CROMO.mod) return null;
    const set = CROMO.sets[i.set] || { id: i.set };
    try {
      return CROMO.mod.cromo(i, { set: { ...set, color: SET_COLORS[i.set] || set.color }, size: "md", fluid: true, state: "missing" });
    } catch (e) { return null; }
  }
  function artOf(ref) {
    const svg = ART.map && ART.map[ref];
    return typeof svg === "string" && svg.startsWith("<svg") ? svg : null;
  }
  // States that are active on a card, in priority order: the first one colours the frame.
  const BADGE_COLORS = { venta: "#FF6B6B", compra: "#3DDC97", puja: "#F2A541", cambio: "#4C8DFF", dealer: "#2EC4B6", objetivo: "#E8EBF0", dup: "#9AA4B8", protegida: "#B9C0CC" };
  function cardBadges(c) {
    const s = c.states, out = [];
    if (s.venta != null) out.push(["venta", "VENTA " + fmtN(s.venta, 0)]);
    if (s.compra != null) out.push(["compra", "COMPRA " + fmtN(s.compra, 0)]);
    if (s.puja != null) out.push(["puja", "PUJA ≤" + fmtN(s.puja, 0)]);
    if (s.cambio) out.push(["cambio", "CAMBIO"]);
    if (s.dealer) out.push(["dealer", "CONV" + (typeof s.dealer === "string" ? " " + s.dealer : "")]);
    if (s.objetivo) out.push(["objetivo", "OBJETIVO"]);
    if (s.dup) out.push(["dup", "×" + s.dup]);
    if (s.protegida) out.push(["protegida", "PROT"]);
    return out;
  }
  function renderArtCard(c, onOpen, svg) {
    const i = c.info;
    const have = c.own.length > 0;
    const serials = c.own.map((a) => "#" + a.serial).join(" ");
    const badges = cardBadges(c);
    const frame = badges.length ? BADGE_COLORS[badges[0][0]] : null;
    const face = h("div", { class: "cc-face cromo--" + (i.rarity || "common") + (have ? "" : " is-slot"), html: svg });
    if (have && (i.rarity === "epic" || i.rarity === "legendary")) face.appendChild(h("div", { class: "cc-foil" }));
    if (badges.length) face.appendChild(h("div", { class: "cc-badges" }, badges.map(([id, text]) =>
      h("span", { class: "cc-badge", style: `--bc:${BADGE_COLORS[id]}` }, icon(id), text))));
    return h("button", {
      class: "cc-card cc-art" + (have ? " is-owned" : " is-missing") + (c.states.objetivo ? " is-target" : "") + (frame ? " has-state" : ""),
      style: `--set:${SET_COLORS[i.set] || "#888"};--rar:${RAR_COLORS[i.rarity] || "#888"}` + (frame ? `;--frame:${frame}` : ""),
      title: `${i.id} · ${i.name}` + (have ? ` · ${serials}/${i.print_run}` : " · falta") +
        ` · nuestro ${have ? fmtP(c.ourValue) : "—"} · mercado ${c.market != null ? fmtN(c.market, 0) : "—"} · libro ${fmtN(c.book, 0)}`,
      onclick: () => onOpen(i.id),
    },
      face,
      h("div", { class: "cc-vline" }, h("span", null, i.id), have ? h("b", null, fmtN(c.ourValue, 0) + " P") : null),
      h("div", { class: "cc-cname" }, i.name),
    );
  }
  function renderCard(c, small, onOpen) {
    const i = c.info;
    const svg = c.own.length ? artOf(i.id) : slotHtml(i);
    if (svg) return renderArtCard(c, onOpen, svg);
    const have = c.own.length > 0;
    const setColor = SET_COLORS[i.set] || "#888";
    const serials = c.own.map((a) => "#" + a.serial).join(" ");
    const el = h("button", {
      class: "cc-card" + (have ? " is-owned" : " is-missing") + (small ? " is-small" : "") + (c.states.objetivo ? " is-target" : ""),
      style: `--set:${setColor};--rar:${RAR_COLORS[i.rarity] || "#888"}`,
      title: `${i.id} · ${i.name}`,
      onclick: () => onOpen(i.id),
    },
      h("div", { class: "cc-card-head" }, h("span", { class: "cc-ref" }, small ? (i.rarity === "epic" ? "ÉPICA" : "LEYEND.") : i.id), h("span", { class: "cc-rdot" })),
      small
        ? h("div", { class: "cc-card-body" }, h("div", { class: "cc-ref-s" }, i.id), h("div", { class: "cc-sub" }, have ? (serials + " · " + fmtP(c.ourValue)) : (c.own.length + "/" + (i.print_run || "?"))))
        : h("div", { class: "cc-card-body" },
          h("div", { class: "cc-name" }, i.name),
          h("div", { class: "cc-sub" }, have ? `${serials}/${i.print_run}` : "falta"),
          h("div", { class: "cc-spacer" }),
          h("div", { class: "cc-val" }, have ? fmtP(c.ourValue) : "—"),
          h("div", { class: "cc-mini" }, "m " + (c.market != null ? fmtN(c.market, 0) : "—") + " · l " + fmtN(c.book, 0))),
      small ? null : h("div", { class: "cc-chips" }, cardChips(c)),
    );
    return el;
  }

  function matchFilter(c, f) {
    if (f.set !== "todos" && c.info.set !== f.set) return false;
    if (f.rarity !== "todas" && c.info.rarity !== f.rarity) return false;
    if (f.states.size) {
      for (const s of f.states) if (c.states[s] != null && c.states[s] !== false) return true;
      return false;
    }
    return true;
  }

  function renderAlbum(m, f, onOpen) {
    const wrap = h("div", { class: "cc-album" });
    for (const s of m.sets) {
      if (f.set !== "todos" && s.id !== f.set) continue;
      const color = SET_COLORS[s.id] || s.color;
      const page = m.album[s.id] || {};
      const pageCards = (s.cards || []).filter((c) => c.page);
      const extra = (s.cards || []).filter((c) => !c.page);
      const have = page.have != null ? page.have : pageCards.filter((c) => m.cards[c.id].own.length).length;
      const of = page.of || pageCards.length || 10;
      if (!s.released) {
        wrap.appendChild(h("div", { class: "cc-set cc-set-closed", style: `--set:${color}` },
          h("b", null, s.id), h("span", null, s.name), h("span", { class: "cc-muted" }, `sin lanzar · se abre en ${s.release || "?"} · ${have}/${of}`)));
        continue;
      }
      const setVal = (s.cards || []).reduce((a, c) => a + m.cards[c.id].own.reduce((x, y) => x + (y.your_value || 0), 0), 0);
      const aff = m.me.affinity ? m.me.affinity[s.id] : null;
      const bonus = m.values.page_bonus;
      const segs = h("div", { class: "cc-segs" }, pageCards.map((c) => h("i", { class: m.cards[c.id].own.length ? "on" : "" })));
      const side = h("div", { class: "cc-set-side" },
        h("div", { class: "cc-set-title" }, h("b", null, s.id), " ", s.name),
        h("div", { class: "cc-set-page" }, h("span", null, `página ${have}/${of}`), h("span", { class: page.complete ? "cc-bonus on" : "cc-bonus" }, page.complete ? `bono +${Math.round((bonus || 0) * 100)} %` : "bono —")),
        segs,
        h("div", { class: "cc-kv" }, h("span", null, "Valor del set"), h("b", null, fmtP(setVal))),
        h("div", { class: "cc-kv" }, h("span", null, "Afinidad"), h("b", null, aff != null ? "×" + fmtN(aff, 1) : "—")),
        page.master ? h("div", { class: "cc-kv" }, h("span", null, "Maestro"), h("b", null, "sí")) : null);
      const grid = h("div", { class: "cc-grid" + ((CROMO.mod || pageCards.some((c) => artOf(c.id))) ? " has-art" : "") });
      let shown = 0;
      for (const c of pageCards) {
        const cm = m.cards[c.id];
        const ok = matchFilter(cm, f);
        const n = renderCard(cm, false, onOpen);
        if (!ok) n.classList.add("is-dim");
        else shown++;
        grid.appendChild(n);
      }
      const ex = h("div", { class: "cc-extra" }, h("div", { class: "cc-extra-t" }, "FUERA DE PÁGINA"),
        h("div", { class: "cc-extra-g" }, extra.map((c) => {
          const n = renderCard(m.cards[c.id], true, onOpen);
          if (!matchFilter(m.cards[c.id], f)) n.classList.add("is-dim"); else shown++;
          return n;
        })));
      const row = h("section", { class: "cc-set" + (grid.classList.contains("has-art") ? " has-art" : ""), style: `--set:${color}` }, side, grid, ex);
      if (f.states.size && !shown) row.classList.add("is-hidden");
      wrap.appendChild(row);
    }
    if (!wrap.children.length) wrap.appendChild(stateBox("empty", "Ningún set coincide con los filtros."));
    return wrap;
  }

  function kpi(label, value, sub) {
    if (U().kpi) return U().kpi({ label, value, sub });
    return h("div", { class: "cc-kpi" }, h("div", { class: "cc-kpi-l" }, label), h("div", { class: "cc-kpi-v" }, h("b", null, value), " ", h("span", null, sub || "")));
  }
  function renderTotals(m) {
    const me = m.me, sc = me.score || {};
    const pages = (me.album && me.album.pages) || [];
    const complete = pages.filter((p) => p.complete);
    let mkt = 0, book = 0, dups = 0, dupSale = 0;
    for (const id in m.cards) {
      const c = m.cards[id];
      for (const a of c.own) { mkt += c.market != null ? c.market : c.book || 0; book += c.book || 0; }
      if (c.own.length > 1) { dups += c.own.length - 1; if (c.states.venta != null) dupSale++; }
    }
    const filled = sc.album_filled != null ? sc.album_filled : pages.reduce((a, p) => a + (p.have || 0), 0);
    const slots = sc.album_slots != null ? sc.album_slots : pages.reduce((a, p) => a + (p.of || 0), 0);
    return h("div", { class: "cc-kpis" },
      kpi("ÁLBUM", `${filled}/${slots}`, "de página"),
      kpi("PÁGINAS", `${complete.length} de ${pages.length || m.sets.length}`, complete.map((p) => p.set).join(" · ")),
      kpi("VALOR NUESTRO", fmtP(me.collection_value), "con bonos"),
      kpi("MERCADO", fmtP(mkt), "último precio"),
      kpi("LIBRO", fmtP(book), "valor de catálogo"),
      kpi("DUPLICADAS", String(dups), `${dupSale} en venta`));
  }

  function renderFilters(f, counts, onChange) {
    const bar = h("div", { class: "cc-filters" });
    for (const s of STATES) {
      const on = f.states.has(s.id);
      bar.appendChild(h("button", {
        class: "cc-fbtn cc-chip-" + s.id + (on ? " on" : ""),
        onclick: () => { on ? f.states.delete(s.id) : f.states.add(s.id); onChange(); },
      }, icon(s.id), s.label, h("span", { class: "cc-fcount" }, String(counts[s.id] || 0))));
    }
    const sel = (val, opts, onSel) => {
      const n = h("select", { class: "cc-select", onchange: (e) => onSel(e.target.value) },
        opts.map(([v, l]) => h("option", { value: v, selected: v === val ? "selected" : null }, l)));
      return n;
    };
    bar.appendChild(h("span", { class: "cc-grow" }));
    bar.appendChild(sel(f.set, [["todos", "Set: todos"]].concat(Object.keys(SET_COLORS).map((k) => [k, "Set: " + k])), (v) => { f.set = v; onChange(); }));
    bar.appendChild(sel(f.rarity, [["todas", "Rareza: todas"]].concat(Object.keys(RAR_LABEL).map((k) => [k, "Rareza: " + RAR_LABEL[k]])), (v) => { f.rarity = v; onChange(); }));
    return bar;
  }

  // ---------- drawer ----------
  function decisionText(d) {
    const parts = [];
    if (d.action) parts.push(d.action);
    for (const k of ["why", "reason", "reasoning", "rationale"]) if (d[k]) parts.push(String(d[k]));
    if (d.ask != null) parts.push("pide " + d.ask + " P");
    if (d.floor != null) parts.push("suelo " + d.floor);
    if (d.limit != null) parts.push("límite " + d.limit);
    if (d.price != null) parts.push("precio " + d.price);
    if (d.gain != null) parts.push("ganancia " + d.gain);
    if (d.gain_if_sold != null) parts.push("ganancia si se vende " + d.gain_if_sold);
    if (d.kwargs && d.kwargs.price != null) parts.push("precio " + d.kwargs.price);
    if (Array.isArray(d.args) && typeof d.args[1] === "string") parts.push("«" + d.args[1] + "»");
    return parts.join(" · ");
  }
  function offerLine(o) {
    const giveR = refsOf(o.give), wantR = refsOf(o.want);
    let type = "anuncio", label = "Oferta", price = "";
    if (giveR.length && wantR.length) { type = "cambio"; label = "Cambio"; price = giveR.join("+") + " ↔ " + wantR.join("+"); }
    else if (giveR.length) { type = "venta"; label = "Venta"; price = fmtP(o.want && o.want.cash); }
    else if (wantR.length) { type = "puja"; label = "Puja"; price = "≤ " + fmtP(o.give && o.give.cash); }
    const who = o.maker === US ? "Nosotros" : o.maker;
    const where = o.venue || (o.thread ? "conversación " + o.thread : (o.to ? "a " + o.to : ""));
    return h("div", { class: "cc-line cc-t-" + type + (o.maker === US ? " is-us" : "") },
      h("span", { class: "cc-line-t" }, label), h("span", { class: "cc-line-m" }, `${who} · ${where}` + (o.expires_tick ? ` · vence t${o.expires_tick}` : "")), h("b", null, price));
  }
  function openDrawer(m, ref) {
    const c = m.cards[ref];
    if (!c) return;
    const i = c.info;
    const body = h("div", { class: "scr-coleccion cc-drawer" });
    // header chips
    const tags = h("div", { class: "cc-dtags" });
    if (c.own.length) tags.appendChild(h("span", { class: "cc-tag" }, "En mano ×" + c.own.length));
    else tags.appendChild(h("span", { class: "cc-tag" }, "Falta"));
    for (const x of cardChips(c)) tags.appendChild(x);
    if (c.rivalBids) tags.appendChild(chip("puja", c.rivalBids + " pujas rivales"));
    body.appendChild(tags);
    const page = m.album[i.set] || {};
    body.appendChild(h("div", { class: "cc-dkpis" },
      kpi("VALOR NUESTRO", c.own.length ? fmtP(c.ourValue) : "—"),
      kpi("MERCADO", c.marketHist.length ? (Math.min(...c.marketHist.map((x) => x.price)) + "–" + Math.max(...c.marketHist.map((x) => x.price)) + " P") : "sin ventas"),
      kpi("LIBRO", fmtP(c.book)),
      kpi("AFINIDAD " + i.set, m.me.affinity && m.me.affinity[i.set] != null ? "×" + fmtN(m.me.affinity[i.set], 1) : "—"),
      kpi("PÁGINA", page.of ? `${page.have}/${page.of}` : "—")));
    // big card + facts
    body.appendChild(h("div", { class: "cc-dhero" },
      h("div", { class: "cc-dcard" }, renderCard(c, false, () => {})),
      h("div", { class: "cc-dfacts" },
        h("div", null, `${i.set} · ${i.setName} · ${RAR_LABEL[i.rarity] || i.rarity}`),
        i.flavour ? h("div", { class: "cc-flav" }, i.flavour) : null,
        h("div", { class: "cc-muted" }, `tirada ${i.print_run} · acuñadas ${i.minted != null ? i.minted : "?"} · ${i.page ? "de página" : "fuera de página"}`),
        c.own.length ? h("div", null, "Nuestras copias: " + c.own.map((a) => `#${a.serial} (id ${a.id}, ${fmtP(a.your_value)})`).join(", ")) : null)));
    // price history
    body.appendChild(h("div", { class: "cc-dsec" }, "PRECIO DE " + ref + " · VENTAS REGISTRADAS"));
    if (c.marketHist.length) {
      const vals = c.marketHist.map((x) => x.price);
      if (U().sparkline) body.appendChild(U().sparkline(vals, { w: 440, h: 70 }));
      body.appendChild(h("div", { class: "cc-list" }, c.marketHist.slice(-8).reverse().map((x) =>
        h("div", { class: "cc-line" }, h("span", { class: "cc-line-t" }, "t" + x.tick), h("span", { class: "cc-line-m" }, (x.parties || []).join(" → ") + (x.venue ? " · " + x.venue : x.persona ? " · " + x.persona : "")), h("b", null, fmtP(x.price))))));
    } else body.appendChild(stateBox("empty", "Sin ventas registradas de esta carta en el feed."));
    // card history
    body.appendChild(h("div", { class: "cc-dsec" }, "HISTORIA DE LA CARTA"));
    const copies = Object.values(m.cardsRec || {}).filter((x) => x && x.ref === ref);
    const hist = [];
    for (const cp of copies) for (const ev of cp.history || []) hist.push({ ...ev, serial: cp.serial, owner: cp.owner });
    hist.sort((a, b) => (b.tick || 0) - (a.tick || 0));
    if (hist.length) body.appendChild(h("div", { class: "cc-list" }, hist.slice(0, 25).map((e) =>
      h("div", { class: "cc-line" + (e.to === US || e.from === US ? " is-us" : "") }, h("span", { class: "cc-line-t" }, "t" + e.tick), h("span", { class: "cc-line-m" }, `#${e.serial}: ${e.from} → ${e.to}` + (e.why ? " · " + e.why : "")), h("b", null, e.price != null ? fmtP(e.price) : "")))));
    else body.appendChild(stateBox("empty", "La grabadora aún no tiene el historial de esta carta."));
    // offers
    body.appendChild(h("div", { class: "cc-dsec" }, "OFERTAS ABIERTAS SOBRE " + ref));
    const seen = new Set();
    const offs = c.offers.filter((o) => (seen.has(o.id) ? false : seen.add(o.id)));
    if (offs.length) body.appendChild(h("div", { class: "cc-list" }, offs.map(offerLine)));
    else body.appendChild(stateBox("empty", "No hay ofertas abiertas."));
    // reasoning
    const ids = new Set(c.own.map((a) => a.id));
    const decs = m.decisions.filter((d) => {
      if (d.ref === ref || d.item === ref || (d.in_refs || []).includes(ref) || (d.out_refs || []).includes(ref)) return true;
      if (ids.has(d.asset) || (d.out_ids || []).some((x) => ids.has(x))) return true;
      try { return JSON.stringify(d).includes('"' + ref + '"'); } catch (e) { return false; }
    }).slice(-6).reverse();
    body.appendChild(h("div", { class: "cc-dsec" }, "QUÉ HA DECIDIDO EL BOT"));
    if (decs.length) body.appendChild(h("div", { class: "cc-reason" }, decs.map((d) =>
      h("div", { class: "cc-line" }, h("span", { class: "cc-line-t" }, d.strategy || ""), h("span", { class: "cc-line-m" }, decisionText(d)), h("b", null, typeof d.at === "string" ? d.at.slice(11, 16) : "")))));
    else body.appendChild(stateBox("empty", "Ninguna decisión del bot menciona esta carta."));

    const title = `${i.id} · ${i.name}`;
    if (U().drawer) U().drawer({ title, body });
    else { document.querySelectorAll(".cc-fallback-drawer").forEach((n) => n.remove()); document.body.appendChild(h("div", { class: "cc-fallback-drawer" }, h("button", { onclick: (e) => e.target.parentNode.remove() }, "×"), h("h3", null, title), body)); }
  }

  // ---------- data ----------
  const S = { filters: { states: new Set(), set: "todos", rarity: "todas" }, model: null, slow: {}, slowAt: 0, opened: null };

  async function load(data) {
    const api = window.api;
    if (!api) throw new Error("api.js no cargado");
    const [catalog, me, myOffers, status, decisions] = await Promise.all([
      safe(() => api.rec("catalog")), safe(() => api.rec("me")), safe(() => api.rec("my_offers")),
      safe(() => api.status()), safe(() => api.decisions()), loadArt(), loadCromo(),
    ]);
    if (!catalog.ok) throw catalog.err;
    const now = Date.now();
    if (now - S.slowAt > 15000) {
      S.slowAt = now;
      const [venues, threads, cards, feed] = await Promise.all([
        safe(() => api.rec("venues")), safe(() => api.recThreads()), safe(() => api.rec("cards")),
        safe(() => api.recStream("feed", { tail: 3000 })),
      ]);
      const vids = ["rastro"].concat(arr(venues.ok ? venues.v.venues || venues.v : []).map((v) => v.venue || v.id).filter(Boolean));
      const books = await Promise.all([...new Set(vids)].map((v) => safe(() => api.rec("books/" + v))));
      S.slow = {
        threads: threads.ok ? arr(threads.v) : [],
        cards: cards.ok ? cards.v : {},
        feed: feed.ok ? arr(feed.v.rows || feed.v) : [],
        books: books.filter((b) => b.ok).map((b) => b.v),
      };
    }
    return {
      catalog: catalog.v, me: me.ok ? me.v : {}, myOffers: myOffers.ok ? myOffers.v : [],
      status: status.ok ? status.v : (data && data.status) || {},
      decisions: decisions.ok ? arr(decisions.v) : [],
      ...S.slow,
    };
  }

  function paint(root) {
    const m = S.model;
    const host = root.querySelector(".cc-body");
    if (!m || !host) return;
    const scroll = root.scrollTop;
    const counts = {};
    for (const id in m.cards) for (const s in m.cards[id].states) counts[s] = (counts[s] || 0) + 1;
    const frag = document.createDocumentFragment();
    frag.appendChild(renderTotals(m));
    frag.appendChild(renderFilters(S.filters, counts, () => paint(root)));
    if (!(m.me.assets || []).length) frag.appendChild(stateBox("empty", "Aún no tenemos cartas grabadas (o la grabadora no ha leído /api/me)."));
    frag.appendChild(renderAlbum(m, S.filters, (ref) => { S.opened = ref; openDrawer(m, ref); }));
    host.replaceChildren(frag);
    root.scrollTop = scroll;
  }

  window.Screens = window.Screens || {};
  window.Screens["coleccion"] = {
    title: "Colección",
    mount(root, params) {
      root.replaceChildren(h("div", { class: "scr-coleccion" },
        h("div", { class: "cc-title" }, h("h1", null, "Colección"), h("span", { class: "cc-muted" }, "álbum por set · estados de cada carta")),
        h("div", { class: "cc-body" }, stateBox("loading"))));
      S.slowAt = 0;
      S.pendingOpen = params || null;
    },
    async refresh(root, data, params) {
      const host = root.querySelector(".cc-body");
      try {
        const d = await load(data);
        S.model = buildModel(d);
        paint(root);
        const want = params || S.pendingOpen;
        if (want && S.model.cards[want] && S.opened !== want) { S.opened = want; S.pendingOpen = null; openDrawer(S.model, want); }
      } catch (e) {
        if (host && !S.model) host.replaceChildren(stateBox("error", e));
      }
    },
    onParams(root, params) { if (params && S.model && S.model.cards[params]) { S.opened = params; openDrawer(S.model, params); } else S.pendingOpen = params || null; },
    unmount() { S.model = null; S.opened = null; },
    _test: { buildModel },
  };
})();
