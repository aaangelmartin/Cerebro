/* SUPERVISIÓN · ver y aprobar (sin controles de encendido ni de modo: eso vive en Bot).
   Detalle: #supervision/<id de decisión> (id del ledger o id de la acción). */
(function () {
  "use strict";
  window.Screens = window.Screens || {};

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
  const fmtTime = (ts) => (U().fmtTime ? U().fmtTime(ts) : ts ? new Date(ts * 1000).toLocaleTimeString("es-ES") : "");
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
  const SRC_LABEL = { opus: "Opus", consejo: "Consejo", reserva: "Reserva", codigo: "Código" };
  const RES_LABEL = { enviado: "Enviado", vetado: "Vetado", rechazado: "Rechazado", pendiente: "Pendiente", sin_enviar: "Sin enviar", cerrado: "Cerrado", sin_acuerdo: "Sin acuerdo" };
  const OUT = { sent: "enviado", deal: "cerrado", no_deal: "sin_acuerdo", expired: "sin_acuerdo", refused: "rechazado", error: "rechazado", vetoed: "vetado" };
  const RAIL_LABEL = { council: "Consejo", value: "Rail de valor", cash_floor: "Suelo de caja", per_tick: "Límite por tick", protected: "Carta protegida", bond: "Fianza mínima" };

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
      case "duel_message": return `Ofrece ${fmtP(p.price)}${p.days != null ? " · " + p.days + " d" : ""} · duelo #${p.duel}`;
      case "duel_accept": return `Acepta ${fmtP(e.price)} · duelo #${p.duel}`;
      case "thread_message": return `Ofrece ${fmtP(p.price)} · conversación #${p.thread}`;
      case "open_thread": return `Abre conversación con ${p.with || "dealer"}${p.topic ? " · " + p.topic : ""}`;
      case "close_thread": return `Cierra conversación #${p.thread}`;
      case "post_offer": return `Publica oferta en ${p.venue || "?"}: da ${side(p.give)} · pide ${side(p.want)}`;
      case "accept_offer": return `Acepta oferta #${p.offer}`;
      case "cancel_offer": return `Retira oferta #${p.offer}`;
      case "venue_open": return `Abre tienda ${p.name || ""}`;
      case "venue_patch": return `Cambia tienda ${p.venue || ""}`;
      case "broker_match": return `Empareja ${p.sell} con ${p.buy} a ${fmtP(p.price)}`;
      case "broker_announce": return "Anuncio del broker";
      case "open_pack": return `Abre sobre #${p.asset}`;
      default: return a.kind || "acción";
    }
  }
  function side(s) {
    if (!s) return "—";
    const parts = [];
    if (cashOf(s)) parts.push(fmtP(s.cash));
    for (const x of s.assets || []) parts.push(typeof x === "object" ? x.ref || x.kind || "#" + x.id : "#" + x);
    for (const t of s.types || []) parts.push(typeof t === "string" ? t : t.ref || JSON.stringify(t));
    return parts.join(" + ") || "nada";
  }

  // ---------- state ----------
  const S = { root: null, filter: null, extra: {}, drawerFor: null, selected: null, params: "", lastData: null };

  async function load() {
    const [stR, decR, couR, outR, logR] = await Promise.all([
      safe(() => A().status(), {}),
      safe(() => A().decisions(undefined), { items: [] }),
      safe(() => A().council(undefined), { items: [] }),
      safe(() => A().outcomes(undefined), { items: [] }),
      safe(() => (A().controlLog ? A().controlLog() : A().journal ? A().journal("control") : null), null),
    ]);
    const councilByAction = {}; for (const c of items(val(couR))) if (c.action_id) councilByAction[c.action_id] = c;
    const outsByAction = {}; for (const o of items(val(outR))) if (o.action_id) (outsByAction[o.action_id] = outsByAction[o.action_id] || []).push(o);
    const ctx = { councilByAction, outsByAction };
    const rows = items(val(decR)).map((d) => enrich(d, ctx)).sort((a, b) => (b.dec.id ?? 0) - (a.dec.id ?? 0));
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
    const mode = { auto: "Auto", observe: "Observar", manual: "Manual", review: "Revisión" }[ctl.mode] || ctl.mode || "—";
    return h("div", { class: "sv-strip" },
      h("span", { class: "sv-dot " + (live ? "on" : "off") }), h("b", { class: "sv-state " + (live ? "on" : "off") }, live ? "ENCENDIDO" : "APAGADO"),
      h("span", { class: "sv-mono" }, `Modo ${mode} · ${active}/${doms.length || 0} dominios activos · gestionado por el bot`),
      st.stop_file ? h("span", { class: "sv-bad" }, "· STOP activo") : null,
      st.doors ? h("span", { class: "sv-muted sv-mono" }, `· mercado ${st.doors === "open" ? "abierto" : "cerrado"}`) : null,
      h("span", { class: "sv-sp" }),
      h("a", { href: "#bot", class: "sv-btn" }, "Cambiar modo y controles en Bot"));
  }

  function queuePanel(data) {
    const mode = ((data.status || {}).control || {}).mode || "auto";
    const auto = mode === "auto";
    const pending = data.rows.filter((r) => r.res === "pendiente").slice(0, 6);
    const hasApproval = typeof A().approve === "function";
    const panel = h("section", { class: "sv-panel sv-queue" + (auto ? " sv-grey" : "") },
      h("div", { class: "sv-ph" }, h("b", {}, "Próximas acciones"),
        h("span", { class: "sv-muted" }, auto ? "Modo auto: el bot envía solo · cambia el modo en Bot" : hasApproval ? "Esperan tu aprobación" : "Aprobación aún no disponible en la API"),
        h("span", { class: "sv-sp" }), h("button", { class: "sv-btn", disabled: "" }, "Aprobar todo")));
    if (!pending.length) {
      panel.append(h("div", { class: "sv-empty" }, auto ? "Nada en cola: en modo auto cada acción sale en su tick." : "Nada esperando aprobación."));
      return panel;
    }
    for (const r of pending) {
      const btn = (label) => h("button", { class: "sv-btn", disabled: "", title: auto ? "Modo auto" : "Sin endpoint de aprobación" }, label);
      panel.append(h("div", { class: "sv-qrow t-" + r.type },
        comp("typeChip", r.type) || h("span", {}, r.type),
        h("div", { class: "sv-grow" }, h("div", {}, title(r.a)), h("div", { class: "sv-muted sv-small" }, r.a.reason || "")),
        btn("Aprobar"), btn("Editar"), btn("Rechazar")));
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
    if (data.decErr) { box.append(comp("error", data.decErr) || h("div", {}, "Error al leer decisiones")); return box; }
    if (!data.rows.length) { box.append(comp("empty", "El bot no ha registrado decisiones todavía (el juego está cerrado o el bot no ha corrido hoy).") || h("div", {}, "Sin decisiones")); return box; }
    if (!list.length) { box.append(comp("empty", "Ninguna decisión con estos filtros.") || h("div", {}, "Sin resultados")); return box; }
    for (const r of list.slice(0, 300)) {
      const id = r.dec.id ?? r.a.id;
      const cells = [
        h("span", { class: "sv-mono sv-muted sv-time" }, fmtTime(r.dec.ts), h("br", {}), h("small", {}, "t" + (r.dec.tick ?? "?"))),
        comp("typeChip", r.type) || h("span", {}, r.type),
        h("div", { class: "sv-grow" }, h("div", { class: "sv-title" }, title(r.a)), h("div", { class: "sv-muted sv-small" }, r.a.reason || ""),
          r.v.ok === false && (r.v.rail || r.v.detail) ? h("div", { class: "sv-bad sv-small" }, `${r.v.rail}: ${r.v.detail}`) : null),
        comp("sourceTag", r.src, r.extra) || h("span", {}, SRC_LABEL[r.src] + (r.extra ? " " + r.extra : "")),
        comp("resultChip", r.res) || h("span", {}, RES_LABEL[r.res]),
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
    const panel = h("section", { class: "sv-panel" }, h("div", { class: "sv-ph" }, h("b", {}, "Votos del Consejo"), h("span", { class: "sv-muted" }, "decisión seleccionada")));
    if (!sel) { panel.append(h("div", { class: "sv-empty" }, "Elige una decisión de la lista.")); return panel; }
    panel.append(h("div", { class: "sv-pad" }, h("div", { class: "sv-mono sv-muted sv-small" }, `${fmtTime(sel.dec.ts)} · ${(sel.a.domain || "").toUpperCase()}`), h("b", {}, title(sel.a))));
    if (!sel.c) { panel.append(h("div", { class: "sv-empty" }, "Esta decisión no pasó por el Consejo.")); return panel; }
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
      const verdict = v ? { approve: "A favor", modify: "Modificar", reject: "En contra" }[v.verdict] || v.verdict : "Se abstiene";
      const detail = v ? (v.reason || (v.params && Object.keys(v.params).length ? "propone " + JSON.stringify(v.params) : "")) : "sin respuesta a tiempo";
      box.append(h("div", { class: "sv-vote" },
        h("div", { class: "sv-row2" }, h("b", {}, role), v && v.model ? h("span", { class: "sv-muted sv-small" }, v.model) : null, h("span", { class: "sv-sp" }),
          h("span", { class: "sv-verdict " + (v ? v.verdict : "none") }, verdict)),
        detail ? h("div", { class: "sv-small" }, detail) : null,
        v && (v.injection || v.rail_risk) ? h("div", { class: "sv-bad sv-small" }, [v.injection ? "posible inyección" : null, v.rail_risk ? "riesgo de rail" : null].filter(Boolean).join(" · ")) : null));
    }
    box.append(h("div", { class: "sv-muted sv-small" }, `Resultado: ${c.result || "—"} · ${c.why || ""}${c.latency_s != null ? " · " + fmtNum(c.latency_s, 1) + " s" : ""}`));
    for (const e of c.errors || []) box.append(h("div", { class: "sv-bad sv-small" }, typeof e === "string" ? e : JSON.stringify(e)));
    return box;
  }

  function railsPanel(rows) {
    const vetoed = rows.filter((r) => r.res === "vetado");
    const by = countBy(vetoed, (r) => r.v.rail || "otro");
    const entries = Object.entries(by).sort((a, b) => b[1] - a[1]);
    const max = Math.max(1, ...entries.map((e) => e[1]));
    const panel = h("section", { class: "sv-panel" }, h("div", { class: "sv-ph" }, h("b", {}, "Vetos por rail"), h("span", { class: "sv-muted" }, String(vetoed.length))));
    if (!entries.length) { panel.append(h("div", { class: "sv-empty" }, "Ningún veto en las decisiones cargadas.")); return panel; }
    const box = h("div", { class: "sv-pad" });
    for (const [rail, n] of entries)
      box.append(h("div", { class: "sv-bar" }, h("span", {}, RAIL_LABEL[rail] || rail), h("span", { class: "sv-track" }, h("i", { style: `width:${(n / max) * 100}%` })), h("b", { class: "sv-mono" }, String(n))));
    const last = vetoed[0];
    if (last) box.append(h("div", { class: "sv-muted sv-small" }, `Último: «${title(last.a)}» — ${last.v.detail || last.v.rail}`));
    panel.append(box);
    return panel;
  }

  function logPanel(data) {
    const panel = h("section", { class: "sv-panel" }, h("div", { class: "sv-ph" }, h("b", {}, "Intervenciones manuales")));
    const box = h("div", { class: "sv-pad" });
    if (data.log === null) {
      const ctl = (data.status || {}).control || {};
      box.append(h("div", { class: "sv-muted sv-small" }, "El registro de cambios (ledger «control») aún no se sirve en la API. Estado actual:"));
      box.append(h("div", { class: "sv-logrow" }, h("span", {}, `Modo ${ctl.mode || "—"} · ${ctl.armed ? "encendido" : "apagado"}`), h("span", { class: "sv-sp" }),
        h("span", { class: "sv-mono sv-muted" }, ctl.updated ? fmtTime(ctl.updated) : "")));
      if ((ctl.paused_domains || []).length) box.append(h("div", { class: "sv-logrow" }, "Pausados: " + ctl.paused_domains.join(", ")));
      if ((ctl.protected || []).length) box.append(h("div", { class: "sv-logrow" }, "Protegidas: " + ctl.protected.join(", ")));
    } else if (!data.log.length) {
      box.append(h("div", { class: "sv-empty" }, "Sin intervenciones manuales."));
    } else {
      for (const r of data.log.slice().reverse().slice(0, 30)) {
        const ch = r.change || {};
        const txt = Object.entries(ch).map(([k, v]) => {
          if (k === "armed") return v ? "Bot encendido" : "Bot apagado";
          if (k === "stop_file") return v ? "STOP activado" : "STOP retirado";
          if (k === "mode") return "Modo cambiado a " + v;
          if (k === "paused_domains") return "Pausados: " + ((v || []).join(", ") || "ninguno");
          return `${k}: ${JSON.stringify(v)}`;
        }).join(" · ");
        box.append(h("div", { class: "sv-logrow" }, h("span", {}, txt || "cambio"), h("span", { class: "sv-sp" }), h("span", { class: "sv-mono sv-muted" }, fmtTime(r.ts))));
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
    b.append(h("div", { class: "sv-sec" }, "Razonamiento"), h("div", {}, r.a.reason || "—"));
    b.append(h("div", { class: "sv-sec" }, `Acción · ${r.a.kind} · ${r.a.domain || ""}`), kv(r.a.params));
    if (r.a.big || r.a.priority) b.append(h("div", { class: "sv-muted sv-small" }, `${r.a.big ? "Grande (revisión del Consejo) · " : ""}prioridad ${fmtNum(r.a.priority, 2)}${r.dec.latency_s != null ? " · latencia " + fmtNum(r.dec.latency_s, 2) + " s" : ""}`));
    // expected vs realised
    b.append(h("div", { class: "sv-sec" }, "Previsto vs. real"));
    const realised = {}; for (const o of r.outs) Object.assign(realised, o.realised || {});
    const grid = h("div", { class: "sv-evr" }, h("div", {}, h("small", {}, "Previsto"), kv(r.a.expected)), h("div", {}, h("small", {}, "Real"),
      r.outs.length ? kv({ estado: [...new Set(r.outs.map((o) => o.status))].join(" → "), ...realised }) : h("div", { class: "sv-muted" }, r.res === "sin_enviar" ? "No se envió (modo de prueba)." : "Sin resultado registrado.")));
    b.append(grid);
    if (r.o && r.o.response && Object.keys(r.o.response).length) b.append(h("details", {}, h("summary", { class: "sv-muted sv-small" }, "Respuesta del servidor"), kv(r.o.response)));
    // rails
    b.append(h("div", { class: "sv-sec" }, "Rails"), h("div", { class: r.v.ok === false ? "sv-bad" : "sv-ok" }, r.v.ok === false ? `Vetado por ${RAIL_LABEL[r.v.rail] || r.v.rail}: ${r.v.detail || ""}` : "Aprobado por todos los rails" + (r.dec.dry_run ? " (sin enviar: modo de prueba)" : "")));
    // council
    b.append(h("div", { class: "sv-sec" }, "Consejo"));
    if (r.c) {
      b.append(votesList(r.c));
      if (r.c.final_params) b.append(h("div", { class: "sv-muted sv-small" }, "Parámetros finales"), kv(r.c.final_params));
    } else b.append(h("div", { class: "sv-muted" }, "No pasó por el Consejo."));
    // lessons
    b.append(h("div", { class: "sv-sec" }, "Lecciones aplicadas"));
    const ls = r.a.lesson_ids || [];
    b.append(ls.length ? h("div", { class: "sv-row2" }, ...ls.map((id) => h("a", { href: "#laboratorio/" + id, class: "sv-link sv-mono" }, id))) : h("div", { class: "sv-muted" }, "Ninguna."));
    if (r.type === "duelo" && (r.a.params || {}).duel != null) b.append(h("a", { href: "#duelos/" + r.a.params.duel, class: "sv-link" }, "Ver el duelo →"));
    return b;
  }

  function findRow(data, id) { return data.rows.find((r) => String(r.dec.id) === id || r.a.id === id); }

  function render(root, data, params) {
    root.querySelector(".sv-strip-wrap").replaceChildren(data.statErr ? comp("error", data.statErr) || h("div", {}, "Sin estado del bot") : strip(data.status));
    root.querySelector(".sv-queue-wrap").replaceChildren(queuePanel(data));
    // filter bar (built once; counts refreshed by rebuilding only when counts change)
    const tc = countBy(data.rows, (r) => r.type), sc = countBy(data.rows, (r) => r.src), rc = countBy(data.rows, (r) => r.res);
    const sig = JSON.stringify([tc, sc, rc]);
    const fbw = root.querySelector(".sv-fb");
    if (!S.fb || !fbw.contains(S.fb)) {
      fbw.dataset.sig = sig;
      S.fb = comp("filterBar", {
        types: TYPES, counts: tc, team: false, search: true,
        extraRows: [
          { key: "fuente", label: "Fuente", options: ["opus", "consejo", "reserva", "codigo"].map((id) => ({ id, label: SRC_LABEL[id], count: sc[id] || 0 })) },
          { key: "resultado", label: "Resultado", options: Object.keys(RES_LABEL).map((id) => ({ id, label: RES_LABEL[id], count: rc[id] || 0 })) },
        ],
        onChange: (st) => { S.filter = st; if (S.renderList) S.renderList(); },
      });
      if (S.fb && S.fb.state) S.filter = S.fb.state;
      fbw.replaceChildren(S.fb || h("div", { class: "sv-muted sv-small" }, "Filtros no disponibles"));
    } else if (fbw.dataset.sig !== sig && S.fb.setCounts) {
      fbw.dataset.sig = sig;
      const ex = {};
      for (const id of ["opus", "consejo", "reserva", "codigo"]) ex["fuente/" + id] = sc[id] || 0;
      for (const id of Object.keys(RES_LABEL)) ex["resultado/" + id] = rc[id] || 0;
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
      root.querySelector(".sv-count").textContent = `${list.length} de ${data.rows.length}`;
    };
    S.renderList = renderList;
    renderList();
    root.querySelector(".sv-right").replaceChildren(votesPanel(sel || data.rows.find((r) => r.c) || null), railsPanel(data.rows), logPanel(data));
    if (p && p !== S.drawerFor) {
      S.drawerFor = p;
      comp("drawer", { wide: true, onClose: () => { S.drawerFor = null; if (/^#supervision\//.test(location.hash)) location.hash = "#supervision"; }, title: sel ? `Decisión #${sel.dec.id}` : `Decisión ${p}`, body: sel ? drawerBody(sel, data) : comp("empty", "No encuentro esa decisión entre las últimas cargadas.") || h("div", {}, "No encontrada") });
    }
    if (!p) S.drawerFor = null;
  }

  window.Screens["supervision"] = {
    title: "Supervisión",
    mount(root, params) {
      S.root = root; S.drawerFor = null; S.params = params;
      root.classList.add("scr-supervision");
      root.replaceChildren(h("div", { class: "sv-layout" },
        h("div", { class: "sv-strip-wrap" }, window.ui.loading()),
        h("div", { class: "sv-main" },
          h("div", { class: "sv-queue-wrap" }),
          h("section", { class: "sv-panel" },
            h("div", { class: "sv-ph" }, h("b", {}, "Qué está haciendo el bot"), h("span", { class: "sv-mono sv-muted sv-count" }, "")),
            h("div", { class: "sv-fb" }),
            h("div", { class: "sv-list-wrap" }, window.ui.loading()))),
        h("aside", { class: "sv-right" })));
    },
    async refresh(root, data, params) {
      S.lastData = data; S.params = params;
      try {
        const d = await load();
        if (S.root !== root || !root.isConnected) return;
        render(root, d, params);
      } catch (e) {
        console.error("supervision", e);
        const lw = root.querySelector(".sv-list-wrap");
        if (lw) lw.replaceChildren(comp("error", e) || h("div", {}, "Error: " + e.message));
      }
    },
    onParams(root, params) { S.params = params; if (!params) { S.drawerFor = null; comp("closeDrawer", true); } },
    unmount(root) { S.root = null; S.fb = null; S.drawerFor = null; root.classList.remove("scr-supervision"); },
  };
})();
