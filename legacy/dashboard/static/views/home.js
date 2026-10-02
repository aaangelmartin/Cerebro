/* View "home". Contract: see static/app.js (mount/render/onEvent/destroy). */
import * as core from "../app.js";
const { $, D, affinityHTML, col, esc, fillHero, heroHTML, lbBarsHTML, logPanelHTML, miniSetsHTML, put, scoreHTML, setSym, tradeHTML, valueHTML, weekendHTML } = core;

export const needs = ["me", "clock", "catalog", "lb", "sched", "dealers", "log", "offers", "threads", "duels", "levels"];

export function mount(root) {
  root.innerHTML = `${heroHTML()}
      <section class="wrap" style="margin-top:18px"><div class="panel logpanel"><h2>Bitácora del equipo <a class="more" href="#intel">Abrir bitácora y referencia</a></h2><div id="home-log"></div></div></section>
      <section class="wrap"><div class="weekend" id="home-wk"></div></section>
      <div class="wrap board">
        <div class="col">
          <section class="panel"><h2>Candidatos para tratar</h2><p class="lede">Sugerencias de solo lectura, con nuestro valor y la afinidad de cada barrio. Desde aquí no se compra ni se vende nada.</p><div id="home-trade"></div></section>
          <section class="panel"><h2>El álbum <a class="more" href="#album">Ver todas las páginas</a></h2><div class="minisets" id="home-sets"></div></section>
          <section class="panel"><h2>Valor de la colección</h2><div id="home-value"></div></section>
        </div>
        <div class="col">
          <section class="panel"><h2>Clasificación <a class="more" href="#leaderboard">Completa</a></h2><div class="hbars" id="home-lb"></div></section>
          <section class="panel"><h2>De dónde vienen los puntos</h2><div id="home-score"></div></section>
          <section class="panel"><h2>Afinidad por barrio</h2><p class="lede">Multiplica lo que vale para nosotros cada cromo del barrio. La raya marca ×1.</p><div class="hbars aff" id="home-aff"></div></section>
          <section class="panel"><h2>Nuestra actividad <a class="more" href="#deals">Ver tratos</a></h2><div id="home-act"></div></section>
        </div>
      </div>`;
}

export function render(root, ctx) {
  const me = D("me"), clock = D("clock"), catalog = D("catalog"), lb = D("lb"), sched = D("sched");
  if (catalog?.currency_symbol) setSym(catalog.currency_symbol);

      fillHero(me, lb);
      put($("home-log"), logPanelHTML(D("log"), { limit: 3 }));
      put($("home-wk"), weekendHTML(clock, sched));
      if (me && catalog) {
        put($("home-trade"), tradeHTML(me, catalog, D("dealers")));
        put($("home-sets"), miniSetsHTML(me, catalog));
        put($("home-value"), valueHTML(me, catalog));
        put($("home-aff"), affinityHTML(me));
        put($("home-score"), scoreHTML(me, sched));
      }
      if (lb && me) put($("home-lb"), lbBarsHTML(lb, me.id, "score", 8));
      const o = D("offers")?.offers || [], t = D("threads")?.threads || [], d = D("duels")?.duels || [], lv = D("levels")?.levels || [];
      const lim = clock?.limits || {};
      put($("home-act"), `<div class="acts">
          <div><b>${o.length}</b><span>Ofertas abiertas${lim.max_open_offers_per_team ? ` de ${esc(lim.max_open_offers_per_team)}` : ""}</span></div>
          <div><b>${t.length}</b><span>Conversaciones${lim.max_open_threads_per_team ? ` de ${esc(lim.max_open_threads_per_team)}` : ""}</span></div>
          <div><b>${d.length}</b><span>Duelos</span></div></div>
        ${lv.length ? `<div class="subh">Niveles anunciados</div><div class="chips">${lv.map(l => `<span class="chip">${esc(l.name ?? l.id ?? "")} · ${esc(l.status ?? "")}</span>`).join("")}</div>` : ""}`);
    
}
