/* View "leaderboard". Contract: see static/app.js (mount/render/onEvent/destroy). */
import * as core from "../app.js";
const { $, D, RAR, col, esc, fmt, lbBarsHTML, num, pct, put, setSym, state } = core;

export const needs = ["me", "lb", "sched"];

export function mount(root) {
  root.innerHTML = `<div class="wrap vhead"><div><h1>Clasificación</h1><p id="lb-sub">Todos los equipos. Toca una columna para ordenar.</p></div></div>
      <section class="wrap"><div class="rounds" id="lb-rounds"></div>
        <div class="board" style="padding-top:20px"><div class="panel"><h2>Tabla</h2><div class="tablewrap" id="lb-table"></div></div>
        <div class="panel"><h2 id="lb-chart-title">Puntos</h2><div class="hbars" id="lb-chart"></div></div></div></section>`;
}

export function render(root, ctx) {
  const me = D("me"), clock = D("clock"), catalog = D("catalog"), lb = D("lb"), sched = D("sched");
  if (catalog?.currency_symbol) setSym(catalog.currency_symbol);

      if (!lb) return;
      const teams = [...(lb.teams || [])];
      const k = state.lbSort, dir = state.lbDesc ? -1 : 1;
      const val = (t, key) => key === "name" ? String(t.name) : key === "rarest" ? (RAR.indexOf(t.rarest?.rarity) * 1000 - (t.rarest?.serial || 0)) : (num(t[key]) ?? -Infinity);
      teams.sort((a, b) => { const x = val(a, k), y = val(b, k); return (x > y ? 1 : x < y ? -1 : 0) * dir || (a.rank - b.rank); });
      const cols = [["rank", "#"], ["name", "Equipo"], ["score", "Puntos"], ["negotiating", "Negociación"], ["market", "Mercado"], ["album_filled", "Álbum"], ["pages_complete", "Páginas"], ["deals", "Tratos"], ["level", "Nivel"], ["rarest", "Más raro"]];
      put($("lb-table"), `<table class="t"><thead><tr>${cols.map(([key, l]) => `<th class="${["name", "rarest"].includes(key) ? "" : "num"}"><button type="button" data-lbsort="${key}" aria-pressed="${k === key}">${esc(l)}${k === key ? (state.lbDesc ? " ↓" : " ↑") : ""}</button></th>`).join("")}</tr></thead><tbody>
        ${teams.map(t => `<tr class="${t.team === me?.id ? "me" : ""}"><td class="num">${esc(t.rank)}</td><td>${esc(t.name)}${t.frozen ? " (congelado)" : ""}</td><td class="num">${esc(fmt(t.score, 2))}</td><td class="num">${esc(fmt(t.negotiating, 2))}</td><td class="num">${esc(fmt(t.market, 2))}</td><td class="num">${esc(t.album_filled)}/${esc(t.album_slots)}</td><td class="num">${esc(t.pages_complete)}</td><td class="num">${esc(t.deals)}</td><td class="num">${esc(t.level)}</td>
          <td>${t.rarest ? `<span style="--rc:${col(D("catalog")?.rarities?.[t.rarest.rarity]?.color, "#9AA4B8")}"><i class="gem"></i></span> ${esc(t.rarest.ref)} #${esc(t.rarest.serial)}/${esc(t.rarest.print_run)}` : "–"}</td></tr>`).join("")}</tbody></table>`);
      const chartKey = ["name", "rank", "rarest"].includes(k) ? "score" : k;
      $("lb-chart-title").textContent = (cols.find(c => c[0] === chartKey) || [, "Puntos"])[1];
      put($("lb-chart"), lbBarsHTML(lb, me?.id, chartKey));
      const w = lb.weights || sched?.weights || {};
      $("lb-sub").textContent = `${teams.length} equipos · instantánea del tick ${lb.snapshot_tick ?? lb.tick ?? "–"}${lb.next_refresh_tick != null ? `, la siguiente en el tick ${lb.next_refresh_tick}` : ""}${w.negotiating ? ` · pesos: negociación ${fmt(w.negotiating, 0)}, mercado ${fmt(w.market, 0)}` : ""}. Toca una columna para ordenar.`;
      put($("lb-rounds"), (lb.rounds || []).map(r => `<div class="round ${r.status === "active" ? "active" : ""}"><div class="muted" style="font-size:12px">Ronda ${esc(r.round)} · ${esc(r.status)}</div><h3>${esc(r.name)}</h3><div style="font-size:13px">Peso ×${esc(fmt(r.weight, 2))}</div>${num(r.phase) != null ? `<div class="bar"><i style="width:${pct(num(r.phase), 1)}%"></i></div>` : ""}</div>`).join(""));
    
}
