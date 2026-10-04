/* DUELOS · duelos vivos como conversaciones, resultados de la sesión y cinta de cierres del juego.
   Detalle: #duelos/<id> abre la conversación completa en el cajón lateral. */
(function () {
  "use strict";
  window.Screens = window.Screens || {};

  // ---------- helpers ----------
  const U = () => window.ui || {};
  const A = () => window.api || {};
  const tr = (k, v) => window.I18N.t(k, v);
  const roleLabel = (d) => tr("duelos.role." + roleType(d));
  const duelChip = () => comp("typeChip", "duelo", tr("duelos.chip.duel"));
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
      return tr("duelos.move.accept", { price: fmtP(e.price) }) + (e.days != null ? " · " + e.days + " d" : "");
    }
    if (a.kind === "duel_message") return tr("duelos.move.offer", { price: fmtP(p.price) }) + (p.days != null ? " · " + p.days + " d" : "");
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
    return cfg ? comp("priceBar", cfg) || h("div", { class: "dl-muted" }, tr("duelos.bar.fallback", { limit: fmtP(cfg.limit), ours: fmtP(cfg.ours), theirs: fmtP(cfg.theirs) })) : h("div", { class: "dl-muted" }, tr("duelos.noPricesYet"));
  };

  // rounds strip + decay lost
  function roundsStrip(d) {
    const r = num(d.rounds) || 0;
    const decay = num(d.decay_per_round) ?? 0.06;
    const mult = Math.pow(1 - decay, r);
    const boxes = h("span", { class: "dl-rounds" });
    const n = Math.max(5, r + 1);
    for (let i = 0; i < Math.min(n, 10); i++) boxes.append(h("i", { class: i < r ? "on" : i === r ? "cur" : "" }));
    return h("span", { class: "dl-roundwrap", title: tr("duelos.round.title", { r, pct: Math.round(decay * 100) }) },
      boxes, h("span", { class: "dl-mono dl-muted" }, `r${r} · ×${fmtNum(mult, 2)}`),
      r > 0 ? h("span", { class: "dl-mono dl-bad" }, ` −${fmtNum((1 - mult) * 100, 0)} %`) : null);
  }

  // transcript: rounds numbered from priced messages
  function transcript(d, decsForDuel, councilByAction, withReason) {
    const box = h("div", { class: "dl-chat" });
    const msgs = d.messages || [];
    if (!msgs.length) { box.append(h("div", { class: "dl-muted dl-pad" }, tr("duelos.noMessagesYet"))); return box; }
    let nOurs = 0, nTheirs = 0;
    for (const m of msgs) {
      const ours = isOurs(m);
      const priced = num(m.price) !== null;
      if (priced) ours ? nOurs++ : nTheirs++;
      const round = priced ? (ours ? nOurs : nTheirs) : null;
      const who = ours ? tr("duelos.usFull") : (d.rival || tr("duelos.rival"));
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
    hist: { sub: "conv", role: "", status: "", q: "", limit: 24 },
    ev: { kind: "", who: "", duel: "", from: "", to: "", us: false, q: "", page: 0, csv: "" },
  };

  async function getTranscript(head) {
    const id = head.duel ?? head.id;
    const count = head.message_count ?? (head.messages || []).length;
    const c = S.transcripts[id];
    if (c && c.count === count && (c.data.status !== "live" || count === c.count) && c.fresh > Date.now() - 2500 && c.fresh > (window.__dashForceAt || 0)) return c.data;
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
        duelChip() || h("b", {}, tr("duelos.chip.duel")),
        comp("typeChip", roleType(d), roleLabel(d)) || h("span", {}, roleLabel(d)),
        h("b", { class: "dl-rival" }, d.rival || tr("duelos.rival")),
        h("span", { class: "dl-sp" }),
        live ? h("span", { class: "dl-mono dl-muted" }, ticksLeft !== null ? `${Math.max(0, ticksLeft)} ticks` : "")
          : comp("resultChip", d.status === "deal" ? "cerrado" : "sin_acuerdo") || h("span", {}, d.status)),
      h("div", { class: "dl-row" }, h("span", { class: "dl-mono dl-item" }, d.item || ""), h("span", { class: "dl-sp" }), roundsStrip(d)));
    const chat = transcript(d, decs, ctx.councilByAction, false);
    chat.dataset.duel = id;
    let foot;
    if (live) {
      foot = h("div", { class: "dl-pane-f" }, h("span", { class: "dl-muted" }, tr("duelos.next")),
        h("span", { class: "dl-next" }, last ? moveText(last) + (last.action && last.action.reason ? " — " + last.action.reason : "") : tr("duelos.waitingBot")),
        h("span", { class: "dl-sp" }), last ? srcTag(sourceOf(last, ctx.councilByAction)) : null);
    } else {
      foot = h("div", { class: "dl-pane-f" },
        h("span", {}, d.status === "deal" ? tr("duelos.closedAt", { price: fmtP(d.price) }) + (num(d.days) ? " · " + d.days + " d" : "") : tr("duelos.noDeal")),
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
    return h("div", { class: "dl-results" }, h("div", { class: "dl-sec" }, tr("duelos.res.title")),
      done.length ? h("div", { class: "dl-row dl-top" }, d, h("div", { class: "dl-grow" },
        line(tr("duelos.res.points"), fmtNum(points, 1)),
        line(tr("duelos.res.closedDeals"), `${done.length} · ${deals.length}`),
        line(tr("duelos.res.avg"), pts(done.length ? points / done.length : null), "dl-ok"),
        line(tr("duelos.res.share"), share === null ? "—" : Math.round(share * 100) + " %"),
        line(tr("duelos.noDeal"), String(done.length - deals.length), "dl-bad"),
        neg ? line(tr("duelos.res.outside"), String(neg), "dl-bad") : null))
        : comp("empty", tr("duelos.res.none")) || h("div", { class: "dl-muted" }, tr("duelos.res.none")));
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
      cell(tr("duelos.sc.played"), String(all.length), "", tr("duelos.sc.finished", { n: done.length })),
      cell(tr("duelos.sc.won"), String(won.length), "ok", pct(won.length)),
      cell(tr("duelos.sc.lost"), String(lost.length), "bad", lost.length ? pct(lost.length) : tr("duelos.sc.outside")),
      cell(tr("duelos.noDeal"), String(noDeal.length), "warn", pct(noDeal.length)),
      even.length ? cell(tr("duelos.sc.even"), String(even.length), "", pct(even.length)) : null,
      cell(tr("duelos.sc.live"), String(live.length), "live", live.length ? tr("duelos.sc.now") : tr("duelos.sc.none")),
      cell(tr("duelos.points"), pts(points), points > 0 ? "ok" : points < 0 ? "bad" : "", tr("duelos.sc.fromDuels")),
      cell(tr("duelos.sc.avg"), pts(done.length ? points / done.length : null), "", tr("duelos.sc.perDuel")));
  }

  function tapePanel(ctx) {
    const rows = ctx.tape.filter((e) => S.team !== "nosotros" || ctx.ourIds.has(+e.payload.duel));
    const box = h("div", { class: "dl-tape" }, h("div", { class: "dl-sec" }, tr("duelos.tape.title")));
    if (ctx.tapeErr) { box.append(comp("error", ctx.tapeErr) || h("div", {}, tr("duelos.tape.error"))); return box; }
    if (!rows.length) { box.append(comp("empty", tr("duelos.tape.none")) || h("div", { class: "dl-muted" }, tr("duelos.tape.noneShort"))); return box; }
    for (const e of rows.slice(0, 80)) {
      const p = e.payload || {};
      const ours = ctx.ourIds.has(+p.duel);
      const rec = ours ? ctx.byId[+p.duel] : null;
      const cells = [
        h("div", { class: "dl-row" }, duelChip() || tr("duelos.chip.duel"), ours ? comp("teamTag", "t10", { us: true }) || h("b", {}, tr("duelos.usFull")) : h("span", { class: "dl-muted" }, "#" + p.duel),
          h("span", { class: "dl-sp" }), rec ? h("b", { class: "dl-mono " + ((num(rec.result) || 0) > 0 ? "dl-ok" : "dl-muted") }, pts(num(rec.result))) : null),
        h("div", { class: "dl-row" }, h("span", {}, (p.item || "") + (rec ? " · vs " + (rec.rival || "") : "")), h("span", { class: "dl-sp" }),
          h("span", { class: "dl-mono dl-muted" }, (p.status === "deal" ? (rec && rec.price != null ? fmtP(rec.price) : tr("duelos.st.deal")) : tr("duelos.st.no_deal")) + " · " + tclock(e.tick))),
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
    if (!msgs.length) return h("div", { class: "dl-muted" }, tr("duelos.noPrices"));
    const ticks = msgs.map((m) => +m.tick || 0), prices = msgs.map((m) => +m.price).concat(lim !== null ? [lim] : []);
    const t0 = Math.min(...ticks), t1 = Math.max(...ticks, t0 + 1);
    const p0 = Math.min(...prices), p1 = Math.max(...prices, p0 + 1);
    const W = 480, H = 140, P = 24;
    const x = (t) => P + ((t - t0) / (t1 - t0)) * (W - 2 * P), y = (p) => H - P - ((p - p0) / (p1 - p0)) * (H - 2 * P);
    const path = (arr) => arr.map((m, i) => (i ? "L" : "M") + x(+m.tick).toFixed(1) + " " + y(+m.price).toFixed(1)).join(" ");
    const ours = msgs.filter(isOurs), theirs = msgs.filter((m) => !isOurs(m));
    const dots = (arr, cls) => arr.map((m) => `<circle class="${cls}" cx="${x(+m.tick).toFixed(1)}" cy="${y(+m.price).toFixed(1)}" r="3.5"/>`).join("");
    const svg = `<svg viewBox="0 0 ${W} ${H}" class="dl-track">
      ${lim !== null ? `<line class="lim" x1="${P}" x2="${W - P}" y1="${y(lim)}" y2="${y(lim)}"/><text class="lbl" x="${W - P}" y="${y(lim) - 4}" text-anchor="end">${tr("duelos.limitN", { n: lim })}</text>` : ""}
      ${d.status === "deal" && num(d.price) !== null ? `<line class="deal" x1="${P}" x2="${W - P}" y1="${y(+d.price)}" y2="${y(+d.price)}"/>` : ""}
      <path class="us" d="${path(ours)}"/><path class="them" d="${path(theirs)}"/>${dots(ours, "us")}${dots(theirs, "them")}
      <text class="lbl" x="${P}" y="${H - 6}">t${t0}</text><text class="lbl" x="${W - P}" y="${H - 6}" text-anchor="end">t${t1}</text>
      <text class="lbl" x="2" y="${y(p1) + 4}">${p1}</text><text class="lbl" x="2" y="${y(p0)}">${p0}</text></svg>`;
    const wrap = h("div", {}); wrap.innerHTML = svg;
    wrap.append(h("div", { class: "dl-legend" }, h("span", { class: "us" }, "● " + tr("duelos.us")), h("span", { class: "them" }, "○ " + tr("duelos.them")), h("span", {}, "— " + tr("duelos.limit"))));
    return wrap;
  }

  function drawerBody(d, ctx) {
    const id = d.duel ?? d.id;
    const decs = ctx.decsByDuel[id] || [];
    const body = h("div", { class: "scr-duelos dl-drawer" });
    body.append(h("div", { class: "dl-row" }, duelChip() || tr("duelos.chip.duel"), comp("typeChip", roleType(d), roleLabel(d)) || "",
      h("span", { class: "dl-muted dl-mono" }, `${tr("duelos.sessionN", { s: d.session ?? "?" })} · #${id}`), h("span", { class: "dl-sp" }),
      comp("resultChip", d.status === "deal" ? "cerrado" : d.status === "no_deal" ? "sin_acuerdo" : "pendiente") || d.status));
    body.append(h("h3", { class: "dl-dtitle" }, `${d.rival || tr("duelos.rival")} · ${d.item || ""}`));
    body.append(h("div", { class: "dl-row" }, roundsStrip(d), h("span", { class: "dl-sp" }),
      h("span", { class: "dl-mono dl-muted" }, `${tr("duelos.limitLower", { n: fmtP(d.your_limit) })} · ${d.limit_meaning || ""}`)));
    if (d.your_days_weight != null) body.append(h("div", { class: "dl-muted" }, `${tr("duelos.daysWeight", { w: d.your_days_weight })} · ${d.days_meaning || ""}`));
    body.append(h("div", { class: "dl-bar" }, priceBar(d, false)));
    body.append(h("div", { class: "dl-sec" }, tr("duelos.dr.pricePerMsg")), priceTrack(d));
    body.append(h("div", { class: "dl-sec" }, tr("duelos.dr.conversation", { n: (d.messages || []).length })), transcript(d, decs, ctx.councilByAction, true));
    // reasoning per move
    body.append(h("div", { class: "dl-sec" }, tr("duelos.dr.decisions", { n: decs.length })));
    if (!decs.length) body.append(h("div", { class: "dl-muted" }, tr("duelos.dr.noDecisions")));
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
        c ? h("div", { class: "dl-council" }, h("span", { class: "dl-muted" }, `${tr("duelos.dr.council")}: ${c.result || ""} — ${c.why || ""}`),
          ...(c.votes || []).map((vt) => h("div", { class: "dl-vote" }, h("b", {}, vt.role || "?"), h("span", { class: "dl-vv " + vt.verdict }, vt.verdict || ""), h("span", { class: "dl-muted" }, vt.reason || (vt.params && Object.keys(vt.params).length ? JSON.stringify(vt.params) : ""))))) : null,
        dec.id != null ? h("a", { href: "#supervision/" + dec.id, class: "dl-link" }, tr("duelos.dr.seeSupervision")) : null);
      body.append(card);
    }
    // outcome
    const r = num(d.result);
    body.append(h("div", { class: "dl-sec" }, tr("duelos.result")));
    if (d.status === "live" || !d.status) {
      const lim = num(d.your_limit), th = num(d.rival_offer && d.rival_offer.price), dec = num(d.decay_per_round) ?? 0.06, rr = num(d.rounds) || 0;
      const marg = lim !== null && th !== null ? (d.role === "seller" ? th - lim : lim - th) : null;
      body.append(h("div", { class: "dl-out" },
        h("div", {}, h("small", {}, tr("duelos.dr.ifAccept", { price: fmtP(th) })), h("b", { class: "dl-mono " + ((marg || 0) > 0 ? "dl-ok" : "dl-bad") }, marg === null ? "—" : pts(marg * Math.pow(1 - dec, rr)) + " pts")),
        h("div", {}, h("small", {}, tr("duelos.dr.anotherRound")), h("b", { class: "dl-mono" }, `r${rr + 1} · ×${fmtNum(Math.pow(1 - dec, rr + 1), 2)}`)),
        h("div", {}, h("small", {}, `${tr("duelos.noDeal")} (${tclock(d.deadline_tick)})`), h("b", { class: "dl-mono dl-bad" }, "0 pts"))));
    } else {
      body.append(h("div", { class: "dl-out" },
        h("div", {}, h("small", {}, tr("duelos.dr.status")), h("b", {}, d.status === "deal" ? tr("duelos.deal") : tr("duelos.noDeal"))),
        h("div", {}, h("small", {}, tr("duelos.price")), h("b", { class: "dl-mono" }, d.price != null ? fmtP(d.price) + (num(d.days) ? " · " + d.days + " d" : "") : "—")),
        h("div", {}, h("small", {}, tr("duelos.points")), h("b", { class: "dl-mono " + ((r || 0) > 0 ? "dl-ok" : (r || 0) < 0 ? "dl-bad" : "dl-muted") }, pts(r)))));
    }
    return body;
  }

  // ---------- historial: same cards as Mercado · Historial (shared .scr-mercado mk- styles) ----------
  const stTxt = (k) => (window.I18N.has("duelos.st." + k, "es") ? tr("duelos.st." + k) : k);
  function histFiltered(heads) {
    const f = S.hist, q = f.q.trim().toLowerCase();
    return heads.filter((d) => {
      if (f.role && roleType(d) !== f.role) return false;
      const st = d.status || "live";
      if (f.status === "won" && !(st === "deal" && (num(d.result) || 0) > 0)) return false;
      if (f.status && f.status !== "won" && st !== f.status) return false;
      if (q && !`${d.rival} ${d.item} #${d.duel ?? d.id}`.toLowerCase().includes(q)) return false;
      return true;
    }).sort((a, b) => (b.session ?? 0) - (a.session ?? 0) || (b.duel ?? b.id) - (a.duel ?? a.id));
  }
  function duelCard(d) {
    const id = d.duel ?? d.id, st = d.status || "live";
    const msgs = (d.messages || []).slice().sort((a, b) => (a.tick || 0) - (b.tick || 0) || (a.id || 0) - (b.id || 0));
    const r = num(d.result);
    const lims = [num(d.your_limit) !== null ? tr("duelos.card.lim", { n: d.your_limit }) : null, st === "deal" && d.price != null ? tr("duelos.card.closed", { price: fmtP(d.price) }) : null].filter(Boolean).join(" · ");
    const card = h("article", { class: `mk-chat mk-chat-hist mk-duel mk-st-${st === "deal" ? "deal" : st === "no_deal" ? "closed" : "open"}`, onclick: (e) => { if (!e.target.closest("a,button,select,input")) location.hash = "#duelos/" + id; } },
      h("header", { class: "mk-chat-h" },
        duelChip() || h("span", {}, tr("duelos.chip.duel")),
        comp("typeChip", roleType(d), d.role === "buyer" ? tr("duelos.weBuy") : tr("duelos.weSell")) || h("span", {}, roleLabel(d)),
        h("b", { class: "mk-chat-who" }, d.rival || tr("duelos.rival")),
        h("span", { class: "mk-status" }, stTxt(st))),
      h("div", { class: "mk-chat-sub" },
        h("span", null, d.item || ""),
        h("span", { class: "mk-muted" }, `#${id} · ${tr("duelos.sessionN", { s: d.session ?? "?" })} · ${tr("duelos.nMessages", { n: msgs.length })}` + (msgs.length ? ` · ${tclock(msgs[0].tick)}–${tclock(msgs[msgs.length - 1].tick)}` : ""))),
      h("div", { class: "mk-chat-bar" }, priceBar(d, true), h("span", { class: "mk-lims" }, lims)),
      h("div", { class: "mk-msgs" }, msgs.length ? msgs.map((m) => {
        const us = isOurs(m);
        const fig = [num(m.price) !== null ? fmtP(m.price) : null, num(m.days) !== null ? m.days + " d" : null].filter(Boolean).join(" · ");
        return h("div", { class: "mk-msg" + (us ? " is-us" : "") },
          h("div", { class: "mk-msg-h" }, h("span", null, us ? tr("duelos.us") : d.rival || tr("duelos.rival")), h("b", null, fig),
            h("span", { class: "mk-muted", title: "tick " + (m.tick ?? "?") }, tclock(m.tick))),
          h("div", { class: "mk-msg-t" }, m.text || ""));
      }) : comp("empty", tr("duelos.noMessages")) || h("div", { class: "mk-muted" }, tr("duelos.noMessages"))),
      h("footer", { class: "mk-duel-f" }, roundsStrip(d), h("span", { class: "mk-grow" }),
        h("b", { class: "mk-mono " + ((r || 0) > 0 ? "dl-ok" : (r || 0) < 0 ? "dl-bad" : "dl-muted") }, st === "live" ? tr("duelos.st.live") : pts(r) + " pts")));
    return card;
  }
  // ---------- historial · eventos: every duel event (our transcripts + the whole feed) ----------
  const EV_KINDS = ["open", "msg", "deal", "no_deal", "session"];
  const evLabel = (k) => tr("duelos.ev.kind." + k);
  function duelEvents(ctx) {
    const out = [];
    for (const hd of ctx.heads) {
      const id = +(hd.duel ?? hd.id);
      const d = (S.transcripts[id] && S.transcripts[id].data) || hd;
      const msgs = d.messages || [];
      const first = msgs.length ? Math.min(...msgs.map((m) => +m.tick || 0)) : null;
      if (first !== null) out.push({ ts: U().tickWall ? U().tickWall(first) : null, tick: first, kind: "open", who: "t10", duel: id, rival: d.rival, us: true,
        text: tr(d.role === "buyer" ? "duelos.ev.openBuy" : "duelos.ev.openSell", { item: d.item || "", rival: d.rival || tr("duelos.rivalLower"), session: d.session ?? "?", limit: d.your_limit ?? "?" }), price: null });
      for (const m of msgs) {
        const ours = isOurs(m);
        out.push({ ts: U().tickWall ? U().tickWall(m.tick) : null, tick: m.tick, kind: "msg", who: ours ? "t10" : d.rival || tr("duelos.rival"), duel: id, rival: d.rival, us: true,
          text: (m.text || "") + (num(m.days) !== null ? ` · ${m.days} d` : ""), price: num(m.price) });
      }
    }
    for (const e of DF.rows) {
      const p = e.payload || {};
      if (e.type === "duel.closed") {
        const id = +p.duel, ours = ctx.ourIds.has(id), hd = ctx.byId[id];
        out.push({ ts: num(e.seen_at) || num(e.ts), tick: e.tick, kind: p.status === "deal" ? "deal" : "no_deal", who: ours ? "t10" : "", duel: id, rival: hd && hd.rival, us: ours,
          text: `${p.item || ""}${hd ? " · vs " + (hd.rival || "") : ""}${hd && num(hd.result) !== null ? " · " + pts(num(hd.result)) + " pts" : ""} · ${tr("duelos.sessionN", { s: p.session ?? "?" })}`, price: hd && p.status === "deal" ? num(hd.price) : null });
      } else out.push({ ts: num(e.seen_at) || num(e.ts), tick: e.tick, kind: "session", who: "", duel: null, us: false, text: `${p.name || e.type} · ${e.type === "duels.finished" ? tr("duelos.ev.ends") : tr("duelos.ev.starts")}`, price: null });
    }
    return out.sort((a, b) => (b.ts || 0) - (a.ts || 0) || (b.tick || 0) - (a.tick || 0));
  }
  function evFiltered(rows) {
    const f = S.ev, q = f.q.toLowerCase();
    const from = f.from ? new Date(f.from).getTime() / 1000 : null, to = f.to ? new Date(f.to).getTime() / 1000 : null;
    return rows.filter((r) => (!f.kind || r.kind === f.kind) && (!f.us || r.us) && (!f.who || r.who === f.who || r.rival === f.who) &&
      (!f.duel || String(r.duel) === f.duel.replace("#", "")) && (!from || (r.ts || 0) >= from) && (!to || (r.ts || 0) <= to) &&
      (!q || `${r.text} ${r.rival || ""} #${r.duel}`.toLowerCase().includes(q)));
  }
  const csvCell = (v) => { const x = v == null ? "" : String(v); return /[",\n;]/.test(x) ? '"' + x.replace(/"/g, '""') + '"' : x; };
  async function renderEvents(root, ctx) {
    const host = root.querySelector(".mk-hist"); if (!host) return;
    // transcripts of all our duels (closed ones stay cached)
    await Promise.all(ctx.heads.map((hd) => getTranscript(hd)));
    if (!root.isConnected) return;
    const all = duelEvents(ctx), rows = evFiltered(all), f = S.ev;
    const whoSel = host.querySelector("[data-f=who]");
    const whos = [...new Set(all.map((r) => r.rival).filter(Boolean))].sort();
    if (whoSel.options.length - 1 !== whos.length) { const cur = whoSel.value; whoSel.replaceChildren(h("option", { value: "" }, tr("duelos.f.rivalAll")), ...whos.map((w) => h("option", { value: w }, w))); whoSel.value = cur; }
    const per = 50, pages = Math.max(1, Math.ceil(rows.length / per)); f.page = Math.min(f.page, pages - 1);
    const slice = rows.slice(f.page * per, f.page * per + per);
    const nUs = rows.filter((r) => r.us).length;
    host.querySelector(".mk-hist-sum").textContent = tr("duelos.ev.summary", { n: rows.length, total: all.length, us: nUs }) + (DF.busy ? " · " + tr("duelos.loading") : "");
    const fmtTs = (ts) => (ts ? tr("duelos.day." + new Date(ts * 1000).getDay()) + " " + (U().fmtTime ? U().fmtTime(ts) : new Date(ts * 1000).toLocaleTimeString(window.I18N.locale)) : "—");
    const table = h("table", { class: "mk-table" },
      h("thead", null, h("tr", null, ["date", "tick", "type", "who", "detail", "duel", "price"].map((x) => h("th", null, tr("duelos.th." + x))))),
      h("tbody", null, slice.map((r) => h("tr", { class: "mk-t-duelo" + (r.us ? " is-us" : ""), onclick: r.duel != null && r.us ? () => { location.hash = "#duelos/" + r.duel; } : null },
        h("td", { class: "mk-mono" }, fmtTs(r.ts)), h("td", { class: "mk-mono" }, r.tick != null ? "t" + r.tick : ""),
        h("td", null, comp("typeChip", "duelo", evLabel(r.kind)) || evLabel(r.kind)),
        h("td", null, r.who === "t10" ? comp("teamTag", "t10", { us: true }) || tr("duelos.us") : h("span", { class: "mk-team" }, r.who || "—")),
        h("td", { class: "mk-det" }, r.text), h("td", { class: "mk-mono" }, r.duel != null ? "#" + r.duel : ""),
        h("td", { class: "mk-mono mk-r" }, r.price != null ? fmtP(r.price) : "")))));
    const tHost = host.querySelector(".mk-hist-table");
    U().keepScroll(tHost, () => tHost.replaceChildren(slice.length ? table : comp("empty", tr("duelos.ev.noMatch")) || h("div", {}, tr("duelos.nothing"))));
    const pg = host.querySelector(".mk-pager");
    const btn = (label, p, on) => h("button", { class: on ? "on" : "", disabled: p < 0 || p >= pages ? "disabled" : null, onclick: () => { f.page = p; renderEvents(root, ctx); } }, label);
    const list = [...new Set([0, pages - 1, f.page - 1, f.page, f.page + 1].filter((p) => p >= 0 && p < pages))].sort((a, b) => a - b);
    const parts = [btn("‹", f.page - 1)];
    list.forEach((p, i) => { if (i && p - list[i - 1] > 1) parts.push(h("span", null, "…")); parts.push(btn(String(p + 1), p, p === f.page)); });
    parts.push(btn("›", f.page + 1));
    pg.replaceChildren(h("span", { class: "mk-muted" }, tr("duelos.pager", { from: rows.length ? f.page * per + 1 : 0, to: Math.min(rows.length, (f.page + 1) * per), total: rows.length })), h("span", { class: "mk-grow" }), ...parts);
    const lines = [tr("duelos.csv.header")];
    for (const r of rows) lines.push([r.ts ? new Date(r.ts * 1000).toISOString() : "", r.tick, evLabel(r.kind), r.who, r.rival, r.duel, r.text, r.price, r.us ? tr("duelos.csv.yes") : ""].map(csvCell).join(","));
    f.csv = lines.join("\n");
    const a = host.querySelector(".mk-export");
    a.setAttribute("href", "data:text/csv;charset=utf-8," + encodeURIComponent("\ufeff" + f.csv));
  }
  function buildEvents() {
    const f = S.ev;
    const upd = (k) => (e) => { f[k] = e.target.type === "checkbox" ? e.target.checked : e.target.value; f.page = 0; refreshNow(); };
    const copyBtn = h("button", { class: "mk-btn", type: "button", onclick: async (ev) => {
      let ok = false; try { await navigator.clipboard.writeText(f.csv || ""); ok = true; } catch (e) { ok = false; }
      ev.target.textContent = ok ? tr("duelos.csv.copied") : tr("duelos.csv.copyFailed"); setTimeout(() => { ev.target.textContent = tr("duelos.csv.copy"); }, 1800);
    } }, tr("duelos.csv.copy"));
    return h("div", { class: "mk-hist" },
      h("div", { class: "mk-hfilters" },
        h("select", { class: "mk-input", onchange: upd("kind") }, h("option", { value: "" }, tr("duelos.f.typeAll")), EV_KINDS.map((k) => h("option", { value: k, selected: f.kind === k ? "selected" : null }, evLabel(k)))),
        h("select", { class: "mk-input", "data-f": "who", onchange: upd("who") }, h("option", { value: "" }, tr("duelos.f.rivalAll"))),
        h("input", { class: "mk-input", placeholder: tr("duelos.f.duelPh"), value: f.duel, onchange: upd("duel") }),
        h("label", { class: "mk-muted" }, tr("duelos.f.from") + " ", h("input", { class: "mk-input", type: "datetime-local", value: f.from, onchange: upd("from") })),
        h("label", { class: "mk-muted" }, tr("duelos.f.to") + " ", h("input", { class: "mk-input", type: "datetime-local", value: f.to, onchange: upd("to") })),
        h("label", { class: "mk-muted" }, h("input", { type: "checkbox", checked: f.us ? "checked" : null, onchange: upd("us") }), " " + tr("duelos.f.onlyUs")),
        h("input", { class: "mk-input mk-q", placeholder: tr("duelos.f.searchText"), value: f.q, onchange: upd("q") }),
        h("span", { class: "mk-grow" }),
        h("a", { class: "mk-btn mk-export", href: "#", download: "bazaar-duelos.csv" }, tr("duelos.csv.export")), copyBtn),
      h("div", { class: "mk-hist-sum mk-muted" }),
      h("div", { class: "mk-hist-table" }, window.ui.loading()),
      h("div", { class: "mk-pager" }));
  }

  function buildHist(root) {
    const f = S.hist;
    const rerender = () => refreshNow();
    const sel = (key, opts) => h("select", { class: "mk-input", onchange: (e) => { f[key] = e.target.value; f.limit = 24; rerender(); } },
      opts.map(([v, l]) => h("option", { value: v, selected: f[key] === v ? "selected" : null }, l)));
    root.replaceChildren(h("div", { class: "scr-mercado is-hist dl-hist" },
      h("div", { class: "mk-head" }, h("h1", null, tr("duelos.hist.title")),
        h("span", { class: "mk-muted" }, S.hist.sub === "conv" ? tr("duelos.hist.subConv") : tr("duelos.hist.subEvents")),
        h("span", { class: "mk-grow" }),
        h("div", { class: "mk-seg mk-histview" }, [["conv", tr("duelos.hist.conversations")], ["eventos", tr("duelos.hist.events")]].map(([v, l]) =>
          h("button", { type: "button", class: S.hist.sub === v ? "on" : "", onclick: () => { if (S.hist.sub === v) return; S.hist.sub = v; buildHist(root); refreshNow(); } }, l))),
        viewSeg()),
      h("div", { class: "dl-scorehost" }),
      S.hist.sub === "eventos" ? buildEvents() : h("div", { class: "mk-conv" },
      h("div", { class: "mk-hfilters" },
        sel("role", [["", tr("duelos.f.roleAll")], ["compra", tr("duelos.weBuy")], ["venta", tr("duelos.weSell")]]),
        sel("status", [["", tr("duelos.f.resultAll")], ["won", tr("duelos.sc.won")], ["deal", tr("duelos.f.withDeal")], ["no_deal", tr("duelos.noDeal")], ["live", tr("duelos.sc.live")]]),
        h("input", { class: "mk-input mk-q", placeholder: tr("duelos.f.searchDuel"), value: f.q, onchange: (e) => { f.q = e.target.value; f.limit = 24; rerender(); } })),
      h("div", { class: "mk-conv-sum mk-muted" }),
      h("div", { class: "mk-conv-list" }, window.ui.loading()))));
  }
  async function renderHist(root, ctx) {
    const sc = root.querySelector(".dl-scorehost"); if (sc) U().keepScroll(sc, () => sc.replaceChildren(scoreboard(ctx)));
    if (S.hist.sub === "eventos") return renderEvents(root, ctx);
    const host = root.querySelector(".mk-conv-list"); if (!host) return;
    if (ctx.listErr && !ctx.heads.length) { host.replaceChildren(comp("error", ctx.listErr) || h("div", {}, "Error")); return; }
    const rows = histFiltered(ctx.heads);
    const counts = {}; for (const d of ctx.heads) { const k = d.status || "live"; counts[k] = (counts[k] || 0) + 1; }
    root.querySelector(".mk-conv-sum").textContent = tr("duelos.hist.summary", { n: rows.length, total: ctx.heads.length }) + " · " + Object.entries(counts).map(([k, v]) => `${v} ${stTxt(k)}`).join(" · ");
    const shown = await Promise.all(rows.slice(0, S.hist.limit).map((hd) => getTranscript(hd)));
    if (!root.isConnected || S.view !== "historial") return;
    U().keyedList(host, shown, {
      key: (d) => d.duel ?? d.id,
      sig: (d) => [(d.messages || []).length, d.status, d.result, d.price].join("|"),
      render: duelCard, inner: ".mk-msgs",
      tail: [shown.length ? null : comp("empty", tr("duelos.hist.noMatch")) || h("div", {}, tr("duelos.nothing")),
        rows.length > S.hist.limit ? h("button", { class: "mk-btn mk-more", type: "button", onclick: () => { S.hist.limit += 24; refreshNow(); } }, tr("duelos.showMore", { n: rows.length - S.hist.limit })) : null] });
    const p = S.params ? String(S.params).split("/")[0] : "";
    if (p && p !== S.drawerFor) openDrawer(p, ctx).catch((e) => console.error("duelos drawer", e));
    if (!p) S.drawerFor = null;
  }
  function viewSeg() {
    return h("div", { class: "mk-seg" }, [["vivo", "● " + tr("duelos.view.live")], ["historial", tr("duelos.view.history")]].map(([id, label]) =>
      h("button", { type: "button", class: S.view === id ? "on" : "", onclick: () => setView(id) }, label)));
  }
  let setView = () => {};

  // every duel event of the whole feed (all days), paged by since_seq and kept incrementally
  const DF = { rows: [], last: 0, busy: null, err: null };
  function pullDuelFeed() {
    if (DF.busy) return DF.busy;
    DF.busy = (async () => {
      try {
        for (let guard = 0; guard < 100; guard++) {
          const r = await A().recStream("feed", { since_seq: DF.last, limit: 2000 });
          const rows = items(r, "rows");
          if (!rows.length) break;
          for (const e of rows) if (/^duels?\./.test(e.type || "")) DF.rows.push(e);
          DF.last = rows[rows.length - 1].seq;
          if (rows.length < 2000) break;
        }
        DF.err = null;
      } catch (e) { DF.err = e; } finally { DF.busy = null; }
    })();
    return DF.busy;
  }

  // ---------- load ----------
  async function load(data) {
    const [liveR, listR, decR, couR, outR, feedR, statR] = await Promise.all([
      safe(() => A().duelsLive(), { duels: [] }),
      safe(() => A().recDuels(), []),
      safe(() => A().decisions(), { items: [] }),
      safe(() => A().council(), { items: [] }),
      safe(() => A().outcomes(), { items: [] }),
      pullDuelFeed(),
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
    void feedR;
    const tape = DF.rows.filter((e) => e.type === "duel.closed").sort((a, b) => (b.seq || 0) - (a.seq || 0));
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
      // never an empty grid: fill up to 6 with our latest finished duels (each pane shows how it ended)
      const have = new Set(shown.map((d) => +(d.duel ?? d.id)));
      const recent = heads.filter((x) => x.status && x.status !== "live" && !have.has(+(x.duel ?? x.id)))
        .sort((a, b) => (b.last_change_tick ?? 0) - (a.last_change_tick ?? 0) || (b.duel ?? b.id) - (a.duel ?? a.id)).slice(0, Math.max(0, 6 - shown.length));
      for (const hd of recent) shown.push({ ...(await getTranscript(hd)), _recent: true });
    } else {
      const closed = heads.filter((x) => x.status && x.status !== "live")
        .sort((a, b) => (b.last_change_tick ?? 0) - (a.last_change_tick ?? 0) || (b.duel ?? b.id) - (a.duel ?? a.id));
      void closed;
    }
    const closedOurs = heads.filter((x) => x.status && x.status !== "live");
    return {
      tick, shown, heads, byId, ourIds, decsByDuel, councilByAction, outByAction, tape, closedOurs,
      liveErr: isErr(liveR) ? liveR.__error : null, listErr: isErr(listR) ? listR.__error : null, tapeErr: DF.rows.length ? null : DF.err,
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

  // live grid: "● en vivo" on live duels; finished ones show when they ended (their result chip is already there)
  function markPane(pane, d) {
    const row = pane.querySelector(".dl-pane-h .dl-row");
    if (!row) return pane;
    if (d._recent) {
      pane.classList.add("is-ended");
      const msgs = d.messages || []; const last = msgs[msgs.length - 1];
      const t = last && last.tick != null ? last.tick : d.last_change_tick;
      if (t != null && U().tickClock) row.append(h("span", { class: "dl-mono dl-muted dl-endwhen" }, U().tickClock(t)));
    } else row.insertBefore(h("span", { class: "dl-livemark" }, "● " + tr("duelos.liveMark")), row.querySelector(".dl-sp"));
    return pane;
  }
  function render(root, ctx, params) {
    const grid = root.querySelector(".dl-grid");
    if (S.fb && S.fb.setCounts) { const c = { compra: 0, venta: 0 }; for (const d of ctx.shown) c[roleType(d)]++; S.fb.setCounts(c); }
    const list = ctx.shown.filter(matches);
    const nRecent = S.view === "vivo" ? ctx.shown.filter((d) => d._recent).length : 0;
    root.querySelector(".dl-sub").textContent = tr("duelos.sub.live", { n: ctx.liveCount }) + (nRecent ? " · " + tr("duelos.sub.recent", { n: nRecent }) : "") + " · " + tr("duelos.sub.closed", { n: ctx.closedOurs.length }) + (ctx.tick !== null ? " · tick " + ctx.tick : "");
    const tail = [];
    if (!list.length) {
      const msg = S.view === "vivo" ? (ctx.liveErr ? null : tr("duelos.empty.live")) : tr("duelos.empty.closed");
      tail.push(msg ? comp("empty", msg) || h("div", { class: "dl-muted" }, msg) : comp("error", ctx.liveErr) || h("div", {}, "Error"));
      if (S.view === "vivo" && ctx.closedOurs.length) tail.push(h("button", { class: "dl-btn", type: "button", onclick: () => setView("historial") }, tr("duelos.seeHistory")));
    }
    // panes keyed by duel: unchanged ones stay, changed ones keep their chat scroll (stuck to the end when it was there)
    U().keyedList(grid, list, {
      key: (d) => d.duel ?? d.id,
      sig: (d) => { const id = d.duel ?? d.id, decs = ctx.decsByDuel[id] || [], last = decs[decs.length - 1];
        return JSON.stringify([(d.messages || []).length, d.status, d.rounds, d.your_offer, d.rival_offer, last && last.id, ctx.tick]); },
      render: (d) => markPane(paneFor(d, ctx), d), inner: ".dl-chat", stickEnd: true, tail });
    const sc = root.querySelector(".dl-scorehost");
    if (sc) U().keepScroll(sc, () => sc.replaceChildren(scoreboard(ctx)));
    const side = root.querySelector(".dl-side-body");
    U().keepScroll(side, () => side.replaceChildren(resultsPanel(ctx), tapePanel(ctx)));
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
    if (!d) { comp("drawer", { onClose: closeHash, title: tr("duelos.dr.title", { id }), body: comp("empty", tr("duelos.dr.notFound")) || h("div", {}, tr("duelos.dr.notFoundShort")) }); return; }
    comp("drawer", { title: `${tr("duelos.dr.title", { id })} · ${roleLabel(d)}`, body: drawerBody(d, ctx), wide: true, onClose: closeHash });
  }

  let refreshNow = () => {};
  const closeHash = () => { S.drawerFor = null; if (/^#duelos\//.test(location.hash)) location.hash = "#duelos"; };

  window.Screens["duelos"] = {
    get title() { return tr("duelos.title"); },
    mount(root, params) {
      if (params === "eventos" || params === "conversaciones") { S.hist.sub = params === "eventos" ? "eventos" : "conv"; params = "historial"; }
      if (params === "historial" || params === "vivo") { S.view = params; params = ""; }
      S.root = root; S.drawerFor = null; S.params = params;
      root.classList.add("scr-duelos");
      let lastData = null;
      refreshNow = () => this.refresh(root, lastData, S.params);
      this._remember = (d) => { lastData = d; };
      setView = (v) => { if (S.view === v) return; S.view = v; this._build(root); refreshNow(); };
      this._build(root);
    },
    _build(root) {
      if (S.view === "historial") { buildHist(root); return; }
      const titleBar = h("div", { class: "dl-title" }, h("h1", {}, tr("duelos.title")), h("span", { class: "dl-sub dl-mono dl-muted" }, ""));
      const grid = h("div", { class: "dl-grid" }, window.ui.loading());
      const segs = h("div", { class: "dl-segs" });
      const drawSegs = () => segs.replaceChildren(
        segmented([["todos", tr("duelos.all")], ["nosotros", tr("duelos.us")]], S.team, (v) => { S.team = v; drawSegs(); refreshNow(); }),
        segmented([["vivo", "● " + tr("duelos.view.live")], ["historial", tr("duelos.view.history")]], S.view, (v) => setView(v)));
      drawSegs();
      const fb = S.fb = comp("filterBar", { types: ["compra", "venta"], team: false, search: true, onChange: (st) => { S.filter = st; refreshNow(); } });
      const side = h("aside", { class: "dl-side" }, segs, fb ? h("div", { class: "dl-fb" }, fb) : null, h("div", { class: "dl-side-body" }, window.ui.loading()));
      root.replaceChildren(h("div", { class: "dl-layout" }, h("section", { class: "dl-main" }, titleBar, h("div", { class: "dl-scorehost" }), grid), side));
    },
    async refresh(root, data, params) {
      if (["historial", "vivo", "eventos", "conversaciones"].includes(params)) params = "";
      if (this._remember) this._remember(data);
      S.params = params;
      try {
        const view = S.view;
        const ctx = await load(data);
        if (S.root !== root || !root.isConnected || view !== S.view) return;
        if (view === "historial") await renderHist(root, ctx); else render(root, ctx, params);
      } catch (e) {
        console.error("duelos", e);
        const grid = root.querySelector(".dl-grid, .mk-conv-list");
        if (grid) grid.replaceChildren(comp("error", e) || h("div", {}, "Error: " + e.message));
      }
    },
    onParams(root, params) {
      if (params === "eventos" || params === "conversaciones") { S.hist.sub = params === "eventos" ? "eventos" : "conv"; S.params = ""; if (S.view === "historial") { this._build(root); refreshNow(); } else setView("historial"); return; }
      if (params === "historial" || params === "vivo") { const v = params; S.params = ""; setView(v); return; }
      S.params = params; if (!params) { S.drawerFor = null; comp("closeDrawer", true); } },
    unmount(root) { S.root = null; S.drawerFor = null; root.classList.remove("scr-duelos"); },
  };
})();
