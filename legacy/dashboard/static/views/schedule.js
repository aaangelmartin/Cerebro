/* View "schedule". Contract: see static/app.js (mount/render/onEvent/destroy). */
import * as core from "../app.js";
const { $, D, DAY_ES, col, esc, eventsListHTML, fmt, kv, put, setSym, tz, wallStr, weekendHTML } = core;

export const needs = ["clock", "sched", "catalog", "levels", "health"];

export function mount(root) {
  root.innerHTML = `<div class="wrap vhead"><div><h1>Calendario</h1><p>Horario del fin de semana, todo lo programado y el estado del reloj del juego.</p></div></div>
      <section class="wrap"><div class="weekend" id="sc-wk"></div>
        <div class="board" style="padding-top:20px"><div class="panel"><h2>Todo lo programado</h2><ul class="nextev" id="sc-all" style="grid-template-columns:repeat(auto-fill,minmax(260px,1fr))"></ul></div>
        <div class="col"><div class="panel"><h2>Reloj y límites</h2><div id="sc-clock"></div></div><div class="panel"><h2>Niveles</h2><div id="sc-levels"></div></div></div></div></section>`;
}

export function render(root, ctx) {
  const me = D("me"), clock = D("clock"), catalog = D("catalog"), lb = D("lb"), sched = D("sched");
  if (catalog?.currency_symbol) setSym(catalog.currency_symbol);

      put($("sc-wk"), weekendHTML(clock, sched, { limit: 4 }));
      if (clock && sched) put($("sc-all"), eventsListHTML(clock, sched, { limit: 200, includePast: false }));
      const h = D("health"), lim = clock?.limits || {};
      const LIM_ES = { accepts_per_team_per_tick: "Aceptaciones por tick", messages_per_side_per_tick: "Mensajes por lado y tick", max_open_threads_per_team: "Conversaciones abiertas (máx)", max_open_offers_per_team: "Ofertas abiertas (máx)", offers_per_team_per_tick: "Ofertas por tick" };
      if (clock) put($("sc-clock"), `<div class="comp"><div><b>${esc(clock.tick)}</b><span>Tick actual</span></div><div><b>${esc(fmt(clock.tick_seconds, 0))} s</b><span>Por tick ahora</span></div><div><b>${esc(fmt(clock.t_hours, 2))} h</b><span>Tiempo de juego</span></div></div>
        <div class="subh">Ritmo por día</div><dl class="kv">${(clock.days || []).map(d => `<dt>${esc(DAY_ES[d.day] || d.name)}</dt><dd>${esc(wallStr(Date.parse(d.opens), tz))}–${esc(wallStr(Date.parse(d.closes), tz))} · un tick cada ${esc(fmt(d.tick_seconds, 0))} s</dd>`).join("")}</dl>
        <div class="subh" style="margin-top:12px">Límites por equipo</div><dl class="kv">${Object.entries(lim).map(([k, v]) => `<dt>${esc(LIM_ES[k] || k.replace(/_/g, " "))}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
        ${h ? `<div class="subh" style="margin-top:12px">Salud del servidor</div>${kv(h)}` : ""}`);
      const lv = D("levels")?.levels || [];
      put($("sc-levels"), lv.length ? lv.map(l => `<div class="rowlink" style="cursor:default;grid-template-columns:auto minmax(0,1fr)"><span class="tag ${l.status === "active" ? "hot" : "soon"}">${esc(l.status ?? "")}</span><span><b>${esc(l.name ?? l.id ?? "Nivel")}</b><br><small class="muted">${esc(l.teaser || l.description || l.how || "")}</small>${kv(l, ["name", "status", "teaser", "description", "id"])}</span></div>`).join("") : `<div class="empty">Aún no se ha anunciado ningún nivel. Cuando la organización revele uno, saldrá aquí.</div>`);
    
}
