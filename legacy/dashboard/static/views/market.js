/* View "market". Contract: see static/app.js (mount/render/onEvent/destroy). */
import * as core from "../app.js";
const { $, D, cache, enc, esc, fmt, load, num, offerRow, put, rawBlock, setSym, state } = core;

export const needs = ["me", "catalog", "venues", "offers", "lb"];

export function mount(root) {
  root.innerHTML = `<div class="wrap vhead"><div><h1>Mercados</h1><p>Los mercados abiertos y sus libros de órdenes. Elige un mercado para ver sus ofertas.</p></div></div>
      <section class="wrap"><div class="venues" id="mk-venues"></div><div class="board even" style="padding-top:0"><div class="panel"><h2 id="mk-title">Libro de órdenes</h2><div id="mk-book"></div></div><div class="panel"><h2>Nuestras ofertas abiertas</h2><div id="mk-ours"></div></div></div></section>`;
}

export function render(root, ctx) {
  const me = D("me"), clock = D("clock"), catalog = D("catalog"), lb = D("lb"), sched = D("sched");
  if (catalog?.currency_symbol) setSym(catalog.currency_symbol);

      const vs = D("venues")?.venues || [];
      if (!state.venue && vs.length) state.venue = vs[0].venue;
      put($("mk-venues"), vs.map(v => `<button type="button" class="venue" data-venue="${esc(v.venue)}" aria-pressed="${state.venue === v.venue}"><h3>${esc(v.name)}</h3>
        <div class="muted" style="font-size:13px">${esc(v.owner_name || v.owner || "")} · ${esc(v.status)}</div><div style="font-size:13px;margin-top:4px">${esc(v.description || "")}</div>
        <div class="chips"><span class="chip">comisión ${esc(fmt((num(v.fee_bps) || 0) / 100, 2))}%${num(v.fee_per_card) ? ` + ${esc(v.fee_per_card)} ${esc(core.SYM)}/cromo` : ""}</span><span class="chip">${esc(fmt(v.trades, 0))} tratos</span><span class="chip">volumen ${esc(fmt(v.volume, 0))}</span><span class="chip">${esc(fmt(v.traders, 0))} equipos</span>${num(v.bond) ? `<span class="chip">fianza ${esc(fmt(v.bond, 0))}</span>` : ""}</div></button>`).join("") || `<div class="empty">No hay mercados abiertos.</div>`);
      const ours = D("offers")?.offers || [];
      put($("mk-ours"), ours.length ? ours.map(o => offerRow(o, me?.id)).join("") : `<div class="empty">No tenemos ofertas publicadas.</div>`);
      if (state.venue) {
        const vn = vs.find(v => v.venue === state.venue);
        $("mk-title").textContent = `Libro de órdenes · ${vn?.name || state.venue}`;
        const path = `/api/venues/${enc(state.venue)}/offers`;
        const c = cache.get(path);
        const draw = d => {
          const list = Array.isArray(d) ? d : d?.offers || d?.book || [];
          put($("mk-book"), list.length ? list.map(o => offerRow(o, me?.id)).join("") + rawBlock(d) : `<div class="empty">El libro está vacío: nadie ha publicado ofertas aquí todavía.</div>`);
        };
        if (c && "data" in c) draw(c.data); else put($("mk-book"), `<div class="skeleton">Cargando ofertas…</div>`);
        load(path, 20e3).then(d => { if (core.current?.id === "market") draw(d); }).catch(e => put($("mk-book"), `<div class="empty">No se pudo cargar el libro: ${esc(e.message)}</div>`));
      }
    
}
