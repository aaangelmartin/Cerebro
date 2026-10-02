/* View "intel". Contract: see static/app.js (mount/render/onEvent/destroy). */
import * as core from "../app.js";
const { $, D, esc, logPanelHTML, md, put, setSym } = core;

export const needs = ["log", "ref"];

export function mount(root) {
  root.innerHTML = `<div class="wrap vhead"><div><h1>Bitácora y referencia</h1><p>Lo que el equipo ha ido descubriendo, y el documento de reglas, puntuación, API y estrategia. Se actualiza solo.</p></div></div>
      <section class="wrap"><div class="panel logpanel"><h2>Bitácora <small>lo más reciente primero</small></h2><div id="intel-log"></div></div></section>
      <section class="wrap" style="margin-top:20px"><div class="panel"><h2>Referencia del Bazaar</h2><div id="intel-ref"></div></div></section>`;
}

export function render(root, ctx) {
  const me = D("me"), clock = D("clock"), catalog = D("catalog"), lb = D("lb"), sched = D("sched");
  if (catalog?.currency_symbol) setSym(catalog.currency_symbol);

      put($("intel-log"), logPanelHTML(D("log"), { limit: 5, full: true }));
      const ref = D("ref");
      if (ref === undefined) put($("intel-ref"), `<div class="skeleton">Cargando la referencia…</div>`);
      else if (!ref) put($("intel-ref"), `<div class="empty">Todavía no hay documento de referencia. Cuando exista <b>BAZAAR.md</b>, se verá aquí con su índice.</div>`);
      else {
        const { html, toc } = md(ref);
        put($("intel-ref"), `<div class="refgrid"><nav class="toc" aria-label="Índice">${toc.filter(t => t.lvl >= 2 || toc.length < 4).map(t => `<button type="button" class="l${t.lvl}" data-anchor="${esc(t.id)}">${t.html}</button>`).join("")}</nav><div class="md">${html}</div></div>`);
      }
    
}
