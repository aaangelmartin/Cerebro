/* DUELOS · duelos vivos como conversaciones, resultados de la sesión y cinta de cierres del juego.
   Detalle: #duelos/<id> abre la conversación completa en el cajón lateral. */
(function () {
  "use strict";
  window.Screens = window.Screens || {};

  // ---------- helpers ----------
  const U = () => window.ui || {};
  const A = () => window.api || {};
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
  const tclock = (tick) => (U().tickClock ? U().tickClock(tick) : "t" + (tick ?? "?"));
  const pts = (n) => (n === null || n === undefined ? "—" : (n > 0 ? "+" : "") + fmtNum(n, 1));
  const items = (r, ...keys) => {
    if (Array.isArray(r)) return r;
    if (!r || typeof r !== "object") return [];
    for (const k of [...keys, "items", "rows", "duels"]) if (Array.isArray(r[k])) return r[k];
    return [];
  };
  async function safe(fn, fallback) {
    try { const f = fn(); return f && f.then ? await f : f === undefined ? fallback : f; }
    catch (e) { return { __error: e, __fallback: fallback }; }
  }
  const isErr = (x) => x && x.__error;
  const val = (x) => (isErr(x) ? x.__fallback : x);
  const isOurs = (m) => ["you", "us", "me", "self"].includes(String(m.from ?? m.sender ?? "").toLowerCase());
  const roleType = (d) => (d.role === "buyer" ? "compra" : "venta");
  const SRC = { opus: "opus", sonnet: "opus", haiku: "opus", council: "consejo", consejo: "consejo", fallback: "reserva", reserva: "reserva", code: "codigo", codigo: "codigo" };

  function sourceOf(dec, councilByAction) {
    if (!dec) return null;
    const a = dec.action || {};
    const c = councilByAction[a.id];
    const s = SRC[String(dec.source || a.source || "").toLowerCase()] || "codigo";
    if (c) {
      const votes = c.votes || [];
      const total = (c.roles || []).length || votes.length;
      const yes = votes.filter((v) => v.verdict !== "reject").length;
      return { src: "consejo", extra: `${yes}/${total}` };
    }
    return { src: s, extra: null };
  }
  const srcTag = (s) => (s ? comp("sourceTag", s.src, s.extra) || h("span", { class: "dl-src" }, s.src + (s.extra ? " " + s.extra : "")) : null);

  function moveText(dec) {
    const a = (dec && dec.action) || {};
    const p = a.params || {};
    if (a.kind === "duel_accept") {
      const e = p.expect || {};
      return `Aceptar ${fmtP(e.price)}${e.days != null ? " · " + e.days + " d" : ""}`;
    }
    if (a.kind === "duel_message") return `Ofrecer ${fmtP(p.price)}${p.days != null ? " · " + p.days + " d" : ""}`;
    return a.kind || "—";
  }

  // price bar config for one duel
  function barCfg(d, compact) {
    const limit = num(d.your_limit);
    const ours = num(d.your_offer && d.your_offer.price);
    const theirs = num(d.rival_offer && d.rival_offer.price);
    const prices = (d.messages || []).map((m) => num(m.price)).filter((x) => x !== null);
    const all = [limit, ours, theirs, num(d.price), ...prices].filter((x) => x !== null);
    if (!all.length) return null;
    let lo = Math.min(...all), hi = Math.max(...all);
    const pad = Math.max(2, Math.round((hi - lo) * 0.15) || Math.round(hi * 0.1));
    lo = Math.max(0, lo - pad); hi = hi + pad;
    let zone = null;
    if (limit !== null && theirs !== null) {
      if (d.role === "seller" && theirs >= limit) zone = [limit, theirs];
      if (d.role === "buyer" && theirs <= limit) zone = [theirs, limit];
    }
    const closed = d.status === "deal" ? { price: num(d.price) } : null;
    const history = (d.messages || []).filter((m) => num(m.price) !== null).map((m) => ({ who: isOurs(m) ? "ours" : "theirs", price: num(m.price) }));
    return { min: lo, max: hi, limit, ours, theirs, zone, closed, history, noDeal: d.status === "no_deal", compact: !!compact };
  }
  const priceBar = (d, compact) => {
    const cfg = barCfg(d, compact);
    return cfg ? comp("priceBar", cfg) || h("div", { class: "dl-muted" }, `Límite ${fmtP(cfg.limit)} · Nosotros ${fmtP(cfg.ours)} · Ellos ${fmtP(cfg.theirs)}`) : h("div", { class: "dl-muted" }, "Sin precios todavía");
  };

  // rounds strip + decay lost
  function roundsStrip(d) {
    const r = num(d.rounds) || 0;
    const decay = num(d.decay_per_round) ?? 0.06;
    const mult = Math.pow(1 - decay, r);
    const boxes = h("span", { class: "dl-rounds" });
    const n = Math.max(5, r + 1);
    for (let i = 0; i < Math.min(n, 10); i++) boxes.append(h("i", { class: i < r ? "on" : i === r ? "cur" : "" }));
    return h("span", { class: "dl-roundwrap", title: `Ronda ${r}: cada ronda pierde ${Math.round(decay * 100)} %` },
      boxes, h("span", { class: "dl-mono dl-muted" }, `r${r} · ×${fmtNum(mult, 2)}`),
      r > 0 ? h("span", { class: "dl-mono dl-bad" }, ` −${fmtNum((1 - mult) * 100, 0)} %`) : null);
  }

  // transcript: rounds numbered from priced messages
  function transcript(d, decsForDuel, councilByAction, withReason) {
    const box = h("div", { class: "dl-chat" });
    const msgs = d.messages || [];
    if (!msgs.length) { box.append(h("div", { class: "dl-muted dl-pad" }, "Sin mensajes todavía.")); return box; }
    let nOurs = 0, nTheirs = 0;
    for (const m of msgs) {
      const ours = isOurs(m);
      const priced = num(m.price) !== null;
      if (priced) ours ? nOurs++ : nTheirs++;
      const round = priced ? (ours ? nOurs : nTheirs) : null;
      const who = ours ? "Team 10 · Nosotros" : (d.rival || "Rival");
      const fig = [num(m.price) !== null ? fmtP(m.price) : null, num(m.days) !== null ? m.days + " d" : null].filter(Boolean).join(" · ");
      const head = h("div", { class: "dl-msg-h" },
        h("span", { class: "dl-who" }, who), h("span", { class: "dl-fig" }, fig, round ? h("small", {}, " r" + round) : null, h("small", { class: "dl-muted", title: "tick " + (m.tick ?? "?") }, " " + tclock(m.tick))));
      const msg = h("div", { class: "dl-msg " + (ours ? "us" : "them") }, head, h("div", { class: "dl-txt" }, m.text || ""));
      if (withReason && ours) {
        const dec = decsForDuel.find((x) => {
          const p = (x.action || {}).params || {};
          return (x.action || {}).kind === "duel_message" && num(p.price) === num(m.price) && Math.abs((x.tick ?? m.tick) - m.tick) <= 1;
        });
        if (dec) msg.append(h("div", { class: "dl-why" }, srcTag(sourceOf(dec, councilByAction)), h("span", {}, (dec.action || {}).reason || "")));
      }
      box.append(msg);
    }
    return box;
  }

  // ---------- state ----------
  const S = {
    view: "vivo", team: "todos", filter: null, root: null, drawerFor: null, scrolls: {},
    transcripts: {}, // id -> {count, data}
  };

  async function getTranscript(head) {
    const id = head.duel ?? head.id;
    const count = head.message_count ?? (head.messages || []).length;
    const c = S.transcripts[id];
    if (c && c.count === count && (c.data.status !== "live" || count === c.count) && c.fresh > Date.now() - 2500) return c.data;
    if (c && c.data.status && c.data.status !== "live" && c.count === count) return c.data;
    const r = await safe(() => A().recDuel(id), null);
    const data = val(r) || head;
    S.transcripts[id] = { count: data.message_count ?? count, data, fresh: Date.now() };
    return data;
  }

  // merge live server dict (current offers, rounds) with the full recorder transcript
  function merge(live, rec) {
    if (!rec) return live;
    if (!live) return rec;
    const msgs = (rec.messages || []).length >= (live.messages || []).length ? rec.messages : live.messages;
    return { ...rec, ...live, messages: msgs };
  }

  // ---------- render ----------
  function paneFor(d, ctx) {
    const id = d.duel ?? d.id;
    const decs = ctx.decsByDuel[id] || [];
    const last = decs[decs.length - 1];
    const ticksLeft = ctx.tick !== null && num(d.deadline_tick) !== null ? num(d.deadline_tick) - ctx.tick : null;
    const live = d.status === "live" || !d.status;
    const head = h("div", { class: "dl-pane-h" },
      h("div", { class: "dl-row" },
        comp("typeChip", "duelo", "Duelo") || h("b", {}, "Duelo"),
        comp("typeChip", roleType(d), roleType(d)) || h("span", {}, roleType(d)),
        h("b", { class: "dl-rival" }, d.rival || "Rival"),
        h("span", { class: "dl-sp" }),
        live ? h("span", { class: "dl-mono dl-muted" }, ticksLeft !== null ? `${Math.max(0, ticksLeft)} ticks` : "")
          : comp("resultChip", d.status === "deal" ? "cerrado" : "sin_acuerdo") || h("span", {}, d.status)),
      h("div", { class: "dl-row" }, h("span", { class: "dl-mono dl-item" }, d.item || ""), h("span", { class: "dl-sp" }), roundsStrip(d)));
    const chat = transcript(d, decs, ctx.councilByAction, false);
    chat.dataset.duel = id;
    let foot;
    if (live) {
      foot = h("div", { class: "dl-pane-f" }, h("span", { class: "dl-muted" }, "Siguiente: "),
        h("span", { class: "dl-next" }, last ? moveText(last) + (last.action && last.action.reason ? " — " + last.action.reason : "") : "esperando decisión del bot"),
        h("span", { class: "dl-sp" }), last ? srcTag(sourceOf(last, ctx.councilByAction)) : null);
    } else {
      foot = h("div", { class: "dl-pane-f" },
        h("span", {}, d.status === "deal" ? `Cerrado a ${fmtP(d.price)}${num(d.days) ? " · " + d.days + " d" : ""}` : "Sin acuerdo"),
        h("span", { class: "dl-sp" }), h("b", { class: "dl-mono " + ((num(d.result) || 0) > 0 ? "dl-ok" : "dl-muted") }, pts(num(d.result)) + " pts"));
    }
    return h("div", { class: "dl-pane", onclick: (e) => { if (!e.target.closest("a,button")) location.hash = "#duelos/" + id; } },
      head, h("div", { class: "dl-bar" }, priceBar(d, true)), chat, foot);
  }

  function resultsPanel(ctx) {
    const done = ctx.closedOurs;
    const deals = done.filter((d) => d.status === "deal");
    const points = done.reduce((s, d) => s + (num(d.result) || 0), 0);
    const rate = done.length ? deals.length / done.length : 0;
    const neg = done.filter((d) => (num(d.result) || 0) < 0).length;
    // pie share: our margin / (gap between the two limits is unknown) -> use margin vs our first ask
    const shares = deals.map((d) => {
      const lim = num(d.your_limit), p = num(d.price);
      const first = (d.messages || []).find((m) => isOurs(m) && num(m.price) !== null);
      if (lim === null || p === null || !first) return null;
      const span = Math.abs(num(first.price) - lim);
      return span > 0 ? Math.min(1, Math.abs(p - lim) / span) : null;
    }).filter((x) => x !== null);
    const share = shares.length ? shares.reduce((a, b) => a + b, 0) / shares.length : null;
    const R = 26, C = 2 * Math.PI * R;
    const donut = `<svg viewBox="0 0 64 64" width="72" height="72" class="dl-donut"><circle cx="32" cy="32" r="${R}" class="bg"/><circle cx="32" cy="32" r="${R}" class="fg" stroke-dasharray="${(C * rate).toFixed(1)} ${C.toFixed(1)}" transform="rotate(-90 32 32)"/><text x="32" y="36" text-anchor="middle">${Math.round(rate * 100)} %</text></svg>`;
    const d = h("div", { class: "dl-donutwrap" }); d.innerHTML = donut;
    const line = (k, v, cls) => h("div", { class: "dl-kv" }, h("span", {}, k), h("b", { class: "dl-mono " + (cls || "") }, v));
    return h("div", { class: "dl-results" }, h("div", { class: "dl-sec" }, "Resultado · nuestros duelos"),
      done.length ? h("div", { class: "dl-row dl-top" }, d, h("div", { class: "dl-grow" },
        line("Puntos de duelo", fmtNum(points, 1)),
        line("Cerrados · con acuerdo", `${done.length} · ${deals.length}`),
        line("Media por duelo", pts(done.length ? points / done.length : null), "dl-ok"),
        line("Cuota del pastel (vs. 1.ª oferta)", share === null ? "—" : Math.round(share * 100) + " %"),
        line("Sin acuerdo", String(done.length - deals.length), "dl-bad"),
        neg ? line("Fuera de límite", String(neg), "dl-bad") : null))
        : comp("empty", "Aún no hay duelos cerrados.") || h("div", { class: "dl-muted" }, "Aún no hay duelos cerrados."));
  }

  // big scoreboard over every duel we have played (all sessions, from the recorder)
  function scoreboard(ctx) {
    const all = ctx.heads;
    const live = all.filter((d) => !d.status || d.status === "live");
    const done = all.filter((d) => d.status && d.status !== "live");
    const deals = done.filter((d) => d.status === "deal");
    const won = deals.filter((d) => (num(d.result) || 0) > 0);
    const lost = done.filter((d) => (num(d.result) || 0) < 0);
    const even = deals.filter((d) => (num(d.result) || 0) === 0);
    const noDeal = done.filter((d) => d.status !== "deal");
    const points = done.reduce((s, d) => s + (num(d.result) || 0), 0);
    const cell = (label, value, tone, sub) => h("div", { class: "dl-sc " + (tone ? "tone-" + tone : "") },
      h("span", { class: "dl-sc-l" }, label), h("b", { class: "dl-sc-v dl-mono" }, value), sub ? h("span", { class: "dl-sc-s" }, sub) : null);
    const pct = (n) => (done.length ? Math.round((n / done.length) * 100) + " %" : "");
    return h("div", { class: "dl-score" },
      cell("Jugados", String(all.length), "", `${done.length} terminados`),
      cell("Ganados", String(won.length), "ok", pct(won.length)),
      cell("Perdidos", String(lost.length), "bad", lost.length ? pct(lost.length) : "fuera de límite"),
      cell("Sin acuerdo", String(noDeal.length), "warn", pct(noDeal.length)),
      even.length ? cell("Acuerdo a 0", String(even.length), "", pct(even.length)) : null,
      cell("En juego", String(live.length), "live", live.length ? "ahora" : "ninguno"),
      cell("Puntos", pts(points), points > 0 ? "ok" : points < 0 ? "bad" : "", "de duelos"),
      cell("Media", pts(done.length ? points / done.length : null), "", "por duelo"));
  }

  function tapePanel(ctx) {
    const rows = ctx.tape.filter((e) => S.team !== "nosotros" || ctx.ourIds.has(+e.payload.duel));
    const box = h("div", { class: "dl-tape" }, h("div", { class: "dl-sec" }, "Cierres de duelo · todo el juego"));
    if (ctx.tapeErr) { box.append(comp("error", ctx.tapeErr) || h("div", {}, "Error al leer el feed")); return box; }
    if (!rows.length) { box.append(comp("empty", "Sin cierres de duelo todavía.") || h("div", { class: "dl-muted" }, "Sin cierres")); return box; }
    for (const e of rows.slice(0, 80)) {
      const p = e.payload || {};
      const ours = ctx.ourIds.has(+p.duel);
      const rec = ours ? ctx.byId[+p.duel] : null;
      const cells = [
        h("div", { class: "dl-row" }, comp("typeChip", "duelo", "Duelo") || "Duelo", ours ? comp("teamTag", "t10", { us: true }) || h("b", {}, "Team 10 · Nosotros") : h("span", { class: "dl-muted" }, "#" + p.duel),
          h("span", { class: "dl-sp" }), rec ? h("b", { class: "dl-mono " + ((num(rec.result) || 0) > 0 ? "dl-ok" : "dl-muted") }, pts(num(rec.result))) : null),
        h("div", { class: "dl-row" }, h("span", {}, (p.item || "") + (rec ? " · vs " + (rec.rival || "") : "")), h("span", { class: "dl-sp" }),
          h("span", { class: "dl-mono dl-muted" }, (p.status === "deal" ? (rec && rec.price != null ? fmtP(rec.price) : "acuerdo") : "sin acuerdo") + " · " + tclock(e.tick))),
      ];
      const onClick = ours ? () => { location.hash = "#duelos/" + p.duel; } : null;
      const r = comp("row", { type: "duelo", cells: [h("div", {}, ...cells)], cols: "1fr", onClick, us: ours }) || h("div", { class: "dl-trow" }, ...cells);
      if (ours) r.classList.add("dl-us");
      box.append(r);
    }
    return box;
  }

  function segmented(opts, cur, onPick) {
    return h("div", { class: "dl-seg" }, ...opts.map(([id, label]) =>
      h("button", { class: id === cur ? "on" : "", type: "button", onclick: () => onPick(id) }, label)));
  }

  // ---------- drawer ----------
  function priceTrack(d) {
    const msgs = (d.messages || []).filter((m) => num(m.price) !== null);
    const lim = num(d.your_limit);
    if (!msgs.length) return h("div", { class: "dl-muted" }, "Sin precios.");
    const ticks = msgs.map((m) => +m.tick || 0), prices = msgs.map((m) => +m.price).concat(lim !== null ? [lim] : []);
    const t0 = Math.min(...ticks), t1 = Math.max(...ticks, t0 + 1);
    const p0 = Math.min(...prices), p1 = Math.max(...prices, p0 + 1);
    const W = 480, H = 140, P = 24;
    const x = (t) => P + ((t - t0) / (t1 - t0)) * (W - 2 * P), y = (p) => H - P - ((p - p0) / (p1 - p0)) * (H - 2 * P);
    const path = (arr) => arr.map((m, i) => (i ? "L" : "M") + x(+m.tick).toFixed(1) + " " + y(+m.price).toFixed(1)).join(" ");
    const ours = msgs.filter(isOurs), theirs = msgs.filter((m) => !isOurs(m));
    const dots = (arr, cls) => arr.map((m) => `<circle class="${cls}" cx="${x(+m.tick).toFixed(1)}" cy="${y(+m.price).toFixed(1)}" r="3.5"/>`).join("");
    const svg = `<svg viewBox="0 0 ${W} ${H}" class="dl-track">
      ${lim !== null ? `<line class="lim" x1="${P}" x2="${W - P}" y1="${y(lim)}" y2="${y(lim)}"/><text class="lbl" x="${W - P}" y="${y(lim) - 4}" text-anchor="end">Límite ${lim}</text>` : ""}
      ${d.status === "deal" && num(d.price) !== null ? `<line class="deal" x1="${P}" x2="${W - P}" y1="${y(+d.price)}" y2="${y(+d.price)}"/>` : ""}
      <path class="us" d="${path(ours)}"/><path class="them" d="${path(theirs)}"/>${dots(ours, "us")}${dots(theirs, "them")}
      <text class="lbl" x="${P}" y="${H - 6}">t${t0}</text><text class="lbl" x="${W - P}" y="${H - 6}" text-anchor="end">t${t1}</text>
      <text class="lbl" x="2" y="${y(p1) + 4}">${p1}</text><text class="lbl" x="2" y="${y(p0)}">${p0}</text></svg>`;
    const wrap = h("div", {}); wrap.innerHTML = svg;
    wrap.append(h("div", { class: "dl-legend" }, h("span", { class: "us" }, "● Nosotros"), h("span", { class: "them" }, "○ Ellos"), h("span", {}, "— Límite")));
    return wrap;
  }

  function drawerBody(d, ctx) {
    const id = d.duel ?? d.id;
    const decs = ctx.decsByDuel[id] || [];
    const body = h("div", { class: "scr-duelos dl-drawer" });
    body.append(h("div", { class: "dl-row" }, comp("typeChip", "duelo", "Duelo") || "Duelo", comp("typeChip", roleType(d), roleType(d)) || "",
      h("span", { class: "dl-muted dl-mono" }, `sesión ${d.session ?? "?"} · #${id}`), h("span", { class: "dl-sp" }),
      comp("resultChip", d.status === "deal" ? "cerrado" : d.status === "no_deal" ? "sin_acuerdo" : "pendiente") || d.status));
    body.append(h("h3", { class: "dl-dtitle" }, `${d.rival || "Rival"} · ${d.item || ""}`));
    body.append(h("div", { class: "dl-row" }, roundsStrip(d), h("span", { class: "dl-sp" }),
      h("span", { class: "dl-mono dl-muted" }, `límite ${fmtP(d.your_limit)} · ${d.limit_meaning || ""}`)));
    if (d.your_days_weight != null) body.append(h("div", { class: "dl-muted" }, `Días: peso ${d.your_days_weight} · ${d.days_meaning || ""}`));
    body.append(h("div", { class: "dl-bar" }, priceBar(d, false)));
    body.append(h("div", { class: "dl-sec" }, "Precio por mensaje"), priceTrack(d));
    body.append(h("div", { class: "dl-sec" }, `Conversación · ${(d.messages || []).length} mensajes`), transcript(d, decs, ctx.councilByAction, true));
    // reasoning per move
    body.append(h("div", { class: "dl-sec" }, `Decisiones del bot · ${decs.length}`));
    if (!decs.length) body.append(h("div", { class: "dl-muted" }, "No hay decisiones registradas para este duelo."));
    for (const dec of decs.slice().reverse()) {
      const a = dec.action || {};
      const c = ctx.councilByAction[a.id];
      const o = ctx.outByAction[a.id];
      const v = dec.verdict || {};
      const status = !v.ok ? "vetado" : dec.dry_run ? "sin_enviar" : o ? ({ sent: "enviado", deal: "cerrado", no_deal: "sin_acuerdo", refused: "rechazado", error: "rechazado", vetoed: "vetado", expired: "sin_acuerdo" }[o.status] || "pendiente") : "pendiente";
      const card = h("div", { class: "dl-dec" },
        h("div", { class: "dl-row" }, h("span", { class: "dl-mono dl-muted", title: "tick " + (dec.tick ?? "?") }, tclock(dec.tick)), h("b", {}, moveText(dec)), h("span", { class: "dl-sp" }),
          srcTag(sourceOf(dec, ctx.councilByAction)), comp("resultChip", status) || status),
        h("div", {}, a.reason || ""),
        !v.ok && (v.rail || v.detail) ? h("div", { class: "dl-bad" }, `Rail ${v.rail}: ${v.detail}`) : null,
        a.expected && Object.keys(a.expected).length ? h("div", { class: "dl-mono dl-muted dl-small" }, Object.entries(a.expected).map(([k, x]) => `${k} ${typeof x === "number" ? fmtNum(x, 2) : x}`).join(" · ")) : null,
        c ? h("div", { class: "dl-council" }, h("span", { class: "dl-muted" }, `Consejo: ${c.result || ""} — ${c.why || ""}`),
          ...(c.votes || []).map((vt) => h("div", { class: "dl-vote" }, h("b", {}, vt.role || "?"), h("span", { class: "dl-vv " + vt.verdict }, vt.verdict || ""), h("span", { class: "dl-muted" }, vt.reason || (vt.params && Object.keys(vt.params).length ? JSON.stringify(vt.params) : ""))))) : null,
        dec.id != null ? h("a", { href: "#supervision/" + dec.id, class: "dl-link" }, "Ver en Supervisión →") : null);
      body.append(card);
    }
    // outcome
    const r = num(d.result);
    body.append(h("div", { class: "dl-sec" }, "Resultado"));
    if (d.status === "live" || !d.status) {
      const lim = num(d.your_limit), th = num(d.rival_offer && d.rival_offer.price), dec = num(d.decay_per_round) ?? 0.06, rr = num(d.rounds) || 0;
      const marg = lim !== null && th !== null ? (d.role === "seller" ? th - lim : lim - th) : null;
      body.append(h("div", { class: "dl-out" },
        h("div", {}, h("small", {}, `Si aceptamos ${fmtP(th)}`), h("b", { class: "dl-mono " + ((marg || 0) > 0 ? "dl-ok" : "dl-bad") }, marg === null ? "—" : pts(marg * Math.pow(1 - dec, rr)) + " pts")),
        h("div", {}, h("small", {}, "Otra ronda"), h("b", { class: "dl-mono" }, `r${rr + 1} · ×${fmtNum(Math.pow(1 - dec, rr + 1), 2)}`)),
        h("div", {}, h("small", {}, `Sin acuerdo (${tclock(d.deadline_tick)})`), h("b", { class: "dl-mono dl-bad" }, "0 pts"))));
    } else {
      body.append(h("div", { class: "dl-out" },
        h("div", {}, h("small", {}, "Estado"), h("b", {}, d.status === "deal" ? "Acuerdo" : "Sin acuerdo")),
        h("div", {}, h("small", {}, "Precio"), h("b", { class: "dl-mono" }, d.price != null ? fmtP(d.price) + (num(d.days) ? " · " + d.days + " d" : "") : "—")),
        h("div", {}, h("small", {}, "Puntos"), h("b", { class: "dl-mono " + ((r || 0) > 0 ? "dl-ok" : (r || 0) < 0 ? "dl-bad" : "dl-muted") }, pts(r)))));
    }
    return body;
  }

  // ---------- load ----------
  async function load(data) {
    const [liveR, listR, decR, couR, outR, feedR, statR] = await Promise.all([
      safe(() => A().duelsLive(), { duels: [] }),
      safe(() => A().recDuels(), []),
      safe(() => A().decisions(), { items: [] }),
      safe(() => A().council(), { items: [] }),
      safe(() => A().outcomes(), { items: [] }),
      safe(() => A().recStream("feed", { tail: 1500 }), { rows: [] }),
      safe(() => A().status(), {}),
    ]);
    const live = val(liveR) || {};
    const st = val(statR) || {};
    const tick = num(live.tick) ?? num(data && (data.tick ?? (data.clock && data.clock.tick))) ?? num(st.tick);
    const heads = items(val(listR), "duels");
    const decs = items(val(decR)).filter((r) => ((r.action || {}).domain === "duels" || String((r.action || {}).kind || "").startsWith("duel")));
    const decsByDuel = {};
    for (const r of decs) { const id = num(((r.action || {}).params || {}).duel); if (id !== null) (decsByDuel[id] = decsByDuel[id] || []).push(r); }
    const councilByAction = {}; for (const c of items(val(couR))) if (c.action_id) councilByAction[c.action_id] = c;
    const outByAction = {}; for (const o of items(val(outR))) if (o.action_id) outByAction[o.action_id] = o;
    const tape = items(val(feedR), "rows").filter((e) => e.type === "duel.closed").sort((a, b) => (b.tick - a.tick) || (b.id - a.id));
    const byId = {}; for (const hd of heads) byId[+(hd.duel ?? hd.id)] = hd;
    const ourIds = new Set(Object.keys(byId).map(Number));
    // live duels: server dicts merged with the recorder transcript
    const liveDuels = items(live, "duels").filter((d) => !d.status || d.status === "live");
    const shown = [];
    if (S.view === "vivo") {
      for (const d of liveDuels) {
        const id = d.duel ?? d.id;
        const rec = byId[+id] ? await getTranscript(byId[+id]) : null;
        shown.push(merge(d, rec));
      }
      // recorder may know live duels the bot snapshot lacks (bot stopped)
      if (!liveDuels.length) for (const hd of heads.filter((x) => x.status === "live")) shown.push(await getTranscript(hd));
    } else {
      const closed = heads.filter((x) => x.status && x.status !== "live")
        .sort((a, b) => (b.last_change_tick ?? 0) - (a.last_change_tick ?? 0) || (b.duel ?? b.id) - (a.duel ?? a.id));
      for (const hd of closed.slice(0, 12)) shown.push(await getTranscript(hd));
    }
    const closedOurs = heads.filter((x) => x.status && x.status !== "live");
    return {
      tick, shown, heads, byId, ourIds, decsByDuel, councilByAction, outByAction, tape, closedOurs,
      liveErr: isErr(liveR) ? liveR.__error : null, listErr: isErr(listR) ? listR.__error : null, tapeErr: isErr(feedR) ? feedR.__error : null,
      liveCount: liveDuels.length || heads.filter((x) => x.status === "live").length,
    };
  }

  function matches(d) {
    const f = S.filter;
    if (!f) return true;
    if (f.types && f.types.size && !f.types.has(roleType(d))) return false;
    const q = String(f.q || "").trim().toLowerCase();
    if (q && !`${d.rival} ${d.item} ${d.duel ?? d.id}`.toLowerCase().includes(q)) return false;
    return true;
  }

  function render(root, ctx, params) {
    const grid = root.querySelector(".dl-grid");
    // keep per-pane scroll (stick to bottom when already there)
    grid.querySelectorAll(".dl-chat").forEach((c) => { S.scrolls[c.dataset.duel] = c.scrollHeight - c.scrollTop - c.clientHeight < 8 ? "end" : c.scrollTop; });
    grid.replaceChildren();
    if (S.fb && S.fb.setCounts) { const c = { compra: 0, venta: 0 }; for (const d of ctx.shown) c[roleType(d)]++; S.fb.setCounts(c); }
    const list = ctx.shown.filter(matches);
    root.querySelector(".dl-sub").textContent = `${ctx.liveCount} en vivo · ${ctx.closedOurs.length} cerrados${ctx.tick !== null ? " · tick " + ctx.tick : ""}`;
    if (!list.length) {
      const msg = S.view === "vivo" ? (ctx.liveErr ? null : "No hay duelos en vivo ahora. El juego está cerrado o no hay sesión de duelos.") : "No hay duelos cerrados que mostrar.";
      grid.append(msg ? comp("empty", msg) || h("div", { class: "dl-muted" }, msg) : comp("error", ctx.liveErr) || h("div", {}, "Error"));
      if (S.view === "vivo" && ctx.closedOurs.length) grid.append(h("button", { class: "dl-btn", type: "button", onclick: () => { S.view = "historial"; refreshNow(); } }, "Ver historial →"));
    }
    for (const d of list) grid.append(paneFor(d, ctx));
    grid.querySelectorAll(".dl-chat").forEach((c) => { const s = S.scrolls[c.dataset.duel]; c.scrollTop = s === undefined || s === "end" ? c.scrollHeight : s; });
    const sc = root.querySelector(".dl-scorehost");
    if (sc) sc.replaceChildren(scoreboard(ctx));
    const side = root.querySelector(".dl-side-body");
    side.replaceChildren(resultsPanel(ctx), tapePanel(ctx));
    // drawer
    const p = params ? String(params).split("/")[0] : "";
    if (p && p !== S.drawerFor) openDrawer(p, ctx).catch((e) => console.error("duelos drawer", e));
    if (!p) S.drawerFor = null;
  }

  async function openDrawer(id, ctx) {
    S.drawerFor = id;
    let d = ctx.shown.find((x) => String(x.duel ?? x.id) === id);
    if (!d || !(d.messages || []).length) {
      const r = await safe(() => A().recDuel(id), null);
      const live = items({ duels: ctx.shown }).find((x) => String(x.duel ?? x.id) === id);
      d = merge(live, val(r)) || d;
    }
    if (!d) { comp("drawer", { onClose: closeHash, title: "Duelo #" + id, body: comp("empty", "No encuentro ese duelo en la grabadora.") || h("div", {}, "No encontrado") }); return; }
    comp("drawer", { title: `Duelo #${id} · ${roleType(d)}`, body: drawerBody(d, ctx), wide: true, onClose: closeHash });
  }

  let refreshNow = () => {};
  const closeHash = () => { S.drawerFor = null; if (/^#duelos\//.test(location.hash)) location.hash = "#duelos"; };

  window.Screens["duelos"] = {
    title: "Duelos",
    mount(root, params) {
      S.root = root; S.drawerFor = null;
      root.classList.add("scr-duelos");
      root.replaceChildren();
      const titleBar = h("div", { class: "dl-title" }, h("h1", {}, "Duelos"), h("span", { class: "dl-sub dl-mono dl-muted" }, ""));
      const grid = h("div", { class: "dl-grid" }, window.ui.loading());
      const segs = h("div", { class: "dl-segs" });
      const drawSegs = () => segs.replaceChildren(
        segmented([["vivo", "En vivo"], ["historial", "Historial"]], S.view, (v) => { S.view = v; drawSegs(); refreshNow(); }),
        segmented([["todos", "Todos"], ["nosotros", "Nosotros"]], S.team, (v) => { S.team = v; drawSegs(); refreshNow(); }));
      drawSegs();
      const fb = S.fb = comp("filterBar", { types: ["compra", "venta"], team: false, search: true, onChange: (st) => { S.filter = st; refreshNow(); } });
      const side = h("aside", { class: "dl-side" }, segs, fb ? h("div", { class: "dl-fb" }, fb) : null, h("div", { class: "dl-side-body" }, window.ui.loading()));
      root.append(h("div", { class: "dl-layout" }, h("section", { class: "dl-main" }, titleBar, h("div", { class: "dl-scorehost" }), grid), side));
      let lastData = null;
      refreshNow = () => this.refresh(root, lastData, S.params);
      const orig = this.refresh;
      S.params = params;
      this._remember = (d) => { lastData = d; };
      void orig;
    },
    async refresh(root, data, params) {
      if (this._remember) this._remember(data);
      S.params = params;
      try {
        const ctx = await load(data);
        if (S.root !== root || !root.isConnected) return;
        render(root, ctx, params);
      } catch (e) {
        console.error("duelos", e);
        const grid = root.querySelector(".dl-grid");
        if (grid) grid.replaceChildren(comp("error", e) || h("div", {}, "Error: " + e.message));
      }
    },
    onParams(root, params) { S.params = params; if (!params) { S.drawerFor = null; comp("closeDrawer", true); } },
    unmount(root) { S.root = null; S.drawerFor = null; root.classList.remove("scr-duelos"); },
  };
})();
